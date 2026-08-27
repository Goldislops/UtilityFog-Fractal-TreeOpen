"""Capture, ceiling, exit-class, determinism and non-disclosure controls.

Every records tree used here is built under pytest's ``tmp_path``. Nothing is
written inside the repository, on any path, in any control.

Control ids SR-C-NNN are declared in ``test_controls_manifest.py``.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys

import pytest

from experiments.source_record.tests import _support as sup
from experiments.source_record.tests.test_records import (
    build_root,
    minimal_valid_set,
)


def tree_snapshot(root):
    """Sorted (relative path, size) pairs for every file below ``root``."""
    return sorted(
        (str(path.relative_to(root)), path.stat().st_size)
        for path in root.rglob("*")
        if path.is_file()
    )


# --------------------------------------------------------------------------
# Success path and summary
# --------------------------------------------------------------------------


def test_sr_c_001_a_valid_records_root_exits_zero_with_a_canonical_summary(
    tmp_path, capsys
):
    validate = sup.require_validate()
    root = build_root(tmp_path, minimal_valid_set())
    code = validate.main([str(root)])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert captured.out.endswith("\n")
    body = captured.out[:-1]
    assert body == json.dumps(
        json.loads(body), sort_keys=True, ensure_ascii=True, separators=(",", ":")
    )


def test_sr_c_002_the_emitted_summary_reports_three_registers_and_no_total(
    tmp_path, capsys
):
    validate = sup.require_validate()
    root = build_root(tmp_path, minimal_valid_set())
    validate.main([str(root)])
    summary = json.loads(capsys.readouterr().out)
    assert set(summary) == {"schema", "registers"}
    assert set(summary["registers"]) == set(sup.REGISTER_DIR_NAMES)
    for name in sup.REGISTER_DIR_NAMES:
        assert set(summary["registers"][name]) == {"record_count", "record_ids"}


def test_sr_c_003_serialize_summary_is_byte_stable_across_repeated_calls(tmp_path):
    validate = sup.require_validate()
    root = build_root(tmp_path, minimal_valid_set())
    summary = validate.validate_records_root(root)
    rendered = [validate.serialize_summary(summary) for _ in range(5)]
    assert len(set(rendered)) == 1
    assert rendered[0].endswith("\n")


# --------------------------------------------------------------------------
# Exit classes
# --------------------------------------------------------------------------


def test_sr_c_004_a_missing_or_non_directory_path_exits_four(tmp_path, capsys):
    validate = sup.require_validate()
    assert validate.main([str(tmp_path / "absent")]) == 4
    capsys.readouterr()
    plain = tmp_path / "a-file"
    plain.write_text("synthetic", encoding="utf-8")
    assert validate.main([str(plain)]) == 4
    capsys.readouterr()


def test_sr_c_005_a_record_refusal_exits_two(tmp_path, capsys):
    validate = sup.require_validate()
    records = minimal_valid_set()
    records[0]["origin"] = "ingested"
    root = build_root(tmp_path, records)
    assert validate.main([str(root)]) == 2
    capsys.readouterr()


def test_sr_c_006_malformed_json_and_a_duplicate_json_key_exit_two(
    tmp_path, capsys
):
    validate = sup.require_validate()
    root = build_root(tmp_path, minimal_valid_set())
    (root / "register-a" / "SR-A-SRC-0001.json").write_text(
        "{not json", encoding="utf-8"
    )
    assert validate.main([str(root)]) == 2
    capsys.readouterr()

    root = build_root(tmp_path / "second", minimal_valid_set())
    (root / "register-a" / "SR-A-SRC-0001.json").write_text(
        '{"schema": "source-record-v1", "schema": "source-record-v1"}',
        encoding="utf-8",
    )
    assert validate.main([str(root)]) == 2
    capsys.readouterr()


def test_sr_c_007_each_ceiling_class_exits_five(tmp_path, capsys):
    validate = sup.require_validate()

    root = build_root(tmp_path / "count", [])
    for index in range(validate.MAX_RECORDS_PER_DIR + 1):
        (root / "register-a" / f"SR-A-SRC-{index:04d}.json").write_text(
            "{}", encoding="utf-8"
        )
    assert validate.main([str(root)]) == 5
    capsys.readouterr()

    root = build_root(tmp_path / "bytes", [])
    (root / "register-a" / "SR-A-SRC-0001.json").write_bytes(
        b"x" * (validate.MAX_RECORD_BYTES + 1)
    )
    assert validate.main([str(root)]) == 5
    capsys.readouterr()

    root = build_root(tmp_path / "total", [])
    chunk = b"x" * 64000
    count = validate.MAX_TOTAL_BYTES // 64000 + 2
    for index in range(count):
        (root / "register-a" / f"SR-A-SRC-{index:04d}.json").write_bytes(chunk)
    assert validate.main([str(root)]) == 5
    capsys.readouterr()


def test_sr_c_008_an_argparse_usage_error_keeps_its_own_systemexit_two(capsys):
    validate = sup.require_validate()
    with pytest.raises(SystemExit) as excinfo:
        validate.main([])
    assert excinfo.value.code == 2
    capsys.readouterr()


def test_sr_c_009_an_unrelated_programming_error_propagates(tmp_path, monkeypatch):
    validate = sup.require_validate()
    root = build_root(tmp_path, minimal_valid_set())

    class Sentinel(Exception):
        pass

    def explode(*_args, **_kwargs):
        raise Sentinel("synthetic programming fault")

    monkeypatch.setattr(validate, "validate_records_root", explode)
    with pytest.raises(Sentinel):
        validate.main([str(root)])


# --------------------------------------------------------------------------
# Non-disclosure
# --------------------------------------------------------------------------


def test_sr_c_010_exactly_one_stderr_line_is_printed_per_expected_failure(
    tmp_path, capsys
):
    validate = sup.require_validate()
    records = minimal_valid_set()
    records[0]["origin"] = "ingested"
    records[1]["recorded_by_label"] = ""
    root = build_root(tmp_path, records)
    validate.main([str(root)])
    captured = capsys.readouterr()
    assert len(captured.err.splitlines()) == 1
    assert captured.err.endswith("\n")


def test_sr_c_011_no_planted_marker_reaches_any_output_channel(tmp_path, capsys):
    validate = sup.require_validate()
    records = minimal_valid_set()
    records[1]["neutral_label"] = sup.MARKER_VALUE
    records[1][sup.MARKER_KEY] = sup.MARKER_SECRET_SHAPED
    root = build_root(tmp_path, records)
    code = validate.main([str(root)])
    captured = capsys.readouterr()
    assert code == 2
    for marker in sup.MARKERS:
        assert marker not in captured.out
        assert marker not in captured.err


def test_sr_c_012_an_undeclared_key_discloses_neither_its_name_nor_its_position(
    tmp_path, capsys
):
    validate = sup.require_validate()
    records = minimal_valid_set()
    records[1][sup.MARKER_KEY] = "synthetic value"
    root = build_root(tmp_path, records)
    validate.main([str(root)])
    err = capsys.readouterr().err
    assert "undeclared-key" in err
    assert sup.MARKER_KEY not in err
    for digit_hint in ("index", "position", "count"):
        assert digit_hint not in err


def test_sr_c_013_a_hostile_path_argument_is_never_echoed(tmp_path, capsys):
    validate = sup.require_validate()
    hostile = str(tmp_path / (sup.MARKER_VALUE + "-absent"))
    code = validate.main([hostile])
    captured = capsys.readouterr()
    assert code == 4
    assert sup.MARKER_VALUE not in captured.err
    assert sup.MARKER_VALUE not in captured.out
    assert len(captured.err.splitlines()) == 1
    for control in ("\r", "\x1b", "\x07"):
        assert control not in captured.err


def test_sr_c_014_a_refusal_carrier_exposes_only_a_token_and_a_path(tmp_path):
    validate = sup.require_validate()
    schema = sup.require_schema()
    records = minimal_valid_set()
    records[0]["origin"] = "ingested"
    root = build_root(tmp_path, records)
    with pytest.raises(validate.RecordsInputError) as excinfo:
        validate.validate_records_root(root)
    error = excinfo.value
    assert isinstance(error.token, str)
    assert isinstance(error.path, tuple)
    assert error.token in schema.REFUSAL_TOKENS
    for name in dir(error):
        assert "value" not in name.lower(), name


def test_sr_c_015_exception_chaining_carries_no_context(tmp_path):
    validate = sup.require_validate()
    root = build_root(tmp_path, minimal_valid_set())
    (root / "register-a" / "SR-A-SRC-0001.json").write_text(
        "{not json " + sup.MARKER_VALUE, encoding="utf-8"
    )
    with pytest.raises(validate.RecordsInputError) as excinfo:
        validate.validate_records_root(root)
    error = excinfo.value
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    assert sup.MARKER_VALUE not in str(error)


def test_sr_c_016_no_environment_variable_alters_refusal_content(
    tmp_path, capsys, monkeypatch
):
    validate = sup.require_validate()
    records = minimal_valid_set()
    records[0]["origin"] = "ingested"
    root = build_root(tmp_path, records)
    validate.main([str(root)])
    baseline = capsys.readouterr().err
    for name in ("DEBUG", "VERBOSE", "SOURCE_RECORD_DEBUG", "PYTHONVERBOSE"):
        monkeypatch.setenv(name, "1")
    validate.main([str(root)])
    assert capsys.readouterr().err == baseline


# --------------------------------------------------------------------------
# Purity, determinism, isolation
# --------------------------------------------------------------------------


def test_sr_c_017_the_validator_writes_nothing_on_any_path(tmp_path, capsys):
    validate = sup.require_validate()
    good = build_root(tmp_path / "good", minimal_valid_set())
    bad_records = minimal_valid_set()
    bad_records[0]["origin"] = "ingested"
    bad = build_root(tmp_path / "bad", bad_records)
    for root in (good, bad):
        before = tree_snapshot(root)
        validate.main([str(root)])
        capsys.readouterr()
        assert tree_snapshot(root) == before


def test_sr_c_018_no_network_call_is_attempted_on_any_path(
    tmp_path, capsys, monkeypatch
):
    validate = sup.require_validate()
    attempts = []

    def refuse(*args, **kwargs):
        attempts.append(args)
        raise AssertionError("the laboratory must not open a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    root = build_root(tmp_path, minimal_valid_set())
    validate.main([str(root)])
    capsys.readouterr()
    assert attempts == []


def test_sr_c_019_output_is_identical_across_permuted_enumeration_order(
    tmp_path, capsys
):
    validate = sup.require_validate()
    records = minimal_valid_set()
    first = build_root(tmp_path / "one", records)
    second = build_root(tmp_path / "two", list(reversed(records)))
    validate.main([str(first)])
    out_one = capsys.readouterr().out
    validate.main([str(second)])
    out_two = capsys.readouterr().out
    assert out_one == out_two


def test_sr_c_020_output_is_identical_across_processes_with_differing_hash_seeds(
    tmp_path,
):
    sup.require_validate()
    root = build_root(tmp_path, minimal_valid_set())
    outputs = []
    for seed in ("0", "1", "12345"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = str(sup.REPO_ROOT)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "experiments.source_record.validate",
                str(root),
            ],
            capture_output=True,
            env=env,
            cwd=str(sup.REPO_ROOT),
            check=False,
        )
        assert completed.returncode == 0, completed.stderr.decode(
            "utf-8", "replace"
        )
        outputs.append(completed.stdout)
    assert len(set(outputs)) == 1


def test_sr_c_021_no_timestamp_or_environment_value_appears_in_the_summary(
    tmp_path, capsys
):
    validate = sup.require_validate()
    root = build_root(tmp_path, minimal_valid_set())
    validate.main([str(root)])
    out = capsys.readouterr().out
    for fragment in (str(os.getpid()), "T00:", "Z\"", str(tmp_path)):
        assert fragment not in out


def test_sr_c_022_no_public_callable_exposes_a_forbidden_parameter(tmp_path):
    validate = sup.require_validate()
    schema = sup.require_schema()
    import inspect

    forbidden = {
        "depth",
        "max_hops",
        "recursive",
        "traverse",
        "dedup",
        "deduplicate",
        "independence",
        "total",
        "flatten",
        "flat",
        "cross_register",
    }
    checked = 0
    for module in (schema, validate):
        for name, value in sorted(vars(module).items()):
            if name.startswith("_") or not callable(value):
                continue
            if getattr(value, "__module__", None) != module.__name__:
                continue
            try:
                signature = inspect.signature(value)
            except (TypeError, ValueError):
                continue
            checked += 1
            for parameter in signature.parameters:
                assert parameter not in forbidden, (name, parameter)
            assert not (forbidden & set(name.split("_"))), name
    assert checked > 0, "no public callable was examined"
