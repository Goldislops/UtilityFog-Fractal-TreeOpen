"""Cosmic Observatory: unified data loading for NPZ snapshots and Portable Genome JSON.

Phase 8 -- The Cosmic Observatory

Provides ObservatorySnapshot (frozen dataclass) consumed by all rendering modules.
"""

from __future__ import annotations

import re
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

    The archive's lifetime is bounded to extraction. Previously the `NpzFile`
    returned by `np.load` stayed referenced through legacy-grid migration (which
    imports the engine and can be expensive), the fallback zero-padding, both
    `.astype()` conversions, the metadata lookups and the return — released only
    by eventual object destruction. `load_snapshot_series()` calls this function
    once per file, so every series member inherits that behaviour. A retained
    handle can interfere with deleting, rotating or replacing a snapshot on
    Windows.

    All five values are now materialised while the archive is open and it is
    closed deterministically before any of that later work begins. Extraction
    failures are not caught, translated or suppressed: a missing key or a failing
    metadata conversion propagates exactly as before, and the `with` block still
    closes the archive on the way out. `str(path)`, `allow_pickle=True`, the
    `0` / `0` / `0.0` metadata defaults and the `int()` / `float()` conversions
    are preserved verbatim.

    The claim is archive resource lifetime relative to extraction — not an
    indefinitely accumulating descriptor leak, and not snapshot validation.
    """
    path = Path(path)
    with np.load(str(path), allow_pickle=True) as snap:
        lattice = snap["lattice"]
        memory_grid = snap["memory_grid"]
        generation = int(snap.get("generation", 0))
        ca_step = int(snap.get("ca_step", 0))
        best_fitness = float(snap.get("best_fitness", 0.0))

    # Auto-migrate old memory grid formats. The archive is already closed here,
    # so neither the engine import nor the migration retains the file handle.
    if memory_grid.shape[0] != NUM_CHANNELS:
        try:
            from scripts.continuous_evolution_ca import _migrate_memory_grid
            memory_grid = _migrate_memory_grid(memory_grid, lattice.shape)
            if not isinstance(memory_grid, np.ndarray):
                # engine helper may return a GPU device array; the snapshot contract is NumPy
                memory_grid = memory_grid.get()
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
        generation=generation,
        ca_step=ca_step,
        best_fitness=best_fitness,
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


_DIGIT_RUNS = re.compile(r"(\d+)")


def _natural_key(path: Path):
    """Numeric-aware filename key: gen9 sorts before gen10.

    Plain lexicographic sorting breaks chronological order across digit-width
    boundaries (the AGENT_HANDOFF snapshot-listing caveat, applied here).
    """
    return (
        [
            (0, int(token)) if token.isdigit() else (1, token)
            for token in _DIGIT_RUNS.split(path.name)
        ],
        path.name,
    )


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
    files = sorted(directory.glob(pattern), key=_natural_key)
    if max_count is not None:
        files = files[:max_count]
    if not files:
        raise FileNotFoundError(
            f"No files matching '{pattern}' in {directory}"
        )
    return [load_npz(f) for f in files]
