"""Cosmic Observatory: snapshot diagnostics and machine-readable reporting.

A deterministic, side-effect-free reporting seam. Nothing here renders, opens a
window, touches the network, writes a file, reads a snapshot from disk or
terminates the process — it takes an already-loaded ``ObservatorySnapshot`` and
returns data. That is what makes it directly testable and what lets the CLI own
exit statuses on its own.

Two products:

  * :func:`diagnose` — the ordered runtime-data-contract checks behind
    ``python -m vis.observatory doctor``.
  * :func:`snapshot_statistics` — the shared statistics both the human ``info``
    output and ``info --json`` are built from, so the two cannot drift.

Scope. These checks describe the Observatory's *runtime data contract*: the
shapes, dtypes, vocabularies and finiteness every renderer and consumer in this
package assumes. They are deliberately NOT scientific validity checks. An
all-void lattice, an all-zero memory channel, a zero fitness and unusual but
finite values are perfectly legal snapshots and are reported as passing.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from vis.observatory.constants import CHANNEL_NAMES, NUM_CHANNELS, STATE_NAMES

# Bumped only when the emitted structure changes incompatibly.
REPORT_SCHEMA = "utilityfog.observatory.report/1"

LATTICE_RANK = 3
LATTICE_DTYPE = np.uint8
MEMORY_DTYPE = np.float32

#: Sorted so the reported vocabulary is deterministic regardless of dict order.
KNOWN_STATE_IDS: Tuple[int, ...] = tuple(sorted(STATE_NAMES))

#: Suffix -> human name of the public load route, mirroring
#: ``vis.observatory.loader.load_snapshot``'s dispatch. Kept as data so the
#: report can name the route a source belongs to.
LOAD_ROUTES: Dict[str, str] = {".npz": "npz", ".json": "portable-genome JSON"}

#: Cap on how many unknown state ids a single ``detail`` string may name, so a
#: corrupt lattice cannot turn a report into a dump of its own cell values.
_MAX_REPORTED_STATE_IDS = 8

#: Cap on any single interpolated token in a ``detail``. A structured dtype
#: renders every one of its fields, a pathological suffix can be arbitrarily
#: long, and ``f"{value}"`` on an integer past ~4300 digits raises ValueError
#: outright. Capping keeps ``Check.detail``'s promise unconditional.
_MAX_DETAIL_TOKEN = 60

_FLOAT_MAX = sys.float_info.max

# --- dtype gating ----------------------------------------------------------
#
# `dtype.kind` characters: b bool, i signed int, u unsigned int, f float,
# c complex, m timedelta, M datetime, O object, S bytes, U unicode, V void.
#
# These two sets are the prerequisites for the only two value-inspecting
# operations in this module. They are deliberately narrow: a check that cannot
# be evaluated safely is reported as FAILED, never skipped into a pass.

#: Kinds whose values can be enumerated and converted to `int` exactly.
#: `np.unique()` sorts, and its sort raises for object dtype; `int()` then
#: raises for unicode, bytes, complex, datetime and void. Float is excluded
#: too, and that exclusion is load-bearing: `int(nan)` raises ValueError,
#: `int(inf)` raises OverflowError, and `int(2.7)` would silently fabricate
#: the valid state id 2 out of a value that is not a state id at all.
_STATE_INSPECTABLE_KINDS = frozenset("biu")

#: Kinds `np.isfinite()` accepts AND whose reductions yield real numbers.
#: numpy also accepts complex, but complex is excluded because `float()` on a
#: complex reduction raises TypeError one layer later, and because a complex
#: memory grid violates the dtype contract regardless.
_NUMERIC_KINDS = frozenset("biuf")


def _clip(value: Any) -> str:
    """Render one interpolated token, bounded and on a single line.

    Everything a ``detail`` interpolates goes through here. Two reasons, both
    demonstrated: a structured dtype's ``str()`` grows without limit and its
    field names are caller-supplied text that may contain newlines, which would
    forge report rows; and ``f"{n}"`` on a sufficiently large integer raises
    ``ValueError`` under CPython's integer-to-string limit.
    """
    try:
        text = str(value)
    except ValueError:
        # CPython's int->str digit limit. Narrow and named: the only operation
        # guarded is this one conversion, for the one documented failure.
        return "<unrenderable>"
    text = " ".join(text.splitlines())
    if len(text) > _MAX_DETAIL_TOKEN:
        text = text[:_MAX_DETAIL_TOKEN] + "..."
    return text


def one_line(text: Any) -> str:
    """Collapse anything ``str.splitlines()`` treats as a line boundary.

    A source path is untrusted data: rendered verbatim into the human report it
    can inject text that looks like an extra check row or a second summary
    line, so a reader (or a grep) would see a verdict the run never reached.
    The boundary set is wider than CR/LF -- ``\\v``, ``\\f``, ``\\x1c``-``\\x1e``,
    ``\\x85``, ``\\u2028`` and ``\\u2029`` all split -- so `splitlines()` is used
    rather than replacing the two obvious characters.

    This matches ``cli._one_line`` exactly. The duplication is deliberate: this
    module imports NumPy at module scope and the CLI must stay importable, and
    usable for argparse errors, without paying that cost.

    JSON output needs no equivalent: ordinary string escaping already makes
    these characters inert, and the value must round-trip verbatim.
    """
    return " ".join(str(text).splitlines()).strip()


@dataclass(frozen=True)
class Check:
    """One runtime-data-contract requirement and its outcome.

    ``detail`` is a short, human-readable explanation. It never contains
    payload contents -- only shapes, dtypes, counts and vocabulary members --
    so a report can be pasted anywhere without leaking snapshot data.
    """

    name: str
    ok: bool
    detail: str

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


# ---------------------------------------------------------------------------
# JSON-safety helpers
# ---------------------------------------------------------------------------


def json_number(value: Any) -> Optional[float]:
    """Return a JSON-safe float, or ``None`` for anything not finitely
    representable as one.

    ``NaN``, ``Infinity`` and ``-Infinity`` have no representation in strict
    JSON; Python's encoder emits the non-standard bare tokens ``NaN`` /
    ``Infinity`` unless told otherwise. Mapping them to ``null`` here means the
    document stays valid for every consumer, and the serializer can then run
    with ``allow_nan=False`` as a genuine assertion rather than a formality.

    Admission is POSITIVE rather than try/except: only the types this module
    can convert exactly are converted at all. That matters because ``float()``
    has three distinct failure modes here -- ``TypeError`` for a complex or an
    arbitrary object, ``ValueError`` for a non-numeric string, and
    ``OverflowError`` for an integer larger than ``sys.float_info.max``. The
    last is an ``ArithmeticError``, so a ``(TypeError, ValueError)`` handler
    would not have caught it, and ``math.isfinite()`` raises on the same value.
    The magnitude test below compares an ``int`` against a ``float``, which
    Python evaluates exactly and without conversion, so it cannot overflow.

    ``bool`` is deliberately not admitted: ``True`` is not the number 1.0, and
    silently reporting it as a fitness value would fabricate data.
    """
    if value is None:
        return None
    if type(value) is int:
        if not -_FLOAT_MAX <= value <= _FLOAT_MAX:
            return None
        return float(value)
    if isinstance(value, (float, np.floating, np.integer)):
        number = float(value)          # np.integer maxes out far below float
        return number if math.isfinite(number) else None
    return None


def _is_exact_int(value: Any) -> bool:
    """True only for a genuine Python ``int``.

    ``bool`` is excluded because ``type(True) is bool``, and ``float`` because
    ``2.0`` is not a generation counter. Both loader paths produce real ``int``
    values (``int(...)`` for NPZ, the portable-genome counter guard for JSON),
    so anything else means the snapshot was built by hand or by a defect.
    """
    return type(value) is int


def _is_real_number(value: Any) -> bool:
    return type(value) in (int, float)


def json_scalar(value: Any) -> Any:
    """JSON-safe rendering of a snapshot metadata scalar.

    A genuine ``int`` is emitted as-is. Anything else is coerced through
    :func:`json_number`, and anything that cannot be coerced becomes ``null``.

    This is reporting, not error suppression: the value being unrepresentable
    is itself a contract violation, and the corresponding check in
    :func:`diagnose` already reports it as a failure. Without this, a report
    *about* a broken counter would die inside the serializer instead of
    describing what was wrong -- the report builder must survive every input
    the checks are designed to flag.
    """
    if _is_exact_int(value):
        # Emitted verbatim, at any magnitude. A Python int of any size is a
        # legal JSON number, and it is the true value; forcing it through
        # float() would raise OverflowError above ~1.8e308 and would lose
        # precision well before that. Reporting the real counter beats
        # reporting a rounded one.
        return value
    return json_number(value)


def format_stat(value: Optional[float]) -> str:
    """Fixed-width rendering of one statistic for the human ``info`` table.

    ``None`` means the underlying value was non-finite: :func:`json_number`
    maps NaN and +/-Infinity to ``None`` so the JSON document stays strictly
    valid. The human table therefore says ``non-finite`` rather than being
    handed ``None`` and dying on a numeric format specifier.
    """
    return f"{value:+.4f}" if value is not None else "non-finite"


def format_percent(value: Optional[float]) -> str:
    """As :func:`format_stat`, for the percentage column."""
    return f"{value:5.1f}" if value is not None else "  n/a"


def format_count(value: Optional[int], width: int = 0) -> str:
    """Fixed-width rendering of a count for the human ``info`` table.

    ``None`` means the count could not be computed -- a lattice dtype the
    statistics cannot compare against an integer. The existing column layout is
    preserved exactly: ``width`` reproduces the previous ``{:>8,}`` for the
    per-state rows, and the default reproduces the unpadded ``{:,}`` used on
    the ``Non-void:`` line.
    """
    if value is None:
        return "n/a".rjust(width)
    return f"{value:>{width},}" if width else f"{value:,}"


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def diagnose(snapshot) -> List[Check]:
    """Return the ordered runtime-data-contract checks for ``snapshot``.

    The order is stable and does not depend on which checks pass, so two runs
    over equivalent snapshots produce identical reports. Every check is
    evaluated -- none short-circuits -- so a snapshot with several problems
    reports all of them at once. A check whose precondition failed reports its
    own failure rather than raising: for example, if the lattice is not an
    array, the rank check fails with an explanatory detail instead of blowing
    up on a missing attribute.
    """
    checks: List[Check] = []
    lattice = getattr(snapshot, "lattice", None)
    memory = getattr(snapshot, "memory_grid", None)

    # Scope note, stated plainly because the name invites a stronger reading:
    # this checks that the snapshot names a source belonging to one of the two
    # public load routes -- it does NOT re-open the file. Re-reading it would
    # be a side effect, and would prove nothing new inside `doctor`, which only
    # reaches here after `load_snapshot()` has already succeeded. The row earns
    # its place by making the report self-describing (a reader sees which route
    # the data came from) and by catching a snapshot assembled in memory when
    # `diagnose()` is used directly as a library call.
    # Suffix comparison is case-SENSITIVE on purpose: `load_snapshot` compares
    # `path.suffix == ".npz"` exactly, and `_validated_snapshot_path` rejects
    # anything else before loading. Lower-casing here would report `RUN.NPZ` as
    # loadable when the public route actually refuses it -- a check that fails
    # open is worse than no check.
    # `isinstance` before any truth test: `if source` on an ndarray raises
    # ValueError ("truth value ... is ambiguous"), and on an arbitrary object
    # `__bool__` can raise anything at all.
    source = getattr(snapshot, "source_path", None)
    has_source = isinstance(source, (str, Path)) and str(source) != ""
    suffix = Path(str(source)).suffix if has_source else ""
    route = LOAD_ROUTES.get(suffix)
    checks.append(Check(
        "source_loadable",
        route is not None,
        f"source is a {route} snapshot" if route is not None
        else (f"source suffix {_clip(suffix)!r} is not a public load route "
              f"({', '.join(sorted(LOAD_ROUTES))})" if has_source
              else "snapshot carries no source path"),
    ))

    lattice_is_array = isinstance(lattice, np.ndarray)
    checks.append(Check(
        "lattice_is_array",
        lattice_is_array,
        "lattice is a NumPy array" if lattice_is_array
        else f"lattice is {type(lattice).__name__}, expected numpy.ndarray",
    ))

    rank_ok = lattice_is_array and lattice.ndim == LATTICE_RANK
    checks.append(Check(
        "lattice_rank_is_three",
        rank_ok,
        f"lattice rank is {LATTICE_RANK}" if rank_ok
        else (f"lattice rank is {lattice.ndim}, expected {LATTICE_RANK}"
              if lattice_is_array else "lattice is not an array"),
    ))

    dims_ok = rank_ok and all(int(d) > 0 for d in lattice.shape)
    checks.append(Check(
        "lattice_dimensions_positive",
        dims_ok,
        f"lattice shape {tuple(int(d) for d in lattice.shape)}" if rank_ok and dims_ok
        else (f"lattice shape {tuple(int(d) for d in lattice.shape)} has a "
              "non-positive dimension" if rank_ok else "lattice rank is not 3"),
    ))

    lattice_dtype_ok = lattice_is_array and lattice.dtype == LATTICE_DTYPE
    checks.append(Check(
        "lattice_dtype",
        lattice_dtype_ok,
        f"lattice dtype is {np.dtype(LATTICE_DTYPE).name}" if lattice_dtype_ok
        else (f"lattice dtype is {_clip(lattice.dtype)}, expected "
              f"{np.dtype(LATTICE_DTYPE).name}" if lattice_is_array
              else "lattice is not an array"),
    ))

    # Prerequisite gate. `np.unique()` sorts, and its sort raises TypeError on
    # an object array whose elements cannot be ordered; `int(v)` then raises
    # for unicode, bytes, complex, datetime, void, and for the NaN and +/-Inf
    # a float array may carry. Inspecting values at all is therefore
    # conditional on a dtype where both operations are total.
    #
    # When the gate closes, the check reports FAILURE, not success: a
    # dependent evaluation that was deliberately not performed is not a pass.
    # The dtype violation is already reported by `lattice_dtype` above, so the
    # two rows agree rather than one silently fabricating a verdict.
    lattice_inspectable = (
        lattice_is_array and lattice.dtype.kind in _STATE_INSPECTABLE_KINDS
    )
    if lattice_inspectable and lattice.size:
        present = sorted(int(v) for v in np.unique(lattice))
        unknown = [v for v in present if v not in STATE_NAMES]
        states_ok = not unknown
        # Bounded on purpose. A uint8 lattice of arbitrary bytes yields up to
        # 251 distinct unknown ids; listing them all would dump cell values
        # into the report, which `Check.detail` promises never to do.
        shown = ", ".join(str(v) for v in unknown[:_MAX_REPORTED_STATE_IDS])
        if len(unknown) > _MAX_REPORTED_STATE_IDS:
            shown += f", ... ({len(unknown)} distinct)"
        detail = (
            f"all state ids within {list(KNOWN_STATE_IDS)}" if states_ok
            else f"state ids [{shown}] outside {list(KNOWN_STATE_IDS)}"
        )
    elif lattice_inspectable:
        states_ok, detail = True, "lattice is empty; no state ids to check"
    elif lattice_is_array:
        states_ok = False
        detail = (f"lattice dtype {_clip(lattice.dtype)} cannot be inspected "
                  "for state ids")
    else:
        states_ok, detail = False, "lattice is not an array"
    checks.append(Check("lattice_states_known", states_ok, detail))

    memory_is_array = isinstance(memory, np.ndarray)
    checks.append(Check(
        "memory_is_array",
        memory_is_array,
        "memory grid is a NumPy array" if memory_is_array
        else f"memory grid is {type(memory).__name__}, expected numpy.ndarray",
    ))

    # Gated on `rank_ok`, not merely on the lattice being an array: with a
    # rank-2 lattice of shape (8, 8), `(NUM_CHANNELS,) + shape` is (8, 8, 8),
    # which a genuinely wrong (8, 8, 8) memory grid would match -- the row
    # would report PASS for a grid that is not 8 channels over the lattice
    # volume. The expected shape is only meaningful once the rank is known.
    if memory_is_array and rank_ok:
        expected = (NUM_CHANNELS,) + tuple(int(d) for d in lattice.shape)
        actual = tuple(int(d) for d in memory.shape)
        shape_ok = actual == expected
        detail = (f"memory shape {actual}" if shape_ok
                  else f"memory shape {actual}, expected {expected}")
    else:
        shape_ok = False
        detail = ("memory grid is not an array" if not memory_is_array
                  else "lattice rank is not 3, so no memory shape is expected")
    checks.append(Check("memory_shape_matches_lattice", shape_ok, detail))

    memory_dtype_ok = memory_is_array and memory.dtype == MEMORY_DTYPE
    checks.append(Check(
        "memory_dtype",
        memory_dtype_ok,
        f"memory dtype is {np.dtype(MEMORY_DTYPE).name}" if memory_dtype_ok
        else (f"memory dtype is {_clip(memory.dtype)}, expected "
              f"{np.dtype(MEMORY_DTYPE).name}" if memory_is_array
              else "memory grid is not an array"),
    ))

    # Prerequisite gate. `np.isfinite()` raises TypeError for object, unicode,
    # bytes, datetime64, timedelta64 and void dtypes -- for object it raises
    # even when every element is a Python float, because the object loop looks
    # for an `isfinite` method on the element. Complex is accepted by numpy but
    # excluded here: it violates the dtype contract anyway, and its reductions
    # would fail one layer later inside the statistics.
    #
    # As above, a closed gate reports FAILURE rather than skipping to a pass.
    memory_numeric = memory_is_array and memory.dtype.kind in _NUMERIC_KINDS
    if memory_numeric and memory.size:
        finite_mask = np.isfinite(memory)
        non_finite = int(memory.size - int(np.count_nonzero(finite_mask)))
        finite_ok = non_finite == 0
        detail = ("all memory values are finite" if finite_ok
                  else f"{non_finite} non-finite memory value(s)")
    elif memory_numeric:
        finite_ok, detail = True, "memory grid is empty; no values to check"
    elif memory_is_array:
        finite_ok = False
        detail = (f"memory dtype {_clip(memory.dtype)} cannot be inspected "
                  "for finiteness")
    else:
        finite_ok, detail = False, "memory grid is not an array"
    checks.append(Check("memory_values_finite", finite_ok, detail))

    for field in ("generation", "ca_step"):
        value = getattr(snapshot, field, None)
        # `and` short-circuits, so `>= 0` only ever runs on a genuine int.
        ok = _is_exact_int(value) and value >= 0
        if _is_exact_int(value):
            # `_clip` because `f"{value}"` raises ValueError past CPython's
            # integer-to-string digit limit.
            detail = f"{field} is {_clip(value)}" if ok else f"{field} is negative"
        else:
            detail = f"{field} is {type(value).__name__}, expected a non-negative int"
        checks.append(Check(f"{field}_non_negative_int", ok, detail))

    # `float(fitness)` is NOT called here. `_is_real_number` admits any Python
    # int, and `float(10**400)` raises OverflowError -- an ArithmeticError, so
    # neither a TypeError nor a ValueError handler would catch it, and
    # `math.isfinite()` raises on the same value. `json_number` performs the
    # magnitude test by exact int/float comparison instead, which cannot
    # overflow, and returns None for anything not finitely representable.
    fitness = getattr(snapshot, "best_fitness", None)
    if _is_real_number(fitness):
        ok = json_number(fitness) is not None
        detail = ("best_fitness is finite" if ok
                  else "best_fitness is not a finite representable number")
    else:
        ok = False
        detail = f"best_fitness is {type(fitness).__name__}, expected a real number"
    checks.append(Check("best_fitness_finite", ok, detail))

    return checks


def summarize(checks: List[Check]) -> Dict[str, int]:
    """Counts for a completed diagnostic run."""
    passed = sum(1 for c in checks if c.ok)
    return {"total": len(checks), "passed": passed, "failed": len(checks) - passed}


def all_ok(checks: List[Check]) -> bool:
    return all(c.ok for c in checks)


# ---------------------------------------------------------------------------
# Shared statistics -- one implementation for human `info` and `info --json`
# ---------------------------------------------------------------------------


def snapshot_statistics(snapshot) -> Dict[str, Any]:
    """Return the statistics both `info` renderings are built from.

    Kept in one place deliberately: the human table and the JSON document
    previously would have needed two subtly different implementations of the
    same percentages and per-channel aggregates.

    Channel aggregates are computed over NON-VOID cells only, matching the
    established human output. A channel with no non-void cells is reported with
    ``populated: false`` and ``null`` aggregates rather than being omitted, so
    the JSON shape is the same for every snapshot; the human renderer skips
    those rows exactly as it always has.

    Preconditions and totality boundary
    -----------------------------------
    NONE. This function is total over every input :func:`diagnose` accepts,
    which is the contract that matters: :func:`doctor_report` embeds these
    statistics, so any input the checks are designed to *report* must not make
    the report itself unconstructible. It previously assumed strictly more than
    ``diagnose`` guaranteed -- bare attribute access, an orderable lattice
    dtype, and a memory dtype whose reductions are real numbers -- and raised
    ``AttributeError``/``TypeError`` on inputs the checks were built to flag.

    The key set is INVARIANT. When a statistic cannot be computed it is
    reported as ``null`` and the row still appears; nothing is fabricated and
    no invalid array is coerced into apparently valid scientific data. For a
    healthy snapshot every value is exact, unchanged from before.
    """
    # Read exactly as `diagnose` reads: a library caller may pass a partial or
    # duck-typed object, and the two must accept the same inputs.
    lattice = getattr(snapshot, "lattice", None)
    memory = getattr(snapshot, "memory_grid", None)

    lattice_is_array = isinstance(lattice, np.ndarray)
    shape = tuple(int(d) for d in lattice.shape) if lattice_is_array else ()
    # `size` rather than a product over `shape`: it is exact for a rank-0
    # array, where the empty product would coincidentally also give 1 but for
    # the wrong reason, and it is 0 for a non-array.
    total_cells = int(lattice.size) if lattice_is_array else 0

    # `lattice > 0` and `lattice == state_id` need an orderable numeric dtype.
    # Unicode, bytes, object-holding-strings, datetime64 and void all raise
    # TypeError on `>`; that is the dtype `lattice_dtype` already reports.
    countable = lattice_is_array and lattice.dtype.kind in _NUMERIC_KINDS
    non_void_mask = (lattice > 0) if countable else None

    state_counts = []
    for state_id in sorted(STATE_NAMES):
        count = int(np.count_nonzero(lattice == state_id)) if countable else None
        state_counts.append({
            "id": int(state_id),
            "name": STATE_NAMES[state_id],
            "count": count,
            "percent": (json_number(count / total_cells * 100)
                        if countable and total_cells else None),
        })

    # A report must survive every input its own checks are designed to flag.
    # `memory_grid[i][non_void_mask]` raises IndexError when the grid's spatial
    # dimensions differ from the lattice, and again when the grid has fewer
    # than eight channels -- precisely the snapshots `memory_shape_matches_
    # lattice` exists to report. Without this gate, `doctor --json` died with a
    # traceback and emitted no document at all on exactly those files, while
    # human `doctor` reported them correctly.
    #
    # The dtype term is equally load-bearing and was the later discovery: for a
    # SHAPE-MATCHING grid of unicode, bytes, complex or datetime64, `.min()`
    # and `.max()` succeed and only `float()` fails one layer down, so a
    # shape-only gate let a wrong dtype through to raise inside `json_number`.
    # The rank term keeps a rank-0 lattice from pairing with a rank-1 grid and
    # indexing a numpy scalar.
    channels_usable = (
        countable
        and lattice.ndim >= 1
        and isinstance(memory, np.ndarray)
        and memory.dtype.kind in _NUMERIC_KINDS
        and memory.ndim == lattice.ndim + 1
        and tuple(int(d) for d in memory.shape[1:]) == shape
    )

    channels = []
    for index, name in enumerate(CHANNEL_NAMES):
        values = None
        if channels_usable and index < int(memory.shape[0]):
            selected = memory[index][non_void_mask]
            if selected.size:
                values = selected
        channels.append({
            "index": index,
            "name": name,
            "populated": values is not None,
            "min": json_number(values.min()) if values is not None else None,
            "max": json_number(values.max()) if values is not None else None,
            "mean": json_number(values.mean()) if values is not None else None,
        })

    fitness = getattr(snapshot, "best_fitness", None)
    return {
        "shape": list(shape),
        "total_cells": total_cells,
        "non_void_count": (int(np.count_nonzero(non_void_mask))
                           if countable else None),
        "generation": json_scalar(getattr(snapshot, "generation", None)),
        "ca_step": json_scalar(getattr(snapshot, "ca_step", None)),
        # Gated on the exact-type test, not merely passed to `json_number`, so
        # a `bool` is reported as null rather than as the number 1.0.
        "best_fitness": json_number(fitness) if _is_real_number(fitness) else None,
        "state_counts": state_counts,
        "channels": channels,
    }


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def info_report(snapshot, source: str) -> Dict[str, Any]:
    """The `info --json` document."""
    report = {
        "schema": REPORT_SCHEMA,
        "kind": "info",
        "ok": True,
        "source": source,
    }
    report.update(snapshot_statistics(snapshot))
    return report


def doctor_report(snapshot, source: str, checks: List[Check]) -> Dict[str, Any]:
    """The `doctor --json` document."""
    return {
        "schema": REPORT_SCHEMA,
        "kind": "doctor",
        "ok": all_ok(checks),
        "source": source,
        "checks": [c.as_dict() for c in checks],
        "summary": summarize(checks),
        "snapshot": snapshot_statistics(snapshot),
    }


def format_doctor(checks: List[Check], source: str) -> List[str]:
    """Human `doctor` output, as lines, in the stable check order.

    Every check is listed whether it passed or failed, so a reader sees the
    full contract rather than only what broke, and the closing line states the
    verdict unambiguously.

    Every returned element is exactly one physical line. The source path is
    untrusted data -- on POSIX a filename may contain CR/LF, and even on
    Windows it may contain U+0085, U+2028 or U+2029, all of which
    ``str.splitlines()` treats as boundaries -- so rendered verbatim it could
    inject a convincing extra ``[PASS]`` row or a second summary line and make
    a reader, or a grep, see a verdict the run never reached. Details are
    collapsed for the same reason: a structured dtype's field names reach a
    detail as caller-supplied text.

    The exit status was never at risk: `cli` computes it from `all_ok`, not
    from this text. The integrity of the report a human reads is the point.
    """
    lines = [f"Snapshot: {one_line(source)}", ""]
    width = max((len(c.name) for c in checks), default=0)
    for check in checks:
        mark = "PASS" if check.ok else "FAIL"
        lines.append(f"  [{mark}] {check.name:<{width}}  {one_line(check.detail)}")
    counts = summarize(checks)
    lines.append("")
    if counts["failed"]:
        lines.append(
            f"FAILED: {counts['failed']} of {counts['total']} checks did not pass."
        )
    else:
        lines.append(f"OK: all {counts['total']} checks passed.")
    return lines
