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
# Channel compatibility
# ---------------------------------------------------------------------------

def _normalize_memory_grid(memory_grid, shape) -> np.ndarray:
    """Return an 8-channel NumPy memory grid for any supported legacy shape.

    Every Observatory consumer indexes channels 0-7, so this is the single
    contract both snapshot formats must satisfy. The migration itself belongs
    to the engine and is NOT reimplemented here: this delegates to
    ``scripts.continuous_evolution_ca._migrate_memory_grid``, which owns the
    established Phase-5-to-Phase-6 and historic 3-channel mappings.

    Extracted verbatim from ``load_npz``, where it previously lived inline, so
    that ``load_genome`` gets the same guarantee. Before this, a portable-genome
    JSON snapshot carrying a legacy 3- or 5-channel grid reached the Observatory
    unnormalised and failed later inside a consumer with an ``IndexError``.

    Behaviour preserved exactly, including the fallback's scope: the ``try``
    still spans the import, the migration and the device-array conversion, so
    an ``ImportError`` raised anywhere in that block still selects the
    zero-padding fallback. An unsupported channel count raises the engine's
    ``ValueError`` -- a translatable, actionable loading failure -- rather than
    surfacing as a renderer ``IndexError``.
    """
    if memory_grid.shape[0] == NUM_CHANNELS:
        return memory_grid
    try:
        from scripts.continuous_evolution_ca import _migrate_memory_grid
        migrated = _migrate_memory_grid(memory_grid, tuple(shape))
        if not isinstance(migrated, np.ndarray):
            # engine helper may return a GPU device array; the snapshot contract is NumPy
            migrated = migrated.get()
        return migrated
    except ImportError:
        # Fallback: zero-pad to 8 channels
        old_ch = memory_grid.shape[0]
        new_grid = np.zeros((NUM_CHANNELS,) + tuple(shape), dtype=np.float32)
        new_grid[:old_ch] = memory_grid[:old_ch]
        return new_grid


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
    closes the archive on the way out. `str(path)`, the `0` / `0` / `0.0`
    metadata defaults and the `int()` / `float()` conversions are preserved
    verbatim.

    ``allow_pickle=False`` -- no pickle, ever
    ----------------------------------------
    An NPZ member of object dtype is stored as a pickle, so loading one with
    pickle enabled is arbitrary code execution by construction. This route is
    reachable from a bare filename on the command line, so the archive is
    opened with ``allow_pickle=False`` and NumPy refuses such a member with a
    ``ValueError`` instead of unpickling it. That refusal is already in the
    CLI's translated-input set, so it surfaces as an ordinary
    ``snapshot-unreadable`` failure rather than a traceback.

    Passed EXPLICITLY although NumPy's default is already ``False``: relying on
    the default would make the property invisible at the call site and
    silently reversible by an upstream change. There is deliberately no
    fallback retry, no flag and no environment override -- a compatibility
    escape hatch would reinstate exactly the execution path being removed.

    No legitimate producer in this repository is affected. Snapshots carry
    numeric arrays plus plain scalars, and the same decision was already taken
    for `scripts/dandelion.py` (PR #432) and for the nextness, calibration,
    engine-resume and replicate loaders.

    The claim is an OBJECT-ARRAY REFUSAL, not whole-archive validation: nothing
    here resists decompression amplification, absurd declared shapes, hostile
    member names or defects in NumPy's own header parsing. A pickle-backed
    legacy archive is refused by design and must be re-exported with numeric
    arrays.

    The other claim is archive resource lifetime relative to extraction — not
    an indefinitely accumulating descriptor leak, and not snapshot validation.
    Both hold on refusal too: the member is decoded inside the ``with`` block,
    so the handle is released whether extraction succeeds or is refused.
    """
    path = Path(path)
    with np.load(str(path), allow_pickle=False) as snap:
        lattice = snap["lattice"]
        memory_grid = snap["memory_grid"]
        generation = int(snap.get("generation", 0))
        ca_step = int(snap.get("ca_step", 0))
        best_fitness = float(snap.get("best_fitness", 0.0))

    # Auto-migrate old memory grid formats. The archive is already closed here,
    # so neither the engine import nor the migration retains the file handle.
    memory_grid = _normalize_memory_grid(memory_grid, lattice.shape)

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

    Legacy 3- and 5-channel grids are normalised through the same seam the NPZ
    path uses, so both formats hand the Observatory the identical 8-channel
    contract. An absent memory grid still yields the established 8-channel
    zero grid; an unsupported channel count fails here, during loading, rather
    than later inside a renderer or metadata consumer.
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
    else:
        # Same 8-channel Observatory contract the NPZ path has always had.
        memory_grid = _normalize_memory_grid(memory_grid, lattice.shape)
    return ObservatorySnapshot(
        lattice=lattice.astype(np.uint8),
        memory_grid=memory_grid.astype(np.float32),
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
