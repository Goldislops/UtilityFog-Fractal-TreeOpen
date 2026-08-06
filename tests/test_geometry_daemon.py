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
written anywhere, and the module's import-time `GEO_DIR.mkdir(...)` is isolated
so the repository's real `data/geometry` directory is never created or modified.

Scope is `.npz` archive resource lifetime only — not snapshot validation, archive
security, deterministic export, atomic output or whole-daemon correctness.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest import mock

import pytest

# `scripts/geometry_daemon.py` runs `GEO_DIR.mkdir(parents=True, exist_ok=True)`
# at module scope. Patching Path.mkdir for the duration of the import keeps that
# side effect out of the repository; production directory configuration is
# unchanged.
with mock.patch.object(Path, "mkdir"):
    from scripts import geometry_daemon


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


def _load_with(archive, path="/fake/v070_gen0001000.npz"):
    """Run the real `_load_snapshot` against `archive`; return the load mock."""
    loader = mock.Mock(return_value=archive)
    with mock.patch.object(geometry_daemon.np, "load", loader):
        result = geometry_daemon._load_snapshot(path)
    return result, loader


# -- helper contract ----------------------------------------------------------


def test_helper_returns_the_exact_extracted_objects():
    contents = _good_contents(generation=7)
    archive = _FakeArchive(contents)
    (state, memory_grid, generation), _ = _load_with(archive)
    assert state is contents["lattice"]
    assert memory_grid is contents["memory_grid"]
    assert generation == 7
    assert type(generation) is int


def test_helper_preserves_the_int_generation_conversion():
    archive = _FakeArchive(_good_contents(generation=_IntLike()))
    (_, _, generation), _ = _load_with(archive)
    assert generation == 42
    assert type(generation) is int


def test_helper_calls_np_load_with_the_same_path_conversion_and_allow_pickle():
    archive = _FakeArchive(_good_contents())
    _, loader = _load_with(archive, path=Path("/fake/dir/v070_gen42.npz"))
    assert loader.call_count == 1
    args, kwargs = loader.call_args
    assert args == (str(Path("/fake/dir/v070_gen42.npz")),)
    assert type(args[0]) is str
    assert kwargs == {"allow_pickle": False}


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
    (state, memory_grid, generation), _ = _load_with(archive)
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


class _FakeStat:
    def __init__(self, size, mtime):
        self.st_size = size
        self.st_mtime = mtime


class _FakeSnapshotPath:
    def __init__(self, name="v070_gen0001000.npz", size=2_000_000, mtime=100.0):
        self.name = name
        self._stat = _FakeStat(size, mtime)

    def stat(self):
        return self._stat

    def __str__(self):
        return f"/fake/{self.name}"


class _FakeDataDir:
    def __init__(self, paths):
        self.paths = list(paths)
        self.globs = []

    def glob(self, pattern):
        self.globs.append(pattern)
        return list(self.paths)


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

    snapshot = _FakeSnapshotPath()
    data_dir = _FakeDataDir([snapshot])
    clock = _FakeClock(stop_after_sleeps=1)
    loader = mock.Mock(return_value=archive)

    with mock.patch.object(geometry_daemon.np, "load", loader), \
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


def test_daemon_cycle_loads_with_the_preserved_call_shape(tmp_path):
    archive = _FakeArchive(_good_contents(generation=1000))
    _, loader, snapshot = _run_one_daemon_cycle(archive, tmp_path)
    assert loader.call_count == 1
    args, kwargs = loader.call_args
    assert args == (str(snapshot),)
    assert kwargs == {"allow_pickle": False}


def test_daemon_cycle_keeps_the_snapshot_glob_pattern(tmp_path):
    archive = _FakeArchive(_good_contents(generation=1000))
    snapshot = _FakeSnapshotPath()
    data_dir = _FakeDataDir([snapshot])
    clock = _FakeClock(stop_after_sleeps=1)
    with mock.patch.object(geometry_daemon.np, "load",
                           mock.Mock(return_value=archive)), \
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
    assert data_dir.globs == ["v070_gen*.npz"]


def test_daemon_skips_tiny_snapshot_without_loading(tmp_path):
    """The established tiny-file threshold still short-circuits before any load."""
    archive = _FakeArchive(_good_contents())
    loader = mock.Mock(return_value=archive)
    data_dir = _FakeDataDir([_FakeSnapshotPath(size=999_999)])
    with mock.patch.object(geometry_daemon.np, "load", loader), \
         mock.patch.object(geometry_daemon, "DATA_DIR", data_dir), \
         mock.patch.object(geometry_daemon, "GEO_DIR", tmp_path), \
         mock.patch.object(geometry_daemon, "time", _FakeClock(stop_after_sleeps=1)):
        try:
            geometry_daemon.run_daemon()
        except KeyboardInterrupt:
            pass
    assert loader.call_count == 0
    assert archive.entered == 0


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
    main_blocks = [
        node for node in tree.body
        if isinstance(node, ast.If) and any(
            isinstance(sub, ast.Name) and sub.id == "__name__"
            for sub in ast.walk(node.test)
        )
    ]
    assert len(main_blocks) == 1
    main_block = main_blocks[0]
    assert len(_helper_calls(main_block)) == 1
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
    """A real NPZ. Object members pickle on the way in, which is harmless."""
    payload = {
        "lattice": np.zeros((2, 2, 2), dtype=np.uint8),
        "memory_grid": np.zeros((8, 2, 2, 2), dtype=np.float32),
        "generation": 7,
    }
    payload.update(members)
    writer = np.savez_compressed if compressed else np.savez
    writer(path, **payload)
    return str(path)


def test_gd_payload_fixture_actually_fires_when_pickle_is_enabled(tmp_path):
    """Control. Without it, every "marker is absent" assertion below could
    pass against a payload that never worked. This is the only place in this
    module that enables pickle."""
    archive = _write_snapshot_gd(
        tmp_path / "control.npz", lattice=_payload_array_gd(tmp_path)
    )
    assert not _marker_gd(tmp_path).exists()

    with np.load(archive, allow_pickle=True) as snap:
        snap["lattice"]

    assert _marker_gd(tmp_path).exists(), "the payload fixture is inert; fix it"


@pytest.mark.parametrize("field", ["lattice", "memory_grid", "generation"])
def test_object_payload_is_refused_by_the_helper(tmp_path, field):
    archive = _write_snapshot_gd(
        tmp_path / f"{field}.npz", **{field: _payload_array_gd(tmp_path)}
    )
    with pytest.raises(ValueError) as excinfo:
        geometry_daemon._load_snapshot(archive)
    assert "allow_pickle=False" in str(excinfo.value)
    assert not _marker_gd(tmp_path).exists(), "the pickle payload executed"


def test_a_compressed_hostile_archive_is_refused_the_same_way(tmp_path):
    """Real producers use `np.savez_compressed`, so the hostile fixture
    exercises that shape too rather than only the uncompressed one."""
    archive = _write_snapshot_gd(
        tmp_path / "compressed.npz", compressed=True,
        lattice=_payload_array_gd(tmp_path),
    )
    with pytest.raises(ValueError) as excinfo:
        geometry_daemon._load_snapshot(archive)
    assert "allow_pickle=False" in str(excinfo.value)
    assert not _marker_gd(tmp_path).exists()


def test_the_compressed_payload_also_fires_when_pickle_is_enabled(tmp_path):
    archive = _write_snapshot_gd(
        tmp_path / "cc.npz", compressed=True,
        lattice=_payload_array_gd(tmp_path),
    )
    with np.load(archive, allow_pickle=True) as snap:
        snap["lattice"]
    assert _marker_gd(tmp_path).exists(), "the compressed payload is inert"


def test_a_refusal_is_never_retried_with_pickle_enabled(tmp_path, monkeypatch):
    archive = _write_snapshot_gd(
        tmp_path / "retry.npz", lattice=_payload_array_gd(tmp_path)
    )
    real_load = np.load
    calls = []

    def _recording_load(*args, **kwargs):
        calls.append(kwargs.get("allow_pickle"))
        return real_load(*args, **kwargs)

    monkeypatch.setattr(geometry_daemon.np, "load", _recording_load)
    with pytest.raises(ValueError):
        geometry_daemon._load_snapshot(archive)
    assert calls == [False]


def test_the_real_archive_is_closed_after_a_refusal(tmp_path, monkeypatch):
    archive = _write_snapshot_gd(
        tmp_path / "closed.npz", lattice=_payload_array_gd(tmp_path)
    )
    real_load = np.load
    opened = []

    def _tracking_load(*args, **kwargs):
        handle = real_load(*args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(geometry_daemon.np, "load", _tracking_load)
    with pytest.raises(ValueError):
        geometry_daemon._load_snapshot(archive)
    assert len(opened) == 1
    assert opened[0].fid is None or getattr(opened[0].fid, "closed", True)


def test_a_numeric_snapshot_still_loads_unchanged(tmp_path):
    archive = _write_snapshot_gd(tmp_path / "clean.npz", generation=np.int64(12))
    state, grid, generation = geometry_daemon._load_snapshot(archive)
    assert state.shape == (2, 2, 2)
    assert grid.shape == (8, 2, 2, 2)
    assert generation == 12 and type(generation) is int
