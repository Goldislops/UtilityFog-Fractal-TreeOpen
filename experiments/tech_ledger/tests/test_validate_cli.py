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


# ---------------------------------------------------------------------------
# Captured-byte aggregate enforcement and the capture-boundary races
# (audit corrections 1 and 2) -- synchronized at the validator's real
# pre-open inspection seam; no sleeps, no timing guesses.
# ---------------------------------------------------------------------------


def _mutate_once_at_capture(monkeypatch, mutate_once):
    """Run ``mutate_once`` exactly once: after the initial stat pass, at
    the first capture's pre-open inspection (the real race window)."""
    real = validate_module._pre_open_inspect
    state = {"done": False}

    def _wrapped(path):
        result = real(path)
        if not state["done"]:
            state["done"] = True
            mutate_once()
        return result

    monkeypatch.setattr(validate_module, "_pre_open_inspect", _wrapped)


def _padded_entry_bytes(entry_id, target_size=None, pad=0):
    entry = _valid_entry(entry_id)
    entry["classification_rationale"] = "Recorded rationale." + "a" * pad
    raw = (json.dumps(entry, sort_keys=True, indent=1) + "\n").encode("utf-8")
    if target_size is None:
        return raw
    base = len(raw) - pad
    entry["classification_rationale"] = "Recorded rationale." + "a" * (
        target_size - base
    )
    raw = (json.dumps(entry, sort_keys=True, indent=1) + "\n").encode("utf-8")
    assert len(raw) == target_size
    return raw


def test_aggregate_growth_after_stat_refuses_exit5(tmp_path, capsys, monkeypatch):
    # Stat total below 4 MiB; every file then grows (each staying under
    # the 128 KiB per-entry ceiling) so the ACTUAL captured total breaches
    # the aggregate ceiling. Content is junk: the refusal must arrive
    # before any parse (proven by the exploding parser).
    names = [f"junk-{i:03d}.json" for i in range(34)]
    for name in names:
        (tmp_path / name).write_bytes(b"x" * 100_000)  # stat total 3.4 MB

    def _grow_all():
        for name in names:
            with (tmp_path / name).open("ab") as f:
                f.write(b"y" * 27_000)  # each 127 000 < 131 072; total > 4 MiB

    _mutate_once_at_capture(monkeypatch, _grow_all)

    def _exploding(raw, filename):  # pragma: no cover - must never run
        raise AssertionError("parse attempted despite aggregate breach")

    monkeypatch.setattr(validate_module, "_parse_entry_bytes", _exploding)
    rc = main([str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 5
    _assert_one_error_line(err)
    assert "total" in err


def test_actual_total_exactly_at_ceiling_accepted(tmp_path, capsys):
    for i in range(32):
        (tmp_path / f"TLV4-{i:03d}.json").write_bytes(
            _padded_entry_bytes(f"TLV4-{i:03d}", target_size=127_000)
        )
    last = MAX_TOTAL_ENTRY_BYTES - 32 * 127_000
    assert last <= MAX_ENTRY_BYTES
    (tmp_path / "TLV4-032.json").write_bytes(
        _padded_entry_bytes("TLV4-032", target_size=last)
    )
    assert main([str(tmp_path)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["total_entry_bytes"] == MAX_TOTAL_ENTRY_BYTES


def test_actual_total_one_byte_over_refuses_exit5(tmp_path, capsys):
    for i in range(32):
        (tmp_path / f"TLV4-{i:03d}.json").write_bytes(
            _padded_entry_bytes(f"TLV4-{i:03d}", target_size=127_000)
        )
    last = MAX_TOTAL_ENTRY_BYTES - 32 * 127_000 + 1
    (tmp_path / "TLV4-032.json").write_bytes(
        _padded_entry_bytes("TLV4-032", target_size=last)
    )
    rc = main([str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 5
    _assert_one_error_line(err)
    assert "total" in err


def test_summary_reports_captured_bytes_not_stat_size(
    tmp_path, capsys, monkeypatch
):
    _write_entry(tmp_path, "TLV4-001")
    stat_size = (tmp_path / "TLV4-001.json").stat().st_size
    replacement = _padded_entry_bytes("TLV4-001", target_size=stat_size + 5_000)

    def _rewrite():
        (tmp_path / "TLV4-001.json").write_bytes(replacement)

    _mutate_once_at_capture(monkeypatch, _rewrite)
    assert main([str(tmp_path)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["total_entry_bytes"] == len(replacement)
    assert summary["total_entry_bytes"] != stat_size


def test_per_entry_growth_refusal_intact(tmp_path, capsys, monkeypatch):
    _write_entry(tmp_path, "TLV4-001")

    def _grow_past_entry_ceiling():
        with (tmp_path / "TLV4-001.json").open("ab") as f:
            f.write(b"z" * (MAX_ENTRY_BYTES + 10))

    _mutate_once_at_capture(monkeypatch, _grow_past_entry_ceiling)
    rc = main([str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 5
    _assert_one_error_line(err)
    assert "per-entry ceiling" in err


def test_symlink_replacement_during_capture_refused_exit4(
    tmp_path, capsys, monkeypatch
):
    entries = tmp_path / "entries"
    entries.mkdir()
    _write_entry(entries, "TLV4-001")
    outside = tmp_path / "outside-target.json"
    outside.write_bytes(
        (json.dumps(_valid_entry("TLV4-099"), sort_keys=True, indent=1) + "\n").encode()
    )
    probe = tmp_path / "symlink-probe"
    try:
        os.symlink(str(outside), str(probe))
    except (OSError, NotImplementedError):  # pragma: no cover - privilege
        pytest.skip("platform lacks symlink privilege")
    os.remove(probe)

    def _replace_with_symlink():
        os.remove(entries / "TLV4-001.json")
        os.symlink(str(outside), str(entries / "TLV4-001.json"))

    _mutate_once_at_capture(monkeypatch, _replace_with_symlink)
    rc = main([str(entries)])
    captured = capsys.readouterr()
    assert rc == 4
    _assert_one_error_line(captured.err)
    # The outside target was neither accepted nor parsed into a summary.
    assert captured.out == ""
    assert "TLV4-099" not in captured.out


def test_regular_file_replacement_during_capture_refused_exit4(
    tmp_path, capsys, monkeypatch
):
    entries = tmp_path / "entries"
    entries.mkdir()
    _write_entry(entries, "TLV4-001")
    decoy = tmp_path / "decoy.json"
    decoy.write_bytes(
        (json.dumps(_valid_entry("TLV4-098"), sort_keys=True, indent=1) + "\n").encode()
    )

    def _replace_with_other_file():
        os.replace(str(decoy), str(entries / "TLV4-001.json"))

    _mutate_once_at_capture(monkeypatch, _replace_with_other_file)
    rc = main([str(entries)])
    captured = capsys.readouterr()
    assert rc == 4
    _assert_one_error_line(captured.err)
    assert "identity" in captured.err
    assert captured.out == ""


def test_stable_files_still_succeed_with_capture_boundary(tmp_path, capsys):
    _write_entry(tmp_path, "TLV4-001")
    _write_entry(tmp_path, "TLV4-002")
    assert main([str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["entry_count"] == 2


# ---------------------------------------------------------------------------
# One physical stderr line (audit correction 3)
# ---------------------------------------------------------------------------


def test_error_output_sanitizes_cr_and_lf(capsys):
    from experiments.tech_ledger.validate import LedgerInputError, _fail

    rc = _fail(LedgerInputError("bad\r\nsplit\nname"), 2)
    err = capsys.readouterr().err
    assert rc == 2
    assert err == "error: bad\\r\\nsplit\\nname\n"
    assert err.count("\n") == 1


def test_newline_bearing_filename_yields_one_error_line(tmp_path, capsys):
    evil_name = "TLV4-666\n.json"
    try:
        (tmp_path / evil_name).write_bytes(b"{not json")
    except OSError:  # pragma: no cover - platform rejects the name
        pytest.skip("filesystem rejects newline-bearing filenames")
    rc = main([str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 2
    _assert_one_error_line(err)
    assert "\\n" in err
