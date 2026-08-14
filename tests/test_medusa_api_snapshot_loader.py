"""Focused tests for `scripts/medusa_api._load_snapshot()` archive lifetime.

The shared snapshot helper used to return while the `NpzFile` from `np.load` was
still referenced, so the archive stayed open through whatever the calling
endpoint did next — census counting and entropy, equanimity masks and elder
sorting, acoustic sector reshaping, geometry sampling and mesh construction — and
was released only by eventual object destruction. Every request repeated that. On
Windows a retained snapshot handle can interfere with deleting, rotating or
replacing that file.

The helper now materialises all four values while the archive is open and closes
it before returning.

Deliberately separate from `tests/test_medusa_api.py`, which is untouched. No
real snapshot, engine, event bus, socket, network port, Flask server, STL or
telemetry file is involved: the module is imported inside a scoped
`MEDUSA_EVENT_BUS_DISABLED=1` override (restored immediately), `np.load` is
replaced by a closure-recording fake, and the one endpoint witness uses Flask's
in-process test client.

Scope is archive resource lifetime relative to extraction — not snapshot
validation, whole-archive validation, endpoint totality, API authentication, atomic file
access or whole-server correctness.
"""

from __future__ import annotations

import ast
import os
import sys
import types
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

pytest.importorskip("flask")  # optional dependency for the REST API; CI provisions it

# Record the ambient environment before the scoped import so a test can prove the
# override restored it exactly — including the originally-absent case.
_EVENT_BUS_ENV_KEY = "MEDUSA_EVENT_BUS_DISABLED"
_ENV_BEFORE_IMPORT = os.environ.get(_EVENT_BUS_ENV_KEY)

# Disable the event-bus PUB socket / StateWatcher thread ONLY for the duration of
# the import, then restore the exact prior environment. `patch.dict` leaks
# nothing into the rest of the pytest process, so no port is bound and no watcher
# thread starts.
with mock.patch.dict(os.environ, {_EVENT_BUS_ENV_KEY: "1"}):
    from scripts import medusa_api  # noqa: E402  (import inside the scoped override)

_ENV_AFTER_IMPORT = os.environ.get(_EVENT_BUS_ENV_KEY)


class Boom(Exception):
    """Distinct conversion failure, so propagation can be asserted exactly."""


class _ExplodingInt:
    def __int__(self):
        raise Boom("generation conversion failed")


class _ExplodingFloat:
    def __float__(self):
        raise Boom("fitness conversion failed")


class _FakeArchive:
    """Stand-in for the `NpzFile` that `np.load` returns.

    Records context entry/exit, explicit closure and key lookups. Defines **no**
    `__del__`, so a recorded closure can never have come from garbage collection,
    reference-count timing or interpreter shutdown.
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


class _FakeSnapshotPath:
    def __init__(self, name="v070_gen0001000.npz"):
        self.name = name

    def __str__(self):
        return f"/fake/data/{self.name}"


def _lattice():
    # A tiny deterministic lattice with several states, so census is meaningful.
    grid = np.zeros((4, 4, 4), dtype=np.uint8)
    grid[0, 0, 0] = 1
    grid[0, 0, 1] = 2
    grid[0, 0, 2] = 2
    grid[0, 0, 3] = 3
    return grid


def _memory_grid():
    return np.zeros((8, 4, 4, 4), dtype=np.float32)


def _contents(**overrides):
    base = {
        "lattice": _lattice(),
        "memory_grid": _memory_grid(),
        "generation": 1234,
        "best_fitness": 0.875,
    }
    base.update(overrides)
    return base


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


def _load(archive, path=None):
    """Run the real `_load_snapshot` against `archive`.

    Returns (result, load mock, admission recorder).
    """
    load_mock = mock.Mock(return_value=archive)
    admission = _FakeAdmission()
    target = path if path is not None else _FakeSnapshotPath()
    with mock.patch.object(medusa_api, "admit_snapshot", admission), \
         mock.patch.object(medusa_api.np, "load", load_mock):
        result = medusa_api._load_snapshot(target)
    return result, load_mock, admission


# -- import-time containment --------------------------------------------------


def test_event_bus_env_override_was_scoped_to_the_import():
    """The override must not leak: the ambient value is exactly as before."""
    assert _ENV_AFTER_IMPORT == _ENV_BEFORE_IMPORT
    assert os.environ.get(_EVENT_BUS_ENV_KEY) == _ENV_BEFORE_IMPORT


def test_no_event_publisher_or_watcher_was_started():
    """Import under the override binds no PUB socket and starts no thread."""
    assert getattr(medusa_api, "_event_publisher", None) is None
    assert getattr(medusa_api, "_state_watcher", None) is None


# -- successful helper load ---------------------------------------------------


def test_helper_returns_the_exact_objects_and_tuple_order():
    contents = _contents()
    archive = _FakeArchive(contents)
    result, *_ = _load(archive)
    assert isinstance(result, tuple) and len(result) == 4
    state, memory_grid, generation, fitness = result
    assert state is contents["lattice"]            # identity, not a copy
    assert memory_grid is contents["memory_grid"]  # identity, not a copy
    assert generation == 1234
    assert fitness == 0.875


def test_generation_is_an_exact_builtin_int():
    archive = _FakeArchive(_contents(generation=np.int64(4242)))
    (_, _, generation, _), *_ = _load(archive)
    assert type(generation) is int
    assert generation == 4242


def test_fitness_is_an_exact_builtin_float():
    archive = _FakeArchive(_contents(best_fitness=np.float32(0.5)))
    (_, _, _, fitness), *_ = _load(archive)
    assert type(fitness) is float
    assert fitness == 0.5


def test_extraction_order_is_preserved():
    archive = _FakeArchive(_contents())
    _load(archive)
    assert archive.lookups == ["lattice", "memory_grid", "generation", "best_fitness"]


def test_np_load_receives_the_admitted_descriptor_and_allow_pickle_false():
    """The path is handed to the guard; NumPy is handed the descriptor the
    guard opened. There is no second open and no `str(path)` conversion left
    to make, because a pathname is never re-resolved for loading."""
    archive = _FakeArchive(_contents())
    path = _FakeSnapshotPath("v070_gen42.npz")
    _, load_mock, admission = _load(archive, path=path)
    assert load_mock.call_count == 1
    args, kwargs = load_mock.call_args
    assert args == (_DESCRIPTOR,)
    assert kwargs == {"allow_pickle": False}
    assert [call["path"] for call in admission.calls] == [path]


def test_helper_admits_against_the_module_data_dir_and_named_policy():
    archive = _FakeArchive(_contents())
    _, _, admission = _load(archive)
    assert len(admission.calls) == 1
    assert admission.calls[0]["data_dir"] is medusa_api.DATA_DIR
    assert admission.calls[0]["policy"] is medusa_api.SNAPSHOT_POLICY
    assert admission.exited == 1


def test_admission_precedes_the_load():
    """Ordering, not merely presence: the guard must have decided before
    NumPy was asked for anything."""
    order = []
    archive = _FakeArchive(_contents())

    class _OrderedAdmission(_FakeAdmission):
        def __call__(self, path, *, data_dir, policy=None):
            order.append("admit")
            return super().__call__(path, data_dir=data_dir, policy=policy)

    def _ordered_load(*args, **kwargs):
        order.append("load")
        return archive

    with mock.patch.object(medusa_api, "admit_snapshot", _OrderedAdmission()), \
         mock.patch.object(medusa_api.np, "load", _ordered_load):
        medusa_api._load_snapshot(_FakeSnapshotPath())
    assert order == ["admit", "load"]


def test_returned_arrays_keep_their_dtypes():
    contents = _contents()
    archive = _FakeArchive(contents)
    (state, memory_grid, _, _), *_ = _load(archive)
    assert state.dtype == np.uint8
    assert memory_grid.dtype == np.float32


# -- closure on success -------------------------------------------------------


def test_archive_context_entered_exactly_once():
    archive = _FakeArchive(_contents())
    _load(archive)
    assert archive.entered == 1


def test_archive_exits_and_closes_exactly_once_on_success():
    archive = _FakeArchive(_contents())
    _load(archive)
    assert archive.exited == 1
    assert archive.closed == 1


def test_archive_already_closed_when_helper_returns():
    """Asserted immediately after the return, while this frame still holds a live
    reference to the archive — so closure was explicit."""
    archive = _FakeArchive(_contents())
    result, *_ = _load(archive)
    assert archive.closed == 1
    assert result[2] == 1234


def test_closure_does_not_depend_on_finalisation():
    """No `__del__` on the fake and the reference stays alive, so the recorded
    closure cannot come from reference-count timing, a gc pass or interpreter
    shutdown. No test here calls gc.collect()."""
    assert not hasattr(_FakeArchive, "__del__")
    archive = _FakeArchive(_contents())
    _load(archive)
    assert archive.closed == 1
    assert archive is not None


# -- closure on every extraction / conversion failure -------------------------


@pytest.mark.parametrize(
    "missing",
    ["lattice", "memory_grid", "generation", "best_fitness"],
    ids=["lattice", "memory_grid", "generation", "best_fitness"],
)
def test_archive_closes_when_a_key_lookup_raises(missing):
    archive = _FakeArchive(_contents(), raise_on=missing)
    with pytest.raises(KeyError):
        _load(archive)
    assert archive.exited == 1
    assert archive.closed == 1


@pytest.mark.parametrize(
    "overrides",
    [{"generation": _ExplodingInt()}, {"best_fitness": _ExplodingFloat()}],
    ids=["generation_int", "best_fitness_float"],
)
def test_archive_closes_when_a_conversion_raises(overrides):
    archive = _FakeArchive(_contents(**overrides))
    with pytest.raises(Boom):
        _load(archive)
    assert archive.exited == 1
    assert archive.closed == 1


def test_original_extraction_exception_propagates_unchanged():
    archive = _FakeArchive(_contents(generation=_ExplodingInt()))
    with pytest.raises(Boom) as exc:
        _load(archive)
    assert type(exc.value) is Boom
    assert str(exc.value) == "generation conversion failed"
    assert archive.closed == 1

    fitness_bad = _FakeArchive(_contents(best_fitness=_ExplodingFloat()))
    with pytest.raises(Boom) as exc2:
        _load(fitness_bad)
    assert str(exc2.value) == "fitness conversion failed"
    assert fitness_bad.closed == 1

    missing = _FakeArchive(_contents(), raise_on="lattice")
    with pytest.raises(KeyError) as exc3:
        _load(missing)
    assert type(exc3.value) is KeyError
    assert missing.closed == 1


@pytest.mark.parametrize(
    "error",
    [OSError("archive read failed"), RuntimeError("boom"), MemoryError("oom"),
     ValueError("bad zip")],
    ids=["os_error", "runtime_error", "memory_error", "value_error"],
)
def test_unrelated_load_failure_is_not_converted_into_a_lifetime_refusal(error):
    """No blanket except was added: an `np.load` failure of any kind propagates
    unchanged rather than becoming a snapshot-lifetime error."""
    load_mock = mock.Mock(side_effect=error)
    with mock.patch.object(medusa_api, "admit_snapshot", _FakeAdmission()), \
         mock.patch.object(medusa_api.np, "load", load_mock):
        with pytest.raises(type(error)) as exc:
            medusa_api._load_snapshot(_FakeSnapshotPath())
    assert type(exc.value) is type(error)
    assert str(exc.value) == str(error)


# -- endpoint witness: closure precedes downstream computation ----------------


def test_census_request_sees_the_archive_closed_before_first_numpy_work():
    """Central witness. `/api/census`'s first downstream NumPy computation is
    `np.unique(state, ...)`; pre-fix the archive was still open at that point,
    because the helper returned it unclosed."""
    contents = _contents()
    archive = _FakeArchive(contents)
    snapshot = _FakeSnapshotPath()
    real_unique = np.unique
    closure_at_first_unique = []

    def _recording_unique(*args, **kwargs):
        closure_at_first_unique.append(archive.closed)
        return real_unique(*args, **kwargs)

    client = medusa_api.app.test_client()
    with mock.patch.object(medusa_api, "_find_latest_snapshot", lambda: snapshot), \
         mock.patch.object(medusa_api, "admit_snapshot", _FakeAdmission()), \
         mock.patch.object(medusa_api.np, "load", mock.Mock(return_value=archive)), \
         mock.patch.object(medusa_api.np, "unique", _recording_unique):
        response = client.get("/api/census")

    assert response.status_code == 200
    assert closure_at_first_unique, "downstream NumPy work must have been reached"
    assert closure_at_first_unique[0] == 1, "archive must be closed before census work"
    assert all(count == 1 for count in closure_at_first_unique)
    assert archive.entered == 1
    assert archive.exited == 1
    assert archive.closed == 1


def test_census_response_body_is_unchanged():
    """The valid response is computed from the extracted arrays exactly as before."""
    archive = _FakeArchive(_contents())
    snapshot = _FakeSnapshotPath("v070_gen0001000.npz")
    client = medusa_api.app.test_client()
    with mock.patch.object(medusa_api, "_find_latest_snapshot", lambda: snapshot), \
         mock.patch.object(medusa_api, "admit_snapshot", _FakeAdmission()), \
         mock.patch.object(medusa_api.np, "load", mock.Mock(return_value=archive)):
        response = client.get("/api/census")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["generation"] == 1234
    assert payload["lattice_size"] == 4
    assert payload["total_cells"] == 64
    assert payload["non_void"] == 4
    assert payload["states"] == {"VOID": 60, "STRUCTURAL": 1, "COMPUTE": 2, "ENERGY": 1}
    assert payload["fitness"] == 0.875
    assert payload["snapshot"] == "v070_gen0001000.npz"
    assert archive.closed == 1


def test_census_without_a_snapshot_still_returns_404_without_loading():
    load_mock = mock.Mock()
    client = medusa_api.app.test_client()
    with mock.patch.object(medusa_api, "_find_latest_snapshot", lambda: None), \
         mock.patch.object(medusa_api.np, "load", load_mock):
        response = client.get("/api/census")
    assert response.status_code == 404
    assert load_mock.call_count == 0


# -- the helper remains the shared path --------------------------------------


def _module_tree():
    source = Path(medusa_api.__file__).read_text(encoding="utf-8")
    return ast.parse(source)


def _calls_named(node, name):
    return [
        sub for sub in ast.walk(node)
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
        and sub.func.id == name
    ]


def _np_load_calls(node):
    return [
        sub for sub in ast.walk(node)
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
        and sub.func.attr == "load" and isinstance(sub.func.value, ast.Name)
        and sub.func.value.id == "np"
    ]


def test_module_has_exactly_one_np_load_and_it_is_inside_the_helper():
    tree = _module_tree()
    helper = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_load_snapshot"
    )
    assert len(_np_load_calls(helper)) == 1
    assert len(_np_load_calls(tree)) == 1  # no second direct archive open anywhere


def test_all_four_endpoints_still_use_the_shared_helper():
    """census, equanimity, acoustic and geometry_stl remain the only callers."""
    tree = _module_tree()
    callers = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and _calls_named(node, "_load_snapshot")
    }
    assert callers == {"census", "equanimity", "acoustic", "geometry_stl"}
    for name in callers:
        function = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == name
        )
        assert _np_load_calls(function) == []  # each goes through the helper only


# ===========================================================================
# Pickle refusal -- medusa_api must never unpickle an NPZ member
#
# An object-dtype member is stored as a pickle, so loading one with pickle
# enabled is arbitrary code execution by construction. The payload below is
# harmless: its reduction writes ONE marker file inside pytest's own tmp_path
# and returns. `__reduce__` runs at PICKLE time and only records the callable,
# so writing the archive is inert; the call would happen at UNPICKLE time.
#
# Scope: an object-member refusal, NOT whole-archive validation.
# ===========================================================================

_MA_MARKER = "MEDUSA_PAYLOAD_EXECUTED"


def _create_marker_ma(directory: str) -> str:
    """Stand in for a malicious payload; deliberately inert.

    Module scope is required -- pickle stores a module-qualified reference, so
    a function defined inside a test body could not be resolved at load time.
    """
    marker = Path(directory) / _MA_MARKER
    marker.write_text("payload executed", encoding="utf-8")
    return str(marker)


class _PayloadMa:
    """Its reduction calls the marker writer when unpickled."""

    def __init__(self, directory):
        self._directory = str(directory)

    def __reduce__(self):
        return (_create_marker_ma, (self._directory,))


def _payload_array_ma(directory):
    return np.array([_PayloadMa(directory)], dtype=object)


def _marker_ma(tmp_path):
    return tmp_path / _MA_MARKER


def _write_snapshot_ma(path, compressed=False, **members):
    """A real NPZ. Object members pickle on the way in, which is harmless.

    The edge is 16 and all five schema members are present, because the
    archive now has to be ADMISSIBLE before its member dtypes matter: a 2-cube
    with four members would be refused for its shape and its membership, and
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
    """Point the API's data directory at pytest's own tmp_path.

    Admission confines the archive to the configured data directory, so a
    fixture written anywhere else is refused for CONTAINMENT before the
    property under test is reached.
    """
    monkeypatch.setattr(medusa_api, "DATA_DIR", tmp_path)
    return tmp_path


def test_ma_payload_fixture_actually_fires_when_pickle_is_enabled(tmp_path):
    """Control. Without it, every "marker is absent" assertion below could
    pass against a payload that never worked. This is the only place in this
    module that enables pickle."""
    archive = _write_snapshot_ma(
        tmp_path / "control.npz", lattice=_payload_array_ma(tmp_path)
    )
    assert not _marker_ma(tmp_path).exists()

    with np.load(archive, allow_pickle=True) as snap:
        snap["lattice"]

    assert _marker_ma(tmp_path).exists(), "the payload fixture is inert; fix it"


@pytest.mark.parametrize(
    "field", ["lattice", "memory_grid", "generation", "best_fitness"]
)
def test_object_payload_is_refused_by_the_helper(confined, field):
    """The refusal moved EARLIER, and the code says so.

    An object member used to be caught by NumPy at `np.load`. It is now caught
    by admission from the member's NPY header, before NumPy is involved at
    all -- so the assertion is the typed reason code, not NumPy's message. The
    property that matters is unchanged and stronger: the payload never runs.
    """
    archive = _write_snapshot_ma(
        confined / f"v070_{field}.npz", **{field: _payload_array_ma(confined)}
    )
    with pytest.raises(medusa_api.SnapshotArchiveRejected) as excinfo:
        medusa_api._load_snapshot(archive)
    assert excinfo.value.reason == "member_dtype_object"
    assert not _marker_ma(confined).exists(), "the pickle payload executed"


def test_numpys_own_pickle_refusal_is_still_in_place_behind_admission(confined):
    """Second line of defence, kept non-vacuous.

    Admission now stops an object member first, so the load-site refusal would
    otherwise never be observed again. Calling NumPy directly on the same
    archive shows it is still exactly as it was.
    """
    archive = _write_snapshot_ma(
        confined / "v070_direct.npz", lattice=_payload_array_ma(confined)
    )
    with pytest.raises(ValueError) as excinfo:
        with np.load(archive, allow_pickle=False) as snap:
            snap["lattice"]
    assert "allow_pickle=False" in str(excinfo.value)
    assert not _marker_ma(confined).exists()


def test_a_refused_archive_never_reaches_np_load_at_all(confined, monkeypatch):
    """Stronger than "it was not retried with pickle enabled": NumPy is not
    asked to open the archive even once."""
    archive = _write_snapshot_ma(
        confined / "v070_retry.npz", lattice=_payload_array_ma(confined)
    )
    real_load = np.load
    calls = []

    def _recording_load(*args, **kwargs):
        calls.append(kwargs.get("allow_pickle"))
        return real_load(*args, **kwargs)

    monkeypatch.setattr(medusa_api.np, "load", _recording_load)
    with pytest.raises(medusa_api.SnapshotArchiveRejected):
        medusa_api._load_snapshot(archive)
    assert calls == []


def test_a_valid_archive_is_loaded_with_pickle_explicitly_disabled(confined,
                                                                   monkeypatch):
    """The counterpart control: on the admitted path the explicit literal is
    still what NumPy receives, so the assertion above is about ordering rather
    than about the flag having quietly disappeared."""
    archive = _write_snapshot_ma(confined / "v070_ok.npz", compressed=True)
    real_load = np.load
    calls = []

    def _recording_load(*args, **kwargs):
        calls.append(kwargs.get("allow_pickle"))
        return real_load(*args, **kwargs)

    monkeypatch.setattr(medusa_api.np, "load", _recording_load)
    medusa_api._load_snapshot(archive)
    assert calls == [False]


def test_the_descriptor_is_closed_after_a_refusal(confined, monkeypatch):
    """Closure on the exceptional path, witnessed on the real file object the
    guard opened -- a NumPy handle is never created for a refused archive."""
    archive = _write_snapshot_ma(
        confined / "v070_closed.npz", lattice=_payload_array_ma(confined)
    )
    # Hooked on `os.fdopen`, not `builtins.open`: the guard opens through
    # `os.open` so it can pass O_NONBLOCK and O_NOFOLLOW, and `os.fdopen` is
    # what turns that descriptor into the file object it yields.
    opened = []
    real_fdopen = os.fdopen

    def _tracking_fdopen(*args, **kwargs):
        handle = real_fdopen(*args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(os, "fdopen", _tracking_fdopen)
    with pytest.raises(medusa_api.SnapshotArchiveRejected):
        medusa_api._load_snapshot(archive)
    assert len(opened) == 1, "the archive was opened more than once, or not at all"
    assert opened[0].closed


def test_a_numeric_snapshot_still_loads_all_four_values(confined):
    archive = _write_snapshot_ma(
        confined / "v070_clean.npz", generation=np.int64(3),
        best_fitness=np.float32(0.25)
    )
    lattice, grid, generation, fitness = medusa_api._load_snapshot(archive)
    assert lattice.dtype == np.uint8 and grid.dtype == np.float32
    assert lattice.shape == (16, 16, 16) and grid.shape == (8, 16, 16, 16)
    assert generation == 3 and type(generation) is int
    assert fitness == pytest.approx(0.25) and type(fitness) is float


# -- selection no longer guesses at "tiny/corrupt" ----------------------------


def test_selection_no_longer_skips_a_small_snapshot(confined):
    """The one-megabyte minimum is gone.

    It was a guess and it was wrong in both directions: a sparse but
    structurally valid snapshot compresses far below a megabyte and was never
    selected, while a hostile archive only had to be padded past the threshold
    to be chosen. Selection is now purely "most recent".
    """
    small = Path(_write_snapshot_ma(confined / "v070_gen000001.npz",
                                    compressed=True))
    assert small.stat().st_size < 1_000_000, "the fixture is not small any more"
    assert medusa_api._find_latest_snapshot() == small


def test_selection_falls_back_past_an_unusable_newest_snapshot(confined):
    """The 1 MB rule was not only a filter, it was a SEARCH.

    It walked newest-first and skipped a file that looked unusable, so the API
    kept answering from the previous good snapshot. Replacing it with a bare
    `snapshots[0]` would have let one truncated or hostile archive wedge all
    four snapshot routes at 503 until a fresh snapshot landed — and the
    producer writes straight to its final path with no temporary-and-rename,
    so a partially written archive IS the newest file for as long as the write
    takes. The search is kept; the predicate is now admission.
    """
    good = Path(_write_snapshot_ma(confined / "v070_gen000001.npz",
                                   compressed=True))
    poison = Path(_hostile_ma("missing_member", confined / "v070_gen000002.npz"))
    os.utime(good, (1_000_000, 1_000_000))
    os.utime(poison, (2_000_000, 2_000_000))

    assert medusa_api._find_latest_snapshot() == good

    client = medusa_api.app.test_client()
    response = client.get("/api/census")
    assert response.status_code == 200, (
        "one unusable newest archive must not wedge the route")
    assert response.get_json()["generation"] == 7


def test_selection_is_bounded_and_does_not_scan_the_whole_directory(confined,
                                                                    monkeypatch):
    """The old search walked every snapshot in the directory. Preflighting all
    of a five-figure directory on every request would itself be the denial of
    service, so the window is bounded — and anything older than it is simply
    not considered."""
    depth = medusa_api.SNAPSHOT_SELECTION_DEPTH
    good = Path(_write_snapshot_ma(confined / "v070_gen000000.npz",
                                   compressed=True))
    os.utime(good, (1_000_000, 1_000_000))
    for index in range(depth + 2):
        poison = Path(_hostile_ma("missing_member",
                                  confined / ("v070_gen%06d.npz" % (index + 1))))
        os.utime(poison, (2_000_000 + index, 2_000_000 + index))

    admitted = []
    real_admit = medusa_api.admit_snapshot

    def _counting_admit(path, **kwargs):
        admitted.append(path)
        return real_admit(path, **kwargs)

    monkeypatch.setattr(medusa_api, "admit_snapshot", _counting_admit)
    selected = medusa_api._find_latest_snapshot()

    assert len(admitted) == depth, "the search was not bounded to the window"
    assert selected != good, "a snapshot outside the window must not be found"
    assert selected.name == "v070_gen%06d.npz" % (depth + 2), (
        "when nothing in the window is admissible the newest is still returned")


def _corrupt_crc_ma(path):
    """Break one member's CRC: a valid header over a corrupt body.

    Preflight cannot see this — a payload can only be checked by decompressing
    it, which is the work admission exists to avoid before it decides.
    """
    data = bytearray(Path(path).read_bytes())
    index = data.find(b"PK\x01\x02")
    struct.pack_into("<I", data, index + 16, 0xDEADBEEF)
    Path(path).write_bytes(bytes(data))
    return Path(path)


def test_a_corrupt_payload_becomes_the_same_sanitized_503(confined):
    """Post-admission archive corruption used to escape as `zipfile.BadZipFile`
    — which is not a `ValueError`, so it sailed past every typed handler into a
    500 with a traceback naming the member."""
    archive = _corrupt_crc_ma(
        _write_snapshot_ma(confined / "v070_gen000020.npz", compressed=True))
    client = medusa_api.app.test_client()
    with mock.patch.object(medusa_api, "_find_latest_snapshot",
                           lambda: archive):
        response = client.get("/api/census")
    assert response.status_code == 503
    assert response.get_json() == {"error": "snapshot_rejected"}
    body = response.get_data(as_text=True)
    assert "lattice" not in body and "CRC" not in body
    assert "v070_gen000020" not in body and "Traceback" not in body


def test_a_corrupt_payload_refusal_carries_only_a_reason_code(confined):
    archive = _corrupt_crc_ma(
        _write_snapshot_ma(confined / "v070_gen000021.npz", compressed=True))
    with pytest.raises(medusa_api.SnapshotArchiveRejected) as excinfo:
        medusa_api._load_snapshot(archive)
    assert excinfo.value.reason == "member_payload_unreadable"
    assert str(excinfo.value) == "member_payload_unreadable"


def test_the_descriptor_is_closed_after_a_payload_refusal(confined, monkeypatch):
    archive = _corrupt_crc_ma(
        _write_snapshot_ma(confined / "v070_gen000022.npz", compressed=True))
    opened = []
    real_fdopen = os.fdopen

    def _tracking_fdopen(*args, **kwargs):
        handle = real_fdopen(*args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(os, "fdopen", _tracking_fdopen)
    with pytest.raises(medusa_api.SnapshotArchiveRejected):
        medusa_api._load_snapshot(archive)
    assert len(opened) == 1
    assert opened[0].closed


def test_status_does_not_500_when_the_selected_snapshot_cannot_be_described(
    confined, monkeypatch
):
    """The non-following property has to reach `/api/status`, not stop at
    selection.

    Selection deliberately KEEPS a dangling link or a symlink loop as a
    candidate so it reaches the guard and is refused with a reason — and when
    nothing in the window is admissible it still returns the newest. A
    following, unguarded `.stat()` here then raised `FileNotFoundError`, which
    Flask turns into a 500 and logs with the attacker-chosen path in the
    traceback.

    The status code is the load-bearing assertion. Flask's non-debug 500 body
    is a generic page, so asserting the path is absent from the RESPONSE would
    hold either way — the disclosure was to the server log, not to the caller.
    """
    ghost = confined / "v070_gen_LEAKNAME_0050.npz"
    monkeypatch.setattr(medusa_api, "_find_latest_snapshot", lambda: ghost)
    client = medusa_api.app.test_client()
    response = client.get("/api/status")
    assert response.status_code == 404, (
        "a snapshot that cannot be described reached an unguarded stat()")
    assert response.get_json() == {"error": "No snapshots found"}


def test_status_still_reports_a_real_snapshot(confined):
    """Counterpart control, so the test above is about the missing entry and
    not about `/api/status` having been broken outright."""
    archive = Path(_write_snapshot_ma(confined / "v070_gen000051.npz",
                                      compressed=True))
    client = medusa_api.app.test_client()
    with mock.patch.object(medusa_api, "_find_latest_snapshot",
                           lambda: archive):
        response = client.get("/api/status")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["latest_snapshot"] == "v070_gen000051.npz"
    assert payload["snapshot_size_mb"] >= 0
    assert payload["snapshot_age_seconds"] >= 0


def test_selection_survives_a_snapshot_that_disappears_mid_scan(confined,
                                                                monkeypatch):
    """The glob and the metadata read are separate syscalls, and the producer
    rotates snapshots. A vanished entry must be skipped silently, not raise an
    OSError whose message carries the attacker-chosen path."""
    good = Path(_write_snapshot_ma(confined / "v070_gen000030.npz",
                                   compressed=True))
    ghost = confined / "v070_gen000031.npz"
    real_glob = Path.glob

    def _glob_with_a_ghost(self, pattern):
        return list(real_glob(self, pattern)) + [ghost]

    monkeypatch.setattr(Path, "glob", _glob_with_a_ghost)
    assert medusa_api._find_latest_snapshot() == good

    client = medusa_api.app.test_client()
    response = client.get("/api/census")
    assert response.status_code == 200, "a vanished candidate broke the route"


def test_selection_survives_a_directory_of_only_vanished_candidates(confined,
                                                                    monkeypatch):
    ghosts = [confined / ("v070_gen0000%d.npz" % i) for i in range(40, 45)]
    monkeypatch.setattr(Path, "glob", lambda self, pattern: list(ghosts))
    assert medusa_api._find_latest_snapshot() is None
    client = medusa_api.app.test_client()
    assert client.get("/api/census").status_code == 404


def test_selection_still_prefers_the_most_recent(confined):
    older = Path(_write_snapshot_ma(confined / "v070_gen000001.npz"))
    newer = Path(_write_snapshot_ma(confined / "v070_gen000002.npz"))
    os.utime(older, (1_000_000, 1_000_000))
    os.utime(newer, (2_000_000, 2_000_000))
    assert medusa_api._find_latest_snapshot() == newer


class _TrimeshSentinel(types.ModuleType):
    """A stand-in for `trimesh` that records any attribute reached for.

    `/api/geometry/stl` is the fourth `_load_snapshot` route and the only one
    whose test used to be `importorskip`-gated — so in authoritative CI, which
    does not install trimesh, it never ran at all. It does not need the real
    package: the refusal must happen BEFORE any mesh work, and a sentinel
    proves that far more directly than the real library could, because every
    attribute access is recorded and the assertion is that none occurred.
    """

    def __init__(self):
        super().__init__("trimesh")
        self.touched = []

    def __getattr__(self, name):
        self.touched.append(name)
        raise AssertionError(
            "trimesh.%s was reached on a rejected snapshot" % name)


@pytest.fixture
def trimesh_sentinel(monkeypatch):
    sentinel = _TrimeshSentinel()
    monkeypatch.setitem(sys.modules, "trimesh", sentinel)
    return sentinel


#: A lattice with SOMETHING in it. `geometry_stl` returns 404 for an all-void
#: lattice at `if len(non_void_coords) == 0`, which is BEFORE it touches
#: `trimesh.primitives` — so the default all-zero fixture would make the
#: counterpart control below assert on a module that was never reached, and
#: would let the refusal test's `touched == []` pass through the 404 path
#: instead of through the refusal.
def _non_void_lattice():
    return np.ones((16, 16, 16), dtype=np.uint8)


def test_geometry_route_answers_503_before_touching_trimesh(confined,
                                                            trimesh_sentinel):
    """Runs in CI rather than skipping: the sentinel replaces the dependency.

    `geometry_stl` imports trimesh first and only then loads the snapshot, so
    the import must succeed for the refusal to be reachable at all — and
    nothing on the module may be used once the snapshot is refused.
    """
    archive = _hostile_ma("missing_member", confined / "v070_gen000009.npz")
    client = medusa_api.app.test_client()
    with mock.patch.object(medusa_api, "_find_latest_snapshot",
                           lambda: Path(archive)):
        response = client.get("/api/geometry/stl")
    assert response.status_code == 503
    assert response.get_json() == {"error": "snapshot_rejected"}
    assert trimesh_sentinel.touched == [], (
        "mesh work began before the snapshot was refused")
    body = response.get_data(as_text=True)
    assert "v070_gen000009" not in body and "Traceback" not in body


def test_geometry_route_reaches_trimesh_only_once_a_snapshot_is_admitted(
    confined, trimesh_sentinel
):
    """The counterpart control, so the assertion above is about the REFUSAL
    and not about the route being unreachable for some other reason.

    The lattice must be NON-VOID. With the default all-zero fixture the route
    returns 404 at `len(non_void_coords) == 0` before any mesh work, so this
    control would assert on a module the route never reached — and the refusal
    test above would have been satisfied by that same 404 rather than by the
    refusal it names.
    """
    archive = _write_snapshot_ma(confined / "v070_gen000012.npz",
                                 compressed=True, lattice=_non_void_lattice())
    client = medusa_api.app.test_client()
    with mock.patch.object(medusa_api, "_find_latest_snapshot",
                           lambda: Path(archive)):
        response = client.get("/api/geometry/stl")
    # The sentinel raises on first attribute use, which Flask turns into a 500.
    # What matters is that trimesh WAS reached, i.e. admission let the route
    # through, and that it was reached only after the snapshot was accepted.
    assert trimesh_sentinel.touched, (
        "an admitted snapshot never reached the mesh stage")
    assert trimesh_sentinel.touched[0] == "primitives"
    assert response.status_code != 503


@pytest.mark.parametrize("route,expected", [
    ("/api/health", 200),
    ("/api/status", 200),
    ("/api/telemetry", 404),
])
def test_routes_that_do_not_load_a_snapshot_keep_their_own_behaviour(
    route, expected, confined
):
    """Health, status, telemetry and the raw download do not go through
    `_load_snapshot`, so a poisoned directory must not turn any of them into a
    snapshot refusal.

    Stated exactly, because the obvious phrasing would be wrong: these are not
    all "unchanged and 200". `/api/telemetry` answers 404 in a directory with
    no telemetry file, which is its own established behaviour and is what is
    pinned here. `/api/health` reads no directory at all, so the poisoned file
    is inert for it -- included anyway as the floor of the comparison.
    """
    _hostile_ma("missing_member", confined / "v070_gen000010.npz")
    client = medusa_api.app.test_client()
    response = client.get(route)
    assert response.status_code == expected
    assert response.get_json().get("error") != "snapshot_rejected"


def test_the_raw_snapshot_download_is_unchanged(confined):
    """`/api/snapshot/latest` deliberately serves the file as bytes and does
    not load it, so it is untouched by admission."""
    archive = Path(_write_snapshot_ma(confined / "v070_gen000011.npz"))
    client = medusa_api.app.test_client()
    with mock.patch.object(medusa_api, "_find_latest_snapshot", lambda: archive):
        response = client.get("/api/snapshot/latest")
    assert response.status_code == 200
    assert response.get_data() == archive.read_bytes()


# ===========================================================================
# Structural admission -- a hostile archive must be refused BEFORE np.load,
# and the four snapshot routes must say so without disclosing why
#
# `_load_snapshot` backs four unauthenticated GET routes on a service that
# binds 0.0.0.0. Pickle refusal and archive lifetime say nothing about an
# archive's shape or its cost: an archive could still name members outside the
# schema, carry traversal-bearing entries, declare a payload of hundreds of
# gigabytes, or lie about its own sizes, and every one of those reached
# `np.load` and the allocation behind it -- once per request, for any caller
# who could place a file in `data/`.
#
# The fixtures are built with the standard library, because NumPy cannot write
# a duplicate member, a corrupt NPY magic or a lying shape. None is hostile in
# SIZE: each is a few hundred kilobytes at most, and the oversized cases lie in their headers
# rather than on disk.
# ===========================================================================

import struct  # noqa: E402
import warnings  # noqa: E402
import zipfile  # noqa: E402

_NPY_MAGIC = b"\x93NUMPY"


def _npy_ma(descr, shape, *, fortran=False, payload=None, header=None,
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


def _schema_ma(edge=16, channels=8):
    """The five members a `v070_gen` snapshot carries, at a valid edge."""
    return {
        "lattice.npy": _npy_ma("|u1", (edge, edge, edge)),
        "memory_grid.npy": _npy_ma("<f4", (channels, edge, edge, edge)),
        "generation.npy": _npy_ma("<i8", ()),
        "ca_step.npy": _npy_ma("<i8", ()),
        "best_fitness.npy": _npy_ma("<f8", ()),
    }


def _zip_ma(path, members, *, compressed=True, duplicate=None):
    mode = zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # a duplicate name is the point here
        with zipfile.ZipFile(path, "w", compression=mode) as archive:
            for name, blob in members.items():
                archive.writestr(name, blob)
            if duplicate is not None:
                archive.writestr(duplicate, members[duplicate])
    return str(path)


def _declared_ma(edge, channels=8):
    """The same five members, DECLARING an `edge` it does not carry.

    The guard checks geometry before size arithmetic, so an archive that lies
    about its shape is refused on the geometry rule without the bytes ever
    needing to exist. That is what keeps a 512-edge case at a few kilobytes
    instead of the 4.1 GiB a real 512-cube payload would require.
    """
    members = _schema_ma(16, channels)
    members["lattice.npy"] = _npy_ma(
        "|u1", (edge, edge, edge), payload=b"",
        header="{'descr': '|u1', 'fortran_order': False, 'shape': "
               "(%d, %d, %d), }" % (edge, edge, edge))
    members["memory_grid.npy"] = _npy_ma(
        "<f4", (channels, edge, edge, edge), payload=b"",
        header="{'descr': '<f4', 'fortran_order': False, 'shape': "
               "(%d, %d, %d, %d), }" % (channels, edge, edge, edge))
    return members


def _hostile_ma(kind, path):
    """Build one hostile archive of the named kind at `path`."""
    members = _schema_ma()
    if kind == "duplicate_member":
        return _zip_ma(path, members, duplicate="lattice.npy")
    if kind == "traversal_name":
        members["../../escape.npy"] = _npy_ma("|u1", (1,))
        return _zip_ma(path, members)
    if kind == "backslash_name":
        members["sub\\escape.npy"] = _npy_ma("|u1", (1,))
        return _zip_ma(path, members)
    if kind == "missing_member":
        members.pop("ca_step.npy")
        return _zip_ma(path, members)
    if kind == "extra_member":
        members["surprise.npy"] = _npy_ma("|u1", (1,))
        return _zip_ma(path, members)
    if kind == "oversized_declared_payload":
        members["lattice.npy"] = _npy_ma(
            "|u8", (256, 256, 256), payload=b"",
            header="{'descr': '|u8', 'fortran_order': False, "
                   "'shape': (256, 256, 256), }")
        members["memory_grid.npy"] = _npy_ma(
            "<f4", (8, 256, 256, 256), payload=b"",
            header="{'descr': '<f4', 'fortran_order': False, "
                   "'shape': (8, 256, 256, 256), }")
        return _zip_ma(path, members)
    if kind == "oversized_edge":
        return _zip_ma(path, _declared_ma(512))
    if kind == "header_payload_mismatch":
        members["lattice.npy"] = _npy_ma("|u1", (16, 16, 16)) + b"\x00" * 64
        return _zip_ma(path, members)
    if kind == "invalid_magic":
        members["lattice.npy"] = b"XXXXXX" + members["lattice.npy"][6:]
        return _zip_ma(path, members)
    if kind == "invalid_version":
        blob = bytearray(members["lattice.npy"])
        blob[6] = 9
        members["lattice.npy"] = bytes(blob)
        return _zip_ma(path, members)
    if kind == "invalid_header":
        members["lattice.npy"] = _npy_ma(
            "|u1", (16, 16, 16), header="{'descr': '|u1', 'shape': (1,), }")
        return _zip_ma(path, members)
    if kind == "object_dtype":
        members["generation.npy"] = _npy_ma("|O", (), payload=b"")
        return _zip_ma(path, members)
    if kind == "structured_dtype":
        members["generation.npy"] = _npy_ma(
            "<i8", (), payload=b"",
            header="{'descr': [('payload', '|O'), ('n', '<i4')], "
                   "'fortran_order': False, 'shape': (1,), }")
        return _zip_ma(path, members)
    if kind == "wrong_rank":
        members["lattice.npy"] = _npy_ma("|u1", (16, 16))
        return _zip_ma(path, members)
    if kind == "spatial_mismatch":
        members["memory_grid.npy"] = _npy_ma(
            "<f4", (8, 32, 32, 32), payload=b"",
            header="{'descr': '<f4', 'fortran_order': False, "
                   "'shape': (8, 32, 32, 32), }")
        return _zip_ma(path, members)
    if kind == "fortran_order":
        members["lattice.npy"] = _npy_ma("|u1", (16, 16, 16), fortran=True)
        return _zip_ma(path, members)
    if kind == "not_an_npz":
        Path(path).write_bytes(_npy_ma("|u1", (16, 16, 16)))
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

#: The four routes that go through `_load_snapshot`. `/api/health`,
#: `/api/status`, `/api/telemetry` and `/api/snapshot/latest` deliberately do
#: not, and are asserted unchanged further down.
_SNAPSHOT_ROUTES = ["/api/census", "/api/equanimity", "/api/acoustic"]


@pytest.mark.parametrize("kind", _HOSTILE_KINDS)
def test_hostile_archive_is_refused_before_np_load(kind, tmp_path, monkeypatch):
    """The load-reached recorder is the whole point.

    Asserting only that something was raised would pass on code that let
    `np.load` open, decompress and allocate first and then failed downstream --
    which is exactly the behaviour this replaces.
    """
    archive = _hostile_ma(kind, tmp_path / "v070_gen000001.npz")
    monkeypatch.setattr(medusa_api, "DATA_DIR", tmp_path)

    reached = []
    real_load = np.load

    def _recording_load(*args, **kwargs):
        reached.append(args[:1])
        return real_load(*args, **kwargs)

    monkeypatch.setattr(medusa_api.np, "load", _recording_load)

    with pytest.raises(medusa_api.SnapshotArchiveRejected) as excinfo:
        medusa_api._load_snapshot(archive)
    assert excinfo.value.reason == _EXPECTED_REASON[kind], (
        "the fixture was refused for a different defect than its name claims")
    assert reached == [], "np.load was reached on a hostile archive"


@pytest.mark.parametrize("kind", _HOSTILE_KINDS)
def test_hostile_refusal_names_no_path_member_or_header(kind, tmp_path, monkeypatch):
    """The refusal is translated for an unauthenticated caller, so it must
    carry no archive content in the first place."""
    archive = _hostile_ma(kind, tmp_path / "v070_gen000002.npz")
    monkeypatch.setattr(medusa_api, "DATA_DIR", tmp_path)
    with pytest.raises(ValueError) as excinfo:
        medusa_api._load_snapshot(archive)
    message = str(excinfo.value)
    assert str(tmp_path) not in message
    assert "v070_gen000002" not in message
    assert ".npy" not in message
    assert "descr" not in message and "escape" not in message
    assert message == message.strip() and "\n" not in message


@pytest.mark.parametrize("route", _SNAPSHOT_ROUTES)
@pytest.mark.parametrize("kind", _HOSTILE_KINDS)
def test_snapshot_route_answers_503_snapshot_rejected(
    kind, route, tmp_path, monkeypatch
):
    """One sanitized body for every refusal: no reason, no traceback, no name."""
    archive = _hostile_ma(kind, tmp_path / "v070_gen000003.npz")
    monkeypatch.setattr(medusa_api, "DATA_DIR", tmp_path)
    client = medusa_api.app.test_client()
    with mock.patch.object(medusa_api, "_find_latest_snapshot",
                           lambda: Path(archive)):
        response = client.get(route)

    assert response.status_code == 503
    assert response.get_json() == {"error": "snapshot_rejected"}
    body = response.get_data(as_text=True)
    assert "v070_gen000003" not in body
    assert str(tmp_path) not in body
    assert "Traceback" not in body and ".npy" not in body
