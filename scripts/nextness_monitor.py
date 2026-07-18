"""Metacognitive calibration receipt over NP1 predictions (NP2).

Functional metacognition ONLY: this module measures when the NP1
predictor is uncertain, surprised, drifting out of its calibrated
regime, or short of history — and says so in a fixed, bounded,
deterministic receipt. It does not act on anything. "Abstain" means
exactly "do not treat this prediction as evidence"; it triggers no
tuning, no orchestration, no engine or observer behavior of any kind.

EXPLICIT NON-CLAIM (load-bearing): nothing here is, or is evidence of,
awareness, sentience or phenomenal experience. It is bookkeeping about
a counting model's error statistics — the *functional* shadow of
"knowing that you might be wrong", which is the only part we can test.

Receipt contract (``nextness-monitor-v1``):

- Only allowlisted, bounded fields; the model identifier comes from a
  fixed allowlist; the abstention reason from a fixed vocabulary
  (``insufficient_history``, ``unseen_state``, ``low_confidence``,
  ``calibration_drift``, ``distribution_shift``, ``none``).
- No free-form text, no internal monologue, no prompt text, no source
  payloads — numbers, enums and booleans only.
- Plain deterministic JSON: sorted keys, fixed rounding, no wall-clock
  timestamps, byte-identical across repeated runs, ≤64 KiB fail-closed.
- Every threshold is bounded, documented configuration — none of them
  is claimed to be universal.
- Unknown observation fields are DISCARDED and honestly counted
  (``discarded_field_count`` + ``input_reduced``); malformed
  observations fail closed with a typed error. All four allowlisted
  fields are REQUIRED (a missing ``prev_seen`` is never defaulted);
  numbers must be exact builtin ``int``/``float`` (bools and custom
  numeric subclasses are rejected before any conversion hook can run)
  and ``min_history``/``window`` exact builtin ints.
- Distribution drift compares the training reference against exactly
  the LATEST ``window`` holdout observations — an older stable holdout
  prefix cannot dilute a late regime change.

Safety: no tuning, orchestration, engine, Swarm Hunter or Lane-A
imports; offline; no network; writes nothing (receipt goes to the
caller / stdout).
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from scripts.nextness_metrics import js_divergence
from scripts.nextness_observer import TOKEN_INDEX, TOKEN_NAMES
from scripts.nextness_predictor import (
    ECE_BINS,
    HOLDOUT_FRACTION_DEFAULT,
    HOLDOUT_FRACTION_MAX,
    HOLDOUT_FRACTION_MIN,
    MAX_LINE_BYTES_DEFAULT,
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

RECEIPT_SCHEMA: Final[str] = "nextness-monitor-v1"

#: The only model identifiers a receipt may carry (fail closed otherwise).
MODEL_ALLOWLIST: Final[tuple[str, ...]] = (
    "empirical_prior",
    "persistence",
    "first_order",
)

#: Fixed abstention vocabulary, in DECISION PRECEDENCE order (first
#: matching reason wins; documented in NEXTNESS_MONITOR_CONTRACT.md).
ABSTAIN_REASONS: Final[tuple[str, ...]] = (
    "insufficient_history",
    "unseen_state",
    "low_confidence",
    "calibration_drift",
    "distribution_shift",
    "none",
)

#: Allowlisted observation-record fields (anything else is discarded and
#: counted; the receipt then carries input_reduced=true).
OBSERVATION_FIELDS: Final[frozenset[str]] = frozenset(
    {"confidence", "hit", "p_actual", "prev_seen"}
)

MAX_RECEIPT_BYTES: Final[int] = 64 * 1024
_ROUND: Final[int] = 6  # fixed decimal rounding for deterministic floats
_MAX_SURPRISE_BITS: Final[float] = 1_000.0  # bound against p_actual underflow


class MonitorInputError(ValueError):
    """A malformed observation record (fail closed, typed)."""


class ReceiptTooLargeError(RuntimeError):
    """Serialized receipt exceeded MAX_RECEIPT_BYTES (fail closed)."""


@dataclass(frozen=True)
class MonitorConfig:
    """Bounded, documented thresholds. None of these is universal; they
    are operating-regime configuration and the receipt echoes them."""

    min_history: int = 30            # observations needed for sufficiency
    window: int = 50                 # rolling window for ECE + drift
    low_confidence_threshold: float = 0.30
    calibration_error_threshold: float = 0.20   # rolling ECE, [0, 1]
    drift_threshold_bits: float = 0.15          # JS divergence, [0, 1] bits

    def validate(self) -> None:
        _require_exact_int("min_history", self.min_history)
        _require_exact_int("window", self.window)
        if not 5 <= self.min_history <= 10_000:
            raise ValueError(f"min_history out of bounds [5, 10000]: {self.min_history}")
        if not 5 <= self.window <= 10_000:
            raise ValueError(f"window out of bounds [5, 10000]: {self.window}")
        for name, value in (
            ("low_confidence_threshold", self.low_confidence_threshold),
            ("calibration_error_threshold", self.calibration_error_threshold),
            ("drift_threshold_bits", self.drift_threshold_bits),
        ):
            if not (isinstance(value, float) and 0.0 < value < 1.0):
                raise ValueError(f"{name} must be a float in (0, 1): {value!r}")


# ---------------------------------------------------------------------------
# Observation validation (container guards + bounded normalization)
# ---------------------------------------------------------------------------


def _require_exact_int(name: str, value: Any) -> None:
    """Exact builtin ``int`` only — bool, float and int subclasses are
    configuration errors, not values to coerce."""
    if type(value) is not int:
        raise ValueError(
            f"{name} must be a builtin int, got {type(value).__name__}"
        )


def _bounded_float(value: Any, field: str, low: float, high: float) -> float:
    """Accept exact builtin ``int``/``float`` finite values inside
    [low, high]; reject everything else (bools, custom numeric subclasses,
    hostile objects with __float__/__str__, NaN/inf, astronomically large
    ints) with a typed error. Exact-type checks run FIRST so no custom
    conversion hook (__float__/__index__) is ever invoked."""
    if type(value) is not int and type(value) is not float:
        raise MonitorInputError(
            f"{field}: expected a builtin real number, got {type(value).__name__}"
        )
    try:
        as_float = float(value)
    except (OverflowError, ValueError) as e:  # e.g. int(10**400) -> inf
        raise MonitorInputError(f"{field}: not representable as a finite float") from e
    if not math.isfinite(as_float):
        raise MonitorInputError(f"{field}: not finite")
    if not low <= as_float <= high:
        raise MonitorInputError(f"{field}: {as_float} outside [{low}, {high}]")
    return as_float


def validate_observations(
    records: Sequence[Any],
) -> tuple[list[dict[str, Any]], int]:
    """Normalize observation records into owned, bounded dicts.

    Returns ``(observations, discarded_field_count)``. Each record must
    be a built-in dict carrying the allowlisted fields; unknown fields
    are discarded (counted), missing/invalid required fields fail
    closed. Values are read exactly once into owned plain objects — no
    caller container is retained.
    """
    observations: list[dict[str, Any]] = []
    discarded = 0
    for i, record in enumerate(records):
        if type(record) is not dict:
            raise MonitorInputError(f"observation {i}: expected builtin dict")
        unknown = set(record) - OBSERVATION_FIELDS
        discarded += len(unknown)
        try:
            confidence = _bounded_float(record["confidence"], "confidence", 0.0, 1.0)
            p_actual = _bounded_float(record["p_actual"], "p_actual", 0.0, 1.0)
        except KeyError as e:
            raise MonitorInputError(f"observation {i}: missing field {e.args[0]!r}") from e
        hit = record.get("hit")
        if type(hit) is not bool:
            raise MonitorInputError(f"observation {i}: hit must be a builtin bool")
        if "prev_seen" not in record:
            # Fail closed — defaulting a missing prev_seen to True would
            # silently mask unseen_state abstention.
            raise MonitorInputError(f"observation {i}: missing field 'prev_seen'")
        prev_seen = record["prev_seen"]
        if type(prev_seen) is not bool:
            raise MonitorInputError(f"observation {i}: prev_seen must be a builtin bool")
        observations.append(
            {
                "confidence": confidence,
                "hit": hit,
                "p_actual": p_actual,
                "prev_seen": prev_seen,
            }
        )
    return observations, discarded


# ---------------------------------------------------------------------------
# Rolling statistics (all deterministic, all bounded)
# ---------------------------------------------------------------------------


def rolling_ece(observations: Sequence[Mapping[str, Any]]) -> float:
    """Fixed-bin expected calibration error over the given observations —
    the same ECE_BINS deterministic binning NP1 uses."""
    if not observations:
        return 0.0
    n = len(observations)
    bin_conf = [0.0] * ECE_BINS
    bin_acc = [0.0] * ECE_BINS
    bin_count = [0] * ECE_BINS
    for ob in observations:
        b = min(int(ob["confidence"] * ECE_BINS), ECE_BINS - 1)
        bin_conf[b] += ob["confidence"]
        bin_acc[b] += 1.0 if ob["hit"] else 0.0
        bin_count[b] += 1
    ece = 0.0
    for b in range(ECE_BINS):
        if bin_count[b]:
            # Algebraically identical to the textbook
            # (count/n)·|conf/count − acc/count| form — the bin count
            # cancels; equivalence is locked by a boundary+seeded fixture
            # test against the unsimplified reference.
            ece += abs(bin_conf[b] - bin_acc[b]) / n
    return ece


def surprise_bits(p_actual: float) -> float:
    """Realised surprise −log₂ P(actual), bounded above (underflow guard)."""
    if p_actual <= 0.0:
        return _MAX_SURPRISE_BITS
    return min(-math.log2(p_actual), _MAX_SURPRISE_BITS)


def canonical_top(dist: Mapping[str, float]) -> str:
    """Argmax over the canonical vocabulary, ties broken by TOKEN_INDEX
    (the token EARLIEST in TOKEN_NAMES order wins) — the same constant-time
    lookup NP1's ``evaluate_predictions`` uses."""
    return max(TOKEN_NAMES, key=lambda t: (dist[t], -TOKEN_INDEX[t]))


# ---------------------------------------------------------------------------
# Receipt construction
# ---------------------------------------------------------------------------


def decide_abstention(
    *,
    observation_count: int,
    latest_confidence: float | None,
    latest_prev_seen: bool,
    rolling_calibration_error: float,
    drift_bits: float,
    config: MonitorConfig,
) -> tuple[bool, str]:
    """Deterministic abstention decision, fixed precedence order.

    Precedence (first match wins): insufficient_history → unseen_state →
    low_confidence → calibration_drift → distribution_shift → none.
    """
    if observation_count < config.min_history:
        return True, "insufficient_history"
    if not latest_prev_seen:
        return True, "unseen_state"
    if latest_confidence is not None and latest_confidence < config.low_confidence_threshold:
        return True, "low_confidence"
    if rolling_calibration_error > config.calibration_error_threshold:
        return True, "calibration_drift"
    if drift_bits > config.drift_threshold_bits:
        return True, "distribution_shift"
    return False, "none"


def build_receipt(
    *,
    model: str,
    observations: Sequence[Any],
    reference_counts: Mapping[str, int],
    recent_counts: Mapping[str, int],
    config: MonitorConfig | None = None,
) -> dict[str, Any]:
    """One deterministic ``nextness-monitor-v1`` receipt.

    ``reference_counts``/``recent_counts`` are dominant-token count
    mappings (training reference vs the recent window) whose smoothed
    Jensen-Shannon divergence — reusing ``nextness_metrics`` — is the
    drift measure. All fields are allowlisted and bounded; see the
    module docstring for the full contract.
    """
    cfg = config or MonitorConfig()
    cfg.validate()
    if model not in MODEL_ALLOWLIST:
        raise MonitorInputError(f"model {model!r} not in fixed allowlist {MODEL_ALLOWLIST}")
    for name, counts in (("reference_counts", reference_counts), ("recent_counts", recent_counts)):
        if type(counts) is not dict:
            raise MonitorInputError(f"{name}: expected builtin dict")
        if any(k not in TOKEN_NAMES for k in counts):
            raise MonitorInputError(f"{name}: unknown token key")
        for v in counts.values():
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise MonitorInputError(f"{name}: counts must be non-negative builtin ints")

    validated, discarded = validate_observations(observations)
    window = validated[-cfg.window :]
    n = len(validated)

    mean_confidence = sum(ob["confidence"] for ob in validated) / n if n else 0.0
    mean_surprise = sum(surprise_bits(ob["p_actual"]) for ob in validated) / n if n else 0.0
    ece = rolling_ece(window)
    drift = js_divergence(reference_counts, recent_counts)

    abstain, reason = decide_abstention(
        observation_count=n,
        latest_confidence=validated[-1]["confidence"] if validated else None,
        latest_prev_seen=validated[-1]["prev_seen"] if validated else True,
        rolling_calibration_error=ece,
        drift_bits=drift,
        config=cfg,
    )

    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "model": model,
        "observation_count": n,
        "mean_confidence": round(mean_confidence, _ROUND),
        "mean_surprise_bits": round(mean_surprise, _ROUND),
        "rolling_calibration_error": round(ece, _ROUND),
        "distribution_drift_bits": round(drift, _ROUND),
        "sufficiency": "sufficient" if n >= cfg.min_history else "insufficient",
        "abstain": abstain,
        "abstain_reason": reason,
        "input_reduced": discarded > 0,
        "discarded_field_count": discarded,
        "config": {
            "min_history": cfg.min_history,
            "window": cfg.window,
            "low_confidence_threshold": round(cfg.low_confidence_threshold, _ROUND),
            "calibration_error_threshold": round(cfg.calibration_error_threshold, _ROUND),
            "drift_threshold_bits": round(cfg.drift_threshold_bits, _ROUND),
        },
        "non_claim": (
            "functional-metacognition-only: no awareness, sentience or "
            "phenomenal-experience claim"
        ),
    }
    serialized = serialize_receipt(receipt)
    if len(serialized.encode("utf-8")) > MAX_RECEIPT_BYTES:
        raise ReceiptTooLargeError(
            f"receipt would exceed {MAX_RECEIPT_BYTES} bytes; refusing to emit"
        )
    return receipt


def serialize_receipt(receipt: Mapping[str, Any]) -> str:
    """Canonical serialization: sorted keys, fixed separators, newline."""
    return json.dumps(receipt, sort_keys=True, separators=(",", ": "), indent=1) + "\n"


# ---------------------------------------------------------------------------
# NP1 bridge: derive observations for one model over one JSONL log
# ---------------------------------------------------------------------------


def observations_from_log(
    log_path: pathlib.Path,
    model: str,
    *,
    smoothing: float = SMOOTHING_DEFAULT,
    holdout_fraction: float = HOLDOUT_FRACTION_DEFAULT,
    max_rows: int = MAX_ROWS_DEFAULT,
    max_line_bytes: int = MAX_LINE_BYTES_DEFAULT,
    window: int = MonitorConfig.window,
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int]]:
    """Replay NP1's chronological holdout as monitor observations.

    Returns ``(observations, reference_counts, recent_counts)`` where the
    reference is the training prefix's dominant-token counts and
    ``recent_counts`` covers exactly the LATEST ``window`` holdout
    observations (an older stable holdout prefix must not dilute a late
    regime change; pass the same ``window`` the receipt's MonitorConfig
    uses). Uses exactly NP1's split, option bounds and model definitions —
    this bridge adds no new prediction semantics.
    """
    if model not in MODEL_ALLOWLIST:
        raise MonitorInputError(f"model {model!r} not in fixed allowlist {MODEL_ALLOWLIST}")
    # Inherited NP1 option bounds (same messages as run_evaluation) —
    # out-of-bounds options must fail closed here too, never reach the
    # distribution builders as silent garbage. Typed as MonitorInputError
    # (message text unchanged) so the CLI's exit-2 catch can be exactly
    # the typed class: these two are the only CLI-reachable input raises
    # on this path.
    if not 0.0 < smoothing <= SMOOTHING_MAX:
        raise MonitorInputError(
            f"smoothing must be in (0, {SMOOTHING_MAX}], got {smoothing}"
        )
    if not HOLDOUT_FRACTION_MIN <= holdout_fraction <= HOLDOUT_FRACTION_MAX:
        raise MonitorInputError(
            f"holdout_fraction must be in [{HOLDOUT_FRACTION_MIN}, "
            f"{HOLDOUT_FRACTION_MAX}], got {holdout_fraction}"
        )
    _require_exact_int("window", window)
    if not 5 <= window <= 10_000:
        raise ValueError(f"window out of bounds [5, 10000]: {window}")
    sequence, _rejections, _rows = read_dominant_sequence(
        log_path, max_rows=max_rows, max_line_bytes=max_line_bytes
    )
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

    def _counts(tokens: Sequence[str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for t in tokens:
            out[t] = out.get(t, 0) + 1
        return out

    return observations, _counts(train), _counts(holdout[-window:])


# ---------------------------------------------------------------------------
# CLI (stdout only — the monitor writes no files)
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Metacognitive calibration receipt over NP1 predictions "
            "(functional metacognition only; stdout only; see module "
            "docstring for the full contract)."
        )
    )
    parser.add_argument("log_path", type=pathlib.Path, help="path to nextness_runs.jsonl")
    parser.add_argument("--model", choices=MODEL_ALLOWLIST, default="first_order")
    parser.add_argument("--smoothing", type=float, default=SMOOTHING_DEFAULT)
    parser.add_argument("--holdout-fraction", type=float, default=HOLDOUT_FRACTION_DEFAULT)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Exit-code contract (inherited from NP1's expected-failure contract):

    - ``0`` success
    - ``2`` validation failure — missing log file or out-of-bounds
      options (argparse's own usage errors also exit 2)
    - ``3`` insufficient history for a train/holdout split

    Every expected failure prints one concise ``error:`` line to stderr —
    never a traceback. The documented catch set is exactly
    ``InsufficientHistoryError`` (exit 3) and the typed
    ``MonitorInputError`` (exit 2); exceptions outside it — including
    plain ``ValueError`` — propagate (monitor typed-input-boundary
    pilot; test-pinned). Direct-Python note: callers catching
    ``ValueError`` remain compatible because ``MonitorInputError``
    subclasses it, but the exact exception type at the two reclassified
    validation sites (smoothing, holdout fraction) is now
    ``MonitorInputError``.
    """
    args = _build_parser().parse_args(argv)
    if not args.log_path.is_file():
        print(f"error: log file not found: {args.log_path}", file=sys.stderr)
        return 2
    config = MonitorConfig()
    try:
        observations, reference, recent = observations_from_log(
            args.log_path,
            args.model,
            smoothing=args.smoothing,
            holdout_fraction=args.holdout_fraction,
            window=config.window,
        )
        receipt = build_receipt(
            model=args.model,
            observations=observations,
            reference_counts=reference,
            recent_counts=recent,
            config=config,
        )
    except InsufficientHistoryError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    except MonitorInputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    sys.stdout.write(serialize_receipt(receipt))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
