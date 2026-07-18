"""NP5: deterministic artifact evaluator — contract + adversarial tests.

Every exact-value fixture below is calculated independently in this file
from the documented formulas — the module is never asked to verify
itself.
"""

from __future__ import annotations

import json
import os
import pathlib
import random

import pytest

from scripts.nextness_evaluator import (
    ASSUMPTION_PREFIX_EXTENSION,
    ASSUMPTION_SAME_SOURCE,
    CONSISTENCY_CHECKS,
    EVALUATION_SCHEMA,
    MAX_DETAIL_ITEMS,
    MAX_EVALUATION_BYTES,
    MAX_INPUT_BYTES,
    MAX_SERIES_RECEIPTS,
    NOT_COMPUTABLE_REASONS,
    EvaluatorInputError,
    build_evaluation,
    check_receipt_consistency,
    chronology_witness,
    evaluate,
    load_json_artifact,
    main,
    serialize_evaluation,
    validate_output_path,
    validate_receipt,
    validate_receipt_series,
    validate_report,
)
from scripts.nextness_observer import WriteOutsideLogDirError
from scripts.nextness_monitor import (
    MonitorConfig,
    build_receipt,
    observations_from_log,
    serialize_receipt,
)
from scripts.nextness_predictor import (
    REJECT_REASONS,
    build_report,
    serialize_report,
)

A = "void_static"
B = "compute_static"


# ---------------------------------------------------------------------------
# Fixture builders (hand-constructed, internally consistent artifacts)
# ---------------------------------------------------------------------------


def _make_report() -> dict:
    rejections = {r: 0 for r in REJECT_REASONS}
    rejections["malformed_json"] = 2
    return {
        "schema": "nextness-predictor-v1",
        "config": {
            "smoothing": 1.0,
            "holdout_fraction": 0.25,
            "max_rows": 100_000,
            "max_line_bytes": 65_536,
            "ece_bins": 10,
            "vocabulary_size": 16,
        },
        "input": {
            "rows_read": 12,
            "rows_accepted": 8,
            "rows_rejected": 2,
            "rejections": rejections,
        },
        "evaluation": {
            "train_rows": 6,
            "holdout_rows": 2,
            "split_index": 6,
            "first_order_unseen_source_count": 1,
            "models": {
                "empirical_prior": {"nll_bits": 3.5, "brier": 0.9, "top1_accuracy": 0.25, "ece": 0.10},
                "persistence": {"nll_bits": 3.9, "brier": 1.1, "top1_accuracy": 0.20, "ece": 0.30},
                "first_order": {"nll_bits": 2.0, "brier": 0.5, "top1_accuracy": 0.60, "ece": 0.05},
            },
        },
        "non_claims": ["baselines only"],
    }


def _make_receipt(
    *,
    observation_count: int = 40,
    mean_confidence: float = 0.5,
    mean_surprise_bits: float = 2.0,
    ece: float = 0.1,
    drift: float = 0.05,
    reason: str = "none",
    abstain: bool | None = None,
    sufficiency: str | None = None,
    model: str = "first_order",
    min_history: int = 30,
    window: int = 50,
    cal_threshold: float = 0.2,
    drift_threshold: float = 0.15,
) -> dict:
    return {
        "schema": "nextness-monitor-v1",
        "model": model,
        "observation_count": observation_count,
        "mean_confidence": mean_confidence,
        "mean_surprise_bits": mean_surprise_bits,
        "rolling_calibration_error": ece,
        "distribution_drift_bits": drift,
        "sufficiency": sufficiency
        if sufficiency is not None
        else ("sufficient" if observation_count >= min_history else "insufficient"),
        "abstain": abstain if abstain is not None else (reason != "none"),
        "abstain_reason": reason,
        "input_reduced": False,
        "discarded_field_count": 0,
        "config": {
            "min_history": min_history,
            "window": window,
            "low_confidence_threshold": 0.3,
            "calibration_error_threshold": cal_threshold,
            "drift_threshold_bits": drift_threshold,
        },
        "non_claim": "functional-metacognition-only",
    }


def _series(receipts: list[dict]) -> list[dict]:
    return validate_receipt_series(receipts)


def _write_log(tmp_path: pathlib.Path, tokens: list[str]) -> pathlib.Path:
    log = tmp_path / "nextness_runs.jsonl"
    log.write_text(
        "\n".join(
            json.dumps({"generation": i, "token_counts": {t: 3}}) for i, t in enumerate(tokens)
        )
        + "\n",
        encoding="utf-8",
    )
    return log


# ---------------------------------------------------------------------------
# Prediction section: independent hand calculations
# ---------------------------------------------------------------------------


def test_prediction_section_hand_calculated_values() -> None:
    ev = evaluate(report=validate_report(_make_report()))
    pred = ev["prediction"]
    # log2(16) = 4 exactly.
    assert pred["uniform_nll_bits"] == {"status": "computed", "value": 4.0}
    # Gaps: uniform minus recorded nll_bits, by hand.
    assert pred["models"]["empirical_prior"]["nll_gap_to_uniform_bits"]["value"] == 4.0 - 3.5
    assert pred["models"]["persistence"]["nll_gap_to_uniform_bits"]["value"] == pytest.approx(0.1)
    assert pred["models"]["first_order"]["nll_gap_to_uniform_bits"]["value"] == 2.0
    rankings = pred["rankings"]["value"]
    assert rankings["by_nll_bits"] == ["first_order", "empirical_prior", "persistence"]
    assert rankings["by_brier"] == ["first_order", "empirical_prior", "persistence"]
    assert rankings["by_top1_accuracy"] == ["first_order", "empirical_prior", "persistence"]
    assert pred["proper_score_rankings_agree"]["value"] is True
    ingestion = pred["ingestion"]["value"]
    assert ingestion["rejection_rate"] == 2 / 12
    assert ingestion["first_order_unseen_source_rate"] == 1 / 2
    # Significance is uncomputable from holdout means — typed result.
    sig = pred["metric_difference_significance"]
    assert sig["status"] == "not_computable"
    assert sig["reason"] == "field_not_recorded"


def test_ranking_tie_breaks_by_canonical_model_order() -> None:
    report = _make_report()
    for m in report["evaluation"]["models"].values():
        m["nll_bits"] = 3.0  # three-way tie
    ev = evaluate(report=validate_report(report))
    assert ev["prediction"]["rankings"]["value"]["by_nll_bits"] == [
        "empirical_prior",
        "persistence",
        "first_order",
    ]


def test_report_absent_prediction_is_typed_not_computable() -> None:
    ev = evaluate(receipts=_series([_make_receipt()]))
    for key in ("uniform_nll_bits", "models", "rankings", "ingestion"):
        entry = ev["prediction"][key]
        assert entry["status"] == "not_computable"
        assert entry["reason"] == "artifact_absent"


# ---------------------------------------------------------------------------
# Consistency verdicts: hand-derived tri-state fixtures
# ---------------------------------------------------------------------------


def test_reason_none_flag_and_sufficiency_consistent_rest_unverifiable() -> None:
    verdicts = check_receipt_consistency(
        validate_receipt(_make_receipt(reason="none"), "r")
    )
    assert verdicts["abstain_flag_matches_reason"] == "consistent"
    assert verdicts["sufficiency_matches_history"] == "consistent"
    # "none" asserts that NO reason fired — but the unseen_state and
    # low_confidence triggers are unrecorded, so with no recorded
    # contradiction the exclusion verdict is honestly unverifiable,
    # and so is the stated-reason trigger.
    assert verdicts["higher_precedence_excluded"] == "unverifiable"
    assert verdicts["stated_reason_trigger"] == "unverifiable"


def test_calibration_drift_trigger_verifiable_both_ways() -> None:
    fired = validate_receipt(
        _make_receipt(reason="calibration_drift", ece=0.25, cal_threshold=0.2), "r"
    )
    assert check_receipt_consistency(fired)["stated_reason_trigger"] == "consistent"
    contradicted = validate_receipt(
        _make_receipt(reason="calibration_drift", ece=0.15, cal_threshold=0.2), "r"
    )
    assert check_receipt_consistency(contradicted)["stated_reason_trigger"] == "contradicted"


def test_contradiction_tolerance_boundary_hand_derived() -> None:
    # Both values are 6-dp-rounded; combined worst-case rounding error is
    # 1e-6, and the tolerance is 2e-6. A recorded gap of 1e-6 must NOT be
    # called a contradiction; a recorded gap of 3e-6 must be.
    within = validate_receipt(
        _make_receipt(reason="calibration_drift", ece=0.2 - 1e-6, cal_threshold=0.2), "r"
    )
    assert check_receipt_consistency(within)["stated_reason_trigger"] == "consistent"
    beyond = validate_receipt(
        _make_receipt(reason="calibration_drift", ece=0.2 - 3e-6, cal_threshold=0.2), "r"
    )
    assert check_receipt_consistency(beyond)["stated_reason_trigger"] == "contradicted"


def test_unseen_state_trigger_is_unverifiable_but_precedence_checked() -> None:
    ok = validate_receipt(
        _make_receipt(reason="unseen_state", observation_count=40, min_history=30), "r"
    )
    v = check_receipt_consistency(ok)
    assert v["stated_reason_trigger"] == "unverifiable"
    assert v["higher_precedence_excluded"] == "consistent"
    # insufficient_history has higher precedence: a receipt claiming
    # unseen_state with too little history contradicts the procedure.
    bad = validate_receipt(
        _make_receipt(
            reason="unseen_state", observation_count=10, min_history=30,
            sufficiency="insufficient",
        ),
        "r",
    )
    assert check_receipt_consistency(bad)["higher_precedence_excluded"] == "contradicted"


def test_distribution_shift_requires_calibration_not_fired() -> None:
    # ece above threshold means calibration_drift should have fired first.
    v = check_receipt_consistency(
        validate_receipt(
            _make_receipt(reason="distribution_shift", ece=0.3, cal_threshold=0.2,
                          drift=0.2, drift_threshold=0.15),
            "r",
        )
    )
    assert v["higher_precedence_excluded"] == "contradicted"
    assert v["stated_reason_trigger"] == "consistent"  # drift 0.2 > 0.15


def test_reason_none_with_recorded_drift_above_threshold_contradicts() -> None:
    v = check_receipt_consistency(
        validate_receipt(
            _make_receipt(reason="none", drift=0.2, drift_threshold=0.15), "r"
        )
    )
    assert v["higher_precedence_excluded"] == "contradicted"


def test_abstain_flag_and_sufficiency_contradictions() -> None:
    flag = validate_receipt(_make_receipt(reason="low_confidence", abstain=False), "r")
    assert check_receipt_consistency(flag)["abstain_flag_matches_reason"] == "contradicted"
    suff = validate_receipt(
        _make_receipt(observation_count=10, min_history=30, sufficiency="sufficient",
                      reason="insufficient_history"),
        "r",
    )
    assert check_receipt_consistency(suff)["sufficiency_matches_history"] == "contradicted"


def test_insufficient_history_trigger_verifiable() -> None:
    ok = validate_receipt(
        _make_receipt(reason="insufficient_history", observation_count=10,
                      min_history=30, sufficiency="insufficient"),
        "r",
    )
    assert check_receipt_consistency(ok)["stated_reason_trigger"] == "consistent"
    lying = validate_receipt(
        _make_receipt(reason="insufficient_history", observation_count=99,
                      min_history=30, sufficiency="sufficient"),
        "r",
    )
    assert check_receipt_consistency(lying)["stated_reason_trigger"] == "contradicted"


# ---------------------------------------------------------------------------
# Higher-precedence truth table (exhaustive, table-driven)
# ---------------------------------------------------------------------------
#
# The v1 receipt does not record the latest observation's prev_seen or
# confidence, so unseen_state and low_confidence triggers are invisible.
# The exclusion check may only say "consistent" when EVERY higher-
# precedence trigger is recorded and shown not to fire; when an
# unrecorded higher trigger could have fired, the honest verdict is
# "unverifiable". A recorded earlier trigger always yields
# "contradicted".


@pytest.mark.parametrize(
    "reason,history_ok,ece_fired,drift_fired,expected",
    [
        # insufficient_history: nothing above it — verify normally.
        ("insufficient_history", False, False, False, "consistent"),
        ("insufficient_history", True, False, False, "consistent"),
        # unseen_state: the only higher clause (history) is recorded.
        ("unseen_state", True, False, False, "consistent"),
        ("unseen_state", False, False, False, "contradicted"),
        # low_confidence: unseen_state is unrecorded above it.
        ("low_confidence", True, False, False, "unverifiable"),
        ("low_confidence", False, False, False, "contradicted"),
        # calibration_drift: unseen_state + low_confidence unrecorded.
        ("calibration_drift", True, False, False, "unverifiable"),
        ("calibration_drift", False, False, False, "contradicted"),
        # distribution_shift: calibration IS recorded (checkable), the
        # two unrecorded clauses still cap the verdict at unverifiable.
        ("distribution_shift", True, False, False, "unverifiable"),
        ("distribution_shift", True, True, False, "contradicted"),
        ("distribution_shift", False, False, False, "contradicted"),
        # none: calibration + drift recorded, two clauses unrecorded.
        ("none", True, False, False, "unverifiable"),
        ("none", True, True, False, "contradicted"),
        ("none", True, False, True, "contradicted"),
        ("none", False, False, False, "contradicted"),
    ],
)
def test_higher_precedence_truth_table(
    reason, history_ok, ece_fired, drift_fired, expected
) -> None:
    receipt = validate_receipt(
        _make_receipt(
            reason=reason,
            observation_count=40 if history_ok else 10,
            min_history=30,
            sufficiency="sufficient" if history_ok else "insufficient",
            ece=0.25 if ece_fired else 0.1,
            cal_threshold=0.2,
            drift=0.2 if drift_fired else 0.05,
            drift_threshold=0.15,
        ),
        "r",
    )
    assert check_receipt_consistency(receipt)["higher_precedence_excluded"] == expected


# ---------------------------------------------------------------------------
# Series comparability (model/config stability gates for recovery)
# ---------------------------------------------------------------------------


def test_mixed_model_series_blocks_and_transitions_not_computable() -> None:
    # Jack's canonical case: first_order n=10 then empirical_prior n=20.
    # Cumulative block recovery across two different predictors is
    # meaningless; it must degrade to a typed result, never a number.
    receipts = _series(
        [
            _make_receipt(observation_count=10, min_history=5, model="first_order"),
            _make_receipt(observation_count=20, min_history=5, model="empirical_prior"),
        ]
    )
    ev = evaluate(receipts=receipts)
    comparability = ev["recovery"]["series_comparability"]["value"]
    assert comparability["model_stable"] is False
    for key in ("surprise_blocks", "confidence_blocks", "abstention_transitions"):
        assert ev["recovery"][key]["status"] == "not_computable"
        assert ev["recovery"][key]["reason"] == "model_not_stable"
    # The prefix-extension assumption's preconditions do NOT hold.
    assert ASSUMPTION_PREFIX_EXTENSION not in ev["assumptions"]
    # Order itself was fine — chronology is a separate, unconflated fact.
    assert ev["recovery"]["chronology"]["value"]["witnessed"] is True


def test_changed_config_blocks_computable_transitions_not() -> None:
    # Stable model, changed monitor configuration: cumulative means are
    # config-independent so blocks stay computable, but abstention
    # transitions compare decisions made under different thresholds.
    receipts = _series(
        [
            _make_receipt(observation_count=10, min_history=5),
            _make_receipt(observation_count=20, min_history=6),
        ]
    )
    ev = evaluate(receipts=receipts)
    comparability = ev["recovery"]["series_comparability"]["value"]
    assert comparability["model_stable"] is True
    assert comparability["config_stable"] is False
    assert ev["recovery"]["surprise_blocks"]["status"] == "computed"
    assert ev["recovery"]["confidence_blocks"]["status"] == "computed"
    assert ev["recovery"]["abstention_transitions"]["status"] == "not_computable"
    assert ev["recovery"]["abstention_transitions"]["reason"] == "config_not_stable"
    assert ASSUMPTION_PREFIX_EXTENSION in ev["assumptions"]  # blocks used it


def test_stable_series_remains_fully_computable() -> None:
    receipts = _series(
        [
            _make_receipt(observation_count=10, min_history=5),
            _make_receipt(observation_count=20, min_history=5),
        ]
    )
    ev = evaluate(receipts=receipts)
    comparability = ev["recovery"]["series_comparability"]["value"]
    assert comparability == {"model_stable": True, "config_stable": True}
    assert ev["recovery"]["surprise_blocks"]["status"] == "computed"
    assert ev["recovery"]["abstention_transitions"]["status"] == "computed"


def test_order_violation_still_wins_over_comparability() -> None:
    # Decreasing counts: order_not_witnessed keeps precedence over the
    # comparability reasons — chronology and comparability are separate
    # contracts and the typed reason must name the first failed gate.
    receipts = _series(
        [
            _make_receipt(observation_count=20, model="first_order"),
            _make_receipt(observation_count=10, model="empirical_prior"),
        ]
    )
    ev = evaluate(receipts=receipts)
    for key in ("surprise_blocks", "confidence_blocks", "abstention_transitions"):
        assert ev["recovery"][key]["reason"] == "order_not_witnessed"


# ---------------------------------------------------------------------------
# Chronology witness + recovery section
# ---------------------------------------------------------------------------


def test_chronology_witness() -> None:
    inc = _series([_make_receipt(observation_count=n) for n in (10, 20, 30)])
    assert chronology_witness(inc) == {"witnessed": True, "first_violation_index": None}
    dup = _series([_make_receipt(observation_count=n) for n in (10, 20, 20)])
    assert chronology_witness(dup) == {"witnessed": False, "first_violation_index": 2}
    single = _series([_make_receipt()])
    assert chronology_witness(single)["witnessed"] is True


def test_recovery_transitions_hand_traced() -> None:
    # abstain pattern T T F T F F T over strictly increasing counts:
    # completed runs [2, 1]; onsets 2; reorientations 2; trailing run 1.
    pattern = [True, True, False, True, False, False, True]
    receipts = _series(
        [
            _make_receipt(
                observation_count=10 * (i + 1),
                reason="low_confidence" if abstain else "none",
                abstain=abstain,
            )
            for i, abstain in enumerate(pattern)
        ]
    )
    ev = evaluate(receipts=receipts)
    trans = ev["recovery"]["abstention_transitions"]["value"]
    assert trans["abstention_onsets"] == 2
    assert trans["reorientations"] == 2
    assert trans["completed_abstention_run_lengths_receipts"] == [2, 1]
    assert trans["unresolved_trailing_abstention_receipts"] == 1


def test_block_means_hand_calculated_with_error_bound() -> None:
    # (n2*m2 - n1*m1) / (n2 - n1) = (40*2.5 - 30*2.0) / 10 = 4.0 exactly;
    # error bound (n1 + n2) * 5e-7 / (n2 - n1) = 70 * 5e-7 / 10 = 3.5e-6.
    receipts = _series(
        [
            _make_receipt(observation_count=30, mean_surprise_bits=2.0),
            _make_receipt(observation_count=40, mean_surprise_bits=2.5),
        ]
    )
    ev = evaluate(receipts=receipts)
    blocks = ev["recovery"]["surprise_blocks"]["value"]
    assert blocks["block_count"] == 1
    block = blocks["blocks"][0]
    assert block["block_mean"] == 4.0
    assert block["error_bound"] == pytest.approx(3.5e-6)
    assert block["within_bounds"] is True
    assert blocks["all_within_bounds"] is True
    # The prefix-extension assumption was used and must be declared.
    assert ASSUMPTION_PREFIX_EXTENSION in ev["assumptions"]


def test_block_means_falsify_prefix_extension_assumption() -> None:
    # Cumulative means 10.0 over 30 then 1.0 over 31 would require the
    # single new observation to have surprise (31*1 - 30*10)/1 = -269
    # bits — impossible for a value bounded in [0, 1000], so the series
    # cannot be prefix-extensions of one stream.
    receipts = _series(
        [
            _make_receipt(observation_count=30, mean_surprise_bits=10.0),
            _make_receipt(observation_count=31, mean_surprise_bits=1.0),
        ]
    )
    blocks = evaluate(receipts=receipts)["recovery"]["surprise_blocks"]["value"]
    assert blocks["blocks"][0]["block_mean"] == pytest.approx(-269.0)
    assert blocks["blocks"][0]["within_bounds"] is False
    assert blocks["all_within_bounds"] is False


def test_order_not_witnessed_blocks_order_dependent_metrics_only() -> None:
    receipts = _series(
        [
            _make_receipt(observation_count=40, reason="low_confidence"),
            _make_receipt(observation_count=30),  # decreasing: witness fails
        ]
    )
    ev = evaluate(receipts=receipts)
    assert ev["recovery"]["chronology"]["value"]["witnessed"] is False
    for key in ("abstention_transitions", "surprise_blocks", "confidence_blocks"):
        assert ev["recovery"][key]["status"] == "not_computable"
        assert ev["recovery"][key]["reason"] == "order_not_witnessed"
    # Order-free metrics still compute.
    assert ev["abstention"]["abstention_rate"]["value"] == 0.5
    assert ev["calibration"]["max_rolling_calibration_error"]["status"] == "computed"
    assert ev["calibration"]["latest_rolling_calibration_error"]["status"] == "not_computable"
    assert ev["assumptions"] == []  # no order → prefix assumption never used


def test_single_receipt_series_too_short_for_transitions() -> None:
    ev = evaluate(receipts=_series([_make_receipt()]))
    assert ev["recovery"]["abstention_transitions"]["reason"] == "series_too_short"
    assert ev["recovery"]["per_observation_recovery"]["reason"] == "field_not_recorded"


# ---------------------------------------------------------------------------
# Abstention section aggregates
# ---------------------------------------------------------------------------


def test_abstention_aggregates_and_reason_histogram() -> None:
    receipts = _series(
        [
            _make_receipt(observation_count=10, min_history=30,
                          reason="insufficient_history", sufficiency="insufficient"),
            _make_receipt(observation_count=40, reason="none"),
            _make_receipt(observation_count=50, reason="calibration_drift",
                          ece=0.25, cal_threshold=0.2),
        ]
    )
    ev = evaluate(receipts=receipts)
    ab = ev["abstention"]
    assert ab["receipt_count"]["value"] == 3
    assert ab["abstention_rate"]["value"] == pytest.approx(2 / 3)
    counts = ab["reason_counts"]["value"]
    assert counts["insufficient_history"] == 1
    assert counts["none"] == 1
    assert counts["calibration_drift"] == 1
    assert counts["unseen_state"] == 0
    assert ab["configurations_identical"]["value"] is True
    assert ab["abstention_quality"]["status"] == "not_computable"
    consistency = ab["consistency"]["value"]
    assert set(consistency) == set(CONSISTENCY_CHECKS)
    for check in CONSISTENCY_CHECKS:
        tallies = consistency[check]["verdicts"]
        assert sum(tallies.values()) == 3
        assert consistency[check]["contradicted_indices_truncated"] is False


def test_mixed_configurations_flagged() -> None:
    receipts = _series(
        [
            _make_receipt(observation_count=30, min_history=30),
            _make_receipt(observation_count=40, min_history=31),
        ]
    )
    ev = evaluate(receipts=receipts)
    assert ev["abstention"]["configurations_identical"]["value"] is False


# ---------------------------------------------------------------------------
# Cross-artifact check (live emitters + synthetic contradiction)
# ---------------------------------------------------------------------------


def _live_artifacts(tmp_path: pathlib.Path) -> tuple[dict, dict]:
    log = _write_log(tmp_path, [A, B] * 30)  # 60 rows: 45 train / 15 holdout
    report = build_report(log)
    observations, reference, recent = observations_from_log(log, "first_order")
    receipt = build_receipt(
        model="first_order",
        observations=observations,
        reference_counts=reference,
        recent_counts=recent,
        config=MonitorConfig(),
    )
    return report, receipt


def test_live_emitter_artifacts_validate_and_cross_check_consistent(tmp_path) -> None:
    # The evaluator must accept exactly what NP1/NP2 actually emit, and —
    # since the receipt's window (50) covers the whole holdout (15) — the
    # receipt's rolling ECE and mean surprise must match the report's
    # holdout ECE and nll_bits within one 6-dp rounding.
    report_raw, receipt_raw = _live_artifacts(tmp_path)
    ev = evaluate(
        report=validate_report(report_raw),
        receipts=_series([receipt_raw]),
    )
    cross = ev["cross_check"]
    assert cross["assumption"] == ASSUMPTION_SAME_SOURCE
    assert cross["ece_match"]["status"] == "computed"
    ece_value = cross["ece_match"]["value"]
    assert ece_value["covering_receipt_count"] == 1
    assert ece_value["results_truncated"] is False
    assert all(entry["verdict"] == "consistent" for entry in ece_value["results"])
    assert all(
        entry["verdict"] == "consistent"
        for entry in cross["surprise_nll_match"]["value"]["results"]
    )
    assert ASSUMPTION_SAME_SOURCE in ev["assumptions"]


def test_cross_check_detects_synthetic_contradiction(tmp_path) -> None:
    report_raw, receipt_raw = _live_artifacts(tmp_path)
    receipt_raw = dict(receipt_raw)
    receipt_raw["rolling_calibration_error"] = round(
        min(1.0, receipt_raw["rolling_calibration_error"] + 0.01), 6
    )
    ev = evaluate(report=validate_report(report_raw), receipts=_series([receipt_raw]))
    assert (
        ev["cross_check"]["ece_match"]["value"]["results"][0]["verdict"] == "contradicted"
    )


def test_cross_check_divergent_cap_regime_is_unverifiable_not_contradicted(tmp_path) -> None:
    # With pathological-but-legal smoothing (1e-306), a single holdout
    # observation with P(actual) < 1e-300 is recorded differently by the
    # two emitters (NP1 floors at ~996.58 bits, NP2 records up to 1000),
    # so genuinely same-source means diverge by ~3.42/n bits — far past
    # the tolerance. The total-bits witness must mark the comparison
    # unverifiable rather than declare a false contradiction.
    tokens = [A] * 60
    tokens[50] = "unclassified"  # novel dominant token inside the holdout
    log = _write_log(tmp_path, tokens)
    report_raw = build_report(log, smoothing=1e-306)
    observations, reference, recent = observations_from_log(
        log, "first_order", smoothing=1e-306
    )
    receipt_raw = build_receipt(
        model="first_order",
        observations=observations,
        reference_counts=reference,
        recent_counts=recent,
        config=MonitorConfig(),
    )
    ev = evaluate(report=validate_report(report_raw), receipts=_series([receipt_raw]))
    results = ev["cross_check"]["surprise_nll_match"]["value"]["results"]
    assert results and all(entry["verdict"] == "unverifiable" for entry in results)


def test_genuine_fp_overshoot_report_still_validates(tmp_path) -> None:
    # NP1's nll_bits is a naive float sum / n; on an all-floored holdout
    # (persistence over a strict alternation with smoothing=1e-306) the
    # mean overshoots -log2(1e-300) by accumulated rounding. That
    # byte-genuine report must validate, not be rejected as hostile.
    log = _write_log(tmp_path, [A, B] * 30)
    report_raw = build_report(log, smoothing=1e-306)
    validated = validate_report(report_raw)  # must not raise
    assert validated["models"]["persistence"]["nll_bits"] >= 996.0
    # A fabricated value beyond the documented slack is still rejected.
    forged = build_report(log, smoothing=1e-306)
    forged["evaluation"]["models"]["persistence"]["nll_bits"] = 997.0
    with pytest.raises(EvaluatorInputError, match="outside"):
        validate_report(forged)


def test_cross_check_requires_covering_receipt(tmp_path) -> None:
    report_raw, receipt_raw = _live_artifacts(tmp_path)
    receipt_raw = dict(receipt_raw)
    receipt_raw["observation_count"] = 14  # not the full holdout
    ev = evaluate(report=validate_report(report_raw), receipts=_series([receipt_raw]))
    assert ev["cross_check"]["ece_match"]["reason"] == "no_covering_receipt"
    assert ASSUMPTION_SAME_SOURCE not in ev["assumptions"]


# ---------------------------------------------------------------------------
# Validation: fail-closed adversarial corpus
# ---------------------------------------------------------------------------


def test_unknown_schema_variants_rejected() -> None:
    report = _make_report()
    report["schema"] = "nextness-predictor-v2"
    with pytest.raises(EvaluatorInputError, match="unknown variant"):
        validate_report(report)
    receipt = _make_receipt()
    receipt["schema"] = "nextness-monitor-v0"
    with pytest.raises(EvaluatorInputError, match="unknown variant"):
        validate_receipt(receipt, "r")


def test_unknown_and_missing_keys_rejected() -> None:
    extra = _make_report()
    extra["surprise_field"] = 1
    with pytest.raises(EvaluatorInputError, match="key set mismatch"):
        validate_report(extra)
    missing = _make_report()
    del missing["config"]
    with pytest.raises(EvaluatorInputError, match="key set mismatch"):
        validate_report(missing)
    receipt = _make_receipt()
    del receipt["config"]
    with pytest.raises(EvaluatorInputError, match="key set mismatch"):
        validate_receipt(receipt, "r")


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda r: r["input"].__setitem__("rows_read", 5), "rows_read <"),
        (lambda r: r["input"]["rejections"].__setitem__("malformed_json", 1), "do not sum"),
        (lambda r: r["evaluation"].__setitem__("split_index", 5), "split_index"),
        (lambda r: r["evaluation"].__setitem__("holdout_rows", 3), "!= rows_accepted"),
        (lambda r: r["evaluation"].__setitem__("first_order_unseen_source_count", 3), "outside"),
    ],
)
def test_internal_accounting_violations_rejected(mutate, match) -> None:
    report = _make_report()
    mutate(report)
    with pytest.raises(EvaluatorInputError, match=match):
        validate_report(report)


def test_bool_is_not_a_count_or_flag_substitute() -> None:
    receipt = _make_receipt()
    receipt["observation_count"] = True
    with pytest.raises(EvaluatorInputError, match="builtin int"):
        validate_receipt(receipt, "r")
    receipt = _make_receipt()
    receipt["abstain"] = 1
    with pytest.raises(EvaluatorInputError, match="builtin bool"):
        validate_receipt(receipt, "r")


def test_hostile_container_and_string_subclasses_rejected() -> None:
    class EvilDict(dict):
        def keys(self):  # pragma: no cover - must never be consulted
            raise AssertionError("hostile keys() was consulted")

    with pytest.raises(EvaluatorInputError, match="builtin dict"):
        validate_report(EvilDict(_make_report()))

    class EvilStr(str):
        def __eq__(self, other):  # pragma: no cover - must never be consulted
            raise AssertionError("hostile __eq__ was consulted")

        __hash__ = str.__hash__

    receipt = _make_receipt()
    receipt["model"] = EvilStr("first_order")
    with pytest.raises(EvaluatorInputError, match="builtin str"):
        validate_receipt(receipt, "r")


def test_astronomical_and_nonfinite_numbers_rejected(tmp_path) -> None:
    receipt = _make_receipt()
    receipt["observation_count"] = 10**7  # beyond MAX_ROWS_CEILING
    with pytest.raises(EvaluatorInputError, match="outside"):
        validate_receipt(receipt, "r")
    receipt = _make_receipt()
    receipt["mean_confidence"] = 10**400  # OverflowError path
    with pytest.raises(EvaluatorInputError, match="finite float"):
        validate_receipt(receipt, "r")
    # NaN smuggled through a real JSON file (Python's json accepts NaN).
    nan_file = tmp_path / "nan.json"
    nan_file.write_text(
        json.dumps(_make_receipt()).replace("0.5", "NaN", 1), encoding="utf-8"
    )
    parsed, _, _ = load_json_artifact(nan_file)
    with pytest.raises(EvaluatorInputError, match="not finite"):
        validate_receipt(parsed, "r")


def test_oversized_artifact_fails_closed_before_parse(tmp_path) -> None:
    big = tmp_path / "big.json"
    big.write_bytes(b"x" * (MAX_INPUT_BYTES + 10))
    with pytest.raises(EvaluatorInputError, match="exceeds"):
        load_json_artifact(big)


def test_pathologically_nested_artifact_fails_closed(tmp_path) -> None:
    deep = tmp_path / "deep.json"
    deep.write_bytes(b"[" * 200_000)  # within the size bound, hostile depth
    with pytest.raises(EvaluatorInputError, match="depth limit"):
        load_json_artifact(deep)


def test_series_bounds_fail_closed() -> None:
    with pytest.raises(EvaluatorInputError, match="empty"):
        validate_receipt_series([])
    with pytest.raises(EvaluatorInputError, match="exceeding"):
        validate_receipt_series([{}] * (MAX_SERIES_RECEIPTS + 1))
    with pytest.raises(EvaluatorInputError, match="builtin dict"):
        validate_receipt_series([_make_receipt(), "not a receipt"])
    with pytest.raises(EvaluatorInputError, match="receipt object or an array"):
        validate_receipt_series("just a string")


def test_no_artifacts_is_an_input_error() -> None:
    with pytest.raises(EvaluatorInputError, match="nothing to evaluate"):
        evaluate()


def test_not_computable_reasons_are_from_fixed_vocabulary() -> None:
    ev = evaluate(receipts=_series([_make_receipt()]))

    def _walk(node) -> None:
        if isinstance(node, dict):
            if node.get("status") == "not_computable":
                assert node["reason"] in NOT_COMPUTABLE_REASONS
                assert isinstance(node["requires"], str) and node["requires"]
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(ev)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_evaluation_byte_identical_across_runs(tmp_path) -> None:
    report_raw, receipt_raw = _live_artifacts(tmp_path)
    report_file = tmp_path / "report.json"
    report_file.write_text(serialize_report(report_raw), encoding="utf-8")
    receipts_file = tmp_path / "receipts.json"
    receipts_file.write_text(
        json.dumps([json.loads(serialize_receipt(receipt_raw))]), encoding="utf-8"
    )
    outputs = {
        serialize_evaluation(
            build_evaluation(report_path=report_file, receipts_path=receipts_file)
        )
        for _ in range(3)
    }
    assert len(outputs) == 1
    evaluation = json.loads(next(iter(outputs)))
    assert evaluation["schema"] == EVALUATION_SCHEMA
    assert evaluation["artifacts"]["report"]["provided"] is True
    assert evaluation["artifacts"]["receipts"]["receipt_count"] == 1
    # Provenance: no paths, no timestamps — just content hashes.
    assert len(evaluation["artifacts"]["report"]["sha256"]) == 64
    assert "time" not in next(iter(outputs)).lower()


def test_input_key_order_does_not_change_the_evaluation(tmp_path) -> None:
    report = _make_report()

    def _reorder(obj):
        if isinstance(obj, dict):
            return {k: _reorder(obj[k]) for k in reversed(list(obj))}
        return obj

    a = tmp_path / "a.json"
    a.write_text(json.dumps(report), encoding="utf-8")
    b = tmp_path / "b.json"
    b.write_text(json.dumps(_reorder(report)), encoding="utf-8")
    ev_a = build_evaluation(report_path=a)
    ev_b = build_evaluation(report_path=b)
    # The bytes differ, so provenance differs — but every computed value
    # must be identical.
    ev_a["artifacts"] = ev_b["artifacts"] = None
    assert serialize_evaluation(ev_a) == serialize_evaluation(ev_b)


# ---------------------------------------------------------------------------
# Property-style seeded traces (stdlib random only — no new dependency)
# ---------------------------------------------------------------------------


def _seeded_series(rng: random.Random, length: int) -> list[dict]:
    series = []
    count = 0
    for _ in range(length):
        count += rng.randint(1, 50)
        reason = rng.choice(
            ["none", "insufficient_history", "unseen_state", "low_confidence",
             "calibration_drift", "distribution_shift"]
        )
        series.append(
            _make_receipt(
                observation_count=count,
                mean_confidence=round(rng.random(), 6),
                mean_surprise_bits=round(rng.random() * 10, 6),
                ece=round(rng.random(), 6),
                drift=round(rng.random(), 6),
                reason=reason,
                sufficiency=rng.choice(["sufficient", "insufficient"]),
            )
        )
    return series


@pytest.mark.parametrize("seed", [7, 77, 777])
def test_seeded_series_bounded_deterministic_and_shuffle_invariant(seed: int) -> None:
    rng = random.Random(seed)
    raw = _seeded_series(rng, 20)
    ev1 = evaluate(receipts=_series(raw))
    ev2 = evaluate(receipts=_series(raw))
    assert serialize_evaluation(ev1) == serialize_evaluation(ev2)
    assert len(serialize_evaluation(ev1).encode("utf-8")) <= MAX_EVALUATION_BYTES

    # Order-free metrics must survive any reordering: seeded shuffles
    # plus a reversal (which guarantees the chronology witness fails, so
    # order-dependent metrics must degrade to typed not_computable —
    # never to wrong numbers).
    permutations = [list(reversed(raw))]
    for _ in range(3):
        shuffled = list(raw)
        rng.shuffle(shuffled)
        permutations.append(shuffled)
    for permuted in permutations:
        ev_p = evaluate(receipts=_series(permuted))
        assert ev_p["abstention"]["reason_counts"] == ev1["abstention"]["reason_counts"]
        assert ev_p["abstention"]["abstention_rate"] == ev1["abstention"]["abstention_rate"]
        assert (
            ev_p["calibration"]["max_rolling_calibration_error"]
            == ev1["calibration"]["max_rolling_calibration_error"]
        )
        for check in CONSISTENCY_CHECKS:
            assert (
                ev_p["abstention"]["consistency"]["value"][check]["verdicts"]
                == ev1["abstention"]["consistency"]["value"][check]["verdicts"]
            )
        if permuted != raw:  # a permutation that breaks strict order
            assert ev_p["recovery"]["abstention_transitions"]["status"] == "not_computable"


def test_full_length_series_stays_inside_output_ceiling() -> None:
    # Worst-ish case: the maximum series length, every receipt
    # contradictory (so contradiction indices saturate), all block lists
    # at their caps — the evaluation must still fit the 64 KiB ceiling,
    # with truncation flagged explicitly rather than silently.
    receipts = _series(
        [
            _make_receipt(
                observation_count=10 + i,
                reason="calibration_drift",
                ece=0.1,             # below threshold: trigger contradicted
                abstain=False,       # contradicts the stated reason
                sufficiency="insufficient",  # contradicts history
            )
            for i in range(MAX_SERIES_RECEIPTS)
        ]
    )
    ev = evaluate(receipts=receipts)
    serialized = serialize_evaluation(ev)
    assert len(serialized.encode("utf-8")) <= MAX_EVALUATION_BYTES
    consistency = ev["abstention"]["consistency"]["value"]
    assert consistency["abstain_flag_matches_reason"]["contradicted_indices_truncated"] is True
    assert (
        len(consistency["abstain_flag_matches_reason"]["contradicted_indices"])
        == MAX_DETAIL_ITEMS
    )
    blocks = ev["recovery"]["surprise_blocks"]["value"]
    assert blocks["blocks_truncated"] is True
    assert blocks["block_count"] == MAX_SERIES_RECEIPTS - 1


def test_report_plus_full_covering_series_stays_inside_output_ceiling() -> None:
    # The other saturation direction: a valid report plus the maximum
    # series where EVERY receipt covers the report's holdout (equal
    # counts — a legitimate recorded corpus whose chronology witness
    # fails). Cross-check result lists must truncate explicitly and the
    # whole evaluation must stay inside the 64 KiB ceiling.
    report = validate_report(_make_report())  # holdout_rows == 2
    receipts = _series(
        [_make_receipt(observation_count=2, min_history=5) for _ in range(MAX_SERIES_RECEIPTS)]
    )
    ev = evaluate(report=report, receipts=receipts)
    assert len(serialize_evaluation(ev).encode("utf-8")) <= MAX_EVALUATION_BYTES
    for key in ("ece_match", "surprise_nll_match"):
        value = ev["cross_check"][key]["value"]
        assert value["covering_receipt_count"] == MAX_SERIES_RECEIPTS
        assert value["results_truncated"] is True
        assert len(value["results"]) == MAX_DETAIL_ITEMS


# ---------------------------------------------------------------------------
# CLI: exit codes, write boundary, concise errors
# ---------------------------------------------------------------------------


def _write_artifacts(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    report_file = tmp_path / "report.json"
    report_file.write_text(json.dumps(_make_report()), encoding="utf-8")
    receipts_file = tmp_path / "receipts.json"
    receipts_file.write_text(
        json.dumps([_make_receipt(observation_count=n) for n in (10, 20)]),
        encoding="utf-8",
    )
    return report_file, receipts_file


def test_cli_success_stdout_and_output_file(tmp_path, capsys) -> None:
    report_file, receipts_file = _write_artifacts(tmp_path)
    assert main(["--report", str(report_file), "--receipts", str(receipts_file)]) == 0
    stdout = capsys.readouterr().out
    assert json.loads(stdout)["schema"] == EVALUATION_SCHEMA

    out = tmp_path / "evaluation.json"
    assert main(["--report", str(report_file), "--output", str(out)]) == 0
    first = out.read_bytes()
    assert main(["--report", str(report_file), "--output", str(out)]) == 0
    assert out.read_bytes() == first  # byte-identical rewrite
    # LF-only on every platform: the written artifact's bytes are exactly
    # the canonical serialization, never newline-translated.
    assert b"\r" not in first
    assert first == serialize_evaluation(build_evaluation(report_path=report_file)).encode("utf-8")


def test_cli_requires_at_least_one_artifact(capsys) -> None:
    assert main([]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "Traceback" not in err


def test_cli_missing_and_malformed_artifacts_exit_2(tmp_path, capsys) -> None:
    assert main(["--report", str(tmp_path / "absent.json")]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert main(["--report", str(bad)]) == 2
    unknown = tmp_path / "unknown.json"
    unknown.write_text(json.dumps({"schema": "mystery-v9"}), encoding="utf-8")
    assert main(["--receipts", str(unknown)]) == 2
    for line in capsys.readouterr().err.splitlines():
        assert line.startswith("error:")


def test_cli_write_boundary_outside_input_dir_exit_4(tmp_path, capsys) -> None:
    report_file, _ = _write_artifacts(tmp_path / "inputs")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert (
        main(["--report", str(report_file), "--output", str(elsewhere / "e.json")]) == 4
    )
    assert "outside the primary input" in capsys.readouterr().err


def test_cli_write_boundary_never_inside_data_tree(tmp_path, capsys, monkeypatch) -> None:
    import scripts.nextness_evaluator as evaluator_module

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(evaluator_module, "_repo_data_dir", lambda: data_dir.resolve())
    report_file = data_dir / "report.json"
    report_file.write_text(json.dumps(_make_report()), encoding="utf-8")
    # Output inside the input's own directory would normally be allowed —
    # but that directory IS the data/ tree, so it must be refused.
    assert (
        main(["--report", str(report_file), "--output", str(data_dir / "e.json")]) == 4
    )
    assert "data/ tree" in capsys.readouterr().err


def test_cli_oversized_evaluation_exit_5(tmp_path, capsys, monkeypatch) -> None:
    import scripts.nextness_evaluator as evaluator_module

    monkeypatch.setattr(evaluator_module, "MAX_EVALUATION_BYTES", 64)
    report_file, _ = _write_artifacts(tmp_path)
    assert main(["--report", str(report_file)]) == 5
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "Traceback" not in err


# ---------------------------------------------------------------------------
# Output identity guard: --output must never name or alias ANY supplied
# input artifact (report OR receipts, primary or not) — by resolved path
# and by file identity (os.path.samefile on resolved inputs; fail closed
# when identity cannot be verified). Refusal contract: exit 4, ONE
# concise ``error:`` line, no traceback, every supplied input
# byte-identical, no replacement artifact written, and the refusal
# happens BEFORE any evaluation computation.
# ---------------------------------------------------------------------------


def _make_hardlink_or_skip(target: pathlib.Path, link: pathlib.Path) -> None:
    try:
        os.link(target, link)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("hard links unsupported on this filesystem")


def _make_symlink_or_skip(target: pathlib.Path, link: pathlib.Path) -> None:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported here (e.g. Windows w/o privilege)")


def _expect_alias_refusal(
    capsys,
    tmp_path: pathlib.Path,
    argv: list[str],
    inputs: list[pathlib.Path],
) -> None:
    """Full refusal contract for one CLI invocation."""
    before = {p: p.read_bytes() for p in inputs}
    entries_before = sorted(p.name for p in tmp_path.iterdir())
    assert main(argv) == 4, argv
    captured = capsys.readouterr()
    assert captured.err.startswith("error:"), argv
    assert captured.err.count("error:") == 1, argv
    assert "Traceback" not in captured.err, argv
    for p, b in before.items():
        assert p.read_bytes() == b, f"input mutated: {p}"
    assert sorted(p.name for p in tmp_path.iterdir()) == entries_before


# --- report-only: all four alias identities --------------------------------


def test_cli_report_only_direct_output_alias_is_refused(tmp_path, capsys) -> None:
    report_file, _ = _write_artifacts(tmp_path)
    _expect_alias_refusal(
        capsys, tmp_path,
        ["--report", str(report_file), "--output", str(report_file)],
        [report_file],
    )


def test_cli_report_only_lexical_output_alias_is_refused(tmp_path, capsys) -> None:
    report_file, _ = _write_artifacts(tmp_path)
    alias = tmp_path / "sub" / ".." / "report.json"
    assert str(alias) != str(report_file)
    _expect_alias_refusal(
        capsys, tmp_path,
        ["--report", str(report_file), "--output", str(alias)],
        [report_file],
    )


def test_cli_report_only_symlink_output_alias_is_refused(tmp_path, capsys) -> None:
    report_file, _ = _write_artifacts(tmp_path)
    link = tmp_path / "evaluation.json"
    _make_symlink_or_skip(report_file, link)
    _expect_alias_refusal(
        capsys, tmp_path,
        ["--report", str(report_file), "--output", str(link)],
        [report_file],
    )


def test_cli_report_only_hardlink_output_alias_is_refused(tmp_path, capsys) -> None:
    report_file, _ = _write_artifacts(tmp_path)
    link = tmp_path / "evaluation.json"
    _make_hardlink_or_skip(report_file, link)
    _expect_alias_refusal(
        capsys, tmp_path,
        ["--report", str(report_file), "--output", str(link)],
        [report_file, link],
    )


# --- receipts-only: the same four identities --------------------------------


def test_cli_receipts_only_direct_output_alias_is_refused(tmp_path, capsys) -> None:
    _, receipts_file = _write_artifacts(tmp_path)
    _expect_alias_refusal(
        capsys, tmp_path,
        ["--receipts", str(receipts_file), "--output", str(receipts_file)],
        [receipts_file],
    )


def test_cli_receipts_only_lexical_output_alias_is_refused(tmp_path, capsys) -> None:
    _, receipts_file = _write_artifacts(tmp_path)
    alias = tmp_path / "sub" / ".." / "receipts.json"
    _expect_alias_refusal(
        capsys, tmp_path,
        ["--receipts", str(receipts_file), "--output", str(alias)],
        [receipts_file],
    )


def test_cli_receipts_only_symlink_output_alias_is_refused(tmp_path, capsys) -> None:
    _, receipts_file = _write_artifacts(tmp_path)
    link = tmp_path / "evaluation.json"
    _make_symlink_or_skip(receipts_file, link)
    _expect_alias_refusal(
        capsys, tmp_path,
        ["--receipts", str(receipts_file), "--output", str(link)],
        [receipts_file],
    )


def test_cli_receipts_only_hardlink_output_alias_is_refused(tmp_path, capsys) -> None:
    _, receipts_file = _write_artifacts(tmp_path)
    link = tmp_path / "evaluation.json"
    _make_hardlink_or_skip(receipts_file, link)
    _expect_alias_refusal(
        capsys, tmp_path,
        ["--receipts", str(receipts_file), "--output", str(link)],
        [receipts_file, link],
    )


# --- both supplied: output aliasing EITHER input is refused -----------------


def test_cli_both_supplied_output_aliasing_report_is_refused(tmp_path, capsys) -> None:
    report_file, receipts_file = _write_artifacts(tmp_path)
    _expect_alias_refusal(
        capsys, tmp_path,
        ["--report", str(report_file), "--receipts", str(receipts_file),
         "--output", str(report_file)],
        [report_file, receipts_file],
    )


def test_cli_both_supplied_output_aliasing_receipts_is_refused(tmp_path, capsys) -> None:
    # The non-primary input: report is primary, receipts sits in the same
    # directory — only an every-supplied-input identity check catches this.
    report_file, receipts_file = _write_artifacts(tmp_path)
    _expect_alias_refusal(
        capsys, tmp_path,
        ["--report", str(report_file), "--receipts", str(receipts_file),
         "--output", str(receipts_file)],
        [report_file, receipts_file],
    )


def test_cli_both_supplied_hardlink_of_receipts_is_refused(tmp_path, capsys) -> None:
    report_file, receipts_file = _write_artifacts(tmp_path)
    link = tmp_path / "evaluation.json"
    _make_hardlink_or_skip(receipts_file, link)
    _expect_alias_refusal(
        capsys, tmp_path,
        ["--report", str(report_file), "--receipts", str(receipts_file),
         "--output", str(link)],
        [report_file, receipts_file, link],
    )


# --- refusal precedes evaluation computation --------------------------------


def test_alias_refusal_precedes_evaluation_computation(tmp_path, capsys, monkeypatch) -> None:
    import scripts.nextness_evaluator as evaluator_module

    report_file, receipts_file = _write_artifacts(tmp_path)

    def spy(*args, **kwargs):
        raise AssertionError("build_evaluation invoked despite alias refusal")

    monkeypatch.setattr(evaluator_module, "build_evaluation", spy)
    assert main(
        ["--report", str(report_file), "--output", str(report_file)]
    ) == 4
    assert main(
        ["--report", str(report_file), "--receipts", str(receipts_file),
         "--output", str(receipts_file)]
    ) == 4
    err = capsys.readouterr().err
    assert "Traceback" not in err


# --- ordinary sibling outputs remain allowed ---------------------------------


def _artifacts_in_two_dirs(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """A report and a receipts artifact in two DIFFERENT directories, so
    primary selection visibly decides which directory confines --output."""
    report_dir = tmp_path / "report_dir"
    receipts_dir = tmp_path / "receipts_dir"
    report_dir.mkdir()
    receipts_dir.mkdir()
    report_file = report_dir / "report.json"
    report_file.write_text(json.dumps(_make_report()), encoding="utf-8")
    receipts_file = receipts_dir / "receipts.json"
    receipts_file.write_text(
        json.dumps([_make_receipt(observation_count=n) for n in (10, 20)]),
        encoding="utf-8",
    )
    return report_file, receipts_file


def test_primary_is_report_regardless_of_mapping_insertion_order(tmp_path) -> None:
    # Receipts inserted FIRST: the report must still be primary — an
    # output beside the report is allowed under the normal lane rules.
    report_file, receipts_file = _artifacts_in_two_dirs(tmp_path)
    inputs = {"receipts": receipts_file, "report": report_file}
    assert list(inputs) == ["receipts", "report"]  # hostile insertion order
    validate_output_path(report_file.parent / "evaluation.json", inputs)  # no raise


def test_output_beside_receipts_refused_when_report_present(tmp_path) -> None:
    # Same hostile insertion order: an output beside the RECEIPTS but
    # outside the report's directory violates primary confinement.
    report_file, receipts_file = _artifacts_in_two_dirs(tmp_path)
    inputs = {"receipts": receipts_file, "report": report_file}
    with pytest.raises(WriteOutsideLogDirError):
        validate_output_path(receipts_file.parent / "evaluation.json", inputs)


def test_receipts_only_mapping_uses_receipts_as_primary(tmp_path) -> None:
    _, receipts_file = _artifacts_in_two_dirs(tmp_path)
    validate_output_path(
        receipts_file.parent / "evaluation.json", {"receipts": receipts_file}
    )  # no raise: receipts is the primary when it is the only input


def test_empty_inputs_mapping_is_descriptive_error_never_stopiteration(tmp_path) -> None:
    with pytest.raises(EvaluatorInputError, match="no input artifact"):
        validate_output_path(tmp_path / "evaluation.json", {})


def test_identity_checks_hold_under_hostile_insertion_order(tmp_path) -> None:
    # Aliases of EITHER artifact stay refused regardless of mapping order.
    report_file, receipts_file = _artifacts_in_two_dirs(tmp_path)
    inputs = {"receipts": receipts_file, "report": report_file}
    with pytest.raises(WriteOutsideLogDirError):
        validate_output_path(report_file, inputs)
    with pytest.raises(WriteOutsideLogDirError):
        validate_output_path(receipts_file, inputs)


def test_cli_sibling_outputs_remain_allowed(tmp_path, capsys) -> None:
    report_file, receipts_file = _write_artifacts(tmp_path)
    report_before = report_file.read_bytes()
    receipts_before = receipts_file.read_bytes()

    fresh = tmp_path / "evaluation.json"          # nonexistent sibling
    assert main(["--report", str(report_file), "--receipts",
                 str(receipts_file), "--output", str(fresh)]) == 0
    assert json.loads(fresh.read_bytes())["schema"] == EVALUATION_SCHEMA

    stale = tmp_path / "stale.json"               # existing non-alias sibling
    stale.write_text("previous content\n", encoding="utf-8")
    assert main(["--report", str(report_file), "--output", str(stale)]) == 0
    assert json.loads(stale.read_bytes())["schema"] == EVALUATION_SCHEMA

    assert report_file.read_bytes() == report_before
    assert receipts_file.read_bytes() == receipts_before


# ---------------------------------------------------------------------------
# Output-boundary pins: directory and symlink-to-directory targets.
#
# Coverage pinning of ESTABLISHED behavior (not a defect): a directory
# target passes path validation (it is inside the primary input's
# directory and aliases nothing) and is refused at write time by the
# documented OSError lane — exit 4, one concise ``error:`` line, no
# traceback, every input byte-identical, the directory and its contents
# untouched, and no output artifact (whole or partial) created.
# ---------------------------------------------------------------------------


def _sentinel_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    target_dir = tmp_path / "already_here"
    target_dir.mkdir()
    (target_dir / "keep.txt").write_text("keep me\n", encoding="utf-8")
    return target_dir


def test_cli_existing_directory_output_target_pinned(tmp_path, capsys) -> None:
    report_file, receipts_file = _write_artifacts(tmp_path)
    target_dir = _sentinel_dir(tmp_path)
    _expect_alias_refusal(
        capsys, tmp_path,
        ["--report", str(report_file), "--receipts", str(receipts_file),
         "--output", str(target_dir)],
        [report_file, receipts_file],
    )
    assert target_dir.is_dir()
    assert (target_dir / "keep.txt").read_text(encoding="utf-8") == "keep me\n"
    assert sorted(p.name for p in target_dir.iterdir()) == ["keep.txt"]


def test_cli_symlink_to_directory_output_target_pinned(tmp_path, capsys) -> None:
    report_file, receipts_file = _write_artifacts(tmp_path)
    real_dir = _sentinel_dir(tmp_path)
    link = tmp_path / "evaluation.json"
    try:
        link.symlink_to(real_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported here (e.g. Windows w/o privilege)")
    _expect_alias_refusal(
        capsys, tmp_path,
        ["--report", str(report_file), "--receipts", str(receipts_file),
         "--output", str(link)],
        [report_file, receipts_file],
    )
    assert real_dir.is_dir()
    assert (real_dir / "keep.txt").read_text(encoding="utf-8") == "keep me\n"
    assert sorted(p.name for p in real_dir.iterdir()) == ["keep.txt"]
    # The output link itself was not replaced by a regular file.
    assert link.is_symlink()
    assert link.resolve() == real_dir.resolve()


# ---------------------------------------------------------------------------
# Live end-to-end: emitter files → CLI → evaluation
# ---------------------------------------------------------------------------


def test_end_to_end_live_pipeline_via_cli(tmp_path, capsys) -> None:
    report_raw, receipt_raw = _live_artifacts(tmp_path)
    report_file = tmp_path / "report.json"
    report_file.write_text(serialize_report(report_raw), encoding="utf-8")
    receipts_file = tmp_path / "receipt.json"
    receipts_file.write_text(serialize_receipt(receipt_raw), encoding="utf-8")
    assert main(["--report", str(report_file), "--receipts", str(receipts_file)]) == 0
    evaluation = json.loads(capsys.readouterr().out)
    assert evaluation["schema"] == EVALUATION_SCHEMA
    # A single live receipt loads as a series of one.
    assert evaluation["artifacts"]["receipts"]["receipt_count"] == 1
    assert (
        evaluation["cross_check"]["ece_match"]["value"]["results"][0]["verdict"]
        == "consistent"
    )


# ---------------------------------------------------------------------------
# Cross-module CLI failure-contract pins (Candidate C; see
# docs/NEXTNESS_CLI_FAILURE_CONTRACTS.md). Pins of ESTABLISHED behavior:
# argparse usage lane (SystemExit(2), multi-line usage:, outside main()'s
# return path);
# identity-inspection failure fails closed (exit 4);
# unexpected-error propagation stays loud
# ---------------------------------------------------------------------------


def test_cli_argparse_usage_error_exits_2(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--bogus"])
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "usage:" in err
    assert "Traceback" not in err


def test_cli_identity_inspection_failure_fails_closed_exit_4(
    tmp_path, capsys, monkeypatch
) -> None:
    report_file, receipts_file = _write_artifacts(tmp_path)
    out = tmp_path / "evaluation.json"
    out.write_text("stale existing non-alias output\n", encoding="utf-8")
    before = {p: p.read_bytes() for p in (report_file, receipts_file, out)}
    entries_before = sorted(p.name for p in tmp_path.iterdir())
    out_resolved = out.resolve()
    real_samefile = os.path.samefile

    def probed(a, b):
        if pathlib.Path(a).resolve() == out_resolved:
            raise PermissionError(13, "identity probe denied")
        return real_samefile(a, b)

    monkeypatch.setattr(os.path, "samefile", probed)
    assert main(["--report", str(report_file), "--receipts", str(receipts_file),
                 "--output", str(out)]) == 4
    captured = capsys.readouterr()
    lines = [l for l in captured.err.strip().splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("error:")
    assert "Traceback" not in captured.err
    for p, b in before.items():
        assert p.read_bytes() == b
    assert sorted(p.name for p in tmp_path.iterdir()) == entries_before


def test_cli_unexpected_errors_are_not_hidden(tmp_path, monkeypatch) -> None:
    import scripts.nextness_evaluator as evaluator_module

    report_file, _ = _write_artifacts(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("sentinel propagation probe")

    monkeypatch.setattr(evaluator_module, "build_evaluation", boom)
    with pytest.raises(RuntimeError, match="sentinel propagation probe"):
        main(["--report", str(report_file)])


# ---------------------------------------------------------------------------
# Output-write STAGE pins (see docs/NEXTNESS_CLI_FAILURE_CONTRACTS.md and the
# 2026-07-17 output-write audit). INJECTED deterministic branch exercises of
# the expected exit-4 operational-write lane — distinct from PUBLIC
# filesystem behavior and never a public-reachability claim. Stage counters
# assert the intended operation (open/write/close) actually fired, so no pin
# can pass by triggering the wrong stage.
# ---------------------------------------------------------------------------


class _StageProxy:
    def __init__(self, raw, fail_write_at=None, fail_close=False):
        self._raw = raw
        self._fail_at = fail_write_at
        self._fail_close = fail_close
        self.writes_ok = 0
        self.close_attempted = False

    def write(self, data):
        if self._fail_at is not None and self.writes_ok + 1 >= self._fail_at:
            raise OSError(28, "injected write failure")
        n = self._raw.write(data)
        self.writes_ok += 1
        return n

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close_attempted = True
        self._raw.__exit__(*exc)
        if self._fail_close and exc[0] is None:
            raise OSError(5, "injected close failure")

    def __getattr__(self, name):
        return getattr(self._raw, name)


def _patch_output_stage(monkeypatch, victim_resolved, *, deny_open=False,
                        fail_write_at=None, fail_close=False):
    """Patch ONLY the victim path's binary-write open; returns stage state."""
    state = {"opens": 0, "proxy": None}
    real_open = pathlib.Path.open

    def patched(self, mode="r", *args, **kwargs):
        if "w" in mode and "b" in mode and self.resolve() == victim_resolved:
            state["opens"] += 1
            if deny_open:
                raise PermissionError(13, "injected open denial")
            raw = real_open(self, mode, *args, **kwargs)
            state["proxy"] = _StageProxy(raw, fail_write_at, fail_close)
            return state["proxy"]
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "open", patched)
    return state


def _stage_exit4_receipt(capsys):
    captured = capsys.readouterr()
    lines = [l for l in captured.err.strip().splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("error:")
    assert "Traceback" not in captured.err


def test_cli_output_open_denial_pinned(tmp_path, capsys, monkeypatch) -> None:
    """Open denial: no truncation ever happened — existing destination,
    inputs and directory inventory all byte-identical; exit 4, one line."""
    report_file, receipts_file = _write_artifacts(tmp_path)
    out = tmp_path / "stage_pin.out"
    out.write_text("pre-existing destination\n", encoding="utf-8")
    before = {p: p.read_bytes() for p in [report_file, receipts_file] + [out]}
    inv = sorted(p.name for p in tmp_path.iterdir())
    state = _patch_output_stage(monkeypatch, out.resolve(), deny_open=True)
    assert main(["--report", str(report_file), "--receipts", str(receipts_file), "--output", str(out)]) == 4
    _stage_exit4_receipt(capsys)
    assert state["opens"] == 1 and state["proxy"] is None  # failed AT open
    for p, b in before.items():
        assert p.read_bytes() == b
    assert sorted(p.name for p in tmp_path.iterdir()) == inv


def test_cli_post_open_write_failure_pinned(tmp_path, capsys, monkeypatch) -> None:
    """Post-open failure of the FIRST whole-buffer write: open succeeded,
    zero writes completed, destination truncated to empty; inputs
    unchanged; exit 4 with one concise line."""
    report_file, receipts_file = _write_artifacts(tmp_path)
    out = tmp_path / "stage_pin.out"
    out.write_text("stale bytes to observe truncation\n", encoding="utf-8")
    before = {p: p.read_bytes() for p in [report_file, receipts_file]}
    state = _patch_output_stage(monkeypatch, out.resolve(), fail_write_at=1)
    assert main(["--report", str(report_file), "--receipts", str(receipts_file), "--output", str(out)]) == 4
    _stage_exit4_receipt(capsys)
    assert state["opens"] == 1 and state["proxy"] is not None  # open SUCCEEDED
    assert state["proxy"].writes_ok == 0                       # first write failed
    assert out.exists() and out.stat().st_size == 0            # truncated-empty
    for p, b in before.items():
        assert p.read_bytes() == b


def test_cli_close_time_failure_pinned(tmp_path, capsys, monkeypatch) -> None:
    """Close-time failure: every write succeeded, the context exit raised —
    the destination holds the COMPLETE canonical serialized bytes although
    the run reports exit 4."""
    report_file, receipts_file = _write_artifacts(tmp_path)
    canon = tmp_path / "canonical.out"
    assert main(["--report", str(report_file), "--receipts", str(receipts_file), "--output", str(canon)]) == 0          # capture canonical success bytes
    capsys.readouterr()
    canonical = canon.read_bytes()
    out = tmp_path / "stage_pin.out"
    before = {p: p.read_bytes() for p in [report_file, receipts_file]}
    state = _patch_output_stage(monkeypatch, out.resolve(), fail_close=True)
    assert main(["--report", str(report_file), "--receipts", str(receipts_file), "--output", str(out)]) == 4
    _stage_exit4_receipt(capsys)
    assert state["opens"] == 1 and state["proxy"] is not None
    assert state["proxy"].writes_ok == 1                       # whole buffer written
    assert state["proxy"].close_attempted                      # failure was AT close
    assert out.read_bytes() == canonical                       # complete bytes present
    for p, b in before.items():
        assert p.read_bytes() == b
