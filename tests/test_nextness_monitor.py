"""NP2: metacognitive calibration receipt — contract + adversarial tests."""

from __future__ import annotations

import json
import math
import pathlib
import random

import pytest

from scripts.nextness_observer import TOKEN_NAMES
from scripts.nextness_monitor import (
    ABSTAIN_REASONS,
    MAX_RECEIPT_BYTES,
    MODEL_ALLOWLIST,
    RECEIPT_SCHEMA,
    MonitorConfig,
    MonitorInputError,
    build_receipt,
    decide_abstention,
    main,
    observations_from_log,
    rolling_ece,
    serialize_receipt,
    surprise_bits,
    validate_observations,
)

A = "void_static"
B = "compute_static"


def _ob(confidence: float, hit: bool, p_actual: float, prev_seen: bool = True) -> dict:
    return {"confidence": confidence, "hit": hit, "p_actual": p_actual, "prev_seen": prev_seen}


def _receipt(observations, *, model="first_order", reference=None, recent=None, config=None):
    return build_receipt(
        model=model,
        observations=observations,
        reference_counts=reference if reference is not None else {A: 10, B: 10},
        recent_counts=recent if recent is not None else {A: 5, B: 5},
        config=config,
    )


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
# Regression scenarios (the six named regimes)
# ---------------------------------------------------------------------------


def test_calibrated_regime_does_not_abstain(tmp_path) -> None:
    # Perfect alternation with LIGHT smoothing: first_order is confident
    # (~0.995), right, calibrated, and train/holdout distributions match
    # -> abstain=false, reason none.
    log = _write_log(tmp_path, [A, B] * 30)
    observations, reference, recent = observations_from_log(
        log, "first_order", smoothing=0.01
    )
    receipt = _receipt(observations, reference=reference, recent=recent,
                       config=MonitorConfig(min_history=10))
    assert receipt["abstain"] is False
    assert receipt["abstain_reason"] == "none"
    assert receipt["sufficiency"] == "sufficient"


def test_monitor_detects_np1_default_smoothing_underconfidence(tmp_path) -> None:
    # FINDING (kept deliberately): with NP1's default Laplace alpha=1.0
    # over 16 tokens, a perfect alternation predictor STATES ~0.605
    # confidence while ACHIEVING 1.0 accuracy — systematically
    # under-confident, and the monitor honestly reports that gap as
    # calibration drift. Metacognition catching its own predictor's
    # smoothing bias is exactly the receipt this package exists to give.
    log = _write_log(tmp_path, [A, B] * 30)
    observations, reference, recent = observations_from_log(log, "first_order")
    receipt = _receipt(observations, reference=reference, recent=recent,
                       config=MonitorConfig(min_history=10))
    assert receipt["abstain"] is True
    assert receipt["abstain_reason"] == "calibration_drift"
    assert receipt["mean_confidence"] < 0.7
    assert receipt["rolling_calibration_error"] > 0.3


def test_under_confident_regime_abstains_on_low_confidence() -> None:
    # Confidence sits below the threshold while accuracy is fine.
    obs = [_ob(0.2, True, 0.2) for _ in range(40)]
    receipt = _receipt(obs, config=MonitorConfig(min_history=10))
    assert receipt["abstain"] is True
    assert receipt["abstain_reason"] == "low_confidence"


def test_over_confident_regime_abstains_on_calibration_drift() -> None:
    # Confident (0.9) but wrong half the time: rolling ECE ~= 0.4+ .
    obs = [_ob(0.9, i % 2 == 0, 0.45) for i in range(40)]
    receipt = _receipt(obs, config=MonitorConfig(min_history=10))
    assert receipt["abstain"] is True
    assert receipt["abstain_reason"] == "calibration_drift"
    assert receipt["rolling_calibration_error"] > 0.2


def test_shifted_regime_abstains_on_distribution_drift() -> None:
    # Healthy predictions, but the recent window's token mix diverges
    # hard from the training reference -> distribution_shift.
    obs = [_ob(0.8, True, 0.8) for _ in range(40)]
    receipt = _receipt(
        obs,
        reference={A: 30},
        recent={B: 30},
        config=MonitorConfig(min_history=10),
    )
    assert receipt["abstain"] is True
    assert receipt["abstain_reason"] == "distribution_shift"
    assert receipt["distribution_drift_bits"] > 0.15


def test_unseen_state_abstains(tmp_path) -> None:
    # The latest previous token was never a training transition source.
    obs = [_ob(0.8, True, 0.8) for _ in range(39)] + [_ob(0.8, False, 0.05, prev_seen=False)]
    receipt = _receipt(obs, config=MonitorConfig(min_history=10))
    assert receipt["abstain"] is True
    assert receipt["abstain_reason"] == "unseen_state"


def test_insufficient_history_abstains_first() -> None:
    obs = [_ob(0.9, True, 0.9) for _ in range(5)]
    receipt = _receipt(obs)  # default min_history=30
    assert receipt["abstain"] is True
    assert receipt["abstain_reason"] == "insufficient_history"
    assert receipt["sufficiency"] == "insufficient"


def test_abstention_precedence_is_fixed() -> None:
    # All triggers simultaneously true -> the FIRST in precedence wins.
    abstain, reason = decide_abstention(
        observation_count=1,               # insufficient
        latest_confidence=0.01,            # low confidence too
        latest_prev_seen=False,            # unseen too
        rolling_calibration_error=0.9,     # drifted too
        drift_bits=0.9,                    # shifted too
        config=MonitorConfig(),
    )
    assert (abstain, reason) == (True, "insufficient_history")
    assert list(ABSTAIN_REASONS)[0] == "insufficient_history"
    assert list(ABSTAIN_REASONS)[-1] == "none"


# ---------------------------------------------------------------------------
# Container guards / adversarial input
# ---------------------------------------------------------------------------


class _HostileStr:
    def __str__(self) -> str:  # pragma: no cover - must never be called
        raise RuntimeError("hostile __str__ escaped into the receipt path")


class _DictSubclass(dict):
    pass


def test_non_builtin_dict_observations_fail_closed() -> None:
    with pytest.raises(MonitorInputError):
        validate_observations([_DictSubclass(_ob(0.5, True, 0.5))])
    with pytest.raises(MonitorInputError):
        validate_observations(["not a dict"])


def test_hostile_values_fail_closed_before_any_stringification() -> None:
    for bad in (_HostileStr(), float("nan"), float("inf"), 10**400, True, "0.5"):
        with pytest.raises(MonitorInputError):
            validate_observations([{**_ob(0.5, True, 0.5), "confidence": bad}])
    with pytest.raises(MonitorInputError):
        validate_observations([{**_ob(0.5, True, 0.5), "hit": 1}])  # int, not bool


def test_out_of_range_probabilities_fail_closed() -> None:
    for bad in (-0.1, 1.5):
        with pytest.raises(MonitorInputError):
            validate_observations([_ob(bad, True, 0.5)])
        with pytest.raises(MonitorInputError):
            validate_observations([_ob(0.5, True, bad)])


def test_unknown_fields_are_discarded_and_honestly_flagged() -> None:
    obs = [{**_ob(0.9, True, 0.9), "monologue": "should never survive", "extra": 1}
           for _ in range(35)]
    receipt = _receipt(obs, config=MonitorConfig(min_history=10))
    assert receipt["input_reduced"] is True
    assert receipt["discarded_field_count"] == 70
    assert "monologue" not in serialize_receipt(receipt)
    assert "should never survive" not in serialize_receipt(receipt)


def test_model_and_count_allowlists_fail_closed() -> None:
    obs = [_ob(0.9, True, 0.9)]
    with pytest.raises(MonitorInputError):
        _receipt(obs, model="clever_new_model")
    with pytest.raises(MonitorInputError):
        _receipt(obs, reference={"not_a_token": 3})
    with pytest.raises(MonitorInputError):
        _receipt(obs, recent={A: True})
    with pytest.raises(MonitorInputError):
        _receipt(obs, recent={A: -1})
    assert set(MODEL_ALLOWLIST) == {"empirical_prior", "persistence", "first_order"}


def test_config_bounds_fail_closed() -> None:
    with pytest.raises(ValueError):
        MonitorConfig(min_history=1).validate()
    with pytest.raises(ValueError):
        MonitorConfig(window=100_000).validate()
    with pytest.raises(ValueError):
        MonitorConfig(low_confidence_threshold=1.0).validate()


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------


def test_surprise_is_bounded_against_underflow() -> None:
    assert surprise_bits(0.0) == 1_000.0
    assert surprise_bits(0.5) == pytest.approx(1.0)
    assert surprise_bits(1.0) == pytest.approx(0.0)


def test_rolling_ece_exact_fixture() -> None:
    # Two observations at confidence 0.85 (bin 8), one hit one miss:
    # ECE = |0.85 - 0.5| = 0.35 exactly.
    obs = [_ob(0.85, True, 0.85), _ob(0.85, False, 0.1)]
    assert rolling_ece(obs) == pytest.approx(0.35, rel=1e-12)


# ---------------------------------------------------------------------------
# Receipt hygiene, determinism, bounds
# ---------------------------------------------------------------------------


def test_receipt_is_deterministic_and_canonical() -> None:
    obs = [_ob(0.7, True, 0.7) for _ in range(35)]
    first = serialize_receipt(_receipt(obs, config=MonitorConfig(min_history=10)))
    second = serialize_receipt(_receipt(obs, config=MonitorConfig(min_history=10)))
    assert first == second
    assert first == json.dumps(
        json.loads(first), sort_keys=True, separators=(",", ": "), indent=1
    ) + "\n"
    assert '"ts"' not in first
    assert len(first.encode("utf-8")) <= MAX_RECEIPT_BYTES


def test_receipt_fields_are_exactly_the_allowlisted_set() -> None:
    obs = [_ob(0.7, True, 0.7) for _ in range(35)]
    receipt = _receipt(obs, config=MonitorConfig(min_history=10))
    assert set(receipt) == {
        "schema", "model", "observation_count", "mean_confidence",
        "mean_surprise_bits", "rolling_calibration_error",
        "distribution_drift_bits", "sufficiency", "abstain",
        "abstain_reason", "input_reduced", "discarded_field_count",
        "config", "non_claim",
    }
    assert receipt["schema"] == RECEIPT_SCHEMA
    assert receipt["abstain_reason"] in ABSTAIN_REASONS
    assert "awareness" in receipt["non_claim"]  # the non-claim is embedded


# ---------------------------------------------------------------------------
# Property-style seeded traces (stdlib random only — no new dependency)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [7, 77, 777])
def test_seeded_trace_receipts_are_bounded_and_deterministic(seed: int, tmp_path) -> None:
    rng = random.Random(seed)
    tokens = [rng.choice([A, B, "energy_pulse", "sensor_alert"]) for _ in range(120)]
    log = _write_log(tmp_path, tokens)
    for model in MODEL_ALLOWLIST:
        obs, reference, recent = observations_from_log(log, model)
        r1 = build_receipt(model=model, observations=obs,
                           reference_counts=reference, recent_counts=recent)
        r2 = build_receipt(model=model, observations=obs,
                           reference_counts=reference, recent_counts=recent)
        assert serialize_receipt(r1) == serialize_receipt(r2)
        assert r1["abstain_reason"] in ABSTAIN_REASONS
        assert 0.0 <= r1["mean_confidence"] <= 1.0
        assert 0.0 <= r1["rolling_calibration_error"] <= 1.0
        assert 0.0 <= r1["distribution_drift_bits"] <= 1.0 + 1e-9
        assert math.isfinite(r1["mean_surprise_bits"])
        assert len(serialize_receipt(r1).encode("utf-8")) <= MAX_RECEIPT_BYTES


# ---------------------------------------------------------------------------
# NP1 bridge + CLI
# ---------------------------------------------------------------------------


def test_bridge_replays_np1_split_without_new_semantics(tmp_path) -> None:
    log = _write_log(tmp_path, [A, B] * 8)  # 16 rows -> split 12/4
    obs, reference, recent = observations_from_log(log, "first_order")
    assert len(obs) == 4
    assert sum(reference.values()) == 12
    assert sum(recent.values()) == 4
    assert all(set(ob) == {"confidence", "hit", "p_actual", "prev_seen"} for ob in obs)


def test_bridge_insufficient_history_fails_closed(tmp_path) -> None:
    from scripts.nextness_predictor import InsufficientHistoryError
    log = _write_log(tmp_path, [A])
    with pytest.raises(InsufficientHistoryError):
        observations_from_log(log, "persistence")


def test_cli_emits_receipt_to_stdout_only(tmp_path, capsys) -> None:
    log = _write_log(tmp_path, [A, B] * 30)
    before = sorted(p.name for p in tmp_path.iterdir())
    assert main([str(log), "--model", "first_order"]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["schema"] == RECEIPT_SCHEMA
    after = sorted(p.name for p in tmp_path.iterdir())
    assert before == after  # the monitor writes NO files


def test_cli_exit_codes(tmp_path) -> None:
    assert main([str(tmp_path / "absent.jsonl")]) == 2
    log = _write_log(tmp_path, [A])
    assert main([str(log)]) == 3
