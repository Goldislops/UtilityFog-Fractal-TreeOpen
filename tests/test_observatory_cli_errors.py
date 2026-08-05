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

# The Observatory package initializer imports `loader.py` and through it NumPy,
# and sibling `vis` modules import matplotlib. Guarding BEFORE the package
# import is what makes a missing optional stack a clean skip rather than a
# hard collection error -- the same convention as tests/test_observatory_cli.py.
pytest.importorskip("numpy")
pytest.importorskip("matplotlib")

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


def _envelopes_in(stderr):
    """Return every error envelope found on stderr, in order.

    This is the enforceable contract, and it is deliberately weaker than
    "stderr contains only the envelope" AND weaker than "the envelope is the
    final line". stderr is shared: the warnings machinery, matplotlib and an
    interpreter shutdown notice can all write there, before or after the CLI
    does, and none of them are under this CLI's control.

    What the CLI guarantees is that IT writes exactly one envelope line and no
    other prose. What a consumer does is scan for a JSON line whose ``schema``
    is the error schema, and -- if more than one is present, which can only
    come from something other than a single CLI invocation -- take the last.
    """
    found = []
    for raw in stderr.splitlines():
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            document = json.loads(line)
        except ValueError:
            continue
        if isinstance(document, dict) and document.get("schema") == cli_errors.ERROR_SCHEMA:
            found.append(document)
    return found


def _envelope_line(stderr):
    """The single envelope a consumer should select from ``stderr``."""
    found = _envelopes_in(stderr)
    assert found, f"no error envelope on stderr: {stderr[:300]!r}"
    return found[-1]


def _only_envelope(capsys, expect_status=None):
    """Assert stdout is empty and the CLI emitted exactly one envelope."""
    captured = capsys.readouterr()
    assert captured.out == "", f"stdout leaked: {captured.out[:200]!r}"
    text = captured.err
    # `endswith` rather than a newline count: `print` emits the platform
    # terminator, so this is CRLF on Windows and LF on the CI runner.
    assert text.endswith("\n")
    found = _envelopes_in(text)
    assert len(found) == 1, f"expected exactly one envelope, got {len(found)}"
    document = found[0]
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


def test_optional_dependency_guards_precede_the_observatory_imports():
    """Collection must SKIP, not error, when the optional numeric/rendering
    stack is absent.

    `from vis.observatory ...` executes `vis/observatory/__init__.py`, which
    imports `loader.py` and then NumPy, so a bare top-level Observatory import
    turns a skippable optional-dependency case into a hard collection error.
    The established convention in `tests/test_observatory_cli.py` is to call
    `pytest.importorskip` for numpy and matplotlib FIRST.

    Asserted structurally against this module's own source, in statement
    order, because the property is about import ordering at collection time --
    which cannot be observed from inside a module that has already imported
    successfully.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    guarded = []
    first_observatory_import = None
    for index, node in enumerate(tree.body):
        if (isinstance(node, ast.ImportFrom) and node.module
                and node.module.split(".")[0] == "vis"):
            if first_observatory_import is None:
                first_observatory_import = index
        # `np = pytest.importorskip("numpy")` or a bare call statement.
        call = None
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
        elif (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
            call = node.value
        if call is None or not isinstance(call.func, ast.Attribute):
            continue
        if call.func.attr != "importorskip":
            continue
        if call.args and isinstance(call.args[0], ast.Constant):
            guarded.append((index, call.args[0].value))

    assert first_observatory_import is not None, "no vis.* import found"
    names = {name for _, name in guarded}
    assert "numpy" in names, "missing pytest.importorskip('numpy')"
    assert "matplotlib" in names, "missing pytest.importorskip('matplotlib')"
    for index, name in guarded:
        if name in ("numpy", "matplotlib"):
            assert index < first_observatory_import, (
                f"importorskip({name!r}) must precede the first vis.* import"
            )


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
    envelope = _envelope_line(capsys.readouterr().err)

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
    _envelope_line(captured.err)


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
    document = _envelope_line(proc.stderr)
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


# ===========================================================================
# Audit corrections
# ===========================================================================


# --- repeated global option: the scan must agree with argparse -------------
#
# argparse's ordinary behaviour is last-wins for a repeated option. The
# pre-scan is a second reader of the same argv, so it must reach the same
# answer -- otherwise the format the CLI *emits* disagrees with the format it
# *parsed*, and which one you observe depends on whether the failure happened
# before or after `parse_args`.


@pytest.mark.parametrize(
    "flags, expected",
    [
        (["--error-format", "json", "--error-format", "human"], "human"),
        (["--error-format", "human", "--error-format", "json"], "json"),
        (["--error-format=json", "--error-format=human"], "human"),
        (["--error-format=human", "--error-format=json"], "json"),
        (["--error-format", "json", "--error-format=human"], "human"),
        (["--error-format=human", "--error-format", "json"], "json"),
    ],
)
def test_repeated_error_format_follows_last_wins(capsys, tmp_path, flags, expected):
    """Runtime lane: the emitted format must match the final selection."""
    target = str(tmp_path / "absent.npz")
    assert cli_mod.main([*flags, "info", target]) == 1
    err = capsys.readouterr().err
    if expected == "json":
        assert _envelopes_in(err), "expected an envelope, got human prose"
    else:
        assert not _envelopes_in(err), "expected human prose, got an envelope"
        assert err.startswith("cosmic-observatory: error: ")


@pytest.mark.parametrize(
    "flags, expected",
    [
        (["--error-format", "json", "--error-format", "human"], "human"),
        (["--error-format", "human", "--error-format", "json"], "json"),
    ],
)
def test_repeated_error_format_agrees_on_the_usage_lane(capsys, flags, expected):
    """Usage lane: decided entirely by the pre-scan, so it is the lane that
    exposes a scanner that disagrees with argparse."""
    with pytest.raises(SystemExit) as exc:
        cli_mod.main([*flags, "zzzzzzzzzz"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert bool(_envelopes_in(err)) is (expected == "json")


def test_the_scan_matches_what_argparse_parsed(capsys, tmp_path):
    """Stated as an equality rather than a shape: whatever argparse records in
    the namespace is what the emitter must have used."""
    target = str(tmp_path / "absent.npz")
    for flags in (["--error-format", "json", "--error-format", "human"],
                  ["--error-format", "human", "--error-format", "json"]):
        parsed = flags[-1] if "=" not in flags[-1] else flags[-1].split("=")[1]
        cli_mod.main([*flags, "info", target])
        err = capsys.readouterr().err
        assert bool(_envelopes_in(err)) is (parsed == "json"), flags


def test_an_invalid_repeat_does_not_select_a_format(capsys, tmp_path):
    """A bad value is a usage error argparse is about to report; it must not
    be accepted as a valid selection by the scanner either."""
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["--error-format", "json", "--error-format", "yaml",
                      "info", str(tmp_path / "absent.npz")])
    assert exc.value.code == 2


# --- a failed occurrence is STICKY ----------------------------------------
#
# Last-wins is only meaningful when every occurrence is valid. argparse cannot
# parse ANY of the invocations below, so the whole command line is refused --
# and the scanner must reach the same conclusion. A later valid occurrence
# must not launder an earlier invalid one into an accepted JSON selection, and
# an earlier valid occurrence must not survive a later missing value.
#
# The rules, stated once:
#   1. no occurrence            -> None
#   2. all occurrences valid    -> the last one (argparse's ordinary result)
#   3. ANY occurrence invalid or missing its value -> "human"
#   4. separated, equals and supported abbreviated forms agree


@pytest.mark.parametrize(
    "argv, expected",
    [
        # 1. absent
        pytest.param([], None, id="absent"),
        pytest.param(["info", "x.npz"], None, id="absent-with-command"),
        # 2. all valid -> last wins
        pytest.param(["--error-format", "json"], "json", id="single-json"),
        pytest.param(["--error-format", "human"], "human", id="single-human"),
        pytest.param(["--error-format", "json", "--error-format", "human"],
                     "human", id="valid-valid-separated"),
        pytest.param(["--error-format=human", "--error-format=json"],
                     "json", id="valid-valid-equals"),
        pytest.param(["--error-f", "json"], "json", id="abbreviated-valid"),
        # 3. any failure is sticky
        pytest.param(["--error-format", "yaml"], "human", id="single-invalid"),
        pytest.param(["--error-format", "yaml", "--error-format", "json"],
                     "human", id="invalid-then-valid-separated"),
        pytest.param(["--error-format=yaml", "--error-format=json"],
                     "human", id="invalid-then-valid-equals"),
        pytest.param(["--error-format", "json", "--error-format", "yaml"],
                     "human", id="valid-then-invalid-separated"),
        pytest.param(["--error-format=json", "--error-format=yaml"],
                     "human", id="valid-then-invalid-equals"),
        pytest.param(["--error-format", "json", "--error-format"],
                     "human", id="valid-then-missing-value"),
        pytest.param(["--error-format=json", "--error-format"],
                     "human", id="equals-then-missing-value"),
        pytest.param(["--error-format"], "human", id="missing-value-alone"),
        pytest.param(["--error-f", "yaml", "--error-format", "json"],
                     "human", id="abbreviated-invalid-then-valid"),
        pytest.param(["--error-f"], "human", id="abbreviated-missing-value"),
        # 4. mixed forms
        pytest.param(["--error-format=yaml", "--error-format", "json"],
                     "human", id="equals-invalid-then-separated-valid"),
        pytest.param(["--error-format", "json", "--error-format=yaml"],
                     "human", id="separated-valid-then-equals-invalid"),
    ],
)
def test_scanner_rules(argv, expected):
    """The seam directly: every rule pinned on one table."""
    assert cli_mod._scan_error_format(argv) == expected


FAILED_SCAN_INVOCATIONS = [
    pytest.param(["--error-format", "yaml", "--error-format", "json"],
                 id="invalid-then-valid"),
    pytest.param(["--error-format=yaml", "--error-format=json"],
                 id="invalid-then-valid-equals"),
    pytest.param(["--error-format", "json", "--error-format", "yaml"],
                 id="valid-then-invalid"),
    pytest.param(["--error-format=json", "--error-format=yaml"],
                 id="valid-then-invalid-equals"),
    pytest.param(["--error-format", "json", "--error-format"],
                 id="valid-then-missing-value"),
    pytest.param(["--error-format=json", "--error-format"],
                 id="equals-then-missing-value"),
    pytest.param(["--error-f", "yaml", "--error-format", "json"],
                 id="abbreviated-invalid-then-valid"),
]


@pytest.mark.parametrize("flags", FAILED_SCAN_INVOCATIONS)
def test_a_failed_error_format_is_refused_in_human_form(capsys, flags):
    """End to end: argparse cannot parse any of these, so the refusal is a
    status-2 usage error in HUMAN form -- a format that was never validly
    selected must not be trusted to carry the refusal."""
    with pytest.raises(SystemExit) as exc:
        cli_mod.main([*flags, "info", "x.npz"])
    assert exc.value.code == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert not _envelopes_in(captured.err), "refusal must not be a JSON envelope"
    assert "cosmic-observatory: error:" in captured.err


@pytest.mark.parametrize("flags", FAILED_SCAN_INVOCATIONS)
def test_a_failed_error_format_never_reaches_the_runtime_lane(capsys, flags, tmp_path):
    """The command never runs, so a runtime error cannot be reported either --
    argparse refuses first, with status 2 rather than 1."""
    with pytest.raises(SystemExit) as exc:
        cli_mod.main([*flags, "info", str(tmp_path / "absent.npz")])
    assert exc.value.code == 2
    assert not _envelopes_in(capsys.readouterr().err)


# --- the scan covers the GLOBAL PREFIX only -------------------------------
#
# `--error-format` is a global option: it is only meaningful before the
# subcommand, because the subparsers action consumes everything from the
# command name onward. The pre-scan must therefore stop at the first
# unconsumed non-option token -- the intended subcommand -- rather than
# walking the whole argv and treating the subcommand's own arguments as
# further global occurrences.


@pytest.mark.parametrize(
    "argv, expected",
    [
        # A misplaced trailing option must not overwrite a valid prefix
        # selection. argparse rejects the trailing option as a usage error,
        # but the caller DID validly ask for JSON, so the refusal is JSON.
        pytest.param(["--error-format", "json", "info", "s.npz",
                      "--error-format", "human"], "json", id="json-prefix-human-trailing"),
        pytest.param(["--error-format", "human", "info", "s.npz",
                      "--error-format", "json"], "human", id="human-prefix-json-trailing"),
        pytest.param(["--error-format=json", "info", "s.npz",
                      "--error-format=human"], "json", id="equals-prefix-equals-trailing"),
        pytest.param(["--error-f", "json", "info", "s.npz",
                      "--error-format", "human"], "json", id="abbrev-prefix-trailing"),
        # No valid prefix: a trailing misplaced option must not retroactively
        # select anything.
        pytest.param(["info", "s.npz", "--error-format", "json"],
                     None, id="no-prefix-trailing-json"),
        pytest.param(["info", "s.npz", "--error-format=json"],
                     None, id="no-prefix-trailing-equals"),
        pytest.param(["doctor", "s.npz", "--json", "--error-format", "json"],
                     None, id="no-prefix-after-flags"),
        # A trailing INVALID occurrence must not make the prefix sticky-human
        # either: the scan never reaches it.
        pytest.param(["--error-format", "json", "info", "s.npz",
                      "--error-format", "yaml"], "json", id="valid-prefix-invalid-trailing"),
        pytest.param(["--error-format", "json", "info", "s.npz",
                      "--error-format"], "json", id="valid-prefix-dangling-trailing"),
        # The subcommand's own options are never global occurrences.
        pytest.param(["--error-format", "json", "slice", "s.npz",
                      "--axis", "x", "--level", "3"], "json", id="subcommand-options-ignored"),
        # Sticky failure still applies when it happens IN the prefix.
        pytest.param(["--error-format", "yaml", "info", "s.npz",
                      "--error-format", "json"], "human", id="invalid-prefix-trailing-valid"),
    ],
)
def test_scanner_reads_only_the_global_prefix(argv, expected):
    assert cli_mod._scan_error_format(argv) == expected


def test_misplaced_trailing_option_still_yields_the_requested_json_envelope(capsys):
    """The end-to-end shape of thread 1: argparse refuses the misplaced
    trailing option, and because JSON was validly selected before the
    subcommand, the refusal is a JSON envelope rather than prose."""
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["--error-format", "json", "info", "s.npz",
                      "--error-format", "human"])
    assert exc.value.code == 2
    document = _only_envelope(capsys, expect_status=2)
    assert document["category"] == "usage"


def test_misplaced_trailing_option_keeps_human_when_human_was_selected(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["--error-format", "human", "info", "s.npz",
                      "--error-format", "json"])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert not _envelopes_in(captured.err)
    assert "cosmic-observatory: error:" in captured.err


def test_a_trailing_option_alone_selects_nothing(capsys):
    """No valid global prefix, so the refusal stays human."""
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["info", "s.npz", "--error-format", "json"])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert not _envelopes_in(captured.err)


def test_all_valid_repeats_still_follow_last_wins(capsys, tmp_path):
    """The correction must not damage the case that does parse."""
    target = str(tmp_path / "absent.npz")
    assert cli_mod.main(["--error-format", "human", "--error-format", "json",
                         "info", target]) == 1
    assert _envelopes_in(capsys.readouterr().err)

    assert cli_mod.main(["--error-format", "json", "--error-format", "human",
                         "info", target]) == 1
    err = capsys.readouterr().err
    assert not _envelopes_in(err)
    assert err.startswith("cosmic-observatory: error: ")


# --- usage-code classification --------------------------------------------


@pytest.mark.parametrize("tail", [["body", "S", "--save"], ["slice", "S", "--axis"]])
def test_option_missing_its_value_is_missing_argument(capsys, tmp_path, tail):
    """`--save` with nothing after it is a missing ARGUMENT, not an invalid
    value: no value was supplied to be invalid."""
    argv = ["--error-format", "json",
            *[str(tmp_path / "s.npz") if t == "S" else t for t in tail]]
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(argv)
    assert exc.value.code == 2
    assert _only_envelope(capsys, expect_status=2)["code"] == "missing-argument"


@pytest.mark.parametrize("command", ["info", "doctor"])
def test_value_given_to_a_valueless_flag_is_unknown_option(capsys, tmp_path, command):
    """`--json=value` supplies a value to a flag that takes none. The
    documented vocabulary calls that `unknown-option`."""
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["--error-format", "json", command,
                      str(tmp_path / "s.npz"), "--json=value"])
    assert exc.value.code == 2
    assert _only_envelope(capsys, expect_status=2)["code"] == "unknown-option"


@pytest.mark.parametrize(
    "tail",
    [
        ["slice", "S", "--axis", "q"],          # invalid choice
        ["channel", "S", "--mode", "nope"],     # invalid choice
        ["slice", "S", "--channel", "99"],      # invalid typed value
        ["slice", "S", "--level", "abc"],       # builtin int converter
    ],
)
def test_invalid_choices_and_values_stay_invalid_argument_value(capsys, tmp_path, tail):
    argv = ["--error-format", "json",
            *[str(tmp_path / "s.npz") if t == "S" else t for t in tail]]
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(argv)
    assert exc.value.code == 2
    assert _only_envelope(capsys)["code"] == "invalid-argument-value"


def test_unrecognised_usage_shapes_fall_back_honestly():
    """The fallback must exist and must be declared, so an unfamiliar argparse
    message is reported honestly rather than guessed into a specific code."""
    assert cli_errors.CODES["usage-error"] == "usage"
    code, _ = cli_mod._classify_usage_error("something argparse has never said")
    assert code == "usage-error"


# --- unexaminable paths are not "wrong kind" ------------------------------


def test_unexaminable_path_is_not_labelled_a_directory(capsys, tmp_path):
    """The OS refused to examine the path, so nothing was established about
    what kind of thing it is. Claiming `snapshot-wrong-path-kind` asserts it
    IS a directory, which was never determined."""
    long_path = f"{tmp_path}{os.sep}{'q' * 60000}.npz"
    assert _run_json(["--error-format", "json", "info", long_path]) == 1
    document = _only_envelope(capsys, expect_status=1)
    assert document["code"] == "input-error"
    assert document["category"] == "input"


def test_unexaminable_animation_directory_uses_the_fallback(capsys, tmp_path):
    long_path = f"{tmp_path}{os.sep}{'q' * 60000}"
    assert _run_json(["--error-format", "json", "animate", long_path]) == 1
    assert _only_envelope(capsys, expect_status=1)["code"] == "input-error"


def test_positively_established_path_kinds_keep_their_specific_codes(capsys, tmp_path):
    """The fallback must not swallow the cases that ARE determined."""
    cases = [
        (str(tmp_path), "snapshot-wrong-path-kind"),
        (str(tmp_path / "absent.npz"), "snapshot-not-found"),
    ]
    unsupported = tmp_path / "s.txt"
    unsupported.write_text("x", encoding="utf-8")
    cases.append((str(unsupported), "snapshot-unsupported-suffix"))

    for target, expected in cases:
        assert _run_json(["--error-format", "json", "info", target]) == 1
        assert _only_envelope(capsys)["code"] == expected, target


# --- stderr framing: a schema-bearing line, not "the last line" ------------


def test_consumer_finds_the_envelope_behind_unrelated_stderr_prose(capsys, tmp_path):
    """Unrelated diagnostics may share stderr. The consumer rule is "find the
    JSON line whose schema is the error schema", not "read the whole stream"
    and not "take the final line"."""
    print("WARNING: some unrelated library noise", file=sys.stderr)
    print("  continued on a second line", file=sys.stderr)

    assert cli_mod.main(["--error-format", "json", "info",
                         str(tmp_path / "absent.npz")]) == 1
    err = capsys.readouterr().err

    assert "unrelated library noise" in err, "the test's own noise must survive"
    with pytest.raises(json.JSONDecodeError):
        json.loads(err)                       # the whole stream is not JSON

    found = _envelopes_in(err)
    assert len(found) == 1, "the CLI must contribute exactly one envelope"
    assert found[0]["code"] == "snapshot-not-found"


def test_the_cli_contributes_exactly_one_envelope_line(capsys, tmp_path):
    assert cli_mod.main(["--error-format", "json", "info",
                         str(tmp_path / "absent.npz")]) == 1
    err = capsys.readouterr().err
    json_lines = [ln for ln in err.splitlines() if ln.strip().startswith("{")]
    assert len(json_lines) == 1


def test_the_cli_writes_no_usage_preamble_or_prose_in_json_mode(capsys):
    """The guarantee that survives the weakened framing contract: whatever
    else shares stderr, the CLI itself adds no usage block and no prose."""
    with pytest.raises(SystemExit):
        cli_mod.main(["--error-format", "json", "zzzzzzzzzz"])
    err = capsys.readouterr().err
    assert "usage:" not in err
    assert "cosmic-observatory: error:" not in err
    assert "Traceback (most recent call last)" not in err
    assert err.strip().startswith("{") and err.strip().endswith("}")


def test_last_matching_envelope_wins_when_several_are_present():
    """Selection rule, stated directly on the helper: several envelopes can
    only come from something other than one CLI invocation, and the consumer
    takes the last."""
    first = cli_errors.format_error("snapshot-not-found", "first")
    second = cli_errors.format_error("unknown-command", "second")
    stream = f"noise\n{first}not json\n{second}trailing noise\n"
    found = _envelopes_in(stream)
    assert len(found) == 2
    assert _envelope_line(stream)["code"] == "unknown-command"
