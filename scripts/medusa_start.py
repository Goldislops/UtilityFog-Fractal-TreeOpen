#!/usr/bin/env python3
"""Phase 16c: Medusa Master Orchestrator — One Script to Rule Them All

Silently spins up the complete Medusa stack:
  1. Watchdog Daemon (monitors engine, auto-restart on crash)
  2. REST API (exposes telemetry to network + NemoClaw)
  3. Geometry Export Daemon (auto-exports STL/CSV/JSON)

The Watchdog handles the engine lifecycle, so we don't start the engine
directly — the Watchdog will detect it's missing and launch it.

Usage:
  python scripts/medusa_start.py              # Start all services
  python scripts/medusa_start.py --status     # Check what's running
  python scripts/medusa_start.py --stop       # Stop all services
"""

from __future__ import annotations

import os
import sys
import json
import time
import subprocess
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
CREATE_NO_WINDOW = 0x08000000

# ---------------------------------------------------------------------------
# API launch recognition: COMPLETE ACCEPTED COMMAND FORMS.
#
# Detection must select the SERVICE, and only the service. Earlier revisions
# matched substring signatures, and a substring recognizes a FRAGMENT: it can
# stop mid-word ("--port" inside "--portability"), start mid-word ("scripts"
# inside "my_scripts"), or ignore what follows ("--help", trailing arguments,
# a nested path handed to another tool). The recognizer below accepts a
# complete command form instead, end to end:
#
#   <interpreter> [-u] -m scripts.medusa_api            <accepted arguments>
#   <interpreter> [-u] <path to scripts\medusa_api.py>  <accepted arguments>
#
# <accepted arguments> is the service's own option grammar — "--port" with a
# value naming a real port (1..65535) and "--host" with a value, each at most
# once, in either order, both optional — and nothing may follow: the grammar
# must consume the command to its END. The end boundary is what a substring
# can never assert, and it is what distinguishes the bare launch (recognized;
# the port defaults) from "--help" (refused: not the service's grammar).
#
# The launch target must sit in LAUNCH POSITION, immediately after the
# interpreter and its optional -u. A command that merely NAMES the file or
# module elsewhere — a nested path argument to another tool, a quoted textual
# mention, a runner invocation — is refused structurally, whatever options it
# carries. That closes the substring design's stated residual:
# "tool.py C:\...\scripts\medusa_api.py --port 8080" is refused because
# "tool.py" occupies the launch position.
#
# The path form accepts absolute and relative paths, both separator styles,
# quoted or unquoted (Windows quotes a path containing spaces; element
# splitting honors double quotes as grouping characters, and an empty
# quoted group still yields an element — a real, empty argument the
# grammar then refuses). Path and module elements compare
# case-insensitively — Windows filesystem semantics, matching the old query's
# behavior — but must be COMPLETE: the final path elements must be exactly
# "scripts\medusa_api.py" and the module exactly "scripts.medusa_api", so a
# longer word ("my_scripts", "medusa_api_tests", "medusa_api.pyc") never
# matches. Option names stay exact: argparse itself is case-sensitive.
#
# Stated boundaries of the accepted grammar, honestly: only the separate
# value form is a launch shape ("--port 8080" — the only form any launcher
# here has ever produced); joined forms ("--port=8080", the fused
# "-mscripts.medusa_api") and interpreter options other than -u are not
# accepted commands. Quote handling is a deliberate simplification of the
# full CommandLineToArgvW rules — backslash-escaped quotes are not
# modeled, so an adversarially quote-crafted command line can parse
# differently here than in the OS; every launcher and shell in this
# system produces conventionally quoted commands. And recognition is by
# command SHAPE: an identically shaped launch of another checkout's copy
# of the script is indistinguishable — as in every prior design, the
# shape is the contract.
# ---------------------------------------------------------------------------

_API_MODULE = "scripts.medusa_api"
_API_SCRIPT = "scripts\\medusa_api.py"


def _split_command_elements(command: str) -> list:
    """Split a command line into its elements.

    Whitespace separates elements; double quotes group — they bound an
    element (or part of one) and are not characters of it. A quoted group
    with nothing in it still yields an element: ``""`` (and a dangling
    ``"``) is a real, empty argument to the process, so it must survive
    splitting for the grammar to refuse it as a trailing element.
    """
    elements, current, quoted, grouped = [], [], False, False
    for character in command:
        if character == '"':
            quoted = not quoted
            grouped = True
        elif character in " \t" and not quoted:
            if current or grouped:
                elements.append("".join(current))
                current = []
            grouped = False
        else:
            current.append(character)
    if current or grouped:
        elements.append("".join(current))
    return elements


def _is_valid_port_value(value: str) -> bool:
    """A port value is decimal digits naming a real port: 1..65535."""
    return value.isascii() and value.isdigit() and 0 < int(value) <= 65535


def _is_accepted_argument_list(arguments: list) -> bool:
    """Accept exactly the service's own option grammar, through to the end.

    ``--port <valid value>`` and ``--host <value>``, each at most once, in
    either order, both optional. Anything else — an unknown option, a
    missing or invalid value, a duplicate, a trailing element — refuses the
    whole command. Consuming every element IS the end-of-command boundary.
    """
    seen = set()
    index = 0
    while index < len(arguments):
        option = arguments[index]
        if option not in ("--port", "--host") or option in seen:
            return False
        if index + 1 >= len(arguments):
            return False  # the option's value is missing
        value = arguments[index + 1]
        if option == "--port":
            if not _is_valid_port_value(value):
                return False
        elif not value or value.startswith("-"):
            return False
        seen.add(option)
        index += 2
    return True


def _is_api_launch_command(command: str) -> bool:
    """True only for a complete accepted API launch command.

    The launch target — the module element or the script path — must sit in
    launch position, immediately after the interpreter and its optional
    ``-u``, and everything after it must satisfy the accepted argument
    grammar to the end of the command.
    """
    elements = _split_command_elements(command)
    rest = elements[1:]  # elements[0] is the interpreter, whatever its path
    if rest and rest[0] == "-u":
        rest = rest[1:]
    if not rest:
        return False
    if rest[0] == "-m":
        return (
            len(rest) >= 2
            and rest[1].lower() == _API_MODULE
            and _is_accepted_argument_list(rest[2:])
        )
    target = rest[0].replace("/", "\\").lower()
    if target == _API_SCRIPT or target.endswith("\\" + _API_SCRIPT):
        return _is_accepted_argument_list(rest[1:])
    return False


# Service definitions
SERVICES = {
    "watchdog": {
        "script": "scripts/watchdog.py",
        "marker": "watchdog.py",
        "description": "Watchdog Daemon (Phase 14d)",
    },
    # The API must be launched as a PACKAGE MODULE. Running it by absolute
    # file path leaves the repository root off sys.path, so its
    # ``from scripts.tuning_api import ...`` fails with ModuleNotFoundError
    # and the service exits immediately.
    #
    # The marker is the RECOGNIZER of complete accepted launch commands
    # defined above — not a substring collection. Selection requires the
    # WHOLE command to be an accepted launch form: module or legacy script,
    # bare or carrying the service's own options in either order, quoted or
    # unquoted path, either separator style, and nothing trailing.
    "api": {
        "module": "scripts.medusa_api",
        "args": ["--port", "8080"],
        "marker": _is_api_launch_command,
        "description": "REST API (Phase 16a)",
    },
    "geometry": {
        "script": "scripts/geometry_daemon.py",
        "marker": "geometry_daemon.py",
        "description": "Geometry Export Daemon (Phase 16b)",
    },
}


def build_process_filter(marker: str) -> str:
    """PowerShell ``Where-Object`` predicate for a plain-string marker.

    ``python.exe AND (CommandLine contains marker)`` — the engine, watchdog
    and geometry selectors keep this exact substring form, unchanged.
    """
    return f"$_.Name -eq 'python.exe' -and ($_.CommandLine -like '*{marker}*')"


#: Host-shell query for the recognizer path: enumerate every python.exe
#: process with its PID and full command line, as JSON. Recognition happens
#: in Python — the shell filters by PROCESS NAME only, so the emitted query
#: carries no knowledge of any launch form.
_PYTHON_PROCESS_QUERY = (
    "Where-Object {$_.Name -eq 'python.exe'} | "
    "Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress"
)


def _parse_process_rows(stdout: str) -> list:
    """Rows from the JSON query: nothing, one bare object, or an array.

    PowerShell emits a bare object (not a one-element array) when the
    pipeline yields a single row, and nothing at all when it yields none.
    """
    text = stdout.strip()
    if not text:
        return []
    rows = json.loads(text)
    return [rows] if isinstance(rows, dict) else rows


def _select_recognized_pids(rows, recognizer) -> list:
    """Ordered, de-duplicated PIDs of rows whose command is recognized.

    A row without a PID is skipped; a row without a command line
    (``CommandLine`` can be null) is refused. Order follows the query; a
    PID appearing more than once is reported once.
    """
    pids = []
    for row in rows:
        pid = row.get("ProcessId")
        if pid is None:
            continue
        pid = int(pid)
        if recognizer(row.get("CommandLine") or "") and pid not in pids:
            pids.append(pid)
    return pids


def find_process(marker) -> list:
    """Find running python.exe processes selected by ``marker``.

    A plain-string marker keeps the original substring query, emitted and
    parsed exactly as before (engine, watchdog, geometry). A callable
    marker is a full-command recognizer: the shell enumerates python.exe
    processes and Python classifies each command line, so the shell query
    itself never encodes a launch form.
    """
    try:
        if callable(marker):
            # -NoProfile -NonInteractive keep stdout pure JSON: the strict
            # parser is all-or-nothing, so a profile banner would otherwise
            # read as "nothing running" (fail-safe, but a double-start risk).
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Get-CimInstance Win32_Process | " + _PYTHON_PROCESS_QUERY],
                capture_output=True, text=True, timeout=10,
            )
            return _select_recognized_pids(_parse_process_rows(result.stdout), marker)
        result = subprocess.run(
            ["powershell", "-Command",
             f"Get-CimInstance Win32_Process | Where-Object {{{build_process_filter(marker)}}} | Select-Object ProcessId | Format-List"],
            capture_output=True, text=True, timeout=10,
        )
        pids = []
        for line in result.stdout.strip().split("\n"):
            if line.strip().startswith("ProcessId"):
                pid = int(line.split(":")[-1].strip())
                if pid not in pids:
                    pids.append(pid)
        return pids
    except Exception:
        return []


def build_command(config: dict) -> list:
    """Build the launch argv for one service.

    A service declaring ``module`` is launched as a package module
    (``python -u -m pkg.mod``) so the repository root stays importable;
    a service declaring ``script`` keeps the file-path form. The API needs
    the module form because it imports ``scripts.*`` at import time.

    Exactly one of the two must be declared. A configuration carrying
    NEITHER would otherwise surface as a bare ``KeyError: 'script'``, and
    one carrying BOTH would silently pick a launch form the author did not
    choose. Both are configuration errors, refused with one generic message
    that reports no supplied value.
    """
    has_module = "module" in config
    has_script = "script" in config
    if has_module == has_script:  # neither, or both
        raise ValueError(
            "Service configuration must define exactly one of 'module' or 'script'."
        )
    if has_module:
        args = [PYTHON, "-u", "-m", config["module"]]
    else:
        args = [PYTHON, "-u", str(PROJECT_ROOT / config["script"])]
    args.extend(config.get("args", []))
    return args


def start_service(name: str, config: dict) -> int:
    """Start a service as a hidden background process."""
    # Check if already running
    existing = find_process(config["marker"])
    if existing:
        print(f"  [{name}] Already running (PID {existing[0]})")
        return existing[0]

    args = build_command(config)

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    log_dir = PROJECT_ROOT / "data"
    stdout_log = log_dir / f"{name}_stdout.log"
    stderr_log = log_dir / f"{name}_stderr.log"

    proc = subprocess.Popen(
        args,
        cwd=str(PROJECT_ROOT),
        stdout=open(stdout_log, "w"),
        stderr=open(stderr_log, "w"),
        env=env,
        creationflags=CREATE_NO_WINDOW,
    )

    print(f"  [{name}] Started (PID {proc.pid}) — {config['description']}")
    return proc.pid


def stop_service(name: str, config: dict):
    """Stop a service by killing its process."""
    pids = find_process(config["marker"])
    if not pids:
        print(f"  [{name}] Not running")
        return

    for pid in pids:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, timeout=10)
            print(f"  [{name}] Stopped (PID {pid})")
        except Exception as e:
            print(f"  [{name}] Failed to stop PID {pid}: {e}")


def status():
    """Check status of all services."""
    print("=" * 55)
    print("  MEDUSA SERVICE STATUS")
    print("=" * 55)

    # Check engine
    engine_pids = find_process("run_v070_engine")
    if engine_pids:
        print(f"  Engine:    RUNNING (PID {engine_pids[0]})")
    else:
        print(f"  Engine:    DOWN")

    # Check each service
    for name, config in SERVICES.items():
        pids = find_process(config["marker"])
        if pids:
            print(f"  {name:10s}: RUNNING (PID {pids[0]})")
        else:
            print(f"  {name:10s}: DOWN")

    # Check latest snapshot
    snapshots = sorted(
        (PROJECT_ROOT / "data").glob("v070_gen*.npz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if snapshots:
        age = time.time() - snapshots[0].stat().st_mtime
        print(f"\n  Latest snapshot: {snapshots[0].name}")
        print(f"  Snapshot age: {age/60:.0f} min")
        print(f"  Engine healthy: {'YES' if age < 900 else 'STALE'}")

    # Check API
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:8080/api/health", timeout=3)
        data = resp.read().decode()
        print(f"\n  API: http://localhost:8080/ — ONLINE")
    except Exception:
        print(f"\n  API: OFFLINE")

    print("=" * 55)


def start_all():
    """Start all Medusa services."""
    print("=" * 55)
    print("  MEDUSA MASTER ORCHESTRATOR — Phase 16c")
    print("  Starting all services...")
    print("=" * 55)

    for name, config in SERVICES.items():
        start_service(name, config)

    print()
    print("  All services started!")
    print("  The Watchdog will auto-launch the engine if it's not running.")
    print()
    print("  REST API:  http://192.168.86.29:8080/")
    print("  Geometry:  data/geometry/")
    print("  Logs:      data/*_stdout.log")
    print("=" * 55)


def stop_all():
    """Stop all Medusa services (including engine)."""
    print("Stopping all Medusa services...")

    # Stop engine first
    engine_pids = find_process("run_v070_engine")
    for pid in engine_pids:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, timeout=10)
            print(f"  [engine] Stopped (PID {pid})")
        except Exception:
            pass

    # Stop services
    for name, config in SERVICES.items():
        stop_service(name, config)

    print("All services stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Medusa Master Orchestrator")
    parser.add_argument("--status", action="store_true", help="Check service status")
    parser.add_argument("--stop", action="store_true", help="Stop all services")
    parser.add_argument("--start", action="store_true", help="Start all services (default)")
    args = parser.parse_args()

    if args.status:
        status()
    elif args.stop:
        stop_all()
    else:
        start_all()
