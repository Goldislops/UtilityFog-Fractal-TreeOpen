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


def test_first_invalid_refusal_is_enumeration_order_independent(
    tmp_path, capsys, monkeypatch
):
    # Two ordinary non-regular .json paths (directories -- no symlink
    # privilege needed).  Whatever raw order enumeration returns, the
    # FIRST reported refusal must be the lexically first invalid name:
    # filename ordering is established before any per-entry inspection,
    # so refusal order can never depend on filesystem enumeration order.
    (tmp_path / "a.json").mkdir()
    (tmp_path / "b.json").mkdir()

    for raw_order in (("a.json", "b.json"), ("b.json", "a.json")):
        def _forced_order(target, _order=raw_order):
            return list(_order)

        monkeypatch.setattr(os, "listdir", _forced_order)
        rc = main([str(tmp_path)])
        err = capsys.readouterr().err
        monkeypatch.undo()
        assert rc == 4
        _assert_one_error_line(err)
        assert err.startswith("error: a.json:"), err  # lexically first, pinned
        assert "not a regular file" in err


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


def _mutate_once_at_capture(monkeypatch, mutate_once, *, on_call=1):
    """Run ``mutate_once`` exactly once, at the ``on_call``-th pre-open
    inspection (the real race window; call 1 = first capture's pre-lstat)."""
    real = validate_module._pre_open_inspect
    state = {"calls": 0, "done": False}

    def _wrapped(path, dir_fd=None):
        result = real(path, dir_fd=dir_fd)
        state["calls"] += 1
        if not state["done"] and state["calls"] == on_call:
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
# Entries-directory binding (review finding 1): symlink/junction refusal,
# rename/replacement detection, capture bound to the inspected directory
# ---------------------------------------------------------------------------


def test_symlink_entries_dir_refused_exit4(tmp_path, capsys):
    real = tmp_path / "real_entries"
    real.mkdir()
    _write_entry(real, "TLV4-001")
    link = tmp_path / "linked_entries"
    try:
        os.symlink(str(real), str(link), target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - privilege
        pytest.skip("platform lacks symlink privilege")
    rc = main([str(link)])
    err = capsys.readouterr().err
    assert rc == 4
    _assert_one_error_line(err)
    assert "symbolic link" in err


def test_junction_entries_dir_refused_exit4(tmp_path, capsys):
    try:
        import _winapi
        create_junction = _winapi.CreateJunction
    except (ImportError, AttributeError):  # pragma: no cover - non-Windows
        pytest.skip("platform has no directory junctions")
    real = tmp_path / "real_entries"
    real.mkdir()
    _write_entry(real, "TLV4-001")
    junction = tmp_path / "junction_entries"
    create_junction(str(real), str(junction))
    rc = main([str(junction)])
    err = capsys.readouterr().err
    assert rc == 4
    _assert_one_error_line(err)
    assert "reparse point" in err


_fallback_only = pytest.mark.skipif(
    not validate_module._FALLBACK_BINDING_SUPPORTED,
    reason="platform has no non-dir_fd directory-binding primitive",
)


def _force_fallback(monkeypatch):
    """Exercise the non-dir_fd binding lane explicitly."""
    monkeypatch.setattr(validate_module, "_DIR_FD_SUPPORTED", False)


def test_directory_replacement_between_enumeration_and_capture_refused(
    tmp_path, capsys, monkeypatch
):
    # The binding must PREVENT the swap outright (or the validator must
    # refuse before reading); an identity recheck alone is insufficient.
    _force_fallback(monkeypatch)
    entries = tmp_path / "entries"
    entries.mkdir()
    _write_entry(entries, "TLV4-001")
    _write_entry(entries, "TLV4-002")
    aside = tmp_path / "aside"

    real_verify = validate_module._verify_binding
    state = {"done": False, "blocked": None}

    def _swapping_verify(binding):
        if not state["done"]:
            state["done"] = True
            try:
                os.rename(str(entries), str(aside))
                state["blocked"] = False
                entries.mkdir()
                _write_entry(entries, "TLV4-001")
                _write_entry(entries, "TLV4-002")
            except OSError:
                state["blocked"] = True
        return real_verify(binding)

    monkeypatch.setattr(validate_module, "_verify_binding", _swapping_verify)
    rc = main([str(entries)])
    captured = capsys.readouterr()
    if state["blocked"]:
        assert rc == 0, captured.err  # binding held; nothing to detect
        assert json.loads(captured.out)["entry_count"] == 2
    else:
        assert rc == 4
        _assert_one_error_line(captured.err)


@_fallback_only
def test_persistent_late_replacement_prevented(tmp_path, capsys, monkeypatch):
    # Residual finding 1: swap the inspected directory AFTER the last
    # binding check but BEFORE the first candidate inspection. A held
    # binding must make the rename impossible; the captured bytes must be
    # the ORIGINAL directory's.
    _force_fallback(monkeypatch)
    entries = tmp_path / "entries"
    entries.mkdir()
    _write_entry(entries, "TLV4-001")
    original_size = (entries / "TLV4-001.json").stat().st_size
    aside = tmp_path / "aside"
    replacement_dir = tmp_path / "replacement"
    replacement_dir.mkdir()
    replacement_bytes = _padded_entry_bytes(
        "TLV4-001", target_size=original_size + 2_700
    )
    (replacement_dir / "TLV4-001.json").write_bytes(replacement_bytes)
    assert len(replacement_bytes) != original_size

    real_probe = validate_module._pre_open_inspect
    state = {"done": False, "blocked": None}

    def _swap_then_probe(path, dir_fd=None):
        if not state["done"]:
            state["done"] = True
            try:
                os.rename(str(entries), str(aside))
                os.rename(str(replacement_dir), str(entries))
                state["blocked"] = False
            except OSError:
                state["blocked"] = True
        return real_probe(path, dir_fd=dir_fd)

    monkeypatch.setattr(validate_module, "_pre_open_inspect", _swap_then_probe)
    rc = main([str(entries)])
    captured = capsys.readouterr()
    assert state["blocked"] is True, "the held binding must prevent the rename"
    assert rc == 0, captured.err
    summary = json.loads(captured.out)
    assert summary["total_entry_bytes"] == original_size
    assert summary["total_entry_bytes"] != len(replacement_bytes)


@_fallback_only
def test_transient_enumeration_swap_and_restore_prevented(
    tmp_path, capsys, monkeypatch
):
    # Residual finding 2: replace the directory ONLY while os.listdir
    # runs (subset of filenames), then restore before any identity
    # recheck. Before/after checks cannot see this; a held binding must
    # prevent it, so the full candidate set is enumerated.
    _force_fallback(monkeypatch)
    entries = tmp_path / "entries"
    entries.mkdir()
    _write_entry(entries, "TLV4-001")
    _write_entry(entries, "TLV4-016")
    aside = tmp_path / "aside"
    transient = tmp_path / "transient"
    transient.mkdir()
    _write_entry(transient, "TLV4-001")  # deliberately omits TLV4-016

    real_listdir = os.listdir
    state = {"done": False, "blocked": None}

    def _swapping_listdir(target):
        if state["done"]:
            return real_listdir(target)
        state["done"] = True
        try:
            os.rename(str(entries), str(aside))
            os.rename(str(transient), str(entries))
            state["blocked"] = False
        except OSError:
            state["blocked"] = True
            return real_listdir(target)
        try:
            return real_listdir(target)
        finally:  # restore before any later identity recheck
            os.rename(str(entries), str(transient))
            os.rename(str(aside), str(entries))

    monkeypatch.setattr(os, "listdir", _swapping_listdir)
    rc = main([str(entries)])
    captured = capsys.readouterr()
    monkeypatch.undo()
    assert state["blocked"] is True, "the held binding must prevent the swap"
    assert rc == 0, captured.err
    summary = json.loads(captured.out)
    assert summary["entry_count"] == 2  # nothing silently omitted
    assert {e["entry_id"] for e in summary["entries"]} == {"TLV4-001", "TLV4-016"}


@_fallback_only
def test_binding_released_after_success(tmp_path, capsys, monkeypatch):
    _force_fallback(monkeypatch)
    entries = tmp_path / "entries"
    entries.mkdir()
    _write_entry(entries, "TLV4-001")
    assert main([str(entries)]) == 0
    capsys.readouterr()
    os.rename(str(entries), str(tmp_path / "moved"))  # released, no error


@_fallback_only
@pytest.mark.parametrize(
    "sabotage",
    ["enumeration", "capture", "parse"],
)
def test_binding_released_after_failures(tmp_path, capsys, monkeypatch, sabotage):
    _force_fallback(monkeypatch)
    entries = tmp_path / "entries"
    entries.mkdir()
    if sabotage == "enumeration":
        (entries / "TLV4-001.json").write_bytes(b"x" * (MAX_ENTRY_BYTES + 1))
        expected = 5
    elif sabotage == "capture":
        _write_entry(entries, "TLV4-001")

        def _boom(path, dir_fd=None):
            raise OSError("synthetic capture failure")

        monkeypatch.setattr(validate_module, "_pre_open_inspect", _boom)
        expected = 4
    else:
        (entries / "TLV4-001.json").write_bytes(b"{not json")
        expected = 2
    assert main([str(entries)]) == expected
    capsys.readouterr()
    os.rename(str(entries), str(tmp_path / "moved"))  # released on failure paths


def test_fail_closed_without_any_binding_primitive(tmp_path, capsys, monkeypatch):
    # No dir_fd and no fallback primitive: refuse BEFORE enumeration
    # rather than retaining identity-only checks as a "binding".
    monkeypatch.setattr(validate_module, "_DIR_FD_SUPPORTED", False)
    monkeypatch.setattr(validate_module, "_FALLBACK_BINDING_SUPPORTED", False)
    _write_entry(tmp_path, "TLV4-001")

    def _must_not_run(target):  # pragma: no cover - must never execute
        raise AssertionError("enumeration ran without a binding")

    monkeypatch.setattr(os, "listdir", _must_not_run)
    rc = main([str(tmp_path)])
    err = capsys.readouterr().err
    monkeypatch.undo()
    assert rc == 4
    _assert_one_error_line(err)
    assert "binding" in err


_dir_fd_only = pytest.mark.skipif(
    not validate_module._DIR_FD_SUPPORTED,
    reason="directory-relative descriptors unavailable on this platform",
)


@_dir_fd_only
def test_capture_bound_to_inspected_directory_fd_mode(
    tmp_path, capsys, monkeypatch
):
    # fd mode: after enumeration and the phase identity check, the
    # pathname is swapped to a different directory whose same-named entry
    # has DIFFERENT content. Captures go through the held descriptor, so
    # the summary must describe the ORIGINAL directory's bytes.
    entries = tmp_path / "entries"
    entries.mkdir()
    _write_entry(entries, "TLV4-001")
    original_size = (entries / "TLV4-001.json").stat().st_size
    aside = tmp_path / "aside"
    replacement = _padded_entry_bytes("TLV4-001", target_size=original_size + 4_000)

    def _swap_directory():
        os.rename(str(entries), str(aside))
        entries.mkdir()
        (entries / "TLV4-001.json").write_bytes(replacement)

    # First pre-open inspection happens inside capture 1, AFTER the
    # phase-level binding check -- exactly the bound-capture window.
    _mutate_once_at_capture(monkeypatch, _swap_directory, on_call=1)
    rc = main([str(entries)])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    summary = json.loads(captured.out)
    assert summary["total_entry_bytes"] == original_size  # original dir bytes
    assert summary["total_entry_bytes"] != len(replacement)


@_dir_fd_only
def test_fd_mode_inspections_go_through_directory_descriptor(
    tmp_path, capsys, monkeypatch
):
    # Every candidate inspection must pass a real dir_fd and a bare
    # filename -- never a reconstructed pathname -- when the descriptor
    # lane is on.
    _write_entry(tmp_path, "TLV4-001")
    _write_entry(tmp_path, "TLV4-002")
    seen = []
    real = validate_module._pre_open_inspect

    def _recording(path, dir_fd=None):
        seen.append((path, dir_fd))
        return real(path, dir_fd=dir_fd)

    monkeypatch.setattr(validate_module, "_pre_open_inspect", _recording)
    assert main([str(tmp_path)]) == 0
    capsys.readouterr()
    assert seen, "captures must run through the inspection seam"
    assert all(dir_fd is not None for _path, dir_fd in seen)
    assert all(os.sep not in path for path, _dir_fd in seen)


@_dir_fd_only
def test_transient_pathname_swap_during_enumeration_fd_mode(
    tmp_path, capsys, monkeypatch
):
    # fd mode: enumeration reads the HELD descriptor, so a pathname
    # swap-and-restore around os.listdir cannot subset or replace the
    # candidate set.  (POSIX permits the renames -- unlike the Windows
    # hold lane, which forbids them -- but the binding makes them
    # irrelevant: every later probe and open goes through the held fd.)
    entries = tmp_path / "entries"
    entries.mkdir()
    _write_entry(entries, "TLV4-001")
    _write_entry(entries, "TLV4-016")
    aside = tmp_path / "aside"
    transient = tmp_path / "transient"
    transient.mkdir()
    _write_entry(transient, "TLV4-001")  # deliberately omits TLV4-016

    real_listdir = os.listdir
    state = {"done": False}

    def _swapping_listdir(target):
        if state["done"]:
            return real_listdir(target)
        state["done"] = True
        os.rename(str(entries), str(aside))
        os.rename(str(transient), str(entries))
        try:
            return real_listdir(target)  # target is the held descriptor
        finally:  # restore before any later pathname cross-check
            os.rename(str(entries), str(transient))
            os.rename(str(aside), str(entries))

    monkeypatch.setattr(os, "listdir", _swapping_listdir)
    rc = main([str(entries)])
    captured = capsys.readouterr()
    monkeypatch.undo()
    assert state["done"] is True, "the swap window must actually run"
    assert rc == 0, captured.err
    summary = json.loads(captured.out)
    assert summary["entry_count"] == 2  # nothing silently omitted
    assert {e["entry_id"] for e in summary["entries"]} == {
        "TLV4-001",
        "TLV4-016",
    }


# ---------------------------------------------------------------------------
# Capability-predicate correspondence (Ubuntu regression): the compiled
# flag must track the primitives the fd lane genuinely calls, on real and
# simulated capability shapes alike.  CPython never registers os.lstat in
# os.supports_dir_fd on any build, so a predicate consulting it is False
# everywhere -- which made every Linux run refuse ordinary validation.
# ---------------------------------------------------------------------------


def _linux_shaped_capabilities():
    # The shape CPython v3.12.13 builds on Linux: os.stat (HAVE_FSTATAT)
    # and os.open (HAVE_OPENAT) registered dir_fd-capable, os.listdir
    # (HAVE_FDOPENDIR) fd-capable, os.stat registered follow_symlinks-
    # capable (HAVE_LSTAT/HAVE_FSTATAT -- the registry governing
    # follow_symlinks=False), O_DIRECTORY present -- while os.lstat is
    # absent from supports_dir_fd even though os.lstat(path, dir_fd=fd)
    # works there (fstatat with AT_SYMLINK_NOFOLLOW, the same capability
    # that registers os.stat).
    return {
        "supports_dir_fd": {os.open, os.stat},
        "supports_fd": {os.listdir, os.stat},
        "supports_follow_symlinks": {os.stat},
        "has_o_directory": True,
    }


def test_predicate_true_on_linux_shaped_capability_sets():
    caps = _linux_shaped_capabilities()
    assert os.lstat not in caps["supports_dir_fd"]  # the exact Ubuntu trap
    assert validate_module._dir_fd_binding_supported(**caps) is True


@pytest.mark.parametrize(
    "absent",
    ["open", "stat", "listdir", "follow_symlinks", "o_directory", "everything"],
)
def test_predicate_false_when_any_primitive_is_absent(absent):
    caps = _linux_shaped_capabilities()
    if absent == "open":
        caps["supports_dir_fd"] = {os.stat}
    elif absent == "stat":
        caps["supports_dir_fd"] = {os.open}
    elif absent == "listdir":
        caps["supports_fd"] = set()
    elif absent == "follow_symlinks":
        # dir_fd support alone is NOT enough: the lane's inspection call
        # passes follow_symlinks=False, and an unregistered
        # follow_symlinks raises NotImplementedError (not an OSError) at
        # runtime -- the predicate must refuse the lane instead.
        caps["supports_follow_symlinks"] = set()
    elif absent == "o_directory":
        caps["has_o_directory"] = False
    else:
        caps = {
            "supports_dir_fd": set(),
            "supports_fd": set(),
            "supports_follow_symlinks": set(),
            "has_o_directory": False,
        }
    assert validate_module._dir_fd_binding_supported(**caps) is False


def test_compiled_flag_matches_real_platform_capabilities():
    # On every platform the module-level flag must equal the predicate
    # over the REAL capability sets -- neither under- nor over-claiming.
    assert validate_module._DIR_FD_SUPPORTED == (
        validate_module._dir_fd_binding_supported(
            os.supports_dir_fd,
            os.supports_fd,
            os.supports_follow_symlinks,
            hasattr(os, "O_DIRECTORY"),
        )
    )


def test_posix_with_dir_fd_primitives_must_select_fd_mode():
    # Anti-skip sentinel: wherever the platform really provides the
    # descriptor primitives (every Linux CI runner), the fd lane MUST be
    # on -- otherwise the @_dir_fd_only tests above silently skip and
    # ordinary validation refuses, exactly the Ubuntu regression.
    if not (
        os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and os.listdir in os.supports_fd
        and hasattr(os, "O_DIRECTORY")
    ):
        pytest.skip("platform genuinely lacks descriptor primitives")
    assert validate_module._DIR_FD_SUPPORTED is True


def test_ordinary_directory_without_dir_fd_binds_or_refuses(
    tmp_path, capsys, monkeypatch
):
    # Without directory-relative descriptors the validator must either
    # hold the fallback binding (Windows) or refuse before enumeration
    # (platforms with neither primitive) -- never enumerate unbound.
    monkeypatch.setattr(validate_module, "_DIR_FD_SUPPORTED", False)
    _write_entry(tmp_path, "TLV4-001")
    _write_entry(tmp_path, "TLV4-002")
    rc = main([str(tmp_path)])
    captured = capsys.readouterr()
    if validate_module._FALLBACK_BINDING_SUPPORTED:
        assert rc == 0, captured.err
        assert json.loads(captured.out)["entry_count"] == 2
    else:
        assert rc == 4
        _assert_one_error_line(captured.err)
        assert "binding" in captured.err


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
