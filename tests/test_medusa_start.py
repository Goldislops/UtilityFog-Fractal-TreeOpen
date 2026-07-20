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
# Process selection during the launch migration.
#
# Two launch forms exist while the migration completes:
#   new    : python -u -m scripts.medusa_api --port 8080
#   legacy : python -u <root>\scripts\medusa_api.py --port 8080
#
# A module-form-only marker misses the legacy process entirely (status says
# DOWN, stop never kills it, and a SECOND API is started beside it). A broad
# substring like "medusa_api" has the opposite fault: it also selects
# unrelated commands that merely mention the module — notably
# `python -m pytest tests/test_medusa_api.py` — which `--stop` would kill.
#
# Detection therefore uses a BOUNDED TUPLE of actual launch signatures, and
# one PowerShell predicate of the shape:
#     python.exe AND (matches A OR matches B)
#
# `-like '*X*'` is plain substring containment for wildcard-free X, which is
# what every signature here is, so these tests model it with `in`.
#
# No test inspects, starts, stops or kills a real process, binds port 8080,
# deploys the API, queries live telemetry, or reads the live data directory:
# process detection, Popen, subprocess.run, urlopen and Path.glob are all
# replaced.
# ---------------------------------------------------------------------------


_MODULE_SIGNATURE = "-m scripts.medusa_api"
_LEGACY_SIGNATURE = "\\scripts\\medusa_api.py"


def _module_command() -> str:
    return " ".join(build_command(SERVICES["api"]))


def _legacy_command() -> str:
    """A representative pre-migration command line (Windows separators)."""
    return " ".join(
        [PYTHON, "-u", str(PROJECT_ROOT / "scripts" / "medusa_api.py"), "--port", "8080"]
    )


def _unrelated_pytest_commands() -> list[str]:
    """Commands that merely MENTION the module and must never be selected."""
    return [
        f"{PYTHON} -m pytest tests/test_medusa_api.py",
        f"{PYTHON} -m pytest tests{os.sep}test_medusa_api.py",
        f"{PYTHON} -m pytest -k medusa_api",
        f"{PYTHON} -c \"import scripts.medusa_api\"",
    ]


def _matching(command: str, marker) -> list[str]:
    from scripts.medusa_start import _signatures

    return [s for s in _signatures(marker) if s in command]


def test_api_marker_is_a_bounded_tuple_of_launch_signatures() -> None:
    marker = SERVICES["api"]["marker"]
    assert isinstance(marker, tuple)
    assert marker == (_MODULE_SIGNATURE, _LEGACY_SIGNATURE)


def test_module_command_matches_only_the_module_signature() -> None:
    assert _matching(_module_command(), SERVICES["api"]["marker"]) == [_MODULE_SIGNATURE]


def test_legacy_command_matches_only_the_legacy_signature() -> None:
    assert _matching(_legacy_command(), SERVICES["api"]["marker"]) == [_LEGACY_SIGNATURE]


def test_unrelated_pytest_command_matches_no_signature() -> None:
    """The false positive that made the broad marker dangerous: `--stop`
    would have killed an ordinary test run."""
    marker = SERVICES["api"]["marker"]
    for command in _unrelated_pytest_commands():
        assert _matching(command, marker) == [], command
        assert "medusa_api" in command  # it DOES mention the module...
        # ...but mentioning it is not a launch signature.


def test_process_filter_is_name_and_parenthesized_alternatives() -> None:
    """python.exe AND (A OR B) — the parentheses are load-bearing: without
    them `-and` binds to the first alternative only."""
    from scripts.medusa_start import build_process_filter

    predicate = build_process_filter(SERVICES["api"]["marker"])
    assert predicate.startswith("$_.Name -eq 'python.exe' -and (")
    assert predicate.endswith(")")
    assert " -or " in predicate
    assert predicate.count("$_.CommandLine -like") == 2
    assert _MODULE_SIGNATURE in predicate and _LEGACY_SIGNATURE in predicate


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
    """status() and stop_service() hand process detection the exact two-signature
    collection, so both launch forms are visible to them."""
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
    assert (_MODULE_SIGNATURE, _LEGACY_SIGNATURE) in seen

    seen.clear()
    ms.stop_service("api", ms.SERVICES["api"])
    capsys.readouterr()
    assert seen == [(_MODULE_SIGNATURE, _LEGACY_SIGNATURE)]


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
    """Only the API marker becomes a signature tuple; the others are untouched
    plain strings matching their own launch commands."""
    assert SERVICES["watchdog"]["marker"] == "watchdog.py"
    assert SERVICES["geometry"]["marker"] == "geometry_daemon.py"
    for name in ("watchdog", "geometry"):
        config = SERVICES[name]
        assert isinstance(config["marker"], str)
        assert config["marker"] in " ".join(build_command(config))
        assert "medusa_api" not in config["marker"]
