"""Calibration experiments orchestrator for the Nextness Observer (Phase 19 PR #4).

Implements the eight calibration experiments designed in
``PHASE_19_PR4_CALIBRATION.md`` (merged as ``3346014``). Each experiment
discriminates the **phase-boundary stability hypothesis** from the
alternate observer-artifact hypotheses flagged in issue #139.

(The earlier "Karuna/Boundary equilibrium" semantic interpretation was
superseded per issue #144 / PR #145: the pre-fix ``karuna_relief`` token
was reading the engine's ``last_active_gen`` channel due to a
``MEMORY_CHANNEL_LAYOUT`` mismatch. ``phase_boundary`` stability is the
well-anchored part of the prior result and is what the calibration
sweeps test for robustness.)

Per Jack's implementation order from the design doc §12 Q7:

    1. check_determinism                    LANDED (Chapter 1)
    2. verify_memory_channels               (upcoming, runtime regression-fence
                                             complementing PR #145's static check)
    3. shuffle_test                         LANDED (Chapter 2, three-mode null-model)
    4. sweep_stride                         (upcoming)
    5. sweep_threshold                      (upcoming)
    6. ablate_cascade                       (upcoming)
    7. sweep_temporal                       (upcoming)
    8. sweep_patch_radius                   (upcoming, possibly deferred)

Chapters 1 + 2 land the shared module infrastructure (write-boundary safety,
deterministic snapshot ordering, content fingerprinting, JSONL output writer,
falsification-status reporting) plus ``check_determinism()`` (Jack's #1 — the
sanity floor) and ``shuffle_test()`` (Jack's #3 — the three-mode null-model
test that pinpoints whether signal lives in lattice geometry, memory_grid
spatial structure, or classifier behaviour).

Scope guarantees (carried forward from PR #138 / PR #140 / PR #142 / PR #143):
    - No engine touch.
    - **No writes outside ``log_path.parent``** — enforced via
      :class:`WriteOutsideLogDirError` reused from ``scripts.nextness_observer``
      so the safety vocabulary stays unified across modules.
    - No HTTP / ZMQ / network of any kind.
    - CPU-only.
    - ``allow_pickle=False`` preserved in any snapshot reads (delegated to
      ``nextness_observer.process_snapshot()``).
    - Bounded compute: each experiment is O(N * P) where N = snapshots and
      P = parameter combinations per experiment. Both small.

Determinism contracts (per design doc §8 + PR #143 revision):
    - Snapshots are sorted by (generation, snapshot_file) before any
      parameter-combination iteration runs. Output is independent of input
      file order.
    - No fresh ``generated_at`` field is added to any output JSONL row.
    - Content fingerprinting for the ``check_determinism`` experiment
      excludes the volatile ``ts`` field that ``process_snapshot()`` writes
      (current timestamp at log-write time); fingerprint covers all
      *content-bearing* fields.
    - All JSONL writes use ``sort_keys=True`` for deterministic field order.

CLI: deferred to a later chapter; this module exposes Python entry points
only for now. The CLI sub-command surface is specified in design doc §5 and
will land alongside the final sweep functions.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import pathlib
import re
import tempfile
from typing import Any

import numpy as np

from scripts.nextness_observer import (
    ObserverConfig,
    WriteOutsideLogDirError,
    process_snapshot,
)
from scripts.nextness_metrics import cci as _cci


# ---------------------------------------------------------------------------
# Shared module constants
# ---------------------------------------------------------------------------


#: Default RNG seed for canonical-run results (e.g. shuffle test). Variance
#: estimates use this plus 5 additional seeds per design doc §12 Q6.
DEFAULT_CANONICAL_SEED: int = 42

#: Additional seeds for variance estimation. Used together with
#: ``DEFAULT_CANONICAL_SEED`` so each experiment that involves randomization
#: produces one canonical value + 5 variance-estimate values.
DEFAULT_VARIANCE_SEEDS: tuple[int, ...] = (1, 2, 3, 4, 5)

#: Top-level fields excluded from the content fingerprint used by
#: ``check_determinism``. ``ts`` is the wallclock timestamp written by
#: ``process_snapshot()`` at log-emit time.
_VOLATILE_TOP_LEVEL_FIELDS: frozenset[str] = frozenset({"ts"})

#: Fields inside the ``budget`` block that are wallclock-derived and must
#: also be excluded from the fingerprint. ``elapsed_seconds`` is measured;
#: ``fraction_used`` and ``exceeded`` are derived from elapsed_seconds vs
#: budget_seconds and so also vary across runs.
_VOLATILE_BUDGET_FIELDS: frozenset[str] = frozenset({
    "elapsed_seconds", "fraction_used", "exceeded",
})

#: Regex for extracting the generation number from a Medusa snapshot
#: filename like ``v070_gen1665781_step16657819_20260518T224644.npz``.
_SNAPSHOT_GENERATION_RE = re.compile(r"v\d+_gen(\d+)_step\d+_")


# ---------------------------------------------------------------------------
# Shared infrastructure: write-boundary, sort key, fingerprint, JSONL writer
# ---------------------------------------------------------------------------


def _validate_calibration_output_path(
    out_path: pathlib.Path,
    log_path: pathlib.Path,
) -> None:
    """Refuse output paths that resolve outside the input log's directory.

    Mirrors ``nextness_metrics._validate_metrics_output_path`` so the same
    Lane B safety contract applies to calibration outputs. Resolves both
    paths to canonical absolute form before comparing — symlink-aware.

    Raises :class:`WriteOutsideLogDirError` (reused from
    ``scripts.nextness_observer``) so the safety vocabulary stays unified
    across all three Lane B modules (observer + metrics + calibration).
    """
    log_dir_resolved = log_path.resolve().parent
    out_resolved = out_path.resolve()
    try:
        out_resolved.relative_to(log_dir_resolved)
    except ValueError as e:
        raise WriteOutsideLogDirError(
            f"refusing to write calibration output outside log_path's "
            f"directory: {out_resolved} is not inside {log_dir_resolved}"
        ) from e


def _extract_generation_from_filename(path: pathlib.Path) -> int:
    """Parse generation number out of a Medusa snapshot filename.

    Expects the canonical ``v070_gen<N>_step<M>_<ts>.npz`` format. Returns
    ``-1`` for filenames that don't match (sorted to the front so unparseable
    paths fail noisily rather than silently re-ordering).
    """
    match = _SNAPSHOT_GENERATION_RE.match(path.name)
    if match is None:
        return -1
    return int(match.group(1))


def _sort_snapshots_by_generation(
    paths: list[pathlib.Path],
) -> list[pathlib.Path]:
    """Sort snapshot paths deterministically by ``(generation, filename)``.

    Generation is the primary key (monotonic, embedded in filename); filename
    is the deterministic tiebreaker. Same priority order as the
    ``nextness_metrics`` sort key, minus ``ts`` since calibration receives
    pathlib.Path objects rather than JSONL entries.
    """
    return sorted(
        paths,
        key=lambda p: (_extract_generation_from_filename(p), p.name),
    )


def _scrub_volatile_fields(entry: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy of ``entry`` with all wallclock-derived fields removed.

    Removes both the top-level ``ts`` and the nested wallclock-derived
    fields inside the ``budget`` block (``elapsed_seconds``, ``fraction_used``,
    ``exceeded``). Leaves all other fields — including ``patches_processed``
    and ``patches_skipped_due_to_budget``, which ARE deterministic — intact.

    This is the schema-aware version of "remove volatile fields" — it knows
    about ``process_snapshot()``'s output structure. If that schema changes
    (new wallclock-derived fields added), the lists above need updating.
    """
    scrubbed = {k: v for k, v in entry.items() if k not in _VOLATILE_TOP_LEVEL_FIELDS}
    budget = scrubbed.get("budget")
    if isinstance(budget, dict):
        scrubbed["budget"] = {
            k: v for k, v in budget.items() if k not in _VOLATILE_BUDGET_FIELDS
        }
    return scrubbed


def _content_fingerprint(entry: dict[str, Any]) -> str:
    """Hash the content-bearing fields of a ``process_snapshot()`` entry.

    Returns a hex SHA256 of the canonical JSON serialization of the entry
    with all wallclock-derived fields removed (see ``_scrub_volatile_fields``).
    Two runs of ``process_snapshot()`` on identical inputs produce identical
    fingerprints despite their timing fields differing.

    Used by ``check_determinism()`` as the byte-identical-on-content test.
    """
    scrubbed = _scrub_volatile_fields(entry)
    canonical = json.dumps(scrubbed, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _write_calibration_jsonl(
    out_path: pathlib.Path,
    pair_rows: list[dict[str, Any]],
    aggregate_row: dict[str, Any],
) -> None:
    """Deterministic JSONL writer.

    Writes ``pair_rows`` in order, then ``aggregate_row`` as the final line.
    ``sort_keys=True`` makes per-row field order deterministic. No fresh
    ``generated_at`` field is added anywhere; the determinism contract from
    PR #142 / PR #143 is preserved.

    Creates parent directories if needed. ``_validate_calibration_output_path``
    should already have been called by the caller to ensure ``out_path`` lives
    inside the log directory.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in pair_rows:
            f.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        f.write(json.dumps(aggregate_row, sort_keys=True, default=str) + "\n")


def _make_per_snapshot_row(
    experiment: str,
    snapshot_path: pathlib.Path,
    generation: int,
    parameter_combination: dict[str, Any],
    metrics: dict[str, Any],
    run_metadata: dict[str, Any],
    calibration_set: str,
) -> dict[str, Any]:
    """Build a per-snapshot JSONL row matching the design doc §8 schema.

    Used by every calibration experiment as the row-emit helper so the
    output schema stays uniform across experiments.
    """
    return {
        "experiment": experiment,
        "snapshot_file": snapshot_path.name,
        "snapshot_generation": generation,
        "parameter_combination": parameter_combination,
        "metrics": metrics,
        "run_metadata": run_metadata,
        "calibration_set": calibration_set,
    }


def _make_aggregate_row(
    experiment: str,
    calibration_set: str,
    n_snapshots: int,
    extra_fields: dict[str, Any],
    falsification_status: str,
) -> dict[str, Any]:
    """Build the final aggregate JSONL row matching design doc §8 schema.

    ``falsification_status`` must be one of ``"hypothesis_supported"``,
    ``"hypothesis_falsified"``, or ``"inconclusive"`` — the three values
    specified by the design doc as mechanically-computed (not judgment-call)
    status reports.

    ``extra_fields`` lets each experiment carry its own additional aggregate
    fields (e.g. ``all_byte_identical`` for determinism;
    ``mean_cci_per_stride`` for stride sweep).
    """
    if falsification_status not in {
        "hypothesis_supported",
        "hypothesis_falsified",
        "inconclusive",
    }:
        raise ValueError(
            f"falsification_status must be one of "
            f"'hypothesis_supported', 'hypothesis_falsified', 'inconclusive'; "
            f"got {falsification_status!r}"
        )
    aggregate: dict[str, Any] = {
        "experiment": experiment,
        "summary_type": "run_aggregate",
        "calibration_set": calibration_set,
        "n_snapshots": n_snapshots,
        "falsification_status": falsification_status,
    }
    aggregate.update(extra_fields)
    return aggregate


def _extract_metrics_subset(entry: dict[str, Any]) -> dict[str, Any]:
    """Pull the per-snapshot metrics out of a ``process_snapshot()`` entry.

    Returns a small dict containing the six per-snapshot metric fields
    (the five PR #142 fields plus the vocabulary occupancy preserved from
    PR #138). Used to populate the ``metrics`` block of a per-snapshot row.
    """
    return {
        "vocabulary_occupancy": entry.get("vocabulary_occupancy"),
        "shannon_entropy_bits": entry.get("shannon_entropy_bits"),
        "entropy_normalized": entry.get("entropy_normalized"),
        "void_compute_balance": entry.get("void_compute_balance"),
        "boundary_rate": entry.get("boundary_rate"),
        "token_counts": entry.get("token_counts"),
    }


# ---------------------------------------------------------------------------
# Experiment 3.7 — check_determinism (Jack's #1 in implementation order)
# ---------------------------------------------------------------------------


def check_determinism(
    snapshots: list[pathlib.Path],
    out_path: pathlib.Path,
    log_path: pathlib.Path,
    calibration_set: str,
    config: ObserverConfig,
    repeats: int = 2,
) -> dict[str, Any]:
    """Run ``process_snapshot()`` ``repeats`` times per snapshot; verify
    that the *content* of each run's output JSONL entry is byte-identical
    across repeats.

    "Content" excludes the volatile ``ts`` field (the wallclock timestamp
    each ``process_snapshot()`` call writes), since identical inputs
    inevitably produce different timestamps. The fingerprint covers every
    other field — token counts, all per-snapshot metrics, lattice shape,
    sampling parameters, budget block, etc.

    This is **the sanity floor** for the rest of the calibration suite
    (per Jack's PR #143 implementation order): if ``process_snapshot()``
    isn't deterministic, every downstream experiment's results are suspect.

    Per design doc §3.7: runs on **both** calibration sets (caller specifies
    which set this invocation covers via the ``calibration_set`` parameter
    — typically called twice, once for "short" and once for "long").

    Falsification status:
        - ``"hypothesis_supported"`` — all repeats produced byte-identical
          content for every snapshot. Determinism holds.
        - ``"hypothesis_falsified"`` — at least one snapshot's repeats
          produced different content fingerprints. Determinism violated;
          a blocker for the rest of the calibration suite.

    Output JSONL has one row per (snapshot × repeat) plus the aggregate row.

    Args:
        snapshots: list of sandboxed snapshot ``.npz`` paths. Sorted
            deterministically before iteration.
        out_path: where to write the ``calibration_determinism.jsonl``
            output. Must resolve under ``log_path.parent`` per the Lane B
            safety contract.
        log_path: the canonical ``nextness_runs.jsonl`` log path. Used both
            as the write-boundary anchor and as the destination for
            ``process_snapshot()``'s side-effect log writes.
        calibration_set: ``"short"`` or ``"long"`` — recorded on every row
            so downstream analysis can filter.
        config: the ``ObserverConfig`` to use for every call to
            ``process_snapshot()``. All ``repeats`` use this same config
            (otherwise determinism testing would be meaningless).
        repeats: how many times to run ``process_snapshot()`` per snapshot.
            Minimum 2 (otherwise the byte-identical comparison is vacuous).
            Defaults to 2 since determinism either holds or it doesn't —
            larger ``repeats`` just spend more compute confirming the same
            thing.

    Returns the aggregate dict for callers that want to inspect it without
    re-reading the output file.

    Raises:
        :class:`WriteOutsideLogDirError` if ``out_path`` is outside the
            log directory.
        ``ValueError`` if ``calibration_set`` isn't ``"short"`` or
            ``"long"``, or ``repeats`` < 2.
    """
    if calibration_set not in {"short", "long"}:
        raise ValueError(
            f"calibration_set must be 'short' or 'long', got "
            f"{calibration_set!r}"
        )
    if repeats < 2:
        raise ValueError(
            f"repeats must be >= 2 (byte-identical comparison needs at "
            f"least two runs), got {repeats}"
        )

    out_path = pathlib.Path(out_path)
    log_path = pathlib.Path(log_path)
    _validate_calibration_output_path(out_path, log_path)

    sorted_snapshots = _sort_snapshots_by_generation(list(snapshots))

    per_snapshot_rows: list[dict[str, Any]] = []
    all_byte_identical = True
    n_snapshots_with_drift = 0

    for snap in sorted_snapshots:
        generation = _extract_generation_from_filename(snap)
        # Run process_snapshot ``repeats`` times; capture each return value.
        # Note: process_snapshot() also writes one JSONL line per call into
        # log_path's directory as a side effect. That's intended — the log
        # accumulates run history. The determinism check operates on the
        # returned dicts, not on the log file.
        run_entries = []
        for _ in range(repeats):
            entry = process_snapshot(snap, config, medusa_is_live=False)
            run_entries.append(entry)

        # Fingerprint each run's content (ts excluded).
        fingerprints = [_content_fingerprint(e) for e in run_entries]
        snapshot_byte_identical = len(set(fingerprints)) == 1
        if not snapshot_byte_identical:
            all_byte_identical = False
            n_snapshots_with_drift += 1

        # Emit one row per (snapshot × repeat_index). Each row carries the
        # fingerprint and a flag for whether that snapshot's repeats matched.
        for repeat_idx, (entry, fp) in enumerate(zip(run_entries, fingerprints)):
            per_snapshot_rows.append(_make_per_snapshot_row(
                experiment="determinism",
                snapshot_path=snap,
                generation=generation,
                parameter_combination={
                    "repeat_index": repeat_idx,
                    "total_repeats": repeats,
                },
                metrics=_extract_metrics_subset(entry),
                run_metadata={
                    "content_fingerprint_sha256_16": fp[:16],
                    "snapshot_byte_identical_across_repeats": snapshot_byte_identical,
                    "elapsed_seconds": entry.get("budget", {}).get(
                        "elapsed_seconds"
                    ),
                    "patches_processed": entry.get("budget", {}).get(
                        "patches_processed"
                    ),
                },
                calibration_set=calibration_set,
            ))

    aggregate = _make_aggregate_row(
        experiment="determinism",
        calibration_set=calibration_set,
        n_snapshots=len(sorted_snapshots),
        extra_fields={
            "repeats_per_snapshot": repeats,
            "all_byte_identical": all_byte_identical,
            "n_snapshots_with_drift": n_snapshots_with_drift,
        },
        falsification_status=(
            "hypothesis_supported" if all_byte_identical
            else "hypothesis_falsified"
        ),
    )

    _write_calibration_jsonl(out_path, per_snapshot_rows, aggregate)
    return aggregate


# ---------------------------------------------------------------------------
# Experiment 3.8 — shuffle_test (3-mode null model, Jack's #3 in order)
# ---------------------------------------------------------------------------


#: The three shuffle modes per design doc §3.8. Each snapshot is processed
#: in all three modes per call so the three-way comparison is built-in.
SHUFFLE_MODES: tuple[str, ...] = (
    "unshuffled",
    "lattice_only_shuffle",
    "joint_lattice_memory_shuffle",
)

#: Threshold below which we call all three modes "similar" (signal is in
#: the classifier). Per design doc §3.8 falsification criterion.
_SHUFFLE_CLASSIFIER_ARTEFACT_THRESHOLD: float = 0.05

#: Threshold above which the joint shuffle is said to "collapse" the
#: distribution (signal is in the lattice geometry / memory_grid structure).
#: Per design doc §3.8 falsification criterion.
_SHUFFLE_HYPOTHESIS_SUPPORT_THRESHOLD: float = 0.10


def _shuffled_snapshot_arrays(
    lattice: np.ndarray,
    memory: np.ndarray,
    mode: str,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(shuffled_lattice, shuffled_memory)`` for the requested mode.

    Per design doc §3.8:
        - ``unshuffled``: arrays returned as-is. Reference baseline.
        - ``lattice_only_shuffle``: lattice cells randomly permuted;
          memory_grid untouched. Tests whether lattice spatial structure
          carries the signal.
        - ``joint_lattice_memory_shuffle``: the **same permutation** is
          applied to both arrays. Lattice cell at original position p moves
          to perm[p]; memory_grid voxels at position p (across all channels)
          also move to perm[p]. Destroys all spatial correlations while
          preserving per-cell lattice/memory pairing.

    The shape contract: ``lattice.shape == (X, Y, Z)``; ``memory.shape ==
    (channels, X, Y, Z)``. Both arrays are NOT mutated; new arrays are
    returned.

    Raises ``ValueError`` for any mode outside :data:`SHUFFLE_MODES`.
    """
    if mode == "unshuffled":
        return lattice, memory
    if mode not in SHUFFLE_MODES:
        raise ValueError(
            f"unknown shuffle mode {mode!r}; expected one of {SHUFFLE_MODES}"
        )

    spatial_size = lattice.size  # X * Y * Z
    perm = rng.permutation(spatial_size)

    flat_lattice = lattice.flatten()
    shuffled_lattice = flat_lattice[perm].reshape(lattice.shape)

    if mode == "lattice_only_shuffle":
        return shuffled_lattice, memory

    # joint_lattice_memory_shuffle: same permutation applied to memory_grid
    n_channels = memory.shape[0]
    flat_memory = memory.reshape(n_channels, spatial_size)
    shuffled_memory = flat_memory[:, perm].reshape(memory.shape)
    return shuffled_lattice, shuffled_memory


def _write_temp_snapshot(
    lattice: np.ndarray,
    memory: np.ndarray,
    generation: int,
    tmp_dir: pathlib.Path,
    filename: str,
) -> pathlib.Path:
    """Write arrays to a temporary ``.npz`` Medusa-format snapshot.

    The temp file is intended to be consumed by ``process_snapshot()`` and
    then deleted by the caller. Format mirrors the real Medusa snapshot
    schema (lattice, memory_grid, generation keys).
    """
    out = tmp_dir / filename
    np.savez(
        str(out),
        lattice=lattice,
        memory_grid=memory,
        generation=np.array(generation),
        best_fitness=np.array(0.0),
    )
    return out


def _cci_from_entry(entry: dict[str, Any]) -> float:
    """Compute CCI from a ``process_snapshot()`` entry's per-snapshot fields."""
    return _cci(
        balance=float(entry.get("void_compute_balance", 0.0)),
        boundary=float(entry.get("boundary_rate", 0.0)),
        entropy_norm=float(entry.get("entropy_normalized", 0.0)),
    )


def _interpret_signal_location(
    mean_cci_unshuffled: float,
    mean_cci_lattice_only: float,
    mean_cci_joint: float,
) -> str:
    """Interpret the three mean-CCI values per design doc §3.8 outcome table.

    Returns one of:
        - ``"classifier_artefact"``: all three modes give similar CCIs.
          Spatial structure isn't load-bearing; pattern lives in the
          classifier rules.
        - ``"lattice_geometry"``: lattice_only and joint give similar
          CCIs, both differ meaningfully from unshuffled. Shuffling the
          lattice alone was sufficient to destroy the signal; shuffling
          memory in addition added nothing. Lattice carries the signal.
        - ``"memory_grid_structure"``: lattice_only ≈ unshuffled but
          joint differs from both. Shuffling lattice alone didn't matter,
          but adding the memory shuffle broke things. Memory carries
          the signal.
        - ``"both_arrays_contribute"``: each shuffle individually
          produces a meaningful drop, AND joint produces additional drop
          beyond lattice_only. Both arrays carry independent signal.
          Strongest evidence for AURA's "real geometric structure" hypothesis.
        - ``"ambiguous"``: pattern doesn't cleanly match any of the above.

    Rule precedence matters: ``lattice_geometry`` requires
    ``lattice_only ≈ joint`` (memory shuffle adds nothing), so we test
    that first. ``both_arrays_contribute`` requires
    ``lattice_only ≠ joint`` (memory shuffle adds further drop).
    """
    d_u_l = abs(mean_cci_unshuffled - mean_cci_lattice_only)
    d_u_j = abs(mean_cci_unshuffled - mean_cci_joint)
    d_l_j = abs(mean_cci_lattice_only - mean_cci_joint)
    eps = _SHUFFLE_CLASSIFIER_ARTEFACT_THRESHOLD

    # Rule 1: all three close → classifier artefact
    if max(d_u_l, d_u_j, d_l_j) < eps:
        return "classifier_artefact"

    # Rule 2: lattice carries signal alone — unshuffled differs from both
    # shuffled modes, but the two shuffled modes are close to each other
    # (memory shuffle adds nothing on top of the lattice shuffle)
    if d_u_l >= eps and d_u_j >= eps and d_l_j < eps:
        return "lattice_geometry"

    # Rule 3: memory carries signal alone — lattice_only ≈ unshuffled
    # (lattice shuffle alone didn't affect the result), but joint differs
    # (adding the memory shuffle is what broke things)
    if d_u_l < eps and d_u_j >= eps and d_l_j >= eps:
        return "memory_grid_structure"

    # Rule 4: both arrays contribute — lattice shuffle alone produces a
    # meaningful drop (d_u_l >= eps), AND joint produces additional drop
    # beyond that (d_l_j >= eps). Each array's spatial structure carries
    # independent signal.
    if d_u_l >= eps and d_l_j >= eps:
        return "both_arrays_contribute"

    return "ambiguous"


def _shuffle_falsification_status(
    mean_cci_unshuffled: float,
    mean_cci_joint: float,
    max_pairwise_diff: float,
) -> str:
    """Mechanical falsification status per design doc §3.8 criteria.

    - ``"hypothesis_falsified"`` if all three modes are within
      :data:`_SHUFFLE_CLASSIFIER_ARTEFACT_THRESHOLD` of each other.
    - ``"hypothesis_supported"`` if the joint shuffle drops CCI by more
      than :data:`_SHUFFLE_HYPOTHESIS_SUPPORT_THRESHOLD` absolute.
    - ``"inconclusive"`` otherwise.
    """
    if max_pairwise_diff < _SHUFFLE_CLASSIFIER_ARTEFACT_THRESHOLD:
        return "hypothesis_falsified"
    if abs(mean_cci_unshuffled - mean_cci_joint) > _SHUFFLE_HYPOTHESIS_SUPPORT_THRESHOLD:
        return "hypothesis_supported"
    return "inconclusive"


def shuffle_test(
    snapshots: list[pathlib.Path],
    out_path: pathlib.Path,
    log_path: pathlib.Path,
    calibration_set: str,
    config: ObserverConfig,
    modes: tuple[str, ...] | None = None,
    seeds: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    """Null-model shuffle test with three modes (per design doc §3.8).

    For each snapshot, runs ``process_snapshot()`` under each requested
    shuffle mode and seed combination, then aggregates the resulting CCI
    distributions to determine whether the equilibrium signal lives in
    the lattice geometry, the memory_grid spatial structure, or the
    classifier behaviour itself.

    Per Jack's PR #143 revision: this is the carpenter's level on the
    floor *plus* a stud finder — the three-way comparison pinpoints which
    array's spatial structure carries the signal, not just whether *any*
    spatial structure does.

    Args:
        snapshots: list of sandboxed ``.npz`` paths to test. Sorted
            deterministically before iteration.
        out_path: output JSONL path. Must resolve under ``log_path.parent``.
        log_path: anchor for the write-boundary safety check; also where
            ``process_snapshot()`` writes its log entries as a side effect.
        calibration_set: ``"short"`` or ``"long"``; recorded on every row.
        config: ``ObserverConfig`` used for every ``process_snapshot()`` call.
        modes: which shuffle modes to run. Defaults to all three. ``"unshuffled"``
            uses only one seed (the canonical one) since it doesn't involve
            randomization; shuffled modes use the full seed list.
        seeds: which RNG seeds to use for shuffled modes. Defaults to
            ``(DEFAULT_CANONICAL_SEED, *DEFAULT_VARIANCE_SEEDS)`` per
            design doc §12 Q6 (one canonical + 5 variance estimates).

    Returns the aggregate dict for callers that want to inspect it without
    re-reading the output file.

    Raises:
        :class:`WriteOutsideLogDirError` if ``out_path`` is outside the
            log directory.
        ``ValueError`` for unknown modes or invalid calibration_set.
    """
    if calibration_set not in {"short", "long"}:
        raise ValueError(
            f"calibration_set must be 'short' or 'long', got {calibration_set!r}"
        )
    if modes is None:
        modes = SHUFFLE_MODES
    for mode in modes:
        if mode not in SHUFFLE_MODES:
            raise ValueError(
                f"unknown shuffle mode {mode!r}; expected one of {SHUFFLE_MODES}"
            )
    if seeds is None:
        seeds = (DEFAULT_CANONICAL_SEED,) + DEFAULT_VARIANCE_SEEDS

    out_path = pathlib.Path(out_path)
    log_path = pathlib.Path(log_path)
    _validate_calibration_output_path(out_path, log_path)

    sorted_snapshots = _sort_snapshots_by_generation(list(snapshots))

    per_snapshot_rows: list[dict[str, Any]] = []
    # Collect per-mode CCI values across all (snapshot × seed) runs for the
    # aggregate's mean computation.
    cci_by_mode: dict[str, list[float]] = {m: [] for m in modes}

    for snap in sorted_snapshots:
        generation = _extract_generation_from_filename(snap)
        # Load snapshot arrays once per snapshot; shuffle in-memory per mode.
        with np.load(str(snap), allow_pickle=False) as data:
            lattice = data["lattice"]
            memory = data["memory_grid"]
            snap_generation = int(data["generation"])

        for mode in modes:
            # unshuffled mode uses only one seed (no randomization involved);
            # shuffled modes use the full seed list per design doc §12 Q6.
            mode_seeds = (seeds[0],) if mode == "unshuffled" else seeds

            for seed in mode_seeds:
                rng = np.random.default_rng(seed)
                shuffled_lattice, shuffled_memory = _shuffled_snapshot_arrays(
                    lattice, memory, mode, rng,
                )

                # Write to a uniquely-named temp file inside a per-snapshot
                # tempdir so process_snapshot can load it. Cleanup is
                # automatic via the context manager.
                with tempfile.TemporaryDirectory(prefix="nextness_shuffle_") as tmp:
                    tmp_dir = pathlib.Path(tmp)
                    temp_snap = _write_temp_snapshot(
                        shuffled_lattice, shuffled_memory, snap_generation,
                        tmp_dir,
                        f"v070_gen{snap_generation}_step{snap_generation*10}_shuffle.npz",
                    )
                    entry = process_snapshot(temp_snap, config, medusa_is_live=False)

                cci_value = _cci_from_entry(entry)
                cci_by_mode[mode].append(cci_value)

                per_snapshot_rows.append(_make_per_snapshot_row(
                    experiment="shuffle",
                    snapshot_path=snap,  # original snapshot, not the temp file
                    generation=generation,
                    parameter_combination={
                        "shuffle_mode": mode,
                        "shuffle_seed": int(seed),
                    },
                    metrics={
                        **_extract_metrics_subset(entry),
                        "cci": cci_value,
                    },
                    run_metadata={
                        "elapsed_seconds": entry.get("budget", {}).get(
                            "elapsed_seconds"
                        ),
                        "patches_processed": entry.get("budget", {}).get(
                            "patches_processed"
                        ),
                    },
                    calibration_set=calibration_set,
                ))

    # Aggregate: mean CCI per mode + pairwise differences + interpretation
    mean_cci_per_mode = {
        m: (sum(vs) / len(vs) if vs else 0.0)
        for m, vs in cci_by_mode.items()
    }
    std_cci_per_mode = {
        m: (
            math.sqrt(sum((v - mean_cci_per_mode[m]) ** 2 for v in vs) / len(vs))
            if len(vs) > 1 else 0.0
        )
        for m, vs in cci_by_mode.items()
    }

    # Pairwise diffs (only meaningful when all three modes are present)
    extra_fields: dict[str, Any] = {
        "mean_cci_per_mode": mean_cci_per_mode,
        "std_cci_per_mode": std_cci_per_mode,
        "n_runs_per_mode": {m: len(vs) for m, vs in cci_by_mode.items()},
        "modes_run": list(modes),
        "seeds_used": list(seeds),
    }

    has_all_three_modes = all(m in cci_by_mode for m in SHUFFLE_MODES) and all(
        len(cci_by_mode[m]) > 0 for m in SHUFFLE_MODES
    )

    if has_all_three_modes:
        mean_u = mean_cci_per_mode["unshuffled"]
        mean_l = mean_cci_per_mode["lattice_only_shuffle"]
        mean_j = mean_cci_per_mode["joint_lattice_memory_shuffle"]
        diff_u_l = abs(mean_u - mean_l)
        diff_u_j = abs(mean_u - mean_j)
        diff_l_j = abs(mean_l - mean_j)
        max_pairwise = max(diff_u_l, diff_u_j, diff_l_j)
        extra_fields["pairwise_cci_diffs"] = {
            "unshuffled_vs_lattice_only": diff_u_l,
            "unshuffled_vs_joint": diff_u_j,
            "lattice_only_vs_joint": diff_l_j,
            "max_pairwise": max_pairwise,
        }
        extra_fields["signal_location_interpretation"] = _interpret_signal_location(
            mean_u, mean_l, mean_j,
        )
        falsification_status = _shuffle_falsification_status(
            mean_u, mean_j, max_pairwise,
        )
    else:
        # Partial run (subset of modes): can't compute the three-way
        # comparison, so we declare inconclusive rather than guess.
        extra_fields["signal_location_interpretation"] = "incomplete_modes"
        falsification_status = "inconclusive"

    aggregate = _make_aggregate_row(
        experiment="shuffle",
        calibration_set=calibration_set,
        n_snapshots=len(sorted_snapshots),
        extra_fields=extra_fields,
        falsification_status=falsification_status,
    )

    _write_calibration_jsonl(out_path, per_snapshot_rows, aggregate)
    return aggregate


# ---------------------------------------------------------------------------
# Experiment 3.6 — verify_memory_channels (Jack's #2 in implementation order;
# runtime regression-fence complementing PR #145's static layout check)
# ---------------------------------------------------------------------------


#: Number of memory channels the engine writes per snapshot, per
#: ``scripts/continuous_evolution_ca.py:646`` (``MEMORY_CHANNELS = 8``).
#: A future engine change that adds or removes channels should be caught
#: by this runtime check.
EXPECTED_MEMORY_CHANNELS: int = 8

#: Expected dtype of the engine's ``memory_grid`` array. Engine writes
#: float32 throughout (see ``init_memory_grid`` at line 652). A dtype
#: change would be a structural drift worth catching.
EXPECTED_MEMORY_DTYPE: str = "float32"

#: Sparsity threshold for the per-channel signature. Voxels with
#: ``abs(value) <= SPARSITY_EPSILON`` are counted as "near-zero" for
#: the sparsity fraction. Chosen conservative — does not depend on any
#: per-channel semantic meaning.
SPARSITY_EPSILON: float = 1e-6


def _per_channel_signature(channel_array: "np.ndarray") -> dict[str, Any]:
    """Compute a small, robust per-channel statistical signature.

    Returns a dict with min/max/mean/std/sparsity, plus a ``finite``
    flag indicating whether every voxel in the channel is a finite
    real number (no ``NaN``, no ``Inf``).

    The fields are designed to be diagnostic — analysts can spot at a
    glance whether a channel looks healthy (varying values, no NaNs,
    sensible mean/std) or pathological (all zero, dominated by NaN,
    constant value across the lattice). The verification status logic
    in :func:`verify_memory_channels` uses only the structural checks
    (shape, dtype, finiteness); the signature numbers are emitted for
    human and downstream-tool inspection.
    """
    flat = channel_array.flatten()
    finite_mask = np.isfinite(flat)
    all_finite = bool(finite_mask.all())
    if all_finite:
        n_near_zero = int(np.sum(np.abs(flat) <= SPARSITY_EPSILON))
        sparsity = n_near_zero / float(flat.size) if flat.size > 0 else 0.0
        return {
            "min": float(flat.min()),
            "max": float(flat.max()),
            "mean": float(flat.mean()),
            "std": float(flat.std()),
            "sparsity": sparsity,
            "n_voxels": int(flat.size),
            "finite": True,
            "n_non_finite": 0,
        }
    # Partial-finite case: report what we can from the finite subset
    # plus an explicit count of non-finite voxels.
    n_non_finite = int((~finite_mask).sum())
    finite_values = flat[finite_mask]
    if finite_values.size > 0:
        signature = {
            "min": float(finite_values.min()),
            "max": float(finite_values.max()),
            "mean": float(finite_values.mean()),
            "std": float(finite_values.std()),
            "sparsity": float(
                (np.abs(finite_values) <= SPARSITY_EPSILON).sum()
            ) / float(flat.size),
            "n_voxels": int(flat.size),
            "finite": False,
            "n_non_finite": n_non_finite,
        }
    else:
        # Every voxel is non-finite — return null stats but a clear status
        signature = {
            "min": None,
            "max": None,
            "mean": None,
            "std": None,
            "sparsity": None,
            "n_voxels": int(flat.size),
            "finite": False,
            "n_non_finite": n_non_finite,
        }
    return signature


def _verify_snapshot_memory_grid(
    snapshot_path: pathlib.Path,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Load a snapshot's memory_grid and verify shape/dtype/finiteness.

    Returns ``(channel_signatures, drift_reasons)``:
        - ``channel_signatures``: dict mapping channel name → per-channel
          signature dict (see :func:`_per_channel_signature`). Only
          populated for channels that exist; uses the canonical
          ``MEMORY_CHANNEL_LAYOUT`` channel names from
          :mod:`scripts.nextness_observer`.
        - ``drift_reasons``: list of human-readable strings describing
          any structural drift detected. Empty list = no drift, snapshot
          verifies clean.

    Per Jack's Chapter 3 guardrails: we do NOT touch the engine, and
    we do NOT cross-reference against the Phase 14e acoustic map (that's
    deferred). The check is strictly: does the snapshot's
    ``memory_grid`` array match the structural invariants we expect
    given PR #145's corrected layout?
    """
    # Import lazily so the module's top-level import graph doesn't
    # depend on the observer at all for non-channel-verification
    # code paths.
    from scripts.nextness_observer import MEMORY_CHANNEL_LAYOUT

    drift_reasons: list[str] = []

    try:
        with np.load(str(snapshot_path), allow_pickle=False) as data:
            if "memory_grid" not in data.files:
                drift_reasons.append(
                    f"snapshot missing 'memory_grid' key (found: "
                    f"{sorted(data.files)})"
                )
                return {}, drift_reasons
            memory = data["memory_grid"]
            # Materialize the array (np.load returns a lazy view)
            memory = np.asarray(memory)
    except Exception as e:
        drift_reasons.append(f"snapshot load failed: {type(e).__name__}: {e}")
        return {}, drift_reasons

    # Structural check 1: number of channels
    if memory.ndim != 4:
        drift_reasons.append(
            f"memory_grid has {memory.ndim} dimensions; expected 4 "
            f"(channels, x, y, z)"
        )
    elif memory.shape[0] != EXPECTED_MEMORY_CHANNELS:
        drift_reasons.append(
            f"memory_grid has {memory.shape[0]} channels; "
            f"expected {EXPECTED_MEMORY_CHANNELS} per "
            f"continuous_evolution_ca.py MEMORY_CHANNELS constant"
        )

    # Structural check 2: dtype
    if str(memory.dtype) != EXPECTED_MEMORY_DTYPE:
        drift_reasons.append(
            f"memory_grid dtype is {memory.dtype}; expected "
            f"{EXPECTED_MEMORY_DTYPE} per engine init_memory_grid"
        )

    # Per-channel signatures (computed for as many channels as exist,
    # even if the count is wrong, so analysts can see what is in the
    # file). Map channel index to name where possible.
    index_to_name: dict[int, str] = {
        idx: name for name, idx in MEMORY_CHANNEL_LAYOUT.items()
    }
    channel_signatures: dict[str, dict[str, Any]] = {}
    if memory.ndim == 4:
        for ch_idx in range(memory.shape[0]):
            name = index_to_name.get(
                ch_idx,
                f"channel_{ch_idx}_unknown",  # extra channels beyond expected layout
            )
            signature = _per_channel_signature(memory[ch_idx])
            channel_signatures[name] = signature
            if not signature["finite"]:
                drift_reasons.append(
                    f"channel {ch_idx} ({name}) contains "
                    f"{signature['n_non_finite']} non-finite voxel(s) "
                    f"(NaN or Inf)"
                )

    return channel_signatures, drift_reasons


def verify_memory_channels(
    snapshots: list[pathlib.Path],
    out_path: pathlib.Path,
    log_path: pathlib.Path,
    calibration_set: str,
) -> dict[str, Any]:
    """Runtime per-snapshot regression-fence for the memory-channel layout.

    Complements the static layout check from PR #145 (`tests/
    test_nextness_observer.py::test_layout_matches_engine_documented_
    8_channel_map`). The static check confirms that the observer's
    constants match what the engine code documents *at test time*;
    this runtime check confirms that *every actual snapshot* matches
    the same invariants. Catches drift that wouldn't show up in a unit
    test — e.g., the engine added a 9th channel mid-run, or a snapshot
    became corrupted, or a dtype changed.

    Per issue #144 / PR #145: the layout that was wrong has been
    corrected and locked in. This experiment is the live runtime
    sentinel ensuring no future drift slips past.

    Per Jack's Chapter 3 guardrails (PR #146 follow-up direction):
        - Lane B only. No engine touch.
        - No threshold / stride / cascade / temporal / patch-radius
          sweeps. No CLI.
        - No vocabulary redesign. No reopening of the Karuna naming.
        - Uses the PR #145-corrected layout as source of truth.
        - Same write-boundary safety contract.
        - Same deterministic JSONL style.

    For each snapshot:
        - Load memory_grid via ``np.load(..., allow_pickle=False)``.
        - Verify shape == (8, X, Y, Z) per engine's MEMORY_CHANNELS = 8.
        - Verify dtype == float32 per engine's init_memory_grid.
        - Per-channel signature: min, max, mean, std, sparsity,
          finite-flag, non-finite-count.
        - Aggregate any drift reasons.

    Falsification status:
        - ``"hypothesis_supported"`` — every snapshot verifies cleanly
          (shape + dtype + finiteness). The corrected layout is holding.
        - ``"hypothesis_falsified"`` — at least one snapshot fails
          verification. Blocking for downstream calibration runs.
        - ``"inconclusive"`` — only emitted for an empty snapshot list.

    Output JSONL: one row per snapshot containing the per-channel
    signatures + drift reasons; final aggregate row summarising
    overall verification status across the run.

    Args:
        snapshots: list of sandboxed ``.npz`` paths.
        out_path: where to write the verification JSONL. Must resolve
            under ``log_path.parent`` per the Lane B safety contract.
        log_path: anchor for the write-boundary check.
        calibration_set: ``"short"`` or ``"long"``; recorded on every row.

    Returns the aggregate dict for callers that want to inspect it
    without re-reading the output file.

    Raises:
        :class:`WriteOutsideLogDirError` if ``out_path`` is outside the
            log directory.
        ``ValueError`` if ``calibration_set`` isn't ``"short"`` or
            ``"long"``.

    Note: unlike :func:`check_determinism` and :func:`shuffle_test`,
    this function does NOT take an ``ObserverConfig`` because it does
    not call ``process_snapshot()``. It reads the raw ``.npz`` files
    directly to inspect structural invariants, deliberately bypassing
    the observer pipeline so it can catch drift that would otherwise
    silently propagate through it.
    """
    if calibration_set not in {"short", "long"}:
        raise ValueError(
            f"calibration_set must be 'short' or 'long', got "
            f"{calibration_set!r}"
        )

    out_path = pathlib.Path(out_path)
    log_path = pathlib.Path(log_path)
    _validate_calibration_output_path(out_path, log_path)

    sorted_snapshots = _sort_snapshots_by_generation(list(snapshots))

    per_snapshot_rows: list[dict[str, Any]] = []
    n_snapshots_verified = 0
    n_snapshots_with_drift = 0
    all_drift_reasons: list[str] = []

    for snap in sorted_snapshots:
        generation = _extract_generation_from_filename(snap)
        signatures, drift_reasons = _verify_snapshot_memory_grid(snap)

        snapshot_verified = (len(drift_reasons) == 0)
        if snapshot_verified:
            n_snapshots_verified += 1
        else:
            n_snapshots_with_drift += 1
            for reason in drift_reasons:
                all_drift_reasons.append(f"{snap.name}: {reason}")

        per_snapshot_rows.append(_make_per_snapshot_row(
            experiment="verify_memory_channels",
            snapshot_path=snap,
            generation=generation,
            parameter_combination={
                "expected_channels": EXPECTED_MEMORY_CHANNELS,
                "expected_dtype": EXPECTED_MEMORY_DTYPE,
            },
            metrics={
                "channel_signatures": signatures,
                "snapshot_verified": snapshot_verified,
                "n_drift_reasons": len(drift_reasons),
            },
            run_metadata={
                "drift_reasons": drift_reasons,
            },
            calibration_set=calibration_set,
        ))

    n_snapshots = len(sorted_snapshots)
    if n_snapshots == 0:
        falsification_status = "inconclusive"
    elif n_snapshots_with_drift == 0:
        falsification_status = "hypothesis_supported"
    else:
        falsification_status = "hypothesis_falsified"

    aggregate = _make_aggregate_row(
        experiment="verify_memory_channels",
        calibration_set=calibration_set,
        n_snapshots=n_snapshots,
        extra_fields={
            "expected_channels": EXPECTED_MEMORY_CHANNELS,
            "expected_dtype": EXPECTED_MEMORY_DTYPE,
            "n_snapshots_verified": n_snapshots_verified,
            "n_snapshots_with_drift": n_snapshots_with_drift,
            # First 10 drift reasons across the run (full list is in the
            # per-snapshot rows; this is a quick-glance aggregate).
            "first_drift_reasons": all_drift_reasons[:10],
        },
        falsification_status=falsification_status,
    )

    _write_calibration_jsonl(out_path, per_snapshot_rows, aggregate)
    return aggregate


__all__ = [
    "DEFAULT_CANONICAL_SEED",
    "DEFAULT_VARIANCE_SEEDS",
    "EXPECTED_MEMORY_CHANNELS",
    "EXPECTED_MEMORY_DTYPE",
    "SHUFFLE_MODES",
    "SPARSITY_EPSILON",
    "check_determinism",
    "shuffle_test",
    "verify_memory_channels",
]
