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
import time
import subprocess
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
CREATE_NO_WINDOW = 0x08000000

# Service definitions
SERVICES = {
    "watchdog": {
        "script": "scripts/watchdog.py",
        "marker": "watchdog.py",
        "description": "Watchdog Daemon (Phase 14d)",
    },
    "api": {
        "script": "scripts/medusa_api.py",
        "args": ["--port", "8080"],
        "marker": "medusa_api.py",
        "description": "REST API (Phase 16a)",
    },
    "geometry": {
        "script": "scripts/geometry_daemon.py",
        "marker": "geometry_daemon.py",
        "description": "Geometry Export Daemon (Phase 16b)",
    },
}


def find_process(marker: str) -> list:
    """Find running processes matching a marker string."""
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             f"Get-CimInstance Win32_Process | Where-Object {{$_.CommandLine -like '*{marker}*' -and $_.Name -eq 'python.exe'}} | Select-Object ProcessId | Format-List"],
            capture_output=True, text=True, timeout=10,
        )
        pids = []
        for line in result.stdout.strip().split("\n"):
            if line.strip().startswith("ProcessId"):
                pid = int(line.split(":")[-1].strip())
                pids.append(pid)
        return pids
    except Exception:
        return []


def start_service(name: str, config: dict) -> int:
    """Start a service as a hidden background process."""
    # Check if already running
    existing = find_process(config["marker"])
    if existing:
        print(f"  [{name}] Already running (PID {existing[0]})")
        return existing[0]

    args = [PYTHON, "-u", str(PROJECT_ROOT / config["script"])]
    args.extend(config.get("args", []))

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
