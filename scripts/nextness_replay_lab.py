"""Offline replay laboratory over recorded Nextness logs (NP6).

Replays one recorded ``nextness_runs.jsonl`` log through NP2's own
abstention decision procedure, step by step across the chronological
holdout, for a small operator-specified set of monitor configurations —
and reports each configuration's abstention TRAJECTORY side by side.

This answers the recovery-after-surprise question at a granularity the
NP5 evaluator cannot reach from receipts alone: *at which holdout step
does the monitor first stop abstaining, does it re-abstain after a
regime change, and how long does reorientation take* — per
configuration, over the same immutable recording.

LABORATORY OBSERVATIONS ONLY (load-bearing):

- Comparisons are descriptive. No configuration is ranked, selected,
  recommended, "improved" or applied to anything; configurations are
  reported in exactly the operator's input order and abstention is
  preserved as a first-class outcome, never treated as a defect.
- No engine parameter is read, searched or written. The only inputs are
  one recorded log and one explicit protocol file; the operator writes
  every configuration by hand — the lab never generates, perturbs or
  optimizes them.
- Nothing here is, or is evidence of, awareness, consciousness,
  phenomenology or biological equivalence.

No new prediction or decision semantics: the replay reuses NP1's public
sequence reader, split arithmetic and distribution builders and NP2's
public ``decide_abstention`` / ``rolling_ece`` / ``canonical_top`` and
``nextness_metrics.js_divergence``. A regression test locks the
replay's final step to what ``observations_from_log`` +
``build_receipt`` produce for the same configuration, so bridge drift
cannot pass silently.

Safety contract (Lane B, mirrors NP1/NP2/NP5):

- Offline only; reads exactly two files (log + protocol), both through
  hard bounds; READ-ONLY with respect to both (tested byte-for-byte,
  including through the CLI). An ``--output`` aliasing either input is
  refused by resolved path AND by file identity (samefile: covers
  existing hard links and symlink targets). Residual race documented in
  validate_output_path: identity is checked at validation time, not
  re-checked at write time.
- Bounded work: at most ``MAX_LAB_CONFIGS`` configurations and
  ``MAX_REPLAY_STEPS`` holdout steps (fail closed above — never a
  silent truncation of the trajectory); protocol files are bounded
  before parsing.
- Writes permitted ONLY inside the resolved input-log directory
  (``WriteOutsideLogDirError`` otherwise) and NEVER inside the
  repository ``data/`` tree; default output is stdout.
- Deterministic output: sorted keys, fixed schema, no wall-clock
  timestamps, no random identifiers, no absolute paths; provenance is
  the SHA-256 of the protocol file's raw bytes and of the accepted
  dominant-token sequence (the log enters the computation only through
  that sequence). Byte-identical across repeated runs; 64 KiB
  fail-closed ceiling.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import sys
from collections.abc import Mapping, Sequence
from typing import Any, Final

from scripts.nextness_metrics import js_divergence
from scripts.nextness_monitor import (
    ABSTAIN_REASONS,
    MODEL_ALLOWLIST,
    MonitorConfig,
    canonical_top,
    decide_abstention,
    rolling_ece,
)
from scripts.nextness_observer import WriteOutsideLogDirError
from scripts.nextness_predictor import (
    HOLDOUT_FRACTION_DEFAULT,
    HOLDOUT_FRACTION_MAX,
    HOLDOUT_FRACTION_MIN,
    MAX_LINE_BYTES_DEFAULT,
    MAX_ROWS_CEILING,
    MAX_ROWS_DEFAULT,
    SMOOTHING_DEFAULT,
    SMOOTHING_MAX,
    InsufficientHistoryError,
    empirical_prior_distribution,
    first_order_distribution,
    persistence_distribution,
    read_dominant_sequence,
    transition_counts,
)

# ---------------------------------------------------------------------------
# Fixed contract constants
# ---------------------------------------------------------------------------

LAB_SCHEMA: Final[str] = "nextness-replay-lab-v1"
PROTOCOL_SCHEMA: Final[str] = "nextness-replay-protocol-v1"

#: Hard bound on configurations per protocol (an ablation is a handful
#: of hand-written regimes, not a parameter search).
MAX_LAB_CONFIGS: Final[int] = 8

#: Hard bound on replayed holdout steps. Per-step rolling statistics
#: cost O(steps x window); this bound keeps the whole replay cheap and
#: is FAIL CLOSED — a longer holdout is refused, never silently
#: truncated (dropping early steps would misstate the trajectory).
MAX_REPLAY_STEPS: Final[int] = 2_000

#: Pre-parse ceiling for the protocol file.
MAX_PROTOCOL_BYTES: Final[int] = 64 * 1024

#: Output ceiling — fail closed (same convention as NP1/NP2/NP5).
MAX_LAB_REPORT_BYTES: Final[int] = 64 * 1024

#: Completed-run detail lists are capped WITH an explicit flag.
MAX_DETAIL_ITEMS: Final[int] = 128

#: Configuration labels are operator-chosen display names.
MAX_LABEL_CHARS: Final[int] = 64

NON_CLAIMS: Final[tuple[str, ...]] = (
    "Laboratory observations over one immutable recording: comparisons "
    "are descriptive, no configuration is ranked, selected, recommended "
    "or applied.",
    "Abstention is preserved as a first-class outcome, not treated as a "
    "defect to eliminate.",
    "No engine parameter is read, searched or written; no awareness, "
    "consciousness, phenomenology or biological-equivalence claim is "
    "made or implied.",
)

_PROTOCOL_KEYS: Final[frozenset[str]] = frozenset(
    {"schema", "model", "smoothing", "holdout_fraction", "configurations"}
)
_CONFIGURATION_KEYS: Final[frozenset[str]] = frozenset(
    {"label", "min_history", "window", "low_confidence_threshold",
     "calibration_error_threshold", "drift_threshold_bits"}
)


class LabInputError(ValueError):
    """A malformed, hostile or out-of-bounds protocol/log input (fail closed)."""


class LabReportTooLargeError(RuntimeError):
    """Serialized lab report exceeded MAX_LAB_REPORT_BYTES (fail closed)."""


# ---------------------------------------------------------------------------
# Protocol loading and validation (exact-type, fail-closed)
# ---------------------------------------------------------------------------


def _exact_str(value: Any, field: str) -> str:
    if type(value) is not str:
        raise LabInputError(f"{field}: expected builtin str, got {type(value).__name__}")
    return value


def _exact_int(value: Any, field: str) -> int:
    if type(value) is not int:
        raise LabInputError(f"{field}: expected builtin int, got {type(value).__name__}")
    return value


def _exact_real(value: Any, field: str) -> float:
    if type(value) is not int and type(value) is not float:
        raise LabInputError(
            f"{field}: expected a builtin real number, got {type(value).__name__}"
        )
    try:
        as_float = float(value)
    except (OverflowError, ValueError) as e:
        raise LabInputError(f"{field}: not representable as a finite float") from e
    if not math.isfinite(as_float):
        raise LabInputError(f"{field}: not finite")
    return as_float


def _exact_dict(value: Any, field: str, keys: frozenset[str]) -> dict[str, Any]:
    if type(value) is not dict:
        raise LabInputError(f"{field}: expected builtin dict, got {type(value).__name__}")
    present = set(value)
    if present != keys:
        unknown = sorted(k if type(k) is str else f"<{type(k).__name__}>" for k in present - keys)
        missing = sorted(keys - present)
        raise LabInputError(
            f"{field}: key set mismatch (unknown={unknown}, missing={missing})"
        )
    return value


def load_protocol(path: pathlib.Path) -> dict[str, Any]:
    """Bounded read + exact-type validation of one protocol file.

    Returns ``{"model", "smoothing", "holdout_fraction", "configs",
    "sha256"}`` where ``configs`` is a list of ``(label,
    MonitorConfig)`` pairs in input order. Threshold validation is
    delegated to NP2's own ``MonitorConfig.validate`` so the lab can
    never accept a configuration the monitor itself would reject.
    """
    with path.open("rb") as f:
        raw = f.read(MAX_PROTOCOL_BYTES + 1)
    if len(raw) > MAX_PROTOCOL_BYTES:
        raise LabInputError(f"protocol exceeds {MAX_PROTOCOL_BYTES} bytes; refusing to parse")

    def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        # A protocol is operator-authored: a duplicate key means two
        # conflicting values were written and last-wins would silently
        # pick one. Ambiguous variants fail closed instead.
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise LabInputError(f"protocol: duplicate JSON key {key!r}")
            out[key] = value
        return out

    try:
        parsed = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_no_duplicate_keys)
    except LabInputError:
        raise  # keep the precise duplicate-key message
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as e:
        raise LabInputError(f"protocol is not valid UTF-8 JSON: {e}") from e
    except RecursionError as e:
        raise LabInputError("protocol nesting exceeds the parser's depth limit") from e

    outer = _exact_dict(parsed, "protocol", _PROTOCOL_KEYS)
    schema = _exact_str(outer["schema"], "protocol.schema")
    if schema != PROTOCOL_SCHEMA:
        raise LabInputError(
            f"protocol.schema: unknown variant {schema!r} (expected {PROTOCOL_SCHEMA!r})"
        )
    model = _exact_str(outer["model"], "protocol.model")
    if model not in MODEL_ALLOWLIST:
        raise LabInputError(f"protocol.model: {model!r} not in fixed allowlist")
    smoothing = _exact_real(outer["smoothing"], "protocol.smoothing")
    if not 0.0 < smoothing <= SMOOTHING_MAX:
        raise LabInputError(
            f"protocol.smoothing: must be in (0, {SMOOTHING_MAX}], got {smoothing}"
        )
    holdout_fraction = _exact_real(outer["holdout_fraction"], "protocol.holdout_fraction")
    if not HOLDOUT_FRACTION_MIN <= holdout_fraction <= HOLDOUT_FRACTION_MAX:
        raise LabInputError(
            f"protocol.holdout_fraction: must be in [{HOLDOUT_FRACTION_MIN}, "
            f"{HOLDOUT_FRACTION_MAX}], got {holdout_fraction}"
        )

    raw_configs = outer["configurations"]
    if type(raw_configs) is not list or not raw_configs:
        raise LabInputError("protocol.configurations: expected a non-empty array")
    if len(raw_configs) > MAX_LAB_CONFIGS:
        raise LabInputError(
            f"protocol.configurations: {len(raw_configs)} configurations exceed "
            f"the {MAX_LAB_CONFIGS} bound"
        )
    configs: list[tuple[str, MonitorConfig]] = []
    seen_labels: set[str] = set()
    for i, item in enumerate(raw_configs):
        entry = _exact_dict(item, f"protocol.configurations[{i}]", _CONFIGURATION_KEYS)
        label = _exact_str(entry["label"], f"protocol.configurations[{i}].label")
        if not label or len(label) > MAX_LABEL_CHARS:
            raise LabInputError(
                f"protocol.configurations[{i}].label: length must be in [1, {MAX_LABEL_CHARS}]"
            )
        if label in seen_labels:
            raise LabInputError(f"protocol.configurations[{i}].label: duplicate {label!r}")
        seen_labels.add(label)
        cfg = MonitorConfig(
            min_history=_exact_int(entry["min_history"], f"protocol.configurations[{i}].min_history"),
            window=_exact_int(entry["window"], f"protocol.configurations[{i}].window"),
            low_confidence_threshold=_exact_real(
                entry["low_confidence_threshold"],
                f"protocol.configurations[{i}].low_confidence_threshold",
            ),
            calibration_error_threshold=_exact_real(
                entry["calibration_error_threshold"],
                f"protocol.configurations[{i}].calibration_error_threshold",
            ),
            drift_threshold_bits=_exact_real(
                entry["drift_threshold_bits"],
                f"protocol.configurations[{i}].drift_threshold_bits",
            ),
        )
        try:
            cfg.validate()  # NP2's own bounds — the lab adds none of its own
        except ValueError as e:
            raise LabInputError(f"protocol.configurations[{i}]: {e}") from e
        configs.append((label, cfg))

    return {
        "model": model,
        "smoothing": smoothing,
        "holdout_fraction": holdout_fraction,
        "configs": configs,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


# ---------------------------------------------------------------------------
# The replay: NP2's bridge semantics, one decision per holdout step
# ---------------------------------------------------------------------------


def replay_observations(
    sequence: Sequence[str],
    model: str,
    *,
    smoothing: float,
    holdout_fraction: float,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Rebuild NP2's bridge observations for one model over one sequence.

    Returns ``(observations, train, holdout)``. This mirrors
    ``nextness_monitor.observations_from_log`` exactly (same split
    arithmetic, same distribution builders, same prev_seen semantics);
    the equivalence-lock test in the suite compares the two end-to-end
    so any silent divergence fails loudly.
    """
    if model not in MODEL_ALLOWLIST:
        # Fail closed like the bridge it mirrors — an unknown model must
        # never silently fall through to first_order semantics.
        raise LabInputError(f"model {model!r} not in fixed allowlist {MODEL_ALLOWLIST}")
    n = len(sequence)
    split = math.floor(n * (1.0 - holdout_fraction))
    train, holdout = list(sequence[:split]), list(sequence[split:])
    if len(train) < 2 or len(holdout) < 1:
        raise InsufficientHistoryError(
            f"need >=2 train and >=1 holdout rows; got train={len(train)}, "
            f"holdout={len(holdout)}"
        )
    prior = empirical_prior_distribution(train, smoothing)
    table = transition_counts(train)
    train_tokens = set(train)
    previous_tokens = [train[-1]] + holdout[:-1]

    observations: list[dict[str, Any]] = []
    for prev, actual in zip(previous_tokens, holdout):
        if model == "empirical_prior":
            dist = prior
            prev_seen = prev in train_tokens
        elif model == "persistence":
            dist = persistence_distribution(prev, smoothing)
            prev_seen = prev in train_tokens
        else:
            dist = first_order_distribution(prev, table, prior, smoothing)
            prev_seen = prev in table
        top = canonical_top(dist)
        observations.append(
            {
                "confidence": dist[top],
                "hit": top == actual,
                "p_actual": dist[actual],
                "prev_seen": prev_seen,
            }
        )
    return observations, train, holdout


def _token_counts(tokens: Sequence[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in tokens:
        out[t] = out.get(t, 0) + 1
    return out


def replay_trajectory(
    observations: Sequence[Mapping[str, Any]],
    train: Sequence[str],
    holdout: Sequence[str],
    config: MonitorConfig,
) -> list[tuple[bool, str]]:
    """One (abstain, reason) decision per holdout step.

    At step t (1-based) the monitor has seen exactly the first t bridge
    observations; rolling ECE runs over the last ``window`` of them and
    drift compares the training reference against the last ``window``
    holdout tokens — precisely NP2's receipt semantics evaluated at
    every prefix instead of only the full holdout.
    """
    reference = _token_counts(train)
    decisions: list[tuple[bool, str]] = []
    for t in range(1, len(observations) + 1):
        prefix = observations[:t]
        window_slice = prefix[-config.window:]
        ece = rolling_ece(window_slice)
        recent = _token_counts(holdout[max(0, t - config.window):t])
        drift = js_divergence(reference, recent)
        decisions.append(
            decide_abstention(
                observation_count=t,
                latest_confidence=prefix[-1]["confidence"],
                latest_prev_seen=prefix[-1]["prev_seen"],
                rolling_calibration_error=ece,
                drift_bits=drift,
                config=config,
            )
        )
    return decisions


def summarize_trajectory(decisions: Sequence[tuple[bool, str]]) -> dict[str, Any]:
    """Deterministic bounded summary of one configuration's trajectory."""
    steps = len(decisions)
    abstained = sum(1 for abstain, _ in decisions if abstain)
    reason_counts = {reason: 0 for reason in ABSTAIN_REASONS}
    for _, reason in decisions:
        reason_counts[reason] += 1

    first_non_abstain: int | None = None
    for i, (abstain, _) in enumerate(decisions):
        if not abstain:
            first_non_abstain = i + 1  # 1-based step index
            break

    onsets = 0
    reorientations = 0
    run_lengths: list[int] = []
    current_run = 1 if decisions[0][0] else 0
    for (prev_a, _), (curr_a, _) in zip(decisions, decisions[1:]):
        if not prev_a and curr_a:
            onsets += 1
            current_run = 1
        elif prev_a and curr_a:
            current_run += 1
        elif prev_a and not curr_a:
            reorientations += 1
            run_lengths.append(current_run)
            current_run = 0
    trailing = current_run if decisions[-1][0] else None

    final_abstain, final_reason = decisions[-1]
    return {
        "step_count": steps,
        "abstention_step_rate": abstained / steps,
        "reason_step_counts": reason_counts,
        "first_non_abstain_step": first_non_abstain,
        "abstention_onsets": onsets,
        "reorientations": reorientations,
        "completed_abstention_run_lengths_steps": run_lengths[:MAX_DETAIL_ITEMS],
        "run_lengths_truncated": len(run_lengths) > MAX_DETAIL_ITEMS,
        "unresolved_trailing_abstention_steps": trailing,
        "final_abstain": final_abstain,
        "final_reason": final_reason,
    }


# ---------------------------------------------------------------------------
# End-to-end lab report
# ---------------------------------------------------------------------------


def build_lab_report(
    log_path: pathlib.Path,
    protocol_path: pathlib.Path,
    *,
    max_rows: int = MAX_ROWS_DEFAULT,
    max_line_bytes: int = MAX_LINE_BYTES_DEFAULT,
) -> dict[str, Any]:
    """One deterministic ``nextness-replay-lab-v1`` report.

    Configurations are replayed and reported in EXACTLY the protocol's
    input order — there is no ranking, no winner and no recommendation
    field, by contract.
    """
    protocol = load_protocol(protocol_path)
    sequence, rejections, rows_read = read_dominant_sequence(
        log_path, max_rows=max_rows, max_line_bytes=max_line_bytes
    )
    # Replay bound BEFORE any observation allocation: the holdout
    # length is fully determined by the already-bounded sequence length
    # and the protocol's holdout_fraction (the same floor arithmetic
    # replay_observations uses — re-checked against its output below),
    # so an oversized holdout is refused without ever constructing the
    # observation list.
    holdout_len = len(sequence) - math.floor(
        len(sequence) * (1.0 - protocol["holdout_fraction"])
    )
    if holdout_len > MAX_REPLAY_STEPS:
        raise LabInputError(
            f"holdout has {holdout_len} steps, exceeding the {MAX_REPLAY_STEPS} "
            f"replay bound (fail closed; re-record or adjust holdout_fraction "
            f"rather than silently truncating a trajectory)"
        )
    observations, train, holdout = replay_observations(
        sequence,
        protocol["model"],
        smoothing=protocol["smoothing"],
        holdout_fraction=protocol["holdout_fraction"],
    )
    # Split-arithmetic invariant: the early bound and the bridge must
    # never disagree about the holdout length.
    assert len(holdout) == holdout_len

    configurations: list[dict[str, Any]] = []
    for label, cfg in protocol["configs"]:
        decisions = replay_trajectory(observations, train, holdout, cfg)
        configurations.append(
            {
                "label": label,
                "config": {
                    "min_history": cfg.min_history,
                    "window": cfg.window,
                    "low_confidence_threshold": cfg.low_confidence_threshold,
                    "calibration_error_threshold": cfg.calibration_error_threshold,
                    "drift_threshold_bits": cfg.drift_threshold_bits,
                },
                "trajectory": summarize_trajectory(decisions),
            }
        )

    # The log enters the computation only through the accepted
    # dominant-token sequence, so that sequence's hash (plus the row
    # accounting) is the reproduction-sufficient provenance for it.
    sequence_digest = hashlib.sha256("\n".join(sequence).encode("utf-8")).hexdigest()

    report: dict[str, Any] = {
        "schema": LAB_SCHEMA,
        "laboratory_observation": True,
        "config": {
            "max_lab_configs": MAX_LAB_CONFIGS,
            "max_replay_steps": MAX_REPLAY_STEPS,
            "max_rows": max_rows,
            "max_line_bytes": max_line_bytes,
            "model": protocol["model"],
            "smoothing": protocol["smoothing"],
            "holdout_fraction": protocol["holdout_fraction"],
        },
        "input": {
            "rows_read": rows_read,
            "rows_accepted": len(sequence),
            "rows_rejected": sum(rejections.values()),
            "rejections": rejections,
            "train_rows": len(train),
            "holdout_steps": len(holdout),
            "sequence_sha256": sequence_digest,
            "protocol_sha256": protocol["sha256"],
        },
        "configurations": configurations,
        "non_claims": list(NON_CLAIMS),
    }
    serialized = serialize_lab_report(report)
    if len(serialized.encode("utf-8")) > MAX_LAB_REPORT_BYTES:
        raise LabReportTooLargeError(
            f"lab report would exceed {MAX_LAB_REPORT_BYTES} bytes; refusing to emit"
        )
    return report


def serialize_lab_report(report: Mapping[str, Any]) -> str:
    """Canonical serialization: sorted keys, fixed separators, newline."""
    return json.dumps(report, sort_keys=True, separators=(",", ": "), indent=1) + "\n"


# ---------------------------------------------------------------------------
# Write-boundary guard (same convention as NP1/NP5)
# ---------------------------------------------------------------------------


def _repo_data_dir() -> pathlib.Path:
    return (pathlib.Path(__file__).resolve().parent.parent / "data").resolve()


def validate_output_path(
    out_path: pathlib.Path,
    log_path: pathlib.Path,
    protocol_path: pathlib.Path,
) -> None:
    """--output may land ONLY inside the input log's directory, NEVER
    inside the repository ``data/`` tree, and NEVER on a path that IS
    either input file — by resolved path (which also covers symlink
    aliases, including dangling ones: resolution targets are compared,
    not link names) or by file identity (``os.path.samefile``: device +
    inode, which covers existing hard links whose paths differ).

    Residual filesystem race, stated precisely: identity is verified at
    validation time; the later write does not re-verify. A concurrent
    actor replacing the output path between validation and write can
    still redirect the write. The lab defends against aliases that
    exist when it validates — it does not claim protection against
    concurrent hostile filesystem manipulation.
    """
    log_dir_resolved = log_path.resolve().parent
    out_resolved = out_path.resolve()
    try:
        out_resolved.relative_to(log_dir_resolved)
    except ValueError as e:
        raise WriteOutsideLogDirError(
            f"refusing to write lab report outside the input-log directory: "
            f"{out_resolved} is not inside {log_dir_resolved}"
        ) from e
    for label, input_path in (("log", log_path), ("protocol", protocol_path)):
        if out_resolved == input_path.resolve():
            raise WriteOutsideLogDirError(
                f"refusing to overwrite the input {label} file: {out_resolved}"
            )
        # Hard links share identity while having distinct paths. Only an
        # EXISTING output can alias an input; stat runs on the resolved
        # path and any failure to verify is itself a refusal (fail
        # closed), never a fall-through.
        if out_resolved.exists():
            try:
                same = os.path.samefile(out_resolved, input_path)
            except OSError as e:
                raise WriteOutsideLogDirError(
                    f"cannot verify output file identity against the input "
                    f"{label} file: {out_resolved}"
                ) from e
            if same:
                raise WriteOutsideLogDirError(
                    f"refusing to overwrite the input {label} file (shared "
                    f"file identity): {out_resolved}"
                )
    data_dir = _repo_data_dir()
    if out_resolved == data_dir or data_dir in out_resolved.parents:
        raise WriteOutsideLogDirError(
            f"refusing to write lab report inside the repository data/ tree: {out_resolved}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Offline replay laboratory: per-step abstention trajectories for "
            "operator-specified monitor configurations over one recorded "
            "Nextness log (laboratory observations only; see module "
            "docstring for the full contract)."
        )
    )
    parser.add_argument("log_path", type=pathlib.Path, help="path to nextness_runs.jsonl")
    parser.add_argument(
        "protocol_path", type=pathlib.Path,
        help="path to a nextness-replay-protocol-v1 JSON file",
    )
    parser.add_argument(
        "--output", type=pathlib.Path, default=None,
        help=(
            "optional report path; must resolve inside the input log's "
            "directory and outside the repository data/ tree (default: stdout)"
        ),
    )
    parser.add_argument("--max-rows", type=int, default=MAX_ROWS_DEFAULT)
    parser.add_argument("--max-line-bytes", type=int, default=MAX_LINE_BYTES_DEFAULT)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Exit-code contract (mirrors NP1's expected-failure contract):

    - ``0`` success
    - ``2`` validation failure — missing input file, malformed or
      out-of-bounds protocol, or a holdout longer than the replay bound
      (argparse usage errors also exit 2)
    - ``3`` insufficient history for a train/holdout split
    - ``4`` output-path failure — write-boundary violation or an
      unwritable target
    - ``5`` lab report exceeds MAX_LAB_REPORT_BYTES (fail closed)

    Every expected failure prints one concise ``error:`` line to stderr —
    never a traceback. The documented catch set is exactly
    ``WriteOutsideLogDirError``, ``InsufficientHistoryError``,
    ``LabReportTooLargeError``, plain ``ValueError`` (the exit-2 lane,
    which includes ``LabInputError``) and the write-lane ``OSError``;
    exceptions outside it propagate. Because the base ``ValueError``
    class is part of the catch set, no claim is made that every
    programming error propagates.
    """
    args = _build_parser().parse_args(argv)
    for label, path in (("log", args.log_path), ("protocol", args.protocol_path)):
        if not path.is_file():
            print(f"error: {label} file not found: {path}", file=sys.stderr)
            return 2
    try:
        if args.output is not None:
            validate_output_path(args.output, args.log_path, args.protocol_path)
        report = build_lab_report(
            args.log_path,
            args.protocol_path,
            max_rows=args.max_rows,
            max_line_bytes=args.max_line_bytes,
        )
    except WriteOutsideLogDirError as e:
        print(f"error: {e}", file=sys.stderr)
        return 4
    except InsufficientHistoryError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    except LabReportTooLargeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 5
    except ValueError as e:  # includes LabInputError (its subclass)
        print(f"error: {e}", file=sys.stderr)
        return 2
    serialized = serialize_lab_report(report)
    if args.output is not None:
        try:
            # Raw byte write: LF-only on every platform, with no
            # dependence on Path.write_text's newline= parameter (same
            # rationale as the NP5 evaluator).
            args.output.write_bytes(serialized.encode("utf-8"))
        except OSError as e:
            print(f"error: cannot write lab report to {args.output}: {e}", file=sys.stderr)
            return 4
    else:
        sys.stdout.write(serialized)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
