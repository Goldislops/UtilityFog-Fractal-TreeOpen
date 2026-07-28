"""Tests for `scripts/watchdog.py` process-query fail-closed behaviour.

`find_engine_processes()` used to convert every failure of the PowerShell
process query — timeout, launch/OS error, a non-zero exit whose stdout happened
to be empty, or output whose PID would not parse — into an empty list. The
watchdog loop reads an empty list as proof that zero engines are running, so a
*monitoring* failure could send it down the engine-down path: pick a snapshot,
call `start_engine`, and count a restart. That can create a duplicate engine or
a restart storm from a state that was never actually observed.

The query now returns `None` on failure, which no caller can mistake for a
successful count of zero, and the loop makes no restart or duplicate-kill
decision from it.

Nothing here runs a real process: `subprocess.run` is replaced at the module
boundary, and the snapshot/start/kill seams are mocked. No real PowerShell,
taskkill, engine, scheduled task or subprocess is executed, no watchdog log file
is written, and no test sleeps in real time.

Scope is the "query failed" versus "query succeeded with zero engines"
distinction only — not whole-watchdog, whole-process-management or
Windows-service totality.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import types
from unittest import mock

import pytest

# `scripts/watchdog.py` builds `logging.FileHandler(log_path)` as an ARGUMENT to
# `logging.basicConfig`, so importing it opens `data/watchdog.log` even when
# basicConfig itself is neutralised. Both are patched for the duration of the
# import so the suite writes no watchdog log and does not reconfigure root
# logging; production logging architecture is unchanged.
with mock.patch("logging.FileHandler"), mock.patch("logging.basicConfig"):
    from scripts import watchdog


VALID_STDOUT = (
    "ProcessId   : 1234\n"
    "CommandLine : python.exe -u run_v070_engine.py --resume snap.npz\n"
    "\n"
    "ProcessId   : 5678\n"
    "CommandLine : python.exe -u run_v070_engine.py --resume other.npz\n"
)

VALID_PROCESSES = [
    (1234, "python.exe -u run_v070_engine.py --resume snap.npz"),
    (5678, "python.exe -u run_v070_engine.py --resume other.npz"),
]


class _Completed:
    """Stand-in for `subprocess.CompletedProcess`."""

    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


class _FakeTime:
    """Deterministic clock whose `sleep` ends the loop instead of waiting."""

    def __init__(self, stop_after_sleeps=1):
        self.stop_after = stop_after_sleeps
        self.sleeps = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        if len(self.sleeps) >= self.stop_after:
            raise KeyboardInterrupt  # run_watchdog treats this as a clean stop

    def time(self):
        return 1000.0


# Query-failure side effects, exercised through the real `subprocess.run` seam.
def _timeout():
    return subprocess.TimeoutExpired(cmd="powershell", timeout=10)


QUERY_FAILURES = [
    ("timeout", _timeout),
    ("os_error", lambda: OSError("launch failed")),
    ("nonzero_exit", lambda: _Completed(stdout="", returncode=1)),
    ("nonzero_exit_with_output", lambda: _Completed(stdout=VALID_STDOUT, returncode=2)),
    ("malformed_pid", lambda: _Completed(
        stdout="ProcessId   : not-a-number\nCommandLine : x\n", returncode=0)),
]
QUERY_FAILURE_IDS = [name for name, _ in QUERY_FAILURES]


def _query(monkeypatch, side_effect):
    """Call the REAL find_engine_processes with a mocked subprocess boundary."""
    monkeypatch.setattr(watchdog.subprocess, "run", mock.Mock(side_effect=side_effect))
    return watchdog.find_engine_processes()


class _Seams:
    """Recorded stand-ins for every side-effecting call the loop can make."""

    def __init__(self, snapshot_name="snap.npz"):
        self.snapshot_name = snapshot_name
        self.snapshot_lookups = 0
        self.started = []
        self.killed = []

    def find_latest_snapshot(self):
        self.snapshot_lookups += 1
        if self.snapshot_name is None:
            return None
        return types.SimpleNamespace(name=self.snapshot_name)

    def start_engine(self, snapshot_path):
        self.started.append(getattr(snapshot_path, "name", snapshot_path))
        return 4321

    def kill_process(self, pid):
        self.killed.append(pid)
        return True


def _run_loop(monkeypatch, side_effects, cycles=1, snapshot_name="snap.npz"):
    """Drive the REAL run_watchdog for `cycles` iterations; return the seams.

    `side_effects` feeds the mocked `subprocess.run`, so each cycle exercises the
    genuine `find_engine_processes` rather than an injected return value.
    """
    seams = _Seams(snapshot_name)
    monkeypatch.setattr(watchdog.subprocess, "run", mock.Mock(side_effect=side_effects))
    monkeypatch.setattr(watchdog, "find_latest_snapshot", seams.find_latest_snapshot)
    monkeypatch.setattr(watchdog, "start_engine", seams.start_engine)
    monkeypatch.setattr(watchdog, "kill_process", seams.kill_process)
    monkeypatch.setattr(watchdog, "time", _FakeTime(stop_after_sleeps=cycles))
    try:
        watchdog.run_watchdog()
    except KeyboardInterrupt:
        pass  # the trailing sleep is outside the loop's try block
    return seams


# -- find_engine_processes: successful queries --------------------------------


def test_successful_query_returns_process_tuples(monkeypatch):
    assert _query(monkeypatch, [_Completed(stdout=VALID_STDOUT)]) == VALID_PROCESSES


def test_successful_query_with_no_matches_returns_exact_empty_list(monkeypatch):
    result = _query(monkeypatch, [_Completed(stdout="", returncode=0)])
    assert result == []
    assert type(result) is list  # an ordinary empty list, never the failure signal
    assert result is not None


def test_successful_query_ignores_incomplete_trailing_record(monkeypatch):
    """Established parsing behaviour: a ProcessId with no CommandLine is skipped."""
    stdout = VALID_STDOUT + "ProcessId   : 9999\n"
    assert _query(monkeypatch, [_Completed(stdout=stdout)]) == VALID_PROCESSES


# -- find_engine_processes: failures produce the unmistakable signal ----------


@pytest.mark.parametrize("name,make", QUERY_FAILURES, ids=QUERY_FAILURE_IDS)
def test_query_failure_returns_none(name, make, monkeypatch):
    """Every recognised query failure must be distinguishable from zero engines."""
    result = _query(monkeypatch, [make()])
    assert result is None
    assert result != []  # explicitly NOT a successful empty result


@pytest.mark.parametrize("name,make", QUERY_FAILURES, ids=QUERY_FAILURE_IDS)
def test_query_failure_logs_the_fixed_message(name, make, monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger="watchdog")
    _query(monkeypatch, [make()])
    assert watchdog.PROCESS_QUERY_FAILED_MESSAGE in caplog.text


def test_unrelated_programming_error_is_not_swallowed(monkeypatch):
    """No blanket catch: an unexpected error still surfaces instead of becoming
    a query-failure signal."""
    monkeypatch.setattr(
        watchdog.subprocess, "run", mock.Mock(side_effect=ZeroDivisionError("bug"))
    )
    with pytest.raises(ZeroDivisionError):
        watchdog.find_engine_processes()


# -- run_watchdog: a failed query reaches no restart decision -----------------


@pytest.mark.parametrize("name,make", QUERY_FAILURES, ids=QUERY_FAILURE_IDS)
def test_query_failure_makes_no_restart_or_kill_decision(name, make, monkeypatch):
    """Pre-fix this returned [], so the loop logged ENGINE DOWN, looked up a
    snapshot and called start_engine."""
    seams = _run_loop(monkeypatch, [make()], cycles=1)
    assert seams.started == []
    assert seams.killed == []
    assert seams.snapshot_lookups == 0  # the restart snapshot was never inspected


@pytest.mark.parametrize("name,make", QUERY_FAILURES, ids=QUERY_FAILURE_IDS)
def test_query_failure_is_not_reported_as_engine_down(name, make, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="watchdog")
    _run_loop(monkeypatch, [make()], cycles=1)
    assert watchdog.ENGINE_STATUS_UNKNOWN_MESSAGE in caplog.text
    assert "ENGINE DOWN" not in caplog.text
    assert "Restart #" not in caplog.text


def test_repeated_query_failures_never_restart(monkeypatch):
    seams = _run_loop(monkeypatch, [_timeout() for _ in range(5)], cycles=5)
    assert seams.started == []
    assert seams.killed == []
    assert seams.snapshot_lookups == 0


# -- restart accounting is untouched by a failed cycle ------------------------


def test_failed_cycle_does_not_consume_restart_accounting(monkeypatch, caplog):
    """A failure cycle followed by a genuine zero-process cycle must restart,
    and must be restart #1.

    This witnesses both counters: had the failure cycle set `last_restart_time`
    the second cycle would be inside the cooldown and skip the restart, and had
    it incremented `restart_count` the log would read "Restart #2".
    """
    caplog.set_level(logging.INFO, logger="watchdog")
    seams = _run_loop(
        monkeypatch, [_timeout(), _Completed(stdout="", returncode=0)], cycles=2
    )
    assert seams.started == ["snap.npz"]
    assert "Restart #1 successful" in caplog.text
    assert "Restart #2" not in caplog.text


def test_successful_cycle_after_failure_still_proceeds(monkeypatch):
    seams = _run_loop(
        monkeypatch,
        [_timeout(), _timeout(), _Completed(stdout="", returncode=0)],
        cycles=3,
    )
    assert seams.started == ["snap.npz"]
    assert seams.snapshot_lookups == 1  # only the successful cycle looked


# -- established successful-query behaviour is preserved ----------------------


def test_genuine_zero_process_result_still_restarts(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="watchdog")
    seams = _run_loop(monkeypatch, [_Completed(stdout="", returncode=0)], cycles=1)
    assert seams.started == ["snap.npz"]
    assert seams.snapshot_lookups == 1
    assert "ENGINE DOWN" in caplog.text


def test_genuine_zero_process_result_with_no_snapshot_does_not_start(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="watchdog")
    seams = _run_loop(
        monkeypatch, [_Completed(stdout="", returncode=0)], cycles=1, snapshot_name=None
    )
    assert seams.started == []
    assert seams.snapshot_lookups == 1
    assert "No snapshot found to resume from!" in caplog.text


def test_duplicate_detection_still_kills_the_extra_process(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="watchdog")
    seams = _run_loop(monkeypatch, [_Completed(stdout=VALID_STDOUT)], cycles=1)
    assert seams.killed == [5678]      # lowest PID kept, the rest killed
    assert seams.started == []
    assert "DUPLICATE DETECTED" in caplog.text


def test_single_healthy_process_is_left_alone(monkeypatch):
    single = "ProcessId   : 1234\nCommandLine : python.exe -u run_v070_engine.py\n"
    monkeypatch.setattr(watchdog, "check_engine_health", lambda p: (True, "ok"))
    seams = _run_loop(monkeypatch, [_Completed(stdout=single)], cycles=1)
    assert seams.started == []
    assert seams.killed == []


# -- --once behaviour ---------------------------------------------------------


@pytest.mark.parametrize("name,make", QUERY_FAILURES, ids=QUERY_FAILURE_IDS)
def test_once_reports_status_unknown_and_exits_non_zero(name, make, monkeypatch, capsys):
    monkeypatch.setattr(watchdog.subprocess, "run", mock.Mock(side_effect=[make()]))
    status = watchdog.run_once()
    output = capsys.readouterr().out
    assert status != 0
    assert status == 1
    assert watchdog.PROCESS_QUERY_FAILED_MESSAGE in output
    assert "Engine NOT running!" not in output  # the false claim it used to make


def test_once_zero_processes_keeps_established_output(monkeypatch, capsys):
    monkeypatch.setattr(
        watchdog.subprocess, "run", mock.Mock(side_effect=[_Completed(stdout="")])
    )
    monkeypatch.setattr(watchdog, "find_latest_snapshot", lambda: None)
    status = watchdog.run_once()
    output = capsys.readouterr().out
    assert status == 0
    assert "Engine NOT running!" in output
    assert "No snapshots found!" in output


def test_once_running_processes_keep_established_output(monkeypatch, capsys):
    monkeypatch.setattr(
        watchdog.subprocess, "run", mock.Mock(side_effect=[_Completed(stdout=VALID_STDOUT)])
    )
    monkeypatch.setattr(watchdog, "check_engine_health", lambda p: (True, "Latest: x"))
    status = watchdog.run_once()
    output = capsys.readouterr().out
    assert status == 0
    assert "Engine running: 2 process(es)" in output
    assert "PID 1234" in output and "PID 5678" in output
    assert "Health: OK" in output
