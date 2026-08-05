"""Machine-readable error contract for the Observatory CLI.

Scope: the `--error-format json` envelope and the automatic upgrade for
`info --json` / `doctor --json`. The envelope's own construction and
sanitising live in `vis.observatory.cli_errors`; wiring, streams and exit
statuses live in `vis.observatory.cli`.

Two distinctions this module exists to pin down:

  * A CLI *invocation* failure produces an envelope on stderr with an empty
    stdout. A completed `doctor` run that merely contains failed checks is a
    normal report on stdout with an empty stderr -- same exit status 1,
    entirely different shape. The envelope is therefore keyed on the
    `_UserError` type, never on "the status was 1".
  * Human mode is unchanged and remains the default. The envelope is opt-in.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from vis.observatory import cli as cli_mod
from vis.observatory import cli_errors

REPO_ROOT = Path(__file__).resolve().parent.parent

# Everything `str.splitlines()` treats as a line boundary. The envelope must
# survive every one of them on a single physical line.
LINE_BREAKS = ["\n", "\r\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e",
               "\x85", " ", " "]

REQUIRED_KEYS = {
    "schema", "ok", "category", "code", "message",
    "suggestion", "command", "argument", "exit_status",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _envelope_line(stderr):
    """Return the envelope, which is the LAST line of stderr.

    Deliberately not "stderr contains only the envelope". stderr is shared:
    the warnings machinery, matplotlib and an interpreter shutdown notice can
    all write there, none of them under this CLI's control. The enforceable
    contract -- and the one consumers are told to rely on -- is that the
    envelope is the final line and is itself exactly one physical line.
    """
    lines = [line for line in stderr.splitlines() if line.strip()]
    assert lines, "no stderr output at all"
    return lines[-1]


def _only_envelope(capsys, expect_status=None):
    """Assert stdout is empty and stderr's last line is one JSON envelope."""
    captured = capsys.readouterr()
    assert captured.out == "", f"stdout leaked: {captured.out[:200]!r}"
    text = captured.err
    # `endswith` rather than a newline count: `print` emits the platform
    # terminator, so this is CRLF on Windows and LF on the CI runner.
    assert text.endswith("\n")
    line = _envelope_line(text)
    assert len(line.splitlines()) == 1, "envelope must be one physical line"
    document = json.loads(line)
    assert isinstance(document, dict)
    if expect_status is not None:
        assert document["exit_status"] == expect_status
    return document


def _run_json(argv):
    """Drive `main()` for an argv that must fail, returning (status, capsys).

    Usage errors raise SystemExit; runtime errors return an int. Both are
    normalised to a status so a single helper covers every category.
    """
    try:
        return cli_mod.main(argv)
    except SystemExit as exc:
        return exc.code


def _run_module(*args):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["MPLBACKEND"] = "Agg"
    return subprocess.run(
        [sys.executable, "-m", "vis.observatory", *args],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=120,
    )


@pytest.fixture
def snap(tmp_path):
    """A path that passes validation but is not a loadable snapshot."""
    path = tmp_path / "snap.npz"
    path.write_bytes(b"not really an npz")
    return str(path)


# ===========================================================================
# The module itself: standard library only, no rendering stack
# ===========================================================================


def test_cli_errors_imports_only_the_standard_library():
    """Parsed from the source, so a lazy or conditional import cannot hide."""
    source = Path(cli_errors.__file__).read_text(encoding="utf-8")
    roots = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
            elif node.level:
                pytest.fail(f"relative import in cli_errors: {ast.dump(node)}")
    non_stdlib = roots - set(sys.stdlib_module_names)
    assert non_stdlib == set(), f"non-stdlib imports: {sorted(non_stdlib)}"


def test_cli_errors_references_no_renderer_or_numeric_stack():
    """Bare words like "animation" and "dashboard" are legitimate vocabulary
    here -- `animation-directory-invalid` is an error code -- so this scans for
    module references rather than substrings. The AST walk above is the
    authoritative import check; this supplements it."""
    source = Path(cli_errors.__file__).read_text(encoding="utf-8")
    for banned in ("numpy", "matplotlib", "plotly", "scatter3d",
                   "vis.observatory.", "import vis"):
        assert banned not in source, f"cli_errors references {banned}"


def test_cli_errors_loads_without_the_observatory_package():
    """In a fresh interpreter, by file path, with no package import: the
    module must come up without pulling NumPy or matplotlib."""
    probe = (
        "import importlib.util, sys;"
        "spec = importlib.util.spec_from_file_location('ce', sys.argv[1]);"
        "m = importlib.util.module_from_spec(spec);"
        "spec.loader.exec_module(m);"
        "assert 'numpy' not in sys.modules, 'numpy imported';"
        "assert 'matplotlib' not in sys.modules, 'matplotlib imported';"
        "print(m.ERROR_SCHEMA)"
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-c", probe, cli_errors.__file__],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == cli_errors.ERROR_SCHEMA


# ===========================================================================
# Vocabulary
# ===========================================================================


def test_category_vocabulary_is_closed():
    assert cli_errors.CATEGORIES == frozenset({"usage", "input"})


def test_every_code_maps_to_a_declared_category():
    assert cli_errors.CODES, "the code vocabulary must not be empty"
    for code, category in cli_errors.CODES.items():
        assert category in cli_errors.CATEGORIES, f"{code} -> {category}"
        assert code == code.lower()
        assert " " not in code


@pytest.mark.parametrize(
    "code",
    [
        "missing-command", "unknown-command", "unknown-option",
        "missing-argument", "invalid-argument-value",
        "snapshot-not-found", "snapshot-wrong-path-kind",
        "snapshot-unsupported-suffix", "snapshot-unreadable",
        "animation-directory-invalid", "level-out-of-range",
    ],
)
def test_required_codes_are_declared(code):
    """The eleven cases the contract must name."""
    assert code in cli_errors.CODES


def test_usage_codes_are_status_two_and_input_codes_are_status_one():
    for code, category in cli_errors.CODES.items():
        expected = 2 if category == "usage" else 1
        assert cli_errors.status_for(code) == expected, code


# ===========================================================================
# Envelope construction
# ===========================================================================


def _envelope(**kwargs):
    kwargs.setdefault("code", "unknown-command")
    kwargs.setdefault("message", "unknown command 'bod'")
    return cli_errors.build_envelope(**kwargs)


def test_envelope_has_exactly_the_documented_keys():
    assert set(_envelope()) == REQUIRED_KEYS


def test_envelope_fixed_fields():
    document = _envelope()
    assert document["schema"] == "utilityfog.observatory.error/1"
    assert document["ok"] is False
    assert document["category"] == "usage"
    assert document["exit_status"] == 2


def test_nullable_fields_are_present_rather_than_omitted():
    document = _envelope()
    for key in ("suggestion", "command", "argument"):
        assert key in document
        assert document[key] is None


def test_envelope_values_are_ordinary_json_types():
    document = _envelope(suggestion="Did you mean 'body'?", command="body",
                         argument="--level")
    for key, value in document.items():
        assert type(key) is str
        assert type(value) in (str, int, bool, type(None)), f"{key}={value!r}"


def test_render_is_one_line_with_one_trailing_newline():
    text = cli_errors.render(_envelope())
    assert text.endswith("\n")
    assert text.count("\n") == 1
    assert len(text.strip().splitlines()) == 1


def test_render_sorts_keys_and_uses_compact_separators():
    text = cli_errors.render(_envelope()).rstrip("\n")
    document = json.loads(text)
    assert list(document) == sorted(REQUIRED_KEYS)
    assert ", " not in text and '": ' not in text


def test_render_is_ascii_escaped():
    """`ensure_ascii=True` is what keeps the one-line contract true for a
    hostile path: it escapes U+2028/U+2029 and every other separator that
    `str.splitlines()` recognises but `json.dumps` would otherwise pass
    through verbatim."""
    text = cli_errors.render(_envelope(message="a b c\x85d"))
    assert text.isascii()
    assert len(text.strip().splitlines()) == 1


@pytest.mark.parametrize("sep", LINE_BREAKS)
def test_render_stays_one_line_for_every_separator(sep):
    text = cli_errors.render(_envelope(message=f"before{sep}after"))
    assert len(text.strip().splitlines()) == 1
    assert text.count("\n") == 1


def test_render_is_byte_stable():
    a = cli_errors.render(_envelope(suggestion="s", command="c", argument="a"))
    b = cli_errors.render(_envelope(suggestion="s", command="c", argument="a"))
    assert a == b


def test_render_emits_no_non_standard_tokens():
    text = cli_errors.render(_envelope())
    assert "NaN" not in text and "Infinity" not in text


# --- bounding ---------------------------------------------------------------


@pytest.mark.parametrize("field", ["message", "suggestion", "argument", "command"])
def test_long_values_are_bounded_with_a_visible_marker(field):
    document = _envelope(**{field: "x" * 100_000})
    value = document[field]
    assert len(value) <= cli_errors.MAX_FIELD_LENGTH + 8
    assert value.endswith("..."), "truncation must be visible, not silent"


def test_bounded_envelope_still_parses():
    text = cli_errors.render(_envelope(message="y" * 100_000))
    assert json.loads(text.rstrip("\n"))["message"].endswith("...")


def test_short_values_are_not_altered():
    assert _envelope(message="plain")["message"] == "plain"


def test_quotes_and_backslashes_round_trip():
    hostile = 'a"b\\c{}d'
    document = json.loads(cli_errors.render(_envelope(message=hostile)))
    assert document["message"] == hostile


def test_envelope_never_contains_traceback_text():
    document = _envelope(message="Traceback (most recent call last): boom")
    assert "Traceback (most recent call last)" not in json.dumps(document)


# ===========================================================================
# CLI wiring: usage errors (status 2)
# ===========================================================================


USAGE_CASES = [
    pytest.param([], "missing-command", id="missing-command"),
    pytest.param(["zzzzzzzzzz"], "unknown-command", id="unknown-command-distant"),
    pytest.param(["slize"], "unknown-command", id="unknown-command-close"),
    pytest.param(["doctor"], "missing-argument", id="missing-argument"),
]


@pytest.mark.parametrize("tail, code", USAGE_CASES)
def test_usage_errors_emit_an_envelope_with_status_two(capsys, tail, code):
    assert _run_json(["--error-format", "json", *tail]) == 2
    document = _only_envelope(capsys, expect_status=2)
    assert document["category"] == "usage"
    assert document["code"] == code


def test_unknown_option_emits_an_envelope(capsys, snap):
    assert _run_json(["--error-format", "json", "info", snap, "--nope"]) == 2
    document = _only_envelope(capsys, expect_status=2)
    assert document["code"] == "unknown-option"


@pytest.mark.parametrize(
    "tail",
    [
        ["slice", "S", "--channel", "99"],
        ["slice", "S", "--channel", "abc"],
        ["animate", "D", "--max-frames", "0"],
        ["signal", "S", "--threshold", "-1"],
        ["signal", "S", "--threshold", "nan"],
    ],
)
def test_invalid_argument_values_emit_an_envelope(capsys, tmp_path, tail):
    argv = ["--error-format", "json", *[
        str(tmp_path / "s.npz") if t == "S" else
        str(tmp_path) if t == "D" else t for t in tail]]
    assert _run_json(argv) == 2
    document = _only_envelope(capsys, expect_status=2)
    assert document["code"] == "invalid-argument-value"


def test_close_typo_carries_a_structured_suggestion(capsys):
    assert _run_json(["--error-format", "json", "slize", "x.npz"]) == 2
    document = _only_envelope(capsys, expect_status=2)
    assert document["code"] == "unknown-command"
    assert document["suggestion"] is not None
    assert "slice" in document["suggestion"]


def test_distant_typo_has_no_suggestion(capsys):
    assert _run_json(["--error-format", "json", "zzzzzzzzzz", "x.npz"]) == 2
    document = _only_envelope(capsys, expect_status=2)
    assert document["suggestion"] is None


def test_suggestion_survives_a_leading_global_option(capsys):
    """Regression: `_first_command_token` skips tokens beginning with `-` but
    had no notion of an option that consumes a value, so the flag's value
    would be read as the subcommand and the did-you-mean feature lost."""
    assert _run_json(["--error-format", "json", "slize", "x.npz"]) == 2
    assert _only_envelope(capsys)["suggestion"] is not None


def test_suggestion_survives_the_equals_form(capsys):
    assert _run_json(["--error-format=json", "slize", "x.npz"]) == 2
    assert _only_envelope(capsys)["suggestion"] is not None


def test_suggestion_still_works_in_human_mode_with_the_flag_present(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["--error-format", "human", "slize", "x.npz"])
    assert exc.value.code == 2
    assert "did you mean" in capsys.readouterr().err.lower()


# ===========================================================================
# CLI wiring: runtime errors (status 1)
# ===========================================================================


def test_missing_snapshot_emits_an_envelope(capsys, tmp_path):
    assert _run_json(["--error-format", "json", "info",
                      str(tmp_path / "absent.npz")]) == 1
    document = _only_envelope(capsys, expect_status=1)
    assert document["category"] == "input"
    assert document["code"] == "snapshot-not-found"


def test_directory_where_snapshot_expected_emits_an_envelope(capsys, tmp_path):
    assert _run_json(["--error-format", "json", "info", str(tmp_path)]) == 1
    assert _only_envelope(capsys)["code"] == "snapshot-wrong-path-kind"


def test_unsupported_suffix_emits_an_envelope(capsys, tmp_path):
    path = tmp_path / "snap.txt"
    path.write_text("x", encoding="utf-8")
    assert _run_json(["--error-format", "json", "info", str(path)]) == 1
    assert _only_envelope(capsys)["code"] == "snapshot-unsupported-suffix"


def test_unreadable_snapshot_emits_an_envelope(capsys, snap):
    assert _run_json(["--error-format", "json", "info", snap]) == 1
    document = _only_envelope(capsys, expect_status=1)
    assert document["code"] == "snapshot-unreadable"
    assert "Traceback" not in json.dumps(document)


@pytest.mark.parametrize("kind", ["missing", "not-a-directory"])
def test_animation_directory_problems_emit_an_envelope(capsys, tmp_path, kind):
    if kind == "missing":
        target = tmp_path / "absent"
    else:
        target = tmp_path / "afile"
        target.write_text("x", encoding="utf-8")
    assert _run_json(["--error-format", "json", "animate", str(target)]) == 1
    assert _only_envelope(capsys)["code"] == "animation-directory-invalid"


# ===========================================================================
# Human mode is unchanged and remains the default
# ===========================================================================


def test_human_is_the_default(capsys, tmp_path):
    assert cli_mod.main(["info", str(tmp_path / "absent.npz")]) == 1
    err = capsys.readouterr().err
    assert err.startswith("cosmic-observatory: error: ")
    with pytest.raises(json.JSONDecodeError):
        json.loads(err)


def test_explicit_human_matches_the_default_byte_for_byte(capsys, tmp_path):
    target = str(tmp_path / "absent.npz")
    assert cli_mod.main(["info", target]) == 1
    default = capsys.readouterr().err
    assert cli_mod.main(["--error-format", "human", "info", target]) == 1
    assert capsys.readouterr().err == default


def test_human_error_is_still_one_line_for_a_hostile_path(capsys, tmp_path):
    hostile = str(tmp_path / "we\rird\nname.npz")
    assert cli_mod.main(["info", hostile]) == 1
    err = capsys.readouterr().err
    assert len(err.strip().splitlines()) == 1


# ===========================================================================
# Help stays human at status 0
# ===========================================================================


@pytest.mark.parametrize("argv", [
    ["--error-format", "json", "--help"],
    ["--error-format", "json", "slice", "--help"],
    ["--error-format", "json", "--help", "slize"],
])
def test_help_stays_human_and_exits_zero(capsys, argv):
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(argv)
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert captured.out.strip() != ""
    assert captured.err == ""
    with pytest.raises(json.JSONDecodeError):
        json.loads(captured.out)


def test_error_format_is_documented_in_help(capsys):
    with pytest.raises(SystemExit):
        cli_mod.main(["--help"])
    out = capsys.readouterr().out
    assert "--error-format" in out
    assert "doctor" in out, "existing help content is preserved"


def test_invalid_error_format_value_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["--error-format", "yaml", "info", "x.npz"])
    assert exc.value.code == 2


def test_error_format_after_the_subcommand_is_a_usage_error(capsys, snap):
    """Documented position is before the subcommand."""
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["info", snap, "--error-format", "json"])
    assert exc.value.code == 2


# ===========================================================================
# Automatic envelope for `info --json` / `doctor --json`
# ===========================================================================


@pytest.mark.parametrize("command", ["info", "doctor"])
def test_json_commands_auto_upgrade_their_load_failures(capsys, command, snap):
    """No global flag: a machine-oriented command must not answer a machine
    consumer with human prose."""
    assert cli_mod.main([command, snap, "--json"]) == 1
    document = _only_envelope(capsys, expect_status=1)
    assert document["schema"] == cli_errors.ERROR_SCHEMA
    assert document["code"] == "snapshot-unreadable"


@pytest.mark.parametrize("command", ["info", "doctor"])
def test_json_commands_stay_human_without_the_flag(capsys, command, snap):
    assert cli_mod.main([command, snap]) == 1
    err = capsys.readouterr().err
    assert err.startswith("cosmic-observatory: error: ")


def test_auto_upgrade_does_not_apply_to_other_subcommands(capsys, snap):
    assert cli_mod.main(["slice", snap]) == 1
    assert capsys.readouterr().err.startswith("cosmic-observatory: error: ")


@pytest.mark.parametrize("command", ["info", "doctor"])
def test_explicit_human_overrides_the_auto_upgrade(capsys, command, snap):
    assert cli_mod.main(["--error-format", "human", command, snap, "--json"]) == 1
    assert capsys.readouterr().err.startswith("cosmic-observatory: error: ")


@pytest.mark.parametrize("command", ["info", "doctor"])
def test_global_and_command_json_produce_exactly_one_envelope(capsys, command, snap):
    assert cli_mod.main(["--error-format", "json", command, snap, "--json"]) == 1
    _only_envelope(capsys, expect_status=1)


# ===========================================================================
# A failed doctor CHECK is a report, not a CLI error
# ===========================================================================


def _bad_check_snapshot(tmp_path):
    np = pytest.importorskip("numpy")
    lattice = np.zeros((2, 3, 4), dtype=np.uint8)
    lattice[0, 0, 0] = 200                       # outside the vocabulary
    path = tmp_path / "badcheck.npz"
    np.savez(path, lattice=lattice,
             memory_grid=np.zeros((8, 2, 3, 4), dtype=np.float32),
             generation=7, ca_step=11, best_fitness=0.25)
    return str(path)


@pytest.mark.parametrize("prefix", [[], ["--error-format", "json"]])
def test_failed_doctor_check_is_a_report_not_an_envelope(capsys, tmp_path, prefix):
    """The distinction the whole contract rests on. Both are status 1: a
    completed diagnostic run with failures is a reported result on stdout,
    not a CLI invocation error. Keying the envelope on the status instead of
    on the error type is exactly what this test refuses."""
    pytest.importorskip("numpy")
    pytest.importorskip("matplotlib")
    path = _bad_check_snapshot(tmp_path)
    assert cli_mod.main([*prefix, "doctor", path]) == 1
    captured = capsys.readouterr()
    assert captured.err == "", "a failed check must not produce an error envelope"
    assert "[FAIL]" in captured.out


def test_failed_doctor_check_json_keeps_stderr_empty(capsys, tmp_path):
    pytest.importorskip("numpy")
    pytest.importorskip("matplotlib")
    path = _bad_check_snapshot(tmp_path)
    assert cli_mod.main(["doctor", path, "--json"]) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    document = json.loads(captured.out)
    assert document["ok"] is False
    assert document["kind"] == "doctor"


def test_report_and_envelope_are_distinguishable_by_schema(capsys, tmp_path, snap):
    """`ok: false` alone is not a discriminator -- a failing doctor report
    also carries it. The schema id and the stream are."""
    pytest.importorskip("numpy")
    pytest.importorskip("matplotlib")
    assert cli_mod.main(["doctor", _bad_check_snapshot(tmp_path), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)

    assert cli_mod.main(["doctor", snap, "--json"]) == 1
    envelope = json.loads(_envelope_line(capsys.readouterr().err))

    assert report["ok"] is False and envelope["ok"] is False
    assert report["schema"] != envelope["schema"]
    assert envelope["schema"] == cli_errors.ERROR_SCHEMA


# ===========================================================================
# Hostile input through the CLI
# ===========================================================================


@pytest.mark.parametrize("sep", LINE_BREAKS)
def test_hostile_path_keeps_the_envelope_on_one_line(capsys, tmp_path, sep):
    """The file is never created: a nonexistent path already reaches the
    not-found lane, which is the message that carries the hostile text."""
    hostile = f"{tmp_path}{os.sep}a{sep}b.npz"
    assert _run_json(["--error-format", "json", "info", hostile]) == 1
    document = _only_envelope(capsys, expect_status=1)
    assert document["code"] == "snapshot-not-found"


def test_hostile_path_cannot_forge_a_second_document(capsys, tmp_path):
    forged = f'{tmp_path}{os.sep}a\n{{"ok":true}}\nb.npz'
    assert _run_json(["--error-format", "json", "info", forged]) == 1
    document = _only_envelope(capsys, expect_status=1)
    assert document["ok"] is False


def test_very_long_path_is_bounded(capsys, tmp_path):
    long_path = f"{tmp_path}{os.sep}{'q' * 60000}.npz"
    assert _run_json(["--error-format", "json", "info", long_path]) == 1
    captured = capsys.readouterr()
    assert len(captured.err) < 4096, "envelope must stay bounded"
    json.loads(_envelope_line(captured.err))


# ===========================================================================
# Defect propagation must not widen
# ===========================================================================


class _Sentinel(Exception):
    """A stand-in for a programming defect, not a user error."""


def test_unexpected_defect_still_propagates_under_json(monkeypatch, snap):
    from vis.observatory import loader as loader_mod

    def _boom(_path):
        raise _Sentinel("defect inside the loader")

    monkeypatch.setattr(loader_mod, "load_snapshot", _boom)
    with pytest.raises(_Sentinel, match="defect inside the loader"):
        cli_mod.main(["--error-format", "json", "info", snap])


@pytest.mark.parametrize("defect", [AttributeError, TypeError, RecursionError])
def test_translated_error_set_never_covers_a_defect_class(defect):
    """The refactor must not widen the boundary."""
    translated = cli_mod._unreadable_input_errors()
    assert not any(issubclass(defect, caught) for caught in translated)


def test_no_envelope_is_emitted_for_an_unexpected_defect(monkeypatch, capsys, snap):
    from vis.observatory import loader as loader_mod

    monkeypatch.setattr(
        loader_mod, "load_snapshot",
        lambda _p: (_ for _ in ()).throw(_Sentinel("boom")),
    )
    with pytest.raises(_Sentinel):
        cli_mod.main(["--error-format", "json", "info", snap])
    assert capsys.readouterr().err == "", "a defect must not be dressed as a user error"


# ===========================================================================
# Public module route and stream identity
# ===========================================================================


@pytest.mark.parametrize(
    "args, status",
    [
        (["--error-format", "json", "zzzzzzzzzz"], 2),
        (["--error-format", "json", "info", "absent.npz"], 1),
    ],
)
def test_envelope_reaches_real_stderr_with_the_right_status(args, status):
    proc = _run_module(*args)
    assert proc.returncode == status
    assert proc.stdout == ""
    document = json.loads(_envelope_line(proc.stderr))
    assert document["exit_status"] == status
    assert "Traceback (most recent call last)" not in proc.stderr


def test_envelope_is_byte_stable_across_processes():
    a = _run_module("--error-format", "json", "info", "absent.npz")
    b = _run_module("--error-format", "json", "info", "absent.npz")
    assert a.stderr == b.stderr
    assert a.returncode == b.returncode


def test_help_through_the_public_route_stays_human():
    proc = _run_module("--error-format", "json", "--help")
    assert proc.returncode == 0
    assert proc.stderr == ""
    assert "--error-format" in proc.stdout
