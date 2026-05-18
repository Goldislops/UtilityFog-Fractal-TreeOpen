"""Phase 19 PR #2 — Nextness Observer (skeleton, offline, read-only).

Per ``PHASE_19_NEXTNESS_OBSERVER.md`` (merged in PR #137 as commit ``c06e958``).

The Nextness Observer is a passive, **read-only**, **offline** Layer-2
analyser that runs alongside Medusa and translates local space-time
patches of the lattice into a small vocabulary of "nextness tokens".
The point is to give Medusa's dynamics a *legible* description above
the per-cell flicker level — without modifying the engine, without
restarting the engine, and without competing with the engine for
compute.

This PR (#2) ships the complete offline skeleton:

  • 16-token hand-coded vocabulary (``TOKEN_NAMES``).
  • Spatial-patch sampler in ``uniform_grid`` mode (``importance`` and
    ``dense`` are stubs that raise ``NotImplementedError`` naming the
    PR each one will land in).
  • Hand-coded classifier cascading 16 predicates over patch features
    (``classify_patch``).
  • Wall-time budget monitor + pre-flight density backoff
    (``BudgetMonitor``, ``compute_safe_stride``).
  • Filesystem I/O: snapshot loading, log writing, end-to-end
    ``process_snapshot``.

Live ZMQ subscription/publishing remain strictly deferred to PR #6.
KL-drift metrics and acoustic-map cross-validation land in PR #4.
Optional learned 512-token embedding is PR #5 if §8 useful-result
criteria suggest the hand-coded vocabulary is limiting.

## Safety contract (from §7 of the design doc)

Every invariant is testable; the test suite in
``tests/test_nextness_observer.py`` ships unit tests for each.

1. No writes to ``data/`` except ``data/nextness_log/``.
2. No HTTP POSTs (GET only on the Medusa REST API).
3. No ZMQ publishes outside the ``nextness.*`` topic namespace.
   **Stronger for PR #2: NO ZMQ AT ALL.** PR #2 is offline-only;
   live integration is strictly PR #6. Module enforces this at
   import time (``_assert_no_zmq_at_import``).
4. CPU only by default (``MEDUSA_OBSERVER_GPU=0`` honoured).
5. Killable at any time (no partial writes, no orphaned subscriptions).
6. Pause-aware (quiescent mode when no fresh snapshots in ``T`` minutes).
7. No ``trust_remote_code=True`` anywhere in the dependency surface.
8. Bounded compute per snapshot via ``MEDUSA_OBSERVER_BUDGET_S``
   (default 30s wall-time). Reduces sampling density rather than
   running over budget.

Per Jack's audit: PR #2 starts with **sampled patches**, NOT a dense
whole-lattice classification pass. Three sampling modes:

- ``uniform_grid`` (default): patches at every Nth voxel.
- ``importance``: bias toward acoustic-stress sectors and Sage neighbourhoods.
- ``dense``: full per-cell pass; offline-only, gated by env var,
  refuses to run when Medusa is live.
"""

from __future__ import annotations

import dataclasses
import enum
import os
from typing import Final


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Phase 19 PR #2 ships with a hand-coded vocabulary. PR #5 may replace
#: this with a learned 512-symbol embedding if the hand-coded version
#: proves limiting per the §8 useful-result criteria.
TOKEN_NAMES: Final[tuple[str, ...]] = (
    # State-stable tokens
    "void_static",          # patch is mostly VOID and stays mostly VOID
    "compute_static",       # mostly COMPUTE, stable
    # State-shift tokens
    "void_birth",           # VOID-dominant patch acquires structure
    "compute_aging",        # compute cells incrementing age in place (Sage-like)
    "compute_decay",        # COMPUTE losing to VOID/STRUCTURAL
    "structural_growth",    # STRUCTURAL count increasing locally
    "structural_decay",     # STRUCTURAL → VOID under decay rules
    # Energy/sensor dynamics
    "energy_pulse",         # Energy gradient propagating across the patch
    "sensor_alert",         # SENSOR cells activating in response to gradient
    # Equanimity-engine signature tokens (Phase 6a–c, 17a)
    "metta_warmth",         # multiple ENERGY neighbours sustaining COMPUTE survival
    "karuna_relief",        # compassion field reducing local distress
    "mudita_resonance",     # sympathetic-joy resonance: mature COMPUTE near growing COMPUTE
    "magnon_lighthouse",    # patch under strong Legend-Sage magnon influence
    "acoustic_stress",      # patch in top-25% friction (Phase 14e correspondence)
    # Boundary / catch-all
    "phase_boundary",       # sharp transition between two regimes within the patch
    "unclassified",         # doesn't fit any other token; catch-all
)

assert len(TOKEN_NAMES) == 16, "PR #2 vocabulary is exactly 16 tokens"
assert len(set(TOKEN_NAMES)) == 16, "Token names must be unique"

#: Index → name lookup. Used as the canonical integer ID for a token.
TOKEN_BY_INDEX: Final[dict[int, str]] = {i: name for i, name in enumerate(TOKEN_NAMES)}

#: Name → index lookup.
TOKEN_INDEX: Final[dict[str, int]] = {name: i for i, name in enumerate(TOKEN_NAMES)}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class SamplingMode(enum.Enum):
    """Three sampling strategies, per the design doc §9 sampling discipline.

    Ordered from least to most expensive. PR #2 implements UNIFORM_GRID;
    IMPORTANCE and DENSE arrive in later PRs (or are stubbed).
    """

    UNIFORM_GRID = "uniform_grid"
    IMPORTANCE = "importance"
    DENSE = "dense"


@dataclasses.dataclass(frozen=True)
class ObserverConfig:
    """Configuration for one Nextness Observer run.

    Frozen dataclass — instances are immutable, which makes them safe
    to pass through the pipeline without worrying about mutation.

    Defaults match the design doc; everything is overridable via env
    vars (``MEDUSA_OBSERVER_*``) or explicit constructor args.
    """

    # Sampling
    sampling_mode: SamplingMode = SamplingMode.UNIFORM_GRID
    uniform_grid_stride: int = 8       # take every Nth voxel along each axis
    patch_spatial_radius: int = 1       # 1 → 3x3x3 Moore neighbourhood
    patch_temporal_window: int = 3      # 3 consecutive snapshots / generations

    # Budget (§7 invariant #8)
    budget_seconds: float = 30.0        # wall-time per snapshot
    min_budget_seconds: float = 5.0     # hard floor; refuse to run below this

    # I/O
    log_directory: str = "data/nextness_log"   # ONLY writable directory
    snapshot_glob: str = "data/v070_gen*.npz"  # where to find snapshots

    # Pause-awareness (§7 invariant #6)
    quiescent_after_minutes: int = 30   # if no fresh snapshot in T min → quiescent

    # Safety overrides (§7 invariants #4, #7)
    use_gpu: bool = False               # MEDUSA_OBSERVER_GPU=0 (default)
    allow_dense_mode: bool = False      # MEDUSA_OBSERVER_DENSE=1 (offline only)

    # Medusa liveness check
    medusa_live_threshold_minutes: int = 30  # snapshot freshness for "live"

    @classmethod
    def from_env(cls, **overrides: object) -> "ObserverConfig":
        """Build a config from env vars + explicit overrides.

        Env vars override defaults; explicit kwargs override env vars.
        Unknown kwargs raise (caught by the dataclass init).
        """
        env: dict[str, object] = {}

        if (v := os.environ.get("MEDUSA_OBSERVER_BUDGET_S")):
            env["budget_seconds"] = float(v)
        if (v := os.environ.get("MEDUSA_OBSERVER_STRIDE")):
            env["uniform_grid_stride"] = int(v)
        if (v := os.environ.get("MEDUSA_OBSERVER_LOG_DIR")):
            env["log_directory"] = v
        if (v := os.environ.get("MEDUSA_OBSERVER_GPU")):
            env["use_gpu"] = v not in ("0", "", "false", "False")
        if (v := os.environ.get("MEDUSA_OBSERVER_DENSE")):
            env["allow_dense_mode"] = v in ("1", "true", "True")
        if (v := os.environ.get("MEDUSA_OBSERVER_MODE")):
            try:
                env["sampling_mode"] = SamplingMode(v)
            except ValueError as e:
                raise ValueError(
                    f"MEDUSA_OBSERVER_MODE={v!r}; must be one of "
                    f"{[m.value for m in SamplingMode]}"
                ) from e

        merged = {**env, **overrides}
        return cls(**merged)  # type: ignore[arg-type]

    def __post_init__(self) -> None:
        if self.budget_seconds < self.min_budget_seconds:
            raise ValueError(
                f"budget_seconds={self.budget_seconds} below floor "
                f"min_budget_seconds={self.min_budget_seconds}; "
                f"refusing to run with too-tight a budget"
            )
        if self.uniform_grid_stride < 1:
            raise ValueError(
                f"uniform_grid_stride={self.uniform_grid_stride}; must be >= 1"
            )
        if self.sampling_mode is SamplingMode.DENSE and not self.allow_dense_mode:
            raise ValueError(
                "sampling_mode=DENSE requires allow_dense_mode=True "
                "(or MEDUSA_OBSERVER_DENSE=1). Dense mode is offline-only "
                "and refuses to run while Medusa is live."
            )


# ---------------------------------------------------------------------------
# Custom exceptions (so callers / tests can be specific)
# ---------------------------------------------------------------------------


class ObserverSafetyError(RuntimeError):
    """Raised when the observer would violate one of the §7 invariants.

    Subclasses make the specific failure inspectable in tests.
    """


class WriteOutsideLogDirError(ObserverSafetyError):
    """Attempted to write to a path outside ``log_directory``."""


class ZmqUseInPR2Error(ObserverSafetyError):
    """PR #2 must NOT use ZMQ at all. Live ZMQ integration is strictly PR #6.

    This error is raised at module import time if ``zmq`` is somehow
    imported into this module's namespace, and at runtime if any
    function attempts to create a ZMQ socket.
    """


class BudgetExceededError(ObserverSafetyError):
    """Wall-time budget for one snapshot exceeded.

    Should be rare in practice — the budget monitor (Chunk 4) reduces
    sampling density before getting here. This is the last-resort
    failure.
    """


class DenseModeWhileLiveError(ObserverSafetyError):
    """``SamplingMode.DENSE`` was attempted while Medusa is live.

    Dense mode is offline-batch only.
    """


# ---------------------------------------------------------------------------
# Safety: ZMQ-import guard for PR #2
# ---------------------------------------------------------------------------
#
# Per the design doc §9 PR #2 row: PR #2 ships a unit test that fails if
# this module attempts any ZMQ socket creation. Belt + suspenders: also
# refuse at import time if ``zmq`` somehow ended up in this module's
# globals. PR #6 will lift this guard intentionally.


def _assert_no_zmq_at_import() -> None:
    """Refuse to import if ``zmq`` leaked into this module's namespace.

    Called once at the bottom of the module. Any later code that needs
    networked I/O in PR #6 will live in a separate module
    (``nextness_observer_live.py``) and lift this guard explicitly.
    """
    if "zmq" in globals():
        raise ZmqUseInPR2Error(
            "Phase 19 PR #2 forbids ZMQ. The 'zmq' module appeared in "
            "this module's globals; live integration is strictly PR #6. "
            "If you're trying to add live publish/subscribe, do it in a "
            "sibling module, not here."
        )


_assert_no_zmq_at_import()


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------

__all__ = [
    # Constants
    "TOKEN_NAMES",
    "TOKEN_BY_INDEX",
    "TOKEN_INDEX",
    # Configuration
    "SamplingMode",
    "ObserverConfig",
    # Errors
    "ObserverSafetyError",
    "WriteOutsideLogDirError",
    "ZmqUseInPR2Error",
    "BudgetExceededError",
    "DenseModeWhileLiveError",
    # Sampler (Chunk 2)
    "Patch",
    "iter_patches",
    "iter_uniform_grid_patches",
    "iter_importance_patches",
    "iter_dense_patches",
]


# ---------------------------------------------------------------------------
# Chunk 2: patch sampler
# ---------------------------------------------------------------------------
#
# The sampler walks the lattice and yields local patches. PR #2 ships only
# UNIFORM_GRID; IMPORTANCE and DENSE are stubs that raise NotImplementedError
# and explicitly name the PR each one will land in.
#
# A Patch is (center_coord, state_view, memory_view). The views are
# zero-copy slices into the source arrays — no allocation per patch.
# Classifier callers MUST treat patches as immutable observations:
# the engine's snapshot is read-only by contract (§7 invariant #1)
# and any defensive caller should respect that even where Python lets
# them poke at the underlying buffer.

from collections.abc import Iterator
from typing import NamedTuple

import numpy as np


class Patch(NamedTuple):
    """A local space-only neighbourhood from one snapshot.

    - ``center`` is the (x, y, z) coordinate of the centre cell.
    - ``state`` is a (2r+1)^3 cube of state values (uint8).
    - ``memory`` is a (channels, 2r+1, 2r+1, 2r+1) block of memory_grid
      values (float32).

    Both ``state`` and ``memory`` are **zero-copy views** into the source
    snapshot arrays. **Callers must treat them as read-only.** PR #2 does
    not enforce immutability via ``setflags(write=False)`` to avoid the
    per-patch overhead at 32k+ patches/snapshot; the read-only contract
    is by convention. The classifier in this module never mutates the
    views (verified by tests), so the convention holds for the in-tree
    use. External callers should respect it.

    Temporal context (per the design doc's ``patch_temporal_window``)
    is NOT part of a Patch in PR #2; classifiers infer temporal
    information from the memory_grid (which encodes age, warmth,
    accumulated state). PR #3 may extend Patch to span multiple
    snapshots if classification proves it needs explicit before/after
    context — but the §3 design defers that until the simpler shape
    is shown insufficient.
    """

    center: tuple[int, int, int]
    state: np.ndarray
    memory: np.ndarray


def iter_uniform_grid_patches(
    state: np.ndarray,
    memory: np.ndarray,
    *,
    stride: int = 8,
    radius: int = 1,
) -> Iterator[Patch]:
    """Yield patches at every ``stride``-th voxel along each axis.

    Patches are skipped near lattice boundaries (where the radius would
    extend past the edge). With a 256x256x256 lattice, stride=8, and
    radius=1, this yields 32^3 = 32,768 patches per snapshot — well
    within the §7 #8 wall-time budget, ~512x cheaper than dense.

    Validates inputs upfront and refuses to run if the lattice is
    too small to fit a single patch.
    """
    if state.ndim != 3:
        raise ValueError(f"state must be 3D (X, Y, Z); got shape {state.shape}")
    if memory.ndim != 4 or memory.shape[1:] != state.shape:
        raise ValueError(
            f"memory shape {memory.shape} inconsistent with state shape "
            f"{state.shape}; expected (channels, *state.shape)"
        )
    if stride < 1:
        raise ValueError(f"stride={stride}; must be >= 1")
    if radius < 1:
        raise ValueError(f"radius={radius}; must be >= 1")

    X, Y, Z = state.shape
    if min(X, Y, Z) < 2 * radius + 1:
        raise ValueError(
            f"lattice {state.shape} smaller than patch window 2r+1="
            f"{2 * radius + 1}; no patches possible"
        )

    for x in range(radius, X - radius, stride):
        sx = slice(x - radius, x + radius + 1)
        for y in range(radius, Y - radius, stride):
            sy = slice(y - radius, y + radius + 1)
            for z in range(radius, Z - radius, stride):
                sz = slice(z - radius, z + radius + 1)
                yield Patch(
                    center=(x, y, z),
                    state=state[sx, sy, sz],
                    memory=memory[:, sx, sy, sz],
                )


def iter_importance_patches(
    state: np.ndarray,
    memory: np.ndarray,
    *,
    radius: int = 1,
    acoustic_map: np.ndarray | None = None,
    sage_coords: list[tuple[int, int, int]] | None = None,
) -> Iterator[Patch]:
    """Stub: importance-weighted sampling lands in Phase 19 PR #3+.

    When implemented, will bias toward acoustic-stress sectors (top-25%
    friction per the Phase 14e map) and Sage neighbourhoods (top-K
    eldest COMPUTE cells). The signature above is a placeholder; it
    may evolve once we see what the metrics pipeline (PR #3) actually
    needs to surface.
    """
    raise NotImplementedError(
        "Importance sampling lands in Phase 19 PR #3+. "
        "Use SamplingMode.UNIFORM_GRID for PR #2."
    )


def iter_dense_patches(
    state: np.ndarray,
    memory: np.ndarray,
    *,
    radius: int = 1,
) -> Iterator[Patch]:
    """Stub: dense per-cell pass lands no earlier than Phase 19 PR #4.

    Dense mode is offline-batch only; will refuse if Medusa is live
    (see the dispatcher ``iter_patches``). When implemented, will
    yield ~16M patches per snapshot for a 256^3 lattice — orders of
    magnitude more than UNIFORM_GRID — so it must be gated by both
    the ``MEDUSA_OBSERVER_DENSE=1`` env var AND a live-medusa freshness
    check before actually running.
    """
    raise NotImplementedError(
        "Dense per-cell sampling lands no earlier than Phase 19 PR #4 "
        "and only for offline batch runs. Use SamplingMode.UNIFORM_GRID "
        "for PR #2."
    )


def iter_patches(
    state: np.ndarray,
    memory: np.ndarray,
    config: ObserverConfig,
    *,
    medusa_is_live: bool = False,
) -> Iterator[Patch]:
    """Top-level dispatcher: route to the sampler for ``config.sampling_mode``.

    Refuses to run dense mode while Medusa is live (per §9 sampling
    discipline). The ``medusa_is_live`` flag is computed by the
    caller — the helper that actually checks snapshot freshness lives
    in Chunk 5 (``is_medusa_live(...)``). Keeping that out of this
    function preserves the sampler as pure logic over arrays, easy
    to test in isolation.
    """
    mode = config.sampling_mode
    if mode is SamplingMode.UNIFORM_GRID:
        return iter_uniform_grid_patches(
            state, memory,
            stride=config.uniform_grid_stride,
            radius=config.patch_spatial_radius,
        )
    if mode is SamplingMode.IMPORTANCE:
        return iter_importance_patches(
            state, memory,
            radius=config.patch_spatial_radius,
        )
    if mode is SamplingMode.DENSE:
        if medusa_is_live:
            raise DenseModeWhileLiveError(
                "SamplingMode.DENSE refuses to run while Medusa is live. "
                "Set medusa_is_live=False (offline batch context) or "
                "switch to UNIFORM_GRID."
            )
        return iter_dense_patches(
            state, memory,
            radius=config.patch_spatial_radius,
        )
    raise ValueError(f"unknown SamplingMode: {mode!r}")


# ---------------------------------------------------------------------------
# Chunk 3: classifier — 16 hand-coded predicates → token name
# ---------------------------------------------------------------------------
#
# `classify_patch(patch) -> str` is the heart of the observer. It runs a
# cascading sequence of cheap predicates over patch features and returns
# exactly one token name from TOKEN_NAMES.
#
# Order matters. Most specific tokens are checked first; broad fallbacks
# (`void_static`, `acoustic_stress`, `unclassified`) sit at the bottom.
# Each predicate is intentionally simple — no ML, no learned thresholds,
# nothing requiring training. This is the v0 baseline against which a
# learned 512-token embedding (PR #5, optional) will be measured.
#
# Two assumptions worth flagging up front:
#
#   1. State integer codes follow the engine's convention (VOID=0, ...,
#      SENSOR=4). These match scripts/continuous_evolution_ca.py.
#
#   2. Memory-grid channel layout is the observer's BEST GUESS at the
#      semantic-to-channel mapping. If the engine's actual layout differs,
#      ONLY the constants in MEMORY_CHANNEL_LAYOUT need updating; the
#      predicates use named accessors via _patch_features. The §8 #3
#      acoustic-correspondence test in PR #4 will catch a wrong mapping
#      empirically — wrong channels → poor correlation → revise.

# --- State integer codes (engine convention) ---
STATE_VOID: Final[int] = 0
STATE_STRUCTURAL: Final[int] = 1
STATE_COMPUTE: Final[int] = 2
STATE_ENERGY: Final[int] = 3
STATE_SENSOR: Final[int] = 4

# --- Memory-grid channel layout (BEST GUESS; verify when calibrating) ---
# If wrong, update these and the classifier should still hold its shape.
MEMORY_CHANNEL_LAYOUT: Final[dict[str, int]] = {
    "compute_age":       0,   # COMPUTE cell age (per Phase 4 onwards)
    "structural_age":    1,   # STRUCTURAL cell age
    "warmth":            2,   # Phase 6a metta accumulator
    "resonance":         3,   # Phase 6b mudita joy/resonance signal
    "compassion":        4,   # Phase 6c karuna relief signal
    "mindsight":         5,   # Phase 6c mindsight signal magnitude
    "magnon":            6,   # Phase 17a magnon field magnitude
    "ampere":            7,   # Ampere unified-field accumulator
}

# --- Age thresholds (matched to the engine's MemoryParams Sage tiers) ---
AGE_SAGE: Final[float] = 8.0       # magnon_sage_age_min default
AGE_ANCIENT: Final[float] = 20.0   # Ancient (2x magnon amplification)
AGE_LEGEND: Final[float] = 50.0    # Legend (5x; the 148 lighthouse Sages)

# --- Memory-signal detection thresholds (normalised; tunable) ---
# These are starting values. PR #4 may tune them via baseline calibration.
THRESHOLD_WARMTH: Final[float] = 0.3
THRESHOLD_RESONANCE: Final[float] = 0.3
THRESHOLD_COMPASSION: Final[float] = 0.3

# --- State-fraction thresholds (over the patch's 27 cells at radius=1) ---
FRACTION_DOMINANT: Final[float] = 0.5    # > 50% of cells (≥14 of 27)
FRACTION_MAJORITY: Final[float] = 0.7    # > 70% of cells (≥19 of 27)

# --- Other detection thresholds ---
DIVERSITY_BOUNDARY: Final[int] = 4   # ≥4 distinct state codes → phase_boundary
ENERGY_PULSE_MIN_COUNT: Final[int] = 3  # ≥3 ENERGY cells → energy_pulse


@dataclasses.dataclass(frozen=True)
class _PatchFeatures:
    """Pre-computed summary statistics over a Patch.

    Computed once per patch in `classify_patch` and passed to the cascading
    predicates. Avoids recomputing the same `.sum()` or `.mean()` calls
    for every candidate token. Internal type — not exported.
    """
    total_cells: int
    void_count: int
    structural_count: int
    compute_count: int
    energy_count: int
    sensor_count: int
    distinct_states: int
    void_frac: float
    structural_frac: float
    compute_frac: float
    energy_frac: float
    sensor_frac: float
    compute_age_mean: float
    structural_age_mean: float
    warmth_mean: float
    resonance_mean: float
    compassion_mean: float
    magnon_mean: float


def _patch_features(patch: Patch) -> _PatchFeatures:
    """Compute the summary statistics block for one patch.

    Defensive over memory-grid shapes: if the engine ever ships fewer
    than 8 channels (e.g., during Phase 3 when only 4 channels existed),
    missing-channel means default to 0.0 instead of raising.
    """
    state = patch.state
    memory = patch.memory
    total = int(state.size)

    void_count = int(np.sum(state == STATE_VOID))
    structural_count = int(np.sum(state == STATE_STRUCTURAL))
    compute_count = int(np.sum(state == STATE_COMPUTE))
    energy_count = int(np.sum(state == STATE_ENERGY))
    sensor_count = int(np.sum(state == STATE_SENSOR))
    counts = (void_count, structural_count, compute_count, energy_count, sensor_count)
    distinct_states = sum(1 for c in counts if c > 0)

    n_channels = memory.shape[0]

    def _safe_mean(channel_name: str) -> float:
        idx = MEMORY_CHANNEL_LAYOUT[channel_name]
        return float(memory[idx].mean()) if idx < n_channels else 0.0

    return _PatchFeatures(
        total_cells=total,
        void_count=void_count,
        structural_count=structural_count,
        compute_count=compute_count,
        energy_count=energy_count,
        sensor_count=sensor_count,
        distinct_states=distinct_states,
        void_frac=void_count / total,
        structural_frac=structural_count / total,
        compute_frac=compute_count / total,
        energy_frac=energy_count / total,
        sensor_frac=sensor_count / total,
        compute_age_mean=_safe_mean("compute_age"),
        structural_age_mean=_safe_mean("structural_age"),
        warmth_mean=_safe_mean("warmth"),
        resonance_mean=_safe_mean("resonance"),
        compassion_mean=_safe_mean("compassion"),
        magnon_mean=_safe_mean("magnon"),
    )


def classify_patch(patch: Patch) -> str:
    """Classify a Patch into one of TOKEN_NAMES via cascading predicates.

    Cascade order is significant. The tokens that match are commented
    in priority order — most specific first, broad fallbacks last.
    The function is total: every patch returns exactly one token,
    with `unclassified` as the last-resort bucket.
    """
    f = _patch_features(patch)

    # 1. Phase boundary — high state diversity in a small patch
    if f.distinct_states >= DIVERSITY_BOUNDARY:
        return "phase_boundary"

    # 2. Magnon lighthouse — COMPUTE-dominant under Legend-tier influence
    if f.compute_frac >= FRACTION_DOMINANT and f.compute_age_mean >= AGE_LEGEND:
        return "magnon_lighthouse"

    # 3. Compute aging — COMPUTE-dominant at Sage age tier (typical Sage)
    if f.compute_frac >= FRACTION_DOMINANT and f.compute_age_mean >= AGE_SAGE:
        return "compute_aging"

    # 4. Mudita resonance — joy/resonance signal alongside any COMPUTE
    if f.compute_count >= 1 and f.resonance_mean >= THRESHOLD_RESONANCE:
        return "mudita_resonance"

    # 5. Karuna relief — compassion signal alongside any COMPUTE
    if f.compute_count >= 1 and f.compassion_mean >= THRESHOLD_COMPASSION:
        return "karuna_relief"

    # 6. Metta warmth — warmth field around COMPUTE/ENERGY
    if (f.compute_count >= 1 or f.energy_count >= 1) and f.warmth_mean >= THRESHOLD_WARMTH:
        return "metta_warmth"

    # 7. Sensor alert — any SENSOR present (intrinsically rare and notable)
    if f.sensor_count >= 1:
        return "sensor_alert"

    # 8. Energy pulse — multiple ENERGY cells; suggests gradient/wave
    if f.energy_count >= ENERGY_PULSE_MIN_COUNT:
        return "energy_pulse"

    # 9. Compute decay — COMPUTE present in a void-dominant cold patch
    if (f.compute_count >= 1
            and f.void_frac >= FRACTION_DOMINANT
            and f.warmth_mean < THRESHOLD_WARMTH):
        return "compute_decay"

    # 10. Compute static — COMPUTE-dominant patch (no age/signal triggers above)
    if f.compute_frac >= FRACTION_DOMINANT:
        return "compute_static"

    # 11. Structural growth — STRUCTURAL-dominant + young
    if f.structural_frac >= FRACTION_DOMINANT and f.structural_age_mean < AGE_SAGE:
        return "structural_growth"

    # 12. Structural decay — STRUCTURAL-dominant + mature
    if f.structural_frac >= FRACTION_DOMINANT and f.structural_age_mean >= AGE_ANCIENT:
        return "structural_decay"

    # 13. Void birth — VOID-dominant but with > 1 distinct state (something forming)
    if f.void_frac >= FRACTION_DOMINANT and f.distinct_states >= 2:
        return "void_birth"

    # 14. Void static — VOID majority and nothing else (the typical "empty" patch)
    if f.void_frac >= FRACTION_MAJORITY:
        return "void_static"

    # 15. Acoustic stress (heuristic placeholder, refined in PR #4 against the
    #     Phase 14e acoustic map) — diverse-but-cold patch suggests friction.
    if f.distinct_states >= 3 and f.warmth_mean < THRESHOLD_WARMTH:
        return "acoustic_stress"

    # 16. Catch-all
    return "unclassified"


# Add Chunk 3 exports
__all__ += [  # type: ignore[misc]
    # Engine-state codes
    "STATE_VOID",
    "STATE_STRUCTURAL",
    "STATE_COMPUTE",
    "STATE_ENERGY",
    "STATE_SENSOR",
    # Memory-channel layout (assumption; verify in PR #4)
    "MEMORY_CHANNEL_LAYOUT",
    # Thresholds (so PR #4 calibration can override or report on them)
    "AGE_SAGE",
    "AGE_ANCIENT",
    "AGE_LEGEND",
    "THRESHOLD_WARMTH",
    "THRESHOLD_RESONANCE",
    "THRESHOLD_COMPASSION",
    "FRACTION_DOMINANT",
    "FRACTION_MAJORITY",
    "DIVERSITY_BOUNDARY",
    "ENERGY_PULSE_MIN_COUNT",
    # Classifier
    "classify_patch",
]


# ---------------------------------------------------------------------------
# Chunk 4: budget monitor + pre-flight density backoff
# ---------------------------------------------------------------------------
#
# Implements §7 invariant #8 of the design doc — the observer must stay
# under a configurable per-snapshot wall-time budget, and reduce sampling
# density rather than running over.
#
# Two cooperating mechanisms:
#
#   1. ``compute_safe_stride()`` — pre-flight: given a lattice shape, a
#      patch radius, a wall-time budget, and a per-patch cost estimate,
#      returns the smallest stride (densest sampling) that should fit.
#      Doubles the stride until the estimated cost is within budget.
#
#   2. ``BudgetMonitor`` — runtime: a context-manager that tracks
#      elapsed wall-time and counts patches processed/skipped. The
#      caller checks ``bm.exceeded()`` in their loop and breaks out
#      gracefully when over. No exception is raised by default —
#      partial classification of a snapshot is preferable to throwing
#      the work away.
#
# Together: pre-flight reduces the chance of needing the runtime bail;
# the runtime monitor catches whatever the pre-flight estimate missed.

import time


@dataclasses.dataclass(frozen=True)
class BudgetReport:
    """Diagnostic block produced by a budget-monitored run.

    Logged alongside the per-snapshot results in Chunk 5's JSONL output
    so PR #4's calibration pass can see how often density backoff
    fired and tune cost-per-patch estimates from real data.
    """

    budget_seconds: float
    elapsed_seconds: float
    patches_processed: int
    patches_skipped_due_to_budget: int
    exceeded: bool

    @property
    def fraction_used(self) -> float:
        return self.elapsed_seconds / self.budget_seconds if self.budget_seconds > 0 else 1.0


class BudgetMonitor:
    """Wall-time tracker for a single observer pass.

    Use as a context manager. The caller is responsible for actually
    breaking out of their loop on ``exceeded()``; this class only tracks.

    Usage::

        with BudgetMonitor(budget_seconds=30.0) as bm:
            for patch in iter_patches(...):
                if bm.exceeded():
                    bm.skip()
                    break
                bm.tick()
                token = classify_patch(patch)

        report = bm.report()
    """

    def __init__(self, budget_seconds: float) -> None:
        if budget_seconds <= 0:
            raise ValueError(
                f"budget_seconds={budget_seconds}; must be > 0"
            )
        self._budget = budget_seconds
        self._start: float | None = None
        self._patches = 0
        self._skipped = 0

    def __enter__(self) -> "BudgetMonitor":
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        # Don't suppress exceptions — let the caller see whatever happened.
        return None

    def elapsed(self) -> float:
        """Seconds since ``__enter__`` (0 if not yet entered)."""
        if self._start is None:
            return 0.0
        return time.monotonic() - self._start

    def remaining(self) -> float:
        """Seconds left on the budget; clamped at 0."""
        return max(0.0, self._budget - self.elapsed())

    def exceeded(self) -> bool:
        """``True`` once elapsed >= budget."""
        return self.elapsed() >= self._budget

    def tick(self) -> None:
        """Increment the processed-patches counter."""
        self._patches += 1

    def skip(self) -> None:
        """Increment the skipped-due-to-budget counter."""
        self._skipped += 1

    def report(self) -> BudgetReport:
        """Snapshot the monitor state into a logged ``BudgetReport``."""
        return BudgetReport(
            budget_seconds=self._budget,
            elapsed_seconds=self.elapsed(),
            patches_processed=self._patches,
            patches_skipped_due_to_budget=self._skipped,
            exceeded=self.exceeded(),
        )


# Default cost-per-patch estimate for compute_safe_stride. The cascade in
# classify_patch is cheap (numpy reductions over 27-cell patches), so a
# conservative 0.5ms/patch is a safe initial guess. PR #4 baseline pass
# can replace this with a measured value.
DEFAULT_COST_PER_PATCH_SECONDS: Final[float] = 5e-4


def _patches_at_stride(
    lattice_shape: tuple[int, int, int],
    radius: int,
    stride: int,
) -> int:
    """Count of patches the uniform-grid sampler would yield.

    Mirrors the sampler's ``range(radius, X - radius, stride)`` exactly,
    so this is an authoritative count, not an approximation.
    """
    X, Y, Z = lattice_shape
    if X <= 2 * radius or Y <= 2 * radius or Z <= 2 * radius:
        return 0
    nx = max(0, len(range(radius, X - radius, stride)))
    ny = max(0, len(range(radius, Y - radius, stride)))
    nz = max(0, len(range(radius, Z - radius, stride)))
    return nx * ny * nz


def compute_safe_stride(
    lattice_shape: tuple[int, int, int],
    *,
    radius: int = 1,
    budget_seconds: float = 30.0,
    cost_per_patch_seconds: float = DEFAULT_COST_PER_PATCH_SECONDS,
    initial_stride: int = 8,
    max_stride: int = 64,
) -> int:
    """Pre-flight: smallest stride whose estimated cost fits the budget.

    Doubles the stride until ``patches * cost_per_patch <= budget``.
    Returns ``initial_stride`` if that already fits; ``max_stride`` if
    no stride within range fits (in which case the caller may need to
    accept partial coverage or skip the snapshot).
    """
    if initial_stride < 1:
        raise ValueError(f"initial_stride={initial_stride}; must be >= 1")
    if max_stride < initial_stride:
        raise ValueError(
            f"max_stride={max_stride} < initial_stride={initial_stride}"
        )

    s = initial_stride
    while s <= max_stride:
        n_patches = _patches_at_stride(lattice_shape, radius, s)
        if n_patches == 0:
            # Lattice too small for this stride — already at minimum density.
            return s
        estimated = n_patches * cost_per_patch_seconds
        if estimated <= budget_seconds:
            return s
        s *= 2

    # Hit the cap; return the largest stride considered.
    return max_stride


# Add Chunk 4 exports
__all__ += [  # type: ignore[misc]
    "BudgetReport",
    "BudgetMonitor",
    "DEFAULT_COST_PER_PATCH_SECONDS",
    "compute_safe_stride",
]


# ---------------------------------------------------------------------------
# Chunk 5: I/O + process_snapshot end-to-end
# ---------------------------------------------------------------------------
#
# This chunk wires Chunks 2 (sampler), 3 (classifier), and 4 (budget) into
# a single function that reads a real Medusa snapshot file and writes a
# JSONL log entry summarising the observation.
#
# Boundaries enforced here:
#
#   • Snapshot loading uses ``allow_pickle=True`` because Medusa's own
#     ``np.savez`` artefacts include pickled metadata (Phase 16's
#     medusa_api uses the same flag). We trust the engine's own files.
#     Loading non-Medusa .npz files is not in scope; the function only
#     accepts paths that match the configured snapshot glob.
#
#   • Writes are restricted to ``config.log_directory`` and its parent
#     must already exist (we create the leaf log dir, never the scaffold).
#     Any attempt to write a path that doesn't resolve into log_directory
#     raises ``WriteOutsideLogDirError`` (§7 invariant #1).
#
#   • No HTTP, no ZMQ, no shell. Only filesystem reads + a single JSONL
#     append per processed snapshot.

import collections
import json
import pathlib
from datetime import datetime, timezone


_REQUIRED_SNAPSHOT_KEYS: Final[frozenset[str]] = frozenset(
    {"lattice", "memory_grid", "generation"}
)
_LOG_FILE_NAME: Final[str] = "nextness_runs.jsonl"


def _is_valid_snapshot_npz(path: pathlib.Path) -> bool:
    """Cheap validity predicate for a ``.npz`` Medusa snapshot.

    Opens the file with ``np.load(..., allow_pickle=False)`` and confirms
    the three required keys (``lattice``, ``memory_grid``, ``generation``)
    are present in the zip directory. Does NOT load or decompress array
    data — ``NpzFile.files`` reads only the zip's central directory, so
    this stays in the milliseconds range even for tens of MB.

    Any failure mode — missing keys, malformed zip, I/O error, pickled
    payload that ``allow_pickle=False`` refuses to materialize at
    file-listing time — yields ``False``. The function never raises.

    Per issue #139 finding (a): replaces the previous file-size
    threshold, which was structurally wrong (real snapshots range from
    ~900 KB sparse-VOID-early to ~54 MB mature-mixed, so size carries
    no validity signal).
    """
    try:
        with np.load(str(path), allow_pickle=False) as snap:
            return _REQUIRED_SNAPSHOT_KEYS.issubset(set(snap.files))
    except Exception:
        # Catch broadly: malformed zip, missing file, permissions,
        # pickled-payload-refused, future numpy quirks. Any failure
        # is "this is not a valid Medusa snapshot."
        return False


def find_latest_snapshot(
    snapshot_dir: str | pathlib.Path,
    pattern: str = "v070_gen*.npz",
) -> pathlib.Path | None:
    """Return the path of the most-recent valid snapshot matching ``pattern``.

    Iterates candidates in newest-first mtime order and returns the
    first one that passes ``_is_valid_snapshot_npz`` (zip directory
    contains the required keys). Returns ``None`` if no candidate
    validates — INCLUDING the case where matching files exist but
    none are well-formed snapshots.

    Per issue #139 finding (a): validity is now a structural check on
    required keys rather than a file-size heuristic. Sparse early-phase
    snapshots (~900 KB) that the old size-threshold silently excluded
    are now recognized, and corrupt ≥1 MB files that the old threshold
    silently admitted are now rejected.
    """
    snapshot_dir = pathlib.Path(snapshot_dir)
    if not snapshot_dir.is_dir():
        return None
    candidates = sorted(
        snapshot_dir.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for p in candidates:
        if _is_valid_snapshot_npz(p):
            return p
    return None


def is_medusa_live(
    snapshot_dir: str | pathlib.Path,
    pattern: str = "v070_gen*.npz",
    threshold_minutes: int = 30,
) -> bool:
    """True if the most-recent snapshot is younger than ``threshold_minutes``.

    Used to gate dense-mode (which refuses to run while Medusa is live)
    and to set the ``medusa_is_live`` field in the JSONL log so PR #4
    can correlate observations with engine activity.
    """
    latest = find_latest_snapshot(snapshot_dir, pattern)
    if latest is None:
        return False
    try:
        age_seconds = max(0.0, time.time() - latest.stat().st_mtime)
    except OSError:
        return False
    return age_seconds / 60.0 < threshold_minutes


def load_snapshot(
    snapshot_path: str | pathlib.Path,
) -> tuple[np.ndarray, np.ndarray, int, dict[str, object]]:
    """Load a Medusa ``.npz`` snapshot.

    Returns ``(state, memory_grid, generation, meta)``:

      • ``state``: uint8 array of shape (X, Y, Z)
      • ``memory_grid``: float32 array of shape (channels, X, Y, Z)
      • ``generation``: int
      • ``meta``: dict of additional numeric/scalar keys; any pickled
        object metadata is silently skipped (see below).

    Uses ``allow_pickle=False`` for safety per Jack's PR #138 audit:
    even though Medusa's own snapshots are trusted, this function accepts
    arbitrary paths and so must not be a pickle-deserialization sink.
    Only the three required numeric keys (``lattice``, ``memory_grid``,
    ``generation``) are needed for classification; any other keys in
    the file are loaded if they're plain numeric arrays/scalars and
    skipped silently if they require pickle.

    Raises ``ValueError`` if required keys are missing or shapes are
    inconsistent — defensive against passing the wrong file.
    """
    snapshot_path = pathlib.Path(snapshot_path)
    if not snapshot_path.is_file():
        raise FileNotFoundError(f"snapshot not found: {snapshot_path}")
    snap = np.load(str(snapshot_path), allow_pickle=False)
    keys = set(snap.files)
    required = {"lattice", "memory_grid", "generation"}
    missing = required - keys
    if missing:
        raise ValueError(
            f"snapshot {snapshot_path.name} missing keys: {sorted(missing)}"
        )
    state = snap["lattice"]
    memory = snap["memory_grid"]
    generation = int(snap["generation"])
    if state.ndim != 3:
        raise ValueError(
            f"snapshot {snapshot_path.name}: state must be 3D, got shape {state.shape}"
        )
    if memory.ndim != 4 or memory.shape[1:] != state.shape:
        raise ValueError(
            f"snapshot {snapshot_path.name}: memory shape {memory.shape} "
            f"inconsistent with state shape {state.shape}"
        )
    # Optional metadata: only include keys that load without pickle.
    # With allow_pickle=False any key requiring pickle will raise ValueError
    # at access time; we catch + skip rather than fail the whole load.
    meta: dict[str, object] = {}
    for k in keys - required:
        try:
            val = snap[k]
        except ValueError:
            # Key needs pickle (object dtype); skip silently per §7 #7 spirit.
            continue
        meta[k] = val.item() if val.ndim == 0 else val
    return state, memory, generation, meta


def _validate_write_path(
    path: pathlib.Path,
    log_directory: pathlib.Path,
) -> None:
    """Raise ``WriteOutsideLogDirError`` if ``path`` is not inside ``log_directory``.

    Resolves both paths to canonical absolute form before comparing — this
    catches symlink-and-traversal escapes, not just literal string mismatches.
    """
    log_resolved = log_directory.resolve()
    path_resolved = path.resolve()
    try:
        path_resolved.relative_to(log_resolved)
    except ValueError as e:
        raise WriteOutsideLogDirError(
            f"refusing to write outside log_directory: "
            f"{path_resolved} is not inside {log_resolved}"
        ) from e


def _ensure_log_dir(log_directory: str | pathlib.Path) -> pathlib.Path:
    """Create ``log_directory`` if missing; refuse if its parent doesn't exist.

    The observer is allowed to create its own leaf directory but not the
    scaffolding above it. If ``data/`` doesn't exist, that's an
    environmental problem the observer should not try to fix.
    """
    log_directory = pathlib.Path(log_directory)
    if log_directory.exists():
        if not log_directory.is_dir():
            raise WriteOutsideLogDirError(
                f"log_directory {log_directory} exists but is not a directory"
            )
        return log_directory
    parent = log_directory.parent
    if not parent.is_dir():
        raise FileNotFoundError(
            f"log_directory parent does not exist: {parent}. "
            f"Refusing to create scaffolding; ensure {parent} exists first."
        )
    log_directory.mkdir(parents=False, exist_ok=False)
    return log_directory


def write_log_entry(
    log_directory: str | pathlib.Path,
    entry: dict[str, object],
) -> pathlib.Path:
    """Append one JSON object as a line to ``<log_directory>/nextness_runs.jsonl``.

    Creates the log directory if needed (subject to ``_ensure_log_dir``'s
    parent-must-exist rule). Validates the resulting path is inside the
    log directory before writing — defence against config drift.
    """
    log_dir = _ensure_log_dir(log_directory)
    log_path = log_dir / _LOG_FILE_NAME
    _validate_write_path(log_path, log_dir)
    line = json.dumps(entry, sort_keys=True, default=str)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return log_path


# ---------------------------------------------------------------------------
# PR #3 — per-snapshot metric helpers (PHASE_19_PR3_METRICS_PIPELINE.md §3)
# ---------------------------------------------------------------------------

import math
from collections.abc import Mapping


def shannon_entropy_bits(token_counts: Mapping[str, int]) -> float:
    """Shannon entropy (in bits) over a token-count distribution.

    Uses base-2 log so the result is in units of bits. Returns 0.0 if the
    distribution is empty (no patches classified). Zero-count tokens are
    skipped under the convention 0·log(0) = 0.

    Maximum value for the canonical 16-token vocabulary is log₂(16) = 4.0
    bits (uniform distribution over all tokens). The first real Medusa
    pass at gen 1,621,779 yielded ~0.98 bits — distribution concentrated
    in two tokens, as documented in issue #139.
    """
    total = sum(token_counts.values())
    if total == 0:
        return 0.0
    h = 0.0
    for count in token_counts.values():
        if count <= 0:
            continue
        p = count / total
        h -= p * math.log2(p)
    return h


def entropy_normalized(entropy_bits: float, vocabulary_size: int) -> float:
    """Normalize a Shannon-entropy-in-bits value to [0, 1].

    Divides by log₂(vocabulary_size) to produce a unit-comparable score
    across different vocabulary sizes (relevant once PR #5 introduces the
    learned 512-token embedding alongside the current 16-token hand-coded
    vocabulary).

    Returns 0.0 if vocabulary_size <= 1 (no information possible) or if
    the supplied entropy is non-positive.
    """
    if vocabulary_size <= 1 or entropy_bits <= 0.0:
        return 0.0
    return entropy_bits / math.log2(vocabulary_size)


def void_compute_balance(state: np.ndarray) -> float:
    """Symmetric balance score between VOID and COMPUTE cell counts.

    Computes ``2 · min(N_VOID, N_COMPUTE) / (N_VOID + N_COMPUTE)`` over the
    raw cell-state array. Range [0, 1]; 1.0 iff the counts are equal; 0.0
    if either state is absent or if the lattice contains neither.

    Captures the "coexistence axis" of AURA's Sakana-derived 3-regime
    framing using the two cell states that dominate the mature 256³
    Medusa lattice. For gen 1,621,779: N_VOID = 7,909,111 (47.14%),
    N_COMPUTE = 7,719,525 (46.01%), giving balance ≈ 0.988.
    """
    n_void = int(np.count_nonzero(state == STATE_VOID))
    n_compute = int(np.count_nonzero(state == STATE_COMPUTE))
    total = n_void + n_compute
    if total == 0:
        return 0.0
    return 2.0 * min(n_void, n_compute) / total


def boundary_rate(token_counts: Mapping[str, int]) -> float:
    """Normalized count of the ``phase_boundary`` token.

    Returns count(phase_boundary) / sum(all token counts), range [0, 1].
    Returns 0.0 if no patches were classified or if ``phase_boundary``
    is absent from the counts mapping.

    Promoted to a top-level metric per PHASE_19_PR3_METRICS_PIPELINE.md
    §3.4 — boundary rate is the single most-architecturally-important
    token signal (fungal-network "growth at active boundary" intuition),
    so it gets a first-class field rather than living only inside the
    nested ``token_counts`` dict.
    """
    total = sum(token_counts.values())
    if total == 0:
        return 0.0
    return token_counts.get("phase_boundary", 0) / total


def process_snapshot(
    snapshot_path: str | pathlib.Path,
    config: ObserverConfig,
    *,
    medusa_is_live: bool | None = None,
    snapshot_dir: str | pathlib.Path | None = None,
) -> dict[str, object]:
    """End-to-end: load a snapshot, classify patches, write a log entry, return summary.

    The summary dict is the same JSON object that gets appended to the
    JSONL log. Returning it lets callers (tests, PR 3 metrics pipeline)
    consume it directly without re-reading the file.

    ``medusa_is_live`` may be passed explicitly (typically by tests) or
    auto-detected via ``is_medusa_live`` against ``snapshot_dir`` (or
    the snapshot's parent directory if not given). Used to gate dense
    mode and to record context in the log.
    """
    snapshot_path = pathlib.Path(snapshot_path)
    state, memory, generation, meta = load_snapshot(snapshot_path)

    if medusa_is_live is None:
        check_dir = pathlib.Path(snapshot_dir) if snapshot_dir else snapshot_path.parent
        medusa_is_live = is_medusa_live(
            check_dir,
            threshold_minutes=config.medusa_live_threshold_minutes,
        )

    # Pre-flight density backoff: pick the smallest stride that fits the budget.
    safe_stride = compute_safe_stride(
        state.shape,
        radius=config.patch_spatial_radius,
        budget_seconds=config.budget_seconds,
        initial_stride=config.uniform_grid_stride,
    )
    # Build a per-snapshot config that uses the chosen stride.
    snapshot_config = dataclasses.replace(config, uniform_grid_stride=safe_stride)

    token_counts: collections.Counter[str] = collections.Counter()

    with BudgetMonitor(budget_seconds=config.budget_seconds) as bm:
        for patch in iter_patches(
            state, memory, snapshot_config, medusa_is_live=medusa_is_live,
        ):
            if bm.exceeded():
                bm.skip()
                break
            token = classify_patch(patch)
            token_counts[token] += 1
            bm.tick()

    report = bm.report()

    # Per issue #139 finding (b): ``BudgetReport.fraction_used`` is a
    # ``@property``, so ``dataclasses.asdict`` (which walks fields only)
    # silently drops it. Build the budget block explicitly so the JSONL
    # log carries the same fraction available on the live object.
    budget_block: dict[str, object] = dict(dataclasses.asdict(report))
    budget_block["fraction_used"] = report.fraction_used

    # PR #3 per-snapshot metrics (PHASE_19_PR3_METRICS_PIPELINE.md §3).
    # All computed from data already in memory; total cost ≈ 50 µs at K=16
    # tokens on a 256³ lattice, negligible against the ~1s classification time.
    shannon_h = shannon_entropy_bits(token_counts)
    entry: dict[str, object] = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "snapshot_file": snapshot_path.name,
        "generation": generation,
        "lattice_shape": list(state.shape),
        "memory_channels": int(memory.shape[0]),
        "sampling_mode": config.sampling_mode.value,
        "patch_radius": config.patch_spatial_radius,
        "stride_initial": config.uniform_grid_stride,
        "stride_used": safe_stride,
        "stride_backoff_fired": safe_stride != config.uniform_grid_stride,
        "medusa_is_live": medusa_is_live,
        "token_counts": dict(token_counts),
        "vocabulary_occupancy": len(token_counts) / max(1, len(TOKEN_NAMES)),
        "shannon_entropy_bits": shannon_h,
        "entropy_normalized": entropy_normalized(shannon_h, len(TOKEN_NAMES)),
        "void_compute_balance": void_compute_balance(state),
        "boundary_rate": boundary_rate(token_counts),
        "budget": budget_block,
    }
    write_log_entry(config.log_directory, entry)
    return entry


# Add Chunk 5 exports
__all__ += [  # type: ignore[misc]
    "find_latest_snapshot",
    "is_medusa_live",
    "load_snapshot",
    "write_log_entry",
    "process_snapshot",
    # PR #3 per-snapshot metric helpers
    "shannon_entropy_bits",
    "entropy_normalized",
    "void_compute_balance",
    "boundary_rate",
]


# ---------------------------------------------------------------------------
# Chunk 6 (next): unit tests for the safety contract + commit + open PR.
# Tests live in tests/test_nextness_observer.py and lock down each §7
# invariant with a dedicated test. PR opens for AURA + Jack review;
# does NOT auto-merge.
# ---------------------------------------------------------------------------
