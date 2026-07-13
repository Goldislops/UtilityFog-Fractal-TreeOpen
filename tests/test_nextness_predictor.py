"""NP1: deterministic next-event baselines — contract + adversarial tests.

Every exact metric fixture below is calculated INDEPENDENTLY in the test
(explicit arithmetic from the documented formulas), never by calling the
module's own helpers — so a formula regression cannot hide behind its own
reflection.
"""

from __future__ import annotations

import json
import math
import pathlib

import pytest

from scripts.nextness_observer import TOKEN_NAMES, WriteOutsideLogDirError
from scripts.nextness_predictor import (
    ECE_BINS,
    InsufficientHistoryError,
    MAX_REPORT_BYTES,
    REJECT_REASONS,
    REPORT_SCHEMA,
    build_report,
    dominant_token,
    empirical_prior_distribution,
    first_order_distribution,
    main,
    persistence_distribution,
    read_dominant_sequence,
    run_evaluation,
    serialize_report,
    transition_counts,
    validate_output_path,
)

A = "void_static"      # canonical index 0
B = "compute_static"   # canonical index 1
K = len(TOKEN_NAMES)   # 16


def _row(generation: int, counts: dict[str, int]) -> str:
    return json.dumps({"generation": generation, "token_counts": counts})


def _write_log(tmp_path: pathlib.Path, lines: list[str]) -> pathlib.Path:
    log = tmp_path / "nextness_runs.jsonl"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log


def _dominant_rows(tokens: list[str]) -> list[str]:
    return [_row(i, {tok: 3}) for i, tok in enumerate(tokens)]


# ---------------------------------------------------------------------------
# Dominant-token extraction
# ---------------------------------------------------------------------------


def test_dominant_token_ties_break_by_canonical_order() -> None:
    # A (index 0) and B (index 1) tied: canonical order wins, not dict order.
    assert dominant_token({B: 2, A: 2}) == A
    assert dominant_token({"phase_boundary": 5, "energy_pulse": 5}) == "energy_pulse"


def test_dominant_token_all_zero_is_none() -> None:
    assert dominant_token({A: 0, B: 0}) is None
    assert dominant_token({}) is None


# ---------------------------------------------------------------------------
# Defensive parsing: every rejection reason, individually accounted
# ---------------------------------------------------------------------------


def test_rejections_are_counted_by_reason_and_never_crash(tmp_path) -> None:
    payload_sentinel = "SENTINEL_PAYLOAD_MUST_NOT_APPEAR_IN_REPORT"
    lines = [
        _row(1, {A: 3}),                                        # accepted
        "{not json" + payload_sentinel,                          # malformed_json
        json.dumps([1, 2, 3]),                                   # not_object
        json.dumps({"token_counts": {A: 1}}),                    # missing_generation
        json.dumps({"generation": True, "token_counts": {A: 1}}),   # invalid_generation (bool)
        json.dumps({"generation": 1.5, "token_counts": {A: 1}}),    # invalid_generation (float)
        json.dumps({"generation": 2}),                           # missing_token_counts
        json.dumps({"generation": 3, "token_counts": [A]}),      # invalid_token_counts
        json.dumps({"generation": 4, "token_counts": {"tok_not_in_vocab": 1}}),  # unknown_token
        json.dumps({"generation": 5, "token_counts": {A: float("nan")}}),   # invalid_count_value
        json.dumps({"generation": 6, "token_counts": {A: -1}}),  # invalid_count_value
        json.dumps({"generation": 7, "token_counts": {A: True}}),  # invalid_count_value (bool)
        json.dumps({"generation": 8, "token_counts": {A: 0}}),   # no_dominant_token
        _row(9, {B: 2}),                                         # accepted
        _row(9, {A: 2}),                                         # duplicate_generation
        _row(4, {A: 2}),                                         # out_of_order_generation
    ]
    # NaN survives json.dumps? No — json.dumps(nan) emits NaN which loads
    # back via json.loads as float('nan') under the default parser. Good.
    log = _write_log(tmp_path, lines)
    seq, rej, rows_read = read_dominant_sequence(log)
    assert seq == [A, B]
    assert rej["malformed_json"] == 1
    assert rej["not_object"] == 1
    assert rej["missing_generation"] == 1
    assert rej["invalid_generation"] == 2
    assert rej["missing_token_counts"] == 1
    assert rej["invalid_token_counts"] == 1
    assert rej["unknown_token"] == 1
    assert rej["invalid_count_value"] == 3
    assert rej["no_dominant_token"] == 1
    assert rej["duplicate_generation"] == 1
    assert rej["out_of_order_generation"] == 1
    assert rej["oversized_line"] == 0
    assert sum(rej.values()) == 14
    assert rows_read == len(lines)
    assert set(rej) == set(REJECT_REASONS)


def test_huge_line_is_rejected_not_parsed(tmp_path) -> None:
    huge = json.dumps({"generation": 1, "token_counts": {A: 1}, "pad": "x" * 70_000})
    log = _write_log(tmp_path, [huge, _row(2, {A: 1})])
    seq, rej, _ = read_dominant_sequence(log)
    assert rej["oversized_line"] == 1
    assert seq == [A]


def test_max_rows_bounds_work(tmp_path) -> None:
    log = _write_log(tmp_path, _dominant_rows([A] * 50))
    seq, _, rows_read = read_dominant_sequence(log, max_rows=10)
    assert rows_read == 10
    assert len(seq) == 10


def test_out_of_order_rows_never_reorder_silently(tmp_path) -> None:
    log = _write_log(
        tmp_path, [_row(1, {A: 1}), _row(3, {B: 1}), _row(2, {A: 1}), _row(4, {A: 1})]
    )
    seq, rej, _ = read_dominant_sequence(log)
    assert seq == [A, B, A]  # gen 2 rejected, NOT inserted between 1 and 3
    assert rej["out_of_order_generation"] == 1


# ---------------------------------------------------------------------------
# Exact metric fixtures — independently calculated
#
# Setup: train = A B A B A B A B (8), holdout = A B A (3), smoothing = 1,
# holdout_fraction = 0.25 (floor(11 * 0.75) = 8). Transition counts from
# train pairs: A->B x4, B->A x3. Previous tokens for the holdout are
# [B (last train), A, B].
# ---------------------------------------------------------------------------

_FIXTURE_SEQUENCE = [A, B, A, B, A, B, A, B, A, B, A]


def _fixture_report(tmp_path) -> dict:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    return build_report(log)


def test_fixture_split_and_transition_bookkeeping(tmp_path) -> None:
    ev = _fixture_report(tmp_path)["evaluation"]
    assert ev["train_rows"] == 8
    assert ev["holdout_rows"] == 3
    assert ev["split_index"] == 8
    assert ev["first_order_unseen_source_count"] == 0


def test_fixture_first_order_exact_metrics(tmp_path) -> None:
    # Row A: P(B|A) = (4+1)/(4+16) = 0.25, others 1/20.
    # Row B: P(A|B) = (3+1)/(3+16) = 4/19, others 1/19.
    # Holdout (prev -> actual): (B->A), (A->B), (B->A); all top-1 hits.
    m = _fixture_report(tmp_path)["evaluation"]["models"]["first_order"]
    nll = (2 * math.log2(19 / 4) + math.log2(20 / 5)) / 3
    brier_b_row = (1 - 4 / 19) ** 2 + 15 * (1 / 19) ** 2
    brier_a_row = (1 - 5 / 20) ** 2 + 15 * (1 / 20) ** 2
    brier = (2 * brier_b_row + brier_a_row) / 3
    # Confidences 4/19, 5/20, 4/19 all land in bin [0.2, 0.3); acc 1.0.
    ece = abs((2 * (4 / 19) + 0.25) / 3 - 1.0)
    assert m["top1_accuracy"] == pytest.approx(1.0)
    assert m["nll_bits"] == pytest.approx(nll, rel=1e-12)
    assert m["brier"] == pytest.approx(brier, rel=1e-12)
    assert m["ece"] == pytest.approx(ece, rel=1e-12)


def test_fixture_persistence_exact_metrics(tmp_path) -> None:
    # Persistence dist: prev gets 2/17, all others 1/17. The alternating
    # holdout means the actual token is NEVER the previous one: 0 hits.
    m = _fixture_report(tmp_path)["evaluation"]["models"]["persistence"]
    assert m["top1_accuracy"] == pytest.approx(0.0)
    assert m["nll_bits"] == pytest.approx(math.log2(17), rel=1e-12)
    brier = (2 / 17) ** 2 + (1 - 1 / 17) ** 2 + 14 * (1 / 17) ** 2
    assert m["brier"] == pytest.approx(brier, rel=1e-12)
    assert m["ece"] == pytest.approx(2 / 17, rel=1e-12)  # conf 2/17, acc 0


def test_fixture_empirical_prior_exact_metrics(tmp_path) -> None:
    # Train counts: A=4, B=4 -> P(A)=P(B)=5/24, others 1/24. Argmax ties
    # A/B; canonical order predicts A every time -> 2/3 accuracy on A,B,A.
    m = _fixture_report(tmp_path)["evaluation"]["models"]["empirical_prior"]
    assert m["top1_accuracy"] == pytest.approx(2 / 3, rel=1e-12)
    assert m["nll_bits"] == pytest.approx(math.log2(24 / 5), rel=1e-12)
    brier = (1 - 5 / 24) ** 2 + (5 / 24) ** 2 + 14 * (1 / 24) ** 2
    assert m["brier"] == pytest.approx(brier, rel=1e-12)
    assert m["ece"] == pytest.approx(abs(5 / 24 - 2 / 3), rel=1e-12)


# ---------------------------------------------------------------------------
# Behavioral shape tests: constant, alternation, unseen tokens, fallback
# ---------------------------------------------------------------------------


def test_constant_sequence_every_model_predicts_it(tmp_path) -> None:
    log = _write_log(tmp_path, _dominant_rows([A] * 12))
    models = build_report(log)["evaluation"]["models"]
    for name in ("empirical_prior", "persistence", "first_order"):
        assert models[name]["top1_accuracy"] == pytest.approx(1.0), name


def test_alternation_rewards_transition_and_punishes_persistence(tmp_path) -> None:
    log = _write_log(tmp_path, _dominant_rows([A, B] * 10))
    models = build_report(log)["evaluation"]["models"]
    assert models["first_order"]["top1_accuracy"] == pytest.approx(1.0)
    assert models["persistence"]["top1_accuracy"] == pytest.approx(0.0)


def test_unseen_holdout_token_is_survivable_and_costly(tmp_path) -> None:
    # 'energy_pulse' first appears in the holdout: every model still emits
    # a full-vocabulary distribution (no crash), it just pays a large NLL.
    seq = [A, B] * 6 + ["energy_pulse", A, B, A]
    log = _write_log(tmp_path, _dominant_rows(seq))
    report = build_report(log)
    for name, m in report["evaluation"]["models"].items():
        assert math.isfinite(m["nll_bits"]), name
        assert m["nll_bits"] > 0.0, name


def test_first_order_unseen_source_falls_back_to_prior() -> None:
    train = [A, B, A, B]
    prior = empirical_prior_distribution(train, smoothing=1.0)
    table = transition_counts(train)
    fallback = first_order_distribution("energy_pulse", table, prior, smoothing=1.0)
    assert fallback == prior  # documented fallback: the empirical prior


def test_unseen_source_count_is_reported(tmp_path) -> None:
    seq = [A, B] * 5 + ["energy_pulse", A]  # 'energy_pulse' is a holdout prev
    log = _write_log(tmp_path, _dominant_rows(seq))
    ev = build_report(log)["evaluation"]
    assert ev["first_order_unseen_source_count"] >= 1


# ---------------------------------------------------------------------------
# Leakage, distributions, insufficiency
# ---------------------------------------------------------------------------


def test_no_holdout_leakage_into_training_prior(tmp_path) -> None:
    # 'sensor_alert' exists ONLY in the holdout. If the prior were built
    # over the full sequence it would carry frequency mass; built over the
    # train prefix only, its probability is exactly the smoothing floor.
    seq = [A, B] * 6 + ["sensor_alert", "sensor_alert", "sensor_alert"]
    split = math.floor(len(seq) * 0.75)
    assert all(t != "sensor_alert" for t in seq[:split])
    prior = empirical_prior_distribution(seq[:split], smoothing=1.0)
    assert prior["sensor_alert"] == pytest.approx(1.0 / (split + K), rel=1e-12)


def test_distributions_are_full_vocabulary_and_normalized() -> None:
    for dist in (
        empirical_prior_distribution([A, B, A], 1.0),
        persistence_distribution(A, 1.0),
        first_order_distribution(A, transition_counts([A, B, A]),
                                 empirical_prior_distribution([A, B], 1.0), 1.0),
    ):
        assert set(dist) == set(TOKEN_NAMES)
        assert sum(dist.values()) == pytest.approx(1.0, rel=1e-12)
        assert all(p > 0 for p in dist.values())


def test_insufficient_history_fails_closed(tmp_path) -> None:
    with pytest.raises(InsufficientHistoryError):
        run_evaluation([A, B])  # train=1 after split: too small
    log = _write_log(tmp_path, _dominant_rows([A]))
    with pytest.raises(InsufficientHistoryError):
        build_report(log)


def test_minimum_viable_history_works() -> None:
    ev = run_evaluation([A, B, A])  # train 2, holdout 1
    assert ev["train_rows"] == 2 and ev["holdout_rows"] == 1


def test_config_bounds_are_enforced() -> None:
    with pytest.raises(ValueError):
        run_evaluation([A] * 10, smoothing=0.0)
    with pytest.raises(ValueError):
        run_evaluation([A] * 10, holdout_fraction=0.9)
    with pytest.raises(ValueError):
        read_dominant_sequence(pathlib.Path("x"), max_rows=0)


# ---------------------------------------------------------------------------
# Report determinism, hygiene and bounds
# ---------------------------------------------------------------------------


def test_report_is_byte_identical_across_repeated_runs(tmp_path) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    first = serialize_report(build_report(log))
    second = serialize_report(build_report(log))
    assert first == second


def test_report_hygiene_no_timestamps_no_payloads(tmp_path) -> None:
    sentinel = "SENTINEL_PAYLOAD_MUST_NOT_APPEAR_IN_REPORT"
    lines = _dominant_rows(_FIXTURE_SEQUENCE) + ["{broken " + sentinel]
    log = _write_log(tmp_path, lines)
    report = build_report(log)
    serialized = serialize_report(report)
    assert report["schema"] == REPORT_SCHEMA
    assert sentinel not in serialized              # payloads never copied
    assert '"ts"' not in serialized                # no wall-clock fields
    assert len(serialized.encode("utf-8")) <= MAX_REPORT_BYTES
    # sorted-keys canonical form
    assert serialized == json.dumps(
        json.loads(serialized), sort_keys=True, separators=(",", ": "), indent=1
    ) + "\n"
    assert report["input"]["rows_rejected"] == 1
    assert report["config"]["ece_bins"] == ECE_BINS


# ---------------------------------------------------------------------------
# Write boundary: inside the input-log directory only, never data/
# ---------------------------------------------------------------------------


def test_output_inside_log_directory_is_allowed(tmp_path) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    validate_output_path(tmp_path / "report.json", log)  # no raise


def test_output_outside_log_directory_is_refused(tmp_path) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    with pytest.raises(WriteOutsideLogDirError):
        validate_output_path(tmp_path.parent / "escape.json", log)
    with pytest.raises(WriteOutsideLogDirError):
        validate_output_path(tmp_path / ".." / "escape.json", log)


def test_output_inside_repo_data_tree_is_refused() -> None:
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    data_log = repo_root / "data" / "nextness_logs" / "nextness_runs.jsonl"
    with pytest.raises(WriteOutsideLogDirError):
        validate_output_path(data_log.parent / "report.json", data_log)
    # Pure path logic: nothing was created or written.


# ---------------------------------------------------------------------------
# CLI end-to-end (offline, tmp-dir only)
# ---------------------------------------------------------------------------


def test_cli_writes_deterministic_report_inside_log_dir(tmp_path, capsys) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    out = tmp_path / "report.json"
    assert main([str(log), "--output", str(out)]) == 0
    text_one = out.read_text(encoding="utf-8")
    assert main([str(log)]) == 0  # stdout path
    stdout = capsys.readouterr().out
    assert stdout == text_one
    assert json.loads(text_one)["schema"] == REPORT_SCHEMA


def test_cli_refuses_output_escape(tmp_path) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    with pytest.raises(WriteOutsideLogDirError):
        main([str(log), "--output", str(tmp_path.parent / "escape.json")])


def test_cli_missing_file_and_insufficient_history_exit_codes(tmp_path) -> None:
    assert main([str(tmp_path / "absent.jsonl")]) == 2
    log = _write_log(tmp_path, _dominant_rows([A]))
    assert main([str(log)]) == 3
