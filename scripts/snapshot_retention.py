#!/usr/bin/env python3
"""Bounded, fail-closed retention for the operational data directory.

Stage one. Two modes exist, `PLAN` and `QUARANTINE`, and `PLAN` is the safe
default. There is deliberately no `DELETE`, no automatic reaping, no automatic
restoration, no scheduler and no way to execute a serialized plan. Permanent
removal is a later tranche that requires a verified backup and an explicit
Windows handle-safe design; nothing here claims to provide it.

Why this exists
---------------
The engine writes a snapshot every 600 seconds and a telemetry artifact every
300, and nothing removes either. PR #470 bounded the discovery primitive and
PR #472 wired the calibrated caps into all three services, so a directory over
its caps now refuses cleanly instead of being enumerated -- but refusing is
not relief. Without retention the directory reaches those caps in roughly 431
days, and the caps that protect readers would then also block the tool meant
to relieve them.

What this is not
----------------
This is a maintenance safety limit, not a repair capability. If the directory
has already grown past the scanner's refusal limits through prolonged
maintenance failure, the scan refuses and retention can do nothing; recovering
from that state is a separately authorized operation.

Nor does it harden recovery. `watchdog.find_latest_snapshot()` and
`start_fog_engine.bat` both take the single newest entry with no admission
check and no fallback. That remains a disclosed, separate prerequisite tranche
and is untouched here.

Safety posture
--------------
Everything is a closed allowlist. Five version-controlled curated files live
in this same directory, alongside the tuning ledger, service logs, a
request-written STL export, artifacts from writers that are not currently
wired, and two subdirectories. None of them is deletable by construction:
retention acts only on names matching an exact, anchored producer grammar, and
every other name is never even statted.

The grammars here are deliberately STRICTER than the discovery glob.
`v070_genjunkgen123.npz` satisfies `v070_gen*.npz` and is therefore selectable
by discovery -- a documented hazard -- but it is not a name this producer
writes, so it is not a name retention may move. Discovery is permissive and
fails closed by refusing to load; retention is restrictive and fails closed by
refusing to act.
"""

from __future__ import annotations

import dataclasses
import enum
import errno
import hashlib
import json
import os
import re
import tempfile
import stat as stat_module
import sys
from pathlib import Path
from typing import Optional, Tuple, Union

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    # Appended, not prepended: this must not be able to shadow a standard
    # library module with a repository file of the same name.
    sys.path.append(str(_PROJECT_ROOT))

from scripts.snapshot_archive_guard import (  # noqa: E402
    PRODUCTION_DISCOVERY_POLICY,
    PRODUCTION_POLICY as SNAPSHOT_ARCHIVE_POLICY,
    SnapshotArchiveRejected,
    admit_snapshot,
)

__all__ = [
    "SNAPSHOT_CLASS",
    "TELEMETRY_CLASS",
    "NO_SEQUENCE",
    "QUARANTINE_DIRNAME",
    "MANIFEST_NAME",
    "MAX_MANIFEST_RECORD_BYTES",
    "RetentionMode",
    "RetentionFailureReason",
    "ClassRetentionPolicy",
    "RetentionPolicy",
    "PRODUCTION_RETENTION_POLICY",
    "CandidateEntry",
    "ScanSucceeded",
    "ScanFailed",
    "ScanResult",
    "PlannedAction",
    "RetentionPlan",
    "PassReport",
    "QuarantineSurvey",
    "classify_name",
    "directory_state",
    "valid_pass_id",
    "default_lock_path",
    "platform_move",
    "PlatformUnsupported",
    "rank",
    "scan_retention_candidates",
    "plan_retention",
    "snapshot_reserve_available",
    "single_instance_lock",
    "survey_quarantine",
    "format_report",
    "run_pass",
    "main",
]

SNAPSHOT_CLASS = "snapshot"
TELEMETRY_CLASS = "telemetry"

#: Telemetry names carry no producer sequence, so they sort on time and name
#: alone. The sentinel sorts before every real generation.
NO_SEQUENCE = (-1, -1)

QUARANTINE_DIRNAME = ".retention_quarantine"
MANIFEST_NAME = "manifest.jsonl"

#: One journal record is a fixed five-key object over a bounded basename, so a
#: cap this size is generous. It exists so a hostile or corrupted name can
#: never make a record unbounded.
MAX_MANIFEST_RECORD_BYTES = 512

_NANOSECONDS = 1_000_000_000

#: Exactly what `run_v070_engine._save_snapshot` writes:
#: ``f"v070_gen{generation:06d}_step{ca_step:06d}_{ts}.npz"`` with ``ts`` from
#: ``strftime("%Y%m%dT%H%M%S")``. Fully anchored at both ends, ASCII digit
#: classes only -- never ``\d``, which in a str pattern also matches Unicode
#: decimal digits -- and every run width-bounded so a pathological name cannot
#: turn matching into arbitrary-precision work.
#: Applied with `fullmatch`, never `match` plus a trailing anchor: in Python
#: the end anchor also matches immediately before a final newline, so the
#: previous form accepted a producer name with a newline appended to it.
#: `fullmatch` is what actually anchors, at both ends.
_SNAPSHOT_NAME = re.compile(
    r"v070_gen([0-9]{1,18})_step([0-9]{1,18})_[0-9]{8}T[0-9]{6}\.npz")

#: Exactly what the engine's status path writes:
#: ``f"telemetry_{ts}.json"`` with the same timestamp grammar.
_TELEMETRY_NAME = re.compile(r"telemetry_[0-9]{8}T[0-9]{6}\.json")


def classify_name(basename):
    """The retention class of `basename`, or None if it is not ours.

    None is the answer for every curated file, every log, both tuning-state
    files, the request-written STL export, both unwired-writer classes, both
    subdirectories, the quarantine directory, and every name that merely
    resembles a producer name. A name that reaches here and is not classified
    is never statted, never planned and never moved.
    """
    if type(basename) is not str:
        return None
    if _SNAPSHOT_NAME.fullmatch(basename) is not None:
        return SNAPSHOT_CLASS
    if _TELEMETRY_NAME.fullmatch(basename) is not None:
        return TELEMETRY_CLASS
    return None


def _sequence_of(basename):
    """`(generation, step)` for a snapshot name, else the sentinel."""
    match = _SNAPSHOT_NAME.fullmatch(basename)
    if match is None:
        return NO_SEQUENCE
    try:
        return (int(match.group(1)), int(match.group(2)))
    except ValueError:  # pragma: no cover - the widths make this unreachable
        return NO_SEQUENCE


#: A pass identifier is a bounded timestamp and nothing else. It is validated
#: by FULL match before anything is created, because it is joined beneath the
#: quarantine root: an absolute value replaces that root outright and a `..`
#: component escapes it, so an unvalidated identifier is a path traversal.
_PASS_ID = re.compile(r"p[0-9]{8}T[0-9]{6}")


def valid_pass_id(pass_id) -> bool:
    """Whether `pass_id` is a well-formed identifier and not a path."""
    if type(pass_id) is not str:
        return False
    return _PASS_ID.fullmatch(pass_id) is not None


# ---------------------------------------------------------------------------
# Modes, reasons and policy
# ---------------------------------------------------------------------------

class RetentionMode(enum.Enum):
    """The two stage-one modes. Nothing removes anything permanently."""

    PLAN = "plan"
    QUARANTINE = "quarantine"


class RetentionFailureReason(enum.Enum):
    """Fixed, path-free reasons a pass produced no actionable outcome."""

    DIRECTORY_OPEN_FAILED = "directory_open_failed"
    ITERATION_FAILED = "iteration_failed"
    ENTRY_LIMIT_EXCEEDED = "entry_limit_exceeded"
    COMBINED_LIMIT_EXCEEDED = "combined_limit_exceeded"
    SNAPSHOT_LIMIT_EXCEEDED = "snapshot_limit_exceeded"
    TELEMETRY_LIMIT_EXCEEDED = "telemetry_limit_exceeded"
    METADATA_READ_FAILED = "metadata_read_failed"
    TIMESTAMP_AMBIGUOUS = "timestamp_ambiguous"
    IDENTITY_UNAVAILABLE = "identity_unavailable"
    IDENTITY_MISMATCH_AFTER_MOVE = "identity_mismatch_after_move"
    RESERVE_CHECK_FAILED = "reserve_check_failed"
    QUARANTINE_ROOT_INVALID = "quarantine_root_invalid"
    PASS_DIRECTORY_COLLISION = "pass_directory_collision"
    MANIFEST_CREATE_FAILED = "manifest_create_failed"
    MANIFEST_RECORD_FAILED = "manifest_record_failed"
    LOCK_UNAVAILABLE = "lock_unavailable"
    PASS_ID_INVALID = "pass_id_invalid"
    QUARANTINE_PLATFORM_UNSUPPORTED = "quarantine_platform_unsupported"
    SURVEY_DIRECTORY_INVALID = "survey_directory_invalid"
    SURVEY_LIMIT_EXCEEDED = "survey_limit_exceeded"


def _validate_positive_int(value) -> None:
    # `True` is an `int` to Python and would silently become a limit of 1, so
    # booleans are refused explicitly rather than by an `isinstance` that
    # happens to accept them.
    if type(value) is not int or value <= 0:
        raise ValueError("retention_policy_invalid")


@dataclasses.dataclass(frozen=True)
class ClassRetentionPolicy:
    """Limits for one artifact class.

    Three separate controls, deliberately not collapsed:

    * ``recovery_floor`` -- the newest N entries are never eligible, whatever
      their age. This is what survives an outage longer than the horizon.
    * ``max_age_seconds`` -- the ordinary eligibility trigger.
    * ``absolute_ceiling`` -- an ELIGIBILITY ceiling that fires even inside
      the horizon, so rank alone can make an entry eligible. It is not a
      guarantee that the directory holds no more than this at any instant:
      each pass performs at most ``max_actions_per_pass`` actions, so a
      producer fast enough to outpace that leaves a temporary backlog which
      drains over successive passes.

    ``max_inspected`` is a SCANNER refusal limit and is not a retention
    control. It must sit far above ``absolute_ceiling``: a scan that refused
    at the ceiling would make ceiling eligibility unreachable.
    """

    max_age_seconds: int
    recovery_floor: int
    absolute_ceiling: int
    max_inspected: int

    def __post_init__(self) -> None:
        for value in (self.max_age_seconds, self.recovery_floor,
                      self.absolute_ceiling, self.max_inspected):
            _validate_positive_int(value)


@dataclasses.dataclass(frozen=True)
class RetentionPolicy:
    """Every limit one pass obeys. There is no default in any executor."""

    snapshot: ClassRetentionPolicy
    telemetry: ClassRetentionPolicy
    quiescence_seconds: int
    max_actions_per_pass: int
    max_directory_entries: int
    max_combined_inspected: int
    reserve_window: int
    reserve_required: int

    def __post_init__(self) -> None:
        for value in (self.quiescence_seconds, self.max_actions_per_pass,
                      self.max_directory_entries, self.max_combined_inspected,
                      self.reserve_window, self.reserve_required):
            _validate_positive_int(value)
        if not isinstance(self.snapshot, ClassRetentionPolicy):
            raise ValueError("retention_policy_invalid")
        if not isinstance(self.telemetry, ClassRetentionPolicy):
            raise ValueError("retention_policy_invalid")
        if self.reserve_required > self.reserve_window:
            raise ValueError("retention_policy_invalid")

    def for_class(self, klass) -> ClassRetentionPolicy:
        if klass == SNAPSHOT_CLASS:
            return self.snapshot
        if klass == TELEMETRY_CLASS:
            return self.telemetry
        raise ValueError("retention_policy_invalid")


#: The one production instance. The horizons have been measured: a separately
#: authorized aggregate-only `PLAN` reported the present age distribution, so
#: they are no longer provisional pending that measurement. Enforcement is a
#: different question -- `QUARANTINE` remains separately authorized and is not
#: implied by the measurement. The scanner limits reuse the audited discovery
#: calibration so retention refuses exactly where discovery refuses.
PRODUCTION_RETENTION_POLICY = RetentionPolicy(
    snapshot=ClassRetentionPolicy(
        max_age_seconds=30 * 86_400,
        recovery_floor=512,
        absolute_ceiling=8_192,
        max_inspected=65_536,
    ),
    telemetry=ClassRetentionPolicy(
        max_age_seconds=14 * 86_400,
        recovery_floor=1_024,
        absolute_ceiling=8_192,
        max_inspected=65_536,
    ),
    quiescence_seconds=900,
    max_actions_per_pass=512,
    max_directory_entries=PRODUCTION_DISCOVERY_POLICY.max_directory_entries,
    max_combined_inspected=PRODUCTION_DISCOVERY_POLICY.max_candidates,
    reserve_window=SNAPSHOT_ARCHIVE_POLICY.selection_depth,
    reserve_required=3,
)


# ---------------------------------------------------------------------------
# Scan results
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class CandidateEntry:
    """One allowlisted, regular, single-linked entry as the scan saw it.

    Carries the FULL stable identity. `os.DirEntry.stat(follow_symlinks=False)`
    reports `st_dev`, `st_ino` and `st_nlink` as 0 on Windows -- measured on
    the deployed platform -- so the scan uses one non-following
    `os.lstat(root / name)` per allowlisted match instead. That single
    authoritative read supplies type, reparse status, link count, size, time,
    device and inode together.

    Size and time alone are not identity: a replacement preserving both would
    otherwise have nothing from the scan to disagree with at revalidation.
    """

    basename: str
    klass: str
    size: int
    mtime_ns: int
    dev: int
    ino: int
    generation: int
    step: int


@dataclasses.dataclass(frozen=True)
class ScanSucceeded:
    """A complete, exact directory pass.

    `root_identity` is the `(device, inode)` of the real, non-reparse
    directory this pass actually enumerated -- the DIRECTORY-shaped
    counterpart of the per-entry identity `CandidateEntry` carries. Without
    it a later step can only prove that a pathname is *a* usable directory,
    never that it is *the* directory that was scanned, so a root renamed or
    replaced after the iterator closed is accepted and a quarantine tree gets
    built inside a directory no pass ever read.

    `None` means no live filesystem read established one: an injected
    synthetic scan, or the empty success returned when the path is missing or
    is not a directory at all. `None` is NOT an identity and never compares
    equal to anything -- see `_scanned_root_unchanged`, which is the only
    thing permitted to compare it.

    Optional and last, so every existing positional construction and every
    `dataclasses.replace` of a scan keeps working unchanged.
    """

    snapshots: Tuple[CandidateEntry, ...]
    telemetry: Tuple[CandidateEntry, ...]
    processed: int
    inspected: int
    excluded: int
    root_identity: Optional[Tuple[int, int]] = None


@dataclasses.dataclass(frozen=True)
class ScanFailed:
    """A sanitized failure with counters only.

    Deliberately carries no candidate field of any kind, so a partially
    observed, attacker-ordered prefix cannot be planned against by accident.
    """

    reason: RetentionFailureReason
    processed: int
    inspected: int


ScanResult = Union[ScanSucceeded, ScanFailed]


def _is_reparse_point(info) -> bool:
    attributes = getattr(info, "st_file_attributes", None)
    if attributes is None:
        return False
    reparse = getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(attributes & reparse)


def _excluded_type(info) -> bool:
    """Whether a SUCCESSFULLY read entry is a kind retention never touches.

    This is not a failure. Identifying a symlink, junction/reparse point,
    directory or other non-regular object REQUIRES the non-following metadata
    read, so an allowlisted name is always read exactly once; what the read
    proves is whether the object may be planned at all. It is never followed,
    never opened and never moved.

    Excluding a successfully identified entry is safe for ranking in a way
    that a FAILED read is not. Removing an element shifts every later element
    to a lower rank, which moves survivors further INSIDE the recovery floor
    and further FROM the absolute ceiling -- conservative in both directions.
    A failed read leaves the position unknown, so no such argument exists and
    the pass aborts instead.
    """
    # `os.lstat` does not follow, so a symlink presents as a link on POSIX and
    # as a reparse point on Windows. Both are excluded here, and neither is
    # ever followed, opened or moved.
    if not stat_module.S_ISREG(info.st_mode):
        return True
    if _is_reparse_point(info):
        return True
    if int(getattr(info, "st_nlink", 1) or 1) != 1:
        return True
    return False


def scan_retention_candidates(directory, *, policy: RetentionPolicy) -> ScanResult:
    """One bounded, non-recursive pass over `directory`.

    The module owns `os.scandir` so directory work is bounded before any list
    can be materialised -- by the time a glob returns, the whole directory has
    already been enumerated and nothing downstream can limit it.

    The existing `discover_snapshot_candidates` cannot serve this: it matches
    only `v070_gen*.npz`, so it cannot see telemetry, and it returns ordered
    paths without the size and modification time retention must compare. This
    pass therefore does its own work while importing the same calibration.

    Bounds, all independent: every yielded root entry counts against
    `max_directory_entries`, with one unstatted, unmatched look-ahead proving
    the exact boundary; every allowlisted match counts against the combined
    and per-class inspection limits BEFORE its metadata read, so the entry one
    past a limit is never statted.

    Any failure -- directory open, iteration, a limit, or a metadata read on
    an allowlisted name -- returns counters and a fixed reason with no
    candidate collection at all.
    """
    if not isinstance(policy, RetentionPolicy):
        raise TypeError("explicit RetentionPolicy required")

    root = Path(os.fspath(directory))

    # The identity of the directory this pass intends to enumerate, from one
    # bounded, non-following read taken BEFORE the iterator is acquired.
    #
    # The order is the whole of the guarantee. Read AFTER the open, this proof
    # and the post-enumeration one both resolve the PATHNAME, so a replacement
    # installed between the open and the first proof is observed by both while
    # the iterator -- bound to a handle, not a name -- goes on yielding the
    # ORIGINAL object's entries. Both halves then agree, about a directory no
    # entry in the pass came from: the exact inverse of the binding. Taking
    # the proof first is what gives the post-open one something acquired
    # earlier to disagree with.
    #
    # `os.scandir` FOLLOWS a reparse point, so a junction enumerates its
    # target perfectly happily while the PATH is somewhere no pass may act.
    # `directory_state` is what sees that, and it also refuses a root whose
    # device or inode the platform reports as zero. Either way the scan fails
    # closed rather than handing back a success nothing downstream can bind
    # to an object.
    root_identity = directory_state(root)

    try:
        iterator = os.scandir(root)
    except (FileNotFoundError, NotADirectoryError):
        if root_identity is not None:
            # A real, non-reparse directory was proved at this pathname a
            # moment ago and the pathname no longer opens as one. That is a
            # live change underneath the pass, not the steady state of a path
            # that was never there, and reporting it as a clean empty success
            # would report health about a directory that has gone.
            return ScanFailed(
                RetentionFailureReason.IDENTITY_UNAVAILABLE, 0, 0)
        # Nothing to maintain is a clean, successful, empty outcome -- and
        # only here: no identity was ever observed AND the open itself says
        # the pathname is missing or is not a directory.
        return ScanSucceeded((), (), 0, 0, 0)
    except OSError:
        return ScanFailed(RetentionFailureReason.DIRECTORY_OPEN_FAILED, 0, 0)

    # IMMEDIATELY, before a single entry is read: the pathname must still be
    # the object proved above. This is what binds the handle that was actually
    # opened to the name every later step resolves.
    #
    # `_scanned_root_unchanged` also refuses a MISSING binding, so a root that
    # never had a usable identity at all -- a reparse point, a zero device or
    # inode, one `os.lstat` could not read -- fails closed here rather than
    # becoming a success nothing downstream can bind to an object.
    if not _scanned_root_unchanged(root, root_identity):
        # `os.scandir` already opened a handle; release it before refusing.
        with iterator:
            pass
        return ScanFailed(RetentionFailureReason.IDENTITY_UNAVAILABLE, 0, 0)

    snapshots = []
    telemetry = []
    processed = 0
    inspected = 0
    excluded = 0
    collected = {SNAPSHOT_CLASS: 0, TELEMETRY_CLASS: 0}
    limit_reason = {
        SNAPSHOT_CLASS: RetentionFailureReason.SNAPSHOT_LIMIT_EXCEEDED,
        TELEMETRY_CLASS: RetentionFailureReason.TELEMETRY_LIMIT_EXCEEDED,
    }

    try:
        with iterator as entries:
            for entry in entries:
                # The iterator has yielded this entry, but it is deliberately
                # not processed: that one look-ahead proves the exact boundary.
                if processed >= policy.max_directory_entries:
                    return ScanFailed(
                        RetentionFailureReason.ENTRY_LIMIT_EXCEEDED,
                        processed, inspected)
                processed += 1

                klass = classify_name(entry.name)
                if klass is None:
                    # Never statted. Curated files, logs, tuning state,
                    # subdirectories and look-alike names all end here.
                    continue

                # Both limits are charged BEFORE the metadata read, so the
                # match one past a limit is refused unstatted.
                if inspected >= policy.max_combined_inspected:
                    return ScanFailed(
                        RetentionFailureReason.COMBINED_LIMIT_EXCEEDED,
                        processed, inspected)
                if collected[klass] >= policy.for_class(klass).max_inspected:
                    return ScanFailed(limit_reason[klass], processed, inspected)

                inspected += 1
                collected[klass] += 1

                try:
                    # ONE non-following read per allowlisted match, and the
                    # authoritative one: a `DirEntry` cache cannot supply
                    # device, inode or link count on Windows.
                    info = os.lstat(root / entry.name)
                except OSError:
                    # The position of this entry in the newest-first order is
                    # now unknown, so every later rank is unknown too and an
                    # entry truly inside the recovery floor could be computed
                    # as outside it. There is no conservative direction, so
                    # the whole pass is discarded.
                    return ScanFailed(
                        RetentionFailureReason.METADATA_READ_FAILED,
                        processed, inspected)

                if _excluded_type(info):
                    excluded += 1
                    continue

                generation, step = _sequence_of(entry.name)
                candidate = CandidateEntry(
                    basename=entry.name,
                    klass=klass,
                    size=int(info.st_size),
                    mtime_ns=int(info.st_mtime_ns),
                    dev=int(getattr(info, "st_dev", 0) or 0),
                    ino=int(getattr(info, "st_ino", 0) or 0),
                    generation=generation,
                    step=step,
                )
                if klass == SNAPSHOT_CLASS:
                    snapshots.append(candidate)
                else:
                    telemetry.append(candidate)
    except OSError:
        return ScanFailed(RetentionFailureReason.ITERATION_FAILED,
                          processed, inspected)

    # Read AGAIN, after the iterator closed, and required to agree. A root
    # replaced DURING the pass leaves the two halves of one scan describing
    # two different directories: the open handle keeps enumerating the
    # original object, while every per-entry `os.lstat(root / name)` above
    # resolves by PATH into the replacement. Equality here is what discards
    # that whole pass instead of planning against the mixture.
    if not _scanned_root_unchanged(root, root_identity):
        return ScanFailed(RetentionFailureReason.IDENTITY_UNAVAILABLE,
                          processed, inspected)

    return ScanSucceeded(tuple(snapshots), tuple(telemetry), processed,
                         inspected, excluded, root_identity)


# ---------------------------------------------------------------------------
# The pure planner
# ---------------------------------------------------------------------------

def _rank_key(entry: CandidateEntry):
    # Newest first, then the producer's own sequence, then the name as a last
    # resort to make the order total. Comparing names as text alone would
    # invert across a digit-count boundary, because `:06d` is a minimum width
    # production has already outgrown.
    return (-entry.mtime_ns, -entry.generation, -entry.step, entry.basename)


def rank(entries):
    """`entries` in deterministic newest-first order, as an immutable tuple."""
    return tuple(sorted(entries, key=_rank_key))


@dataclasses.dataclass(frozen=True)
class PlannedAction:
    """One entry the pass would move, with the identity it was planned on.

    The identity is the complete `(dev, ino, size, mtime_ns)` captured by the
    scan, so a replacement between scan and action is detectable even when it
    preserves size and time.
    """

    basename: str
    klass: str
    size: int
    mtime_ns: int
    dev: int
    ino: int

    @property
    def identity(self):
        return (self.dev, self.ino, self.size, self.mtime_ns)


@dataclasses.dataclass(frozen=True)
class RetentionPlan:
    """What a pass would do, computed purely from a scan and a clock."""

    actions: Tuple[PlannedAction, ...]
    snapshot_eligible: int
    telemetry_eligible: int
    ambiguous: int
    refused: Optional[RetentionFailureReason]


def _class_plan(entries, class_policy, *, policy, now_ns):
    """Eligible entries for one class, oldest-first, plus the ambiguous count.

    An entry is eligible only when it is beyond the recovery floor, quiescent
    and unambiguously timestamped, AND either older than the horizon or at or
    beyond the absolute ceiling.
    """
    # Future-dated entries are removed BEFORE ranking, not skipped during it.
    # A future timestamp sorts first, so leaving one in place would push every
    # real entry to a HIGHER rank and out of the recovery floor -- the unsafe
    # direction. Removing them shifts survivors to LOWER ranks instead, which
    # is conservative, and the same argument that licenses type exclusion.
    trustworthy = [entry for entry in entries if now_ns - entry.mtime_ns >= 0]
    ambiguous = len(entries) - len(trustworthy)
    ordered = rank(trustworthy)
    eligible = []
    quiescence_ns = policy.quiescence_seconds * _NANOSECONDS
    horizon_ns = class_policy.max_age_seconds * _NANOSECONDS

    for position, entry in enumerate(ordered):
        age_ns = now_ns - entry.mtime_ns
        if position < class_policy.recovery_floor:
            continue
        if age_ns < quiescence_ns:
            continue
        if age_ns > horizon_ns or position >= class_policy.absolute_ceiling:
            eligible.append(entry)

    eligible.sort(key=lambda entry: (entry.mtime_ns, entry.basename))
    return eligible, ambiguous


def plan_retention(scan: ScanResult, *, policy: RetentionPolicy,
                   now_ns: int) -> RetentionPlan:
    """The one planner both modes use. Pure: same inputs, same plan.

    `now_ns` is injected rather than read, so a plan is reproducible and a
    test can place an entry exactly on a boundary. A live pass captures it
    once at pass start and uses that single value throughout.
    """
    if isinstance(scan, ScanFailed):
        return RetentionPlan((), 0, 0, 0, scan.reason)

    snapshot_eligible, snapshot_ambiguous = _class_plan(
        scan.snapshots, policy.snapshot, policy=policy, now_ns=now_ns)
    telemetry_eligible, telemetry_ambiguous = _class_plan(
        scan.telemetry, policy.telemetry, policy=policy, now_ns=now_ns)

    merged = sorted(snapshot_eligible + telemetry_eligible,
                    key=lambda entry: (entry.mtime_ns, entry.basename))
    actions = tuple(
        PlannedAction(entry.basename, entry.klass, entry.size, entry.mtime_ns,
                      entry.dev, entry.ino)
        for entry in merged[:policy.max_actions_per_pass]
    )
    return RetentionPlan(
        actions=actions,
        snapshot_eligible=len(snapshot_eligible),
        telemetry_eligible=len(telemetry_eligible),
        ambiguous=snapshot_ambiguous + telemetry_ambiguous,
        refused=None,
    )


# ---------------------------------------------------------------------------
# The snapshot reserve
# ---------------------------------------------------------------------------

def snapshot_reserve_available(scan: ScanResult, *, policy: RetentionPolicy,
                               data_dir, admit=None) -> bool:
    """Whether enough preflight-admissible archives remain to act on snapshots.

    Probes newest-first through snapshots the planner cannot take, and
    stops as soon as ``reserve_required`` have passed admission. The depth
    is bounded by ``reserve_window`` AND by ``snapshot.recovery_floor``:
    past the floor the planner makes entries ELIGIBLE, so counting them
    would certify a reserve out of the very archives the same pass is
    about to quarantine. At the production values the floor is 512 and the
    window is 8, so the protected prefix already contains the whole window
    and this bound changes nothing there: at most eight bounded preflights
    per pass -- a central-directory and NPY-header read each, never a
    payload materialisation.

    The guarantee is exactly "preflight-admissible", and no more.
    ``admit_snapshot`` is bounded structural preflight; a valid header over a
    corrupt body surfaces only during array materialisation, which happens in
    the consumers and not here. These archives are not thereby proved loadable,
    valid or resumable, and this module never says otherwise.

    Full resume viability and automatic fallback belong to the separate
    watchdog and batch recovery-hardening tranche.
    """
    if isinstance(scan, ScanFailed):
        return False
    probe = admit if admit is not None else admit_snapshot
    root = Path(os.fspath(data_dir))
    found = 0
    # Both bounds apply. The window caps the work; the recovery floor caps
    # WHAT MAY BE COUNTED, because only entries inside the protected prefix
    # are guaranteed absent from the snapshot action set this same pass
    # will plan. Narrowing the probe keeps every accepted policy
    # constructible -- an unsafe SHAPE simply stays reserve-blocked
    # instead of certifying a reserve it cannot keep.
    depth = min(policy.reserve_window, policy.snapshot.recovery_floor)
    for entry in rank(scan.snapshots)[:depth]:
        try:
            with probe(root / entry.basename, data_dir=root,
                       policy=SNAPSHOT_ARCHIVE_POLICY):
                found += 1
        except SnapshotArchiveRejected:
            continue
        if found >= policy.reserve_required:
            return True
    return found >= policy.reserve_required


# ---------------------------------------------------------------------------
# The single-instance lock
# ---------------------------------------------------------------------------

def default_lock_path(directory):
    """The lock for `directory`, OUTSIDE it.

    The lock used to live inside the target, so an ordinary `PLAN` created a
    file in the very directory it was measuring -- changing the entry count it
    reported and disqualifying any zero-mutation acceptance run.

    The name is an opaque digest of the normalized absolute target, so it is
    deterministic -- two callers for one target contend on one lock -- and
    collision-resistant across targets. A truncated SHA-256 makes a collision
    cryptographically implausible, which is not the same as impossible, and
    this does not claim otherwise. It carries no locator: nothing about the
    operational path is recoverable from a filename sitting in a shared
    temporary directory.
    """
    normalized = os.path.normcase(os.path.abspath(os.fspath(directory)))
    digest = hashlib.sha256(normalized.encode("utf-8", "surrogatepass"))
    return Path(tempfile.gettempdir()) / (
        "uft-retention-%s.lock" % digest.hexdigest()[:32])


def _lock_path_is_outside(lock_path, directory) -> bool:
    r"""Whether `lock_path` is PROVED to lie outside `directory`.

    The lock is opened with `O_CREAT` before the target is ever scanned,
    so a lock inside the maintained directory creates an entry in the very
    directory being measured -- in `PLAN` too. A target already at
    `max_directory_entries` is then pushed OVER the scanner limit by that
    one entry, and every later pass refuses before retention can deliver
    any relief. So the relationship is settled BEFORE anything is opened.

    Both paths go through `os.path.realpath`, so `.`/`..` are normalized
    away and existing symlink, junction and reparse-point parents are
    resolved to what they actually name. Comparison is by PATH COMPONENT,
    never by string prefix: `.../database.lock` starts with the characters
    of `.../data` while being a perfectly valid sibling, and a `startswith`
    test would refuse it.

    Resolution alone is not enough on Windows, because `realpath` KEEPS an
    extended-length prefix. A drive-letter path and its `\\?\` spelling
    name one file yet resolve to two different roots, so the guard answered
    "outside" for a lock that was inside -- and `\\?\` is the ordinary
    MAX_PATH workaround, not an exotic spelling. Both paths are therefore
    reduced to one canonical form first: an extended drive path loses the
    prefix, and `\\?\UNC\server\share\x` becomes `\\server\share\x`.
    Windows `realpath` MAY itself reduce some device spellings to an
    ordinary path before this function ever sees them -- `\\.\` drive
    forms are observed to come back as plain drive paths -- in which case
    the ordinary component comparison decides them and the explicit
    branch below never runs. Whatever namespace form does survive
    resolution and cannot be mapped onto a drive or UNC path --
    `\\?\Volume{...}`, `\\?\GLOBALROOT\...`, a bare prefix, a bare
    `\\?\UNC\` -- is refused rather than guessed at.

    Fails CLOSED on the expected conversion, resolution and
    component-construction failures -- `OSError`, `ValueError` and
    `TypeError` raised by `os.fspath`, `realpath`, `normcase` or the
    component split -- and on the unmapped namespaces above. Each returns
    False, because an unprovable relationship is not a safe one.
    Exceptions outside that set are deliberately NOT caught: a
    `RuntimeError` is a defect, not an unusable path, and must not be
    reported as a safe refusal.

    Two inputs are rejected EXPLICITLY rather than left to raise. A
    `bytes` path -- including a path-like object whose `__fspath__`
    returns `bytes` -- is a valid path to the operating system but not to
    the string work here. And an embedded NUL is refused outright: it
    cannot occur in a filename, `realpath` does not reject it on every
    platform (on Windows it is returned unchanged, NOT raised as
    `ValueError`), and the `os.open` that would follow raises
    `ValueError`, which is not the `OSError` the lock path contains. Both
    are decided before anything is opened.

    That covers the `main` route only. `_LockHandle.acquire` still
    catches only `OSError`, so a caller using `single_instance_lock`
    DIRECTLY with such a path can still receive the `ValueError`. That is
    a separate, disclosed defect and is not repaired here.

    The default lock path is run through this same decision rather than
    trusted, since nothing guarantees the system temporary directory is
    outside the target.

    This is a NAMESPACE check, not an atomic one. It establishes the
    relationship at the instant it is asked; a path component replaced
    between this call and the open is not detected, and no filesystem
    primitive available here would close that window. Nor does it see a
    POSIX bind mount, which presents one directory under two names that
    `realpath` collapses in neither direction. It removes a foreseeable
    operator error and a self-inflicted wedge -- it is not an adversarial
    guarantee, and does not claim to be.
    """
    canonical = []
    for candidate in (directory, lock_path):
        try:
            text = os.fspath(candidate)
        except (OSError, ValueError, TypeError):
            return False
        # Text paths only. `bytes` is a valid path to the operating system
        # but not to the string work below, and letting it reach that work
        # turned a refusable input into an escaping `TypeError`. The check
        # is AFTER `os.fspath`, because a path-like object can return
        # `bytes` from `__fspath__`.
        if not isinstance(text, str):
            return False
        # A NUL cannot occur in a filename. `realpath` returns it unchanged
        # on Windows rather than raising, and the `os.open` that would
        # follow raises `ValueError` -- not the `OSError` the lock path
        # contains -- so it is refused here, before anything is opened.
        if "\x00" in text:
            return False
        try:
            resolved = os.path.realpath(text)
            # `realpath` may already have reduced a device spelling to an
            # ordinary path, in which case the comparison below decides it
            # and this branch never runs. What survives resolution and
            # cannot be mapped is refused.
            if resolved[:4] == "\\\\.\\":
                return False
            # The extended-length forms are spellings of ordinary paths,
            # and `realpath` keeps that prefix -- so without this the same
            # directory spelled two ways compares as two different roots
            # and containment is missed entirely.
            if resolved[:4] == "\\\\?\\":
                rest = resolved[4:]
                if len(rest) > 4 and rest[:4].upper() == "UNC\\":
                    resolved = "\\\\" + rest[4:]
                elif (len(rest) >= 2 and rest[1] == ":"
                      and rest[0].isalpha()):
                    resolved = rest
                else:
                    return False
            # Components, never a string prefix. Both separators are split
            # so one canonical sequence comes out whatever spelling
            # arrived; on POSIX a backslash inside a name can only make
            # this refuse, which is the safe direction. The split is inside
            # the boundary because it is where a surviving non-text value
            # would raise.
            normalized = os.path.normcase(resolved)
            parts = [part for part
                     in normalized.replace("\\", "/").split("/")
                     if part]
        except (OSError, ValueError, TypeError):
            return False
        canonical.append(parts)
    target_parts, lock_parts = canonical
    if not target_parts:
        return False
    return lock_parts[:len(target_parts)] != target_parts


class _LockHandle:
    """An operating-system-held exclusive lock on one file.

    Held by the kernel against the open handle, so it is released when the
    handle closes -- including when the process dies abnormally. A "does the
    lock file exist" sentinel is deliberately NOT used: after a crash it goes
    stale and wedges maintenance permanently, which is the opposite of the
    property wanted here.
    """

    def __init__(self, path):
        self._path = Path(os.fspath(path))
        self._fd = None

    def acquire(self) -> bool:
        try:
            self._fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError:
            # Cannot even open the lock: report the fixed code and do nothing.
            # No path, no errno text, no traceback reaches the caller.
            self._fd = None
            return False
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            # The lock is held elsewhere. Releasing the descriptor is cleanup,
            # not the outcome: a close that fails here must not turn a plain
            # "another pass is running" into an exception carrying an errno
            # and a path, and must not replace the fixed `lock_unavailable`
            # line the operator is promised. Same rule as the manifest
            # journal: contain it, clear the reference exactly once on every
            # path, and never retry -- a failed close leaves the descriptor
            # state ambiguous, and a second attempt could close a descriptor
            # the runtime has already reissued to something else.
            try:
                os.close(self._fd)
            except OSError:
                pass
            finally:
                self._fd = None
            return False
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                os.lseek(self._fd, 0, os.SEEK_SET)
                msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        finally:
            # EXACTLY ONE close attempt, on every path, and its failure is
            # contained. This runs from `single_instance_lock.__exit__`, which
            # in `main` happens AFTER the report has been printed and the exit
            # status chosen -- so an escaping OSError could only replace a
            # complete, truthful outcome with a traceback, possibly one that
            # arrives when a QUARANTINE pass has already moved files. It would
            # also displace an exception the `with` body raised, hiding the
            # real diagnosis behind an errno from the lock file.
            #
            # `_fd` is cleared whatever the close did. Leaving a stale number
            # behind is not untidiness: the operating system reissues
            # descriptor numbers immediately, so a later traversal of this
            # method would close something else entirely. Clearing it is also
            # what makes a repeated `release` inert. The close is never
            # retried, for the same reason the manifest close is not.
            try:
                os.close(self._fd)
            except OSError:
                pass
            finally:
                self._fd = None


class single_instance_lock:  # noqa: N801 - used as a context manager
    """Yield True if this process took the lock, False if another holds it.

    A caller that receives False must do nothing at all: another pass is
    already running, and two concurrent passes could plan against each other's
    half-completed work.
    """

    def __init__(self, path):
        self._handle = _LockHandle(path)
        self._acquired = False

    def __enter__(self) -> bool:
        self._acquired = self._handle.acquire()
        return self._acquired

    def __exit__(self, *exc) -> bool:
        if self._acquired:
            self._handle.release()
        return False


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class QuarantineSurvey:
    """What one quarantine pass directory currently holds.

    The DIRECTORY CONTENTS are restoration ground truth. The manifest adds
    quarantine time and pre-move metadata; a crash between a rename and its
    journal record leaves a file that is still fully restorable by name and
    merely lacks recorded metadata, which is counted rather than repaired.

    Counts only. No name ever appears in this object or in anything emitted
    from it.
    """

    present: int
    manifested: int
    unmanifested: int
    malformed_records: int
    duplicates: int
    refused: Optional[RetentionFailureReason]


_MANIFEST_KEYS = ("basename", "class", "size", "mtime_ns", "quarantined_at")


def _exact_int(value) -> bool:
    # `True` is an `int` to Python. A schema that accepted it would not be the
    # closed schema this claims to be.
    return type(value) is int


def _valid_record(record) -> Optional[str]:
    """The basename a well-formed record names, or None if it is malformed."""
    if type(record) is not dict:
        return None
    if set(record) != set(_MANIFEST_KEYS):
        return None
    basename = record["basename"]
    klass = record["class"]
    if type(basename) is not str or type(klass) is not str:
        return None
    if not _exact_int(record["size"]) or record["size"] < 0:
        return None
    if not _exact_int(record["mtime_ns"]) or not _exact_int(
            record["quarantined_at"]):
        return None
    if classify_name(basename) != klass:
        return None
    return basename


def _survey_refusal(reason) -> QuarantineSurvey:
    return QuarantineSurvey(0, 0, 0, 0, 0, reason)


def _regular_file_identity(info):
    """`(dev, ino)` for a real regular file, or None.

    Proves the object is regular, is not a reparse point, and has a stable
    nonzero identity -- the file-shaped counterpart of `directory_state`.
    """
    if not stat_module.S_ISREG(info.st_mode) or _is_reparse_point(info):
        return None
    identity = _stable_identity(info)
    if identity is None:
        return None
    return identity[:2]


#: No-follow and nonblocking where the platform has them. Both are absent on
#: Windows and default to 0 there, exactly as the archive guard documents.
#:
#: `O_NOFOLLOW` closes the window between proving the path and opening it.
#: `O_NONBLOCK` matters because a plain read-only `open` of a FIFO blocks until
#: a writer appears: someone able to write into the quarantine directory could
#: otherwise `mkfifo` a `manifest.jsonl` and hang reconciliation indefinitely.
_MANIFEST_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_BINARY", 0)
)


def _read_manifest_bytes(manifest, byte_budget):
    """The journal's bytes, or None when it must be refused.

    Returns `b""` when there is simply no manifest -- an unjournalled pass
    directory is a state to report, not a fault.

    Three checks, not two. The PATH is proved before the open, the HANDLE
    after it, and the PATH AGAIN after that, with all three stable identities
    required to agree.

    The third is not redundant. Windows has no `O_NOFOLLOW`, so an attacker can
    move the real manifest aside and leave a symlink at its path pointing back
    at that same object. The open follows the link, so the handle carries
    exactly the identity the pre-open check recorded and `fstat` agrees --
    while the path is now a reparse point. Only re-reading the path can see
    that, and it is read before a single byte is consumed.

    Proving only the handle is weaker still: `fstat` reports the target, a
    perfectly ordinary regular file, and never the link that led to it.

    Every acquired handle receives exactly one close attempt, and a close that
    fails is a refusal rather than a footnote: bytes are returned only once
    the descriptor has actually been released. Reporting a normal result over
    a failed close would be a quiet lie about whether the read completed.

    As everywhere here, this detects replacement. It is not an atomic Windows
    defence against every hostile swap, and does not claim to be.
    """
    try:
        before = _regular_file_identity(os.lstat(manifest))
    except FileNotFoundError:
        return b""
    except OSError:
        return None
    if before is None:
        return None

    try:
        handle = os.open(manifest, _MANIFEST_OPEN_FLAGS)
    except FileNotFoundError:
        return b""
    except OSError:
        return None

    collected = None
    try:
        if _regular_file_identity(os.fstat(handle)) != before:
            # The opened object is not what the path described.
            collected = None
        elif _regular_file_identity(os.lstat(manifest)) != before:
            # The path is no longer that object -- including the alias case,
            # where the identity still matches but the path is now a link.
            collected = None
        else:
            # A bounded read LOOP. One `os.read` may legitimately return fewer
            # bytes than asked for, and treating that as end-of-file would
            # accept a partial prefix as the whole journal -- silently
            # reporting every record beyond it as unmanifested. The loop never
            # accumulates more than one look-ahead byte past the budget, stops
            # at a genuine end-of-file, and cannot spin, because each turn
            # either grows the buffer or breaks.
            limit = byte_budget + 1
            buffer = bytearray()
            while len(buffer) < limit:
                chunk = os.read(handle, limit - len(buffer))
                if not chunk:
                    break
                buffer.extend(chunk)
            collected = bytes(buffer)
    except OSError:
        collected = None

    # Exactly one close attempt, outside the block above so it happens on
    # every path, and its failure decides the outcome.
    try:
        os.close(handle)
    except OSError:
        return None
    return collected


def survey_quarantine(pass_directory, *, policy: RetentionPolicy) -> QuarantineSurvey:
    """Read-only, BOUNDED reconciliation of one pass directory.

    Nothing is restored, removed, rewritten or repaired here, in any
    circumstance. A truncated final record stays truncated: repairing a
    journal would destroy the evidence of how the pass ended.

    Every dimension is bounded, because this reads a directory an operator may
    have added to and a journal that may be corrupt: at most one batch of
    entries plus the manifest, and at most one batch of maximum-length records
    in bytes. Overflow is a sanitized refusal, never a partial answer.

    The schema is closed and exact -- the five named keys, no others, no
    booleans standing in for integers, and a class that agrees with the
    basename's own grammar.

    The pass directory is BOUND, and the binding is proved three times over.
    One non-following read takes `(dev, ino)` before anything is enumerated,
    and a directory with no such identity is refused there. That identity is
    then re-proved after `os.scandir` holds its iterator and before an entry
    is consumed, after enumeration has closed and before the manifest
    pathname is resolved, and once more the instant those bytes come back --
    before a single record is parsed and before any count is calculated.

    The third proof is not decoration. Enumeration and the manifest read
    resolve the SAME pathname twice, so without it names collected from the
    original directory could be reconciled against a journal read from its
    replacement and hand back a `manifested` count that neither directory
    ever held. A mismatch at any proof discards every collected name and
    every manifest byte and answers the ordinary zeroed refusal; it is taken
    ahead of the byte-budget refusal, because measuring bytes that came from
    somewhere else is not discarding them.

    This is the PASS directory's own binding, and it is not the data root's.
    A scan binding travels with a live scan of the maintained data root;
    this one is taken here, on the directory handed in, and never leaves the
    call. Reconciliation still reads no data root at all.

    Three extra metadata reads, fixed at one per proof -- never one per entry
    and never one per record. Contents may change freely within the same
    directory: an operator adding or removing a file changes what is
    enumerated without changing `(dev, ino)`, and that is not a replacement.

    What this does NOT close: every proof reads a PATHNAME, and the operating
    system resolves that pathname again when it opens the directory and again
    when it opens the manifest. A substitution installed and withdrawn wholly
    between two proofs -- so that `os.scandir` or the manifest open lands on
    the impostor while both bracketing reads see the original -- is not
    detected. Neither is a recycled identity: a `(dev, ino)` the platform has
    handed back out compares equal to the one it replaced, so an object that
    was removed and another created into its slot can satisfy every proof.
    This detects replacement between the explicit proofs. It is not an atomic
    defence against a hostile swap and does not claim to be.
    """
    if not isinstance(policy, RetentionPolicy):
        raise TypeError("explicit RetentionPolicy required")

    root = Path(os.fspath(pass_directory))
    # RETAINED, not discarded. Proving the directory and then throwing the
    # answer away leaves every later resolution of this pathname unbound.
    surveyed = directory_state(root)
    if surveyed is None:
        return _survey_refusal(RetentionFailureReason.SURVEY_DIRECTORY_INVALID)

    # PAYLOAD entries are capped on their own, and the manifest is allowed as
    # at most one ADDITIONAL entry. Charging them to one shared budget would
    # let a missing manifest hand back a spare payload slot, which is not what
    # "one batch" means.
    present = []
    manifest_entries = 0
    try:
        with os.scandir(root) as entries:
            # (a) The iterator is held; nothing has been consumed from it yet.
            if not _scanned_root_unchanged(root, surveyed):
                return _survey_refusal(
                    RetentionFailureReason.SURVEY_DIRECTORY_INVALID)
            for entry in entries:
                if entry.name == MANIFEST_NAME:
                    manifest_entries += 1
                    if manifest_entries > 1:  # pragma: no cover - one name
                        return _survey_refusal(
                            RetentionFailureReason.SURVEY_LIMIT_EXCEEDED)
                    continue
                present.append(entry.name)
                if len(present) > policy.max_actions_per_pass:
                    return _survey_refusal(
                        RetentionFailureReason.SURVEY_LIMIT_EXCEEDED)
    except OSError:
        return _survey_refusal(RetentionFailureReason.SURVEY_DIRECTORY_INVALID)

    # (b) Enumeration is over and the iterator is closed. The names in hand
    # came from this directory, and the manifest pathname is about to be
    # resolved through the same root component.
    if not _scanned_root_unchanged(root, surveyed):
        return _survey_refusal(RetentionFailureReason.SURVEY_DIRECTORY_INVALID)

    # Exactly one batch of maximum-length records, plus a single look-ahead
    # byte whose arrival is itself the refusal.
    byte_budget = policy.max_actions_per_pass * MAX_MANIFEST_RECORD_BYTES
    raw = _read_manifest_bytes(root / MANIFEST_NAME, byte_budget)
    if raw is None:
        return _survey_refusal(RetentionFailureReason.SURVEY_DIRECTORY_INVALID)
    # (c) The bytes are in hand. Proved BEFORE the byte budget is applied:
    # a length taken from a journal that belongs to some other directory must
    # not decide this directory's refusal reason, and discarding the bytes
    # means not measuring them either.
    if not _scanned_root_unchanged(root, surveyed):
        return _survey_refusal(RetentionFailureReason.SURVEY_DIRECTORY_INVALID)
    if len(raw) > byte_budget:
        return _survey_refusal(RetentionFailureReason.SURVEY_LIMIT_EXCEEDED)

    manifested = set()
    malformed = 0
    duplicates = 0
    if raw:
        chunks = raw.split(b"\n")
        if chunks and chunks[-1] == b"":
            chunks.pop()
        elif chunks:
            # A crash can leave the final record without its newline, or half
            # written. Unresolved, never absent, and never repaired.
            malformed += 1
            chunks.pop()
        # However short the records are, at most one batch of them is parsed:
        # a corrupt journal of one-byte lines must not turn reconciliation
        # into unbounded work just because each line is tiny.
        if len(chunks) > policy.max_actions_per_pass:
            return _survey_refusal(RetentionFailureReason.SURVEY_LIMIT_EXCEEDED)
        for chunk in chunks:
            if len(chunk) + 1 > MAX_MANIFEST_RECORD_BYTES:
                malformed += 1
                continue
            try:
                text = chunk.decode("utf-8")
            except UnicodeDecodeError:
                malformed += 1
                continue
            try:
                record = json.loads(text)
            except ValueError:
                malformed += 1
                continue
            basename = _valid_record(record)
            if basename is None:
                malformed += 1
                continue
            if basename in manifested:
                duplicates += 1
                continue
            manifested.add(basename)

    return QuarantineSurvey(
        present=len(present),
        manifested=len([name for name in present if name in manifested]),
        unmanifested=len([name for name in present if name not in manifested]),
        malformed_records=malformed,
        duplicates=duplicates,
        refused=None,
    )


class PlatformUnsupported(OSError):
    """This platform has no no-replace move that stage one is willing to use."""


def platform_move(source, destination) -> None:
    """Move `source` onto `destination`, refusing if the destination exists.

    Windows is the operational target and `os.rename` there is no-replace at
    the operating-system level: it raises when the destination exists rather
    than clobbering it. That is the property this tranche needs, because a
    silent replacement would be a deletion inside a change that promises none.

    POSIX `os.rename` REPLACES an existing destination silently, and the
    obvious workaround -- test for the destination, then rename -- is a race,
    not an atomic operation, and this module will not describe it as one.
    Rather than ship a check-then-move dressed up as safe, stage one refuses
    to quarantine on POSIX at all. `PLAN` remains fully portable, and the
    movement step is injectable so the lifecycle is still exercised in CI.

    A proven no-replace primitive per platform (`renameat2`/`RENAME_NOREPLACE`
    on Linux, `renamex_np` on macOS) is a later tranche.
    """
    if os.name != "nt":
        raise PlatformUnsupported(errno.ENOTSUP,
                                  "quarantine_platform_unsupported")
    os.rename(source, destination)


def _stable_identity(info):
    """`(dev, ino, size, mtime_ns)`, or None when identity is unavailable.

    Size and modification time alone are NOT identity: a swapped file can
    carry both. A zero device or inode means the platform did not supply a
    stable identity for this object, and a move that cannot be verified must
    not happen at all.
    """
    dev = int(getattr(info, "st_dev", 0) or 0)
    ino = int(getattr(info, "st_ino", 0) or 0)
    if dev == 0 or ino == 0:
        return None
    return (dev, ino, int(info.st_size), int(info.st_mtime_ns))


def directory_state(path):
    """`(dev, ino)` for a real directory at `path`, or None.

    Proved from ONE fresh non-following read, and it proves three things
    together: that the object is a directory, that it is not a reparse point,
    and that it has a stable nonzero identity. `(dev, ino)` alone says WHICH
    object a path is, never what KIND -- so a pass path replaced by a symlink
    or a plain file kept an identity comparison passing while no longer being
    anywhere it is safe to move files into.

    Deliberately NOT the file 4-tuple. A directory's size and modification
    time change whenever its contents do -- writing the journal into the pass
    directory changes both -- so including them would make every legitimate
    move look like a swapped destination.

    This detects path replacement. It is not, and is not claimed to be, an
    atomic Windows defence against every hostile swap.
    """
    try:
        info = os.lstat(path)
    except OSError:
        return None
    if not stat_module.S_ISDIR(info.st_mode) or _is_reparse_point(info):
        return None
    identity = _stable_identity(info)
    if identity is None:
        return None
    return identity[:2]


def _scanned_root_unchanged(path, scanned) -> bool:
    """Whether `path` is STILL the exact directory a live scan enumerated.

    One fresh non-following read compared against the `(dev, ino)` the scan
    bound to itself. Deliberately the directory pair and never the file
    4-tuple: a directory's size and modification time change whenever its
    contents do, and a pass that moves entries out of the root it is
    maintaining changes both by design -- so a 4-tuple comparison would call
    the pass's own legitimate work a replacement.

    Fails closed on a MISSING binding, which is the whole point of the
    function existing rather than the comparison being written inline.
    `None` is the absence of an identity, not a value: `directory_state` also
    answers `None` for a path that is gone, so `scanned == directory_state(p)`
    would be true for an unbound scan over a path that does not exist and
    would "prove" a directory nothing ever read. An injected synthetic scan
    is exactly that case.

    This detects replacement. It is not an atomic defence against a hostile
    swap and does not claim to be: the caller acts on a PATHNAME, which the
    operating system resolves again when it acts.
    """
    if scanned is None:
        return False
    return directory_state(path) == scanned


def _open_manifest(pass_directory):
    """Exclusively create the journal and verify it by handle."""
    path = Path(pass_directory) / MANIFEST_NAME
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        info = os.fstat(fd)
        if not stat_module.S_ISREG(info.st_mode) or _is_reparse_point(info):
            raise OSError(errno.EINVAL, "manifest_not_regular")
    except BaseException:
        # Every validation exit closes the descriptor, including one raised by
        # `fstat` itself. A leaked handle here would keep the journal open for
        # the life of the process.
        os.close(fd)
        raise
    return fd


def _record(fd, action, quarantined_at) -> None:
    """Append one bounded, closed-schema record and synchronise it.

    The manifest is operational STATE, not a diagnostic. It necessarily holds
    basenames, so it lives inside the quarantine directory and is never
    emitted; everything this module prints stays strictly path-free.
    """
    payload = {
        "basename": action.basename,
        "class": action.klass,
        "size": int(action.size),
        "mtime_ns": int(action.mtime_ns),
        "quarantined_at": int(quarantined_at),
    }
    line = (json.dumps(payload, sort_keys=True, separators=(",", ":"))
            + "\n").encode("utf-8")
    if len(line) > MAX_MANIFEST_RECORD_BYTES:
        raise OSError(errno.ENAMETOOLONG, "manifest_record_too_long")
    # `os.write` may write fewer bytes than asked. A half-written record is a
    # silently corrupt journal, so this loops -- and a write that cannot make
    # progress is a refusal rather than an infinite loop.
    written = 0
    while written < len(line):
        count = os.write(fd, line[written:])
        if count <= 0:
            raise OSError(errno.EIO, "manifest_record_incomplete")
        written += count
    # Synchronised only once the record is whole.
    os.fsync(fd)


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class PassReport:
    """One pass, as aggregate counts and fixed codes only.

    Deliberately path-free apart from `planned_actions`, which is the caller's
    in-process plan rather than something emitted; `format_report` renders only
    counts and fixed identifiers.
    """

    mode: str
    refused: Optional[RetentionFailureReason]
    processed: int
    inspected: int
    excluded: int
    snapshot_eligible: int
    telemetry_eligible: int
    ambiguous: int
    planned_actions: Tuple[PlannedAction, ...]
    planned_actions_count: int
    moved: int
    skipped: int
    unmanifested: int
    halted: bool
    reserve_ok: bool
    snapshot_actions_blocked: bool


def _report(mode, *, refused=None, scan=None, plan=None, actions=(), moved=0,
            skipped=0, unmanifested=0, halted=False, reserve_ok=True,
            blocked=False) -> PassReport:
    processed = getattr(scan, "processed", 0)
    inspected = getattr(scan, "inspected", 0)
    excluded = getattr(scan, "excluded", 0)
    return PassReport(
        mode=mode.value,
        refused=refused,
        processed=processed,
        inspected=inspected,
        excluded=excluded,
        snapshot_eligible=getattr(plan, "snapshot_eligible", 0),
        telemetry_eligible=getattr(plan, "telemetry_eligible", 0),
        ambiguous=getattr(plan, "ambiguous", 0),
        planned_actions=tuple(actions),
        planned_actions_count=len(tuple(actions)),
        moved=moved,
        skipped=skipped,
        unmanifested=unmanifested,
        halted=halted,
        reserve_ok=reserve_ok,
        snapshot_actions_blocked=blocked,
    )


def format_report(report: PassReport) -> str:
    """One fixed, path-free line. Counts, booleans and closed codes only."""
    reason = report.refused.value if report.refused is not None else "none"
    return (
        "retention mode=%s refused=%s processed=%d inspected=%d excluded=%d "
        "snap_eligible=%d telem_eligible=%d ambiguous=%d planned=%d "
        "moved=%d skipped=%d unmanifested=%d halted=%s reserve_ok=%s "
        "snapshot_blocked=%s"
        % (report.mode, reason, report.processed, report.inspected,
           report.excluded, report.snapshot_eligible, report.telemetry_eligible,
           report.ambiguous, report.planned_actions_count, report.moved,
           report.skipped, report.unmanifested, report.halted,
           report.reserve_ok, report.snapshot_actions_blocked)
    )


def _idle_quarantine_root_usable(data_root, device) -> bool:
    """Whether an EXISTING quarantine root is usable, creating nothing.

    The sibling below creates the root when it is missing, which is exactly
    what a pass with no actions must not do. This answers the narrower
    question an idle pass needs, from ONE non-following read:

        absent                          -> True, and nothing was created
        present, usable, same device    -> True
        present and anything else       -> False

    Only `FileNotFoundError` counts as absent. Any other metadata failure is a
    root that exists and cannot be proved, which fails closed -- an idle pass
    that reported a clean no-op over an unusable root would tell an operator
    the directory is healthy right up until the next action-bearing pass.

    The three structural checks mirror `directory_state`, deliberately, rather
    than calling it: distinguishing absence from unusability needs the errno,
    and a second `os.lstat` would open a window between the two reads for the
    very replacement this is looking for.
    """
    root = Path(data_root) / QUARANTINE_DIRNAME
    try:
        info = os.lstat(root)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if not stat_module.S_ISDIR(info.st_mode) or _is_reparse_point(info):
        return False
    identity = _stable_identity(info)
    # Same volume: a same-volume rename is the whole basis for the move being
    # a directory-entry operation, so a root that has become a mount point
    # elsewhere is already unusable, today's pass moving nothing or not.
    return identity is not None and identity[0] == device


def _root_creation_has_headroom(scan, policy: RetentionPolicy) -> bool:
    """Whether ONE more top-level entry fits inside the scanner's own bound.

    Only a SUCCESSFUL scan says anything about the entry count; anything else
    is treated as no headroom at all, which fails closed. The scanner never
    reports more than `max_directory_entries` -- it refuses one past it on an
    unprocessed look-ahead -- so `>=` and `==` coincide for any scan this
    module produced. `<` is written rather than `!=` so the comparison stays
    fail-closed if that ever changes.
    """
    if not isinstance(scan, ScanSucceeded):
        return False
    return scan.processed < policy.max_directory_entries


def _validated_quarantine_root(data_root, *, may_create):
    """The quarantine root as a real, non-reparse directory on this volume.

    Returns `(root, None)` when the root is usable, or `(None, reason)`.

    Creating an ABSENT root costs the data root one top-level entry, and the
    scan charges every yielded root entry against `max_directory_entries` and
    refuses one past it. So creation is gated: `may_create` is false when the
    successful scan processed the maximum, and the pass then refuses
    `ENTRY_LIMIT_EXCEEDED` rather than pushing the directory past the very
    bound it exists to hold -- after which no later pass could scan far enough
    to help. Nothing is created on that path and no mover is called.

    That is a deliberate, disclosed trade: an action batch that might itself
    have relieved the directory is forgone at exactly the limit, because every
    planned move can still be skipped -- an open handle, a changed identity, a
    quiescence window -- leaving a net gain of one entry and a directory no
    later pass can read. The refusal is also PERSISTENT at the exact limit,
    and hand-creating the root is the one repair that makes it worse: that
    pushes the directory to the limit plus one, where the SCANNER refuses
    first. The remedies are raising the bound or relieving entries out of
    band, never a removal from here.

    It does NOT close the residual race in which a concurrent producer adds
    entries between the scan and this creation; nothing here makes those two
    steps atomic.

    Absence is proved SPECIFICALLY by `FileNotFoundError` from one
    non-following read. `directory_state(root) is None` cannot serve here: it
    conflates "absent" with "present and unprovable", so a root that exists
    but cannot be read would be charged headroom it does not consume -- and,
    worse, would be handed to `os.mkdir`. Any other `OSError` is a root that
    exists and cannot be proved, which stays the more specific
    `QUARANTINE_ROOT_INVALID`.

    The three structural checks mirror `directory_state` rather than calling
    it, for the same reason `_idle_quarantine_root_usable` does: telling
    absence from unusability needs the errno, and a second `os.lstat` would
    open a window between the two reads for the very replacement this looks
    for. The caller still re-proves the root's identity and device
    immediately before any mutation.
    """
    root = Path(data_root) / QUARANTINE_DIRNAME
    try:
        info = os.lstat(root)
    except FileNotFoundError:
        # The ONLY creating branch, and only with headroom to spend.
        if not may_create:
            return None, RetentionFailureReason.ENTRY_LIMIT_EXCEEDED
        try:
            os.mkdir(root)
        except OSError:
            return None, RetentionFailureReason.QUARANTINE_ROOT_INVALID
        if directory_state(root) is None:
            return None, RetentionFailureReason.QUARANTINE_ROOT_INVALID
        return root, None
    except OSError:
        return None, RetentionFailureReason.QUARANTINE_ROOT_INVALID
    if not stat_module.S_ISDIR(info.st_mode) or _is_reparse_point(info):
        return None, RetentionFailureReason.QUARANTINE_ROOT_INVALID
    if _stable_identity(info) is None:
        return None, RetentionFailureReason.QUARANTINE_ROOT_INVALID
    return root, None


def _quarantine(data_root, plan_actions, *, policy, now_ns, pass_id, scan,
                plan, reserve_ok, blocked, mover):
    """Move at most one bounded batch into a fresh, exclusively created pass
    directory, journalling each completed move.

    The rename is same-volume and therefore a directory-entry operation, but it
    is NOT proof against a hostile path swap: nothing available here makes that
    atomic on Windows. What this does provide is recoverability plus
    detection -- the object's complete stable identity is verified immediately
    before the move and again afterwards, and a mismatch stops the whole pass
    and preserves the moved object for audit rather than attempting a second
    blind move to put it back.
    """
    mode = RetentionMode.QUARANTINE

    # The identifier is validated before ANYTHING is created, because it is
    # joined beneath the quarantine root: an absolute value would replace that
    # root outright and a `..` component would escape it.
    if not valid_pass_id(pass_id):
        return _report(mode, refused=RetentionFailureReason.PASS_ID_INVALID,
                       scan=scan, plan=plan, actions=plan_actions,
                       reserve_ok=reserve_ok, blocked=blocked)

    # The data root itself first, before anything is created or moved: it must
    # be a real directory with a stable identity, or an environment that cannot
    # support any of this does exactly nothing.
    #
    # And it must be the SAME real directory the scan enumerated. Proving only
    # that the path is usable proves nothing about WHICH object it is, so a
    # root renamed or replaced after `scan_retention_candidates` closed its
    # iterator would be accepted here -- and this is the last point at which
    # that costs nothing. `_validated_quarantine_root` immediately below may
    # `os.mkdir` the quarantine root, `os.mkdir` then makes the pass directory
    # and `_open_manifest` the journal, all inside whatever the path now names.
    # The per-file identity checks in the move loop cannot help: they skip
    # planned ACTIONS, and skipping every action still leaves a quarantine tree
    # created inside a directory this pass never scanned.
    #
    # A single read serves both questions, so the check costs nothing extra.
    data_state = directory_state(data_root)
    scanned_root = getattr(scan, "root_identity", None)
    if (data_state is None or scanned_root is None
            or data_state != scanned_root):
        return _report(mode, refused=RetentionFailureReason.IDENTITY_UNAVAILABLE,
                       scan=scan, plan=plan, actions=plan_actions,
                       reserve_ok=reserve_ok, blocked=blocked)
    device = data_state[0]

    # Creation is charged against the scanner's own entry bound, so the root
    # is only made when this pass measured room for it.
    root, root_refusal = _validated_quarantine_root(
        data_root, may_create=_root_creation_has_headroom(scan, policy))
    if root is None:
        return _report(mode, refused=root_refusal,
                       scan=scan, plan=plan, actions=plan_actions,
                       reserve_ok=reserve_ok, blocked=blocked)

    # The quarantine tree must live on the data root's device: a same-volume
    # rename is the entire basis for the move being a directory-entry
    # operation, and a root that has become a mount point elsewhere silently
    # turns it into a copy.
    root_before = directory_state(root)
    if root_before is None or root_before[0] != device:
        return _report(mode, refused=RetentionFailureReason.QUARANTINE_ROOT_INVALID,
                       scan=scan, plan=plan, actions=plan_actions,
                       reserve_ok=reserve_ok, blocked=blocked)

    pass_directory = root / pass_id
    try:
        # Atomic exclusive creation: a bare mkdir raises when the path is
        # already there. A pre-existing pass path means either a repeated
        # identifier or someone else's evidence, and neither may be written
        # into, so no permissive-creation shortcut is used anywhere here.
        os.mkdir(pass_directory)
    except OSError:
        return _report(mode, refused=RetentionFailureReason.PASS_DIRECTORY_COLLISION,
                       scan=scan, plan=plan, actions=plan_actions,
                       reserve_ok=reserve_ok, blocked=blocked)

    # Re-proved AFTER the exclusive creation: the window between `mkdir` and
    # this read is exactly where a replacement would land.
    pass_identity = directory_state(pass_directory)
    root_identity = directory_state(root)
    if (pass_identity is None or root_identity is None
            or pass_identity[0] != device or root_identity != root_before):
        return _report(mode, refused=RetentionFailureReason.QUARANTINE_ROOT_INVALID,
                       scan=scan, plan=plan, actions=plan_actions,
                       reserve_ok=reserve_ok, blocked=blocked)

    try:
        manifest_fd = _open_manifest(pass_directory)
    except OSError:
        return _report(mode, refused=RetentionFailureReason.MANIFEST_CREATE_FAILED,
                       scan=scan, plan=plan, actions=plan_actions,
                       reserve_ok=reserve_ok, blocked=blocked)

    moved = 0
    skipped = 0
    unmanifested = 0
    halted = False
    refused = None
    close_failed = False
    quiescence_ns = policy.quiescence_seconds * _NANOSECONDS

    try:
        for action in plan_actions:
            source = Path(data_root) / action.basename

            # -- revalidate immediately before the move ---------------------
            try:
                info = os.lstat(source)
            except OSError:
                skipped += 1
                continue
            if classify_name(action.basename) != action.klass:
                skipped += 1
                continue
            if not stat_module.S_ISREG(info.st_mode) or _is_reparse_point(info):
                skipped += 1
                continue
            # The authoritative link check: Windows reports 0 from a DirEntry,
            # so this is the first place the count is real.
            if int(getattr(info, "st_nlink", 1) or 1) != 1:
                skipped += 1
                continue
            identity = _stable_identity(info)
            if identity is None:
                refused = RetentionFailureReason.IDENTITY_UNAVAILABLE
                halted = True
                break
            if identity != action.identity:
                # The complete identity, not merely size and time: a swapped
                # object can carry both of those unchanged.
                skipped += 1
                continue
            if (now_ns - identity[3]) < quiescence_ns:
                skipped += 1
                continue

            # -- the source's directory is still the one that was scanned ---
            # `mover` is handed PATHNAMES, and the operating system resolves
            # `data_root / basename` afresh when it renames. The identity
            # matched just above belongs to whatever that path names NOW, so
            # on its own it cannot tell a planned entry from an identically
            # named entry in a directory swapped in behind it. This is what
            # makes "before moving any candidate" literal rather than
            # inferred from the destination proofs below.
            #
            # Halts rather than skips: a data root that is no longer the
            # scanned one invalidates every remaining action at once, not
            # this one.
            if not _scanned_root_unchanged(data_root, scanned_root):
                refused = RetentionFailureReason.IDENTITY_UNAVAILABLE
                halted = True
                break

            # -- the quarantine destination is still what it was ------------
            if (directory_state(pass_directory) != pass_identity
                    or directory_state(root) != root_identity):
                refused = RetentionFailureReason.QUARANTINE_ROOT_INVALID
                halted = True
                break

            destination = pass_directory / action.basename
            try:
                mover(source, destination)
            except OSError:
                # A reader's open handle makes this fail on Windows. That is a
                # safety property, not a fault: skip and carry on.
                skipped += 1
                continue
            moved += 1

            # -- verify what actually arrived -------------------------------
            try:
                arrived = _stable_identity(os.lstat(destination))
            except OSError:
                arrived = None
            if arrived != identity:
                refused = RetentionFailureReason.IDENTITY_MISMATCH_AFTER_MOVE
                halted = True
                unmanifested += 1
                break
            if (directory_state(pass_directory) != pass_identity
                    or directory_state(root) != root_identity):
                refused = RetentionFailureReason.QUARANTINE_ROOT_INVALID
                halted = True
                unmanifested += 1
                break

            try:
                _record(manifest_fd, action, now_ns)
            except OSError:
                # The object is already moved and is now evidence without a
                # record. Stop safely rather than continue journal-blind.
                unmanifested += 1
                refused = RetentionFailureReason.MANIFEST_RECORD_FAILED
                halted = True
                break
    finally:
        # EXACTLY ONE close attempt, on every path. A failure here is caught
        # rather than allowed to escape: objects may already have moved, and
        # letting an OSError out would cost the caller the entire aggregate --
        # how many moved, how many were skipped, how many are evidence without
        # a record -- and would print a traceback where the operator expects
        # one fixed, path-free line. It is never retried: a failed close leaves
        # the descriptor state ambiguous, and a second attempt could close a
        # descriptor the runtime has already reissued to something else.
        try:
            os.close(manifest_fd)
        except OSError:
            close_failed = True

    if close_failed:
        # Every record already completed its bounded write and `fsync`, so
        # nothing is unmanifested merely because the descriptor did not release
        # cleanly; the count is left exactly as the loop set it. An earlier
        # refusal is more specific than this one and is preserved.
        if refused is None:
            refused = RetentionFailureReason.MANIFEST_RECORD_FAILED
        halted = True

    return _report(mode, refused=refused, scan=scan, plan=plan,
                   actions=plan_actions, moved=moved, skipped=skipped,
                   unmanifested=unmanifested, halted=halted,
                   reserve_ok=reserve_ok, blocked=blocked)


def run_pass(directory, *, policy: RetentionPolicy, mode: RetentionMode,
             now_ns=None, pass_id=None, admit=None, scan=None,
             mover=None) -> PassReport:
    """One retention pass. `PLAN` inspects and reports; `QUARANTINE` moves.

    There is no parameter by which a caller can supply a plan: a live pass
    always scans and plans afresh, so a stale dry-run result can never be
    replayed against a directory that has moved on. `scan` exists only for
    `PLAN`-mode analysis and is refused outright in `QUARANTINE`.

    `now_ns` is captured once and used throughout, so every age comparison in
    one pass is against a single instant.
    """
    if not isinstance(policy, RetentionPolicy):
        raise TypeError("explicit RetentionPolicy required")
    if not isinstance(mode, RetentionMode):
        raise TypeError("explicit RetentionMode required")
    if scan is not None and mode is not RetentionMode.PLAN:
        raise ValueError("retention_scan_injection_plan_only")
    if mode is RetentionMode.QUARANTINE:
        # Both gates are checked before any work: an invalid identifier or an
        # unsupported platform must cost nothing at all.
        if not valid_pass_id(pass_id if pass_id is not None
                             else _default_pass_id()):
            return _report(mode,
                           refused=RetentionFailureReason.PASS_ID_INVALID)
        if mover is None and os.name != "nt":
            return _report(
                mode,
                refused=RetentionFailureReason.QUARANTINE_PLATFORM_UNSUPPORTED)

    captured_now = int(now_ns) if now_ns is not None else int(_wall_clock_ns())
    observed = scan if scan is not None else scan_retention_candidates(
        directory, policy=policy)
    plan = plan_retention(observed, policy=policy, now_ns=captured_now)

    if plan.refused is not None:
        return _report(mode, refused=plan.refused, scan=observed, plan=plan)

    # -- the snapshot reserve gates snapshot actions only --------------------
    #
    # Telemetry is read by no resume path, and `/api/telemetry` consumes only
    # the newest file, which the telemetry floor protects by three orders of
    # magnitude. Coupling telemetry cleanup to snapshot availability would be
    # superstition rather than safety, so it is deliberately not coupled.
    wants_snapshots = any(action.klass == SNAPSHOT_CLASS
                          for action in plan.actions)
    reserve_ok = True
    if wants_snapshots:
        try:
            reserve_ok = snapshot_reserve_available(
                observed, policy=policy, data_dir=directory, admit=admit)
        except SnapshotArchiveRejected:  # pragma: no cover - probe handles it
            reserve_ok = False
        except Exception:
            return _report(mode,
                           refused=RetentionFailureReason.RESERVE_CHECK_FAILED,
                           scan=observed, plan=plan, reserve_ok=False)

    blocked = wants_snapshots and not reserve_ok
    if blocked:
        # Re-plan from a telemetry-only view of the SAME observed scan, so the
        # action cap is applied to what may actually be actioned. Filtering
        # snapshots out of the already-capped batch instead would discard
        # those positions rather than refill them: a directory whose oldest
        # eligible entries are all snapshots takes no telemetry action at all,
        # however much telemetry was eligible.
        #
        # The planner is unchanged and still owns ordering, the oldest-first
        # merge and the action cap -- only its input is narrowed, and only on
        # this branch. `plan` above remains the source of the reported
        # eligibility counts, so those stay complete rather than selected.
        telemetry_only = dataclasses.replace(observed, snapshots=())
        actions = plan_retention(
            telemetry_only,
            policy=policy,
            now_ns=captured_now,
        ).actions
    else:
        actions = plan.actions

    if mode is RetentionMode.PLAN:
        # A LIVE plan proves the target it actually read, immediately before
        # reporting on it. `scan_retention_candidates` reports a missing or
        # non-directory path as an EMPTY SUCCESS -- correct in isolation,
        # because there is nothing to maintain -- and `os.scandir` FOLLOWS a
        # reparse point, so a junction is enumerated while being somewhere no
        # pass may act. `QUARANTINE` proves the root on both its branches;
        # without this, `PLAN` reports a clean no-op and the operator CLI
        # exits 0 over all three, which is the opposite of what was asked.
        #
        # ONLY when `scan is None`. An injected scan represents an object this
        # invocation did NOT read, so validating the supplied path would prove
        # the WRONG object and would couple a synthetic analysis to whatever
        # the working directory happens to contain.
        #
        # One non-following read, creating nothing. The quarantine root is
        # neither inspected nor made: `PLAN` mutates nothing at all, and
        # inspecting the root here would report on a path this mode never
        # touches.
        # It is not enough that the path is A usable directory: it must still
        # be THE directory this pass enumerated. `_scanned_root_unchanged`
        # compares against the identity the scan bound to itself and fails
        # closed when there is none -- which is also what keeps the injected
        # case honest, because an unbound scan can never satisfy it even if
        # the guard above were ever removed.
        if scan is None and not _scanned_root_unchanged(
                directory, observed.root_identity):
            return _report(mode,
                           refused=RetentionFailureReason.IDENTITY_UNAVAILABLE,
                           scan=observed, plan=plan, actions=actions,
                           reserve_ok=reserve_ok, blocked=blocked)
        return _report(mode, scan=observed, plan=plan, actions=actions,
                       reserve_ok=reserve_ok, blocked=blocked)

    if plan.ambiguous:
        # A future modification time undermines the ordering the entire policy
        # rests on, so nothing moves at all.
        return _report(mode, refused=RetentionFailureReason.TIMESTAMP_AMBIGUOUS,
                       scan=observed, plan=plan, actions=actions,
                       reserve_ok=reserve_ok, blocked=blocked)

    if not actions:
        # Nothing is actionable, so create nothing at all. `_quarantine` would
        # otherwise make the quarantine root, a pass directory and an empty
        # manifest while moving no entry -- and that is not merely untidy. The
        # scan charges EVERY yielded root entry against `max_directory_entries`
        # and refuses one entry past it, so a directory that scanned at exactly
        # the limit would be pushed over it by the very pass meant to relieve
        # it, after which no later pass could get far enough to help.
        #
        # The root is still PROVED here, because skipping `_quarantine` would
        # otherwise skip the only check that catches an unusable target: the
        # scan reports a missing or non-directory path as an empty SUCCESS, so
        # without this the pass would report a clean no-op against something
        # that is not a directory at all. Proving costs one read and creates
        # nothing.
        # Same binding as the action-bearing branch: an idle pass that
        # reported a clean no-op over a root it never scanned would tell an
        # operator the directory is healthy on the strength of a reading taken
        # somewhere else.
        data_state = directory_state(directory)
        if (data_state is None or observed.root_identity is None
                or data_state != observed.root_identity):
            return _report(mode,
                           refused=RetentionFailureReason.IDENTITY_UNAVAILABLE,
                           scan=observed, plan=plan, actions=actions,
                           reserve_ok=reserve_ok, blocked=blocked)
        # `_quarantine` was also the only place an EXISTING quarantine root
        # was proved, so skipping it must not skip that too. This creates
        # nothing: an absent root stays absent, and the next action-bearing
        # pass is what makes it.
        if not _idle_quarantine_root_usable(directory, data_state[0]):
            return _report(
                mode,
                refused=RetentionFailureReason.QUARANTINE_ROOT_INVALID,
                scan=observed, plan=plan, actions=actions,
                reserve_ok=reserve_ok, blocked=blocked)
        return _report(mode, scan=observed, plan=plan, actions=actions,
                       reserve_ok=reserve_ok, blocked=blocked)

    return _quarantine(directory, actions, policy=policy, now_ns=captured_now,
                       pass_id=pass_id if pass_id is not None
                       else _default_pass_id(),
                       scan=observed, plan=plan, reserve_ok=reserve_ok,
                       blocked=blocked,
                       mover=mover if mover is not None else platform_move)


def _wall_clock_ns() -> int:
    import time
    return time.time_ns()


def _default_pass_id() -> str:
    """A bounded, deterministic identifier. A timestamp, never a path."""
    import time
    return time.strftime("p%Y%m%dT%H%M%S", time.gmtime())


def main(argv=None) -> int:
    """Operator entry point. `PLAN` unless `--quarantine` is given explicitly.

    Prints one fixed, path-free line. It never restores and never reaps: both
    remain separately authorized operations with no implementation here.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description=("Bounded snapshot and telemetry retention. Plans by "
                     "default; quarantines one bounded batch only when asked. "
                     "Never deletes."))
    parser.add_argument("directory", help="the operational data directory")
    parser.add_argument("--quarantine", action="store_true",
                        help="move one bounded batch into quarantine")
    parser.add_argument("--lock", default=None,
                        help=("path to the single-instance lock file; by "
                              "default an opaque per-target name in the "
                              "system temporary directory, deliberately "
                              "OUTSIDE the directory being maintained"))
    args = parser.parse_args(argv)

    mode = (RetentionMode.QUARANTINE if args.quarantine
            else RetentionMode.PLAN)
    lock_path = args.lock or default_lock_path(args.directory)
    # Proved outside the maintained directory BEFORE any open, so an
    # unsafe placement creates nothing in the target and cannot wedge a
    # directory that is already at its entry bound. The existing
    # `lock_unavailable` code is reused: `acquire` already reports it when
    # the lock cannot be opened at all, and declining to open one whose
    # placement is unsafe is the same class of outcome.
    if not _lock_path_is_outside(lock_path, args.directory):
        print("retention refused=%s"
              % RetentionFailureReason.LOCK_UNAVAILABLE.value)
        return 1
    with single_instance_lock(lock_path) as acquired:
        if not acquired:
            print("retention refused=%s"
                  % RetentionFailureReason.LOCK_UNAVAILABLE.value)
            return 1
        report = run_pass(args.directory,
                          policy=PRODUCTION_RETENTION_POLICY, mode=mode)
        print(format_report(report))
        return 1 if (report.refused is not None or report.halted) else 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
