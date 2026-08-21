"""Tests for `scripts/snapshot_retention.py` -- stage-one bounded retention.

Stage one is `PLAN` and recoverable `QUARANTINE` only. There is no `DELETE`,
no automatic reaping, no automatic restoration, no scheduler and no execution
of a serialized plan. Nothing here touches the real `data/` directory: every
population is either an injected fake `scandir` or a handful of real files in
pytest's own `tmp_path`. No test creates a production-sized directory.

Two numbers that look similar are deliberately different controls and are
tested as such: the SCANNER refusal limits (196,608 entries / 65,536 inspected)
and the RETENTION ceilings (8,192 per class). A scanner that refused at the
ceiling would make ceiling eligibility unreachable, so scanning must succeed at
ceiling-plus-one.

Scope is the retention module. Not the merged discovery cache, not admission,
not the watchdog or batch recovery paths -- those remain unbounded with no
admission fallback and are a disclosed separate tranche.
"""

from __future__ import annotations

import dataclasses
import errno
import json
import os
import re
import stat as stat_module
import sys
from pathlib import Path
from unittest import mock

import pytest

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.append(_PROJECT_ROOT)

# Imported defensively so the failing-first commit produces one attributable
# failure per control rather than a single collection error. `importorskip`
# is deliberately NOT used: a skipped control proves nothing, and this file is
# required to run with zero skips.
try:
    from scripts import snapshot_retention as retention
except ImportError:  # pragma: no cover - only before the module exists
    retention = None

from scripts import snapshot_archive_guard as guard  # noqa: E402


DAY = 86_400
NOW = 1_800_000_000_000_000_000  # a fixed pass-start value, in nanoseconds


def _ns(seconds):
    return int(seconds) * 1_000_000_000


def _snap_name(generation=1, step=1, stamp="20260101T000000"):
    return "v070_gen%06d_step%06d_%s.npz" % (generation, step, stamp)


def _telem_name(stamp="20260101T000000"):
    return "telemetry_%s.json" % stamp


class _Stat:
    """A stand-in for `os.stat_result` with only the fields retention reads.

    This models `os.lstat`, which is what the scanner reads: a `DirEntry`
    cache reports `st_dev`, `st_ino` and `st_nlink` as 0 on Windows -- measured
    on the deployed platform -- so it cannot supply the stable identity the
    plan must carry, and one authoritative non-following read is used instead.
    """

    def __init__(self, *, mode=stat_module.S_IFREG | 0o644, size=64,
                 mtime_ns=NOW - _ns(60 * DAY), nlink=1, dev=41, ino=0,
                 file_attributes=None):
        self.st_mode = mode
        self.st_size = size
        self.st_mtime_ns = mtime_ns
        self.st_nlink = nlink
        self.st_dev = dev
        self.st_ino = ino
        if file_attributes is not None:
            self.st_file_attributes = file_attributes


_INO = [0]


class _Entry:
    """One directory entry. Its metadata is served through the fake `lstat`."""

    __slots__ = ("name", "stat_result", "error", "recorder")

    def __init__(self, name, stat_result=None, error=None):
        self.name = name
        if stat_result is None:
            _INO[0] += 1
            stat_result = _Stat(ino=_INO[0])
        elif getattr(stat_result, "st_ino", 0) == 0:
            _INO[0] += 1
            stat_result.st_ino = _INO[0]
        self.stat_result = stat_result
        self.error = error
        self.recorder = None


class _FakeScandir:
    """A recording stand-in for `os.scandir`, yielding `_Entry` objects."""

    def __init__(self, entries, open_error=None, iteration_error_after=None):
        self.entries = list(entries)
        self.open_error = open_error
        self.iteration_error_after = iteration_error_after
        self.yielded = []
        self.statted = []
        self.closed = 0
        self.by_name = {}
        for entry in self.entries:
            entry.recorder = self
            self.by_name[entry.name] = entry

    def lstat(self, path, *args, **kwargs):
        """The scanner's one authoritative non-following read."""
        name = os.path.basename(os.fspath(path))
        entry = self.by_name.get(name)
        if entry is None:
            raise FileNotFoundError(errno.ENOENT, "no such file")
        self.statted.append((name, False))
        if entry.error is not None:
            raise entry.error
        return entry.stat_result

    def __call__(self, directory):
        if self.open_error is not None:
            raise self.open_error
        return self

    def __enter__(self):
        return self._iterate()

    def __exit__(self, *exc):
        self.closed += 1
        return False

    def _iterate(self):
        for index, entry in enumerate(self.entries):
            if (self.iteration_error_after is not None
                    and index == self.iteration_error_after):
                raise OSError(errno.EIO, "Input/output error")
            self.yielded.append(entry.name)
            yield entry


def _install(monkeypatch, fake):
    monkeypatch.setattr(retention.os, "scandir", fake)
    monkeypatch.setattr(retention.os, "lstat", fake.lstat)
    return fake


def _snapshots(count, *, start=0, age_days=60, size=64):
    """`count` snapshot entries, newest first by construction."""
    return [
        _Entry(_snap_name(start + index, start + index),
               _Stat(mtime_ns=NOW - _ns(age_days * DAY) - _ns(index),
                     size=size))
        for index in range(count)
    ]


def _telemetry(count, *, age_days=60):
    return [
        _Entry(_telem_name("20260101T%06d" % index),
               _Stat(mtime_ns=NOW - _ns(age_days * DAY) - _ns(index)))
        for index in range(count)
    ]


def _scan(directory="data", policy=None):
    return retention.scan_retention_candidates(
        directory, policy=policy or retention.PRODUCTION_RETENTION_POLICY)


# ===========================================================================
# The production policy
# ===========================================================================

def test_the_production_policy_carries_the_authorized_values():
    policy = retention.PRODUCTION_RETENTION_POLICY
    assert policy.snapshot.max_age_seconds == 30 * DAY
    assert policy.snapshot.recovery_floor == 512
    assert policy.snapshot.absolute_ceiling == 8_192
    assert policy.snapshot.max_inspected == 65_536
    assert policy.telemetry.max_age_seconds == 14 * DAY
    assert policy.telemetry.recovery_floor == 1_024
    assert policy.telemetry.absolute_ceiling == 8_192
    assert policy.telemetry.max_inspected == 65_536
    assert policy.quiescence_seconds == 900
    assert policy.max_actions_per_pass == 512
    assert policy.max_directory_entries == 196_608
    assert policy.max_combined_inspected == 65_536
    assert policy.reserve_window == 8
    assert policy.reserve_required == 3


def test_the_production_policy_is_one_frozen_shared_instance():
    policy = retention.PRODUCTION_RETENTION_POLICY
    assert policy is retention.PRODUCTION_RETENTION_POLICY
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.quiescence_seconds = 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.snapshot.recovery_floor = 1


@pytest.mark.parametrize("field", ["max_age_seconds", "recovery_floor",
                                   "absolute_ceiling", "max_inspected"])
@pytest.mark.parametrize("value", [0, -1, 1.5, "8", None, True, False],
                         ids=["zero", "negative", "float", "str", "none",
                              "true", "false"])
def test_an_invalid_class_policy_field_is_refused(field, value):
    """`True` is an `int` to Python and would silently become 1, so booleans
    are refused explicitly rather than by an `isinstance` that accepts them."""
    kwargs = {"max_age_seconds": 10, "recovery_floor": 2,
              "absolute_ceiling": 4, "max_inspected": 8}
    kwargs[field] = value
    with pytest.raises(ValueError):
        retention.ClassRetentionPolicy(**kwargs)


def test_the_executor_has_no_hidden_policy_default():
    """Calibration lives in the named constant, never in a signature where a
    call site cannot show which values it got."""
    import inspect
    parameter = inspect.signature(
        retention.scan_retention_candidates).parameters["policy"]
    assert parameter.default is inspect.Parameter.empty
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_v1_modes_are_exactly_plan_and_quarantine():
    assert {mode.name for mode in retention.RetentionMode} == {
        "PLAN", "QUARANTINE"}
    source = Path(retention.__file__).read_text(encoding="utf-8")
    tree = __import__("ast").parse(source)
    import ast as _ast
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Constant) and isinstance(node.value, str):
            assert node.value.lower() not in ("delete", "reap", "restore")


def test_no_delete_reap_restore_or_scheduler_surface_exists():
    names = {name.lower() for name in dir(retention)}
    for banned in ("delete", "reap", "restore", "schedule", "purge", "unlink",
                   "rmtree"):
        assert not any(banned in name for name in names), banned


def test_the_module_is_not_importable_from_a_request_handler():
    """A retention scan must never be reachable from an unauthenticated GET."""
    import ast as _ast
    for consumer in ("medusa_api", "lucid_server"):
        source = Path(
            Path(retention.__file__).parent / (consumer + ".py")
        ).read_text(encoding="utf-8")
        for node in _ast.walk(_ast.parse(source)):
            if isinstance(node, _ast.ImportFrom) and node.module:
                assert "snapshot_retention" not in node.module
            if isinstance(node, _ast.Import):
                for alias in node.names:
                    assert "snapshot_retention" not in alias.name


# ===========================================================================
# Grammars -- strict, anchored, ASCII-only
# ===========================================================================

_VALID_SNAPSHOTS = [
    "v070_gen000001_step000001_20260101T000000.npz",
    "v070_gen1_step1_20260101T000000.npz",
    "v070_gen" + "9" * 18 + "_step" + "9" * 18 + "_20260101T000000.npz",
]

_INVALID_SNAPSHOTS = [
    "v070_genjunk.npz",
    "v070_genjunkgen123.npz",
    "v070_gen000001.npz",
    "v070_gen000001_step000001.npz",
    "v070_gen000001_step000001_20260101T000000.npz.bak",
    "xv070_gen000001_step000001_20260101T000000.npz",
    "v070_gen000001_step000001_20260101T000000.NPZ",
    "v070_gen" + "9" * 19 + "_step000001_20260101T000000.npz",
    "v070_gen١٢٣_step000001_20260101T000000.npz",
    "v070_gen000001_step000001_2026010T000000.npz",
    "v070_gen000001_step000001_20260101t000000.npz",
    "../v070_gen000001_step000001_20260101T000000.npz",
    "v070_gen000001_step000001_20260101T000000.npz ",
]

_VALID_TELEMETRY = ["telemetry_20260101T000000.json"]

_INVALID_TELEMETRY = [
    "telemetry.json",
    "telemetry_.json",
    "telemetry_20260101T000000.json.bak",
    "telemetry_20260101T000000.JSON",
    "telemetry_١٢٣٤٥٦٧٨T000000.json",
    "xtelemetry_20260101T000000.json",
    "telemetry_20260101T00000.json",
]


@pytest.mark.parametrize("name", _VALID_SNAPSHOTS)
def test_the_snapshot_grammar_accepts_what_the_producer_writes(name):
    assert retention.classify_name(name) == retention.SNAPSHOT_CLASS


@pytest.mark.parametrize("name", _INVALID_SNAPSHOTS)
def test_the_snapshot_grammar_refuses_everything_else(name):
    assert retention.classify_name(name) is None


@pytest.mark.parametrize("name", _VALID_TELEMETRY)
def test_the_telemetry_grammar_accepts_what_the_producer_writes(name):
    assert retention.classify_name(name) == retention.TELEMETRY_CLASS


@pytest.mark.parametrize("name", _INVALID_TELEMETRY)
def test_the_telemetry_grammar_refuses_everything_else(name):
    assert retention.classify_name(name) is None


def test_retention_is_stricter_than_the_discovery_glob():
    """The asymmetry is the point. `v070_genjunk.npz` IS selectable by bounded
    discovery -- a documented hazard -- but must never be DELETABLE. Discovery
    is permissive and fails closed by refusing to load; retention is
    restrictive and fails closed by refusing to act."""
    import fnmatch
    hostile = "v070_genjunkgen123.npz"
    assert fnmatch.fnmatch(hostile, guard._SNAPSHOT_GLOB)
    assert retention.classify_name(hostile) is None


def test_the_grammars_use_ascii_digit_classes_only():
    source = Path(retention.__file__).read_text(encoding="utf-8")
    for pattern in re.findall(r"re\.compile\((.*?)\)", source, re.S):
        assert "\\d" not in pattern, pattern


@pytest.mark.parametrize("name", [
    "medusa_live.html", "medusa_lucid.html", "medusa_optics.html",
    "organism_genome_qr.png", "organism_v075_phase6c.genome.json",
    "tuning_ledger.jsonl", "tuning_pending.json",
    "watchdog.log", "v070_gpu_stdout.log", "v070_gpu_stderr.log",
    "medusa_gen123_geometry.stl", "acoustic_map_step100.json",
    "emergency_checkpoint.npz", "checkpoint_gen1_x.fog.npz",
    "geometry", "nextness_log", ".retention_quarantine",
])
def test_curated_state_log_and_subdirectory_names_are_never_classified(name):
    """Five of these are version-controlled inside `data/`; two are tuning
    state; the rest are logs, request-written exports, unwired writers and
    subdirectories. A closed allowlist is what keeps every one of them safe."""
    assert retention.classify_name(name) is None


# ===========================================================================
# The bounded scanner
# ===========================================================================

def test_non_allowlisted_names_receive_no_metadata_read(monkeypatch):
    fake = _install(monkeypatch, _FakeScandir([
        _Entry("watchdog.log"), _Entry("medusa_live.html"),
        _Entry("v070_genjunk.npz"), _Entry("tuning_ledger.jsonl"),
        _Entry(_snap_name(1, 1)),
    ]))
    result = _scan()
    assert isinstance(result, retention.ScanSucceeded)
    assert [name for name, _ in fake.statted] == [_snap_name(1, 1)]
    assert all(follow is False for _, follow in fake.statted)


def test_the_scanner_closes_its_iterator(monkeypatch):
    fake = _install(monkeypatch, _FakeScandir(_snapshots(3)))
    _scan()
    assert fake.closed == 1


def test_both_classes_are_collected_separately(monkeypatch):
    _install(monkeypatch, _FakeScandir(_snapshots(3) + _telemetry(2)))
    result = _scan()
    assert len(result.snapshots) == 3
    assert len(result.telemetry) == 2
    assert result.inspected == 5
    assert result.processed == 5


# -- scanner refusal limits are NOT the retention ceilings -------------------

def _tiny(entries=1000, combined=1000, snap=1000, telem=1000, ceiling=8_192,
          floor=0):
    return retention.RetentionPolicy(
        snapshot=retention.ClassRetentionPolicy(
            max_age_seconds=30 * DAY, recovery_floor=max(floor, 1),
            absolute_ceiling=ceiling, max_inspected=snap),
        telemetry=retention.ClassRetentionPolicy(
            max_age_seconds=14 * DAY, recovery_floor=max(floor, 1),
            absolute_ceiling=ceiling, max_inspected=telem),
        quiescence_seconds=900, max_actions_per_pass=512,
        max_directory_entries=entries, max_combined_inspected=combined,
        reserve_window=8, reserve_required=3)


@pytest.mark.parametrize("count", [8_192, 8_193])
def test_the_scanner_succeeds_at_the_retention_ceiling_and_beyond(monkeypatch,
                                                                  count):
    """A scanner that refused at 8,192 would make ceiling eligibility
    unreachable. These are different controls and must not share a limit."""
    _install(monkeypatch, _FakeScandir(_snapshots(count)))
    policy = _tiny(entries=200_000, combined=65_536, snap=65_536)
    result = retention.scan_retention_candidates("data", policy=policy)
    assert isinstance(result, retention.ScanSucceeded)
    assert len(result.snapshots) == count


def test_exactly_the_combined_inspection_limit_succeeds(monkeypatch):
    _install(monkeypatch, _FakeScandir(_snapshots(6) + _telemetry(4)))
    result = retention.scan_retention_candidates("data", policy=_tiny(combined=10))
    assert isinstance(result, retention.ScanSucceeded)
    assert result.inspected == 10


def test_one_past_the_combined_limit_refuses_without_statting_it(monkeypatch):
    fake = _install(monkeypatch, _FakeScandir(_snapshots(6) + _telemetry(5)))
    result = retention.scan_retention_candidates("data", policy=_tiny(combined=10))
    assert isinstance(result, retention.ScanFailed)
    assert result.reason is retention.RetentionFailureReason.COMBINED_LIMIT_EXCEEDED
    assert len(fake.statted) == 10, "the 65,537th-equivalent match was statted"
    assert not hasattr(result, "snapshots")
    assert not hasattr(result, "telemetry")


def test_the_combined_limit_binds_before_the_per_class_limits(monkeypatch):
    """With both classes present the combined limit is the binding one."""
    _install(monkeypatch, _FakeScandir(_snapshots(6) + _telemetry(6)))
    result = retention.scan_retention_candidates(
        "data", policy=_tiny(combined=10, snap=1000, telem=1000))
    assert isinstance(result, retention.ScanFailed)
    assert result.reason is retention.RetentionFailureReason.COMBINED_LIMIT_EXCEEDED


@pytest.mark.parametrize("klass,builder,limit_field,reason_name", [
    ("snapshot", _snapshots, "snap", "SNAPSHOT_LIMIT_EXCEEDED"),
    ("telemetry", _telemetry, "telem", "TELEMETRY_LIMIT_EXCEEDED"),
])
def test_each_class_has_its_own_inspection_limit(monkeypatch, klass, builder,
                                                 limit_field, reason_name):
    _install(monkeypatch, _FakeScandir(builder(5)))
    policy = _tiny(**{limit_field: 4, "combined": 1000})
    result = retention.scan_retention_candidates("data", policy=policy)
    assert isinstance(result, retention.ScanFailed)
    assert result.reason is getattr(
        retention.RetentionFailureReason, reason_name)


def test_exactly_the_entry_limit_succeeds(monkeypatch):
    _install(monkeypatch, _FakeScandir(_snapshots(10)))
    result = retention.scan_retention_candidates("data", policy=_tiny(entries=10))
    assert isinstance(result, retention.ScanSucceeded)
    assert result.processed == 10


def test_one_past_the_entry_limit_fails_with_an_unstatted_look_ahead(monkeypatch):
    fake = _install(monkeypatch, _FakeScandir(_snapshots(11)))
    result = retention.scan_retention_candidates("data", policy=_tiny(entries=10))
    assert isinstance(result, retention.ScanFailed)
    assert result.reason is retention.RetentionFailureReason.ENTRY_LIMIT_EXCEEDED
    assert result.processed == 10
    assert len(fake.statted) == 10, "the look-ahead entry was statted"


@pytest.mark.parametrize("kind,fake_kwargs,reason_name", [
    ("open", {"open_error": PermissionError(13, "denied")},
     "DIRECTORY_OPEN_FAILED"),
    ("iteration", {"iteration_error_after": 3}, "ITERATION_FAILED"),
])
def test_directory_level_failures_return_no_candidate_collection(
        monkeypatch, kind, fake_kwargs, reason_name):
    _install(monkeypatch, _FakeScandir(_snapshots(10), **fake_kwargs))
    result = _scan()
    assert isinstance(result, retention.ScanFailed)
    assert result.reason is getattr(retention.RetentionFailureReason,
                                    reason_name)
    assert not hasattr(result, "snapshots")


def test_a_missing_directory_is_a_clean_empty_scan(monkeypatch):
    _install(monkeypatch, _FakeScandir([], open_error=FileNotFoundError(
        errno.ENOENT, "No such file or directory")))
    result = _scan()
    assert isinstance(result, retention.ScanSucceeded)
    assert result.snapshots == () and result.telemetry == ()


# -- metadata failure aborts; type exclusion does not ------------------------

@pytest.mark.parametrize("klass,entries", [
    ("snapshot", lambda: _snapshots(3) + [
        _Entry(_snap_name(99, 99), error=OSError(errno.EIO, "io"))]),
    ("telemetry", lambda: _telemetry(3) + [
        _Entry(_telem_name("20260202T000000"), error=OSError(errno.EIO, "io"))]),
])
def test_a_metadata_failure_on_an_allowlisted_name_aborts_the_whole_pass(
        monkeypatch, klass, entries):
    """Its position in the newest-first order is UNKNOWN, so every later rank
    is unknown too -- an entry truly inside the recovery floor could be
    computed as outside it. There is no conservative direction available, so
    v1 discards everything and permits zero actions."""
    _install(monkeypatch, _FakeScandir(entries()))
    result = _scan()
    assert isinstance(result, retention.ScanFailed)
    assert result.reason is retention.RetentionFailureReason.METADATA_READ_FAILED
    assert not hasattr(result, "snapshots")
    assert not hasattr(result, "telemetry")


_EXCLUDED_TYPES = [
    ("symlink", dict(stat_result=_Stat(mode=stat_module.S_IFLNK | 0o777))),
    ("reparse_point", dict(stat_result=_Stat(
        file_attributes=stat_module.FILE_ATTRIBUTE_REPARSE_POINT))),
    ("directory", dict(stat_result=_Stat(mode=stat_module.S_IFDIR | 0o755))),
    ("fifo", dict(stat_result=_Stat(mode=stat_module.S_IFIFO | 0o644))),
    ("hardlinked", dict(stat_result=_Stat(nlink=2))),
]


@pytest.mark.parametrize("label,kwargs", _EXCLUDED_TYPES,
                         ids=[label for label, _ in _EXCLUDED_TYPES])
def test_a_successful_read_identifying_an_excluded_type_is_not_a_failure(
        monkeypatch, label, kwargs):
    """Identifying the type REQUIRES a non-following metadata read, so
    "never statted" would be a false claim. The object is read once, excluded,
    and never followed, opened or actioned."""
    excluded = _Entry(_snap_name(500, 500), **kwargs)
    _install(monkeypatch, _FakeScandir(_snapshots(3) + [excluded]))
    result = _scan()
    assert isinstance(result, retention.ScanSucceeded)
    assert len(result.snapshots) == 3
    assert result.excluded == 1
    assert excluded.name not in [entry.basename for entry in result.snapshots]


def test_type_exclusion_shifts_survivors_conservatively(monkeypatch):
    """Removing an element shifts every later element to a LOWER rank, which
    moves survivors FURTHER INSIDE the floor and FURTHER FROM the ceiling.
    Both directions are conservative -- which is exactly why exclusion may
    continue where an unknown position may not."""
    entries = _snapshots(6)
    excluded = _Entry(_snap_name(777, 777),
                      _Stat(mode=stat_module.S_IFLNK | 0o777))
    entries.insert(2, excluded)
    _install(monkeypatch, _FakeScandir(entries))
    result = _scan()
    ranked = retention.rank(result.snapshots)
    assert len(ranked) == 6
    assert [entry.basename for entry in ranked] == [
        entry.name for entry in entries if entry is not excluded]


def test_a_hardlinked_entry_is_excluded_when_the_platform_reports_it(monkeypatch):
    """`st_nlink > 1` from the scan pass excludes immediately. Windows reports
    0 there (measured), so the authoritative link check happens at the
    revalidation `lstat` instead -- see the quarantine controls."""
    linked = _Entry(_snap_name(600, 600), _Stat(nlink=2))
    _install(monkeypatch, _FakeScandir(_snapshots(2) + [linked]))
    result = _scan()
    assert isinstance(result, retention.ScanSucceeded)
    assert len(result.snapshots) == 2
    assert result.excluded == 1


def test_scan_results_are_immutable_tuples(monkeypatch):
    _install(monkeypatch, _FakeScandir(_snapshots(2) + _telemetry(2)))
    result = _scan()
    assert type(result.snapshots) is tuple
    assert type(result.telemetry) is tuple
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.processed = 0


# ===========================================================================
# The pure planner
# ===========================================================================

_PLANNER_INO = [0]


def _entry(name, klass, mtime_ns, generation=-1, step=-1, size=64):
    _PLANNER_INO[0] += 1
    return retention.CandidateEntry(basename=name, klass=klass, size=size,
                                    mtime_ns=mtime_ns, dev=41,
                                    ino=_PLANNER_INO[0],
                                    generation=generation, step=step)


def _built_scan(snapshots=(), telemetry=()):
    return retention.ScanSucceeded(
        snapshots=tuple(snapshots), telemetry=tuple(telemetry),
        processed=len(snapshots) + len(telemetry),
        inspected=len(snapshots) + len(telemetry), excluded=0)


def _plan(scan, policy=None, now_ns=NOW):
    return retention.plan_retention(
        scan, policy=policy or retention.PRODUCTION_RETENTION_POLICY,
        now_ns=now_ns)


def _aged_snapshots(count, *, age_days):
    return [
        _entry(_snap_name(index, index), retention.SNAPSHOT_CLASS,
               NOW - _ns(age_days * DAY) - _ns(index), index, index)
        for index in range(count)
    ]


def test_rank_order_is_newest_first_by_time_then_sequence_then_name():
    same = NOW - _ns(60 * DAY)
    entries = [
        _entry(_snap_name(1, 1), retention.SNAPSHOT_CLASS, same, 1, 1),
        _entry(_snap_name(3, 9), retention.SNAPSHOT_CLASS, same, 3, 9),
        _entry(_snap_name(3, 4), retention.SNAPSHOT_CLASS, same, 3, 4),
        _entry(_snap_name(2, 2), retention.SNAPSHOT_CLASS, same - 1, 2, 2),
    ]
    ranked = [entry.basename for entry in retention.rank(entries)]
    assert ranked == [_snap_name(3, 9), _snap_name(3, 4),
                      _snap_name(1, 1), _snap_name(2, 2)]


def test_equal_times_break_deterministically_and_totally():
    same = NOW - _ns(60 * DAY)
    entries = [_entry("telemetry_20260101T00000%d.json" % index,
                      retention.TELEMETRY_CLASS, same) for index in (3, 1, 2)]
    ranked = [entry.basename for entry in retention.rank(entries)]
    assert ranked == sorted(entry.basename for entry in entries)
    assert retention.rank(entries) == retention.rank(list(reversed(entries)))


def test_telemetry_carries_the_no_sequence_sentinel(monkeypatch):
    _install(monkeypatch, _FakeScandir(_telemetry(1)))
    result = _scan()
    assert (result.telemetry[0].generation,
            result.telemetry[0].step) == retention.NO_SEQUENCE


def test_the_recovery_floor_protects_the_newest_entries_at_any_age():
    scan = _built_scan(snapshots=_aged_snapshots(600, age_days=400))
    plan = _plan(scan)
    acted = {action.basename for action in plan.actions}
    ranked = retention.rank(scan.snapshots)
    for protected in ranked[:512]:
        assert protected.basename not in acted
    assert plan.snapshot_eligible == 600 - 512


@pytest.mark.parametrize("count,expected", [(512, 0), (513, 1)])
def test_the_floor_boundary_and_boundary_plus_one(count, expected):
    scan = _built_scan(snapshots=_aged_snapshots(count, age_days=400))
    assert _plan(scan).snapshot_eligible == expected


def test_inside_the_horizon_and_under_the_ceiling_nothing_is_eligible():
    scan = _built_scan(snapshots=_aged_snapshots(2000, age_days=5))
    plan = _plan(scan)
    assert plan.snapshot_eligible == 0
    assert plan.actions == ()


def test_the_age_horizon_boundary_and_boundary_plus_one():
    policy = retention.PRODUCTION_RETENTION_POLICY
    horizon = policy.snapshot.max_age_seconds
    at = _built_scan(snapshots=[
        _entry(_snap_name(index, index), retention.SNAPSHOT_CLASS,
               NOW - _ns(horizon), index, index) for index in range(600)])
    beyond = _built_scan(snapshots=[
        _entry(_snap_name(index, index), retention.SNAPSHOT_CLASS,
               NOW - _ns(horizon) - 1, index, index) for index in range(600)])
    assert _plan(at).snapshot_eligible == 0, "age == horizon is not > horizon"
    assert _plan(beyond).snapshot_eligible == 600 - 512


def test_the_absolute_ceiling_fires_inside_the_age_horizon():
    """The genuine hard cap: if cadence accelerates, rank beyond the ceiling
    becomes eligible even though every entry is young."""
    scan = _built_scan(snapshots=_aged_snapshots(8_300, age_days=1))
    plan = _plan(scan)
    assert plan.snapshot_eligible == 8_300 - 8_192


@pytest.mark.parametrize("count,expected", [(8_192, 0), (8_193, 1)])
def test_ceiling_eligibility_begins_at_rank_8192(count, expected):
    scan = _built_scan(snapshots=_aged_snapshots(count, age_days=1))
    assert _plan(scan).snapshot_eligible == expected


def test_quiescence_excludes_a_possibly_in_flight_write():
    """The producer writes straight to its final path with no
    temporary-and-rename, so a young file may be mid-write."""
    policy = retention.PRODUCTION_RETENTION_POLICY
    fresh = _entry(_snap_name(1, 1), retention.SNAPSHOT_CLASS,
                   NOW - _ns(policy.quiescence_seconds - 1), 1, 1)
    old = _aged_snapshots(600, age_days=400)
    plan = _plan(_built_scan(snapshots=[fresh] + old))
    assert fresh.basename not in {action.basename for action in plan.actions}


def test_a_future_timestamp_is_ambiguous_and_never_actioned():
    future = _entry(_snap_name(1, 1), retention.SNAPSHOT_CLASS, NOW + 1, 1, 1)
    scan = _built_scan(snapshots=[future] + _aged_snapshots(600, age_days=400))
    plan = _plan(scan)
    assert plan.ambiguous == 1
    assert future.basename not in {action.basename for action in plan.actions}


def test_actions_are_capped_and_ordered_oldest_first():
    policy = retention.PRODUCTION_RETENTION_POLICY
    scan = _built_scan(snapshots=_aged_snapshots(2000, age_days=400))
    plan = _plan(scan)
    assert len(plan.actions) == policy.max_actions_per_pass
    ages = [action.mtime_ns for action in plan.actions]
    assert ages == sorted(ages), "actions are not oldest-first"


def test_the_two_classes_are_planned_independently():
    scan = _built_scan(
        snapshots=_aged_snapshots(600, age_days=400),
        telemetry=[_entry(_telem_name("2026010%dT000000" % (index % 10)),
                          retention.TELEMETRY_CLASS,
                          NOW - _ns(400 * DAY) - _ns(index))
                   for index in range(1100)])
    plan = _plan(scan)
    assert plan.snapshot_eligible == 88
    assert plan.telemetry_eligible == 1100 - 1024


def test_a_failed_scan_yields_no_actionable_plan():
    failed = retention.ScanFailed(
        reason=retention.RetentionFailureReason.ITERATION_FAILED,
        processed=5, inspected=2)
    plan = _plan(failed)
    assert plan.actions == ()
    assert plan.refused is retention.RetentionFailureReason.ITERATION_FAILED


def test_the_planner_is_pure_and_repeatable():
    scan = _built_scan(snapshots=_aged_snapshots(900, age_days=400))
    first = _plan(scan)
    second = _plan(scan)
    assert first == second
    assert _plan(scan, now_ns=NOW) == first


def test_plan_results_are_immutable():
    plan = _plan(_built_scan(snapshots=_aged_snapshots(600, age_days=400)))
    assert type(plan.actions) is tuple
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.ambiguous = 3


# ===========================================================================
# The snapshot reserve -- preflight-admissible only
# ===========================================================================

class _Admit:
    """A stand-in for `admit_snapshot`, counting preflights."""

    def __init__(self, admissible_indices):
        self.admissible = set(admissible_indices)
        self.calls = []

    def __call__(self, path, *, data_dir, policy=None):
        index = len(self.calls)
        self.calls.append(os.path.basename(os.fspath(path)))
        if index in self.admissible:
            return _NullContext()
        raise guard.SnapshotArchiveRejected("member_missing")


class _NullContext:
    def __enter__(self):
        return object()

    def __exit__(self, *exc):
        return False


def _reserve(scan, admit, policy=None):
    return retention.snapshot_reserve_available(
        scan, policy=policy or retention.PRODUCTION_RETENTION_POLICY,
        data_dir="data", admit=admit)


def test_three_preflight_admissible_within_eight_proceeds():
    admit = _Admit({0, 3, 7})
    assert _reserve(_built_scan(snapshots=_aged_snapshots(20, age_days=1)),
                    admit) is True
    assert len(admit.calls) <= 8


def test_two_preflight_admissible_within_eight_blocks_snapshot_actions():
    admit = _Admit({0, 5})
    assert _reserve(_built_scan(snapshots=_aged_snapshots(20, age_days=1)),
                    admit) is False
    assert len(admit.calls) == 8


def test_the_reserve_never_preflights_more_than_the_window():
    admit = _Admit(set())
    _reserve(_built_scan(snapshots=_aged_snapshots(5_000, age_days=1)), admit)
    assert len(admit.calls) == 8, "the bounded probe window was exceeded"


def test_the_reserve_stops_as_soon_as_it_is_satisfied():
    admit = _Admit({0, 1, 2})
    assert _reserve(_built_scan(snapshots=_aged_snapshots(20, age_days=1)),
                    admit) is True
    assert len(admit.calls) == 3


def test_the_reserve_probes_newest_first():
    admit = _Admit({0, 1, 2})
    scan = _built_scan(snapshots=_aged_snapshots(20, age_days=1))
    _reserve(scan, admit)
    assert admit.calls == [
        entry.basename for entry in retention.rank(scan.snapshots)[:3]]


def test_fewer_snapshots_than_required_blocks(monkeypatch):
    admit = _Admit({0, 1})
    assert _reserve(_built_scan(snapshots=_aged_snapshots(2, age_days=1)),
                    admit) is False


def test_a_reserve_shortfall_blocks_snapshots_but_not_telemetry():
    """Justified, not assumed: telemetry is never read by any resume path,
    and `/api/telemetry` consumes only the newest file, which the telemetry
    floor protects by three orders of magnitude. Coupling them would be
    superstition rather than safety."""
    scan = _built_scan(
        snapshots=_aged_snapshots(600, age_days=400),
        telemetry=[_entry(_telem_name("2026010%dT00000%d" % (i % 10, i % 10)),
                          retention.TELEMETRY_CLASS,
                          NOW - _ns(400 * DAY) - _ns(i))
                   for i in range(1100)])
    report = retention.run_pass(
        "data", policy=retention.PRODUCTION_RETENTION_POLICY,
        mode=retention.RetentionMode.PLAN, now_ns=NOW,
        scan=scan, admit=_Admit({0, 1}))
    assert report.snapshot_actions_blocked is True
    assert all(action.klass == retention.TELEMETRY_CLASS
               for action in report.planned_actions)
    assert report.planned_actions


def test_an_unexpected_reserve_exception_aborts_the_whole_pass():
    def _boom(path, *, data_dir, policy=None):
        raise RuntimeError("unexpected")

    report = retention.run_pass(
        "data", policy=retention.PRODUCTION_RETENTION_POLICY,
        mode=retention.RetentionMode.PLAN, now_ns=NOW,
        scan=_built_scan(snapshots=_aged_snapshots(600, age_days=400)),
        admit=_boom)
    assert report.refused is retention.RetentionFailureReason.RESERVE_CHECK_FAILED
    assert report.planned_actions == ()


def test_the_reserve_never_materializes_a_numpy_payload():
    source = Path(retention.__file__).read_text(encoding="utf-8")
    for banned in ("np.load", "numpy", "allow_pickle", "NpzFile"):
        assert banned not in source, banned


def test_the_module_says_preflight_admissible_not_loadable():
    source = Path(retention.__file__).read_text(encoding="utf-8").lower()
    assert "preflight-admissible" in source
    for overclaim in ("loadable recovery", "valid recovery archive",
                      "resumable recovery"):
        assert overclaim not in source, overclaim


# ===========================================================================
# Quarantine -- recoverable, journalled, never reaping
#
# Real files, in pytest's own tmp_path, in single digits. Policies are
# injected small so a floor of 512 does not require 513 real fixtures.
# ===========================================================================

def _write(directory, name, *, age_days, size=64):
    path = Path(directory) / name
    path.write_bytes(b"\x00" * size)
    stamp = int((NOW - _ns(age_days * DAY)) // 1_000_000_000)
    os.utime(path, ns=(stamp * 1_000_000_000, stamp * 1_000_000_000))
    return path


def _populate(directory, snapshots=3, telemetry=0, age_days=400):
    made = []
    for index in range(snapshots):
        made.append(_write(directory, _snap_name(index, index),
                           age_days=age_days + index))
    for index in range(telemetry):
        made.append(_write(directory, _telem_name("2026010%dT00000%d"
                                                  % (index % 10, index % 10)),
                           age_days=age_days + index))
    return made


def _quarantine_policy(**kwargs):
    base = dict(entries=1000, combined=1000, snap=1000, telem=1000,
                ceiling=8_192, floor=1)
    base.update(kwargs)
    return _tiny(**base)


def _injected_mover(source, destination):
    """The movement abstraction, injected so CI exercises the lifecycle.

    On Windows this IS the production path: `os.rename` there is no-replace at
    the operating-system level. On POSIX it uses `os.link` followed by
    `os.unlink`, which is genuinely no-replace -- `link` fails with EEXIST
    rather than clobbering -- and preserves the inode, so identity
    verification is exercised exactly as it would be on the real target.

    It is a TEST DOUBLE. `platform_move`, the production primitive, still
    refuses on POSIX rather than shipping a substitute, and a separate control
    proves it.
    """
    if os.name == "nt":
        os.rename(source, destination)
        return
    os.link(source, destination)
    os.unlink(source)


def _run(directory, mode=None, policy=None, pass_id="p20260101T000000",
         admit=None, now_ns=NOW, mover=None):
    return retention.run_pass(
        directory,
        policy=policy or _quarantine_policy(),
        mode=mode or retention.RetentionMode.QUARANTINE,
        now_ns=now_ns, pass_id=pass_id,
        admit=admit if admit is not None else _Admit({0, 1, 2}),
        mover=mover if mover is not None else _injected_mover)


def _quarantine_root(directory):
    return Path(directory) / retention.QUARANTINE_DIRNAME


def test_plan_mode_mutates_nothing(tmp_path):
    made = _populate(tmp_path, snapshots=4)
    before = sorted(p.name for p in tmp_path.iterdir())
    report = _run(tmp_path, mode=retention.RetentionMode.PLAN)
    assert report.planned_actions
    assert report.moved == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert not _quarantine_root(tmp_path).exists()
    assert all(path.exists() for path in made)


def test_quarantine_moves_only_the_planned_entries(tmp_path):
    _populate(tmp_path, snapshots=4)
    keep = _write(tmp_path, _snap_name(900, 900), age_days=1)
    curated = _write(tmp_path, "medusa_live.html", age_days=900)
    report = _run(tmp_path)
    assert report.moved == report.planned_actions_count
    assert keep.exists(), "a young snapshot was moved"
    assert curated.exists(), "a curated tracked file was moved"
    moved = sorted(p.name for p in
                   (_quarantine_root(tmp_path) / "p20260101T000000").iterdir()
                   if p.name != retention.MANIFEST_NAME)
    assert moved == sorted(action.basename
                           for action in report.planned_actions)


def test_at_most_one_bounded_batch_per_pass(tmp_path):
    _populate(tmp_path, snapshots=6)
    policy = _quarantine_policy()
    policy = dataclasses.replace(policy, max_actions_per_pass=2)
    report = _run(tmp_path, policy=policy)
    assert report.moved == 2
    assert len(list((_quarantine_root(tmp_path) / "p20260101T000000").iterdir())
               ) == 3  # two moved files plus the manifest


def test_the_pass_directory_is_created_exclusively(tmp_path):
    _populate(tmp_path, snapshots=3)
    root = _quarantine_root(tmp_path)
    (root / "p20260101T000000").mkdir(parents=True)
    report = _run(tmp_path)
    assert report.refused is retention.RetentionFailureReason.PASS_DIRECTORY_COLLISION
    assert report.moved == 0


def test_no_exist_ok_or_makedirs_shortcut_is_used():
    source = Path(retention.__file__).read_text(encoding="utf-8")
    assert "exist_ok" not in source
    assert "makedirs" not in source


def test_a_non_directory_quarantine_root_is_refused(tmp_path):
    _populate(tmp_path, snapshots=3)
    _quarantine_root(tmp_path).write_bytes(b"not a directory")
    report = _run(tmp_path)
    assert report.refused is retention.RetentionFailureReason.QUARANTINE_ROOT_INVALID
    assert report.moved == 0


def test_the_manifest_is_created_exclusively_and_verified_by_handle(tmp_path):
    _populate(tmp_path, snapshots=3)
    root = _quarantine_root(tmp_path)
    (root / "p20260101T000000").mkdir(parents=True)
    (root / "p20260101T000000" / retention.MANIFEST_NAME).write_text("x")
    report = _run(tmp_path)
    assert report.moved == 0
    assert report.refused in (
        retention.RetentionFailureReason.PASS_DIRECTORY_COLLISION,
        retention.RetentionFailureReason.MANIFEST_CREATE_FAILED)


def test_the_manifest_schema_is_closed_and_bounded(tmp_path):
    _populate(tmp_path, snapshots=3)
    _run(tmp_path)
    manifest = (_quarantine_root(tmp_path) / "p20260101T000000"
                / retention.MANIFEST_NAME)
    lines = manifest.read_text(encoding="utf-8").splitlines(keepends=True)
    assert lines
    for line in lines:
        assert len(line.encode("utf-8")) <= retention.MAX_MANIFEST_RECORD_BYTES
        record = json.loads(line)
        assert set(record) == {"basename", "class", "size", "mtime_ns",
                               "quarantined_at"}
        assert isinstance(record["basename"], str)
        assert isinstance(record["size"], int)
        assert isinstance(record["mtime_ns"], int)


def test_the_manifest_records_quarantine_time_not_the_files_mtime(tmp_path):
    """A rename preserves mtime, so the moved file cannot say when quarantine
    began. That is why this pass is journalled rather than stateless."""
    _populate(tmp_path, snapshots=2)
    _run(tmp_path)
    manifest = (_quarantine_root(tmp_path) / "p20260101T000000"
                / retention.MANIFEST_NAME)
    for line in manifest.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        assert record["quarantined_at"] != record["mtime_ns"]


def test_directory_contents_are_restoration_ground_truth(tmp_path):
    """A crash between the rename and the manifest append leaves a file that
    is still fully restorable by name; only its recorded metadata is lost."""
    _populate(tmp_path, snapshots=3)
    _run(tmp_path)
    pass_dir = _quarantine_root(tmp_path) / "p20260101T000000"
    manifest = pass_dir / retention.MANIFEST_NAME
    lines = manifest.read_text(encoding="utf-8").splitlines()
    manifest.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    survey = retention.survey_quarantine(pass_dir, policy=_quarantine_policy())
    assert survey.unmanifested == 1
    assert survey.present == len(lines)


def test_a_truncated_final_record_is_unresolved_and_never_repaired(tmp_path):
    _populate(tmp_path, snapshots=3)
    _run(tmp_path)
    pass_dir = _quarantine_root(tmp_path) / "p20260101T000000"
    manifest = pass_dir / retention.MANIFEST_NAME
    original = manifest.read_bytes()
    manifest.write_bytes(original[:-12])
    survey = retention.survey_quarantine(pass_dir, policy=_quarantine_policy())
    assert survey.malformed_records >= 1
    assert manifest.read_bytes() == original[:-12], "the manifest was repaired"


def test_no_restoration_or_reaping_command_exists(tmp_path):
    _populate(tmp_path, snapshots=3)
    _run(tmp_path)
    pass_dir = _quarantine_root(tmp_path) / "p20260101T000000"
    moved = [p for p in pass_dir.iterdir() if p.name != retention.MANIFEST_NAME]
    assert moved
    for _ in range(3):
        _run(tmp_path, pass_id="p20260101T00000%d" % _)
    assert all(path.exists() for path in moved), "a quarantined file was reaped"


def test_the_quarantine_directory_is_never_a_retention_candidate(tmp_path):
    _populate(tmp_path, snapshots=3)
    _run(tmp_path)
    report = _run(tmp_path, pass_id="p20260101T000001")
    assert retention.QUARANTINE_DIRNAME not in [
        action.basename for action in report.planned_actions]


# -- identity, before and after the rename -----------------------------------

def test_a_full_stable_identity_is_required_before_moving(tmp_path,
                                                          monkeypatch):
    """Windows `DirEntry.stat()` reports dev=0/ino=0 -- measured on the
    deployed platform -- so identity is established at the revalidation
    `lstat`. If it is still unavailable there, QUARANTINE fails closed."""
    _populate(tmp_path, snapshots=3)
    real_lstat = os.lstat

    def _identityless(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        return _Stat(mode=info.st_mode, size=info.st_size,
                     mtime_ns=info.st_mtime_ns, nlink=1, dev=0, ino=0)

    monkeypatch.setattr(retention.os, "lstat", _identityless)
    report = _run(tmp_path)
    assert report.refused is retention.RetentionFailureReason.IDENTITY_UNAVAILABLE
    assert report.moved == 0
    pass_dir = _quarantine_root(tmp_path) / "p20260101T000000"
    if pass_dir.exists():
        assert not [entry for entry in pass_dir.iterdir()
                    if entry.name != retention.MANIFEST_NAME]


def test_size_and_time_alone_are_not_identity():
    source = Path(retention.__file__).read_text(encoding="utf-8")
    assert "st_dev" in source and "st_ino" in source


def test_a_fingerprint_change_between_plan_and_act_skips_the_entry(tmp_path,
                                                                   monkeypatch):
    _populate(tmp_path, snapshots=3)
    # The OLDEST entry: the newest is inside the recovery floor and is never
    # actioned, so tampering with it would prove nothing.
    victim = sorted(path.name for path in tmp_path.iterdir())[-1]
    real_lstat = os.lstat
    tampered = {"done": False}

    def _tamper(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if os.path.basename(os.fspath(path)) == victim and not tampered["done"]:
            tampered["done"] = True
            return _Stat(mode=info.st_mode, size=info.st_size + 1,
                         mtime_ns=info.st_mtime_ns, nlink=1,
                         dev=info.st_dev, ino=info.st_ino)
        return info

    monkeypatch.setattr(retention.os, "lstat", _tamper)
    report = _run(tmp_path)
    assert report.skipped >= 1
    assert (tmp_path / victim).exists()


def test_a_sharing_violation_is_skipped_and_counted(tmp_path):
    """An open reader handle makes the rename fail on Windows. That is a
    safety property, not a fault: the pass skips and carries on."""
    _populate(tmp_path, snapshots=3)
    blocked = {"n": 0}

    def _blocking(source, destination):
        if blocked["n"] == 0:
            blocked["n"] += 1
            raise PermissionError(errno.EACCES, "sharing violation")
        return _injected_mover(source, destination)

    report = _run(tmp_path, mover=_blocking)
    assert report.skipped >= 1
    assert report.moved >= 1
    assert report.halted is False


def test_a_post_move_identity_mismatch_halts_and_preserves(tmp_path,
                                                           monkeypatch):
    """The rename is not swap-proof. A swap is DETECTABLE afterwards, and the
    correct response is to stop everything and preserve the moved object for
    audit -- never a blind automatic restore."""
    _populate(tmp_path, snapshots=4)
    real_lstat = os.lstat
    seen = {"post": 0}

    def _mismatch(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if retention.QUARANTINE_DIRNAME in os.fspath(path) and \
                os.path.basename(os.fspath(path)).startswith("v070_gen"):
            seen["post"] += 1
            return _Stat(mode=info.st_mode, size=info.st_size,
                         mtime_ns=info.st_mtime_ns, nlink=1,
                         dev=info.st_dev, ino=info.st_ino + 1)
        return info

    monkeypatch.setattr(retention.os, "lstat", _mismatch)
    report = _run(tmp_path)
    assert report.halted is True
    assert report.refused is (
        retention.RetentionFailureReason.IDENTITY_MISMATCH_AFTER_MOVE)
    assert report.moved <= 1
    pass_dir = _quarantine_root(tmp_path) / "p20260101T000000"
    preserved = [p for p in pass_dir.iterdir()
                 if p.name != retention.MANIFEST_NAME]
    assert len(preserved) == 1, "the moved object was not preserved"


def test_no_blind_automatic_restore_is_attempted():
    source = Path(retention.__file__).read_text(encoding="utf-8")
    assert "rename(destination, source)" not in source
    assert "rename(dst, src)" not in source


# ===========================================================================
# Ambiguity, mode equivalence, the lock, and disclosure
# ===========================================================================

def test_quarantine_aborts_entirely_on_an_ambiguous_timestamp(tmp_path):
    """A future modification time undermines the ordering the whole policy
    rests on, so QUARANTINE refuses to act at all rather than acting around
    it."""
    _populate(tmp_path, snapshots=3)
    future = _write(tmp_path, _snap_name(800, 800), age_days=0)
    os.utime(future, ns=(NOW + _ns(3600), NOW + _ns(3600)))
    report = _run(tmp_path)
    assert report.refused is retention.RetentionFailureReason.TIMESTAMP_AMBIGUOUS
    assert report.moved == 0
    assert future.exists()


def test_plan_mode_reports_an_ambiguous_timestamp_without_refusing(tmp_path):
    _populate(tmp_path, snapshots=3)
    future = _write(tmp_path, _snap_name(800, 800), age_days=0)
    os.utime(future, ns=(NOW + _ns(3600), NOW + _ns(3600)))
    report = _run(tmp_path, mode=retention.RetentionMode.PLAN)
    assert report.ambiguous == 1
    assert future.name not in [a.basename for a in report.planned_actions]


def test_both_modes_use_the_same_pure_planner(tmp_path):
    """Not "the same plan is executed" -- the same PLANNER over identical
    input state. A live pass always re-scans and re-plans."""
    _populate(tmp_path, snapshots=5)
    scan = retention.scan_retention_candidates(
        tmp_path, policy=_quarantine_policy())
    planned = retention.plan_retention(scan, policy=_quarantine_policy(),
                                       now_ns=NOW)
    dry = _run(tmp_path, mode=retention.RetentionMode.PLAN)
    assert [a.basename for a in dry.planned_actions] == [
        a.basename for a in planned.actions]

    live = _run(tmp_path, mode=retention.RetentionMode.QUARANTINE)
    assert [a.basename for a in live.planned_actions] == [
        a.basename for a in planned.actions]


def test_quarantine_freshly_scans_rather_than_replaying(tmp_path):
    _populate(tmp_path, snapshots=4)
    dry = _run(tmp_path, mode=retention.RetentionMode.PLAN)
    assert dry.planned_actions
    for action in dry.planned_actions:
        (tmp_path / action.basename).unlink()
    report = _run(tmp_path, mode=retention.RetentionMode.QUARANTINE)
    assert report.moved == 0, "a stale dry-run plan was replayed"


def test_run_pass_refuses_a_serialized_plan():
    import inspect
    parameters = inspect.signature(retention.run_pass).parameters
    assert "plan" not in parameters
    assert "actions" not in parameters
    assert "serialized" not in parameters


# -- the single-instance lock ------------------------------------------------

def test_the_lock_is_held_by_the_operating_system(tmp_path):
    path = tmp_path / "retention.lock"
    with retention.single_instance_lock(path) as first:
        assert first is True
        with retention.single_instance_lock(path) as second:
            assert second is False, "a second holder acquired the same lock"


def test_the_lock_is_released_when_its_handle_closes(tmp_path):
    """Release is by handle, which the operating system performs on process
    exit -- including an abnormal one. A stale sentinel file must never wedge
    maintenance permanently."""
    path = tmp_path / "retention.lock"
    with retention.single_instance_lock(path) as acquired:
        assert acquired is True
    assert path.exists(), "the lock file itself is not the lock"
    with retention.single_instance_lock(path) as reacquired:
        assert reacquired is True


def test_a_pre_existing_lock_file_alone_does_not_block(tmp_path):
    path = tmp_path / "retention.lock"
    path.write_bytes(b"")
    with retention.single_instance_lock(path) as acquired:
        assert acquired is True


def test_the_lock_uses_a_real_locking_primitive():
    source = Path(retention.__file__).read_text(encoding="utf-8")
    assert ("msvcrt" in source and "locking" in source) or "flock" in source
    assert "if os.path.exists(lock" not in source


# -- diagnostics carry no locator --------------------------------------------

def test_the_report_is_aggregate_only_and_path_free(tmp_path):
    _populate(tmp_path, snapshots=3, telemetry=2)
    report = _run(tmp_path, mode=retention.RetentionMode.PLAN)
    for field in dataclasses.fields(report):
        value = getattr(report, field.name)
        if field.name == "planned_actions":
            continue
        assert not isinstance(value, (bytes, Path)), field.name
        if isinstance(value, str):
            assert value in {mode.value for mode in retention.RetentionMode}


def test_the_emitted_diagnostic_line_carries_no_locator(tmp_path, capsys):
    _populate(tmp_path, snapshots=3)
    report = _run(tmp_path, mode=retention.RetentionMode.PLAN)
    line = retention.format_report(report)
    for leak in ("v070_gen", ".npz", "telemetry_", str(tmp_path), "/", "\\",
                 "Traceback", "Errno"):
        assert leak not in line, leak


def test_the_manifest_is_state_not_a_diagnostic(tmp_path, capsys):
    """The manifest necessarily contains basenames, so it lives inside the
    quarantine directory and is never emitted. Emitted diagnostics stay
    strictly path-free."""
    _populate(tmp_path, snapshots=3)
    _run(tmp_path)
    printed = capsys.readouterr()
    assert "v070_gen" not in printed.out and "v070_gen" not in printed.err


def test_a_refusal_reason_is_a_fixed_closed_code():
    values = {reason.value for reason in retention.RetentionFailureReason}
    for value in values:
        assert re.fullmatch(r"[a-z_]+", value), value


# -- optimized mode and structural hygiene -----------------------------------

def test_the_module_uses_no_assert_statements():
    """Nothing may depend on `__debug__`: `python -O` must behave identically."""
    import ast as _ast
    tree = _ast.parse(Path(retention.__file__).read_text(encoding="utf-8"))
    assert not [node for node in _ast.walk(tree)
                if isinstance(node, _ast.Assert)]


def test_the_module_imports_no_service_or_scheduler():
    import ast as _ast
    tree = _ast.parse(Path(retention.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in _ast.walk(tree) if isinstance(node, _ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in _ast.walk(tree)
        if isinstance(node, _ast.ImportFrom) and node.module
    }
    for banned in ("flask", "websockets", "sched", "subprocess", "numpy"):
        assert banned not in imported, banned


def test_no_persistent_operational_location_is_hard_coded():
    source = Path(retention.__file__).read_text(encoding="utf-8")
    for leak in ("C:\\", "OneDrive", "Area 51", "kevin", "/srv/", "/mnt/"):
        assert leak not in source, leak


def test_the_guard_contract_is_imported_not_reimplemented():
    source = Path(retention.__file__).read_text(encoding="utf-8")
    assert "snapshot_archive_guard" in source
    assert "def admit_snapshot" not in source
    assert "PRODUCTION_DISCOVERY_POLICY" in source


def test_the_merged_discovery_and_admission_behaviour_is_untouched():
    """This tranche adds two files and modifies none, so PR #472's guarantees
    hold by construction. Pinned here so a later edit cannot quietly change
    that."""
    assert guard.PRODUCTION_DISCOVERY_POLICY.max_directory_entries == 196_608
    assert guard.PRODUCTION_DISCOVERY_POLICY.max_candidates == 65_536
    assert guard.PRODUCTION_POLICY.selection_depth == 8
    assert guard.DISCOVERY_CACHE_TTL_SECONDS == 10.0


# ===========================================================================
# Audit corrections -- six defects the green checks did not catch
# ===========================================================================

# -- 1. PLAN must not mutate the directory it is measuring -------------------

def test_plan_via_the_cli_leaves_the_target_directory_unchanged(tmp_path,
                                                                capsys):
    """The default lock used to be created INSIDE the target, so an ordinary
    dry run changed the very entry count it was reporting -- and would have
    invalidated a zero-mutation acceptance run."""
    _populate(tmp_path, snapshots=3)
    before = sorted(path.name for path in tmp_path.iterdir())
    retention.main([str(tmp_path)])
    capsys.readouterr()
    assert sorted(path.name for path in tmp_path.iterdir()) == before


def test_the_default_lock_lives_outside_the_target(tmp_path):
    lock = Path(os.fspath(retention.default_lock_path(tmp_path)))
    assert lock.parent != Path(os.fspath(tmp_path))
    assert Path(os.fspath(tmp_path)) not in lock.parents


def test_the_default_lock_name_is_opaque_and_carries_no_locator(tmp_path):
    named = tmp_path / "medusa-operational-data"
    named.mkdir()
    lock = Path(os.fspath(retention.default_lock_path(named)))
    assert named.name not in lock.name
    assert re.fullmatch(r"[A-Za-z0-9._-]+", lock.name), lock.name


def test_the_same_normalized_target_maps_to_one_lock(tmp_path):
    first = retention.default_lock_path(tmp_path)
    second = retention.default_lock_path(Path(os.fspath(tmp_path)) / ".")
    assert Path(os.fspath(first)) == Path(os.fspath(second))


def test_different_targets_do_not_share_a_lock(tmp_path):
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()
    assert (Path(os.fspath(retention.default_lock_path(one)))
            != Path(os.fspath(retention.default_lock_path(two))))


def test_an_explicit_lock_override_is_preserved(tmp_path, capsys):
    _populate(tmp_path, snapshots=2)
    override = tmp_path.parent / "explicit.lock"
    retention.main([str(tmp_path), "--lock", str(override)])
    capsys.readouterr()
    assert override.exists()


def test_a_lock_open_failure_is_a_fixed_code_without_disclosure(tmp_path,
                                                                monkeypatch,
                                                                capsys):
    def _denied(*args, **kwargs):
        raise PermissionError(errno.EACCES, "permission denied")

    monkeypatch.setattr(retention.os, "open", _denied)
    status = retention.main([str(tmp_path)])
    printed = capsys.readouterr()
    assert status == 1
    assert retention.RetentionFailureReason.LOCK_UNAVAILABLE.value in printed.out
    for leak in ("Traceback", "permission denied", str(tmp_path), "Errno"):
        assert leak not in printed.out and leak not in printed.err


# -- 2. a pass identifier must never function as a path ----------------------

_HOSTILE_PASS_IDS = [
    "..", ".", "", "../escape", "p20260101T000000/..",
    "p20260101T000000\\..", "sub/p20260101T000000",
    "p20260101T000000\n", "p20260101T000000\r\n", " p20260101T000000",
    "p20260101T000000 ", "xp20260101T000000", "p20260101T000000x",
    "p2026010T000000", "p20260101T00000", "p20260101t000000",
    "P20260101T000000", "p2026٠١٠١T000000",
    os.path.join(os.sep, "abs", "p20260101T000000"),
]


@pytest.mark.parametrize("pass_id", _HOSTILE_PASS_IDS)
def test_a_malformed_pass_id_refuses_with_zero_mutation(tmp_path, pass_id):
    """An absolute value or a `..` component joined beneath the quarantine
    root escapes it entirely. The identifier is validated by full match before
    anything at all is created."""
    _populate(tmp_path, snapshots=3)
    before = sorted(path.name for path in tmp_path.iterdir())
    report = _run(tmp_path, pass_id=pass_id)
    assert report.refused is retention.RetentionFailureReason.PASS_ID_INVALID
    assert report.moved == 0
    assert sorted(path.name for path in tmp_path.iterdir()) == before
    assert not _quarantine_root(tmp_path).exists()


@pytest.mark.parametrize("pass_id", [123, b"p20260101T000000", ["p"], 1.5])
def test_a_wrongly_typed_pass_id_refuses(tmp_path, pass_id):
    _populate(tmp_path, snapshots=3)
    report = _run(tmp_path, pass_id=pass_id)
    assert report.refused is retention.RetentionFailureReason.PASS_ID_INVALID
    assert report.moved == 0


def test_the_generated_pass_id_satisfies_its_own_grammar():
    assert re.fullmatch(r"p[0-9]{8}T[0-9]{6}", retention._default_pass_id())


# -- 3. the allowlists must be truly anchored --------------------------------

_TRAILING = [
    "v070_gen000001_step000001_20260101T000000.npz\n",
    "v070_gen000001_step000001_20260101T000000.npz\r\n",
    "v070_gen000001_step000001_20260101T000000.npz\r",
    "telemetry_20260101T000000.json\n",
    "telemetry_20260101T000000.json\r\n",
    "telemetry_20260101T000000.json\r",
    "\nv070_gen000001_step000001_20260101T000000.npz",
    "\ntelemetry_20260101T000000.json",
]


@pytest.mark.parametrize("name", _TRAILING,
                         ids=[repr(name) for name in _TRAILING])
def test_a_name_with_surrounding_material_is_not_a_producer_name(name):
    """Python's `$` matches immediately before a trailing newline, so `match`
    with `$` accepted `...npz\\n`. Full matching is what actually anchors."""
    assert retention.classify_name(name) is None


@pytest.mark.parametrize("name", _TRAILING[:6],
                         ids=[repr(name) for name in _TRAILING[:6]])
def test_a_name_with_a_trailing_newline_receives_no_metadata_read(monkeypatch,
                                                                  name):
    fake = _install(monkeypatch, _FakeScandir([_Entry(name)]))
    result = _scan()
    assert isinstance(result, retention.ScanSucceeded)
    assert result.snapshots == () and result.telemetry == ()
    assert fake.statted == []


# -- 4. the plan must carry the full stable identity -------------------------

def test_an_inode_replacement_with_identical_size_and_time_is_detected(
        tmp_path, monkeypatch):
    """Size and time alone are not identity. A replacement that preserves both
    evaded detection entirely, because `(st_dev, st_ino)` was first read at
    revalidation and so had nothing from the scan to disagree with."""
    _populate(tmp_path, snapshots=3)
    victim = sorted(path.name for path in tmp_path.iterdir())[-1]
    real_scan = retention.scan_retention_candidates

    def _scan_then_replace(directory, *, policy):
        observed = real_scan(directory, policy=policy)
        path = Path(os.fspath(directory)) / victim
        info = os.lstat(path)
        payload = path.read_bytes()
        path.unlink()
        path.write_bytes(payload)  # same size
        os.utime(path, ns=(info.st_mtime_ns, info.st_mtime_ns))  # same time
        return observed

    monkeypatch.setattr(retention, "scan_retention_candidates",
                        _scan_then_replace)
    report = _run(tmp_path)
    assert (tmp_path / victim).exists(), "a replaced object was moved"
    assert report.skipped >= 1


def test_the_scan_captures_the_full_stable_identity(monkeypatch, tmp_path):
    _populate(tmp_path, snapshots=2)
    result = retention.scan_retention_candidates(
        tmp_path, policy=_quarantine_policy())
    for entry in result.snapshots:
        assert entry.dev != 0 and entry.ino != 0
        real = os.lstat(tmp_path / entry.basename)
        assert (entry.dev, entry.ino) == (real.st_dev, real.st_ino)


def test_a_planned_action_carries_the_identity_it_was_planned_on(tmp_path):
    _populate(tmp_path, snapshots=3)
    report = _run(tmp_path, mode=retention.RetentionMode.PLAN)
    for action in report.planned_actions:
        real = os.lstat(tmp_path / action.basename)
        assert (action.dev, action.ino) == (real.st_dev, real.st_ino)


def test_quarantine_refuses_before_creating_anything_without_identity(
        tmp_path, monkeypatch):
    _populate(tmp_path, snapshots=3)
    real_lstat = os.lstat

    def _identityless(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        return _Stat(mode=info.st_mode, size=info.st_size,
                     mtime_ns=info.st_mtime_ns, nlink=1, dev=0, ino=0)

    monkeypatch.setattr(retention.os, "lstat", _identityless)
    report = _run(tmp_path)
    assert report.refused is retention.RetentionFailureReason.IDENTITY_UNAVAILABLE
    assert report.moved == 0
    assert not _quarantine_root(tmp_path).exists()


# -- 5. journal writing and reconciliation must be bounded and strict --------

def _pass_dir(tmp_path, records=(), extra_files=(), name="p20260101T000000"):
    """Build a quarantine pass directory by hand, for survey controls."""
    root = tmp_path / retention.QUARANTINE_DIRNAME
    root.mkdir()
    directory = root / name
    directory.mkdir()
    for filename in extra_files:
        (directory / filename).write_bytes(b"\x00" * 8)
    if records:
        payload = b"".join(records)
        (directory / retention.MANIFEST_NAME).write_bytes(payload)
    return directory


def _record_bytes(name, klass=None, **overrides):
    body = {
        "basename": name,
        "class": klass or retention.SNAPSHOT_CLASS,
        "size": 8,
        "mtime_ns": 1,
        "quarantined_at": 2,
    }
    body.update(overrides)
    return (json.dumps(body, sort_keys=True, separators=(",", ":"))
            + "\n").encode("utf-8")


def _survey(directory, policy=None):
    return retention.survey_quarantine(
        directory, policy=policy or _quarantine_policy())


def test_the_survey_validates_its_directory(tmp_path):
    root = tmp_path / retention.QUARANTINE_DIRNAME
    root.mkdir()
    impostor = root / "p20260101T000000"
    impostor.write_bytes(b"not a directory")
    survey = _survey(impostor)
    assert survey.refused is retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID


def test_the_survey_bounds_the_number_of_entries(tmp_path):
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, extra_files=[
        _snap_name(index, index) for index in range(6)])
    policy = dataclasses.replace(_quarantine_policy(), max_actions_per_pass=2)
    survey = _survey(directory, policy)
    assert survey.refused is retention.RetentionFailureReason.SURVEY_LIMIT_EXCEEDED
    assert name is not None


def test_the_survey_bounds_the_manifest_size(tmp_path):
    directory = _pass_dir(
        tmp_path,
        records=[_record_bytes(_snap_name(index, index)) for index in range(6)],
        extra_files=[_snap_name(index, index) for index in range(6)])
    policy = dataclasses.replace(_quarantine_policy(), max_actions_per_pass=1)
    survey = _survey(directory, policy)
    assert survey.refused is retention.RetentionFailureReason.SURVEY_LIMIT_EXCEEDED


def test_the_survey_rejects_an_extra_key(tmp_path):
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path,
                          records=[_record_bytes(name, extra="unexpected")],
                          extra_files=[name])
    survey = _survey(directory)
    assert survey.malformed_records == 1
    assert survey.unmanifested == 1


@pytest.mark.parametrize("overrides", [
    {"size": True}, {"mtime_ns": False}, {"quarantined_at": "2"},
    {"size": 1.5}, {"basename": 7}, {"class": 3},
], ids=["size_true", "mtime_false", "quarantined_str", "size_float",
        "basename_int", "class_int"])
def test_the_survey_enforces_exact_types(tmp_path, overrides):
    """`True` is an `int` to Python; a schema that accepted it would not be
    the closed schema this claims to be."""
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, records=[_record_bytes(name, **overrides)],
                          extra_files=[name])
    survey = _survey(directory)
    assert survey.malformed_records == 1


def test_the_survey_validates_class_and_basename_consistency(tmp_path):
    name = _snap_name(1, 1)
    directory = _pass_dir(
        tmp_path,
        records=[_record_bytes(name, klass=retention.TELEMETRY_CLASS)],
        extra_files=[name])
    survey = _survey(directory)
    assert survey.malformed_records == 1


def test_the_survey_counts_duplicate_records(tmp_path):
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path,
                          records=[_record_bytes(name), _record_bytes(name)],
                          extra_files=[name])
    survey = _survey(directory)
    assert survey.duplicates == 1


def test_the_survey_counts_invalid_utf8(tmp_path):
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path,
                          records=[b"\xff\xfe not utf-8\n"],
                          extra_files=[name])
    survey = _survey(directory)
    assert survey.malformed_records >= 1
    assert survey.unmanifested == 1


def test_the_survey_counts_an_overlong_record(tmp_path):
    name = _snap_name(1, 1)
    padded = _record_bytes(name, basename="v" * 600)
    directory = _pass_dir(tmp_path, records=[padded], extra_files=[name])
    survey = _survey(directory)
    assert survey.malformed_records >= 1


def test_the_survey_never_repairs_or_removes_anything(tmp_path):
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, records=[_record_bytes(name)[:-4]],
                          extra_files=[name])
    manifest = directory / retention.MANIFEST_NAME
    before = manifest.read_bytes()
    survey = _survey(directory)
    assert survey.malformed_records >= 1
    assert manifest.read_bytes() == before
    assert (directory / name).exists()


def test_the_survey_emits_no_name(tmp_path, capsys):
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, records=[_record_bytes(name)],
                          extra_files=[name])
    survey = _survey(directory)
    printed = capsys.readouterr()
    assert "v070_gen" not in printed.out and "v070_gen" not in printed.err
    for field in dataclasses.fields(survey):
        value = getattr(survey, field.name)
        assert not isinstance(value, (str, bytes, Path)), field.name


def test_a_short_journal_write_is_a_fixed_failure(tmp_path, monkeypatch):
    """`os.write` may write fewer bytes than asked. A half-written record
    would be a silently corrupt journal, so the write loops and a write that
    cannot complete is a fixed refusal."""
    _populate(tmp_path, snapshots=3)
    real_write = os.write
    calls = {"n": 0}

    def _short(fd, data):
        # Targeted at journal records only: patching every `os.write` would
        # also catch whatever the runner uses for its own output.
        if data.startswith(b'{"basename"') and calls["n"] == 0:
            calls["n"] += 1
            return 0  # a zero-length write that will never progress
        return real_write(fd, data)

    monkeypatch.setattr(retention.os, "write", _short)
    report = _run(tmp_path)
    assert report.refused is retention.RetentionFailureReason.MANIFEST_RECORD_FAILED
    assert report.halted is True
    assert report.unmanifested >= 1


def test_the_journal_write_loops_until_complete(tmp_path, monkeypatch):
    _populate(tmp_path, snapshots=3)
    real_write = os.write
    partial = {"n": 0}

    def _partial(fd, data):
        if data.startswith(b'{"basename"') and len(data) > 1:
            partial["n"] += 1
            if partial["n"] % 2 == 1:
                return real_write(fd, data[:1])
        return real_write(fd, data)

    monkeypatch.setattr(retention.os, "write", _partial)
    report = _run(tmp_path)
    assert report.refused is None
    manifest = (_quarantine_root(tmp_path) / "p20260101T000000"
                / retention.MANIFEST_NAME)
    for line in manifest.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        assert set(record) == {"basename", "class", "size", "mtime_ns",
                               "quarantined_at"}


def test_a_manifest_validation_failure_closes_its_descriptor(tmp_path,
                                                             monkeypatch):
    _populate(tmp_path, snapshots=3)
    real_fstat = os.fstat

    def _not_regular(fd):
        info = real_fstat(fd)
        return _Stat(mode=stat_module.S_IFIFO | 0o600, size=0, mtime_ns=0,
                     nlink=1, dev=info.st_dev, ino=info.st_ino)

    monkeypatch.setattr(retention.os, "fstat", _not_regular)
    closed = []
    real_close = os.close
    monkeypatch.setattr(retention.os, "close",
                        lambda fd: (closed.append(fd), real_close(fd))[1])
    report = _run(tmp_path)
    assert report.refused is retention.RetentionFailureReason.MANIFEST_CREATE_FAILED
    assert closed, "the manifest descriptor was leaked on the failure path"


# -- 6. the destination must never be silently replaced ----------------------

def test_the_platform_move_refuses_an_existing_destination(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.write_bytes(b"source")
    destination.write_bytes(b"destination")
    with pytest.raises(OSError):
        retention.platform_move(source, destination)
    assert destination.read_bytes() == b"destination"


def test_a_plain_rename_would_silently_replace_on_posix(tmp_path):
    """Non-vacuity for the control above: this is exactly the hazard, and it
    is why a plain `os.rename` is not the movement primitive here."""
    source = tmp_path / "plain_source"
    destination = tmp_path / "plain_destination"
    source.write_bytes(b"source")
    destination.write_bytes(b"destination")
    if os.name == "nt":
        with pytest.raises(OSError):
            os.rename(source, destination)
        assert destination.read_bytes() == b"destination"
    else:
        os.rename(source, destination)
        assert destination.read_bytes() == b"source"


def test_real_quarantine_is_windows_only(tmp_path):
    """Stage one provides a proven no-replace move on Windows, which is the
    operational target. Elsewhere it refuses rather than pretending that
    check-then-rename is atomic."""
    _populate(tmp_path, snapshots=3)
    report = retention.run_pass(
        tmp_path, policy=_quarantine_policy(),
        mode=retention.RetentionMode.QUARANTINE, now_ns=NOW,
        pass_id="p20260101T000000", admit=_Admit({0, 1, 2}))
    if os.name == "nt":
        assert report.refused is not (
            retention.RetentionFailureReason.QUARANTINE_PLATFORM_UNSUPPORTED)
    else:
        assert report.refused is (
            retention.RetentionFailureReason.QUARANTINE_PLATFORM_UNSUPPORTED)
        assert report.moved == 0
        assert not _quarantine_root(tmp_path).exists()


def test_plan_remains_portable_on_every_platform(tmp_path):
    _populate(tmp_path, snapshots=3)
    report = _run(tmp_path, mode=retention.RetentionMode.PLAN)
    assert report.refused is None
    assert report.planned_actions


def test_the_module_does_not_call_check_then_rename_atomic():
    source = Path(retention.__file__).read_text(encoding="utf-8")
    lowered = source.lower()
    assert "atomic" not in lowered or "rename" not in lowered.split(
        "atomic", 1)[1][:200]
