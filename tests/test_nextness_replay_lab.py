"""NP6: offline replay laboratory — contract + adversarial tests.

Every exact-value fixture is hand-derived in this file from the
documented decision procedure — the module is never asked to verify
itself. The equivalence-lock section pins the replay's semantics to
NP2's own bridge + receipt so silent divergence fails loudly.
"""

from __future__ import annotations

import json
import pathlib
import random

import pytest

from scripts.nextness_monitor import (
    MODEL_ALLOWLIST,
    MonitorConfig,
    build_receipt,
    observations_from_log,
)
from scripts.nextness_predictor import read_dominant_sequence
from scripts.nextness_replay_lab import (
    LAB_SCHEMA,
    MAX_LAB_CONFIGS,
    MAX_LAB_REPORT_BYTES,
    MAX_PROTOCOL_BYTES,
    MAX_REPLAY_STEPS,
    LabInputError,
    build_lab_report,
    load_protocol,
    main,
    replay_observations,
    replay_trajectory,
    serialize_lab_report,
    summarize_trajectory,
)

A = "void_static"
B = "compute_static"


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


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


def _config_entry(label: str, **overrides) -> dict:
    entry = {
        "label": label,
        "min_history": 30,
        "window": 50,
        "low_confidence_threshold": 0.3,
        "calibration_error_threshold": 0.2,
        "drift_threshold_bits": 0.15,
    }
    entry.update(overrides)
    return entry


def _write_protocol(
    tmp_path: pathlib.Path,
    configurations: list[dict],
    *,
    model: str = "first_order",
    smoothing: float = 1.0,
    holdout_fraction: float = 0.25,
    name: str = "protocol.json",
) -> pathlib.Path:
    protocol = tmp_path / name
    protocol.write_text(
        json.dumps(
            {
                "schema": "nextness-replay-protocol-v1",
                "model": model,
                "smoothing": smoothing,
                "holdout_fraction": holdout_fraction,
                "configurations": configurations,
            }
        ),
        encoding="utf-8",
    )
    return protocol


#: Loose thresholds that never fire on the alternating fixture, so the
#: only abstention driver left is min_history — making trajectories
#: hand-derivable.
_LOOSE = {
    "low_confidence_threshold": 0.01,
    "calibration_error_threshold": 0.9,
    "drift_threshold_bits": 0.9,
}


# ---------------------------------------------------------------------------
# Hand-derived trajectories
# ---------------------------------------------------------------------------


def test_trajectory_hand_derived_min_history_ablation(tmp_path) -> None:
    # [A,B]*30: 60 accepted rows, split floor(60*0.75)=45 train, 15
    # holdout steps. With loose thresholds the decision at step t is
    # abstain(insufficient_history) iff t < min_history, else none.
    # min_history=5  -> steps 1..4 abstain, first non-abstain step 5.
    # min_history=10 -> steps 1..9 abstain, first non-abstain step 10.
    log = _write_log(tmp_path, [A, B] * 30)
    protocol = _write_protocol(
        tmp_path,
        [
            _config_entry("strict-ish", min_history=10, **_LOOSE),
            _config_entry("loose", min_history=5, **_LOOSE),
        ],
    )
    report = build_lab_report(log, protocol)
    assert report["schema"] == LAB_SCHEMA
    assert report["laboratory_observation"] is True
    assert report["input"]["holdout_steps"] == 15
    assert report["input"]["train_rows"] == 45

    by_label = {c["label"]: c["trajectory"] for c in report["configurations"]}
    # Input order is preserved exactly — no ranking, no reordering.
    assert [c["label"] for c in report["configurations"]] == ["strict-ish", "loose"]

    strict = by_label["strict-ish"]
    assert strict["step_count"] == 15
    assert strict["first_non_abstain_step"] == 10
    assert strict["abstention_step_rate"] == 9 / 15
    assert strict["reason_step_counts"]["insufficient_history"] == 9
    assert strict["reason_step_counts"]["none"] == 6
    assert strict["abstention_onsets"] == 0
    assert strict["reorientations"] == 1
    assert strict["completed_abstention_run_lengths_steps"] == [9]
    assert strict["unresolved_trailing_abstention_steps"] is None
    assert strict["final_abstain"] is False
    assert strict["final_reason"] == "none"

    loose = by_label["loose"]
    assert loose["first_non_abstain_step"] == 5
    assert loose["abstention_step_rate"] == 4 / 15
    assert loose["completed_abstention_run_lengths_steps"] == [4]


def test_trajectory_preserves_honest_abstention_calibration_drift(tmp_path) -> None:
    # NP2's permanent finding: alternating sequence + default smoothing
    # (1.0) leaves first_order systematically under-confident (~0.605
    # confidence, hit rate 1.0 -> rolling ECE ~0.395 > 0.2). Once
    # min_history is satisfied the trajectory moves straight into
    # calibration_drift and NEVER leaves abstention — the lab must
    # report that outcome as-is, not force a "working" configuration.
    log = _write_log(tmp_path, [A, B] * 30)
    protocol = _write_protocol(tmp_path, [_config_entry("default-ish", min_history=10)])
    trajectory = build_lab_report(log, protocol)["configurations"][0]["trajectory"]
    assert trajectory["first_non_abstain_step"] is None
    assert trajectory["abstention_step_rate"] == 1.0
    assert trajectory["reason_step_counts"]["insufficient_history"] == 9
    assert trajectory["reason_step_counts"]["calibration_drift"] == 6
    assert trajectory["final_abstain"] is True
    assert trajectory["final_reason"] == "calibration_drift"
    assert trajectory["unresolved_trailing_abstention_steps"] == 15
    assert trajectory["reorientations"] == 0


# ---------------------------------------------------------------------------
# Equivalence lock: replay == NP2's own bridge + receipt
# ---------------------------------------------------------------------------


def _counts(tokens: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in tokens:
        out[t] = out.get(t, 0) + 1
    return out


#: The drift-sensitive configuration lifts the calibration threshold out
#: of the way so distribution_shift is the reason that actually DECIDES
#: — without it the higher-precedence reasons mask the drift half of the
#: replay and mutations there would be test-invisible.
_DRIFT_SENSITIVE = {
    "min_history": 5,
    "window": 7,
    "low_confidence_threshold": 0.01,
    "calibration_error_threshold": 0.85,
    "drift_threshold_bits": 0.05,
}


@pytest.mark.parametrize("model", MODEL_ALLOWLIST)
@pytest.mark.parametrize(
    "cfg_kwargs",
    [
        {"min_history": 10, "window": 50},
        {"min_history": 5, "window": 7},
        _DRIFT_SENSITIVE,
    ],
)
@pytest.mark.parametrize(
    "tokens",
    [
        # 60 rows, integral split (45): the A-regime starts at index 52,
        # so the change lands at holdout step 8 — mid-holdout, non-uniform.
        [A, B] * 26 + [A] * 8,
        # 61 rows, FRACTIONAL split (61*0.75 = 45.75 -> floor 45): pins
        # the floor in the re-derived split arithmetic — round/ceil
        # mutants produce different holdouts and fail the lock.
        [A, B] * 24 + [A] * 13,
    ],
    ids=["integral-split", "fractional-split"],
)
def test_replay_final_step_matches_live_receipt(tmp_path, model, cfg_kwargs, tokens) -> None:
    # The lab re-derives the bridge (it needs the train/holdout token
    # lists for per-step drift windows, which observations_from_log does
    # not return). This lock pins every re-derived piece to the live NP2
    # path: observations float-for-float, reference/recent counts, and
    # the final-step decision against build_receipt.
    log = _write_log(tmp_path, tokens)
    smoothing = 0.5
    cfg = MonitorConfig(**cfg_kwargs)

    sequence, _, _ = read_dominant_sequence(log)
    observations, train, holdout = replay_observations(
        sequence, model, smoothing=smoothing, holdout_fraction=0.25
    )
    live_obs, live_reference, live_recent = observations_from_log(
        log, model, smoothing=smoothing, holdout_fraction=0.25, window=cfg.window
    )
    assert observations == live_obs  # exact float-for-float equality
    assert _counts(train) == live_reference
    assert _counts(holdout[-cfg.window:]) == live_recent

    receipt = build_receipt(
        model=model,
        observations=live_obs,
        reference_counts=live_reference,
        recent_counts=live_recent,
        config=cfg,
    )
    decisions = replay_trajectory(observations, train, holdout, cfg)
    final_abstain, final_reason = decisions[-1]
    assert final_abstain == receipt["abstain"]
    assert final_reason == receipt["abstain_reason"]


def test_equivalence_lock_exercises_distribution_shift(tmp_path) -> None:
    # Meta-lock: at least one locked case must be DECIDED by drift, or
    # the js_divergence half of the replay is dead code to the suite.
    log = _write_log(tmp_path, [A, B] * 20 + [A] * 20)
    cfg = MonitorConfig(**_DRIFT_SENSITIVE)
    sequence, _, _ = read_dominant_sequence(log)
    observations, train, holdout = replay_observations(
        sequence, "first_order", smoothing=0.5, holdout_fraction=0.25
    )
    live_obs, live_reference, live_recent = observations_from_log(
        log, "first_order", smoothing=0.5, holdout_fraction=0.25, window=cfg.window
    )
    receipt = build_receipt(
        model="first_order",
        observations=live_obs,
        reference_counts=live_reference,
        recent_counts=live_recent,
        config=cfg,
    )
    assert receipt["abstain_reason"] == "distribution_shift"
    decisions = replay_trajectory(observations, train, holdout, cfg)
    assert decisions[-1] == (True, "distribution_shift")


def test_replay_trajectory_matches_independent_per_step_reference(tmp_path) -> None:
    # Differential check at EVERY step (the receipt lock pins only the
    # final one): the expected decision is rebuilt here with
    # independently written prefix/window slices feeding NP2's own
    # decide_abstention, so an off-by-one in the lab's slicing shows up
    # at some mid-trajectory step even when the final step agrees. The
    # regime change lands at holdout step 8 (index 52 of a 45-row train
    # prefix + 15-step holdout), the window (7) is shorter than the
    # trajectory, and the drift-sensitive config lets distribution_shift
    # actually decide steps — so windowed-recent-vs-whole-prefix
    # mutants, first-window-vs-last-window mutants and stale-latest
    # mutants all diverge from the reference at some step.
    from scripts.nextness_metrics import js_divergence
    from scripts.nextness_monitor import decide_abstention, rolling_ece

    tokens = [A, B] * 26 + [A] * 8
    log = _write_log(tmp_path, tokens)
    sequence, _, _ = read_dominant_sequence(log)
    cfg = MonitorConfig(**_DRIFT_SENSITIVE)
    observations, train, holdout = replay_observations(
        sequence, "first_order", smoothing=0.5, holdout_fraction=0.25
    )
    assert len(set(map(str, observations))) > 1  # non-degenerate holdout
    decisions = replay_trajectory(observations, train, holdout, cfg)

    reference_counts = _counts(train)
    seen_reasons = set()
    for step in range(1, len(holdout) + 1):
        window_obs = observations[:step][-cfg.window:]
        recent_counts = _counts(holdout[step - cfg.window if step > cfg.window else 0:step])
        expected = decide_abstention(
            observation_count=step,
            latest_confidence=observations[step - 1]["confidence"],
            latest_prev_seen=observations[step - 1]["prev_seen"],
            rolling_calibration_error=rolling_ece(window_obs),
            drift_bits=js_divergence(reference_counts, recent_counts),
            config=cfg,
        )
        assert decisions[step - 1] == expected
        seen_reasons.add(decisions[step - 1][1])
    # The fixture must exercise the drift half mid-trajectory, or this
    # differential proves less than it appears to.
    assert "distribution_shift" in seen_reasons
    assert len(seen_reasons) >= 2


def test_per_step_latest_observation_decides_low_confidence(tmp_path) -> None:
    # A fixture whose per-step confidence VARIES across the threshold:
    # in [A,B,A,C]* the transition source A splits its mass between B
    # and C (confidence ~0.38) while B and C both continue to A
    # (~0.60). With low_confidence_threshold=0.5 the decision at each
    # step depends on THAT step's latest observation — a replay that
    # reused a stale observation (e.g. the first one) would emit a
    # constant reason and diverge from the per-step reference.
    from scripts.nextness_metrics import js_divergence
    from scripts.nextness_monitor import decide_abstention, rolling_ece

    C = "void_birth"
    tokens = [A, B, A, C] * 15  # 60 rows: 45 train / 15 holdout
    log = _write_log(tmp_path, tokens)
    sequence, _, _ = read_dominant_sequence(log)
    cfg = MonitorConfig(
        min_history=5,
        window=7,
        low_confidence_threshold=0.5,
        calibration_error_threshold=0.85,
        drift_threshold_bits=0.9,
    )
    observations, train, holdout = replay_observations(
        sequence, "first_order", smoothing=0.5, holdout_fraction=0.25
    )
    confidences = {ob["confidence"] for ob in observations}
    assert len(confidences) > 1  # the threshold has something to separate
    decisions = replay_trajectory(observations, train, holdout, cfg)

    reference_counts = _counts(train)
    for step in range(1, len(holdout) + 1):
        window_obs = observations[:step][-cfg.window:]
        recent_counts = _counts(holdout[step - cfg.window if step > cfg.window else 0:step])
        expected = decide_abstention(
            observation_count=step,
            latest_confidence=observations[step - 1]["confidence"],
            latest_prev_seen=observations[step - 1]["prev_seen"],
            rolling_calibration_error=rolling_ece(window_obs),
            drift_bits=js_divergence(reference_counts, recent_counts),
            config=cfg,
        )
        assert decisions[step - 1] == expected
    post_history = [reason for _, reason in decisions[cfg.min_history - 1:]]
    assert "low_confidence" in post_history
    assert "none" in post_history  # the reason genuinely alternates


# ---------------------------------------------------------------------------
# No-winner contract
# ---------------------------------------------------------------------------


def test_no_ranking_or_winner_fields_anywhere(tmp_path) -> None:
    # The contract forbids ranking STRUCTURE, so the check walks keys —
    # the non-claims prose legitimately names the forbidden concepts.
    log = _write_log(tmp_path, [A, B] * 30)
    protocol = _write_protocol(
        tmp_path,
        [
            _config_entry("x", min_history=5, **_LOOSE),
            _config_entry("y", min_history=10, **_LOOSE),
        ],
    )
    report = build_lab_report(log, protocol)
    forbidden = {"winner", "rank", "ranking", "best", "recommendation", "score"}

    def _walk_keys(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                assert key.lower() not in forbidden
                _walk_keys(value)
        elif isinstance(node, list):
            for item in node:
                _walk_keys(item)

    _walk_keys(report)
    assert report["laboratory_observation"] is True


def test_configuration_results_independent_of_protocol_order(tmp_path) -> None:
    log = _write_log(tmp_path, [A, B] * 30)
    entries = [
        _config_entry("x", min_history=5, **_LOOSE),
        _config_entry("y", min_history=10, **_LOOSE),
    ]
    fwd = _write_protocol(tmp_path, entries, name="fwd.json")
    rev = _write_protocol(tmp_path, list(reversed(entries)), name="rev.json")
    report_fwd = build_lab_report(log, fwd)
    report_rev = build_lab_report(log, rev)
    assert [c["label"] for c in report_fwd["configurations"]] == ["x", "y"]
    assert [c["label"] for c in report_rev["configurations"]] == ["y", "x"]
    fwd_by_label = {c["label"]: c for c in report_fwd["configurations"]}
    rev_by_label = {c["label"]: c for c in report_rev["configurations"]}
    assert fwd_by_label == rev_by_label  # per-config results order-free


# ---------------------------------------------------------------------------
# Determinism and read-only posture
# ---------------------------------------------------------------------------


def test_lab_report_byte_identical_and_inputs_untouched(tmp_path) -> None:
    log = _write_log(tmp_path, [A, B] * 30)
    protocol = _write_protocol(tmp_path, [_config_entry("only", min_history=5)])
    log_bytes = log.read_bytes()
    protocol_bytes = protocol.read_bytes()
    outputs = {serialize_lab_report(build_lab_report(log, protocol)) for _ in range(3)}
    assert len(outputs) == 1
    serialized = next(iter(outputs))
    assert len(serialized.encode("utf-8")) <= MAX_LAB_REPORT_BYTES
    report = json.loads(serialized)
    assert len(report["input"]["sequence_sha256"]) == 64
    assert len(report["input"]["protocol_sha256"]) == 64
    # Read-only with respect to both inputs, byte for byte.
    assert log.read_bytes() == log_bytes
    assert protocol.read_bytes() == protocol_bytes


def test_protocol_key_order_does_not_change_results(tmp_path) -> None:
    log = _write_log(tmp_path, [A, B] * 30)
    base = {
        "schema": "nextness-replay-protocol-v1",
        "model": "first_order",
        "smoothing": 1.0,
        "holdout_fraction": 0.25,
        "configurations": [_config_entry("only", min_history=5)],
    }
    fwd = tmp_path / "fwd.json"
    fwd.write_text(json.dumps(base), encoding="utf-8")
    rev = tmp_path / "rev.json"
    rev.write_text(
        json.dumps({k: base[k] for k in reversed(list(base))}), encoding="utf-8"
    )
    report_fwd = build_lab_report(log, fwd)
    report_rev = build_lab_report(log, rev)
    # The bytes differ (hash provenance differs); the science must not.
    report_fwd["input"]["protocol_sha256"] = report_rev["input"]["protocol_sha256"] = None
    assert serialize_lab_report(report_fwd) == serialize_lab_report(report_rev)


# ---------------------------------------------------------------------------
# Property-style seeded traces (stdlib random only — no new dependency)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [7, 77, 777])
def test_seeded_trajectory_invariants(seed: int, tmp_path) -> None:
    rng = random.Random(seed)
    tokens = [rng.choice([A, B, "void_birth", "unclassified"]) for _ in range(120)]
    log = _write_log(tmp_path, tokens)
    protocol = _write_protocol(
        tmp_path,
        [
            _config_entry(
                f"cfg{i}",
                min_history=rng.choice([5, 10, 30]),
                window=rng.choice([5, 20, 50]),
                low_confidence_threshold=rng.choice([0.1, 0.3, 0.7]),
                calibration_error_threshold=rng.choice([0.1, 0.3]),
                drift_threshold_bits=rng.choice([0.05, 0.3]),
            )
            for i in range(3)
        ],
        model=rng.choice(list(MODEL_ALLOWLIST)),
    )
    report = build_lab_report(log, protocol)
    again = build_lab_report(log, protocol)
    assert serialize_lab_report(report) == serialize_lab_report(again)

    for entry in report["configurations"]:
        t = entry["trajectory"]
        steps = t["step_count"]
        assert steps == report["input"]["holdout_steps"]
        assert sum(t["reason_step_counts"].values()) == steps
        abstained = steps - t["reason_step_counts"]["none"]
        assert t["abstention_step_rate"] == abstained / steps
        assert 0.0 <= t["abstention_step_rate"] <= 1.0
        assert t["reorientations"] <= t["abstention_onsets"] + 1
        assert t["run_lengths_truncated"] is False
        assert len(t["completed_abstention_run_lengths_steps"]) == t["reorientations"]
        # Every abstained step lives in exactly one maximal run:
        # completed runs plus the unresolved trailing run must add up.
        trailing = t["unresolved_trailing_abstention_steps"] or 0
        assert sum(t["completed_abstention_run_lengths_steps"]) + trailing == abstained
        if t["first_non_abstain_step"] is None:
            assert t["abstention_step_rate"] == 1.0
        else:
            assert 1 <= t["first_non_abstain_step"] <= steps
        assert (t["final_reason"] == "none") == (t["final_abstain"] is False)


# ---------------------------------------------------------------------------
# Protocol validation: fail-closed adversarial corpus
# ---------------------------------------------------------------------------


def test_protocol_bounds_fail_closed(tmp_path) -> None:
    log = _write_log(tmp_path, [A, B] * 30)
    too_many = _write_protocol(
        tmp_path,
        [_config_entry(f"c{i}") for i in range(MAX_LAB_CONFIGS + 1)],
        name="many.json",
    )
    with pytest.raises(LabInputError, match="exceed"):
        build_lab_report(log, too_many)
    empty = _write_protocol(tmp_path, [], name="empty.json")
    with pytest.raises(LabInputError, match="non-empty"):
        build_lab_report(log, empty)
    dupes = _write_protocol(
        tmp_path, [_config_entry("same"), _config_entry("same")], name="dupes.json"
    )
    with pytest.raises(LabInputError, match="duplicate"):
        build_lab_report(log, dupes)
    long_label = _write_protocol(
        tmp_path, [_config_entry("x" * 65)], name="long.json"
    )
    with pytest.raises(LabInputError, match="length"):
        build_lab_report(log, long_label)


def test_protocol_unknown_variants_and_types_fail_closed(tmp_path) -> None:
    with pytest.raises(LabInputError, match="unknown variant"):
        load_protocol(_write_schema_variant(tmp_path))
    extra = tmp_path / "extra.json"
    payload = {
        "schema": "nextness-replay-protocol-v1",
        "model": "first_order",
        "smoothing": 1.0,
        "holdout_fraction": 0.25,
        "configurations": [_config_entry("a")],
        "surprise": 1,
    }
    extra.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(LabInputError, match="key set mismatch"):
        load_protocol(extra)

    bool_history = _write_protocol(
        tmp_path, [_config_entry("a", min_history=True)], name="bool.json"
    )
    with pytest.raises(LabInputError, match="builtin int"):
        load_protocol(bool_history)

    nan_file = tmp_path / "nan.json"
    nan_file.write_text(
        json.dumps(
            {
                "schema": "nextness-replay-protocol-v1",
                "model": "first_order",
                "smoothing": 1.0,
                "holdout_fraction": 0.25,
                "configurations": [_config_entry("a")],
            }
        ).replace("0.3", "NaN", 1),
        encoding="utf-8",
    )
    with pytest.raises(LabInputError, match="not finite"):
        load_protocol(nan_file)

    out_of_monitor_bounds = _write_protocol(
        tmp_path,
        [_config_entry("a", calibration_error_threshold=1.5)],
        name="oob.json",
    )
    with pytest.raises(LabInputError, match="must be a float in"):
        load_protocol(out_of_monitor_bounds)

    unknown_model = _write_protocol(
        tmp_path, [_config_entry("a")], model="second_order", name="model.json"
    )
    with pytest.raises(LabInputError, match="allowlist"):
        load_protocol(unknown_model)


def _write_schema_variant(tmp_path: pathlib.Path) -> pathlib.Path:
    p = tmp_path / "variant.json"
    p.write_text(
        json.dumps(
            {
                "schema": "nextness-replay-protocol-v2",
                "model": "first_order",
                "smoothing": 1.0,
                "holdout_fraction": 0.25,
                "configurations": [_config_entry("a")],
            }
        ),
        encoding="utf-8",
    )
    return p


def test_oversized_protocol_fails_closed_before_parse(tmp_path) -> None:
    big = tmp_path / "big.json"
    big.write_bytes(b"x" * (MAX_PROTOCOL_BYTES + 10))
    with pytest.raises(LabInputError, match="exceeds"):
        load_protocol(big)


def test_replay_step_bound_fails_closed_not_truncated(tmp_path) -> None:
    # holdout_fraction 0.5 over 2*(MAX_REPLAY_STEPS+1) rows yields
    # MAX_REPLAY_STEPS+1 holdout steps — one past the bound.
    tokens = [A, B] * (MAX_REPLAY_STEPS + 1)
    log = _write_log(tmp_path, tokens)
    protocol = _write_protocol(
        tmp_path, [_config_entry("a")], holdout_fraction=0.5
    )
    with pytest.raises(LabInputError, match="replay bound"):
        build_lab_report(log, protocol)


def test_replay_bound_rejects_before_observations_allocation(tmp_path, monkeypatch) -> None:
    # The bound must be enforced from the ALREADY-BOUNDED sequence
    # length, before replay_observations is ever invoked — the oversized
    # observation list must never be constructed.
    import scripts.nextness_replay_lab as lab_module

    tokens = [A, B] * (MAX_REPLAY_STEPS + 1)
    log = _write_log(tmp_path, tokens)
    protocol = _write_protocol(tmp_path, [_config_entry("a")], holdout_fraction=0.5)
    invocations: list[int] = []
    real = lab_module.replay_observations

    def _spy(*args, **kwargs):
        invocations.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(lab_module, "replay_observations", _spy)
    with pytest.raises(LabInputError, match="replay bound"):
        build_lab_report(log, protocol)
    assert invocations == []  # never called; no observation list built


@pytest.mark.parametrize(
    "fraction,rows,expect_ok",
    [
        (0.5, 2 * MAX_REPLAY_STEPS, True),        # holdout exactly at the limit
        (0.5, 2 * MAX_REPLAY_STEPS + 2, False),   # limit + 1
        (0.25, 4 * MAX_REPLAY_STEPS + 4, False),  # limit + 1 at another fraction
        (0.05, 20 * MAX_REPLAY_STEPS, True),      # max accepted sequence, holdout == limit
        (0.05, 20 * MAX_REPLAY_STEPS + 20, False),
    ],
    ids=["limit@0.5", "limit+1@0.5", "limit+1@0.25", "limit@0.05", "limit+1@0.05"],
)
def test_replay_bound_boundary_across_fractions(tmp_path, fraction, rows, expect_ok) -> None:
    tokens = [A if i % 2 == 0 else B for i in range(rows)]
    log = _write_log(tmp_path, tokens)
    protocol = _write_protocol(
        tmp_path,
        [_config_entry("a", min_history=5, window=5, **_LOOSE)],
        holdout_fraction=fraction,
    )
    if expect_ok:
        report = build_lab_report(log, protocol)
        assert report["input"]["holdout_steps"] == MAX_REPLAY_STEPS
    else:
        with pytest.raises(LabInputError, match="replay bound"):
            build_lab_report(log, protocol)


def test_hard_link_output_alias_refused_and_inputs_intact(tmp_path, capsys) -> None:
    # An --output that is an existing HARD LINK to an input shares its
    # file identity while having a different path: writing through it
    # would destroy the recording. It must be refused with the inputs
    # byte-intact.
    import os

    log = _write_log(tmp_path, [A, B] * 30)
    protocol = _write_protocol(tmp_path, [_config_entry("a", min_history=5)])
    for label, target in (("log", log), ("protocol", protocol)):
        alias = tmp_path / f"alias_{label}.json"
        os.link(target, alias)
        before = target.read_bytes()
        assert main([str(log), str(protocol), "--output", str(alias)]) == 4
        assert target.read_bytes() == before
        err = capsys.readouterr().err
        assert "identity" in err or "overwrite" in err
        alias.unlink()


def test_symlink_output_alias_refused_and_inputs_intact(tmp_path, capsys) -> None:
    import os

    log = _write_log(tmp_path, [A, B] * 30)
    protocol = _write_protocol(tmp_path, [_config_entry("a", min_history=5)])
    alias = tmp_path / "alias_symlink.json"
    try:
        os.symlink(log, alias)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform/user")
    before = log.read_bytes()
    assert main([str(log), str(protocol), "--output", str(alias)]) == 4
    assert log.read_bytes() == before


# ---------------------------------------------------------------------------
# Output-boundary pins: directory and symlink-to-directory targets.
#
# Coverage pinning of ESTABLISHED behavior (not a defect): a directory
# target passes path validation (inside the input-log directory, aliases
# nothing) and is refused at write time by the documented OSError lane —
# exit 4, one concise ``error:`` line, no traceback, both inputs
# byte-identical, the directory and its contents untouched, no output
# artifact (whole or partial) created.
# ---------------------------------------------------------------------------


def _pin_dir_target_refusal(capsys, tmp_path, out_target) -> None:
    log = _write_log(tmp_path, [A, B] * 30)
    protocol = _write_protocol(tmp_path, [_config_entry("a", min_history=5)])
    log_before = log.read_bytes()
    protocol_before = protocol.read_bytes()
    entries_before = sorted(p.name for p in tmp_path.iterdir())

    assert main([str(log), str(protocol), "--output", str(out_target)]) == 4

    captured = capsys.readouterr()
    err_lines = [line for line in captured.err.strip().splitlines() if line]
    assert len(err_lines) == 1 and err_lines[0].startswith("error:")
    assert "Traceback" not in captured.err
    assert log.read_bytes() == log_before
    assert protocol.read_bytes() == protocol_before
    assert sorted(p.name for p in tmp_path.iterdir()) == entries_before


def test_cli_existing_directory_output_target_pinned(tmp_path, capsys) -> None:
    target_dir = tmp_path / "already_here"
    target_dir.mkdir()
    (target_dir / "keep.txt").write_text("keep me\n", encoding="utf-8")
    _pin_dir_target_refusal(capsys, tmp_path, target_dir)
    assert target_dir.is_dir()
    assert (target_dir / "keep.txt").read_text(encoding="utf-8") == "keep me\n"
    assert sorted(p.name for p in target_dir.iterdir()) == ["keep.txt"]


def test_cli_symlink_to_directory_output_target_pinned(tmp_path, capsys) -> None:
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    (real_dir / "keep.txt").write_text("keep me\n", encoding="utf-8")
    link = tmp_path / "lab.json"
    try:
        link.symlink_to(real_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this platform/user")
    _pin_dir_target_refusal(capsys, tmp_path, link)
    assert real_dir.is_dir()
    assert (real_dir / "keep.txt").read_text(encoding="utf-8") == "keep me\n"
    assert sorted(p.name for p in real_dir.iterdir()) == ["keep.txt"]
    # The output link itself was not replaced by a regular file.
    assert link.is_symlink()
    assert link.resolve() == real_dir.resolve()


# ---------------------------------------------------------------------------
# CLI: exit codes, write boundary, concise errors
# ---------------------------------------------------------------------------


def test_cli_success_stdout_and_lf_only_output(tmp_path, capsys) -> None:
    log = _write_log(tmp_path, [A, B] * 30)
    protocol = _write_protocol(tmp_path, [_config_entry("only", min_history=5)])
    assert main([str(log), str(protocol)]) == 0
    stdout = capsys.readouterr().out
    assert json.loads(stdout)["schema"] == LAB_SCHEMA

    out = tmp_path / "lab.json"
    assert main([str(log), str(protocol), "--output", str(out)]) == 0
    first = out.read_bytes()
    assert main([str(log), str(protocol), "--output", str(out)]) == 0
    assert out.read_bytes() == first
    assert b"\r" not in first
    assert first == serialize_lab_report(build_lab_report(log, protocol)).encode("utf-8")


def test_cli_expected_failures_concise(tmp_path, capsys) -> None:
    log = _write_log(tmp_path, [A, B] * 30)
    protocol = _write_protocol(tmp_path, [_config_entry("a")])
    assert main([str(tmp_path / "absent.jsonl"), str(protocol)]) == 2
    assert main([str(log), str(tmp_path / "absent.json")]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert main([str(log), str(bad)]) == 2
    short_dir = tmp_path / "short"
    short_dir.mkdir()
    short_log = _write_log(short_dir, [A, B])
    short_protocol = _write_protocol(short_dir, [_config_entry("a")])
    assert main([str(short_log), str(short_protocol)]) == 3
    err = capsys.readouterr().err
    for line in err.splitlines():
        assert line.startswith("error:")
    assert "Traceback" not in err


def test_cli_refuses_to_overwrite_either_input(tmp_path, capsys) -> None:
    # An in-directory --output that names the log or the protocol would
    # destroy the immutable recording — refused, inputs byte-intact.
    log = _write_log(tmp_path, [A, B] * 30)
    protocol = _write_protocol(tmp_path, [_config_entry("a", min_history=5)])
    log_bytes = log.read_bytes()
    protocol_bytes = protocol.read_bytes()
    assert main([str(log), str(protocol), "--output", str(log)]) == 4
    assert main([str(log), str(protocol), "--output", str(protocol)]) == 4
    err = capsys.readouterr().err
    assert "refusing to overwrite the input" in err
    assert log.read_bytes() == log_bytes
    assert protocol.read_bytes() == protocol_bytes
    # A legitimate in-directory output leaves both inputs untouched too.
    out = tmp_path / "lab-output.json"
    assert main([str(log), str(protocol), "--output", str(out)]) == 0
    assert log.read_bytes() == log_bytes
    assert protocol.read_bytes() == protocol_bytes


def test_duplicate_protocol_keys_fail_closed(tmp_path) -> None:
    dup = tmp_path / "dup.json"
    dup.write_text(
        '{"schema": "nextness-replay-protocol-v1", "model": "first_order", '
        '"model": "persistence", "smoothing": 1.0, "holdout_fraction": 0.25, '
        '"configurations": [{"label": "a", "min_history": 30, "window": 50, '
        '"low_confidence_threshold": 0.3, "calibration_error_threshold": 0.2, '
        '"drift_threshold_bits": 0.15}]}',
        encoding="utf-8",
    )
    with pytest.raises(LabInputError, match="duplicate JSON key"):
        load_protocol(dup)


def test_replay_observations_rejects_unknown_model() -> None:
    with pytest.raises(LabInputError, match="allowlist"):
        replay_observations(
            [A, B] * 10, "persistance", smoothing=0.5, holdout_fraction=0.25
        )


def test_cli_write_boundary_exit_4(tmp_path, capsys, monkeypatch) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log = _write_log(log_dir, [A, B] * 30)
    protocol = _write_protocol(log_dir, [_config_entry("a", min_history=5)])
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert main([str(log), str(protocol), "--output", str(elsewhere / "lab.json")]) == 4
    assert "outside the input-log directory" in capsys.readouterr().err

    import scripts.nextness_replay_lab as lab_module

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(lab_module, "_repo_data_dir", lambda: data_dir.resolve())
    data_log = _write_log(data_dir, [A, B] * 30)
    data_protocol = _write_protocol(data_dir, [_config_entry("a", min_history=5)])
    assert (
        main([str(data_log), str(data_protocol), "--output", str(data_dir / "lab.json")]) == 4
    )
    assert "data/ tree" in capsys.readouterr().err


def test_cli_oversized_report_exit_5(tmp_path, capsys, monkeypatch) -> None:
    import scripts.nextness_replay_lab as lab_module

    monkeypatch.setattr(lab_module, "MAX_LAB_REPORT_BYTES", 64)
    log = _write_log(tmp_path, [A, B] * 30)
    protocol = _write_protocol(tmp_path, [_config_entry("a", min_history=5)])
    assert main([str(log), str(protocol)]) == 5
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "Traceback" not in err


# ---------------------------------------------------------------------------
# Output ceiling at maximum breadth
# ---------------------------------------------------------------------------


def test_max_configs_report_stays_inside_ceiling(tmp_path) -> None:
    log = _write_log(tmp_path, [A, B] * 30)
    protocol = _write_protocol(
        tmp_path,
        [
            _config_entry(f"configuration-{i:02d}-{'x' * 40}", min_history=5 + i)
            for i in range(MAX_LAB_CONFIGS)
        ],
    )
    report = build_lab_report(log, protocol)
    assert len(report["configurations"]) == MAX_LAB_CONFIGS
    assert len(serialize_lab_report(report).encode("utf-8")) <= MAX_LAB_REPORT_BYTES


def test_summarize_trajectory_alternating_pattern_hand_traced() -> None:
    # Decisions T T F T F F T (reasons arbitrary but coherent):
    # completed runs [2, 1]; onsets 2; reorientations 2; trailing 1.
    decisions = [
        (True, "insufficient_history"),
        (True, "insufficient_history"),
        (False, "none"),
        (True, "low_confidence"),
        (False, "none"),
        (False, "none"),
        (True, "distribution_shift"),
    ]
    t = summarize_trajectory(decisions)
    assert t["abstention_onsets"] == 2
    assert t["reorientations"] == 2
    assert t["completed_abstention_run_lengths_steps"] == [2, 1]
    assert t["unresolved_trailing_abstention_steps"] == 1
    assert t["first_non_abstain_step"] == 3
    assert t["abstention_step_rate"] == 4 / 7
    assert t["final_reason"] == "distribution_shift"


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
        main([])
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "usage:" in err
    assert "Traceback" not in err


def test_cli_identity_inspection_failure_fails_closed_exit_4(
    tmp_path, capsys, monkeypatch
) -> None:
    import os
    import pathlib as _pathlib

    log = _write_log(tmp_path, [A, B] * 30)
    protocol = _write_protocol(tmp_path, [_config_entry("a", min_history=5)])
    out = tmp_path / "lab.json"
    out.write_text("stale existing non-alias output\n", encoding="utf-8")
    before = {p: p.read_bytes() for p in (log, protocol, out)}
    entries_before = sorted(p.name for p in tmp_path.iterdir())
    out_resolved = out.resolve()
    real_samefile = os.path.samefile

    def probed(a, b):
        if _pathlib.Path(a).resolve() == out_resolved:
            raise PermissionError(13, "identity probe denied")
        return real_samefile(a, b)

    monkeypatch.setattr(os.path, "samefile", probed)
    assert main([str(log), str(protocol), "--output", str(out)]) == 4
    captured = capsys.readouterr()
    lines = [l for l in captured.err.strip().splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("error:")
    assert "Traceback" not in captured.err
    for p, b in before.items():
        assert p.read_bytes() == b
    assert sorted(p.name for p in tmp_path.iterdir()) == entries_before


def test_cli_unexpected_errors_are_not_hidden(tmp_path, monkeypatch) -> None:
    import scripts.nextness_replay_lab as lab_module

    log = _write_log(tmp_path, [A, B] * 30)
    protocol = _write_protocol(tmp_path, [_config_entry("a", min_history=5)])

    def boom(*args, **kwargs):
        raise RuntimeError("sentinel propagation probe")

    monkeypatch.setattr(lab_module, "build_lab_report", boom)
    with pytest.raises(RuntimeError, match="sentinel propagation probe"):
        main([str(log), str(protocol)])


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
    log = _write_log(tmp_path, [A, B] * 30)
    protocol = _write_protocol(tmp_path, [_config_entry("a", min_history=5)])
    out = tmp_path / "stage_pin.out"
    out.write_text("pre-existing destination\n", encoding="utf-8")
    before = {p: p.read_bytes() for p in [log, protocol] + [out]}
    inv = sorted(p.name for p in tmp_path.iterdir())
    state = _patch_output_stage(monkeypatch, out.resolve(), deny_open=True)
    assert main([str(log), str(protocol), "--output", str(out)]) == 4
    _stage_exit4_receipt(capsys)
    assert state["opens"] == 1 and state["proxy"] is None  # failed AT open
    for p, b in before.items():
        assert p.read_bytes() == b
    assert sorted(p.name for p in tmp_path.iterdir()) == inv


def test_cli_post_open_write_failure_pinned(tmp_path, capsys, monkeypatch) -> None:
    """Post-open failure of the FIRST whole-buffer write: open succeeded,
    zero writes completed, destination truncated to empty; inputs
    unchanged; exit 4 with one concise line."""
    log = _write_log(tmp_path, [A, B] * 30)
    protocol = _write_protocol(tmp_path, [_config_entry("a", min_history=5)])
    out = tmp_path / "stage_pin.out"
    out.write_text("stale bytes to observe truncation\n", encoding="utf-8")
    before = {p: p.read_bytes() for p in [log, protocol]}
    state = _patch_output_stage(monkeypatch, out.resolve(), fail_write_at=1)
    assert main([str(log), str(protocol), "--output", str(out)]) == 4
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
    log = _write_log(tmp_path, [A, B] * 30)
    protocol = _write_protocol(tmp_path, [_config_entry("a", min_history=5)])
    canon = tmp_path / "canonical.out"
    assert main([str(log), str(protocol), "--output", str(canon)]) == 0          # capture canonical success bytes
    capsys.readouterr()
    canonical = canon.read_bytes()
    out = tmp_path / "stage_pin.out"
    before = {p: p.read_bytes() for p in [log, protocol]}
    state = _patch_output_stage(monkeypatch, out.resolve(), fail_close=True)
    assert main([str(log), str(protocol), "--output", str(out)]) == 4
    _stage_exit4_receipt(capsys)
    assert state["opens"] == 1 and state["proxy"] is not None
    assert state["proxy"].writes_ok == 1                       # whole buffer written
    assert state["proxy"].close_attempted                      # failure was AT close
    assert out.read_bytes() == canonical                       # complete bytes present
    for p, b in before.items():
        assert p.read_bytes() == b


# ---------------------------------------------------------------------------
# Cross-module compatibility controls for the predictor typed-input-
# boundary pilot: the lab publicly re-exposes the imported reader's
# bounds (--max-rows / --max-line-bytes), so their public exit-2 lanes
# are pinned byte-for-byte here. No replay-lab production change.
# ---------------------------------------------------------------------------


def test_cli_reader_bound_public_lanes_exit_2(tmp_path, capsys) -> None:
    """The lab's reader-bound public lanes: exact message, single stderr
    line, exit 2, no traceback, inputs untouched."""
    log = _write_log(tmp_path, [A, B] * 30)
    protocol = _write_protocol(tmp_path, [_config_entry("a", min_history=5)])
    before = {p: p.read_bytes() for p in (log, protocol)}
    for argv, expected in (
        ([str(log), str(protocol), "--max-rows", "0"],
         "error: max_rows must be in (0, 1000000], got 0"),
        ([str(log), str(protocol), "--max-line-bytes", "0"],
         "error: max_line_bytes must be positive, got 0"),
    ):
        assert main(argv) == 2
        err = capsys.readouterr().err
        lines = [l for l in err.strip().splitlines() if l.strip()]
        assert lines == [expected]
        assert "Traceback" not in err
    for p, b in before.items():
        assert p.read_bytes() == b


def test_reader_bound_error_is_predictor_typed_through_broad_lane(tmp_path, capsys) -> None:
    """Cross-module compatibility pin: the predictor's typed reader-bound
    error (PredictorInputError) subclasses ValueError, so it continues
    through this CLI's documented broad exit-2 lane unchanged — same
    message, one concise line, no traceback, inputs untouched."""
    from scripts.nextness_predictor import PredictorInputError

    assert issubclass(PredictorInputError, ValueError)
    log = _write_log(tmp_path, [A, B] * 30)
    protocol = _write_protocol(tmp_path, [_config_entry("a", min_history=5)])
    before = {p: p.read_bytes() for p in (log, protocol)}
    with pytest.raises(PredictorInputError):
        read_dominant_sequence(log, max_rows=0)
    assert main([str(log), str(protocol), "--max-rows", "0"]) == 2
    err = capsys.readouterr().err
    lines = [l for l in err.strip().splitlines() if l.strip()]
    assert lines == ["error: max_rows must be in (0, 1000000], got 0"]
    assert "Traceback" not in err
    for p, b in before.items():
        assert p.read_bytes() == b
