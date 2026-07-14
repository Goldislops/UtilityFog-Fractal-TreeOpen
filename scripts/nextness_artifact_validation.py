"""Public structural validators for recorded Nextness artifacts (NP9).

Full object-level validation for the three recorded artifact schemas
that previously had no public validator:

- ``nextness-evaluation-v1``  -> :func:`validate_evaluation_artifact`
- ``nextness-replay-lab-v1``  -> :func:`validate_lab_artifact`
- ``nextness-evidence-packet-v1`` -> :func:`validate_evidence_packet`

plus bounded file-loading counterparts (:func:`load_evaluation_artifact`,
:func:`load_lab_artifact`, :func:`load_evidence_packet`) that add a
pre-parse size ceiling, duplicate-JSON-key rejection and a recursion
fail-closed guard in front of the object validators.

VALIDATION ONLY (load-bearing): nothing here scores, ranks, tunes,
repairs or silently normalizes malformed evidence. A validator either
returns a sanitized built-in copy of the artifact (the caller's object
is never mutated and never aliased into the result) or raises
:class:`ArtifactValidationError` with a deterministic, field-anchored
message. No filesystem write exists in any library function.

WHAT STRUCTURAL VALIDATION ESTABLISHES — AND WHAT IT CANNOT:

- It establishes that an object has exactly the v1 shape the live
  emitters produce: exact key sets at every level, exact builtin types
  (bool never passes as int), finite numbers in documented ranges,
  fixed vocabularies, envelope forms, truncation indicators that agree
  with their lists, and the cross-field identities the artifact itself
  records (counts that must sum, gates that must cohere, assumptions
  that must match computed sections).
- It does NOT recompute prediction metrics (that needs the underlying
  report/receipts), does NOT verify provenance hashes against real
  bytes (that is NP8's job — a structurally valid ``broken`` link stays
  broken), and does NOT establish that replay decisions were correct
  (that needs the source log). Invariants hidden by truncation (e.g.
  run-length sums when the list was capped) are checked only in the
  untruncated case, where the artifact actually establishes them.

Safety contract (Lane B, mirrors NP5/NP6/NP8): offline; no network; no
model, engine, orchestrator or provider import; fixed input bounds
(1 MiB per artifact file); deterministic behavior with no timestamps,
randomness or environment dependence.
"""

from __future__ import annotations

import json
import math
import pathlib
from collections.abc import Mapping
from typing import Any, Final

from scripts.nextness_evaluator import (
    ASSUMPTION_PREFIX_EXTENSION,
    ASSUMPTION_SAME_SOURCE,
    CONSISTENCY_CHECKS,
    CONTRADICTION_TOLERANCE,
    CROSS_CHECK_TOLERANCE,
    EVALUATION_SCHEMA,
    MAX_EVALUATION_BYTES,
    MAX_INPUT_BYTES,
    MAX_SERIES_RECEIPTS,
    NOT_COMPUTABLE_REASONS,
    VERDICTS,
)
from scripts.nextness_evaluator import MAX_DETAIL_ITEMS as EVAL_MAX_DETAIL_ITEMS
from scripts.nextness_evaluator import NON_CLAIMS as EVALUATION_NON_CLAIMS
from scripts.nextness_evidence_packet import (
    LINK_KINDS,
    LINK_NOT_COMPUTABLE_REASONS,
    MAX_LOG_BYTES,
    MAX_PACKET_ARTIFACTS,
    MAX_PACKET_BYTES,
    PACKET_SCHEMA,
    ROLES,
)
from scripts.nextness_evidence_packet import NON_CLAIMS as PACKET_NON_CLAIMS
from scripts.nextness_monitor import ABSTAIN_REASONS, MODEL_ALLOWLIST, RECEIPT_SCHEMA
from scripts.nextness_predictor import (
    HOLDOUT_FRACTION_MAX,
    HOLDOUT_FRACTION_MIN,
    MAX_LINE_BYTES_DEFAULT,
    MAX_ROWS_CEILING,
    MAX_ROWS_DEFAULT,
    REJECT_REASONS,
    REPORT_SCHEMA,
    SMOOTHING_MAX,
)
from scripts.nextness_replay_lab import (
    LAB_SCHEMA,
    MAX_LAB_CONFIGS,
    MAX_LAB_REPORT_BYTES,
    MAX_LABEL_CHARS,
    MAX_REPLAY_STEPS,
)
from scripts.nextness_replay_lab import MAX_DETAIL_ITEMS as LAB_MAX_DETAIL_ITEMS
from scripts.nextness_replay_lab import NON_CLAIMS as LAB_NON_CLAIMS

# ---------------------------------------------------------------------------
# Contract constants
# ---------------------------------------------------------------------------

#: Pre-parse ceiling for the file loaders (same bound NP5/NP8 use).
MAX_ARTIFACT_BYTES: Final[int] = MAX_INPUT_BYTES

#: Bounded free-text ceiling (requires/non-claim strings).
_MAX_TEXT_CHARS: Final[int] = 500

_HEX64: Final[frozenset[str]] = frozenset("0123456789abcdef")

_SUFFICIENCY: Final[tuple[str, ...]] = ("sufficient", "insufficient")

#: Fixed validation-depth vocabulary the packet manifest may carry.
PACKET_VALIDATION_DEPTHS: Final[tuple[str, ...]] = (
    "full", "schema_identifier_only", "sequence_reader",
)

#: Per-role schema identifiers the packet manifest may carry.
_PACKET_SCHEMA_BY_ROLE: Final[dict[str, str]] = {
    "report": REPORT_SCHEMA,
    "receipts": RECEIPT_SCHEMA,
    "evaluation": EVALUATION_SCHEMA,
    "lab": LAB_SCHEMA,
    "protocol": "nextness-replay-protocol-v1",
    "log": "jsonl-nextness-runs",
}


class ArtifactValidationError(ValueError):
    """A malformed, hostile or unknown-variant artifact (fail closed)."""


# ---------------------------------------------------------------------------
# Exact-type primitives (no conversion hook, no hostile repr, no subclass
# is ever iterated or member-accessed before its exact type is proven)
# ---------------------------------------------------------------------------


def _exact_str(value: Any, field: str) -> str:
    if type(value) is not str:
        raise ArtifactValidationError(
            f"{field}: expected builtin str, got {type(value).__name__}"
        )
    return value


def _exact_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise ArtifactValidationError(
            f"{field}: expected builtin bool, got {type(value).__name__}"
        )
    return value


def _exact_int(value: Any, field: str, low: int, high: int | None = None) -> int:
    if type(value) is not int:
        raise ArtifactValidationError(
            f"{field}: expected builtin int, got {type(value).__name__}"
        )
    if value < low or (high is not None and value > high):
        bound = f"[{low}, {high}]" if high is not None else f">= {low}"
        raise ArtifactValidationError(f"{field}: {value} outside {bound}")
    return value


def _exact_float(
    value: Any,
    field: str,
    low: float,
    high: float,
    *,
    low_open: bool = False,
    high_open: bool = False,
) -> float:
    if type(value) is not int and type(value) is not float:
        raise ArtifactValidationError(
            f"{field}: expected a builtin real number, got {type(value).__name__}"
        )
    try:
        as_float = float(value)
    except (OverflowError, ValueError) as e:
        raise ArtifactValidationError(f"{field}: not representable as a finite float") from e
    if not math.isfinite(as_float):
        raise ArtifactValidationError(f"{field}: not finite")
    below = as_float < low or (low_open and as_float == low)
    above = as_float > high or (high_open and as_float == high)
    if below or above:
        raise ArtifactValidationError(f"{field}: {as_float} outside the documented range")
    return as_float


def _exact_dict(value: Any, field: str, keys: frozenset[str] | tuple[str, ...]) -> dict[str, Any]:
    if type(value) is not dict:
        raise ArtifactValidationError(
            f"{field}: expected builtin dict, got {type(value).__name__}"
        )
    expected = frozenset(keys)
    present = set(value)
    if present != expected:
        unknown = sorted(k if type(k) is str else f"<{type(k).__name__}>" for k in present - expected)
        missing = sorted(expected - present)
        raise ArtifactValidationError(
            f"{field}: key set mismatch (unknown={unknown}, missing={missing})"
        )
    return value


def _exact_list(value: Any, field: str, max_items: int) -> list[Any]:
    if type(value) is not list:
        raise ArtifactValidationError(
            f"{field}: expected builtin list, got {type(value).__name__}"
        )
    if len(value) > max_items:
        raise ArtifactValidationError(
            f"{field}: {len(value)} items exceed the {max_items} bound"
        )
    return value


def _enum(value: Any, field: str, allowed: tuple[str, ...]) -> str:
    text = _exact_str(value, field)
    if text not in allowed:
        raise ArtifactValidationError(f"{field}: unknown variant {text!r}")
    return text


def _bounded_text(value: Any, field: str) -> str:
    text = _exact_str(value, field)
    if not text or len(text) > _MAX_TEXT_CHARS:
        raise ArtifactValidationError(f"{field}: length must be in [1, {_MAX_TEXT_CHARS}]")
    return text


def _hex64(value: Any, field: str) -> str:
    text = _exact_str(value, field)
    if len(text) != 64 or not set(text) <= _HEX64:
        raise ArtifactValidationError(f"{field}: expected a 64-char lowercase hex sha256")
    return text


def _const(value: Any, field: str, expected: Any) -> Any:
    # Exact-type check first so constants can never be satisfied by
    # subclasses or numeric look-alikes.
    if type(value) is not type(expected) or value != expected:
        raise ArtifactValidationError(f"{field}: does not match the v1 constant")
    return value


def _const_str_list(value: Any, field: str, expected: tuple[str, ...]) -> list[str]:
    items = _exact_list(value, field, len(expected))
    if len(items) != len(expected):
        raise ArtifactValidationError(f"{field}: does not match the v1 constant list")
    for i, (item, want) in enumerate(zip(items, expected)):
        _const(item, f"{field}[{i}]", want)
    return list(expected)


# ---------------------------------------------------------------------------
# Result envelope (shared by every evaluation section)
# ---------------------------------------------------------------------------


def _envelope(value: Any, field: str) -> tuple[str, Any]:
    """Validate the two-variant result envelope; return (status, payload).

    ``computed``       -> exactly {status, value}
    ``not_computable`` -> exactly {status, reason, requires}
    """
    if type(value) is not dict:
        raise ArtifactValidationError(
            f"{field}: expected a result envelope dict, got {type(value).__name__}"
        )
    status = value.get("status")
    if type(status) is not str:
        # Exact type BEFORE any comparison: a hostile str subclass's
        # __eq__ must never execute.
        raise ArtifactValidationError(f"{field}.status: expected builtin str")
    if status == "computed":
        _exact_dict(value, field, ("status", "value"))
        return "computed", value["value"]
    if status == "not_computable":
        _exact_dict(value, field, ("status", "reason", "requires"))
        _enum(value["reason"], f"{field}.reason", NOT_COMPUTABLE_REASONS)
        _bounded_text(value["requires"], f"{field}.requires")
        return "not_computable", None
    raise ArtifactValidationError(f"{field}.status: unknown variant")


def _sanitize_envelope(value: Mapping[str, Any], payload: Any) -> dict[str, Any]:
    if value["status"] == "computed":
        return {"status": "computed", "value": payload}
    return {
        "status": "not_computable",
        "reason": value["reason"],
        "requires": value["requires"],
    }


def _require_not_computable(value: Any, field: str) -> dict[str, Any]:
    """Sections the v1 emitter can never compute must say so."""
    status, _ = _envelope(value, field)
    if status != "not_computable":
        raise ArtifactValidationError(
            f"{field}: the v1 emitter never computes this section"
        )
    return _sanitize_envelope(value, None)


# ---------------------------------------------------------------------------
# Bounded file loading (duplicate keys rejected before semantics)
# ---------------------------------------------------------------------------


def _load_bounded(path: pathlib.Path) -> Any:
    with path.open("rb") as f:
        raw = f.read(MAX_ARTIFACT_BYTES + 1)
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise ArtifactValidationError(
            f"artifact exceeds {MAX_ARTIFACT_BYTES} bytes; refusing to parse"
        )

    def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, item in pairs:
            if key in out:
                raise ArtifactValidationError(f"artifact: duplicate JSON key {key!r}")
            out[key] = item
        return out

    try:
        return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_no_duplicate_keys)
    except ArtifactValidationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as e:
        raise ArtifactValidationError(f"artifact is not valid UTF-8 JSON: {e}") from e
    except RecursionError as e:
        raise ArtifactValidationError("artifact nesting exceeds the parser's depth limit") from e


def load_evaluation_artifact(path: pathlib.Path) -> dict[str, Any]:
    """Bounded load + full structural validation of an evaluation file."""
    return validate_evaluation_artifact(_load_bounded(path))


def load_lab_artifact(path: pathlib.Path) -> dict[str, Any]:
    """Bounded load + full structural validation of a lab-report file."""
    return validate_lab_artifact(_load_bounded(path))


def load_evidence_packet(path: pathlib.Path) -> dict[str, Any]:
    """Bounded load + full structural validation of an evidence packet."""
    return validate_evidence_packet(_load_bounded(path))


# ---------------------------------------------------------------------------
# nextness-evaluation-v1
# ---------------------------------------------------------------------------

_EVALUATION_KEYS: Final[tuple[str, ...]] = (
    "schema", "config", "assumptions", "prediction", "calibration",
    "abstention", "recovery", "cross_check", "non_claims", "artifacts",
)
_EVAL_CONFIG: Final[dict[str, Any]] = {
    "max_input_bytes": MAX_INPUT_BYTES,
    "max_series_receipts": MAX_SERIES_RECEIPTS,
    "max_detail_items": EVAL_MAX_DETAIL_ITEMS,
    "contradiction_tolerance": CONTRADICTION_TOLERANCE,
    "cross_check_tolerance": CROSS_CHECK_TOLERANCE,
    "max_evaluation_bytes": MAX_EVALUATION_BYTES,
}
_MODEL_METRICS: Final[tuple[str, ...]] = (
    "nll_bits", "nll_gap_to_uniform_bits", "brier", "top1_accuracy",
)
_INGESTION_KEYS: Final[tuple[str, ...]] = (
    "rows_read", "rows_accepted", "rejection_rate", "train_rows",
    "holdout_rows", "first_order_unseen_source_rate",
)
_NLL_BITS_MAX: Final[float] = -math.log2(1e-300) + 1e-6  # NP5's validation bound


def _validate_eval_prediction(section: Any, report_provided: bool) -> dict[str, Any]:
    keys = ("uniform_nll_bits", "models", "rankings",
            "proper_score_rankings_agree", "ingestion",
            "metric_difference_significance")
    outer = _exact_dict(section, "prediction", keys)
    out: dict[str, Any] = {}
    out["metric_difference_significance"] = _require_not_computable(
        outer["metric_difference_significance"], "prediction.metric_difference_significance"
    )
    if not report_provided:
        for key in keys[:-1]:
            out[key] = _require_not_computable(outer[key], f"prediction.{key}")
        return out

    status, value = _envelope(outer["uniform_nll_bits"], "prediction.uniform_nll_bits")
    if status != "computed":
        raise ArtifactValidationError(
            "prediction.uniform_nll_bits: must be computed when the report was provided"
        )
    out["uniform_nll_bits"] = _sanitize_envelope(
        outer["uniform_nll_bits"], _const(value, "prediction.uniform_nll_bits.value", 4.0)
    )

    models = _exact_dict(outer["models"], "prediction.models", MODEL_ALLOWLIST)
    sane_models: dict[str, Any] = {}
    for name in MODEL_ALLOWLIST:
        metrics = _exact_dict(models[name], f"prediction.models.{name}", _MODEL_METRICS)
        sane: dict[str, Any] = {}
        for metric, low, high in (
            ("nll_bits", 0.0, _NLL_BITS_MAX),
            ("nll_gap_to_uniform_bits", 4.0 - _NLL_BITS_MAX, 4.0),
            ("brier", 0.0, 2.0),
            ("top1_accuracy", 0.0, 1.0),
        ):
            m_status, m_value = _envelope(metrics[metric], f"prediction.models.{name}.{metric}")
            if m_status != "computed":
                raise ArtifactValidationError(
                    f"prediction.models.{name}.{metric}: must be computed"
                )
            sane[metric] = _sanitize_envelope(
                metrics[metric],
                _exact_float(m_value, f"prediction.models.{name}.{metric}.value", low, high),
            )
        # Deterministic identity, EXACT equality: the producer computes
        # the gap as one IEEE double subtraction from the same recorded
        # values, and JSON's shortest-repr floats round-trip exactly —
        # so any deviation, even one representable step, is a recorded
        # contradiction, not rounding.
        if sane["nll_gap_to_uniform_bits"]["value"] != 4.0 - sane["nll_bits"]["value"]:
            raise ArtifactValidationError(
                f"prediction.models.{name}.nll_gap_to_uniform_bits: does not "
                f"equal uniform_nll_bits - nll_bits"
            )
        sane_models[name] = sane
    out["models"] = sane_models

    r_status, r_value = _envelope(outer["rankings"], "prediction.rankings")
    if r_status != "computed":
        raise ArtifactValidationError("prediction.rankings: must be computed")
    rankings = _exact_dict(
        r_value, "prediction.rankings.value",
        ("by_nll_bits", "by_brier", "by_top1_accuracy"),
    )
    sane_rankings: dict[str, list[str]] = {}
    for key in ("by_nll_bits", "by_brier", "by_top1_accuracy"):
        ranking = _exact_list(rankings[key], f"prediction.rankings.value.{key}", len(MODEL_ALLOWLIST))
        names = [_enum(item, f"prediction.rankings.value.{key}[{i}]", MODEL_ALLOWLIST)
                 for i, item in enumerate(ranking)]
        if sorted(names) != sorted(MODEL_ALLOWLIST):
            raise ArtifactValidationError(
                f"prediction.rankings.value.{key}: not a permutation of the model allowlist"
            )
        sane_rankings[key] = names
    out["rankings"] = _sanitize_envelope(outer["rankings"], sane_rankings)

    a_status, a_value = _envelope(
        outer["proper_score_rankings_agree"], "prediction.proper_score_rankings_agree"
    )
    if a_status != "computed":
        raise ArtifactValidationError("prediction.proper_score_rankings_agree: must be computed")
    agree = _exact_bool(a_value, "prediction.proper_score_rankings_agree.value")
    if agree != (sane_rankings["by_nll_bits"] == sane_rankings["by_brier"]):
        raise ArtifactValidationError(
            "prediction.proper_score_rankings_agree: contradicts the recorded rankings"
        )
    out["proper_score_rankings_agree"] = _sanitize_envelope(
        outer["proper_score_rankings_agree"], agree
    )

    i_status, i_value = _envelope(outer["ingestion"], "prediction.ingestion")
    if i_status != "computed":
        raise ArtifactValidationError("prediction.ingestion: must be computed")
    ingestion = _exact_dict(i_value, "prediction.ingestion.value", _INGESTION_KEYS)
    rows_read = _exact_int(ingestion["rows_read"], "prediction.ingestion.value.rows_read", 1, MAX_ROWS_CEILING)
    rows_accepted = _exact_int(ingestion["rows_accepted"], "prediction.ingestion.value.rows_accepted", 3, MAX_ROWS_CEILING)
    train_rows = _exact_int(ingestion["train_rows"], "prediction.ingestion.value.train_rows", 2, MAX_ROWS_CEILING)
    holdout_rows = _exact_int(ingestion["holdout_rows"], "prediction.ingestion.value.holdout_rows", 1, MAX_ROWS_CEILING)
    if train_rows + holdout_rows != rows_accepted:
        raise ArtifactValidationError(
            "prediction.ingestion.value: train_rows + holdout_rows != rows_accepted"
        )
    if rows_read < rows_accepted:
        raise ArtifactValidationError(
            "prediction.ingestion.value: rows_read < rows_accepted"
        )
    out["ingestion"] = _sanitize_envelope(outer["ingestion"], {
        "rows_read": rows_read,
        "rows_accepted": rows_accepted,
        "rejection_rate": _exact_float(ingestion["rejection_rate"], "prediction.ingestion.value.rejection_rate", 0.0, 1.0),
        "train_rows": train_rows,
        "holdout_rows": holdout_rows,
        "first_order_unseen_source_rate": _exact_float(
            ingestion["first_order_unseen_source_rate"],
            "prediction.ingestion.value.first_order_unseen_source_rate", 0.0, 1.0,
        ),
    })
    return out


def _validate_eval_calibration(section: Any, report_provided: bool, receipts_provided: bool) -> dict[str, Any]:
    keys = ("holdout_ece_by_model", "ece_bin_width",
            "max_rolling_calibration_error", "latest_rolling_calibration_error",
            "miscalibration_direction")
    outer = _exact_dict(section, "calibration", keys)
    out: dict[str, Any] = {}
    out["miscalibration_direction"] = _require_not_computable(
        outer["miscalibration_direction"], "calibration.miscalibration_direction"
    )
    for key, gate in (("holdout_ece_by_model", report_provided), ("ece_bin_width", report_provided)):
        status, value = _envelope(outer[key], f"calibration.{key}")
        if not gate:
            if status != "not_computable":
                raise ArtifactValidationError(
                    f"calibration.{key}: computed without the report artifact"
                )
            out[key] = _sanitize_envelope(outer[key], None)
        else:
            if status != "computed":
                raise ArtifactValidationError(f"calibration.{key}: must be computed")
            if key == "ece_bin_width":
                out[key] = _sanitize_envelope(outer[key], _const(value, "calibration.ece_bin_width.value", 0.1))
            else:
                eces = _exact_dict(value, "calibration.holdout_ece_by_model.value", MODEL_ALLOWLIST)
                out[key] = _sanitize_envelope(outer[key], {
                    name: _exact_float(eces[name], f"calibration.holdout_ece_by_model.value.{name}", 0.0, 1.0)
                    for name in MODEL_ALLOWLIST
                })
    for key in ("max_rolling_calibration_error", "latest_rolling_calibration_error"):
        status, value = _envelope(outer[key], f"calibration.{key}")
        if not receipts_provided and status == "computed":
            raise ArtifactValidationError(
                f"calibration.{key}: computed without the receipts artifact"
            )
        if status == "computed":
            out[key] = _sanitize_envelope(outer[key], _exact_float(value, f"calibration.{key}.value", 0.0, 1.0))
        else:
            out[key] = _sanitize_envelope(outer[key], None)
    return out


def _validate_eval_abstention(
    section: Any, receipts_provided: bool, receipt_count: int | None
) -> tuple[dict[str, Any], int | None]:
    """Returns ``(sanitized_section, abstained_count_or_None)``.

    ``abstained_count`` is receipt_count − reason_counts["none"], and is
    returned ONLY when the artifact's own abstain_flag_matches_reason
    witness records zero contradictions — the producer counts the RATE
    from abstain flags but the HISTOGRAM from reasons, and a series with
    contradictory flags (which the evaluator legitimately reports rather
    than rejects) can make the two disagree. Enforcing the identity
    unconditionally would falsely reject genuine artifacts.
    """
    keys = ("receipt_count", "abstention_rate", "reason_counts",
            "configurations_identical", "consistency", "abstention_quality")
    outer = _exact_dict(section, "abstention", keys)
    out: dict[str, Any] = {}
    out["abstention_quality"] = _require_not_computable(
        outer["abstention_quality"], "abstention.abstention_quality"
    )
    if not receipts_provided:
        for key in keys[:-1]:
            out[key] = _require_not_computable(outer[key], f"abstention.{key}")
        return out, None

    c_status, c_value = _envelope(outer["receipt_count"], "abstention.receipt_count")
    if c_status != "computed":
        raise ArtifactValidationError("abstention.receipt_count: must be computed")
    n = _exact_int(c_value, "abstention.receipt_count.value", 1, MAX_SERIES_RECEIPTS)
    if receipt_count is not None and n != receipt_count:
        raise ArtifactValidationError(
            "abstention.receipt_count: contradicts artifacts.receipts.receipt_count"
        )
    out["receipt_count"] = _sanitize_envelope(outer["receipt_count"], n)

    r_status, r_value = _envelope(outer["abstention_rate"], "abstention.abstention_rate")
    if r_status != "computed":
        raise ArtifactValidationError("abstention.abstention_rate: must be computed")
    out["abstention_rate"] = _sanitize_envelope(
        outer["abstention_rate"],
        _exact_float(r_value, "abstention.abstention_rate.value", 0.0, 1.0),
    )

    rc_status, rc_value = _envelope(outer["reason_counts"], "abstention.reason_counts")
    if rc_status != "computed":
        raise ArtifactValidationError("abstention.reason_counts: must be computed")
    counts_raw = _exact_dict(rc_value, "abstention.reason_counts.value", ABSTAIN_REASONS)
    counts = {
        reason: _exact_int(counts_raw[reason], f"abstention.reason_counts.value.{reason}", 0, n)
        for reason in ABSTAIN_REASONS
    }
    if sum(counts.values()) != n:
        raise ArtifactValidationError(
            "abstention.reason_counts: counts do not sum to receipt_count"
        )
    out["reason_counts"] = _sanitize_envelope(outer["reason_counts"], counts)

    ci_status, ci_value = _envelope(outer["configurations_identical"], "abstention.configurations_identical")
    if ci_status != "computed":
        raise ArtifactValidationError("abstention.configurations_identical: must be computed")
    out["configurations_identical"] = _sanitize_envelope(
        outer["configurations_identical"],
        _exact_bool(ci_value, "abstention.configurations_identical.value"),
    )

    k_status, k_value = _envelope(outer["consistency"], "abstention.consistency")
    if k_status != "computed":
        raise ArtifactValidationError("abstention.consistency: must be computed")
    checks_raw = _exact_dict(k_value, "abstention.consistency.value", CONSISTENCY_CHECKS)
    sane_checks: dict[str, Any] = {}
    for check in CONSISTENCY_CHECKS:
        entry = _exact_dict(
            checks_raw[check], f"abstention.consistency.value.{check}",
            ("verdicts", "contradicted_indices", "contradicted_indices_truncated"),
        )
        tallies_raw = _exact_dict(entry["verdicts"], f"abstention.consistency.value.{check}.verdicts", VERDICTS)
        tallies = {
            verdict: _exact_int(tallies_raw[verdict], f"abstention.consistency.value.{check}.verdicts.{verdict}", 0, n)
            for verdict in VERDICTS
        }
        if sum(tallies.values()) != n:
            raise ArtifactValidationError(
                f"abstention.consistency.value.{check}: verdict tallies do not sum to receipt_count"
            )
        indices = _exact_list(
            entry["contradicted_indices"],
            f"abstention.consistency.value.{check}.contradicted_indices",
            EVAL_MAX_DETAIL_ITEMS,
        )
        sane_indices = []
        previous = -1
        for i, item in enumerate(indices):
            idx = _exact_int(item, f"abstention.consistency.value.{check}.contradicted_indices[{i}]", 0, n - 1)
            if idx <= previous:
                raise ArtifactValidationError(
                    f"abstention.consistency.value.{check}.contradicted_indices: not strictly increasing"
                )
            previous = idx
            sane_indices.append(idx)
        truncated = _exact_bool(
            entry["contradicted_indices_truncated"],
            f"abstention.consistency.value.{check}.contradicted_indices_truncated",
        )
        if truncated != (tallies["contradicted"] > EVAL_MAX_DETAIL_ITEMS):
            raise ArtifactValidationError(
                f"abstention.consistency.value.{check}: truncation flag contradicts the contradicted tally"
            )
        if len(sane_indices) != min(tallies["contradicted"], EVAL_MAX_DETAIL_ITEMS):
            raise ArtifactValidationError(
                f"abstention.consistency.value.{check}: index list length contradicts the contradicted tally"
            )
        sane_checks[check] = {
            "verdicts": tallies,
            "contradicted_indices": sane_indices,
            "contradicted_indices_truncated": truncated,
        }
    out["consistency"] = _sanitize_envelope(outer["consistency"], sane_checks)

    abstained = n - counts["none"]
    flag_witness_clean = (
        sane_checks["abstain_flag_matches_reason"]["verdicts"]["contradicted"] == 0
    )
    if flag_witness_clean:
        # Exact identity — integer division of the same ints the
        # producer divides; no tolerance (floats round-trip exactly).
        if out["abstention_rate"]["value"] != abstained / n:
            raise ArtifactValidationError(
                "abstention.abstention_rate: contradicts the reason counts "
                "on a flag-coherent series"
            )
        return out, abstained
    return out, None


def _validate_eval_blocks(value: Any, field: str, low: float, high: float) -> dict[str, Any]:
    outer = _exact_dict(value, field, ("blocks", "blocks_truncated", "block_count", "all_within_bounds"))
    block_count = _exact_int(outer["block_count"], f"{field}.block_count", 1, MAX_SERIES_RECEIPTS - 1)
    truncated = _exact_bool(outer["blocks_truncated"], f"{field}.blocks_truncated")
    if truncated != (block_count > EVAL_MAX_DETAIL_ITEMS):
        raise ArtifactValidationError(f"{field}: truncation flag contradicts block_count")
    blocks = _exact_list(outer["blocks"], f"{field}.blocks", EVAL_MAX_DETAIL_ITEMS)
    if len(blocks) != min(block_count, EVAL_MAX_DETAIL_ITEMS):
        raise ArtifactValidationError(f"{field}: blocks length contradicts block_count")
    sane_blocks = []
    for i, item in enumerate(blocks):
        entry = _exact_dict(item, f"{field}.blocks[{i}]", ("block_mean", "error_bound", "within_bounds"))
        # Block means may legitimately fall outside [low, high] — that is
        # exactly what within_bounds records — so only finiteness is
        # required; the within_bounds STATEMENT must cohere with the
        # recorded numbers.
        mean = _exact_float(entry["block_mean"], f"{field}.blocks[{i}].block_mean", -1e12, 1e12)
        bound = _exact_float(entry["error_bound"], f"{field}.blocks[{i}].error_bound", 0.0, 1e12)
        within = _exact_bool(entry["within_bounds"], f"{field}.blocks[{i}].within_bounds")
        if within != ((low - bound) <= mean <= (high + bound)):
            raise ArtifactValidationError(
                f"{field}.blocks[{i}]: within_bounds contradicts the recorded mean and bound"
            )
        sane_blocks.append({"block_mean": mean, "error_bound": bound, "within_bounds": within})
    all_within = _exact_bool(outer["all_within_bounds"], f"{field}.all_within_bounds")
    if not truncated and all_within != all(b["within_bounds"] for b in sane_blocks):
        raise ArtifactValidationError(
            f"{field}: all_within_bounds contradicts the recorded blocks"
        )
    if truncated and not all_within:
        # Fine: a hidden block may have violated; the visible ones can't prove otherwise.
        pass
    if truncated and all_within and not all(b["within_bounds"] for b in sane_blocks):
        raise ArtifactValidationError(
            f"{field}: all_within_bounds contradicts a visible violating block"
        )
    return {
        "blocks": sane_blocks,
        "blocks_truncated": truncated,
        "block_count": block_count,
        "all_within_bounds": all_within,
    }


def _validate_eval_recovery(
    section: Any, receipts_provided: bool, abstained_count: int | None
) -> dict[str, Any]:
    keys = ("chronology", "series_comparability", "abstention_transitions",
            "surprise_blocks", "confidence_blocks", "per_observation_recovery")
    outer = _exact_dict(section, "recovery", keys)
    out: dict[str, Any] = {}
    out["per_observation_recovery"] = _require_not_computable(
        outer["per_observation_recovery"], "recovery.per_observation_recovery"
    )
    if not receipts_provided:
        for key in keys[:-1]:
            out[key] = _require_not_computable(outer[key], f"recovery.{key}")
        return out

    ch_status, ch_value = _envelope(outer["chronology"], "recovery.chronology")
    if ch_status != "computed":
        raise ArtifactValidationError("recovery.chronology: must be computed")
    chronology = _exact_dict(ch_value, "recovery.chronology.value", ("witnessed", "first_violation_index"))
    witnessed = _exact_bool(chronology["witnessed"], "recovery.chronology.value.witnessed")
    violation = chronology["first_violation_index"]
    if witnessed:
        if violation is not None:
            raise ArtifactValidationError(
                "recovery.chronology.value: witnessed with a violation index"
            )
    else:
        violation = _exact_int(violation, "recovery.chronology.value.first_violation_index", 1, MAX_SERIES_RECEIPTS - 1)
    out["chronology"] = _sanitize_envelope(
        outer["chronology"], {"witnessed": witnessed, "first_violation_index": violation}
    )

    sc_status, sc_value = _envelope(outer["series_comparability"], "recovery.series_comparability")
    if sc_status != "computed":
        raise ArtifactValidationError("recovery.series_comparability: must be computed")
    comparability = _exact_dict(sc_value, "recovery.series_comparability.value", ("model_stable", "config_stable"))
    model_stable = _exact_bool(comparability["model_stable"], "recovery.series_comparability.value.model_stable")
    config_stable = _exact_bool(comparability["config_stable"], "recovery.series_comparability.value.config_stable")
    out["series_comparability"] = _sanitize_envelope(
        outer["series_comparability"], {"model_stable": model_stable, "config_stable": config_stable}
    )

    # Gate coherence: a failed gate forbids computation downstream, and
    # the order gate runs FIRST in the emitter, so a failed witness pins
    # the not-computable reason to order_not_witnessed exactly.
    t_status, t_value = _envelope(outer["abstention_transitions"], "recovery.abstention_transitions")
    s_status, s_value = _envelope(outer["surprise_blocks"], "recovery.surprise_blocks")
    f_status, f_value = _envelope(outer["confidence_blocks"], "recovery.confidence_blocks")
    if not witnessed:
        for key, status in (
            ("abstention_transitions", t_status),
            ("surprise_blocks", s_status),
            ("confidence_blocks", f_status),
        ):
            if status == "computed":
                raise ArtifactValidationError(
                    "recovery: order-dependent sections computed without a chronology witness"
                )
            if outer[key]["reason"] != "order_not_witnessed":
                raise ArtifactValidationError(
                    f"recovery.{key}: a failed witness pins the reason to order_not_witnessed"
                )
    if not model_stable and ("computed" in (t_status, s_status, f_status)):
        raise ArtifactValidationError(
            "recovery: sections computed across an unstable model series"
        )
    if not config_stable and t_status == "computed":
        raise ArtifactValidationError(
            "recovery.abstention_transitions: computed across an unstable configuration series"
        )
    if s_status != f_status:
        raise ArtifactValidationError(
            "recovery: surprise and confidence blocks must share computability"
        )

    if t_status == "computed":
        transitions = _exact_dict(
            t_value, "recovery.abstention_transitions.value",
            ("abstention_onsets", "reorientations",
             "completed_abstention_run_lengths_receipts", "run_lengths_truncated",
             "unresolved_trailing_abstention_receipts"),
        )
        onsets = _exact_int(transitions["abstention_onsets"], "recovery.abstention_transitions.value.abstention_onsets", 0, MAX_SERIES_RECEIPTS)
        reorientations = _exact_int(transitions["reorientations"], "recovery.abstention_transitions.value.reorientations", 0, MAX_SERIES_RECEIPTS)
        if reorientations > onsets + 1:
            raise ArtifactValidationError(
                "recovery.abstention_transitions.value: reorientations exceed onsets + 1"
            )
        run_lengths = _exact_list(
            transitions["completed_abstention_run_lengths_receipts"],
            "recovery.abstention_transitions.value.completed_abstention_run_lengths_receipts",
            EVAL_MAX_DETAIL_ITEMS,
        )
        sane_runs = [
            _exact_int(item, f"recovery.abstention_transitions.value.completed_abstention_run_lengths_receipts[{i}]", 1, MAX_SERIES_RECEIPTS)
            for i, item in enumerate(run_lengths)
        ]
        truncated = _exact_bool(transitions["run_lengths_truncated"], "recovery.abstention_transitions.value.run_lengths_truncated")
        if truncated != (reorientations > EVAL_MAX_DETAIL_ITEMS):
            raise ArtifactValidationError(
                "recovery.abstention_transitions.value: truncation flag contradicts reorientations"
            )
        if len(sane_runs) != min(reorientations, EVAL_MAX_DETAIL_ITEMS):
            raise ArtifactValidationError(
                "recovery.abstention_transitions.value: run list length contradicts reorientations"
            )
        trailing = transitions["unresolved_trailing_abstention_receipts"]
        if trailing is not None:
            trailing = _exact_int(trailing, "recovery.abstention_transitions.value.unresolved_trailing_abstention_receipts", 1, MAX_SERIES_RECEIPTS)
        # Every abstained receipt lives in exactly one maximal run, so
        # on a flag-coherent series (abstained_count witnessed by the
        # abstention section) the completed runs plus any trailing run
        # must sum to it — checkable only when the run list was not
        # truncated (truncation hides the identity; honest limitation).
        if not truncated and abstained_count is not None:
            if sum(sane_runs) + (trailing or 0) != abstained_count:
                raise ArtifactValidationError(
                    "recovery.abstention_transitions.value: completed runs "
                    "plus trailing do not equal the abstained receipts"
                )
        out["abstention_transitions"] = _sanitize_envelope(outer["abstention_transitions"], {
            "abstention_onsets": onsets,
            "reorientations": reorientations,
            "completed_abstention_run_lengths_receipts": sane_runs,
            "run_lengths_truncated": truncated,
            "unresolved_trailing_abstention_receipts": trailing,
        })
    else:
        out["abstention_transitions"] = _sanitize_envelope(outer["abstention_transitions"], None)

    if s_status == "computed":
        out["surprise_blocks"] = _sanitize_envelope(
            outer["surprise_blocks"],
            _validate_eval_blocks(s_value, "recovery.surprise_blocks.value", 0.0, 1000.0),
        )
        out["confidence_blocks"] = _sanitize_envelope(
            outer["confidence_blocks"],
            _validate_eval_blocks(f_value, "recovery.confidence_blocks.value", 0.0, 1.0),
        )
    else:
        out["surprise_blocks"] = _sanitize_envelope(outer["surprise_blocks"], None)
        out["confidence_blocks"] = _sanitize_envelope(outer["confidence_blocks"], None)
    return out


def _validate_eval_cross_check(section: Any, report_provided: bool, receipts_provided: bool) -> dict[str, Any]:
    outer = _exact_dict(section, "cross_check", ("assumption", "ece_match", "surprise_nll_match"))
    out: dict[str, Any] = {"assumption": _const(outer["assumption"], "cross_check.assumption", ASSUMPTION_SAME_SOURCE)}
    both = report_provided and receipts_provided
    for key, entry_keys in (
        ("ece_match", ("model", "report_ece", "receipt_rolling_calibration_error", "verdict")),
        ("surprise_nll_match", ("model", "report_nll_bits", "receipt_mean_surprise_bits", "verdict")),
    ):
        status, value = _envelope(outer[key], f"cross_check.{key}")
        if status == "computed":
            if not both:
                raise ArtifactValidationError(
                    f"cross_check.{key}: computed without both artifacts"
                )
            wrapper = _exact_dict(
                value, f"cross_check.{key}.value",
                ("results", "results_truncated", "covering_receipt_count"),
            )
            count = _exact_int(wrapper["covering_receipt_count"], f"cross_check.{key}.value.covering_receipt_count", 1, MAX_SERIES_RECEIPTS)
            truncated = _exact_bool(wrapper["results_truncated"], f"cross_check.{key}.value.results_truncated")
            if truncated != (count > EVAL_MAX_DETAIL_ITEMS):
                raise ArtifactValidationError(
                    f"cross_check.{key}.value: truncation flag contradicts covering_receipt_count"
                )
            results = _exact_list(wrapper["results"], f"cross_check.{key}.value.results", EVAL_MAX_DETAIL_ITEMS)
            if len(results) != min(count, EVAL_MAX_DETAIL_ITEMS):
                raise ArtifactValidationError(
                    f"cross_check.{key}.value: results length contradicts covering_receipt_count"
                )
            sane_results = []
            for i, item in enumerate(results):
                entry = _exact_dict(item, f"cross_check.{key}.value.results[{i}]", entry_keys)
                sane = {"model": _enum(entry["model"], f"cross_check.{key}.value.results[{i}].model", MODEL_ALLOWLIST)}
                for numeric in entry_keys[1:3]:
                    high = 1.0 if key == "ece_match" else 1000.0
                    sane[numeric] = _exact_float(entry[numeric], f"cross_check.{key}.value.results[{i}].{numeric}", 0.0, high)
                sane["verdict"] = _enum(entry["verdict"], f"cross_check.{key}.value.results[{i}].verdict", VERDICTS)
                sane_results.append(sane)
            out[key] = _sanitize_envelope(outer[key], {
                "results": sane_results,
                "results_truncated": truncated,
                "covering_receipt_count": count,
            })
        else:
            out[key] = _sanitize_envelope(outer[key], None)
    return out


def _validate_eval_artifact_slot(value: Any, field: str, schema: str, with_count: bool) -> dict[str, Any]:
    if type(value) is not dict:
        raise ArtifactValidationError(f"{field}: expected builtin dict, got {type(value).__name__}")
    provided = value.get("provided")
    if type(provided) is not bool:
        raise ArtifactValidationError(f"{field}.provided: expected builtin bool")
    if provided is False:
        _exact_dict(value, field, ("provided",))
        return {"provided": False}
    keys = ("provided", "sha256", "bytes", "schema") + (("receipt_count",) if with_count else ())
    _exact_dict(value, field, keys)
    out: dict[str, Any] = {
        "provided": True,
        "sha256": _hex64(value["sha256"], f"{field}.sha256"),
        "bytes": _exact_int(value["bytes"], f"{field}.bytes", 1, MAX_ARTIFACT_BYTES),
        "schema": _const(value["schema"], f"{field}.schema", schema),
    }
    if with_count:
        out["receipt_count"] = _exact_int(value["receipt_count"], f"{field}.receipt_count", 1, MAX_SERIES_RECEIPTS)
    return out


def validate_evaluation_artifact(artifact: Any) -> dict[str, Any]:
    """Full structural validation of one recorded nextness-evaluation-v1
    artifact. Returns a sanitized builtin copy; never mutates the input."""
    outer = _exact_dict(artifact, "evaluation", _EVALUATION_KEYS)
    _const(outer["schema"], "evaluation.schema", EVALUATION_SCHEMA)

    config = _exact_dict(outer["config"], "evaluation.config", tuple(_EVAL_CONFIG))
    for key, expected in _EVAL_CONFIG.items():
        _const(config[key], f"evaluation.config.{key}", expected)

    artifacts = _exact_dict(outer["artifacts"], "evaluation.artifacts", ("report", "receipts"))
    report_slot = _validate_eval_artifact_slot(
        artifacts["report"], "evaluation.artifacts.report", REPORT_SCHEMA, with_count=False
    )
    receipts_slot = _validate_eval_artifact_slot(
        artifacts["receipts"], "evaluation.artifacts.receipts", RECEIPT_SCHEMA, with_count=True
    )
    report_provided = report_slot["provided"]
    receipts_provided = receipts_slot["provided"]
    if not report_provided and not receipts_provided:
        raise ArtifactValidationError(
            "evaluation.artifacts: at least one artifact must have been provided"
        )

    prediction = _validate_eval_prediction(outer["prediction"], report_provided)
    calibration = _validate_eval_calibration(outer["calibration"], report_provided, receipts_provided)
    abstention, abstained_count = _validate_eval_abstention(
        outer["abstention"], receipts_provided,
        receipts_slot.get("receipt_count") if receipts_provided else None,
    )
    recovery = _validate_eval_recovery(outer["recovery"], receipts_provided, abstained_count)
    cross_check = _validate_eval_cross_check(outer["cross_check"], report_provided, receipts_provided)

    assumptions_raw = _exact_list(outer["assumptions"], "evaluation.assumptions", 2)
    assumptions = [
        _enum(item, f"evaluation.assumptions[{i}]",
              (ASSUMPTION_PREFIX_EXTENSION, ASSUMPTION_SAME_SOURCE))
        for i, item in enumerate(assumptions_raw)
    ]
    if len(set(assumptions)) != len(assumptions):
        raise ArtifactValidationError("evaluation.assumptions: duplicate assumption")
    prefix_used = recovery["surprise_blocks"]["status"] == "computed"
    cross_used = cross_check["ece_match"]["status"] == "computed"
    expected_assumptions = (
        [ASSUMPTION_PREFIX_EXTENSION] if prefix_used else []
    ) + ([ASSUMPTION_SAME_SOURCE] if cross_used else [])
    if assumptions != expected_assumptions:
        raise ArtifactValidationError(
            "evaluation.assumptions: does not match the computed sections"
        )

    non_claims = _const_str_list(outer["non_claims"], "evaluation.non_claims", EVALUATION_NON_CLAIMS)

    return {
        "schema": EVALUATION_SCHEMA,
        "config": dict(_EVAL_CONFIG),
        "assumptions": assumptions,
        "prediction": prediction,
        "calibration": calibration,
        "abstention": abstention,
        "recovery": recovery,
        "cross_check": cross_check,
        "non_claims": non_claims,
        "artifacts": {"report": report_slot, "receipts": receipts_slot},
    }


# ---------------------------------------------------------------------------
# nextness-replay-lab-v1
# ---------------------------------------------------------------------------

_LAB_KEYS: Final[tuple[str, ...]] = (
    "schema", "laboratory_observation", "config", "input", "configurations", "non_claims",
)
_LAB_CONFIG_KEYS: Final[tuple[str, ...]] = (
    "max_lab_configs", "max_replay_steps", "max_rows", "max_line_bytes",
    "model", "smoothing", "holdout_fraction",
)
_LAB_INPUT_KEYS: Final[tuple[str, ...]] = (
    "rows_read", "rows_accepted", "rows_rejected", "rejections",
    "train_rows", "holdout_steps", "sequence_sha256", "protocol_sha256",
)
_MONITOR_CONFIG_KEYS: Final[tuple[str, ...]] = (
    "min_history", "window", "low_confidence_threshold",
    "calibration_error_threshold", "drift_threshold_bits",
)
_TRAJECTORY_KEYS: Final[tuple[str, ...]] = (
    "step_count", "abstention_step_rate", "reason_step_counts",
    "first_non_abstain_step", "abstention_onsets", "reorientations",
    "completed_abstention_run_lengths_steps", "run_lengths_truncated",
    "unresolved_trailing_abstention_steps", "final_abstain", "final_reason",
)


def _validate_lab_trajectory(value: Any, field: str, holdout_steps: int) -> dict[str, Any]:
    trajectory = _exact_dict(value, field, _TRAJECTORY_KEYS)
    steps = _exact_int(trajectory["step_count"], f"{field}.step_count", 1, MAX_REPLAY_STEPS)
    if steps != holdout_steps:
        raise ArtifactValidationError(f"{field}.step_count: contradicts input.holdout_steps")
    counts_raw = _exact_dict(trajectory["reason_step_counts"], f"{field}.reason_step_counts", ABSTAIN_REASONS)
    counts = {
        reason: _exact_int(counts_raw[reason], f"{field}.reason_step_counts.{reason}", 0, steps)
        for reason in ABSTAIN_REASONS
    }
    if sum(counts.values()) != steps:
        raise ArtifactValidationError(
            f"{field}.reason_step_counts: counts do not sum to step_count"
        )
    abstained = steps - counts["none"]
    rate = _exact_float(trajectory["abstention_step_rate"], f"{field}.abstention_step_rate", 0.0, 1.0)
    if rate != abstained / steps:
        raise ArtifactValidationError(
            f"{field}.abstention_step_rate: contradicts the reason counts"
        )
    first = trajectory["first_non_abstain_step"]
    if first is not None:
        first = _exact_int(first, f"{field}.first_non_abstain_step", 1, steps)
        if counts["none"] == 0:
            raise ArtifactValidationError(
                f"{field}.first_non_abstain_step: recorded although every step abstained"
            )
    elif abstained != steps:
        raise ArtifactValidationError(
            f"{field}.first_non_abstain_step: null although a step did not abstain"
        )
    onsets = _exact_int(trajectory["abstention_onsets"], f"{field}.abstention_onsets", 0, steps)
    reorientations = _exact_int(trajectory["reorientations"], f"{field}.reorientations", 0, steps)
    if reorientations > onsets + 1:
        raise ArtifactValidationError(f"{field}.reorientations: exceed onsets + 1")
    runs_raw = _exact_list(
        trajectory["completed_abstention_run_lengths_steps"],
        f"{field}.completed_abstention_run_lengths_steps", LAB_MAX_DETAIL_ITEMS,
    )
    runs = [
        _exact_int(item, f"{field}.completed_abstention_run_lengths_steps[{i}]", 1, steps)
        for i, item in enumerate(runs_raw)
    ]
    truncated = _exact_bool(trajectory["run_lengths_truncated"], f"{field}.run_lengths_truncated")
    if truncated != (reorientations > LAB_MAX_DETAIL_ITEMS):
        raise ArtifactValidationError(
            f"{field}.run_lengths_truncated: contradicts reorientations"
        )
    if len(runs) != min(reorientations, LAB_MAX_DETAIL_ITEMS):
        raise ArtifactValidationError(
            f"{field}.completed_abstention_run_lengths_steps: length contradicts reorientations"
        )
    final_abstain = _exact_bool(trajectory["final_abstain"], f"{field}.final_abstain")
    final_reason = _enum(trajectory["final_reason"], f"{field}.final_reason", ABSTAIN_REASONS)
    if final_abstain != (final_reason != "none"):
        raise ArtifactValidationError(
            f"{field}: final_abstain contradicts final_reason"
        )
    trailing = trajectory["unresolved_trailing_abstention_steps"]
    if final_abstain:
        trailing = _exact_int(trailing, f"{field}.unresolved_trailing_abstention_steps", 1, steps)
    elif trailing is not None:
        raise ArtifactValidationError(
            f"{field}.unresolved_trailing_abstention_steps: recorded although the final step did not abstain"
        )
    if not truncated:
        total = sum(runs) + (trailing or 0)
        if total != abstained:
            raise ArtifactValidationError(
                f"{field}: completed runs plus trailing do not sum to the abstained steps"
            )
    return {
        "step_count": steps,
        "abstention_step_rate": rate,
        "reason_step_counts": counts,
        "first_non_abstain_step": first,
        "abstention_onsets": onsets,
        "reorientations": reorientations,
        "completed_abstention_run_lengths_steps": runs,
        "run_lengths_truncated": truncated,
        "unresolved_trailing_abstention_steps": trailing,
        "final_abstain": final_abstain,
        "final_reason": final_reason,
    }


def validate_lab_artifact(artifact: Any) -> dict[str, Any]:
    """Full structural validation of one recorded nextness-replay-lab-v1
    artifact. Returns a sanitized builtin copy; never mutates the input."""
    outer = _exact_dict(artifact, "lab", _LAB_KEYS)
    _const(outer["schema"], "lab.schema", LAB_SCHEMA)
    _const(outer["laboratory_observation"], "lab.laboratory_observation", True)

    config = _exact_dict(outer["config"], "lab.config", _LAB_CONFIG_KEYS)
    sane_config = {
        "max_lab_configs": _const(config["max_lab_configs"], "lab.config.max_lab_configs", MAX_LAB_CONFIGS),
        "max_replay_steps": _const(config["max_replay_steps"], "lab.config.max_replay_steps", MAX_REPLAY_STEPS),
        "max_rows": _exact_int(config["max_rows"], "lab.config.max_rows", 1, MAX_ROWS_CEILING),
        "max_line_bytes": _exact_int(config["max_line_bytes"], "lab.config.max_line_bytes", 1),
        "model": _enum(config["model"], "lab.config.model", MODEL_ALLOWLIST),
        "smoothing": _exact_float(config["smoothing"], "lab.config.smoothing", 0.0, SMOOTHING_MAX, low_open=True),
        "holdout_fraction": _exact_float(config["holdout_fraction"], "lab.config.holdout_fraction", HOLDOUT_FRACTION_MIN, HOLDOUT_FRACTION_MAX),
    }

    inp = _exact_dict(outer["input"], "lab.input", _LAB_INPUT_KEYS)
    rows_read = _exact_int(inp["rows_read"], "lab.input.rows_read", 1, MAX_ROWS_CEILING)
    rows_accepted = _exact_int(inp["rows_accepted"], "lab.input.rows_accepted", 3, MAX_ROWS_CEILING)
    rows_rejected = _exact_int(inp["rows_rejected"], "lab.input.rows_rejected", 0, MAX_ROWS_CEILING)
    rejections_raw = _exact_dict(inp["rejections"], "lab.input.rejections", REJECT_REASONS)
    rejections = {
        reason: _exact_int(rejections_raw[reason], f"lab.input.rejections.{reason}", 0, MAX_ROWS_CEILING)
        for reason in REJECT_REASONS
    }
    if sum(rejections.values()) != rows_rejected:
        raise ArtifactValidationError("lab.input: rejections do not sum to rows_rejected")
    if rows_read < rows_accepted + rows_rejected:
        raise ArtifactValidationError("lab.input: rows_read < rows_accepted + rows_rejected")
    train_rows = _exact_int(inp["train_rows"], "lab.input.train_rows", 2, MAX_ROWS_CEILING)
    holdout_steps = _exact_int(inp["holdout_steps"], "lab.input.holdout_steps", 1, MAX_REPLAY_STEPS)
    if train_rows + holdout_steps != rows_accepted:
        raise ArtifactValidationError("lab.input: train_rows + holdout_steps != rows_accepted")

    configurations = _exact_list(outer["configurations"], "lab.configurations", MAX_LAB_CONFIGS)
    if not configurations:
        raise ArtifactValidationError("lab.configurations: empty")
    labels: set[str] = set()
    sane_configurations = []
    for i, item in enumerate(configurations):
        entry = _exact_dict(item, f"lab.configurations[{i}]", ("label", "config", "trajectory"))
        label = _exact_str(entry["label"], f"lab.configurations[{i}].label")
        if not label or len(label) > MAX_LABEL_CHARS:
            raise ArtifactValidationError(
                f"lab.configurations[{i}].label: length must be in [1, {MAX_LABEL_CHARS}]"
            )
        if label in labels:
            raise ArtifactValidationError(f"lab.configurations[{i}].label: duplicate")
        labels.add(label)
        monitor_cfg = _exact_dict(entry["config"], f"lab.configurations[{i}].config", _MONITOR_CONFIG_KEYS)
        sane_monitor = {
            "min_history": _exact_int(monitor_cfg["min_history"], f"lab.configurations[{i}].config.min_history", 5, 10_000),
            "window": _exact_int(monitor_cfg["window"], f"lab.configurations[{i}].config.window", 5, 10_000),
            "low_confidence_threshold": _exact_float(monitor_cfg["low_confidence_threshold"], f"lab.configurations[{i}].config.low_confidence_threshold", 0.0, 1.0, low_open=True, high_open=True),
            "calibration_error_threshold": _exact_float(monitor_cfg["calibration_error_threshold"], f"lab.configurations[{i}].config.calibration_error_threshold", 0.0, 1.0, low_open=True, high_open=True),
            "drift_threshold_bits": _exact_float(monitor_cfg["drift_threshold_bits"], f"lab.configurations[{i}].config.drift_threshold_bits", 0.0, 1.0, low_open=True, high_open=True),
        }
        sane_configurations.append({
            "label": label,
            "config": sane_monitor,
            "trajectory": _validate_lab_trajectory(
                entry["trajectory"], f"lab.configurations[{i}].trajectory", holdout_steps
            ),
        })

    non_claims = _const_str_list(outer["non_claims"], "lab.non_claims", LAB_NON_CLAIMS)

    return {
        "schema": LAB_SCHEMA,
        "laboratory_observation": True,
        "config": sane_config,
        "input": {
            "rows_read": rows_read,
            "rows_accepted": rows_accepted,
            "rows_rejected": rows_rejected,
            "rejections": rejections,
            "train_rows": train_rows,
            "holdout_steps": holdout_steps,
            "sequence_sha256": _hex64(inp["sequence_sha256"], "lab.input.sequence_sha256"),
            "protocol_sha256": _hex64(inp["protocol_sha256"], "lab.input.protocol_sha256"),
        },
        "configurations": sane_configurations,
        "non_claims": non_claims,
    }


# ---------------------------------------------------------------------------
# nextness-evidence-packet-v1
# ---------------------------------------------------------------------------

_PACKET_KEYS: Final[tuple[str, ...]] = ("schema", "config", "artifacts", "links", "non_claims")

#: The two manifest roles each provenance link compares.
_LINK_ENDPOINTS: Final[dict[str, tuple[str, str]]] = {
    "evaluation_report_sha256": ("evaluation", "report"),
    "evaluation_receipts_sha256": ("evaluation", "receipts"),
    "lab_protocol_sha256": ("lab", "protocol"),
    "lab_sequence_sha256": ("lab", "log"),
}
_PACKET_CONFIG: Final[dict[str, int]] = {
    "max_packet_artifacts": MAX_PACKET_ARTIFACTS,
    "max_input_bytes": MAX_INPUT_BYTES,
    "max_packet_bytes": MAX_PACKET_BYTES,
}


def _validate_packet_entry(value: Any, field: str, role: str) -> dict[str, Any]:
    base = ("role", "schema", "bytes", "sha256", "validation")
    if role == "log":
        keys = base + ("sequence_sha256", "sequence_bounds", "rows_accepted")
    elif role == "receipts":
        keys = base + ("receipt_count",)
    else:
        keys = base
    entry = _exact_dict(value, field, keys)
    _const(entry["role"], f"{field}.role", role)
    _const(entry["schema"], f"{field}.schema", _PACKET_SCHEMA_BY_ROLE[role])
    max_bytes = MAX_LOG_BYTES if role == "log" else MAX_ARTIFACT_BYTES
    out: dict[str, Any] = {
        "role": role,
        "schema": _PACKET_SCHEMA_BY_ROLE[role],
        "bytes": _exact_int(entry["bytes"], f"{field}.bytes", 0, max_bytes),
        "sha256": _hex64(entry["sha256"], f"{field}.sha256"),
    }
    expected_depth = {
        "report": "full", "receipts": "full", "protocol": "full",
        "evaluation": "schema_identifier_only", "lab": "schema_identifier_only",
        "log": "sequence_reader",
    }[role]
    depth = _enum(entry["validation"], f"{field}.validation", PACKET_VALIDATION_DEPTHS)
    if role == "log" and depth != "sequence_reader":
        raise ArtifactValidationError(f"{field}.validation: log entries are sequence_reader")
    if role in ("report", "receipts", "protocol") and depth != "full":
        raise ArtifactValidationError(f"{field}.validation: {role} entries are full")
    if role in ("evaluation", "lab") and depth not in ("schema_identifier_only", "full"):
        raise ArtifactValidationError(f"{field}.validation: unknown depth for {role}")
    del expected_depth  # documented above; evaluation/lab may deepen honestly
    out["validation"] = depth
    if role == "receipts":
        out["receipt_count"] = _exact_int(entry["receipt_count"], f"{field}.receipt_count", 1, MAX_SERIES_RECEIPTS)
    if role == "log":
        out["sequence_sha256"] = _hex64(entry["sequence_sha256"], f"{field}.sequence_sha256")
        bounds = _exact_dict(entry["sequence_bounds"], f"{field}.sequence_bounds", ("max_rows", "max_line_bytes"))
        out["sequence_bounds"] = {
            "max_rows": _const(bounds["max_rows"], f"{field}.sequence_bounds.max_rows", MAX_ROWS_DEFAULT),
            "max_line_bytes": _const(bounds["max_line_bytes"], f"{field}.sequence_bounds.max_line_bytes", MAX_LINE_BYTES_DEFAULT),
        }
        out["rows_accepted"] = _exact_int(entry["rows_accepted"], f"{field}.rows_accepted", 0, MAX_ROWS_CEILING)
    return out


def _validate_packet_link(value: Any, field: str, with_reader_bounds: bool) -> dict[str, Any]:
    if type(value) is not dict:
        raise ArtifactValidationError(f"{field}: expected builtin dict, got {type(value).__name__}")
    status = value.get("status")
    if type(status) is not str:
        raise ArtifactValidationError(f"{field}.status: expected builtin str")
    if status == "not_computable":
        _exact_dict(value, field, ("status", "reason", "requires"))
        return {
            "status": "not_computable",
            "reason": _enum(value["reason"], f"{field}.reason", LINK_NOT_COMPUTABLE_REASONS),
            "requires": _bounded_text(value["requires"], f"{field}.requires"),
        }
    if status in ("verified", "broken"):
        keys = ("status", "recorded_sha256", "actual_sha256") + (
            ("reader_bounds",) if with_reader_bounds else ()
        )
        _exact_dict(value, field, keys)
        recorded = _hex64(value["recorded_sha256"], f"{field}.recorded_sha256")
        actual = _hex64(value["actual_sha256"], f"{field}.actual_sha256")
        # Form coherence only: a verified statement must record equal
        # hashes and a broken one unequal. This validates the STATEMENT,
        # not the external hash relationship (NP8's job) — a structurally
        # valid broken link stays broken.
        if (status == "verified") != (recorded == actual):
            raise ArtifactValidationError(
                f"{field}: status contradicts the recorded hashes"
            )
        out: dict[str, Any] = {"status": status, "recorded_sha256": recorded, "actual_sha256": actual}
        if with_reader_bounds:
            bounds = _exact_dict(value["reader_bounds"], f"{field}.reader_bounds", ("max_rows", "max_line_bytes"))
            out["reader_bounds"] = {
                "max_rows": _exact_int(bounds["max_rows"], f"{field}.reader_bounds.max_rows", 1, MAX_ROWS_CEILING),
                "max_line_bytes": _exact_int(bounds["max_line_bytes"], f"{field}.reader_bounds.max_line_bytes", 1),
            }
        return out
    raise ArtifactValidationError(f"{field}.status: unknown variant")


def validate_evidence_packet(artifact: Any) -> dict[str, Any]:
    """Full structural validation of one recorded
    nextness-evidence-packet-v1 artifact. Returns a sanitized builtin
    copy; never mutates the input. Validates the packet's statements'
    FORM only — it does not recompute any hash and never converts a
    broken link into success."""
    outer = _exact_dict(artifact, "packet", _PACKET_KEYS)
    _const(outer["schema"], "packet.schema", PACKET_SCHEMA)

    config = _exact_dict(outer["config"], "packet.config", tuple(_PACKET_CONFIG))
    for key, expected in _PACKET_CONFIG.items():
        _const(config[key], f"packet.config.{key}", expected)

    entries = _exact_list(outer["artifacts"], "packet.artifacts", MAX_PACKET_ARTIFACTS)
    if not entries:
        raise ArtifactValidationError("packet.artifacts: empty")
    seen_roles: list[str] = []
    sane_entries = []
    for i, item in enumerate(entries):
        if type(item) is not dict:
            raise ArtifactValidationError(
                f"packet.artifacts[{i}]: expected builtin dict, got {type(item).__name__}"
            )
        role = _enum(item.get("role"), f"packet.artifacts[{i}].role", ROLES)
        if role in seen_roles:
            raise ArtifactValidationError(f"packet.artifacts[{i}].role: duplicate role")
        seen_roles.append(role)
        sane_entries.append(_validate_packet_entry(item, f"packet.artifacts[{i}]", role))
    order = [role for role in ROLES if role in seen_roles]
    if seen_roles != order:
        raise ArtifactValidationError("packet.artifacts: roles not in canonical order")

    links_raw = _exact_dict(outer["links"], "packet.links", LINK_KINDS)
    links = {
        kind: _validate_packet_link(
            links_raw[kind], f"packet.links.{kind}",
            with_reader_bounds=(kind == "lab_sequence_sha256"),
        )
        for kind in LINK_KINDS
    }

    # Link/endpoint coherence: a hash comparison needs both artifacts.
    # verified/broken without both endpoints in the manifest is a
    # statement about evidence the packet does not carry; conversely,
    # counterpart_absent with both endpoints present contradicts the
    # manifest. (An evaluation link may still be link_not_recorded with
    # both present — the evaluation itself recorded provided:false — and
    # with an endpoint absent either not-computable reason is a genuine
    # producer form for evaluation links; lab links only ever record
    # counterpart_absent.)
    for kind, (left, right) in _LINK_ENDPOINTS.items():
        link = links[kind]
        both = left in seen_roles and right in seen_roles
        if link["status"] in ("verified", "broken"):
            if not both:
                raise ArtifactValidationError(
                    f"packet.links.{kind}: {link['status']} requires both "
                    f"endpoint artifacts ({left}, {right}) in the manifest"
                )
        else:  # not_computable — reason already vocabulary-checked
            if both and (
                kind.startswith("lab_") or link["reason"] == "counterpart_absent"
            ):
                raise ArtifactValidationError(
                    f"packet.links.{kind}: not_computable/{link['reason']} "
                    f"although both endpoints are present in the manifest"
                )

    non_claims = _const_str_list(outer["non_claims"], "packet.non_claims", PACKET_NON_CLAIMS)

    return {
        "schema": PACKET_SCHEMA,
        "config": dict(_PACKET_CONFIG),
        "artifacts": sane_entries,
        "links": links,
        "non_claims": non_claims,
    }
