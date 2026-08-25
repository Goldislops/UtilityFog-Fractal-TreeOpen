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


# -- the three compiled grammars, pinned on the COMPILED objects -------------
#
# The retired control read the module SOURCE TEXT with a non-greedy
# `re.findall(r"re\.compile\((.*?)\)", source, re.S)`. A non-greedy capture
# stops at the FIRST `)`, and `_SNAPSHOT_NAME` opens a capturing group before
# its second digit run, so that call yielded only
#
#     '\n    r"v070_gen([0-9]{1,18}'
#
# -- one of that pattern's FOUR digit runs. Across the module it saw FIVE of
# the EIGHT runs and was blind to THREE: the snapshot STEP, DATE and TIME. A
# `\d` introduced at any of those three positions was invisible to it, and no
# other control covered them either. These read `.pattern` off the compiled
# objects, so every run is in scope, and the rejection controls below exercise
# all eight positions behaviourally as well.

_EXPECTED_GRAMMARS = {
    "_SNAPSHOT_NAME":
        r"v070_gen([0-9]{1,18})_step([0-9]{1,18})_[0-9]{8}T[0-9]{6}\.npz",
    "_TELEMETRY_NAME": r"telemetry_[0-9]{8}T[0-9]{6}\.json",
    "_PASS_ID": r"p[0-9]{8}T[0-9]{6}",
}

#: `[0-9]{n}` or `[0-9]{n,m}` -- the only digit-run form the grammars may use.
_ASCII_DIGIT_RUN = re.compile(r"\[0-9\]\{[0-9]+(?:,[0-9]+)?\}")

#: Digit-run POSITIONS per grammar: snapshot has four (generation, step, date,
#: time), telemetry two (date, time), the pass identifier two (date, time).
_DIGIT_RUN_COUNTS = {"_SNAPSHOT_NAME": 4, "_TELEMETRY_NAME": 2, "_PASS_ID": 2}
_TOTAL_DIGIT_RUNS = 8

#: A `str` pattern's `\d` matches every Unicode decimal digit, not just ASCII.
#: These are the first codepoint of three such blocks; `_foreign` re-spells an
#: ASCII run into each. `[0-9]` matches none of them.
_UNICODE_DIGIT_SCRIPTS = {
    "arabic_indic": "٠",
    "devanagari": "०",
    "fullwidth": "０",
}


def _foreign(digits, base):
    """`digits` re-spelled in the decimal script beginning at `base`.

    `base="0"` returns the ASCII run unchanged, which is how each hostile
    fixture below has an otherwise-identical valid twin.
    """
    return "".join(chr(ord(base) + int(digit)) for digit in digits)


def _snapshot_spelled(generation="000001", step="000001",
                      date="20260101", clock="000000"):
    return "v070_gen%s_step%s_%sT%s.npz" % (generation, step, date, clock)


def _telemetry_spelled(date="20260101", clock="000000"):
    return "telemetry_%sT%s.json" % (date, clock)


def _pass_id_spelled(date="20260101", clock="000000"):
    return "p%sT%s" % (date, clock)


#: One row per digit-run position: `(label, kind, builder)`, where `builder`
#: takes a script base and re-spells ONLY that one run.
_DIGIT_RUN_POSITIONS = [
    ("snapshot.generation", "snapshot",
     lambda base: _snapshot_spelled(generation=_foreign("000001", base))),
    ("snapshot.step", "snapshot",
     lambda base: _snapshot_spelled(step=_foreign("000001", base))),
    ("snapshot.date", "snapshot",
     lambda base: _snapshot_spelled(date=_foreign("20260101", base))),
    ("snapshot.time", "snapshot",
     lambda base: _snapshot_spelled(clock=_foreign("000000", base))),
    ("telemetry.date", "telemetry",
     lambda base: _telemetry_spelled(date=_foreign("20260101", base))),
    ("telemetry.time", "telemetry",
     lambda base: _telemetry_spelled(clock=_foreign("000000", base))),
    ("pass_id.date", "pass_id",
     lambda base: _pass_id_spelled(date=_foreign("20260101", base))),
    ("pass_id.time", "pass_id",
     lambda base: _pass_id_spelled(clock=_foreign("000000", base))),
]

_POSITION_IDS = [row[0] for row in _DIGIT_RUN_POSITIONS]


@pytest.mark.parametrize("name", sorted(_EXPECTED_GRAMMARS))
def test_each_compiled_grammar_is_exactly_the_pinned_pattern(name):
    """Pinned on `.pattern`, not on the source text that spells it."""
    compiled = getattr(retention, name)
    assert isinstance(compiled, re.Pattern)
    assert compiled.pattern == _EXPECTED_GRAMMARS[name]
    # `re.UNICODE` is implicit for every `str` pattern; anything ELSE here --
    # `re.IGNORECASE` above all -- would silently widen the grammar.
    assert compiled.flags == re.UNICODE


def test_the_module_compiles_exactly_these_three_grammars():
    """A fourth compiled pattern would sit outside every control here."""
    compiled = sorted(name for name, value in vars(retention).items()
                      if isinstance(value, re.Pattern))
    assert compiled == sorted(_EXPECTED_GRAMMARS)


@pytest.mark.parametrize("name", sorted(_EXPECTED_GRAMMARS))
def test_no_compiled_grammar_uses_a_unicode_aware_shorthand(name):
    pattern = getattr(retention, name).pattern
    for shorthand in ("\\d", "\\D", "\\w", "\\W", "\\s", "\\S", "\\b", "\\B"):
        assert shorthand not in pattern, (name, shorthand)


@pytest.mark.parametrize("name", sorted(_EXPECTED_GRAMMARS))
def test_every_digit_run_is_an_explicitly_bounded_ascii_class(name):
    pattern = getattr(retention, name).pattern
    runs = _ASCII_DIGIT_RUN.findall(pattern)
    assert len(runs) == _DIGIT_RUN_COUNTS[name], (name, runs)
    # With the bounded ASCII runs removed, no character class may survive: an
    # unbounded `[0-9]*`/`[0-9]+`, or any other bracket class, fails here.
    assert "[" not in _ASCII_DIGIT_RUN.sub("", pattern), pattern


def test_the_three_grammars_carry_exactly_eight_digit_run_positions():
    total = sum(len(_ASCII_DIGIT_RUN.findall(getattr(retention, name).pattern))
                for name in _EXPECTED_GRAMMARS)
    assert total == _TOTAL_DIGIT_RUNS
    assert len(_DIGIT_RUN_POSITIONS) == _TOTAL_DIGIT_RUNS


@pytest.mark.parametrize("label,kind,build", _DIGIT_RUN_POSITIONS,
                         ids=_POSITION_IDS)
def test_each_digit_run_position_fixture_is_otherwise_valid(label, kind,
                                                            build):
    """Non-vacuity for the rejection controls below.

    Without this, a fixture malformed in some OTHER way would be refused
    whatever digit class the grammar used, and the rejection would prove
    nothing about the digit class at all.
    """
    ascii_form = build("0")
    if kind == "pass_id":
        assert retention.valid_pass_id(ascii_form) is True
    elif kind == "snapshot":
        assert retention.classify_name(ascii_form) == retention.SNAPSHOT_CLASS
    else:
        assert retention.classify_name(ascii_form) == retention.TELEMETRY_CLASS


@pytest.mark.parametrize("script_name,base",
                         sorted(_UNICODE_DIGIT_SCRIPTS.items()))
@pytest.mark.parametrize("label,kind,build", _DIGIT_RUN_POSITIONS,
                         ids=_POSITION_IDS)
def test_no_digit_run_position_accepts_a_unicode_decimal_digit(
        label, kind, build, script_name, base):
    """Eight positions x three scripts: `\d` is observable at every one.

    `\d` in a `str` pattern matches all three of these blocks and `[0-9]`
    matches none, so substituting `\d` at ANY single position makes exactly
    the cases for that position start classifying or validating.
    """
    hostile = build(base)
    assert hostile != build("0"), "the fixture re-spelled nothing"
    assert not hostile.isascii(), hostile
    if kind == "pass_id":
        assert retention.valid_pass_id(hostile) is False
        return
    assert retention.classify_name(hostile) is None
    if kind == "snapshot":
        assert retention._sequence_of(hostile) == retention.NO_SEQUENCE


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
    """The protected set is the fixture's newest 512 by construction -- index
    0 is newest and each successive index is one nanosecond older -- so it is
    written as literals rather than recomputed with `retention.rank`."""
    scan = _built_scan(snapshots=_aged_snapshots(600, age_days=400))
    plan = _plan(scan)
    acted = {action.basename for action in plan.actions}
    assert acted, "an empty plan would satisfy the loop below vacuously"
    for index in range(512):
        assert _snap_name(index, index) not in acted
    assert acted == {_snap_name(index, index) for index in range(512, 600)}
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


def test_the_aged_snapshot_fixture_is_newest_first_by_construction():
    """The premise the reserve-order oracle below rests on, asserted directly.

    `_aged_snapshots` gives index 0 the largest `mtime_ns` and makes each
    successive index exactly one nanosecond older, so index order IS
    newest-first and the expected probe order can be written as literals.
    """
    entries = _aged_snapshots(20, age_days=1)
    times = [entry.mtime_ns for entry in entries]
    assert times == sorted(times, reverse=True)
    assert len(set(times)) == len(times), "the fixture must not tie"
    assert [entry.basename for entry in entries[:3]] == [
        _snap_name(0, 0), _snap_name(1, 1), _snap_name(2, 2)]


def test_the_reserve_probes_newest_first():
    """The expected order is derived from the FIXTURE, never from `rank`.

    Naming `retention.rank` here would let production ordering compute its own
    expectation: invert `_rank_key` and both sides invert together, so the
    control agrees with the defect. These literals come from the fixture's
    construction -- index 0 newest, one nanosecond apart -- pinned by the test
    above.
    """
    admit = _Admit({0, 1, 2})
    scan = _built_scan(snapshots=_aged_snapshots(20, age_days=1))
    _reserve(scan, admit)
    assert admit.calls == [_snap_name(0, 0), _snap_name(1, 1),
                           _snap_name(2, 2)]


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
    began. That is why this pass is journalled rather than stateless.

    The fixture must be large enough for the reserve to SUCCEED. With only two
    snapshots the reserve needs three admissible archives, finds two, blocks
    every snapshot action, and the pass writes an empty manifest -- whereupon
    the assertion loop below runs zero times and proves nothing at all. The
    non-vacuity guards are therefore load-bearing, not decoration.
    """
    _populate(tmp_path, snapshots=5)
    report = _run(tmp_path)
    assert report.reserve_ok is True
    assert report.snapshot_actions_blocked is False
    assert report.moved >= 1
    manifest = (_quarantine_root(tmp_path) / "p20260101T000000"
                / retention.MANIFEST_NAME)
    records = [json.loads(line) for line
               in manifest.read_text(encoding="utf-8").splitlines()]
    assert len(records) == report.moved
    assert records
    for record in records:
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

        # Build the replacement under a different name FIRST, then move it
        # over. Deleting and immediately recreating is not enough: ext4
        # cheerfully reuses the just-freed inode number, so the fixture
        # produced an identical identity and proved nothing. Allocating the
        # new object while the old one still exists guarantees a distinct
        # inode on both platforms.
        swap = path.with_name(path.name + ".swap")
        swap.write_bytes(payload)                                # same size
        os.utime(swap, ns=(info.st_mtime_ns, info.st_mtime_ns))  # same time
        os.replace(swap, path)

        replaced = os.lstat(path)
        assert replaced.st_ino != info.st_ino, (
            "the fixture did not actually change identity")
        assert (replaced.st_size, replaced.st_mtime_ns) == (
            info.st_size, info.st_mtime_ns), (
            "the fixture must preserve size and time, or it proves nothing")
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


# ===========================================================================
# Final audit corrections
# ===========================================================================

# -- 1. a directory must still BE a directory, on the expected device --------

def test_directory_state_requires_a_real_directory(tmp_path):
    """`(dev, ino)` alone says which object this is, not what kind it is. A
    pass path replaced by a symlink or a file keeps neither property by
    accident, so the type is proved from the same fresh read."""
    real = tmp_path / "real"
    real.mkdir()
    assert retention.directory_state(real) is not None

    plain = tmp_path / "plain"
    plain.write_bytes(b"x")
    assert retention.directory_state(plain) is None

    missing = tmp_path / "missing"
    assert retention.directory_state(missing) is None


def test_directory_state_rejects_a_reparse_point(tmp_path, monkeypatch):
    real = tmp_path / "reparse"
    real.mkdir()
    genuine = os.lstat(real)

    def _reparse(path, *args, **kwargs):
        info = _Stat(mode=genuine.st_mode, size=genuine.st_size,
                     mtime_ns=genuine.st_mtime_ns, nlink=1,
                     dev=genuine.st_dev, ino=genuine.st_ino,
                     file_attributes=stat_module.FILE_ATTRIBUTE_REPARSE_POINT)
        return info

    monkeypatch.setattr(retention.os, "lstat", _reparse)
    assert retention.directory_state(real) is None


def test_directory_state_requires_stable_identity(tmp_path, monkeypatch):
    real = tmp_path / "identityless"
    real.mkdir()
    genuine = os.lstat(real)
    monkeypatch.setattr(
        retention.os, "lstat",
        lambda path, *a, **k: _Stat(mode=genuine.st_mode, size=0, mtime_ns=0,
                                    nlink=1, dev=0, ino=0))
    assert retention.directory_state(real) is None


def _swap_pass_path_for(tmp_path, monkeypatch, replacement_mode, when):
    """Make the pass directory present as `replacement_mode` from call `when`."""
    real_lstat = os.lstat
    seen = {"n": 0}

    def _mutating(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        text = os.fspath(path)
        if (retention.QUARANTINE_DIRNAME in text
                and os.path.basename(text).startswith("p2026")):
            seen["n"] += 1
            if seen["n"] >= when:
                return _Stat(mode=replacement_mode, size=info.st_size,
                             mtime_ns=info.st_mtime_ns, nlink=1,
                             dev=info.st_dev, ino=info.st_ino)
        return info

    monkeypatch.setattr(retention.os, "lstat", _mutating)
    return seen


@pytest.mark.parametrize("mode_name,mode", [
    ("symlink", stat_module.S_IFLNK | 0o777),
    ("regular_file", stat_module.S_IFREG | 0o644),
], ids=["symlink", "regular_file"])
def test_a_pass_path_replaced_at_capture_refuses(tmp_path, monkeypatch,
                                                 mode_name, mode):
    """Replaced between exclusive creation and the initial identity capture."""
    _populate(tmp_path, snapshots=3)
    _swap_pass_path_for(tmp_path, monkeypatch, mode, when=1)
    report = _run(tmp_path)
    assert report.moved == 0
    assert report.refused in (
        retention.RetentionFailureReason.QUARANTINE_ROOT_INVALID,
        retention.RetentionFailureReason.IDENTITY_UNAVAILABLE)


@pytest.mark.parametrize("mode_name,mode", [
    ("symlink", stat_module.S_IFLNK | 0o777),
    ("regular_file", stat_module.S_IFREG | 0o644),
], ids=["symlink", "regular_file"])
def test_a_pass_path_replaced_during_revalidation_halts(tmp_path, monkeypatch,
                                                        mode_name, mode):
    """Replaced later, once moves are already under way."""
    _populate(tmp_path, snapshots=4)
    _swap_pass_path_for(tmp_path, monkeypatch, mode, when=3)
    report = _run(tmp_path)
    assert report.halted is True
    assert report.refused is retention.RetentionFailureReason.QUARANTINE_ROOT_INVALID


def test_a_quarantine_root_replaced_by_a_symlink_refuses(tmp_path,
                                                         monkeypatch):
    _populate(tmp_path, snapshots=3)
    real_lstat = os.lstat

    def _rooted(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if os.path.basename(os.fspath(path)) == retention.QUARANTINE_DIRNAME:
            return _Stat(mode=stat_module.S_IFLNK | 0o777, size=info.st_size,
                         mtime_ns=info.st_mtime_ns, nlink=1,
                         dev=info.st_dev, ino=info.st_ino)
        return info

    monkeypatch.setattr(retention.os, "lstat", _rooted)
    report = _run(tmp_path)
    assert report.moved == 0
    assert report.refused is retention.RetentionFailureReason.QUARANTINE_ROOT_INVALID


def test_the_quarantine_tree_must_share_the_data_root_device(tmp_path,
                                                             monkeypatch):
    """A same-volume rename is the whole basis for the move being a
    directory-entry operation. A quarantine root that has become a mount point
    elsewhere breaks that, and is refused."""
    _populate(tmp_path, snapshots=3)
    real_lstat = os.lstat

    def _other_device(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if retention.QUARANTINE_DIRNAME in os.fspath(path):
            return _Stat(mode=info.st_mode, size=info.st_size,
                         mtime_ns=info.st_mtime_ns, nlink=1,
                         dev=info.st_dev + 1, ino=info.st_ino)
        return info

    monkeypatch.setattr(retention.os, "lstat", _other_device)
    report = _run(tmp_path)
    assert report.moved == 0
    assert report.refused is retention.RetentionFailureReason.QUARANTINE_ROOT_INVALID


def test_the_data_root_is_proved_a_directory_before_quarantine(tmp_path):
    plain = tmp_path / "not_a_directory"
    plain.write_bytes(b"x")
    report = _run(plain)
    assert report.moved == 0
    assert report.refused is not None


# -- 2. the survey's remaining boundaries ------------------------------------

def _many(count):
    return [_snap_name(index, index) for index in range(count)]


def test_payload_entries_are_capped_independently_of_the_manifest(tmp_path):
    """Exactly one batch of payload entries succeeds."""
    policy = dataclasses.replace(_quarantine_policy(), max_actions_per_pass=4)
    names = _many(4)
    directory = _pass_dir(tmp_path,
                          records=[_record_bytes(name) for name in names],
                          extra_files=names)
    survey = _survey(directory, policy)
    assert survey.refused is None
    assert survey.present == 4
    assert survey.manifested == 4


def test_one_payload_past_the_cap_refuses(tmp_path):
    policy = dataclasses.replace(_quarantine_policy(), max_actions_per_pass=4)
    names = _many(5)
    directory = _pass_dir(tmp_path, extra_files=names)
    survey = _survey(directory, policy)
    assert survey.refused is retention.RetentionFailureReason.SURVEY_LIMIT_EXCEEDED


def test_a_missing_manifest_does_not_buy_an_extra_payload_slot(tmp_path):
    """The manifest is allowed as ONE additional entry, not as a spare payload
    slot that its absence hands back."""
    policy = dataclasses.replace(_quarantine_policy(), max_actions_per_pass=4)
    directory = _pass_dir(tmp_path, extra_files=_many(5))
    assert not (directory / retention.MANIFEST_NAME).exists()
    survey = _survey(directory, policy)
    assert survey.refused is retention.RetentionFailureReason.SURVEY_LIMIT_EXCEEDED


def test_the_manifest_byte_budget_is_exact(tmp_path):
    policy = dataclasses.replace(_quarantine_policy(), max_actions_per_pass=2)
    budget = 2 * retention.MAX_MANIFEST_RECORD_BYTES
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, extra_files=[name])
    manifest = directory / retention.MANIFEST_NAME
    manifest.write_bytes(b"x" * (budget - 1) + b"\n")
    survey = _survey(directory, policy)
    assert survey.refused is None


def test_one_byte_past_the_manifest_budget_refuses(tmp_path):
    policy = dataclasses.replace(_quarantine_policy(), max_actions_per_pass=2)
    budget = 2 * retention.MAX_MANIFEST_RECORD_BYTES
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, extra_files=[name])
    manifest = directory / retention.MANIFEST_NAME
    manifest.write_bytes(b"x" * budget + b"\n")
    survey = _survey(directory, policy)
    assert survey.refused is retention.RetentionFailureReason.SURVEY_LIMIT_EXCEEDED


def test_the_record_count_is_capped_however_short_the_records(tmp_path):
    """A corrupt journal of one-byte lines must not turn parsing into
    unbounded work just because each record is tiny."""
    policy = dataclasses.replace(_quarantine_policy(), max_actions_per_pass=4)
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, extra_files=[name])
    manifest = directory / retention.MANIFEST_NAME
    manifest.write_bytes(b"x\n" * 200)
    survey = _survey(directory, policy)
    assert survey.refused is retention.RetentionFailureReason.SURVEY_LIMIT_EXCEEDED


def test_exactly_the_record_cap_parses(tmp_path):
    policy = dataclasses.replace(_quarantine_policy(), max_actions_per_pass=4)
    names = _many(4)
    directory = _pass_dir(tmp_path,
                          records=[_record_bytes(name) for name in names],
                          extra_files=names)
    survey = _survey(directory, policy)
    assert survey.refused is None
    assert survey.manifested == 4


@pytest.mark.parametrize("mode_name,mode", [
    ("symlink", stat_module.S_IFLNK | 0o777),
    ("directory", stat_module.S_IFDIR | 0o755),
    ("fifo", stat_module.S_IFIFO | 0o644),
], ids=["symlink", "directory", "fifo"])
def test_a_manifest_of_the_wrong_type_is_a_sanitized_refusal(tmp_path,
                                                             monkeypatch,
                                                             mode_name, mode):
    """The manifest is opened through a descriptor and `fstat`ed, so a
    replaced or linked manifest is refused before a byte is read."""
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, records=[_record_bytes(name)],
                          extra_files=[name])
    real_fstat = os.fstat

    def _wrong_type(fd):
        info = real_fstat(fd)
        if stat_module.S_ISREG(info.st_mode):
            return _Stat(mode=mode, size=info.st_size, mtime_ns=0, nlink=1,
                         dev=info.st_dev, ino=info.st_ino)
        return info

    monkeypatch.setattr(retention.os, "fstat", _wrong_type)
    survey = _survey(directory)
    assert survey.refused is retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID
    assert survey.present == 0


def test_a_reparse_manifest_is_a_sanitized_refusal(tmp_path, monkeypatch):
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, records=[_record_bytes(name)],
                          extra_files=[name])
    real_fstat = os.fstat

    def _reparse(fd):
        info = real_fstat(fd)
        return _Stat(mode=info.st_mode, size=info.st_size, mtime_ns=0,
                     nlink=1, dev=info.st_dev, ino=info.st_ino,
                     file_attributes=stat_module.FILE_ATTRIBUTE_REPARSE_POINT)

    monkeypatch.setattr(retention.os, "fstat", _reparse)
    survey = _survey(directory)
    assert survey.refused is retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID


def test_the_survey_closes_its_manifest_handle(tmp_path, monkeypatch):
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, records=[_record_bytes(name)],
                          extra_files=[name])
    opened = []
    closed = []
    real_open = os.open
    real_close = os.close
    monkeypatch.setattr(retention.os, "open",
                        lambda *a, **k: (lambda fd: (opened.append(fd), fd)[1])(
                            real_open(*a, **k)))
    monkeypatch.setattr(retention.os, "close",
                        lambda fd: (closed.append(fd), real_close(fd))[1])
    _survey(directory)
    assert opened, "the manifest was not opened through a descriptor"
    assert set(opened) <= set(closed), "a manifest handle was leaked"


def test_a_survey_refusal_still_repairs_and_removes_nothing(tmp_path):
    policy = dataclasses.replace(_quarantine_policy(), max_actions_per_pass=1)
    names = _many(3)
    directory = _pass_dir(tmp_path,
                          records=[_record_bytes(name) for name in names],
                          extra_files=names)
    manifest = directory / retention.MANIFEST_NAME
    before = manifest.read_bytes()
    survey = _survey(directory, policy)
    assert survey.refused is not None
    assert manifest.read_bytes() == before
    assert all((directory / name).exists() for name in names)


# -- 3. prose that must not overclaim ----------------------------------------

def test_the_ceiling_is_not_described_as_an_unconditional_cap():
    """It is an eligibility trigger. Each pass performs at most 512 actions,
    so a fast enough producer leaves a temporary backlog that drains over
    several passes."""
    source = Path(retention.__file__).read_text(encoding="utf-8").lower()
    for overclaim in ("cannot outrun", "hard count cap",
                      "unconditional cap"):
        assert overclaim not in source, overclaim
    assert "backlog" in source


def test_the_hashed_lock_is_not_claimed_collision_free():
    source = Path(retention.__file__).read_text(encoding="utf-8").lower()
    for overclaim in ("collision free", "collision-free", "never collide",
                      "cannot collide"):
        assert overclaim not in source, overclaim
    assert "collision-resistant" in source


# ===========================================================================
# The manifest PATH, and short reads
# ===========================================================================

def _manifest_of(directory):
    return Path(directory) / retention.MANIFEST_NAME


def _try_symlink(link, target):
    """Create a real symlink, or report that this platform will not.

    Returns True when a genuine link exists. Never skips: the caller runs the
    injected equivalent instead, so the property is proved either way and the
    suite stays zero-skip.
    """
    try:
        os.symlink(os.fspath(target), os.fspath(link))
    except (OSError, NotImplementedError, AttributeError):
        return False
    return True


def test_a_real_symlinked_manifest_is_refused(tmp_path):
    """`fstat` on the OPENED handle reports the TARGET, which is a perfectly
    regular file -- so handle validation alone can never reject a symlinked
    manifest. The path itself has to be proved.

    Where the platform grants symlink creation this uses a real link; where it
    does not, the identical condition is injected. Both branches assert the
    same refusal, and neither skips.
    """
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, extra_files=[name])
    real_target = tmp_path / "real_manifest_target"
    real_target.write_bytes(_record_bytes(name))
    manifest = _manifest_of(directory)

    used_real_link = _try_symlink(manifest, real_target)
    if used_real_link:
        assert os.path.islink(manifest)
        assert stat_module.S_ISREG(os.stat(manifest).st_mode), (
            "the link must point at a regular file, or this proves nothing")
        survey = _survey(directory)
    else:
        manifest.write_bytes(_record_bytes(name))
        real_lstat = os.lstat

        def _as_symlink(path, *args, **kwargs):
            info = real_lstat(path, *args, **kwargs)
            if os.path.basename(os.fspath(path)) == retention.MANIFEST_NAME:
                return _Stat(mode=stat_module.S_IFLNK | 0o777,
                             size=info.st_size, mtime_ns=info.st_mtime_ns,
                             nlink=1, dev=info.st_dev, ino=info.st_ino)
            return info

        with mock.patch.object(retention.os, "lstat", _as_symlink):
            survey = _survey(directory)

    assert survey.refused is retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID
    assert survey.present == 0


def test_a_reparse_manifest_path_is_refused(tmp_path, monkeypatch):
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, records=[_record_bytes(name)],
                          extra_files=[name])
    real_lstat = os.lstat

    def _reparse_path(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if os.path.basename(os.fspath(path)) == retention.MANIFEST_NAME:
            return _Stat(mode=info.st_mode, size=info.st_size,
                         mtime_ns=info.st_mtime_ns, nlink=1,
                         dev=info.st_dev, ino=info.st_ino,
                         file_attributes=stat_module.FILE_ATTRIBUTE_REPARSE_POINT)
        return info

    monkeypatch.setattr(retention.os, "lstat", _reparse_path)
    survey = _survey(directory)
    assert survey.refused is retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID


def test_a_replacement_between_the_path_and_handle_checks_is_refused(
        tmp_path, monkeypatch):
    """The path proves one object and the handle another: identity must agree
    across both, or something was swapped in between."""
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, records=[_record_bytes(name)],
                          extra_files=[name])
    real_fstat = os.fstat

    def _different_object(fd):
        info = real_fstat(fd)
        if stat_module.S_ISREG(info.st_mode):
            return _Stat(mode=info.st_mode, size=info.st_size,
                         mtime_ns=info.st_mtime_ns, nlink=1,
                         dev=info.st_dev, ino=info.st_ino + 1)
        return info

    monkeypatch.setattr(retention.os, "fstat", _different_object)
    survey = _survey(directory)
    assert survey.refused is retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID


def test_a_special_manifest_cannot_block_the_survey(tmp_path):
    """A FIFO named `manifest.jsonl` would block a plain read-only `open`
    until a writer appeared. The path check refuses it before `open` is
    reached, and the open itself uses the platform's nonblocking flag where
    one exists."""
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, extra_files=[name])
    manifest = _manifest_of(directory)

    made_fifo = False
    if hasattr(os, "mkfifo"):
        try:
            os.mkfifo(os.fspath(manifest))
            made_fifo = True
        except (OSError, NotImplementedError):
            made_fifo = False

    if made_fifo:
        survey = _survey(directory)
    else:
        manifest.write_bytes(b"")
        real_lstat = os.lstat

        def _as_fifo(path, *args, **kwargs):
            info = real_lstat(path, *args, **kwargs)
            if os.path.basename(os.fspath(path)) == retention.MANIFEST_NAME:
                return _Stat(mode=stat_module.S_IFIFO | 0o644, size=0,
                             mtime_ns=info.st_mtime_ns, nlink=1,
                             dev=info.st_dev, ino=info.st_ino)
            return info

        with mock.patch.object(retention.os, "lstat", _as_fifo):
            survey = _survey(directory)

    assert survey.refused is retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID


def test_the_manifest_open_uses_no_follow_where_available():
    source = Path(retention.__file__).read_text(encoding="utf-8")
    assert "O_NOFOLLOW" in source
    assert "O_NONBLOCK" in source


def test_every_survey_descriptor_is_closed_on_a_validation_failure(tmp_path,
                                                                   monkeypatch):
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, records=[_record_bytes(name)],
                          extra_files=[name])
    opened = []
    closed = []
    real_open = os.open
    real_close = os.close
    real_fstat = os.fstat

    def _tracked_open(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        opened.append(fd)
        return fd

    def _wrong(fd):
        info = real_fstat(fd)
        if stat_module.S_ISREG(info.st_mode):
            return _Stat(mode=stat_module.S_IFIFO | 0o644, size=0, mtime_ns=0,
                         nlink=1, dev=info.st_dev, ino=info.st_ino)
        return info

    monkeypatch.setattr(retention.os, "open", _tracked_open)
    monkeypatch.setattr(retention.os, "close",
                        lambda fd: (closed.append(fd), real_close(fd))[1])
    monkeypatch.setattr(retention.os, "fstat", _wrong)
    survey = _survey(directory)
    assert survey.refused is retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID
    assert opened and set(opened) <= set(closed)


def test_a_survey_read_failure_stays_fixed_and_path_free(tmp_path, monkeypatch,
                                                          capsys):
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, records=[_record_bytes(name)],
                          extra_files=[name])

    def _read_fails(fd, size):
        raise OSError(errno.EIO, "input/output error")

    monkeypatch.setattr(retention.os, "read", _read_fails)
    survey = _survey(directory)
    printed = capsys.readouterr()
    assert survey.refused is retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID
    assert "v070_gen" not in printed.out and "v070_gen" not in printed.err
    for field in dataclasses.fields(survey):
        assert not isinstance(getattr(survey, field.name),
                              (str, bytes, Path)), field.name


# -- short reads must not weaken the byte boundary ---------------------------

def _fragmenting_read(monkeypatch, chunk_size):
    """Deliver every manifest read in `chunk_size`-byte fragments."""
    real_read = os.read
    calls = {"n": 0}

    def _short(fd, size):
        calls["n"] += 1
        return real_read(fd, min(size, chunk_size))

    monkeypatch.setattr(retention.os, "read", _short)
    return calls


def test_an_exact_budget_manifest_survives_short_reads(tmp_path, monkeypatch):
    policy = dataclasses.replace(_quarantine_policy(), max_actions_per_pass=2)
    budget = 2 * retention.MAX_MANIFEST_RECORD_BYTES
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, extra_files=[name])
    manifest = _manifest_of(directory)
    manifest.write_bytes(b"x" * (budget - 1) + b"\n")

    calls = _fragmenting_read(monkeypatch, 7)
    survey = _survey(directory, policy)
    assert survey.refused is None
    assert calls["n"] > 1, "the fixture did not actually fragment the read"


def test_an_over_budget_manifest_is_refused_across_short_reads(tmp_path,
                                                               monkeypatch):
    policy = dataclasses.replace(_quarantine_policy(), max_actions_per_pass=2)
    budget = 2 * retention.MAX_MANIFEST_RECORD_BYTES
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, extra_files=[name])
    manifest = _manifest_of(directory)
    manifest.write_bytes(b"x" * budget + b"\n")

    calls = _fragmenting_read(monkeypatch, 7)
    survey = _survey(directory, policy)
    assert survey.refused is retention.RetentionFailureReason.SURVEY_LIMIT_EXCEEDED
    assert calls["n"] > 1


def test_a_short_read_is_never_mistaken_for_the_whole_manifest(tmp_path,
                                                               monkeypatch):
    """The failure this forbids: one short read treated as EOF, so a partial
    prefix is validated as the complete journal and every record beyond it is
    silently reported unmanifested."""
    policy = dataclasses.replace(_quarantine_policy(), max_actions_per_pass=8)
    names = _many(3)
    directory = _pass_dir(tmp_path,
                          records=[_record_bytes(one) for one in names],
                          extra_files=names)
    calls = _fragmenting_read(monkeypatch, 1)
    survey = _survey(directory, policy)
    assert survey.refused is None
    assert survey.manifested == 3, "a partial prefix was taken as complete"
    assert survey.unmanifested == 0
    assert calls["n"] > 3


def test_the_read_loop_cannot_spin_without_progress(tmp_path, monkeypatch):
    """A read returning nothing is end-of-file, not an invitation to retry."""
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, records=[_record_bytes(name)],
                          extra_files=[name])
    calls = {"n": 0}

    def _always_empty(fd, size):
        calls["n"] += 1
        if calls["n"] > 64:
            raise AssertionError("the read loop spun without progress")
        return b""

    monkeypatch.setattr(retention.os, "read", _always_empty)
    survey = _survey(directory)
    assert survey.refused is None
    assert survey.unmanifested == 1
    assert calls["n"] <= 2


# ===========================================================================
# The same-object alias, and close failure
# ===========================================================================

def test_a_same_object_alias_after_open_is_refused(tmp_path, monkeypatch):
    """The case pre-open `lstat` plus post-open `fstat` cannot catch.

    Windows has no `O_NOFOLLOW`, so an attacker can move the real manifest
    aside and drop a symlink at its path pointing back at that SAME object.
    The open follows the link, so the handle carries exactly the identity the
    pre-open check recorded and `fstat` agrees -- while the path is now a
    reparse point. Only a fresh post-open `lstat` of the path can see it.

    Injected rather than built from a real link, so the control is portable
    and never skips: the identity is deliberately held IDENTICAL throughout,
    which is precisely what makes the existing comparisons pass.
    """
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, records=[_record_bytes(name)],
                          extra_files=[name])
    manifest = _manifest_of(directory)
    genuine = os.lstat(manifest)
    seen = {"lstat": 0}
    reads = {"n": 0}
    real_lstat = os.lstat
    real_read = os.read

    def _alias_after_open(path, *args, **kwargs):
        if os.path.basename(os.fspath(path)) == retention.MANIFEST_NAME:
            seen["lstat"] += 1
            if seen["lstat"] == 1:
                return genuine  # pre-open: a perfectly ordinary regular file
            # post-open: a reparse point standing where the file was, and
            # aliasing the very same object, so identity still agrees.
            return _Stat(mode=stat_module.S_IFLNK | 0o777,
                         size=genuine.st_size, mtime_ns=genuine.st_mtime_ns,
                         nlink=1, dev=genuine.st_dev, ino=genuine.st_ino,
                         file_attributes=stat_module.FILE_ATTRIBUTE_REPARSE_POINT)
        return real_lstat(path, *args, **kwargs)

    def _counting_read(fd, size):
        reads["n"] += 1
        return real_read(fd, size)

    monkeypatch.setattr(retention.os, "lstat", _alias_after_open)
    monkeypatch.setattr(retention.os, "read", _counting_read)
    survey = _survey(directory)

    assert seen["lstat"] >= 2, (
        "the path was not re-read after the open, so the alias is invisible")
    assert survey.refused is retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID
    assert reads["n"] == 0, "bytes were read from an aliased manifest path"


def test_the_post_open_path_recheck_accepts_an_untouched_manifest(tmp_path,
                                                                  monkeypatch):
    """Non-vacuity for the control above: the recheck must not refuse a
    manifest that nothing has touched."""
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, records=[_record_bytes(name)],
                          extra_files=[name])
    seen = {"lstat": 0}
    real_lstat = os.lstat

    def _counting(path, *args, **kwargs):
        if os.path.basename(os.fspath(path)) == retention.MANIFEST_NAME:
            seen["lstat"] += 1
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(retention.os, "lstat", _counting)
    survey = _survey(directory)
    assert seen["lstat"] >= 2
    assert survey.refused is None
    assert survey.manifested == 1


def test_a_path_removed_between_open_and_recheck_is_refused(tmp_path,
                                                            monkeypatch):
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, records=[_record_bytes(name)],
                          extra_files=[name])
    seen = {"lstat": 0}
    real_lstat = os.lstat

    def _vanishing(path, *args, **kwargs):
        if os.path.basename(os.fspath(path)) == retention.MANIFEST_NAME:
            seen["lstat"] += 1
            if seen["lstat"] > 1:
                raise FileNotFoundError(errno.ENOENT, "no such file")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(retention.os, "lstat", _vanishing)
    survey = _survey(directory)
    assert survey.refused is retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID


# -- a close that fails is a refusal, not a footnote -------------------------

def test_a_close_failure_refuses_rather_than_returning_bytes(tmp_path,
                                                              capsys):
    """The helper collected its bytes, then swallowed an `os.close` error and
    returned them anyway -- so a close failure silently produced a normal
    answer while the body claimed it produced a refusal. The claim is the one
    worth keeping."""
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, records=[_record_bytes(name)],
                          extra_files=[name])
    real_close = os.close
    closes = {"n": 0}

    def _close_then_fail(fd):
        closes["n"] += 1
        real_close(fd)                     # the descriptor IS released
        raise OSError(errno.EIO, "input/output error on close")

    with mock.patch.object(retention.os, "close", _close_then_fail):
        survey = _survey(directory)

    printed = capsys.readouterr()
    assert closes["n"] == 1, "the handle received other than one close attempt"
    assert survey.refused is retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID
    assert survey.present == 0
    for leak in ("v070_gen", ".npz", "input/output", "Errno", "Traceback",
                 str(tmp_path)):
        assert leak not in printed.out and leak not in printed.err, leak
    for field in dataclasses.fields(survey):
        assert not isinstance(getattr(survey, field.name),
                              (str, bytes, Path)), field.name


def test_a_successful_close_still_returns_the_bytes(tmp_path):
    """Non-vacuity: the refusal above must come from the close FAILING, not
    from the close being attempted at all."""
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, records=[_record_bytes(name)],
                          extra_files=[name])
    survey = _survey(directory)
    assert survey.refused is None
    assert survey.manifested == 1


def test_exactly_one_close_attempt_per_acquired_handle(tmp_path):
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, records=[_record_bytes(name)],
                          extra_files=[name])
    opened = []
    closed = []
    real_open = os.open
    real_close = os.close

    def _tracked_open(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        opened.append(fd)
        return fd

    def _tracked_close(fd):
        closed.append(fd)
        return real_close(fd)

    with mock.patch.object(retention.os, "open", _tracked_open), \
            mock.patch.object(retention.os, "close", _tracked_close):
        _survey(directory)

    assert len(opened) == 1
    assert closed == opened, "the handle was closed other than exactly once"


def test_a_close_failure_after_a_read_failure_stays_one_refusal(tmp_path,
                                                                 capsys):
    """Both fail: the outcome is still one fixed sanitized refusal, and the
    handle still receives exactly one close attempt."""
    name = _snap_name(1, 1)
    directory = _pass_dir(tmp_path, records=[_record_bytes(name)],
                          extra_files=[name])
    real_close = os.close
    closes = {"n": 0}

    def _close_then_fail(fd):
        closes["n"] += 1
        real_close(fd)
        raise OSError(errno.EIO, "close failed")

    def _read_fails(fd, size):
        raise OSError(errno.EIO, "read failed")

    with mock.patch.object(retention.os, "close", _close_then_fail), \
            mock.patch.object(retention.os, "read", _read_fails):
        survey = _survey(directory)

    printed = capsys.readouterr()
    assert closes["n"] == 1
    assert survey.refused is retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID
    assert "close failed" not in printed.out and "read failed" not in printed.out


# ---------------------------------------------------------------------------
# Reserve-blocked telemetry refill
# ---------------------------------------------------------------------------
#
# The adversarial ordering is the whole point: eligible snapshots are made
# strictly OLDER than eligible telemetry, so the oldest-first merged list is
# entirely snapshots for the first `max_actions_per_pass` positions. A reserve
# shortfall then removes every one of them, and the question these controls
# settle is whether the vacated positions are refilled from the telemetry that
# was eligible all along but fell outside the cap.
#
# The existing shortfall control cannot see this: its combined eligible
# population is 88 + 76, far below the 512 cap, so the cap never binds and no
# position is ever vacated.

_REFILL_SNAPSHOT_AGE_DAYS = 400          # older -- sorts first, takes the cap
_REFILL_TELEMETRY_AGE_DAYS = 100         # newer, still far beyond 14 days
_REFILL_SNAPSHOT_TOTAL = 1_100           # 588 eligible above the 512 floor


def _refill_snapshots(count=_REFILL_SNAPSHOT_TOTAL):
    return [
        _entry(_snap_name(index, index), retention.SNAPSHOT_CLASS,
               NOW - _ns(_REFILL_SNAPSHOT_AGE_DAYS * DAY) - _ns(index),
               index, index)
        for index in range(count)
    ]


def _refill_telemetry(count, *, tail_ties=0):
    """`count` telemetry entries, the oldest `tail_ties` sharing one mtime.

    The tie group is emitted in DESCENDING name order so that insertion order
    is not the expected order: only the basename tie-break can produce it.
    """
    entries = [
        _entry(_telem_name("20260101T%06d" % index), retention.TELEMETRY_CLASS,
               NOW - _ns(_REFILL_TELEMETRY_AGE_DAYS * DAY) - _ns(index))
        for index in range(count - tail_ties)
    ]
    tie_mtime = NOW - _ns(_REFILL_TELEMETRY_AGE_DAYS * DAY) - _ns(count)
    entries.extend(
        _entry(_telem_name("20260102T%06d" % (tail_ties - 1 - offset)),
               retention.TELEMETRY_CLASS, tie_mtime)
        for offset in range(tail_ties)
    )
    return entries


def _refill_scan(telemetry_count, *, tail_ties=0,
                 snapshot_count=_REFILL_SNAPSHOT_TOTAL):
    return _built_scan(snapshots=_refill_snapshots(snapshot_count),
                       telemetry=_refill_telemetry(telemetry_count,
                                                   tail_ties=tail_ties))


def _refill_report(scan, admit=None):
    return retention.run_pass(
        "data", policy=retention.PRODUCTION_RETENTION_POLICY,
        mode=retention.RetentionMode.PLAN, now_ns=NOW, scan=scan,
        admit=admit if admit is not None else _Admit({0, 1}))


def _expected_refill_basenames(telemetry_count, cap=512):
    """Derived from the fixture, not from the implementation.

    Telemetry index `i` carries mtime `NOW - 100d - i`, so a larger index is
    older. The newest `recovery_floor` are protected; everything past them is
    eligible, and oldest-first means descending index.
    """
    floor = retention.PRODUCTION_RETENTION_POLICY.telemetry.recovery_floor
    oldest_first = [_telem_name("20260101T%06d" % index)
                    for index in range(telemetry_count - 1, floor - 1, -1)]
    return oldest_first[:cap]


def test_at_least_512_older_eligible_snapshots_occupy_the_original_cap():
    """The premise every refill control below rests on."""
    scan = _refill_scan(1_724)
    plan = _plan(scan)
    assert plan.snapshot_eligible == 588
    assert plan.telemetry_eligible == 700
    assert len(plan.actions) == 512
    assert all(action.klass == retention.SNAPSHOT_CLASS
               for action in plan.actions)


def test_a_reserve_shortfall_refills_the_batch_with_every_eligible_telemetry():
    """Under the cap: every eligible telemetry action must survive."""
    scan = _refill_scan(1_324)               # 300 eligible telemetry
    report = _refill_report(scan)
    assert report.reserve_ok is False
    assert report.snapshot_actions_blocked is True
    names = [action.basename for action in report.planned_actions]
    assert len(names) == 300
    assert names == _expected_refill_basenames(1_324)


def test_a_reserve_shortfall_refill_stops_at_the_action_cap():
    """Over the cap: exactly `max_actions_per_pass` telemetry actions."""
    scan = _refill_scan(1_724)               # 700 eligible telemetry
    report = _refill_report(scan)
    assert report.snapshot_actions_blocked is True
    names = [action.basename for action in report.planned_actions]
    assert len(names) == 512
    assert names == _expected_refill_basenames(1_724)


def test_refilled_telemetry_stays_oldest_first_with_the_basename_tie_break():
    scan = _refill_scan(1_044, tail_ties=20)
    report = _refill_report(scan)
    assert report.snapshot_actions_blocked is True
    names = [action.basename for action in report.planned_actions]
    assert len(names) == 20
    assert names == sorted(names)
    assert names == [_telem_name("20260102T%06d" % index)
                     for index in range(20)]


def test_no_snapshot_action_survives_a_reserve_shortfall():
    report = _refill_report(_refill_scan(1_724))
    assert report.snapshot_actions_blocked is True
    assert report.planned_actions
    assert not any(action.klass == retention.SNAPSHOT_CLASS
                   for action in report.planned_actions)


def test_reserve_blocked_eligibility_counts_stay_complete_not_selected():
    """The counts are eligibility, not selection, and the refill must not
    quietly redefine them as the number of actions taken."""
    report = _refill_report(_refill_scan(1_724))
    assert report.snapshot_eligible == 588
    assert report.telemetry_eligible == 700
    assert report.planned_actions_count == 512


def test_planned_reflects_the_refilled_action_set():
    report = _refill_report(_refill_scan(1_724))
    assert report.planned_actions_count == len(report.planned_actions)
    line = retention.format_report(report)
    assert "planned=512" in line
    assert "snap_eligible=588" in line
    assert "telem_eligible=700" in line
    assert "snapshot_blocked=True" in line


def test_the_refill_never_exceeds_the_action_cap():
    cap = retention.PRODUCTION_RETENTION_POLICY.max_actions_per_pass
    assert cap == 512
    for telemetry_count in (1_324, 1_724, 3_000):
        report = _refill_report(_refill_scan(telemetry_count))
        assert len(report.planned_actions) <= cap


def test_a_passing_reserve_leaves_combined_ordering_and_cap_unchanged():
    """The refill must be confined to the blocked branch."""
    scan = _refill_scan(1_724)
    report = _refill_report(scan, admit=_Admit({0, 1, 2}))
    assert report.reserve_ok is True
    assert report.snapshot_actions_blocked is False
    assert report.planned_actions == _plan(scan).actions
    assert len(report.planned_actions) == 512
    assert all(action.klass == retention.SNAPSHOT_CLASS
               for action in report.planned_actions)


def test_no_eligible_snapshot_leaves_behavior_identical_and_never_probes():
    """`snap_eligible=0` is the branch the accepted operational PLAN took."""
    scan = _refill_scan(1_324, snapshot_count=100)    # 100 < the 512 floor
    admit = _Admit({0, 1})
    report = _refill_report(scan, admit=admit)
    assert report.snapshot_eligible == 0
    assert admit.calls == []                          # reserve never probed
    assert report.reserve_ok is True
    assert report.snapshot_actions_blocked is False
    assert report.planned_actions == _plan(scan).actions


def test_an_unexpected_reserve_exception_still_refuses_the_whole_refill_pass():
    def _boom(path, *, data_dir, policy=None):
        raise RuntimeError("unexpected")

    report = _refill_report(_refill_scan(1_724), admit=_boom)
    assert report.refused is retention.RetentionFailureReason.RESERVE_CHECK_FAILED
    assert report.planned_actions == ()


def _refill_disk_policy():
    """A tiny policy so the cap binds with ten real files rather than 2,800."""
    return retention.RetentionPolicy(
        snapshot=retention.ClassRetentionPolicy(
            max_age_seconds=30 * DAY, recovery_floor=1,
            absolute_ceiling=8_192, max_inspected=1_000),
        telemetry=retention.ClassRetentionPolicy(
            max_age_seconds=14 * DAY, recovery_floor=1,
            absolute_ceiling=8_192, max_inspected=1_000),
        quiescence_seconds=900, max_actions_per_pass=3,
        max_directory_entries=1_000, max_combined_inspected=1_000,
        reserve_window=8, reserve_required=3)


def _populate_refill_dir(directory):
    for index in range(5):
        _write(directory, _snap_name(index, index),
               age_days=_REFILL_SNAPSHOT_AGE_DAYS + index)
    for index in range(5):
        _write(directory, _telem_name("20260101T%06d" % index),
               age_days=_REFILL_TELEMETRY_AGE_DAYS + index)


def test_plan_and_quarantine_consume_the_same_refilled_selection(tmp_path):
    policy = _refill_disk_policy()
    plan_dir = tmp_path / "plan"
    quarantine_dir = tmp_path / "quarantine"
    plan_dir.mkdir()
    quarantine_dir.mkdir()
    _populate_refill_dir(plan_dir)
    _populate_refill_dir(quarantine_dir)

    planned = retention.run_pass(
        plan_dir, policy=policy, mode=retention.RetentionMode.PLAN,
        now_ns=NOW, admit=_Admit({0, 1}))
    quarantined = retention.run_pass(
        quarantine_dir, policy=policy,
        mode=retention.RetentionMode.QUARANTINE, now_ns=NOW,
        pass_id="p20260101T000000", admit=_Admit({0, 1}),
        mover=_injected_mover)

    assert planned.snapshot_actions_blocked is True
    assert quarantined.snapshot_actions_blocked is True
    assert len(planned.planned_actions) == 3
    assert all(action.klass == retention.TELEMETRY_CLASS
               for action in planned.planned_actions)
    assert ([action.basename for action in planned.planned_actions]
            == [action.basename for action in quarantined.planned_actions])
    assert quarantined.moved == 3


# ---------------------------------------------------------------------------
# Empty quarantine passes must be side-effect free
# ---------------------------------------------------------------------------
#
# `_validated_quarantine_root` creates `.retention_quarantine` when it is
# absent, and `_quarantine` then exclusively creates a pass directory and a
# manifest. Reaching that code with an empty action set writes three objects
# while moving nothing.
#
# That is not merely untidy. The scan charges EVERY yielded root entry against
# `max_directory_entries` -- excluded directories included -- and refuses one
# entry past the limit. A directory that scanned at exactly the limit is
# therefore pushed over it by the very pass meant to relieve it, after which no
# later pass can get far enough to help.
#
# The refusal for an unusable data root has to survive that change. The scan
# treats a missing or non-directory target as an EMPTY SUCCESSFUL scan, so the
# `_quarantine` call is presently the only thing that turns such a target into
# the fixed `IDENTITY_UNAVAILABLE` refusal. Skipping `_quarantine` without
# re-proving the root would silently report a clean no-op against a path that
# is not a directory at all.


def _no_action_policy(**kwargs):
    """Floors high enough that nothing in a small fixture is ever eligible."""
    base = dict(entries=1_000, combined=1_000, snap=1_000, telem=1_000,
                ceiling=8_192, floor=50)
    base.update(kwargs)
    return _tiny(**base)


def _no_action_run(directory, policy=None, pass_id="p20260101T000000",
                   admit=None, mover=_injected_mover):
    return retention.run_pass(
        directory, policy=policy or _no_action_policy(),
        mode=retention.RetentionMode.QUARANTINE, now_ns=NOW,
        pass_id=pass_id, admit=admit if admit is not None else _Admit({0, 1, 2}),
        mover=mover)


def test_a_no_action_quarantine_pass_creates_no_quarantine_state(tmp_path):
    made = _populate(tmp_path, snapshots=4)
    before = sorted(p.name for p in tmp_path.iterdir())
    report = _no_action_run(tmp_path)
    assert report.planned_actions == ()
    assert report.moved == 0
    assert not _quarantine_root(tmp_path).exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert all(path.exists() for path in made)


def test_a_reserve_blocked_pass_with_no_eligible_telemetry_creates_nothing(
        tmp_path):
    """The exact shape the refill correction can produce: snapshots blocked,
    nothing left to refill with, so the pass must do nothing at all."""
    for index in range(5):
        _write(tmp_path, _snap_name(index, index), age_days=400 + index)
    _write(tmp_path, _telem_name("20260101T000001"), age_days=100)
    report = _no_action_run(tmp_path, policy=_quarantine_policy(),
                            admit=_Admit({0, 1}))
    assert report.snapshot_actions_blocked is True
    assert report.reserve_ok is False
    assert report.snapshot_eligible == 4          # complete, not selected
    assert report.telemetry_eligible == 0
    assert report.planned_actions == ()
    assert report.planned_actions_count == 0
    assert report.moved == 0
    assert not _quarantine_root(tmp_path).exists()


def test_a_no_action_pass_leaves_a_full_directory_scannable(tmp_path):
    """A directory sitting at exactly `max_directory_entries` must still be
    scannable on the next pass. One created root entry would end that."""
    count = 6
    for index in range(count):
        _write(tmp_path, _snap_name(index, index), age_days=400 + index)
    policy = _no_action_policy(entries=count)

    first = _no_action_run(tmp_path, policy=policy)
    assert first.refused is None
    assert first.planned_actions == ()
    assert first.processed == count
    assert len(list(tmp_path.iterdir())) == count

    second = _no_action_run(tmp_path, policy=policy,
                            pass_id="p20260101T000001")
    assert second.refused is not (
        retention.RetentionFailureReason.ENTRY_LIMIT_EXCEEDED)
    assert second.refused is None
    assert second.processed == count


@pytest.mark.parametrize("entries", [0, 1, 5, 6])
def test_a_no_action_pass_never_grows_the_directory(tmp_path, entries):
    for index in range(entries):
        _write(tmp_path, _snap_name(index, index), age_days=400 + index)
    policy = _no_action_policy(entries=max(entries, 1))
    report = _no_action_run(tmp_path, policy=policy)
    assert report.planned_actions == ()
    assert len(list(tmp_path.iterdir())) == entries
    assert not _quarantine_root(tmp_path).exists()


def test_a_no_action_report_keeps_its_mode_counters_and_status(tmp_path):
    _populate(tmp_path, snapshots=4)
    report = _no_action_run(tmp_path)
    assert report.mode == retention.RetentionMode.QUARANTINE.value
    assert report.refused is None
    assert report.processed == 4
    assert report.inspected == 4
    assert report.snapshot_eligible == 0
    assert report.telemetry_eligible == 0
    assert report.ambiguous == 0
    assert report.planned_actions_count == 0
    assert report.moved == 0
    assert report.skipped == 0
    assert report.unmanifested == 0
    assert report.halted is False
    assert report.reserve_ok is True
    assert report.snapshot_actions_blocked is False
    line = retention.format_report(report)
    assert "mode=quarantine" in line
    assert "refused=none" in line
    assert "planned=0" in line
    assert "moved=0" in line


def test_timestamp_ambiguity_still_refuses_before_the_no_action_return(
        tmp_path):
    _populate(tmp_path, snapshots=3)
    _write(tmp_path, _snap_name(900, 900), age_days=-5)      # future-dated
    report = _no_action_run(tmp_path)
    assert report.refused is (
        retention.RetentionFailureReason.TIMESTAMP_AMBIGUOUS)
    assert report.ambiguous == 1
    assert not _quarantine_root(tmp_path).exists()


def test_an_invalid_pass_identifier_still_precedes_the_no_action_return(
        tmp_path):
    _populate(tmp_path, snapshots=4)
    report = _no_action_run(tmp_path, pass_id="../escape")
    assert report.refused is retention.RetentionFailureReason.PASS_ID_INVALID
    assert not _quarantine_root(tmp_path).exists()


def test_the_platform_gate_still_precedes_the_no_action_return(tmp_path):
    """With no injected mover the platform gate is checked before anything is
    created. Where it does not fire, the no-action path must still create
    nothing, so this control is meaningful on both platforms."""
    _populate(tmp_path, snapshots=4)
    report = _no_action_run(tmp_path, mover=None)
    if os.name == "nt":
        assert report.refused is not (
            retention.RetentionFailureReason.QUARANTINE_PLATFORM_UNSUPPORTED)
    else:
        assert report.refused is (
            retention.RetentionFailureReason.QUARANTINE_PLATFORM_UNSUPPORTED)
    assert not _quarantine_root(tmp_path).exists()


def test_a_non_directory_data_root_still_refuses_identity_unavailable(
        tmp_path):
    """The scan reports a missing or non-directory target as an EMPTY SUCCESS,
    so the no-action path must re-prove the root rather than inherit a clean
    report from a target that is not a directory."""
    plain = tmp_path / "not_a_directory"
    plain.write_bytes(b"x")
    report = _no_action_run(plain)
    assert report.refused is (
        retention.RetentionFailureReason.IDENTITY_UNAVAILABLE)
    assert report.moved == 0
    assert report.planned_actions == ()


def test_a_missing_data_root_still_refuses_identity_unavailable(tmp_path):
    report = _no_action_run(tmp_path / "gone")
    assert report.refused is (
        retention.RetentionFailureReason.IDENTITY_UNAVAILABLE)
    assert report.moved == 0
    assert report.planned_actions == ()


def test_a_nonempty_quarantine_pass_still_creates_its_state(tmp_path):
    """The correction must not disturb the ordinary path."""
    _populate(tmp_path, snapshots=4)
    report = retention.run_pass(
        tmp_path, policy=_quarantine_policy(),
        mode=retention.RetentionMode.QUARANTINE, now_ns=NOW,
        pass_id="p20260101T000000", admit=_Admit({0, 1, 2}),
        mover=_injected_mover)
    assert report.planned_actions
    assert report.moved == len(report.planned_actions)
    root = _quarantine_root(tmp_path)
    assert root.is_dir()
    assert (root / "p20260101T000000").is_dir()
    assert (root / "p20260101T000000" / retention.MANIFEST_NAME).is_file()


# ---------------------------------------------------------------------------
# A manifest close failure must be a refusal, not an escaping exception
# ---------------------------------------------------------------------------
#
# `_quarantine` closes the journal in a `finally`. If that close raises -- an
# underlying storage error is the obvious way -- the exception escapes AFTER
# files have already moved, so the caller loses the whole aggregate: how many
# were moved, how many skipped, how many are now evidence without a record.
# The CLI prints a traceback instead of the fixed, path-free line.
#
# The fault is injected against the MANIFEST DESCRIPTOR SPECIFICALLY. A blanket
# `os.close` failure would break unrelated descriptors and pytest's own
# cleanup, and would prove nothing about this path. The injector releases the
# descriptor for real before raising, so nothing leaks.


class _ManifestCloseFault:
    """Fail the close of the quarantine manifest, for ONE descriptor lifetime.

    `retention.os` is the process-global `os` module, so patching `os.close`
    here is global for the duration of the test. That is only safe while the
    injector matches exactly one descriptor lifetime, because a file
    descriptor is a NUMBER the operating system recycles the moment it is
    released -- the next `os.open` can hand the same integer to something
    entirely unrelated.

    So the target is retired BEFORE the real close, not after. Clearing it
    afterwards would leave a window in which the number has already been
    released and reissued while the injector still matched it, which would
    fail an unrelated close and inflate `close_attempts` -- the very counter
    the "exactly one close attempt" control depends on. Retiring first makes
    the match strictly one-shot: this descriptor, this lifetime, once.
    """

    def __init__(self, monkeypatch, *, fail=True):
        self.fail = fail
        self.target_fd = None
        self.close_attempts = []
        self.opened = 0
        real_open_manifest = retention._open_manifest
        real_close = os.close

        def _open_manifest(pass_directory):
            fd = real_open_manifest(pass_directory)
            self.opened += 1
            self.target_fd = fd
            return fd

        def _close(fd):
            if self.target_fd is not None and fd == self.target_fd:
                self.close_attempts.append(fd)
                # Retire the target FIRST: from here the number may be reissued
                # at any moment, and every later close must delegate.
                self.target_fd = None
                real_close(fd)          # release for real: never leak an fd
                if self.fail:
                    raise OSError(errno.EIO, "injected manifest close failure")
                return None
            return real_close(fd)

        monkeypatch.setattr(retention, "_open_manifest", _open_manifest)
        monkeypatch.setattr(retention.os, "close", _close)


def _identity_breaking_mover(source, destination):
    """Move, then replace the arrival with a distinct object.

    That makes the post-move identity comparison fail, which is a DIFFERENT
    and more specific refusal than a close failure -- exactly what a close
    failure must not overwrite.
    """
    _injected_mover(source, destination)
    os.unlink(destination)
    with open(destination, "wb") as handle:
        handle.write(b"\x00" * 7)


def test_a_manifest_close_failure_does_not_escape_run_pass(tmp_path,
                                                           monkeypatch):
    _populate(tmp_path, snapshots=5)
    fault = _ManifestCloseFault(monkeypatch)
    report = _run(tmp_path)                       # must not raise
    assert isinstance(report, retention.PassReport)
    assert fault.close_attempts


def test_a_close_failure_after_a_recorded_move_reports_a_halted_refusal(
        tmp_path, monkeypatch):
    _populate(tmp_path, snapshots=5)
    fault = _ManifestCloseFault(monkeypatch)
    report = _run(tmp_path)
    assert report.refused is (
        retention.RetentionFailureReason.MANIFEST_RECORD_FAILED)
    assert report.halted is True
    assert report.moved == 4                      # every eligible entry moved
    assert report.skipped == 0
    assert report.planned_actions_count == 4
    assert fault.opened == 1


def test_a_close_failure_alone_never_increments_unmanifested(tmp_path,
                                                             monkeypatch):
    """Each record completed its bounded write and `fsync` before the close,
    so nothing is evidence-without-a-record."""
    _populate(tmp_path, snapshots=5)
    _ManifestCloseFault(monkeypatch)
    report = _run(tmp_path)
    assert report.unmanifested == 0


def test_a_close_failure_does_not_overwrite_an_earlier_refusal(tmp_path,
                                                               monkeypatch):
    _populate(tmp_path, snapshots=5)
    _ManifestCloseFault(monkeypatch)
    report = _run(tmp_path, mover=_identity_breaking_mover)
    assert report.refused is (
        retention.RetentionFailureReason.IDENTITY_MISMATCH_AFTER_MOVE)
    assert report.halted is True
    assert report.unmanifested == 1


def test_the_manifest_descriptor_receives_exactly_one_close_attempt(
        tmp_path, monkeypatch):
    _populate(tmp_path, snapshots=5)
    fault = _ManifestCloseFault(monkeypatch)
    _run(tmp_path)
    assert len(fault.close_attempts) == 1


def test_a_successful_manifest_close_keeps_the_successful_report(tmp_path,
                                                                 monkeypatch):
    _populate(tmp_path, snapshots=5)
    fault = _ManifestCloseFault(monkeypatch, fail=False)
    report = _run(tmp_path)
    assert report.refused is None
    assert report.halted is False
    assert report.moved == 4
    assert report.unmanifested == 0
    assert len(fault.close_attempts) == 1


def test_an_empty_action_pass_never_opens_or_closes_a_manifest(tmp_path,
                                                               monkeypatch):
    _populate(tmp_path, snapshots=4)
    fault = _ManifestCloseFault(monkeypatch)
    report = _no_action_run(tmp_path)
    assert report.planned_actions == ()
    assert fault.opened == 0
    assert fault.close_attempts == []
    assert not _quarantine_root(tmp_path).exists()


def test_a_record_failure_then_a_close_failure_stays_one_halted_refusal(
        tmp_path, monkeypatch):
    _populate(tmp_path, snapshots=5)
    fault = _ManifestCloseFault(monkeypatch)

    def _boom(fd, action, now_ns):
        raise OSError(errno.EIO, "injected record failure")

    monkeypatch.setattr(retention, "_record", _boom)
    report = _run(tmp_path)
    assert report.refused is (
        retention.RetentionFailureReason.MANIFEST_RECORD_FAILED)
    assert report.halted is True
    assert report.moved == 1                # stopped at the first record
    assert report.unmanifested == 1         # that one object, not the close
    assert len(fault.close_attempts) == 1


def test_a_close_failure_report_leaks_no_path_or_exception_text(tmp_path,
                                                                monkeypatch):
    _populate(tmp_path, snapshots=5)
    _ManifestCloseFault(monkeypatch)
    report = _run(tmp_path)
    line = retention.format_report(report)
    assert "manifest_record_failed" in line
    assert "halted=True" in line
    for leak in ("injected", "EIO", "Errno", "Traceback", "manifest.jsonl",
                 str(tmp_path), tmp_path.name, "\\\\", "/"):
        assert leak not in line, leak


# ---------------------------------------------------------------------------
# An idle pass must still refuse an unusable quarantine root
# ---------------------------------------------------------------------------
#
# The no-action return deliberately skips `_quarantine`, which is what stops a
# zero-action pass creating quarantine state. But `_quarantine` was also the
# only place an EXISTING `.retention_quarantine` was validated, so skipping it
# silently dropped that refusal: a root that is a plain file, a reparse point,
# identity-less, or on another volume produced a clean `refused=none` while
# being unusable for the very next action-bearing pass.
#
# The distinction the correction must draw is three-way, not two-way:
#   absent                      -> valid no-op, and create nothing
#   present and usable, same volume -> valid no-op
#   present and unusable        -> QUARANTINE_ROOT_INVALID
#
# Reparse, device and identity cases use CONTROLLED METADATA rather than real
# symlinks or mount points: those need privileges CI does not have, and the
# suite already establishes this seam for the action-bearing path.


def _fake_quarantine_root_metadata(monkeypatch, directory, *, replace=None,
                                   raise_with=None):
    """Fake `.retention_quarantine`'s metadata ONLY, leaving all else real."""
    real_lstat = os.lstat
    target = os.path.normcase(os.fspath(_quarantine_root(directory)))

    def _lstat(path, *args, **kwargs):
        if os.path.normcase(os.fspath(path)) == target:
            if raise_with is not None:
                raise raise_with
            return replace(real_lstat(path, *args, **kwargs))
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(retention.os, "lstat", _lstat)


def _idle_dir(directory, snapshots=4):
    """A directory whose entries are all protected, so no action is planned."""
    return _populate(directory, snapshots=snapshots)


def test_an_idle_pass_refuses_a_quarantine_root_that_is_a_plain_file(tmp_path):
    _idle_dir(tmp_path)
    _quarantine_root(tmp_path).write_bytes(b"x")
    report = _no_action_run(tmp_path)
    assert report.planned_actions == ()
    assert report.refused is (
        retention.RetentionFailureReason.QUARANTINE_ROOT_INVALID)
    assert report.moved == 0


def test_an_idle_pass_refuses_a_reparse_point_quarantine_root(tmp_path,
                                                              monkeypatch):
    _idle_dir(tmp_path)
    _quarantine_root(tmp_path).mkdir()
    reparse = getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    _fake_quarantine_root_metadata(
        monkeypatch, tmp_path,
        replace=lambda info: _Stat(mode=info.st_mode, size=info.st_size,
                                   mtime_ns=info.st_mtime_ns, nlink=1,
                                   dev=info.st_dev, ino=info.st_ino,
                                   file_attributes=reparse))
    report = _no_action_run(tmp_path)
    assert report.refused is (
        retention.RetentionFailureReason.QUARANTINE_ROOT_INVALID)


def test_an_idle_pass_refuses_a_quarantine_root_on_another_device(tmp_path,
                                                                  monkeypatch):
    """A same-volume rename is the entire basis for the move being a
    directory-entry operation, so a root that has become a mount point
    elsewhere is unusable even when nothing is being moved today."""
    _idle_dir(tmp_path)
    _quarantine_root(tmp_path).mkdir()
    _fake_quarantine_root_metadata(
        monkeypatch, tmp_path,
        replace=lambda info: _Stat(mode=info.st_mode, size=info.st_size,
                                   mtime_ns=info.st_mtime_ns, nlink=1,
                                   dev=info.st_dev + 1, ino=info.st_ino))
    report = _no_action_run(tmp_path)
    assert report.refused is (
        retention.RetentionFailureReason.QUARANTINE_ROOT_INVALID)


def test_an_idle_pass_refuses_a_quarantine_root_without_identity(tmp_path,
                                                                 monkeypatch):
    _idle_dir(tmp_path)
    _quarantine_root(tmp_path).mkdir()
    _fake_quarantine_root_metadata(
        monkeypatch, tmp_path,
        replace=lambda info: _Stat(mode=info.st_mode, size=info.st_size,
                                   mtime_ns=info.st_mtime_ns, nlink=1,
                                   dev=0, ino=0))
    report = _no_action_run(tmp_path)
    assert report.refused is (
        retention.RetentionFailureReason.QUARANTINE_ROOT_INVALID)


def test_an_idle_pass_refuses_an_unreadable_quarantine_root(tmp_path,
                                                            monkeypatch):
    """Only `FileNotFoundError` means absent. Any other metadata failure is a
    root that exists and cannot be proved, which fails closed."""
    _idle_dir(tmp_path)
    _quarantine_root(tmp_path).mkdir()
    _fake_quarantine_root_metadata(
        monkeypatch, tmp_path,
        raise_with=OSError(errno.EACCES, "injected metadata failure"))
    report = _no_action_run(tmp_path)
    assert report.refused is (
        retention.RetentionFailureReason.QUARANTINE_ROOT_INVALID)


def test_an_idle_pass_accepts_an_absent_quarantine_root_and_creates_nothing(
        tmp_path):
    made = _idle_dir(tmp_path)
    before = sorted(path.name for path in tmp_path.iterdir())
    report = _no_action_run(tmp_path)
    assert report.refused is None
    assert report.planned_actions == ()
    assert not _quarantine_root(tmp_path).exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == before
    assert all(path.exists() for path in made)


def test_an_idle_pass_accepts_a_valid_existing_quarantine_root(tmp_path):
    _idle_dir(tmp_path)
    root = _quarantine_root(tmp_path)
    root.mkdir()
    report = _no_action_run(tmp_path)
    assert report.refused is None
    assert report.planned_actions == ()
    assert root.is_dir()
    assert list(root.iterdir()) == []          # no pass directory, no manifest


def test_an_invalid_data_root_still_outranks_the_quarantine_root_check(
        tmp_path):
    """The data root is proved first: a target that is not a directory can
    have no meaningful quarantine root to judge."""
    plain = tmp_path / "not_a_directory"
    plain.write_bytes(b"x")
    report = _no_action_run(plain)
    assert report.refused is (
        retention.RetentionFailureReason.IDENTITY_UNAVAILABLE)


def test_timestamp_ambiguity_still_outranks_an_unusable_quarantine_root(
        tmp_path):
    _idle_dir(tmp_path, snapshots=3)
    _write(tmp_path, _snap_name(900, 900), age_days=-5)      # future-dated
    _quarantine_root(tmp_path).write_bytes(b"x")
    report = _no_action_run(tmp_path)
    assert report.refused is (
        retention.RetentionFailureReason.TIMESTAMP_AMBIGUOUS)


def test_an_invalid_pass_identifier_still_outranks_an_unusable_root(tmp_path):
    _idle_dir(tmp_path)
    _quarantine_root(tmp_path).write_bytes(b"x")
    report = _no_action_run(tmp_path, pass_id="../escape")
    assert report.refused is retention.RetentionFailureReason.PASS_ID_INVALID


def test_the_platform_gate_still_outranks_an_unusable_quarantine_root(
        tmp_path):
    _idle_dir(tmp_path)
    _quarantine_root(tmp_path).write_bytes(b"x")
    report = _no_action_run(tmp_path, mover=None)
    if os.name == "nt":
        assert report.refused is (
            retention.RetentionFailureReason.QUARANTINE_ROOT_INVALID)
    else:
        assert report.refused is (
            retention.RetentionFailureReason.QUARANTINE_PLATFORM_UNSUPPORTED)


def test_an_action_bearing_pass_is_unchanged_by_the_idle_root_check(tmp_path):
    _populate(tmp_path, snapshots=4)
    report = retention.run_pass(
        tmp_path, policy=_quarantine_policy(),
        mode=retention.RetentionMode.QUARANTINE, now_ns=NOW,
        pass_id="p20260101T000000", admit=_Admit({0, 1, 2}),
        mover=_injected_mover)
    assert report.refused is None
    assert report.planned_actions
    assert report.moved == len(report.planned_actions)
    root = _quarantine_root(tmp_path)
    assert (root / "p20260101T000000" / retention.MANIFEST_NAME).is_file()


def test_an_exactly_full_directory_with_a_valid_root_stays_exactly_full(
        tmp_path):
    count = 6
    for index in range(count - 1):
        _write(tmp_path, _snap_name(index, index), age_days=400 + index)
    _quarantine_root(tmp_path).mkdir()          # the sixth entry
    policy = _no_action_policy(entries=count)

    first = _no_action_run(tmp_path, policy=policy)
    assert first.refused is None
    assert first.planned_actions == ()
    assert first.processed == count
    assert len(list(tmp_path.iterdir())) == count

    second = _no_action_run(tmp_path, policy=policy,
                            pass_id="p20260101T000001")
    assert second.refused is None
    assert second.processed == count
    assert len(list(tmp_path.iterdir())) == count


# ---------------------------------------------------------------------------
# The manifest close fault must bind to ONE descriptor lifetime
# ---------------------------------------------------------------------------
#
# `_ManifestCloseFault` patches `retention.os.close`, and `retention.os` IS the
# process-global `os` module -- so the patch is global for the test. That is
# tolerable only while the injector matches exactly one descriptor lifetime.
# It matches on the fd NUMBER and never clears `target_fd`, and the operating
# system recycles fd numbers freely: once the manifest descriptor is released,
# the very next `os.open` can hand the same integer to something unrelated,
# and closing THAT would take the injected failure and inflate the
# exactly-one-close-attempt counter the close controls depend on.
#
# These assert the invariant directly rather than waiting for the platform to
# recycle a number, so they are deterministic on every OS.


def test_the_manifest_close_fault_retires_its_target_after_one_lifetime(
        tmp_path, monkeypatch):
    _populate(tmp_path, snapshots=5)
    fault = _ManifestCloseFault(monkeypatch)
    report = _run(tmp_path)
    assert report.refused is (
        retention.RetentionFailureReason.MANIFEST_RECORD_FAILED)
    assert len(fault.close_attempts) == 1
    assert fault.target_fd is None


def test_a_successful_manifest_close_also_retires_the_target(tmp_path,
                                                             monkeypatch):
    _populate(tmp_path, snapshots=5)
    fault = _ManifestCloseFault(monkeypatch, fail=False)
    report = _run(tmp_path)
    assert report.refused is None
    assert len(fault.close_attempts) == 1
    assert fault.target_fd is None


def test_a_recycled_descriptor_number_is_not_treated_as_the_manifest(
        tmp_path, monkeypatch):
    """The decisive control: reopen until the released number comes back, then
    close it. A live injector would fail that close and count it twice."""
    _populate(tmp_path, snapshots=5)
    fault = _ManifestCloseFault(monkeypatch)
    _run(tmp_path)
    assert len(fault.close_attempts) == 1
    released = fault.close_attempts[0]

    spare = tmp_path / "recycled_probe"
    spare.write_bytes(b"x")
    handles = []
    recycled = None
    try:
        for _ in range(64):
            handle = os.open(spare, os.O_RDONLY)
            if handle == released:
                recycled = handle
                break
            handles.append(handle)
    finally:
        for handle in handles:
            os.close(handle)

    if recycled is not None:
        os.close(recycled)                    # must NOT raise the injection
    assert len(fault.close_attempts) == 1


def test_the_manifest_close_fault_leaks_no_descriptor(tmp_path, monkeypatch):
    _populate(tmp_path, snapshots=5)
    probe = tmp_path / "watermark"
    probe.write_bytes(b"x")

    def _watermark():
        handle = os.open(probe, os.O_RDONLY)
        os.close(handle)
        return handle

    before = _watermark()
    fault = _ManifestCloseFault(monkeypatch)
    _run(tmp_path)
    after = _watermark()
    assert len(fault.close_attempts) == 1
    assert after <= before + 1


# ===========================================================================
# D1 -- an ACTION-BEARING pass must not create the quarantine root when the
#       directory is already at its own entry bound
# ===========================================================================
#
# The no-action correction above closed exactly one half of this. The scan
# charges EVERY yielded root entry against `max_directory_entries` and refuses
# one past it, so creating `.retention_quarantine` costs the data root one
# top-level entry it may not have. An action-bearing pass reaches
# `_validated_quarantine_root`, which creates that root unconditionally --
# and every planned move can still be SKIPPED (an open handle, an identity
# change, quiescence), leaving a net +1 and a directory no later pass can
# scan.
#
# Absence must be proved by `FileNotFoundError` specifically. A root that
# exists but cannot be read costs no headroom at all and is the more specific
# `QUARANTINE_ROOT_INVALID`.


def _headroom_policy(entries, **kwargs):
    base = dict(entries=entries, combined=1_000, snap=1_000, telem=1_000,
                ceiling=8_192, floor=1)
    base.update(kwargs)
    return _tiny(**base)


def _headroom_run(directory, policy, pass_id="p20260101T000000",
                  mover=_injected_mover, admit=None):
    return retention.run_pass(
        directory, policy=policy,
        mode=retention.RetentionMode.QUARANTINE, now_ns=NOW,
        pass_id=pass_id,
        admit=admit if admit is not None else _Admit({0, 1, 2}),
        mover=mover)


def test_an_action_bearing_pass_at_the_entry_limit_refuses_and_creates_nothing(
        tmp_path):
    count = 6
    _populate(tmp_path, snapshots=count)
    before = sorted(path.name for path in tmp_path.iterdir())
    report = _headroom_run(tmp_path, _headroom_policy(count))
    assert report.planned_actions, "the fixture must be action-bearing"
    assert report.refused is (
        retention.RetentionFailureReason.ENTRY_LIMIT_EXCEEDED)
    assert report.moved == 0
    assert report.skipped == 0
    assert report.unmanifested == 0
    assert not _quarantine_root(tmp_path).exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == before


def test_the_entry_limit_refusal_calls_no_mover(tmp_path):
    def _forbidden(source, destination):     # pragma: no cover - must not run
        raise AssertionError("a mover ran on a refused pass")

    _populate(tmp_path, snapshots=6)
    report = _headroom_run(tmp_path, _headroom_policy(6), mover=_forbidden)
    assert report.refused is (
        retention.RetentionFailureReason.ENTRY_LIMIT_EXCEEDED)
    assert report.moved == 0


def test_one_below_the_entry_limit_still_creates_the_root_and_moves(tmp_path):
    count = 6
    _populate(tmp_path, snapshots=count)
    report = _headroom_run(tmp_path, _headroom_policy(count + 1))
    assert report.refused is None
    assert report.moved == report.planned_actions_count
    assert report.moved > 0
    assert _quarantine_root(tmp_path).is_dir()


def test_past_the_entry_limit_the_scan_itself_still_refuses(tmp_path):
    count = 6
    _populate(tmp_path, snapshots=count)
    report = _headroom_run(tmp_path, _headroom_policy(count - 1))
    assert report.refused is (
        retention.RetentionFailureReason.ENTRY_LIMIT_EXCEEDED)
    assert report.planned_actions == ()
    assert not _quarantine_root(tmp_path).exists()


def test_a_directory_refused_for_headroom_is_still_scannable(tmp_path):
    count = 6
    _populate(tmp_path, snapshots=count)
    policy = _headroom_policy(count)
    first = _headroom_run(tmp_path, policy)
    assert first.refused is (
        retention.RetentionFailureReason.ENTRY_LIMIT_EXCEEDED)

    rescan = retention.scan_retention_candidates(tmp_path, policy=policy)
    assert isinstance(rescan, retention.ScanSucceeded)
    assert rescan.processed == count

    second = _headroom_run(tmp_path, policy, pass_id="p20260101T000001")
    assert second.refused is (
        retention.RetentionFailureReason.ENTRY_LIMIT_EXCEEDED)
    assert second.processed == count
    assert not _quarantine_root(tmp_path).exists()


def test_an_existing_root_at_the_entry_limit_still_acts(tmp_path):
    """A root that already exists costs no headroom, so the pass proceeds and
    the top-level count cannot grow."""
    count = 6
    _populate(tmp_path, snapshots=count)
    _quarantine_root(tmp_path).mkdir()
    entries = count + 1                    # the files plus the root itself
    before = len(list(tmp_path.iterdir()))
    report = _headroom_run(tmp_path, _headroom_policy(entries))
    assert report.refused is None
    assert report.moved > 0
    assert len(list(tmp_path.iterdir())) <= before


def test_an_existing_root_at_the_entry_limit_permits_an_all_skipped_pass(
        tmp_path):
    """Nothing eligible, a valid root already present: a clean no-op that does
    not grow the directory."""
    count = 6
    _populate(tmp_path, snapshots=count)
    _quarantine_root(tmp_path).mkdir()
    entries = count + 1
    before = len(list(tmp_path.iterdir()))
    report = _headroom_run(tmp_path, _headroom_policy(entries, floor=50))
    assert report.planned_actions == ()
    assert report.refused is None
    assert len(list(tmp_path.iterdir())) == before


def test_a_present_but_invalid_root_at_the_limit_is_root_invalid_not_the_limit(
        tmp_path):
    """Precedence: a root that EXISTS consumes no headroom, so the specific
    refusal for an unusable root wins."""
    count = 6
    _populate(tmp_path, snapshots=count)
    _quarantine_root(tmp_path).write_bytes(b"not a directory")
    report = _headroom_run(tmp_path, _headroom_policy(count + 1))
    assert report.refused is (
        retention.RetentionFailureReason.QUARANTINE_ROOT_INVALID)
    assert report.moved == 0


def _root_lstat_error(monkeypatch, error):
    real_lstat = os.lstat

    def _patched(path, *args, **kwargs):
        if os.path.basename(os.fspath(path)) == retention.QUARANTINE_DIRNAME:
            raise error
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(retention.os, "lstat", _patched)


def test_an_unreadable_root_is_not_absence_and_is_never_created(
        tmp_path, monkeypatch):
    """`directory_state(root) is None` conflates ABSENT with PRESENT-and-
    unprovable. Only `FileNotFoundError` is absence; anything else is a root
    that exists, and no `mkdir` may be attempted against it."""
    _populate(tmp_path, snapshots=6)
    _root_lstat_error(monkeypatch,
                      PermissionError(errno.EACCES, "permission denied"))
    report = _headroom_run(tmp_path, _headroom_policy(1_000))
    assert report.refused is (
        retention.RetentionFailureReason.QUARANTINE_ROOT_INVALID)
    assert report.moved == 0
    assert not _quarantine_root(tmp_path).exists(), (
        "a refusal created the very root it refused")


def test_an_absent_root_below_the_limit_is_still_created(tmp_path):
    """The `FileNotFoundError` branch is the ONLY creating branch."""
    _populate(tmp_path, snapshots=6)
    report = _headroom_run(tmp_path, _headroom_policy(1_000))
    assert report.refused is None
    assert _quarantine_root(tmp_path).is_dir()


@pytest.mark.parametrize("offset,expected_refusal,expects_root", [
    (-1, retention.RetentionFailureReason.ENTRY_LIMIT_EXCEEDED, False),
    (0, retention.RetentionFailureReason.ENTRY_LIMIT_EXCEEDED, False),
    (1, None, True),
])
def test_the_entry_bound_is_exact_at_limit_minus_one_limit_and_limit_plus_one(
        tmp_path, offset, expected_refusal, expects_root):
    count = 6
    _populate(tmp_path, snapshots=count)
    report = _headroom_run(tmp_path, _headroom_policy(count + offset))
    assert report.refused is expected_refusal
    assert _quarantine_root(tmp_path).exists() is expects_root


def test_an_invalid_pass_identifier_precedes_the_headroom_refusal(tmp_path):
    _populate(tmp_path, snapshots=6)
    report = _headroom_run(tmp_path, _headroom_policy(6), pass_id="../escape")
    assert report.refused is retention.RetentionFailureReason.PASS_ID_INVALID
    assert not _quarantine_root(tmp_path).exists()


def test_timestamp_ambiguity_precedes_the_headroom_refusal(tmp_path):
    _populate(tmp_path, snapshots=5)
    _write(tmp_path, _snap_name(900, 900), age_days=-5)      # future-dated
    report = _headroom_run(tmp_path, _headroom_policy(6))
    assert report.refused is (
        retention.RetentionFailureReason.TIMESTAMP_AMBIGUOUS)
    assert not _quarantine_root(tmp_path).exists()


def test_a_reserve_check_failure_precedes_the_headroom_refusal(tmp_path):
    def _boom(path, *, data_dir, policy=None):
        raise RuntimeError("unexpected")

    _populate(tmp_path, snapshots=6)
    report = _headroom_run(tmp_path, _headroom_policy(6), admit=_boom)
    assert report.refused is (
        retention.RetentionFailureReason.RESERVE_CHECK_FAILED)
    assert not _quarantine_root(tmp_path).exists()


def test_an_unusable_data_root_precedes_the_headroom_refusal(tmp_path,
                                                             monkeypatch):
    _populate(tmp_path, snapshots=6)
    real_lstat = os.lstat

    def _identityless(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if os.fspath(path) == os.fspath(tmp_path):
            return _Stat(mode=info.st_mode, size=info.st_size,
                         mtime_ns=info.st_mtime_ns, nlink=1, dev=0, ino=0)
        return info

    monkeypatch.setattr(retention.os, "lstat", _identityless)
    report = _headroom_run(tmp_path, _headroom_policy(6))
    assert report.refused is (
        retention.RetentionFailureReason.IDENTITY_UNAVAILABLE)
    assert not _quarantine_root(tmp_path).exists()


def test_the_headroom_refusal_introduces_no_deletion_primitive():
    source = Path(retention.__file__).read_text(encoding="utf-8")
    for banned in ("os.unlink", "os.remove", "os.rmdir", "shutil.rmtree",
                   "shutil."):
        assert banned not in source, banned
# ===========================================================================
# D2 -- a LIVE `PLAN` must prove the data root's usable directory identity
# ===========================================================================
#
# `scan_retention_candidates` reports a missing or non-directory target as an
# EMPTY SUCCESSFUL scan -- correct in isolation, because there is nothing to
# maintain -- and `os.scandir` FOLLOWS a reparse-point root, so a junction
# scans its target while being somewhere no pass may act. `QUARANTINE` proves
# the root on both its branches. `PLAN` proves nothing at all, so a live dry
# run over any of the three prints a clean report and exits 0.
#
# The proof is taken ONLY when `scan is None`, i.e. when this invocation
# actually read the live filesystem. An injected scan represents an object
# this invocation did NOT read: validating the supplied path would prove the
# wrong object and couple a synthetic analysis to the working directory.


def _live_plan(directory, policy=None):
    return retention.run_pass(
        directory, policy=policy or _quarantine_policy(),
        mode=retention.RetentionMode.PLAN, now_ns=NOW,
        admit=_Admit({0, 1, 2}))


def test_a_live_plan_over_a_missing_root_refuses_identity_unavailable(
        tmp_path):
    report = _live_plan(tmp_path / "gone")
    assert report.refused is (
        retention.RetentionFailureReason.IDENTITY_UNAVAILABLE)
    assert report.planned_actions == ()
    assert not (tmp_path / "gone").exists()


def test_a_live_plan_over_a_plain_file_refuses_identity_unavailable(tmp_path):
    plain = tmp_path / "not_a_directory"
    plain.write_bytes(b"x")
    report = _live_plan(plain)
    assert report.refused is (
        retention.RetentionFailureReason.IDENTITY_UNAVAILABLE)
    assert report.planned_actions == ()
    assert plain.read_bytes() == b"x"


def test_a_live_plan_over_a_reparse_root_refuses_identity_unavailable(
        tmp_path, monkeypatch):
    _populate(tmp_path, snapshots=4)
    real_lstat = os.lstat
    reparse = getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

    def _junction(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if os.fspath(path) == os.fspath(tmp_path):
            return _Stat(mode=info.st_mode, size=info.st_size,
                         mtime_ns=info.st_mtime_ns, nlink=1,
                         dev=info.st_dev or 41, ino=info.st_ino or 7,
                         file_attributes=reparse)
        return info

    monkeypatch.setattr(retention.os, "lstat", _junction)
    report = _live_plan(tmp_path)
    assert report.refused is (
        retention.RetentionFailureReason.IDENTITY_UNAVAILABLE)


def test_a_live_plan_over_an_identityless_root_refuses(tmp_path, monkeypatch):
    _populate(tmp_path, snapshots=4)
    real_lstat = os.lstat

    def _identityless(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if os.fspath(path) == os.fspath(tmp_path):
            return _Stat(mode=info.st_mode, size=info.st_size,
                         mtime_ns=info.st_mtime_ns, nlink=1, dev=0, ino=0)
        return info

    monkeypatch.setattr(retention.os, "lstat", _identityless)
    report = _live_plan(tmp_path)
    assert report.refused is (
        retention.RetentionFailureReason.IDENTITY_UNAVAILABLE)


def test_a_live_plan_over_a_healthy_root_still_reports_cleanly(tmp_path):
    _populate(tmp_path, snapshots=4)
    report = _live_plan(tmp_path)
    assert report.refused is None
    assert report.planned_actions
    assert not _quarantine_root(tmp_path).exists()


def test_a_live_plan_refusal_creates_nothing(tmp_path):
    target = tmp_path / "gone"
    _live_plan(target)
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_a_live_plan_never_inspects_or_creates_the_quarantine_root(
        tmp_path, monkeypatch):
    _populate(tmp_path, snapshots=4)
    seen = []
    real_lstat = os.lstat

    def _watch(path, *args, **kwargs):
        if retention.QUARANTINE_DIRNAME in os.fspath(path):
            seen.append(os.fspath(path))
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(retention.os, "lstat", _watch)
    report = _live_plan(tmp_path)
    assert report.refused is None
    assert seen == []
    assert not _quarantine_root(tmp_path).exists()


def test_an_injected_scan_plan_is_not_coupled_to_the_working_directory(
        tmp_path, monkeypatch):
    """The justification for the bypass, made checkable. A synthetic analysis
    names an object this invocation never read, so the report must not depend
    on whether that name happens to resolve from the current directory."""
    scan = _built_scan(snapshots=_aged_snapshots(600, age_days=400))
    monkeypatch.chdir(tmp_path)
    report = retention.run_pass(
        "data", policy=retention.PRODUCTION_RETENTION_POLICY,
        mode=retention.RetentionMode.PLAN, now_ns=NOW, scan=scan,
        admit=_Admit({0, 1, 2}))
    assert report.refused is None
    assert report.planned_actions
    assert not (tmp_path / "data").exists()


def test_an_injected_scan_plan_over_a_missing_path_still_reports(tmp_path):
    scan = _built_scan(snapshots=_aged_snapshots(600, age_days=400))
    report = retention.run_pass(
        tmp_path / "never_existed",
        policy=retention.PRODUCTION_RETENTION_POLICY,
        mode=retention.RetentionMode.PLAN, now_ns=NOW, scan=scan,
        admit=_Admit({0, 1, 2}))
    assert report.refused is None
    assert report.planned_actions


def test_standalone_scan_semantics_for_missing_and_plain_targets_are_kept(
        tmp_path):
    """The scan's own contract is unchanged: nothing to maintain is a clean,
    successful, empty outcome. Only `run_pass` adds the proof."""
    policy = _quarantine_policy()
    missing = retention.scan_retention_candidates(tmp_path / "gone",
                                                  policy=policy)
    assert isinstance(missing, retention.ScanSucceeded)
    assert (missing.processed, missing.inspected, missing.excluded) == (0, 0, 0)
    plain = tmp_path / "plain"
    plain.write_bytes(b"x")
    result = retention.scan_retention_candidates(plain, policy=policy)
    assert isinstance(result, retention.ScanSucceeded)
    assert (result.processed, result.inspected, result.excluded) == (0, 0, 0)


def test_the_cli_exits_nonzero_for_a_missing_target(tmp_path, capsys):
    status = retention.main([str(tmp_path / "gone")])
    printed = capsys.readouterr()
    assert status == 1
    assert (retention.RetentionFailureReason.IDENTITY_UNAVAILABLE.value
            in printed.out)
    assert str(tmp_path) not in printed.out


def test_the_cli_exits_nonzero_for_a_non_directory_target(tmp_path, capsys):
    plain = tmp_path / "plain"
    plain.write_bytes(b"x")
    status = retention.main([str(plain)])
    capsys.readouterr()
    assert status == 1


def test_the_cli_still_exits_zero_for_a_healthy_directory(tmp_path, capsys):
    _populate(tmp_path, snapshots=3)
    status = retention.main([str(tmp_path)])
    printed = capsys.readouterr()
    assert status == 0
    assert "refused=none" in printed.out


def test_quarantine_precedence_over_an_unusable_root_is_unchanged(tmp_path):
    """`PLAN` gains a proof; `QUARANTINE` keeps the one it always had, in the
    same place, with the same reason, and injection stays refused outright."""
    missing = _headroom_run(tmp_path / "gone", _headroom_policy(1_000))
    assert missing.refused is (
        retention.RetentionFailureReason.IDENTITY_UNAVAILABLE)
    plain = tmp_path / "plain"
    plain.write_bytes(b"x")
    assert _headroom_run(plain, _headroom_policy(1_000)).refused is (
        retention.RetentionFailureReason.IDENTITY_UNAVAILABLE)
    with pytest.raises(ValueError):
        retention.run_pass(tmp_path, policy=_headroom_policy(1_000),
                           mode=retention.RetentionMode.QUARANTINE,
                           now_ns=NOW, pass_id="p20260101T000000",
                           scan=_built_scan())
