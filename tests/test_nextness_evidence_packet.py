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
    # No public validator exists for these two — the depth says so.
    assert by_role["evaluation"]["validation"] == "schema_identifier_only"
    assert by_role["lab"]["validation"] == "schema_identifier_only"
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


def test_cli_data_tree_refused(chain, tmp_path, capsys, monkeypatch) -> None:
    import scripts.nextness_evidence_packet as packet_module

    monkeypatch.setattr(
        packet_module, "_repo_data_dir", lambda: chain["log"].parent.resolve()
    )
    assert main(_chain_args(chain) + ["--output", str(chain["log"].parent / "p.json")]) == 4
    assert "data/ tree" in capsys.readouterr().err


def test_cli_oversized_packet_exit_5(chain, capsys, monkeypatch) -> None:
    import scripts.nextness_evidence_packet as packet_module

    monkeypatch.setattr(packet_module, "MAX_PACKET_BYTES", 64)
    assert main(_chain_args(chain)) == 5
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
