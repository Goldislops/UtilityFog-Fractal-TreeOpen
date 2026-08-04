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
    """Return a JSON-safe float, or ``None`` for anything non-finite.

    ``NaN``, ``Infinity`` and ``-Infinity`` have no representation in strict
    JSON; Python's encoder emits the non-standard bare tokens ``NaN`` /
    ``Infinity`` unless told otherwise. Mapping them to ``null`` here means the
    document stays valid for every consumer, and the serializer can then run
    with ``allow_nan=False`` as a genuine assertion rather than a formality.
    """
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


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
        return value
    try:
        return json_number(value)
    except (TypeError, ValueError):
        return None


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
    source = getattr(snapshot, "source_path", None)
    suffix = Path(str(source)).suffix if source else ""
    route = LOAD_ROUTES.get(suffix)
    checks.append(Check(
        "source_loadable",
        route is not None,
        f"source is a {route} snapshot" if route is not None
        else (f"source suffix {suffix!r} is not a public load route "
              f"({', '.join(sorted(LOAD_ROUTES))})" if source
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
        else (f"lattice dtype is {lattice.dtype}, expected "
              f"{np.dtype(LATTICE_DTYPE).name}" if lattice_is_array
              else "lattice is not an array"),
    ))

    if lattice_is_array and lattice.size:
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
    elif lattice_is_array:
        states_ok, detail = True, "lattice is empty; no state ids to check"
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
        else (f"memory dtype is {memory.dtype}, expected "
              f"{np.dtype(MEMORY_DTYPE).name}" if memory_is_array
              else "memory grid is not an array"),
    ))

    if memory_is_array and memory.size:
        finite_mask = np.isfinite(memory)
        non_finite = int(memory.size - int(np.count_nonzero(finite_mask)))
        finite_ok = non_finite == 0
        detail = ("all memory values are finite" if finite_ok
                  else f"{non_finite} non-finite memory value(s)")
    elif memory_is_array:
        finite_ok, detail = True, "memory grid is empty; no values to check"
    else:
        finite_ok, detail = False, "memory grid is not an array"
    checks.append(Check("memory_values_finite", finite_ok, detail))

    for field in ("generation", "ca_step"):
        value = getattr(snapshot, field, None)
        ok = _is_exact_int(value) and value >= 0
        if _is_exact_int(value):
            detail = f"{field} is {value}" if ok else f"{field} is negative"
        else:
            detail = f"{field} is {type(value).__name__}, expected a non-negative int"
        checks.append(Check(f"{field}_non_negative_int", ok, detail))

    fitness = getattr(snapshot, "best_fitness", None)
    if _is_real_number(fitness):
        ok = math.isfinite(float(fitness))
        detail = "best_fitness is finite" if ok else "best_fitness is not finite"
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
    """
    lattice = snapshot.lattice
    shape = tuple(int(d) for d in lattice.shape)
    total_cells = 1
    for dim in shape:
        total_cells *= dim
    non_void_mask = lattice > 0

    state_counts = []
    for state_id in sorted(STATE_NAMES):
        count = int(np.sum(lattice == state_id))
        state_counts.append({
            "id": int(state_id),
            "name": STATE_NAMES[state_id],
            "count": count,
            "percent": json_number(count / total_cells * 100) if total_cells else None,
        })

    # A report must survive every input its own checks are designed to flag.
    # `memory_grid[i][non_void_mask]` raises IndexError when the grid's spatial
    # dimensions differ from the lattice, and again when the grid has fewer
    # than eight channels -- precisely the snapshots `memory_shape_matches_
    # lattice` exists to report. Without this gate, `doctor --json` died with a
    # traceback and emitted no document at all on exactly those files, while
    # human `doctor` reported them correctly.
    memory = getattr(snapshot, "memory_grid", None)
    channels_usable = (
        isinstance(memory, np.ndarray)
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

    return {
        "shape": list(shape),
        "total_cells": total_cells,
        "non_void_count": int(np.sum(non_void_mask)),
        "generation": json_scalar(snapshot.generation),
        "ca_step": json_scalar(snapshot.ca_step),
        "best_fitness": json_number(snapshot.best_fitness)
        if _is_real_number(snapshot.best_fitness) else None,
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
    """
    lines = [f"Snapshot: {source}", ""]
    width = max((len(c.name) for c in checks), default=0)
    for check in checks:
        mark = "PASS" if check.ok else "FAIL"
        lines.append(f"  [{mark}] {check.name:<{width}}  {check.detail}")
    counts = summarize(checks)
    lines.append("")
    if counts["failed"]:
        lines.append(
            f"FAILED: {counts['failed']} of {counts['total']} checks did not pass."
        )
    else:
        lines.append(f"OK: all {counts['total']} checks passed.")
    return lines
