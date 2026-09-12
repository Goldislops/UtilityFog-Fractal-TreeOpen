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
    assert type(excinfo.value) is PermissionError
    assert excinfo.value.errno == 13
    assert excinfo.value.strerror == "injected read denial"
    captured = capsys.readouterr()
    assert captured.out == ""  # the CLI emitted nothing
    assert captured.err == ""  # no misleading concise conversion
    for p, b in before.items():
        assert p.read_bytes() == b


# ---------------------------------------------------------------------------
# Decode-boundary RecursionError, and real deep input: two subjects, two
# mechanisms.
#
# The seam tests inject a RecursionError AT the decode boundary
# deterministically, so the decoder-originated rejection contract is pinned
# the same way wherever the suite runs: such a row follows the reader's
# EXISTING malformed-row containment policy — counted, the run continues —
# and never crashes with a traceback.
#
# The separate fixed-depth fixture is fed to the REAL decoder, exercising
# genuine decoding and whichever rejection/containment path then applies.
# That fixture is NOT guaranteed to exhaust every decoder, so its test pins
# only what holds whichever disposition fires.
# ---------------------------------------------------------------------------

#: Marker carried by the deep-nesting fixture so the decoder seam below can
#: recognise exactly that record and no other.
_DEEP_NEST_MARKER = "DEEP-NEST-PROBE"

#: A genuinely deep record: 20 000 nested arrays, ~40 KiB, comfortably inside
#: the 65 536-byte default ``max_line_bytes`` ceiling, so the byte ceilings
#: never pre-empt the decode and the record does reach ``json.loads``.
#: It serves two different subjects: the seam tests mark it and inject the
#: decoder exception deterministically, while the real-decoder totality test
#: feeds these same bytes to the ACTUAL parser and pins only what every
#: interpreter agrees on. The nesting is therefore load-bearing, not
#: decoration.
_DEEP_NEST_ROW = ('{"generation": 1, "probe": "' + _DEEP_NEST_MARKER
                  + '", "token_counts": {"void_static": '
                  + "[" * 20000 + "]" * 20000 + '}}')


class _DecodeSeam:
    """Deterministic, marker-scoped seam over the shared ``json`` decoder.

    Whether a payload of some fixed nesting depth exhausts the decoder is a
    property of the environment the suite runs in, not of this repository.
    Measured on this fixture (``_DEEP_NEST_ROW``: 20 000 nested arrays,
    ~40 KiB) on 2026-09-09: Windows CPython 3.12.14 [MSC v.1944] raised
    ``RecursionError`` from ``json.loads``, while Linux CPython 3.14.4
    [GCC 15.2.0] decoded the identical bytes successfully, after which the
    record fell through to an unrelated domain-validation rejection. Those
    two environments differ in interpreter version, operating system, C
    compiler, build configuration and stack layout simultaneously, so the
    difference is NOT attributable to interpreter version alone, and OS,
    build, compiler and stack effects are not ruled out. Nothing is claimed
    here about any other depth, payload or environment.

    A fixed nesting depth is therefore not a dependable cross-environment
    trigger for the decode-boundary ``RecursionError`` contract. This seam
    supplies that exception deterministically instead, so the contract is
    pinned the same way wherever the suite runs, while a separate fixed-input
    test feeds these same bytes to the REAL decoder and asserts only what
    holds whichever disposition fires — so genuine decoding and the
    containment plumbing stay exercised.

    SCOPE WARNING: ``module.json`` is the ONE process-wide ``json`` module.
    Installing this seam replaces ``json.loads`` for every caller in the
    process, not just for ``module``; the ``module`` argument names the
    consumer under test, it does not narrow the patch. Safety rests on the
    marker instead: every unmarked call is delegated to the real decoder with
    its positional and keyword arguments forwarded unchanged, and each test
    calls ``restore()`` BEFORE parsing its own output — that ordering is
    load-bearing, not incidental.

    Restoration is exact: the previous ``json.loads`` is put back without
    disturbing any other ``monkeypatch`` made by the same test, and
    ``monkeypatch`` still owns the fallback, so the decoder is restored even
    when the test body raises before ``restore()`` is reached.
    """

    def __init__(self, marker: str, message: str) -> None:
        self.marker = marker
        self.message = message
        self.raised = 0                                # sentinels raised
        self.marked: list[tuple[tuple, dict]] = []     # marked calls
        self.delegated: list[tuple[tuple, dict]] = []  # pass-through calls

    def install(self, monkeypatch, module) -> "_DecodeSeam":
        self._monkeypatch = monkeypatch
        self._module = module
        real = module.json.loads
        self._real = real

        def patched(s, *args, **kwargs):
            if type(s) is str and self.marker in s:
                self.marked.append((args, dict(kwargs)))
                self.raised += 1
                raise RecursionError(self.message)
            self.delegated.append((args, dict(kwargs)))
            return real(s, *args, **kwargs)

        monkeypatch.setattr(module.json, "loads", patched)
        assert module.json.loads is patched      # the seam is actually armed
        return self

    def restore(self) -> None:
        """Put the real decoder back, exactly, and prove it is back."""
        self._monkeypatch.setattr(self._module.json, "loads", self._real)
        assert self._module.json.loads is self._real


class _ReaderRecorder:
    """Pass-through recorder over the reader boundary the monitor already
    calls.

    It invokes the REAL reader, forwards its arguments unchanged, returns
    its result unchanged, and records what happened as a side effect. It
    classifies nothing, counts nothing of its own, and cannot manufacture a
    result: every value asserted against below is a value the real reader
    returned.
    """

    def __init__(self, real) -> None:
        self._real = real
        self.calls: list[tuple] = []

    def __call__(self, *args, **kwargs):
        sequence, rejections, rows_read = self._real(*args, **kwargs)
        self.calls.append((args, dict(kwargs), list(sequence),
                           dict(rejections), rows_read))
        return sequence, rejections, rows_read


def test_cli_decode_recursionerror_row_contained_receipt_unaffected(
    tmp_path, monkeypatch, capsys
) -> None:
    """Inherited reader containment, asserted at the reader boundary AND at
    the monitor's own output surface.

    The monitor discards the shared reader's rejection counters, and the
    fixed receipt shape stays exactly as it is — no production change and no
    new receipt field. The rejection CATEGORY is therefore pinned where it
    is actually produced: a test-local pass-through recorder wraps the
    reader boundary the monitor already calls, so the counters asserted
    below are the ones the unchanged reader really returned.

    That distinction is the point. The receipt is byte-identical whether the
    offending record was contained at the decode boundary or turned away
    later by an unrelated domain-validation rejection, so receipt equality
    alone cannot tell those apart. ``seam.raised == 1`` shows the marked
    decode was reached; the recorded ``malformed_json`` count shows what the
    reader made of it; the recorded sequence and row accounting show that
    every other record survived intact.

    The reference receipt remains the check that processing continued and
    the contained record contributed nothing to the output."""
    import scripts.nextness_monitor as monitor_module
    from scripts.nextness_predictor import REJECT_REASONS

    good_rows = "\n".join(
        json.dumps({"generation": i, "token_counts": {t: 3}})
        for i, t in enumerate([A, B] * 30))
    log = tmp_path / "nest.jsonl"

    # Reference: exactly these good rows, no offending record, no seam.
    log.write_text(good_rows + "\n", encoding="utf-8")
    assert main([str(log)]) == 0
    reference = capsys.readouterr().out
    # Anchor the self-generated reference to absolute facts, so a defect
    # that corrupted BOTH runs identically cannot hide inside the comparison.
    reference_receipt = json.loads(reference)
    assert reference_receipt["schema"] == RECEIPT_SCHEMA
    assert reference_receipt["observation_count"] == 15

    # Record the reader boundary for the seam-armed run only, so the counts
    # below belong to that run and to no other.
    recorder = _ReaderRecorder(monitor_module.read_dominant_sequence)
    monkeypatch.setattr(monitor_module, "read_dominant_sequence", recorder)

    # The same good rows, with the offending record first and the seam armed.
    log.write_text(_DEEP_NEST_ROW + "\n" + good_rows + "\n", encoding="utf-8")
    before = log.read_bytes()
    seam = _DecodeSeam(_DEEP_NEST_MARKER, "sentinel parser depth probe")
    seam.install(monkeypatch, monitor_module)
    assert main([str(log)]) == 0
    seam.restore()
    captured = capsys.readouterr()
    assert seam.raised == 1                    # the marked decode ran, once
    assert len(seam.delegated) == 60           # every good row delegated
    assert all(kw == {} for _a, kw in seam.delegated)   # reader: no kwargs

    # The intended reader invocation happened, exactly once, on this log,
    # with the bounding arguments the monitor is supposed to forward.
    assert len(recorder.calls) == 1
    args, kwargs, sequence, rejections, rows_read = recorder.calls[0]
    assert pathlib.Path(args[0]) == log
    assert set(kwargs) == {"max_rows", "max_line_bytes"}

    # The contained record was counted as malformed_json and as nothing
    # else. The vocabulary is taken from the reader's own contract, so a
    # category renamed or dropped there fails here instead of slipping past.
    assert set(rejections) == set(REJECT_REASONS)
    assert rejections["malformed_json"] == 1
    assert {r: c for r, c in rejections.items() if c} == {"malformed_json": 1}
    assert sum(rejections.values()) == 1

    # Continuation is exact, and it is the RIGHT rows in the RIGHT order —
    # not merely the right tally.
    assert sequence == [A, B] * 30
    assert len(sequence) == 60                 # rows accepted
    assert rows_read == 61                     # physical rows read

    assert "Traceback" not in captured.err
    assert captured.err == ""
    assert captured.out == reference           # contained: receipt unchanged
    assert log.read_bytes() == before


# ---------------------------------------------------------------------------
# Real-decoder totality. The seam tests above pin WHICH rejection a
# decode-boundary RecursionError produces; they cannot exercise the real
# parser, because they raise before it is called. These tests do the
# complement: the same genuinely deep bytes go through the ACTUAL decoder,
# and only interpreter-invariant properties are asserted. Which disposition
# fires is deliberately NOT pinned here — that is the seam tests' subject,
# and pinning it here is exactly the runtime dependence this file removed.
# ---------------------------------------------------------------------------


def test_cli_real_deeply_nested_row_survivable_on_any_decoder(
    tmp_path, capsys
) -> None:
    """NO seam: the genuine 20 000-deep, ~40 KiB record is fed to the real
    parser ahead of the good rows.

    Invariant on every interpreter, and all this test claims: the record
    never reaches the receipt — which is byte-identical to the receipt for
    the same log without it — exit 0, no traceback, input byte-unchanged."""
    good_rows = "\n".join(
        json.dumps({"generation": i, "token_counts": {t: 3}})
        for i, t in enumerate([A, B] * 30))
    log = tmp_path / "nest.jsonl"
    log.write_text(good_rows + "\n", encoding="utf-8")
    assert main([str(log)]) == 0
    reference = capsys.readouterr().out
    assert json.loads(reference)["schema"] == RECEIPT_SCHEMA

    log.write_text(_DEEP_NEST_ROW + "\n" + good_rows + "\n", encoding="utf-8")
    before = log.read_bytes()
    assert main([str(log)]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "Traceback" not in captured.err
    assert captured.out == reference
    assert log.read_bytes() == before


def test_post_decode_recursionerror_propagates(
    tmp_path, monkeypatch, capsys
) -> None:
    """Outside-seam pin for the consumer. A sentinel RecursionError raised
    AFTER a successful decode — from the monitor's own distribution builder
    — propagates exactly: no containment, no typed translation, no
    stdout/stderr, input unchanged. This pins ONE post-decode site, which is
    what shows the inherited containment is not broad swallowing; it is not
    by itself a proof of locality at every site."""
    import scripts.nextness_monitor as monitor_module

    log = _write_log(tmp_path, [A, B] * 30)
    before = log.read_bytes()
    real_first_order = monitor_module.first_order_distribution

    def patched(*args, **kwargs):
        raise RecursionError("sentinel post-decode recursion")

    monkeypatch.setattr(monitor_module, "first_order_distribution", patched)
    with pytest.raises(RecursionError) as excinfo:
        main([str(log)])
    monkeypatch.undo()
    assert monitor_module.first_order_distribution is real_first_order
    assert type(excinfo.value) is RecursionError
    assert str(excinfo.value) == "sentinel post-decode recursion"
    captured = capsys.readouterr()
    assert captured.out == ""  # the CLI emitted nothing
    assert captured.err == ""  # no misleading concise conversion
    assert log.read_bytes() == before


def test_direct_reader_use_gets_shared_typed_exception(tmp_path) -> None:
    """Boundary totality: an index-overflowing max_line_bytes through
    the monitor's bridge raises the shared reader's typed
    PredictorInputError — never raw OverflowError (the failing-first
    inherited-overflow lane, inverted)."""
    from scripts.nextness_predictor import PredictorInputError

    log = tmp_path / "nextness_runs.jsonl"
    log.write_text(
        "\n".join(
            json.dumps({"generation": i, "token_counts": {t: 3}})
            for i, t in enumerate([A, B] * 30)
        ) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(PredictorInputError) as excinfo:
        observations_from_log(
            log, "first_order", max_line_bytes=9223372036854775806)
    assert type(excinfo.value) is PredictorInputError
    assert "16777216" in str(excinfo.value)


def test_cli_receipt_ceiling_exit_5_injected(tmp_path, monkeypatch, capsys) -> None:
    """Defensive receipt-ceiling completion (INJECTED: the ceiling is
    lowered — the current fixed public receipt shape cannot naturally
    reach 64 KiB and this test claims NO public reachability): the CLI
    maps build_receipt's fail-closed ReceiptTooLargeError to exactly
    one concise error: line and exit 5; direct build_receipt callers
    still receive the typed exception."""
    import scripts.nextness_monitor as monitor_module
    from scripts.nextness_monitor import ReceiptTooLargeError

    log = tmp_path / "nextness_runs.jsonl"
    log.write_text(
        "\n".join(
            json.dumps({"generation": i, "token_counts": {t: 3}})
            for i, t in enumerate([A, B] * 30)
        ) + "\n",
        encoding="utf-8",
    )
    before = log.read_bytes()
    monkeypatch.setattr(monitor_module, "MAX_RECEIPT_BYTES", 64)
    rc = monitor_module.main([str(log)])
    captured = capsys.readouterr()
    assert rc == 5
    assert captured.out == ""  # nothing oversized is ever emitted
    lines = [l for l in captured.err.strip().splitlines() if l.strip()]
    assert lines == ["error: receipt would exceed 64 bytes; refusing to emit"]
    assert "Traceback" not in captured.err
    assert log.read_bytes() == before

    # Direct build_receipt behavior preserved under the same ceiling.
    observations, reference, recent = monitor_module.observations_from_log(
        log, "first_order", window=monitor_module.MonitorConfig().window)
    with pytest.raises(ReceiptTooLargeError):
        monitor_module.build_receipt(
            model="first_order",
            observations=observations,
            reference_counts=reference,
            recent_counts=recent,
            config=monitor_module.MonitorConfig(),
        )
    monkeypatch.undo()


# ---------------------------------------------------------------------------
# Batch 4 — exact-string field boundary + hook-free diagnostics.
#
# Reachability: the PUBLIC CLI feeds observations parsed from the JSONL log,
# whose object keys are always builtin str, so none of the hazards below are
# CLI-reachable. They are DIRECT-Python-API only — a caller passing records
# built in memory. The repair is defensive totality on that lane.
# ---------------------------------------------------------------------------


_GOOD_OBS = {"confidence": 0.5, "p_actual": 0.5, "hit": True, "prev_seen": True}
_SUBSTITUTE = {"confidence": 0.99, "p_actual": 0.01, "hit": False, "prev_seen": False}
_REQUIRED_FIELDS = ("confidence", "p_actual", "hit", "prev_seen")


class _ObsRaisingMeta(type):
    """Metaclass whose __name__ property raises."""

    ran = False

    @property
    def __name__(cls):
        _ObsRaisingMeta.ran = True
        raise RuntimeError("metaclass __name__ hook executed")


class _ObsMetaBomb(metaclass=_ObsRaisingMeta):
    pass


class _SoftFieldKey:
    """Hash-collides with a field name AND compares equal — used to satisfy
    that field and supply its own value."""

    def __init__(self, target: str) -> None:
        self._h = hash(target)

    def __hash__(self) -> int:
        return self._h

    def __eq__(self, other):
        return True


class _HardFieldKey:
    """Hash-collides with a field name; comparison/representation armed.
    __hash__ is inert until armed so the collision can be planted."""

    fired: list[str] = []
    armed = False

    def __init__(self, target: str) -> None:
        self._h = hash(target)

    def __hash__(self) -> int:
        if _HardFieldKey.armed:
            _HardFieldKey.fired.append("__hash__")
            raise RuntimeError("__hash__ hook executed")
        return self._h

    def __eq__(self, other):
        _HardFieldKey.fired.append("__eq__")
        raise RuntimeError("__eq__ hook executed")

    def __repr__(self):
        _HardFieldKey.fired.append("__repr__")
        raise RuntimeError("__repr__ hook executed")


class _DistinctCollidingKey:
    """Hash-collides with a field name but compares UNEQUAL while disarmed,
    so it coexists with the genuine key instead of merging at construction.

    Once armed, EVERY hook — ``__hash__``, ``__eq__`` and ``__repr__`` —
    records itself and raises, so the validator is held to touching none of
    them. Construction-time observations are cleared before arming.
    """

    fired: list[str] = []
    armed = False

    def __init__(self, target: str) -> None:
        self._h = hash(target)

    def __hash__(self) -> int:
        if _DistinctCollidingKey.armed:
            _DistinctCollidingKey.fired.append("__hash__")
            raise RuntimeError("__hash__ hook executed")
        return self._h

    def __eq__(self, other):
        if _DistinctCollidingKey.armed:
            _DistinctCollidingKey.fired.append("__eq__")
            raise RuntimeError("__eq__ hook executed")
        return False  # distinct from the genuine key while disarmed

    def __repr__(self):
        _DistinctCollidingKey.fired.append("__repr__")
        raise RuntimeError("__repr__ hook executed")


def _obs_arm() -> None:
    _ObsRaisingMeta.ran = False
    _HardFieldKey.fired.clear()
    _HardFieldKey.armed = False
    _DistinctCollidingKey.fired.clear()
    _DistinctCollidingKey.armed = False


def _without(field: str) -> dict:
    return {k: v for k, v in _GOOD_OBS.items() if k != field}


def test_soft_colliding_key_cannot_substitute_any_required_field() -> None:
    """A foreign key colliding with a field name and comparing equal used to
    SATISFY that field and supply the value the receipt is computed from."""
    from scripts.nextness_monitor import MonitorInputError, validate_observations

    expected = {
        "confidence": "observation 0: missing field 'confidence'",
        "p_actual": "observation 0: missing field 'p_actual'",
        "hit": "observation 0: hit must be a builtin bool",
        "prev_seen": "observation 0: missing field 'prev_seen'",
    }
    for field in _REQUIRED_FIELDS:
        record = _without(field)
        record[_SoftFieldKey(field)] = _SUBSTITUTE[field]
        with pytest.raises(MonitorInputError) as excinfo:
            validate_observations([record])
        assert str(excinfo.value) == expected[field], field


def test_hard_colliding_key_runs_no_hook_for_any_required_field() -> None:
    """The record is traversed by item iteration, so a colliding foreign key
    is never hashed, compared or represented by the validator."""
    from scripts.nextness_monitor import MonitorInputError, validate_observations

    for field in _REQUIRED_FIELDS:
        _obs_arm()
        record = _without(field)
        record[_HardFieldKey(field)] = _SUBSTITUTE[field]
        _HardFieldKey.armed = True          # planted; nothing may touch it now
        try:
            with pytest.raises(MonitorInputError):
                validate_observations([record])
            assert _HardFieldKey.fired == [], field
        finally:
            _HardFieldKey.armed = False


def test_absent_required_field_keeps_the_established_refusal() -> None:
    """With no genuine key at all, the established typed refusals stand."""
    from scripts.nextness_monitor import MonitorInputError, validate_observations

    for field, message in (
        ("confidence", "observation 0: missing field 'confidence'"),
        ("p_actual", "observation 0: missing field 'p_actual'"),
        ("hit", "observation 0: hit must be a builtin bool"),
        ("prev_seen", "observation 0: missing field 'prev_seen'"),
    ):
        with pytest.raises(MonitorInputError) as excinfo:
            validate_observations([_without(field)])
        assert str(excinfo.value) == message


def test_genuine_field_wins_beside_a_foreign_colliding_key() -> None:
    """A genuine exact-string field coexisting with a colliding foreign key
    is used; the foreign key is counted once as a discarded field and none
    of its hooks run."""
    from scripts.nextness_monitor import validate_observations

    _obs_arm()
    record = dict(_GOOD_OBS)
    record[_DistinctCollidingKey("confidence")] = 0.99
    assert len(record) == len(_GOOD_OBS) + 1  # genuinely two separate entries

    # Construction is done; drop anything the dict build observed, then arm
    # so that ANY hook the validator might reach records itself and raises.
    _DistinctCollidingKey.fired.clear()
    _DistinctCollidingKey.armed = True
    try:
        observations, discarded = validate_observations([record])
    finally:
        _DistinctCollidingKey.armed = False

    assert observations == [_GOOD_OBS]
    assert observations[0]["confidence"] == 0.5   # genuine value, not 0.99
    assert discarded == 1                          # foreign key counted once
    assert _DistinctCollidingKey.fired == []       # zero hooks fired


def test_hostile_metaclass_never_consulted_by_either_diagnostic() -> None:
    """Both raw type(value).__name__ diagnostics could execute a hostile
    metaclass property from inside error formatting."""
    from scripts.nextness_monitor import (
        MonitorInputError,
        _bounded_float,
        _require_exact_int,
    )

    _obs_arm()
    with pytest.raises(ValueError) as excinfo:
        _require_exact_int("n", _ObsMetaBomb())
    assert str(excinfo.value) == "n must be a builtin int, got non-builtin value"
    assert _ObsRaisingMeta.ran is False

    _obs_arm()
    with pytest.raises(MonitorInputError) as excinfo:
        _bounded_float(_ObsMetaBomb(), "f", 0.0, 1.0)
    assert str(excinfo.value) == "f: expected a builtin real number, got non-builtin value"
    assert _ObsRaisingMeta.ran is False


def test_builtin_diagnostic_messages_are_byte_identical() -> None:
    """Builtin supplied values keep their exact pre-existing messages."""
    from scripts.nextness_monitor import (
        MonitorInputError,
        _bounded_float,
        _require_exact_int,
    )

    for value, name in (("x", "str"), (1.5, "float"), ([], "list"), (None, "NoneType")):
        with pytest.raises(ValueError) as excinfo:
            _require_exact_int("n", value)
        assert str(excinfo.value) == f"n must be a builtin int, got {name}"

    for value, name in (("x", "str"), ([], "list"), (None, "NoneType"), (True, "bool")):
        with pytest.raises(MonitorInputError) as excinfo:
            _bounded_float(value, "f", 0.0, 1.0)
        assert str(excinfo.value) == f"f: expected a builtin real number, got {name}"


def test_describe_type_names_builtins_and_falls_back_generically() -> None:
    from scripts.nextness_monitor import _describe_type

    assert _describe_type(True) == "bool"  # before int
    assert _describe_type(1) == "int"
    assert _describe_type(1.0) == "float"
    assert _describe_type("s") == "str"
    assert _describe_type([]) == "list"
    assert _describe_type({}) == "dict"
    assert _describe_type(()) == "tuple"
    assert _describe_type(set()) == "set"
    assert _describe_type(b"") == "bytes"
    assert _describe_type(None) == "NoneType"

    class _IntSub(int):
        pass

    assert _describe_type(_IntSub(1)) == "non-builtin value"
    _obs_arm()
    assert _describe_type(_ObsMetaBomb()) == "non-builtin value"
    assert _ObsRaisingMeta.ran is False


def test_valid_direct_input_and_discard_policy_unchanged() -> None:
    """Valid DIRECT records normalize exactly as before, and the documented
    discard-and-count policy for unknown string fields is preserved."""
    from scripts.nextness_monitor import MonitorInputError, validate_observations

    observations, discarded = validate_observations([dict(_GOOD_OBS)])
    assert observations == [_GOOD_OBS]
    assert discarded == 0

    observations, discarded = validate_observations(
        [{**_GOOD_OBS, "zzz": 1, "extra": 2}]
    )
    assert observations == [_GOOD_OBS]
    assert discarded == 2

    # The record guard itself is unchanged.
    with pytest.raises(MonitorInputError) as excinfo:
        validate_observations([["not", "a", "dict"]])
    assert str(excinfo.value) == "observation 0: expected builtin dict"
