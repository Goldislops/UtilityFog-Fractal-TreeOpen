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
    marker = SERVICES["api"]["marker"]
    assert marker == "medusa_api"
    assert marker in " ".join(build_command(SERVICES["api"]))


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
    """Status/stop rely on the marker matching the launched command line."""
    for name, config in SERVICES.items():
        assert config["marker"] in " ".join(build_command(config)), name


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
# Legacy-process compatibility during migration.
#
# The API's launch form changed from an absolute file path to a package
# module. A process started under the OLD form may still be running, and its
# command line contains ".../scripts/medusa_api.py" — which does NOT contain
# the module-form string "scripts.medusa_api". A module-form-only marker
# therefore makes a legacy process invisible to status, stop and
# duplicate-start detection, and a second API would be started beside it.
#
# The marker is the common substring "medusa_api", which matches both forms.
#
# Nothing here inspects, starts, stops, restarts or kills a real process,
# binds port 8080, deploys the API, or touches live telemetry: process
# detection and Popen are both replaced.
# ---------------------------------------------------------------------------


def _legacy_command() -> str:
    """A representative pre-migration command line."""
    return " ".join(
        [PYTHON, "-u", str(PROJECT_ROOT / "scripts" / "medusa_api.py"), "--port", "8080"]
    )


def test_marker_matches_the_module_launch_command() -> None:
    marker = SERVICES["api"]["marker"]
    assert marker == "medusa_api"
    assert marker in " ".join(build_command(SERVICES["api"]))


def test_marker_matches_a_representative_legacy_command() -> None:
    """The failing-first fact, pinned: the module-form-only marker does not
    appear in the legacy command line, but the common marker does."""
    legacy = _legacy_command()
    assert legacy.endswith("--port 8080")
    assert "medusa_api.py" in legacy

    assert SERVICES["api"]["marker"] in legacy      # common marker: matches
    assert "scripts.medusa_api" not in legacy       # module-form-only: misses


def test_marker_matches_both_launch_forms_simultaneously() -> None:
    marker = SERVICES["api"]["marker"]
    module_command = " ".join(build_command(SERVICES["api"]))
    assert marker in module_command and marker in _legacy_command()


def test_legacy_process_prevents_a_duplicate_start(monkeypatch, capsys) -> None:
    """A still-running legacy process must be detected, so start_service
    reports it and never launches a second API."""
    import scripts.medusa_start as ms

    def _detect(marker):
        # Only the API marker resolves, and only to a mocked legacy PID.
        return [4321] if marker == "medusa_api" else []

    def _never_popen(*args, **kwargs):
        raise AssertionError("Popen must not run while a process is already detected")

    monkeypatch.setattr(ms, "find_process", _detect)
    monkeypatch.setattr(ms.subprocess, "Popen", _never_popen)

    pid = ms.start_service("api", ms.SERVICES["api"])
    assert pid == 4321
    assert "Already running" in capsys.readouterr().out


def test_status_and_stop_pass_the_common_marker_to_detection(monkeypatch, capsys) -> None:
    """status() and stop_service() both look the API up by the same common
    marker, so a legacy process is visible to them too."""
    import urllib.request

    import scripts.medusa_start as ms

    seen: list[str] = []

    def _record(marker):
        seen.append(marker)
        return []  # nothing running: no taskkill path is ever entered

    def _no_network(*args, **kwargs):
        raise OSError("network disabled in tests")

    monkeypatch.setattr(ms, "find_process", _record)
    monkeypatch.setattr(urllib.request, "urlopen", _no_network)

    ms.status()
    capsys.readouterr()
    assert "medusa_api" in seen

    seen.clear()
    ms.stop_service("api", ms.SERVICES["api"])
    capsys.readouterr()
    assert seen == ["medusa_api"]


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
    """Only the API marker widens; the others keep their exact file names."""
    assert SERVICES["watchdog"]["marker"] == "watchdog.py"
    assert SERVICES["geometry"]["marker"] == "geometry_daemon.py"
    for name in ("watchdog", "geometry"):
        config = SERVICES[name]
        assert config["marker"] in " ".join(build_command(config))
        assert "medusa_api" not in config["marker"]
