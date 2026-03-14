"""Tests for vis.observatory -- Cosmic Observatory (Phase 8).

Follows patterns from tests/test_visualization.py:
  - tempfile for output paths
  - plt.close() after each test
  - Tests both empty and populated data
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Observatory imports
# ---------------------------------------------------------------------------
from vis.observatory.constants import (
    STATE_COLORS,
    STATE_NAMES,
    CHANNEL_NAMES,
    CHANNEL_COLORMAPS,
    VOID,
    STRUCTURAL,
    COMPUTE,
    ENERGY,
    SENSOR,
    NUM_CHANNELS,
    SIGNAL_FIELD_CHANNEL,
    WARMTH_CHANNEL,
    COMPUTE_AGE_CHANNEL,
)
from vis.observatory.loader import (
    ObservatorySnapshot,
    load_npz,
    load_snapshot,
    load_snapshot_series,
)
from vis.observatory.slicer import (
    slice_lattice,
    slice_channel,
    slice_composite,
    tri_slice,
)
from vis.observatory.dashboard import observatory_dashboard


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_snapshot(
    size: int = 16,
    seed: int = 42,
    signal_active: bool = True,
    warmth_active: bool = True,
) -> ObservatorySnapshot:
    """Create a synthetic snapshot for testing."""
    rng = np.random.default_rng(seed)

    lattice = np.zeros((size, size, size), dtype=np.uint8)
    # Fill a sphere with STRUCTURAL
    center = size // 2
    for x in range(size):
        for y in range(size):
            for z in range(size):
                r = np.sqrt((x - center) ** 2 + (y - center) ** 2 + (z - center) ** 2)
                if r < size * 0.4:
                    lattice[x, y, z] = STRUCTURAL
                    if rng.random() < 0.1:
                        lattice[x, y, z] = COMPUTE
                    elif rng.random() < 0.1:
                        lattice[x, y, z] = ENERGY
                elif r < size * 0.45:
                    lattice[x, y, z] = SENSOR

    memory_grid = np.zeros((NUM_CHANNELS, size, size, size), dtype=np.float32)
    # Channel 0: compute_age -- random ages for COMPUTE cells
    compute_mask = lattice == COMPUTE
    memory_grid[0][compute_mask] = rng.uniform(0, 10, size=np.sum(compute_mask)).astype(np.float32)
    # Channel 2: memory_strength -- 1.0 base for all non-void
    memory_grid[2][lattice > 0] = rng.uniform(0.5, 2.0, size=np.sum(lattice > 0)).astype(np.float32)
    # Channel 5: signal_field -- sparse bipolar
    if signal_active:
        sig_mask = compute_mask & (rng.random((size, size, size)) < 0.3)
        memory_grid[5][sig_mask] = rng.uniform(-0.5, 0.5, size=np.sum(sig_mask)).astype(np.float32)
    # Channel 6: warmth -- sparse on STRUCTURAL
    if warmth_active:
        struct_mask = lattice == STRUCTURAL
        warm_mask = struct_mask & (rng.random((size, size, size)) < 0.2)
        memory_grid[6][warm_mask] = rng.uniform(0, 0.05, size=np.sum(warm_mask)).astype(np.float32)

    return ObservatorySnapshot(
        lattice=lattice,
        memory_grid=memory_grid,
        generation=1000,
        ca_step=10000,
        best_fitness=0.5,
        source_path="synthetic",
    )


def _make_empty_snapshot() -> ObservatorySnapshot:
    """Create an all-void snapshot for edge case testing."""
    return ObservatorySnapshot(
        lattice=np.zeros((16, 16, 16), dtype=np.uint8),
        memory_grid=np.zeros((NUM_CHANNELS, 16, 16, 16), dtype=np.float32),
        generation=0,
        ca_step=0,
        best_fitness=0.0,
        source_path="empty",
    )


@pytest.fixture
def snapshot():
    return _make_snapshot()


@pytest.fixture
def empty_snapshot():
    return _make_empty_snapshot()


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------

class TestConstants:
    def test_state_colors_has_all_states(self):
        for sid in [VOID, STRUCTURAL, COMPUTE, ENERGY, SENSOR]:
            assert sid in STATE_COLORS

    def test_state_names_has_all_states(self):
        for sid in [VOID, STRUCTURAL, COMPUTE, ENERGY, SENSOR]:
            assert sid in STATE_NAMES

    def test_channel_names_length(self):
        assert len(CHANNEL_NAMES) == NUM_CHANNELS

    def test_channel_colormaps_all_defined(self):
        for i in range(NUM_CHANNELS):
            assert i in CHANNEL_COLORMAPS


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------

class TestLoader:
    def test_snapshot_shape(self, snapshot):
        assert snapshot.shape == (16, 16, 16)

    def test_non_void_mask(self, snapshot):
        mask = snapshot.non_void_mask
        assert mask.shape == (16, 16, 16)
        assert mask.dtype == bool
        assert np.sum(mask) == snapshot.non_void_count

    def test_non_void_count(self, snapshot):
        assert snapshot.non_void_count > 0

    def test_channel(self, snapshot):
        ch0 = snapshot.channel(0)
        assert ch0.shape == (16, 16, 16)

    def test_channel_masked(self, snapshot):
        ch = snapshot.channel_masked(0, COMPUTE)
        assert ch.shape == (16, 16, 16)
        # Non-COMPUTE cells should be NaN
        assert np.any(np.isnan(ch))

    def test_state_coords(self, snapshot):
        coords = snapshot.state_coords(STRUCTURAL)
        assert coords.ndim == 2
        assert coords.shape[1] == 3

    def test_state_count(self, snapshot):
        total = sum(snapshot.state_count(s) for s in [VOID, STRUCTURAL, COMPUTE, ENERGY, SENSOR])
        assert total == 16 ** 3

    def test_empty_snapshot(self, empty_snapshot):
        assert empty_snapshot.non_void_count == 0
        assert empty_snapshot.state_count(VOID) == 16 ** 3

    def test_load_npz_roundtrip(self, snapshot):
        """Save to NPZ, reload, verify equality."""
        with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f:
            np.savez(
                f.name,
                lattice=snapshot.lattice,
                memory_grid=snapshot.memory_grid,
                generation=snapshot.generation,
                ca_step=snapshot.ca_step,
                best_fitness=snapshot.best_fitness,
            )
            loaded = load_npz(f.name)
        os.unlink(f.name)

        assert np.array_equal(loaded.lattice, snapshot.lattice)
        assert np.allclose(loaded.memory_grid, snapshot.memory_grid)
        assert loaded.generation == snapshot.generation
        assert loaded.ca_step == snapshot.ca_step

    def test_load_snapshot_autodetect_npz(self, snapshot):
        """load_snapshot() auto-detects .npz format."""
        with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f:
            np.savez(
                f.name,
                lattice=snapshot.lattice,
                memory_grid=snapshot.memory_grid,
                generation=snapshot.generation,
                ca_step=snapshot.ca_step,
                best_fitness=snapshot.best_fitness,
            )
            loaded = load_snapshot(f.name)
        os.unlink(f.name)
        assert loaded.shape == snapshot.shape

    def test_load_snapshot_unknown_format(self):
        with pytest.raises(ValueError, match="Unknown file format"):
            load_snapshot("test.xyz")


# ---------------------------------------------------------------------------
# Slicer tests
# ---------------------------------------------------------------------------

class TestSlicer:
    def test_slice_lattice_z(self, snapshot):
        import matplotlib.pyplot as plt
        fig, ax = slice_lattice(snapshot, axis="z", level=8)
        assert fig is not None
        assert ax is not None
        plt.close(fig)

    def test_slice_lattice_x(self, snapshot):
        import matplotlib.pyplot as plt
        fig, ax = slice_lattice(snapshot, axis="x", level=8)
        assert fig is not None
        plt.close(fig)

    def test_slice_lattice_y(self, snapshot):
        import matplotlib.pyplot as plt
        fig, ax = slice_lattice(snapshot, axis="y")
        assert fig is not None
        plt.close(fig)

    def test_slice_lattice_save(self, snapshot):
        import matplotlib.pyplot as plt
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            fig, _ = slice_lattice(snapshot, save_path=f.name)
            assert os.path.exists(f.name)
            assert os.path.getsize(f.name) > 0
            plt.close(fig)
        os.unlink(f.name)

    def test_slice_channel(self, snapshot):
        import matplotlib.pyplot as plt
        fig, ax = slice_channel(snapshot, SIGNAL_FIELD_CHANNEL)
        assert fig is not None
        plt.close(fig)

    def test_slice_channel_with_state_mask(self, snapshot):
        import matplotlib.pyplot as plt
        fig, ax = slice_channel(snapshot, COMPUTE_AGE_CHANNEL, state_mask=COMPUTE)
        assert fig is not None
        plt.close(fig)

    def test_slice_composite(self, snapshot):
        import matplotlib.pyplot as plt
        fig, ax = slice_composite(snapshot, overlay_channel=SIGNAL_FIELD_CHANNEL)
        assert fig is not None
        plt.close(fig)

    def test_slice_composite_warmth(self, snapshot):
        import matplotlib.pyplot as plt
        fig, ax = slice_composite(snapshot, overlay_channel=WARMTH_CHANNEL)
        assert fig is not None
        plt.close(fig)

    def test_tri_slice_states(self, snapshot):
        import matplotlib.pyplot as plt
        fig = tri_slice(snapshot)
        assert fig is not None
        plt.close(fig)

    def test_tri_slice_channel(self, snapshot):
        import matplotlib.pyplot as plt
        fig = tri_slice(snapshot, channel=SIGNAL_FIELD_CHANNEL)
        assert fig is not None
        plt.close(fig)

    def test_slice_empty_snapshot(self, empty_snapshot):
        import matplotlib.pyplot as plt
        fig, ax = slice_lattice(empty_snapshot)
        assert fig is not None
        plt.close(fig)


# ---------------------------------------------------------------------------
# Dashboard tests
# ---------------------------------------------------------------------------

class TestDashboard:
    def test_dashboard_creates_figure(self, snapshot):
        import matplotlib.pyplot as plt
        fig = observatory_dashboard(snapshot)
        assert fig is not None
        axes = fig.get_axes()
        assert len(axes) >= 9  # 3x3 grid + colorbars
        plt.close(fig)

    def test_dashboard_save(self, snapshot):
        import matplotlib.pyplot as plt
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            fig = observatory_dashboard(snapshot, save_path=f.name)
            assert os.path.exists(f.name)
            assert os.path.getsize(f.name) > 0
            plt.close(fig)
        os.unlink(f.name)

    def test_dashboard_empty_snapshot(self, empty_snapshot):
        import matplotlib.pyplot as plt
        fig = observatory_dashboard(empty_snapshot)
        assert fig is not None
        plt.close(fig)


# ---------------------------------------------------------------------------
# Scatter3D tests (only if plotly is available)
# ---------------------------------------------------------------------------

class TestScatter3D:
    @pytest.fixture(autouse=True)
    def _check_plotly(self):
        pytest.importorskip("plotly")

    def test_organism_body(self, snapshot):
        from vis.observatory.scatter3d import organism_body
        fig = organism_body(snapshot)
        assert fig is not None
        # Should have traces for non-void states
        assert len(fig.data) >= 1

    def test_organism_body_save_html(self, snapshot):
        from vis.observatory.scatter3d import organism_body
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            organism_body(snapshot, save_html=f.name)
            assert os.path.exists(f.name)
            assert os.path.getsize(f.name) > 0
        os.unlink(f.name)

    def test_signal_field_3d(self, snapshot):
        from vis.observatory.scatter3d import signal_field_3d
        fig = signal_field_3d(snapshot)
        assert fig is not None

    def test_warmth_glow_3d(self, snapshot):
        from vis.observatory.scatter3d import warmth_glow_3d
        fig = warmth_glow_3d(snapshot)
        assert fig is not None

    def test_compute_elders_3d(self, snapshot):
        from vis.observatory.scatter3d import compute_elders_3d
        fig = compute_elders_3d(snapshot)
        assert fig is not None

    def test_channel_overlay(self, snapshot):
        from vis.observatory.scatter3d import channel_overlay
        fig = channel_overlay(snapshot, SIGNAL_FIELD_CHANNEL)
        assert fig is not None

    def test_dual_view(self, snapshot):
        from vis.observatory.scatter3d import dual_view
        fig = dual_view(snapshot)
        assert fig is not None


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestCLI:
    def test_info_command(self, snapshot):
        """Test the info CLI command."""
        with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f:
            np.savez(
                f.name,
                lattice=snapshot.lattice,
                memory_grid=snapshot.memory_grid,
                generation=snapshot.generation,
                ca_step=snapshot.ca_step,
                best_fitness=snapshot.best_fitness,
            )
            from vis.observatory.cli import main
            main(["info", f.name])
        os.unlink(f.name)

    def test_slice_command(self, snapshot):
        import matplotlib.pyplot as plt
        with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f_npz:
            np.savez(
                f_npz.name,
                lattice=snapshot.lattice,
                memory_grid=snapshot.memory_grid,
                generation=snapshot.generation,
                ca_step=snapshot.ca_step,
                best_fitness=snapshot.best_fitness,
            )
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f_png:
                from vis.observatory.cli import main
                main(["slice", f_npz.name, "--save", f_png.name])
                assert os.path.exists(f_png.name)
            os.unlink(f_png.name)
        os.unlink(f_npz.name)

    def test_dashboard_command(self, snapshot):
        import matplotlib.pyplot as plt
        with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f_npz:
            np.savez(
                f_npz.name,
                lattice=snapshot.lattice,
                memory_grid=snapshot.memory_grid,
                generation=snapshot.generation,
                ca_step=snapshot.ca_step,
                best_fitness=snapshot.best_fitness,
            )
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f_png:
                from vis.observatory.cli import main
                main(["dashboard", f_npz.name, "--save", f_png.name])
                assert os.path.exists(f_png.name)
            os.unlink(f_png.name)
        os.unlink(f_npz.name)
