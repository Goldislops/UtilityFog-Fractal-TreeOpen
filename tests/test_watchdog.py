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
import os
import pathlib
import subprocess
import sys
import types
from unittest import mock

import pytest

from scripts.snapshot_archive_guard import (
    PRODUCTION_DISCOVERY_POLICY,
    CandidateDiscoveryPolicy,
    DiscoveryFailed,
    DiscoveryFailureReason,
    DiscoverySucceeded,
)

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

    def discover_snapshots(self):
        self.snapshot_lookups += 1
        if self.snapshot_name is None:
            return DiscoverySucceeded((), 0, 0, 0)
        return DiscoverySucceeded((pathlib.Path(self.snapshot_name),), 0, 1, 1)

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
    monkeypatch.setattr(watchdog, "discover_snapshots", seams.discover_snapshots)
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
    monkeypatch.setattr(
        watchdog, "discover_snapshots", lambda: DiscoverySucceeded((), 0, 0, 0)
    )
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


# =============================================================================
# Bounded snapshot discovery
# =============================================================================
#
# `find_latest_snapshot()` used to be an unbounded
# `sorted(DATA_DIR.glob("v070_gen*.npz"), key=lambda p: p.stat().st_mtime)`.
# It ran from three call sites -- the per-cycle health check, the engine-down
# restart branch and `--once` -- and collapsed every possible directory state
# into `Path | None`. "The directory is empty", "names matched but every
# metadata read failed" and "the listing could not be completed at all" were
# indistinguishable, and the last of those could send the loop down the restart
# path on a directory state it had never actually observed.
#
# `discover_snapshots()` now returns the shared primitive's result and each
# caller keeps those states apart.
#
# This section is DISCOVERY ONLY and makes no archive-admission claim.
# `admit_snapshot` and `first_admissible` are not used: a corrupt or partially
# written newest snapshot is still selected and still handed to the restart
# subprocess, and one can still burn the restart budget. A selected path can
# also disappear after discovery succeeds but before the subprocess opens it.
# Neither is closed here.
#
# Nothing below starts a process, reads the real data directory or writes a
# watchdog log: `watchdog.DATA_DIR` is redirected to pytest's `tmp_path`,
# `subprocess.Popen` is mocked at the module boundary, and the import-time
# `logging.FileHandler` patch above is untouched.


def _touch_snapshot(directory, name, mtime_ns=None):
    """Create one candidate file, optionally at an exact modification time."""
    path = pathlib.Path(directory) / name
    path.write_bytes(b"")
    if mtime_ns is not None:
        os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


ENGINE_DOWN = [_Completed(stdout="", returncode=0)]


def _discovering_loop(monkeypatch, side_effects, data_dir, *, policy=None, cycles=1):
    """Drive the REAL loop with REAL discovery over `data_dir`.

    Unlike `_run_loop`, neither `discover_snapshots` nor `start_engine` is
    stubbed: the genuine functions run, and `subprocess.Popen` is mocked at the
    module boundary so an attempted engine start is observable and inert.
    """
    popen = mock.Mock()
    monkeypatch.setattr(watchdog.subprocess, "run", mock.Mock(side_effect=side_effects))
    monkeypatch.setattr(watchdog.subprocess, "Popen", popen)
    monkeypatch.setattr(watchdog, "DATA_DIR", pathlib.Path(data_dir))
    if policy is not None:
        monkeypatch.setattr(watchdog, "PRODUCTION_DISCOVERY_POLICY", policy)
    monkeypatch.setattr(watchdog, "kill_process", lambda pid: True)
    monkeypatch.setattr(watchdog, "time", _FakeTime(stop_after_sleeps=cycles))
    try:
        watchdog.run_watchdog()
    except KeyboardInterrupt:
        pass
    return popen


def _state_loop(monkeypatch, state, cycles=1):
    """Drive the REAL loop with one fixed discovery result every cycle."""
    seams = _Seams()
    monkeypatch.setattr(
        watchdog.subprocess,
        "run",
        mock.Mock(side_effect=[_Completed(stdout="", returncode=0)] * cycles),
    )
    monkeypatch.setattr(watchdog, "discover_snapshots", lambda: state)
    monkeypatch.setattr(watchdog, "start_engine", seams.start_engine)
    monkeypatch.setattr(watchdog, "kill_process", seams.kill_process)
    clock = _FakeTime(stop_after_sleeps=cycles)
    monkeypatch.setattr(watchdog, "time", clock)
    try:
        watchdog.run_watchdog()
    except KeyboardInterrupt:
        pass
    return seams, clock


# -- the calibrated policy is imported, never redefined -----------------------


def test_watchdog_uses_the_one_production_discovery_policy():
    # Identity, not equality: a per-consumer instance would be a mixed-cap
    # production state that no test could see.
    assert watchdog.PRODUCTION_DISCOVERY_POLICY is PRODUCTION_DISCOVERY_POLICY


def test_watchdog_defines_no_calibration_constant_of_its_own():
    assert watchdog.PRODUCTION_DISCOVERY_POLICY.max_directory_entries == 196_608
    assert watchdog.PRODUCTION_DISCOVERY_POLICY.max_candidates == 65_536


def test_discovery_passes_the_policy_explicitly(monkeypatch, tmp_path):
    seen = {}

    def fake(directory, *, policy):
        seen["directory"] = directory
        seen["policy"] = policy
        return DiscoverySucceeded((), 0, 0, 0)

    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)
    monkeypatch.setattr(watchdog, "discover_snapshot_candidates", fake)
    watchdog.discover_snapshots()
    assert seen["directory"] == tmp_path
    assert seen["policy"] is PRODUCTION_DISCOVERY_POLICY


def test_discovery_does_not_glob_the_data_directory(monkeypatch, tmp_path):
    # `glob` materialises the whole listing before anything can bound it:
    # `glob.glob` is `list(iglob(...))` and even `iglob` reaches `_listdir`,
    # which is `return list(it)`.
    _touch_snapshot(tmp_path, "v070_gen1.npz")
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)

    def refuse(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("the unbounded glob is still in the discovery path")

    monkeypatch.setattr(pathlib.Path, "glob", refuse)
    result = watchdog.discover_snapshots()
    assert isinstance(result, DiscoverySucceeded)
    assert [p.name for p in result.ordered] == ["v070_gen1.npz"]


# -- S1: clean empty ----------------------------------------------------------


def test_s1_clean_empty_discovery(monkeypatch, tmp_path):
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)
    result = watchdog.discover_snapshots()
    assert isinstance(result, DiscoverySucceeded)
    assert result.ordered == () and result.matched == 0


def test_s1_missing_data_directory_is_clean_empty_not_a_failure(monkeypatch, tmp_path):
    # `Path.glob` over a missing directory also yielded nothing, so this is the
    # established behaviour rather than a new refusal.
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path / "absent")
    assert isinstance(watchdog.discover_snapshots(), DiscoverySucceeded)


def test_s1_restart_branch_keeps_the_legacy_message_verbatim(
    monkeypatch, tmp_path, caplog
):
    caplog.set_level(logging.INFO, logger="watchdog")
    popen = _discovering_loop(monkeypatch, ENGINE_DOWN, tmp_path)
    assert popen.call_count == 0
    assert "  No snapshot found to resume from!" in caplog.text


def test_s1_health_keeps_the_legacy_message_verbatim(monkeypatch, tmp_path):
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)
    assert watchdog.check_engine_health([(1, "x")]) == (False, "No snapshots found")


def test_s1_once_keeps_the_legacy_message_verbatim(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        watchdog.subprocess, "run", mock.Mock(side_effect=[_Completed(stdout="")])
    )
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)
    assert watchdog.run_once() == 0
    output = capsys.readouterr().out
    assert "Engine NOT running!" in output
    assert "  No snapshots found!" in output


# -- S2: every matching name's metadata read failed ---------------------------


class _FakeEntry:
    """A `DirEntry` stand-in whose metadata read fails."""

    def __init__(self, name):
        self.name = name

    def stat(self, *, follow_symlinks=True):
        raise OSError("vanished mid-scan")


class _FakeScandir:
    """A context-manager iterator, exactly as `os.scandir` returns."""

    def __init__(self, entries):
        self._entries = list(entries)

    def __enter__(self):
        return iter(self._entries)

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._entries)


def _all_unreadable(monkeypatch, names):
    import scripts.snapshot_archive_guard as sag

    monkeypatch.setattr(
        sag.os, "scandir", lambda directory: _FakeScandir(_FakeEntry(n) for n in names)
    )


def test_s2_mid_scan_disappearance_is_counted_not_raised(monkeypatch, tmp_path):
    _all_unreadable(monkeypatch, ["v070_gen1.npz", "v070_gen2.npz"])
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)
    result = watchdog.discover_snapshots()
    assert isinstance(result, DiscoverySucceeded)
    assert result.unreadable == 2 and result.matched == 2
    assert result.ordered == ()
    assert result.all_matching_unreadable is True


def test_s2_is_not_reported_as_clean_empty(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="watchdog")
    _all_unreadable(monkeypatch, ["v070_gen1.npz"])
    popen = _discovering_loop(monkeypatch, ENGINE_DOWN, tmp_path)
    assert popen.call_count == 0
    assert watchdog.SNAPSHOT_METADATA_UNREADABLE_MESSAGE in caplog.text
    assert "No snapshot found to resume from!" not in caplog.text


def test_s2_health_reports_its_own_state(monkeypatch, tmp_path):
    _all_unreadable(monkeypatch, ["v070_gen1.npz"])
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)
    healthy, status = watchdog.check_engine_health([(1, "x")])
    assert healthy is False
    assert status == watchdog.SNAPSHOT_METADATA_UNREADABLE_MESSAGE


def test_s2_once_reports_its_own_state_and_keeps_exit_zero(
    monkeypatch, tmp_path, capsys
):
    _all_unreadable(monkeypatch, ["v070_gen1.npz"])
    monkeypatch.setattr(
        watchdog.subprocess, "run", mock.Mock(side_effect=[_Completed(stdout="")])
    )
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)
    assert watchdog.run_once() == 0
    output = capsys.readouterr().out
    assert watchdog.SNAPSHOT_METADATA_UNREADABLE_MESSAGE in output
    assert "No snapshots found!" not in output


# -- S3: the listing could not be completed -----------------------------------


TINY_ENTRY_CAP = CandidateDiscoveryPolicy(max_directory_entries=2, max_candidates=64)
TINY_CANDIDATE_CAP = CandidateDiscoveryPolicy(max_directory_entries=64, max_candidates=2)


def test_s3_entry_limit_is_a_bounded_failure(monkeypatch, tmp_path):
    for index in range(4):
        _touch_snapshot(tmp_path, "v070_gen%d.npz" % index)
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)
    monkeypatch.setattr(watchdog, "PRODUCTION_DISCOVERY_POLICY", TINY_ENTRY_CAP)
    result = watchdog.discover_snapshots()
    assert isinstance(result, DiscoveryFailed)
    assert result.reason is DiscoveryFailureReason.ENTRY_LIMIT_EXCEEDED


def test_s3_candidate_limit_is_a_bounded_failure(monkeypatch, tmp_path):
    for index in range(4):
        _touch_snapshot(tmp_path, "v070_gen%d.npz" % index)
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)
    monkeypatch.setattr(watchdog, "PRODUCTION_DISCOVERY_POLICY", TINY_CANDIDATE_CAP)
    result = watchdog.discover_snapshots()
    assert isinstance(result, DiscoveryFailed)
    assert result.reason is DiscoveryFailureReason.CANDIDATE_LIMIT_EXCEEDED


def test_s3_failure_carries_no_candidate_prefix():
    # A partially observed, attacker-ordered prefix must not be consumable.
    assert not hasattr(
        DiscoveryFailed(DiscoveryFailureReason.ITERATION_FAILED, 1, 1, 0), "ordered"
    )


def test_s3_never_starts_an_engine(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="watchdog")
    for index in range(4):
        _touch_snapshot(tmp_path, "v070_gen%d.npz" % index)
    popen = _discovering_loop(monkeypatch, ENGINE_DOWN, tmp_path, policy=TINY_ENTRY_CAP)
    assert popen.call_count == 0
    assert "entry_limit_exceeded" in caplog.text
    assert "No snapshot found to resume from!" not in caplog.text


def test_s3_message_is_path_free(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="watchdog")
    for index in range(4):
        _touch_snapshot(tmp_path, "v070_gen%d.npz" % index)
    _discovering_loop(monkeypatch, ENGINE_DOWN, tmp_path, policy=TINY_ENTRY_CAP)
    assert str(tmp_path) not in caplog.text
    assert ".npz" not in watchdog.SNAPSHOT_DISCOVERY_FAILED_TEMPLATE


@pytest.mark.parametrize("reason", list(DiscoveryFailureReason))
def test_s3_every_reason_has_a_fixed_path_free_message(reason):
    rendered = watchdog.SNAPSHOT_DISCOVERY_FAILED_TEMPLATE.format(reason=reason.value)
    assert reason.value in rendered
    assert "/" not in rendered and "\\" not in rendered


def test_s3_health_reports_its_own_state(monkeypatch, tmp_path):
    for index in range(4):
        _touch_snapshot(tmp_path, "v070_gen%d.npz" % index)
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)
    monkeypatch.setattr(watchdog, "PRODUCTION_DISCOVERY_POLICY", TINY_ENTRY_CAP)
    healthy, status = watchdog.check_engine_health([(1, "x")])
    assert healthy is False
    assert "entry_limit_exceeded" in status


def test_s3_once_reports_its_own_state_and_keeps_exit_zero(
    monkeypatch, tmp_path, capsys
):
    for index in range(4):
        _touch_snapshot(tmp_path, "v070_gen%d.npz" % index)
    monkeypatch.setattr(
        watchdog.subprocess, "run", mock.Mock(side_effect=[_Completed(stdout="")])
    )
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)
    monkeypatch.setattr(watchdog, "PRODUCTION_DISCOVERY_POLICY", TINY_ENTRY_CAP)
    assert watchdog.run_once() == 0
    assert "entry_limit_exceeded" in capsys.readouterr().out


# -- restart accounting is untouched by every indeterminate state -------------


INDETERMINATE_STATES = [
    DiscoverySucceeded((), 0, 0, 0),
    DiscoverySucceeded((), 2, 2, 2),
    DiscoveryFailed(DiscoveryFailureReason.ENTRY_LIMIT_EXCEEDED, 3, 1, 0),
    DiscoveryFailed(DiscoveryFailureReason.CANDIDATE_LIMIT_EXCEEDED, 3, 2, 0),
    DiscoveryFailed(DiscoveryFailureReason.DIRECTORY_OPEN_FAILED, 0, 0, 0),
    DiscoveryFailed(DiscoveryFailureReason.ITERATION_FAILED, 3, 1, 0),
]
INDETERMINATE_IDS = [
    "clean_empty",
    "all_unreadable",
    "entry_limit",
    "candidate_limit",
    "open_failed",
    "iteration_failed",
]


@pytest.mark.parametrize("state", INDETERMINATE_STATES, ids=INDETERMINATE_IDS)
def test_no_indeterminate_state_starts_an_engine(state, monkeypatch):
    seams, _ = _state_loop(monkeypatch, state, cycles=3)
    assert seams.started == []


@pytest.mark.parametrize("state", INDETERMINATE_STATES, ids=INDETERMINATE_IDS)
def test_no_indeterminate_state_consumes_restart_accounting(state, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="watchdog")
    _state_loop(monkeypatch, state, cycles=3)
    assert "Restart #" not in caplog.text
    assert "MAX RESTARTS" not in caplog.text


def test_repeated_discovery_failure_never_exhausts_the_budget(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="watchdog")
    failure = DiscoveryFailed(DiscoveryFailureReason.ITERATION_FAILED, 3, 1, 0)
    seams, _ = _state_loop(monkeypatch, failure, cycles=12)
    assert seams.started == []
    assert "MAX RESTARTS" not in caplog.text


@pytest.mark.parametrize("state", INDETERMINATE_STATES, ids=INDETERMINATE_IDS)
def test_indeterminate_states_sleep_exactly_once_per_cycle(state, monkeypatch):
    # The established fail-closed branches sleep and `continue`; a second sleep
    # would double the cadence exactly when the watchdog is least sure of the
    # world.
    _, clock = _state_loop(monkeypatch, state, cycles=3)
    assert len(clock.sleeps) == 3
    assert clock.sleeps == [watchdog.CHECK_INTERVAL] * 3


# -- S4: a usable listing -----------------------------------------------------


def test_s4_selects_the_primitive_ordering_head(monkeypatch, tmp_path):
    _touch_snapshot(tmp_path, "v070_gen1.npz", mtime_ns=1_000_000_000_000_000_000)
    newest = _touch_snapshot(
        tmp_path, "v070_gen2.npz", mtime_ns=2_000_000_000_000_000_000
    )
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)
    result = watchdog.discover_snapshots()
    assert result.ordered[0] == newest


def test_s4_mtime_ties_break_on_generation_not_filename(monkeypatch, tmp_path):
    # `:06d` in the producer's format is a MINIMUM width production has already
    # outgrown, so comparing names as text inverts across a digit-count
    # boundary: "v070_gen999999" > "v070_gen1000000" as strings.
    same = 1_700_000_000_000_000_000
    for name in ("v070_gen9.npz", "v070_gen10.npz", "v070_gen100.npz"):
        _touch_snapshot(tmp_path, name, mtime_ns=same)
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)
    result = watchdog.discover_snapshots()
    assert [p.name for p in result.ordered] == [
        "v070_gen100.npz",
        "v070_gen10.npz",
        "v070_gen9.npz",
    ]


def test_s4_partial_unreadability_still_yields_a_usable_head(monkeypatch, tmp_path):
    import scripts.snapshot_archive_guard as sag

    good = _touch_snapshot(tmp_path, "v070_gen1.npz")
    real_scandir = sag.os.scandir

    def mixed(directory):
        with real_scandir(directory) as entries:
            real = list(entries)
        return _FakeScandir([_FakeEntry("v070_gen9.npz"), *real])

    monkeypatch.setattr(sag.os, "scandir", mixed)
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)
    result = watchdog.discover_snapshots()
    assert result.unreadable == 1
    assert result.all_matching_unreadable is False
    assert result.ordered[0].name == good.name


def test_s4_starts_the_engine_with_the_selected_path(monkeypatch, tmp_path):
    newest = _touch_snapshot(
        tmp_path, "v070_gen2.npz", mtime_ns=2_000_000_000_000_000_000
    )
    _touch_snapshot(tmp_path, "v070_gen1.npz", mtime_ns=1_000_000_000_000_000_000)
    popen = _discovering_loop(monkeypatch, ENGINE_DOWN, tmp_path)
    assert popen.call_count == 1
    argv = popen.call_args[0][0]
    assert "--resume" in argv
    assert argv[argv.index("--resume") + 1] == str(newest)


def test_s4_health_keeps_its_established_strings(monkeypatch, tmp_path):
    _touch_snapshot(tmp_path, "v070_gen1.npz")
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)
    healthy, status = watchdog.check_engine_health([(1, "x")])
    assert healthy is True
    assert status.startswith("Latest: v070_gen1.npz (")
    assert status.endswith(" min ago)")


def test_s4_health_stale_keeps_its_established_string(monkeypatch, tmp_path):
    _touch_snapshot(tmp_path, "v070_gen1.npz", mtime_ns=1)
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)
    healthy, status = watchdog.check_engine_health([(1, "x")])
    assert healthy is False
    assert status.endswith(" min old (stale)")


def test_s4_once_keeps_its_established_string(monkeypatch, tmp_path, capsys):
    _touch_snapshot(tmp_path, "v070_gen1.npz")
    monkeypatch.setattr(
        watchdog.subprocess, "run", mock.Mock(side_effect=[_Completed(stdout="")])
    )
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)
    assert watchdog.run_once() == 0
    assert "  Latest snapshot: v070_gen1.npz" in capsys.readouterr().out


# -- S5: the later metadata read did not establish an age ---------------------
#
# `DiscoverySucceeded` carries `ordered`, `unreadable`, `processed` and
# `matched` -- and NO modification time. The age comparison therefore needs a
# SECOND metadata read, after selection, and `check_engine_health` catches the
# whole of `OSError` there.
#
# That read can fail for ANY `OSError` cause -- the entry having been removed,
# a permission or sharing denial, or a general I/O or mount failure are only
# examples. The watchdog cannot distinguish them and does not try: one fixed,
# path-free, cause-neutral outcome covers all of them, because a message that
# names a cause it did not establish is worse than one that names none. On a
# network-mounted data directory the permission and I/O cases are not exotic.
#
# This tranche does not close the underlying race, lock or fault. It gives the
# failure a fixed outcome instead of an `OSError` escaping into the loop's
# blanket handler (or, from `--once`, into a traceback).


# Factories, not stored instances. Each invocation raises a FRESH exception, so
# no test can pass by re-raising an object another call already unwound, and
# the `__traceback__` one raise attaches cannot accumulate into the next.
STAT_FAILURES = [
    ("missing", lambda: FileNotFoundError(2, "No such file or directory")),
    ("permission", lambda: PermissionError(13, "Permission denied")),
    ("generic_io", lambda: OSError(5, "Input/output error")),
]
STAT_FAILURE_IDS = [name for name, _ in STAT_FAILURES]

# Vocabulary that would assert a cause the second metadata read never
# established. `OSError` is caught whole, so none of these may appear.
CAUSE_WORDS = (
    "went away", "disappear", "deleted", "removed", "missing", "gone",
    "vanish", "permission", "denied", "locked", "unreadable",
)


def _failing_stat(target, make_error):
    real_stat = pathlib.Path.stat

    def stat(self, *args, **kwargs):
        if self == target:
            raise make_error()
        return real_stat(self, *args, **kwargs)

    return stat


@pytest.mark.parametrize("name,make", STAT_FAILURES, ids=STAT_FAILURE_IDS)
def test_s5_health_reports_the_fixed_unknown_for_every_cause(
    name, make, monkeypatch, tmp_path
):
    target = _touch_snapshot(tmp_path, "v070_gen1.npz")
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pathlib.Path, "stat", _failing_stat(target, make))
    healthy, status = watchdog.check_engine_health([(1, "x")])
    assert healthy is False
    assert status == watchdog.SNAPSHOT_HEALTH_UNKNOWN_MESSAGE


def test_s5_every_cause_produces_the_identical_status(monkeypatch, tmp_path):
    # Independent of what the message happens to say: the three causes must be
    # indistinguishable from the outside.
    seen = set()
    for _, make in STAT_FAILURES:
        with monkeypatch.context() as patch:
            target = _touch_snapshot(tmp_path, "v070_gen1.npz")
            patch.setattr(watchdog, "DATA_DIR", tmp_path)
            patch.setattr(pathlib.Path, "stat", _failing_stat(target, make))
            seen.add(watchdog.check_engine_health([(1, "x")]))
    assert len(seen) == 1


@pytest.mark.parametrize("name,make", STAT_FAILURES, ids=STAT_FAILURE_IDS)
def test_s5_once_does_not_traceback_and_keeps_exit_zero(
    name, make, monkeypatch, tmp_path, capsys
):
    single = "ProcessId   : 1234\nCommandLine : python.exe -u run_v070_engine.py\n"
    target = _touch_snapshot(tmp_path, "v070_gen1.npz")
    monkeypatch.setattr(
        watchdog.subprocess, "run", mock.Mock(side_effect=[_Completed(stdout=single)])
    )
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pathlib.Path, "stat", _failing_stat(target, make))
    assert watchdog.run_once() == 0
    output = capsys.readouterr().out
    assert watchdog.SNAPSHOT_HEALTH_UNKNOWN_MESSAGE in output
    assert "Traceback" not in output


@pytest.mark.parametrize("name,make", STAT_FAILURES, ids=STAT_FAILURE_IDS)
def test_s5_discloses_no_path_for_any_cause(name, make, monkeypatch, tmp_path, capsys):
    single = "ProcessId   : 1234\nCommandLine : python.exe -u run_v070_engine.py\n"
    target = _touch_snapshot(tmp_path, "v070_gen1.npz")
    monkeypatch.setattr(
        watchdog.subprocess, "run", mock.Mock(side_effect=[_Completed(stdout=single)])
    )
    monkeypatch.setattr(watchdog, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pathlib.Path, "stat", _failing_stat(target, make))
    watchdog.run_once()
    output = capsys.readouterr().out
    assert str(tmp_path) not in output
    assert "v070_gen1.npz" not in output


def test_s5_message_is_path_free():
    assert ".npz" not in watchdog.SNAPSHOT_HEALTH_UNKNOWN_MESSAGE
    assert "/" not in watchdog.SNAPSHOT_HEALTH_UNKNOWN_MESSAGE
    assert "\\" not in watchdog.SNAPSHOT_HEALTH_UNKNOWN_MESSAGE


def test_s5_message_names_no_cause():
    lowered = watchdog.SNAPSHOT_HEALTH_UNKNOWN_MESSAGE.lower()
    offenders = [word for word in CAUSE_WORDS if word in lowered]
    assert offenders == []


def test_s5_message_states_only_what_was_observed():
    message = watchdog.SNAPSHOT_HEALTH_UNKNOWN_MESSAGE
    assert "metadata could not be read" in message
    assert "age not established" in message


# -- the fixed messages stay distinct from one another ------------------------


def test_the_fixed_snapshot_messages_are_all_distinct():
    rendered = watchdog.SNAPSHOT_DISCOVERY_FAILED_TEMPLATE.format(reason="x")
    messages = {
        watchdog.SNAPSHOT_METADATA_UNREADABLE_MESSAGE,
        watchdog.SNAPSHOT_HEALTH_UNKNOWN_MESSAGE,
        rendered,
        "No snapshots found",
    }
    assert len(messages) == 4


# -- the #425 rule survives: a failed process query discovers nothing ---------


@pytest.mark.parametrize("name,make", QUERY_FAILURES, ids=QUERY_FAILURE_IDS)
def test_query_failure_performs_no_discovery_at_all(name, make, monkeypatch):
    seams = _run_loop(monkeypatch, [make()], cycles=1)
    assert seams.snapshot_lookups == 0
    assert seams.started == []


def test_query_failure_creates_no_subprocess_beyond_the_query(monkeypatch, tmp_path):
    _touch_snapshot(tmp_path, "v070_gen1.npz")
    popen = _discovering_loop(monkeypatch, [_timeout()], tmp_path)
    assert popen.call_count == 0
