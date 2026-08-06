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
validation, archive security, endpoint totality, API authentication, atomic file
access or whole-server correctness.
"""

from __future__ import annotations

import ast
import os
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


def _load(archive, path=None):
    """Run the real `_load_snapshot` against `archive`; return (result, mock)."""
    load_mock = mock.Mock(return_value=archive)
    target = path if path is not None else _FakeSnapshotPath()
    with mock.patch.object(medusa_api.np, "load", load_mock):
        result = medusa_api._load_snapshot(target)
    return result, load_mock


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
    result, _ = _load(archive)
    assert isinstance(result, tuple) and len(result) == 4
    state, memory_grid, generation, fitness = result
    assert state is contents["lattice"]            # identity, not a copy
    assert memory_grid is contents["memory_grid"]  # identity, not a copy
    assert generation == 1234
    assert fitness == 0.875


def test_generation_is_an_exact_builtin_int():
    archive = _FakeArchive(_contents(generation=np.int64(4242)))
    (_, _, generation, _), _ = _load(archive)
    assert type(generation) is int
    assert generation == 4242


def test_fitness_is_an_exact_builtin_float():
    archive = _FakeArchive(_contents(best_fitness=np.float32(0.5)))
    (_, _, _, fitness), _ = _load(archive)
    assert type(fitness) is float
    assert fitness == 0.5


def test_extraction_order_is_preserved():
    archive = _FakeArchive(_contents())
    _load(archive)
    assert archive.lookups == ["lattice", "memory_grid", "generation", "best_fitness"]


def test_np_load_receives_str_path_and_allow_pickle_false():
    archive = _FakeArchive(_contents())
    path = _FakeSnapshotPath("v070_gen42.npz")
    _, load_mock = _load(archive, path=path)
    assert load_mock.call_count == 1
    args, kwargs = load_mock.call_args
    assert args == (str(path),)
    assert type(args[0]) is str
    assert kwargs == {"allow_pickle": False}


def test_returned_arrays_keep_their_dtypes():
    contents = _contents()
    archive = _FakeArchive(contents)
    (state, memory_grid, _, _), _ = _load(archive)
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
    result, _ = _load(archive)
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
    with mock.patch.object(medusa_api.np, "load", load_mock):
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
    """A real NPZ. Object members pickle on the way in, which is harmless."""
    payload = {
        "lattice": np.zeros((2, 2, 2), dtype=np.uint8),
        "memory_grid": np.zeros((8, 2, 2, 2), dtype=np.float32),
        "generation": 7,
        "best_fitness": 0.5,
    }
    payload.update(members)
    writer = np.savez_compressed if compressed else np.savez
    writer(path, **payload)
    return str(path)


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
def test_object_payload_is_refused_by_the_helper(tmp_path, field):
    """`best_fitness` is unique to this module -- it is the only loader of the
    six that reads a fourth member."""
    archive = _write_snapshot_ma(
        tmp_path / f"{field}.npz", **{field: _payload_array_ma(tmp_path)}
    )
    with pytest.raises(ValueError) as excinfo:
        medusa_api._load_snapshot(archive)
    assert "allow_pickle=False" in str(excinfo.value)
    assert not _marker_ma(tmp_path).exists(), "the pickle payload executed"


def test_a_refusal_is_never_retried_with_pickle_enabled(tmp_path, monkeypatch):
    archive = _write_snapshot_ma(
        tmp_path / "retry.npz", lattice=_payload_array_ma(tmp_path)
    )
    real_load = np.load
    calls = []

    def _recording_load(*args, **kwargs):
        calls.append(kwargs.get("allow_pickle"))
        return real_load(*args, **kwargs)

    monkeypatch.setattr(medusa_api.np, "load", _recording_load)
    with pytest.raises(ValueError):
        medusa_api._load_snapshot(archive)
    assert calls == [False]


def test_the_real_archive_is_closed_after_a_refusal(tmp_path, monkeypatch):
    archive = _write_snapshot_ma(
        tmp_path / "closed.npz", lattice=_payload_array_ma(tmp_path)
    )
    real_load = np.load
    opened = []

    def _tracking_load(*args, **kwargs):
        handle = real_load(*args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(medusa_api.np, "load", _tracking_load)
    with pytest.raises(ValueError):
        medusa_api._load_snapshot(archive)
    assert len(opened) == 1
    assert opened[0].fid is None or opened[0].fid.closed


def test_a_numeric_snapshot_still_loads_all_four_values(tmp_path):
    archive = _write_snapshot_ma(
        tmp_path / "clean.npz", generation=np.int64(3), best_fitness=np.float32(0.25)
    )
    lattice, grid, generation, fitness = medusa_api._load_snapshot(archive)
    assert lattice.dtype == np.uint8 and grid.dtype == np.float32
    assert generation == 3 and type(generation) is int
    assert fitness == pytest.approx(0.25) and type(fitness) is float
