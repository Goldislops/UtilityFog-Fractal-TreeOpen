"""Tests for `scripts/snapshot_retention.py` -- stage-one bounded retention.

Stage one is `PLAN` and recoverable `QUARANTINE` only. There is no `DELETE`,
no automatic reaping, no automatic restoration, no scheduler and no execution
of a serialized plan. Nothing here touches the real `data/` directory. A
population is one of exactly three things: a `ScanSucceeded` built DIRECTLY
from `CandidateEntry` values by `_built_scan`, which never goes near a
filesystem and is what the large planner and reserve populations use; an
injected fake `scandir` for the scanner controls; or a handful of real files
in pytest's own `tmp_path` for the quarantine controls. Only the first is ever
production-sized, and it creates no directory at all -- no test creates a
production-sized directory on disk.

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


def _dir_stat(dev=41, ino=9_000_001, **kwargs):
    """A directory `_Stat` with a stable identity, as `os.lstat` reports one."""
    kwargs.setdefault("mode", stat_module.S_IFDIR | 0o755)
    return _Stat(dev=dev, ino=ino, **kwargs)


class _FakeScandir:
    """A recording stand-in for `os.scandir`, yielding `_Entry` objects.

    Also serves the SCANNED ROOT's own metadata, because the scanner reads the
    directory's stable identity around the open and again after the
    enumeration. Root reads are counted separately and never appear in
    `statted`, which stays a record of what the pass did to ENTRIES.

    `root_stats` supplies successive answers for those reads, which is how a
    root replaced or removed part-way through one pass is expressed.

    `root` is known at CONSTRUCTION, not at the call: the scanner's first
    reading of the directory is taken before `os.scandir` is reached at all,
    and a fake that only learned its own pathname once it was called would
    answer that first reading with `FileNotFoundError` and turn every control
    here into an identity refusal.
    """

    def __init__(self, entries, open_error=None, iteration_error_after=None,
                 root_stat=None, root_stats=None, root="data"):
        self.entries = list(entries)
        self.open_error = open_error
        self.iteration_error_after = iteration_error_after
        self.yielded = []
        self.statted = []
        self.closed = 0
        self.root = os.fspath(root)
        self.root_reads = 0
        self.root_stat = _dir_stat() if root_stat is None else root_stat
        self.root_stats = None if root_stats is None else list(root_stats)
        self.by_name = {}
        for entry in self.entries:
            entry.recorder = self
            self.by_name[entry.name] = entry

    def _root_answer(self):
        self.root_reads += 1
        if self.root_stats is not None:
            index = min(self.root_reads - 1, len(self.root_stats) - 1)
            answer = self.root_stats[index]
        else:
            answer = self.root_stat
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def lstat(self, path, *args, **kwargs):
        """The scanner's one authoritative non-following read."""
        target = os.fspath(path)
        if self.root is not None and target == self.root:
            return self._root_answer()
        name = os.path.basename(target)
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
        self.root = os.fspath(directory)
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


#: The two request handlers that share `scripts/` with the retention module.
_REQUEST_HANDLER_MODULES = ("medusa_api", "lucid_server")


def _handler_imports(module_name):
    """Every module name `module_name` imports, by static parse.

    Both node kinds are collected, and `ImportFrom` contributes its module AND
    each imported alias qualified onto it, so `from scripts import
    snapshot_retention` is caught by the alias arm even though its `node.module`
    is only `scripts`. A relative import carries no absolute module name, so its
    written dotted form is recorded instead of being silently dropped.
    """
    import ast as _ast
    path = Path(retention.__file__).parent / (module_name + ".py")
    source = path.read_text(encoding="utf-8")
    assert source.strip(), path
    collected = []
    for node in _ast.walk(_ast.parse(source)):
        if isinstance(node, _ast.Import):
            collected.extend(alias.name for alias in node.names)
        elif isinstance(node, _ast.ImportFrom):
            prefix = "." * node.level + (node.module or "")
            collected.append(prefix)
            collected.extend(prefix + "." + alias.name for alias in node.names)
    return collected


_IMPORT_FORMS = [
    "import scripts.snapshot_retention",
    "import scripts.snapshot_retention as _r",
    "from scripts import snapshot_retention",
    "from scripts.snapshot_retention import scan_retention_candidates",
    "from . import snapshot_retention",
    "from .snapshot_retention import scan_retention_candidates",
]


@pytest.mark.parametrize("form", _IMPORT_FORMS)
def test_the_handler_import_collector_sees_every_import_form(form):
    """Non-vacuity for the control below, WITHOUT requiring either handler to
    import anything.

    Zero imports in a request handler is a legitimately safe state, so the
    collector must not be validated by "the list came back non-empty". It is
    validated against this fixture instead. Two of these forms --
    `from scripts import snapshot_retention` and `from . import
    snapshot_retention` -- are invisible to a per-node check on
    `ImportFrom.module`, which is why the collector qualifies aliases onto
    their module and records the relative prefix.
    """
    import ast as _ast
    collected = []
    for node in _ast.walk(_ast.parse(form + chr(10))):
        if isinstance(node, _ast.Import):
            collected.extend(alias.name for alias in node.names)
        elif isinstance(node, _ast.ImportFrom):
            prefix = "." * node.level + (node.module or "")
            collected.append(prefix)
            collected.extend(prefix + "." + alias.name for alias in node.names)
    assert any("snapshot_retention" in name for name in collected), (
        form, collected)


def test_the_module_is_not_importable_from_a_request_handler():
    """A retention scan must never be reachable from an unauthenticated GET.

    Imports from BOTH handlers are collected first and judged in ONE assertion
    over the collected result, so this cannot pass merely by walking a tree
    that produced no import nodes.

    Zero imports is a legitimately SAFE state and is deliberately not required
    to be non-empty. What is pinned instead is that both named files were
    located, read with content, and parsed -- the failure mode a per-node
    assertion inside a loop cannot distinguish from success.
    """
    collected = {name: _handler_imports(name)
                 for name in _REQUEST_HANDLER_MODULES}
    assert sorted(collected) == sorted(_REQUEST_HANDLER_MODULES)
    offenders = sorted(
        (module_name, imported)
        for module_name, names in collected.items()
        for imported in names
        if "snapshot_retention" in imported)
    assert offenders == [], offenders


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
    r"""Eight positions x three scripts: `\d` is observable at every one.

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
        reserve_window=1, reserve_required=1)


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
    # The root's own metadata must be missing too. A fixture whose `os.scandir`
    # says "no such directory" while its `os.lstat` reports a healthy one is
    # not a missing directory at all -- it is a directory that vanished under
    # the pass, which is a different outcome and has its own control.
    _install(monkeypatch, _FakeScandir([], open_error=FileNotFoundError(
        errno.ENOENT, "No such file or directory"),
        root_stat=FileNotFoundError(errno.ENOENT, "no such file")))
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
    """The scan must SUCCEED and carry the whole fixture population first.

    A `ScanFailed`, or a success that collected nothing, would satisfy the
    per-entry loop below by never entering it. The expected population is the
    exact two basenames `_populate` writes, not merely "non-empty".
    """
    _populate(tmp_path, snapshots=2)
    result = retention.scan_retention_candidates(
        tmp_path, policy=_quarantine_policy())
    assert isinstance(result, retention.ScanSucceeded)
    assert sorted(entry.basename for entry in result.snapshots) == [
        _snap_name(0, 0), _snap_name(1, 1)]
    assert result.telemetry == ()
    for entry in result.snapshots:
        assert entry.dev != 0 and entry.ino != 0
        real = os.lstat(tmp_path / entry.basename)
        assert (entry.dev, entry.ino) == (real.st_dev, real.st_ino)


def test_a_planned_action_carries_the_identity_it_was_planned_on(tmp_path):
    """No refusal, and the exact planned population, before the per-action loop.

    `_quarantine_policy` has `floor=1`, so of the three entries `_populate`
    writes -- index 0 newest, each successive index a day older -- the floor
    protects index 0 and exactly indices 1 and 2 are planned. A refusal, or a
    plan that selected nothing, would otherwise pass here by never looping.
    """
    _populate(tmp_path, snapshots=3)
    report = _run(tmp_path, mode=retention.RetentionMode.PLAN)
    assert report.refused is None
    assert sorted(action.basename for action in report.planned_actions) == [
        _snap_name(1, 1), _snap_name(2, 2)]
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
    real_open = os.open
    real_fstat = os.fstat
    target = {"fd": None}

    def _tracking_open(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        try:
            is_manifest = (os.path.basename(os.fspath(path))
                           == retention.MANIFEST_NAME)
        except TypeError:
            is_manifest = False
        if is_manifest:
            target["fd"] = fd
        return fd

    def _not_regular(fd):
        info = real_fstat(fd)
        if fd != target["fd"]:
            return info
        return _Stat(mode=stat_module.S_IFIFO | 0o600, size=0, mtime_ns=0,
                     nlink=1, dev=info.st_dev, ino=info.st_ino)

    monkeypatch.setattr(retention.os, "open", _tracking_open)
    monkeypatch.setattr(retention.os, "fstat", _not_regular)
    closed = []
    real_close = os.close

    def _tracking_close(fd):
        if fd == target["fd"]:
            closed.append(fd)
        return real_close(fd)

    monkeypatch.setattr(retention.os, "close", _tracking_close)
    report = _run(tmp_path)
    assert report.refused is retention.RetentionFailureReason.MANIFEST_CREATE_FAILED
    assert target["fd"] is not None, "the manifest descriptor was never opened"
    assert closed == [target["fd"]], (
        "the manifest descriptor was leaked or closed more than once")


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
                            admit=_Admit(set()))
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
    target_info = real_lstat(_quarantine_root(directory))
    target_identity = (target_info.st_dev, target_info.st_ino)

    def _lstat(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if (info.st_dev, info.st_ino) == target_identity:
            if raise_with is not None:
                raise raise_with
            return replace(info)
        return info

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
# It matches on the fd NUMBER, and the operating system recycles fd numbers
# freely: once the manifest descriptor is released, the very next `os.open` can
# hand the same integer to something unrelated, and closing THAT would take the
# injected failure and inflate the exactly-one-close-attempt counter the close
# controls depend on. The injector therefore clears `target_fd` BEFORE the real
# close, and these controls are what hold it to that.
#
# These assert the retirement invariant directly rather than waiting for the
# platform to recycle a number, so they are deterministic on every OS.


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
    """Reopen until the released number comes back, then close it: a live
    injector would fail that close and count it twice.

    Recycling is the platform's choice, so `recycled` may stay None and the
    reissue arm may not execute on a given run. The retirement invariant that
    makes recycling harmless is proved unconditionally by the two controls
    above; this one adds the real-reissue observation when the platform
    offers it, and its close-attempt count is asserted either way.
    """
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


# ===========================================================================
# P2 -- a live scan binds the identity of the directory it actually scanned
# ===========================================================================
#
# The scan retained a full stable identity for every candidate FILE and none
# at all for the DIRECTORY it enumerated, so nothing downstream could tell
# "this path is a usable directory" from "this path is still the directory
# this pass read". A root renamed or replaced after the iterator closed was
# therefore accepted, and `_quarantine` went on to create the quarantine root,
# the pass directory and the manifest inside a directory no pass ever scanned.
# The per-file checks could not prevent that: they skip planned ACTIONS, and
# skipping every action still leaves the tree created.


def test_a_successful_scan_carries_the_scanned_roots_identity(monkeypatch):
    _install(monkeypatch, _FakeScandir(_snapshots(3),
                                       root_stat=_dir_stat(dev=41, ino=777)))
    result = _scan()
    assert isinstance(result, retention.ScanSucceeded)
    assert result.root_identity == (41, 777)


def test_the_root_identity_is_read_exactly_three_times_and_never_as_an_entry(
        monkeypatch):
    """Bounded: three reads per pass whatever the directory holds, and none of
    them is charged to the per-entry accounting the limits are built on.

    Three, not two, and each one brackets something different: one before
    `os.scandir` and one immediately after it bracket the OPEN, which is where
    a handle and a pathname part company; the third, after the iterator
    closes, brackets the ENUMERATION. Two reads on the same side of the open
    can only ever agree with each other about the wrong directory.
    """
    fake = _install(monkeypatch, _FakeScandir(_snapshots(64)))
    result = _scan()
    assert isinstance(result, retention.ScanSucceeded)
    assert fake.root_reads == 3
    assert len(fake.statted) == 64
    assert all(name != fake.root for name, _ in fake.statted)
    assert result.processed == 64 and result.inspected == 64


_UNUSABLE_ROOTS = [
    ("zero_device", _dir_stat(dev=0, ino=5)),
    ("zero_inode", _dir_stat(dev=41, ino=0)),
    ("reparse_point", _dir_stat(
        file_attributes=stat_module.FILE_ATTRIBUTE_REPARSE_POINT)),
    ("not_a_directory", _Stat(mode=stat_module.S_IFREG | 0o644, dev=41,
                              ino=5)),
    ("unreadable", PermissionError(errno.EACCES, "denied")),
]


@pytest.mark.parametrize("label,root_stat", _UNUSABLE_ROOTS,
                         ids=[label for label, _ in _UNUSABLE_ROOTS])
def test_a_root_without_a_usable_identity_fails_the_scan_closed(
        monkeypatch, label, root_stat):
    """`os.scandir` FOLLOWS a reparse point and enumerates its target quite
    happily, and a platform that reports a zero device or inode has supplied
    no identity at all. Neither may become a success nothing can bind to."""
    fake = _install(monkeypatch, _FakeScandir(_snapshots(3),
                                              root_stat=root_stat))
    result = _scan()
    assert isinstance(result, retention.ScanFailed)
    assert result.reason is retention.RetentionFailureReason.IDENTITY_UNAVAILABLE
    assert (result.processed, result.inspected) == (0, 0)
    assert fake.statted == [], "entries were read before the root was proved"
    assert fake.closed == 1, "the scandir handle was not released"
    assert not hasattr(result, "snapshots")


#: Each is THREE answers, not two: the change must land after the open has
#: been bracketed by two agreeing readings, or it would be caught at the open
#: instead and this control would silently stop covering the window it names.
_CHANGED_ROOTS = [
    ("replaced", [_dir_stat(ino=1), _dir_stat(ino=1), _dir_stat(ino=2)]),
    ("moved_to_another_volume", [_dir_stat(dev=41, ino=1),
                                 _dir_stat(dev=41, ino=1),
                                 _dir_stat(dev=42, ino=1)]),
    ("removed", [_dir_stat(ino=1), _dir_stat(ino=1),
                 FileNotFoundError(errno.ENOENT, "no such file")]),
    ("became_a_reparse_point", [_dir_stat(ino=1), _dir_stat(ino=1),
                                _dir_stat(ino=1, file_attributes=(
                                    stat_module.FILE_ATTRIBUTE_REPARSE_POINT))]),
    ("lost_its_identity", [_dir_stat(ino=1), _dir_stat(ino=1),
                           _dir_stat(dev=0, ino=0)]),
]


@pytest.mark.parametrize("label,root_stats", _CHANGED_ROOTS,
                         ids=[label for label, _ in _CHANGED_ROOTS])
def test_a_root_replaced_during_the_scan_discards_the_whole_pass(
        monkeypatch, label, root_stats):
    """The open handle keeps enumerating the ORIGINAL object while every
    per-entry `os.lstat(root / name)` resolves by PATH into the replacement,
    so the two halves of one scan would describe two different directories.

    The change lands AFTER the open, so all three readings are taken and the
    pass is discarded by the last of them -- the enumeration window, not the
    open window, which has its own controls.
    """
    fake = _install(monkeypatch, _FakeScandir(_snapshots(5),
                                              root_stats=root_stats))
    result = _scan()
    assert isinstance(result, retention.ScanFailed)
    assert result.reason is retention.RetentionFailureReason.IDENTITY_UNAVAILABLE
    assert fake.root_reads == 3
    assert not hasattr(result, "snapshots")


def test_a_content_change_inside_the_same_root_is_not_a_replacement(
        monkeypatch):
    """Identity is `(device, inode)` and NEVER the file four-tuple. A
    directory's size and modification time change whenever its contents do --
    which is exactly what a pass that moves entries out of the root it is
    maintaining does -- so a four-tuple comparison would call the pass's own
    legitimate work a swapped directory."""
    before = _dir_stat(ino=55, size=4_096, mtime_ns=NOW - _ns(DAY))
    after = _dir_stat(ino=55, size=8_192, mtime_ns=NOW)
    _install(monkeypatch, _FakeScandir(_snapshots(3),
                                       root_stats=[before, after]))
    result = _scan()
    assert isinstance(result, retention.ScanSucceeded)
    assert result.root_identity == (41, 55)
    assert len(result.snapshots) == 3


# -- the binding is fail-closed on absence, which is what keeps injection safe

def test_an_unbound_scan_can_never_prove_any_path(tmp_path):
    """`None` is the ABSENCE of an identity, not a value. `directory_state`
    also answers `None` for a path that is gone, so a bare equality would let
    an unbound scan "prove" a directory nothing ever read."""
    missing = tmp_path / "gone"
    assert retention._scanned_root_unchanged(tmp_path, None) is False
    assert retention._scanned_root_unchanged(missing, None) is False
    real = retention.directory_state(tmp_path)
    assert real is not None
    assert retention._scanned_root_unchanged(tmp_path, real) is True
    assert retention._scanned_root_unchanged(missing, real) is False


def test_a_synthetic_injected_scan_carries_no_binding():
    assert _built_scan().root_identity is None
    assert _built_scan(
        snapshots=_aged_snapshots(3, age_days=400)).root_identity is None


def test_the_empty_success_paths_carry_no_binding(tmp_path):
    """A missing or non-directory target is still a clean empty success, and
    still carries nothing to bind: there was no directory to identify."""
    policy = _quarantine_policy()
    missing = retention.scan_retention_candidates(tmp_path / "gone",
                                                  policy=policy)
    assert isinstance(missing, retention.ScanSucceeded)
    assert missing.root_identity is None
    plain = tmp_path / "plain"
    plain.write_bytes(b"x")
    result = retention.scan_retention_candidates(plain, policy=policy)
    assert isinstance(result, retention.ScanSucceeded)
    assert result.root_identity is None


# -- the live races, reproduced against a real filesystem --------------------


class _Repointing:
    """The two identities a repointing fixture actually produced."""

    __slots__ = ("before", "after", "blocked")

    def __init__(self):
        self.before = None
        self.after = None
        self.blocked = None


def _repointing_scan(monkeypatch, live, aside, replacement=True):
    """Rename `live` aside AFTER the scan closed, exactly as the defect
    describes, and optionally put a fresh directory back at the name.

    The replacement is allocated WHILE the original still exists and is only
    then renamed over the vacated pathname. Creating it after the rename is
    not enough: a filesystem may hand back the inode number it has just
    released -- ext4 does exactly that -- and the fixture would prove nothing.
    Both identities are recorded so a control can assert the pathname really
    does name a different object, rather than merely that some refusal
    happened.
    """
    real_scan = retention.scan_retention_candidates
    record = _Repointing()

    def _scan_then_repoint(directory, *, policy):
        result = real_scan(directory, policy=policy)
        record.before = _directory_identity(live)
        decoy = Path(os.fspath(live) + ".decoy")
        if replacement:
            decoy.mkdir()
        try:
            os.rename(live, aside)
            if replacement:
                os.rename(decoy, live)
                record.after = _directory_identity(live)
        except OSError as error:
            record.blocked = error
            if decoy.exists():
                decoy.rmdir()
        return result

    monkeypatch.setattr(retention, "scan_retention_candidates",
                        _scan_then_repoint)
    return record


def test_a_live_plan_stays_bound_when_the_path_moves_after_the_scan(
        tmp_path, monkeypatch):
    live = tmp_path / "live"
    live.mkdir()
    _populate(live, snapshots=4)
    record = _repointing_scan(monkeypatch, live, tmp_path / "aside")
    report = _live_plan(live)
    assert record.before is not None, "the original root was never identified"
    if record.blocked is None:
        assert record.after is not None, "no substitute was installed at the name"
        assert record.before != record.after, (
            "the fixture did not actually change the root's identity")
        assert list(live.iterdir()) == [], "PLAN mutated the replacement"
    else:
        assert record.after is None
    assert report.refused is None
    assert report.planned_actions_count == 3
    assert report.moved == 0


def test_quarantine_stays_on_the_scanned_object_when_its_path_is_replaced(
        tmp_path, monkeypatch):
    """A permitted POSIX rename must not redirect any mutation; Windows may
    deny the rename while the same exact-object guarantee remains held."""
    live = tmp_path / "live"
    live.mkdir()
    aside = tmp_path / "aside"
    made = _populate(live, snapshots=6)
    record = _repointing_scan(monkeypatch, live, aside)
    report = _run(live)
    assert record.before is not None, "the original root was never identified"
    assert report.refused is None
    assert report.moved == report.planned_actions_count == 5
    if record.blocked is None:
        assert record.after is not None, "no substitute was installed at the name"
        assert record.before != record.after, (
            "the fixture did not actually change the root's identity")
        assert list(live.iterdir()) == [], "the replacement was mutated"
        assert not _quarantine_root(live).exists(), (
            "quarantine was built in the unscanned replacement")
        assert _quarantine_root(aside).is_dir(), (
            "quarantine did not follow the held scanned object")
        assert sum(path.is_file() for path in aside.iterdir()) == 1
    else:
        assert record.after is None
        assert not aside.exists()
        assert _quarantine_root(live).is_dir()
        assert sum(path.exists() for path in made) == 1


def test_quarantine_stays_on_the_scanned_object_when_its_path_vanishes(
        tmp_path, monkeypatch):
    live = tmp_path / "live"
    live.mkdir()
    aside = tmp_path / "aside"
    _populate(live, snapshots=6)
    record = _repointing_scan(monkeypatch, live, aside, replacement=False)
    report = _run(live)
    assert report.refused is None
    assert report.moved == report.planned_actions_count == 5
    if record.blocked is None:
        assert not live.exists()
        assert _quarantine_root(aside).is_dir()
    else:
        assert live.is_dir()
        assert not aside.exists()
        assert _quarantine_root(live).is_dir()


def test_an_idle_quarantine_pass_stays_bound_after_its_path_is_replaced(
        tmp_path, monkeypatch):
    """The no-action report remains about the held object and creates nothing."""
    live = tmp_path / "live"
    live.mkdir()
    _populate(live, snapshots=2, age_days=0)      # far inside the horizon
    record = _repointing_scan(monkeypatch, live, tmp_path / "aside")
    report = _run(live)
    assert record.before is not None, "the original root was never identified"
    assert report.planned_actions == ()
    assert report.refused is None
    assert not _quarantine_root(live).exists()
    if record.blocked is None:
        assert record.after is not None, "no substitute was installed at the name"
        assert record.before != record.after, (
            "the fixture did not actually change the root's identity")
        assert list(live.iterdir()) == [], "the replacement was mutated"
        assert not _quarantine_root(tmp_path / "aside").exists()
    else:
        assert record.after is None


def test_a_root_that_appears_after_an_empty_scan_is_not_accepted(
        tmp_path, monkeypatch):
    """The empty-success path has nothing to bind, so a directory that turns
    up between the failed `os.scandir` and the check must not be adopted."""
    live = tmp_path / "late"
    real_scan = retention.scan_retention_candidates

    def _scan_then_create(directory, *, policy):
        result = real_scan(directory, policy=policy)
        os.mkdir(live)
        return result

    monkeypatch.setattr(retention, "scan_retention_candidates",
                        _scan_then_create)
    report = _run(live)
    assert report.refused is (
        retention.RetentionFailureReason.IDENTITY_UNAVAILABLE)
    assert list(live.iterdir()) == []


def test_a_root_replaced_mid_batch_stays_on_the_held_original(tmp_path):
    """A pathname swap never redirects the remaining move lifecycle.

    Windows may refuse the rename while the binding is live. Descriptor-based
    POSIX hosts may allow it; there the pass continues on the held original and
    must leave the unscanned replacement byte-for-byte untouched. Both outcomes
    enforce the same boundary without requiring a halt merely because the
    caller's pathname changed.
    """
    live = tmp_path / "live"
    live.mkdir()
    _populate(live, snapshots=6)
    moves = []
    replacement = {"value": None, "blocked": None}
    decoy_name = "unscanned-replacement.txt"

    def _recording_mover(source, destination):
        _injected_mover(source, destination)
        moves.append(os.path.basename(os.fspath(source)))
        if len(moves) == 1:
            try:
                replacement["value"] = _replace_root_pathname(
                    live, contents=(decoy_name,))
            except OSError as error:
                replacement["blocked"] = error

    report = _run(live, mover=_recording_mover)
    assert report.moved == report.planned_actions_count == len(moves) == 5
    assert report.halted is False
    assert report.refused is None
    changed = replacement["value"]
    if changed is None:
        assert replacement["blocked"] is not None
        assert _quarantine_root(live).is_dir()
    else:
        assert changed.before != changed.after
        assert _listing(live) == [decoy_name]
        assert not _quarantine_root(live).exists(), (
            "the remaining lifecycle reached the unscanned replacement")
        pass_directory = (_quarantine_root(changed.displaced)
                          / "p20260101T000000")
        assert pass_directory.is_dir()
        assert len([path for path in pass_directory.iterdir()
                    if path.name != retention.MANIFEST_NAME]) == report.moved


def test_a_stable_root_is_completely_unaffected(tmp_path):
    """Invariant seven, stated directly: the ordinary path does not notice."""
    live = tmp_path / "live"
    live.mkdir()
    _populate(live, snapshots=6)
    # One inside the recovery floor, five actionable.
    planned = _run(live, mode=retention.RetentionMode.PLAN)
    assert planned.refused is None and len(planned.planned_actions) == 5
    report = _run(live)
    assert report.refused is None
    assert report.moved == 5 and report.skipped == 0
    assert not report.halted
    pass_dir = _quarantine_root(live) / "p20260101T000000"
    assert sorted(p.name for p in pass_dir.iterdir()) == sorted(
        [retention.MANIFEST_NAME]
        + [_snap_name(index, index) for index in range(1, 6)])


# ===========================================================================
# P2 -- breadth controls for the scanned-root binding
# ===========================================================================
#
# The block above pins the binding itself. These pin what the binding must NOT
# disturb, the operator-visible consequence, and the sharpest statement of the
# defect: that per-file identity was never able to prevent the DIRECTORY-level
# mutations, because those happen before the loop that does the skipping.


#: Captured at import, before any control can patch `os.lstat`. Several
#: controls below fake the root's metadata AND replace the root, and a
#: non-vacuity proof taken through a faked `lstat` would report the fake's
#: fixed answer for both halves of the comparison and prove nothing.
_REAL_LSTAT = os.lstat


def _directory_identity(path):
    """`(device, inode)` for `path`, read INDEPENDENTLY of the module.

    The non-vacuity proofs below must not be able to agree with the code they
    are judging, so they take their own genuine `os.lstat` rather than calling
    `directory_state`.
    """
    info = _REAL_LSTAT(path)
    return (info.st_dev, info.st_ino)


def _listing(path):
    """The sorted basenames in `path`, via `os.listdir`.

    Deliberately NOT `Path.iterdir`, which on this interpreter enumerates
    through `os.scandir` -- the very primitive some controls replace. A fixture
    that read its own result through the double under test would be reading the
    double's answer.
    """
    return sorted(os.listdir(path))


def _scanned_root(tmp_path, name="data", **populate):
    """A populated data root that is a CHILD of `tmp_path`.

    The replacement controls rename the root itself, so the root may not be
    `tmp_path`: pytest owns that pathname and walks it during teardown.
    """
    root = tmp_path / name
    root.mkdir()
    if populate:
        _populate(root, **populate)
    return root


class _RootReplacement:
    """What one root-pathname replacement actually did.

    `before` and `after` are the two `(device, inode)` pairs the pathname
    named, so a control can assert the swap was REAL rather than merely
    asserting that some refusal happened.
    """

    __slots__ = ("before", "after", "displaced", "decoy_names")

    def __init__(self, before, after, displaced, decoy_names):
        self.before = before
        self.after = after
        self.displaced = displaced
        self.decoy_names = tuple(decoy_names)


def _replace_root_pathname(root, *, contents=(), age_days=400):
    """Make `root` name a DIFFERENT real directory, and report both identities.

    The substitute is allocated WHILE the original still exists and is then
    renamed over the vacated pathname. Removing the original and recreating it
    is not enough: a filesystem is free to hand back the inode number it just
    released -- ext4 does exactly that -- and the fixture would prove nothing.
    Two same-directory renames guarantee two live objects and therefore two
    distinct identities, on Windows and POSIX alike.

    Nothing here is a junction, a symlink or a mount point. The substitute is
    an ordinary directory, which is the point: it satisfies every structural
    check `directory_state` makes and is still not the directory scanned.
    """
    root = Path(os.fspath(root))
    before = _directory_identity(root)
    decoy = root.with_name(root.name + ".decoy")
    decoy.mkdir()
    for name in contents:
        _write(decoy, name, age_days=age_days)
    displaced = root.with_name(root.name + ".displaced")
    os.rename(root, displaced)
    os.rename(decoy, root)
    return _RootReplacement(before, _directory_identity(root), displaced,
                            _listing(root))


class _ScanThatReplacesItsRoot:
    """Wrap the one scan a live pass makes, and swap the root as it returns.

    This is the exact window the defect lives in: the real scan has completed
    and closed its iterator, and no caller has yet re-resolved the pathname.
    `run_pass` looks `scan_retention_candidates` up as a module global, so
    patching it is a deterministic seam -- the same one the existing
    `_scan_then_replace` control uses for a candidate FILE.
    """

    __slots__ = ("_root", "_contents", "_real", "calls", "replacement",
                 "blocked")

    def __init__(self, root, *, contents=()):
        self._root = Path(os.fspath(root))
        self._contents = contents
        self._real = retention.scan_retention_candidates
        self.calls = 0
        self.replacement = None
        self.blocked = None

    def __call__(self, directory, *, policy):
        observed = self._real(directory, policy=policy)
        self.calls += 1
        try:
            self.replacement = _replace_root_pathname(
                self._root, contents=self._contents)
        except OSError as error:
            self.blocked = error
        return observed


def _replace_root_after_the_scan(monkeypatch, root, *, contents=()):
    swap = _ScanThatReplacesItsRoot(root, contents=contents)
    monkeypatch.setattr(retention, "scan_retention_candidates", swap)
    return swap


def test_the_held_root_routes_directory_mutations_to_the_scanned_object(
        tmp_path, monkeypatch):
    """Matching replacement basenames cannot redirect quarantine mutations."""
    root = _scanned_root(tmp_path, snapshots=3)
    names = _listing(root)
    swap = _replace_root_after_the_scan(monkeypatch, root, contents=names)
    report = _headroom_run(root, _headroom_policy(1_000))

    assert report.refused is None
    assert report.skipped == 0
    assert report.moved == report.planned_actions_count == 2
    if swap.replacement is None:
        assert swap.blocked is not None
        assert not (tmp_path / "data.displaced").exists()
        assert _quarantine_root(root).is_dir()
    else:
        assert swap.replacement.before != swap.replacement.after, (
            "the fixture did not actually change the root's identity")
        assert swap.replacement.decoy_names == tuple(names), (
            "the substitute must carry the same names, or it proves nothing")
        assert _listing(root) == names, "the replacement was mutated"
        assert not _quarantine_root(root).exists()
        assert _quarantine_root(swap.replacement.displaced).is_dir()


def test_the_cli_never_reports_over_an_unscanned_root(
        tmp_path, monkeypatch, capsys):
    """The operator-visible consequence, through the real entry point.

    Exit 0 over a directory the pass never read is exactly what the caller
    must never be told.
    """
    root = _scanned_root(tmp_path, snapshots=3)
    swap = _replace_root_after_the_scan(monkeypatch, root)
    status = retention.main([str(root)])
    printed = capsys.readouterr()
    if swap.replacement is None:
        # The CLI now holds the exact target across both the lock and scan.
        # Windows therefore denies the injected rename, and the successful
        # report is genuinely about the directory that was read.
        assert swap.blocked is not None
        assert status == 0
        assert "refused=none" in printed.out
    else:
        # Descriptor-relative platforms may permit the pathname swap. The
        # CLI still scans and reports on the held original object, never the
        # unscanned replacement now occupying the caller's spelling.
        assert swap.replacement.before != swap.replacement.after
        assert status == 0
        assert "refused=none" in printed.out
    assert str(tmp_path) not in printed.out


def test_a_held_root_success_renders_a_path_free_line(tmp_path, monkeypatch):
    """Exact-object continuation keeps the emitted line path-free."""
    root = _scanned_root(tmp_path, snapshots=3)
    swap = _replace_root_after_the_scan(monkeypatch, root)
    line = retention.format_report(
        _headroom_run(root, _headroom_policy(1_000)))
    if swap.replacement is None:
        assert swap.blocked is not None
    else:
        assert swap.replacement.before != swap.replacement.after
    assert "refused=none" in line
    for leak in ("v070_gen", ".npz", "telemetry_", str(tmp_path), "/", "\\",
                 "Traceback", "Errno"):
        assert leak not in line, leak


def test_a_stable_root_still_completes_the_quarantine_lifecycle(tmp_path):
    """Moves and journal, end to end, through the injectable mover.

    This also proves the binding is an IDENTITY check and not a state check:
    the pass itself removes entries from the data root, so the root's size and
    modification time change under it while it runs, and the lifecycle still
    completes.
    """
    root = _scanned_root(tmp_path, snapshots=4)
    before = _directory_identity(root)
    listing_before = _listing(root)
    report = _run(root)

    assert report.refused is None
    assert report.halted is False
    assert report.moved == report.planned_actions_count
    assert report.moved == 3
    assert report.skipped == 0

    pass_directory = _quarantine_root(root) / "p20260101T000000"
    moved = [name for name in _listing(pass_directory)
             if name != retention.MANIFEST_NAME]
    assert moved == sorted(action.basename
                           for action in report.planned_actions)
    records = [json.loads(line) for line in
               (pass_directory / retention.MANIFEST_NAME).read_bytes()
               .decode("utf-8").splitlines()]
    assert sorted(record["basename"] for record in records) == moved

    assert _directory_identity(root) == before, (
        "the data root's identity changed during its own pass")
    assert _listing(root) != listing_before, (
        "the fixture must actually change the root's contents")


def test_an_entry_created_in_the_same_root_is_not_a_replacement(tmp_path,
                                                                monkeypatch):
    """A directory's size and modification time change whenever its contents
    do. Binding on anything but `(device, inode)` would turn an ordinary
    producer write -- the engine appends a snapshot every 600 seconds -- into a
    permanent false mismatch, and retention would never run again."""
    root = _scanned_root(tmp_path, snapshots=4)
    identity = _directory_identity(root)
    listing = _listing(root)
    real_scan = retention.scan_retention_candidates

    def _scan_then_write(directory, *, policy):
        observed = real_scan(directory, policy=policy)
        _write(directory, _snap_name(900, 900), age_days=0)
        return observed

    monkeypatch.setattr(retention, "scan_retention_candidates",
                        _scan_then_write)
    report = _live_plan(root)

    assert _directory_identity(root) == identity, (
        "creating an entry changed the directory's own identity")
    assert _listing(root) != listing, (
        "the fixture did not actually change the directory's contents")
    assert report.refused is None, (
        "an ordinary producer write was read as a root replacement")
    assert report.planned_actions


def test_an_entry_removed_from_the_same_root_is_not_a_replacement(
        tmp_path, monkeypatch):
    """The other direction, and the one a QUARANTINE pass causes itself."""
    root = _scanned_root(tmp_path, snapshots=4)
    identity = _directory_identity(root)
    listing = _listing(root)
    real_scan = retention.scan_retention_candidates

    def _scan_then_remove(directory, *, policy):
        observed = real_scan(directory, policy=policy)
        victim = Path(os.fspath(directory)) / _snap_name(3, 3)
        # Carried OUT of the root, so an entry genuinely leaves. Renaming it
        # in place would change the listing without changing the entry count.
        os.rename(victim, root.parent / "carried_away")
        return observed

    monkeypatch.setattr(retention, "scan_retention_candidates",
                        _scan_then_remove)
    report = _live_plan(root)

    assert _directory_identity(root) == identity
    assert _listing(root) != listing, (
        "the fixture did not actually change the directory's contents")
    assert report.refused is None


def _unusable_root(tmp_path, monkeypatch, shape):
    """One of the four roots no pass may ever act on, plus its pathname."""
    if shape == "missing":
        return tmp_path / "gone"
    if shape == "plain_file":
        plain = tmp_path / "plain"
        plain.write_bytes(b"x")
        return plain

    root = _scanned_root(tmp_path, snapshots=4)
    real_lstat = os.lstat
    target = os.path.normcase(os.fspath(root))
    reparse = getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

    def _patched(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if os.path.normcase(os.fspath(path)) != target:
            return info
        if shape == "reparse":
            return _Stat(mode=info.st_mode, size=info.st_size,
                         mtime_ns=info.st_mtime_ns, nlink=1,
                         dev=info.st_dev or 41, ino=info.st_ino or 7,
                         file_attributes=reparse)
        return _Stat(mode=info.st_mode, size=info.st_size,
                     mtime_ns=info.st_mtime_ns, nlink=1, dev=0, ino=0)

    monkeypatch.setattr(retention.os, "lstat", _patched)
    return root


_UNUSABLE_ROOTS = ["missing", "plain_file", "reparse", "identityless"]


@pytest.mark.parametrize("shape", _UNUSABLE_ROOTS)
def test_an_unusable_root_stays_fail_closed_in_plan(tmp_path, monkeypatch,
                                                    shape):
    """A root that cannot be proved at all was already refused, and still is.

    The binding reuses `IDENTITY_UNAVAILABLE` rather than adding a reason, so
    "no identity available" and "the identity is not the scanned one" report
    the same closed code. Both are truthful -- the scanned directory's identity
    IS unavailable at that path -- and both create nothing, which is what these
    controls pin.
    """
    root = _unusable_root(tmp_path, monkeypatch, shape)
    report = _live_plan(root)
    assert report.refused is (
        retention.RetentionFailureReason.IDENTITY_UNAVAILABLE)


@pytest.mark.parametrize("shape", _UNUSABLE_ROOTS)
def test_an_unusable_root_stays_fail_closed_in_quarantine(tmp_path,
                                                          monkeypatch, shape):
    root = _unusable_root(tmp_path, monkeypatch, shape)
    report = _headroom_run(root, _headroom_policy(1_000))
    assert report.refused is (
        retention.RetentionFailureReason.IDENTITY_UNAVAILABLE)
    assert report.moved == 0
    assert not _quarantine_root(root).exists()


def test_an_injected_scan_reports_the_same_whatever_the_pathname_is(
        tmp_path, monkeypatch):
    """Filesystem-independence made checkable: three different pathnames --
    absent, a real unrelated directory reached relatively, and a plain file --
    must give one identical report from one identical injected scan."""
    real = _scanned_root(tmp_path, snapshots=2)
    identity = _directory_identity(real)
    plain = tmp_path / "plain"
    plain.write_bytes(b"x")

    def _report_for(target):
        return retention.format_report(retention.run_pass(
            target, policy=retention.PRODUCTION_RETENTION_POLICY,
            mode=retention.RetentionMode.PLAN, now_ns=NOW,
            scan=_built_scan(snapshots=_aged_snapshots(600, age_days=400)),
            admit=_Admit({0, 1, 2})))

    monkeypatch.chdir(tmp_path)
    absent = _report_for(tmp_path / "never_existed")
    relative = _report_for("data")
    non_directory = _report_for(plain)
    assert absent == relative == non_directory
    assert "refused=none" in absent
    assert _directory_identity(real) == identity
    assert _listing(real) == [_snap_name(0, 0), _snap_name(1, 1)]


def test_an_injected_scan_is_still_refused_outright_in_quarantine(tmp_path):
    """The bypass exists for analysis only. Nothing about the root binding
    opens a way to hand a mutating pass a scan it did not take."""
    with pytest.raises(ValueError):
        retention.run_pass(tmp_path, policy=_headroom_policy(1_000),
                           mode=retention.RetentionMode.QUARANTINE,
                           now_ns=NOW, pass_id="p20260101T000000",
                           scan=_built_scan())


def test_the_candidate_identity_check_still_owns_the_per_file_case(
        tmp_path, monkeypatch):
    """A replaced FILE inside an unreplaced root is still a SKIP, not a root
    refusal. The two corrections sit at different levels and neither may
    swallow the other."""
    root = _scanned_root(tmp_path, snapshots=3)
    identity = _directory_identity(root)
    victim = _snap_name(2, 2)
    real_scan = retention.scan_retention_candidates

    def _scan_then_replace_the_file(directory, *, policy):
        observed = real_scan(directory, policy=policy)
        path = Path(os.fspath(directory)) / victim
        info = os.lstat(path)
        swap = path.with_name(path.name + ".swap")
        swap.write_bytes(path.read_bytes())
        os.utime(swap, ns=(info.st_mtime_ns, info.st_mtime_ns))
        os.replace(swap, path)
        return observed

    monkeypatch.setattr(retention, "scan_retention_candidates",
                        _scan_then_replace_the_file)
    report = _run(root)
    assert _directory_identity(root) == identity, (
        "the fixture replaced the root, not the file")
    assert report.refused is None
    assert report.skipped >= 1
    assert (root / victim).exists(), "a replaced object was moved"


def test_the_reserve_shortfall_refill_is_unchanged_under_the_binding(
        tmp_path):
    root = _scanned_root(tmp_path)
    for index in range(5):
        _write(root, _snap_name(index, index), age_days=400 + index)
    for index in range(3):
        _write(root, _telem_name("2026010%dT00000%d" % (index, index)),
               age_days=300 + index)
    report = _run(root, admit=_Admit(set()))
    assert report.reserve_ok is False
    assert report.snapshot_actions_blocked is True
    assert report.refused is None
    assert report.moved == 2
    assert all(action.klass == retention.TELEMETRY_CLASS
               for action in report.planned_actions)


def test_the_entry_headroom_refusal_is_unchanged_under_the_binding(tmp_path):
    root = _scanned_root(tmp_path, snapshots=6)
    before = _listing(root)
    report = _headroom_run(root, _headroom_policy(6))
    assert report.planned_actions, "the fixture must be action-bearing"
    assert report.refused is (
        retention.RetentionFailureReason.ENTRY_LIMIT_EXCEEDED)
    assert not _quarantine_root(root).exists()
    assert _listing(root) == before


def test_the_survey_is_untouched_by_the_data_root_binding(tmp_path):
    """Reconciliation reads a pass directory, never the data root, so the
    DATA-ROOT binding has nothing to say about it.

    Named for the binding it is about. The survey has since gained a
    binding of its own -- taken on the pass directory handed in, and
    proved across enumeration and the journal read -- so "untouched by
    the root binding" must not be read as "has no binding at all"."""
    root = _scanned_root(tmp_path, snapshots=3)
    _run(root)
    pass_directory = _quarantine_root(root) / "p20260101T000000"
    survey = retention.survey_quarantine(pass_directory,
                                         policy=_quarantine_policy())
    assert survey.refused is None
    assert survey.present == 2
    assert survey.manifested == 2
    assert survey.unmanifested == 0


def test_the_public_surface_carries_only_the_bound_root(tmp_path):
    """The whole correction is one optional field and one PRIVATE helper.

    `__all__`, every public signature and the closed reason set are what other
    code and other passes depend on; a correction that quietly widened any of
    them would be a different change from the one that was authorized.
    """
    assert len(retention.__all__) == 34
    assert "root_identity" not in retention.__all__
    assert "_scanned_root_unchanged" not in retention.__all__
    assert len(list(retention.RetentionFailureReason)) == 20
    fields = [field.name for field in
              dataclasses.fields(retention.ScanSucceeded)]
    assert fields == ["snapshots", "telemetry", "processed", "inspected",
                      "excluded", "root_identity"]
    # Backward compatible: every pre-existing five-positional construction
    # still works, and records no binding.
    legacy = retention.ScanSucceeded((), (), 0, 0, 0)
    assert legacy.root_identity is None


# ===========================================================================
# P3 -- the open-to-first-proof window
# ===========================================================================
#
# `scan_retention_candidates` acquires its iterator FIRST and proves the root
# SECOND:
#
#     iterator = os.scandir(root)
#     ...
#     root_identity = directory_state(root)
#
# A substitute installed between those two statements leaves the handle
# enumerating the ORIGINAL object while BOTH of the scan's proofs -- the one
# taken before the first entry and the one taken after the iterator closes --
# read the SUBSTITUTE and agree with each other. The scan therefore SUCCEEDS,
# bound to a directory it never opened; `run_pass` proves the same pathname
# again, gets the same agreeing answer, and goes on to build the quarantine
# tree inside the substitute and move the substitute's files.
#
# The two proofs bracket the ENUMERATION. They do not bracket the OPEN, and
# the open is where the handle and the pathname part company.
#
# Nothing here sleeps, threads or races. The window is entered by wrapping
# `os.scandir` itself: the wrapper acquires the real iterator, performs the
# substitution, and only then hands back the iterator it already holds. That
# is the window exactly, in one thread, in a fixed order, on every platform.

#: Non-allowlisted on both sides, so neither is ever classified, statted,
#: planned or moved. They exist only so a control can say WHICH object a
#: handle was enumerating instead of inferring it from a listing that both
#: directories would satisfy equally well.
_ORIGINAL_MARKER = "enumerated_the_original.marker"
_REPLACEMENT_MARKER = "installed_at_the_pathname.marker"


class _RecordedIterator:
    """The real `os.scandir` iterator, with its yields and its close recorded.

    The scanner uses the iterator as a context manager on both of its paths --
    `with iterator as entries:` around the enumeration, and a bare
    `with iterator: pass` when it refuses before iterating -- so those three
    methods are the whole surface. Nothing is filtered, reordered or withheld:
    every entry the real iterator produces is passed straight through, which
    is what makes `yielded` evidence of which directory the handle was on
    rather than of what the fixture wished it were.
    """

    __slots__ = ("_real", "yielded", "closed")

    def __init__(self, real):
        self._real = real
        self.yielded = []
        self.closed = 0

    def __enter__(self):
        self._real.__enter__()
        return self

    def __exit__(self, *exc):
        self.closed += 1
        return self._real.__exit__(*exc)

    def __iter__(self):
        for entry in self._real:
            self.yielded.append(entry.name)
            yield entry

    def undrained(self):
        """What the REAL handle still has to give.

        A closed `os.ScandirIterator` yields nothing; an open one over a
        populated directory yields its entries. Only meaningful where the
        handle was never iterated -- which is every refusing control here, and
        is why an empty answer there means released rather than exhausted.
        """
        return [entry.name for entry in self._real]


class _ScandirThatMovesTheRootUnderTheOpen:
    """`os.scandir`, wrapped so a substitution lands in one exact window.

    `when="after_open"` is the defect's own window: acquire the real iterator
    over the ORIGINAL object, replace the pathname, then return the iterator
    already acquired. `when="before_open"` puts the substitution on the other
    side of the same call, which is the window a PRE-OPEN proof creates and
    must also close. `when="never"` substitutes nothing at all, so a control
    can prove the seam itself refuses nothing.

    `vanish` renames the root away and puts nothing back, so the real
    `os.scandir` raises `FileNotFoundError` over a pathname that WAS a real
    directory when the pass proved it moments earlier.

    Only the pass's own FIRST enumeration is interfered with. A control's own
    assertions -- and `os.walk` below -- go through the untouched primitive.
    """

    __slots__ = ("_root", "_contents", "_when", "_vanish", "_real",
                 "calls", "replacement", "displaced", "iterators",
                 "blocked")

    def __init__(self, root, *, contents=(), when="after_open", vanish=False):
        self._root = Path(os.fspath(root))
        self._contents = tuple(contents)
        self._when = when
        self._vanish = vanish
        self._real = os.scandir
        self.calls = 0
        self.replacement = None
        self.displaced = None
        self.iterators = []
        self.blocked = None

    def _substitute(self):
        if self._when == "never":
            return
        try:
            if self._vanish:
                self.displaced = self._root.with_name(
                    self._root.name + ".displaced")
                os.rename(self._root, self.displaced)
                return
            self.replacement = _replace_root_pathname(
                self._root, contents=self._contents)
            self.displaced = self.replacement.displaced
        except OSError as error:
            self.blocked = error
            decoy = self._root.with_name(self._root.name + ".decoy")
            if decoy.exists():
                for child in decoy.iterdir():
                    child.unlink()
                decoy.rmdir()

    def _wrap(self, iterator):
        recorded = _RecordedIterator(iterator)
        self.iterators.append(recorded)
        return recorded

    def __call__(self, directory):
        self.calls += 1
        if self.calls > 1:
            return self._real(directory)
        if self._when == "before_open":
            self._substitute()
            return self._wrap(self._real(directory))
        iterator = self._real(directory)
        self._substitute()
        return self._wrap(iterator)


def _move_the_root_under_the_open(monkeypatch, root, **kwargs):
    swap = _ScandirThatMovesTheRootUnderTheOpen(root, **kwargs)
    monkeypatch.setattr(retention.os, "scandir", swap)
    return swap


def _root_and_matching_substitute(tmp_path, snapshots=3):
    """A populated root, its eligible names, and the substitute's contents.

    The substitute is given the SAME eligible allowlisted names, so a refusal
    can never be the trivial consequence of it holding nothing worth acting
    on: every structural check, every classification and every age comparison
    succeeds on it just as well as on the original. What differs is WHICH
    object the pathname names, and that is the only thing left for a refusal
    to be about.
    """
    root = _scanned_root(tmp_path, snapshots=snapshots)
    names = _listing(root)
    _write(root, _ORIGINAL_MARKER, age_days=400)
    return root, names, list(names) + [_REPLACEMENT_MARKER]


def _manifests_beneath(tmp_path):
    """Every journal beneath `tmp_path`, walked through the real primitive."""
    found = []
    for directory, _subdirectories, files in os.walk(tmp_path):
        if retention.MANIFEST_NAME in files:
            found.append(directory)
    return found


# -- fixture integrity, proved without the module under test -----------------

def test_an_open_handle_and_its_pathname_really_do_part_company(tmp_path):
    """Every control below rests on one claim about the platform: a directory
    renamed out from under an already-acquired `os.scandir` handle keeps being
    enumerated THROUGH THAT HANDLE, while the pathname it used to have
    resolves to the substitute. If that were not true here, the controls would
    be refusing for some entirely different reason and would prove nothing
    about the window they name.

    So it is asserted rather than assumed, and asserted using no retention
    code at all.
    """
    root, names, contents = _root_and_matching_substitute(tmp_path)
    handle = _RecordedIterator(os.scandir(root))
    replacement = _replace_root_pathname(root, contents=contents)
    with handle as entries:
        enumerated = sorted(entry.name for entry in entries)

    assert replacement.before is not None
    assert replacement.after is not None
    assert replacement.before != replacement.after, (
        "the two directories were never given distinct identities")
    assert _ORIGINAL_MARKER in enumerated, (
        "the handle stopped enumerating the object it was opened on")
    assert _REPLACEMENT_MARKER not in enumerated, (
        "the handle followed the pathname instead of the object")
    assert _REPLACEMENT_MARKER in _listing(root), (
        "the pathname did not come to name the substitute")
    assert _ORIGINAL_MARKER not in _listing(root)
    assert sorted(name for name in enumerated
                  if name != _ORIGINAL_MARKER) == sorted(names), (
        "both directories must carry the same eligible names")
    assert handle.closed == 1


def test_the_window_wrapper_refuses_nothing_when_it_substitutes_nothing(
        tmp_path, monkeypatch):
    """The seam is not the refusal. Installed with no substitution at all, the
    same wrapper leaves an ordinary pass entirely alone: the scan succeeds,
    binds the root it enumerated, and the quarantine lifecycle completes.
    """
    root, names, _contents = _root_and_matching_substitute(tmp_path)
    swap = _move_the_root_under_the_open(monkeypatch, root, when="never")
    identity = _directory_identity(root)
    report = _headroom_run(root, _headroom_policy(1_000))

    assert swap.calls == 1
    assert swap.replacement is None
    handle, = swap.iterators
    assert handle.closed == 1
    assert sorted(handle.yielded) == sorted(names + [_ORIGINAL_MARKER])
    assert report.refused is None
    assert report.halted is False
    assert report.moved == report.planned_actions_count
    assert report.moved >= 1, "the fixture must be action-bearing"
    assert _directory_identity(root) == identity
    assert _quarantine_root(root).exists()


# -- the window itself, at the level it opens in -----------------------------

def test_the_scanner_refuses_a_root_replaced_between_the_open_and_the_proof(
        tmp_path, monkeypatch):
    """The defect. The handle is on the original; both of the scan's proofs
    are on the substitute; the two proofs agree with each other and neither
    has anything to do with what was enumerated. A scan that returns success
    here hands every later step a binding to a directory it never opened, and
    every later step then re-proves that same binding successfully.
    """
    root, names, contents = _root_and_matching_substitute(tmp_path)
    swap = _move_the_root_under_the_open(monkeypatch, root, contents=contents)
    result = retention.scan_retention_candidates(
        root, policy=_headroom_policy(1_000))

    assert swap.calls == 1
    assert swap.replacement.before is not None
    assert swap.replacement.after is not None
    assert swap.replacement.before != swap.replacement.after, (
        "the fixture did not actually change the root's identity")
    assert set(names) <= set(swap.replacement.decoy_names), (
        "the substitute must carry the same eligible names, or a refusal "
        "could be a name mismatch and nothing more")

    assert isinstance(result, retention.ScanFailed), (
        "the scan succeeded while bound to a directory it never enumerated")
    assert result.reason is (
        retention.RetentionFailureReason.IDENTITY_UNAVAILABLE)
    assert not hasattr(result, "snapshots")
    assert not hasattr(result, "telemetry")
    assert (result.processed, result.inspected) == (0, 0), (
        "entries were read inside a root the pass had not proved")


def test_the_refused_open_is_released_and_never_enumerated(tmp_path,
                                                           monkeypatch):
    """A refusal that leaked the handle would pin the original directory open
    for as long as the process lived, on the very platform whose rename
    semantics this module is built around.
    """
    root, _names, contents = _root_and_matching_substitute(tmp_path)
    swap = _move_the_root_under_the_open(monkeypatch, root, contents=contents)
    retention.scan_retention_candidates(root, policy=_headroom_policy(1_000))

    handle, = swap.iterators
    assert swap.replacement.before != swap.replacement.after
    assert handle.closed == 1, "the scandir handle was not released"
    assert handle.yielded == [], (
        "entries were enumerated inside a root the pass had not proved")
    assert handle.undrained() == [], (
        "the handle was left open on the directory that was refused")


def test_the_refusal_is_about_which_directory_and_not_about_a_bad_one(
        tmp_path, monkeypatch):
    """The substitute is an ordinary, perfectly usable directory: not a
    junction, not a symlink, not a mount point, not a file. It holds the same
    eligible names and scans clean when nothing is disturbing it. So the
    pathname now identifies a REAL directory that is simply not the one the
    handle was opened on, and that -- alone -- is what the refusal is about.
    """
    root, names, contents = _root_and_matching_substitute(tmp_path)
    swap = _move_the_root_under_the_open(monkeypatch, root, contents=contents)
    refused = retention.scan_retention_candidates(
        root, policy=_headroom_policy(1_000))

    now = _directory_identity(root)
    assert stat_module.S_ISDIR(_REAL_LSTAT(root).st_mode), (
        "the pathname does not name a directory at all")
    assert now == swap.replacement.after
    assert now != swap.replacement.before, (
        "the pathname still names the object the handle was opened on")
    assert retention.directory_state(root) is not None, (
        "the substitute is not even provable, so the refusal proves nothing")

    # The same substitute, undisturbed, is scannable over the very same names.
    fresh = retention.scan_retention_candidates(
        root, policy=_headroom_policy(1_000))
    assert isinstance(fresh, retention.ScanSucceeded)
    assert sorted(entry.basename for entry in fresh.snapshots) == sorted(names)
    assert fresh.root_identity == swap.replacement.after

    assert isinstance(refused, retention.ScanFailed)
    assert refused.reason is (
        retention.RetentionFailureReason.IDENTITY_UNAVAILABLE)


# -- and what the two live modes do with it ----------------------------------

def test_a_live_plan_stays_bound_when_the_path_moves_during_the_scan(
        tmp_path, monkeypatch):
    """`PLAN` reports only on the held object, never the replacement name."""
    root, names, contents = _root_and_matching_substitute(tmp_path)
    swap = _move_the_root_under_the_open(monkeypatch, root, contents=contents)
    report = _live_plan(root, policy=_headroom_policy(1_000))

    if swap.replacement is None:
        assert swap.blocked is not None
    else:
        assert swap.replacement.before != swap.replacement.after
        assert _listing(root) == sorted(contents), "PLAN mutated the replacement"
        assert _listing(swap.displaced) == sorted(
            names + [_ORIGINAL_MARKER]), "PLAN mutated the scanned object"
    assert report.refused is None
    assert report.planned_actions_count == 2
    assert (report.processed, report.inspected) == (4, 3)
    assert report.moved == 0


def test_quarantine_stays_on_the_scanned_object_when_its_path_moves_under_open(
        tmp_path, monkeypatch):
    """The scan window cannot redirect quarantine into an unscanned object."""
    root, names, contents = _root_and_matching_substitute(tmp_path)
    swap = _move_the_root_under_the_open(monkeypatch, root, contents=contents)
    report = _headroom_run(root, _headroom_policy(1_000))

    assert report.refused is None
    assert report.moved == report.planned_actions_count == 2
    assert report.skipped == 0
    assert report.unmanifested == 0
    assert report.halted is False
    if swap.replacement is None:
        assert swap.blocked is not None
        assert _quarantine_root(root).is_dir()
    else:
        assert swap.replacement.before != swap.replacement.after
        assert set(names) <= set(swap.replacement.decoy_names)
        assert not _quarantine_root(root).exists(), (
            "a quarantine tree was built inside the replacement")
        assert _quarantine_root(swap.displaced).is_dir(), (
            "quarantine did not follow the held scanned object")
        assert _listing(root) == sorted(contents), "the replacement was mutated"


# -- the two windows a pre-open proof creates, which it must also close ------

def test_a_root_that_vanishes_between_its_proof_and_the_open_fails_closed(
        tmp_path, monkeypatch):
    """A pathname that was NEVER a directory is nothing to maintain, and stays
    the clean empty success it has always been. A pathname that WAS a real
    directory when this pass proved it and is gone by the time the open is
    attempted is a different fact entirely: the object the pass was pointed at
    disappeared underneath it. Reporting that as a healthy empty directory
    tells an operator the opposite of what happened, and is precisely the
    outcome the empty-success branch must not be allowed to absorb.
    """
    root = _scanned_root(tmp_path, snapshots=3)
    swap = _move_the_root_under_the_open(monkeypatch, root,
                                         when="before_open", vanish=True)
    result = retention.scan_retention_candidates(
        root, policy=_headroom_policy(1_000))

    assert swap.calls == 1
    assert swap.displaced is not None
    assert stat_module.S_ISDIR(_REAL_LSTAT(swap.displaced).st_mode), (
        "the original directory was destroyed rather than moved aside")
    assert not os.path.exists(root), "the fixture did not vacate the pathname"
    assert isinstance(result, retention.ScanFailed), (
        "a root that vanished under the pass was reported as a clean, empty, "
        "successful directory")
    assert result.reason is (
        retention.RetentionFailureReason.IDENTITY_UNAVAILABLE)
    assert (result.processed, result.inspected) == (0, 0)


def test_a_pathname_that_was_never_a_directory_is_still_a_clean_empty_scan(
        tmp_path):
    """The other half of that discrimination, pinned beside it so the two
    cannot drift apart. Nothing to maintain stays a success and carries no
    binding; something that vanished under the pass does not.
    """
    policy = _headroom_policy(1_000)
    absent = retention.scan_retention_candidates(tmp_path / "gone",
                                                 policy=policy)
    assert isinstance(absent, retention.ScanSucceeded)
    assert absent.root_identity is None
    assert (absent.processed, absent.inspected) == (0, 0)

    plain = tmp_path / "not_a_directory"
    plain.write_bytes(b"x")
    result = retention.scan_retention_candidates(plain, policy=policy)
    assert isinstance(result, retention.ScanSucceeded)
    assert result.root_identity is None


def test_a_root_replaced_between_its_proof_and_the_open_is_refused(
        tmp_path, monkeypatch):
    """The second window a pre-open proof opens, seen from the other side.

    Here the handle is acquired on the SUBSTITUTE, so the enumeration and the
    pathname agree with each other perfectly -- and both disagree with the
    object this pass proved a moment earlier. Going ahead would mean
    maintaining a directory that replaced the one the operator pointed at,
    which is the same fact as the window above and is refused the same way.
    """
    root, names, contents = _root_and_matching_substitute(tmp_path)
    swap = _move_the_root_under_the_open(monkeypatch, root, contents=contents,
                                         when="before_open")
    result = retention.scan_retention_candidates(
        root, policy=_headroom_policy(1_000))

    handle, = swap.iterators
    assert swap.replacement.before != swap.replacement.after
    assert set(names) <= set(swap.replacement.decoy_names)
    assert isinstance(result, retention.ScanFailed), (
        "a pass proved one directory and enumerated another")
    assert result.reason is (
        retention.RetentionFailureReason.IDENTITY_UNAVAILABLE)
    assert (result.processed, result.inspected) == (0, 0)
    assert handle.closed == 1, "the scandir handle was not released"
    assert handle.yielded == []
    assert handle.undrained() == []


# ===========================================================================
# Pre-open proof -- the remaining decision-table rows
# ===========================================================================


#: The same five root changes as `_CHANGED_ROOTS`, expressed as the PAIR this
#: control needs: what the root was, and what it became. The enumeration
#: control needs three answers because its mismatch lands after the open;
#: this one needs two, because its mismatch lands before the first entry is
#: read. Derived rather than restated, so the two can never drift apart.
_PRE_OPEN_CHANGED_ROOTS = [(label, answers[0], answers[-1])
                           for label, answers in _CHANGED_ROOTS]


@pytest.mark.parametrize("label,before,after", _PRE_OPEN_CHANGED_ROOTS,
                         ids=[row[0] for row in _PRE_OPEN_CHANGED_ROOTS])
def test_a_root_replaced_before_the_first_entry_is_read_refuses(
        monkeypatch, label, before, after):
    """The window the ordering opens. The identity is acquired BEFORE the
    iterator, so a replacement installed either side of the open -- between
    the proof and the acquisition, or between the acquisition and the first
    proof of the handle -- disagrees with something read earlier and is
    refused. Read after the open instead, both proofs would observe the
    replacement, agree with each other, and bind the pass to a directory the
    iterator never enumerated.

    Nothing is read from the directory and the handle is released.
    """
    fake = _install(monkeypatch, _FakeScandir(_snapshots(5),
                                              root_stats=[before, after]))
    result = _scan()
    assert isinstance(result, retention.ScanFailed)
    assert result.reason is retention.RetentionFailureReason.IDENTITY_UNAVAILABLE
    assert (result.processed, result.inspected) == (0, 0)
    assert fake.root_reads == 2
    assert fake.yielded == [], "an entry was yielded after the mismatch"
    assert fake.statted == [], "an entry was read after the mismatch"
    assert fake.closed == 1, "the scandir handle was not released"
    assert not hasattr(result, "snapshots")


def test_a_root_that_stops_being_a_directory_between_proof_and_open_refuses(
        monkeypatch):
    fake = _install(monkeypatch, _FakeScandir(
        _snapshots(3), root_stat=_dir_stat(ino=1),
        open_error=NotADirectoryError(errno.ENOTDIR, "not a directory")))
    result = _scan()
    assert isinstance(result, retention.ScanFailed)
    assert result.reason is retention.RetentionFailureReason.IDENTITY_UNAVAILABLE
    assert fake.root_reads == 1


def test_an_unreadable_root_is_still_a_directory_open_failure(monkeypatch):
    """The open's own non-missing outcomes are untouched by the new proof,
    whether or not an identity was observed first."""
    for root_stat in (_dir_stat(ino=1),
                      PermissionError(errno.EACCES, "denied")):
        fake = _FakeScandir(_snapshots(3), root_stat=root_stat,
                            open_error=PermissionError(errno.EACCES, "denied"))
        monkeypatch_local = pytest.MonkeyPatch()
        try:
            _install(monkeypatch_local, fake)
            result = _scan()
        finally:
            monkeypatch_local.undo()
        assert isinstance(result, retention.ScanFailed)
        assert result.reason is (
            retention.RetentionFailureReason.DIRECTORY_OPEN_FAILED)


def test_an_openable_root_with_no_prior_identity_is_never_an_empty_success(
        monkeypatch):
    """The empty success needs BOTH halves. `os.scandir` FOLLOWS a reparse
    point and opens it perfectly happily, so an open that succeeds over a
    pathname no identity was ever proved at fails closed instead."""
    fake = _install(monkeypatch, _FakeScandir(
        _snapshots(3),
        root_stat=_dir_stat(ino=1,
                            file_attributes=(
                                stat_module.FILE_ATTRIBUTE_REPARSE_POINT))))
    result = _scan()
    assert isinstance(result, retention.ScanFailed)
    assert result.reason is retention.RetentionFailureReason.IDENTITY_UNAVAILABLE
    assert fake.statted == [] and fake.closed == 1


# ===========================================================================
# A single-instance LOCK close failure must be contained, not escape
# ===========================================================================
#
# `_LockHandle.acquire` and `_LockHandle.release` both call `os.close` on the
# lock descriptor UNGUARDED in their cleanup paths.
#
# In `release` that call is the `finally` of the unlock block, so a raising
# close escapes through `single_instance_lock.__exit__`. In `main` the report
# has already been printed and the return value already chosen by then, so the
# operator gets a traceback INSTEAD OF the promised fixed, path-free outcome --
# and in a QUARANTINE pass that traceback arrives after files have already been
# renamed into quarantine, so the aggregate that says how many moved is lost
# with it.
#
# In `acquire` the same unguarded close sits on the lock-contention path, where
# it replaces the intended `False` -- and therefore the sanitized
# `lock_unavailable` line and exit status 1 -- with an exception carrying an
# errno and a path.
#
# In BOTH cases the `self._fd = None` that follows the close never executes
# when the close raises, leaving a stale descriptor reference on the handle:
# the number it names may already have been reissued to something else, so a
# later traversal of `release` would close an unrelated descriptor. That is
# exactly the hazard `_quarantine` already documents for the manifest journal
# ("a second attempt could close a descriptor the runtime has already
# reissued to something else"); the lock is the same hazard, unfixed.
#
# The correction contains `OSError` at both sites, ALWAYS clears `_fd` exactly
# once, and never retries the close.
#
# The fault below is injected against the LOCK DESCRIPTOR SPECIFICALLY, by
# path. `retention.os` is the process-global `os` module, so a blanket
# `os.close` failure would break pytest's own descriptors and the quarantine
# manifest's, and would prove nothing about this path.


def _normalized_fs_path(value):
    """Normalize anything `os.open` accepts into one comparable text key.

    Returns None for a value that is not a path at all -- an integer
    descriptor for a `dir_fd`-relative open, or a name that cannot be brought
    into text form -- so a non-path open can never accidentally compare equal
    to the lock and be mistaken for it.
    """
    if isinstance(value, int):
        return None
    try:
        text = os.fspath(value)
    except TypeError:
        return None
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8", "surrogateescape")
        except ValueError:  # pragma: no cover - decoding cannot fail this way
            return None
    try:
        # Resolve the production descriptor route while its parent anchor is
        # live. The original lexical pathname and `/proc/self/fd/<n>/name`
        # identify one lock object, so an `abspath`-only oracle silently stops
        # observing the descriptor that production actually opened on POSIX.
        return os.path.normcase(os.path.realpath(text))
    except (OSError, ValueError):  # pragma: no cover - defensive
        return None


class _LockCloseFault:
    """Fail the close of the SINGLE-INSTANCE LOCK, for ONE descriptor lifetime.

    Two levels of selectivity, and both are needed.

    First, by PATH at open time. `retention.os` is the process-global `os`
    module, so patching `os.close` is global for the duration of the test --
    and the same pass also opens and closes the quarantine manifest. The
    injector therefore only ever adopts a descriptor that `os.open` handed out
    for the lock file itself; every other descriptor, the manifest's included,
    is recorded and delegated untouched. The lock lives OUTSIDE the maintained
    directory by construction, so the two paths can never normalize equal.

    Second, by DESCRIPTOR LIFETIME at close time, which is the lesson
    `_ManifestCloseFault` already paid for: a file descriptor is a NUMBER the
    operating system recycles the moment it is released, so the very next
    `os.open` can hand the same integer to something entirely unrelated. The
    target is therefore retired BEFORE the real close, never after. Clearing
    it afterwards would leave a window in which the number has been released
    and reissued while the injector still matched it -- failing an unrelated
    close and inflating `close_attempts`, the counter the "exactly one close
    attempt" control depends on.

    The real close always happens, and happens first, so no descriptor leaks
    and the operating system genuinely drops the lock even when the injected
    failure follows.

    Retirement is also what makes a RETRY visible. `close_attempts` counts
    only the injected close, so a correction that contained the failure and
    then closed again would leave it at one and look correct; `retired_fd`
    therefore stays set after retirement and `retried_closes` records any
    further close of that number, delegating it rather than injecting. The
    watch is dropped the instant `os.open` hands the number out again, which
    is the only way that number can legitimately belong to something else.

    `arm` selects WHICH lock-path open is adopted rather than assuming the
    first: a contention control needs the CONTENDER's descriptor while the
    holder's stays open, and a report-comparison control needs one unfaulted
    invocation before the faulted one.
    """

    def __init__(self, monkeypatch, lock_path, *, arm=True, fail=True):
        self.fail = fail
        self.lock_path = _normalized_fs_path(lock_path)
        self.target_fd = None
        self.retired_fd = None
        self.lock_opens = []
        self.other_opens = []
        self.close_attempts = []
        self.delegated_closes = 0
        self.retried_closes = []
        self._arm_next = bool(arm)
        real_open = os.open
        real_close = os.close

        def _open(path, *args, **kwargs):
            fd = real_open(path, *args, **kwargs)
            if fd == self.retired_fd:
                # The number has been REISSUED. Stop watching it entirely:
                # from here a close of this integer belongs to whatever just
                # took it, and counting that as a second attempt on the lock
                # would be a fabrication. Every reissue passes through here,
                # so the watch closes itself the moment it stops being sound.
                self.retired_fd = None
            if _normalized_fs_path(path) == self.lock_path:
                self.lock_opens.append(fd)
                if self._arm_next:
                    self._arm_next = False
                    self.target_fd = fd
            else:
                self.other_opens.append(fd)
            return fd

        def _close(fd):
            if self.target_fd is not None and fd == self.target_fd:
                self.close_attempts.append(fd)
                # Retire the target FIRST: from here the number may be
                # reissued at any moment, and every later close must delegate.
                self.target_fd = None
                self.retired_fd = fd
                real_close(fd)          # release for real: never leak an fd
                if self.fail:
                    raise OSError(errno.EIO, "injected lock close failure")
                return None
            if self.retired_fd is not None and fd == self.retired_fd:
                # A SECOND close of the number the first attempt already
                # named, with no reissue in between -- so this is a RETRY, and
                # a retry is exactly what must never happen: the descriptor
                # state after a failed close is ambiguous, and by the time a
                # retry lands the number may belong to something else. It is
                # recorded and then delegated, so the control sees it rather
                # than the injector hiding it.
                self.retried_closes.append(fd)
            self.delegated_closes += 1
            return real_close(fd)

        monkeypatch.setattr(retention.os, "open", _open)
        monkeypatch.setattr(retention.os, "close", _close)

    def arm(self):
        """Adopt the NEXT descriptor `os.open` hands out for the lock path."""
        self._arm_next = True


def _lock_layout(tmp_path):
    """A data directory and a lock file that lives OUTSIDE it.

    The lock must never sit inside the directory being measured -- a `PLAN`
    that created a file in its own target would change the entry count it
    reports -- and every control here passes the path explicitly, so nothing
    is ever created in the shared system temporary directory.
    """
    data = Path(tmp_path) / "data"
    data.mkdir()
    return data, Path(tmp_path) / "retention.lock"


def _lock_only(tmp_path):
    """Just the lock file. Controls that exercise the handle alone need no
    target directory at all, and creating one would only invite the reader to
    look for a relationship that is not being tested."""
    return Path(tmp_path) / "retention.lock"


class _LockBodyFailure(Exception):
    """A distinct, unmistakable failure raised by the `with` body itself."""


class _FailingUnlockModule:
    """A stand-in for `msvcrt` whose UNLOCK call fails.

    The Windows branch of `release` is the only one that issues an explicit
    unlock; on POSIX the kernel drops the `flock` when the descriptor closes,
    so there is no call there to fail. Modelling that branch with a double is
    what makes "an unlock failure followed by a close failure" a control that
    runs identically on every platform, instead of one that only means
    something on Windows or needs elevation to reach.
    """

    LK_NBLCK = 0
    LK_UNLCK = 1

    def __init__(self):
        self.calls = []

    def locking(self, fd, mode, length):
        self.calls.append((fd, mode, length))
        raise OSError(errno.EACCES, "injected unlock failure")


# -- the injector itself, proved before anything is proved with it -----------
#
# These bind nothing to `_LockHandle`: they drive the patched `os` entry points
# directly, so they hold identically before and after the correction and can
# never be mistaken for evidence about the fix.


def test_the_lock_close_fault_delegates_every_other_descriptor(tmp_path,
                                                               monkeypatch):
    """Selectivity, stated directly: while armed and failing, an unrelated
    descriptor closes normally and is not counted, and only the lock
    descriptor takes the injected failure."""
    data, lock_path = _lock_layout(tmp_path)
    fault = _LockCloseFault(monkeypatch, lock_path)

    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    probe = data / "unrelated"
    probe.write_bytes(b"x")
    probe_fd = os.open(probe, os.O_RDONLY)
    os.close(probe_fd)                        # must NOT raise
    assert probe_fd in fault.other_opens
    assert fault.close_attempts == []
    assert fault.delegated_closes == 1

    with pytest.raises(OSError) as caught:
        os.close(lock_fd)
    assert caught.value.errno == errno.EIO
    assert fault.close_attempts == [lock_fd]
    assert fault.lock_opens == [lock_fd]
    assert fault.target_fd is None, "the target was not retired"
    assert fault.retried_closes == []


def test_the_lock_close_fault_sees_a_retried_close(tmp_path, monkeypatch):
    """The retry watch, proved on the injector rather than on the handle.

    `close_attempts` cannot detect a retry -- the target is retired by then,
    so a second close delegates and is never counted. Without a separate
    watch, a correction that contained the failure and then closed the same
    number again would satisfy every containment control here while keeping
    the more dangerous half of the defect.
    """
    lock_path = _lock_only(tmp_path)
    fault = _LockCloseFault(monkeypatch, lock_path)
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    with pytest.raises(OSError):
        os.close(lock_fd)
    assert fault.retried_closes == []
    with pytest.raises(OSError) as caught:
        os.close(lock_fd)                     # the retry: already released
    assert caught.value.errno == errno.EBADF
    assert fault.retried_closes == [lock_fd]
    assert fault.close_attempts == [lock_fd], "the retry was injected too"


def test_the_lock_close_fault_stops_watching_a_reissued_number(tmp_path,
                                                               monkeypatch):
    """The watch must retire itself the moment the number is handed out
    again, or an ordinary recycled descriptor would be reported as a retry."""
    data, lock_path = _lock_layout(tmp_path)
    fault = _LockCloseFault(monkeypatch, lock_path)
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    with pytest.raises(OSError):
        os.close(lock_fd)
    assert fault.retired_fd == lock_fd

    spare = data / "reissue_probe"
    spare.write_bytes(b"x")
    handles = []
    reissued = None
    try:
        for _ in range(64):
            opened = os.open(spare, os.O_RDONLY)
            if opened == lock_fd:
                reissued = opened
                break
            handles.append(opened)
    finally:
        for opened in handles:
            os.close(opened)

    if reissued is not None:
        assert fault.retired_fd is None, "the watch outlived the reissue"
        os.close(reissued)                    # an unrelated close, not a retry
    assert fault.retried_closes == []
    assert fault.close_attempts == [lock_fd]


def test_the_lock_close_fault_retires_its_target_after_one_lifetime(
        tmp_path, monkeypatch):
    lock_path = _lock_only(tmp_path)
    fault = _LockCloseFault(monkeypatch, lock_path, fail=False)
    handle = retention._LockHandle(lock_path)
    assert handle.acquire() is True
    handle.release()
    assert len(fault.close_attempts) == 1
    assert fault.target_fd is None
    assert fault.retired_fd == fault.close_attempts[0]


def test_a_recycled_descriptor_number_is_not_treated_as_the_lock(tmp_path,
                                                                 monkeypatch):
    """Reopen until the released number comes back, then close it: a live
    injector would fail that close and count it twice.

    Recycling is the platform's choice, so `recycled` may stay None and the
    reissue arm may not execute on a given run. The retirement invariant that
    makes recycling harmless is proved unconditionally above; this one adds
    the real-reissue observation when the platform offers it, and asserts the
    close-attempt count either way.
    """
    data, lock_path = _lock_layout(tmp_path)
    fault = _LockCloseFault(monkeypatch, lock_path, fail=False)
    handle = retention._LockHandle(lock_path)
    assert handle.acquire() is True
    handle.release()
    assert len(fault.close_attempts) == 1
    released = fault.close_attempts[0]

    spare = data / "recycled_probe"
    spare.write_bytes(b"x")
    handles = []
    recycled = None
    try:
        for _ in range(64):
            opened = os.open(spare, os.O_RDONLY)
            if opened == released:
                recycled = opened
                break
            handles.append(opened)
    finally:
        for opened in handles:
            os.close(opened)

    if recycled is not None:
        os.close(recycled)                    # must NOT raise the injection
    assert len(fault.close_attempts) == 1


def test_the_lock_close_fault_leaks_no_descriptor(tmp_path, monkeypatch):
    data, lock_path = _lock_layout(tmp_path)
    probe = data / "watermark"
    probe.write_bytes(b"x")

    def _watermark():
        opened = os.open(probe, os.O_RDONLY)
        os.close(opened)
        return opened

    before = _watermark()
    fault = _LockCloseFault(monkeypatch, lock_path)
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    with pytest.raises(OSError):
        os.close(lock_fd)
    after = _watermark()
    assert fault.close_attempts == [lock_fd]
    assert after <= before + 1


def test_the_lock_close_fault_never_targets_the_manifest_descriptor(
        tmp_path, monkeypatch):
    """The one control that puts BOTH descriptors in flight at once.

    A full QUARANTINE pass runs inside a held lock, so the lock descriptor is
    open across the whole pass while the manifest descriptor is opened,
    written, synchronised and closed inside it. The manifest close must be a
    plain delegation: it is a different path, therefore a different adopted
    descriptor, therefore never the injected one. `fail=False` keeps this a
    statement about the INJECTOR rather than about the correction, so it holds
    identically before and after the fix.

    The manifest is only OBSERVED here. Nothing about manifest handling is
    changed, and the completed journal is read back as independent proof that
    its own close really did succeed.
    """
    data, lock_path = _lock_layout(tmp_path)
    _populate(data, snapshots=5)
    fault = _LockCloseFault(monkeypatch, lock_path, fail=False)

    seen = {}
    real_open_manifest = retention._open_manifest

    def _observed_open_manifest(pass_directory):
        fd = real_open_manifest(pass_directory)
        seen["fd"] = fd
        seen["path"] = Path(pass_directory) / retention.MANIFEST_NAME
        return fd

    monkeypatch.setattr(retention, "_open_manifest", _observed_open_manifest)

    # Capture the completed journal while the manifest and its held-directory
    # route are both still valid. Reading `seen["path"]` after `_run` returns
    # dereferences a released `/proc/self/fd/<n>` route and tests descriptor
    # recycling rather than manifest-close behavior.
    delegated_close = retention.os.close

    def _capture_manifest_before_close(fd):
        if fd == seen.get("fd"):
            seen["contents"] = seen["path"].read_text(encoding="utf-8")
        return delegated_close(fd)

    monkeypatch.setattr(retention.os, "close", _capture_manifest_before_close)

    with retention.single_instance_lock(lock_path) as acquired:
        assert acquired is True
        report = _run(data)

    assert report.refused is None
    assert report.moved == 4
    lock_fd = fault.lock_opens[0]
    assert seen["fd"] != lock_fd, "both descriptors must be live at once"
    assert seen["fd"] in fault.other_opens
    assert seen["fd"] not in fault.close_attempts
    assert fault.close_attempts == [lock_fd]
    assert _normalized_fs_path(seen["path"]) != fault.lock_path
    lines = [line for line
             in seen["contents"].splitlines() if line]
    assert len(lines) == report.moved, "the manifest close did not succeed"


# -- release: the failure must be contained -----------------------------------


def test_a_lock_release_close_failure_does_not_escape_the_context_manager(
        tmp_path, monkeypatch):
    lock_path = _lock_only(tmp_path)
    fault = _LockCloseFault(monkeypatch, lock_path)
    with retention.single_instance_lock(lock_path) as acquired:
        assert acquired is True
    assert len(fault.close_attempts) == 1


def test_a_contained_release_close_failure_clears_the_descriptor_reference(
        tmp_path, monkeypatch):
    """A stale `_fd` is not untidiness: the number it holds may already have
    been reissued, so anything that later trusted it would close a descriptor
    belonging to something else."""
    lock_path = _lock_only(tmp_path)
    fault = _LockCloseFault(monkeypatch, lock_path)
    handle = retention._LockHandle(lock_path)
    assert handle.acquire() is True
    handle.release()
    assert handle._fd is None
    assert len(fault.close_attempts) == 1


def test_the_lock_descriptor_receives_exactly_one_close_attempt(tmp_path,
                                                                monkeypatch):
    """One attempt, and no retry. Both halves matter: a correction that
    contained the failure and then tried the close again would satisfy every
    other control here while reintroducing the worse half of the defect --
    a close aimed at a number the runtime may already have reissued."""
    lock_path = _lock_only(tmp_path)
    fault = _LockCloseFault(monkeypatch, lock_path)
    with retention.single_instance_lock(lock_path) as acquired:
        assert acquired is True
    assert fault.close_attempts == [fault.lock_opens[0]]
    assert fault.retried_closes == []
    assert fault.target_fd is None


def test_a_repeated_release_after_a_contained_close_failure_is_inert(
        tmp_path, monkeypatch):
    """The unlock and the close sit on ONE path, with the close in the
    `finally`, so any second traversal of `release` is necessarily a second
    close attempt. Counting close attempts therefore counts traversals on
    every platform, with no `msvcrt`/`fcntl` branch in the control at all.

    A second traversal would also be actively dangerous, which is why this is
    asserted rather than assumed: the number the failed close named may
    already have been reissued, so closing it again would take out an
    unrelated descriptor. `retried_closes` records exactly that -- a close of
    the retired number with no reissue in between -- and stops watching the
    moment the number is genuinely handed out again, so ordinary recycling
    cannot forge an observation.
    """
    lock_path = _lock_only(tmp_path)
    fault = _LockCloseFault(monkeypatch, lock_path)
    handle = retention._LockHandle(lock_path)
    assert handle.acquire() is True
    handle.release()                          # contained; one close attempt
    assert handle._fd is None
    assert len(fault.close_attempts) == 1

    handle.release()                          # inert: no unlock, no close
    assert fault.retried_closes == []
    assert len(fault.close_attempts) == 1
    assert handle._fd is None


def test_an_exception_in_the_body_survives_a_lock_close_failure(tmp_path,
                                                                monkeypatch):
    """Precedence. The body's own failure is what the caller must see; a
    cleanup failure that replaced it would hide the real diagnosis behind an
    errno from the lock file."""
    lock_path = _lock_only(tmp_path)
    fault = _LockCloseFault(monkeypatch, lock_path)
    with pytest.raises(_LockBodyFailure):
        with retention.single_instance_lock(lock_path) as acquired:
            assert acquired is True
            raise _LockBodyFailure("the body's own failure")
    assert len(fault.close_attempts) == 1


def test_an_unlock_failure_followed_by_a_close_failure_stays_contained(
        tmp_path, monkeypatch):
    """Both halves of the cleanup fail at once.

    The unlock is modelled rather than required, so this runs the same on
    every platform: the existing `except OSError: pass` swallows the unlock,
    and the correction must then also contain the close that the `finally`
    performs -- while still clearing `_fd` exactly once.
    """
    lock_path = _lock_only(tmp_path)
    fault = _LockCloseFault(monkeypatch, lock_path)
    handle = retention._LockHandle(lock_path)
    assert handle.acquire() is True

    unlock = _FailingUnlockModule()
    with mock.patch.dict(sys.modules, {"msvcrt": unlock}), \
            mock.patch.object(retention.os, "name", "nt"):
        handle.release()                      # must not raise
    assert unlock.calls, "the modelled unlock branch never ran"
    assert handle._fd is None
    assert len(fault.close_attempts) == 1
    assert fault.retried_closes == []


# -- acquire: a contended lock plus a failing close ---------------------------


def test_a_lock_acquisition_failure_with_a_failing_close_returns_false(
        tmp_path, monkeypatch):
    """Genuine contention, not a patched locking primitive: a second
    descriptor on the same file fails `msvcrt.locking` and `fcntl.flock`
    alike, so the control needs no platform branch and no second process."""
    lock_path = _lock_only(tmp_path)
    fault = _LockCloseFault(monkeypatch, lock_path, arm=False)
    with retention.single_instance_lock(lock_path) as held:
        assert held is True
        fault.arm()                           # the CONTENDER's descriptor
        contender = retention._LockHandle(lock_path)
        assert contender.acquire() is False
        assert contender._fd is None
        assert len(fault.close_attempts) == 1
        assert fault.retried_closes == []
    assert len(fault.close_attempts) == 1, "the holder's close was injected"


def test_a_contended_cli_pass_with_a_failing_close_reports_lock_unavailable(
        tmp_path, monkeypatch, capsys):
    data, lock_path = _lock_layout(tmp_path)
    _populate(data, snapshots=3)
    fault = _LockCloseFault(monkeypatch, lock_path, arm=False)
    with retention.single_instance_lock(lock_path) as held:
        assert held is True
        fault.arm()
        status = retention.main([str(data), "--lock", str(lock_path)])
        printed = capsys.readouterr()
    assert status == 1
    assert printed.out.strip() == (
        "retention refused=%s"
        % retention.RetentionFailureReason.LOCK_UNAVAILABLE.value)
    assert printed.err == ""
    assert len(fault.close_attempts) == 1
    assert fault.retried_closes == []
    for leak in ("Traceback", "OSError", "Errno", "EIO", "injected",
                 "descriptor", "fd=", str(tmp_path), str(lock_path),
                 lock_path.name):
        assert leak not in printed.out, leak
        assert leak not in printed.err, leak


# -- the operator outcome must be exactly what it would have been -------------


def test_a_successful_plan_through_main_survives_a_lock_close_failure(
        tmp_path, monkeypatch, capsys):
    """`main` prints the report and chooses its exit status BEFORE `__exit__`
    releases the lock, so a close failure arrives too late to change anything
    except by destroying it.

    The unfaulted invocation supplies the reference line, and the faulted one
    must reproduce it BYTE FOR BYTE. That is a stronger statement than any
    list of forbidden substrings -- nothing whatsoever is added, so no path,
    no errno text and no descriptor number can be present -- and the explicit
    leak list is kept alongside it to name what is being ruled out.
    """
    data, lock_path = _lock_layout(tmp_path)
    _populate(data, snapshots=3)
    fault = _LockCloseFault(monkeypatch, lock_path, arm=False)

    reference_status = retention.main([str(data), "--lock", str(lock_path)])
    reference = capsys.readouterr()
    assert reference_status == 0
    assert "refused=none" in reference.out
    assert fault.close_attempts == []

    fault.arm()
    status = retention.main([str(data), "--lock", str(lock_path)])
    printed = capsys.readouterr()

    assert status == 0
    assert printed.out == reference.out
    assert printed.err == ""
    assert len(fault.close_attempts) == 1
    for leak in ("Traceback", "OSError", "Errno", "EIO", "injected",
                 "descriptor", "fd=", str(tmp_path), str(lock_path),
                 lock_path.name):
        assert leak not in printed.out, leak
        assert leak not in printed.err, leak


def test_a_refused_pass_through_main_keeps_its_reason_and_exit_status(
        tmp_path, monkeypatch, capsys):
    """A controlled refusal is a diagnosis. A close failure that replaced it
    would tell the operator nothing about the target at all."""
    data, lock_path = _lock_layout(tmp_path)
    absent = data / "absent"
    fault = _LockCloseFault(monkeypatch, lock_path, arm=False)

    reference_status = retention.main([str(absent), "--lock", str(lock_path)])
    reference = capsys.readouterr()
    assert reference_status == 1
    assert (retention.RetentionFailureReason.IDENTITY_UNAVAILABLE.value
            in reference.out)

    fault.arm()
    status = retention.main([str(absent), "--lock", str(lock_path)])
    printed = capsys.readouterr()

    assert status == 1
    assert printed.out == reference.out
    assert printed.err == ""
    assert len(fault.close_attempts) == 1
    for leak in ("Traceback", "OSError", "Errno", "EIO", "injected",
                 str(tmp_path), str(lock_path)):
        assert leak not in printed.out, leak
        assert leak not in printed.err, leak


def test_a_quarantine_pass_that_moved_artifacts_keeps_its_accounting(
        tmp_path, monkeypatch):
    """The worst arrival time for the escaping close: after the renames.

    Files are already in quarantine when the lock is released, so an escaping
    OSError costs the caller the entire aggregate -- how many moved, how many
    were skipped, how many are evidence without a record -- for a failure that
    changed none of it. The counts are checked against the directory and the
    journal, not merely against themselves.
    """
    data, lock_path = _lock_layout(tmp_path)
    _populate(data, snapshots=5)
    fault = _LockCloseFault(monkeypatch, lock_path)

    with retention.single_instance_lock(lock_path) as acquired:
        assert acquired is True
        report = _run(data)
        line = retention.format_report(report)

    assert report.refused is None
    assert report.halted is False
    assert report.moved == 4
    assert report.moved == report.planned_actions_count
    assert report.skipped == 0
    assert report.unmanifested == 0
    assert len(fault.close_attempts) == 1

    pass_directory = _quarantine_root(data) / "p20260101T000000"
    arrived = [path for path in pass_directory.iterdir()
               if path.name != retention.MANIFEST_NAME]
    assert len(arrived) == report.moved
    manifest = pass_directory / retention.MANIFEST_NAME
    records = [json.loads(entry) for entry
               in manifest.read_text(encoding="utf-8").splitlines() if entry]
    assert len(records) == report.moved
    assert "moved=4" in line and "halted=False" in line


# -- nothing about the ordinary lifecycle may change --------------------------


def test_the_lock_survives_acquisition_contention_release_and_reacquisition(
        tmp_path):
    """No injection at all. The correction touches two cleanup paths and must
    leave the behaviour every other control rests on exactly as it was."""
    lock_path = _lock_only(tmp_path)
    with retention.single_instance_lock(lock_path) as first:
        assert first is True
        with retention.single_instance_lock(lock_path) as second:
            assert second is False
    with retention.single_instance_lock(lock_path) as again:
        assert again is True

    handle = retention._LockHandle(lock_path)
    assert handle.acquire() is True
    handle.release()
    assert handle._fd is None
    handle.release()                          # already inert today
    assert handle._fd is None


def test_the_lock_lifecycle_is_unchanged_when_the_close_succeeds(tmp_path,
                                                                 monkeypatch):
    """The same lifecycle with the injector installed but not failing, so the
    close counts are observable: one adopted descriptor per armed acquisition,
    one close attempt each, and contention still answers False."""
    lock_path = _lock_only(tmp_path)
    fault = _LockCloseFault(monkeypatch, lock_path, fail=False)
    with retention.single_instance_lock(lock_path) as first:
        assert first is True
        with retention.single_instance_lock(lock_path) as second:
            assert second is False
    assert len(fault.close_attempts) == 1
    assert len(fault.lock_opens) == 2         # holder and contender

    fault.arm()
    with retention.single_instance_lock(lock_path) as reacquired:
        assert reacquired is True
    assert len(fault.close_attempts) == 2
    assert fault.target_fd is None


def test_a_lock_open_failure_leaves_no_descriptor_reference(tmp_path,
                                                            monkeypatch):
    """The third cleanup path. It is already correct, and is pinned here so
    "always clear `_fd`" is stated for every exit `acquire` and `release`
    have between them."""
    lock_path = _lock_only(tmp_path)

    def _denied(*args, **kwargs):
        raise PermissionError(errno.EACCES, "permission denied")

    monkeypatch.setattr(retention.os, "open", _denied)
    handle = retention._LockHandle(lock_path)
    assert handle.acquire() is False
    assert handle._fd is None


# ===========================================================================
# P4 -- the SURVEY proves its pass directory ONCE and then stops looking
# ===========================================================================
#
# `survey_quarantine` opens with a proof and immediately throws it away:
#
#     if directory_state(root) is None:
#         return _survey_refusal(
#             RetentionFailureReason.SURVEY_DIRECTORY_INVALID)
#
# The `(device, inode)` pair that call read is never compared against
# anything. Everything after it -- the `os.scandir` block, the manifest read
# and the record parse -- acts on the PATHNAME again, and the operating
# system resolves that pathname afresh every single time.
#
# `os.scandir` binds the OBJECT. Once the iterator exists it keeps enumerating
# the directory it was opened on, whatever the pathname comes to mean. Every
# other step binds the NAME. So a substitution installed at any point after
# the opening proof splits the survey in half: the entry names come from the
# directory the handle is on, and the journal comes from whatever now answers
# to the pathname.
#
# The consequence is not a wrong count. It is a CLEAN RECONCILIATION of a
# state that no directory on the volume has ever held -- payload names from
# one object, matching records from another, `refused=None`, `unmanifested=0`.
# An operator reading that answer concludes the pass is fully journalled and
# that nothing needs recovering.
#
# The correction is three calls to the helper that already exists,
# `_scanned_root_unchanged`, against the identity the opening proof already
# reads: one inside the scan block before a single entry is consumed, one
# after the scan block before the manifest is resolved, and one after the
# manifest bytes come back and BEFORE their length is measured. No new
# symbol, no new reason, no new field.
#
# Nothing here sleeps, threads or races. Each window is entered by wrapping
# the primitive that opens it -- `os.scandir` for the four scan-time windows,
# `os.lstat` for the manifest-resolution window -- so the substitution lands
# at one exact statement, in one thread, in a fixed order, on every platform.


#: The five windows, named for the statement each one lands between. They are
#: parametrised over rather than written out one control at a time so that a
#: window added later cannot quietly acquire fewer controls than its
#: neighbours.
_SURVEY_WINDOWS = ("before_scandir", "after_scandir", "mid_enumeration",
                   "after_enumeration", "manifest_lstat")

#: The windows in which the handle is already open on the ORIGINAL object, so
#: the entry names keep coming from it while the pathname names the
#: substitute. These are the composite-answer windows.
_COMPOSING_WINDOWS = ("after_scandir", "mid_enumeration", "after_enumeration",
                      "manifest_lstat")


def _names_the_manifest(path):
    """Whether `path`'s last component is the journal's fixed name.

    The manifest-resolution window is entered by watching `os.lstat`, which
    the whole interpreter shares, so the watcher has to recognise the one
    pathname it cares about and pass everything else straight through
    untouched. `os.lstat` also accepts a descriptor, which is not a pathname
    at all and must not raise here.
    """
    try:
        text = os.fspath(path)
    except TypeError:
        return False
    if isinstance(text, bytes):
        text = os.fsdecode(text)
    return os.path.basename(text) == retention.MANIFEST_NAME


def _pass_directory_payloads(count):
    """`count` allowlisted basenames, as a completed pass would hold them."""
    return [_snap_name(index + 1, index + 1) for index in range(count)]


def _journalled_pass_directory(tmp_path, *, payloads=1, journal=True):
    """A finished pass directory, and the payload names inside it.

    Built through `_pass_dir`, the survey block's own builder, so these
    controls and the schema controls above are looking at the same shape of
    directory. It is a CHILD of the quarantine root rather than `tmp_path`
    itself, because every control below renames it and pytest owns `tmp_path`
    and walks it during teardown.
    """
    names = _pass_directory_payloads(payloads)
    records = [_record_bytes(name) for name in names] if journal else ()
    directory = _pass_dir(tmp_path, records=records, extra_files=names)
    return directory, names


def _replace_pass_directory_pathname(directory, *, entries=(), records=()):
    """Make `directory` name a DIFFERENT real directory, and prove it did.

    The counterpart of `_replace_root_pathname` for a pass directory, and
    built the same way and for the same reason: the substitute is allocated
    WHILE the original still exists and is then renamed over the vacated
    pathname, because removing the original and recreating it would let the
    filesystem hand back the inode it just released and the fixture would
    prove nothing.

    It takes journal bytes as well as entry names, which is the whole
    difference. A pass directory's answer is assembled from its entries AND
    its manifest, so a substitute that could not carry a journal could not
    express the defect this block is about.

    Nothing here is a junction, a symlink or a mount point. The substitute is
    an ordinary directory that satisfies every structural check
    `directory_state` makes, and is still not the directory that was proved.

    The two identities are asserted HERE rather than in each control, so no
    control can accidentally rest on a substitution that never happened.
    """
    directory = Path(os.fspath(directory))
    before = _directory_identity(directory)
    decoy = directory.with_name(directory.name + ".decoy")
    decoy.mkdir()
    for name in entries:
        (decoy / name).write_bytes(b"\x00" * 8)
    if records:
        (decoy / retention.MANIFEST_NAME).write_bytes(b"".join(records))
    displaced = directory.with_name(directory.name + ".displaced")
    os.rename(directory, displaced)
    os.rename(decoy, directory)
    after = _directory_identity(directory)
    assert before is not None, "the original had no identity to lose"
    assert after is not None, "the substitute has no identity of its own"
    assert before != after, (
        "the fixture did not actually change which object the pathname names")
    return _RootReplacement(before, after, displaced, _listing(directory))


class _Substitution:
    """A pass-directory replacement, deferred until a window opens it.

    Callable with no arguments so the scan wrapper and the `lstat` watcher can
    both fire it without knowing what it does, and idempotent so a window that
    is entered twice still describes one substitution.
    """

    __slots__ = ("_directory", "_entries", "_records", "armed", "replacement")

    def __init__(self, directory, *, entries=(), records=(), armed=True):
        self._directory = Path(os.fspath(directory))
        self._entries = tuple(entries)
        self._records = tuple(records)
        self.armed = armed
        self.replacement = None

    def __call__(self):
        if not self.armed or self.replacement is not None:
            return
        self.replacement = _replace_pass_directory_pathname(
            self._directory, entries=self._entries, records=self._records)


class _WithdrawnSubstitution:
    """Put the ORIGINAL back at the pathname the substitute took over.

    This exists to state a DISCLOSED LIMIT rather than to catch anything: a
    substitution that is installed and withdrawn wholly between two proofs
    leaves both proofs reading the identity they expect, and no comparison of
    two `(device, inode)` pairs can see it.
    """

    __slots__ = ("_directory", "_substitution", "restored")

    def __init__(self, directory, substitution):
        self._directory = Path(os.fspath(directory))
        self._substitution = substitution
        self.restored = None

    def __call__(self):
        replacement = self._substitution.replacement
        assert replacement is not None, "nothing was installed to withdraw"
        aside = self._directory.with_name(self._directory.name + ".withdrawn")
        os.rename(self._directory, aside)
        os.rename(replacement.displaced, self._directory)
        self.restored = _directory_identity(self._directory)
        assert self.restored == replacement.before, (
            "the withdrawal did not restore the original object")


class _ContentChangedInPlace:
    """Add and remove entries INSIDE the directory, without replacing it.

    A directory's size and modification time change whenever its contents do,
    and a pass directory an operator is looking at may legitimately change
    while it is being read. This is the fixture that proves the correction
    compares the `(device, inode)` pair and not the file 4-tuple.
    """

    __slots__ = ("_directory", "_added", "_removed", "performed")

    def __init__(self, directory, *, added=(), removed=()):
        self._directory = Path(os.fspath(directory))
        self._added = tuple(added)
        self._removed = tuple(removed)
        self.performed = False

    def __call__(self):
        for name in self._added:
            (self._directory / name).write_bytes(b"\x00" * 8)
        for name in self._removed:
            os.unlink(self._directory / name)
        self.performed = True


class _RecordedSurveyIterator(_RecordedIterator):
    """`_RecordedIterator`, with the two enumeration-time windows opened.

    The recorder above pins WHICH object a handle stayed on, and that evidence
    -- `yielded`, `closed`, `undrained` -- is exactly what these controls need
    too, so it is inherited rather than reimplemented and a reader comparing
    the two blocks is comparing the same measurements.

    What is added is two injection points the recorder deliberately does not
    have: one immediately after the first entry has been handed to the caller
    and consumed by it, and one at the close that ends the scan block. The
    close hook runs AFTER the real handle has been released, so the window it
    opens is unambiguously "the enumeration is over and the manifest has not
    been resolved" rather than anything happening under a live handle.
    """

    __slots__ = ("_after_first_entry", "_at_close")

    def __init__(self, real, *, after_first_entry=None, at_close=None):
        super().__init__(real)
        self._after_first_entry = after_first_entry
        self._at_close = at_close

    def __iter__(self):
        for index, entry in enumerate(self._real):
            self.yielded.append(entry.name)
            yield entry
            if index == 0 and self._after_first_entry is not None:
                self._after_first_entry()

    def __exit__(self, *exc):
        result = super().__exit__(*exc)
        if self._at_close is not None:
            self._at_close()
        return result


class _ScandirAroundTheSurveyScan:
    """`os.scandir`, wrapped so one deferred action lands in one exact window.

    `when="before_scandir"` acts on the other side of the same call the survey
    makes, which is the window an opening proof leaves behind and a pre-loop
    proof must close. `when="after_scandir"` acquires the real iterator over
    the ORIGINAL object, acts, and then hands back the iterator it already
    holds -- the window in which the handle and the pathname part company.
    `when="mid_enumeration"` acts once the first entry has been counted, and
    `when="after_enumeration"` once the handle has been released.
    `when="never"` acts not at all, so the same seam can prove that the
    wrapper itself refuses nothing.

    Only the survey's own FIRST enumeration is interfered with. Every
    assertion a control makes for itself goes through `_listing`, which uses
    `os.listdir`, and every identity it reads goes through `_REAL_LSTAT`, so
    no fixture ever reads its own result back through the double under test.
    """

    __slots__ = ("_perform", "_when", "_at_close", "_real", "calls",
                 "iterators")

    def __init__(self, perform, *, when="after_scandir", at_close=None):
        self._perform = perform
        self._when = when
        self._at_close = at_close
        self._real = os.scandir
        self.calls = 0
        self.iterators = []

    def _act(self):
        if self._when != "never":
            self._perform()

    def _wrap(self, iterator):
        recorded = _RecordedSurveyIterator(
            iterator,
            after_first_entry=(self._act if self._when == "mid_enumeration"
                               else None),
            at_close=self._closer())
        self.iterators.append(recorded)
        return recorded

    def _closer(self):
        if self._when == "after_enumeration":
            if self._at_close is None:
                return self._act
            return lambda: (self._act(), self._at_close())
        return self._at_close

    def __call__(self, directory):
        self.calls += 1
        if self.calls > 1:
            return self._real(directory)
        if self._when == "before_scandir":
            self._act()
            return self._wrap(self._real(directory))
        iterator = self._real(directory)
        if self._when == "after_scandir":
            self._act()
        return self._wrap(iterator)


class _LstatThatActsWhenTheManifestIsResolved:
    """`os.lstat`, wrapped to act as the journal's pathname is first resolved.

    `_read_manifest_bytes` begins by reading the manifest's own metadata. That
    read is the first moment in the whole survey at which the journal's
    pathname is resolved, so acting immediately BEFORE it means every
    subsequent step inside the read -- the open, the `fstat` comparison, the
    second `lstat`, the bytes themselves -- sees one self-consistent
    substitute. The read therefore succeeds completely and returns a perfectly
    valid journal. Nothing inside `_read_manifest_bytes` is defeated, faulted
    or contradicted; it is simply pointed at another directory.

    Delegation is to `_REAL_LSTAT`, captured at import, so that a control
    combining this watcher with any other metadata double still reaches the
    genuine primitive exactly once per call.
    """

    __slots__ = ("_perform", "_when", "manifest_reads")

    def __init__(self, perform, *, when="manifest_lstat"):
        self._perform = perform
        self._when = when
        self.manifest_reads = 0

    def __call__(self, path, *args, **kwargs):
        if _names_the_manifest(path):
            self.manifest_reads += 1
            if self._when != "never" and self.manifest_reads == 1:
                self._perform()
        return _REAL_LSTAT(path, *args, **kwargs)


class _SurveyWindow:
    """Everything one installed window can be asked about afterwards."""

    __slots__ = ("when", "action", "scan", "lstat")

    def __init__(self, when, action, scan, lstat):
        self.when = when
        self.action = action
        self.scan = scan
        self.lstat = lstat

    @property
    def replacement(self):
        return getattr(self.action, "replacement", None)

    @property
    def iterator(self):
        """The one handle the survey opened, or None if it opened none."""
        if not self.scan.iterators:
            return None
        handle, = self.scan.iterators
        return handle


def _act_during_the_survey(monkeypatch, action, when, *, at_close=None):
    """Install `action` so it fires in exactly one named window.

    The scan wrapper is installed for EVERY window, including the
    manifest-resolution one and `never`, because its recording -- which names
    the handle yielded and whether it was closed -- is evidence every control
    wants and is not itself an injection.
    """
    assert when in _SURVEY_WINDOWS + ("never",), when
    scan_when = when if when in ("before_scandir", "after_scandir",
                                 "mid_enumeration",
                                 "after_enumeration") else "never"
    scan = _ScandirAroundTheSurveyScan(action, when=scan_when,
                                       at_close=at_close)
    monkeypatch.setattr(retention.os, "scandir", scan)
    watcher = _LstatThatActsWhenTheManifestIsResolved(
        action, when=when if when == "manifest_lstat" else "never")
    monkeypatch.setattr(retention.os, "lstat", watcher)
    return _SurveyWindow(when, action, scan, watcher)


def _replace_during_the_survey(monkeypatch, directory, when, *, entries=(),
                               records=(), at_close=None):
    substitution = _Substitution(directory, entries=entries, records=records,
                                 armed=when != "never")
    return _act_during_the_survey(monkeypatch, substitution, when,
                                  at_close=at_close)


class _CountedDirectoryIdentityReads:
    """Every non-following metadata read the survey takes of ONE pathname.

    Keyed on the normalised pathname so that the journal's own reads -- which
    `_read_manifest_bytes` takes of a different path and which scale with
    nothing -- are never confused with the directory proofs, which are what
    this is counting.
    """

    __slots__ = ("_target", "reads")

    def __init__(self, monkeypatch, directory):
        self._target = os.path.normcase(
            os.path.abspath(os.fspath(directory)))
        self.reads = 0
        monkeypatch.setattr(retention.os, "lstat", self)

    def __call__(self, path, *args, **kwargs):
        try:
            text = os.path.normcase(os.path.abspath(os.fspath(path)))
        except TypeError:
            text = None
        if text == self._target:
            self.reads += 1
        return _REAL_LSTAT(path, *args, **kwargs)


class _ManifestDescriptorLedger:
    """Every descriptor opened on a journal, and every close attempt on one.

    A refusal that leaked the journal's descriptor would pin the file open for
    the life of the process, and a double close would be a use-after-free
    against whatever number the operating system recycled into that slot.
    Both are counted rather than assumed.
    """

    __slots__ = ("opened", "closed")

    def __init__(self, monkeypatch):
        self.opened = []
        self.closed = []
        real_open = os.open
        real_close = os.close

        def _open(path, *args, **kwargs):
            handle = real_open(path, *args, **kwargs)
            if _names_the_manifest(path):
                self.opened.append(handle)
            return handle

        def _close(handle):
            if handle in self.opened:
                self.closed.append(handle)
            return real_close(handle)

        monkeypatch.setattr(retention.os, "open", _open)
        monkeypatch.setattr(retention.os, "close", _close)


class _CountedManifestReads:
    """How many times the survey resolved and read the journal at all.

    The proof taken after the scan block is the one that decides whether an
    unproved directory's journal is opened. Counting the calls says that
    directly, rather than inferring it from counts that a later refusal would
    have zeroed anyway.
    """

    __slots__ = ("calls", "_real")

    def __init__(self, monkeypatch):
        self.calls = 0
        self._real = retention._read_manifest_bytes
        monkeypatch.setattr(retention, "_read_manifest_bytes", self)

    def __call__(self, manifest, byte_budget):
        self.calls += 1
        return self._real(manifest, byte_budget)


class _CountedRecordParses:
    """How many journal records were actually decoded into objects.

    `json.loads` is where a record stops being bytes the survey is holding and
    becomes a value the survey is acting on. Requirement 5 says the bytes are
    DISCARDED when the directory is disproved after the read, and a count of
    zero here is what "discarded" means.
    """

    __slots__ = ("calls", "_real")

    def __init__(self, monkeypatch):
        self.calls = 0
        self._real = json.loads
        monkeypatch.setattr(retention.json, "loads", self)

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self._real(*args, **kwargs)


def _fake_pass_directory_metadata(monkeypatch, directory, *, replace,
                                  from_read=1):
    """Serve altered metadata for `directory` from the Nth read onwards.

    Modelled on `_fake_quarantine_root_metadata` above, and for the same
    reason: a real reparse point needs a privilege CI does not have, a second
    device needs a mount, and an object with no stable identity cannot be
    created on demand at all. The platform behaviour is modelled through a
    double so the control is deterministic everywhere.

    `from_read` is what makes it a WINDOW rather than a starting condition.
    Read zero is the survey's opening proof, and every later read is one of
    the three proofs the correction adds, so `from_read=1` is a substitution
    the opening proof cannot see and `from_read=3` is one that arrives while
    the journal is being read.
    """
    target = os.path.normcase(os.path.abspath(os.fspath(directory)))
    reads = []

    def _lstat(path, *args, **kwargs):
        info = _REAL_LSTAT(path, *args, **kwargs)
        try:
            text = os.path.normcase(os.path.abspath(os.fspath(path)))
        except TypeError:
            return info
        if text != target:
            return info
        reads.append(text)
        if len(reads) > from_read:
            return replace(info)
        return info

    monkeypatch.setattr(retention.os, "lstat", _lstat)
    return reads


def _reparsed(info):
    reparse = getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return _Stat(mode=info.st_mode, size=info.st_size,
                 mtime_ns=info.st_mtime_ns, nlink=1, dev=info.st_dev,
                 ino=info.st_ino, file_attributes=reparse)


def _moved_to_another_device(info):
    return _Stat(mode=info.st_mode, size=info.st_size,
                 mtime_ns=info.st_mtime_ns, nlink=1, dev=info.st_dev + 1,
                 ino=info.st_ino)


def _without_a_stable_identity(info):
    return _Stat(mode=info.st_mode, size=info.st_size,
                 mtime_ns=info.st_mtime_ns, nlink=1, dev=0, ino=0)


_METADATA_SUBSTITUTIONS = [
    ("reparse_point", _reparsed),
    ("another_device", _moved_to_another_device),
    ("no_identity", _without_a_stable_identity),
]


def _assert_a_sanitized_refusal(survey, reason):
    """The whole refusal, checked as one shape rather than one field.

    A survey refusal is an aggregate the operator sees. It must carry the
    reason, nothing else, and NO count -- a partial answer over a directory
    the pass could not prove is exactly what "never a partial answer" rules
    out -- and it must carry no name, path or errno in any field.
    """
    assert survey.refused is reason, survey
    assert (survey.present, survey.manifested, survey.unmanifested) == (
        0, 0, 0), "a refusal reported counts over a directory it disproved"
    assert (survey.malformed_records, survey.duplicates) == (0, 0), (
        "a refusal reported journal findings it was not entitled to")
    for field in dataclasses.fields(survey):
        value = getattr(survey, field.name)
        assert not isinstance(value, (str, bytes, Path)), field.name
        assert not isinstance(value, OSError), field.name


# -- the premise, proved on the real platform with no retention code ---------

def test_a_pass_directory_handle_and_its_pathname_really_do_part_company(
        tmp_path):
    """Every control below rests on one claim about this platform: an
    `os.scandir` iterator binds the OBJECT, and a pathname resolved afterwards
    binds the NAME. If they did not part company here, the controls would be
    refusing for some other reason entirely and would prove nothing about the
    windows they are named for.

    So it is asserted, on real directories, using no retention code at all --
    including the sharpest form of the split: the handle keeps producing the
    original's entries while an `lstat` of the JOURNAL's pathname resolves
    inside the substitute, which is precisely how one answer comes to be
    assembled out of two directories.
    """
    directory, names = _journalled_pass_directory(tmp_path, payloads=2,
                                                  journal=False)
    records = [_record_bytes(name) for name in names]
    handle = _RecordedSurveyIterator(os.scandir(directory))
    replacement = _replace_pass_directory_pathname(directory, records=records)
    with handle as entries:
        enumerated = sorted(entry.name for entry in entries)

    assert replacement.before != replacement.after
    assert enumerated == sorted(names), (
        "the handle stopped enumerating the object it was opened on")
    assert _listing(directory) == [retention.MANIFEST_NAME], (
        "the pathname did not come to name the substitute")
    assert _listing(replacement.displaced) == sorted(names), (
        "the original directory did not survive the substitution intact")
    journal = _REAL_LSTAT(directory / retention.MANIFEST_NAME)
    assert stat_module.S_ISREG(journal.st_mode), (
        "the journal pathname does not resolve inside the substitute")
    assert _directory_identity(replacement.displaced) == replacement.before
    assert _directory_identity(directory) == replacement.after
    assert handle.closed == 1


def test_the_survey_window_seam_refuses_nothing_when_it_substitutes_nothing(
        tmp_path, monkeypatch):
    """The seam is not the refusal.

    Both wrappers are installed -- the scan recorder and the `lstat` watcher
    -- with nothing armed, and an ordinary survey must come back byte for byte
    what an uninstrumented one does. An injection model that changed the
    answer by existing would make every refusal below unattributable.
    """
    directory, names = _journalled_pass_directory(tmp_path, payloads=3)
    reference = _survey(directory)
    window = _replace_during_the_survey(monkeypatch, directory, "never")
    survey = _survey(directory)

    assert window.replacement is None
    assert window.scan.calls == 1
    assert window.lstat.manifest_reads >= 1, (
        "the journal was never resolved, so the watcher watched nothing")
    assert window.iterator.closed == 1
    assert sorted(window.iterator.yielded) == sorted(
        names + [retention.MANIFEST_NAME])
    assert survey == reference
    assert survey.refused is None
    assert (survey.present, survey.manifested, survey.unmanifested) == (
        3, 3, 0)


# -- the headline: one answer assembled out of two directories ---------------

@pytest.mark.parametrize("when", _COMPOSING_WINDOWS)
def test_the_survey_never_reconciles_two_directories_into_one_answer(
        tmp_path, monkeypatch, when):
    """The defect, stated as the operator sees it.

    The original holds payloads and NO journal. The substitute holds a journal
    naming exactly those payloads and NO payloads. Neither directory, surveyed
    on its own, reconciles: the original reports everything unmanifested, and
    the substitute reports nothing at all. Both of those reference answers are
    taken here, from the same two objects, so the composite cannot be dismissed
    as a fixture that was reconciled all along.

    Uncorrected, the survey enumerates the original through the handle and
    reads the substitute's journal through the pathname, and returns
    `refused=None` with `unmanifested=0` -- a fully journalled pass that never
    existed. An operator acting on that answer restores nothing, because the
    answer says there is nothing to restore.
    """
    directory, names = _journalled_pass_directory(tmp_path, payloads=2,
                                                  journal=False)
    records = [_record_bytes(name) for name in names]
    window = _replace_during_the_survey(monkeypatch, directory, when,
                                        records=records)
    survey = _survey(directory)

    replacement = window.replacement
    assert replacement.before != replacement.after
    assert _listing(replacement.displaced) == sorted(names), (
        "the original must hold the payloads and no journal")
    assert _listing(directory) == [retention.MANIFEST_NAME], (
        "the substitute must hold the journal and no payload")
    assert sorted(window.iterator.yielded) in (sorted(names), []), (
        "the handle enumerated something that was neither directory")

    _assert_a_sanitized_refusal(
        survey, retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID)

    original_alone = _survey(replacement.displaced)
    assert (original_alone.refused, original_alone.present,
            original_alone.manifested, original_alone.unmanifested) == (
                None, 2, 0, 2), "the original alone must not reconcile"
    substitute_alone = _survey(directory)
    assert (substitute_alone.refused, substitute_alone.present,
            substitute_alone.manifested, substitute_alone.unmanifested) == (
                None, 0, 0, 0), "the substitute alone holds no payload at all"


# -- every window, one control each ------------------------------------------

@pytest.mark.parametrize("when", _SURVEY_WINDOWS)
def test_a_pass_directory_replaced_in_any_window_is_refused(
        tmp_path, monkeypatch, when):
    """One refusal per window, with the substitute made as ORDINARY as the
    original: a real directory, not a junction, not a symlink, not a mount
    point, carrying the same payload names and the same journal. It surveys
    perfectly cleanly when nothing is disturbing it.

    So the pathname identifies a directory that is entirely usable and simply
    is not the one that was proved, and that -- alone -- is what the refusal
    is about.
    """
    directory, names = _journalled_pass_directory(tmp_path, payloads=2)
    records = [_record_bytes(name) for name in names]
    window = _replace_during_the_survey(monkeypatch, directory, when,
                                        entries=names, records=records)
    survey = _survey(directory)

    assert window.replacement.before != window.replacement.after
    assert sorted(window.replacement.decoy_names) == sorted(
        names + [retention.MANIFEST_NAME]), (
        "the substitute must carry the same names, or the refusal could be a "
        "content difference and nothing more")
    _assert_a_sanitized_refusal(
        survey, retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID)
    assert _survey(window.replacement.displaced).refused is None, (
        "the ORIGINAL is a perfectly surveyable directory")


@pytest.mark.parametrize("when", _SURVEY_WINDOWS)
def test_a_replacement_refusal_mutates_neither_directory(tmp_path, monkeypatch,
                                                         when):
    """Reconciliation is read-only in every circumstance, and a refusal is
    still a reconciliation. Both objects are checked, because a correction
    that tidied up after itself would leave the original intact and the
    substitute changed."""
    directory, names = _journalled_pass_directory(tmp_path, payloads=2)
    records = [_record_bytes(name) for name in names]
    window = _replace_during_the_survey(monkeypatch, directory, when,
                                        entries=names, records=records)
    survey = _survey(directory)

    displaced = window.replacement.displaced
    assert survey.refused is (
        retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID)
    assert _listing(displaced) == sorted(names + [retention.MANIFEST_NAME])
    assert _listing(directory) == sorted(names + [retention.MANIFEST_NAME])
    assert (displaced / retention.MANIFEST_NAME).read_bytes() == b"".join(
        records)
    assert (directory / retention.MANIFEST_NAME).read_bytes() == b"".join(
        records)
    assert _directory_identity(displaced) == window.replacement.before
    assert _directory_identity(directory) == window.replacement.after


def test_the_survey_refusal_emits_nothing_at_all(tmp_path, monkeypatch,
                                                 capsys):
    """The module's output is path-free everywhere else and must stay so on
    the new refusal path. Names are the one thing a pass directory is full
    of."""
    directory, names = _journalled_pass_directory(tmp_path, payloads=2)
    _replace_during_the_survey(monkeypatch, directory, "after_scandir",
                               entries=names)
    survey = _survey(directory)
    printed = capsys.readouterr()

    assert survey.refused is (
        retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID)
    assert printed.out == ""
    assert printed.err == ""
    for leak in (names[0], "v070_gen", str(tmp_path), str(directory),
                 "Errno", "OSError", "Traceback", ".decoy", ".displaced"):
        assert leak not in printed.out, leak
        assert leak not in printed.err, leak


def test_main_fails_closed_when_the_held_lock_parent_cannot_be_released(
        tmp_path, monkeypatch, capsys):
    """A borrowed anchor close failure cannot follow a clean-success line."""
    data, lock_path = _lock_layout(tmp_path)
    _populate(data, snapshots=3)
    real_release = retention._DirectoryAnchor.release

    def _failed_release(anchor):
        real_release(anchor)
        return False

    monkeypatch.setattr(retention._DirectoryAnchor, "release",
                        _failed_release)
    status = retention.main([str(data), "--lock", str(lock_path)])
    printed = capsys.readouterr()

    assert status == 1
    assert "refused=lock_unavailable" in printed.out
    assert "halted=True" in printed.out
    assert printed.err == ""


def test_main_fails_closed_when_the_held_target_cannot_be_released(
        tmp_path, monkeypatch, capsys):
    """A borrowed target close failure is part of the operator outcome."""
    data, lock_path = _lock_layout(tmp_path)
    _populate(data, snapshots=3)
    real_release = retention._DirectoryBinding.release

    def _failed_release(binding):
        real_release(binding)
        return False

    monkeypatch.setattr(retention._DirectoryBinding, "release",
                        _failed_release)
    status = retention.main([str(data), "--lock", str(lock_path)])
    printed = capsys.readouterr()

    assert status == 1
    assert "refused=identity_unavailable" in printed.out
    assert "halted=True" in printed.out
    assert printed.err == ""


# -- what the handle did, and what it must not have done ---------------------

@pytest.mark.parametrize("when", ["before_scandir", "after_scandir"])
def test_a_replacement_before_the_first_entry_is_refused_unenumerated(
        tmp_path, monkeypatch, when):
    """A directory that has not been proved must not be read AT ALL.

    Both of these windows close before the loop begins, so the proof inside
    the scan block is reached with nothing consumed. The handle must come back
    closed and empty on both counts: nothing yielded, and nothing left to
    yield -- an open handle over a refused directory would pin it for the life
    of the process on the very platform whose rename semantics this module is
    built around.
    """
    directory, names = _journalled_pass_directory(tmp_path, payloads=3)
    window = _replace_during_the_survey(monkeypatch, directory, when,
                                        entries=names)
    survey = _survey(directory)

    handle = window.iterator
    assert window.replacement.before != window.replacement.after
    assert survey.refused is (
        retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID)
    assert handle.yielded == [], (
        "entries were read inside a directory the survey had not proved")
    assert handle.closed == 1, "the scandir handle was not released"
    assert handle.undrained() == [], (
        "the handle was left open on the directory that was refused")


@pytest.mark.parametrize("when", _SURVEY_WINDOWS + ("never",))
def test_the_scan_handle_is_closed_exactly_once_on_every_outcome(
        tmp_path, monkeypatch, when):
    """One acquisition, one release, whatever the survey decided. Exactly
    once matters in both directions: a missing close leaks, and a second close
    would run against whatever the operating system recycled into that
    slot."""
    directory, names = _journalled_pass_directory(tmp_path, payloads=2)
    window = _replace_during_the_survey(monkeypatch, directory, when,
                                        entries=names)
    _survey(directory)

    assert window.scan.calls == 1
    assert window.iterator.closed == 1


@pytest.mark.parametrize("when", ["never", "manifest_lstat"])
def test_every_manifest_descriptor_is_closed_exactly_once(tmp_path,
                                                          monkeypatch, when):
    """The journal descriptor's lifetime is unchanged by the correction.

    `never` is the ordinary read, and `manifest_lstat` is the one window in
    which the bytes are read in full and then discarded -- the case where a
    descriptor is easiest to forget, because the value it produced is thrown
    away.
    """
    directory, names = _journalled_pass_directory(tmp_path, payloads=2)
    records = [_record_bytes(name) for name in names]
    _replace_during_the_survey(monkeypatch, directory, when, records=records)
    ledger = _ManifestDescriptorLedger(monkeypatch)
    _survey(directory)

    assert len(ledger.opened) == 1, "the journal was not read exactly once"
    assert ledger.closed == ledger.opened, (
        "a journal descriptor was leaked or closed twice")


# -- the three proofs, each doing something the others cannot ----------------

@pytest.mark.parametrize("when", ["mid_enumeration", "after_enumeration"])
def test_no_journal_is_opened_once_the_scan_block_has_been_disproved(
        tmp_path, monkeypatch, when):
    """The proof after the scan block is the one that decides whether an
    unproved directory's journal is opened at all.

    These two windows are past the pre-loop proof, so only the post-scan proof
    stands between the substitution and the substitute's journal. Uncorrected,
    the survey opens and reads it. The reference count taken first proves the
    counter is not simply reporting zero for everything.
    """
    directory, names = _journalled_pass_directory(tmp_path, payloads=2)
    records = [_record_bytes(name) for name in names]

    reference = _CountedManifestReads(monkeypatch)
    assert _survey(directory).refused is None
    assert reference.calls == 1, "an undisturbed survey reads its journal"

    window = _replace_during_the_survey(monkeypatch, directory, when,
                                        records=records)
    counted = _CountedManifestReads(monkeypatch)
    survey = _survey(directory)

    assert window.replacement.before != window.replacement.after
    assert survey.refused is (
        retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID)
    assert counted.calls == 0, (
        "the journal of a directory the survey had disproved was read")


def test_no_record_is_parsed_once_the_journal_read_disproves_the_directory(
        tmp_path, monkeypatch):
    """Requirement 5 says the manifest bytes are DISCARDED on a mismatch
    detected after the read, and this is what discarding them means: not one
    record is decoded into a value the survey then acts on.

    This is the window no earlier proof can reach. The substitution arrives
    while the journal's own pathname is being resolved, so the pre-loop proof
    and the post-scan proof have both already passed and agreed.
    """
    directory, names = _journalled_pass_directory(tmp_path, payloads=2,
                                                  journal=False)
    records = [_record_bytes(name) for name in names]

    reference_window = _replace_during_the_survey(monkeypatch, directory,
                                                  "never")
    reference = _CountedRecordParses(monkeypatch)
    assert _survey(directory).refused is None
    assert reference_window.replacement is None
    assert reference.calls == 0, "the original carries no journal to parse"

    window = _replace_during_the_survey(monkeypatch, directory,
                                        "manifest_lstat", records=records)
    counted = _CountedRecordParses(monkeypatch)
    survey = _survey(directory)

    assert window.lstat.manifest_reads >= 1
    assert window.replacement.before != window.replacement.after
    assert survey.refused is (
        retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID)
    assert counted.calls == 0, (
        "records were parsed out of a journal the survey had disproved")
    assert (survey.malformed_records, survey.duplicates) == (0, 0)


def test_the_entry_count_of_the_enumerated_object_cannot_choose_the_reason(
        tmp_path, monkeypatch):
    """A refusal reason is a diagnosis, and it must not be selectable by
    whatever the pass directory happens to hold.

    The original overflows the entry budget; the substitute does not. Without
    a proof taken BEFORE the loop, the enumeration reaches the budget first
    and returns `SURVEY_LIMIT_EXCEEDED` -- a bounds diagnosis for a directory
    that was replaced -- and every later proof is unreachable behind that
    early return. The operator is told the pass is too big, and is never told
    the pathname moved.

    The undisturbed reference is taken first, so the limit refusal is known to
    be reachable and this control cannot pass by the limit never firing.
    """
    directory, names = _journalled_pass_directory(tmp_path, payloads=6,
                                                  journal=False)
    policy = dataclasses.replace(_quarantine_policy(),
                                 max_actions_per_pass=2)
    assert _survey(directory, policy).refused is (
        retention.RetentionFailureReason.SURVEY_LIMIT_EXCEEDED), (
        "the fixture must overflow the entry budget when left alone")

    window = _replace_during_the_survey(monkeypatch, directory,
                                        "after_scandir",
                                        entries=names[:1])
    survey = _survey(directory, policy)

    assert window.replacement.before != window.replacement.after
    assert len(_listing(window.replacement.displaced)) > 2, (
        "the enumerated object must be the one that overflows")
    assert len(window.replacement.decoy_names) <= 2, (
        "the substitute must be within the budget, so the two objects "
        "disagree about whether the limit was reached")
    _assert_a_sanitized_refusal(
        survey, retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID)
    assert window.iterator.yielded == [], (
        "the overflowing directory was enumerated before it was proved")


def test_the_length_of_a_substituted_journal_cannot_choose_the_reason(
        tmp_path, monkeypatch):
    """The same argument at the other end of the survey, and the reason the
    third proof is placed BEFORE the byte-budget comparison.

    Measuring the substitute's bytes to pick a refusal reason is not
    discarding them, and it hands the choice of diagnosis to whoever wrote
    them: a long journal produces `SURVEY_LIMIT_EXCEEDED` and a short one
    produces the reconciled composite. Neither answer mentions the only thing
    that actually happened.

    The undisturbed reference is taken first against a journal of the same
    length, so the budget refusal is known to be reachable.
    """
    policy = dataclasses.replace(_quarantine_policy(),
                                 max_actions_per_pass=1)
    budget = 1 * retention.MAX_MANIFEST_RECORD_BYTES
    oversized = [b"x" * (budget + 8) + b"\n"]

    # A separate parent, because `_pass_dir` creates the quarantine root and
    # will not create it twice under one `tmp_path`.
    reference_parent = tmp_path / "reference"
    reference_parent.mkdir()
    reference_directory = _pass_dir(reference_parent, records=oversized,
                                    extra_files=[_snap_name(1, 1)])
    assert _survey(reference_directory, policy).refused is (
        retention.RetentionFailureReason.SURVEY_LIMIT_EXCEEDED), (
        "the fixture journal must overflow the byte budget when left alone")

    directory, _names = _journalled_pass_directory(tmp_path, payloads=1,
                                                   journal=False)
    window = _replace_during_the_survey(monkeypatch, directory,
                                        "manifest_lstat", records=oversized)
    survey = _survey(directory, policy)

    assert window.replacement.before != window.replacement.after
    assert len((directory / retention.MANIFEST_NAME).read_bytes()) > budget
    _assert_a_sanitized_refusal(
        survey, retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID)


# -- an unproved directory whose metadata, not whose identity, went bad ------

@pytest.mark.parametrize("label,replace", _METADATA_SUBSTITUTIONS,
                         ids=[row[0] for row in _METADATA_SUBSTITUTIONS])
@pytest.mark.parametrize("from_read", [1, 2, 3],
                         ids=["before_the_scan", "before_the_journal",
                              "after_the_journal"])
def test_a_pass_directory_that_stops_being_usable_between_proofs_fails_closed(
        tmp_path, monkeypatch, label, replace, from_read):
    """`(device, inode)` says WHICH object a pathname is, never what KIND.

    A pathname that has become a reparse point, or has moved to another
    device, or reports no stable identity at all, is not somewhere a survey
    may go on reading -- and none of those is a difference an identity
    comparison alone would notice, because `_scanned_root_unchanged` asks
    `directory_state`, which proves kind and identity together.

    The three read positions are the three proofs. Modelled through
    controlled metadata, exactly as the quarantine-root controls above are,
    because a real reparse point needs a privilege CI does not have and an
    object with no stable identity cannot be created on demand.

    The undisturbed reference is taken first, so a refusal cannot be the
    fixture being unsurveyable to begin with.
    """
    directory, _names = _journalled_pass_directory(tmp_path, payloads=2)
    assert _survey(directory).refused is None, (
        "the fixture must survey cleanly before any metadata is altered")

    reads = _fake_pass_directory_metadata(monkeypatch, directory,
                                          replace=replace,
                                          from_read=from_read)
    survey = _survey(directory)

    assert len(reads) > from_read, (
        "the survey never took a %s proof, so nothing was substituted"
        % label)
    _assert_a_sanitized_refusal(
        survey, retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID)


# -- the identity budget -----------------------------------------------------

@pytest.mark.parametrize("payloads,journal", [(0, False), (1, True),
                                              (8, True), (24, True)],
                         ids=["empty", "one", "eight", "twenty_four"])
def test_the_survey_reads_the_directory_identity_a_fixed_four_times(
        tmp_path, monkeypatch, payloads, journal):
    """Four reads: the opening proof, and the three the correction adds.

    Fixed is the point. A proof taken per entry or per record would turn a
    bounded reconciliation into work that scales with a directory an operator
    may have added to, which is the one thing this whole module refuses to do.
    The journal's own metadata reads are a different pathname and are not
    counted here.
    """
    directory, _names = _journalled_pass_directory(tmp_path,
                                                   payloads=payloads,
                                                   journal=journal)
    counted = _CountedDirectoryIdentityReads(monkeypatch, directory)
    survey = _survey(directory)

    assert survey.refused is None
    assert survey.present == payloads
    assert counted.reads == 4, (
        "the directory identity was read %d times for %d entries"
        % (counted.reads, payloads))


# -- nothing about an undisturbed survey may change --------------------------

def test_a_stable_pass_directory_reconciles_exactly_as_it_did_before(tmp_path):
    """No injection at all. A stable directory passes all three proofs, so the
    ordinary answer -- and the precedence that produces it -- is untouched."""
    directory, names = _journalled_pass_directory(tmp_path, payloads=3)
    survey = _survey(directory)

    assert survey.refused is None
    assert (survey.present, survey.manifested, survey.unmanifested) == (
        3, 3, 0)
    assert (survey.malformed_records, survey.duplicates) == (0, 0)
    assert _listing(directory) == sorted(
        names + [retention.MANIFEST_NAME])


def test_a_stable_pass_directory_with_no_journal_is_still_unjournalled(
        tmp_path):
    """A crash between the last rename and the journal write leaves a
    directory of fully restorable files and no record of them. That is a
    counted, reported state and not a refusal, and the correction must not
    have turned an absent journal into a disproved directory."""
    directory, names = _journalled_pass_directory(tmp_path, payloads=3,
                                                  journal=False)
    survey = _survey(directory)

    assert survey.refused is None
    assert (survey.present, survey.manifested, survey.unmanifested) == (
        0 + 3, 0, 3)
    assert retention.MANIFEST_NAME not in _listing(directory)
    assert _listing(directory) == sorted(names)


def test_content_changing_after_the_enumeration_is_not_a_replacement(
        tmp_path, monkeypatch):
    """A directory's size and modification time change whenever its contents
    do, and an operator may legitimately be adding to a quarantine pass while
    it is being surveyed. The correction compares the `(device, inode)` pair
    for exactly this reason, and a 4-tuple comparison here would call ordinary
    activity a hostile swap.

    The change lands once the handle has been released, so the enumeration is
    finished and the expected answer is one fixed tuple on every platform.
    Both proofs still to come -- the one before the journal is resolved, and
    the one after it is read -- see a changed directory that is the same
    object, and must pass.
    """
    directory, names = _journalled_pass_directory(tmp_path, payloads=3)
    identity = _directory_identity(directory)
    before = _listing(directory)
    change = _ContentChangedInPlace(directory,
                                    added=["operator_added.tmp"],
                                    removed=[names[-1]])
    window = _act_during_the_survey(monkeypatch, change, "after_enumeration")
    survey = _survey(directory)

    assert change.performed, "the fixture changed nothing"
    assert _listing(directory) != before, "the contents did not really change"
    assert _directory_identity(directory) == identity, (
        "the fixture replaced the directory instead of changing it")
    assert survey.refused is None, (
        "an ordinary content change was reported as a replacement")
    assert (survey.present, survey.manifested, survey.unmanifested) == (
        3, 3, 0)
    assert window.iterator.closed == 1


def test_content_changing_during_the_enumeration_is_not_a_replacement(
        tmp_path, monkeypatch):
    """The same statement in the harder window, with the change landing under
    a live handle.

    The COUNTS are deliberately not asserted here. Whether an entry created
    after an iterator was acquired is yielded by that iterator is a platform
    question this file does not answer and must not rest on. What is asserted
    is the whole of what the correction is about: the pathname still names the
    same object, so this is not a replacement and must not be refused as one,
    and whatever was enumerated is accounted for exactly once.
    """
    directory, _names = _journalled_pass_directory(tmp_path, payloads=3)
    identity = _directory_identity(directory)
    before = _listing(directory)
    change = _ContentChangedInPlace(directory, added=["operator_added.tmp"])
    window = _act_during_the_survey(monkeypatch, change, "mid_enumeration")
    survey = _survey(directory)

    assert change.performed, "the fixture changed nothing"
    assert _listing(directory) != before, "the contents did not really change"
    assert _directory_identity(directory) == identity, (
        "the fixture replaced the directory instead of changing it")
    assert survey.refused is None, (
        "an ordinary content change was reported as a replacement")
    assert survey.present == survey.manifested + survey.unmanifested
    assert survey.present >= 3, "the pre-existing payloads must all be counted"
    assert (survey.malformed_records, survey.duplicates) == (0, 0)
    assert window.iterator.closed == 1


# -- every pre-existing refusal keeps its precedence -------------------------

def test_an_invalid_pass_directory_is_still_refused_before_any_enumeration(
        tmp_path, monkeypatch):
    """The opening proof still comes first and still short-circuits
    everything: a pathname that is not a directory is refused without a
    single `os.scandir` call, which is what makes the new pre-loop proof an
    addition rather than a replacement."""
    root = tmp_path / retention.QUARANTINE_DIRNAME
    root.mkdir()
    impostor = root / "p20260101T000000"
    impostor.write_bytes(b"not a directory")
    window = _replace_during_the_survey(monkeypatch, impostor, "never")
    survey = _survey(impostor)

    _assert_a_sanitized_refusal(
        survey, retention.RetentionFailureReason.SURVEY_DIRECTORY_INVALID)
    assert window.scan.calls == 0, (
        "an unproved pathname was enumerated before it was refused")


def test_the_entry_limit_refusal_is_unchanged_for_a_stable_directory(tmp_path):
    directory, _names = _journalled_pass_directory(tmp_path, payloads=6,
                                                   journal=False)
    policy = dataclasses.replace(_quarantine_policy(),
                                 max_actions_per_pass=2)
    survey = _survey(directory, policy)
    _assert_a_sanitized_refusal(
        survey, retention.RetentionFailureReason.SURVEY_LIMIT_EXCEEDED)


def test_the_journal_byte_limit_refusal_is_unchanged_for_a_stable_directory(
        tmp_path):
    policy = dataclasses.replace(_quarantine_policy(),
                                 max_actions_per_pass=1)
    budget = 1 * retention.MAX_MANIFEST_RECORD_BYTES
    directory = _pass_dir(tmp_path, records=[b"x" * (budget + 8) + b"\n"],
                          extra_files=[_snap_name(1, 1)])
    survey = _survey(directory, policy)
    _assert_a_sanitized_refusal(
        survey, retention.RetentionFailureReason.SURVEY_LIMIT_EXCEEDED)


def test_the_record_count_limit_refusal_is_unchanged_for_a_stable_directory(
        tmp_path):
    directory = _pass_dir(
        tmp_path,
        records=[_record_bytes(_snap_name(index, index))
                 for index in range(6)],
        extra_files=[_snap_name(1, 1)])
    policy = dataclasses.replace(_quarantine_policy(),
                                 max_actions_per_pass=2)
    survey = _survey(directory, policy)
    _assert_a_sanitized_refusal(
        survey, retention.RetentionFailureReason.SURVEY_LIMIT_EXCEEDED)


def test_malformed_and_duplicate_records_are_still_counted_not_refused(
        tmp_path):
    """Malformed records are evidence of how a pass ended and are counted,
    never repaired and never escalated into a refusal. The correction adds
    three proofs that a stable directory passes, so this survives untouched."""
    name = _snap_name(1, 1)
    directory = _pass_dir(
        tmp_path,
        records=[_record_bytes(name), _record_bytes(name),
                 b"{ not json\n", _record_bytes(name, extra="unexpected")],
        extra_files=[name])
    survey = _survey(directory)

    assert survey.refused is None
    assert survey.duplicates == 1
    assert survey.malformed_records == 2
    assert (survey.present, survey.manifested, survey.unmanifested) == (
        1, 1, 0)


# -- what the correction still cannot see, said out loud ---------------------

def test_a_substitution_withdrawn_between_two_proofs_is_not_detected(
        tmp_path, monkeypatch):
    """A DISCLOSED LIMIT, pinned so nobody has to rediscover it.

    Three proofs compare `(device, inode)` at three instants. A substitution
    installed and withdrawn wholly between two of them leaves every proof
    reading the identity it expects, and the survey reconciles normally. The
    answer here is the ORIGINAL's own answer -- the substitute contributed
    nothing, because it was gone before the journal was resolved -- so this
    is a limit on DETECTION, not a wrong answer.

    The two other disclosed limits are of the same kind and are not
    mechanisable here: a `(device, inode)` pair recycled onto a new object
    compares equal, and no proof binds the operating-system handle, because
    the survey acts on a PATHNAME the operating system resolves afresh each
    time. This module says so in `_scanned_root_unchanged`'s own docstring:
    it detects replacement, and is not an atomic defence against a hostile
    swap.
    """
    directory, names = _journalled_pass_directory(tmp_path, payloads=2,
                                                  journal=False)
    records = [_record_bytes(name) for name in names]
    substitution = _Substitution(directory, records=records)
    withdrawal = _WithdrawnSubstitution(directory, substitution)
    window = _act_during_the_survey(monkeypatch, substitution,
                                    "mid_enumeration", at_close=withdrawal)
    survey = _survey(directory)

    assert window.replacement is not None
    assert window.replacement.before != window.replacement.after
    assert withdrawal.restored == window.replacement.before, (
        "the withdrawal did not put the original back")
    assert survey.refused is None
    assert (survey.present, survey.manifested, survey.unmanifested) == (
        2, 0, 2), "the answer is the original's own, not a composite"
    assert _directory_identity(directory) == window.replacement.before


# -- the correction's surface ------------------------------------------------

def test_the_survey_correction_adds_no_symbol_of_any_kind(tmp_path):
    """Three calls to a helper that already exists, against an identity the
    survey already reads. No new public name, no new failure reason, no new
    output field, and no new parameter -- other passes and other code depend
    on every one of those, and widening any of them would be a different
    change from the one that was authorized.
    """
    assert len(retention.__all__) == 34
    assert "_scanned_root_unchanged" not in retention.__all__
    assert len(list(retention.RetentionFailureReason)) == 20
    assert [field.name for field in
            dataclasses.fields(retention.QuarantineSurvey)] == [
                "present", "manifested", "unmanifested", "malformed_records",
                "duplicates", "refused"]
    code = retention.survey_quarantine.__code__
    assert code.co_argcount == 1
    assert code.co_kwonlyargcount == 1
    assert code.co_varnames[:2] == ("pass_directory", "policy")


# ===========================================================================
# P1 -- the LOCK must be proved OUTSIDE the maintained directory before it is
# opened
# ===========================================================================
#
# `main()` selects the lock and enters `single_instance_lock()` BEFORE
# `run_pass()` ever scans the target:
#
#     lock_path = args.lock or default_lock_path(args.directory)
#     with single_instance_lock(lock_path) as acquired:
#
# `_LockHandle.acquire()` opens with `os.O_CREAT`, so a `--lock` inside the
# maintained directory CREATES an entry there -- in PLAN mode too, which is
# supposed to measure the directory without touching it. Worse, a target
# already at `max_directory_entries` is pushed OVER the scanner limit by that
# one new entry, and every subsequent pass then refuses with
# `entry_limit_exceeded` before retention can deliver any relief. The
# directory becomes wedged at exactly the moment maintenance is needed.
#
# The default lock path is normally in the system temporary directory, but
# nothing proves that directory is outside the target, so the default is run
# through the same decision rather than trusted.
#
# The refusal reuses the EXISTING `LOCK_UNAVAILABLE` code. That is not a
# stretch of its meaning: `acquire()` already returns it when the lock cannot
# be opened at all ("Cannot even open the lock: report the fixed code and do
# nothing"). Declining to open a lock whose placement is unsafe is the same
# class of outcome, and the closed reason set therefore stays at twenty.


def _inside_lock(target):
    """A lock path directly inside the maintained directory."""
    return Path(os.fspath(target)) / "retention.lock"


def _assert_refused_without_locator(status, printed, target, lock):
    """The fixed, sanitized refusal: code only, no locator, nothing on stderr."""
    assert status == 1
    assert (retention.RetentionFailureReason.LOCK_UNAVAILABLE.value
            in printed.out)
    assert printed.err == ""
    for leak in (str(target), str(lock), "Traceback", "Errno", "errno"):
        assert leak not in printed.out
        assert leak not in printed.err


def test_plan_refuses_a_lock_placed_inside_the_target(tmp_path, capsys):
    """PLAN must not create an entry in the directory it is measuring."""
    root = _scanned_root(tmp_path, snapshots=3)
    lock = _inside_lock(root)
    before = _listing(root)
    status = retention.main([str(root), "--lock", str(lock)])
    printed = capsys.readouterr()
    _assert_refused_without_locator(status, printed, root, lock)
    assert _listing(root) == before
    assert not lock.exists()


def test_quarantine_refuses_a_lock_placed_inside_the_target(tmp_path, capsys):
    """The same decision guards the acting mode, not just the dry run."""
    root = _scanned_root(tmp_path, snapshots=3)
    lock = _inside_lock(root)
    before = _listing(root)
    status = retention.main([str(root), "--quarantine", "--lock", str(lock)])
    printed = capsys.readouterr()
    _assert_refused_without_locator(status, printed, root, lock)
    assert _listing(root) == before
    assert not lock.exists()
    assert not _quarantine_root(root).exists()


def test_the_target_itself_as_the_lock_path_is_refused(tmp_path, monkeypatch,
                                                       capsys):
    """The directory is not outside itself.

    Opening a directory fails on its own, so a status check alone would pass
    vacuously against the unfixed code. The control therefore also proves the
    target was never OPENED as a lock -- the decision has to come first.
    """
    root = _scanned_root(tmp_path, snapshots=2)
    opened = []
    genuine = retention.os.open

    def _recording(path, *args, **kwargs):
        opened.append(os.fspath(path))
        return genuine(path, *args, **kwargs)

    monkeypatch.setattr(retention.os, "open", _recording)
    before = _listing(root)
    status = retention.main([str(root), "--lock", str(root)])
    printed = capsys.readouterr()
    _assert_refused_without_locator(status, printed, root, root)
    assert os.fspath(root) not in opened
    assert _listing(root) == before


@pytest.mark.parametrize("alias", [
    "./retention.lock",
    "sub/../retention.lock",
    ".//retention.lock",
])
def test_a_normalized_alias_inside_the_target_is_refused(tmp_path, capsys,
                                                         alias):
    """`.` and `..` must be normalized away before the decision, so a lock
    that merely LOOKS external cannot smuggle itself inside."""
    root = _scanned_root(tmp_path, snapshots=2)
    (root / "sub").mkdir()
    lock = Path(os.fspath(root)) / alias
    before = _listing(root)
    status = retention.main([str(root), "--lock", str(lock)])
    printed = capsys.readouterr()
    assert status == 1
    assert (retention.RetentionFailureReason.LOCK_UNAVAILABLE.value
            in printed.out)
    assert printed.err == ""
    assert _listing(root) == before
    assert not (root / "retention.lock").exists()


def test_a_parent_alias_resolving_into_the_target_is_refused(tmp_path, capsys):
    """Containment reached through an ALIAS must be refused too.

    A real symlink is used where the platform grants it; where it does not,
    the same relationship is presented through `os.path.realpath`, which is
    the function the decision must consult. Either way the control runs -- it
    is never skipped -- and both forms assert the identical refusal.
    """
    root = _scanned_root(tmp_path, snapshots=2)
    alias = tmp_path / "alias"
    real_symlink = True
    try:
        alias.symlink_to(root, target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError):
        real_symlink = False
        # A REAL, WRITABLE directory. If the alias did not exist the lock open
        # would fail on its own and the control would pass vacuously against
        # the unfixed code, proving nothing about alias resolution.
        alias.mkdir()

    lock = alias / "retention.lock"
    if not real_symlink:
        genuine = os.path.realpath

        def _aliased(path, *args, **kwargs):
            if os.fspath(path) == os.fspath(lock):
                return os.fspath(Path(os.fspath(root)) / "retention.lock")
            return genuine(path, *args, **kwargs)

        monkey = pytest.MonkeyPatch()
        monkey.setattr(retention.os.path, "realpath", _aliased)
    else:
        monkey = None

    before = _listing(root)
    try:
        status = retention.main([str(root), "--lock", str(lock)])
        printed = capsys.readouterr()
    finally:
        if monkey is not None:
            monkey.undo()

    assert status == 1
    assert (retention.RetentionFailureReason.LOCK_UNAVAILABLE.value
            in printed.out)
    assert printed.err == ""
    assert _listing(root) == before
    assert not (root / "retention.lock").exists()


def test_a_default_temporary_directory_inside_the_target_is_refused(
        tmp_path, monkeypatch, capsys):
    """The DEFAULT lock goes through the same decision as an override.

    If the system temporary directory happens to sit inside the maintained
    directory, the opaque default name is no protection at all.
    """
    root = _scanned_root(tmp_path, snapshots=2)
    inside_tmp = root / "tmp"
    inside_tmp.mkdir()
    monkeypatch.setattr(retention.tempfile, "gettempdir",
                        lambda: str(inside_tmp))
    before = _listing(root)
    status = retention.main([str(root)])
    printed = capsys.readouterr()
    assert status == 1
    assert (retention.RetentionFailureReason.LOCK_UNAVAILABLE.value
            in printed.out)
    assert printed.err == ""
    assert _listing(root) == before
    assert _listing(inside_tmp) == []


def test_an_exactly_full_target_is_not_wedged_by_a_rejected_lock(
        tmp_path, monkeypatch, capsys):
    """The concrete harm: one lock entry pushes a full directory over the
    scanner limit, and then EVERY pass refuses before relief is possible.

    The production policy is replaced with one whose entry bound equals the
    directory's current population, so the target is exactly full. Rejecting
    the lock must leave it exactly full -- not one over.
    """
    root = _scanned_root(tmp_path, snapshots=4)
    full = len(_listing(root))
    monkeypatch.setattr(retention, "PRODUCTION_RETENTION_POLICY",
                        _tiny(entries=full, combined=1000))
    lock = _inside_lock(root)
    status = retention.main([str(root), "--lock", str(lock)])
    printed = capsys.readouterr()
    assert status == 1
    assert (retention.RetentionFailureReason.LOCK_UNAVAILABLE.value
            in printed.out)
    assert (retention.RetentionFailureReason.ENTRY_LIMIT_EXCEEDED.value
            not in printed.out)
    assert len(_listing(root)) == full
    assert not lock.exists()


def test_the_same_full_target_still_passes_with_a_lock_outside_it(
        tmp_path, monkeypatch, capsys):
    """The other half of the wedging proof: with the lock outside, the
    exactly-full directory is still scannable and is NOT refused."""
    root = _scanned_root(tmp_path, snapshots=4)
    full = len(_listing(root))
    monkeypatch.setattr(retention, "PRODUCTION_RETENTION_POLICY",
                        _tiny(entries=full, combined=1000))
    lock = tmp_path / "outside.lock"
    status = retention.main([str(root), "--lock", str(lock)])
    printed = capsys.readouterr()
    assert (retention.RetentionFailureReason.ENTRY_LIMIT_EXCEEDED.value
            not in printed.out)
    assert (retention.RetentionFailureReason.LOCK_UNAVAILABLE.value
            not in printed.out)
    assert len(_listing(root)) == full
    assert status == 0


def test_a_sibling_lock_outside_the_target_still_works(tmp_path, capsys):
    """Valid outside placement is untouched: the lock is created and used."""
    root = _scanned_root(tmp_path, snapshots=3)
    lock = tmp_path / "sibling.lock"
    before = _listing(root)
    status = retention.main([str(root), "--lock", str(lock)])
    printed = capsys.readouterr()
    assert status == 0
    assert "refused=none" in printed.out
    assert lock.exists()
    assert _listing(root) == before


def test_a_sibling_sharing_a_name_prefix_is_not_treated_as_inside(
        tmp_path, capsys):
    """Containment is by PATH COMPONENT, never by string prefix.

    `.../database.lock` starts with the characters of `.../data`, so a naive
    `startswith` refuses a perfectly valid sibling. This control fails on any
    such implementation and holds identically before and after the fix.
    """
    root = _scanned_root(tmp_path, name="data", snapshots=2)
    lock = tmp_path / "database.lock"
    status = retention.main([str(root), "--lock", str(lock)])
    printed = capsys.readouterr()
    assert status == 0
    assert "refused=none" in printed.out
    assert lock.exists()


def test_a_failure_to_compute_the_path_relation_refuses_rather_than_raises(
        tmp_path, monkeypatch, capsys):
    """Fail closed. If the relationship cannot be established, the pass
    refuses with the fixed code -- it does not proceed, and it does not let an
    OSError escape as a traceback."""
    root = _scanned_root(tmp_path, snapshots=2)

    def _unresolvable(path, *args, **kwargs):
        raise OSError(errno.EIO, "cannot resolve")

    monkeypatch.setattr(retention.os.path, "realpath", _unresolvable)
    lock = tmp_path / "outside.lock"
    before = _listing(root)
    status = retention.main([str(root), "--lock", str(lock)])
    printed = capsys.readouterr()
    assert status == 1
    assert (retention.RetentionFailureReason.LOCK_UNAVAILABLE.value
            in printed.out)
    assert printed.err == ""
    assert "Traceback" not in printed.out
    assert _listing(root) == before


def test_a_rejected_lock_placement_changes_no_byte_of_the_target(tmp_path,
                                                                 capsys):
    """Not merely the same NAMES: the same bytes and the same sizes."""
    root = _scanned_root(tmp_path, snapshots=3)
    before = {name: (root / name).read_bytes() for name in _listing(root)}
    status = retention.main([str(root), "--lock", str(_inside_lock(root))])
    capsys.readouterr()
    assert status == 1
    after = {name: (root / name).read_bytes() for name in _listing(root)}
    assert after == before


def test_the_lock_decision_precedes_any_open(tmp_path, monkeypatch, capsys):
    """Nothing is opened at all when the placement is unsafe.

    `os.open` is replaced by a recorder that fails the control if the lock is
    ever opened. This is what separates "created then removed" from "never
    created".
    """
    root = _scanned_root(tmp_path, snapshots=2)
    opened = []
    genuine = retention.os.open

    def _recording(path, *args, **kwargs):
        opened.append(os.fspath(path))
        return genuine(path, *args, **kwargs)

    monkeypatch.setattr(retention.os, "open", _recording)
    lock = _inside_lock(root)
    status = retention.main([str(root), "--lock", str(lock)])
    capsys.readouterr()
    assert status == 1
    assert os.fspath(lock) not in opened


def test_an_existing_outside_lock_is_untouched_by_a_rejected_run(tmp_path,
                                                                 capsys):
    """A rejection must not disturb an unrelated, valid lock file."""
    root = _scanned_root(tmp_path, snapshots=2)
    keeper = tmp_path / "keeper.lock"
    keeper.write_bytes(b"held")
    status = retention.main([str(root), "--lock", str(_inside_lock(root))])
    capsys.readouterr()
    assert status == 1
    assert keeper.read_bytes() == b"held"


# ===========================================================================
# P2 -- the RESERVE may only count snapshots the planner cannot quarantine
# ===========================================================================
#
# `snapshot_reserve_available` probes the newest `reserve_window` entries:
#
#     for entry in rank(scan.snapshots)[:policy.reserve_window]:
#
# `_class_plan` protects only the newest `recovery_floor` entries:
#
#     if position < class_policy.recovery_floor:
#         continue
#
# When `recovery_floor < reserve_window` the ranks in between are BOTH counted
# toward the reserve AND eligible for quarantine. The check therefore passes
# on the strength of archives the same pass is about to move. With five
# admissible snapshots, a floor of 1 and `reserve_required=3`, the probe finds
# three, the planner makes ranks 1..4 eligible, four are moved, and ONE is
# left -- a third of the reserve that was just certified.
#
# Production is unaffected: `recovery_floor` is 512 and `reserve_window` is
# `SNAPSHOT_ARCHIVE_POLICY.selection_depth`, which is 8, so the protected
# prefix already contains the whole probe window. The defect is reachable only
# through an accepted CUSTOM policy, which is why the correction narrows the
# probe rather than rejecting the policy.


def _reserve_policy(*, floor, window=8, required=3):
    """A policy built for THESE controls, independent of `_tiny`.

    The reserve controls must be able to state their own window and
    requirement without being coupled to the shared tiny-policy fixture, so
    that a change to one cannot silently redefine the other.
    """
    return retention.RetentionPolicy(
        snapshot=retention.ClassRetentionPolicy(
            max_age_seconds=30 * DAY, recovery_floor=floor,
            absolute_ceiling=8_192, max_inspected=1_000),
        telemetry=retention.ClassRetentionPolicy(
            max_age_seconds=14 * DAY, recovery_floor=floor,
            absolute_ceiling=8_192, max_inspected=1_000),
        quiescence_seconds=900, max_actions_per_pass=512,
        max_directory_entries=1_000, max_combined_inspected=1_000,
        reserve_window=window, reserve_required=required)


def _vulnerable_policy():
    """recovery_floor (1) < reserve_window (8): the overlapping shape."""
    return _reserve_policy(floor=1)


def _five_old_snapshots():
    return _built_scan(snapshots=_aged_snapshots(5, age_days=400))


def test_the_overlapping_policy_shape_is_what_the_defect_needs():
    """The premise, asserted rather than assumed."""
    policy = _vulnerable_policy()
    assert policy.snapshot.recovery_floor == 1
    assert policy.reserve_window == 8
    assert policy.reserve_required == 3
    assert policy.snapshot.recovery_floor < policy.reserve_window


def test_the_planner_would_quarantine_all_but_one_of_those_snapshots():
    """The harm, stated in the planner's own terms and independent of the
    reserve: four of five move, leaving one -- below `reserve_required`."""
    policy = _vulnerable_policy()
    plan = _plan(_five_old_snapshots(), policy=policy)
    moved = [action.basename for action in plan.actions
             if action.klass == retention.SNAPSHOT_CLASS]
    assert len(moved) == 4
    assert 5 - len(moved) == 1
    assert 5 - len(moved) < policy.reserve_required


def test_the_reserve_cannot_count_snapshots_the_planner_will_quarantine():
    """The correction: with only the protected prefix countable, three
    admissible archives cannot be found, so snapshot actions stay blocked."""
    admit = _Admit({0, 1, 2, 3, 4})
    assert _reserve(_five_old_snapshots(), admit,
                    policy=_vulnerable_policy()) is False


def test_every_counted_reserve_snapshot_is_disjoint_from_planned_actions():
    """The invariant itself, proved by basename rather than argued.

    Whatever the probe counted must not appear in the snapshot action set.
    """
    policy = _vulnerable_policy()
    scan = _five_old_snapshots()
    admit = _Admit({0, 1, 2, 3, 4})
    _reserve(scan, admit, policy=policy)
    probed = set(admit.calls)
    planned = {action.basename for action in _plan(scan, policy=policy).actions
               if action.klass == retention.SNAPSHOT_CLASS}
    assert probed, "the probe must actually have looked at something"
    assert probed & planned == set()


def test_the_probe_never_reaches_beyond_the_protected_prefix():
    """Bounded by the recovery floor AND the reserve window, whichever binds."""
    policy = _vulnerable_policy()
    admit = _Admit(set())
    _reserve(_built_scan(snapshots=_aged_snapshots(5_000, age_days=400)),
             admit, policy=policy)
    bound = min(policy.reserve_window, policy.snapshot.recovery_floor)
    assert len(admit.calls) == bound == 1


def test_a_recovery_floor_below_the_reserve_requirement_blocks_actions():
    """If the protected prefix is smaller than `reserve_required`, the reserve
    can never be satisfied and snapshot actions must stay blocked -- however
    many admissible archives exist further down."""
    policy = _reserve_policy(floor=2)
    assert policy.snapshot.recovery_floor < policy.reserve_required
    admit = _Admit(set(range(50)))
    assert _reserve(_built_scan(snapshots=_aged_snapshots(50, age_days=400)),
                    admit, policy=policy) is False
    assert len(admit.calls) == 2


def test_rejected_archives_inside_the_protected_prefix_do_not_count():
    """Admissible and rejected archives mixed inside the protected prefix: only
    the admissible ones count, and the bound still holds."""
    policy = _reserve_policy(floor=4)
    admit = _Admit({0, 2})                      # ranks 1 and 3 are rejected
    assert _reserve(_built_scan(snapshots=_aged_snapshots(20, age_days=400)),
                    admit, policy=policy) is False
    assert len(admit.calls) == 4


def test_a_protected_prefix_that_does_satisfy_the_reserve_still_proceeds():
    """The correction must not block a policy that is genuinely safe."""
    policy = _reserve_policy(floor=4)
    admit = _Admit({0, 1, 2})
    assert _reserve(_built_scan(snapshots=_aged_snapshots(20, age_days=400)),
                    admit, policy=policy) is True
    assert len(admit.calls) == 3


def test_the_production_policy_probe_bound_is_unchanged():
    """Production's protected prefix already contains the whole window, so the
    narrowing is a no-op there -- bound and outcome both."""
    production = retention.PRODUCTION_RETENTION_POLICY
    assert production.snapshot.recovery_floor == 512
    assert production.reserve_window == 8
    assert min(production.reserve_window,
               production.snapshot.recovery_floor) == 8
    admit = _Admit(set())
    _reserve(_built_scan(snapshots=_aged_snapshots(5_000, age_days=1)), admit)
    assert len(admit.calls) == 8


def test_the_production_policy_outcome_is_unchanged():
    admit = _Admit({0, 3, 7})
    assert _reserve(_built_scan(snapshots=_aged_snapshots(20, age_days=1)),
                    admit) is True
    admit = _Admit({0, 5})
    assert _reserve(_built_scan(snapshots=_aged_snapshots(20, age_days=1)),
                    admit) is False


def test_telemetry_stays_actionable_when_the_reserve_blocks_snapshots():
    """The refill path must survive the narrowing: blocking snapshots must not
    also strand telemetry."""
    policy = _vulnerable_policy()
    telemetry = [
        _entry(_telem_name("2026010%dT000000" % index),
               retention.TELEMETRY_CLASS,
               NOW - _ns(400 * DAY) - _ns(index))
        for index in range(6)
    ]
    scan = _built_scan(snapshots=_aged_snapshots(5, age_days=400),
                       telemetry=telemetry)
    report = retention.run_pass(
        "data", policy=policy, mode=retention.RetentionMode.PLAN,
        now_ns=NOW, scan=scan, admit=_Admit({0, 1, 2, 3, 4}))
    assert report.snapshot_actions_blocked is True
    assert report.refused is None
    assert report.planned_actions, "telemetry must remain actionable"
    assert all(action.klass == retention.TELEMETRY_CLASS
               for action in report.planned_actions)


def test_the_narrowed_probe_never_materializes_a_payload():
    """Still bounded structural preflight only: the injected probe is the only
    thing called, and it never opens an array."""
    policy = _vulnerable_policy()
    admit = _Admit({0})
    _reserve(_five_old_snapshots(), admit, policy=policy)
    assert len(admit.calls) == 1
    assert all(name.endswith(".npz") for name in admit.calls)


# ===========================================================================
# P1 follow-up -- the Windows EXTENDED-LENGTH namespace defeated the guard
# ===========================================================================
#
# `_lock_path_is_outside` resolves both paths with `os.path.realpath` and then
# compares components. On Windows `realpath` PRESERVES the extended-length
# prefix, so the same directory spelled two ways produces two different roots:
#
#     realpath(r"C:\data\x.lock")       -> "C:\\data\\x.lock"
#     realpath(r"\\?\C:\data\x.lock")   -> "\\\\?\\C:\\data\\x.lock"
#
# The component sequences then share no prefix, the guard answers "outside",
# and the lock is created INSIDE the maintained directory. Measured through
# `main()` in PLAN mode against the uncorrected code:
#
#     plain     : retention refused=lock_unavailable   rc=1  target after=[]
#     extended  : retention mode=plan refused=none processed=1
#                 rc=0  target after=['sneak.lock']
#
# `processed=1` is the pass counting the lock file it had just created -- the
# exact entry inflation that wedges a directory at `max_directory_entries`.
#
# `\\?\` is the ordinary Windows workaround for MAX_PATH on deep paths, so
# this is a foreseeable operator spelling rather than an attack, and Windows is
# this module's stated operational target. It is also invisible to Linux CI,
# which is why the deterministic control below drives the canonicalization
# through a substituted `realpath` and therefore runs identically everywhere.

_EXTENDED_PREFIX = "\\\\?\\"
_DEVICE_PREFIX = "\\\\.\\"


def _extended(path):
    """The extended-length spelling of an ordinary Windows path."""
    return _EXTENDED_PREFIX + os.fspath(path)


def _fixed_realpath(mapping):
    """A `realpath` double returning canonical Windows spellings.

    The point is to exercise the namespace canonicalization on EVERY platform.
    Windows path handling is not available on POSIX, so the resolved forms are
    supplied directly and the code under test must reconcile them itself.
    """
    def _resolver(path, *args, **kwargs):
        return mapping[os.fspath(path)]
    return _resolver


# -- the guard, decided directly ---------------------------------------------

def test_a_plain_lock_inside_a_plain_target_is_refused(monkeypatch):
    """The control case the extended spellings are measured against."""
    _decide(monkeypatch, _WIN_INSIDE, _WIN_TARGET, expected=False)


def test_an_extended_lock_inside_a_plain_target_is_refused(monkeypatch):
    """An extended-length lock must not escape an ordinary target.

    The resolved forms are INJECTED rather than produced by the host. Passing
    a raw Windows namespace string through a POSIX `realpath` does not test
    Windows canonicalization at all -- POSIX reads it as an ordinary relative
    filename and prepends the working directory -- so the control would
    silently stop covering the defect on the platform CI actually runs on.
    Injection makes the relationship itself the subject.
    """
    _decide(monkeypatch, _WIN_INSIDE_EXT, _WIN_TARGET, expected=False)


def test_a_plain_lock_inside_an_extended_target_is_refused(monkeypatch):
    """The prefix on the TARGET must not defeat the guard either."""
    _decide(monkeypatch, _WIN_INSIDE, _WIN_TARGET_EXT, expected=False)


def test_both_paths_in_extended_form_are_refused(monkeypatch):
    """Equivalent spellings on both sides still resolve to containment."""
    _decide(monkeypatch, _WIN_INSIDE_EXT, _WIN_TARGET_EXT, expected=False)


def test_an_extended_sibling_outside_the_target_is_still_accepted(monkeypatch):
    """Canonicalization must not turn every extended path into a refusal."""
    _decide(monkeypatch, _WIN_OUTSIDE_EXT, _WIN_TARGET, expected=True)


def test_an_extended_sibling_sharing_a_name_prefix_is_accepted(monkeypatch):
    """Component containment must survive canonicalization: `...database.lock`
    is not inside `...data` however either side is spelled."""
    _decide(monkeypatch, _WIN_PREFIX_SIBLING_EXT, _WIN_TARGET, expected=True)


# -- deterministic canonicalization, running on every platform ---------------

@pytest.mark.parametrize("target,lock,expected", [
    # extended drive form against its ordinary equivalent, both directions
    ("\\\\?\\C:\\data", "C:\\data\\x.lock", False),
    ("C:\\data", "\\\\?\\C:\\data\\x.lock", False),
    ("\\\\?\\C:\\data", "\\\\?\\C:\\data\\x.lock", False),
    # extended UNC form against its ordinary equivalent, both directions
    ("\\\\?\\UNC\\server\\share\\data", "\\\\server\\share\\data\\x.lock", False),
    ("\\\\server\\share\\data", "\\\\?\\UNC\\server\\share\\data\\x.lock", False),
    ("\\\\?\\UNC\\server\\share\\data",
     "\\\\?\\UNC\\server\\share\\data\\x.lock", False),
    # genuinely outside, in every spelling
    ("\\\\?\\C:\\data", "C:\\elsewhere\\x.lock", True),
    ("C:\\data", "\\\\?\\C:\\elsewhere\\x.lock", True),
    ("\\\\?\\UNC\\server\\share\\data", "\\\\server\\share\\other\\x.lock", True),
    # a name that merely starts with the target's characters
    ("\\\\?\\C:\\data", "\\\\?\\C:\\database.lock", True),
])
def test_equivalent_windows_spellings_reach_one_answer(monkeypatch, target,
                                                       lock, expected):
    """The canonicalization itself, decided without any Windows API.

    `realpath` is replaced by a double returning the spellings verbatim, so
    this control exercises the namespace reconciliation on Linux CI exactly as
    on the Windows seat. Without it the defect would be visible only on the
    platform that suffers from it.
    """
    monkeypatch.setattr(retention.os.path, "realpath",
                        _fixed_realpath({target: target, lock: lock}))
    assert retention._lock_path_is_outside(lock, target) is expected


@pytest.mark.parametrize("spelling", [
    "\\\\.\\C:\\data\\x.lock",          # device namespace
    "\\\\.\\PhysicalDrive0",            # device namespace, not a file at all
    "\\\\?\\Volume{00000000-0000-0000-0000-000000000000}\\x.lock",
    "\\\\?\\GLOBALROOT\\Device\\HarddiskVolume1\\x.lock",
    "\\\\?\\",                          # prefix with nothing after it
    "\\\\?\\UNC\\",                     # UNC prefix with no server or share
])
def test_an_unsupported_windows_namespace_fails_closed(monkeypatch, spelling):
    """A namespace that cannot be mapped onto an ordinary drive or UNC path is
    not proved outside anything, so it must refuse rather than guess."""
    target = "C:\\data"
    monkeypatch.setattr(retention.os.path, "realpath",
                        _fixed_realpath({target: target, spelling: spelling}))
    assert retention._lock_path_is_outside(spelling, target) is False


def test_an_unsupported_namespace_on_the_target_side_also_fails_closed(
        monkeypatch):
    target = "\\\\?\\GLOBALROOT\\Device\\HarddiskVolume1\\data"
    lock = "C:\\elsewhere\\x.lock"
    monkeypatch.setattr(retention.os.path, "realpath",
                        _fixed_realpath({target: target, lock: lock}))
    assert retention._lock_path_is_outside(lock, target) is False


# -- end to end through the CLI ----------------------------------------------

def test_plan_refuses_an_extended_lock_inside_the_target(tmp_path, monkeypatch,
                                                         capsys):
    """The whole harm, through `main`, in the mode that promises to touch
    nothing -- and proved to come from the GUARD.

    On Windows the extended spelling is the genuine vector and the host
    resolves it. Elsewhere the Windows relationship is injected, because a raw
    namespace string means nothing to a POSIX `realpath`. Either way `os.open`
    must never be reached: a refusal that arrived only because the operating
    system could not find an impossible filename would be a false positive
    wearing the shape of a safety property.
    """
    root = _scanned_root(tmp_path, snapshots=3)
    lock = Path(os.fspath(root)) / "sneak.lock"
    argument = _platform_extended(monkeypatch, root, lock)
    opened = _open_recorder(monkeypatch)
    before = _listing(root)
    status = retention.main([str(root), "--lock", argument])
    printed = capsys.readouterr()
    assert status == 1
    assert printed.out.strip() == "retention refused=lock_unavailable"
    assert printed.err == ""
    assert opened == [], "the guard must refuse before anything is opened"
    assert _listing(root) == before
    assert not lock.exists()


def test_the_extended_refusal_leaks_no_locator_or_namespace(tmp_path,
                                                            monkeypatch,
                                                            capsys):
    """No path, no prefix, no errno, no traceback -- and still no open."""
    root = _scanned_root(tmp_path, snapshots=2)
    lock = Path(os.fspath(root)) / "sneak.lock"
    argument = _platform_extended(monkeypatch, root, lock)
    opened = _open_recorder(monkeypatch)
    status = retention.main([str(root), "--lock", argument])
    printed = capsys.readouterr()
    assert status == 1
    assert opened == []
    for leak in (str(root), "sneak.lock", _EXTENDED_PREFIX, _DEVICE_PREFIX,
                 "Traceback", "Errno", "errno"):
        assert leak not in printed.out
        assert leak not in printed.err


def test_an_exactly_full_target_is_not_wedged_by_an_extended_lock(
        tmp_path, monkeypatch, capsys):
    """The wedge, reached through the extended spelling.

    The directory is exactly at its entry bound. Creating one lock entry would
    push it over and every later pass would refuse before retention could give
    relief, so the refusal must leave it exactly full -- and must come from the
    guard rather than from a failed open.
    """
    root = _scanned_root(tmp_path, snapshots=4)
    full = len(_listing(root))
    monkeypatch.setattr(retention, "PRODUCTION_RETENTION_POLICY",
                        _tiny(entries=full, combined=1000))
    lock = Path(os.fspath(root)) / "sneak.lock"
    argument = _platform_extended(monkeypatch, root, lock)
    opened = _open_recorder(monkeypatch)
    status = retention.main([str(root), "--lock", argument])
    printed = capsys.readouterr()
    assert status == 1
    assert printed.out.strip() == "retention refused=lock_unavailable"
    assert (retention.RetentionFailureReason.ENTRY_LIMIT_EXCEEDED.value
            not in printed.out)
    assert opened == []
    assert len(_listing(root)) == full


def test_an_extended_lock_outside_the_target_still_locks_the_pass(tmp_path,
                                                                  capsys):
    """Valid outside placement keeps working end to end.

    The extended spelling is used only where the host understands it; the
    canonicalization of an extended OUTSIDE path is decided deterministically
    by `test_an_extended_sibling_outside_the_target_is_still_accepted`.
    """
    root = _scanned_root(tmp_path, snapshots=3)
    lock = tmp_path / "outside.lock"
    argument = _extended(lock) if os.name == "nt" else str(lock)
    status = retention.main([str(root), "--lock", argument])
    printed = capsys.readouterr()
    assert status == 0
    assert "refused=none" in printed.out
    assert lock.exists()


def test_the_extended_correction_adds_no_public_surface():
    """The repair stays private: no export, no reason, no signature change."""
    assert len(retention.__all__) == 34
    assert len(list(retention.RetentionFailureReason)) == 20
    assert "_lock_path_is_outside" not in retention.__all__
    code = retention.single_instance_lock.__init__.__code__
    assert code.co_varnames[:2] == ("self", "path")


# ===========================================================================
# P1 follow-up 2 -- portable namespace controls, and non-text / NUL inputs
# ===========================================================================
#
# Two controls added with the extended-length correction passed a raw
# extended-length string through the HOST's `realpath`. On POSIX that string
# is an ordinary relative filename, so `realpath` prepended the working
# directory, the namespace branches never fired, and the guard answered
# "outside" -- the controls asserted the opposite and would have FAILED on
# this repository's Ubuntu CI. On the platform the defect actually lives on
# they were never evaluated at all.
#
# The corrected controls INJECT the resolved forms, so the Windows
# relationship is the subject on every platform and no skip is involved.
#
# Three end-to-end controls also passed on POSIX for the wrong reason: the
# guard accepted the impossible filename, `os.open` then failed with ENOENT,
# and `_LockHandle.acquire` reported `lock_unavailable`. The right answer
# arrived from the wrong place. They now instrument `os.open` and require it
# never to be entered, so the refusal is proved to be the guard's.

_BS = chr(92)
_NUL = chr(0)

_WIN_TARGET = "C:" + _BS + "ops" + _BS + "data"
_WIN_TARGET_EXT = _EXTENDED_PREFIX + _WIN_TARGET
_WIN_INSIDE = _WIN_TARGET + _BS + "retention.lock"
_WIN_INSIDE_EXT = _EXTENDED_PREFIX + _WIN_INSIDE
_WIN_OUTSIDE = "C:" + _BS + "ops" + _BS + "retention.lock"
_WIN_OUTSIDE_EXT = _EXTENDED_PREFIX + _WIN_OUTSIDE
_WIN_PREFIX_SIBLING_EXT = _EXTENDED_PREFIX + _WIN_TARGET + "base.lock"

_UNC_TARGET = _BS + _BS + "server" + _BS + "share" + _BS + "data"
_UNC_TARGET_EXT = (_EXTENDED_PREFIX + "UNC" + _BS + "server" + _BS + "share"
                   + _BS + "data")
_UNC_INSIDE = _UNC_TARGET + _BS + "x.lock"
_UNC_INSIDE_EXT_LOWER = (_EXTENDED_PREFIX + "unc" + _BS + "server" + _BS
                         + "share" + _BS + "data" + _BS + "x.lock")


def _decide(monkeypatch, lock, target, *, expected, resolved=None):
    """Decide one lock/target relation with the resolution INJECTED.

    `os.path.realpath` is called in exactly one place in the module -- inside
    `_lock_path_is_outside` -- so substituting it changes the guard's view and
    nothing else. `resolved` supplies a measured resolution where the host
    would rewrite a spelling before the guard ever sees it.
    """
    table = {lock: lock, target: target}
    table.update(resolved or {})
    monkeypatch.setattr(retention.os.path, "realpath", _fixed_realpath(table))
    assert retention._lock_path_is_outside(lock, target) is expected


def _open_recorder(monkeypatch):
    """Every `os.open` the module performs, so a control can require none."""
    opened = []
    genuine = retention.os.open

    def _recording(path, *args, **kwargs):
        opened.append(os.fspath(path))
        return genuine(path, *args, **kwargs)

    monkeypatch.setattr(retention.os, "open", _recording)
    return opened


def _platform_extended(monkeypatch, root, lock):
    """The CLI argument naming `lock` through the extended-length namespace.

    On Windows the host resolves the genuine spelling. Elsewhere the argument
    stays an ordinary path and the extended Windows relationship is injected
    into the guard, so the canonicalization is exercised on both platforms and
    the control is never skipped and never satisfied by an impossible
    filename.
    """
    if os.name == "nt":
        return _extended(lock)
    genuine = retention.os.path.realpath
    table = {os.fspath(root): _WIN_TARGET, os.fspath(lock): _WIN_INSIDE_EXT}

    def _resolver(path, *args, **kwargs):
        key = os.fspath(path)
        if key in table:
            return table[key]
        return genuine(path, *args, **kwargs)

    monkeypatch.setattr(retention.os.path, "realpath", _resolver)
    return str(lock)


class _BytesPath:
    """A path-like object whose `__fspath__` returns `bytes`."""

    def __init__(self, value):
        self._value = value

    def __fspath__(self):
        return os.fsencode(self._value)


@pytest.mark.parametrize("spelling", [
    _EXTENDED_PREFIX + "c:" + _BS + "ops" + _BS + "data" + _BS + "retention.lock",
    _EXTENDED_PREFIX + "C:/ops/data/retention.lock",
    "//?/C:/ops/data/retention.lock",
])
def test_mixed_case_and_slash_spellings_still_resolve_inside(monkeypatch,
                                                             spelling):
    r"""Case and separator are spelling, not identity.

    Windows `realpath` reduces all three of these to the SAME extended
    backslash form -- measured on the Windows seat, where each returns
    `\\?\C:\ops\data\retention.lock`. That measured resolution is what
    the guard is handed here, so the control decides the canonicalization
    rather than re-testing the host's parser, and it decides it identically on
    Ubuntu.
    """
    _decide(monkeypatch, spelling, _WIN_TARGET, expected=False,
            resolved={spelling: _WIN_INSIDE_EXT})


@pytest.mark.parametrize("target,lock", [
    (_UNC_TARGET_EXT, _UNC_INSIDE),
    (_UNC_TARGET, _UNC_INSIDE_EXT_LOWER),
    (_UNC_TARGET_EXT, _UNC_INSIDE_EXT_LOWER),
])
def test_extended_unc_matches_ordinary_unc(monkeypatch, target, lock):
    """The UNC spellings name one share and must reconcile, in either case."""
    _decide(monkeypatch, lock, target, expected=False)


def test_an_unc_share_sibling_is_still_outside(monkeypatch):
    """The UNC reconciliation must not swallow a genuine sibling share."""
    _decide(monkeypatch, _BS + _BS + "server" + _BS + "share" + _BS + "other"
            + _BS + "x.lock", _UNC_TARGET_EXT, expected=True)


def test_the_windows_relation_is_decided_without_the_host(monkeypatch):
    """The injection is honest: with the double installed the guard's answer
    depends on the SPELLINGS and not on the machine running the suite."""
    _decide(monkeypatch, _WIN_OUTSIDE, _WIN_TARGET, expected=True)
    _decide(monkeypatch, _WIN_INSIDE, _WIN_TARGET, expected=False)


# -- non-text and NUL inputs -------------------------------------------------

def test_a_bytes_lock_path_is_refused_without_raising(tmp_path):
    """`bytes` is a valid path to the operating system but not to the string
    work this guard does. It must refuse, not raise."""
    root = _scanned_root(tmp_path, snapshots=1)
    lock = os.fsencode(os.fspath(Path(os.fspath(root)) / "x.lock"))
    assert retention._lock_path_is_outside(lock, root) is False


def test_a_bytes_target_path_is_refused_without_raising(tmp_path):
    root = _scanned_root(tmp_path, snapshots=1)
    lock = Path(os.fspath(root)) / "x.lock"
    assert retention._lock_path_is_outside(
        lock, os.fsencode(os.fspath(root))) is False


def test_a_path_like_returning_bytes_is_refused_without_raising(tmp_path):
    """`os.fspath` succeeds and yields `bytes`, so the type decision has to
    come after the conversion rather than before it."""
    root = _scanned_root(tmp_path, snapshots=1)
    lock = _BytesPath(os.fspath(Path(os.fspath(root)) / "x.lock"))
    assert retention._lock_path_is_outside(lock, root) is False
    assert retention._lock_path_is_outside(
        Path(os.fspath(root)) / "x.lock", _BytesPath(os.fspath(root))) is False


def test_an_embedded_nul_in_the_lock_path_is_refused(tmp_path):
    """A NUL cannot appear in a filename. `realpath` does not reject it on
    every platform, and `os.open` raises `ValueError` -- which is NOT the
    `OSError` the lock path contains -- so it must be refused here, before
    anything is opened."""
    root = _scanned_root(tmp_path, snapshots=1)
    assert retention._lock_path_is_outside(
        str(tmp_path / "outside") + _NUL + ".lock", root) is False


def test_an_embedded_nul_in_the_target_path_is_refused(tmp_path):
    root = _scanned_root(tmp_path, snapshots=1)
    assert retention._lock_path_is_outside(
        tmp_path / "outside.lock", str(root) + _NUL) is False


def test_a_type_error_building_the_components_is_contained(tmp_path,
                                                           monkeypatch):
    """Component construction must sit inside the fail-closed boundary.

    `normcase` is made to return `bytes`, so the split that follows raises
    `TypeError`. Before the correction that escaped as a traceback.
    """
    root = _scanned_root(tmp_path, snapshots=1)
    monkeypatch.setattr(retention.os.path, "normcase", os.fsencode)
    assert retention._lock_path_is_outside(
        tmp_path / "outside.lock", root) is False


@pytest.mark.parametrize("raised", [
    OSError(errno.EIO, "unresolvable"),
    ValueError("embedded null byte"),
    TypeError("not a path"),
])
def test_each_documented_resolution_failure_fails_closed(tmp_path, monkeypatch,
                                                         raised):
    """Exactly the three enumerated classes, each proved to refuse."""
    root = _scanned_root(tmp_path, snapshots=1)

    def _raiser(path, *args, **kwargs):
        raise raised

    monkeypatch.setattr(retention.os.path, "realpath", _raiser)
    assert retention._lock_path_is_outside(
        tmp_path / "outside.lock", root) is False


def test_an_unexpected_error_class_is_not_swallowed(tmp_path, monkeypatch):
    """The containment is deliberately narrow: a `RuntimeError` is a bug, not
    an unusable path, and must not be reported as a safe refusal."""
    root = _scanned_root(tmp_path, snapshots=1)

    def _raiser(path, *args, **kwargs):
        raise RuntimeError("not a path failure")

    monkeypatch.setattr(retention.os.path, "realpath", _raiser)
    with pytest.raises(RuntimeError):
        retention._lock_path_is_outside(tmp_path / "outside.lock", root)


def test_the_cli_refuses_an_embedded_nul_lock_without_opening_anything(
        tmp_path, monkeypatch, capsys):
    """Through `main`: fixed refusal, nothing opened, nothing changed.

    This covers the CLI route only. `_LockHandle.acquire` still catches just
    `OSError`, so a caller using `single_instance_lock` DIRECTLY with such a
    path can still receive `ValueError`. That is a separate, disclosed defect
    and is deliberately not repaired here.
    """
    root = _scanned_root(tmp_path, snapshots=2)
    opened = _open_recorder(monkeypatch)
    before = _listing(root)
    outside_before = _listing(tmp_path)
    status = retention.main([str(root), "--lock",
                             str(tmp_path / "outside") + _NUL + ".lock"])
    printed = capsys.readouterr()
    assert status == 1
    assert printed.out.strip() == "retention refused=lock_unavailable"
    assert printed.err == ""
    assert opened == []
    assert _listing(root) == before
    assert _listing(tmp_path) == outside_before


def test_the_direct_library_nul_defect_is_still_present_and_unrepaired():
    """Pinned deliberately. `_LockHandle.acquire` catches only `OSError`, so a
    direct library caller still receives the `ValueError` from `os.open`.
    Repairing it is separately authorized; this control records the boundary
    so the disclosure cannot quietly go stale."""
    source = Path(retention.__file__).read_text(encoding="utf-8")
    start = source.index("    def acquire(self)")
    end = source.index("    def release(self)")
    assert "except OSError:" in source[start:end]
    assert "ValueError" not in source[start:end]


# ===========================================================================
# Final readiness corrections -- object-bound quarantine and lock containment
# ===========================================================================


def test_quarantine_mutations_stay_on_the_exact_scanned_directory_object(
        tmp_path, monkeypatch):
    """Swap the pathname after the last scan-identity comparison.

    The replacement has the same eligible basenames, so per-file checks alone
    skip every action after creating quarantine state in the wrong object.  A
    corrected pass instead keeps one binding to the scanned directory: Windows
    may deny the rename while that binding is held, and descriptor-relative
    platforms may let the rename happen, but no mutation may reach the
    unscanned replacement in either case.
    """
    root = _scanned_root(tmp_path, snapshots=4)
    names = _listing(root)
    genuine = retention._validated_quarantine_root
    attempted = {"replacement": None, "blocked": None}

    def _swap_after_the_binding(data_root, *, may_create):
        try:
            attempted["replacement"] = _replace_root_pathname(
                root, contents=names)
        except OSError as error:
            attempted["blocked"] = error
        return genuine(data_root, may_create=may_create)

    monkeypatch.setattr(retention, "_validated_quarantine_root",
                        _swap_after_the_binding)
    report = _run(root)

    assert report.refused is None
    assert report.halted is False
    assert report.moved == report.planned_actions_count == 3
    replacement = attempted["replacement"]
    if replacement is None:
        assert attempted["blocked"] is not None, (
            "the replacement neither happened nor met an active binding")
        assert _quarantine_root(root).is_dir()
    else:
        assert replacement.before != replacement.after
        assert not _quarantine_root(root).exists(), (
            "quarantine state reached the unscanned replacement")
        assert _quarantine_root(replacement.displaced).is_dir(), (
            "the exact scanned object did not receive its own quarantine")
        assert _listing(root) == names, (
            "the unscanned replacement's contents were changed")


def _object_alias_identity_seam(monkeypatch, target, alias, *, same_object):
    """Give component-disjoint paths deterministic filesystem identities.

    The four alias families below require machine-global configuration to make
    literally.  This seam supplies only the object identity result that those
    real aliases produce; all path parsing, ancestry walking and CLI ordering
    remain production code.
    """
    genuine = getattr(retention, "_directory_object_identity", None)
    target_key = os.path.normcase(os.path.abspath(os.fspath(target)))
    alias_key = os.path.normcase(os.path.abspath(os.fspath(alias)))

    def _identity(path, *, follow_reparse):
        key = os.path.normcase(os.path.abspath(os.fspath(path)))
        if key == target_key:
            return (7001, 9001)
        if key == alias_key:
            return (7001, 9001 if same_object else 9002)
        if genuine is None:
            return None
        return genuine(path, follow_reparse=follow_reparse)

    monkeypatch.setattr(retention, "_directory_object_identity", _identity,
                        raising=False)


@pytest.mark.parametrize("alias_family", [
    "windows_mapped_drive",
    "windows_administrative_share",
    "windows_subst_root",
    "posix_bind_mount",
])
def test_a_component_disjoint_alias_of_the_target_is_rejected_before_open(
        tmp_path, monkeypatch, capsys, alias_family):
    """Different namespace roots do not make one directory two objects."""
    root = _scanned_root(tmp_path, name="maintained", snapshots=2)
    alias = tmp_path / alias_family
    alias.mkdir()
    lock = alias / "retention.lock"
    _object_alias_identity_seam(monkeypatch, root, alias, same_object=True)
    opened = _open_recorder(monkeypatch)
    before = _listing(root)

    status = retention.main([str(root), "--lock", str(lock)])
    printed = capsys.readouterr()

    assert status == 1
    assert printed.out.strip() == "retention refused=lock_unavailable"
    assert printed.err == ""
    assert opened == [], "the lock sink was reached before object containment"
    assert not lock.exists()
    assert _listing(root) == before


def test_a_component_disjoint_distinct_directory_remains_outside(
        tmp_path, monkeypatch):
    """Object comparison must not reject an ordinary outside sibling."""
    root = _scanned_root(tmp_path, name="maintained", snapshots=1)
    outside = tmp_path / "different-object"
    outside.mkdir()
    lock = outside / "retention.lock"
    _object_alias_identity_seam(monkeypatch, root, outside, same_object=False)
    assert retention._lock_path_is_outside(lock, root) is True


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor-route contract")
def test_trusted_held_routes_do_not_reenter_the_untrusted_path_proof(
        tmp_path, monkeypatch, capsys):
    """The user spellings are proved once; private descriptor routes are not.

    `_lock_object_ancestry_is_outside` deliberately treats a non-followed
    symlink as unprovable. That is correct for arbitrary input and wrong for a
    route the process itself derived from a live held descriptor.
    """
    root = _scanned_root(tmp_path, snapshots=2)
    lock = tmp_path / "outside.lock"
    genuine = retention._lock_object_ancestry_is_outside
    calls = []

    def _untrusted_path_proof(lock_path, directory):
        spellings = (os.fspath(lock_path), os.fspath(directory))
        calls.append(spellings)
        assert not any("/proc/self/fd/" in value
                       or "/dev/fd/" in value for value in spellings), (
            "a trusted held route re-entered the arbitrary-path proof")
        return genuine(lock_path, directory)

    monkeypatch.setattr(retention, "_lock_object_ancestry_is_outside",
                        _untrusted_path_proof)
    status = retention.main([str(root), "--lock", str(lock)])
    printed = capsys.readouterr()

    assert calls == [(str(lock), str(root))]
    assert status == 0
    assert "refused=none" in printed.out
    assert lock.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor-route contract")
def test_an_ordinary_directory_at_a_descriptor_spelling_is_never_trusted(
        tmp_path, monkeypatch):
    """A chroot can make the conventional fd spelling ordinary namespace."""
    held_root = tmp_path / "held"
    held_root.mkdir()
    impostor = tmp_path / "impostor"
    impostor.mkdir()
    held_info = os.stat(held_root)
    expected = (held_info.st_dev, held_info.st_ino)
    real_lstat = os.lstat
    real_stat = os.stat

    def _ordinary_candidate(path, *args, **kwargs):
        if str(path).startswith(("/proc/self/fd/", "/dev/fd/")):
            return real_lstat(impostor)
        return real_lstat(path, *args, **kwargs)

    def _followed_candidate(path, *args, **kwargs):
        if str(path).startswith(("/proc/self/fd/", "/dev/fd/")):
            return real_stat(impostor)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(retention.os, "lstat", _ordinary_candidate)
    monkeypatch.setattr(retention.os, "stat", _followed_candidate)
    assert retention._trusted_posix_descriptor_route(123, expected) is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor ancestry")
def test_held_posix_ancestry_rejects_a_contained_lock_before_the_sink(
        tmp_path, monkeypatch, capsys):
    """Held-object ancestry is authoritative after namespace validation.

    The two pathname guards are replaced by permissive seams to model a
    component-disjoint alias they cannot decide. Real held descriptors still
    name a target and one of its descendants, so the final bounded `openat`
    walk must refuse before the lock-file context manager is constructed.
    """
    root = _scanned_root(tmp_path, snapshots=2)
    descendant = root / "nested"
    descendant.mkdir()
    lock = descendant / "retention.lock"
    monkeypatch.setattr(retention, "_lock_path_is_outside",
                        lambda lock_path, directory: True)
    monkeypatch.setattr(retention, "_lock_object_ancestry_is_outside",
                        lambda lock_path, directory: True)

    def _lock_sink_was_reached(path):
        raise AssertionError("held ancestry allowed the lock sink")

    monkeypatch.setattr(retention, "single_instance_lock",
                        _lock_sink_was_reached)
    status = retention.main([str(root), "--lock", str(lock)])
    printed = capsys.readouterr()

    assert status == 1
    assert printed.out.strip() == "retention refused=lock_unavailable"
    assert printed.err == ""
    assert not lock.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor namespaces")
@pytest.mark.parametrize("namespace", ["/proc/self/fd", "/dev/fd"])
@pytest.mark.parametrize("alias_side", ["lock", "target"])
def test_user_supplied_descriptor_routes_gain_no_containment_bypass(
        tmp_path, monkeypatch, capsys, namespace, alias_side):
    """Trusted internal descriptor routing does not bless the same text.

    A caller-controlled descriptor spelling that reaches the maintained object
    remains ordinary untrusted input. Whether it appears on the target or lock
    side, containment is rejected before any production `os.open` call.
    """
    if not os.path.isdir(namespace):
        pytest.skip("descriptor namespace unavailable")
    root = _scanned_root(tmp_path, snapshots=2)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    held = os.open(root, flags)
    try:
        descriptor_route = Path(namespace) / str(held)
        if alias_side == "lock":
            directory_arg = str(root)
            lock_arg = str(descriptor_route / "retention.lock")
        else:
            directory_arg = str(descriptor_route)
            lock_arg = str(root / "retention.lock")
        opened = _open_recorder(monkeypatch)
        before = _listing(root)
        status = retention.main([directory_arg, "--lock", lock_arg])
        printed = capsys.readouterr()
    finally:
        os.close(held)

    assert status == 1
    assert printed.out.strip() == "retention refused=lock_unavailable"
    assert printed.err == ""
    assert opened == []
    assert _listing(root) == before
    assert not (root / "retention.lock").exists()
