"""Observatory channel compatibility for portable-genome JSON snapshots.

Scope: the eight-channel contract every Observatory consumer relies on, and
whether both snapshot formats deliver it.

Before this package `load_npz` migrated legacy 3- and 5-channel memory grids
inline, but `load_genome` did not: a portable-genome JSON snapshot carrying a
legacy grid reached the Observatory unnormalised and failed later inside a
consumer with an `IndexError` on channel 3..7. Both paths now share one seam,
`loader._normalize_memory_grid`, which delegates to the engine's established
migration rather than reimplementing it.

Layer boundary: wire integrity (shape rank, payload lengths, base64, positive
channel counts) belongs to `scripts.portable_genome` and is covered by
`tests/test_portable_genome_epigenetic_snapshot.py`. This module owns which
*positive* channel counts the Observatory can actually consume, and the
end-to-end CLI reachability of both.
"""

from __future__ import annotations

import base64
import json
import sys
import types

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("matplotlib")

import vis.observatory.loader as loader

# Imported eagerly and deliberately. `load_genome`'s first statement imports
# this module, and importing it pulls `scripts.continuous_evolution_ca`. Two
# tests below patch that engine entry in `sys.modules`; if the extractor were
# not already cached, that patch would break its import instead of the
# migration under test — so a single-test or `-k` selection would fail.
import scripts.portable_genome  # noqa: F401
from vis.observatory.loader import load_genome, load_snapshot

NUM_CHANNELS = loader.NUM_CHANNELS
SHAPE = (2, 2, 2)
CELLS = SHAPE[0] * SHAPE[1] * SHAPE[2]
MIGRATION_MODULE = "scripts.continuous_evolution_ca"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _b64(array):
    return base64.b64encode(np.ascontiguousarray(array).tobytes()).decode("ascii")


def _genome(memory_grid=None, channels=None, shape=SHAPE, lattice=None):
    """A well-formed portable genome, optionally carrying a memory grid."""
    if lattice is None:
        lattice = np.zeros(shape, dtype=np.uint8)
        lattice[0, 0, 0] = 1
    epi = {
        "included": True,
        "lattice_shape": list(shape),
        "lattice_b64": _b64(lattice),
        "snapshot_generation": 5,
        "snapshot_ca_step": 6,
    }
    doc = {"epigenetic_snapshot": epi}
    if memory_grid is not None:
        epi["memory_grid_b64"] = _b64(memory_grid)
        doc["memory_layout"] = {
            "num_channels": channels if channels is not None else memory_grid.shape[0]
        }
    return doc


def _write(tmp_path, doc, name="genome.json"):
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _grid(channels, fill=None):
    """A memory grid whose every channel carries a distinct marker value.

    Markers start at 10 and step by 10 so none of them collides with the
    migration's own defaults (0.0 and 1.0). Without that, a channel asserted to
    hold the default 1.0 could equally be an accidental copy of a source
    channel, and the mapping test would not distinguish them.
    """
    grid = np.zeros((channels,) + SHAPE, dtype=np.float32)
    for c in range(channels):
        grid[c] = float((c + 1) * 10) if fill is None else fill
    return grid


# ---------------------------------------------------------------------------
# Positive controls: valid data still works
# ---------------------------------------------------------------------------


def test_valid_eight_channel_genome_passes_through_unchanged(tmp_path):
    grid = _grid(NUM_CHANNELS)
    path = _write(tmp_path, _genome(grid))
    snap = load_genome(path)
    assert snap.memory_grid.shape == (NUM_CHANNELS,) + SHAPE
    assert snap.memory_grid.dtype == np.float32
    assert snap.lattice.dtype == np.uint8
    np.testing.assert_array_equal(snap.memory_grid, grid)


def test_absent_memory_grid_still_yields_the_zero_grid(tmp_path):
    """Established behaviour, unchanged."""
    path = _write(tmp_path, _genome())
    snap = load_genome(path)
    assert snap.memory_grid.shape == (NUM_CHANNELS,) + SHAPE
    assert not snap.memory_grid.any()


def test_metadata_and_lattice_survive_the_round_trip(tmp_path):
    lattice = np.arange(CELLS, dtype=np.uint8).reshape(SHAPE)
    path = _write(tmp_path, _genome(_grid(NUM_CHANNELS), lattice=lattice))
    snap = load_genome(path)
    np.testing.assert_array_equal(snap.lattice, lattice)
    assert snap.generation == 5
    assert snap.ca_step == 6


def test_load_snapshot_routes_json_through_load_genome(tmp_path):
    """Anti-vacuity: the public entry point reaches this path for `.json`."""
    path = _write(tmp_path, _genome(_grid(NUM_CHANNELS)), name="organism.json")
    snap = load_snapshot(path)
    assert snap.memory_grid.shape == (NUM_CHANNELS,) + SHAPE


# ---------------------------------------------------------------------------
# Legacy migration -- exact historic placement, not merely the right shape
# ---------------------------------------------------------------------------


def test_five_channel_genome_migrates_to_eight(tmp_path):
    """Phase 5 -> Phase 6: the five originals keep their index, and the three
    new channels (signal, warmth, cooldown) are zero."""
    grid = _grid(5)
    path = _write(tmp_path, _genome(grid))
    snap = load_genome(path)
    assert snap.memory_grid.shape == (NUM_CHANNELS,) + SHAPE
    for c in range(5):
        np.testing.assert_array_equal(snap.memory_grid[c], grid[c])
    for c in range(5, NUM_CHANNELS):
        assert not snap.memory_grid[c].any(), f"channel {c} should be zero"


def test_three_channel_genome_migrates_to_eight_with_historic_mapping(tmp_path):
    """Historic 3-channel mapping: 0->0, 1->2, 2->4, with channel 1 defaulting
    to 0.0 and channel 3 to 1.0."""
    grid = _grid(3)
    path = _write(tmp_path, _genome(grid))
    snap = load_genome(path)
    assert snap.memory_grid.shape == (NUM_CHANNELS,) + SHAPE
    np.testing.assert_array_equal(snap.memory_grid[0], grid[0])
    np.testing.assert_array_equal(snap.memory_grid[2], grid[1])
    np.testing.assert_array_equal(snap.memory_grid[4], grid[2])
    assert not snap.memory_grid[1].any()
    np.testing.assert_array_equal(
        snap.memory_grid[3], np.ones(SHAPE, dtype=np.float32)
    )
    for c in (5, 6, 7):
        assert not snap.memory_grid[c].any(), f"channel {c} should be zero"


@pytest.mark.parametrize("channels", [3, 5])
def test_migrated_genome_grid_is_a_numpy_float32_array(tmp_path, channels):
    path = _write(tmp_path, _genome(_grid(channels)))
    snap = load_genome(path)
    assert isinstance(snap.memory_grid, np.ndarray)
    assert snap.memory_grid.dtype == np.float32


@pytest.mark.parametrize("channels", [1, 2, 4, 6, 7, 9, 16])
def test_unsupported_channel_counts_fail_during_loading(tmp_path, channels):
    """Not later, inside a renderer: `load_genome` itself refuses, with a
    ValueError the CLI already translates."""
    path = _write(tmp_path, _genome(_grid(channels)))
    with pytest.raises(ValueError, match="Cannot migrate memory grid"):
        load_genome(path)


# ---------------------------------------------------------------------------
# The shared seam is genuinely shared
# ---------------------------------------------------------------------------


def test_npz_and_genome_paths_use_the_same_normalization_seam():
    """Structural: neither loader reimplements the migration."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(loader)))
    for name in ("load_npz", "load_genome"):
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == name
        )
        called = {
            n.func.id for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "_normalize_memory_grid" in called, f"{name} bypasses the seam"
        assert "_migrate_memory_grid" not in called, f"{name} reimplements migration"


@pytest.mark.parametrize("channels", [3, 5])
def test_npz_and_genome_produce_identical_grids_for_the_same_legacy_data(
    tmp_path, channels
):
    """The strongest statement of the contract: same legacy input, same
    Observatory snapshot, whichever format carried it."""
    grid = _grid(channels)
    lattice = np.zeros(SHAPE, dtype=np.uint8)
    lattice[1, 1, 1] = 2

    npz_path = tmp_path / "snap.npz"
    np.savez(npz_path, lattice=lattice, memory_grid=grid,
             generation=5, ca_step=6, best_fitness=0.0)
    json_path = _write(tmp_path, _genome(grid, lattice=lattice))

    from_npz = load_snapshot(npz_path)
    from_json = load_snapshot(json_path)
    np.testing.assert_array_equal(from_npz.memory_grid, from_json.memory_grid)
    np.testing.assert_array_equal(from_npz.lattice, from_json.lattice)


# ---------------------------------------------------------------------------
# NPZ behaviour preserved: archive lifetime and the ImportError fallback
# ---------------------------------------------------------------------------


def test_npz_legacy_migration_still_works_through_the_shared_seam(tmp_path):
    """The NPZ path keeps migrating legacy grids after the extraction.

    Archive *lifetime* is deliberately not re-asserted here: POSIX `unlink`
    of an open file succeeds, so a "delete after load" check is vacuous on the
    Linux CI runner. `tests/test_observatory_loader.py` already holds the real,
    platform-independent witness — it records `archive.closed` at the migration
    seam itself — and that test is unmodified by this package.
    """
    path = tmp_path / "snap.npz"
    grid = _grid(3)
    np.savez(path, lattice=np.zeros(SHAPE, dtype=np.uint8),
             memory_grid=grid, generation=0, ca_step=0, best_fitness=0.0)
    snap = load_snapshot(path)
    assert snap.memory_grid.shape == (NUM_CHANNELS,) + SHAPE
    np.testing.assert_array_equal(snap.memory_grid[0], grid[0])
    np.testing.assert_array_equal(snap.memory_grid[2], grid[1])
    np.testing.assert_array_equal(snap.memory_grid[4], grid[2])


@pytest.mark.parametrize("channels", [3, 5])
def test_import_error_fallback_zero_pads(monkeypatch, tmp_path, channels):
    """Established fallback, explicitly characterised and preserved: when the
    engine cannot be imported, the grid is zero-padded rather than migrated —
    so the historic 3-channel remapping does NOT apply on this path."""
    monkeypatch.setitem(sys.modules, MIGRATION_MODULE, None)  # import -> ImportError
    grid = _grid(channels)
    path = _write(tmp_path, _genome(grid))
    snap = load_genome(path)
    assert snap.memory_grid.shape == (NUM_CHANNELS,) + SHAPE
    for c in range(channels):
        np.testing.assert_array_equal(snap.memory_grid[c], grid[c])
    for c in range(channels, NUM_CHANNELS):
        assert not snap.memory_grid[c].any()


def test_device_array_result_is_converted_to_numpy(monkeypatch, tmp_path):
    """A GPU device array from the engine still satisfies the NumPy contract."""

    class _FakeDevice:
        def __init__(self, array):
            self._array = array

        def get(self):
            return self._array

    migrated = np.ones((NUM_CHANNELS,) + SHAPE, dtype=np.float32)
    stub = types.ModuleType(MIGRATION_MODULE)
    stub._migrate_memory_grid = lambda grid, shape: _FakeDevice(migrated)
    monkeypatch.setitem(sys.modules, MIGRATION_MODULE, stub)

    path = _write(tmp_path, _genome(_grid(3)))
    snap = load_genome(path)
    assert isinstance(snap.memory_grid, np.ndarray)
    np.testing.assert_array_equal(snap.memory_grid, migrated)


# ---------------------------------------------------------------------------
# CLI reachability -- the real command, the real loader
# ---------------------------------------------------------------------------


def _run_cli(argv):
    """Drive the genuine CLI end to end.

    Nothing is faked: these all use `info`, whose dispatch imports only
    `vis.observatory.constants` and NumPy — no renderer, no GUI, no output
    file. The loader and extractor are the real ones.
    """
    from vis.observatory import cli as cli_mod

    return cli_mod.main(argv)


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        pytest.param(lambda d: d["epigenetic_snapshot"].__setitem__(
            "lattice_shape", [2, 2]), "three dimensions", id="rank"),
        pytest.param(lambda d: d["epigenetic_snapshot"].__setitem__(
            "lattice_shape", [2, 0, 2]), "positive", id="zero-dim"),
        pytest.param(lambda d: d["epigenetic_snapshot"].__setitem__(
            "lattice_b64", "!!!!"), "valid base64", id="base64"),
        pytest.param(lambda d: d["epigenetic_snapshot"].__setitem__(
            "lattice_b64", base64.b64encode(b"\x00").decode()), "payload length",
            id="payload"),
        pytest.param(lambda d: d["epigenetic_snapshot"].__setitem__(
            "included", "yes"), "JSON boolean", id="included"),
    ],
)
def test_malformed_genome_is_a_one_line_cli_error(tmp_path, capsys, mutate, fragment):
    doc = _genome()
    mutate(doc)
    path = _write(tmp_path, doc)
    assert _run_cli(["info", str(path)]) == 1
    err = capsys.readouterr().err
    assert "Traceback (most recent call last)" not in err
    assert len(err.strip().splitlines()) == 1
    assert fragment in err


def test_unsupported_channel_count_is_a_one_line_cli_error(tmp_path, capsys):
    path = _write(tmp_path, _genome(_grid(4)))
    assert _run_cli(["info", str(path)]) == 1
    err = capsys.readouterr().err
    assert "Traceback (most recent call last)" not in err
    assert len(err.strip().splitlines()) == 1
    assert "Cannot migrate memory grid" in err


@pytest.mark.parametrize("channels", [3, 5, 8])
def test_valid_genome_reports_through_the_cli(tmp_path, capsys, channels):
    """Positive control at the CLI: legacy grids now render metadata instead of
    crashing in a consumer."""
    path = _write(tmp_path, _genome(_grid(channels)))
    assert _run_cli(["info", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Generation: 5" in out
    assert "Ch 7" in out          # channel 7 is reachable -> grid really is 8-deep
