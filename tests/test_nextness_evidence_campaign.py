"""Tests for scripts/nextness_evidence_campaign.py (campaign contract 3.10).

Synthetic tmp_path fixtures only: no real Medusa artifact, no network, no
engine, no observer or calibration execution. Every test builds its own
workspace under pytest's tmp_path; nothing touches the repository data/
tree (the data-exclusion test itself patches the campaign's _repo_data_dir
to a tmp directory).
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import pathlib
import shutil

import pytest

import scripts.nextness_evidence_campaign as campaign
from scripts.nextness_evaluator import EvaluatorInputError
from scripts.nextness_evidence_packet import PacketInputError
from scripts.nextness_predictor import (
    MAX_LINE_BYTES_DEFAULT,
    MAX_ROWS_CEILING,
    MAX_ROWS_DEFAULT,
    TOKEN_NAMES,
    PredictorInputError,
)
from scripts.nextness_replay_lab import LabInputError, build_lab_report

# ---------------------------------------------------------------------------
# Fixture helpers (synthetic, deterministic)
# ---------------------------------------------------------------------------


def _log_rows(n: int) -> list[bytes]:
    rows = []
    for i in range(n):
        row = {"generation": i, "token_counts": {TOKEN_NAMES[i % 3]: 5}}
        rows.append(json.dumps(row, sort_keys=True).encode("utf-8"))
    return rows


def _write_log(path: pathlib.Path, n: int = 40) -> None:
    path.write_bytes(b"".join(row + b"\n" for row in _log_rows(n)))


def _protocol_dict(**overrides):
    protocol = {
        "schema": "nextness-replay-protocol-v1",
        "model": "first_order",
        "smoothing": 1.0,
        "holdout_fraction": 0.25,
        "configurations": [
            {
                "label": "primary",
                "min_history": 5,
                "window": 50,
                "low_confidence_threshold": 0.3,
                "calibration_error_threshold": 0.2,
                "drift_threshold_bits": 0.15,
            },
            {
                "label": "secondary",
                "min_history": 6,
                "window": 60,
                "low_confidence_threshold": 0.35,
                "calibration_error_threshold": 0.25,
                "drift_threshold_bits": 0.2,
            },
        ],
    }
    protocol.update(overrides)
    return protocol


def _write_protocol(path: pathlib.Path, **overrides) -> None:
    path.write_bytes(
        json.dumps(_protocol_dict(**overrides), sort_keys=True).encode("utf-8")
    )


@pytest.fixture()
def ws(tmp_path):
    """A standard campaign workspace: valid log + protocol, absent out dir."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_log(workspace / "log.jsonl")
    _write_protocol(workspace / "protocol.json")
    return workspace


def _argv(workspace, *, label="primary", out="campaign_out", extra=()):
    return [
        str(workspace / "log.jsonl"),
        str(workspace / "protocol.json"),
        "--workspace-dir",
        str(workspace),
        "--receipt-config-label",
        label,
        "--output-dir",
        str(workspace / out),
        *extra,
    ]


def _read_published(workspace, out="campaign_out"):
    final = workspace / out
    return {p.name: p.read_bytes() for p in final.iterdir()}


def _load_json(workspace, out, name):
    return json.loads((workspace / out / name).read_text(encoding="utf-8"))


def _assert_one_error_line(err: str) -> None:
    assert err.startswith("error:")
    assert err.count("\n") == 1 and err.endswith("\n")
    assert "Traceback" not in err


def _staging_residue(parent: pathlib.Path) -> list[str]:
    return [
        p.name
        for p in parent.iterdir()
        if p.name.startswith(".nextness-campaign-staging-")
    ]


# ---------------------------------------------------------------------------
# Success path: publication set, determinism, provenance, coherence
# ---------------------------------------------------------------------------


def test_success_exact_eight_file_publication(ws, capsys):
    rc = campaign.main(_argv(ws))
    out, err = capsys.readouterr().out, capsys.readouterr().err
    assert rc == 0
    assert err == ""
    assert out.startswith("published: ")
    assert out.count("\n") == 1
    published = _read_published(ws)
    assert sorted(published) == sorted(campaign.PUBLICATION_FILENAMES)
    assert len(published) == 8
    # Metrics artifacts are absent from the set by contract.
    assert not any("metrics" in name for name in published)


def test_byte_identical_repeated_campaigns(ws, capsys):
    assert campaign.main(_argv(ws, out="run_one")) == 0
    assert campaign.main(_argv(ws, out="run_two")) == 0
    capsys.readouterr()
    first = _read_published(ws, "run_one")
    second = _read_published(ws, "run_two")
    assert sorted(first) == sorted(second)
    for name in first:
        assert first[name] == second[name], f"{name} differs between runs"


def test_all_four_np8_provenance_links_verified(ws, capsys):
    assert campaign.main(_argv(ws)) == 0
    capsys.readouterr()
    packet = _load_json(ws, "campaign_out", campaign.PACKET_FILENAME)
    for kind in (
        "evaluation_report_sha256",
        "evaluation_receipts_sha256",
        "lab_protocol_sha256",
        "lab_sequence_sha256",
    ):
        assert packet["links"][kind]["status"] == "verified", kind
    manifest = _load_json(ws, "campaign_out", campaign.MANIFEST_FILENAME)
    assert all(v == "verified" for v in manifest["np8_links"].values())


def test_manifest_validation(ws, capsys):
    assert campaign.main(_argv(ws)) == 0
    capsys.readouterr()
    out_dir = ws / "campaign_out"
    raw = (out_dir / campaign.MANIFEST_FILENAME).read_bytes()
    assert len(raw) <= campaign.MAX_CAMPAIGN_MANIFEST_BYTES
    manifest = json.loads(raw.decode("utf-8"))
    assert manifest["schema"] == "nextness-evidence-campaign-v1"
    assert (
        manifest["config"]["max_campaign_manifest_bytes"]
        == campaign.MAX_CAMPAIGN_MANIFEST_BYTES
    )
    # Relative filenames only; no absolute path (in particular not the
    # workspace path) leaks into the manifest bytes.
    text = raw.decode("utf-8")
    assert str(ws) not in text
    assert str(ws).replace(os.sep, "\\\\") not in text
    assert str(ws).replace(os.sep, "/") not in text
    # The seven non-manifest files are recorded with matching size + hash;
    # the manifest never records its own hash.
    recorded = {
        entry["filename"]: entry
        for entry in (*manifest["inputs"].values(), *manifest["artifacts"].values())
    }
    assert sorted(recorded) == sorted(
        n for n in campaign.PUBLICATION_FILENAMES if n != campaign.MANIFEST_FILENAME
    )
    for filename, entry in recorded.items():
        actual = (out_dir / filename).read_bytes()
        assert entry["bytes"] == len(actual), filename
        assert entry["sha256"] == hashlib.sha256(actual).hexdigest(), filename
    assert campaign.MANIFEST_FILENAME not in json.dumps(recorded)
    # Completeness evidence: campaign bounds echoed, both outcomes held.
    completeness = manifest["completeness"]
    assert completeness["max_rows"] == MAX_ROWS_DEFAULT
    assert completeness["max_line_bytes"] == MAX_LINE_BYTES_DEFAULT
    assert completeness["no_record_beyond_max_rows"] is True
    assert completeness["no_oversized_record"] is True
    # The natural same-source campaign computes consistent verdicts, and
    # the manifest carries NP5's envelope unchanged.
    evaluation = _load_json(ws, "campaign_out", campaign.EVALUATION_FILENAME)
    assert manifest["cross_check"] == {
        "ece_match": evaluation["cross_check"]["ece_match"],
        "surprise_nll_match": evaluation["cross_check"]["surprise_nll_match"],
    }
    for check in manifest["cross_check"].values():
        assert check["status"] == "computed"
        assert all(r["verdict"] == "consistent" for r in check["value"]["results"])
    # The published receipt is a single receipt object, not a series array.
    receipt = _load_json(ws, "campaign_out", campaign.RECEIPT_FILENAME)
    assert receipt["schema"] == "nextness-monitor-v1"
    assert manifest["non_claims"] == list(campaign.NON_CLAIMS)


# ---------------------------------------------------------------------------
# Configuration selection: explicit, no implicit winner
# ---------------------------------------------------------------------------


def test_explicit_configuration_selection_drives_receipt(ws, capsys):
    assert campaign.main(_argv(ws, label="secondary")) == 0
    capsys.readouterr()
    receipt = _load_json(ws, "campaign_out", campaign.RECEIPT_FILENAME)
    assert receipt["config"] == {
        "min_history": 6,
        "window": 60,
        "low_confidence_threshold": 0.35,
        "calibration_error_threshold": 0.25,
        "drift_threshold_bits": 0.2,
    }
    manifest = _load_json(ws, "campaign_out", campaign.MANIFEST_FILENAME)
    assert manifest["receipt_config_label"] == "secondary"
    assert manifest["receipt_config"] == receipt["config"]


def test_missing_label_is_argparse_usage_exit2(ws, capsys):
    argv = _argv(ws)
    idx = argv.index("--receipt-config-label")
    del argv[idx : idx + 2]
    with pytest.raises(SystemExit) as excinfo:
        campaign.main(argv)
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "usage:" in err
    assert "Traceback" not in err


def test_unknown_label_refuses_exit2(ws, capsys):
    rc = campaign.main(_argv(ws, label="no-such-label"))
    err = capsys.readouterr().err
    assert rc == 2
    _assert_one_error_line(err)
    assert "no-such-label" in err
    assert not (ws / "campaign_out").exists()


def test_duplicate_label_refuses_exit2(ws, capsys):
    protocol = _protocol_dict()
    protocol["configurations"][1]["label"] = "primary"
    (ws / "protocol.json").write_bytes(
        json.dumps(protocol, sort_keys=True).encode("utf-8")
    )
    rc = campaign.main(_argv(ws))
    err = capsys.readouterr().err
    assert rc == 2
    _assert_one_error_line(err)
    assert "duplicate" in err


def test_all_configurations_retained_without_winner(ws, capsys):
    assert campaign.main(_argv(ws)) == 0
    capsys.readouterr()
    lab = _load_json(ws, "campaign_out", campaign.LAB_FILENAME)
    labels = [entry["label"] for entry in lab["configurations"]]
    assert labels == ["primary", "secondary"]  # operator order, all retained
    for entry in lab["configurations"]:
        assert sorted(entry) == ["config", "label", "trajectory"]
        for key in entry["trajectory"]:
            assert "winner" not in key and "rank" not in key and "score" not in key
    manifest = _load_json(ws, "campaign_out", campaign.MANIFEST_FILENAME)
    assert "winner" not in json.dumps(manifest)


# ---------------------------------------------------------------------------
# Complete-log preflight (contract section 3.6)
# ---------------------------------------------------------------------------


def test_excess_row_refusal_exit2(ws, capsys):
    _write_log(ws / "log.jsonl", 11)
    rc = campaign.main(_argv(ws, extra=("--max-rows", "10")))
    err = capsys.readouterr().err
    assert rc == 2
    _assert_one_error_line(err)
    assert "complete-log refusal" in err
    assert not (ws / "campaign_out").exists()


def test_excess_row_refusal_at_max_rows_ceiling(ws, capsys):
    # MAX_ROWS_CEILING + 1 physical records (blank records count): the
    # preflight must probe one record past the ceiling, which NP1's reader
    # can never be asked to do -- proving the preflight is campaign-owned.
    (ws / "log.jsonl").write_bytes(b"\n" * (MAX_ROWS_CEILING + 1))
    rc = campaign.main(_argv(ws, extra=("--max-rows", str(MAX_ROWS_CEILING))))
    err = capsys.readouterr().err
    assert rc == 2
    _assert_one_error_line(err)
    assert "complete-log refusal" in err


def test_oversized_record_refusal_exit2(ws, capsys):
    rows = _log_rows(40)
    rows.insert(5, b"x" * 200)  # content over the campaign max_line_bytes
    (ws / "log.jsonl").write_bytes(b"".join(r + b"\n" for r in rows))
    rc = campaign.main(_argv(ws, extra=("--max-line-bytes", "150")))
    err = capsys.readouterr().err
    assert rc == 2
    _assert_one_error_line(err)
    assert "complete-log refusal" in err
    assert "max_line_bytes" in err


def test_preflight_framing_fidelity(ws, capsys):
    # LF rows, one CRLF row, one blank record, and a final unterminated
    # record: every physical record counts exactly as NP1's rows_read.
    rows = _log_rows(6)
    payload = (
        rows[0] + b"\n"
        + rows[1] + b"\r\n"   # CRLF-terminated
        + b"\n"               # blank record (counts, no rejection)
        + rows[2] + b"\n"
        + rows[3] + b"\n"
        + rows[4] + b"\n"
        + rows[5]             # final unterminated record
    )
    (ws / "log.jsonl").write_bytes(payload)
    assert campaign.main(_argv(ws)) == 0
    capsys.readouterr()
    manifest = _load_json(ws, "campaign_out", campaign.MANIFEST_FILENAME)
    report = _load_json(ws, "campaign_out", campaign.REPORT_FILENAME)
    assert manifest["completeness"]["records_observed"] == 7
    assert report["input"]["rows_read"] == 7
    assert report["input"]["rows_accepted"] == 6
    # The preflight performed no rejection classification: NP1 still owns
    # the reject accounting (blank records are neither).
    assert report["input"]["rows_rejected"] == 0


# ---------------------------------------------------------------------------
# Size-preflight lane separation (contract section 3.9)
# ---------------------------------------------------------------------------


def test_staged_log_over_max_log_bytes_exit5(ws, capsys):
    # >16 MiB of well-framed junk rows (each under max_line_bytes, all
    # within max_rows) plus enough valid rows for the chain: the campaign's
    # own size preflight, not a PacketInputError, decides the lane.
    junk = b"x" * 65_000
    with (ws / "log.jsonl").open("wb") as f:
        for row in _log_rows(40):
            f.write(row + b"\n")
        for _ in range(261):
            f.write(junk + b"\n")
    rc = campaign.main(_argv(ws))
    err = capsys.readouterr().err
    assert rc == 5
    _assert_one_error_line(err)
    assert "campaign size preflight" in err


def test_oversize_generated_json_artifact_exit5(ws, capsys, monkeypatch):
    # The campaign-written report exceeds NP5/NP8 MAX_INPUT_BYTES: the
    # campaign preflight confirms the named ceiling BEFORE NP5's loader
    # runs -- exit 5 with no exception-message parsing anywhere.
    big = '{"pad": "' + "a" * 1_100_000 + '"}\n'
    monkeypatch.setattr(campaign, "serialize_report", lambda report: big)
    rc = campaign.main(_argv(ws))
    err = capsys.readouterr().err
    assert rc == 5
    _assert_one_error_line(err)
    assert "campaign size preflight" in err


def test_evaluator_error_after_passed_preflight_propagates(ws, monkeypatch):
    # A structurally invalid campaign-GENERATED report (small, so the size
    # preflight passes): the EvaluatorInputError NP5 raises is a loud
    # internal invariant failure -- neither exit 2 nor exit 5, never
    # swallowed, never re-typed.
    monkeypatch.setattr(campaign, "serialize_report", lambda report: "{}\n")
    with pytest.raises(EvaluatorInputError):
        campaign.main(_argv(ws))
    assert not (ws / "campaign_out").exists()


def test_packet_error_after_passed_preflight_propagates(ws, monkeypatch):
    monkeypatch.setattr(
        campaign,
        "serialize_lab_report",
        lambda report: '{"schema": "nextness-replay-lab-v1"}\n',
    )
    with pytest.raises(PacketInputError):
        campaign.main(_argv(ws))
    assert not (ws / "campaign_out").exists()


def test_manifest_ceiling_exit5(ws, capsys, monkeypatch):
    monkeypatch.setattr(campaign, "MAX_CAMPAIGN_MANIFEST_BYTES", 10)
    rc = campaign.main(_argv(ws))
    err = capsys.readouterr().err
    assert rc == 5
    _assert_one_error_line(err)
    assert "manifest" in err


# ---------------------------------------------------------------------------
# LabInputError: the four required direct-catch failure families (exit 2)
# ---------------------------------------------------------------------------


def test_lab_family_malformed_protocol_exit2(ws, capsys):
    _write_protocol(ws / "protocol.json", model="not-a-model")
    rc = campaign.main(_argv(ws))
    err = capsys.readouterr().err
    assert rc == 2
    _assert_one_error_line(err)
    assert "allowlist" in err


def test_lab_family_protocol_over_ceiling_exit2_never_exit5(ws, capsys):
    protocol = _protocol_dict()
    protocol["configurations"][1]["label"] = "p" + "a" * 63  # keep valid label
    raw = json.dumps(protocol, sort_keys=True)
    padded = raw[:-1] + ', "pad": "' + "b" * 66_000 + '"}'
    (ws / "protocol.json").write_bytes(padded.encode("utf-8"))
    rc = campaign.main(_argv(ws))
    err = capsys.readouterr().err
    assert rc == 2  # NP6's LabInputError lane, never the exit-5 ceiling lane
    _assert_one_error_line(err)
    assert "65536" in err


def test_lab_family_reader_bound_translated_exit2(ws, capsys, monkeypatch):
    # The genuine NP6 translation: PredictorInputError at the reader call
    # inside build_lab_report becomes LabInputError (message byte-identical,
    # cause preserved). First prove the error object's shape directly, then
    # prove the campaign surfaces exactly that class -- untranslated -- as
    # exit 2.
    with pytest.raises(LabInputError) as excinfo:
        build_lab_report(ws / "log.jsonl", ws / "protocol.json", max_rows=0)
    assert isinstance(excinfo.value.__cause__, PredictorInputError)
    assert str(excinfo.value) == str(excinfo.value.__cause__)
    expected_message = str(excinfo.value)

    real = build_lab_report

    def _bad_bounds(log_path, protocol_path, *, max_rows, max_line_bytes):
        return real(log_path, protocol_path, max_rows=0, max_line_bytes=max_line_bytes)

    monkeypatch.setattr(campaign, "build_lab_report", _bad_bounds)
    rc = campaign.main(_argv(ws))
    err = capsys.readouterr().err
    assert rc == 2
    _assert_one_error_line(err)
    assert err == f"error: {expected_message}\n"  # no re-typing, no prefix


def test_lab_family_replay_steps_exceeded_exit2(ws, capsys):
    # holdout_fraction 0.5 over 4200 accepted rows -> 2100 replay steps,
    # over MAX_REPLAY_STEPS = 2000. Raised by build_lab_report itself (the
    # protocol has already loaded) and it is a step-count bound on operator
    # input -- the exit-5 byte-ceiling lane never applies.
    _write_log(ws / "log.jsonl", 4200)
    _write_protocol(ws / "protocol.json", holdout_fraction=0.5)
    rc = campaign.main(_argv(ws))
    err = capsys.readouterr().err
    assert rc == 2
    _assert_one_error_line(err)
    assert "replay bound" in err


def test_plain_valueerror_propagates_not_exit2(ws, capsys, monkeypatch):
    # Negative control: a sentinel plain ValueError at the NP6 call seam
    # propagates -- the campaign catches the exact LabInputError subclass,
    # not its ValueError base. This case deliberately asserts propagation
    # and expects neither exit 2 nor a concise error line.
    def _sentinel(log_path, protocol_path, *, max_rows, max_line_bytes):
        raise ValueError("sentinel-plain-valueerror")

    monkeypatch.setattr(campaign, "build_lab_report", _sentinel)
    with pytest.raises(ValueError, match="sentinel-plain-valueerror"):
        campaign.main(_argv(ws))
    assert capsys.readouterr().err == ""


def test_runtime_error_propagates(ws, monkeypatch):
    # NP8's packet self-validation failure is a loud internal RuntimeError;
    # any RuntimeError outside the documented catch set propagates.
    def _sentinel(paths):
        raise RuntimeError("internal: sentinel self-validation failure")

    monkeypatch.setattr(campaign, "build_packet", _sentinel)
    with pytest.raises(RuntimeError, match="sentinel self-validation"):
        campaign.main(_argv(ws))


# ---------------------------------------------------------------------------
# Insufficiency (exit 3)
# ---------------------------------------------------------------------------


def test_insufficient_history_exit3(ws, capsys):
    _write_log(ws / "log.jsonl", 2)
    rc = campaign.main(_argv(ws))
    err = capsys.readouterr().err
    assert rc == 3
    _assert_one_error_line(err)


# ---------------------------------------------------------------------------
# Containment (exit 4) and the data/ exclusion
# ---------------------------------------------------------------------------


def test_workspace_not_existing_directory_exit4(ws, capsys):
    argv = _argv(ws)
    argv[argv.index("--workspace-dir") + 1] = str(ws / "nope")
    rc = campaign.main(argv)
    err = capsys.readouterr().err
    assert rc == 4
    _assert_one_error_line(err)


def test_workspace_under_repo_data_tree_exit4(tmp_path, capsys, monkeypatch):
    fake_data = tmp_path / "data"
    inner = fake_data / "workspace"
    inner.mkdir(parents=True)
    _write_log(inner / "log.jsonl")
    _write_protocol(inner / "protocol.json")
    monkeypatch.setattr(campaign, "_repo_data_dir", lambda: fake_data.resolve())
    rc = campaign.main(_argv(inner))
    err = capsys.readouterr().err
    assert rc == 4
    _assert_one_error_line(err)
    assert "data/" in err
    # Nothing was created anywhere under the data tree.
    assert sorted(p.name for p in inner.iterdir()) == ["log.jsonl", "protocol.json"]


def test_log_outside_workspace_exit4(ws, tmp_path, capsys):
    outside = tmp_path / "outside.jsonl"
    _write_log(outside)
    argv = _argv(ws)
    argv[0] = str(outside)
    rc = campaign.main(argv)
    err = capsys.readouterr().err
    assert rc == 4
    _assert_one_error_line(err)


def test_output_dir_outside_workspace_exit4(ws, tmp_path, capsys):
    argv = _argv(ws)
    argv[argv.index("--output-dir") + 1] = str(tmp_path / "elsewhere")
    rc = campaign.main(argv)
    err = capsys.readouterr().err
    assert rc == 4
    _assert_one_error_line(err)


def test_output_dir_already_exists_exit4(ws, capsys):
    (ws / "campaign_out").mkdir()
    rc = campaign.main(_argv(ws))
    err = capsys.readouterr().err
    assert rc == 4
    _assert_one_error_line(err)
    assert "already exists" in err


def test_output_dir_aliasing_input_exit4(ws, capsys):
    argv = _argv(ws)
    argv[argv.index("--output-dir") + 1] = str(ws / "log.jsonl")
    rc = campaign.main(argv)
    err = capsys.readouterr().err
    assert rc == 4
    _assert_one_error_line(err)


# ---------------------------------------------------------------------------
# Staging (exit 6), cleanup, and the honest residuals
# ---------------------------------------------------------------------------


def test_staging_creation_failure_exit6(ws, capsys):
    rc = campaign.main(_argv(ws, out=os.path.join("missing", "final")))
    err = capsys.readouterr().err
    assert rc == 6
    _assert_one_error_line(err)
    assert "staging" in err


def test_staging_cleanup_on_handled_failure(ws, capsys):
    rc = campaign.main(_argv(ws, label="no-such-label"))
    capsys.readouterr()
    assert rc == 2
    assert _staging_residue(ws) == []


def test_hard_kill_residual_documented_not_claimed():
    # The residual is asserted as documentation, not as a cleanup
    # guarantee: the published non-claims must state that an uncatchable
    # termination may leave staging behind.
    joined = " ".join(campaign.NON_CLAIMS)
    assert "hard kill" in joined
    assert "staging" in joined
    assert "not" in joined


def test_input_bytes_preserved_on_success_and_refusal(ws, capsys):
    log_before = (ws / "log.jsonl").read_bytes()
    protocol_before = (ws / "protocol.json").read_bytes()
    assert campaign.main(_argv(ws)) == 0
    assert campaign.main(_argv(ws, label="no-such-label", out="other")) == 2
    capsys.readouterr()
    assert (ws / "log.jsonl").read_bytes() == log_before
    assert (ws / "protocol.json").read_bytes() == protocol_before


def test_staged_input_authority_and_captured_bytes(ws, capsys, monkeypatch):
    # Reference run first.
    assert campaign.main(_argv(ws, out="reference")) == 0
    original = (ws / "log.jsonl").read_bytes()

    # Second run: the ORIGINAL log is mutated mid-run (after capture), via
    # a seam wrapper around NP1's builder. The staged copy -- not the
    # subsequently changed original -- must drive every output, and the
    # manifest hashes must describe the captured bytes.
    real_build_report = campaign.build_report

    def _mutating(staged_log, **kwargs):
        with (ws / "log.jsonl").open("ab") as f:
            f.write(b'{"garbage": true}\n')
        return real_build_report(staged_log, **kwargs)

    monkeypatch.setattr(campaign, "build_report", _mutating)
    assert campaign.main(_argv(ws, out="mutated")) == 0
    capsys.readouterr()

    reference = _read_published(ws, "reference")
    mutated = _read_published(ws, "mutated")
    for name in reference:
        assert reference[name] == mutated[name], name
    # The published log is the captured snapshot, not the mutated original.
    assert mutated["nextness_runs.jsonl"] == original
    assert (ws / "log.jsonl").read_bytes() != original
    manifest = _load_json(ws, "mutated", campaign.MANIFEST_FILENAME)
    assert (
        manifest["inputs"]["log"]["sha256"]
        == hashlib.sha256(original).hexdigest()
    )


# ---------------------------------------------------------------------------
# Publication (exit 7): the destination race stays within the non-claims
# ---------------------------------------------------------------------------


def test_destination_race_reported_or_permitted(ws, capsys, monkeypatch):
    # Inject a concurrent creation of the destination between validation
    # and the rename. Contract 3.7: the outcome is OS-dependent -- either a
    # REPORTED publication failure (exit 7) or a permitted replacement of
    # the concurrently created empty directory (exit 0). Both are inside
    # the contract; an unobservable replacement is a standing non-claim.
    real_publish = campaign._publish

    def _racing(staging_dir, final_resolved):
        os.makedirs(final_resolved)
        real_publish(staging_dir, final_resolved)

    monkeypatch.setattr(campaign, "_publish", _racing)
    rc = campaign.main(_argv(ws))
    captured = capsys.readouterr()
    assert rc in (0, 7)
    if rc == 7:
        _assert_one_error_line(captured.err)
        assert "publication failed" in captured.err
        assert _staging_residue(ws) == []
    else:
        published = _read_published(ws)
        assert sorted(published) == sorted(campaign.PUBLICATION_FILENAMES)


# ---------------------------------------------------------------------------
# Coherence gate: all four outcomes (contract section 3.4)
# ---------------------------------------------------------------------------


def _patched_evaluation(monkeypatch, mutate):
    real = campaign.build_evaluation

    def _wrapped(**kwargs):
        evaluation = real(**kwargs)
        mutate(evaluation)
        return evaluation

    monkeypatch.setattr(campaign, "build_evaluation", _wrapped)


def test_coherence_contradicted_refuses_exit2(ws, capsys, monkeypatch):
    def _contradict(evaluation):
        results = evaluation["cross_check"]["ece_match"]["value"]["results"]
        results[0]["verdict"] = "contradicted"

    _patched_evaluation(monkeypatch, _contradict)
    rc = campaign.main(_argv(ws))
    err = capsys.readouterr().err
    assert rc == 2
    _assert_one_error_line(err)
    assert "coherence refusal" in err
    assert "contradicted" in err
    assert not (ws / "campaign_out").exists()


def test_coherence_unverifiable_publishes(ws, capsys, monkeypatch):
    def _unverifiable(evaluation):
        results = evaluation["cross_check"]["surprise_nll_match"]["value"]["results"]
        results[0]["verdict"] = "unverifiable"

    _patched_evaluation(monkeypatch, _unverifiable)
    assert campaign.main(_argv(ws)) == 0
    capsys.readouterr()
    manifest = _load_json(ws, "campaign_out", campaign.MANIFEST_FILENAME)
    results = manifest["cross_check"]["surprise_nll_match"]["value"]["results"]
    assert results[0]["verdict"] == "unverifiable"  # carried unchanged


def test_coherence_not_computable_publishes(ws, capsys, monkeypatch):
    blocked = {
        "status": "not_computable",
        "reason": "no_covering_receipt",
        "requires": "a covering receipt",
    }

    def _blocked(evaluation):
        evaluation["cross_check"]["ece_match"] = dict(blocked)
        evaluation["cross_check"]["surprise_nll_match"] = dict(blocked)
        # NP5 emits the same-source assumption only alongside a computed
        # cross-check; the simulated no-covering-receipt evaluation must
        # match NP5's real shape or NP9 rightly rejects it.
        evaluation["assumptions"] = [
            a
            for a in evaluation["assumptions"]
            if not a.startswith("cross-check-same-source")
        ]

    _patched_evaluation(monkeypatch, _blocked)
    assert campaign.main(_argv(ws)) == 0
    capsys.readouterr()
    manifest = _load_json(ws, "campaign_out", campaign.MANIFEST_FILENAME)
    assert manifest["cross_check"]["ece_match"] == blocked
    assert manifest["cross_check"]["surprise_nll_match"] == blocked


# ---------------------------------------------------------------------------
# Option lineage, selected-label recording, NP8 default-bound exception
# ---------------------------------------------------------------------------


def test_option_lineage_and_np8_default_bound_exception(ws, capsys, monkeypatch):
    captured_kwargs = {}
    real_bridge = campaign.observations_from_log

    def _spy(log_path, model, **kwargs):
        captured_kwargs["model"] = model
        captured_kwargs.update(kwargs)
        return real_bridge(log_path, model, **kwargs)

    monkeypatch.setattr(campaign, "observations_from_log", _spy)
    _write_log(ws / "log.jsonl", 60)
    assert (
        campaign.main(
            _argv(ws, extra=("--max-rows", "500", "--max-line-bytes", "30000"))
        )
        == 0
    )
    capsys.readouterr()

    # Protocol options reach NP1 and NP2; identical campaign reader bounds
    # reach NP1, NP2 and NP6; the labelled configuration's window reaches
    # the NP2 bridge as well as the receipt config.
    report = _load_json(ws, "campaign_out", campaign.REPORT_FILENAME)
    lab = _load_json(ws, "campaign_out", campaign.LAB_FILENAME)
    assert report["config"]["smoothing"] == 1.0
    assert report["config"]["holdout_fraction"] == 0.25
    assert report["config"]["max_rows"] == 500
    assert report["config"]["max_line_bytes"] == 30000
    assert lab["config"]["model"] == "first_order"
    assert lab["config"]["smoothing"] == 1.0
    assert lab["config"]["holdout_fraction"] == 0.25
    assert lab["config"]["max_rows"] == 500
    assert lab["config"]["max_line_bytes"] == 30000
    assert captured_kwargs["model"] == "first_order"
    assert captured_kwargs["smoothing"] == 1.0
    assert captured_kwargs["holdout_fraction"] == 0.25
    assert captured_kwargs["max_rows"] == 500
    assert captured_kwargs["max_line_bytes"] == 30000
    assert captured_kwargs["window"] == 50  # the selected label's window

    # Selected-label recording: the manifest ties the receipt to the named
    # protocol configuration (the receipt itself records values, no label).
    manifest = _load_json(ws, "campaign_out", campaign.MANIFEST_FILENAME)
    receipt = _load_json(ws, "campaign_out", campaign.RECEIPT_FILENAME)
    assert manifest["receipt_config_label"] == "primary"
    assert manifest["receipt_config"] == receipt["config"]
    assert "label" not in receipt
    by_label = {c["label"]: c["config"] for c in lab["configurations"]}
    assert manifest["receipt_config"] == by_label["primary"]

    # NP8 default-bound exception: the packet's log entry echoes NP1
    # DEFAULT bounds (it is not the completeness witness), while the
    # campaign preflight evidence and the lab-sequence link both carry the
    # campaign bounds.
    packet = _load_json(ws, "campaign_out", campaign.PACKET_FILENAME)
    log_entry = next(e for e in packet["artifacts"] if e["role"] == "log")
    assert log_entry["sequence_bounds"] == {
        "max_rows": MAX_ROWS_DEFAULT,
        "max_line_bytes": MAX_LINE_BYTES_DEFAULT,
    }
    assert manifest["completeness"]["max_rows"] == 500
    assert manifest["completeness"]["max_line_bytes"] == 30000
    link = packet["links"]["lab_sequence_sha256"]
    assert link["status"] == "verified"
    assert link["reader_bounds"] == {"max_rows": 500, "max_line_bytes": 30000}


# ---------------------------------------------------------------------------
# Static import quarantine
# ---------------------------------------------------------------------------


def test_static_import_quarantine():
    module_path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "scripts"
        / "nextness_evidence_campaign.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    allowed = {
        "__future__",
        "argparse",
        "hashlib",
        "json",
        "os",
        "pathlib",
        "shutil",
        "sys",
        "tempfile",
        "collections.abc",
        "typing",
        "scripts.nextness_predictor",
        "scripts.nextness_monitor",
        "scripts.nextness_evaluator",
        "scripts.nextness_replay_lab",
        "scripts.nextness_evidence_packet",
    }
    assert imported <= allowed, f"unexpected imports: {sorted(imported - allowed)}"
    forbidden_fragments = (
        "observer",
        "calibration",
        "metrics",
        "continuous_evolution",
        "medusa",
        "event_bus",
        "orchestrator",
        "tuning",
        "agent_backends",
        "subprocess",
        "socket",
        "http",
        "urllib",
        "requests",
        "zmq",
        "ollama",
    )
    for name in imported:
        for fragment in forbidden_fragments:
            assert fragment not in name, f"forbidden import {name}"


# ---------------------------------------------------------------------------
# Option validation (the campaign's own exit-2 lane)
# ---------------------------------------------------------------------------


def test_out_of_range_reader_bounds_refuse_exit2(ws, capsys):
    rc = campaign.main(_argv(ws, extra=("--max-rows", "0")))
    err = capsys.readouterr().err
    assert rc == 2
    _assert_one_error_line(err)
    rc = campaign.main(
        _argv(ws, extra=("--max-rows", str(MAX_ROWS_CEILING + 1)))
    )
    err = capsys.readouterr().err
    assert rc == 2
    _assert_one_error_line(err)
    rc = campaign.main(_argv(ws, extra=("--max-line-bytes", "0")))
    err = capsys.readouterr().err
    assert rc == 2
    _assert_one_error_line(err)
