"""NP8: deterministic evidence packet — contract + adversarial tests.

The packet is packaging and provenance verification only; every test
below checks manifest/link truthfulness, never any new metric.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from scripts.nextness_evaluator import build_evaluation, serialize_evaluation
from scripts.nextness_evidence_packet import (
    LINK_KINDS,
    MAX_INPUT_BYTES,
    MAX_PACKET_BYTES,
    PACKET_SCHEMA,
    ROLES,
    PacketInputError,
    build_packet,
    main,
    serialize_packet,
)
from scripts.nextness_monitor import (
    MonitorConfig,
    build_receipt,
    observations_from_log,
    serialize_receipt,
)
from scripts.nextness_predictor import build_report, serialize_report
from scripts.nextness_replay_lab import build_lab_report, serialize_lab_report

A = "void_static"
B = "compute_static"


# ---------------------------------------------------------------------------
# Fixture: one complete artifact chain, produced by the live emitters
# ---------------------------------------------------------------------------


def _write(path: pathlib.Path, content: str) -> pathlib.Path:
    path.write_bytes(content.encode("utf-8"))
    return path


@pytest.fixture()
def chain(tmp_path):
    log = _write(
        tmp_path / "nextness_runs.jsonl",
        "\n".join(
            json.dumps({"generation": i, "token_counts": {t: 3}})
            for i, t in enumerate([A, B] * 30)
        )
        + "\n",
    )
    report_obj = build_report(log)
    report = _write(tmp_path / "report.json", serialize_report(report_obj))
    observations, reference, recent = observations_from_log(log, "first_order")
    receipt_obj = build_receipt(
        model="first_order",
        observations=observations,
        reference_counts=reference,
        recent_counts=recent,
        config=MonitorConfig(),
    )
    receipts = _write(tmp_path / "receipt.json", serialize_receipt(receipt_obj))
    evaluation_obj = build_evaluation(report_path=report, receipts_path=receipts)
    evaluation = _write(tmp_path / "evaluation.json", serialize_evaluation(evaluation_obj))
    protocol = _write(
        tmp_path / "protocol.json",
        json.dumps(
            {
                "schema": "nextness-replay-protocol-v1",
                "model": "first_order",
                "smoothing": 1.0,
                "holdout_fraction": 0.25,
                "configurations": [
                    {"label": "defaults", "min_history": 30, "window": 50,
                     "low_confidence_threshold": 0.3,
                     "calibration_error_threshold": 0.2,
                     "drift_threshold_bits": 0.15}
                ],
            }
        )
        + "\n",
    )
    lab_obj = build_lab_report(log, protocol)
    lab = _write(tmp_path / "lab.json", serialize_lab_report(lab_obj))
    return {
        "log": log, "report": report, "receipts": receipts,
        "evaluation": evaluation, "protocol": protocol, "lab": lab,
    }


# ---------------------------------------------------------------------------
# The whole chain verifies
# ---------------------------------------------------------------------------


def test_full_chain_all_links_verified(chain) -> None:
    packet = build_packet(chain)
    assert packet["schema"] == PACKET_SCHEMA
    assert [entry["role"] for entry in packet["artifacts"]] == list(ROLES)
    for kind in LINK_KINDS:
        assert packet["links"][kind]["status"] == "verified", kind
    by_role = {entry["role"]: entry for entry in packet["artifacts"]}
    assert by_role["report"]["validation"] == "full"
    assert by_role["receipts"]["validation"] == "full"
    assert by_role["receipts"]["receipt_count"] == 1
    assert by_role["protocol"]["validation"] == "full"
    # Full structural validation through the NP9 public validators.
    assert by_role["evaluation"]["validation"] == "full"
    assert by_role["lab"]["validation"] == "full"
    assert by_role["log"]["validation"] == "sequence_reader"
    assert len(by_role["log"]["sequence_sha256"]) == 64


def test_receipts_array_form_counts(chain, tmp_path) -> None:
    single = json.loads(chain["receipts"].read_text(encoding="utf-8"))
    array_file = _write(tmp_path / "receipt_array.json", json.dumps([single, single]))
    packet = build_packet({"receipts": array_file})
    assert packet["artifacts"][0]["receipt_count"] == 2


# ---------------------------------------------------------------------------
# Broken links are reported as broken — byte-level, no interpretation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tampered_role,link",
    [
        ("report", "evaluation_report_sha256"),
        ("receipts", "evaluation_receipts_sha256"),
        ("protocol", "lab_protocol_sha256"),
    ],
)
def test_tampered_counterpart_breaks_exactly_that_link(chain, tampered_role, link) -> None:
    # Append a trailing newline: content changes, artifact stays valid.
    path = chain[tampered_role]
    path.write_bytes(path.read_bytes() + b"\n")
    packet = build_packet(chain)
    assert packet["links"][link]["status"] == "broken"
    assert packet["links"][link]["recorded_sha256"] != packet["links"][link]["actual_sha256"]
    for other in LINK_KINDS:
        if other != link:
            assert packet["links"][other]["status"] == "verified", other


def test_tampered_log_breaks_sequence_link(chain) -> None:
    # One appended accepted row changes the dominant-token sequence.
    chain["log"].write_bytes(
        chain["log"].read_bytes()
        + (json.dumps({"generation": 60, "token_counts": {A: 3}}) + "\n").encode()
    )
    packet = build_packet(chain)
    assert packet["links"]["lab_sequence_sha256"]["status"] == "broken"


# ---------------------------------------------------------------------------
# Typed not-computable links — absence is never failure or invention
# ---------------------------------------------------------------------------


def test_missing_counterparts_are_typed_not_computable(chain) -> None:
    packet = build_packet({"evaluation": chain["evaluation"]})
    for kind in ("evaluation_report_sha256", "evaluation_receipts_sha256"):
        entry = packet["links"][kind]
        assert entry["status"] == "not_computable"
        assert entry["reason"] == "counterpart_absent"
    for kind in ("lab_protocol_sha256", "lab_sequence_sha256"):
        assert packet["links"][kind]["reason"] == "counterpart_absent"


def test_link_not_recorded_when_evaluation_lacked_the_artifact(chain, tmp_path) -> None:
    # An evaluation produced WITHOUT receipts records provided: false —
    # given a receipts file anyway, the link is honestly not_computable
    # (link_not_recorded), never guessed.
    report_only = build_evaluation(report_path=chain["report"])
    eval_file = _write(tmp_path / "eval_report_only.json", serialize_evaluation(report_only))
    packet = build_packet(
        {"evaluation": eval_file, "report": chain["report"], "receipts": chain["receipts"]}
    )
    assert packet["links"]["evaluation_report_sha256"]["status"] == "verified"
    entry = packet["links"]["evaluation_receipts_sha256"]
    assert entry["status"] == "not_computable"
    assert entry["reason"] == "link_not_recorded"


def test_log_only_packet_is_valid_and_fully_typed(chain) -> None:
    packet = build_packet({"log": chain["log"]})
    assert len(packet["artifacts"]) == 1
    for kind in LINK_KINDS:
        assert packet["links"][kind]["status"] == "not_computable"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_packet_byte_identical_across_runs_and_role_order(chain) -> None:
    outputs = {serialize_packet(build_packet(chain)) for _ in range(3)}
    assert len(outputs) == 1
    reordered = dict(reversed(list(chain.items())))
    assert serialize_packet(build_packet(reordered)) == next(iter(outputs))
    serialized = next(iter(outputs))
    assert len(serialized.encode("utf-8")) <= MAX_PACKET_BYTES
    assert "time" not in json.dumps(sorted(json.loads(serialized))).lower()


# ---------------------------------------------------------------------------
# Fail-closed adversarial corpus
# ---------------------------------------------------------------------------


def test_role_and_count_bounds_fail_closed(chain) -> None:
    with pytest.raises(PacketInputError, match="nothing to package"):
        build_packet({})
    with pytest.raises(PacketInputError, match="unknown artifact roles"):
        build_packet({"telemetry": chain["log"]})


def test_unknown_schema_variants_rejected(chain, tmp_path) -> None:
    payload = json.loads(chain["evaluation"].read_text(encoding="utf-8"))
    payload["schema"] = "nextness-evaluation-v2"
    bad = _write(tmp_path / "bad_eval.json", json.dumps(payload))
    with pytest.raises(PacketInputError, match="unknown variant"):
        build_packet({"evaluation": bad})


def test_invalid_report_rejected_through_existing_validator(chain, tmp_path) -> None:
    payload = json.loads(chain["report"].read_text(encoding="utf-8"))
    payload["evaluation"]["split_index"] += 1  # break an NP1 identity
    bad = _write(tmp_path / "bad_report.json", json.dumps(payload))
    with pytest.raises(PacketInputError, match="report:"):
        build_packet({"report": bad})


def test_duplicate_json_keys_rejected(tmp_path) -> None:
    dup = _write(
        tmp_path / "dup.json",
        '{"schema": "nextness-evaluation-v1", "schema": "nextness-evaluation-v1"}',
    )
    with pytest.raises(PacketInputError, match="duplicate JSON key"):
        build_packet({"evaluation": dup})


def test_malformed_link_fields_rejected(chain, tmp_path) -> None:
    payload = json.loads(chain["lab"].read_text(encoding="utf-8"))
    payload["input"]["protocol_sha256"] = "NOT-A-HASH"
    bad = _write(tmp_path / "bad_lab.json", json.dumps(payload))
    with pytest.raises(PacketInputError, match="64-char lowercase hex"):
        build_packet({"lab": bad, "protocol": chain["protocol"]})
    payload = json.loads(chain["evaluation"].read_text(encoding="utf-8"))
    payload["artifacts"] = []
    bad2 = _write(tmp_path / "bad_eval_shape.json", json.dumps(payload))
    with pytest.raises(PacketInputError, match="builtin dict"):
        build_packet({"evaluation": bad2, "report": chain["report"]})


def test_oversized_artifact_fails_closed(tmp_path) -> None:
    big = tmp_path / "big.json"
    big.write_bytes(b"x" * (MAX_INPUT_BYTES + 10))
    with pytest.raises(PacketInputError, match="exceeds"):
        build_packet({"evaluation": big})


# ---------------------------------------------------------------------------
# CLI: exit codes, write boundary incl. alias identity, concise errors
# ---------------------------------------------------------------------------


def _chain_args(chain) -> list[str]:
    args = []
    for role, path in chain.items():
        args += [f"--{role}", str(path)]
    return args


def test_cli_success_and_lf_only_output(chain, tmp_path, capsys) -> None:
    assert main(_chain_args(chain)) == 0
    assert json.loads(capsys.readouterr().out)["schema"] == PACKET_SCHEMA
    out = tmp_path / "packet.json"
    assert main(_chain_args(chain) + ["--output", str(out)]) == 0
    first = out.read_bytes()
    assert main(_chain_args(chain) + ["--output", str(out)]) == 0
    assert out.read_bytes() == first
    assert b"\r" not in first


def test_cli_expected_failures_concise(chain, tmp_path, capsys) -> None:
    assert main([]) == 2
    assert main(["--report", str(tmp_path / "absent.json")]) == 2
    err = capsys.readouterr().err
    for line in err.splitlines():
        assert line.startswith("error:")
    assert "Traceback" not in err


def test_cli_write_boundary_and_alias_identity(chain, tmp_path, capsys) -> None:
    import os

    # tmp_path is the primary input's own directory; its PARENT is
    # outside it (subdirectories are inside and legitimately allowed by
    # the stack-wide containment convention).
    outside = tmp_path.parent / "np8-outside-p.json"
    assert main(_chain_args(chain) + ["--output", str(outside)]) == 4
    # Naming ANY input directly is refused.
    assert main(_chain_args(chain) + ["--output", str(chain["log"])]) == 4
    # A hard link alias to any input is refused with the input intact.
    alias = chain["log"].parent / "alias.json"
    os.link(chain["protocol"], alias)
    before = chain["protocol"].read_bytes()
    assert main(_chain_args(chain) + ["--output", str(alias)]) == 4
    assert chain["protocol"].read_bytes() == before
    err = capsys.readouterr().err
    assert "identity" in err or "overwrite" in err


# ---------------------------------------------------------------------------
# Output-boundary pins: directory targets, symlink-to-directory targets,
# and symlink output aliases against EVERY supplied input role.
#
# Coverage pinning of ESTABLISHED behavior (not a defect):
# - a directory target passes path validation (inside the primary
#   input's directory, aliases nothing) and is refused at write time by
#   the documented OSError lane;
# - a symlink whose resolution target IS a supplied input is refused by
#   the identity guard before any packet is built.
# Both refusals: exit 4, one concise ``error:`` line, no traceback,
# every supplied input byte-identical, directory/sentinel contents
# unchanged, no output artifact (whole or partial) created.
# ---------------------------------------------------------------------------


def _pin_packet_refusal(capsys, chain, tmp_path, out_target) -> None:
    before = {role: path.read_bytes() for role, path in chain.items()}
    entries_before = sorted(p.name for p in tmp_path.iterdir())

    assert main(_chain_args(chain) + ["--output", str(out_target)]) == 4

    captured = capsys.readouterr()
    err_lines = [line for line in captured.err.strip().splitlines() if line]
    assert len(err_lines) == 1 and err_lines[0].startswith("error:")
    assert "Traceback" not in captured.err
    for role, path in chain.items():
        assert path.read_bytes() == before[role], f"input mutated: {role}"
    assert sorted(p.name for p in tmp_path.iterdir()) == entries_before


def test_cli_existing_directory_output_target_pinned(chain, tmp_path, capsys) -> None:
    target_dir = tmp_path / "already_here"
    target_dir.mkdir()
    (target_dir / "keep.txt").write_text("keep me\n", encoding="utf-8")
    _pin_packet_refusal(capsys, chain, tmp_path, target_dir)
    assert target_dir.is_dir()
    assert (target_dir / "keep.txt").read_text(encoding="utf-8") == "keep me\n"
    assert sorted(p.name for p in target_dir.iterdir()) == ["keep.txt"]


def test_cli_symlink_to_directory_output_target_pinned(chain, tmp_path, capsys) -> None:
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    (real_dir / "keep.txt").write_text("keep me\n", encoding="utf-8")
    link = tmp_path / "packet.json"
    try:
        link.symlink_to(real_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported here (e.g. Windows w/o privilege)")
    _pin_packet_refusal(capsys, chain, tmp_path, link)
    assert real_dir.is_dir()
    assert (real_dir / "keep.txt").read_text(encoding="utf-8") == "keep me\n"
    assert sorted(p.name for p in real_dir.iterdir()) == ["keep.txt"]
    # The output link itself was not replaced by a regular file.
    assert link.is_symlink()
    assert link.resolve() == real_dir.resolve()


@pytest.mark.parametrize("role", list(ROLES))
def test_cli_symlink_output_alias_of_each_input_role_pinned(
    chain, tmp_path, capsys, role
) -> None:
    """A symlink inside the primary input's directory whose resolution
    target IS the supplied ``role`` artifact must be refused by the
    identity guard — for every role the chain fixture exposes."""
    link = tmp_path / f"alias_{role}.json"
    try:
        link.symlink_to(chain[role])
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported here (e.g. Windows w/o privilege)")
    _pin_packet_refusal(capsys, chain, tmp_path, link)
    # The link itself is untouched and still resolves to the intact input.
    assert link.resolve() == chain[role].resolve()
    assert link.read_bytes() == chain[role].read_bytes()


def test_cli_data_tree_refused(chain, tmp_path, capsys, monkeypatch) -> None:
    import scripts.nextness_evidence_packet as packet_module

    monkeypatch.setattr(
        packet_module, "_repo_data_dir", lambda: chain["log"].parent.resolve()
    )
    assert main(_chain_args(chain) + ["--output", str(chain["log"].parent / "p.json")]) == 4
    assert "data/ tree" in capsys.readouterr().err


def test_cli_oversized_packet_exit_5(chain, capsys, monkeypatch) -> None:
    import scripts.nextness_artifact_validation as validation_module
    import scripts.nextness_evidence_packet as packet_module

    monkeypatch.setattr(packet_module, "MAX_PACKET_BYTES", 64)
    # The self-validator pins the config echo to the v1 constant, so its
    # expectation must move with the monkeypatched ceiling for the
    # ceiling breach itself to be reachable.
    monkeypatch.setitem(validation_module._PACKET_CONFIG, "max_packet_bytes", 64)
    assert main(_chain_args(chain)) == 5
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "Traceback" not in err


# ---------------------------------------------------------------------------
# Correction A: the sequence link uses the LAB'S RECORDED reader bounds
# ---------------------------------------------------------------------------


def _make_protocol(tmp_path: pathlib.Path, name: str = "protocol.json", **overrides) -> pathlib.Path:
    payload = {
        "schema": "nextness-replay-protocol-v1",
        "model": "first_order",
        "smoothing": 1.0,
        "holdout_fraction": 0.25,
        "configurations": [
            {"label": "defaults", "min_history": 30, "window": 50,
             "low_confidence_threshold": 0.3,
             "calibration_error_threshold": 0.2,
             "drift_threshold_bits": 0.15}
        ],
    }
    payload.update(overrides)
    return _write(tmp_path / name, json.dumps(payload) + "\n")


def _custom_bounds_pair(tmp_path: pathlib.Path, **reader_bounds):
    # A 40-row log whose accepted sequence CHANGES under the custom
    # bounds relative to NP1 defaults: row 20 is oversized for the
    # custom max_line_bytes, and max_rows=10 cuts ingestion short.
    rows = []
    for i in range(40):
        counts = {A: 3} if i % 2 == 0 else {B: 3}
        if i == 20:
            counts = {B: 3, "void_birth": 1, "unclassified": 2}  # longer line
        rows.append(json.dumps({"generation": i, "token_counts": counts}))
    log = _write(tmp_path / "custom_log.jsonl", "\n".join(rows) + "\n")
    protocol = _make_protocol(tmp_path, name="custom_protocol.json")
    lab_obj = build_lab_report(log, protocol, **reader_bounds)
    lab = _write(tmp_path / "custom_lab.json", serialize_lab_report(lab_obj))
    return log, lab


@pytest.mark.parametrize(
    "reader_bounds",
    [
        {"max_rows": 10},
        {"max_line_bytes": 70},
        {"max_rows": 30, "max_line_bytes": 70},
    ],
    ids=["max-rows-only", "max-line-bytes-only", "both"],
)
def test_lab_sequence_link_verifies_with_recorded_bounds(tmp_path, reader_bounds) -> None:
    # A genuinely-paired log+lab produced with non-default reader bounds
    # accepts a DIFFERENT sequence than the defaults would; the link
    # must recompute with the lab's recorded bounds and verify.
    log, lab = _custom_bounds_pair(tmp_path, **reader_bounds)
    packet = build_packet({"lab": lab, "log": log})
    link = packet["links"]["lab_sequence_sha256"]
    assert link["status"] == "verified"
    # The bounds actually used are reported for reproducibility.
    for key, value in reader_bounds.items():
        assert link["reader_bounds"][key] == value
    # The custom bounds genuinely diverge from the defaults, or this
    # test proves nothing: the manifest's default-bounds sequence hash
    # must differ from the recorded one.
    by_role = {e["role"]: e for e in packet["artifacts"]}
    assert by_role["log"]["sequence_sha256"] != link["recorded_sha256"]


def test_lab_sequence_link_tampered_digest_still_broken(tmp_path) -> None:
    log, lab = _custom_bounds_pair(tmp_path, max_rows=10)
    payload = json.loads(lab.read_text(encoding="utf-8"))
    payload["input"]["sequence_sha256"] = "0" * 64
    tampered = _write(tmp_path / "tampered_lab.json", json.dumps(payload))
    packet = build_packet({"lab": tampered, "log": log})
    assert packet["links"]["lab_sequence_sha256"]["status"] == "broken"


def test_recorded_bounds_exact_boundaries_accepted(chain, tmp_path) -> None:
    # Values at the exact NP1/NP6 acceptance boundaries must validate
    # (the digest comparison then reports broken for this unpaired lab,
    # which is fine — the bounds VALIDATION is what is under test).
    from scripts.nextness_predictor import MAX_ROWS_CEILING

    payload = json.loads(chain["lab"].read_text(encoding="utf-8"))
    payload["config"]["max_rows"] = MAX_ROWS_CEILING
    payload["config"]["max_line_bytes"] = 1
    boundary = _write(tmp_path / "boundary_lab.json", json.dumps(payload))
    packet = build_packet({"lab": boundary, "log": chain["log"]})
    assert packet["links"]["lab_sequence_sha256"]["status"] in ("verified", "broken")
    # boundary totality: exactly at the shared 16 MiB line-bytes ceiling
    # is accepted (tiny log — the bounded reader allocates lazily)
    from scripts.nextness_predictor import MAX_LINE_BYTES_CEILING

    payload = json.loads(chain["lab"].read_text(encoding="utf-8"))
    payload["config"]["max_line_bytes"] = MAX_LINE_BYTES_CEILING
    at_ceiling = _write(tmp_path / "at_ceiling_lab.json", json.dumps(payload))
    packet = build_packet({"lab": at_ceiling, "log": chain["log"]})
    assert packet["links"]["lab_sequence_sha256"]["status"] in ("verified", "broken")


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_rows", 0),
        ("max_rows", -1),
        ("max_rows", 1_000_001),
        ("max_rows", True),
        ("max_rows", 10.0),
        ("max_rows", "100"),
        ("max_line_bytes", 0),
        ("max_line_bytes", -5),
        ("max_line_bytes", False),
        ("max_line_bytes", 65536.0),
        ("max_line_bytes", None),
        # boundary totality: the defensive extraction ceiling refuses an
        # index-overflowing recorded bound before the reader replay
        ("max_line_bytes", 16_777_217),
        ("max_line_bytes", 9223372036854775806),
    ],
)
def test_malformed_recorded_bounds_rejected(chain, tmp_path, field, value) -> None:
    payload = json.loads(chain["lab"].read_text(encoding="utf-8"))
    payload["config"][field] = value
    bad = _write(tmp_path / "bad_bounds_lab.json", json.dumps(payload))
    with pytest.raises(PacketInputError, match=field):
        build_packet({"lab": bad, "log": chain["log"]})


# ---------------------------------------------------------------------------
# Correction B: provided flags are EXACT builtin bools
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, "verified"),
        (False, "link_not_recorded"),
        (1, "error"),
        (0, "error"),
        ("true", "error"),
        ("false", "error"),
        (None, "error"),
        ([], "error"),
        ({}, "error"),
    ],
    ids=["True", "False", "int-1", "int-0", "str-true", "str-false",
         "None", "list", "dict"],
)
def test_provided_flag_truth_table(chain, tmp_path, value, expected) -> None:
    # A tampered evaluation must never SUPPRESS verification by smuggling
    # a truthy/falsy non-bool through the provided flag: only builtin
    # True verifies, only builtin False is typed link_not_recorded, and
    # everything else is malformed input (fail closed).
    if expected == "link_not_recorded":
        # A GENUINE provided:false evaluation comes from the emitter
        # itself (receipts-only) — full validation rejects a synthetic
        # slot that keeps stale sha/bytes keys beside provided:false.
        genuine = build_evaluation(receipts_path=chain["receipts"])
        mutated = _write(
            tmp_path / "receipts_only_eval.json", serialize_evaluation(genuine)
        )
    else:
        payload = json.loads(chain["evaluation"].read_text(encoding="utf-8"))
        payload["artifacts"]["report"]["provided"] = value
        mutated = _write(tmp_path / "mutated_eval.json", json.dumps(payload))
    inputs = {"evaluation": mutated, "report": chain["report"]}
    if expected == "error":
        with pytest.raises(PacketInputError, match="provided"):
            build_packet(inputs)
    else:
        link = build_packet(inputs)["links"]["evaluation_report_sha256"]
        if expected == "verified":
            assert link["status"] == "verified"
        else:
            assert link["status"] == "not_computable"
            assert link["reason"] == "link_not_recorded"


# ---------------------------------------------------------------------------
# Correction C: log size and memory contract (MAX_LOG_BYTES, chunked hash)
# ---------------------------------------------------------------------------


def test_log_larger_than_one_mib_is_accepted_and_verifies(tmp_path) -> None:
    # ~2 MiB of genuine rows (>1 MiB, well under MAX_LOG_BYTES), with a
    # small holdout fraction so the NP6 replay bound holds — the whole
    # lab/log pair must package and the sequence link must verify.
    from scripts.nextness_evidence_packet import MAX_LOG_BYTES

    rows = [
        json.dumps({"generation": i, "token_counts": {A if i % 2 == 0 else B: 3}})
        for i in range(40_000)
    ]
    content = "\n".join(rows) + "\n"
    assert 1_048_576 < len(content.encode()) <= MAX_LOG_BYTES
    log = _write(tmp_path / "big_log.jsonl", content)
    protocol = _make_protocol(tmp_path, holdout_fraction=0.05)
    lab = _write(
        tmp_path / "big_lab.json", serialize_lab_report(build_lab_report(log, protocol))
    )
    packet = build_packet({"lab": lab, "log": log})
    assert packet["links"]["lab_sequence_sha256"]["status"] == "verified"
    by_role = {e["role"]: e for e in packet["artifacts"]}
    assert by_role["log"]["bytes"] == len(content.encode())
    # Chunked hashing must equal a whole-file hash.
    import hashlib

    assert by_role["log"]["sha256"] == hashlib.sha256(content.encode()).hexdigest()


def test_log_size_ceiling_exact_limit_and_limit_plus_one(tmp_path) -> None:
    from scripts.nextness_evidence_packet import MAX_LOG_BYTES

    row = json.dumps({"generation": 0, "token_counts": {A: 3}}) + "\n"
    pad = MAX_LOG_BYTES - len(row.encode())
    exact = _write(tmp_path / "exact.jsonl", row + " " * (pad - 1) + "\n")
    assert exact.stat().st_size == MAX_LOG_BYTES
    packet = build_packet({"log": exact})
    assert packet["artifacts"][0]["bytes"] == MAX_LOG_BYTES

    over = tmp_path / "over.jsonl"
    over.write_bytes((row + " " * (pad - 1) + "\n").encode() + b"x")
    assert over.stat().st_size == MAX_LOG_BYTES + 1
    with pytest.raises(PacketInputError, match="log exceeds"):
        build_packet({"log": over})


# ---------------------------------------------------------------------------
# Correction D: one parse per JSON artifact
# ---------------------------------------------------------------------------


def test_each_json_artifact_parsed_exactly_once(chain, monkeypatch) -> None:
    import scripts.nextness_evidence_packet as packet_module

    calls: dict[str, int] = {}
    real = packet_module._load_bounded_json

    def _spy(path):
        calls[str(path)] = calls.get(str(path), 0) + 1
        return real(path)

    monkeypatch.setattr(packet_module, "_load_bounded_json", _spy)
    build_packet(chain)
    assert calls, "loader never invoked"
    assert all(count == 1 for count in calls.values()), calls


# ---------------------------------------------------------------------------
# NP10 integration: full structural validation of evaluation/lab inputs
# (failing-first corpus — pre-integration NP8 accepted every one of these)
# ---------------------------------------------------------------------------


def _mutated_artifact_file(tmp_path, source: pathlib.Path, name: str, mutate) -> pathlib.Path:
    payload = json.loads(source.read_text(encoding="utf-8"))
    mutate(payload)
    return _write(tmp_path / name, json.dumps(payload))


EVALUATION_INPUT_MUTATIONS = [
    ("unknown-extra-field", lambda a: a.__setitem__("surprise", 1)),
    ("malformed-envelope", lambda a: a["prediction"]["uniform_nll_bits"].__setitem__("status", "maybe")),
    ("invalid-chronology", lambda a: a["recovery"]["chronology"]["value"].__setitem__("first_violation_index", 1)),
]


@pytest.mark.parametrize("name,mutate", EVALUATION_INPUT_MUTATIONS,
                         ids=[m[0] for m in EVALUATION_INPUT_MUTATIONS])
def test_malformed_evaluation_inputs_rejected(chain, tmp_path, name, mutate) -> None:
    bad = _mutated_artifact_file(tmp_path, chain["evaluation"], f"bad_eval_{name}.json", mutate)
    with pytest.raises(PacketInputError, match="evaluation:"):
        build_packet({"evaluation": bad, "report": chain["report"]})


def _lab_counts_desync(a: dict) -> None:
    a["configurations"][0]["trajectory"]["reason_step_counts"]["unseen_state"] += 1


def _lab_duplicate_labels(a: dict) -> None:
    a["configurations"].append(json.loads(json.dumps(a["configurations"][0])))


def _lab_final_incoherent(a: dict) -> None:
    trajectory = a["configurations"][0]["trajectory"]
    trajectory["final_abstain"] = not trajectory["final_abstain"]


def _lab_truncation_lie(a: dict) -> None:
    a["configurations"][0]["trajectory"]["run_lengths_truncated"] = True


LAB_INPUT_MUTATIONS = [
    ("reason-counts-desync", _lab_counts_desync),
    ("duplicate-labels", _lab_duplicate_labels),
    ("final-incoherent", _lab_final_incoherent),
    ("truncation-lie", _lab_truncation_lie),
]


@pytest.mark.parametrize("name,mutate", LAB_INPUT_MUTATIONS,
                         ids=[m[0] for m in LAB_INPUT_MUTATIONS])
def test_malformed_lab_inputs_rejected(chain, tmp_path, name, mutate) -> None:
    bad = _mutated_artifact_file(tmp_path, chain["lab"], f"bad_lab_{name}.json", mutate)
    with pytest.raises(PacketInputError, match="lab:"):
        build_packet({"lab": bad, "protocol": chain["protocol"]})


def test_manifest_depth_is_full_for_evaluation_and_lab(chain) -> None:
    # With NP9 integrated, the honest depth label rises to "full" — the
    # only deliberate output change of the integration.
    packet = build_packet(chain)
    by_role = {entry["role"]: entry for entry in packet["artifacts"]}
    assert by_role["evaluation"]["validation"] == "full"
    assert by_role["lab"]["validation"] == "full"
    # Provenance results are unchanged by the integration.
    for kind, link in packet["links"].items():
        assert link["status"] == "verified", kind


def test_emitted_packet_is_self_validated(chain, monkeypatch) -> None:
    import scripts.nextness_artifact_validation as validation_module

    calls: list[int] = []
    real = validation_module.validate_evidence_packet

    def _spy(obj):
        calls.append(1)
        return real(obj)

    monkeypatch.setattr(validation_module, "validate_evidence_packet", _spy)
    build_packet({"log": chain["log"]})
    assert calls == [1]  # exactly one self-validation before serialization


def test_self_validation_failure_is_internal_not_input_error(chain, monkeypatch, capsys) -> None:
    # A failure while validating the packet NP8 JUST EMITTED is an
    # internal programming/contract failure — it must propagate loudly,
    # never masquerade as the documented exit-2 "malformed user input"
    # lane. External validator failures are wrapped as PacketInputError
    # at _validate_role (that is the exit-2 lane); the emitted-packet
    # self-check deliberately becomes RuntimeError instead.
    import scripts.nextness_artifact_validation as validation_module
    from scripts.nextness_artifact_validation import ArtifactValidationError

    def _boom(obj):
        raise ArtifactValidationError("injected internal contract failure")

    monkeypatch.setattr(validation_module, "validate_evidence_packet", _boom)
    with pytest.raises(RuntimeError, match="internal"):
        main(["--log", str(chain["log"])])
    # And a genuinely malformed EXTERNAL artifact still takes the
    # documented concise exit-2 lane (validator untouched for inputs).
    monkeypatch.undo()
    bad = chain["log"].parent / "bad_eval.json"
    bad.write_bytes(b'{"schema": "nextness-evaluation-v2"}')
    assert main(["--evaluation", str(bad)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "Traceback" not in err


# ---------------------------------------------------------------------------
# No ranking/scoring structure anywhere
# ---------------------------------------------------------------------------


def test_no_ranking_or_score_fields(chain) -> None:
    packet = build_packet(chain)
    forbidden = {"winner", "rank", "ranking", "best", "recommendation", "score"}

    def _walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                assert key.lower() not in forbidden
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(packet)
    assert packet["non_claims"]


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
    chain, tmp_path, capsys, monkeypatch
) -> None:
    import os
    import pathlib as _pathlib

    out = tmp_path / "packet.json"
    out.write_text("stale existing non-alias output\n", encoding="utf-8")
    before = {role: path.read_bytes() for role, path in chain.items()}
    out_before = out.read_bytes()
    entries_before = sorted(p.name for p in tmp_path.iterdir())
    out_resolved = out.resolve()
    real_samefile = os.path.samefile

    def probed(a, b):
        if _pathlib.Path(a).resolve() == out_resolved:
            raise PermissionError(13, "identity probe denied")
        return real_samefile(a, b)

    monkeypatch.setattr(os.path, "samefile", probed)
    assert main(_chain_args(chain) + ["--output", str(out)]) == 4
    captured = capsys.readouterr()
    lines = [l for l in captured.err.strip().splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("error:")
    assert "Traceback" not in captured.err
    for role, path in chain.items():
        assert path.read_bytes() == before[role], role
    assert out.read_bytes() == out_before
    assert sorted(p.name for p in tmp_path.iterdir()) == entries_before


def test_cli_unexpected_errors_are_not_hidden(chain, monkeypatch) -> None:
    import scripts.nextness_evidence_packet as packet_module

    def boom(*args, **kwargs):
        raise RuntimeError("sentinel propagation probe")

    monkeypatch.setattr(packet_module, "build_packet", boom)
    with pytest.raises(RuntimeError, match="sentinel propagation probe"):
        main(_chain_args(chain))


# ---------------------------------------------------------------------------
# Evidence-packet typed-input-boundary pilot (gated;
# docs/NEXTNESS_CLI_FAILURE_CONTRACTS.md). Failing-first target: a sentinel
# plain ValueError escaping the internal build seam must PROPAGATE through
# public main(), never convert to the documented exit-2 input lane. Uses the
# same build_packet monkeypatch seam as the sentinel-RuntimeError pin above.
# ---------------------------------------------------------------------------


def test_cli_internal_plain_valueerror_propagates(chain, monkeypatch) -> None:
    """Pilot pin: an internal plain ValueError from the packet's build
    seam is an unexpected programming error and must propagate — not
    masquerade as a concise exit-2 input failure. (PacketInputError and
    the wrapped validator errors remain the documented exit-2 lane.)"""
    import scripts.nextness_evidence_packet as packet_module

    def boom(*args, **kwargs):
        raise ValueError("sentinel plain ValueError probe")

    monkeypatch.setattr(packet_module, "build_packet", boom)
    with pytest.raises(ValueError, match="sentinel plain ValueError probe"):
        main(_chain_args(chain))


def test_cli_packet_input_error_still_exit_2(chain, monkeypatch, capsys) -> None:
    """Typed PacketInputError remains the documented exit-2 lane: one
    concise error: line, byte-identical message shape, no traceback."""
    import scripts.nextness_evidence_packet as packet_module
    from scripts.nextness_evidence_packet import PacketInputError

    def typed_boom(*args, **kwargs):
        raise PacketInputError("sentinel typed input failure")

    monkeypatch.setattr(packet_module, "build_packet", typed_boom)
    assert main(_chain_args(chain)) == 2
    err = capsys.readouterr().err
    lines = [l for l in err.strip().splitlines() if l.strip()]
    assert lines == ["error: sentinel typed input failure"]
    assert "Traceback" not in err


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


def test_cli_output_open_denial_pinned(chain, tmp_path, capsys, monkeypatch) -> None:
    """Open denial: no truncation ever happened — existing destination,
    inputs and directory inventory all byte-identical; exit 4, one line."""
    _ = tmp_path  # chain fixture provides inputs in tmp_path
    out = tmp_path / "stage_pin.out"
    out.write_text("pre-existing destination\n", encoding="utf-8")
    before = {p: p.read_bytes() for p in list(chain.values()) + [out]}
    inv = sorted(p.name for p in tmp_path.iterdir())
    state = _patch_output_stage(monkeypatch, out.resolve(), deny_open=True)
    assert main(_chain_args(chain) + ["--output", str(out)]) == 4
    _stage_exit4_receipt(capsys)
    assert state["opens"] == 1 and state["proxy"] is None  # failed AT open
    for p, b in before.items():
        assert p.read_bytes() == b
    assert sorted(p.name for p in tmp_path.iterdir()) == inv


def test_cli_post_open_write_failure_pinned(chain, tmp_path, capsys, monkeypatch) -> None:
    """Post-open failure of the FIRST whole-buffer write: open succeeded,
    zero writes completed, destination truncated to empty; inputs
    unchanged; exit 4 with one concise line."""
    _ = tmp_path  # chain fixture provides inputs in tmp_path
    out = tmp_path / "stage_pin.out"
    out.write_text("stale bytes to observe truncation\n", encoding="utf-8")
    before = {p: p.read_bytes() for p in list(chain.values())}
    state = _patch_output_stage(monkeypatch, out.resolve(), fail_write_at=1)
    assert main(_chain_args(chain) + ["--output", str(out)]) == 4
    _stage_exit4_receipt(capsys)
    assert state["opens"] == 1 and state["proxy"] is not None  # open SUCCEEDED
    assert state["proxy"].writes_ok == 0                       # first write failed
    assert out.exists() and out.stat().st_size == 0            # truncated-empty
    for p, b in before.items():
        assert p.read_bytes() == b


def test_cli_close_time_failure_pinned(chain, tmp_path, capsys, monkeypatch) -> None:
    """Close-time failure: every write succeeded, the context exit raised —
    the destination holds the COMPLETE canonical serialized bytes although
    the run reports exit 4."""
    _ = tmp_path  # chain fixture provides inputs in tmp_path
    canon = tmp_path / "canonical.out"
    assert main(_chain_args(chain) + ["--output", str(canon)]) == 0          # capture canonical success bytes
    capsys.readouterr()
    canonical = canon.read_bytes()
    out = tmp_path / "stage_pin.out"
    before = {p: p.read_bytes() for p in list(chain.values())}
    state = _patch_output_stage(monkeypatch, out.resolve(), fail_close=True)
    assert main(_chain_args(chain) + ["--output", str(out)]) == 4
    _stage_exit4_receipt(capsys)
    assert state["opens"] == 1 and state["proxy"] is not None
    assert state["proxy"].writes_ok == 1                       # whole buffer written
    assert state["proxy"].close_attempted                      # failure was AT close
    assert out.read_bytes() == canonical                       # complete bytes present
    for p, b in before.items():
        assert p.read_bytes() == b


# ---------------------------------------------------------------------------
# Read-side propagation pin (commits the post-train audit's probe-only
# claim): an argument-conditional read-side PermissionError on the
# primary input propagates unchanged through public main() — exact
# identity and message, no concise stderr conversion, inputs
# byte-identical, no destination created. The patch matches ONLY the
# resolved victim path in a read mode, so output-write lanes are never
# accidentally exercised.
# ---------------------------------------------------------------------------


def test_cli_read_side_oserror_propagates(chain, tmp_path, monkeypatch, capsys) -> None:
    out = tmp_path / "never_written.out"
    inputs = list(chain.values())
    before = {p: p.read_bytes() for p in inputs}
    victim = chain["report"].resolve()
    real_open = pathlib.Path.open

    def patched(self, mode="r", *args, **kwargs):
        if "r" in mode and "w" not in mode and self.resolve() == victim:
            raise PermissionError(13, "injected read denial")
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "open", patched)
    with pytest.raises(PermissionError) as excinfo:
        main(_chain_args(chain) + ["--output", str(out)])
    monkeypatch.undo()
    assert type(excinfo.value) is PermissionError
    assert excinfo.value.errno == 13
    assert excinfo.value.strerror == "injected read denial"
    captured = capsys.readouterr()
    assert captured.out == ""  # the CLI emitted nothing
    assert captured.err == ""  # no misleading concise conversion
    assert not out.exists()
    for p, b in before.items():
        assert p.read_bytes() == b


# ---------------------------------------------------------------------------
# Batch 3 — hook-free type diagnostics + exact-string field lookup
# (Option-B family policy). Refusals must be typed PacketInputError whose
# formatting reads NO attribute of the rejected value or of its class, and
# _exact_dict_field must never run a hook of an unproven key — nor let a
# hash-colliding foreign key satisfy a required string field.
# ---------------------------------------------------------------------------


class _RaisingMeta(type):
    """Metaclass whose __name__ property raises — even type(x).__name__ is a
    user-controlled hook."""

    ran = False

    @property
    def __name__(cls):
        _RaisingMeta.ran = True
        raise RuntimeError("metaclass __name__ hook executed")


class _MetaBomb(metaclass=_RaisingMeta):
    pass


class _StrictCollisionKey(metaclass=_RaisingMeta):
    """A non-str key hashing EXACTLY like a target str, every hook armed.

    ``__hash__`` is inert only until armed, permitting the single hash needed
    to plant the collision in a dict; after arming the lookup must not hash,
    compare or represent it either.
    """

    fired: list[str] = []
    armed = False

    def __init__(self, target: str) -> None:
        self._h = hash(target)

    def __hash__(self) -> int:
        if _StrictCollisionKey.armed:
            _StrictCollisionKey.fired.append("__hash__")
            raise RuntimeError("__hash__ hook executed")
        return self._h

    def __eq__(self, other):
        _StrictCollisionKey.fired.append("__eq__")
        raise RuntimeError("__eq__ hook executed")

    def __repr__(self):
        _StrictCollisionKey.fired.append("__repr__")
        raise RuntimeError("__repr__ hook executed")


class _SoftCollisionKey:
    """Hash-collides with a target str AND compares equal — the soundness
    variant that used to satisfy a required field and supply its value."""

    def __init__(self, target: str) -> None:
        self._h = hash(target)

    def __hash__(self) -> int:
        return self._h

    def __eq__(self, other):
        return True


def _packet_arm() -> None:
    _RaisingMeta.ran = False
    _StrictCollisionKey.fired.clear()
    _StrictCollisionKey.armed = False


def test_packet_hostile_metaclass_never_consulted_at_any_site() -> None:
    """All four supplied-value diagnostics refuse with the exact typed error
    and the generic description, without consulting the metaclass."""
    from scripts.nextness_evidence_packet import (
        PacketInputError,
        _evaluation_link,
        _exact_dict_field,
        _recorded_reader_bounds,
    )

    cases = [
        (lambda: _exact_dict_field(_MetaBomb(), "x", "ctx"),
         "ctx: expected builtin dict, got non-builtin value"),
        (lambda: _evaluation_link({"artifacts": {"lab": {"provided": _MetaBomb()}}}, "lab", None),
         "evaluation.artifacts.lab.provided: expected builtin bool, "
         "got non-builtin value"),
        (lambda: _recorded_reader_bounds({"config": {"max_rows": _MetaBomb(),
                                                     "max_line_bytes": 1}}),
         "lab.config.max_rows: expected builtin int, got non-builtin value"),
        (lambda: _recorded_reader_bounds({"config": {"max_rows": 1,
                                                     "max_line_bytes": _MetaBomb()}}),
         "lab.config.max_line_bytes: expected builtin int, got non-builtin value"),
    ]
    for call, expected in cases:
        _packet_arm()
        with pytest.raises(PacketInputError) as excinfo:
            call()
        assert type(excinfo.value) is PacketInputError
        assert str(excinfo.value) == expected
        assert _RaisingMeta.ran is False


def test_packet_strict_collision_key_runs_no_hook_at_all() -> None:
    """A foreign key colliding with a required field name must never have
    __hash__/__eq__/__repr__/metaclass __name__ invoked by the lookup."""
    from scripts.nextness_evidence_packet import PacketInputError, _exact_dict_field

    _packet_arm()
    container = {_StrictCollisionKey("schema"): 1}
    _StrictCollisionKey.armed = True  # planted: no further hash allowed
    try:
        with pytest.raises(PacketInputError) as excinfo:
            _exact_dict_field(container, "schema", "ctx")
        assert type(excinfo.value) is PacketInputError
        assert str(excinfo.value) == "ctx: missing field 'schema'"
        assert _StrictCollisionKey.fired == []
        assert _RaisingMeta.ran is False
    finally:
        _StrictCollisionKey.armed = False


def test_packet_collision_key_can_never_satisfy_a_required_field() -> None:
    """Soundness: a colliding key whose __eq__ returns True previously
    satisfied the field AND supplied its own value as the field's content."""
    from scripts.nextness_evidence_packet import PacketInputError, _exact_dict_field

    container = {_SoftCollisionKey("schema"): "HOSTILE-VALUE"}
    with pytest.raises(PacketInputError) as excinfo:
        _exact_dict_field(container, "schema", "ctx")
    assert str(excinfo.value) == "ctx: missing field 'schema'"


def test_packet_genuine_field_wins_beside_a_foreign_key() -> None:
    """A container carrying both a hostile foreign key and the genuine exact
    string field returns the genuine value, firing no hook."""
    from scripts.nextness_evidence_packet import _exact_dict_field

    _packet_arm()
    container = {_MetaBomb(): "HOSTILE", "schema": "GENUINE"}
    assert _exact_dict_field(container, "schema", "ctx") == "GENUINE"
    assert _RaisingMeta.ran is False
    assert _StrictCollisionKey.fired == []


def test_packet_builtin_lane_diagnostics_are_byte_identical() -> None:
    """PUBLIC/ARTIFACT lane keeps every message, exception type and range
    message byte-for-byte."""
    from scripts.nextness_evidence_packet import (
        PacketInputError,
        _evaluation_link,
        _exact_dict_field,
        _recorded_reader_bounds,
    )

    matrix = [
        (lambda: _exact_dict_field([], "x", "ctx"),
         "ctx: expected builtin dict, got list"),
        (lambda: _exact_dict_field({}, "x", "ctx"),
         "ctx: missing field 'x'"),
        (lambda: _evaluation_link({"artifacts": {"lab": {"provided": 1}}}, "lab", None),
         "evaluation.artifacts.lab.provided: expected builtin bool, got int"),
        (lambda: _recorded_reader_bounds({"config": {"max_rows": "x", "max_line_bytes": 1}}),
         "lab.config.max_rows: expected builtin int, got str"),
        (lambda: _recorded_reader_bounds({"config": {"max_rows": 0, "max_line_bytes": 1}}),
         "lab.config.max_rows: 0 outside (0, 1000000]"),
        (lambda: _recorded_reader_bounds({"config": {"max_rows": 1, "max_line_bytes": "x"}}),
         "lab.config.max_line_bytes: expected builtin int, got str"),
        (lambda: _recorded_reader_bounds({"config": {"max_rows": 1, "max_line_bytes": 0}}),
         "lab.config.max_line_bytes: 0 outside [1, 16777216]"),
    ]
    for call, expected in matrix:
        with pytest.raises(PacketInputError) as excinfo:
            call()
        assert type(excinfo.value) is PacketInputError
        assert str(excinfo.value) == expected


def test_packet_exact_dict_field_returns_the_value_unchanged() -> None:
    """Accepted lookups are unaffected and return the stored object itself."""
    from scripts.nextness_evidence_packet import _exact_dict_field

    sentinel = {"nested": 1}
    container = {"a": 0, "x": sentinel}
    assert _exact_dict_field(container, "x", "ctx") is sentinel


def test_packet_describe_type_is_hook_free_and_names_builtins() -> None:
    """Identity table only: builtins by literal name, everything else generic."""
    from scripts.nextness_evidence_packet import _describe_type

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
    assert _describe_type(int) == "non-builtin value"
    _packet_arm()
    assert _describe_type(_MetaBomb()) == "non-builtin value"
    assert _RaisingMeta.ran is False


# ---------------------------------------------------------------------------
# Outer role-map boundary (DIRECT API only — the public CLI builds this map
# itself with exact builtin str roles). build_packet() and
# validate_output_path() previously consumed the caller's mapping directly
# via set(), `in`, subscript and list rendering.
# ---------------------------------------------------------------------------


_ROLE_MAP_NOT_DICT = "artifact role map: expected a builtin dict"
_ROLE_MAP_FOREIGN_KEY = "artifact role map: role keys must be builtin strings"


class _ReprBombKey:
    """Foreign role key whose __repr__ raises — the unknown-roles message
    rendered the key list, which repr()s every element."""

    fired: list[str] = []

    def __repr__(self):
        _ReprBombKey.fired.append("__repr__")
        raise RuntimeError("__repr__ hook executed")


class _SoftCollidingRole:
    """Collides with a real role AND compares equal: used to satisfy that
    role and supply its own value."""

    def __init__(self, target: str) -> None:
        self._h = hash(target)

    def __hash__(self) -> int:
        return self._h

    def __eq__(self, other):
        return True


class _HardCollidingRole:
    """Collides with a real role; every comparison/representation raises."""

    fired: list[str] = []

    def __init__(self, target: str) -> None:
        self._h = hash(target)

    def __hash__(self) -> int:
        return self._h

    def __eq__(self, other):
        _HardCollidingRole.fired.append("__eq__")
        raise RuntimeError("__eq__ hook executed")

    def __repr__(self):
        _HardCollidingRole.fired.append("__repr__")
        raise RuntimeError("__repr__ hook executed")


class _HostileRoleDict(dict):
    """An exact-dict SUBCLASS whose iteration hooks are armed."""

    fired: list[str] = []

    def items(self):
        _HostileRoleDict.fired.append("items")
        raise RuntimeError("items hook executed")

    def keys(self):
        _HostileRoleDict.fired.append("keys")
        raise RuntimeError("keys hook executed")

    def __iter__(self):
        _HostileRoleDict.fired.append("__iter__")
        raise RuntimeError("__iter__ hook executed")


def _role_map_arm() -> None:
    _ReprBombKey.fired.clear()
    _HardCollidingRole.fired.clear()
    _HostileRoleDict.fired.clear()


def test_role_map_foreign_key_repr_never_runs(chain) -> None:
    """A foreign role key whose __repr__ raises used to escape from
    build_packet() when the unknown-roles message rendered the key list."""
    from scripts.nextness_evidence_packet import PacketInputError, build_packet

    _role_map_arm()
    with pytest.raises(PacketInputError) as excinfo:
        build_packet({_ReprBombKey(): chain["report"]})
    assert str(excinfo.value) == _ROLE_MAP_FOREIGN_KEY
    assert _ReprBombKey.fired == []


def test_role_map_collision_cannot_satisfy_a_role_in_build_packet(chain) -> None:
    """A key colliding with 'report' and comparing equal used to satisfy that
    role and supply its own value as the artifact."""
    from scripts.nextness_evidence_packet import PacketInputError, build_packet

    with pytest.raises(PacketInputError) as excinfo:
        build_packet({_SoftCollidingRole("report"): chain["report"]})
    assert str(excinfo.value) == _ROLE_MAP_FOREIGN_KEY


def test_role_map_hard_collision_runs_no_hook_in_validate_output_path(chain, tmp_path) -> None:
    """Primary-role selection used to hash and compare caller keys."""
    from scripts.nextness_evidence_packet import PacketInputError, validate_output_path

    _role_map_arm()
    out = chain["report"].parent / "packet.json"
    with pytest.raises(PacketInputError) as excinfo:
        validate_output_path(out, {_HardCollidingRole("report"): chain["report"]})
    assert str(excinfo.value) == _ROLE_MAP_FOREIGN_KEY
    assert _HardCollidingRole.fired == []


def test_role_map_collision_cannot_supply_the_primary_input(chain) -> None:
    """A soft-colliding key used to be ACCEPTED by validate_output_path and
    supply the primary input that anchors the whole write boundary."""
    from scripts.nextness_evidence_packet import PacketInputError, validate_output_path

    out = chain["report"].parent / "packet.json"
    with pytest.raises(PacketInputError) as excinfo:
        validate_output_path(out, {_SoftCollidingRole("report"): chain["report"]})
    assert str(excinfo.value) == _ROLE_MAP_FOREIGN_KEY


def test_role_map_foreign_key_is_rejected_beside_a_genuine_role(chain) -> None:
    """A foreign key must be refused, never silently ignored, even when a
    genuine role is present in the same mapping."""
    from scripts.nextness_evidence_packet import PacketInputError, build_packet

    _role_map_arm()
    with pytest.raises(PacketInputError) as excinfo:
        build_packet({_ReprBombKey(): chain["report"], "report": chain["report"]})
    assert str(excinfo.value) == _ROLE_MAP_FOREIGN_KEY
    assert _ReprBombKey.fired == []


def test_role_map_dict_subclass_iteration_hooks_never_run(chain) -> None:
    """Only an exact builtin dict is accepted, so a subclass is refused
    before any of its iteration hooks can interpose."""
    from scripts.nextness_evidence_packet import (
        PacketInputError,
        build_packet,
        validate_output_path,
    )

    out = chain["report"].parent / "packet.json"
    for call in (
        lambda: build_packet(_HostileRoleDict({"report": chain["report"]})),
        lambda: validate_output_path(out, _HostileRoleDict({"report": chain["report"]})),
    ):
        _role_map_arm()
        with pytest.raises(PacketInputError) as excinfo:
            call()
        assert str(excinfo.value) == _ROLE_MAP_NOT_DICT
        assert _HostileRoleDict.fired == []


def test_role_map_refusals_report_no_supplied_type_name(chain) -> None:
    """Both refusals are generic: neither names the supplied type."""
    from scripts.nextness_evidence_packet import PacketInputError, build_packet

    for bad in ([("report", chain["report"])], ("report",), None):
        with pytest.raises(PacketInputError) as excinfo:
            build_packet(bad)
        message = str(excinfo.value)
        assert message == _ROLE_MAP_NOT_DICT
        for leaked in ("list", "tuple", "NoneType", "non-builtin"):
            assert leaked not in message


def test_role_map_preserves_public_messages_and_valid_inputs(chain) -> None:
    """Valid exact-dict DIRECT inputs and every pre-existing public message
    are unchanged."""
    from scripts.nextness_evidence_packet import (
        PacketInputError,
        build_packet,
        validate_output_path,
    )

    with pytest.raises(PacketInputError) as excinfo:
        build_packet({})
    assert str(excinfo.value) == "no artifacts provided: nothing to package"

    with pytest.raises(PacketInputError) as excinfo:
        build_packet({"bogus": chain["report"]})
    assert str(excinfo.value) == "unknown artifact roles: ['bogus']"

    # A valid exact dict still builds, and the write boundary still accepts.
    packet = build_packet(chain)
    assert packet["schema"] == PACKET_SCHEMA
    validate_output_path(chain["report"].parent / "packet.json", chain)


# ---------------------------------------------------------------------------
# Complete role-map grammar: exact-dict identity, emptiness and the artifact
# ceiling are decided BEFORE any key is traversed; unknown roles are refused
# on proven exact strings. Both entry points rely on this boundary alone.
# ---------------------------------------------------------------------------


class _ArmableRoleKey:
    """A foreign key that can be planted (inert hash) and then armed, so a
    test can prove the ceiling refuses before ANY key hook executes."""

    fired: list[str] = []
    armed = False

    def __hash__(self) -> int:
        if _ArmableRoleKey.armed:
            _ArmableRoleKey.fired.append("__hash__")
            raise RuntimeError("__hash__ hook executed")
        return 0

    def __eq__(self, other):
        _ArmableRoleKey.fired.append("__eq__")
        raise RuntimeError("__eq__ hook executed")

    def __repr__(self):
        _ArmableRoleKey.fired.append("__repr__")
        raise RuntimeError("__repr__ hook executed")


def test_role_map_ceiling_refuses_before_any_key_hook(chain) -> None:
    """A nine-entry map is refused by the exact-dict ceiling before the map
    is traversed, so a hostile key planted inside it is never touched."""
    from scripts.nextness_evidence_packet import (
        MAX_PACKET_ARTIFACTS,
        PacketInputError,
        build_packet,
    )

    _ArmableRoleKey.fired.clear()
    _ArmableRoleKey.armed = False
    payload = {f"r{i}": chain["report"] for i in range(8)}
    payload[_ArmableRoleKey()] = chain["report"]  # planted while inert
    _ArmableRoleKey.armed = True
    try:
        assert len(payload) == MAX_PACKET_ARTIFACTS + 1
        with pytest.raises(PacketInputError) as excinfo:
            build_packet(payload)
        assert str(excinfo.value) == f"9 artifacts exceed the {MAX_PACKET_ARTIFACTS} bound"
        assert _ArmableRoleKey.fired == []
    finally:
        _ArmableRoleKey.armed = False


def test_role_map_large_map_diagnostic_stays_short(chain) -> None:
    """An oversized map must not be rendered: the refusal names a count, not
    ten thousand keys."""
    from scripts.nextness_evidence_packet import (
        MAX_PACKET_ARTIFACTS,
        PacketInputError,
        build_packet,
    )

    payload = {f"r{i}": chain["report"] for i in range(10_000)}
    with pytest.raises(PacketInputError) as excinfo:
        build_packet(payload)
    message = str(excinfo.value)
    assert message == f"10000 artifacts exceed the {MAX_PACKET_ARTIFACTS} bound"
    assert len(message) < 64
    assert "r0" not in message and "r9999" not in message


def test_output_alias_refused_for_an_unknown_role(chain) -> None:
    """The alias sweep only walks ROLES, so an UNKNOWN role naming the output
    path used to slip past it entirely and validate successfully."""
    from scripts.nextness_evidence_packet import PacketInputError, validate_output_path

    out = chain["report"].parent / "packet.json"
    out.write_bytes(b"PRE-EXISTING")
    before_out = out.read_bytes()
    before_report = chain["report"].read_bytes()

    with pytest.raises(PacketInputError) as excinfo:
        validate_output_path(out, {"report": chain["report"], "bogus": out})
    assert str(excinfo.value) == "unknown artifact roles: ['bogus']"
    assert out.read_bytes() == before_out
    assert chain["report"].read_bytes() == before_report


def test_output_validation_unknown_only_is_typed_not_stopiteration(chain) -> None:
    """A map with no known role used to fall out of primary-role selection as
    a bare StopIteration."""
    from scripts.nextness_evidence_packet import PacketInputError, validate_output_path

    out = chain["report"].parent / "packet.json"
    with pytest.raises(PacketInputError) as excinfo:
        validate_output_path(out, {"bogus": chain["report"]})
    assert type(excinfo.value) is PacketInputError
    assert str(excinfo.value) == "unknown artifact roles: ['bogus']"

    with pytest.raises(PacketInputError):  # never StopIteration
        validate_output_path(out, {"nope": chain["report"], "alsonope": chain["report"]})


def test_output_validation_empty_map_uses_the_no_artifacts_message(chain) -> None:
    """An empty map reaches the established no-artifacts refusal, not
    StopIteration."""
    from scripts.nextness_evidence_packet import PacketInputError, validate_output_path

    out = chain["report"].parent / "packet.json"
    with pytest.raises(PacketInputError) as excinfo:
        validate_output_path(out, {})
    assert str(excinfo.value) == "no artifacts provided: nothing to package"


def test_valid_exact_dict_behaviour_is_unchanged(chain) -> None:
    """Valid exact-dict input still builds identically and still validates."""
    from scripts.nextness_evidence_packet import (
        build_packet,
        serialize_packet,
        validate_output_path,
    )

    first = serialize_packet(build_packet(chain))
    second = serialize_packet(build_packet(dict(chain)))
    assert first == second  # byte-identical across repeated runs
    validate_output_path(chain["report"].parent / "packet.json", chain)
    # A single-role exact dict remains acceptable.
    assert build_packet({"log": chain["log"]})["schema"] == PACKET_SCHEMA
