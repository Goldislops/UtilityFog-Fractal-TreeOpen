"""Deterministic offline evaluator over recorded NP1/NP2 artifacts (NP5).

Reads artifacts that already exist on disk — NP1 predictor reports
(``nextness-predictor-v1``) and NP2 monitor receipts
(``nextness-monitor-v1``), singly or as a recorded series — and answers
one question honestly: *what can these artifacts establish about
prediction, uncertainty, abstention and recovery after surprise, and
what remains uncomputable from them?*

SCOPE OF CLAIM (deliberate, narrow): this module observes and scores
recorded artifacts. It never tunes, actuates, selects engine rules,
invokes a model, contacts a service, or writes into the engine or the
observer. Nothing here is, or is evidence of, awareness, consciousness,
phenomenology or biological equivalence — see ``NON_CLAIMS``.

The honest core is the RESULT ENVELOPE: every metric is emitted either
as ``{"status": "computed", "value": ...}`` or as ``{"status":
"not_computable", "reason": <fixed code>, "requires": <what evidence is
missing>}``. Uncomputability is a first-class, typed result — the
evaluator never substitutes a guess for absent evidence.

Three structural facts about the v1 artifacts drive the design:

1. An NP2 receipt does not record the latest observation's confidence
   or ``prev_seen`` — the two inputs that two of the six abstention
   reasons depend on. Full abstention-decision verification is therefore
   PROVABLY not computable from receipts; the evaluator instead emits
   per-clause tri-state verdicts (``consistent`` / ``contradicted`` /
   ``unverifiable``) for exactly the clauses the recorded fields can
   witness.
2. Receipts carry no timestamps (by emitter design). Series order is
   witnessed only by strictly increasing ``observation_count``; when the
   witness fails, order-dependent metrics return a typed
   ``order_not_witnessed`` result while order-free metrics still
   compute.
3. Receipt floats are rounded to 6 decimal places by the emitter, so
   every comparison against them carries a derived tolerance
   (documented at the constants below) — a contradiction is only
   declared when it exceeds worst-case rounding error.

Safety contract (Lane B, mirrors nextness_predictor/nextness_monitor):

- Offline only: no network, HTTP, ZMQ, Ollama or model calls; the only
  I/O is reading the artifact files named on the command line and
  (optionally) writing one evaluation next to them.
- Bounded input: artifact files are read through a hard pre-parse size
  ceiling (``MAX_INPUT_BYTES``) — at most ``MAX_INPUT_BYTES + 1`` bytes
  are ever materialized; receipt series are bounded by
  ``MAX_SERIES_RECEIPTS``. Exact-type, fail-closed validation runs
  before any arithmetic; unknown schemas, unknown keys and missing keys
  are all rejected (unknown variants never pass silently).
- Writes are permitted ONLY inside the directory of the primary input
  artifact (``WriteOutsideLogDirError`` otherwise), NEVER inside the
  repository ``data/`` tree, and NEVER onto a path that IS any supplied
  input artifact — report or receipts alike: aliases are refused by
  resolved path and by file identity (``os.path.samefile`` on resolved
  paths; hard links included), failing closed when identity cannot be
  verified. Identity is checked at validation time, before any artifact
  is parsed or any evaluation computed; the later write does not
  re-verify (documented residual race, same as NP6/NP8).
- Deterministic output: sorted keys, fixed schema, no wall-clock
  timestamps, no random identifiers, no absolute paths (provenance is
  the SHA-256 of each artifact's raw bytes); the same input bytes always
  produce a byte-identical evaluation, checked against a 64 KiB
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

from scripts.nextness_monitor import (
    ABSTAIN_REASONS,
    MODEL_ALLOWLIST,
    RECEIPT_SCHEMA,
)
from scripts.nextness_observer import TOKEN_NAMES, WriteOutsideLogDirError
from scripts.nextness_predictor import (
    ECE_BINS,
    HOLDOUT_FRACTION_MAX,
    HOLDOUT_FRACTION_MIN,
    MAX_ROWS_CEILING,
    REJECT_REASONS,
    REPORT_SCHEMA,
    SMOOTHING_MAX,
)

# ---------------------------------------------------------------------------
# Fixed contract constants
# ---------------------------------------------------------------------------

EVALUATION_SCHEMA: Final[str] = "nextness-evaluation-v1"

#: Pre-parse input ceiling: at most this many bytes of an artifact file
#: are ever read (the loader probes one extra byte to detect overflow,
#: so peak materialization is MAX_INPUT_BYTES + 1). A realistic receipt
#: is ~1 KiB, so a full 256-receipt series fits comfortably.
MAX_INPUT_BYTES: Final[int] = 1_048_576

#: Hard bound on receipts per recorded series (fail closed above).
MAX_SERIES_RECEIPTS: Final[int] = 256

#: Evaluation size ceiling — fail closed rather than emit an unbounded
#: blob (same 64 KiB convention as NP1 reports and NP2 receipts).
MAX_EVALUATION_BYTES: Final[int] = 64 * 1024

#: Detailed per-item lists (block means, run lengths, contradiction
#: indices) are capped at this many entries WITH an explicit
#: ``truncated`` flag — never silently — so the evaluation stays inside
#: MAX_EVALUATION_BYTES for a full 256-receipt series.
MAX_DETAIL_ITEMS: Final[int] = 128

#: NP2 rounds every receipt float to 6 decimal places, so a recorded
#: value differs from the true value by at most 5e-7. Comparing two
#: recorded values therefore carries a worst-case combined rounding
#: error of 1e-6; comparing one recorded value against one unrounded
#: value carries 5e-7. Each tolerance below is twice its worst case, so
#: a declared contradiction can never be a rounding artifact.
CONTRADICTION_TOLERANCE: Final[float] = 2e-6   # recorded vs recorded
CROSS_CHECK_TOLERANCE: Final[float] = 1e-6     # recorded vs unrounded

#: Kept manually in sync with nextness_monitor's surprise underflow cap
#: (its private ``_MAX_SURPRISE_BITS = 1000.0``).
SURPRISE_BITS_MAX: Final[float] = 1_000.0

#: Mirrors NP1's log floor: evaluate_predictions clamps P(actual) at
#: 1e-300, so a single observation's surprise never exceeds
#: -log2(1e-300) in the report.
NLL_BITS_MAX: Final[float] = -math.log2(1e-300)

#: NP1's nll_bits is a naive float sum divided by n, so a genuine
#: all-floored report overshoots NLL_BITS_MAX by accumulated rounding
#: (measured up to ~1.5e-8 at n = 1e6). Validation allows this small
#: slack above the exact bound; fabricated out-of-range values are
#: still rejected.
_NLL_BITS_VALIDATION_MAX: Final[float] = NLL_BITS_MAX + 1e-6

#: Multiclass Brier score over a full probability distribution is
#: bounded by 2 (all mass on one wrong token).
BRIER_MAX: Final[float] = 2.0

#: Fixed vocabulary for typed not-computable results.
NOT_COMPUTABLE_REASONS: Final[tuple[str, ...]] = (
    "artifact_absent",        # the artifact carrying the evidence was not provided
    "field_not_recorded",     # the v1 schema does not record the required evidence
    "series_too_short",       # the computation needs more receipts than exist
    "order_not_witnessed",    # observation_count is not strictly increasing
    "no_covering_receipt",    # no receipt satisfies the cross-check precondition
    "model_not_stable",       # the series mixes predictor models
    "config_not_stable",      # the series mixes monitor configurations
)

#: Tri-state consistency verdicts (fixed vocabulary).
VERDICTS: Final[tuple[str, ...]] = ("consistent", "contradicted", "unverifiable")

#: Per-receipt consistency checks (fixed vocabulary; aggregated in the
#: abstention section).
CONSISTENCY_CHECKS: Final[tuple[str, ...]] = (
    "abstain_flag_matches_reason",
    "sufficiency_matches_history",
    "higher_precedence_excluded",
    "stated_reason_trigger",
)

#: Assumptions are only ever emitted when a metric that depends on them
#: is actually computed, and they are fixed strings (deterministic).
ASSUMPTION_PREFIX_EXTENSION: Final[str] = (
    "receipt-series-prefix-extension: consecutive receipts are cumulative "
    "snapshots of one growing observation stream"
)
ASSUMPTION_SAME_SOURCE: Final[str] = (
    "cross-check-same-source: the receipts were derived from the same log "
    "and NP1 options as the report (not recorded in either artifact)"
)

NON_CLAIMS: Final[tuple[str, ...]] = (
    "Evaluates recorded artifacts only: observes and scores, never tunes, "
    "actuates, selects rules, invokes a model or contacts a service.",
    "No awareness, consciousness, phenomenology or biological-equivalence "
    "claim is made or implied by any value in this evaluation.",
    "A not_computable result is a statement about the artifacts' evidence, "
    "not about the underlying system.",
)

#: Expected key sets — exact match required (unknown variants fail closed).
_REPORT_KEYS: Final[frozenset[str]] = frozenset(
    {"schema", "config", "input", "evaluation", "non_claims"}
)
_REPORT_CONFIG_KEYS: Final[frozenset[str]] = frozenset(
    {"smoothing", "holdout_fraction", "max_rows", "max_line_bytes",
     "ece_bins", "vocabulary_size"}
)
_REPORT_INPUT_KEYS: Final[frozenset[str]] = frozenset(
    {"rows_read", "rows_accepted", "rows_rejected", "rejections"}
)
_REPORT_EVALUATION_KEYS: Final[frozenset[str]] = frozenset(
    {"train_rows", "holdout_rows", "split_index",
     "first_order_unseen_source_count", "models"}
)
_MODEL_METRIC_KEYS: Final[frozenset[str]] = frozenset(
    {"nll_bits", "brier", "top1_accuracy", "ece"}
)
_RECEIPT_KEYS: Final[frozenset[str]] = frozenset(
    {"schema", "model", "observation_count", "mean_confidence",
     "mean_surprise_bits", "rolling_calibration_error",
     "distribution_drift_bits", "sufficiency", "abstain", "abstain_reason",
     "input_reduced", "discarded_field_count", "config", "non_claim"}
)
_RECEIPT_CONFIG_KEYS: Final[frozenset[str]] = frozenset(
    {"min_history", "window", "low_confidence_threshold",
     "calibration_error_threshold", "drift_threshold_bits"}
)

_MAX_NON_CLAIM_CHARS: Final[int] = 500
_MAX_NON_CLAIMS_ITEMS: Final[int] = 16


class EvaluatorInputError(ValueError):
    """A malformed, hostile or unknown-variant artifact (fail closed)."""


class EvaluationTooLargeError(RuntimeError):
    """Serialized evaluation exceeded MAX_EVALUATION_BYTES (fail closed)."""


# ---------------------------------------------------------------------------
# Result envelope: every metric is computed or typed-not-computable
# ---------------------------------------------------------------------------


def _computed(value: Any) -> dict[str, Any]:
    return {"status": "computed", "value": value}


def _not_computable(reason: str, requires: str) -> dict[str, Any]:
    if reason not in NOT_COMPUTABLE_REASONS:  # internal invariant, not input
        raise ValueError(f"unknown not-computable reason: {reason!r}")
    return {"status": "not_computable", "reason": reason, "requires": requires}


# ---------------------------------------------------------------------------
# Exact-type validators (hostile input boundary; no conversion hooks,
# no stringification, no traversal before the type is proven)
# ---------------------------------------------------------------------------


def _exact_str(value: Any, field: str) -> str:
    if type(value) is not str:
        raise EvaluatorInputError(f"{field}: expected builtin str, got {type(value).__name__}")
    return value


def _exact_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise EvaluatorInputError(f"{field}: expected builtin bool, got {type(value).__name__}")
    return value


def _exact_int(value: Any, field: str, low: int, high: int | None = None) -> int:
    if type(value) is not int:
        raise EvaluatorInputError(f"{field}: expected builtin int, got {type(value).__name__}")
    if value < low or (high is not None and value > high):
        bound = f"[{low}, {high}]" if high is not None else f">= {low}"
        raise EvaluatorInputError(f"{field}: {value} outside {bound}")
    return value


def _exact_float(
    value: Any,
    field: str,
    low: float,
    high: float,
) -> float:
    """Exact builtin int/float, finite, inside [low, high].

    Exact-type checks run FIRST, so no custom __float__/__index__ hook is
    ever invoked (same posture as nextness_monitor's _bounded_float).
    """
    if type(value) is not int and type(value) is not float:
        raise EvaluatorInputError(
            f"{field}: expected a builtin real number, got {type(value).__name__}"
        )
    try:
        as_float = float(value)
    except (OverflowError, ValueError) as e:  # e.g. int(10**400) -> inf
        raise EvaluatorInputError(f"{field}: not representable as a finite float") from e
    if not math.isfinite(as_float):
        raise EvaluatorInputError(f"{field}: not finite")
    if not low <= as_float <= high:
        raise EvaluatorInputError(f"{field}: {as_float} outside [{low}, {high}]")
    return as_float


def _exact_dict(value: Any, field: str, keys: frozenset[str]) -> dict[str, Any]:
    """Builtin dict with EXACTLY the given key set (unknown keys are an
    unknown variant; missing keys are missing evidence — both fail closed)."""
    if type(value) is not dict:
        raise EvaluatorInputError(f"{field}: expected builtin dict, got {type(value).__name__}")
    present = set(value)
    if present != keys:
        # Non-str keys are named by type only — never repr'd/str'd, so a
        # hostile key's __repr__ can never run in the error path.
        unknown = sorted(k if type(k) is str else f"<{type(k).__name__}>" for k in present - keys)
        missing = sorted(keys - present)
        raise EvaluatorInputError(
            f"{field}: key set mismatch (unknown={unknown}, missing={missing})"
        )
    return value


def _bounded_text(value: Any, field: str) -> str:
    text = _exact_str(value, field)
    if not text or len(text) > _MAX_NON_CLAIM_CHARS:
        raise EvaluatorInputError(
            f"{field}: length must be in [1, {_MAX_NON_CLAIM_CHARS}]"
        )
    return text


# ---------------------------------------------------------------------------
# Artifact loading (size limit BEFORE parse) and validation
# ---------------------------------------------------------------------------


def load_json_artifact(path: pathlib.Path, *, max_bytes: int = MAX_INPUT_BYTES) -> tuple[Any, str, int]:
    """Bounded read + parse of one artifact file.

    Returns ``(parsed, sha256_hex, byte_count)``. At most ``max_bytes + 1``
    bytes are read (the extra byte only detects overflow); a larger file
    fails closed before any parsing or hashing of the full content.
    """
    with path.open("rb") as f:
        raw = f.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise EvaluatorInputError(
            f"artifact exceeds {max_bytes} bytes; refusing to parse"
        )
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as e:
        raise EvaluatorInputError(f"artifact is not valid UTF-8: {e.reason}") from e
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError) as e:
        raise EvaluatorInputError(f"artifact is not valid JSON: {e}") from e
    except RecursionError as e:
        # A pathologically nested artifact (e.g. one megabyte of "[")
        # exhausts the parser's recursion budget — fail closed like any
        # other malformed artifact instead of propagating a traceback.
        raise EvaluatorInputError("artifact nesting exceeds the parser's depth limit") from e
    return parsed, hashlib.sha256(raw).hexdigest(), len(raw)


def validate_report(obj: Any) -> dict[str, Any]:
    """Exact-type, fail-closed validation of one nextness-predictor-v1
    report. Returns an owned normalized dict (no caller container is
    retained). Internal-accounting identities established by NP1's own
    construction are re-checked — an artifact violating them is not a
    v1 report, whatever its schema string says."""
    outer = _exact_dict(obj, "report", _REPORT_KEYS)
    schema = _exact_str(outer["schema"], "report.schema")
    if schema != REPORT_SCHEMA:
        raise EvaluatorInputError(
            f"report.schema: unknown variant {schema!r} (expected {REPORT_SCHEMA!r})"
        )

    cfg = _exact_dict(outer["config"], "report.config", _REPORT_CONFIG_KEYS)
    smoothing = _exact_float(cfg["smoothing"], "report.config.smoothing", 0.0, SMOOTHING_MAX)
    if smoothing <= 0.0:
        raise EvaluatorInputError("report.config.smoothing: must be > 0")
    holdout_fraction = _exact_float(
        cfg["holdout_fraction"], "report.config.holdout_fraction",
        HOLDOUT_FRACTION_MIN, HOLDOUT_FRACTION_MAX,
    )
    max_rows = _exact_int(cfg["max_rows"], "report.config.max_rows", 1, MAX_ROWS_CEILING)
    max_line_bytes = _exact_int(cfg["max_line_bytes"], "report.config.max_line_bytes", 1)
    ece_bins = _exact_int(cfg["ece_bins"], "report.config.ece_bins", 1)
    if ece_bins != ECE_BINS:
        raise EvaluatorInputError(
            f"report.config.ece_bins: unknown variant {ece_bins} (v1 uses {ECE_BINS})"
        )
    vocabulary_size = _exact_int(cfg["vocabulary_size"], "report.config.vocabulary_size", 2)
    if vocabulary_size != len(TOKEN_NAMES):
        raise EvaluatorInputError(
            f"report.config.vocabulary_size: unknown variant {vocabulary_size} "
            f"(v1 vocabulary has {len(TOKEN_NAMES)} tokens)"
        )

    inp = _exact_dict(outer["input"], "report.input", _REPORT_INPUT_KEYS)
    rows_read = _exact_int(inp["rows_read"], "report.input.rows_read", 0, MAX_ROWS_CEILING)
    rows_accepted = _exact_int(inp["rows_accepted"], "report.input.rows_accepted", 0, MAX_ROWS_CEILING)
    rows_rejected = _exact_int(inp["rows_rejected"], "report.input.rows_rejected", 0, MAX_ROWS_CEILING)
    rejections_raw = _exact_dict(
        inp["rejections"], "report.input.rejections", frozenset(REJECT_REASONS)
    )
    rejections = {
        reason: _exact_int(rejections_raw[reason], f"report.input.rejections.{reason}", 0, MAX_ROWS_CEILING)
        for reason in REJECT_REASONS
    }
    if sum(rejections.values()) != rows_rejected:
        raise EvaluatorInputError(
            "report.input: rejections do not sum to rows_rejected"
        )
    if rows_read < rows_accepted + rows_rejected:
        raise EvaluatorInputError(
            "report.input: rows_read < rows_accepted + rows_rejected"
        )

    ev = _exact_dict(outer["evaluation"], "report.evaluation", _REPORT_EVALUATION_KEYS)
    train_rows = _exact_int(ev["train_rows"], "report.evaluation.train_rows", 2, MAX_ROWS_CEILING)
    holdout_rows = _exact_int(ev["holdout_rows"], "report.evaluation.holdout_rows", 1, MAX_ROWS_CEILING)
    split_index = _exact_int(ev["split_index"], "report.evaluation.split_index", 2, MAX_ROWS_CEILING)
    if split_index != train_rows:
        raise EvaluatorInputError("report.evaluation: split_index != train_rows")
    if train_rows + holdout_rows != rows_accepted:
        raise EvaluatorInputError(
            "report.evaluation: train_rows + holdout_rows != rows_accepted"
        )
    unseen = _exact_int(
        ev["first_order_unseen_source_count"],
        "report.evaluation.first_order_unseen_source_count", 0, holdout_rows,
    )
    models_raw = _exact_dict(
        ev["models"], "report.evaluation.models", frozenset(MODEL_ALLOWLIST)
    )
    models: dict[str, dict[str, float]] = {}
    for name in MODEL_ALLOWLIST:
        metrics = _exact_dict(
            models_raw[name], f"report.evaluation.models.{name}", _MODEL_METRIC_KEYS
        )
        models[name] = {
            "nll_bits": _exact_float(metrics["nll_bits"], f"{name}.nll_bits", 0.0, _NLL_BITS_VALIDATION_MAX),
            "brier": _exact_float(metrics["brier"], f"{name}.brier", 0.0, BRIER_MAX),
            "top1_accuracy": _exact_float(metrics["top1_accuracy"], f"{name}.top1_accuracy", 0.0, 1.0),
            "ece": _exact_float(metrics["ece"], f"{name}.ece", 0.0, 1.0),
        }

    non_claims = outer["non_claims"]
    if type(non_claims) is not list or not non_claims or len(non_claims) > _MAX_NON_CLAIMS_ITEMS:
        raise EvaluatorInputError(
            f"report.non_claims: expected a non-empty list of at most "
            f"{_MAX_NON_CLAIMS_ITEMS} strings"
        )
    for i, item in enumerate(non_claims):
        _bounded_text(item, f"report.non_claims[{i}]")

    return {
        "smoothing": smoothing,
        "holdout_fraction": holdout_fraction,
        "max_rows": max_rows,
        "max_line_bytes": max_line_bytes,
        "vocabulary_size": vocabulary_size,
        "rows_read": rows_read,
        "rows_accepted": rows_accepted,
        "rows_rejected": rows_rejected,
        "rejections": rejections,
        "train_rows": train_rows,
        "holdout_rows": holdout_rows,
        "first_order_unseen_source_count": unseen,
        "models": models,
    }


def validate_receipt(obj: Any, field: str) -> dict[str, Any]:
    """Exact-type, fail-closed validation of one nextness-monitor-v1
    receipt. Returns an owned normalized dict.

    NOTE: internal CONSISTENCY (e.g. the abstain flag versus the stated
    reason) is deliberately NOT validated here — a well-formed receipt
    that contradicts itself is exactly the evidence the abstention
    section exists to report, so it must load successfully.
    """
    outer = _exact_dict(obj, field, _RECEIPT_KEYS)
    schema = _exact_str(outer["schema"], f"{field}.schema")
    if schema != RECEIPT_SCHEMA:
        raise EvaluatorInputError(
            f"{field}.schema: unknown variant {schema!r} (expected {RECEIPT_SCHEMA!r})"
        )
    model = _exact_str(outer["model"], f"{field}.model")
    if model not in MODEL_ALLOWLIST:
        raise EvaluatorInputError(f"{field}.model: {model!r} not in fixed allowlist")
    sufficiency = _exact_str(outer["sufficiency"], f"{field}.sufficiency")
    if sufficiency not in ("sufficient", "insufficient"):
        raise EvaluatorInputError(f"{field}.sufficiency: unknown variant {sufficiency!r}")
    reason = _exact_str(outer["abstain_reason"], f"{field}.abstain_reason")
    if reason not in ABSTAIN_REASONS:
        raise EvaluatorInputError(f"{field}.abstain_reason: unknown variant {reason!r}")

    cfg = _exact_dict(outer["config"], f"{field}.config", _RECEIPT_CONFIG_KEYS)
    # The emitter validates thresholds in the OPEN interval (0, 1) but
    # echoes them rounded to 6 dp, so a recorded echo can legitimately
    # be exactly 0.0 or 1.0 (e.g. 1e-9 rounds to 0.0) — the evaluator
    # accepts the CLOSED interval for the recorded echo.
    config = {
        "min_history": _exact_int(cfg["min_history"], f"{field}.config.min_history", 5, 10_000),
        "window": _exact_int(cfg["window"], f"{field}.config.window", 5, 10_000),
        "low_confidence_threshold": _exact_float(
            cfg["low_confidence_threshold"], f"{field}.config.low_confidence_threshold", 0.0, 1.0
        ),
        "calibration_error_threshold": _exact_float(
            cfg["calibration_error_threshold"], f"{field}.config.calibration_error_threshold", 0.0, 1.0
        ),
        "drift_threshold_bits": _exact_float(
            cfg["drift_threshold_bits"], f"{field}.config.drift_threshold_bits", 0.0, 1.0
        ),
    }

    return {
        "model": model,
        "observation_count": _exact_int(
            outer["observation_count"], f"{field}.observation_count", 0, MAX_ROWS_CEILING
        ),
        "mean_confidence": _exact_float(
            outer["mean_confidence"], f"{field}.mean_confidence", 0.0, 1.0
        ),
        "mean_surprise_bits": _exact_float(
            outer["mean_surprise_bits"], f"{field}.mean_surprise_bits", 0.0, SURPRISE_BITS_MAX
        ),
        "rolling_calibration_error": _exact_float(
            outer["rolling_calibration_error"], f"{field}.rolling_calibration_error", 0.0, 1.0
        ),
        "distribution_drift_bits": _exact_float(
            outer["distribution_drift_bits"], f"{field}.distribution_drift_bits", 0.0, 1.0
        ),
        "sufficiency": sufficiency,
        "abstain": _exact_bool(outer["abstain"], f"{field}.abstain"),
        "abstain_reason": reason,
        "input_reduced": _exact_bool(outer["input_reduced"], f"{field}.input_reduced"),
        "discarded_field_count": _exact_int(
            outer["discarded_field_count"], f"{field}.discarded_field_count", 0
        ),
        "non_claim": _bounded_text(outer["non_claim"], f"{field}.non_claim"),
        "config": config,
    }


def validate_receipt_series(obj: Any) -> list[dict[str, Any]]:
    """A recorded series: a JSON array of receipts (order = array order)
    or a single receipt object (a series of one). Bounded, fail closed."""
    if type(obj) is dict:
        return [validate_receipt(obj, "receipts[0]")]
    if type(obj) is not list:
        raise EvaluatorInputError(
            f"receipts: expected a receipt object or an array of receipts, "
            f"got {type(obj).__name__}"
        )
    if not obj:
        raise EvaluatorInputError("receipts: series is empty (no evidence to evaluate)")
    if len(obj) > MAX_SERIES_RECEIPTS:
        raise EvaluatorInputError(
            f"receipts: series has {len(obj)} receipts, exceeding the "
            f"{MAX_SERIES_RECEIPTS} bound"
        )
    return [validate_receipt(item, f"receipts[{i}]") for i, item in enumerate(obj)]


# ---------------------------------------------------------------------------
# Chronology witness
# ---------------------------------------------------------------------------


def chronology_witness(receipts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Series order is only trusted if observation_count strictly
    increases (each receipt saw more observations than the one before).
    Equal counts are ambiguous — a deterministic emitter produces
    byte-identical receipts for identical inputs, so an equal-count
    neighbour adds no ordering evidence — and are treated as a failed
    witness, not an error."""
    for i in range(1, len(receipts)):
        if receipts[i]["observation_count"] <= receipts[i - 1]["observation_count"]:
            return {"witnessed": False, "first_violation_index": i}
    return {"witnessed": True, "first_violation_index": None}


def series_comparability(receipts: Sequence[Mapping[str, Any]]) -> dict[str, bool]:
    """Order-free stability facts, deliberately SEPARATE from chronology.

    A strictly increasing observation_count says the receipts are
    ordered — it does not say they describe one regime. Cumulative
    block recovery is only meaningful over one predictor model
    (the recorded means are model-derived), and abstention transitions
    are only meaningful when both the model and the monitor
    configuration (the thresholds the decisions were made under) held
    still. Both facts ARE recorded per receipt, so they are checked,
    never assumed.
    """
    return {
        "model_stable": all(r["model"] == receipts[0]["model"] for r in receipts),
        "config_stable": all(r["config"] == receipts[0]["config"] for r in receipts),
    }


# ---------------------------------------------------------------------------
# Section: prediction (NP1 report evidence)
# ---------------------------------------------------------------------------

_REQUIRES_REPORT: Final[str] = "an NP1 nextness-predictor-v1 report artifact"
_REQUIRES_RECEIPTS: Final[str] = "an NP2 nextness-monitor-v1 receipt series artifact"


def _ranking(models: Mapping[str, Mapping[str, float]], metric: str, *, descending: bool) -> list[str]:
    """Deterministic model ranking; ties broken by canonical
    MODEL_ALLOWLIST order (the enumeration index)."""
    order = {name: i for i, name in enumerate(MODEL_ALLOWLIST)}
    return sorted(
        MODEL_ALLOWLIST,
        key=lambda name: (
            -models[name][metric] if descending else models[name][metric],
            order[name],
        ),
    )


def _prediction_section(report: Mapping[str, Any] | None) -> dict[str, Any]:
    if report is None:
        absent = _not_computable("artifact_absent", _REQUIRES_REPORT)
        return {
            "uniform_nll_bits": absent,
            "models": absent,
            "rankings": absent,
            "proper_score_rankings_agree": absent,
            "ingestion": absent,
            "metric_difference_significance": _not_computable(
                "artifact_absent", _REQUIRES_REPORT
            ),
        }
    models = report["models"]
    uniform_nll = math.log2(report["vocabulary_size"])
    per_model = {
        name: {
            "nll_bits": _computed(models[name]["nll_bits"]),
            # "gap", not "improvement": the sign says which side of the
            # uniform reference the model landed on, nothing more.
            "nll_gap_to_uniform_bits": _computed(uniform_nll - models[name]["nll_bits"]),
            "brier": _computed(models[name]["brier"]),
            "top1_accuracy": _computed(models[name]["top1_accuracy"]),
        }
        for name in MODEL_ALLOWLIST
    }
    rankings = {
        "by_nll_bits": _ranking(models, "nll_bits", descending=False),
        "by_brier": _ranking(models, "brier", descending=False),
        "by_top1_accuracy": _ranking(models, "top1_accuracy", descending=True),
    }
    return {
        "uniform_nll_bits": _computed(uniform_nll),
        "models": per_model,
        "rankings": _computed(rankings),
        "proper_score_rankings_agree": _computed(
            rankings["by_nll_bits"] == rankings["by_brier"]
        ),
        "ingestion": _computed(
            {
                "rows_read": report["rows_read"],
                "rows_accepted": report["rows_accepted"],
                "rejection_rate": report["rows_rejected"] / report["rows_read"],
                "train_rows": report["train_rows"],
                "holdout_rows": report["holdout_rows"],
                "first_order_unseen_source_rate": (
                    report["first_order_unseen_source_count"] / report["holdout_rows"]
                ),
            }
        ),
        "metric_difference_significance": _not_computable(
            "field_not_recorded",
            "per-observation outcomes (the report records holdout means only, "
            "so no variance estimate or significance statement is possible)",
        ),
    }


# ---------------------------------------------------------------------------
# Section: calibration (either artifact)
# ---------------------------------------------------------------------------


def _calibration_section(
    report: Mapping[str, Any] | None,
    receipts: Sequence[Mapping[str, Any]] | None,
    order: Mapping[str, Any] | None,
) -> dict[str, Any]:
    section: dict[str, Any] = {}
    if report is None:
        section["holdout_ece_by_model"] = _not_computable("artifact_absent", _REQUIRES_REPORT)
        section["ece_bin_width"] = _not_computable("artifact_absent", _REQUIRES_REPORT)
    else:
        section["holdout_ece_by_model"] = _computed(
            {name: report["models"][name]["ece"] for name in MODEL_ALLOWLIST}
        )
        section["ece_bin_width"] = _computed(1.0 / ECE_BINS)
    if receipts is None:
        section["max_rolling_calibration_error"] = _not_computable(
            "artifact_absent", _REQUIRES_RECEIPTS
        )
        section["latest_rolling_calibration_error"] = _not_computable(
            "artifact_absent", _REQUIRES_RECEIPTS
        )
    else:
        # max over the series is order-free; "latest" needs the witness.
        section["max_rolling_calibration_error"] = _computed(
            max(r["rolling_calibration_error"] for r in receipts)
        )
        if order is not None and order["witnessed"]:
            section["latest_rolling_calibration_error"] = _computed(
                receipts[-1]["rolling_calibration_error"]
            )
        else:
            section["latest_rolling_calibration_error"] = _not_computable(
                "order_not_witnessed",
                "strictly increasing observation_count across the series",
            )
    section["miscalibration_direction"] = _not_computable(
        "field_not_recorded",
        "signed per-bin confidence-accuracy gaps (both artifacts record "
        "absolute-gap ECE only, so over- versus under-confidence cannot be "
        "distinguished)",
    )
    return section


# ---------------------------------------------------------------------------
# Section: abstention (NP2 receipt evidence; tri-state consistency)
# ---------------------------------------------------------------------------


def _cmp_recorded(a: float, b: float) -> int:
    """Compare two RECORDED (6-dp-rounded) values with the derived
    tolerance: returns -1 (a definitely below b), 1 (definitely above),
    0 (indistinguishable within worst-case rounding error)."""
    if a <= b - CONTRADICTION_TOLERANCE:
        return -1
    if a >= b + CONTRADICTION_TOLERANCE:
        return 1
    return 0


def check_receipt_consistency(receipt: Mapping[str, Any]) -> dict[str, str]:
    """Per-receipt tri-state verdicts for the fixed CONSISTENCY_CHECKS.

    Only clauses witnessed by RECORDED fields can be judged; a clause
    depending on the unrecorded latest observation (its confidence or
    prev_seen flag) is ``unverifiable`` — that is the honest limit of
    the v1 receipt schema, not a defect of the receipt.
    """
    n = receipt["observation_count"]
    cfg = receipt["config"]
    reason = receipt["abstain_reason"]
    ece = receipt["rolling_calibration_error"]
    drift = receipt["distribution_drift_bits"]
    cal_thr = cfg["calibration_error_threshold"]
    drift_thr = cfg["drift_threshold_bits"]
    history_ok = n >= cfg["min_history"]

    verdicts: dict[str, str] = {}

    verdicts["abstain_flag_matches_reason"] = (
        "consistent" if receipt["abstain"] == (reason != "none") else "contradicted"
    )
    verdicts["sufficiency_matches_history"] = (
        "consistent"
        if (receipt["sufficiency"] == "sufficient") == history_ok
        else "contradicted"
    )

    # Higher-precedence exclusion, honest truth table. Decision
    # precedence is fixed (insufficient_history > unseen_state >
    # low_confidence > calibration_drift > distribution_shift > none),
    # but the v1 receipt records neither the latest observation's
    # prev_seen (unseen_state trigger) nor its confidence
    # (low_confidence trigger). So:
    #   - a RECORDED earlier trigger firing => contradicted;
    #   - otherwise, if an UNRECORDED earlier trigger could have fired,
    #     the verdict is unverifiable — never consistent;
    #   - "consistent" survives only where every earlier clause is
    #     recorded and shown not to fire (insufficient_history, which
    #     has no earlier clause, and unseen_state, whose only earlier
    #     clause is the recorded history check).
    if reason == "insufficient_history":
        excluded = "consistent"
    elif not history_ok:
        excluded = "contradicted"  # recorded higher trigger fired
    elif reason == "unseen_state":
        excluded = "consistent"
    elif reason == "distribution_shift" and _cmp_recorded(ece, cal_thr) > 0:
        excluded = "contradicted"  # recorded calibration_drift should have fired
    elif reason == "none" and (
        _cmp_recorded(ece, cal_thr) > 0 or _cmp_recorded(drift, drift_thr) > 0
    ):
        excluded = "contradicted"  # recorded drift/calibration should have fired
    else:
        # low_confidence / calibration_drift / distribution_shift / none
        # with no recorded contradiction: unseen_state (and, below
        # low_confidence, the confidence trigger) is unrecorded and
        # could have fired.
        excluded = "unverifiable"
    verdicts["higher_precedence_excluded"] = excluded

    # The stated reason's own trigger, where the receipt records it.
    if reason == "insufficient_history":
        trigger = "consistent" if not history_ok else "contradicted"
    elif reason == "calibration_drift":
        trigger = "contradicted" if _cmp_recorded(ece, cal_thr) < 0 else "consistent"
    elif reason == "distribution_shift":
        trigger = "contradicted" if _cmp_recorded(drift, drift_thr) < 0 else "consistent"
    else:
        # unseen_state and low_confidence depend on the latest
        # observation's prev_seen / confidence; "none" additionally
        # asserts both non-triggers. None of those fields is recorded.
        trigger = "unverifiable"
    verdicts["stated_reason_trigger"] = trigger

    return verdicts


def _abstention_section(receipts: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    if receipts is None:
        absent = _not_computable("artifact_absent", _REQUIRES_RECEIPTS)
        return {
            "receipt_count": absent,
            "abstention_rate": absent,
            "reason_counts": absent,
            "configurations_identical": absent,
            "consistency": absent,
            "abstention_quality": _not_computable("artifact_absent", _REQUIRES_RECEIPTS),
        }
    n = len(receipts)
    reason_counts = {reason: 0 for reason in ABSTAIN_REASONS}
    abstained = 0
    for r in receipts:
        reason_counts[r["abstain_reason"]] += 1
        abstained += 1 if r["abstain"] else 0

    consistency: dict[str, Any] = {}
    for check in CONSISTENCY_CHECKS:
        tallies = {verdict: 0 for verdict in VERDICTS}
        contradicted_indices: list[int] = []
        for i, r in enumerate(receipts):
            verdict = check_receipt_consistency(r)[check]
            tallies[verdict] += 1
            if verdict == "contradicted":
                contradicted_indices.append(i)
        consistency[check] = {
            "verdicts": tallies,
            "contradicted_indices": contradicted_indices[:MAX_DETAIL_ITEMS],
            "contradicted_indices_truncated": len(contradicted_indices) > MAX_DETAIL_ITEMS,
        }

    return {
        "receipt_count": _computed(n),
        "abstention_rate": _computed(abstained / n),
        "reason_counts": _computed(reason_counts),
        # Mixed configurations mean the reason histogram aggregates
        # different operating regimes — flagged, not forbidden.
        "configurations_identical": _computed(
            all(r["config"] == receipts[0]["config"] for r in receipts)
        ),
        "consistency": _computed(consistency),
        "abstention_quality": _not_computable(
            "field_not_recorded",
            "per-observation outcomes during abstained spans (receipts record "
            "aggregates only, so whether an abstention was warranted cannot be "
            "established from the artifacts)",
        ),
    }


# ---------------------------------------------------------------------------
# Section: recovery after surprise (ordered NP2 series evidence)
# ---------------------------------------------------------------------------


def _block_means(
    receipts: Sequence[Mapping[str, Any]], field: str, low: float, high: float
) -> dict[str, Any]:
    """Recover the mean of FIELD over each inter-receipt observation
    block, with propagated rounding-error bounds.

    Under the prefix-extension assumption, receipt i's mean over n_i
    observations and receipt i+1's mean over n_{i+1} observations
    algebraically determine the mean over the (n_{i+1} - n_i) NEW
    observations: (n2*m2 - n1*m1) / (n2 - n1). Each recorded mean
    carries at most 5e-7 rounding error, so the recovered block mean
    carries at most (n1 + n2) * 5e-7 / (n2 - n1) — reported alongside
    every value, because it grows without bound as blocks shrink
    relative to the running total.

    A block mean outside [low, high] by more than its error bound is
    impossible for per-observation values bounded in [low, high], so it
    FALSIFIES the prefix-extension assumption for this series — reported
    as ``within_bounds`` per block and rolled up by the caller.
    """
    blocks: list[dict[str, float | bool]] = []
    for prev, curr in zip(receipts, receipts[1:]):
        n1, n2 = prev["observation_count"], curr["observation_count"]
        m1, m2 = prev[field], curr[field]
        width = n2 - n1  # witness guarantees width >= 1
        mean = (n2 * m2 - n1 * m1) / width
        bound = (n1 + n2) * 5e-7 / width
        blocks.append(
            {
                "block_mean": mean,
                "error_bound": bound,
                "within_bounds": (low - bound) <= mean <= (high + bound),
            }
        )
    return {
        "blocks": blocks[:MAX_DETAIL_ITEMS],
        "blocks_truncated": len(blocks) > MAX_DETAIL_ITEMS,
        "block_count": len(blocks),
        "all_within_bounds": all(b["within_bounds"] for b in blocks),
    }


def _recovery_section(
    receipts: Sequence[Mapping[str, Any]] | None,
    order: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if receipts is None:
        absent = _not_computable("artifact_absent", _REQUIRES_RECEIPTS)
        return {
            "chronology": absent,
            "series_comparability": absent,
            "abstention_transitions": absent,
            "surprise_blocks": absent,
            "confidence_blocks": absent,
            "per_observation_recovery": _not_computable(
                "artifact_absent", _REQUIRES_RECEIPTS
            ),
        }
    assert order is not None
    comparability = series_comparability(receipts)
    section: dict[str, Any] = {
        "chronology": _computed(dict(order)),
        "series_comparability": _computed(dict(comparability)),
    }

    # Gate precedence (first failed gate names the typed reason):
    # order_not_witnessed > series_too_short > model_not_stable >
    # config_not_stable. Chronology and comparability are separate
    # contracts — a well-ordered series over mixed regimes is still
    # incomparable, and vice versa.
    if not order["witnessed"]:
        blocked = _not_computable(
            "order_not_witnessed",
            "strictly increasing observation_count across the series",
        )
        section["abstention_transitions"] = blocked
        section["surprise_blocks"] = blocked
        section["confidence_blocks"] = blocked
    elif len(receipts) < 2:
        short = _not_computable(
            "series_too_short", "at least two chronologically witnessed receipts"
        )
        section["abstention_transitions"] = short
        section["surprise_blocks"] = short
        section["confidence_blocks"] = short
    elif not comparability["model_stable"]:
        mixed = _not_computable(
            "model_not_stable",
            "a single predictor model across the series (cumulative means "
            "from different models cannot be combined into blocks, and "
            "their abstention decisions describe different predictors)",
        )
        section["abstention_transitions"] = mixed
        section["surprise_blocks"] = mixed
        section["confidence_blocks"] = mixed
    elif not comparability["config_stable"]:
        # Cumulative means are config-independent (they aggregate the
        # model's own observations), so blocks stay computable; the
        # abstention decisions were made under different thresholds, so
        # transitions between them are not one monitor reorienting.
        section["abstention_transitions"] = _not_computable(
            "config_not_stable",
            "a single monitor configuration across the series (decisions "
            "under different thresholds are not one monitor's trajectory)",
        )
        section["surprise_blocks"] = _computed(
            _block_means(receipts, "mean_surprise_bits", 0.0, SURPRISE_BITS_MAX)
        )
        section["confidence_blocks"] = _computed(
            _block_means(receipts, "mean_confidence", 0.0, 1.0)
        )
    else:
        onsets = 0          # abstain False -> True between neighbours
        reorientations = 0  # abstain True -> False between neighbours
        run_lengths: list[int] = []  # completed abstaining runs, in receipts
        current_run = 1 if receipts[0]["abstain"] else 0
        for prev, curr in zip(receipts, receipts[1:]):
            if not prev["abstain"] and curr["abstain"]:
                onsets += 1
                current_run = 1
            elif prev["abstain"] and curr["abstain"]:
                current_run += 1
            elif prev["abstain"] and not curr["abstain"]:
                reorientations += 1
                run_lengths.append(current_run)
                current_run = 0
        trailing = current_run if receipts[-1]["abstain"] else None
        section["abstention_transitions"] = _computed(
            {
                "abstention_onsets": onsets,
                "reorientations": reorientations,
                "completed_abstention_run_lengths_receipts": run_lengths[:MAX_DETAIL_ITEMS],
                "run_lengths_truncated": len(run_lengths) > MAX_DETAIL_ITEMS,
                "unresolved_trailing_abstention_receipts": trailing,
            }
        )
        section["surprise_blocks"] = _computed(
            _block_means(receipts, "mean_surprise_bits", 0.0, SURPRISE_BITS_MAX)
        )
        section["confidence_blocks"] = _computed(
            _block_means(receipts, "mean_confidence", 0.0, 1.0)
        )

    section["per_observation_recovery"] = _not_computable(
        "field_not_recorded",
        "per-observation surprise values (receipts record cumulative means "
        "only; recovery is resolvable at receipt granularity, never at "
        "observation granularity)",
    )
    return section


# ---------------------------------------------------------------------------
# Section: cross-artifact check (conditional on an unrecordable premise)
# ---------------------------------------------------------------------------


def _capped_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Cross-check result lists follow the same explicit-truncation
    convention as every other detail list: capped at MAX_DETAIL_ITEMS
    (series order is the deterministic selection rule), full count kept."""
    return {
        "results": results[:MAX_DETAIL_ITEMS],
        "results_truncated": len(results) > MAX_DETAIL_ITEMS,
        "covering_receipt_count": len(results),
    }


def _cross_check_section(
    report: Mapping[str, Any] | None,
    receipts: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    if report is None or receipts is None:
        missing = _REQUIRES_REPORT if report is None else _REQUIRES_RECEIPTS
        return {
            "assumption": ASSUMPTION_SAME_SOURCE,
            "ece_match": _not_computable("artifact_absent", missing),
            "surprise_nll_match": _not_computable("artifact_absent", missing),
        }
    holdout_rows = report["holdout_rows"]
    # A receipt "covers" the report's evaluation when it saw exactly the
    # full holdout AND its rolling window spans the whole holdout — then
    # (under the same-source assumption) its rolling ECE is the same
    # computation as the report's holdout ECE, and its mean surprise is
    # the report's nll_bits.
    covering = [
        r
        for r in receipts
        if r["observation_count"] == holdout_rows and r["config"]["window"] >= holdout_rows
    ]
    if not covering:
        blocked = _not_computable(
            "no_covering_receipt",
            f"a receipt with observation_count == {holdout_rows} (the report's "
            f"holdout_rows) and config.window >= {holdout_rows}",
        )
        return {
            "assumption": ASSUMPTION_SAME_SOURCE,
            "ece_match": blocked,
            "surprise_nll_match": blocked,
        }

    ece_results: list[dict[str, Any]] = []
    surprise_results: list[dict[str, Any]] = []
    for r in covering:
        model = r["model"]
        report_ece = report["models"][model]["ece"]
        ece_results.append(
            {
                "model": model,
                "report_ece": report_ece,
                "receipt_rolling_calibration_error": r["rolling_calibration_error"],
                "verdict": (
                    "consistent"
                    if abs(report_ece - r["rolling_calibration_error"]) <= CROSS_CHECK_TOLERANCE
                    else "contradicted"
                ),
            }
        )
        report_nll = report["models"][model]["nll_bits"]
        surprise = r["mean_surprise_bits"]
        # The two emitters record extreme per-observation surprise
        # differently: for P(actual) < 1e-300 NP1 floors at exactly
        # NLL_BITS_MAX bits while NP2 records up to 1000 bits, so the
        # two MEANS legitimately diverge by up to (1000 - NLL_BITS_MAX)/n
        # — far beyond the tolerance. The divergence is only POSSIBLE if
        # some single observation reached the floor, and per-observation
        # surprises are non-negative, so max per-obs <= mean * n: if a
        # recorded mean-times-count stays below NLL_BITS_MAX, that
        # artifact witnesses that NO observation was in the divergent
        # regime. One floored observation forces BOTH totals above
        # NLL_BITS_MAX (minus <=0.5 receipt rounding at n <= 1e6), so
        # the comparison is unverifiable only when BOTH totals clear the
        # threshold (1.0-bit margin, failing toward "unverifiable").
        n_receipt = r["observation_count"]
        cap_possible = (
            report_nll * holdout_rows >= NLL_BITS_MAX - 1.0
            and surprise * n_receipt >= NLL_BITS_MAX - 1.0
        )
        if cap_possible:
            verdict = "unverifiable"
        else:
            verdict = (
                "consistent"
                if abs(report_nll - surprise) <= CROSS_CHECK_TOLERANCE
                else "contradicted"
            )
        surprise_results.append(
            {
                "model": model,
                "report_nll_bits": report_nll,
                "receipt_mean_surprise_bits": surprise,
                "verdict": verdict,
            }
        )
    return {
        "assumption": ASSUMPTION_SAME_SOURCE,
        "ece_match": _computed(_capped_results(ece_results)),
        "surprise_nll_match": _computed(_capped_results(surprise_results)),
    }


# ---------------------------------------------------------------------------
# End-to-end evaluation
# ---------------------------------------------------------------------------


def evaluate(
    *,
    report: Mapping[str, Any] | None = None,
    receipts: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """One deterministic evaluation over already-VALIDATED artifacts
    (see validate_report / validate_receipt_series). At least one
    artifact is required — with neither there is no evidence at all."""
    if report is None and receipts is None:
        raise EvaluatorInputError("no artifacts provided: nothing to evaluate")

    order = chronology_witness(receipts) if receipts is not None else None
    recovery = _recovery_section(receipts, order)
    cross = _cross_check_section(report, receipts)

    # Assumptions are listed IFF a computed value in this evaluation
    # depends on them (deterministic function of the inputs). The
    # prefix-extension assumption is used exactly when block recovery
    # actually ran — i.e. when its complete preconditions held.
    assumptions: list[str] = []
    if recovery["surprise_blocks"]["status"] == "computed":
        assumptions.append(ASSUMPTION_PREFIX_EXTENSION)
    if cross["ece_match"]["status"] == "computed":
        assumptions.append(ASSUMPTION_SAME_SOURCE)

    return {
        "schema": EVALUATION_SCHEMA,
        "config": {
            "max_input_bytes": MAX_INPUT_BYTES,
            "max_series_receipts": MAX_SERIES_RECEIPTS,
            "max_detail_items": MAX_DETAIL_ITEMS,
            "contradiction_tolerance": CONTRADICTION_TOLERANCE,
            "cross_check_tolerance": CROSS_CHECK_TOLERANCE,
            "max_evaluation_bytes": MAX_EVALUATION_BYTES,
        },
        "assumptions": assumptions,
        "prediction": _prediction_section(report),
        "calibration": _calibration_section(report, receipts, order),
        "abstention": _abstention_section(receipts),
        "recovery": recovery,
        "cross_check": cross,
        "non_claims": list(NON_CLAIMS),
    }


def build_evaluation(
    *,
    report_path: pathlib.Path | None = None,
    receipts_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Load, validate and evaluate artifact files, attaching SHA-256
    provenance (of the raw bytes — sufficient to reproduce every
    calculation, with no paths, timestamps or environment leakage)."""
    report = None
    receipts = None
    artifacts: dict[str, Any] = {
        "report": {"provided": False},
        "receipts": {"provided": False},
    }
    if report_path is not None:
        parsed, digest, size = load_json_artifact(report_path)
        report = validate_report(parsed)
        artifacts["report"] = {
            "provided": True,
            "sha256": digest,
            "bytes": size,
            "schema": REPORT_SCHEMA,
        }
    if receipts_path is not None:
        parsed, digest, size = load_json_artifact(receipts_path)
        receipts = validate_receipt_series(parsed)
        artifacts["receipts"] = {
            "provided": True,
            "sha256": digest,
            "bytes": size,
            "schema": RECEIPT_SCHEMA,
            "receipt_count": len(receipts),
        }
    evaluation = evaluate(report=report, receipts=receipts)
    evaluation["artifacts"] = artifacts
    serialized = serialize_evaluation(evaluation)
    if len(serialized.encode("utf-8")) > MAX_EVALUATION_BYTES:
        raise EvaluationTooLargeError(
            f"evaluation would exceed {MAX_EVALUATION_BYTES} bytes; refusing to emit"
        )
    return evaluation


def serialize_evaluation(evaluation: Mapping[str, Any]) -> str:
    """Canonical serialization: sorted keys, fixed separators, newline
    (identical convention to NP1 reports and NP2 receipts)."""
    return json.dumps(evaluation, sort_keys=True, separators=(",", ": "), indent=1) + "\n"


# ---------------------------------------------------------------------------
# Write-boundary guard (mirrors nextness_predictor's convention)
# ---------------------------------------------------------------------------


def _repo_data_dir() -> pathlib.Path:
    return (pathlib.Path(__file__).resolve().parent.parent / "data").resolve()


def validate_output_path(
    out_path: pathlib.Path, inputs: Mapping[str, pathlib.Path]
) -> None:
    """--output may land ONLY inside the primary input artifact's
    directory (the --report file when provided, else the --receipts
    file), NEVER inside the repository ``data/`` tree — the same rule
    nextness_predictor enforces for its own reports — and NEVER on a
    path that IS any supplied input artifact (corrected-NP6/NP8
    semantics): by resolved path (which also covers lexical and symlink
    aliases, dangling ones included — resolution targets are compared,
    not link or segment names) or by file identity
    (``os.path.samefile`` on the RESOLVED paths: device + inode / file
    ID, which covers existing hard links whose paths differ).

    ``inputs`` maps role name (``"report"`` / ``"receipts"``) to the
    supplied path. The primary is selected EXPLICITLY by fixed role
    order — ``report`` when present, else ``receipts`` — never by the
    mapping's insertion order, and identity is checked against EVERY
    recognized entry in that same fixed order, not merely the primary.
    An empty mapping is a descriptive ``EvaluatorInputError``, never a
    bare ``StopIteration``.

    Residual filesystem race, stated precisely (same as NP6/NP8):
    identity is verified at validation time; the later write does not
    re-verify. A concurrent actor replacing the output path between
    validation and write can still redirect the write. This guard
    defends against aliases that exist when it validates — it does not
    claim protection against concurrent hostile filesystem manipulation.
    """
    # Fixed, explicit role order (report first) — primary selection and
    # identity iteration are independent of how the mapping was built.
    ordered = [(role, inputs[role]) for role in ("report", "receipts") if role in inputs]
    if not ordered:
        raise EvaluatorInputError(
            "no input artifact supplied for output validation: provide "
            "report and/or receipts"
        )
    primary = ordered[0][1]
    input_dir_resolved = primary.resolve().parent
    out_resolved = out_path.resolve()
    try:
        out_resolved.relative_to(input_dir_resolved)
    except ValueError as e:
        raise WriteOutsideLogDirError(
            f"refusing to write evaluation outside the primary input "
            f"artifact's directory: {out_resolved} is not inside {input_dir_resolved}"
        ) from e
    for role, input_path in ordered:
        input_resolved = input_path.resolve()
        if out_resolved == input_resolved:
            raise WriteOutsideLogDirError(
                f"refusing to overwrite the input {role} artifact: {out_resolved}"
            )
        # Hard links share identity while having distinct paths. Only an
        # EXISTING output can alias an input; stat runs on the resolved
        # paths and any failure to verify is itself a refusal (fail
        # closed), never a fall-through.
        if out_resolved.exists():
            try:
                same = os.path.samefile(out_resolved, input_resolved)
            except OSError as e:
                raise WriteOutsideLogDirError(
                    f"cannot verify output file identity against the input "
                    f"{role} artifact: {out_resolved}"
                ) from e
            if same:
                raise WriteOutsideLogDirError(
                    f"refusing to overwrite the input {role} artifact "
                    f"(shared file identity): {out_resolved}"
                )
    data_dir = _repo_data_dir()
    if out_resolved == data_dir or data_dir in out_resolved.parents:
        raise WriteOutsideLogDirError(
            f"refusing to write evaluation inside the repository data/ tree: {out_resolved}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic offline evaluation of recorded NP1 reports and "
            "NP2 receipt series (observes and scores artifacts only; see "
            "module docstring for the full contract)."
        )
    )
    parser.add_argument(
        "--report", type=pathlib.Path, default=None,
        help="path to a recorded nextness-predictor-v1 report (JSON)",
    )
    parser.add_argument(
        "--receipts", type=pathlib.Path, default=None,
        help=(
            "path to a recorded nextness-monitor-v1 receipt or JSON array "
            "of receipts (array order = series order)"
        ),
    )
    parser.add_argument(
        "--output", type=pathlib.Path, default=None,
        help=(
            "optional evaluation path; must resolve inside the primary "
            "input artifact's directory, outside the repository data/ "
            "tree, and must not name or alias any supplied input "
            "artifact (default: stdout)"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Exit-code contract (mirrors NP1's expected-failure contract):

    - ``0`` success
    - ``2`` validation failure — missing/oversized/malformed artifact,
      unknown schema variant, or no artifact provided (argparse's own
      usage errors also exit 2)
    - ``4`` output-path failure — write-boundary violation or an
      unwritable target
    - ``5`` evaluation exceeds MAX_EVALUATION_BYTES (fail closed)

    There is no exit-3: "not enough evidence" is never a CLI failure
    here — it is a typed not_computable result inside a successful
    evaluation. Every expected failure prints one concise ``error:``
    line to stderr — never a traceback; unexpected programming errors
    propagate loudly.
    """
    args = _build_parser().parse_args(argv)
    if args.report is None and args.receipts is None:
        print("error: provide --report and/or --receipts", file=sys.stderr)
        return 2
    for label, path in (("report", args.report), ("receipts", args.receipts)):
        if path is not None and not path.is_file():
            print(f"error: {label} artifact not found: {path}", file=sys.stderr)
            return 2
    # Primary-first, fixed role order; identity is checked against every
    # supplied input, and validation runs BEFORE any artifact is parsed
    # or any evaluation computed.
    inputs: dict[str, pathlib.Path] = {}
    if args.report is not None:
        inputs["report"] = args.report
    if args.receipts is not None:
        inputs["receipts"] = args.receipts
    try:
        if args.output is not None:
            validate_output_path(args.output, inputs)
        evaluation = build_evaluation(
            report_path=args.report, receipts_path=args.receipts
        )
    except WriteOutsideLogDirError as e:
        print(f"error: {e}", file=sys.stderr)
        return 4
    except EvaluationTooLargeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 5
    except EvaluatorInputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    serialized = serialize_evaluation(evaluation)
    if args.output is not None:
        try:
            # Raw byte write: no platform newline translation, no
            # dependence on Path.write_text's newline= parameter (which
            # only exists on newer Pythons) — a recorded evaluation's
            # bytes and sha256 must not depend on the producing
            # interpreter or operating system.
            args.output.write_bytes(serialized.encode("utf-8"))
        except OSError as e:
            print(f"error: cannot write evaluation to {args.output}: {e}", file=sys.stderr)
            return 4
    else:
        sys.stdout.write(serialized)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
