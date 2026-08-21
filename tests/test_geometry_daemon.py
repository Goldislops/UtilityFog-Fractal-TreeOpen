"""Tests for `scripts/geometry_daemon.py` snapshot-archive resource lifetime.

Both snapshot load sites previously did `snap = np.load(..., allow_pickle=True)`
and then left the returned `NpzFile` referenced in the calling frame: through the
entire export stage in `run_daemon()`, and until process teardown on the
`--once` path. The archive's underlying file handle therefore stayed open far
longer than the extraction required, which on Windows can block cleanup,
rotation or replacement of that snapshot.

`_load_snapshot()` now bounds the archive's lifetime to the extraction itself and
closes it explicitly before returning — before any exporter runs.

Nothing here touches a real snapshot, engine, printer, STL generation or
long-running daemon: `np.load` is replaced at the module boundary with a fake
archive that records context entry/exit and closure, the three exporters are
recorders, and the clock is deterministic. No `.npz`, CSV, JSON, STL or PNG is
written outside pytest's own `tmp_path` (the pickle-refusal tests appended
at the end write real NPZ archives there), and the module's import-time
`GEO_DIR.mkdir(...)` is isolated
so the repository's real `data/geometry` directory is never created or modified.

Scope is `.npz` archive resource lifetime and object-member refusal — not
snapshot validation, whole-archive validation, deterministic export, atomic
output or whole-daemon correctness.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

# `scripts/geometry_daemon.py` runs `GEO_DIR.mkdir(parents=True, exist_ok=True)`
# at module scope. Patching Path.mkdir for the duration of the import keeps that
# side effect out of the repository; production directory configuration is
# unchanged.
with mock.patch.object(Path, "mkdir"):
    from scripts import geometry_daemon

# The bounded discovery primitive and its one calibrated production policy live
# in the guard, so a test that injects a directory population or pins the
# policy identity has to reach them there rather than through the consumer's
# imported names.
from scripts import snapshot_archive_guard  # noqa: E402


class Boom(Exception):
    """Distinct extraction failure, so propagation can be asserted exactly."""


class _ExplodingInt:
    """Materialises as a `generation` value whose int() conversion fails."""

    def __int__(self):
        raise Boom("generation conversion failed")


class _IntLike:
    """Proves the existing int(...) conversion is still applied."""

    def __int__(self):
        return 42


class _FakeArchive:
    """Stand-in for the `NpzFile` that `np.load` returns.

    Records context entry/exit, explicit closure and key lookups. Deliberately
    defines **no** `__del__`, so a recorded closure can never have come from
    garbage collection or finalisation.
    """

    def __init__(self, contents=None, raise_on=None):
        self.contents = {} if contents is None else contents
        self.raise_on = raise_on
        self.entered = 0
        self.exited = 0
        self.closed = 0
        self.lookups = []

    def __enter__(self):
        self.entered += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exited += 1
        self.close()
        return False  # never suppress an extraction failure

    def close(self):
        self.closed += 1

    def __getitem__(self, key):
        self.lookups.append(key)
        if self.raise_on == key:
            raise KeyError(key)
        return self.contents[key]


def _good_contents(generation=7):
    return {
        "lattice": object(),
        "memory_grid": object(),
        "generation": generation,
    }


_DESCRIPTOR = object()


class _FakeAdmission:
    """Stand-in for the shared guard.

    Records how it was called, hands back a sentinel descriptor, and records
    that its block was exited. Using a sentinel rather than a real file is what
    lets the lifetime tests below stay free of any archive on disk, while the
    real guard is exercised end to end by the hostile-archive tests.
    """

    def __init__(self):
        self.calls = []
        self.exited = 0

    def __call__(self, path, *, data_dir, policy=None):
        self.calls.append({"path": path, "data_dir": data_dir, "policy": policy})
        return self

    def __enter__(self):
        return _DESCRIPTOR

    def __exit__(self, exc_type, exc, tb):
        self.exited += 1
        return False  # never suppress anything


def _load_with(archive, path="/fake/v070_gen0001000.npz"):
    """Run the real `_load_snapshot` against `archive`.

    Returns (result, load mock, admission recorder).
    """
    loader = mock.Mock(return_value=archive)
    admission = _FakeAdmission()
    with mock.patch.object(geometry_daemon, "admit_snapshot", admission), \
         mock.patch.object(geometry_daemon.np, "load", loader):
        result = geometry_daemon._load_snapshot(path)
    return result, loader, admission


# -- helper contract ----------------------------------------------------------


def test_helper_returns_the_exact_extracted_objects():
    contents = _good_contents(generation=7)
    archive = _FakeArchive(contents)
    (state, memory_grid, generation), *_ = _load_with(archive)
    assert state is contents["lattice"]
    assert memory_grid is contents["memory_grid"]
    assert generation == 7
    assert type(generation) is int


def test_helper_preserves_the_int_generation_conversion():
    archive = _FakeArchive(_good_contents(generation=_IntLike()))
    (_, _, generation), *_ = _load_with(archive)
    assert generation == 42
    assert type(generation) is int


def test_helper_loads_from_the_admitted_descriptor_with_allow_pickle_false():
    """The path is handed to the guard; NumPy is handed the descriptor the
    guard opened. There is no second open and no `str(path)` conversion left
    to make, because a pathname is never re-resolved for loading."""
    archive = _FakeArchive(_good_contents())
    path = Path("/fake/dir/v070_gen42.npz")
    _, loader, admission = _load_with(archive, path=path)
    assert loader.call_count == 1
    args, kwargs = loader.call_args
    assert args == (_DESCRIPTOR,)
    assert kwargs == {"allow_pickle": False}
    assert [call["path"] for call in admission.calls] == [path]


def test_helper_admits_against_the_module_data_dir_and_named_policy():
    archive = _FakeArchive(_good_contents())
    _, _, admission = _load_with(archive)
    assert len(admission.calls) == 1
    assert admission.calls[0]["data_dir"] is geometry_daemon.DATA_DIR
    assert admission.calls[0]["policy"] is geometry_daemon.SNAPSHOT_POLICY
    assert admission.exited == 1


def test_admission_precedes_the_load():
    """Ordering, not merely presence: the guard must have decided before
    NumPy was asked for anything."""
    order = []
    archive = _FakeArchive(_good_contents())

    class _OrderedAdmission(_FakeAdmission):
        def __call__(self, path, *, data_dir, policy=None):
            order.append("admit")
            return super().__call__(path, data_dir=data_dir, policy=policy)

    def _ordered_load(*args, **kwargs):
        order.append("load")
        return archive

    with mock.patch.object(geometry_daemon, "admit_snapshot", _OrderedAdmission()), \
         mock.patch.object(geometry_daemon.np, "load", _ordered_load):
        geometry_daemon._load_snapshot("/fake/v070_gen1.npz")
    assert order == ["admit", "load"]


def test_helper_enters_the_archive_context_exactly_once():
    archive = _FakeArchive(_good_contents())
    _load_with(archive)
    assert archive.entered == 1


def test_helper_closes_the_archive_exactly_once_on_success():
    archive = _FakeArchive(_good_contents())
    _load_with(archive)
    assert archive.exited == 1
    assert archive.closed == 1


def test_archive_is_already_closed_when_the_helper_returns():
    """The assertion runs immediately after the return, while this frame still
    holds a live reference to the archive — so closure was explicit."""
    archive = _FakeArchive(_good_contents())
    (state, memory_grid, generation), *_ = _load_with(archive)
    assert archive.closed == 1
    assert state is not None and generation == 7


def test_closure_does_not_depend_on_finalisation():
    """No `__del__` exists on the fake and the reference stays alive, so a
    recorded closure cannot have come from garbage collection."""
    assert not hasattr(_FakeArchive, "__del__")
    archive = _FakeArchive(_good_contents())
    _load_with(archive)
    assert archive.closed == 1
    assert archive is not None  # still referenced here; nothing was finalised


def test_helper_extracts_every_required_key():
    archive = _FakeArchive(_good_contents())
    _load_with(archive)
    assert archive.lookups == ["lattice", "memory_grid", "generation"]


# -- closure on every extraction failure --------------------------------------


@pytest.mark.parametrize(
    "missing_key", ["lattice", "memory_grid", "generation"],
    ids=["lattice", "memory_grid", "generation"],
)
def test_archive_closes_when_a_key_lookup_raises(missing_key):
    archive = _FakeArchive(_good_contents(), raise_on=missing_key)
    with pytest.raises(KeyError):
        _load_with(archive)
    assert archive.exited == 1
    assert archive.closed == 1


def test_archive_closes_when_the_generation_conversion_raises():
    archive = _FakeArchive(_good_contents(generation=_ExplodingInt()))
    with pytest.raises(Boom):
        _load_with(archive)
    assert archive.exited == 1
    assert archive.closed == 1


def test_original_extraction_exception_propagates_unchanged():
    """Extraction failures are neither caught, translated nor suppressed."""
    archive = _FakeArchive(_good_contents(generation=_ExplodingInt()))
    with pytest.raises(Boom) as exc:
        _load_with(archive)
    assert type(exc.value) is Boom
    assert str(exc.value) == "generation conversion failed"
    assert archive.closed == 1

    missing = _FakeArchive(_good_contents(), raise_on="lattice")
    with pytest.raises(KeyError) as exc2:
        _load_with(missing)
    assert type(exc2.value) is KeyError
    assert missing.closed == 1


# -- one controlled daemon cycle ----------------------------------------------


class _FakeSnapshotPath:
    """A stand-in for one snapshot path that is also a REAL directory entry.

    It used to be a pure duck type: `.stat()`, `.name`, `__str__` and nothing
    else. That worked while discovery sorted on `p.stat().st_mtime`, which
    accepts any object with a `.stat()`. Discovery now describes candidates
    with `os.lstat`, which takes only `str | bytes | os.PathLike` -- deliberately,
    because reading the ENTRY rather than whatever it points at is the whole
    point of the non-following ordering.

    So the fake owns a real, tiny file and forwards `__fspath__` to it. That
    keeps the double honest in both directions: `os.lstat` returns real
    metadata, and `change()` rewrites the real file rather than a fabricated
    stat result, so the daemon's fingerprint sees a genuine change.

    Backing this with a fabricated `.stat()` instead would have been worse than
    useless: `os.lstat` on a path that does not exist raises `OSError`,
    `newest_first` skips it, and every daemon-cycle test would pass while
    exercising nothing.
    """

    def __init__(self, directory, name="v070_gen0001000.npz", size=64,
                 mtime=100.0):
        self.name = name
        self._real = Path(directory) / name
        self._real.write_bytes(b"\x00" * size)
        self._set_mtime(mtime)

    def _set_mtime(self, mtime):
        stamp = int(mtime * 1_000_000_000)
        os.utime(self._real, ns=(stamp, stamp))

    def stat(self):
        return self._real.stat()

    def change(self, size=None, mtime=None):
        """Replace the file at this path, as a rotating producer would."""
        if size is not None:
            self._real.write_bytes(b"\x00" * size)
        if mtime is not None:
            self._set_mtime(mtime)
        return self

    def __fspath__(self):
        return os.fspath(self._real)

    def __str__(self):
        return os.fspath(self._real)


class _FakeDataDir:
    """A stand-in data directory that is also a REAL one.

    It used to expose `glob()` and nothing else, which was enough while the
    daemon only globbed it. `DATA_DIR` is now handed to `admit_snapshot` as the
    confinement root by the bounded admission search, and to bounded discovery
    as the directory to scan — both of which resolve it as a path, so a
    `glob`-only duck type made the search raise `TypeError` into the daemon's
    broad handler and no cycle ran at all.

    So it forwards `__fspath__` to the real directory the fake snapshots were
    written into, which is what confinement should be comparing against
    anyway.

    `glob()` survives as a TRIPWIRE rather than as a collaborator: production
    no longer calls it, and `globs` staying empty is what proves that.
    """

    def __init__(self, paths, directory=None):
        self.paths = list(paths)
        self.globs = []
        if directory is None and self.paths:
            directory = Path(os.fspath(self.paths[0])).parent
        self._directory = Path(directory) if directory is not None else Path(".")

    def glob(self, pattern):
        self.globs.append(pattern)
        return list(self.paths)

    def __fspath__(self):
        return os.fspath(self._directory)


class _FakeClock:
    """Deterministic clock whose sleep ends the daemon loop."""

    def __init__(self, stop_after_sleeps=1, now=10_000.0):
        self.stop_after = stop_after_sleeps
        self.now = now
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        if len(self.sleeps) >= self.stop_after:
            raise KeyboardInterrupt


def _run_one_daemon_cycle(archive, tmp_path):
    """Drive the real `run_daemon()` for one cycle; return the recorded calls.

    Every exporter records the archive's closure count at the moment it is
    invoked, which is what makes the ordering guarantee observable.
    """
    calls = []

    def _recorder(name):
        def _record(*args):
            calls.append({"exporter": name, "closed_at_call": archive.closed,
                          "args": args})
            return None
        return _record

    snapshot = _FakeSnapshotPath(tmp_path)
    data_dir = _FakeDataDir([snapshot])
    clock = _FakeClock(stop_after_sleeps=1)
    loader = mock.Mock(return_value=archive)

    with mock.patch.object(geometry_daemon, "admit_snapshot", _FakeAdmission()), \
         mock.patch.object(geometry_daemon.np, "load", loader), \
         mock.patch.object(geometry_daemon, "DATA_DIR", data_dir), \
         mock.patch.object(geometry_daemon, "GEO_DIR", tmp_path), \
         mock.patch.object(geometry_daemon, "time", clock), \
         mock.patch.object(geometry_daemon, "export_sage_pointcloud",
                           _recorder("csv")), \
         mock.patch.object(geometry_daemon, "export_voxel_summary",
                           _recorder("json")), \
         mock.patch.object(geometry_daemon, "export_stl", _recorder("stl")):
        try:
            geometry_daemon.run_daemon()
        except KeyboardInterrupt:
            pass  # the trailing sleep sits outside the loop's try block
    return calls, loader, snapshot


def test_daemon_cycle_closes_the_archive_before_the_first_exporter(tmp_path):
    """Central witness. Pre-fix the archive was still open here: every exporter
    saw closed == 0, because the handle was held for the whole export stage."""
    contents = _good_contents(generation=1000)
    archive = _FakeArchive(contents)
    calls, _, _ = _run_one_daemon_cycle(archive, tmp_path)
    assert [c["exporter"] for c in calls] == ["csv", "json", "stl"]
    assert calls[0]["closed_at_call"] == 1, "archive must be closed before export"
    for call in calls:
        assert call["closed_at_call"] == 1
    assert archive.entered == 1
    assert archive.exited == 1
    assert archive.closed == 1


def test_daemon_cycle_preserves_exporter_order(tmp_path):
    archive = _FakeArchive(_good_contents(generation=1000))
    calls, _, _ = _run_one_daemon_cycle(archive, tmp_path)
    assert [c["exporter"] for c in calls] == ["csv", "json", "stl"]


def test_daemon_cycle_passes_the_same_objects_to_every_exporter(tmp_path):
    contents = _good_contents(generation=1000)
    archive = _FakeArchive(contents)
    calls, _, _ = _run_one_daemon_cycle(archive, tmp_path)
    by_name = {c["exporter"]: c["args"] for c in calls}
    # export_sage_pointcloud(state, memory_grid, gen, output_dir)
    assert by_name["csv"][0] is contents["lattice"]
    assert by_name["csv"][1] is contents["memory_grid"]
    assert by_name["csv"][2] == 1000
    assert by_name["csv"][3] == tmp_path
    # export_voxel_summary(state, memory_grid, gen, output_dir)
    assert by_name["json"][:3] == by_name["csv"][:3]
    # export_stl(state, gen, output_dir)
    assert by_name["stl"][0] is contents["lattice"]
    assert by_name["stl"][1] == 1000
    assert by_name["stl"][2] == tmp_path


def test_daemon_cycle_loads_from_the_admitted_descriptor(tmp_path):
    archive = _FakeArchive(_good_contents(generation=1000))
    _, loader, _snapshot = _run_one_daemon_cycle(archive, tmp_path)
    assert loader.call_count == 1
    args, kwargs = loader.call_args
    assert args == (_DESCRIPTOR,)
    assert kwargs == {"allow_pickle": False}


def test_daemon_cycle_discovers_under_the_calibrated_caps(tmp_path):
    """Its predecessor asserted the daemon called `DATA_DIR.glob("v070_gen*
    .npz")`. That call site is exactly what this tranche removes: by the time a
    glob hands anything back, the whole directory has already been
    materialised, so nothing downstream can bound the work.

    The name matching is unchanged and lives in the primitive, which pins it
    against `Path.glob` on whichever platform it runs on. What the daemon must
    now prove is that it hands the discovery its calibrated caps.
    """
    archive = _FakeArchive(_good_contents(generation=1000))
    snapshot = _FakeSnapshotPath(tmp_path)
    data_dir = _FakeDataDir([snapshot])
    clock = _FakeClock(stop_after_sleeps=1)
    policies = []
    real_discover = geometry_daemon.discover_snapshot_candidates

    def _recording_discover(directory, *, policy):
        policies.append(policy)
        return real_discover(directory, policy=policy)

    with mock.patch.object(geometry_daemon, "admit_snapshot", _FakeAdmission()), \
         mock.patch.object(geometry_daemon.np, "load",
                           mock.Mock(return_value=archive)), \
         mock.patch.object(geometry_daemon, "discover_snapshot_candidates",
                           _recording_discover), \
         mock.patch.object(geometry_daemon, "DATA_DIR", data_dir), \
         mock.patch.object(geometry_daemon, "GEO_DIR", tmp_path), \
         mock.patch.object(geometry_daemon, "time", clock), \
         mock.patch.object(geometry_daemon, "export_sage_pointcloud",
                           lambda *a: None), \
         mock.patch.object(geometry_daemon, "export_voxel_summary",
                           lambda *a: None), \
         mock.patch.object(geometry_daemon, "export_stl", lambda *a: None):
        try:
            geometry_daemon.run_daemon()
        except KeyboardInterrupt:
            pass
    assert policies == [snapshot_archive_guard.PRODUCTION_DISCOVERY_POLICY]
    assert data_dir.globs == [], "the daemon still globbed the data directory"


def test_a_small_but_valid_snapshot_is_no_longer_skipped(tmp_path):
    """The one-megabyte minimum is gone.

    It was a guess at "tiny/corrupt" and it was wrong in both directions: a
    sparse but structurally valid snapshot compresses far below a megabyte and
    was skipped for ever, while a hostile archive only had to be padded past
    the threshold to be processed. Admission decides usability now, so a
    valid 40 kB snapshot must be loaded.
    """
    archive = _FakeArchive(_good_contents(generation=7))
    loader = mock.Mock(return_value=archive)
    data_dir = _FakeDataDir([_FakeSnapshotPath(tmp_path, size=40_000)])
    with mock.patch.object(geometry_daemon, "admit_snapshot", _FakeAdmission()), \
         mock.patch.object(geometry_daemon.np, "load", loader), \
         mock.patch.object(geometry_daemon, "DATA_DIR", data_dir), \
         mock.patch.object(geometry_daemon, "GEO_DIR", tmp_path), \
         mock.patch.object(geometry_daemon, "export_sage_pointcloud",
                           lambda *a: None), \
         mock.patch.object(geometry_daemon, "export_voxel_summary",
                           lambda *a: None), \
         mock.patch.object(geometry_daemon, "export_stl", lambda *a: None), \
         mock.patch.object(geometry_daemon, "time", _FakeClock(stop_after_sleeps=1)):
        try:
            geometry_daemon.run_daemon()
        except KeyboardInterrupt:
            pass
    assert loader.call_count == 1
    assert archive.entered == 1


def _run_rejecting_daemon(tmp_path, snapshot, refusals, sleeps=1):
    """Drive `run_daemon()` with an admission that refuses `refusals` times.

    Returns (exporter calls, printed output lines, admission attempt count).
    """
    attempts = []

    class _RefusingAdmission:
        def __call__(self, path, *, data_dir, policy=None):
            attempts.append(str(path))
            if len(attempts) <= refusals:
                raise geometry_daemon.SnapshotArchiveRejected("member_missing")
            return self

        def __enter__(self):
            return _DESCRIPTOR

        def __exit__(self, *exc):
            return False

    calls = []
    data_dir = _FakeDataDir([snapshot])
    clock = _FakeClock(stop_after_sleeps=sleeps)
    archive = _FakeArchive(_good_contents())

    def _recorder(name):
        def _record(*args):
            calls.append(name)
            return None
        return _record

    with mock.patch.object(geometry_daemon, "admit_snapshot", _RefusingAdmission()), \
         mock.patch.object(geometry_daemon.np, "load",
                           mock.Mock(return_value=archive)), \
         mock.patch.object(geometry_daemon, "DATA_DIR", data_dir), \
         mock.patch.object(geometry_daemon, "GEO_DIR", tmp_path), \
         mock.patch.object(geometry_daemon, "time", clock), \
         mock.patch.object(geometry_daemon, "export_sage_pointcloud",
                           _recorder("csv")), \
         mock.patch.object(geometry_daemon, "export_voxel_summary",
                           _recorder("json")), \
         mock.patch.object(geometry_daemon, "export_stl", _recorder("stl")):
        try:
            geometry_daemon.run_daemon()
        except KeyboardInterrupt:
            pass
    return calls, attempts


def test_a_rejected_snapshot_runs_no_exporter_and_leaves_the_daemon_alive(
    tmp_path, capsys
):
    snapshot = _FakeSnapshotPath(tmp_path)
    calls, attempts = _run_rejecting_daemon(tmp_path, snapshot, refusals=1)
    output = capsys.readouterr().out
    assert calls == [], "an exporter ran on a rejected snapshot"
    assert attempts == [str(snapshot)]
    assert "Snapshot rejected: member_missing" in output
    # The daemon reached its sleep, which is how this loop is stopped at all.
    assert output.count("Snapshot rejected") == 1


def test_a_rejection_never_logs_the_archive_name(tmp_path, capsys):
    snapshot = _FakeSnapshotPath(tmp_path, name="v070_gen_LEAKNAME_0001.npz")
    _run_rejecting_daemon(tmp_path, snapshot, refusals=1)
    output = capsys.readouterr().out
    assert "LEAKNAME" not in output, (
        "the daemon logged a rejected archive's chosen name")


def test_an_unchanged_rejected_snapshot_is_not_reprocessed(tmp_path, capsys):
    """Fingerprint memory: repeated polls over a poisoned directory must not
    repeat the preflight or repeat the log."""
    snapshot = _FakeSnapshotPath(tmp_path)
    calls, attempts = _run_rejecting_daemon(tmp_path, snapshot, refusals=5,
                                            sleeps=4)
    output = capsys.readouterr().out
    assert calls == []
    assert attempts == [str(snapshot)], "the rejected archive was re-preflighted"
    assert output.count("Snapshot rejected") == 1


def test_a_changed_snapshot_at_the_same_path_is_retried(tmp_path):
    """A rotated or replaced file differs in size or mtime, so the memory must
    not lock the daemon out of a subsequently valid snapshot."""
    snapshot = _FakeSnapshotPath(tmp_path)
    attempts = []
    calls = []

    class _RefuseThenAccept:
        def __call__(self, path, *, data_dir, policy=None):
            attempts.append(snapshot.stat().st_mtime_ns)
            if len(attempts) == 1:
                raise geometry_daemon.SnapshotArchiveRejected("member_missing")
            return self

        def __enter__(self):
            return _DESCRIPTOR

        def __exit__(self, *exc):
            return False

    class _ChangingClock(_FakeClock):
        def sleep(self, seconds):
            snapshot.change(mtime=self.now + len(self.sleeps) + 1)
            super().sleep(seconds)

    data_dir = _FakeDataDir([snapshot])
    with mock.patch.object(geometry_daemon, "admit_snapshot", _RefuseThenAccept()), \
         mock.patch.object(geometry_daemon.np, "load",
                           mock.Mock(return_value=_FakeArchive(_good_contents()))), \
         mock.patch.object(geometry_daemon, "DATA_DIR", data_dir), \
         mock.patch.object(geometry_daemon, "GEO_DIR", tmp_path), \
         mock.patch.object(geometry_daemon, "time",
                           _ChangingClock(stop_after_sleeps=2)), \
         mock.patch.object(geometry_daemon, "export_sage_pointcloud",
                           lambda *a: calls.append("csv")), \
         mock.patch.object(geometry_daemon, "export_voxel_summary",
                           lambda *a: calls.append("json")), \
         mock.patch.object(geometry_daemon, "export_stl",
                           lambda *a: calls.append("stl")):
        try:
            geometry_daemon.run_daemon()
        except KeyboardInterrupt:
            pass

    assert len(attempts) == 2, "the changed snapshot was never retried"
    assert calls == ["csv", "json", "stl"], "the retry did not export"


# -- both load sites use the helper -------------------------------------------


def _module_tree():
    source = Path(geometry_daemon.__file__).read_text(encoding="utf-8")
    return ast.parse(source)


def _np_load_calls(node):
    found = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if (isinstance(func, ast.Attribute) and func.attr == "load"
                and isinstance(func.value, ast.Name) and func.value.id == "np"):
            found.append(sub)
    return found


def _helper_calls(node):
    return [
        sub for sub in ast.walk(node)
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
        and sub.func.id == "_load_snapshot"
    ]


def test_module_has_exactly_one_np_load_and_it_is_inside_the_helper():
    """No second direct archive open survives anywhere in the module."""
    tree = _module_tree()
    helper = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_load_snapshot"
    )
    assert len(_np_load_calls(helper)) == 1
    assert len(_np_load_calls(tree)) == 1  # module-wide: only the helper's


def test_daemon_path_uses_the_helper():
    tree = _module_tree()
    daemon = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_daemon"
    )
    assert len(_helper_calls(daemon)) == 1
    assert _np_load_calls(daemon) == []


def test_once_path_uses_the_helper():
    """The `--once` production path calls the closing helper, not a second load."""
    tree = _module_tree()
    once = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_once"
    )
    assert len(_helper_calls(once)) == 1
    assert _np_load_calls(once) == []


def test_the_main_block_delegates_to_the_two_named_entry_points():
    """`run_once` is the real `--once` path, not a paraphrase of it: the
    `__main__` block calls it and does no snapshot work of its own."""
    tree = _module_tree()
    main_blocks = [
        node for node in tree.body
        if isinstance(node, ast.If) and any(
            isinstance(sub, ast.Name) and sub.id == "__name__"
            for sub in ast.walk(node.test)
        )
    ]
    assert len(main_blocks) == 1
    main_block = main_blocks[0]
    called = {
        node.func.id for node in ast.walk(main_block)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert {"run_once", "run_daemon"} <= called
    assert _helper_calls(main_block) == []
    assert _np_load_calls(main_block) == []


# ===========================================================================
# Pickle refusal -- geometry_daemon must never unpickle an NPZ member
#
# An object-dtype member is stored as a pickle, so loading one with pickle
# enabled is arbitrary code execution by construction. The payload below is
# harmless: its reduction writes ONE marker file inside pytest's own tmp_path
# and returns. `__reduce__` runs at PICKLE time and only records the callable,
# so writing the archive is inert; the call would happen at UNPICKLE time.
#
# Scope: an object-member refusal, NOT whole-archive validation.
# ===========================================================================

_GD_MARKER = "GEOMETRY_PAYLOAD_EXECUTED"


def _create_marker_gd(directory: str) -> str:
    """Stand in for a malicious payload; deliberately inert.

    Module scope is required -- pickle stores a module-qualified reference, so
    a function defined inside a test body could not be resolved at load time.
    """
    marker = Path(directory) / _GD_MARKER
    marker.write_text("payload executed", encoding="utf-8")
    return str(marker)


class _PayloadGd:
    """Its reduction calls the marker writer when unpickled."""

    def __init__(self, directory):
        self._directory = str(directory)

    def __reduce__(self):
        return (_create_marker_gd, (self._directory,))


def _payload_array_gd(directory):
    return np.array([_PayloadGd(directory)], dtype=object)


def _marker_gd(tmp_path):
    return tmp_path / _GD_MARKER


def _write_snapshot_gd(path, compressed=False, **members):
    """A real NPZ. Object members pickle on the way in, which is harmless.

    The edge is 16 and all five schema members are present, because the
    archive now has to be ADMISSIBLE before its member dtypes matter: a 2-cube
    with three members would be refused for its shape and its membership, and
    the pickle property below would never be reached.
    """
    payload = {
        "lattice": np.zeros((16, 16, 16), dtype=np.uint8),
        "memory_grid": np.zeros((8, 16, 16, 16), dtype=np.float32),
        "generation": 7,
        "ca_step": 11,
        "best_fitness": 0.5,
    }
    payload.update(members)
    writer = np.savez_compressed if compressed else np.savez
    writer(path, **payload)
    return str(path)


@pytest.fixture
def confined(tmp_path, monkeypatch):
    """Point the daemon's data directory at pytest's own tmp_path.

    Admission confines the archive to the configured data directory, so a
    fixture written anywhere else is refused for CONTAINMENT before the
    property under test is reached.
    """
    monkeypatch.setattr(geometry_daemon, "DATA_DIR", tmp_path)
    return tmp_path


def test_gd_payload_fixture_actually_fires_when_pickle_is_enabled(tmp_path):
    """Control. Without it, every "marker is absent" assertion below could
    pass against a payload that never worked. Pickle is enabled here and in the
    compressed-archive control below, and nowhere else in this module."""
    archive = _write_snapshot_gd(
        tmp_path / "control.npz", lattice=_payload_array_gd(tmp_path)
    )
    assert not _marker_gd(tmp_path).exists()

    with np.load(archive, allow_pickle=True) as snap:
        snap["lattice"]

    assert _marker_gd(tmp_path).exists(), "the payload fixture is inert; fix it"


@pytest.mark.parametrize("field", ["lattice", "memory_grid", "generation"])
def test_object_payload_is_refused_by_the_helper(confined, field):
    """The refusal moved EARLIER, and the code says so.

    An object member used to be caught by NumPy at `np.load`. It is now caught
    by admission from the member's NPY header, before NumPy is involved at
    all -- so the assertion is the typed reason code, not NumPy's message. The
    property that matters is unchanged and stronger: the payload never runs.
    """
    archive = _write_snapshot_gd(
        confined / f"v070_{field}.npz", **{field: _payload_array_gd(confined)}
    )
    with pytest.raises(geometry_daemon.SnapshotArchiveRejected) as excinfo:
        geometry_daemon._load_snapshot(archive)
    assert excinfo.value.reason == "member_dtype_object"
    assert not _marker_gd(confined).exists(), "the pickle payload executed"


def test_numpys_own_pickle_refusal_is_still_in_place_behind_admission(confined):
    """Second line of defence, kept non-vacuous.

    Admission now stops an object member first, so the load-site refusal would
    otherwise never be observed again. Calling NumPy directly on the same
    archive shows it is still exactly as it was.
    """
    archive = _write_snapshot_gd(
        confined / "v070_direct.npz", lattice=_payload_array_gd(confined)
    )
    with pytest.raises(ValueError) as excinfo:
        with np.load(archive, allow_pickle=False) as snap:
            snap["lattice"]
    assert "allow_pickle=False" in str(excinfo.value)
    assert not _marker_gd(confined).exists()


def test_a_compressed_hostile_archive_is_refused_the_same_way(confined):
    """Real producers use `np.savez_compressed`, so the hostile fixture
    exercises that shape too rather than only the uncompressed one."""
    archive = _write_snapshot_gd(
        confined / "v070_compressed.npz", compressed=True,
        lattice=_payload_array_gd(confined),
    )
    with pytest.raises(geometry_daemon.SnapshotArchiveRejected) as excinfo:
        geometry_daemon._load_snapshot(archive)
    assert excinfo.value.reason == "member_dtype_object"
    assert not _marker_gd(confined).exists()


def test_the_compressed_payload_also_fires_when_pickle_is_enabled(tmp_path):
    archive = _write_snapshot_gd(
        tmp_path / "cc.npz", compressed=True,
        lattice=_payload_array_gd(tmp_path),
    )
    with np.load(archive, allow_pickle=True) as snap:
        snap["lattice"]
    assert _marker_gd(tmp_path).exists(), "the compressed payload is inert"


def test_a_refused_archive_never_reaches_np_load_at_all(confined, monkeypatch):
    """Stronger than "it was not retried with pickle enabled": NumPy is not
    asked to open the archive even once."""
    archive = _write_snapshot_gd(
        confined / "v070_retry.npz", lattice=_payload_array_gd(confined)
    )
    real_load = np.load
    calls = []

    def _recording_load(*args, **kwargs):
        calls.append(kwargs.get("allow_pickle"))
        return real_load(*args, **kwargs)

    monkeypatch.setattr(geometry_daemon.np, "load", _recording_load)
    with pytest.raises(geometry_daemon.SnapshotArchiveRejected):
        geometry_daemon._load_snapshot(archive)
    assert calls == []


def test_a_valid_archive_is_loaded_with_pickle_explicitly_disabled(confined,
                                                                   monkeypatch):
    """The counterpart control: on the admitted path the explicit literal is
    still what NumPy receives, so the assertion above is about ordering rather
    than about the flag having quietly disappeared."""
    archive = _write_snapshot_gd(confined / "v070_ok.npz", compressed=True)
    real_load = np.load
    calls = []

    def _recording_load(*args, **kwargs):
        calls.append(kwargs.get("allow_pickle"))
        return real_load(*args, **kwargs)

    monkeypatch.setattr(geometry_daemon.np, "load", _recording_load)
    geometry_daemon._load_snapshot(archive)
    assert calls == [False]


def test_the_descriptor_is_closed_after_a_refusal(confined, monkeypatch):
    """Closure on the exceptional path, witnessed on the real file object the
    guard opened rather than on a NumPy handle that is never created."""
    archive = _write_snapshot_gd(
        confined / "v070_closed.npz", lattice=_payload_array_gd(confined)
    )
    # Hooked on `os.fdopen`, not `builtins.open`: the guard opens through
    # `os.open` so it can pass O_NONBLOCK and O_NOFOLLOW, and `os.fdopen` is
    # what turns that descriptor into the file object it yields.
    import os as _os
    opened = []
    real_fdopen = _os.fdopen

    def _tracking_fdopen(*args, **kwargs):
        handle = real_fdopen(*args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(_os, "fdopen", _tracking_fdopen)
    with pytest.raises(geometry_daemon.SnapshotArchiveRejected):
        geometry_daemon._load_snapshot(archive)
    assert len(opened) == 1, "the archive was opened more than once, or not at all"
    assert opened[0].closed


def test_discovery_skips_a_candidate_that_disappears_mid_scan(confined,
                                                              monkeypatch,
                                                              capsys):
    """Enumeration and the metadata read are separate syscalls. A vanished
    entry must be counted and skipped silently — the old `p.stat()` raised into
    the loop's broad handler, which prints the exception, and OSError's message
    carries the attacker-chosen path."""
    _write_snapshot_gd(confined / "v070_gen000030.npz", compressed=True)
    monkeypatch.setattr(snapshot_archive_guard.os, "scandir",
                        _GeoScandir(["v070_gen_GHOSTNAME_0031.npz"]))
    monkeypatch.setattr(geometry_daemon, "GEO_DIR", confined)
    exporters = []
    for name in ("export_sage_pointcloud", "export_voxel_summary", "export_stl"):
        monkeypatch.setattr(geometry_daemon, name,
                            lambda *a, _n=name: exporters.append(_n))

    geometry_daemon.run_once()

    output = capsys.readouterr()
    assert exporters == ["export_sage_pointcloud", "export_voxel_summary",
                         "export_stl"], "the ghost blocked a valid snapshot"
    assert "GHOSTNAME" not in output.out and "GHOSTNAME" not in output.err


def test_the_fingerprint_does_not_follow_a_symlink(confined, tmp_path):
    """A rejected link fingerprinted by its TARGET kept changing whenever
    anything touched the target, so the daemon re-preflighted and re-logged the
    same unchanged poison on every poll."""
    target = tmp_path / "fingerprint_target.npz"
    target.write_bytes(b"x" * 64)
    link = confined / "v070_fplink.npz"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):  # pragma: no cover - platform gate
        pytest.skip("symlink creation is not permitted in this environment")

    before = geometry_daemon._snapshot_fingerprint(link)
    target.write_bytes(b"y" * 4096)  # the target changes; the link does not
    after = geometry_daemon._snapshot_fingerprint(link)
    assert before == after, "the fingerprint tracked the target, not the entry"


def test_a_numeric_snapshot_still_loads_unchanged(confined):
    archive = _write_snapshot_gd(confined / "v070_clean.npz",
                                 generation=np.int64(12))
    state, grid, generation = geometry_daemon._load_snapshot(archive)
    assert state.shape == (16, 16, 16)
    assert grid.shape == (8, 16, 16, 16)
    assert generation == 12 and type(generation) is int


def test_the_once_path_exits_nonzero_with_one_bounded_reason(confined, capsys,
                                                             monkeypatch):
    """`--once` has no loop to stay alive in: it reports and fails.

    The REAL `run_once` runs here, with only admission replaced.
    """
    _write_snapshot_gd(confined / "v070_gen000once.npz")
    exporters = []
    monkeypatch.setattr(geometry_daemon, "GEO_DIR", confined)
    for name in ("export_sage_pointcloud", "export_voxel_summary", "export_stl"):
        monkeypatch.setattr(geometry_daemon, name,
                            lambda *a, _n=name: exporters.append(_n))

    def _refuse(path, *, data_dir, policy=None):
        raise geometry_daemon.SnapshotArchiveRejected("member_missing")

    monkeypatch.setattr(geometry_daemon, "admit_snapshot", _refuse)

    with pytest.raises(SystemExit) as excinfo:
        geometry_daemon.run_once()

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.strip() == "Snapshot rejected: member_missing"
    assert "v070_gen000once" not in captured.err
    assert "v070_gen000once" not in captured.out
    assert exporters == [], "an exporter ran on a rejected snapshot"


@pytest.mark.parametrize("raised", [
    MemoryError("oom"),
    KeyboardInterrupt(),
    RuntimeError("programmer error"),
    TypeError("wrong argument"),
], ids=["memory", "keyboard_interrupt", "runtime", "type"])
def test_the_once_path_lets_everything_but_a_refusal_propagate(confined,
                                                               monkeypatch,
                                                               raised):
    """Only `SnapshotArchiveRejected` becomes the bounded exit-1 refusal.

    A `MemoryError` means the machine is out of memory, a `KeyboardInterrupt`
    means the operator asked to stop, and a programmer error means the code is
    wrong. Reporting any of them as "the snapshot was bad" would hide a real
    fault behind a sanitized message and exit 1 as though the input were at
    fault. Each must leave `run_once` exactly as it was raised, and no exporter
    may run.
    """
    _write_snapshot_gd(confined / "v070_gen000prop.npz")
    exporters = []
    monkeypatch.setattr(geometry_daemon, "GEO_DIR", confined)
    for name in ("export_sage_pointcloud", "export_voxel_summary", "export_stl"):
        monkeypatch.setattr(geometry_daemon, name,
                            lambda *a, _n=name: exporters.append(_n))

    def _raise(path, *, data_dir, policy=None):
        raise raised

    monkeypatch.setattr(geometry_daemon, "admit_snapshot", _raise)

    with pytest.raises(type(raised)) as excinfo:
        geometry_daemon.run_once()

    assert type(excinfo.value) is type(raised)
    assert str(excinfo.value) == str(raised)
    assert not isinstance(excinfo.value, SystemExit), (
        "a non-refusal was converted into the bounded exit-1 lane")
    assert exporters == []


def test_the_daemon_loop_does_not_treat_a_programmer_error_as_a_refusal(
    tmp_path, capsys
):
    """The watcher's broad handler still catches non-refusals so the daemon
    survives — but it must not record them as rejected snapshots, or the
    fingerprint memory would suppress a real, recurring fault."""
    snapshot = _FakeSnapshotPath(tmp_path)
    data_dir = _FakeDataDir([snapshot])

    class _Boom(RuntimeError):
        pass

    def _raise(path, *, data_dir, policy=None):
        raise _Boom("programmer error")

    with mock.patch.object(geometry_daemon, "admit_snapshot", _raise), \
         mock.patch.object(geometry_daemon, "DATA_DIR", data_dir), \
         mock.patch.object(geometry_daemon, "GEO_DIR", tmp_path), \
         mock.patch.object(geometry_daemon, "time",
                           _FakeClock(stop_after_sleeps=1)):
        try:
            geometry_daemon.run_daemon()
        except KeyboardInterrupt:
            pass

    output = capsys.readouterr().out
    assert "Snapshot rejected" not in output, (
        "a programmer error was reported as a snapshot refusal")


def test_the_once_path_falls_back_past_an_unusable_newest_snapshot(confined,
                                                                    capsys,
                                                                    monkeypatch):
    """One unusable archive with the newest mtime must not stall exports.

    The producer writes straight to its final path with no
    temporary-and-rename, so a partially written snapshot IS the newest file
    for as long as the write takes.
    """
    good = Path(_write_snapshot_gd(confined / "v070_gen000001.npz",
                                   compressed=True))
    poison = Path(_hostile_gd("missing_member", confined / "v070_gen000002.npz"))
    os.utime(good, (1_000_000, 1_000_000))
    os.utime(poison, (2_000_000, 2_000_000))

    exporters = []
    monkeypatch.setattr(geometry_daemon, "GEO_DIR", confined)
    for name in ("export_sage_pointcloud", "export_voxel_summary", "export_stl"):
        monkeypatch.setattr(geometry_daemon, name,
                            lambda *a, _n=name: exporters.append(_n))

    geometry_daemon.run_once()

    assert exporters == ["export_sage_pointcloud", "export_voxel_summary",
                         "export_stl"], "the poison archive stalled the export"
    assert "Done!" in capsys.readouterr().out


def test_the_once_path_distinguishes_unreadable_candidates_from_none(confined,
                                                                     capsys,
                                                                     monkeypatch):
    """`[]` means two very different things and must not be reported alike.

    An empty directory is "nothing to export"; a directory whose every
    candidate failed its metadata read is a fault, and a wrapper checking the
    exit status has to be able to tell them apart.
    """
    ghosts = ["v070_gen_LEAKNAME_%d.npz" % index for index in range(4)]
    monkeypatch.setattr(snapshot_archive_guard.os, "scandir",
                        _GeoScandir(ghosts, include_real=False))
    exporters = []
    monkeypatch.setattr(geometry_daemon, "GEO_DIR", confined)
    for name in ("export_sage_pointcloud", "export_voxel_summary", "export_stl"):
        monkeypatch.setattr(geometry_daemon, name,
                            lambda *a, _n=name: exporters.append(_n))

    with pytest.raises(SystemExit) as excinfo:
        geometry_daemon.run_once()

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.strip() == "Snapshot candidates unreadable"
    assert "LEAKNAME" not in captured.err and "LEAKNAME" not in captured.out
    assert "No snapshots found" not in captured.out
    assert exporters == []


def test_the_once_path_still_reports_a_genuinely_empty_directory(confined,
                                                                 capsys):
    """The counterpart: no candidates at all is not a fault, and must not
    become one."""
    geometry_daemon.run_once()
    captured = capsys.readouterr()
    assert "No snapshots found!" in captured.out
    assert captured.err == ""


def test_the_once_path_still_exports_a_valid_snapshot(confined, capsys,
                                                      monkeypatch):
    """The counterpart control, so the test above is about the REFUSAL and not
    about `run_once` being broken."""
    _write_snapshot_gd(confined / "v070_gen000ok.npz", compressed=True)
    exporters = []
    monkeypatch.setattr(geometry_daemon, "GEO_DIR", confined)
    for name in ("export_sage_pointcloud", "export_voxel_summary", "export_stl"):
        monkeypatch.setattr(geometry_daemon, name,
                            lambda *a, _n=name: exporters.append(_n) or None)

    geometry_daemon.run_once()

    assert exporters == ["export_sage_pointcloud", "export_voxel_summary",
                         "export_stl"]
    assert "Done!" in capsys.readouterr().out


# ===========================================================================
# Structural admission -- a hostile archive must be refused BEFORE np.load
#
# Pickle refusal and archive lifetime say nothing about an archive's shape or
# its cost. This daemon loads whatever appears in the watched directory, so an
# archive can still name members outside the schema, carry traversal-bearing
# entries, declare a payload of hundreds of gigabytes, or lie about its own
# sizes -- and every one of those reached `np.load` and the allocation behind
# it.
#
# The fixtures below are built with the standard library rather than NumPy,
# because NumPy cannot write a duplicate member, a corrupt NPY magic or a
# lying shape. None of them is hostile in SIZE: each is a few hundred kilobytes at most, and
# the oversized cases lie in their headers instead of on disk.
# ===========================================================================

import struct  # noqa: E402
import warnings  # noqa: E402
import zipfile  # noqa: E402

_NPY_MAGIC = b"\x93NUMPY"


def _npy_gd(descr, shape, *, fortran=False, payload=None, header=None,
            version=(1, 0)):
    """One `.npy` member as raw bytes, with every field independently forgeable."""
    if header is None:
        if not shape:
            shape_text = "()"
        elif len(shape) == 1:
            shape_text = "(%d,)" % shape[0]
        else:
            shape_text = "(" + ", ".join(str(d) for d in shape) + ")"
        header = "{'descr': '%s', 'fortran_order': %s, 'shape': %s, }" % (
            descr, fortran, shape_text)
    body = header.encode("latin1")
    prelude = 10 if version == (1, 0) else 12
    body += b" " * ((-(prelude + len(body) + 1)) % 64) + b"\n"
    out = bytearray(_NPY_MAGIC) + bytes(version)
    out += (struct.pack("<H", len(body)) if version == (1, 0)
            else struct.pack("<I", len(body)))
    out += body
    if payload is None:
        digits = descr[2:] if descr[0] in "<>|=" else descr[1:]
        itemsize = int(digits) if digits else 0
        count = 1
        for dim in shape:
            count *= dim
        payload = b"\x00" * (count * itemsize)
    return bytes(out) + payload


def _schema_gd(edge=16, channels=8):
    """The five members a `v070_gen` snapshot carries, at a valid edge."""
    return {
        "lattice.npy": _npy_gd("|u1", (edge, edge, edge)),
        "memory_grid.npy": _npy_gd("<f4", (channels, edge, edge, edge)),
        "generation.npy": _npy_gd("<i8", ()),
        "ca_step.npy": _npy_gd("<i8", ()),
        "best_fitness.npy": _npy_gd("<f8", ()),
    }


def _zip_gd(path, members, *, compressed=True, duplicate=None):
    mode = zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # a duplicate name is the point here
        with zipfile.ZipFile(path, "w", compression=mode) as archive:
            for name, blob in members.items():
                archive.writestr(name, blob)
            if duplicate is not None:
                archive.writestr(duplicate, members[duplicate])
    return str(path)


def _declared_gd(edge, channels=8):
    """The same five members, DECLARING an `edge` it does not carry.

    The guard checks geometry before size arithmetic, so an archive that lies
    about its shape is refused on the geometry rule without the bytes ever
    needing to exist. That is what keeps a 512-edge case at a few kilobytes
    instead of the 4.1 GiB a real 512-cube payload would require.
    """
    members = _schema_gd(16, channels)
    members["lattice.npy"] = _npy_gd(
        "|u1", (edge, edge, edge), payload=b"",
        header="{'descr': '|u1', 'fortran_order': False, 'shape': "
               "(%d, %d, %d), }" % (edge, edge, edge))
    members["memory_grid.npy"] = _npy_gd(
        "<f4", (channels, edge, edge, edge), payload=b"",
        header="{'descr': '<f4', 'fortran_order': False, 'shape': "
               "(%d, %d, %d, %d), }" % (channels, edge, edge, edge))
    return members


def _hostile_gd(kind, path):
    """Build one hostile archive of the named kind at `path`."""
    members = _schema_gd()
    if kind == "duplicate_member":
        return _zip_gd(path, members, duplicate="lattice.npy")
    if kind == "traversal_name":
        members["../../escape.npy"] = _npy_gd("|u1", (1,))
        return _zip_gd(path, members)
    if kind == "backslash_name":
        members["sub\\escape.npy"] = _npy_gd("|u1", (1,))
        return _zip_gd(path, members)
    if kind == "missing_member":
        members.pop("ca_step.npy")
        return _zip_gd(path, members)
    if kind == "extra_member":
        members["surprise.npy"] = _npy_gd("|u1", (1,))
        return _zip_gd(path, members)
    if kind == "oversized_declared_payload":
        members["lattice.npy"] = _npy_gd(
            "|u8", (256, 256, 256), payload=b"",
            header="{'descr': '|u8', 'fortran_order': False, "
                   "'shape': (256, 256, 256), }")
        members["memory_grid.npy"] = _npy_gd(
            "<f4", (8, 256, 256, 256), payload=b"",
            header="{'descr': '<f4', 'fortran_order': False, "
                   "'shape': (8, 256, 256, 256), }")
        return _zip_gd(path, members)
    if kind == "oversized_edge":
        return _zip_gd(path, _declared_gd(512))
    if kind == "header_payload_mismatch":
        members["lattice.npy"] = _npy_gd("|u1", (16, 16, 16)) + b"\x00" * 64
        return _zip_gd(path, members)
    if kind == "invalid_magic":
        members["lattice.npy"] = b"XXXXXX" + members["lattice.npy"][6:]
        return _zip_gd(path, members)
    if kind == "invalid_version":
        blob = bytearray(members["lattice.npy"])
        blob[6] = 9
        members["lattice.npy"] = bytes(blob)
        return _zip_gd(path, members)
    if kind == "invalid_header":
        members["lattice.npy"] = _npy_gd(
            "|u1", (16, 16, 16), header="{'descr': '|u1', 'shape': (1,), }")
        return _zip_gd(path, members)
    if kind == "object_dtype":
        members["generation.npy"] = _npy_gd("|O", (), payload=b"")
        return _zip_gd(path, members)
    if kind == "structured_dtype":
        members["generation.npy"] = _npy_gd(
            "<i8", (), payload=b"",
            header="{'descr': [('payload', '|O'), ('n', '<i4')], "
                   "'fortran_order': False, 'shape': (1,), }")
        return _zip_gd(path, members)
    if kind == "wrong_rank":
        members["lattice.npy"] = _npy_gd("|u1", (16, 16))
        return _zip_gd(path, members)
    if kind == "spatial_mismatch":
        members["memory_grid.npy"] = _npy_gd(
            "<f4", (8, 32, 32, 32), payload=b"",
            header="{'descr': '<f4', 'fortran_order': False, "
                   "'shape': (8, 32, 32, 32), }")
        return _zip_gd(path, members)
    if kind == "fortran_order":
        members["lattice.npy"] = _npy_gd("|u1", (16, 16, 16), fortran=True)
        return _zip_gd(path, members)
    if kind == "not_an_npz":
        Path(path).write_bytes(_npy_gd("|u1", (16, 16, 16)))
        return str(path)
    raise AssertionError("unknown hostile archive kind: " + kind)


_HOSTILE_KINDS = [
    "duplicate_member", "traversal_name", "backslash_name", "missing_member",
    "extra_member", "oversized_declared_payload", "oversized_edge",
    "header_payload_mismatch", "invalid_magic", "invalid_version",
    "invalid_header", "object_dtype", "structured_dtype", "wrong_rank",
    "spatial_mismatch", "fortran_order", "not_an_npz",
]

#: The reason code each hostile kind must produce. Asserting only that a
#: ValueError was raised would be weak: SnapshotArchiveRejected IS a
#: ValueError, so an unrelated failure would satisfy it. Pinning the code ties
#: each fixture to the defect its name claims.
_EXPECTED_REASON = {
    "duplicate_member": "member_duplicate",
    "traversal_name": "member_name_unsafe",
    "backslash_name": "member_name_unsafe",
    "missing_member": "member_missing",
    "extra_member": "member_unexpected",
    "oversized_declared_payload": "member_payload_too_large",
    "oversized_edge": "edge_out_of_range",
    "header_payload_mismatch": "member_size_inconsistent",
    "invalid_magic": "member_npy_magic_invalid",
    "invalid_version": "member_npy_version_unsupported",
    "invalid_header": "member_header_malformed",
    "object_dtype": "member_dtype_object",
    "structured_dtype": "member_dtype_structured",
    "wrong_rank": "member_rank",
    "spatial_mismatch": "spatial_disagreement",
    "fortran_order": "member_fortran_order",
    "not_an_npz": "not_zip_archive",
}


@pytest.mark.parametrize("kind", _HOSTILE_KINDS)
def test_hostile_archive_is_refused_before_np_load(kind, tmp_path, monkeypatch):
    """The load-reached recorder is the whole point.

    Asserting only that something was raised would pass on code that let
    `np.load` open, decompress and allocate first and then failed downstream --
    which is exactly the behaviour this replaces.
    """
    archive = _hostile_gd(kind, tmp_path / "v070_gen000001.npz")
    monkeypatch.setattr(geometry_daemon, "DATA_DIR", tmp_path)

    reached = []
    real_load = np.load

    def _recording_load(*args, **kwargs):
        reached.append(args[:1])
        return real_load(*args, **kwargs)

    monkeypatch.setattr(geometry_daemon.np, "load", _recording_load)

    with pytest.raises(geometry_daemon.SnapshotArchiveRejected) as excinfo:
        geometry_daemon._load_snapshot(archive)
    assert excinfo.value.reason == _EXPECTED_REASON[kind], (
        "the fixture was refused for a different defect than its name claims")
    assert reached == [], "np.load was reached on a hostile archive"


@pytest.mark.parametrize("kind", _HOSTILE_KINDS)
def test_hostile_refusal_names_no_path_member_or_header(kind, tmp_path, monkeypatch):
    """The refusal reaches unattended logs, so it must carry no archive content."""
    archive = _hostile_gd(kind, tmp_path / "v070_gen000002.npz")
    monkeypatch.setattr(geometry_daemon, "DATA_DIR", tmp_path)
    with pytest.raises(ValueError) as excinfo:
        geometry_daemon._load_snapshot(archive)
    message = str(excinfo.value)
    assert str(tmp_path) not in message
    assert "v070_gen000002" not in message
    assert ".npy" not in message
    assert "descr" not in message and "escape" not in message
    assert message == message.strip() and "\n" not in message


# ===========================================================================
# Bounded discovery, used directly
#
# The daemon is serial: watch mode polls every 60 seconds and `--once` runs a
# single pass, so there is no concurrent request topology here and no cache is
# needed. What IS needed is the same explicit calibrated policy the other two
# consumers use, and the same fail-closed refusal semantics -- because a
# directory over its cap must not silently become "nothing to export".
#
# Populations are injected through a fake `scandir`; nothing below creates a
# cap-level directory.
# ===========================================================================


class _GeoScandir:
    """A synthetic directory for the bounded discovery path.

    `open_error` makes the directory itself unopenable, which is how a real
    `directory_open_failed` is produced without breaking a real filesystem.
    Ghost entries raise from `stat`, exactly as an entry rotated away between
    enumeration and the metadata read does. Both are mutable so one test can
    move the directory between states.
    """

    class _Ghost:
        __slots__ = ("name",)

        def __init__(self, name):
            self.name = name

        def stat(self, *, follow_symlinks=True):
            raise FileNotFoundError(2, "No such file or directory")

    def __init__(self, ghosts=(), *, include_real=True, open_error=None):
        self.ghosts = [os.path.basename(name) for name in ghosts]
        self.include_real = include_real
        self.open_error = open_error
        self.directory = None
        self.scans = 0
        self._real = os.scandir  # captured BEFORE the patch replaces it

    def __call__(self, directory):
        self.directory = directory
        self.scans += 1
        if self.open_error is not None:
            raise self.open_error
        return self

    def __enter__(self):
        return self._iterate()

    def __exit__(self, *exc):
        return False

    def _iterate(self):
        if self.include_real:
            with self._real(self.directory) as entries:
                for entry in entries:
                    yield entry
        for name in self.ghosts:
            yield self._Ghost(name)


def _no_exporters(monkeypatch, sink):
    for name in ("export_sage_pointcloud", "export_voxel_summary", "export_stl"):
        monkeypatch.setattr(geometry_daemon, name,
                            lambda *a, _n=name: sink.append(_n))


# -- the explicit policy, in both entry points --------------------------------

def test_geometry_consumes_the_bounded_discovery_primitive():
    source = Path(geometry_daemon.__file__).read_text(encoding="utf-8")
    assert "PRODUCTION_DISCOVERY_POLICY" in source
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
    assert "discover_snapshot_candidates" in imported
    assert "PRODUCTION_DISCOVERY_POLICY" in imported
    assert "order_candidates" not in imported


def test_no_unbounded_discovery_call_site_remains_in_geometry():
    tree = ast.parse(Path(geometry_daemon.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "v070_gen*" not in node.value, node.value
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(
                node.func, "attr", None)
            assert name not in ("glob", "iglob", "order_candidates",
                                "newest_first"), name


@pytest.mark.parametrize("entry_point", ["run_daemon", "run_once"])
def test_both_entry_points_pass_the_production_policy_explicitly(entry_point):
    """Not a default, and not a locally-invented policy: the ONE shared
    instance, named at the call site where a reader can see which caps it got.
    """
    tree = ast.parse(Path(geometry_daemon.__file__).read_text(encoding="utf-8"))
    function = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef)
                    and node.name == entry_point)
    calls = [node for node in ast.walk(function)
             if isinstance(node, ast.Call)
             and getattr(node.func, "id", None) == "discover_snapshot_candidates"]
    assert len(calls) == 1, entry_point
    keywords = {kw.arg: kw.value for kw in calls[0].keywords}
    assert "policy" in keywords, "the policy must be explicit and keyword-named"
    assert getattr(keywords["policy"], "id", None) == "PRODUCTION_DISCOVERY_POLICY"


def test_the_policy_geometry_uses_is_the_shared_instance():
    assert (geometry_daemon.PRODUCTION_DISCOVERY_POLICY
            is snapshot_archive_guard.PRODUCTION_DISCOVERY_POLICY)
    assert geometry_daemon.PRODUCTION_DISCOVERY_POLICY.max_directory_entries == 196_608
    assert geometry_daemon.PRODUCTION_DISCOVERY_POLICY.max_candidates == 65_536


# -- watch mode fails closed and recovers -------------------------------------

def test_the_daemon_runs_no_exporter_on_a_discovery_failure(tmp_path,
                                                            monkeypatch,
                                                            capsys):
    monkeypatch.setattr(geometry_daemon, "DATA_DIR", tmp_path)
    monkeypatch.setattr(geometry_daemon, "GEO_DIR", tmp_path)
    monkeypatch.setattr(geometry_daemon, "time", _FakeClock(stop_after_sleeps=4))
    monkeypatch.setattr(
        snapshot_archive_guard.os, "scandir",
        _GeoScandir(open_error=PermissionError(13, "Permission denied")))
    exporters = []
    _no_exporters(monkeypatch, exporters)

    try:
        geometry_daemon.run_daemon()
    except KeyboardInterrupt:
        pass

    output = capsys.readouterr()
    assert exporters == [], "an exporter ran on a discovery failure"
    # Not vacuous: the daemon must actually have REACHED the failure and said
    # so. Without this the assertion above would also hold for a daemon that
    # simply found an empty directory.
    assert "Snapshot discovery failed" in output.out
    assert "[GEO] Error:" not in output.out, (
        "the failure escaped into the loop's broad handler")


def test_the_daemon_reports_a_discovery_failure_once_per_episode(tmp_path,
                                                                 monkeypatch,
                                                                 capsys):
    """Repeated-failure suppression, as the archive-refusal lane already has:
    a persistent fault is one line, not one line per poll."""
    monkeypatch.setattr(geometry_daemon, "DATA_DIR", tmp_path)
    monkeypatch.setattr(geometry_daemon, "GEO_DIR", tmp_path)
    monkeypatch.setattr(geometry_daemon, "time", _FakeClock(stop_after_sleeps=5))
    monkeypatch.setattr(
        snapshot_archive_guard.os, "scandir",
        _GeoScandir(open_error=PermissionError(13, "Permission denied")))
    _no_exporters(monkeypatch, [])

    try:
        geometry_daemon.run_daemon()
    except KeyboardInterrupt:
        pass

    output = capsys.readouterr().out
    assert output.count("Snapshot discovery failed") == 1, output


def test_the_daemon_diagnostic_names_no_path_and_no_exception(tmp_path,
                                                              monkeypatch,
                                                              capsys):
    """This daemon runs unattended over a directory anyone able to write there
    can fill, so the only thing it may say is a fixed code."""
    leaky = tmp_path / "LEAKDIR"
    leaky.mkdir()
    monkeypatch.setattr(geometry_daemon, "DATA_DIR", leaky)
    monkeypatch.setattr(geometry_daemon, "GEO_DIR", tmp_path)
    monkeypatch.setattr(geometry_daemon, "time", _FakeClock(stop_after_sleeps=3))
    monkeypatch.setattr(
        snapshot_archive_guard.os, "scandir",
        _GeoScandir(open_error=PermissionError(13, "Permission denied")))
    _no_exporters(monkeypatch, [])

    try:
        geometry_daemon.run_daemon()
    except KeyboardInterrupt:
        pass

    captured = capsys.readouterr()
    for leak in ("LEAKDIR", "Permission denied", "Errno", "Traceback", ".npz"):
        assert leak not in captured.out and leak not in captured.err, leak
    assert "directory_open_failed" in captured.out


def test_the_daemon_re_arms_after_a_recovered_discovery(tmp_path, monkeypatch,
                                                        capsys):
    """Recovery: a successful discovery ends the episode, so a later failure
    is reported again rather than staying suppressed for ever."""
    monkeypatch.setattr(geometry_daemon, "DATA_DIR", tmp_path)
    monkeypatch.setattr(geometry_daemon, "GEO_DIR", tmp_path)
    directory = _GeoScandir(open_error=PermissionError(13, "Permission denied"))
    monkeypatch.setattr(snapshot_archive_guard.os, "scandir", directory)
    _no_exporters(monkeypatch, [])

    class _FlippingClock(_FakeClock):
        def sleep(self, seconds):
            step = len(self.sleeps) + 1
            if step == 2:
                directory.open_error = None          # recovered: clean empty
            elif step == 4:
                directory.open_error = PermissionError(13, "Permission denied")
            return super().sleep(seconds)

    monkeypatch.setattr(geometry_daemon, "time",
                        _FlippingClock(stop_after_sleeps=6))
    try:
        geometry_daemon.run_daemon()
    except KeyboardInterrupt:
        pass

    output = capsys.readouterr().out
    assert output.count("Snapshot discovery failed") == 2, output


# -- `--once` fails closed ----------------------------------------------------

def test_the_once_path_exits_nonzero_on_a_discovery_failure(confined, capsys,
                                                            monkeypatch):
    """A cron or CI wrapper has to be able to tell "the directory could not be
    discovered" from "there is nothing to export"."""
    monkeypatch.setattr(geometry_daemon, "GEO_DIR", confined)
    monkeypatch.setattr(
        snapshot_archive_guard.os, "scandir",
        _GeoScandir(open_error=PermissionError(13, "Permission denied")))
    exporters = []
    _no_exporters(monkeypatch, exporters)

    with pytest.raises(SystemExit) as excinfo:
        geometry_daemon.run_once()

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.strip() == "Snapshot discovery failed: directory_open_failed"
    assert "No snapshots found" not in captured.out
    assert exporters == []
    for leak in (str(confined), "Permission denied", "Errno", "Traceback"):
        assert leak not in captured.err


def test_the_once_path_discovery_failure_is_not_an_empty_directory(confined,
                                                                   capsys,
                                                                   monkeypatch):
    """The four states, side by side through the real `--once` path: a
    discovery failure, an all-unreadable directory and a clean empty one each
    produce their own outcome."""
    monkeypatch.setattr(geometry_daemon, "GEO_DIR", confined)
    _no_exporters(monkeypatch, [])
    directory = _GeoScandir(include_real=False)
    monkeypatch.setattr(snapshot_archive_guard.os, "scandir", directory)

    directory.open_error = PermissionError(13, "Permission denied")
    with pytest.raises(SystemExit) as failure:
        geometry_daemon.run_once()
    failure_err = capsys.readouterr().err

    directory.open_error = None
    directory.ghosts = ["v070_gen000001.npz", "v070_gen000002.npz"]
    with pytest.raises(SystemExit) as unreadable:
        geometry_daemon.run_once()
    unreadable_err = capsys.readouterr().err

    directory.ghosts = []
    geometry_daemon.run_once()
    empty = capsys.readouterr()

    assert failure.value.code == 1
    assert unreadable.value.code == 1
    assert "Snapshot discovery failed" in failure_err
    assert unreadable_err.strip() == "Snapshot candidates unreadable"
    assert failure_err != unreadable_err
    assert "No snapshots found!" in empty.out
    assert empty.err == ""


def test_a_discovery_failure_is_not_an_archive_refusal(confined, capsys,
                                                       monkeypatch):
    """`SnapshotArchiveRejected` is downstream of a SUCCESSFUL discovery and
    keeps its own established message and exit."""
    monkeypatch.setattr(geometry_daemon, "GEO_DIR", confined)
    _no_exporters(monkeypatch, [])
    _hostile_gd("missing_member", confined / "v070_gen000001.npz")

    with pytest.raises(SystemExit) as excinfo:
        geometry_daemon.run_once()

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.strip().startswith("Snapshot rejected:")
    assert "Snapshot discovery failed" not in captured.err
    assert "Snapshot candidates unreadable" not in captured.err


# ===========================================================================
# Watch mode keeps all-matching-unreadable apart from clean empty
#
# `--once` already distinguished them: an empty directory is "nothing to
# export" and exits zero, while a directory whose every candidate failed its
# metadata read is a FAULT and exits nonzero. Watch mode collapsed both into
# the same silent sleep, so a daemon running blind over a directory it could
# see but not describe was indistinguishable from a daemon with nothing to do.
#
# Watch mode now carries the same three-way distinction, with one fixed
# path-free line per problem EPISODE and a transition between kinds treated as
# a new episode -- because "the directory stopped opening" and "the entries
# stopped describing" are different faults and the second must not hide behind
# the first's rate limit.
# ===========================================================================


class _ScriptedClock(_FakeClock):
    """A daemon clock that applies a scripted directory change at each sleep.

    `script` maps a 1-based sleep index to a callable run just before that
    sleep, which is how one test walks the daemon through several directory
    states without any real waiting.
    """

    def __init__(self, script, stop_after_sleeps):
        super().__init__(stop_after_sleeps=stop_after_sleeps)
        self.script = dict(script)

    def sleep(self, seconds):
        action = self.script.get(len(self.sleeps) + 1)
        if action is not None:
            action()
        return super().sleep(seconds)


def _run_geo_daemon(monkeypatch, tmp_path, directory, clock):
    """Drive the REAL `run_daemon()` over an injected directory."""
    monkeypatch.setattr(geometry_daemon, "DATA_DIR", tmp_path)
    monkeypatch.setattr(geometry_daemon, "GEO_DIR", tmp_path)
    monkeypatch.setattr(snapshot_archive_guard.os, "scandir", directory)
    monkeypatch.setattr(geometry_daemon, "time", clock)
    exporters = []
    _no_exporters(monkeypatch, exporters)
    try:
        geometry_daemon.run_daemon()
    except KeyboardInterrupt:
        pass
    return exporters


_UNREADABLE_LINE = "Snapshot candidates unreadable"
_FAILED_LINE = "Snapshot discovery failed"


def test_the_daemon_is_silent_for_a_clean_empty_directory(tmp_path,
                                                          monkeypatch,
                                                          capsys):
    """Nothing to export is not a fault and must not become one."""
    exporters = _run_geo_daemon(
        monkeypatch, tmp_path, _GeoScandir(include_real=False),
        _FakeClock(stop_after_sleeps=4))
    output = capsys.readouterr().out
    assert exporters == []
    assert _UNREADABLE_LINE not in output
    assert _FAILED_LINE not in output
    assert "[GEO] Error:" not in output


def test_the_daemon_reports_unreadable_candidates_once_per_episode(tmp_path,
                                                                   monkeypatch,
                                                                   capsys):
    """Names matched and none could be described: the daemon is running blind
    over a directory it can see. One line, not one per poll, and the loop
    stays alive."""
    ghosts = ["v070_gen00000%d.npz" % index for index in range(4)]
    exporters = _run_geo_daemon(
        monkeypatch, tmp_path, _GeoScandir(ghosts, include_real=False),
        _FakeClock(stop_after_sleeps=5))
    output = capsys.readouterr().out
    assert output.count(_UNREADABLE_LINE) == 1, output
    assert _FAILED_LINE not in output, "an unreadable directory was relabelled"
    assert exporters == []
    assert "[GEO] Daemon shutting down" in output   # the loop survived


def test_the_daemon_unreadable_diagnostic_names_no_path(tmp_path, monkeypatch,
                                                        capsys):
    ghosts = ["v070_gen_LEAKNAME_%d.npz" % index for index in range(3)]
    _run_geo_daemon(monkeypatch, tmp_path, _GeoScandir(ghosts,
                                                       include_real=False),
                    _FakeClock(stop_after_sleeps=3))
    captured = capsys.readouterr()
    for leak in ("LEAKNAME", ".npz", "Errno", "No such file", "Traceback"):
        assert leak not in captured.out and leak not in captured.err, leak
    assert _UNREADABLE_LINE in captured.out


def test_a_clean_empty_recovery_re_arms_the_unreadable_episode(tmp_path,
                                                               monkeypatch,
                                                               capsys):
    """A successful NON-BLIND discovery -- clean empty here, or a listing with
    readable candidates -- ends the episode, so a later blind spell is
    reported again instead of staying suppressed. All-matching-unreadable does
    not end it: that is the blind state itself."""
    ghosts = ["v070_gen000001.npz", "v070_gen000002.npz"]
    directory = _GeoScandir(ghosts, include_real=False)

    def recover():
        directory.ghosts = []

    def relapse():
        directory.ghosts = list(ghosts)

    clock = _ScriptedClock({2: recover, 4: relapse}, stop_after_sleeps=6)
    exporters = _run_geo_daemon(monkeypatch, tmp_path, directory, clock)

    output = capsys.readouterr().out
    assert output.count(_UNREADABLE_LINE) == 2, output
    assert exporters == []


def test_the_daemon_distinguishes_unreadable_from_a_discovery_failure(
        tmp_path, monkeypatch, capsys):
    """Two different faults, two different fixed codes. Neither may hide
    behind the other's suppression."""
    ghosts = ["v070_gen000001.npz"]
    directory = _GeoScandir(ghosts, include_real=False)

    def to_failure():
        directory.open_error = PermissionError(13, "Permission denied")

    def to_unreadable():
        directory.open_error = None

    clock = _ScriptedClock({1: to_failure, 3: to_unreadable},
                           stop_after_sleeps=4)
    exporters = _run_geo_daemon(monkeypatch, tmp_path, directory, clock)

    output = capsys.readouterr().out
    assert output.count(_UNREADABLE_LINE) == 2, output
    assert output.count(_FAILED_LINE) == 1, output
    assert "directory_open_failed" in output
    assert exporters == []


def test_a_readable_snapshot_ends_a_discovery_failure_episode(tmp_path,
                                                              monkeypatch,
                                                              capsys):
    """The other recovery direction: an ordered listing re-arms too."""
    directory = _GeoScandir(include_real=False,
                            open_error=PermissionError(13, "Permission denied"))

    def recover():
        directory.open_error = None

    def relapse():
        directory.open_error = PermissionError(13, "Permission denied")

    clock = _ScriptedClock({2: recover, 4: relapse}, stop_after_sleeps=6)
    _run_geo_daemon(monkeypatch, tmp_path, directory, clock)

    output = capsys.readouterr().out
    assert output.count(_FAILED_LINE) == 2, output


def test_watch_mode_and_once_agree_on_the_three_states(tmp_path, monkeypatch,
                                                       capsys):
    """The adapter-level requirement, stated as one control: clean empty,
    all-matching-unreadable and `DiscoveryFailed` are three outcomes in BOTH
    entry points, not two in one and three in the other."""
    monkeypatch.setattr(geometry_daemon, "DATA_DIR", tmp_path)
    monkeypatch.setattr(geometry_daemon, "GEO_DIR", tmp_path)
    _no_exporters(monkeypatch, [])
    directory = _GeoScandir(include_real=False)
    monkeypatch.setattr(snapshot_archive_guard.os, "scandir", directory)

    geometry_daemon.run_once()
    empty_once = capsys.readouterr()

    directory.ghosts = ["v070_gen000001.npz"]
    with pytest.raises(SystemExit):
        geometry_daemon.run_once()
    unreadable_once = capsys.readouterr()

    directory.ghosts = []
    directory.open_error = PermissionError(13, "Permission denied")
    with pytest.raises(SystemExit):
        geometry_daemon.run_once()
    failed_once = capsys.readouterr()

    assert "No snapshots found!" in empty_once.out and empty_once.err == ""
    assert unreadable_once.err.strip() == _UNREADABLE_LINE
    assert failed_once.err.strip().startswith(_FAILED_LINE)

    # And the same three, distinct, through the watch loop.
    directory.open_error = None
    directory.ghosts = []
    empty_watch = capsys.readouterr()
    _run_geo_daemon(monkeypatch, tmp_path, directory,
                    _FakeClock(stop_after_sleeps=2))
    empty_watch = capsys.readouterr().out
    assert _UNREADABLE_LINE not in empty_watch and _FAILED_LINE not in empty_watch

    directory.ghosts = ["v070_gen000001.npz"]
    _run_geo_daemon(monkeypatch, tmp_path, directory,
                    _FakeClock(stop_after_sleeps=2))
    unreadable_watch = capsys.readouterr().out
    assert _UNREADABLE_LINE in unreadable_watch
    assert _FAILED_LINE not in unreadable_watch

    directory.ghosts = []
    directory.open_error = PermissionError(13, "Permission denied")
    _run_geo_daemon(monkeypatch, tmp_path, directory,
                    _FakeClock(stop_after_sleeps=2))
    failed_watch = capsys.readouterr().out
    assert _FAILED_LINE in failed_watch
    assert _UNREADABLE_LINE not in failed_watch
