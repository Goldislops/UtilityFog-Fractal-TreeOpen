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


# ---------------------------------------------------------------------------
# NP2 corrections (delta audit): exact-type guards, required prev_seen,
# windowed drift, canonical tie-break equivalence, gated ECE simplification,
# inherited NP1 reader behavior, abstention-only outcomes.
# ---------------------------------------------------------------------------


class _IntSubclass(int):
    pass


def test_config_min_history_and_window_must_be_exact_builtin_ints() -> None:
    # Correction A: bool, float and numeric subclasses are rejected even
    # when their numeric value sits inside the documented range.
    for bad in (True, 30.0, _IntSubclass(30)):
        with pytest.raises(ValueError):
            MonitorConfig(min_history=bad).validate()
    for bad in (True, 50.0, _IntSubclass(50)):
        with pytest.raises(ValueError):
            MonitorConfig(window=bad).validate()
    MonitorConfig(min_history=30, window=50).validate()  # exact ints still fine


def test_numeric_subclasses_rejected_without_invoking_conversion_hooks() -> None:
    # Correction B: only exact builtin int/float are supported observation
    # numbers; custom subclasses are rejected through MonitorInputError
    # BEFORE any conversion hook (__float__/__index__) can run.
    hook_calls: list[str] = []

    class _HookedFloat(float):
        def __float__(self) -> float:
            hook_calls.append("float.__float__")
            return 0.5

    class _HookedInt(int):
        def __float__(self) -> float:
            hook_calls.append("int.__float__")
            return 0.5

        def __index__(self) -> int:
            hook_calls.append("int.__index__")
            return 0

    for bad in (_HookedFloat(0.5), _HookedInt(0)):
        for field in ("confidence", "p_actual"):
            with pytest.raises(MonitorInputError):
                validate_observations([{**_ob(0.5, True, 0.5), field: bad}])
    assert hook_calls == []  # rejection happened before conversion


def test_missing_prev_seen_fails_closed_and_never_defaults_to_true() -> None:
    # Correction C: prev_seen is REQUIRED; a missing value must not be
    # silently defaulted to True (that would mask unseen_state abstention).
    record = {"confidence": 0.9, "hit": True, "p_actual": 0.9}  # no prev_seen
    with pytest.raises(MonitorInputError):
        validate_observations([record])
    for bad in (None, 1, 0, "true"):
        with pytest.raises(MonitorInputError):
            validate_observations([{**_ob(0.9, True, 0.9), "prev_seen": bad}])


def test_recent_counts_use_exactly_the_latest_window_observations(tmp_path) -> None:
    # Correction D: 60 train + 20 holdout; the older half of the holdout
    # continues the training regime, the last `window`=10 observations are
    # a hard regime change to all-B. Whole-holdout counting dilutes the
    # shift below the drift threshold; windowed counting must not.
    tokens = [A, B] * 30 + [A, B] * 5 + [B] * 10
    log = _write_log(tmp_path, tokens)
    obs, reference, recent = observations_from_log(
        log, "persistence", smoothing=0.01, window=10
    )
    assert reference == {A: 30, B: 30}
    assert recent == {B: 10}  # exactly the latest window, not {A: 5, B: 15}

    # Expected drift derived independently of the bridge: hand-built count
    # dicts through the shared metric, cross-checked against the hand
    # calculation JS((.5,.5),(0,1)) = 1 - 0.75*log2(3) + 0.5*log2(2) ~ 0.3113.
    from scripts.nextness_metrics import js_divergence

    expected_drift = js_divergence({A: 30, B: 30}, {B: 10})
    diluted_drift = js_divergence({A: 30, B: 30}, {A: 5, B: 15})
    assert expected_drift == pytest.approx(0.3113, abs=2e-3)
    assert diluted_drift < 0.15 < expected_drift  # dilution hid the shift

    receipt = build_receipt(
        model="persistence",
        observations=obs,
        reference_counts=reference,
        recent_counts=recent,
        config=MonitorConfig(min_history=10, window=10),
    )
    assert receipt["distribution_drift_bits"] == round(expected_drift, 6)
    assert receipt["abstain"] is True
    assert receipt["abstain_reason"] == "distribution_shift"


def test_default_window_bounds_recent_counts(tmp_path) -> None:
    # Correction D at the default window: holdout 100 > window 50 must
    # yield exactly 50 recent counts, not the entire holdout.
    log = _write_log(tmp_path, [A, B] * 150 + [B] * 100)
    _obs, reference, recent = observations_from_log(log, "persistence")
    assert sum(reference.values()) == 300
    assert recent == {B: 50}


def test_bridge_window_must_be_exact_builtin_int_in_bounds(tmp_path) -> None:
    log = _write_log(tmp_path, [A, B] * 8)
    for bad in (True, 10.0, _IntSubclass(10), 4, 10_001):
        with pytest.raises(ValueError):
            observations_from_log(log, "persistence", window=bad)


def test_canonical_top_matches_legacy_token_names_index_tie_break() -> None:
    # Correction E equivalence proof: TOKEN_INDEX tie-breaking selects the
    # same token as the legacy TOKEN_NAMES.index expression on uniform,
    # pairwise-tied and coarsely-quantized (tie-rich) distributions.
    from scripts.nextness_monitor import canonical_top

    dists = [{t: 1.0 / len(TOKEN_NAMES) for t in TOKEN_NAMES}]
    for i in range(len(TOKEN_NAMES)):
        for j in range(i + 1, len(TOKEN_NAMES)):
            d = {t: 0.01 for t in TOKEN_NAMES}
            d[TOKEN_NAMES[i]] = 0.4
            d[TOKEN_NAMES[j]] = 0.4
            dists.append(d)
    rng = random.Random(4242)
    for _ in range(500):
        dists.append({t: round(rng.random() * 5) / 5.0 for t in TOKEN_NAMES})
    for d in dists:
        legacy = max(TOKEN_NAMES, key=lambda t: (d[t], -TOKEN_NAMES.index(t)))
        assert canonical_top(d) == legacy


def _rolling_ece_reference(observations) -> float:
    # The pre-simplification form, kept VERBATIM as the equivalence oracle
    # for correction F: (count/n) * |conf/count - acc/count| per bin.
    from scripts.nextness_predictor import ECE_BINS

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
            ece += (bin_count[b] / n) * abs(
                bin_conf[b] / bin_count[b] - bin_acc[b] / bin_count[b]
            )
    return ece


def test_ece_simplification_equivalent_on_boundary_and_seeded_fixtures() -> None:
    # Correction F gate: exact bin-boundary confidences (0.0, 0.1, ..., 1.0),
    # the recorded exact fixture, degenerate cases and seeded traces must
    # agree with the pre-simplification form to 1e-12 AND serialize
    # identically after the receipt's fixed 6-decimal rounding.
    fixtures = [
        [_ob(round(k * 0.1, 1), k % 2 == 0, 0.5) for k in range(11)],
        [_ob(0.85, True, 0.85), _ob(0.85, False, 0.1)],
        [],
        [_ob(1.0, True, 1.0)] * 7,
        [_ob(0.0, False, 0.0)] * 3,
    ]
    for seed in (7, 77, 777, 4242):
        rng = random.Random(seed)
        fixtures.append(
            [_ob(rng.random(), rng.random() < 0.5, rng.random()) for _ in range(97)]
        )
    for obs in fixtures:
        simplified = rolling_ece(obs)
        reference = _rolling_ece_reference(obs)
        assert simplified == pytest.approx(reference, abs=1e-12)
        assert round(simplified, 6) == round(reference, 6)


def test_blank_records_consume_raw_row_budget_through_the_bridge(tmp_path) -> None:
    # Inherited NP1 reader contract: blank records are neither observations
    # nor violations, but they consume max_rows budget (bounded raw work).
    rows = [
        json.dumps({"generation": i, "token_counts": {(A if i % 2 == 0 else B): 3}})
        for i in range(40)
    ]
    log = tmp_path / "nextness_runs.jsonl"
    log.write_text("\n\n\n" + "\n".join(rows) + "\n", encoding="utf-8")
    obs, reference, recent = observations_from_log(log, "persistence", max_rows=40)
    # 3 blanks + 37 data rows fit the budget: split floor(37*0.75)=27/10.
    assert sum(reference.values()) == 27
    assert len(obs) == 10


def test_oversized_record_stops_ingestion_through_the_bridge(tmp_path) -> None:
    # Inherited NP1 reader contract: the first oversized record is counted
    # and TERMINATES ingestion with bounded reads (fail closed) — rows
    # after it never become observations.
    rows = [
        json.dumps({"generation": i, "token_counts": {(A if i % 2 == 0 else B): 3}})
        for i in range(30)
    ]
    big = json.dumps({"generation": 98, "token_counts": {A: 3}, "pad": "x" * 5000})
    log = tmp_path / "nextness_runs.jsonl"
    log.write_text(
        "\n".join(rows[:20]) + "\n" + big + "\n" + "\n".join(rows[20:]) + "\n",
        encoding="utf-8",
    )
    obs, reference, recent = observations_from_log(
        log, "persistence", max_line_bytes=256
    )
    # Exactly the 20 pre-oversize rows: split floor(20*0.75)=15/5.
    assert sum(reference.values()) == 15
    assert len(obs) == 5


def test_invalid_inherited_predictor_options_fail_closed(tmp_path) -> None:
    # Inherited NP1 option bounds must hold on the bridge too — never
    # silently produce distributions from out-of-bounds smoothing or a
    # degenerate holdout fraction.
    log = _write_log(tmp_path, [A, B] * 30)
    for kwargs in (
        {"smoothing": -1.0},
        {"smoothing": 0.0},
        {"smoothing": 1e9},
        {"holdout_fraction": 0.01},
        {"holdout_fraction": 0.9},
    ):
        with pytest.raises(ValueError):
            observations_from_log(log, "first_order", **kwargs)


def test_cli_invalid_options_exit_concisely_and_write_nothing(tmp_path, capsys) -> None:
    # Inherited expected-failure CLI contract: concise `error:` line on
    # stderr, exit 2, no traceback, no files written.
    log = _write_log(tmp_path, [A, B] * 30)
    before = sorted(p.name for p in tmp_path.iterdir())
    assert main([str(log), "--smoothing", "-1"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "Traceback" not in err
    assert main([str(log), "--holdout-fraction", "0.9"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "Traceback" not in err
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_rejected_evidence_yields_typed_failure_or_documented_abstention() -> None:
    # Abstention contract: rejected predictor evidence is a typed input
    # failure (no receipt at all); insufficient evidence is a documented
    # abstention receipt whose fields stay inside the closed allowlist —
    # never an action, tuning, orchestration or write signal.
    with pytest.raises(MonitorInputError):
        _receipt([{**_ob(0.5, True, 0.5), "p_actual": float("nan")}])
    receipt = _receipt([_ob(0.9, True, 0.9)] * 3)
    assert receipt["abstain"] is True
    assert receipt["abstain_reason"] == "insufficient_history"
    assert set(receipt) == {
        "schema", "model", "observation_count", "mean_confidence",
        "mean_surprise_bits", "rolling_calibration_error",
        "distribution_drift_bits", "sufficiency", "abstain",
        "abstain_reason", "input_reduced", "discarded_field_count",
        "config", "non_claim",
    }


# ---------------------------------------------------------------------------
# Cross-module CLI failure-contract pins (Candidate C; see
# docs/NEXTNESS_CLI_FAILURE_CONTRACTS.md). Pins of ESTABLISHED behavior:
# argparse usage lane (SystemExit(2), multi-line usage:, outside main()'s
# return path);
# unexpected-error propagation stays loud
# ---------------------------------------------------------------------------


def test_cli_argparse_usage_error_exits_2(tmp_path, capsys) -> None:
    log = _write_log(tmp_path, [A, B] * 30)
    before = log.read_bytes()
    with pytest.raises(SystemExit) as excinfo:
        main([str(log), "--model", "nope"])
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "usage:" in err
    assert "Traceback" not in err
    assert log.read_bytes() == before


def test_cli_unexpected_errors_are_not_hidden(tmp_path, monkeypatch) -> None:
    import scripts.nextness_monitor as monitor_module

    log = _write_log(tmp_path, [A, B] * 30)

    def boom(*args, **kwargs):
        raise RuntimeError("sentinel propagation probe")

    monkeypatch.setattr(monitor_module, "build_receipt", boom)
    with pytest.raises(RuntimeError, match="sentinel propagation probe"):
        main([str(log)])


# ---------------------------------------------------------------------------
# Monitor typed-input-boundary pilot (gated; docs/NEXTNESS_CLI_FAILURE_CONTRACTS.md).
# Failing-first target: a sentinel plain ValueError escaping the
# post-validation monitor core must PROPAGATE, never convert to the
# documented exit-2 input lane. Preservation controls pin the exact
# public behavior of every genuine lane, byte-for-byte.
# ---------------------------------------------------------------------------


def test_cli_internal_plain_valueerror_propagates(tmp_path, monkeypatch) -> None:
    """Pilot pin: an internal plain ValueError from the post-validation
    core (decide_abstention) is an unexpected programming error and must
    propagate — not masquerade as a concise exit-2 input failure."""
    import scripts.nextness_monitor as monitor_module

    log = _write_log(tmp_path, [A, B] * 30)
    before = log.read_bytes()

    def boom(*args, **kwargs):
        raise ValueError("sentinel plain ValueError probe")

    monkeypatch.setattr(monitor_module, "decide_abstention", boom)
    with pytest.raises(ValueError, match="sentinel plain ValueError probe"):
        main([str(log)])
    assert log.read_bytes() == before


def test_cli_monitor_input_error_still_exit_2(tmp_path, monkeypatch, capsys) -> None:
    """Typed MonitorInputError remains the documented exit-2 lane: one
    concise error: line, no traceback, supplied input untouched."""
    import scripts.nextness_monitor as monitor_module

    log = _write_log(tmp_path, [A, B] * 30)
    before = log.read_bytes()

    def typed_boom(*args, **kwargs):
        raise MonitorInputError("sentinel typed input failure")

    monkeypatch.setattr(monitor_module, "observations_from_log", typed_boom)
    assert main([str(log)]) == 2
    err = capsys.readouterr().err
    lines = [l for l in err.strip().splitlines() if l.strip()]
    assert lines == ["error: sentinel typed input failure"]
    assert "Traceback" not in err
    assert log.read_bytes() == before


def test_cli_smoothing_and_holdout_bounds_exact_public_behavior(tmp_path, capsys) -> None:
    """The two reclassified validation lanes keep their public behavior
    byte-for-byte: exact message, single stderr line, exit 2, no
    traceback, input untouched."""
    log = _write_log(tmp_path, [A, B] * 30)
    before = log.read_bytes()
    for argv, expected in (
        ([str(log), "--smoothing", "0.0"],
         "error: smoothing must be in (0, 1000.0], got 0.0"),
        ([str(log), "--holdout-fraction", "0.9"],
         "error: holdout_fraction must be in [0.05, 0.5], got 0.9"),
    ):
        assert main(argv) == 2
        err = capsys.readouterr().err
        lines = [l for l in err.strip().splitlines() if l.strip()]
        assert lines == [expected]
        assert "Traceback" not in err
    assert log.read_bytes() == before


def test_cli_insufficient_history_still_exit_3(tmp_path, capsys) -> None:
    """InsufficientHistoryError keeps its own exit-3 clause: one concise
    error: line, no traceback, input untouched."""
    log = _write_log(tmp_path, [A])
    before = log.read_bytes()
    assert main([str(log)]) == 3
    err = capsys.readouterr().err
    lines = [l for l in err.strip().splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("error:")
    assert "Traceback" not in err
    assert log.read_bytes() == before


# ---------------------------------------------------------------------------
# Read-side propagation pin (commits the post-train audit's probe-only
# claim): an argument-conditional read-side PermissionError on the
# primary input propagates unchanged through public main() — exact
# identity and message, no concise stderr conversion, inputs
# byte-identical, no destination created. The patch matches ONLY the
# resolved victim path in a read mode, so output-write lanes are never
# accidentally exercised.
# ---------------------------------------------------------------------------


def test_cli_read_side_oserror_propagates(tmp_path, monkeypatch, capsys) -> None:
    log = _write_log(tmp_path, [A, B] * 30)
    inputs = [log]
    before = {p: p.read_bytes() for p in inputs}
    victim = log.resolve()
    real_open = pathlib.Path.open

    def patched(self, mode="r", *args, **kwargs):
        if "r" in mode and "w" not in mode and self.resolve() == victim:
            raise PermissionError(13, "injected read denial")
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "open", patched)
    with pytest.raises(PermissionError) as excinfo:
        main([str(log)])
    monkeypatch.undo()
    assert "injected read denial" in str(excinfo.value)
    assert type(excinfo.value) is PermissionError
    err = capsys.readouterr().err
    assert err == ""  # no misleading concise conversion
    for p, b in before.items():
        assert p.read_bytes() == b
