"""Phase 16c launch-path contract: the REST API must start as a package module.

Launching ``scripts/medusa_api.py`` by absolute file path leaves the repository
root off ``sys.path``, so the module's import-time ``from scripts.tuning_api
import ...`` fails with ``ModuleNotFoundError: No module named 'scripts'`` and
the API exits before serving anything. These tests pin the module form, the
process marker that matches that command line, and the unchanged watchdog /
geometry launch shape.

Nothing here binds a port, starts a server, restarts or stops any process, or
touches live data. The only subprocess is ``--help``, which parses arguments
and exits.
"""

from __future__ import annotations

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


def test_api_marker_matches_the_module_command() -> None:
    """Process detection/status must be able to find the module-form process."""
    from scripts.medusa_start import _signatures

    module_command = " ".join(build_command(SERVICES["api"]))
    assert any(s in module_command for s in _signatures(SERVICES["api"]["marker"]))


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


def test_every_service_marker_appears_in_its_own_command() -> None:
    """Status/stop rely on at least one signature matching the launch command."""
    from scripts.medusa_start import _signatures

    for name, config in SERVICES.items():
        command = " ".join(build_command(config))
        assert any(s in command for s in _signatures(config["marker"])), name


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
# Process selection: LAUNCH SHAPES built from COMPLETE elements.
#
# Detection must select the API service and nothing else. A signature that is
# only a path segment is insufficient, because a test invocation names the
# same file — and a signature whose elements can end MID-WORD is insufficient
# too, because a prefix then poses as the element:
#
#   service : python.exe -u -m scripts.medusa_api --port 8080
#   tests   : python.exe -m scripts.medusa_api_tests
#   help    : python.exe -m scripts.medusa_api --help
#   nested  : python.exe tool.py C:\UtilityFog\scripts\medusa_api.py --portability
#
# Only the first is the service: it names the complete module element AND the
# service's own argument list. The others embed the module name or ``--port``
# as a prefix of a longer word, or without the argument list. Every signature
# therefore begins at an argument boundary (a space or a path separator) and
# ends with " --port " — the complete argument plus its trailing separator.
# That is a positive test for the launch shape, NOT an exclusion of the word
# "pytest" — nothing here enumerates test runners.
#
# Quoted variants cover an install path containing spaces, where Windows
# wraps the script path in double quotes and the closing quote lands between
# the path and the arguments. Relative launches are supported ONLY through
# explicit complete forms anchored by the space before ``scripts`` — not by
# removing the leading separator from the absolute forms, which would let
# ``my_scripts\medusa_api.py --port`` match as the service.
#
# Signatures are deliberately WILDCARD-FREE, so `-like '*sig*'` is plain
# substring containment and these portable tests model it faithfully with
# `in`. Command strings are explicit synthetic literals, independent of the
# CI runner: the signatures are Windows path forms and the runner is Linux.
#
# No test inspects, starts, stops or kills a real process, binds port 8080,
# deploys the API, queries live telemetry, or reads the live data directory:
# process detection, Popen, subprocess.run, urlopen and Path.glob are all
# replaced.
# ---------------------------------------------------------------------------


_MODULE_SIGNATURE = " -m scripts.medusa_api --port "
_WIN_LEGACY_SIGNATURE = "\\scripts\\medusa_api.py --port "
_POSIX_LEGACY_SIGNATURE = "/scripts/medusa_api.py --port "
_WIN_QUOTED_SIGNATURE = "\\scripts\\medusa_api.py\" --port "
_POSIX_QUOTED_SIGNATURE = "/scripts/medusa_api.py\" --port "
_WIN_RELATIVE_SIGNATURE = " scripts\\medusa_api.py --port "
_POSIX_RELATIVE_SIGNATURE = " scripts/medusa_api.py --port "

_EXPECTED_SIGNATURES = (
    _MODULE_SIGNATURE,
    _WIN_LEGACY_SIGNATURE,
    _POSIX_LEGACY_SIGNATURE,
    _WIN_QUOTED_SIGNATURE,
    _POSIX_QUOTED_SIGNATURE,
    _WIN_RELATIVE_SIGNATURE,
    _POSIX_RELATIVE_SIGNATURE,
)

#: Real service command lines — literal, host-independent.
_WIN_LEGACY_COMMAND = "python.exe -u C:\\UtilityFog\\scripts\\medusa_api.py --port 8080"
_POSIX_LEGACY_COMMAND = "python.exe -u C:/UtilityFog/scripts/medusa_api.py --port 8080"
_WIN_QUOTED_COMMAND = (
    'python.exe -u "C:\\Program Files\\UtilityFog\\scripts\\medusa_api.py" --port 8080'
)
_POSIX_QUOTED_COMMAND = (
    'python.exe -u "C:/Program Files/UtilityFog/scripts/medusa_api.py" --port 8080'
)
_WIN_RELATIVE_COMMAND = "python.exe -u scripts\\medusa_api.py --port 8080"
_POSIX_RELATIVE_COMMAND = "python.exe -u scripts/medusa_api.py --port 8080"

#: Commands that name or mention the module but are NOT the service.
_UNRELATED_COMMANDS = (
    # Absolute-path test invocations: these contain the full path segment,
    # leading separator included, and were the surviving false positives.
    "python.exe -m pytest C:\\UtilityFog\\scripts\\medusa_api.py",
    "python.exe -m pytest C:/UtilityFog/scripts/medusa_api.py",
    'python.exe -m pytest "C:\\Program Files\\UtilityFog\\scripts\\medusa_api.py"',
    # Relative form.
    "python.exe -m pytest scripts/medusa_api.py",
    # The module's own test file, both separators.
    "python.exe -m pytest tests/test_medusa_api.py",
    "python.exe -m pytest tests\\test_medusa_api.py",
    # Mentions rather than launches.
    "python.exe -m pytest -k medusa_api",
    'python.exe -c "import scripts.medusa_api"',
    # Partial words: the module name or ``--port`` appears only as a PREFIX
    # of a longer element, or without the service's argument list.
    "python.exe -m scripts.medusa_api_tests",
    "python.exe -m scripts.medusa_api --help",
    "python.exe tool.py C:\\UtilityFog\\scripts\\medusa_api.py --portability",
    # A longer module name carrying the service's own option.
    "python.exe -m scripts.medusa_api_tests --port 9000",
    # A ``scripts`` path element that is itself the suffix of a longer word.
    "python.exe -u C:\\Backup\\my_scripts\\medusa_api.py --port 8080",
)


def _module_command() -> str:
    return " ".join(build_command(SERVICES["api"]))


def _matching(command: str, marker) -> list[str]:
    from scripts.medusa_start import _signatures

    return [s for s in _signatures(marker) if s in command]


def test_api_marker_is_a_bounded_tuple_of_launch_signatures() -> None:
    marker = SERVICES["api"]["marker"]
    assert isinstance(marker, tuple)
    assert marker == _EXPECTED_SIGNATURES


def test_signatures_are_wildcard_free() -> None:
    """`-like '*sig*'` is substring containment only while signatures carry no
    wildcards — which is what lets these portable tests model it with `in`."""
    for signature in _EXPECTED_SIGNATURES:
        assert "*" not in signature and "?" not in signature and "[" not in signature


def test_module_command_matches_only_the_module_signature() -> None:
    assert _matching(_module_command(), SERVICES["api"]["marker"]) == [_MODULE_SIGNATURE]


def test_real_legacy_launches_match_only_their_own_signature() -> None:
    """Every real orchestrator launch form is still detected: both separators,
    quoted and unquoted."""
    marker = SERVICES["api"]["marker"]
    for command, expected in (
        (_WIN_LEGACY_COMMAND, _WIN_LEGACY_SIGNATURE),
        (_POSIX_LEGACY_COMMAND, _POSIX_LEGACY_SIGNATURE),
        (_WIN_QUOTED_COMMAND, _WIN_QUOTED_SIGNATURE),
        (_POSIX_QUOTED_COMMAND, _POSIX_QUOTED_SIGNATURE),
    ):
        assert _matching(command, marker) == [expected], command


def test_quoted_install_path_with_spaces_is_detected() -> None:
    """A path containing spaces is quoted by Windows, so the closing quote
    sits between the path and the arguments."""
    marker = SERVICES["api"]["marker"]
    assert "Program Files" in _WIN_QUOTED_COMMAND
    assert _matching(_WIN_QUOTED_COMMAND, marker) == [_WIN_QUOTED_SIGNATURE]
    assert _matching(_POSIX_QUOTED_COMMAND, marker) == [_POSIX_QUOTED_SIGNATURE]


def test_explicit_relative_launches_match_only_their_own_signature() -> None:
    """Relative-launch support comes from EXPLICIT complete forms anchored at
    the argument boundary before ``scripts`` — not from removing the leading
    separator from the absolute signatures."""
    marker = SERVICES["api"]["marker"]
    for command, expected in (
        (_WIN_RELATIVE_COMMAND, _WIN_RELATIVE_SIGNATURE),
        (_POSIX_RELATIVE_COMMAND, _POSIX_RELATIVE_SIGNATURE),
    ):
        assert _matching(command, marker) == [expected], command


def test_module_name_is_a_complete_element_not_a_prefix() -> None:
    """``scripts.medusa_api_tests`` embeds the module name as a prefix; the
    boundary after the complete module element refuses it — even when the
    longer module carries the service's own option."""
    marker = SERVICES["api"]["marker"]
    for command in (
        "python.exe -m scripts.medusa_api_tests",
        "python.exe -m scripts.medusa_api_tests --port 9000",
    ):
        assert "-m scripts.medusa_api" in command  # the old signature IS inside
        assert _matching(command, marker) == [], command


def test_module_help_invocation_is_refused() -> None:
    """This suite itself runs ``-m scripts.medusa_api --help`` as a
    subprocess; ``--stop`` during a test run must not select it. The
    discriminator is the service's own argument list, and --help is not
    it."""
    command = "python.exe -m scripts.medusa_api --help"
    assert "-m scripts.medusa_api" in command  # the old signature IS inside
    assert _matching(command, SERVICES["api"]["marker"]) == [], command


def test_option_prefix_on_a_nested_unrelated_path_is_refused() -> None:
    """``--portability`` embeds ``--port`` as a prefix. The trailing boundary
    makes ``--port`` a complete argument, so a nested unrelated path handed
    to another tool is refused."""
    command = "python.exe tool.py C:\\UtilityFog\\scripts\\medusa_api.py --portability"
    assert "\\scripts\\medusa_api.py --port" in command  # the old signature IS inside
    assert _matching(command, SERVICES["api"]["marker"]) == [], command


def test_scripts_element_is_complete_not_a_word_suffix() -> None:
    """De-anchoring the absolute signatures (dropping the leading separator)
    would let a longer word ending in ``scripts`` match. The retained left
    boundary refuses it."""
    command = "python.exe -u C:\\Backup\\my_scripts\\medusa_api.py --port 8080"
    assert "scripts\\medusa_api.py --port " in command  # the de-anchored form IS inside
    assert _matching(command, SERVICES["api"]["marker"]) == [], command


def test_undetected_hand_launches_are_a_stated_residual() -> None:
    """The false-NEGATIVE side of the boundary, pinned deliberately: a hand
    launch relying on the argparse default port, or reordering ``--host``
    before ``--port``, shows no recognized shape. The bare miss is forced,
    not chosen — the bare command line is a strict prefix of the refused
    ``--help`` command line, so under substring matching any signature
    catching one catches both. The orchestrator itself always passes
    ``--port``, so no orchestrator-built launch is ever missed."""
    marker = SERVICES["api"]["marker"]
    bare = "python.exe -u -m scripts.medusa_api"
    assert (bare + " --help").startswith(bare)  # the forcing prefix relation
    for command in (
        bare,
        "python.exe -u -m scripts.medusa_api --host 0.0.0.0 --port 8080",
    ):
        assert _matching(command, marker) == [], command


def test_every_signature_is_bounded_on_both_sides() -> None:
    """Each signature begins at an argument boundary — a space or a path
    separator — and ends with the complete ``--port`` argument plus its
    trailing separator, so no element can extend into a longer word."""
    for signature in _EXPECTED_SIGNATURES:
        assert signature[0] in (" ", "\\", "/"), signature
        assert signature.endswith(" --port "), signature


def test_absolute_path_pytest_invocations_are_refused() -> None:
    """The surviving false positive: an absolute-path test run contains the
    whole path segment, leading separator included, yet is not the service."""
    marker = SERVICES["api"]["marker"]
    for command in (
        "python.exe -m pytest C:\\UtilityFog\\scripts\\medusa_api.py",
        "python.exe -m pytest C:/UtilityFog/scripts/medusa_api.py",
    ):
        assert "\\scripts\\medusa_api.py" in command or "/scripts/medusa_api.py" in command
        assert _matching(command, marker) == [], command


def test_unrelated_commands_match_no_signature() -> None:
    """`--stop` must never select a command that merely names the module."""
    marker = SERVICES["api"]["marker"]
    for command in _UNRELATED_COMMANDS:
        assert _matching(command, marker) == [], command
        assert "medusa_api" in command  # it DOES name the module...
        # ...but naming it is not a launch shape.


def test_selection_does_not_depend_on_excluding_test_runners() -> None:
    """No signature mentions pytest or any other runner: the discriminator is
    the presence of the service's own argument list."""
    for signature in _EXPECTED_SIGNATURES:
        assert "pytest" not in signature
        assert "test" not in signature
        assert signature.endswith(" --port ")


def test_process_filter_is_name_and_parenthesized_alternatives() -> None:
    """python.exe AND (A OR B OR ...) — the parentheses are load-bearing:
    without them `-and` binds to the first alternative only."""
    from scripts.medusa_start import build_process_filter

    predicate = build_process_filter(SERVICES["api"]["marker"])
    assert predicate.startswith("$_.Name -eq 'python.exe' -and (")
    assert predicate.endswith(")")
    assert predicate.count("$_.CommandLine -like") == 7
    assert predicate.count(" -or ") == 6
    assert predicate.count("(") == 1 and predicate.count(")") == 1
    for signature in _EXPECTED_SIGNATURES:
        assert signature in predicate


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
    """One process can satisfy more than one signature; it is reported once."""
    import scripts.medusa_start as ms

    class _Result:
        stdout = "ProcessId : 111\nProcessId : 111\nProcessId : 222\nProcessId : 111\n"

    monkeypatch.setattr(ms.subprocess, "run", lambda *a, **k: _Result())
    assert ms.find_process(SERVICES["api"]["marker"]) == [111, 222]


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


def test_status_and_stop_pass_the_exact_signature_collection(monkeypatch, capsys) -> None:
    """status() and stop_service() hand process detection the exact signature
    collection, so every launch form is visible to them."""
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
    assert _EXPECTED_SIGNATURES in seen

    seen.clear()
    ms.stop_service("api", ms.SERVICES["api"])
    capsys.readouterr()
    assert seen == [_EXPECTED_SIGNATURES]


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
    """Only the API marker is a signature tuple; the others are untouched
    plain strings matching their own launch commands."""
    assert SERVICES["watchdog"]["marker"] == "watchdog.py"
    assert SERVICES["geometry"]["marker"] == "geometry_daemon.py"
    for name in ("watchdog", "geometry"):
        config = SERVICES[name]
        assert isinstance(config["marker"], str)
        assert config["marker"] in " ".join(build_command(config))
        assert "medusa_api" not in config["marker"]
