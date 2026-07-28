#!/usr/bin/env python3
"""Phase 14d: Medusa Watchdog Daemon

A lightweight, completely decoupled monitoring service that:
1. Checks if the Medusa engine process is alive every 60 seconds
2. Detects and kills duplicate processes
3. Automatically restarts from the latest .npz snapshot on crash
4. Maintains a clean log of all anomalies and reboots

Run as: python scripts/watchdog.py
Or install as a Windows scheduled task for true 24/7 autonomy.

Inspired by Intel's PowerVia: completely separating monitoring (power)
from execution (signal) to prevent architectural congestion.
"""

import os
import sys
import time
import signal
import subprocess
import logging
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = DATA_DIR
PYTHON_EXE = sys.executable  # Use the same Python that runs this script
ENGINE_SCRIPT = PROJECT_ROOT / "scripts" / "run_v070_engine.py"
RULE_FILE = PROJECT_ROOT / "ca" / "rules" / "example.toml"

CHECK_INTERVAL = 60        # seconds between pulse checks
MAX_RESTART_ATTEMPTS = 10  # before giving up
RESTART_COOLDOWN = 30      # seconds to wait before restart after crash
PROCESS_NAME = "run_v070_engine.py"

# Fixed status lines for a FAILED process query. A query failure means the
# engine's real state is unknown -- it is never evidence that zero engines are
# running -- so these are deliberately distinct from "ENGINE DOWN!".
PROCESS_QUERY_FAILED_MESSAGE = "Process query FAILED: engine status unknown"
ENGINE_STATUS_UNKNOWN_MESSAGE = (
    "Engine status UNKNOWN: process query failed; no restart decision this cycle"
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log_path = LOG_DIR / "watchdog.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHDOG] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("watchdog")

# ---------------------------------------------------------------------------
# Process Management
# ---------------------------------------------------------------------------

def find_engine_processes():
    """Find all running Medusa engine processes.

    Returns a list of ``(pid, cmdline)`` when the query SUCCEEDS — an ordinary
    empty list when it succeeded and simply matched nothing — and ``None`` when
    the query itself FAILED, so the engine's real state is unknown.

    That distinction is the whole point: the watchdog restarts the engine when
    it sees zero processes. Previously every failure — a PowerShell timeout, a
    launch/OS error, a non-zero exit whose stdout happened to be empty, or
    output whose PID would not parse — was converted into ``[]``, which the loop
    read as proof that no engine was running. A monitoring failure could
    therefore start a duplicate engine or drive a restart storm. ``None`` cannot
    be mistaken for a successful count of zero.

    Only expected process-query and parsing boundary failures are caught; there
    is no blanket catch, so unrelated programming errors still surface.
    """
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -like '*run_v070_engine*' -and $_.Name -eq 'python.exe'} | Select-Object ProcessId, CommandLine | Format-List"],
            capture_output=True, text=True, timeout=10
        )
    except (subprocess.SubprocessError, OSError):
        # Timeout, launch failure, or any other OS-level query failure.
        log.error(PROCESS_QUERY_FAILED_MESSAGE)
        return None

    # A non-zero exit means the query did not run to completion, so its (often
    # empty) stdout is NOT evidence that no engine is running.
    if result.returncode != 0:
        log.error(PROCESS_QUERY_FAILED_MESSAGE)
        return None

    processes = []
    current_pid = None
    current_cmd = None
    try:
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line.startswith("ProcessId"):
                current_pid = int(line.split(":")[-1].strip())
            elif line.startswith("CommandLine"):
                current_cmd = line.split(":", 1)[-1].strip()
                if current_pid and current_cmd:
                    processes.append((current_pid, current_cmd))
                current_pid = None
                current_cmd = None
    except ValueError:
        # A PID that will not parse means the listing cannot be trusted; report
        # unknown rather than a silently partial count.
        log.error(PROCESS_QUERY_FAILED_MESSAGE)
        return None
    return processes


def find_latest_snapshot():
    """Find the most recent .npz snapshot in the data directory."""
    snapshots = sorted(
        DATA_DIR.glob("v070_gen*.npz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if snapshots:
        return snapshots[0]
    return None


def kill_process(pid):
    """Kill a process by PID."""
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                       capture_output=True, timeout=10)
        log.info(f"Killed process {pid}")
        return True
    except Exception as e:
        log.error(f"Failed to kill process {pid}: {e}")
        return False


def start_engine(snapshot_path):
    """Start the Medusa engine from a snapshot, hidden and logged."""
    log.info(f"Starting engine from: {snapshot_path.name}")

    args = [PYTHON_EXE, "-u", str(ENGINE_SCRIPT)]
    if snapshot_path:
        args.extend(["--resume", str(snapshot_path)])

    stdout_log = DATA_DIR / "v070_gpu_stdout.log"
    stderr_log = DATA_DIR / "v070_gpu_stderr.log"

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    try:
        # Use CREATE_NO_WINDOW to avoid QuickEdit freeze
        CREATE_NO_WINDOW = 0x08000000
        proc = subprocess.Popen(
            args,
            cwd=str(PROJECT_ROOT),
            stdout=open(stdout_log, "w"),
            stderr=open(stderr_log, "w"),
            env=env,
            creationflags=CREATE_NO_WINDOW,
        )
        log.info(f"Engine started: PID {proc.pid}")
        return proc.pid
    except Exception as e:
        log.error(f"Failed to start engine: {e}")
        return None


def check_engine_health(processes):
    """Check if the engine is producing recent snapshots."""
    latest = find_latest_snapshot()
    if not latest:
        return False, "No snapshots found"

    age = time.time() - latest.stat().st_mtime
    if age > 900:  # 15 minutes without a snapshot = stalled
        return False, f"Latest snapshot is {age/60:.0f} min old (stale)"

    return True, f"Latest: {latest.name} ({age/60:.0f} min ago)"


# ---------------------------------------------------------------------------
# Main Watchdog Loop
# ---------------------------------------------------------------------------

def run_watchdog():
    """Main watchdog loop — runs forever, checking every 60 seconds."""
    log.info("=" * 60)
    log.info("  MEDUSA WATCHDOG DAEMON — Phase 14d")
    log.info(f"  Check interval: {CHECK_INTERVAL}s")
    log.info(f"  Project: {PROJECT_ROOT}")
    log.info(f"  Log: {log_path}")
    log.info("=" * 60)

    restart_count = 0
    last_restart_time = 0

    while True:
        try:
            # 1. Find engine processes
            processes = find_engine_processes()

            # 1a. A FAILED query is not proof the engine is down, so no restart
            # or duplicate-kill decision may be made from it: no snapshot
            # lookup, no start_engine, no kill_process, and restart_count /
            # last_restart_time are left exactly as they were. Wait the normal
            # cadence and re-query on the next cycle.
            if processes is None:
                log.error(ENGINE_STATUS_UNKNOWN_MESSAGE)
                time.sleep(CHECK_INTERVAL)
                continue

            num_engines = len(processes)

            # 2. Handle duplicate processes
            if num_engines > 1:
                log.warning(f"DUPLICATE DETECTED: {num_engines} engine processes running!")
                # Keep the oldest (lowest PID), kill the rest
                processes.sort(key=lambda x: x[0])
                for pid, cmd in processes[1:]:
                    log.warning(f"  Killing duplicate PID {pid}")
                    kill_process(pid)
                log.info(f"  Kept primary PID {processes[0][0]}")

            # 3. Handle no engine running
            elif num_engines == 0:
                log.warning("ENGINE DOWN! No Medusa process detected.")

                # Cooldown check
                time_since_restart = time.time() - last_restart_time
                if time_since_restart < RESTART_COOLDOWN:
                    log.info(f"  Cooldown: waiting {RESTART_COOLDOWN - time_since_restart:.0f}s before restart")
                    time.sleep(CHECK_INTERVAL)
                    continue

                # Restart attempt
                if restart_count >= MAX_RESTART_ATTEMPTS:
                    log.error(f"  MAX RESTARTS ({MAX_RESTART_ATTEMPTS}) EXCEEDED. Manual intervention needed!")
                    time.sleep(CHECK_INTERVAL * 5)  # Back off
                    continue

                snapshot = find_latest_snapshot()
                if snapshot:
                    pid = start_engine(snapshot)
                    if pid:
                        restart_count += 1
                        last_restart_time = time.time()
                        log.info(f"  Restart #{restart_count} successful (PID {pid})")
                    else:
                        log.error("  Restart FAILED!")
                else:
                    log.error("  No snapshot found to resume from!")

            # 4. Engine is running — health check
            else:
                pid = processes[0][0]
                healthy, status = check_engine_health(processes)

                if healthy:
                    # Reset restart counter on sustained health
                    if restart_count > 0 and (time.time() - last_restart_time) > 600:
                        log.info(f"  Engine stable for 10+ min, resetting restart counter (was {restart_count})")
                        restart_count = 0

                    # Periodic heartbeat (every 5 minutes = every 5th check)
                    if int(time.time()) % 300 < CHECK_INTERVAL:
                        log.info(f"  HEARTBEAT: PID {pid} | {status}")
                else:
                    log.warning(f"  HEALTH WARNING: PID {pid} | {status}")
                    # Don't kill yet — give it 2 more checks
                    # (The stale snapshot might just be a slow step at 256³)

        except KeyboardInterrupt:
            log.info("Watchdog shutting down (Ctrl+C)")
            break
        except Exception as e:
            log.error(f"Watchdog error: {e}", exc_info=True)

        time.sleep(CHECK_INTERVAL)


def run_once():
    """One-shot status check for ``--once``. Returns the process exit status.

    A failed process query reports the fixed status-unknown line and exits
    non-zero: it must never print "Engine NOT running!", which asserts a fact a
    failed query cannot establish. A successful query keeps its established
    output for zero, one or many processes and exits 0.

    Split out of the ``__main__`` block only so the query-failure branch has a
    return status to assert; argument parsing and dispatch are unchanged.
    """
    processes = find_engine_processes()
    if processes is None:
        print(PROCESS_QUERY_FAILED_MESSAGE)
        return 1
    if processes:
        print(f"Engine running: {len(processes)} process(es)")
        for pid, cmd in processes:
            print(f"  PID {pid}: {cmd[:80]}...")
        healthy, status = check_engine_health(processes)
        print(f"  Health: {'OK' if healthy else 'WARNING'} — {status}")
    else:
        print("Engine NOT running!")
        snapshot = find_latest_snapshot()
        if snapshot:
            print(f"  Latest snapshot: {snapshot.name}")
        else:
            print("  No snapshots found!")
    return 0


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Medusa Watchdog Daemon (Phase 14d)")
    parser.add_argument("--check-interval", type=int, default=60, help="Seconds between checks")
    parser.add_argument("--once", action="store_true", help="Run one check and exit")
    args = parser.parse_args()

    CHECK_INTERVAL = args.check_interval

    if args.once:
        sys.exit(run_once())
    else:
        run_watchdog()
