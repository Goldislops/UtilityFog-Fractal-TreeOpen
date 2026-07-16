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
    # lane (ArtifactValidationError inherits ValueError, which main
    # catches for external artifacts).
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
