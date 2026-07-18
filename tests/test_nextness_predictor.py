"""NP1: deterministic next-event baselines — contract + adversarial tests.

Every exact metric fixture below is calculated INDEPENDENTLY in the test
(explicit arithmetic from the documented formulas), never by calling the
module's own helpers — so a formula regression cannot hide behind its own
reflection.
"""

from __future__ import annotations

import json
import math
import os
import pathlib

import pytest

import scripts.nextness_predictor as nextness_predictor
from scripts.nextness_observer import TOKEN_NAMES, WriteOutsideLogDirError
from scripts.nextness_predictor import (
    ECE_BINS,
    InsufficientHistoryError,
    MAX_LINE_BYTES_DEFAULT,
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


def _padded_row(generation: int, counts: dict[str, int], content_bytes: int) -> str:
    """A valid row padded to EXACTLY content_bytes bytes (terminator excluded).

    json.dumps here is pure ASCII, so byte length == character length and
    each pad character grows the record by exactly one byte.
    """
    base = json.dumps({"generation": generation, "token_counts": counts, "pad": ""})
    deficit = content_bytes - len(base)
    assert deficit >= 0, "content_bytes too small for the base row"
    padded = json.dumps(
        {"generation": generation, "token_counts": counts, "pad": "x" * deficit}
    )
    assert len(padded.encode("utf-8")) == content_bytes
    return padded


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


def test_huge_line_is_rejected_and_terminates_ingestion(tmp_path) -> None:
    # Fail-closed contract: the first oversized record is counted and ends
    # ingestion — skipping past it would require unbounded scanning for
    # the next record boundary, so the row after it is never read.
    huge = json.dumps({"generation": 1, "token_counts": {A: 1}, "pad": "x" * 70_000})
    log = _write_log(tmp_path, [huge, _row(2, {A: 1})])
    seq, rej, rows_read = read_dominant_sequence(log)
    assert rej["oversized_line"] == 1
    assert seq == []
    assert rows_read == 1


def test_line_content_exactly_at_byte_bound_is_accepted(tmp_path) -> None:
    # The bound is on record CONTENT (LF or CRLF terminator excluded): a
    # record of exactly max_line_bytes bytes is still a valid observation.
    for terminator in (b"\n", b"\r\n"):
        log = tmp_path / "nextness_runs.jsonl"
        log.write_bytes(
            _padded_row(1, {A: 3}, 200).encode("utf-8") + terminator
            + _row(2, {B: 2}).encode("utf-8") + terminator
        )
        seq, rej, rows_read = read_dominant_sequence(log, max_line_bytes=200)
        assert rej["oversized_line"] == 0, terminator
        assert seq == [A, B], terminator
        assert rows_read == 2, terminator


def test_line_one_byte_over_bound_is_oversized_and_terminal(tmp_path) -> None:
    for terminator in (b"\n", b"\r\n"):
        log = tmp_path / "nextness_runs.jsonl"
        log.write_bytes(
            _padded_row(1, {A: 3}, 201).encode("utf-8") + terminator
            + _row(2, {B: 2}).encode("utf-8") + terminator
        )
        seq, rej, rows_read = read_dominant_sequence(log, max_line_bytes=200)
        assert rej["oversized_line"] == 1, terminator
        assert seq == [], terminator  # fail closed: nothing after it is read
        assert rows_read == 1, terminator


def test_unterminated_giant_record_reads_bounded_bytes(tmp_path, monkeypatch) -> None:
    # Pre-allocation guard: a 4 MB unterminated record must be DETECTED as
    # oversized without ever being materialized in full. The counting
    # wrapper measures the bytes actually pulled from the file.
    log = tmp_path / "nextness_runs.jsonl"
    log.write_bytes(b"x" * 4_000_000)  # one physical record, no terminator
    counted = {"bytes": 0}
    real_open = pathlib.Path.open

    class _CountingFile:
        def __init__(self, raw):
            self._raw = raw

        def readline(self, limit=-1):
            chunk = self._raw.readline(limit)
            counted["bytes"] += len(chunk)
            return chunk

        def __iter__(self):
            for line in self._raw:
                counted["bytes"] += len(line)
                yield line

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return self._raw.__exit__(*exc)

        def __getattr__(self, name):
            return getattr(self._raw, name)

    def counting_open(self, *args, **kwargs):
        raw = real_open(self, *args, **kwargs)
        return _CountingFile(raw) if self == log else raw

    monkeypatch.setattr(pathlib.Path, "open", counting_open)
    seq, rej, rows_read = read_dominant_sequence(log)
    assert rej["oversized_line"] == 1
    assert seq == []
    assert rows_read == 1
    # Bounded read: at most one max_line_bytes-sized probe plus slack —
    # never the full 4 MB record.
    assert counted["bytes"] <= MAX_LINE_BYTES_DEFAULT + 4096


def test_max_rows_bounds_work(tmp_path) -> None:
    log = _write_log(tmp_path, _dominant_rows([A] * 50))
    seq, _, rows_read = read_dominant_sequence(log, max_rows=10)
    assert rows_read == 10
    assert len(seq) == 10


def test_max_rows_exact_limit_and_one_over(tmp_path) -> None:
    log = _write_log(tmp_path, _dominant_rows([A] * 10))
    seq, _, rows_read = read_dominant_sequence(log, max_rows=10)
    assert (len(seq), rows_read) == (10, 10)   # exact limit: everything read
    log11 = _write_log(tmp_path, _dominant_rows([A] * 11))
    seq11, _, rows_read11 = read_dominant_sequence(log11, max_rows=10)
    assert (len(seq11), rows_read11) == (10, 10)  # limit+1: the 11th is untouched


def test_max_rows_counts_blank_physical_records(tmp_path) -> None:
    # max_rows is a RAW-work bound: blank physical records consume budget
    # even though they are neither observations nor violations.
    log = _write_log(tmp_path, ["", "", ""] + _dominant_rows([A, B, A]))
    seq, rej, rows_read = read_dominant_sequence(log, max_rows=5)
    assert rows_read == 5
    assert seq == [A, B]      # 3 blanks + 2 rows exhaust the budget of 5
    assert sum(rej.values()) == 0


def test_blank_line_flood_terminates_within_budget(tmp_path) -> None:
    log = tmp_path / "nextness_runs.jsonl"
    log.write_text("\n" * 10_000, encoding="utf-8")
    seq, rej, rows_read = read_dominant_sequence(log, max_rows=50)
    assert rows_read == 50    # bounded raw work, NOT 10,000 refunded reads
    assert seq == []
    assert sum(rej.values()) == 0


def test_report_rows_read_counts_blank_records(tmp_path) -> None:
    rows = _dominant_rows(_FIXTURE_SEQUENCE)
    log = _write_log(tmp_path, rows[:3] + [""] + rows[3:7] + [""] + rows[7:])
    report = build_report(log)
    assert report["input"]["rows_read"] == len(_FIXTURE_SEQUENCE) + 2
    assert report["input"]["rows_accepted"] == len(_FIXTURE_SEQUENCE)
    assert report["input"]["rows_rejected"] == 0


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
# Output identity guard: --output must never name or alias the input log
# (same convention as NP6/NP8: resolved path + os.path.samefile, fail
# closed when identity cannot be verified). Refusal contract at the CLI:
# exit 4, ONE concise ``error:`` line, no traceback, input byte-identical,
# no report written anywhere.
# ---------------------------------------------------------------------------


def test_validate_output_direct_same_path_is_refused(tmp_path) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    with pytest.raises(WriteOutsideLogDirError):
        validate_output_path(log, log)


def test_validate_output_lexical_alias_is_refused(tmp_path) -> None:
    # A path that names the log through a redundant component: distinct
    # lexically, identical once resolved. 'sub' need not exist — the
    # comparison is between resolution targets, not link/segment names.
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    alias = tmp_path / "sub" / ".." / "nextness_runs.jsonl"
    assert str(alias) != str(log)
    with pytest.raises(WriteOutsideLogDirError):
        validate_output_path(alias, log)


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


def test_validate_output_hardlink_alias_is_refused(tmp_path) -> None:
    # A hard link has a distinct path (resolution does NOT unify it) but
    # shares file identity — only os.path.samefile can catch it.
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    link = tmp_path / "report.json"
    _make_hardlink_or_skip(log, link)
    with pytest.raises(WriteOutsideLogDirError):
        validate_output_path(link, log)


def test_validate_output_symlink_alias_is_refused(tmp_path) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    link = tmp_path / "report.json"
    _make_symlink_or_skip(log, link)
    with pytest.raises(WriteOutsideLogDirError):
        validate_output_path(link, log)


def test_validate_output_ordinary_siblings_still_allowed(tmp_path) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    validate_output_path(tmp_path / "report.json", log)  # nonexistent: allowed
    existing = tmp_path / "existing.json"
    existing.write_text("old content\n", encoding="utf-8")
    validate_output_path(existing, log)  # existing non-alias: allowed


def _cli_alias_refusal_receipt(
    capsys, tmp_path: pathlib.Path, log: pathlib.Path, out_arg: pathlib.Path
) -> None:
    """Full refusal contract: exit 4 · one error: line · no traceback ·
    input byte-identical · no report written (no new filesystem entry)."""
    input_before = log.read_bytes()
    entries_before = sorted(p.name for p in tmp_path.iterdir())
    err = _expect_cli_failure(capsys, [str(log), "--output", str(out_arg)], 4)
    assert err.count("error:") == 1
    assert log.read_bytes() == input_before
    assert sorted(p.name for p in tmp_path.iterdir()) == entries_before


def test_cli_output_naming_input_log_is_refused(tmp_path, capsys) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    _cli_alias_refusal_receipt(capsys, tmp_path, log, log)


def test_cli_output_lexical_alias_is_refused(tmp_path, capsys) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    alias = tmp_path / "sub" / ".." / "nextness_runs.jsonl"
    _cli_alias_refusal_receipt(capsys, tmp_path, log, alias)


def test_cli_output_hardlink_alias_is_refused(tmp_path, capsys) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    link = tmp_path / "report.json"
    _make_hardlink_or_skip(log, link)
    input_before = log.read_bytes()
    err = _expect_cli_failure(capsys, [str(log), "--output", str(link)], 4)
    assert err.count("error:") == 1
    assert log.read_bytes() == input_before
    assert link.read_bytes() == input_before  # shared identity: still the log


def test_cli_output_symlink_alias_is_refused(tmp_path, capsys) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    link = tmp_path / "report.json"
    _make_symlink_or_skip(log, link)
    input_before = log.read_bytes()
    err = _expect_cli_failure(capsys, [str(log), "--output", str(link)], 4)
    assert err.count("error:") == 1
    assert log.read_bytes() == input_before


def test_cli_nonexistent_sibling_output_remains_allowed(tmp_path, capsys) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    input_before = log.read_bytes()
    out = tmp_path / "report.json"
    assert main([str(log), "--output", str(out)]) == 0
    assert out.is_file()
    assert log.read_bytes() == input_before
    assert json.loads(out.read_text(encoding="utf-8"))["schema"] == REPORT_SCHEMA


def test_cli_existing_non_alias_sibling_output_remains_allowed(tmp_path) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    out = tmp_path / "report.json"
    out.write_text("stale previous content\n", encoding="utf-8")
    assert main([str(log), "--output", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["schema"] == REPORT_SCHEMA


# ---------------------------------------------------------------------------
# File-output byte contract: exactly serialize_report(...).encode("utf-8"),
# LF only, independent of platform newline translation.
# ---------------------------------------------------------------------------


def test_file_output_bytes_are_exact_canonical_utf8(tmp_path) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    out = tmp_path / "report.json"
    assert main([str(log), "--output", str(out)]) == 0
    expected = serialize_report(build_report(log)).encode("utf-8")
    data = out.read_bytes()
    assert data == expected
    assert b"\r" not in data                    # no platform CRLF translation
    assert data.endswith(b"\n")                 # exactly one trailing LF byte
    assert not data.endswith(b"\n\n")


def test_stdout_report_matches_canonical_serialization(tmp_path, capsys) -> None:
    # Established stdout contract, asserted character-exactly: stdout is
    # sys.stdout.write(serialize_report(report)) — unchanged by the file
    # byte-output repair.
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    assert main([str(log)]) == 0
    assert capsys.readouterr().out == serialize_report(build_report(log))


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


# Expected-failure contract: documented nonzero exit + one concise
# ``error:`` stderr line, never a traceback; unexpected programming
# errors are NOT converted into clean exits.


def _expect_cli_failure(capsys, argv: list[str], code: int) -> str:
    assert main(argv) == code, argv
    captured = capsys.readouterr()
    assert captured.err.startswith("error:"), argv
    assert "Traceback" not in captured.err, argv
    return captured.err


def test_cli_missing_file_and_insufficient_history_exit_codes(tmp_path, capsys) -> None:
    _expect_cli_failure(capsys, [str(tmp_path / "absent.jsonl")], 2)
    log = _write_log(tmp_path, _dominant_rows([A]))
    _expect_cli_failure(capsys, [str(log)], 3)


def test_cli_validation_errors_are_concise_exit_2(tmp_path, capsys) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    for extra in (
        ["--smoothing", "0"],
        ["--smoothing", "1001"],
        ["--holdout-fraction", "0.9"],
        ["--max-rows", "0"],
        ["--max-rows", "2000000"],
        ["--max-line-bytes", "0"],
    ):
        _expect_cli_failure(capsys, [str(log), *extra], 2)


def test_cli_output_escape_is_concise_exit_4(tmp_path, capsys) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    escape = tmp_path.parent / "escape.json"
    _expect_cli_failure(capsys, [str(log), "--output", str(escape)], 4)
    assert not escape.exists()


def test_cli_unwritable_output_is_concise_exit_4(tmp_path, capsys) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    # The log's own directory passes the boundary check but cannot be
    # opened for writing on any platform.
    _expect_cli_failure(capsys, [str(log), "--output", str(tmp_path)], 4)


def test_cli_report_too_large_is_concise_exit_5(tmp_path, capsys, monkeypatch) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    monkeypatch.setattr(nextness_predictor, "MAX_REPORT_BYTES", 10)
    _expect_cli_failure(capsys, [str(log)], 5)


def test_cli_unexpected_errors_are_not_hidden(tmp_path, monkeypatch) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))

    def boom(*args, **kwargs):
        raise RuntimeError("unexpected programming error")

    monkeypatch.setattr(nextness_predictor, "build_report", boom)
    with pytest.raises(RuntimeError, match="unexpected programming error"):
        main([str(log)])


# ---------------------------------------------------------------------------
# Cross-module CLI failure-contract pins (Candidate C; see
# docs/NEXTNESS_CLI_FAILURE_CONTRACTS.md). Pins of ESTABLISHED behavior:
# argparse usage lane (SystemExit(2), multi-line usage:, outside main()'s
# return path);
# identity-inspection failure fails closed (exit 4)
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
    """A PermissionError from the guard's identity comparison (samefile on
    the existing non-alias output) must be a refusal — exit 4, one concise
    error: line, no traceback, inputs/destination/inventory untouched."""
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    out = tmp_path / "report.json"
    out.write_text("stale existing non-alias output\n", encoding="utf-8")
    log_before, out_before = log.read_bytes(), out.read_bytes()
    entries_before = sorted(p.name for p in tmp_path.iterdir())
    out_resolved = out.resolve()
    real_samefile = os.path.samefile

    def probed(a, b):
        if pathlib.Path(a).resolve() == out_resolved:
            raise PermissionError(13, "identity probe denied")
        return real_samefile(a, b)

    monkeypatch.setattr(os.path, "samefile", probed)
    assert main([str(log), "--output", str(out)]) == 4
    captured = capsys.readouterr()
    lines = [l for l in captured.err.strip().splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("error:")
    assert "Traceback" not in captured.err
    assert log.read_bytes() == log_before
    assert out.read_bytes() == out_before
    assert sorted(p.name for p in tmp_path.iterdir()) == entries_before


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
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    out = tmp_path / "stage_pin.out"
    out.write_text("pre-existing destination\n", encoding="utf-8")
    before = {p: p.read_bytes() for p in [log] + [out]}
    inv = sorted(p.name for p in tmp_path.iterdir())
    state = _patch_output_stage(monkeypatch, out.resolve(), deny_open=True)
    assert main([str(log), "--output", str(out)]) == 4
    _stage_exit4_receipt(capsys)
    assert state["opens"] == 1 and state["proxy"] is None  # failed AT open
    for p, b in before.items():
        assert p.read_bytes() == b
    assert sorted(p.name for p in tmp_path.iterdir()) == inv


def test_cli_post_open_write_failure_pinned(tmp_path, capsys, monkeypatch) -> None:
    """Post-open failure of the FIRST whole-buffer write: open succeeded,
    zero writes completed, destination truncated to empty; inputs
    unchanged; exit 4 with one concise line."""
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    out = tmp_path / "stage_pin.out"
    out.write_text("stale bytes to observe truncation\n", encoding="utf-8")
    before = {p: p.read_bytes() for p in [log]}
    state = _patch_output_stage(monkeypatch, out.resolve(), fail_write_at=1)
    assert main([str(log), "--output", str(out)]) == 4
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
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    canon = tmp_path / "canonical.out"
    assert main([str(log), "--output", str(canon)]) == 0          # capture canonical success bytes
    capsys.readouterr()
    canonical = canon.read_bytes()
    out = tmp_path / "stage_pin.out"
    before = {p: p.read_bytes() for p in [log]}
    state = _patch_output_stage(monkeypatch, out.resolve(), fail_close=True)
    assert main([str(log), "--output", str(out)]) == 4
    _stage_exit4_receipt(capsys)
    assert state["opens"] == 1 and state["proxy"] is not None
    assert state["proxy"].writes_ok == 1                       # whole buffer written
    assert state["proxy"].close_attempted                      # failure was AT close
    assert out.read_bytes() == canonical                       # complete bytes present
    for p, b in before.items():
        assert p.read_bytes() == b


# ---------------------------------------------------------------------------
# Predictor typed-input-boundary pilot (gated; docs/NEXTNESS_CLI_FAILURE_CONTRACTS.md).
# Failing-first target: a sentinel plain ValueError escaping the
# post-validation evaluation core must PROPAGATE, never convert to the
# documented exit-2 input lane. Preservation controls pin every genuine
# public lane byte-for-byte.
# ---------------------------------------------------------------------------


def test_cli_internal_plain_valueerror_propagates(tmp_path, monkeypatch) -> None:
    """Pilot pin: an internal plain ValueError from the post-validation
    evaluation core (run_evaluation) is an unexpected programming error
    and must propagate — not masquerade as a concise exit-2 failure."""
    import scripts.nextness_predictor as predictor_module

    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    before = log.read_bytes()

    def boom(*args, **kwargs):
        raise ValueError("sentinel plain ValueError probe")

    monkeypatch.setattr(predictor_module, "run_evaluation", boom)
    with pytest.raises(ValueError, match="sentinel plain ValueError probe"):
        main([str(log)])
    assert log.read_bytes() == before


def test_cli_config_bounds_exact_public_behavior(tmp_path, capsys) -> None:
    """The four reclassified validation lanes keep their public behavior
    byte-for-byte: exact message, single stderr line, exit 2, no
    traceback, input untouched."""
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    before = log.read_bytes()
    for argv, expected in (
        ([str(log), "--max-rows", "0"],
         "error: max_rows must be in (0, 1000000], got 0"),
        ([str(log), "--max-line-bytes", "0"],
         "error: max_line_bytes must be positive, got 0"),
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


def test_cli_insufficient_history_still_exit_3_pilot(tmp_path, capsys) -> None:
    log = _write_log(tmp_path, _dominant_rows([A, B]))
    before = log.read_bytes()
    assert main([str(log)]) == 3
    err = capsys.readouterr().err
    lines = [l for l in err.strip().splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("error:")
    assert "Traceback" not in err
    assert log.read_bytes() == before


def test_cli_output_alias_refusal_still_exit_4_pilot(tmp_path, capsys) -> None:
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    before = log.read_bytes()
    assert main([str(log), "--output", str(log)]) == 4
    err = capsys.readouterr().err
    lines = [l for l in err.strip().splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("error:")
    assert "Traceback" not in err
    assert log.read_bytes() == before


def test_cli_report_ceiling_still_exit_5_pilot(tmp_path, monkeypatch, capsys) -> None:
    import scripts.nextness_predictor as predictor_module

    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    before = log.read_bytes()
    monkeypatch.setattr(predictor_module, "MAX_REPORT_BYTES", 8)
    assert main([str(log)]) == 5
    err = capsys.readouterr().err
    lines = [l for l in err.strip().splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("error:")
    assert "Traceback" not in err
    assert log.read_bytes() == before


def test_typed_identity_at_the_four_reclassified_sites(tmp_path) -> None:
    """Direct-API pin: the four reclassified sites now raise
    PredictorInputError (a ValueError subclass — base-class catchers
    remain compatible); the evaluation core's equal-length/non-empty
    invariant stays a PLAIN ValueError and is NOT part of the typed
    input lane."""
    from scripts.nextness_predictor import (
        PredictorInputError,
        evaluate_predictions,
        run_evaluation,
    )

    assert issubclass(PredictorInputError, ValueError)
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    with pytest.raises(PredictorInputError):
        read_dominant_sequence(log, max_rows=0)
    with pytest.raises(PredictorInputError):
        read_dominant_sequence(log, max_line_bytes=0)
    with pytest.raises(PredictorInputError):
        run_evaluation([A, B] * 6, smoothing=0.0)
    with pytest.raises(PredictorInputError):
        run_evaluation([A, B] * 6, holdout_fraction=0.9)
    with pytest.raises(ValueError) as excinfo:
        evaluate_predictions([], [])
    assert type(excinfo.value) is ValueError  # plain, deliberately untyped


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
    log = _write_log(tmp_path, _dominant_rows(_FIXTURE_SEQUENCE))
    out = tmp_path / "never_written.out"
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
        main([str(log), "--output", str(out)])
    monkeypatch.undo()
    assert "injected read denial" in str(excinfo.value)
    assert type(excinfo.value) is PermissionError
    err = capsys.readouterr().err
    assert err == ""  # no misleading concise conversion
    assert not out.exists()
    for p, b in before.items():
        assert p.read_bytes() == b
