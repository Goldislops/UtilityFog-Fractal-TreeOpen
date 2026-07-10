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
from scripts.nextness_metrics import (
    cci as _cci,
    js_divergence as _js_divergence,
)


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


def _validate_config_log_directory(
    config: ObserverConfig,
    log_path: pathlib.Path,
) -> None:
    """Refuse configs whose ``log_directory`` diverges from ``log_path.parent``.

    Closes the gap flagged in Jack's PR #149 audit: calibration functions
    validate ``out_path`` against ``log_path.parent`` via
    :func:`_validate_calibration_output_path`, but functions that call
    ``process_snapshot()`` also write through ``config.log_directory``
    (one JSONL line per call into ``<log_directory>/nextness_runs.jsonl``).
    If ``config.log_directory`` and ``log_path.parent`` ever diverge, the
    calibration function may write outside the claimed boundary even though
    ``out_path`` is validated.

    This guard requires::

        Path(config.log_directory).resolve() == log_path.parent.resolve()

    so the side-effect log writes land in the same directory the calibration
    function's safety contract anchors on. Symlink-aware via ``resolve()``;
    matches the canonical-form comparison style used elsewhere.

    Crucially, this raises BEFORE any ``process_snapshot()`` call, so a
    mismatched config can never create or write into a stray log directory
    (``process_snapshot`` calls ``_ensure_log_dir`` which would create the
    misconfigured directory on first call).

    Raises :class:`WriteOutsideLogDirError` so the safety vocabulary stays
    unified with the existing ``out_path`` boundary check.
    """
    config_log_resolved = pathlib.Path(config.log_directory).resolve()
    log_path_parent_resolved = log_path.resolve().parent
    if config_log_resolved != log_path_parent_resolved:
        raise WriteOutsideLogDirError(
            f"refusing to run calibration with config.log_directory "
            f"diverging from log_path.parent: "
            f"config.log_directory={config_log_resolved} "
            f"vs log_path.parent={log_path_parent_resolved}. "
            f"process_snapshot() writes side-effect log entries to "
            f"config.log_directory; the two must match for the Lane B "
            f"write-boundary contract to hold."
        )


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
    _validate_config_log_directory(config, log_path)

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
                    # patches_processed is deterministic; elapsed_seconds
                    # is wallclock-derived and would break byte-identical
                    # re-run. Timing is available in process_snapshot's
                    # own log entry, joinable on snapshot_file.
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
    _validate_config_log_directory(config, log_path)

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
                        # patches_processed is deterministic; elapsed_seconds
                        # is wallclock-derived and would break byte-identical
                        # re-run. Timing is available in process_snapshot's
                        # own log entry, joinable on snapshot_file.
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


# ---------------------------------------------------------------------------
# Experiment 3.1 — sweep_stride (spatial sampling sweep)
# ---------------------------------------------------------------------------


#: Default spatial strides to sweep per design doc §3.1. Stride 8 is the
#: PR #142 baseline (kept as canonical reference); stride 4 quadruples
#: patch count to test sampling-resolution sensitivity; stride 16 cuts
#: patch count eighth-fold as a confirmation that coarsening doesn't
#: hide structure either.
DEFAULT_STRIDES: tuple[int, ...] = (4, 8, 16)

#: Canonical reference stride against which the others are compared in
#: the sweep aggregate. Matches PR #142's baseline so the per-stride
#: differences map back to "what we previously thought."
CANONICAL_STRIDE: int = 8

#: Falsification threshold per design doc §3.1: if stride 4 produces
#: ``|Δvocabulary_occupancy| > 0.15`` versus stride 8, the saturation
#: result is at least partly a sampling artefact.
_STRIDE_SAMPLING_ARTEFACT_THRESHOLD: float = 0.15

#: Tolerance for "metrics are stable across strides" — if all pairwise
#: voc_occ diffs across strides are below this, the equilibrium signal
#: is judged stride-invariant (AURA's hypothesis supported on the
#: sampling axis).
_STRIDE_STABILITY_THRESHOLD: float = 0.05


def _clone_config_with_stride(
    base_config: ObserverConfig,
    stride: int,
) -> ObserverConfig:
    """Return a copy of ``base_config`` with ``uniform_grid_stride`` set.

    Uses ``dataclasses.replace`` since ``ObserverConfig`` is a frozen
    dataclass — direct mutation would raise. Validation (e.g. stride
    against budget) runs in ``ObserverConfig.__post_init__``; any
    incompatible stride/budget combination raises here, not deep in
    the sweep loop.
    """
    return dataclasses.replace(base_config, uniform_grid_stride=stride)


def sweep_stride(
    snapshots: list[pathlib.Path],
    out_path: pathlib.Path,
    log_path: pathlib.Path,
    calibration_set: str,
    config: ObserverConfig,
    strides: tuple[int, ...] = DEFAULT_STRIDES,
) -> dict[str, Any]:
    """Spatial stride sweep per design doc §3.1.

    For each snapshot × stride combination, run ``process_snapshot()``
    with the stride overridden and capture per-snapshot metrics
    (vocabulary_occupancy, entropy, boundary_rate, CCI) plus the
    full token_counts distribution. Aggregate compares metrics across
    strides; mechanical falsification_status per the design-doc
    criterion (stride 4 producing |Δvoc_occ| > 0.15 vs stride 8 →
    sampling artefact).

    The CANONICAL_STRIDE (= 8) is used as the reference against which
    others are compared, mirroring PR #142's baseline so "what changes
    relative to what we previously thought" is the natural read.

    Args:
        snapshots: list of sandboxed ``.npz`` paths.
        out_path: where to write the sweep JSONL.
        log_path: write-boundary anchor; also where process_snapshot
            writes its own log entries as a side effect.
        calibration_set: ``"short"`` or ``"long"``; recorded on rows.
        config: base ``ObserverConfig``; stride is overridden per sweep
            value, other fields preserved.
        strides: tuple of strides to sweep. Defaults to (4, 8, 16) per
            :data:`DEFAULT_STRIDES`. Caller can supply other values
            for experimental purposes.

    Returns the aggregate dict for callers that want to inspect it
    without re-reading the output file.

    Raises:
        :class:`WriteOutsideLogDirError` if ``out_path`` is outside log dir.
        ``ValueError`` for invalid calibration_set, empty strides tuple,
        or non-positive stride values.

    Mechanical falsification_status:
        - ``"hypothesis_supported"``: all pairwise voc_occ diffs across
          strides are below ``_STRIDE_STABILITY_THRESHOLD`` (= 0.05).
          The signal is stride-invariant within tolerance.
        - ``"hypothesis_falsified"``: the |stride 4 − stride 8| voc_occ
          diff exceeds ``_STRIDE_SAMPLING_ARTEFACT_THRESHOLD`` (= 0.15).
          The previous saturation result is at least partly a sampling
          artefact.
        - ``"inconclusive"``: middle ground. Worth running more
          snapshots or tightening the predicates.
    """
    if calibration_set not in {"short", "long"}:
        raise ValueError(
            f"calibration_set must be 'short' or 'long', got "
            f"{calibration_set!r}"
        )
    if not strides:
        raise ValueError("strides must be non-empty")
    for s in strides:
        if not isinstance(s, int) or s <= 0:
            raise ValueError(
                f"every stride must be a positive int, got {s!r}"
            )

    out_path = pathlib.Path(out_path)
    log_path = pathlib.Path(log_path)
    _validate_calibration_output_path(out_path, log_path)
    _validate_config_log_directory(config, log_path)

    sorted_snapshots = _sort_snapshots_by_generation(list(snapshots))

    per_snapshot_rows: list[dict[str, Any]] = []
    # Per-stride aggregator: stride -> list of {snapshot_path, metrics, token_counts}
    by_stride: dict[int, list[dict[str, Any]]] = {s: [] for s in strides}

    for snap in sorted_snapshots:
        generation = _extract_generation_from_filename(snap)
        for stride in strides:
            stride_config = _clone_config_with_stride(config, stride)
            entry = process_snapshot(snap, stride_config, medusa_is_live=False)
            cci_value = _cci_from_entry(entry)
            token_counts = entry.get("token_counts", {}) or {}

            metrics = _extract_metrics_subset(entry)
            metrics["cci"] = cci_value

            per_snapshot_rows.append(_make_per_snapshot_row(
                experiment="stride_sweep",
                snapshot_path=snap,
                generation=generation,
                parameter_combination={"stride": stride},
                metrics=metrics,
                run_metadata={
                    # patches_processed is deterministic; elapsed_seconds
                    # is wallclock-derived and would break byte-identical
                    # re-run. Timing is available in process_snapshot's
                    # own log entry, joinable on snapshot_file.
                    "patches_processed": entry.get("budget", {}).get(
                        "patches_processed"
                    ),
                    "stride_used": entry.get("stride_used"),
                    "stride_backoff_fired": entry.get("stride_backoff_fired"),
                },
                calibration_set=calibration_set,
            ))

            by_stride[stride].append({
                "snapshot": snap.name,
                "generation": generation,
                "metrics": metrics,
                "token_counts": token_counts,
            })

    # --- Per-stride summary statistics ---
    per_stride_summary: dict[str, Any] = {}
    for stride, runs in by_stride.items():
        if not runs:
            per_stride_summary[str(stride)] = {
                "n_snapshots": 0,
            }
            continue
        voc_occs = [r["metrics"]["vocabulary_occupancy"] for r in runs]
        entropies = [r["metrics"]["entropy_normalized"] for r in runs]
        boundaries = [r["metrics"]["boundary_rate"] for r in runs]
        ccis = [r["metrics"]["cci"] for r in runs]
        per_stride_summary[str(stride)] = {
            "n_snapshots": len(runs),
            "mean_vocabulary_occupancy": sum(voc_occs) / len(voc_occs),
            "mean_entropy_normalized": sum(entropies) / len(entropies),
            "mean_boundary_rate": sum(boundaries) / len(boundaries),
            "mean_cci": sum(ccis) / len(ccis),
        }

    # --- Cross-stride differences (vs canonical stride 8 when present) ---
    cross_stride_diffs: dict[str, Any] = {}
    if CANONICAL_STRIDE in by_stride and by_stride[CANONICAL_STRIDE]:
        canon_voc = per_stride_summary[str(CANONICAL_STRIDE)]["mean_vocabulary_occupancy"]
        canon_cci = per_stride_summary[str(CANONICAL_STRIDE)]["mean_cci"]
        for stride in strides:
            if stride == CANONICAL_STRIDE:
                continue
            stride_voc = per_stride_summary[str(stride)]["mean_vocabulary_occupancy"]
            stride_cci = per_stride_summary[str(stride)]["mean_cci"]
            cross_stride_diffs[f"voc_occ_diff_{stride}_vs_{CANONICAL_STRIDE}"] = (
                stride_voc - canon_voc
            )
            cross_stride_diffs[f"cci_diff_{stride}_vs_{CANONICAL_STRIDE}"] = (
                stride_cci - canon_cci
            )

    # --- Cross-stride JS divergence (per snapshot, pairwise) ---
    # For each snapshot, compute JS divergence between each pair of strides'
    # token_counts. Mean across snapshots tells us whether different strides
    # see systematically different distributions.
    cross_stride_js: dict[str, list[float]] = {}
    if len(sorted_snapshots) > 0 and len(strides) >= 2:
        for i, s_a in enumerate(strides):
            for s_b in strides[i + 1:]:
                key = f"js_divergence_stride_{s_a}_vs_{s_b}_bits"
                js_values = []
                # Build per-snapshot token_counts lookup
                lookup_a = {r["snapshot"]: r["token_counts"]
                            for r in by_stride[s_a]}
                lookup_b = {r["snapshot"]: r["token_counts"]
                            for r in by_stride[s_b]}
                for snap_name in lookup_a:
                    if snap_name not in lookup_b:
                        continue
                    js_val = _js_divergence(lookup_a[snap_name], lookup_b[snap_name])
                    js_values.append(js_val)
                if js_values:
                    cross_stride_js[key + "_mean"] = sum(js_values) / len(js_values)
                    cross_stride_js[key + "_max"] = max(js_values)

    # --- Falsification status ---
    falsification_status: str
    if not sorted_snapshots:
        falsification_status = "inconclusive"
    elif CANONICAL_STRIDE not in by_stride or 4 not in by_stride:
        # Without both stride 4 and stride 8, can't apply the §3.1 criterion
        # — declare inconclusive rather than guess.
        falsification_status = "inconclusive"
    else:
        diff_4_vs_8 = abs(
            per_stride_summary["4"]["mean_vocabulary_occupancy"]
            - per_stride_summary[str(CANONICAL_STRIDE)]["mean_vocabulary_occupancy"]
        )
        if diff_4_vs_8 > _STRIDE_SAMPLING_ARTEFACT_THRESHOLD:
            falsification_status = "hypothesis_falsified"
        else:
            # Check all pairwise voc_occ diffs for general stability
            voc_occs = [
                per_stride_summary[str(s)]["mean_vocabulary_occupancy"]
                for s in strides
            ]
            max_pairwise = max(voc_occs) - min(voc_occs)
            if max_pairwise <= _STRIDE_STABILITY_THRESHOLD:
                falsification_status = "hypothesis_supported"
            else:
                falsification_status = "inconclusive"

    extra_fields: dict[str, Any] = {
        "strides_swept": list(strides),
        "canonical_stride": CANONICAL_STRIDE,
        "per_stride_summary": per_stride_summary,
        "cross_stride_diffs": cross_stride_diffs,
        "cross_stride_js_divergence": cross_stride_js,
        "stride_sampling_artefact_threshold": _STRIDE_SAMPLING_ARTEFACT_THRESHOLD,
        "stride_stability_threshold": _STRIDE_STABILITY_THRESHOLD,
    }

    aggregate = _make_aggregate_row(
        experiment="stride_sweep",
        calibration_set=calibration_set,
        n_snapshots=len(sorted_snapshots),
        extra_fields=extra_fields,
        falsification_status=falsification_status,
    )

    _write_calibration_jsonl(out_path, per_snapshot_rows, aggregate)
    return aggregate


# ---------------------------------------------------------------------------
# Experiment 3.4 — sweep_threshold (threshold sensitivity sweep)
# ---------------------------------------------------------------------------


#: Default multipliers per design doc §12 Q3 (Jack's resolution: ±10%,
#: ±25%, ±50%, including the baseline 1.0). Symmetric around 1.0 so we
#: see whether the threshold is on a cliff in either direction.
DEFAULT_THRESHOLD_MULTIPLIERS: tuple[float, ...] = (0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5)

#: Default threshold to sweep. ``THRESHOLD_WARMTH`` is the only
#: classifier-active threshold post-#144 (the deprecated tokens
#: ``karuna_relief`` / ``mudita_resonance`` / ``magnon_lighthouse``
#: don't fire, so sweeping ``THRESHOLD_COMPASSION`` / ``THRESHOLD_RESONANCE``
#: would be no-ops). Caller can override if they want to sweep a different
#: future threshold.
DEFAULT_THRESHOLD_NAME: str = "THRESHOLD_WARMTH"

#: Falsification threshold per design doc §3.4 (adapted post-#144):
#: a ±25% multiplier producing > 50% relative change in the firing count
#: of the threshold's downstream token indicates the threshold is on a
#: knife edge. Original §3.4 spec named ``karuna_relief`` (deprecated);
#: post-#144 the only active threshold-dependent token is ``metta_warmth``.
_THRESHOLD_KNIFE_EDGE_REL_CHANGE: float = 0.5

#: Multiplier range considered "±25%" for the knife-edge criterion.
#: Multipliers within [0.75, 1.25] are checked; outside is too far for
#: the criterion to apply.
_THRESHOLD_KNIFE_EDGE_MULT_RANGE: tuple[float, float] = (0.75, 1.25)


def sweep_threshold(
    snapshots: list[pathlib.Path],
    out_path: pathlib.Path,
    log_path: pathlib.Path,
    calibration_set: str,
    config: ObserverConfig,
    threshold_name: str = DEFAULT_THRESHOLD_NAME,
    multipliers: tuple[float, ...] = DEFAULT_THRESHOLD_MULTIPLIERS,
    threshold_dependent_token: str | None = None,
) -> dict[str, Any]:
    """Threshold sensitivity sweep per design doc §3.4.

    For each ``(snapshot, multiplier)`` pair, temporarily override the
    named threshold constant on the observer module to ``base_value *
    multiplier``, run ``process_snapshot()``, capture metrics + the
    threshold-dependent token's firing count, then restore the original
    value. ``try/finally`` ensures restoration even on exception.

    The thresholds (``THRESHOLD_WARMTH``, etc.) live as module-level
    ``Final[float]`` constants in ``scripts.nextness_observer`` because
    they're typed for static analysis. Python doesn't enforce ``Final``
    at runtime, so we can monkeypatch + restore for sweep purposes —
    this is precisely the kind of experimental override the constants
    were designed to be subject to during calibration. We do NOT mutate
    the observer module from production code paths; only from inside
    this sweep, within try/finally, single-threaded by construction.

    Per design doc §12 Q3: multipliers default to ``(0.5, 0.75, 0.9,
    1.0, 1.1, 1.25, 1.5)`` — symmetric ±10%, ±25%, ±50% around the
    baseline of 1.0.

    Per design doc §3.4 (adapted post-#144 since ``karuna_relief`` is
    deprecated): mechanical falsification_status:

        - ``"hypothesis_supported"``: relative change in the
          threshold-dependent token's firing count across ±25% multipliers
          stays below ``_THRESHOLD_KNIFE_EDGE_REL_CHANGE`` (= 0.5).
          Threshold is well-positioned.
        - ``"hypothesis_falsified"``: ±25% multiplier produces > 50%
          relative change in the firing count. Threshold is on a cliff
          and the current value can't be trusted as "well-calibrated."
        - ``"inconclusive"``: the threshold-dependent token never fires
          on any (snapshot, multiplier) combination so the relative-
          change criterion has no denominator; OR fewer than 3
          multipliers in the ±25% range.

    Args:
        snapshots: list of sandboxed ``.npz`` paths.
        out_path: where to write the sweep JSONL.
        log_path: write-boundary anchor.
        calibration_set: ``"short"`` or ``"long"``.
        config: base ``ObserverConfig`` (used as-is for all multipliers;
            only the threshold constant changes).
        threshold_name: name of the constant on ``scripts.nextness_observer``
            to sweep. Must be an attribute of the module. Defaults to
            ``"THRESHOLD_WARMTH"``.
        multipliers: tuple of float multipliers to apply to the
            threshold's base value. Must be all positive.
        threshold_dependent_token: name of the token whose firing count
            we track across the sweep for the knife-edge criterion.
            **Required and explicit-only** (post-#164 hardening): there is no
            default. The former silent default ``"metta_warmth"`` was demoted
            to status ``diagnostic_only`` and removed from the active cascade
            (Workstream B/C, PR #163/#164), so it never fires and a sweep
            against it is ``inconclusive`` *by construction* — silently
            defaulting to it produced guaranteed-inconclusive calibration
            evidence. We refuse to pick a replacement default silently either:
            the caller must name a routing token (status not in
            ``NON_ROUTING_STATUSES``) whose firing count genuinely depends on
            the swept threshold. The tokens that actually gate on
            ``THRESHOLD_WARMTH`` post-#144 are ``compute_decay`` and
            ``acoustic_stress`` (both gate on ``warmth_mean < THRESHOLD_WARMTH``).
            Passing ``None``, an unknown token, or a non-routing token raises
            ``ValueError``.

    Returns the aggregate dict for callers that want to inspect it.

    Raises:
        :class:`WriteOutsideLogDirError` if ``out_path`` is outside log dir.
        ``ValueError`` for invalid calibration_set, missing threshold
            attribute, empty multipliers, non-positive multipliers, or a
            ``threshold_dependent_token`` that is ``None`` (not passed
            explicitly), unknown, or non-routing.
    """
    # Lazy import of the observer module so we can monkeypatch its
    # threshold attribute. This is the only place in the calibration
    # module that mutates observer state, and only within try/finally.
    from scripts import nextness_observer as _observer_module

    if calibration_set not in {"short", "long"}:
        raise ValueError(
            f"calibration_set must be 'short' or 'long', got "
            f"{calibration_set!r}"
        )
    if not hasattr(_observer_module, threshold_name):
        raise ValueError(
            f"threshold_name {threshold_name!r} not found on "
            f"scripts.nextness_observer module"
        )
    if not multipliers:
        raise ValueError("multipliers must be non-empty")
    for m in multipliers:
        if not isinstance(m, (int, float)) or m <= 0:
            raise ValueError(
                f"every multiplier must be a positive number, got {m!r}"
            )

    # threshold_dependent_token is explicit-only (post-#164 hardening). We
    # refuse to silently default to a non-routing token: metta_warmth (the
    # former default) is diagnostic_only and a sweep against it is inconclusive
    # by construction, so a silent default manufactures guaranteed-inconclusive
    # evidence. Force the caller to name a routing token explicitly.
    if threshold_dependent_token is None:
        raise ValueError(
            "threshold_dependent_token must be passed explicitly; there is no "
            "default. The former silent default 'metta_warmth' is now status "
            "'diagnostic_only' (non-routing, Workstream B/C PR #163/#164): it "
            "never fires in the active cascade, so sweeping against it is "
            "inconclusive by construction. Choose a routing token whose firing "
            "count actually depends on the swept threshold, e.g. one of: "
            f"{sorted(_observer_module.ROUTING_TOKENS)}."
        )
    if threshold_dependent_token not in _observer_module.TOKEN_NAMES:
        raise ValueError(
            f"threshold_dependent_token {threshold_dependent_token!r} is not a "
            f"known token. Valid tokens: {sorted(_observer_module.TOKEN_NAMES)}."
        )
    if threshold_dependent_token not in _observer_module.ROUTING_TOKENS:
        status = _observer_module.TOKEN_STATUS[threshold_dependent_token]
        raise ValueError(
            f"threshold_dependent_token {threshold_dependent_token!r} has "
            f"non-routing status {status!r}: it never fires in the active "
            "cascade, so the sweep would be inconclusive by construction. Pass "
            "a routing token instead, e.g. one of: "
            f"{sorted(_observer_module.ROUTING_TOKENS)}."
        )

    out_path = pathlib.Path(out_path)
    log_path = pathlib.Path(log_path)
    _validate_calibration_output_path(out_path, log_path)
    _validate_config_log_directory(config, log_path)

    sorted_snapshots = _sort_snapshots_by_generation(list(snapshots))

    base_threshold_value = float(getattr(_observer_module, threshold_name))

    per_snapshot_rows: list[dict[str, Any]] = []
    # Per-multiplier aggregator: multiplier -> list of {snapshot, metrics,
    # threshold_dependent_token_count, total_classified}.
    by_multiplier: dict[float, list[dict[str, Any]]] = {m: [] for m in multipliers}

    for snap in sorted_snapshots:
        generation = _extract_generation_from_filename(snap)
        for multiplier in multipliers:
            new_threshold_value = base_threshold_value * multiplier
            # Monkeypatch + restore inside try/finally. Single-threaded
            # by construction (calibration is sequential).
            original = getattr(_observer_module, threshold_name)
            try:
                setattr(_observer_module, threshold_name, new_threshold_value)
                entry = process_snapshot(snap, config, medusa_is_live=False)
            finally:
                setattr(_observer_module, threshold_name, original)

            token_counts = entry.get("token_counts", {}) or {}
            total_classified = sum(token_counts.values())
            token_count = int(token_counts.get(threshold_dependent_token, 0))
            metrics = _extract_metrics_subset(entry)
            metrics["cci"] = _cci_from_entry(entry)
            metrics["threshold_dependent_token_count"] = token_count
            metrics["threshold_dependent_token_name"] = threshold_dependent_token
            metrics["threshold_dependent_token_fraction"] = (
                token_count / total_classified if total_classified else 0.0
            )

            per_snapshot_rows.append(_make_per_snapshot_row(
                experiment="threshold_sweep",
                snapshot_path=snap,
                generation=generation,
                parameter_combination={
                    "threshold_name": threshold_name,
                    "threshold_multiplier": multiplier,
                    "threshold_effective_value": new_threshold_value,
                    "threshold_dependent_token": threshold_dependent_token,
                },
                metrics=metrics,
                run_metadata={
                    # patches_processed is deterministic; elapsed_seconds
                    # was wallclock-derived and removed in Chapter 4 to
                    # preserve byte-identical re-run.
                    "patches_processed": entry.get("budget", {}).get(
                        "patches_processed"
                    ),
                },
                calibration_set=calibration_set,
            ))

            by_multiplier[multiplier].append({
                "snapshot": snap.name,
                "metrics": metrics,
                "token_count": token_count,
                "total_classified": total_classified,
            })

    # --- Per-multiplier summary statistics ---
    per_multiplier_summary: dict[str, Any] = {}
    for multiplier, runs in by_multiplier.items():
        if not runs:
            per_multiplier_summary[str(multiplier)] = {"n_snapshots": 0}
            continue
        voc_occs = [r["metrics"]["vocabulary_occupancy"] for r in runs]
        ccis = [r["metrics"]["cci"] for r in runs]
        token_counts = [r["token_count"] for r in runs]
        token_fractions = [r["metrics"]["threshold_dependent_token_fraction"]
                           for r in runs]
        per_multiplier_summary[str(multiplier)] = {
            "n_snapshots": len(runs),
            "effective_threshold_value": base_threshold_value * multiplier,
            "mean_vocabulary_occupancy": sum(voc_occs) / len(voc_occs),
            "mean_cci": sum(ccis) / len(ccis),
            "mean_threshold_dependent_token_count": sum(token_counts) / len(token_counts),
            "mean_threshold_dependent_token_fraction": sum(token_fractions) / len(token_fractions),
            "max_threshold_dependent_token_count": max(token_counts),
        }

    # --- Falsification logic (knife-edge detection per §3.4) ---
    # Find the baseline (multiplier=1.0) and compare against multipliers
    # in [0.75, 1.25] (the ±25% range).
    falsification_status: str = "inconclusive"
    knife_edge_evidence: dict[str, Any] = {}
    if 1.0 in by_multiplier and by_multiplier[1.0]:
        baseline_summary = per_multiplier_summary["1.0"]
        baseline_count = baseline_summary["mean_threshold_dependent_token_count"]
        in_range = [
            m for m in multipliers
            if _THRESHOLD_KNIFE_EDGE_MULT_RANGE[0] <= m <= _THRESHOLD_KNIFE_EDGE_MULT_RANGE[1]
            and m != 1.0
        ]
        knife_edge_evidence["baseline_multiplier"] = 1.0
        knife_edge_evidence["baseline_mean_token_count"] = baseline_count
        knife_edge_evidence["multipliers_in_range"] = in_range

        if baseline_count == 0 and all(
            per_multiplier_summary[str(m)]["mean_threshold_dependent_token_count"] == 0
            for m in in_range
        ):
            # The token never fires anywhere in the ±25% range.
            # No relative-change denominator → inconclusive.
            knife_edge_evidence["reason"] = (
                f"{threshold_dependent_token} never fires on any snapshot "
                f"in the ±25% multiplier range; relative change undefined"
            )
            falsification_status = "inconclusive"
        elif len(in_range) < 2:
            knife_edge_evidence["reason"] = (
                f"fewer than 2 multipliers in ±25% range; criterion needs at least 2"
            )
            falsification_status = "inconclusive"
        else:
            # Compute max relative change vs baseline across the ±25% range.
            max_rel_change = 0.0
            for m in in_range:
                m_count = per_multiplier_summary[str(m)][
                    "mean_threshold_dependent_token_count"
                ]
                denom = max(baseline_count, m_count, 1.0)  # avoid div-by-zero
                rel_change = abs(m_count - baseline_count) / denom
                if rel_change > max_rel_change:
                    max_rel_change = rel_change
            knife_edge_evidence["max_rel_change_in_25pct_range"] = max_rel_change
            knife_edge_evidence["knife_edge_threshold"] = _THRESHOLD_KNIFE_EDGE_REL_CHANGE
            if max_rel_change > _THRESHOLD_KNIFE_EDGE_REL_CHANGE:
                falsification_status = "hypothesis_falsified"
            else:
                falsification_status = "hypothesis_supported"

    extra_fields: dict[str, Any] = {
        "threshold_name": threshold_name,
        "threshold_base_value": base_threshold_value,
        "threshold_dependent_token": threshold_dependent_token,
        "multipliers_swept": list(multipliers),
        "per_multiplier_summary": per_multiplier_summary,
        "knife_edge_evidence": knife_edge_evidence,
    }

    aggregate = _make_aggregate_row(
        experiment="threshold_sweep",
        calibration_set=calibration_set,
        n_snapshots=len(sorted_snapshots),
        extra_fields=extra_fields,
        falsification_status=falsification_status,
    )

    _write_calibration_jsonl(out_path, per_snapshot_rows, aggregate)
    return aggregate


# ---------------------------------------------------------------------------
# Chapter 6 — ablate_cascade (design doc §3.5, Jack #6 in implementation order)
# ---------------------------------------------------------------------------


#: Default dominant tokens to disable one-at-a-time. Per the Chapter 6
#: real-Medusa smoke pass (post-#145 layout fix), the currently dominant
#: active tokens above the 5% rate threshold are:
#:
#:     phase_boundary 66.5%, sensor_alert 20.9%, void_birth 9.5%
#:
#: Disabling each in turn exposes whatever predicate would have fired
#: "next" — the §3.5 cascade-ablation hidden-token probe. Aimed at the
#: post-#145 dominant cascade rather than pre-#145 ghosts per Jack's
#: PR #152 audit (``compute_static`` / ``void_static`` are no-ops in
#: the corrected post-#145 distribution and were dropped from the default).
DEFAULT_ABLATION_DISABLED_TOKENS: tuple[str, ...] = (
    "phase_boundary",
    "sensor_alert",
    "void_birth",
)

#: The ACTIVE classifier cascade order (deprecated tokens excluded per
#: TOKEN_STATUS post-#144). This must mirror :func:`classify_patch` in
#: ``nextness_observer.py``; a parity regression-fence test locks the
#: non-ablated calibration cascade against the observer cascade on
#: synthetic patches covering every branch. ``unclassified`` is the
#: fall-through bucket, not an explicit cascade step.
# metta_warmth removed from the active cascade per Workstream B/C (PR #163):
# it is now status "diagnostic_only" in the observer's TOKEN_STATUS and no
# longer routes classification. The observer's classify_patch skips it; this
# mirror must match (parity regression-fence test enforces agreement).
_ACTIVE_CASCADE_ORDER: tuple[str, ...] = (
    "phase_boundary",
    "compute_aging",
    "sensor_alert",
    "energy_pulse",
    "compute_decay",
    "compute_static",
    "structural_growth",
    "structural_decay",
    "void_birth",
    "void_static",
    "acoustic_stress",
)

#: Per design doc §3.5: a non-baseline ablation mode that reveals more than
#: this many additional tokens firing above the rate threshold indicates the
#: cascade is hiding signal.
_CASCADE_ABLATION_HIDDEN_TOKEN_COUNT_THRESHOLD: int = 5

#: Per design doc §3.5: per-token rate threshold for "additional token firing"
#: — tokens that go from < 5% in baseline to > 5% in an ablation mode count
#: as emerging. Symmetric: tokens already > 5% in baseline don't re-count
#: just because they shifted within the > 5% band.
_CASCADE_ABLATION_HIDDEN_TOKEN_RATE_THRESHOLD: float = 0.05


def _predicate_fires(token: str, features: Any) -> bool:
    """Return True if the cascade predicate for ``token`` matches ``features``.

    Mirrors the inline predicates in
    :func:`scripts.nextness_observer.classify_patch` for ablation purposes.
    Drift is locked out by the parity regression-fence test
    ``test_classify_patch_ablation_parity_with_observer_on_synthetic_battery``
    in ``test_nextness_calibration.py``.
    """
    # Lazy import so observer-module constants are picked up live (matches
    # the sweep_threshold pattern of reading thresholds at call-time).
    from scripts.nextness_observer import (
        AGE_ANCIENT,
        AGE_SAGE,
        DIVERSITY_BOUNDARY,
        ENERGY_PULSE_MIN_COUNT,
        FRACTION_DOMINANT,
        FRACTION_MAJORITY,
        THRESHOLD_WARMTH,
    )
    f = features
    if token == "phase_boundary":
        return f.distinct_states >= DIVERSITY_BOUNDARY
    if token == "compute_aging":
        return f.compute_frac >= FRACTION_DOMINANT and f.compute_age_mean >= AGE_SAGE
    # metta_warmth intentionally absent: demoted to diagnostic_only (PR #163),
    # no longer a routing token. It is not in _ACTIVE_CASCADE_ORDER, so this
    # mirror is never asked to evaluate it; a stray call would (correctly)
    # fall through to the ValueError below.
    if token == "sensor_alert":
        return f.sensor_count >= 1
    if token == "energy_pulse":
        return f.energy_count >= ENERGY_PULSE_MIN_COUNT
    if token == "compute_decay":
        return (
            f.compute_count >= 1
            and f.void_frac >= FRACTION_DOMINANT
            and f.warmth_mean < THRESHOLD_WARMTH
        )
    if token == "compute_static":
        return f.compute_frac >= FRACTION_DOMINANT
    if token == "structural_growth":
        return f.structural_frac >= FRACTION_DOMINANT and f.structural_age_mean < AGE_SAGE
    if token == "structural_decay":
        return f.structural_frac >= FRACTION_DOMINANT and f.structural_age_mean >= AGE_ANCIENT
    if token == "void_birth":
        return f.void_frac >= FRACTION_DOMINANT and f.distinct_states >= 2
    if token == "void_static":
        return f.void_frac >= FRACTION_MAJORITY
    if token == "acoustic_stress":
        return f.distinct_states >= 3 and f.warmth_mean < THRESHOLD_WARMTH
    raise ValueError(f"unknown cascade token {token!r}")


def _classify_patch_ablation(
    patch: Any,
    *,
    disabled_tokens: frozenset[str] = frozenset(),
    reverse_order: bool = False,
) -> str:
    """Calibration-side classify_patch with cascade-ablation knobs.

    Mirrors :func:`scripts.nextness_observer.classify_patch`'s ACTIVE
    cascade (deprecated tokens skipped per TOKEN_STATUS). Two knobs:

    * ``disabled_tokens`` — set of token names whose predicates are skipped.
      If a disabled token's predicate would have fired, the cascade
      continues to the next token instead, revealing what was "hiding"
      one rung below.
    * ``reverse_order`` — if True, cascade order is reversed (least-specific
      first). Stress-tests the cascade-ordering decision per design doc §3.5.

    With ``disabled_tokens=frozenset()`` and ``reverse_order=False`` this
    function MUST agree with the observer's ``classify_patch`` bit-for-bit.
    The parity regression-fence test enforces this.

    Returns ``"unclassified"`` if no predicate fires (the cascade's
    fall-through bucket).
    """
    from scripts.nextness_observer import _patch_features
    f = _patch_features(patch)
    order = (
        tuple(reversed(_ACTIVE_CASCADE_ORDER)) if reverse_order
        else _ACTIVE_CASCADE_ORDER
    )
    for token in order:
        if token in disabled_tokens:
            continue
        if _predicate_fires(token, f):
            return token
    return "unclassified"


def _make_ablating_classifier(
    disabled_tokens: frozenset[str],
    reverse_order: bool,
):
    """Return a closure suitable for monkey-patching observer.classify_patch.

    The returned callable signature matches the observer's
    ``classify_patch(patch) -> str``. Used by :func:`ablate_cascade` inside
    a try/finally to install + restore the classifier for one ablation
    mode at a time.
    """
    def _ablating_classifier(patch: Any) -> str:
        return _classify_patch_ablation(
            patch,
            disabled_tokens=disabled_tokens,
            reverse_order=reverse_order,
        )
    return _ablating_classifier


def _ablation_modes_for_run(
    disabled_tokens: tuple[str, ...],
    include_baseline: bool,
    include_reverse: bool,
) -> list[dict[str, Any]]:
    """Build the ordered list of modes to run.

    Each mode is a dict with ``label`` (string for parameter_combination),
    ``disabled_tokens`` (frozenset for the classifier), and ``reverse_order``
    (bool). Order is: baseline (if requested) → one disable_<token> per
    token (in input order) → reverse_order (if requested).
    """
    modes: list[dict[str, Any]] = []
    if include_baseline:
        modes.append({
            "label": "baseline",
            "disabled_tokens": frozenset(),
            "reverse_order": False,
        })
    for token in disabled_tokens:
        modes.append({
            "label": f"disable_{token}",
            "disabled_tokens": frozenset({token}),
            "reverse_order": False,
        })
    if include_reverse:
        modes.append({
            "label": "reverse_order",
            "disabled_tokens": frozenset(),
            "reverse_order": True,
        })
    return modes


def _emerging_tokens_vs_baseline(
    baseline_counts: dict[str, int],
    mode_counts: dict[str, int],
    rate_threshold: float,
) -> dict[str, Any]:
    """Compute which tokens emerge in ``mode_counts`` vs ``baseline_counts``.

    A token is "emerging" if its rate in mode_counts crosses
    ``rate_threshold`` while its rate in baseline_counts was below it.
    Returns the emerging-token list, both totals, and the count for the
    falsification criterion.
    """
    baseline_total = sum(baseline_counts.values())
    mode_total = sum(mode_counts.values())
    baseline_rate = lambda t: (baseline_counts.get(t, 0) / baseline_total) if baseline_total else 0.0
    mode_rate = lambda t: (mode_counts.get(t, 0) / mode_total) if mode_total else 0.0
    all_tokens = set(baseline_counts) | set(mode_counts)
    emerging = sorted(
        t for t in all_tokens
        if baseline_rate(t) <= rate_threshold and mode_rate(t) > rate_threshold
    )
    return {
        "emerging_tokens": emerging,
        "emerging_token_count": len(emerging),
        "baseline_total": baseline_total,
        "mode_total": mode_total,
        "rate_threshold": rate_threshold,
    }


def ablate_cascade(
    snapshots: list[pathlib.Path],
    out_path: pathlib.Path,
    log_path: pathlib.Path,
    calibration_set: str,
    config: ObserverConfig,
    disabled_tokens: tuple[str, ...] = DEFAULT_ABLATION_DISABLED_TOKENS,
    include_baseline: bool = True,
    include_reverse: bool = True,
) -> dict[str, Any]:
    """Cascade ablation / cascade-order test per design doc §3.5.

    For each snapshot, run ``process_snapshot()`` once per ablation mode.
    Modes:

      * ``"baseline"`` — unmodified cascade (sanity reference; required
        as denominator for the emerging-token criterion)
      * ``"disable_<token>"`` — for each ``disabled_tokens`` entry, run
        with that token's predicate skipped (observe what fires "next")
      * ``"reverse_order"`` — run with the active cascade reversed
        (least-specific first)

    Each mode is installed by monkey-patching ``classify_patch`` on the
    observer module with an ablating closure, wrapped in ``try/finally``
    to guarantee restoration even on exception. Mirrors the
    ``sweep_threshold`` monkey-patch + restore pattern.

    Mechanical falsification_status per design doc §3.5:

      * ``"hypothesis_supported"``: across all non-baseline modes, the
        max additional-token count (tokens crossing the 5% rate threshold
        in a mode while ≤ 5% in baseline) is ≤ 5. The cascade is sensibly
        ordered; ablation does not expose a long tail.
      * ``"hypothesis_falsified"``: at least one non-baseline mode reveals
        > 5 additional tokens crossing the 5% rate threshold. The cascade
        ordering is the dominant cause of the apparent two-token saturation.
      * ``"inconclusive"``: no baseline mode requested (no denominator),
        or baseline produced no patches, or only the baseline mode was run.

    Args:
        snapshots: list of sandboxed ``.npz`` paths. Sorted by generation.
        out_path: where to write the cascade ablation JSONL.
        log_path: write-boundary anchor. Same canonical
            ``nextness_runs.jsonl`` path used everywhere else.
        calibration_set: ``"short"`` or ``"long"``.
        config: ``ObserverConfig`` used for every ``process_snapshot()``
            call. ``config.log_directory`` must equal ``log_path.parent``
            (enforced by ``_validate_config_log_directory`` per Jack
            PR #149 audit).
        disabled_tokens: tuple of token names whose predicates to ablate
            one-at-a-time. Defaults to the dominant tokens in current
            Medusa state. Every entry must be an active cascade token.
        include_baseline: whether to include the unmodified-cascade mode.
            Defaults to True. Disabling this forces ``inconclusive``
            because emerging-token computation has no denominator.
        include_reverse: whether to include the cascade-order-reversal
            mode. Defaults to True. Disabling skips that stress test.

    Returns the aggregate dict for callers that want to inspect it
    without re-reading the output file.

    Raises:
        :class:`WriteOutsideLogDirError` if ``out_path`` is outside log dir
            or ``config.log_directory`` diverges from ``log_path.parent``.
        ``ValueError`` for invalid calibration_set, unknown token in
            ``disabled_tokens``, or empty mode set.
    """
    # Lazy import of the observer module so we can monkeypatch its
    # classify_patch attribute. Only place in the calibration module that
    # mutates observer state besides sweep_threshold; only within try/finally.
    from scripts import nextness_observer as _observer_module

    if calibration_set not in {"short", "long"}:
        raise ValueError(
            f"calibration_set must be 'short' or 'long', got {calibration_set!r}"
        )
    for t in disabled_tokens:
        if t not in _ACTIVE_CASCADE_ORDER:
            raise ValueError(
                f"disabled token {t!r} is not an active cascade token "
                f"(active: {_ACTIVE_CASCADE_ORDER})"
            )

    modes = _ablation_modes_for_run(
        disabled_tokens=disabled_tokens,
        include_baseline=include_baseline,
        include_reverse=include_reverse,
    )
    if not modes:
        raise ValueError(
            "no modes selected; at least one of include_baseline, "
            "include_reverse, or non-empty disabled_tokens is required"
        )

    out_path = pathlib.Path(out_path)
    log_path = pathlib.Path(log_path)
    _validate_calibration_output_path(out_path, log_path)
    _validate_config_log_directory(config, log_path)

    sorted_snapshots = _sort_snapshots_by_generation(list(snapshots))

    per_snapshot_rows: list[dict[str, Any]] = []
    # Per-mode aggregator: mode_label -> per-snapshot list of token_counts
    # (for the aggregate's per_mode_summary and emerging-token analysis).
    by_mode: dict[str, list[dict[str, Any]]] = {m["label"]: [] for m in modes}

    for snap in sorted_snapshots:
        generation = _extract_generation_from_filename(snap)
        for mode in modes:
            # Monkeypatch + restore inside try/finally. Single-threaded by
            # construction (calibration is sequential).
            original_classifier = _observer_module.classify_patch
            ablating_classifier = _make_ablating_classifier(
                disabled_tokens=mode["disabled_tokens"],
                reverse_order=mode["reverse_order"],
            )
            try:
                _observer_module.classify_patch = ablating_classifier
                entry = process_snapshot(snap, config, medusa_is_live=False)
            finally:
                _observer_module.classify_patch = original_classifier

            token_counts = dict(entry.get("token_counts", {}) or {})
            metrics = _extract_metrics_subset(entry)
            metrics["cci"] = _cci_from_entry(entry)

            per_snapshot_rows.append(_make_per_snapshot_row(
                experiment="cascade_ablation",
                snapshot_path=snap,
                generation=generation,
                parameter_combination={
                    "mode": mode["label"],
                    "disabled_tokens": sorted(mode["disabled_tokens"]),
                    "reverse_order": mode["reverse_order"],
                },
                metrics=metrics,
                run_metadata={
                    # patches_processed is deterministic; elapsed_seconds
                    # is wallclock-derived and excluded to preserve
                    # byte-identical re-run (Chapter 4 pattern).
                    "patches_processed": entry.get("budget", {}).get(
                        "patches_processed"
                    ),
                },
                calibration_set=calibration_set,
            ))

            by_mode[mode["label"]].append({
                "snapshot": snap.name,
                "metrics": metrics,
                "token_counts": token_counts,
            })

    # --- Per-mode summary statistics ---
    per_mode_summary: dict[str, Any] = {}
    # Aggregate token_counts across snapshots per mode for emerging-token
    # computation. Per-snapshot rows above carry the raw per-snapshot
    # distribution; the aggregate uses the summed distribution to avoid
    # noise from any single snapshot dominating.
    summed_counts_by_mode: dict[str, dict[str, int]] = {}
    for mode_label, runs in by_mode.items():
        summed: dict[str, int] = {}
        for r in runs:
            for tok, n in r["token_counts"].items():
                summed[tok] = summed.get(tok, 0) + int(n)
        summed_counts_by_mode[mode_label] = summed

        if not runs:
            per_mode_summary[mode_label] = {"n_snapshots": 0}
            continue
        voc_occs = [r["metrics"]["vocabulary_occupancy"] for r in runs]
        ccis = [r["metrics"]["cci"] for r in runs]
        per_mode_summary[mode_label] = {
            "n_snapshots": len(runs),
            "mean_vocabulary_occupancy": sum(voc_occs) / len(voc_occs),
            "mean_cci": sum(ccis) / len(ccis),
            "summed_token_counts": summed,
        }

    # --- Falsification logic (§3.5 cascade-hiding-signal criterion) ---
    falsification_status: str = "inconclusive"
    emerging_token_evidence: dict[str, Any] = {}
    non_baseline_modes = [m["label"] for m in modes if m["label"] != "baseline"]

    if not include_baseline or not by_mode.get("baseline"):
        emerging_token_evidence["reason"] = (
            "baseline mode not included or produced no patches; "
            "emerging-token criterion has no denominator"
        )
    elif not non_baseline_modes:
        emerging_token_evidence["reason"] = (
            "only baseline mode requested; no ablation to compare against"
        )
    else:
        baseline_counts = summed_counts_by_mode["baseline"]
        per_mode_emerging: dict[str, Any] = {}
        max_emerging_count = 0
        max_emerging_mode = None
        for mode_label in non_baseline_modes:
            mode_counts = summed_counts_by_mode[mode_label]
            evidence = _emerging_tokens_vs_baseline(
                baseline_counts=baseline_counts,
                mode_counts=mode_counts,
                rate_threshold=_CASCADE_ABLATION_HIDDEN_TOKEN_RATE_THRESHOLD,
            )
            per_mode_emerging[mode_label] = evidence
            if evidence["emerging_token_count"] > max_emerging_count:
                max_emerging_count = evidence["emerging_token_count"]
                max_emerging_mode = mode_label

        emerging_token_evidence["per_mode"] = per_mode_emerging
        emerging_token_evidence["max_emerging_token_count"] = max_emerging_count
        emerging_token_evidence["max_emerging_mode"] = max_emerging_mode
        emerging_token_evidence["hidden_token_count_threshold"] = (
            _CASCADE_ABLATION_HIDDEN_TOKEN_COUNT_THRESHOLD
        )
        emerging_token_evidence["hidden_token_rate_threshold"] = (
            _CASCADE_ABLATION_HIDDEN_TOKEN_RATE_THRESHOLD
        )

        if max_emerging_count > _CASCADE_ABLATION_HIDDEN_TOKEN_COUNT_THRESHOLD:
            falsification_status = "hypothesis_falsified"
        else:
            falsification_status = "hypothesis_supported"

    extra_fields: dict[str, Any] = {
        "disabled_tokens": list(disabled_tokens),
        "modes_run": [m["label"] for m in modes],
        "include_baseline": include_baseline,
        "include_reverse": include_reverse,
        "per_mode_summary": per_mode_summary,
        "emerging_token_evidence": emerging_token_evidence,
    }

    aggregate = _make_aggregate_row(
        experiment="cascade_ablation",
        calibration_set=calibration_set,
        n_snapshots=len(sorted_snapshots),
        extra_fields=extra_fields,
        falsification_status=falsification_status,
    )

    _write_calibration_jsonl(out_path, per_snapshot_rows, aggregate)
    return aggregate


# ---------------------------------------------------------------------------
# Chapter 7 — sweep_temporal (design doc §3.2, Jack #7 in implementation order)
# ---------------------------------------------------------------------------


#: Default gap specs for the short calibration set (12 consecutive snapshots
#: at ~10-min cadence). Each entry is ``(label, index_stride)``. Index stride
#: is the number of positions to skip in the generation-sorted snapshot list.
#: Short-set spacing: 1 = ~10min (adjacent); 6 = ~60min (~1h).
DEFAULT_GAP_SPECS_SHORT: tuple[tuple[str, int], ...] = (
    ("adjacent", 1),
    ("1h", 6),
)

#: Default gap specs for the long calibration set (12 snapshots spread across
#: ~24h at ~120-min cadence). Long-set spacing: 1 = ~2h (consecutive in long
#: set); 3 = ~6h; 11 = ~24h (first to last of 12 snapshots).
DEFAULT_GAP_SPECS_LONG: tuple[tuple[str, int], ...] = (
    ("2h", 1),
    ("6h", 3),
    ("24h", 11),
)

#: §3.2 falsification threshold: mean JS divergence at the LARGEST gap above
#: this value (in bits) indicates a drifting system, not a stable attractor.
_TEMPORAL_DRIFT_JS_THRESHOLD_BITS: float = 0.1

#: §3.2 attractor threshold: mean JS divergence at the largest gap below this
#: value (in bits) is the "small JS" expectation for a stable attractor.
#: Between this and the falsification threshold is the inconclusive band.
_TEMPORAL_DRIFT_ATTRACTOR_JS_THRESHOLD_BITS: float = 0.01


def _temporal_pair_stats(values: list[float]) -> dict[str, float]:
    """Mean / std (sample, n-1 denominator) / max for a list of pair values.

    Returns std=0.0 for n<=1 (no variance to estimate). Used for both JS
    divergence and CCI drift summaries inside sweep_temporal.
    """
    if not values:
        return {"mean": 0.0, "std": 0.0, "max": 0.0}
    mean = sum(values) / len(values)
    if len(values) > 1:
        std = math.sqrt(
            sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        )
    else:
        std = 0.0
    return {"mean": mean, "std": std, "max": max(values)}


def sweep_temporal(
    snapshots: list[pathlib.Path],
    out_path: pathlib.Path,
    log_path: pathlib.Path,
    calibration_set: str,
    config: ObserverConfig,
    gap_specs: tuple[tuple[str, int], ...] | None = None,
) -> dict[str, Any]:
    """Temporal window sweep per design doc §3.2.

    Tests whether the equilibrium is short-term stillness or genuine
    longer-horizon stability. For each ``(gap_label, index_stride)`` in
    ``gap_specs``, forms snapshot pairs ``(snapshots[i], snapshots[i+stride])``
    after sorting by generation, then computes Jensen-Shannon divergence
    (bits) between the pair's ``token_counts`` distributions and the
    absolute CCI drift between the two endpoints.

    Per design doc §2.5 + Jack PR #143 coherence note, this experiment
    draws gaps from whichever calibration set actually contains that
    spacing: short for ~10min and ~1h gaps, long for ~2h, ~6h, ~24h gaps.
    A single ``sweep_temporal()`` call handles one set at a time —
    callers run it twice (once per set) to cover the full temporal
    discrimination matrix.

    Mechanical falsification_status per the §3.2 criterion applied to
    the LARGEST gap in ``gap_specs`` (the last entry by convention):

      * ``"hypothesis_supported"``: mean JS at the largest gap is below
        ``_TEMPORAL_DRIFT_ATTRACTOR_JS_THRESHOLD_BITS`` (= 0.01). System
        has genuinely settled — attractor confirmed at this timescale.
      * ``"hypothesis_falsified"``: mean JS at the largest gap exceeds
        ``_TEMPORAL_DRIFT_JS_THRESHOLD_BITS`` (= 0.1). PR #142 50-min
        stillness was a snapshot of a moving system, not a fixed point.
      * ``"inconclusive"``: mean JS between the two thresholds (neither
        obviously stable nor obviously drifting), OR the largest gap
        produced no pairs (too few snapshots for the requested stride).

    Args:
        snapshots: list of sandboxed ``.npz`` paths. Sorted by generation
            before pair formation. Per-snapshot ``process_snapshot()``
            calls are cached so each snapshot is processed at most once
            even when it appears in multiple gap-pair lists.
        out_path: where to write the temporal sweep JSONL.
        log_path: write-boundary anchor; same canonical
            ``nextness_runs.jsonl`` path used elsewhere.
        calibration_set: ``"short"`` or ``"long"``. Controls the default
            ``gap_specs`` when none is provided.
        config: ``ObserverConfig`` for every ``process_snapshot()`` call.
            Subject to the PR #149 config-log-dir guard.
        gap_specs: tuple of ``(label, index_stride)``. Defaults to
            :data:`DEFAULT_GAP_SPECS_SHORT` for the short set and
            :data:`DEFAULT_GAP_SPECS_LONG` for the long set. Caller can
            override to test custom spacings. ``label`` is the human-
            readable name recorded in the output (e.g., ``"2h"``);
            ``index_stride`` is the number of generation-sorted positions
            to skip when forming pairs.

    Returns the aggregate dict for callers that want to inspect it
    without re-reading the output file.

    Raises:
        :class:`WriteOutsideLogDirError` if ``out_path`` is outside log dir
            or ``config.log_directory`` diverges from ``log_path.parent``.
        ``ValueError`` for invalid calibration_set, empty gap_specs (when
            provided explicitly), empty label, or non-positive stride.
    """
    if calibration_set not in {"short", "long"}:
        raise ValueError(
            f"calibration_set must be 'short' or 'long', got {calibration_set!r}"
        )
    if gap_specs is None:
        gap_specs = (
            DEFAULT_GAP_SPECS_SHORT if calibration_set == "short"
            else DEFAULT_GAP_SPECS_LONG
        )
    if not gap_specs:
        raise ValueError("gap_specs must be non-empty when provided explicitly")
    for entry in gap_specs:
        if not (isinstance(entry, tuple) and len(entry) == 2):
            raise ValueError(
                f"each gap_specs entry must be (label, index_stride), got {entry!r}"
            )
        label, stride = entry
        if not isinstance(label, str) or not label:
            raise ValueError(
                f"gap_spec label must be a non-empty str, got {label!r}"
            )
        if not isinstance(stride, int) or stride < 1:
            raise ValueError(
                f"gap_spec index_stride must be a positive int, got {stride!r}"
            )

    out_path = pathlib.Path(out_path)
    log_path = pathlib.Path(log_path)
    _validate_calibration_output_path(out_path, log_path)
    _validate_config_log_directory(config, log_path)

    sorted_snapshots = _sort_snapshots_by_generation(list(snapshots))

    # Cache: snapshot path -> process_snapshot entry. Each snapshot is
    # processed at most once even when it appears in multiple gap-pair
    # lists (an 'adjacent' pair and a '1h' pair may share endpoints).
    entry_cache: dict[pathlib.Path, dict[str, Any]] = {}

    def _get_entry(snap: pathlib.Path) -> dict[str, Any]:
        if snap not in entry_cache:
            entry_cache[snap] = process_snapshot(snap, config, medusa_is_live=False)
        return entry_cache[snap]

    per_snapshot_rows: list[dict[str, Any]] = []
    # Per-gap aggregator: gap_label -> {n_pairs, js stats, cci_drift stats}
    per_gap_summary: dict[str, Any] = {}

    for gap_label, gap_stride in gap_specs:
        js_values: list[float] = []
        cci_drifts: list[float] = []

        for i in range(len(sorted_snapshots) - gap_stride):
            snap_a = sorted_snapshots[i]
            snap_b = sorted_snapshots[i + gap_stride]
            entry_a = _get_entry(snap_a)
            entry_b = _get_entry(snap_b)

            tc_a = dict(entry_a.get("token_counts", {}) or {})
            tc_b = dict(entry_b.get("token_counts", {}) or {})
            cci_a = _cci_from_entry(entry_a)
            cci_b = _cci_from_entry(entry_b)

            js_val = _js_divergence(tc_a, tc_b)
            cci_drift = abs(cci_a - cci_b)
            js_values.append(js_val)
            cci_drifts.append(cci_drift)

            generation_a = _extract_generation_from_filename(snap_a)
            generation_b = _extract_generation_from_filename(snap_b)

            per_snapshot_rows.append(_make_per_snapshot_row(
                experiment="temporal_sweep",
                snapshot_path=snap_a,
                generation=generation_a,
                parameter_combination={
                    "gap_label": gap_label,
                    "gap_index_stride": gap_stride,
                    "snapshot_b": snap_b.name,
                    "generation_b": generation_b,
                    "generation_diff": generation_b - generation_a,
                },
                metrics={
                    "js_divergence_bits": js_val,
                    "cci_drift": cci_drift,
                    "cci_a": cci_a,
                    "cci_b": cci_b,
                },
                run_metadata={
                    # Both endpoints' patches_processed; deterministic.
                    # elapsed_seconds intentionally omitted (wallclock).
                    "patches_processed_a": entry_a.get("budget", {}).get(
                        "patches_processed"
                    ),
                    "patches_processed_b": entry_b.get("budget", {}).get(
                        "patches_processed"
                    ),
                },
                calibration_set=calibration_set,
            ))

        if js_values:
            js_stats = _temporal_pair_stats(js_values)
            drift_stats = _temporal_pair_stats(cci_drifts)
            per_gap_summary[gap_label] = {
                "n_pairs": len(js_values),
                "index_stride": gap_stride,
                "mean_js_divergence_bits": js_stats["mean"],
                "std_js_divergence_bits": js_stats["std"],
                "max_js_divergence_bits": js_stats["max"],
                "mean_cci_drift": drift_stats["mean"],
                "std_cci_drift": drift_stats["std"],
                "max_cci_drift": drift_stats["max"],
            }
        else:
            per_gap_summary[gap_label] = {
                "n_pairs": 0,
                "index_stride": gap_stride,
            }

    # --- Falsification status — largest gap (last in gap_specs by convention)
    falsification_status: str = "inconclusive"
    falsification_evidence: dict[str, Any] = {
        "js_falsification_threshold_bits": _TEMPORAL_DRIFT_JS_THRESHOLD_BITS,
        "js_attractor_threshold_bits": _TEMPORAL_DRIFT_ATTRACTOR_JS_THRESHOLD_BITS,
    }
    largest_gap_label = gap_specs[-1][0]
    largest_summary = per_gap_summary.get(largest_gap_label, {})
    if largest_summary.get("n_pairs", 0) > 0:
        largest_mean_js = largest_summary["mean_js_divergence_bits"]
        falsification_evidence["largest_gap_label"] = largest_gap_label
        falsification_evidence["largest_gap_mean_js"] = largest_mean_js
        if largest_mean_js > _TEMPORAL_DRIFT_JS_THRESHOLD_BITS:
            falsification_status = "hypothesis_falsified"
        elif largest_mean_js < _TEMPORAL_DRIFT_ATTRACTOR_JS_THRESHOLD_BITS:
            falsification_status = "hypothesis_supported"
        else:
            falsification_status = "inconclusive"
            falsification_evidence["reason"] = (
                "mean JS at the largest gap falls between the attractor "
                "threshold and the falsification threshold; neither "
                "obviously stable nor obviously drifting"
            )
    else:
        falsification_evidence["reason"] = (
            f"largest gap {largest_gap_label!r} produced 0 pairs "
            f"(too few snapshots for the requested index_stride)"
        )

    extra_fields: dict[str, Any] = {
        "gap_specs": [list(g) for g in gap_specs],
        "per_gap_summary": per_gap_summary,
        "falsification_evidence": falsification_evidence,
    }

    aggregate = _make_aggregate_row(
        experiment="temporal_sweep",
        calibration_set=calibration_set,
        n_snapshots=len(sorted_snapshots),
        extra_fields=extra_fields,
        falsification_status=falsification_status,
    )

    _write_calibration_jsonl(out_path, per_snapshot_rows, aggregate)
    return aggregate


# ---------------------------------------------------------------------------
# Chapter 8 — sweep_patch_radius (design doc §3.3, Jack #8 in implementation order)
# ---------------------------------------------------------------------------


#: Default patch radii to compare. Radius 1 is the PR #142 baseline
#: (3x3x3 = 27 cells per patch); radius 2 is the coarse-grained variant
#: (5x5x5 = 125 cells per patch).
DEFAULT_PATCH_RADII: tuple[int, ...] = (1, 2)

#: The canonical baseline radius (matches PR #142 + every prior chapter).
#: Used as the reference against which other radii are compared in the
#: §3.3 falsification criterion.
PATCH_RADIUS_BASELINE: int = 1

#: §3.3 falsification threshold: absolute CCI difference between any
#: non-baseline radius and the baseline that exceeds this value indicates
#: the baseline carries scale-specific structure (a patch-size artefact)
#: rather than a real scale-robust feature.
_PATCH_RADIUS_CCI_FALSIFICATION_THRESHOLD: float = 0.10

#: Cell-count thresholds in the observer module that scale linearly with
#: patch volume. ``ENERGY_PULSE_MIN_COUNT`` is currently the only such
#: threshold post-#144: ``DIVERSITY_BOUNDARY`` is bounded by the state
#: alphabet (5 states max), and the ``compute_count >= 1`` /
#: ``sensor_count >= 1`` style predicates are intentionally minimum-
#: presence checks that don't rescale. ``THRESHOLD_WARMTH``, ``AGE_*``,
#: and ``FRACTION_*`` predicates are already scale-invariant.
_COUNT_THRESHOLDS_TO_RESCALE: tuple[str, ...] = (
    "ENERGY_PULSE_MIN_COUNT",
)


def _patch_cell_count(radius: int) -> int:
    """Number of cells in a patch of the given Moore-neighbourhood radius."""
    return (2 * radius + 1) ** 3


def _rescale_count_threshold_for_radius(
    baseline_value: int,
    baseline_radius: int,
    new_radius: int,
) -> int:
    """Linear rescaling of a cell-count threshold by patch volume ratio.

    A patch of radius ``r`` has ``(2r+1)^3`` cells. The threshold scales
    proportionally so the *fraction* of cells required stays constant
    across radii. Result is rounded to the nearest integer and clamped
    to a minimum of 1 (a count threshold of 0 would be a no-op).

    Example: baseline ``ENERGY_PULSE_MIN_COUNT=3`` at radius 1 (27 cells,
    fraction 3/27 = 0.111) rescales at radius 2 (125 cells) to
    ``round(3 * 125/27) = round(13.89) = 14`` (fraction 14/125 = 0.112,
    matching baseline within rounding).
    """
    baseline_volume = _patch_cell_count(baseline_radius)
    new_volume = _patch_cell_count(new_radius)
    rescaled = round(baseline_value * new_volume / baseline_volume)
    return max(1, rescaled)


def _clone_config_with_radius(
    base_config: ObserverConfig,
    radius: int,
) -> ObserverConfig:
    """Return a copy of ``base_config`` with ``patch_spatial_radius=radius``.

    Mirrors :func:`_clone_config_with_stride` from Chapter 4 — uses
    ``dataclasses.replace`` since ``ObserverConfig`` is frozen. Any
    invariants on the new radius value (e.g., positive int) are enforced
    by ``ObserverConfig.__post_init__`` at construction time, so invalid
    combinations raise here rather than deep in the sweep loop.
    """
    return dataclasses.replace(base_config, patch_spatial_radius=radius)


def sweep_patch_radius(
    snapshots: list[pathlib.Path],
    out_path: pathlib.Path,
    log_path: pathlib.Path,
    calibration_set: str,
    config: ObserverConfig,
    radii: tuple[int, ...] = DEFAULT_PATCH_RADII,
) -> dict[str, Any]:
    """Patch-size / coarse-graining check per design doc §3.3.

    For each (snapshot, radius) pair:
      1. Clone ``ObserverConfig`` with ``patch_spatial_radius=radius``.
      2. Monkey-patch the count-based observer thresholds listed in
         ``_COUNT_THRESHOLDS_TO_RESCALE`` to their volume-proportional
         values at the new radius. Same try/finally restore pattern as
         Chapter 5 (sweep_threshold).
      3. Call ``process_snapshot()`` and capture per-snapshot metrics
         (vocabulary_occupancy, shannon_entropy_bits, entropy_normalized,
         void_compute_balance, boundary_rate) plus CCI and the full
         ``token_counts`` distribution for cross-radius comparison.
      4. Restore original threshold values.

    Per Jack Chapter 8 guardrails from PR #153 review:
      - Patch-radius / coarse-graining check ONLY
      - Compare radius 1 vs radius 2
      - Rescale ONLY count thresholds that truly need rescaling
        (currently just ``ENERGY_PULSE_MIN_COUNT``)
      - No engine touch, no CLI, no Lane A, no predicate redesign
        beyond what the radius comparison requires
      - No final "ignition" claim

    Mechanical falsification_status per §3.3:

      - ``"hypothesis_supported"``: |CCI(non-baseline) - CCI(baseline)|
        stays at or below ``_PATCH_RADIUS_CCI_FALSIFICATION_THRESHOLD``
        (= 0.10) for every non-baseline radius. The phenomenon is
        scale-robust; the 3x3x3 baseline is not a patch-size artefact.
      - ``"hypothesis_falsified"``: at least one non-baseline radius
        produces |CCI diff| > 0.10. The baseline carries scale-specific
        structure and needs reframing in a future PR.
      - ``"inconclusive"``: ``PATCH_RADIUS_BASELINE`` not in ``radii``
        (no reference to compare against), no snapshots, or only the
        baseline radius requested.

    Args:
        snapshots: list of sandboxed ``.npz`` paths.
        out_path: where to write the radius-sweep JSONL.
        log_path: write-boundary anchor.
        calibration_set: ``"short"`` or ``"long"``.
        config: base ``ObserverConfig``; ``patch_spatial_radius`` is
            overridden per sweep radius. Other fields preserved.
        radii: tuple of integer radii to sweep. Defaults to
            :data:`DEFAULT_PATCH_RADII` = ``(1, 2)``. Must all be
            positive integers; baseline radius (``PATCH_RADIUS_BASELINE``
            = 1) should be included or the falsification criterion is
            undefined and the run falls back to ``inconclusive``.

    Returns the aggregate dict for callers that want to inspect it
    without re-reading the output file.

    Raises:
        :class:`WriteOutsideLogDirError` if ``out_path`` is outside log dir
            or ``config.log_directory`` diverges from ``log_path.parent``.
        ``ValueError`` for invalid calibration_set, empty radii, or
            non-positive radius values.
    """
    # Lazy import of the observer module so we can monkeypatch its
    # count threshold attributes. Same pattern as sweep_threshold (Ch5)
    # and ablate_cascade (Ch6); only here within try/finally.
    from scripts import nextness_observer as _observer_module

    if calibration_set not in {"short", "long"}:
        raise ValueError(
            f"calibration_set must be 'short' or 'long', got {calibration_set!r}"
        )
    if not radii:
        raise ValueError("radii must be non-empty")
    for r in radii:
        if not isinstance(r, int) or r <= 0:
            raise ValueError(f"every radius must be a positive int, got {r!r}")

    out_path = pathlib.Path(out_path)
    log_path = pathlib.Path(log_path)
    _validate_calibration_output_path(out_path, log_path)
    _validate_config_log_directory(config, log_path)

    sorted_snapshots = _sort_snapshots_by_generation(list(snapshots))

    # Snapshot the baseline values of count thresholds so we can rescale
    # them per-radius. ENERGY_PULSE_MIN_COUNT is the only entry today;
    # the loop generalises if more get added.
    baseline_threshold_values: dict[str, int] = {
        name: int(getattr(_observer_module, name))
        for name in _COUNT_THRESHOLDS_TO_RESCALE
    }

    per_snapshot_rows: list[dict[str, Any]] = []
    # Per-radius aggregator: radius -> list of {snapshot, metrics, cci,
    # rescaled_thresholds, token_counts}.
    by_radius: dict[int, list[dict[str, Any]]] = {r: [] for r in radii}

    for snap in sorted_snapshots:
        generation = _extract_generation_from_filename(snap)
        for radius in radii:
            radius_config = _clone_config_with_radius(config, radius)

            # Compute rescaled threshold values for this radius.
            rescaled = {
                name: _rescale_count_threshold_for_radius(
                    baseline_value=baseline_threshold_values[name],
                    baseline_radius=PATCH_RADIUS_BASELINE,
                    new_radius=radius,
                )
                for name in _COUNT_THRESHOLDS_TO_RESCALE
            }

            # Monkey-patch + restore. Single-threaded by construction
            # (calibration is sequential).
            originals = {
                name: getattr(_observer_module, name)
                for name in _COUNT_THRESHOLDS_TO_RESCALE
            }
            try:
                for name, value in rescaled.items():
                    setattr(_observer_module, name, value)
                entry = process_snapshot(snap, radius_config, medusa_is_live=False)
            finally:
                for name, value in originals.items():
                    setattr(_observer_module, name, value)

            cci_value = _cci_from_entry(entry)
            token_counts = dict(entry.get("token_counts", {}) or {})
            metrics = _extract_metrics_subset(entry)
            metrics["cci"] = cci_value

            per_snapshot_rows.append(_make_per_snapshot_row(
                experiment="patch_radius_sweep",
                snapshot_path=snap,
                generation=generation,
                parameter_combination={
                    "patch_spatial_radius": radius,
                    "patch_cell_count": _patch_cell_count(radius),
                    "rescaled_count_thresholds": dict(sorted(rescaled.items())),
                },
                metrics=metrics,
                run_metadata={
                    # patches_processed is deterministic; elapsed_seconds
                    # excluded per the Chapter 4 byte-identical pattern.
                    "patches_processed": entry.get("budget", {}).get(
                        "patches_processed"
                    ),
                },
                calibration_set=calibration_set,
            ))

            by_radius[radius].append({
                "snapshot": snap.name,
                "metrics": metrics,
                "token_counts": token_counts,
            })

    # --- Per-radius summary statistics ---
    per_radius_summary: dict[str, Any] = {}
    for radius, runs in by_radius.items():
        if not runs:
            per_radius_summary[str(radius)] = {"n_snapshots": 0}
            continue
        voc_occs = [r["metrics"]["vocabulary_occupancy"] for r in runs]
        ccis = [r["metrics"]["cci"] for r in runs]
        boundary_rates = [r["metrics"]["boundary_rate"] for r in runs]
        per_radius_summary[str(radius)] = {
            "n_snapshots": len(runs),
            "patch_cell_count": _patch_cell_count(radius),
            "mean_vocabulary_occupancy": sum(voc_occs) / len(voc_occs),
            "mean_cci": sum(ccis) / len(ccis),
            "mean_boundary_rate": sum(boundary_rates) / len(boundary_rates),
        }

    # --- Cross-radius diffs (vs baseline) ---
    cross_radius_diffs: dict[str, float] = {}
    if PATCH_RADIUS_BASELINE in by_radius and by_radius[PATCH_RADIUS_BASELINE]:
        baseline_cci = per_radius_summary[str(PATCH_RADIUS_BASELINE)]["mean_cci"]
        baseline_voc = per_radius_summary[str(PATCH_RADIUS_BASELINE)][
            "mean_vocabulary_occupancy"
        ]
        for radius in radii:
            if radius == PATCH_RADIUS_BASELINE:
                continue
            radius_cci = per_radius_summary[str(radius)]["mean_cci"]
            radius_voc = per_radius_summary[str(radius)]["mean_vocabulary_occupancy"]
            cross_radius_diffs[f"cci_diff_r{radius}_vs_r{PATCH_RADIUS_BASELINE}"] = (
                radius_cci - baseline_cci
            )
            cross_radius_diffs[f"voc_occ_diff_r{radius}_vs_r{PATCH_RADIUS_BASELINE}"] = (
                radius_voc - baseline_voc
            )

    # --- Falsification status (§3.3 |CCI diff| > 0.10 criterion) ---
    falsification_status: str = "inconclusive"
    falsification_evidence: dict[str, Any] = {
        "baseline_radius": PATCH_RADIUS_BASELINE,
        "cci_falsification_threshold": _PATCH_RADIUS_CCI_FALSIFICATION_THRESHOLD,
    }
    non_baseline_radii = [r for r in radii if r != PATCH_RADIUS_BASELINE]

    if not sorted_snapshots:
        falsification_evidence["reason"] = "no snapshots provided"
    elif PATCH_RADIUS_BASELINE not in by_radius or not by_radius[PATCH_RADIUS_BASELINE]:
        falsification_evidence["reason"] = (
            f"baseline radius {PATCH_RADIUS_BASELINE} not in radii; "
            f"falsification criterion needs a reference value"
        )
    elif not non_baseline_radii:
        falsification_evidence["reason"] = (
            "only baseline radius requested; no comparison radius to test against"
        )
    else:
        # Max |CCI diff| across all non-baseline radii.
        max_abs_cci_diff = 0.0
        max_abs_diff_radius: int | None = None
        per_radius_abs_diff: dict[str, float] = {}
        for r in non_baseline_radii:
            diff_key = f"cci_diff_r{r}_vs_r{PATCH_RADIUS_BASELINE}"
            abs_diff = abs(cross_radius_diffs.get(diff_key, 0.0))
            per_radius_abs_diff[str(r)] = abs_diff
            if abs_diff > max_abs_cci_diff:
                max_abs_cci_diff = abs_diff
                max_abs_diff_radius = r
        falsification_evidence["per_radius_abs_cci_diff"] = per_radius_abs_diff
        falsification_evidence["max_abs_cci_diff"] = max_abs_cci_diff
        falsification_evidence["max_abs_diff_radius"] = max_abs_diff_radius
        if max_abs_cci_diff > _PATCH_RADIUS_CCI_FALSIFICATION_THRESHOLD:
            falsification_status = "hypothesis_falsified"
        else:
            falsification_status = "hypothesis_supported"

    extra_fields: dict[str, Any] = {
        "radii_swept": list(radii),
        "baseline_radius": PATCH_RADIUS_BASELINE,
        "rescaled_threshold_names": list(_COUNT_THRESHOLDS_TO_RESCALE),
        "baseline_threshold_values": baseline_threshold_values,
        "per_radius_summary": per_radius_summary,
        "cross_radius_diffs": cross_radius_diffs,
        "falsification_evidence": falsification_evidence,
    }

    aggregate = _make_aggregate_row(
        experiment="patch_radius_sweep",
        calibration_set=calibration_set,
        n_snapshots=len(sorted_snapshots),
        extra_fields=extra_fields,
        falsification_status=falsification_status,
    )

    _write_calibration_jsonl(out_path, per_snapshot_rows, aggregate)
    return aggregate


__all__ = [
    "CANONICAL_STRIDE",
    "DEFAULT_ABLATION_DISABLED_TOKENS",
    "DEFAULT_CANONICAL_SEED",
    "DEFAULT_GAP_SPECS_LONG",
    "DEFAULT_GAP_SPECS_SHORT",
    "DEFAULT_PATCH_RADII",
    "DEFAULT_STRIDES",
    "DEFAULT_THRESHOLD_MULTIPLIERS",
    "DEFAULT_THRESHOLD_NAME",
    "DEFAULT_VARIANCE_SEEDS",
    "EXPECTED_MEMORY_CHANNELS",
    "EXPECTED_MEMORY_DTYPE",
    "PATCH_RADIUS_BASELINE",
    "SHUFFLE_MODES",
    "SPARSITY_EPSILON",
    "ablate_cascade",
    "check_determinism",
    "shuffle_test",
    "sweep_patch_radius",
    "sweep_stride",
    "sweep_temporal",
    "sweep_threshold",
    "verify_memory_channels",
]
