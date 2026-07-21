"""Phase 16c launch-path contract: the REST API must start as a package module.

Launching ``scripts/medusa_api.py`` by absolute file path leaves the repository
root off ``sys.path``, so the module's import-time ``from scripts.tuning_api
import ...`` fails with ``ModuleNotFoundError: No module named 'scripts'`` and
the API exits before serving anything. These tests pin the module form, the
full-command recognizer that selects the service's process, and the unchanged
watchdog / geometry launch shape.

Nothing here binds a port, starts a server, restarts or stops any process, or
touches live data. The only subprocesses are ``--help`` (parses arguments and
exits) and — on Windows only — PowerShell pipelines over SYNTHETIC objects
that never touch the live process table.
"""

from __future__ import annotations

import base64
import inspect
import os
import subprocess
import sys

import pytest

from scripts.medusa_start import PROJECT_ROOT, PYTHON, SERVICES, build_command

_EXACTLY_ONE = "Service configuration must define exactly one of 'module' or 'script'."


def test_api_launches_as_a_package_module() -> None:
    """The API command is ``python -u -m scripts.medusa_api --port 8080``."""
    cmd = build_command(SERVICES["api"])
    assert cmd[:4] == [PYTHON, "-u", "-m", "scripts.medusa_api"]
    assert cmd[4:] == ["--port", "8080"]


def test_api_command_carries_no_file_path_form() -> None:
    """The defective file-path invocation must not reappear in any position."""
    cmd = build_command(SERVICES["api"])
    assert not any(str(arg).endswith("medusa_api.py") for arg in cmd)
    assert "script" not in SERVICES["api"]


def test_api_marker_is_the_full_command_recognizer() -> None:
    """The marker is the recognizer function itself — not a substring, not a
    collection of substrings."""
    from scripts.medusa_start import _is_api_launch_command

    assert SERVICES["api"]["marker"] is _is_api_launch_command
    assert callable(SERVICES["api"]["marker"])


def test_watchdog_and_geometry_launch_behaviour_unchanged() -> None:
    """Only the API moves to module form; the others keep the file-path form."""
    for name, script_name in (
        ("watchdog", "watchdog.py"),
        ("geometry", "geometry_daemon.py"),
    ):
        config = SERVICES[name]
        cmd = build_command(config)
        assert "module" not in config
        assert cmd[:2] == [PYTHON, "-u"]
        assert cmd[2] == str(PROJECT_ROOT / config["script"])
        assert "-m" not in cmd
        assert config["marker"] == script_name
        assert config["marker"] in cmd[2]


def test_every_service_marker_selects_its_own_command() -> None:
    """Status/stop rely on the marker selecting the service's own launch,
    rendered exactly as the OS renders it (subprocess.list2cmdline)."""
    for name, config in SERVICES.items():
        command = subprocess.list2cmdline(build_command(config))
        marker = config["marker"]
        if callable(marker):
            assert marker(command), name
        else:
            assert marker in command, name


def test_api_module_help_resolves_imports() -> None:
    """The module form actually imports cleanly.

    ``--help`` only: argparse prints usage and exits 0 without binding a port
    or constructing the server. The event bus is disabled so no publisher
    socket is created.
    """
    env = os.environ.copy()
    env["MEDUSA_EVENT_BUS_DISABLED"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.run(
        [sys.executable, "-u", "-m", "scripts.medusa_api", "--help"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ModuleNotFoundError" not in proc.stderr
    assert "No module named 'scripts'" not in proc.stderr
    assert "--port" in proc.stdout
    assert "--host" in proc.stdout


def test_api_usage_text_documents_the_module_invocation() -> None:
    """The module's own usage line must not advertise the broken form."""
    src = (PROJECT_ROOT / "scripts" / "medusa_api.py").read_text(encoding="utf-8")
    assert "python -m scripts.medusa_api" in src
    assert "python scripts/medusa_api.py" not in src


def test_build_command_rejects_a_configuration_declaring_neither() -> None:
    """A config with no launch form must not surface as a bare KeyError."""
    with pytest.raises(ValueError) as excinfo:
        build_command({"marker": "x", "description": "d"})
    assert type(excinfo.value) is ValueError
    assert str(excinfo.value) == _EXACTLY_ONE


def test_build_command_rejects_a_configuration_declaring_both() -> None:
    """Declaring both would silently pick a form the author did not choose."""
    with pytest.raises(ValueError) as excinfo:
        build_command(
            {"module": "scripts.x", "script": "scripts/x.py", "marker": "x"}
        )
    assert type(excinfo.value) is ValueError
    assert str(excinfo.value) == _EXACTLY_ONE


def test_launch_form_refusal_reports_no_supplied_value() -> None:
    """The message is generic: it names neither the module nor the script."""
    for config in (
        {},
        {"module": "scripts.secret", "script": "scripts/secret.py"},
    ):
        with pytest.raises(ValueError) as excinfo:
            build_command(config)
        message = str(excinfo.value)
        assert message == _EXACTLY_ONE
        assert "secret" not in message


def test_every_real_service_declares_exactly_one_launch_form() -> None:
    """The shipped registry satisfies the invariant the guard enforces."""
    for name, config in SERVICES.items():
        assert ("module" in config) != ("script" in config), name
        build_command(config)  # constructs without raising


# ---------------------------------------------------------------------------
# Process selection: COMPLETE ACCEPTED COMMAND FORMS, not substrings.
#
# A substring signature recognizes a fragment, and a fragment can stop
# mid-word ("--port" inside "--portability"), start mid-word ("scripts"
# inside "my_scripts"), or ignore what follows ("--help", trailing
# arguments, a nested path handed to another tool). The recognizer accepts
# a complete command instead:
#
#   <interpreter> [-u] -m scripts.medusa_api            <accepted arguments>
#   <interpreter> [-u] <path to scripts\medusa_api.py>  <accepted arguments>
#
# where the accepted arguments are the service's own option grammar —
# "--port <1..65535>" and "--host <value>", each at most once, either
# order, both optional — consumed to the END of the command. The end
# boundary is what a substring can never assert: it recognizes the bare
# launch (the port defaults) while refusing "--help", two commands one of
# which is a strict prefix of the other. And because the launch target
# must sit in launch position, a command that merely NAMES the file or
# module — a nested path, a quoted mention, a runner invocation — is
# refused structurally, even when the service's own options follow. That
# closes the substring design's stated residual.
#
# The portable model is the recognizer itself: pure Python over fixed
# command strings, identical on every host. The emitted host-shell side is
# validated twice — its exact emission is pinned without execution, and,
# on Windows only, the production pipeline fragment runs through REAL
# PowerShell over SYNTHETIC objects (never the live process table); those
# tests skip on the Linux CI runner and run on the Windows seat.
#
# No test inspects, starts, stops or kills a real process, binds port
# 8080, deploys the API, queries live telemetry, or reads the live data
# directory: process detection, Popen, subprocess.run, urlopen and
# Path.glob are replaced or handed synthetic input everywhere else.
# ---------------------------------------------------------------------------


#: Accepted launch commands — fixed literals, host-independent.
_ACCEPTED_COMMANDS = (
    # Module form: the orchestrator's own shape, then bare and single-option
    # hand launches, both option orders, with and without -u.
    "python.exe -u -m scripts.medusa_api --port 8080",
    "python.exe -m scripts.medusa_api",
    "python.exe -u -m scripts.medusa_api",
    "python.exe -m scripts.medusa_api --port 8080",
    "python.exe -m scripts.medusa_api --host 0.0.0.0",
    "python.exe -m scripts.medusa_api --port 8080 --host 0.0.0.0",
    "python.exe -m scripts.medusa_api --host 192.168.86.29 --port 8080",
    # Legacy absolute paths, both separator styles, unquoted.
    "python.exe -u C:\\UtilityFog\\scripts\\medusa_api.py --port 8080",
    "python.exe -u C:/UtilityFog/scripts/medusa_api.py --port 8080",
    # Quoted install path containing spaces, both separator styles.
    'python.exe -u "C:\\Program Files\\UtilityFog\\scripts\\medusa_api.py" --port 8080',
    'python.exe -u "C:/Program Files/UtilityFog/scripts/medusa_api.py" --port 8080',
    # Relative launches, both separator styles.
    "python.exe -u scripts\\medusa_api.py --port 8080",
    "python.exe -u scripts/medusa_api.py --port 8080",
    # Legacy bare and host-carrying forms.
    "python.exe C:\\UtilityFog\\scripts\\medusa_api.py",
    "python.exe scripts/medusa_api.py --host localhost",
    'python.exe "C:\\Program Files\\UtilityFog\\scripts\\medusa_api.py" --host 0.0.0.0 --port 8080',
    # A quoted interpreter path containing spaces.
    '"C:\\Program Files\\Python\\python.exe" -u -m scripts.medusa_api --port 8080',
)

#: Refused commands — fixed literals. Most name the module or the file;
#: none is an accepted launch form.
_REFUSED_COMMANDS = (
    # Module names with suffixes — with and without the service's options.
    "python.exe -m scripts.medusa_api_tests",
    "python.exe -m scripts.medusa_api_tests --port 9000",
    "python.exe -m scripts.medusa_api2 --port 8080",
    # --help and other unknown, invalid or incomplete options.
    "python.exe -m scripts.medusa_api --help",
    "python.exe -u -m scripts.medusa_api --help",
    "python.exe -m scripts.medusa_api --port",
    "python.exe -m scripts.medusa_api --port 8o8o",
    "python.exe -m scripts.medusa_api --port 0",
    "python.exe -m scripts.medusa_api --port 65536",
    "python.exe -m scripts.medusa_api --port=8080",
    "python.exe -m scripts.medusa_api --port 8080 --port 9090",
    "python.exe -m scripts.medusa_api --host",
    "python.exe -m scripts.medusa_api --host --port 8080",
    "python.exe -m scripts.medusa_api --portability",
    "python.exe -u C:\\UtilityFog\\scripts\\medusa_api.py --portability",
    # Extra trailing arguments beyond the accepted grammar.
    "python.exe -m scripts.medusa_api --port 8080 extra",
    "python.exe -m scripts.medusa_api --port 8080 --help",
    "python.exe -u scripts/medusa_api.py --port 8080 --reload",
    # Nested unrelated paths: the file is an ARGUMENT, not the launch
    # target — refused even when the service's own options follow.
    "python.exe tool.py C:\\UtilityFog\\scripts\\medusa_api.py --portability",
    "python.exe tool.py C:\\UtilityFog\\scripts\\medusa_api.py --port 8080",
    "python.exe -m pytest C:\\UtilityFog\\scripts\\medusa_api.py",
    "python.exe -m pytest C:/UtilityFog/scripts/medusa_api.py",
    'python.exe -m pytest "C:\\Program Files\\UtilityFog\\scripts\\medusa_api.py"',
    "python.exe -m pytest scripts/medusa_api.py",
    "python.exe -m pytest scripts/medusa_api.py --port 8080",
    "python.exe -m pytest tests/test_medusa_api.py",
    "python.exe -m pytest tests\\test_medusa_api.py",
    "python.exe -m pytest -k medusa_api",
    # Textual mentions inside another command.
    'python.exe -c "import scripts.medusa_api"',
    'python.exe analyze.py --grep " -m scripts.medusa_api --port "',
    # Longer words around the path elements.
    "python.exe -u C:\\Backup\\my_scripts\\medusa_api.py --port 8080",
    "python.exe -u C:\\UtilityFog\\scripts\\medusa_api_extra.py --port 8080",
    "python.exe -u C:\\UtilityFog\\scripts\\premedusa_api.py --port 8080",
    "python.exe -u C:\\UtilityFog\\scripts\\medusa_api.pyc --port 8080",
    # No launch target at all.
    "python.exe",
    "python.exe -u",
    "python.exe --port 8080",
    "",
    # Empty quoted groups are REAL empty arguments to the process — an
    # extra trailing argument the grammar refuses, and an empty launch
    # target when they sit in launch position.
    'python.exe -m scripts.medusa_api ""',
    'python.exe -m scripts.medusa_api "',
    'python.exe -m scripts.medusa_api --host ok "',
    'python.exe "" -m scripts.medusa_api --port 8080',
)


def test_accepted_commands_are_recognized() -> None:
    """Every accepted launch form — module and legacy script, bare, each
    option, both orders, quoted and unquoted, both separator styles."""
    recognize = SERVICES["api"]["marker"]
    for command in _ACCEPTED_COMMANDS:
        assert recognize(command), command


def test_refused_commands_are_refused() -> None:
    """Suffixed modules, --help, invalid/incomplete/unknown options, extra
    trailing arguments, nested unrelated paths, textual mentions."""
    recognize = SERVICES["api"]["marker"]
    for command in _REFUSED_COMMANDS:
        assert not recognize(command), command


def test_build_command_output_is_recognized_as_rendered() -> None:
    """The exact command build_command() produces — as the OS renders it,
    including a quoted interpreter path when it contains spaces."""
    recognize = SERVICES["api"]["marker"]
    assert recognize(subprocess.list2cmdline(build_command(SERVICES["api"])))
    spaced = subprocess.list2cmdline(
        ["C:\\Program Files\\Python\\python.exe", "-u", "-m",
         "scripts.medusa_api", "--port", "8080"]
    )
    assert recognize(spaced)


def test_end_of_command_boundary_separates_bare_launch_from_help() -> None:
    """The substring design could not hold both of these at once: the bare
    launch is a strict PREFIX of the --help invocation, so any fragment
    matching one matched both. Recognizing the complete command with an
    end boundary holds both."""
    recognize = SERVICES["api"]["marker"]
    bare = "python.exe -u -m scripts.medusa_api"
    assert recognize(bare)
    assert recognize(bare + " --port 8080")
    assert not recognize(bare + " --help")
    assert not recognize(bare + " --port 8080 --help")
    assert not recognize(bare + " --port 8080 extra")


def test_option_order_no_longer_matters() -> None:
    """--host before --port was a stated false negative of the substring
    design; the parsed grammar accepts either order."""
    recognize = SERVICES["api"]["marker"]
    assert recognize("python.exe -u -m scripts.medusa_api --host 192.168.86.29 --port 8080")
    assert recognize("python.exe -u -m scripts.medusa_api --port 8080 --host 192.168.86.29")


def test_nested_path_is_refused_even_with_service_options() -> None:
    """The substring design's stated residual, now closed: a command whose
    launch position holds another tool is refused even when the medusa
    path AND valid service options follow as arguments."""
    recognize = SERVICES["api"]["marker"]
    nested = "python.exe tool.py C:\\UtilityFog\\scripts\\medusa_api.py --port 8080"
    launch = "python.exe -u C:\\UtilityFog\\scripts\\medusa_api.py --port 8080"
    assert not recognize(nested)
    assert recognize(launch)


def test_partial_word_forms_remain_refused() -> None:
    """The three exhibits that defeated prefix substrings stay refused."""
    recognize = SERVICES["api"]["marker"]
    for command in (
        "python.exe -m scripts.medusa_api_tests",
        "python.exe -m scripts.medusa_api --help",
        "python.exe tool.py C:\\UtilityFog\\scripts\\medusa_api.py --portability",
    ):
        assert not recognize(command), command


def test_windows_path_case_is_insensitive_and_options_are_exact() -> None:
    """Path and module elements compare case-insensitively (Windows
    filesystem semantics, matching the old query's behavior); option names
    stay exact, as argparse itself is case-sensitive."""
    recognize = SERVICES["api"]["marker"]
    assert recognize("PYTHON.EXE -u C:\\UTILITYFOG\\SCRIPTS\\MEDUSA_API.PY --port 8080")
    assert recognize("python.exe -m SCRIPTS.MEDUSA_API --port 8080")
    assert not recognize("python.exe -m scripts.medusa_api --PORT 8080")


def test_element_splitting_honors_double_quotes() -> None:
    """Quotes group; they bound elements and are not characters of them."""
    from scripts.medusa_start import _split_command_elements

    assert _split_command_elements(
        'python.exe -u "C:\\Program Files\\UtilityFog\\scripts\\medusa_api.py" --port 8080'
    ) == [
        "python.exe", "-u",
        "C:\\Program Files\\UtilityFog\\scripts\\medusa_api.py",
        "--port", "8080",
    ]
    assert _split_command_elements("  python.exe   -m   scripts.medusa_api  ") == [
        "python.exe", "-m", "scripts.medusa_api",
    ]
    assert _split_command_elements('a "b c" d') == ["a", "b c", "d"]
    assert _split_command_elements("") == []
    # An empty quoted group is a REAL empty argument and must survive
    # splitting, so the grammar can refuse it as a trailing element.
    assert _split_command_elements('a "" b') == ["a", "", "b"]
    assert _split_command_elements('a ""') == ["a", ""]
    assert _split_command_elements('a "') == ["a", ""]


def test_port_values_must_name_a_real_port() -> None:
    from scripts.medusa_start import _is_valid_port_value

    for value in ("1", "80", "8080", "65535"):
        assert _is_valid_port_value(value), value
    for value in ("", "0", "65536", "8o8o", "-1", "8080 ", "８０８０"):
        assert not _is_valid_port_value(value), value


def test_recognition_is_a_positive_grammar_not_a_runner_blacklist() -> None:
    """No runner is enumerated anywhere in the recognizer: refusal falls out
    of the accepted grammar, so an unknown future runner is refused for the
    same reason pytest is."""
    import scripts.medusa_start as ms

    source = (
        inspect.getsource(ms._is_api_launch_command)
        + inspect.getsource(ms._is_accepted_argument_list)
        + inspect.getsource(ms._split_command_elements)
        + inspect.getsource(ms._is_valid_port_value)
    )
    assert "pytest" not in source
    assert "unittest" not in source


def test_string_marker_predicate_is_unchanged() -> None:
    """Engine, watchdog and geometry keep the exact substring predicate."""
    from scripts.medusa_start import build_process_filter

    assert (
        build_process_filter("watchdog.py")
        == "$_.Name -eq 'python.exe' -and ($_.CommandLine -like '*watchdog.py*')"
    )
    assert (
        build_process_filter("run_v070_engine")
        == "$_.Name -eq 'python.exe' -and ($_.CommandLine -like '*run_v070_engine*')"
    )


def test_api_query_is_name_only_and_launch_form_free() -> None:
    """The recognizer path's shell query filters by process NAME and selects
    PID + CommandLine as JSON — it encodes nothing about any launch form."""
    from scripts.medusa_start import _PYTHON_PROCESS_QUERY

    assert _PYTHON_PROCESS_QUERY == (
        "Where-Object {$_.Name -eq 'python.exe'} | "
        "Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress"
    )
    assert "medusa" not in _PYTHON_PROCESS_QUERY
    assert "-like" not in _PYTHON_PROCESS_QUERY


def test_find_process_emits_the_name_only_query_for_the_api(monkeypatch) -> None:
    """Emission pin, no execution: the API path sends exactly the
    enumeration query; nothing about the service leaks into the shell."""
    import scripts.medusa_start as ms

    captured: list = []

    class _Result:
        stdout = ""

    def _capture(args, **kwargs):
        captured.append(args)
        return _Result()

    monkeypatch.setattr(ms.subprocess, "run", _capture)
    assert ms.find_process(ms.SERVICES["api"]["marker"]) == []
    assert captured == [[
        "powershell", "-NoProfile", "-NonInteractive", "-Command",
        "Get-CimInstance Win32_Process | " + ms._PYTHON_PROCESS_QUERY,
    ]]


def test_find_process_emits_the_unchanged_query_for_string_markers(monkeypatch) -> None:
    """Emission pin, no execution: plain-string markers keep the original
    substring query byte for byte."""
    import scripts.medusa_start as ms

    captured: list = []

    class _Result:
        stdout = ""

    def _capture(args, **kwargs):
        captured.append(args)
        return _Result()

    monkeypatch.setattr(ms.subprocess, "run", _capture)
    assert ms.find_process("watchdog.py") == []
    assert captured == [[
        "powershell", "-Command",
        "Get-CimInstance Win32_Process | Where-Object {$_.Name -eq 'python.exe'"
        " -and ($_.CommandLine -like '*watchdog.py*')} | Select-Object ProcessId"
        " | Format-List",
    ]]


def test_parse_process_rows_handles_every_query_shape() -> None:
    """Fixed strings for the three JSON shapes the query can emit."""
    from scripts.medusa_start import _parse_process_rows

    assert _parse_process_rows("") == []
    assert _parse_process_rows("   \n") == []
    single = '{"ProcessId":7,"CommandLine":"python.exe -m scripts.medusa_api"}'
    assert _parse_process_rows(single) == [
        {"ProcessId": 7, "CommandLine": "python.exe -m scripts.medusa_api"}
    ]
    many = (
        '[{"ProcessId":1,"CommandLine":null},'
        '{"ProcessId":2,"CommandLine":"python.exe -m scripts.medusa_api"}]'
    )
    assert _parse_process_rows(many) == [
        {"ProcessId": 1, "CommandLine": None},
        {"ProcessId": 2, "CommandLine": "python.exe -m scripts.medusa_api"},
    ]


def test_select_recognized_pids_orders_dedupes_and_refuses_null() -> None:
    """Ordered de-duplicated PIDs; null command lines and missing PIDs are
    never selected."""
    from scripts.medusa_start import _select_recognized_pids

    marker = SERVICES["api"]["marker"]
    rows = [
        {"ProcessId": 11, "CommandLine": "python.exe -u -m scripts.medusa_api --port 8080"},
        {"ProcessId": 22, "CommandLine": "python.exe -u -m scripts.medusa_api --help"},
        {"ProcessId": 11, "CommandLine": "python.exe -u -m scripts.medusa_api --port 8080"},
        {"ProcessId": None, "CommandLine": "python.exe -u -m scripts.medusa_api --port 8080"},
        {"ProcessId": 44, "CommandLine": None},
        {"ProcessId": 55, "CommandLine": "python.exe -u scripts\\medusa_api.py --host 0.0.0.0"},
    ]
    assert _select_recognized_pids(rows, marker) == [11, 55]


def test_noisy_query_output_reads_as_nothing_running(monkeypatch) -> None:
    """The JSON parser is all-or-nothing by design: non-JSON noise in the
    query output yields NO pids (fail-safe — never a wrong PID, never a
    wrong kill). The -NoProfile -NonInteractive invocation keeps the real
    stream pure JSON."""
    import scripts.medusa_start as ms

    class _Result:
        stdout = (
            'Loading personal profile...\n'
            '[{"ProcessId":11,"CommandLine":"python.exe -u -m scripts.medusa_api --port 8080"}]'
        )

    monkeypatch.setattr(ms.subprocess, "run", lambda *a, **k: _Result())
    assert ms.find_process(ms.SERVICES["api"]["marker"]) == []


@pytest.mark.skipif(sys.platform != "win32", reason="validates the host shell itself")
def test_host_shell_pipeline_matches_the_portable_model() -> None:
    """The production query fragment, run through REAL PowerShell over
    SYNTHETIC objects: the shell keeps every python.exe row whatever its
    command shape (recognition is Python's job) and drops other process
    names; the JSON round-trips through the production parser; the
    recognizer then selects exactly the accepted commands. No live process
    is touched — Get-CimInstance never runs here."""
    import scripts.medusa_start as ms

    script = (
        "@("
        "[pscustomobject]@{Name='python.exe'; ProcessId=11; CommandLine="
        "'python.exe -u -m scripts.medusa_api --port 8080'},"
        "[pscustomobject]@{Name='python.exe'; ProcessId=22; CommandLine="
        "'python.exe -u -m scripts.medusa_api --help'},"
        "[pscustomobject]@{Name='node.exe'; ProcessId=33; CommandLine="
        "'python.exe -u -m scripts.medusa_api --port 8080'},"
        "[pscustomobject]@{Name='python.exe'; ProcessId=11; CommandLine="
        "'python.exe -u -m scripts.medusa_api --port 8080'},"
        "[pscustomobject]@{Name='python.exe'; ProcessId=44; CommandLine="
        "'python.exe -u \"C:\\Program Files\\UtilityFog\\scripts\\medusa_api.py\" --port 8080'}"
        ") | " + ms._PYTHON_PROCESS_QUERY
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-EncodedCommand", encoded],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    rows = ms._parse_process_rows(result.stdout)
    assert [row["ProcessId"] for row in rows] == [11, 22, 11, 44]
    assert ms._select_recognized_pids(rows, ms.SERVICES["api"]["marker"]) == [11, 44]


@pytest.mark.skipif(sys.platform != "win32", reason="validates the host shell itself")
def test_host_shell_single_row_json_shape_is_handled() -> None:
    """One pipeline row makes PowerShell emit a bare object, not an array —
    the shape _parse_process_rows normalizes. Synthetic objects only."""
    import scripts.medusa_start as ms

    script = (
        "@([pscustomobject]@{Name='python.exe'; ProcessId=7; CommandLine="
        "'python.exe -m scripts.medusa_api'}) | " + ms._PYTHON_PROCESS_QUERY
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-EncodedCommand", encoded],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    rows = ms._parse_process_rows(result.stdout)
    assert isinstance(rows, list) and len(rows) == 1
    assert ms._select_recognized_pids(rows, ms.SERVICES["api"]["marker"]) == [7]


def test_single_string_marker_behaviour_is_unchanged(monkeypatch) -> None:
    """Engine, watchdog and geometry keep their plain-string markers and the
    original one-alternative predicate."""
    import scripts.medusa_start as ms

    assert (
        ms.build_process_filter("watchdog.py")
        == "$_.Name -eq 'python.exe' -and ($_.CommandLine -like '*watchdog.py*')"
    )
    assert (
        ms.build_process_filter("run_v070_engine")
        == "$_.Name -eq 'python.exe' -and ($_.CommandLine -like '*run_v070_engine*')"
    )

    class _Result:
        stdout = "ProcessId : 77\n"

    monkeypatch.setattr(ms.subprocess, "run", lambda *a, **k: _Result())
    assert ms.find_process("watchdog.py") == [77]


def test_find_process_returns_no_duplicate_pids(monkeypatch) -> None:
    """One PID can appear more than once in the query rows; it is reported
    once, in first-seen order."""
    import scripts.medusa_start as ms

    class _Result:
        stdout = (
            '[{"ProcessId":111,"CommandLine":"python.exe -u -m scripts.medusa_api --port 8080"},'
            '{"ProcessId":111,"CommandLine":"python.exe -u -m scripts.medusa_api --port 8080"},'
            '{"ProcessId":222,"CommandLine":"python.exe -u scripts/medusa_api.py --port 8080"},'
            '{"ProcessId":111,"CommandLine":"python.exe -u -m scripts.medusa_api --port 8080"}]'
        )

    monkeypatch.setattr(ms.subprocess, "run", lambda *a, **k: _Result())
    assert ms.find_process(ms.SERVICES["api"]["marker"]) == [111, 222]


def test_legacy_process_prevents_a_duplicate_start(monkeypatch, capsys) -> None:
    """A still-running legacy process must be detected, so start_service
    reports it and never launches a second API."""
    import scripts.medusa_start as ms

    def _detect(marker):
        return [4321] if marker == SERVICES["api"]["marker"] else []

    def _never_popen(*args, **kwargs):
        raise AssertionError("Popen must not run while a process is already detected")

    monkeypatch.setattr(ms, "find_process", _detect)
    monkeypatch.setattr(ms.subprocess, "Popen", _never_popen)

    pid = ms.start_service("api", ms.SERVICES["api"])
    assert pid == 4321
    assert "Already running" in capsys.readouterr().out


def test_status_and_stop_pass_the_recognizer_itself(monkeypatch, capsys) -> None:
    """status() and stop_service() hand process detection the exact marker —
    the recognizer function — so every accepted launch form is visible to
    them."""
    import urllib.request
    from pathlib import Path

    import scripts.medusa_start as ms

    seen: list = []

    def _record(marker):
        seen.append(marker)
        return []  # nothing running: no taskkill path is ever entered

    def _no_network(*args, **kwargs):
        raise OSError("network disabled in tests")

    monkeypatch.setattr(ms, "find_process", _record)
    monkeypatch.setattr(urllib.request, "urlopen", _no_network)
    # Test isolation: never read the real snapshot directory.
    monkeypatch.setattr(Path, "glob", lambda self, pattern: [])

    ms.status()
    capsys.readouterr()
    assert any(marker is ms._is_api_launch_command for marker in seen)

    seen.clear()
    ms.stop_service("api", ms.SERVICES["api"])
    capsys.readouterr()
    assert len(seen) == 1 and seen[0] is ms._is_api_launch_command


def test_stop_service_does_not_kill_when_nothing_is_detected(monkeypatch, capsys) -> None:
    """Guard the guard: with no detected PID, no kill command is issued."""
    import scripts.medusa_start as ms

    def _never_run(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called with no detected PID")

    monkeypatch.setattr(ms, "find_process", lambda marker: [])
    monkeypatch.setattr(ms.subprocess, "run", _never_run)

    ms.stop_service("api", ms.SERVICES["api"])
    assert "Not running" in capsys.readouterr().out


def test_watchdog_and_geometry_markers_are_unchanged() -> None:
    """Only the API marker is a recognizer; the others are untouched plain
    strings matching their own launch commands."""
    assert SERVICES["watchdog"]["marker"] == "watchdog.py"
    assert SERVICES["geometry"]["marker"] == "geometry_daemon.py"
    for name in ("watchdog", "geometry"):
        config = SERVICES[name]
        assert isinstance(config["marker"], str)
        assert config["marker"] in " ".join(build_command(config))
        assert "medusa_api" not in config["marker"]
