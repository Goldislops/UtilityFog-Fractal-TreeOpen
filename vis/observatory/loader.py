"""Cosmic Observatory: unified data loading for NPZ snapshots and Portable Genome JSON.

Phase 8 -- The Cosmic Observatory

Provides ObservatorySnapshot (frozen dataclass) consumed by all rendering modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from vis.observatory.constants import NUM_CHANNELS


@dataclass(frozen=True)
class ObservatorySnapshot:
    """Immutable snapshot of organism state for visualization."""

    lattice: np.ndarray       # (D, D, D) uint8 -- cell state IDs
    memory_grid: np.ndarray   # (8, D, D, D) float32 -- memory channels
    generation: int
    ca_step: int
    best_fitness: float
    source_path: Optional[str] = None

    # -- helpers --------------------------------------------------------

    @property
    def shape(self) -> Tuple[int, int, int]:
        return self.lattice.shape  # type: ignore[return-value]

    @property
    def non_void_mask(self) -> np.ndarray:
        """Boolean mask where lattice > 0 (non-void cells)."""
        return self.lattice > 0

    @property
    def non_void_count(self) -> int:
        return int(np.sum(self.non_void_mask))

    def channel(self, index: int) -> np.ndarray:
        """Get a memory channel by index (0-7)."""
        return self.memory_grid[index]

    def channel_masked(self, index: int, state: int) -> np.ndarray:
        """Get memory channel values only where lattice == state; NaN elsewhere."""
        mask = self.lattice == state
        return np.where(mask, self.memory_grid[index], np.nan)

    def state_coords(self, state: int) -> np.ndarray:
        """Return (N, 3) array of voxel indices where lattice == state."""
        return np.argwhere(self.lattice == state)

    def state_count(self, state: int) -> int:
        """Count cells of a given state."""
        return int(np.sum(self.lattice == state))


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_npz(path: str | Path) -> ObservatorySnapshot:
    """Load an NPZ snapshot file.

    NPZ files contain: lattice, memory_grid, generation, ca_step, best_fitness.
    Auto-migrates old 3-channel or 5-channel memory grids to 8 channels.
    """
    path = Path(path)
    snap = np.load(str(path), allow_pickle=True)
    lattice = snap["lattice"]
    memory_grid = snap["memory_grid"]

    # Auto-migrate old memory grid formats
    if memory_grid.shape[0] != NUM_CHANNELS:
        try:
            from scripts.continuous_evolution_ca import _migrate_memory_grid
            memory_grid = _migrate_memory_grid(memory_grid, lattice.shape)
        except ImportError:
            # Fallback: zero-pad to 8 channels
            old_ch = memory_grid.shape[0]
            new_grid = np.zeros(
                (NUM_CHANNELS,) + lattice.shape, dtype=np.float32
            )
            new_grid[:old_ch] = memory_grid[:old_ch]
            memory_grid = new_grid

    return ObservatorySnapshot(
        lattice=lattice.astype(np.uint8),
        memory_grid=memory_grid.astype(np.float32),
        generation=int(snap.get("generation", 0)),
        ca_step=int(snap.get("ca_step", 0)),
        best_fitness=float(snap.get("best_fitness", 0.0)),
        source_path=str(path),
    )


def load_genome(path: str | Path) -> ObservatorySnapshot:
    """Load from Portable Genome JSON with epigenetic snapshot.

    Delegates to ``scripts.portable_genome.extract_epigenetic_snapshot()``.
    Raises ValueError if the genome has no epigenetic data.
    """
    from scripts.portable_genome import extract_epigenetic_snapshot

    path = Path(path)
    result = extract_epigenetic_snapshot(str(path))
    if result is None:
        raise ValueError(
            f"Genome at {path} has no epigenetic snapshot. "
            "Re-export with --include-epigenetic flag."
        )
    lattice, memory_grid, meta = result
    if memory_grid is None:
        memory_grid = np.zeros((NUM_CHANNELS,) + lattice.shape, dtype=np.float32)
    return ObservatorySnapshot(
        lattice=lattice,
        memory_grid=memory_grid,
        generation=meta.get("generation", 0),
        ca_step=meta.get("ca_step", 0),
        best_fitness=0.0,
        source_path=str(path),
    )


def load_snapshot(path: str | Path) -> ObservatorySnapshot:
    """Auto-detect file type and load.

    .npz  -> load_npz()
    .json -> load_genome()
    """
    path = Path(path)
    if path.suffix == ".npz":
        return load_npz(path)
    elif path.suffix == ".json":
        return load_genome(path)
    else:
        raise ValueError(f"Unknown file format: {path.suffix}. Expected .npz or .json")


def load_snapshot_series(
    directory: str | Path,
    pattern: str = "v070_*.npz",
    max_count: Optional[int] = None,
) -> List[ObservatorySnapshot]:
    """Load a time-ordered series of snapshots for animation.

    Sorts by filename (which embeds generation/step/timestamp) for
    chronological order.
    """
    directory = Path(directory)
    files = sorted(directory.glob(pattern))
    if max_count is not None:
        files = files[:max_count]
    if not files:
        raise FileNotFoundError(
            f"No files matching '{pattern}' in {directory}"
        )
    return [load_npz(f) for f in files]
