"""Validator CLI tests: determinism, refusal lanes, ceilings, zero writes."""

from __future__ import annotations

import copy
import json
import os
import pathlib

import pytest

import experiments.tech_ledger.validate as validate_module
from experiments.tech_ledger.validate import (
    MAX_ENTRIES,
    MAX_ENTRY_BYTES,
    MAX_TOTAL_ENTRY_BYTES,
    main,
    validate_directory,
)

_EXEMPLARS = (
    pathlib.Path(__file__).resolve().parent.parent / "entries"
)


def _valid_entry(entry_id="TLV4-042"):
    return {
        "schema": "tech-ledger-v1",
        "entry_id": entry_id,
        "neutral_name": "Example demonstrated technology",
        "primary_classification": "A",
        "classification_qualifiers": [],
        "classification_rationale": "Recorded rationale.",
        "legitimate_uses": ["one legitimate use"],
        "unsuitable_uses": ["one unsuitable use"],
        "repository_placements": ["research-ledger"],
        "implementation_disposition": "eligible",
        "minimal_evidence_before_implementation": ["ordinary test evidence"],
        "implementation_seam": "a deterministic test seam",
        "provenance": {
            "source_kind": "user-supplied-audit",
            "source_reference": "example reference",
            "attributed_author": "example author",
            "recorded_date": "2026-08-01",
            "verification_status": "unverified",
        },
        "related_intake_ledger_entries": [],
        "warnings": ["schema validity is not scientific validity"],
        "status": "active",
    }


def _write_entry(directory, entry_id="TLV4-042", filename=None, entry=None):
    entry = entry if entry is not None else _valid_entry(entry_id)
    name = filename or f"{entry_id}.json"
    (directory / name).write_bytes(
        (json.dumps(entry, sort_keys=True, indent=1) + "\n").encode("utf-8")
    )
    return name


def _snapshot(directory):
    return {
        p.name: p.read_bytes() for p in sorted(directory.iterdir()) if p.is_file()
    }


def _assert_one_error_line(err):
    assert err.startswith("error:")
    assert err.count("\n") == 1 and err.endswith("\n")
    assert "Traceback" not in err


def test_success_canonical_deterministic_output(tmp_path, capsys):
    _write_entry(tmp_path, "TLV4-001")
    _write_entry(tmp_path, "TLV4-002")
    before = _snapshot(tmp_path)
    assert main([str(tmp_path)]) == 0
    first = capsys.readouterr()
    assert first.err == ""
    assert main([str(tmp_path)]) == 0
    second = capsys.readouterr()
    # Repeated runs: byte-identical canonical output; zero writes.
    assert first.out == second.out
    assert first.out.endswith("\n")
    assert "\r" not in first.out
    assert _snapshot(tmp_path) == before
    summary = json.loads(first.out)
    assert summary["schema"] == "tech-ledger-v1"
    assert summary["entry_count"] == 2
    # Relative filenames and entry ids only -- no absolute path anywhere.
    assert str(tmp_path) not in first.out
    assert str(tmp_path).replace(os.sep, "/") not in first.out


def test_deterministic_filename_order(tmp_path, capsys):
    # Written in scrambled order; reported in sorted filename order.
    _write_entry(tmp_path, "TLV4-030")
    _write_entry(tmp_path, "TLV4-002")
    _write_entry(tmp_path, "TLV4-100")
    assert main([str(tmp_path)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert [e["filename"] for e in summary["entries"]] == [
        "TLV4-002.json",
        "TLV4-030.json",
        "TLV4-100.json",
    ]


def test_duplicate_json_key_refused_exit2(tmp_path, capsys):
    _write_entry(tmp_path, "TLV4-001")
    raw = (tmp_path / "TLV4-001.json").read_text(encoding="utf-8")
    patched = raw.replace(
        '"status": "active"', '"status": "active", "status": "parked"', 1
    )
    (tmp_path / "TLV4-001.json").write_bytes(patched.encode("utf-8"))
    rc = main([str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 2
    _assert_one_error_line(err)
    assert "duplicate JSON key" in err


def test_malformed_json_refused_exit2(tmp_path, capsys):
    (tmp_path / "TLV4-001.json").write_bytes(b"{not json")
    rc = main([str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 2
    _assert_one_error_line(err)


def test_root_non_object_refused_exit2(tmp_path, capsys):
    (tmp_path / "TLV4-001.json").write_bytes(b"[]\n")
    rc = main([str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 2
    _assert_one_error_line(err)
    assert "JSON object" in err


def test_schema_refusal_exit2(tmp_path, capsys):
    entry = _valid_entry("TLV4-001")
    entry["status"] = "no-such-status"
    _write_entry(tmp_path, "TLV4-001", entry=entry)
    rc = main([str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 2
    _assert_one_error_line(err)


def test_duplicate_entry_id_across_files_refused_exit2(tmp_path, capsys):
    _write_entry(tmp_path, "TLV4-001")
    _write_entry(tmp_path, "TLV4-001", filename="TLV4-001-copy.json")
    rc = main([str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 2
    _assert_one_error_line(err)
    assert "duplicate entry_id" in err


def test_symlink_entry_refused_exit4(tmp_path, capsys):
    _write_entry(tmp_path, "TLV4-001")
    link = tmp_path / "TLV4-002.json"
    try:
        os.symlink(str(tmp_path / "TLV4-001.json"), str(link))
    except (OSError, NotImplementedError):  # pragma: no cover - privilege
        pytest.skip("platform lacks symlink privilege")
    rc = main([str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 4
    _assert_one_error_line(err)
    assert "symbolic-link" in err


def test_missing_directory_exit4(tmp_path, capsys):
    rc = main([str(tmp_path / "nope")])
    err = capsys.readouterr().err
    assert rc == 4
    _assert_one_error_line(err)


def test_non_directory_input_exit4(tmp_path, capsys):
    target = tmp_path / "file.txt"
    target.write_bytes(b"not a dir")
    rc = main([str(target)])
    err = capsys.readouterr().err
    assert rc == 4
    _assert_one_error_line(err)


def test_entry_count_ceiling_exit5(tmp_path, capsys):
    # Ceilings precede parsing: the files are junk bytes, never parsed.
    for i in range(MAX_ENTRIES + 1):
        (tmp_path / f"junk-{i:04d}.json").write_bytes(b"x")
    rc = main([str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 5
    _assert_one_error_line(err)
    assert f"{MAX_ENTRIES}-entry ceiling" in err


def test_per_entry_byte_ceiling_exit5(tmp_path, capsys):
    (tmp_path / "TLV4-001.json").write_bytes(b"x" * (MAX_ENTRY_BYTES + 1))
    rc = main([str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 5
    _assert_one_error_line(err)
    assert "per-entry ceiling" in err


def test_total_byte_ceiling_exit5(tmp_path, capsys):
    # Each file under the per-entry ceiling; the SUM breaches the total.
    per_file = MAX_ENTRY_BYTES - 1024
    count = (MAX_TOTAL_ENTRY_BYTES // per_file) + 1
    for i in range(count):
        (tmp_path / f"junk-{i:04d}.json").write_bytes(b"x" * per_file)
    rc = main([str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 5
    _assert_one_error_line(err)
    assert "total entry bytes" in err


def test_bounds_precede_parsing(tmp_path, monkeypatch, capsys):
    # If parsing ran before the ceilings, the junk above would exit 2;
    # prove no parse is even attempted on a ceiling breach.
    def _exploding(raw, filename):  # pragma: no cover - must never run
        raise AssertionError("parse attempted before ceilings")

    monkeypatch.setattr(validate_module, "_parse_entry_bytes", _exploding)
    (tmp_path / "TLV4-001.json").write_bytes(b"x" * (MAX_ENTRY_BYTES + 1))
    rc = main([str(tmp_path)])
    capsys.readouterr()
    assert rc == 5


def test_sentinel_programming_error_propagates(tmp_path, monkeypatch):
    _write_entry(tmp_path, "TLV4-001")

    def _sentinel(obj):
        raise RuntimeError("sentinel-unrelated-programming-error")

    monkeypatch.setattr(validate_module, "validate_entry", _sentinel)
    with pytest.raises(RuntimeError, match="sentinel-unrelated"):
        main([str(tmp_path)])


def test_argparse_usage_error_systemexit2(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_non_json_files_ignored(tmp_path, capsys):
    _write_entry(tmp_path, "TLV4-001")
    (tmp_path / "README.md").write_bytes(b"# not an entry\n")
    assert main([str(tmp_path)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["entry_count"] == 1


def test_validate_directory_pure_and_reusable(tmp_path):
    _write_entry(tmp_path, "TLV4-001")
    before = _snapshot(tmp_path)
    first = validate_directory(tmp_path)
    second = validate_directory(tmp_path)
    assert first == second
    assert copy.deepcopy(first)["entry_count"] == 1
    assert _snapshot(tmp_path) == before
