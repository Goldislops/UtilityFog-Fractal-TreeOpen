"""Deterministic next-event baselines over Nextness Observer logs (NP1).

Reads existing ``nextness_runs.jsonl`` rows — never raw snapshots, never
live engine state — and evaluates three transparent baseline predictors
of the *next dominant vocabulary token*:

1. ``empirical_prior``   — smoothed frequency of dominant tokens in the
   training prefix; ignores the previous token entirely.
2. ``persistence``       — predicts "the next dominant token equals the
   previous one", smoothed over the full vocabulary.
3. ``first_order``       — first-order Markov transition model with
   additive (Laplace) smoothing; unseen previous tokens fall back to the
   empirical prior (documented below).

SCOPE OF CLAIM (deliberate, narrow): these are *baselines* whose job is
to make future claims falsifiable. Reporting includes every model, and a
simple baseline winning is a fully expected, fully reported outcome.
Nothing here measures or implies intelligence, awareness or performance
victory. This module contains no learning beyond counting.

Safety contract (Lane B, mirrors nextness_observer/nextness_metrics):

- Offline only: no network, HTTP, ZMQ, Ollama or model calls; the only
  I/O is reading one JSONL file and (optionally) writing one report next
  to it.
- Writes are permitted ONLY inside the resolved input-log directory
  (``WriteOutsideLogDirError`` otherwise), NEVER inside the repository
  ``data/`` tree — reports about ``data/`` logs go to stdout — and NEVER
  onto a path that IS the input log itself: aliases are refused by
  resolved path and by file identity (``os.path.samefile``; hard links
  included), failing closed when identity cannot be verified. Identity
  is checked at validation time; the later write does not re-verify
  (documented residual race, same as NP6/NP8).
- File output is written as explicit UTF-8 BYTES (single trailing LF,
  never platform newline translation): the file always contains exactly
  ``serialize_report(report).encode("utf-8")``.
- Chronological evaluation only: rows must arrive in strictly increasing
  ``generation`` order; out-of-order and duplicate generations are
  rejected and counted, never silently reordered (sorting could hide
  leakage; refusing cannot).
- Defensive parsing: built-in ``dict`` rows only, known vocabulary only,
  finite non-negative numeric counts only (bools rejected explicitly);
  every rejection is counted by reason. Row payloads are never copied
  into the report — only counts.
- Bounded raw work: ``max_rows`` counts every physical input record
  (blank, rejected and accepted alike) and records are read with bounded
  ``readline`` calls so no more than ``max_line_bytes + 2`` bytes of a
  record are ever materialized; the first oversized record is counted
  and terminates ingestion (fail closed). CLI failures for expected
  invalid input exit with documented nonzero codes and concise stderr —
  never a traceback.
- Deterministic output: sorted keys, fixed schema/version, no wall-clock
  timestamps, canonical-order tie-breaking, fixed ECE bins; the same
  input file always produces byte-identical reports.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import sys
from collections.abc import Mapping, Sequence
from typing import Any, Final

from scripts.nextness_observer import TOKEN_NAMES, WriteOutsideLogDirError

# ---------------------------------------------------------------------------
# Fixed contract constants
# ---------------------------------------------------------------------------

REPORT_SCHEMA: Final[str] = "nextness-predictor-v1"

#: Canonical index for deterministic dominant-token tie-breaking: among
#: tied maximal counts the token EARLIEST in TOKEN_NAMES order wins.
_TOKEN_INDEX: Final[dict[str, int]] = {t: i for i, t in enumerate(TOKEN_NAMES)}

#: Hard input bounds (accidental-unbounded-work guards, not tuning knobs).
MAX_ROWS_DEFAULT: Final[int] = 100_000
MAX_ROWS_CEILING: Final[int] = 1_000_000
MAX_LINE_BYTES_DEFAULT: Final[int] = 65_536

#: Hard ceiling on the max_line_bytes PARAMETER itself (16 MiB) —
#: deliberately far above the 65,536-byte default while keeping the
#: bounded probe arithmetic (max_line_bytes + 2) safely representable
#: as an index-sized integer on every platform and preserving an honest
#: per-record resource bound. Owned here; metrics mirrors it
#: (anti-drift test-pinned) and the artifact validators enforce it on
#: recorded configuration values.
MAX_LINE_BYTES_CEILING: Final[int] = 16_777_216

#: Additive (Laplace) smoothing pseudo-count, shared by all three models
#: so their likelihoods are comparable. Documented in the baseline doc;
#: configurable but bounded — smoothing is a floor against log(0), not a
#: fitted parameter.
SMOOTHING_DEFAULT: Final[float] = 1.0
SMOOTHING_MAX: Final[float] = 1_000.0

#: Chronological holdout fraction (tail of the sequence). Bounded so a
#: degenerate split cannot silently produce an empty side.
HOLDOUT_FRACTION_DEFAULT: Final[float] = 0.25
HOLDOUT_FRACTION_MIN: Final[float] = 0.05
HOLDOUT_FRACTION_MAX: Final[float] = 0.5

#: Fixed deterministic ECE binning: 10 equal-width confidence bins over
#: [0, 1]; the final bin is closed above.
ECE_BINS: Final[int] = 10

#: Report size ceiling — fail closed rather than emit an unbounded blob.
MAX_REPORT_BYTES: Final[int] = 64 * 1024

#: Rejection reasons (fixed vocabulary; the report carries ONLY counts).
REJECT_REASONS: Final[tuple[str, ...]] = (
    "oversized_line",
    "malformed_json",
    "not_object",
    "missing_generation",
    "invalid_generation",
    "out_of_order_generation",
    "duplicate_generation",
    "missing_token_counts",
    "invalid_token_counts",
    "unknown_token",
    "invalid_count_value",
    "no_dominant_token",
)


class ReportTooLargeError(RuntimeError):
    """Serialized report exceeded MAX_REPORT_BYTES (fail closed)."""


class InsufficientHistoryError(RuntimeError):
    """Too few accepted rows to form a train/holdout split."""


class PredictorInputError(ValueError):
    """Out-of-bounds public configuration (typed input boundary).

    Subclasses ``ValueError`` so direct-Python callers catching the base
    class remain compatible; the CLI's exit-2 catch names exactly this
    class, so a plain internal ``ValueError`` propagates instead of
    masquerading as an input failure (predictor typed-boundary pilot).
    """


# ---------------------------------------------------------------------------
# Defensive row parsing
# ---------------------------------------------------------------------------


def _valid_count(value: Any) -> bool:
    """A usable token count: real int/float, finite, non-negative.

    ``bool`` is an ``int`` subclass in Python and is rejected explicitly —
    ``True`` counts are a schema violation, not a count of one.
    """
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    return value >= 0


def dominant_token(token_counts: Mapping[str, Any]) -> str | None:
    """The maximal-count token, ties broken by canonical TOKEN_NAMES order.

    Returns ``None`` when no token has a strictly positive count (an
    all-zero row has no dominant event and is rejected upstream). The
    caller is responsible for having validated keys/values first.
    """
    best: str | None = None
    best_count = 0.0
    for token in TOKEN_NAMES:  # canonical order makes ties deterministic
        count = token_counts.get(token, 0)
        if count > best_count:
            best = token
            best_count = count
    return best


def read_dominant_sequence(
    log_path: pathlib.Path,
    *,
    max_rows: int = MAX_ROWS_DEFAULT,
    max_line_bytes: int = MAX_LINE_BYTES_DEFAULT,
) -> tuple[list[str], dict[str, int], int]:
    """Parse the JSONL log into a chronological dominant-token sequence.

    Returns ``(sequence, rejections, rows_read)`` where ``rejections``
    maps every reason in REJECT_REASONS to a count.

    Raw-work bound: ``rows_read`` counts every PHYSICAL input record
    consumed — accepted, rejected and blank alike — so ``max_rows``
    bounds raw input work, not just observations. Blank records are
    neither observations nor violations: they consume row budget without
    appearing in ``rejections``. The accepted-observation count is
    ``len(sequence)`` (reported as ``rows_accepted``).

    Pre-allocation line-size bound: records are ``\\n``-delimited and read
    with bounded ``readline`` calls of at most ``max_line_bytes + 2``
    bytes, so an oversized or unterminated record is never materialized
    in full. A record whose content (raw bytes; LF or CRLF terminator
    excluded) exceeds ``max_line_bytes`` is counted ``oversized_line``
    and TERMINATES ingestion (fail closed): skipping past it would
    require unbounded scanning for the next record boundary. Total read
    work is therefore bounded by ``max_rows * (max_line_bytes + 2)``
    bytes.

    Chronology contract: ``generation`` must be strictly increasing over
    ACCEPTED rows. A row whose generation equals the last accepted one is
    counted ``duplicate_generation``; a smaller one is counted
    ``out_of_order_generation``. Neither is silently reordered.
    """
    if not 0 < max_rows <= MAX_ROWS_CEILING:
        raise PredictorInputError(
            f"max_rows must be in (0, {MAX_ROWS_CEILING}], got {max_rows}"
        )
    # Total line-bound validation: only a non-boolean builtin int in
    # [1, MAX_LINE_BYTES_CEILING] reaches the bounded readline call, so
    # the probe arithmetic (max_line_bytes + 2) can never overflow an
    # index-sized integer — the OverflowError is made unreachable, not
    # caught. Raised BEFORE the input is opened.
    if (isinstance(max_line_bytes, bool) or not isinstance(max_line_bytes, int)
            or not 1 <= max_line_bytes <= MAX_LINE_BYTES_CEILING):
        raise PredictorInputError(
            f"max_line_bytes must be a non-boolean integer in "
            f"[1, {MAX_LINE_BYTES_CEILING}], got {max_line_bytes!r}"
        )

    sequence: list[str] = []
    rejections: dict[str, int] = {reason: 0 for reason in REJECT_REASONS}
    rows_read = 0
    last_generation: int | None = None

    with log_path.open("rb") as f:
        while rows_read < max_rows:
            chunk = f.readline(max_line_bytes + 2)
            if not chunk:
                break  # EOF
            rows_read += 1
            if chunk.endswith(b"\n"):
                # LF or CRLF terminator — excluded from the content bound
                # (a record of exactly max_line_bytes content plus either
                # terminator fits in the max_line_bytes + 2 probe).
                content = chunk[:-2] if chunk.endswith(b"\r\n") else chunk[:-1]
            else:
                # EOF-unterminated record, or a probe that hit the read
                # limit mid-record (already past the bound either way).
                content = chunk
            if len(content) > max_line_bytes:
                # Fail closed: count and stop — never drain or
                # resynchronize past an oversized record.
                rejections["oversized_line"] += 1
                break
            stripped = content.decode("utf-8", errors="replace").strip()
            if not stripped:
                # Blank records are not observations and not violations,
                # but they still consume raw-row budget (bounded work).
                continue
            try:
                row = json.loads(stripped)
            except (json.JSONDecodeError, ValueError, RecursionError):
                # RecursionError: a row nested beyond the parser's depth
                # limit (still inside the byte ceilings). It follows the
                # EXISTING malformed-row containment policy — counted and
                # skipped like any other unparseable row; this is the
                # reader's own row policy, not a family-wide convention.
                # Recursion depth recovers fully once the parser unwinds;
                # RecursionError raised OUTSIDE this decode call is not
                # caught anywhere and still propagates.
                rejections["malformed_json"] += 1
                continue
            # Built-in dict rows only — json.loads only ever produces
            # dicts for objects, so this rejects arrays/scalars, and, for
            # rows injected programmatically in tests, hostile mappings.
            if type(row) is not dict:
                rejections["not_object"] += 1
                continue
            if "generation" not in row:
                rejections["missing_generation"] += 1
                continue
            generation = row["generation"]
            if isinstance(generation, bool) or not isinstance(generation, int):
                rejections["invalid_generation"] += 1
                continue
            if "token_counts" not in row:
                rejections["missing_token_counts"] += 1
                continue
            token_counts = row["token_counts"]
            if type(token_counts) is not dict:
                rejections["invalid_token_counts"] += 1
                continue
            if any(key not in _TOKEN_INDEX for key in token_counts):
                rejections["unknown_token"] += 1
                continue
            if any(not _valid_count(v) for v in token_counts.values()):
                rejections["invalid_count_value"] += 1
                continue
            # Chronology AFTER shape validation so a malformed row can
            # never advance the generation cursor.
            if last_generation is not None:
                if generation == last_generation:
                    rejections["duplicate_generation"] += 1
                    continue
                if generation < last_generation:
                    rejections["out_of_order_generation"] += 1
                    continue
            dominant = dominant_token(token_counts)
            if dominant is None:
                rejections["no_dominant_token"] += 1
                continue
            last_generation = generation
            sequence.append(dominant)

    return sequence, rejections, rows_read


# ---------------------------------------------------------------------------
# The three baselines: each returns P(next token) as a dict over the FULL
# canonical vocabulary, always summing to 1.0 (within float precision).
# ---------------------------------------------------------------------------


def _normalized(weights: Sequence[float]) -> dict[str, float]:
    total = sum(weights)
    return {t: w / total for t, w in zip(TOKEN_NAMES, weights)}


def empirical_prior_distribution(
    train: Sequence[str], smoothing: float
) -> dict[str, float]:
    """Smoothed frequency of dominant tokens in the training prefix."""
    counts = {t: 0 for t in TOKEN_NAMES}
    for token in train:
        counts[token] += 1
    return _normalized([counts[t] + smoothing for t in TOKEN_NAMES])


def persistence_distribution(previous: str, smoothing: float) -> dict[str, float]:
    """All mass on the previous token, smoothed over the vocabulary."""
    return _normalized(
        [(1.0 if t == previous else 0.0) + smoothing for t in TOKEN_NAMES]
    )


def transition_counts(train: Sequence[str]) -> dict[str, dict[str, int]]:
    """First-order transition counts over consecutive training pairs."""
    table: dict[str, dict[str, int]] = {}
    for prev, nxt in zip(train, train[1:]):
        row = table.setdefault(prev, {t: 0 for t in TOKEN_NAMES})
        row[nxt] += 1
    return table


def first_order_distribution(
    previous: str,
    table: Mapping[str, Mapping[str, int]],
    prior: Mapping[str, float],
    smoothing: float,
) -> dict[str, float]:
    """Smoothed transition row for ``previous``; falls back to the prior.

    Fallback contract (documented in the baseline doc): a previous token
    never seen as a transition SOURCE in training has no row to smooth —
    the model abstains to the empirical prior rather than inventing a
    uniform row, and the evaluation records how often that happened via
    the model's own metrics (the fallback is the prior, so the comparison
    stays honest).
    """
    row = table.get(previous)
    if row is None:
        return dict(prior)
    return _normalized([row[t] + smoothing for t in TOKEN_NAMES])


# ---------------------------------------------------------------------------
# Metrics: NLL (bits), multiclass Brier, top-1 accuracy, fixed-bin ECE
# ---------------------------------------------------------------------------


def evaluate_predictions(
    predictions: Sequence[Mapping[str, float]],
    actuals: Sequence[str],
) -> dict[str, float]:
    """Deterministic holdout metrics for one model.

    - ``nll_bits``: mean −log₂ P(actual). Base-2 to match the repo's
      entropy/divergence convention (bits everywhere).
    - ``brier``: mean multiclass Brier score Σ_t (p_t − 1[t=actual])².
    - ``top1_accuracy``: argmax with canonical-order tie-breaking.
    - ``ece``: expected calibration error over ECE_BINS fixed equal-width
      confidence bins (final bin closed above), weighted by bin size.
    """
    if len(predictions) != len(actuals) or not predictions:
        raise ValueError("predictions and actuals must be equal-length and non-empty")
    n = len(predictions)
    nll_total = 0.0
    brier_total = 0.0
    correct = 0
    bin_confidence = [0.0] * ECE_BINS
    bin_accuracy = [0.0] * ECE_BINS
    bin_count = [0] * ECE_BINS
    for dist, actual in zip(predictions, actuals):
        p_actual = dist[actual]
        nll_total += -math.log2(max(p_actual, 1e-300))
        brier_total += sum(
            (dist[t] - (1.0 if t == actual else 0.0)) ** 2 for t in TOKEN_NAMES
        )
        # argmax with canonical tie-break (first maximal in TOKEN_NAMES).
        top_token = max(TOKEN_NAMES, key=lambda t: (dist[t], -_TOKEN_INDEX[t]))
        confidence = dist[top_token]
        hit = top_token == actual
        correct += 1 if hit else 0
        bin_idx = min(int(confidence * ECE_BINS), ECE_BINS - 1)
        bin_confidence[bin_idx] += confidence
        bin_accuracy[bin_idx] += 1.0 if hit else 0.0
        bin_count[bin_idx] += 1
    ece = 0.0
    for b in range(ECE_BINS):
        if bin_count[b] == 0:
            continue
        avg_conf = bin_confidence[b] / bin_count[b]
        avg_acc = bin_accuracy[b] / bin_count[b]
        ece += (bin_count[b] / n) * abs(avg_conf - avg_acc)
    return {
        "nll_bits": nll_total / n,
        "brier": brier_total / n,
        "top1_accuracy": correct / n,
        "ece": ece,
    }


# ---------------------------------------------------------------------------
# End-to-end evaluation
# ---------------------------------------------------------------------------


def run_evaluation(
    sequence: Sequence[str],
    *,
    smoothing: float = SMOOTHING_DEFAULT,
    holdout_fraction: float = HOLDOUT_FRACTION_DEFAULT,
) -> dict[str, Any]:
    """Chronological train/holdout evaluation of all three baselines.

    The split is a single chronological cut: the first
    ``floor(N · (1 − holdout_fraction))`` dominant tokens train, the rest
    are holdout targets. Each holdout position is predicted from the
    TRUE previous token (available at prediction time; the first holdout
    target's previous token is the last training token) — models never
    see a holdout token before predicting it, and nothing is shuffled.
    """
    if not 0.0 < smoothing <= SMOOTHING_MAX:
        raise PredictorInputError(
            f"smoothing must be in (0, {SMOOTHING_MAX}], got {smoothing}"
        )
    if not HOLDOUT_FRACTION_MIN <= holdout_fraction <= HOLDOUT_FRACTION_MAX:
        raise PredictorInputError(
            f"holdout_fraction must be in [{HOLDOUT_FRACTION_MIN}, "
            f"{HOLDOUT_FRACTION_MAX}], got {holdout_fraction}"
        )
    n = len(sequence)
    split = math.floor(n * (1.0 - holdout_fraction))
    train = list(sequence[:split])
    holdout = list(sequence[split:])
    if len(train) < 2 or len(holdout) < 1:
        raise InsufficientHistoryError(
            f"need >=2 train and >=1 holdout rows; got train={len(train)}, "
            f"holdout={len(holdout)} from {n} accepted rows"
        )

    prior = empirical_prior_distribution(train, smoothing)
    table = transition_counts(train)

    previous_tokens = [train[-1]] + holdout[:-1]
    models: dict[str, list[dict[str, float]]] = {
        "empirical_prior": [dict(prior) for _ in holdout],
        "persistence": [
            persistence_distribution(prev, smoothing) for prev in previous_tokens
        ],
        "first_order": [
            first_order_distribution(prev, table, prior, smoothing)
            for prev in previous_tokens
        ],
    }
    unseen_sources = sum(1 for prev in previous_tokens if prev not in table)

    metrics = {
        name: evaluate_predictions(preds, holdout) for name, preds in models.items()
    }
    return {
        "train_rows": len(train),
        "holdout_rows": len(holdout),
        "split_index": split,
        "first_order_unseen_source_count": unseen_sources,
        "models": metrics,
    }


def build_report(
    log_path: pathlib.Path,
    *,
    smoothing: float = SMOOTHING_DEFAULT,
    holdout_fraction: float = HOLDOUT_FRACTION_DEFAULT,
    max_rows: int = MAX_ROWS_DEFAULT,
    max_line_bytes: int = MAX_LINE_BYTES_DEFAULT,
) -> dict[str, Any]:
    """Full deterministic report for one log file.

    Contains configuration echoes, row/rejection accounting, the split
    boundary and per-model metrics. Never contains row payloads, file
    contents or wall-clock timestamps. Keys serialize sorted; the same
    input yields a byte-identical report.
    """
    sequence, rejections, rows_read = read_dominant_sequence(
        log_path, max_rows=max_rows, max_line_bytes=max_line_bytes
    )
    evaluation = run_evaluation(
        sequence, smoothing=smoothing, holdout_fraction=holdout_fraction
    )
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "config": {
            "smoothing": smoothing,
            "holdout_fraction": holdout_fraction,
            "max_rows": max_rows,
            "max_line_bytes": max_line_bytes,
            "ece_bins": ECE_BINS,
            "vocabulary_size": len(TOKEN_NAMES),
        },
        "input": {
            "rows_read": rows_read,
            "rows_accepted": len(sequence),
            "rows_rejected": sum(rejections.values()),
            "rejections": rejections,
        },
        "evaluation": evaluation,
        "non_claims": [
            "Baselines only: no intelligence, awareness or performance-victory claim.",
            "A simple baseline outperforming a complex one is an expected, reported outcome.",
        ],
    }
    serialized = serialize_report(report)
    if len(serialized.encode("utf-8")) > MAX_REPORT_BYTES:
        raise ReportTooLargeError(
            f"report would exceed {MAX_REPORT_BYTES} bytes; refusing to emit"
        )
    return report


def serialize_report(report: Mapping[str, Any]) -> str:
    """Canonical serialization: sorted keys, fixed separators, newline."""
    return json.dumps(report, sort_keys=True, separators=(",", ": "), indent=1) + "\n"


# ---------------------------------------------------------------------------
# Write-boundary guard: inside the input-log directory only, never data/
# ---------------------------------------------------------------------------


def _repo_data_dir() -> pathlib.Path:
    return (pathlib.Path(__file__).resolve().parent.parent / "data").resolve()


def validate_output_path(out_path: pathlib.Path, log_path: pathlib.Path) -> None:
    """Enforce the NP1 write contract for --output.

    The report may land ONLY inside the resolved input-log directory
    (mirroring nextness_metrics), NEVER inside the repository ``data/``
    tree — even when the input log itself lives there; reports about
    ``data/`` logs go to stdout instead — and NEVER on a path that IS
    the input log: by resolved path (which also covers lexical and
    symlink aliases, dangling ones included — resolution targets are
    compared, not link or segment names) or by file identity
    (``os.path.samefile``: device + inode / file ID, which covers
    existing hard links whose paths differ).

    Residual filesystem race, stated precisely (same as NP6/NP8):
    identity is verified at validation time; the later write does not
    re-verify. A concurrent actor replacing the output path between
    validation and write can still redirect the write. This guard
    defends against aliases that exist when it validates — it does not
    claim protection against concurrent hostile filesystem manipulation.
    """
    log_resolved = log_path.resolve()
    log_dir_resolved = log_resolved.parent
    out_resolved = out_path.resolve()
    try:
        out_resolved.relative_to(log_dir_resolved)
    except ValueError as e:
        raise WriteOutsideLogDirError(
            f"refusing to write predictor report outside the input-log "
            f"directory: {out_resolved} is not inside {log_dir_resolved}"
        ) from e
    if out_resolved == log_resolved:
        raise WriteOutsideLogDirError(
            f"refusing to overwrite the input log file: {out_resolved}"
        )
    # Hard links share identity while having distinct paths. Only an
    # EXISTING output can alias the input; stat runs on the resolved
    # path and any failure to verify is itself a refusal (fail closed),
    # never a fall-through.
    if out_resolved.exists():
        try:
            same = os.path.samefile(out_resolved, log_path)
        except OSError as e:
            raise WriteOutsideLogDirError(
                f"cannot verify output file identity against the input log "
                f"file: {out_resolved}"
            ) from e
        if same:
            raise WriteOutsideLogDirError(
                f"refusing to overwrite the input log file (shared file "
                f"identity): {out_resolved}"
            )
    data_dir = _repo_data_dir()
    if out_resolved == data_dir or data_dir in out_resolved.parents:
        raise WriteOutsideLogDirError(
            f"refusing to write predictor report inside the repository data/ "
            f"tree: {out_resolved}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic next-dominant-token baselines over a Nextness "
            "Observer JSONL log (offline; see module docstring for the "
            "full safety contract)."
        )
    )
    parser.add_argument("log_path", type=pathlib.Path, help="path to nextness_runs.jsonl")
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=None,
        help=(
            "optional report path; must resolve inside the input log's "
            "directory, outside the repository data/ tree, and must not "
            "name or alias the input log itself (default: stdout)"
        ),
    )
    parser.add_argument("--smoothing", type=float, default=SMOOTHING_DEFAULT)
    parser.add_argument(
        "--holdout-fraction", type=float, default=HOLDOUT_FRACTION_DEFAULT
    )
    parser.add_argument("--max-rows", type=int, default=MAX_ROWS_DEFAULT)
    parser.add_argument(
        "--max-line-bytes", type=int, default=MAX_LINE_BYTES_DEFAULT,
        help=(
            f"per-record content-byte bound (default "
            f"{MAX_LINE_BYTES_DEFAULT}; ceiling {MAX_LINE_BYTES_CEILING})"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Exit-code contract (documented, tested):

    - ``0`` success
    - ``2`` validation failure — missing log file or out-of-bounds
      configuration (argparse's own usage errors also exit 2)
    - ``3`` insufficient history for a train/holdout split
    - ``4`` output-path failure — write-boundary violation or an
      unwritable target
    - ``5`` report exceeds MAX_REPORT_BYTES (fail closed)

    Every expected failure prints one concise ``error:`` line to stderr —
    never a traceback. The documented catch set is exactly
    ``WriteOutsideLogDirError``, ``InsufficientHistoryError``,
    ``ReportTooLargeError``, the typed ``PredictorInputError`` (the
    exit-2 lane — out-of-bounds configuration raises it directly) and
    the write-lane ``OSError``. Exceptions outside it — including plain
    ``ValueError`` — propagate (predictor typed-boundary pilot;
    test-pinned). Direct-Python note: callers catching ``ValueError``
    remain compatible because ``PredictorInputError`` subclasses it, but
    the exact exception type at the four reclassified validation sites
    (max_rows, max_line_bytes, smoothing, holdout_fraction) is now
    ``PredictorInputError``.
    """
    args = _build_parser().parse_args(argv)
    if not args.log_path.is_file():
        print(f"error: log file not found: {args.log_path}", file=sys.stderr)
        return 2
    try:
        if args.output is not None:
            validate_output_path(args.output, args.log_path)
        report = build_report(
            args.log_path,
            smoothing=args.smoothing,
            holdout_fraction=args.holdout_fraction,
            max_rows=args.max_rows,
            max_line_bytes=args.max_line_bytes,
        )
    except WriteOutsideLogDirError as e:
        print(f"error: {e}", file=sys.stderr)
        return 4
    except InsufficientHistoryError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    except ReportTooLargeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 5
    except PredictorInputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    serialized = serialize_report(report)
    if args.output is not None:
        try:
            # Explicit UTF-8 bytes (NP5/NP6/NP8 convention): the file is
            # exactly serialize_report(report).encode("utf-8"), one
            # trailing LF, immune to platform newline translation.
            args.output.write_bytes(serialized.encode("utf-8"))
        except OSError as e:
            print(f"error: cannot write report to {args.output}: {e}", file=sys.stderr)
            return 4
    else:
        sys.stdout.write(serialized)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
