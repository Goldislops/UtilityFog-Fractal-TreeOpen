"""Focused tests for `vis/observatory/loader.py` NPZ archive resource lifetime.

`load_npz()` used to keep the `NpzFile` returned by `np.load` referenced through
legacy-grid migration (which imports the engine and can be expensive), the
fallback zero-padding, both `.astype()` conversions, the metadata lookups and the
return — released only by eventual object destruction. `load_snapshot_series()`
calls it once per file, so every series member inherited that behaviour. On
Windows a retained handle can interfere with deleting, rotating or replacing a
snapshot.

All five values are now materialised while the archive is open and it closes
deterministically before any of that later work begins.

Deliberately separate from the rendering-heavy `tests/test_observatory.py`, which
is untouched: this module needs no matplotlib, loads no real Medusa snapshot and
runs no visualization. Archive lifecycle is exercised with a closure-recording
fake, and the legacy-migration path is driven through a controlled stand-in at
the exact import seam. Nothing is written inside the repository.

Scope is archive resource lifetime relative to extraction — not an indefinitely
accumulating descriptor leak, not snapshot validation, not migration policy.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest import mock

import numpy as np
import pytest


def _import_loader():
    """Return the genuine `vis.observatory.loader` module.

    `vis/__init__.py` eagerly imports the matplotlib-backed plotting modules, so
    a plain import would fail wherever matplotlib is absent — but the loader
    contract under test needs only NumPy, and this module must not be skipped for
    a rendering dependency it does not use. Where the plotting stack is present
    (as in maintained CI) the ordinary import is used and nothing is stubbed.
    Otherwise minimal namespace packages stand in for `vis` / `vis.observatory`
    just long enough to load the real `loader.py` from disk, and `sys.modules` is
    restored afterwards so no later test sees a half-initialised `vis`.
    """
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        pass
    else:
        return importlib.import_module("vis.observatory.loader")

    repo_root = Path(__file__).resolve().parents[1]
    added = []
    for name, directory in (
        ("vis", repo_root / "vis"),
        ("vis.observatory", repo_root / "vis" / "observatory"),
    ):
        if name not in sys.modules:
            package = types.ModuleType(name)
            package.__path__ = [str(directory)]
            sys.modules[name] = package
            added.append(name)
    try:
        module = importlib.import_module("vis.observatory.loader")
    finally:
        for name in added:
            sys.modules.pop(name, None)
        sys.modules.pop("vis.observatory.constants", None)
        sys.modules.pop("vis.observatory.loader", None)
    return module


loader = _import_loader()
NUM_CHANNELS = loader.NUM_CHANNELS
MIGRATION_MODULE = "scripts.continuous_evolution_ca"


class Boom(Exception):
    """Distinct extraction failure, so propagation can be asserted exactly."""


class _ExplodingInt:
    def __int__(self):
        raise Boom("generation conversion failed")


class _ExplodingFloat:
    def __float__(self):
        raise Boom("fitness conversion failed")


class _FakeArchive:
    """Stand-in for the `NpzFile` that `np.load` returns.

    Records context entry/exit, explicit closure, key lookups and `.get()` calls.
    Defines **no** `__del__`, so a recorded closure can never have come from
    garbage collection or finalisation.
    """

    def __init__(self, contents=None, raise_on=None, raise_on_get=None):
        self.contents = {} if contents is None else contents
        self.raise_on = raise_on
        self.raise_on_get = raise_on_get
        self.entered = 0
        self.exited = 0
        self.closed = 0
        self.lookups = []
        self.gets = []

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

    def get(self, key, default=None):
        self.gets.append(key)
        if self.raise_on_get == key:
            raise KeyError(key)
        return self.contents.get(key, default)


def _lattice(size=2):
    return np.arange(size ** 3, dtype=np.uint8).reshape(size, size, size)


def _grid(channels=NUM_CHANNELS, size=2):
    return np.arange(channels * size ** 3, dtype=np.float32).reshape(
        (channels, size, size, size)
    )


def _contents(**overrides):
    base = {
        "lattice": _lattice(),
        "memory_grid": _grid(),
        "generation": 1234,
        "ca_step": 99,
        "best_fitness": 0.75,
    }
    base.update(overrides)
    return base


def _load(archive, path="/fake/v070_gen1.npz"):
    """Run the real `load_npz` against `archive`; return (snapshot, load mock)."""
    load_mock = mock.Mock(return_value=archive)
    with mock.patch.object(loader.np, "load", load_mock):
        snapshot = loader.load_npz(path)
    return snapshot, load_mock


# -- successful load ----------------------------------------------------------


def test_successful_load_returns_the_same_values():
    contents = _contents()
    archive = _FakeArchive(contents)
    snapshot, _ = _load(archive, path="/fake/dir/v070_gen1234.npz")
    np.testing.assert_array_equal(snapshot.lattice, contents["lattice"])
    np.testing.assert_array_equal(snapshot.memory_grid, contents["memory_grid"])
    assert snapshot.generation == 1234
    assert snapshot.ca_step == 99
    assert snapshot.best_fitness == 0.75
    assert snapshot.source_path == str(Path("/fake/dir/v070_gen1234.npz"))


def test_dtype_conversions_are_preserved():
    archive = _FakeArchive(_contents(lattice=_lattice().astype(np.int32),
                                    memory_grid=_grid().astype(np.float64)))
    snapshot, _ = _load(archive)
    assert snapshot.lattice.dtype == np.uint8
    assert snapshot.memory_grid.dtype == np.float32


def test_np_load_receives_str_path_and_allow_pickle():
    archive = _FakeArchive(_contents())
    _, load_mock = _load(archive, path=Path("/fake/dir/v070_gen7.npz"))
    assert load_mock.call_count == 1
    args, kwargs = load_mock.call_args
    assert args == (str(Path("/fake/dir/v070_gen7.npz")),)
    assert type(args[0]) is str
    assert kwargs == {"allow_pickle": True}


def test_metadata_defaults_are_preserved_when_keys_are_absent():
    archive = _FakeArchive({"lattice": _lattice(), "memory_grid": _grid()})
    snapshot, _ = _load(archive)
    assert snapshot.generation == 0
    assert snapshot.ca_step == 0
    assert snapshot.best_fitness == 0.0
    assert type(snapshot.generation) is int
    assert type(snapshot.ca_step) is int
    assert type(snapshot.best_fitness) is float


def test_metadata_conversions_are_applied():
    archive = _FakeArchive(_contents(generation=np.int64(5), ca_step=np.int64(6),
                                     best_fitness=np.float32(0.5)))
    snapshot, _ = _load(archive)
    assert type(snapshot.generation) is int and snapshot.generation == 5
    assert type(snapshot.ca_step) is int and snapshot.ca_step == 6
    assert type(snapshot.best_fitness) is float and snapshot.best_fitness == 0.5


# -- closure on success -------------------------------------------------------


def test_archive_context_entered_exactly_once():
    archive = _FakeArchive(_contents())
    _load(archive)
    assert archive.entered == 1


def test_archive_closed_exactly_once_on_success():
    archive = _FakeArchive(_contents())
    _load(archive)
    assert archive.exited == 1
    assert archive.closed == 1


def test_archive_already_closed_when_load_npz_returns():
    """Asserted immediately after the return, while this frame still holds a
    live reference — so closure was explicit."""
    archive = _FakeArchive(_contents())
    snapshot, _ = _load(archive)
    assert archive.closed == 1
    assert snapshot.generation == 1234


def test_closure_does_not_depend_on_finalisation():
    """No `__del__` on the fake and the reference stays alive, so the recorded
    closure cannot have come from reference-count timing or a gc pass. No test
    here calls gc.collect()."""
    assert not hasattr(_FakeArchive, "__del__")
    archive = _FakeArchive(_contents())
    _load(archive)
    assert archive.closed == 1
    assert archive is not None


def test_all_five_values_are_read_while_the_archive_is_open():
    archive = _FakeArchive(_contents())
    _load(archive)
    assert archive.lookups == ["lattice", "memory_grid"]
    assert archive.gets == ["generation", "ca_step", "best_fitness"]


# -- closure on every extraction failure --------------------------------------


@pytest.mark.parametrize("missing", ["lattice", "memory_grid"],
                         ids=["lattice", "memory_grid"])
def test_archive_closes_when_a_required_lookup_raises(missing):
    archive = _FakeArchive(_contents(), raise_on=missing)
    with pytest.raises(KeyError):
        _load(archive)
    assert archive.exited == 1
    assert archive.closed == 1


@pytest.mark.parametrize("key", ["generation", "ca_step", "best_fitness"],
                         ids=["generation", "ca_step", "best_fitness"])
def test_archive_closes_when_a_metadata_lookup_raises(key):
    archive = _FakeArchive(_contents(), raise_on_get=key)
    with pytest.raises(KeyError):
        _load(archive)
    assert archive.exited == 1
    assert archive.closed == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"generation": _ExplodingInt()},
        {"ca_step": _ExplodingInt()},
        {"best_fitness": _ExplodingFloat()},
    ],
    ids=["generation_int", "ca_step_int", "best_fitness_float"],
)
def test_archive_closes_when_a_metadata_conversion_raises(overrides):
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

    missing = _FakeArchive(_contents(), raise_on="lattice")
    with pytest.raises(KeyError) as exc2:
        _load(missing)
    assert type(exc2.value) is KeyError
    assert missing.closed == 1


# -- legacy-grid migration ordering (central witness) -------------------------


def _legacy_load(archive, migrate=None, import_error=False):
    """Load a legacy-grid snapshot, driving the migration import seam.

    The engine is never imported or executed: a controlled module stand-in is
    installed at `scripts.continuous_evolution_ca` for the duration.
    """
    calls = []

    def _default_migrate(grid, shape):
        calls.append({"closed": archive.closed, "grid": grid, "shape": shape})
        return np.zeros((NUM_CHANNELS,) + tuple(shape), dtype=np.float32)

    migrate_fn = migrate or _default_migrate
    if import_error:
        patched = {MIGRATION_MODULE: None}  # `import` of a None entry -> ImportError
    else:
        stub = types.ModuleType(MIGRATION_MODULE)
        stub._migrate_memory_grid = migrate_fn
        patched = {MIGRATION_MODULE: stub}

    load_mock = mock.Mock(return_value=archive)
    with mock.patch.dict(sys.modules, patched), \
         mock.patch.object(loader.np, "load", load_mock):
        snapshot = loader.load_npz("/fake/legacy.npz")
    return snapshot, calls


def test_archive_is_closed_before_legacy_migration_begins():
    """Central witness. Pre-fix the archive was still open here: migration was
    entered with the handle retained (recorded closed == 0)."""
    archive = _FakeArchive(_contents(memory_grid=_grid(channels=3)))
    snapshot, calls = _legacy_load(archive)
    assert len(calls) == 1, "migration seam must have been reached"
    assert calls[0]["closed"] == 1, "archive must be closed before migration"
    assert archive.entered == 1
    assert archive.exited == 1
    assert archive.closed == 1
    assert snapshot.memory_grid.shape == (NUM_CHANNELS, 2, 2, 2)


def test_legacy_migration_receives_the_extracted_grid_and_lattice_shape():
    legacy = _grid(channels=3)
    archive = _FakeArchive(_contents(memory_grid=legacy))
    _, calls = _legacy_load(archive)
    np.testing.assert_array_equal(calls[0]["grid"], legacy)
    assert tuple(calls[0]["shape"]) == (2, 2, 2)


def test_migrated_device_array_result_still_gets_converted_to_numpy():
    class _FakeDeviceArray:
        def __init__(self, array):
            self._array = array
            self.get_calls = 0

        def get(self):
            self.get_calls += 1
            return self._array

    migrated = np.ones((NUM_CHANNELS, 2, 2, 2), dtype=np.float32)
    device = _FakeDeviceArray(migrated)
    archive = _FakeArchive(_contents(memory_grid=_grid(channels=5)))
    snapshot, _ = _legacy_load(archive, migrate=lambda grid, shape: device)
    assert device.get_calls == 1
    assert isinstance(snapshot.memory_grid, np.ndarray)
    assert snapshot.memory_grid.dtype == np.float32
    np.testing.assert_array_equal(snapshot.memory_grid, migrated)
    assert archive.closed == 1


def test_import_error_fallback_zero_pads_to_eight_channels():
    legacy = _grid(channels=3)
    archive = _FakeArchive(_contents(memory_grid=legacy))
    snapshot, calls = _legacy_load(archive, import_error=True)
    assert calls == []  # migration never ran
    assert snapshot.memory_grid.shape == (NUM_CHANNELS, 2, 2, 2)
    assert snapshot.memory_grid.dtype == np.float32
    np.testing.assert_array_equal(snapshot.memory_grid[:3], legacy)
    np.testing.assert_array_equal(
        snapshot.memory_grid[3:],
        np.zeros((NUM_CHANNELS - 3, 2, 2, 2), dtype=np.float32),
    )
    assert archive.closed == 1


def test_eight_channel_grid_skips_migration_entirely():
    archive = _FakeArchive(_contents())
    snapshot, calls = _legacy_load(archive)
    assert calls == []
    assert snapshot.memory_grid.shape == (NUM_CHANNELS, 2, 2, 2)


# -- load_snapshot delegation -------------------------------------------------


def test_load_snapshot_delegates_npz_to_the_closing_loader():
    """Not a patched-away delegation check: the real `load_npz` runs, so the
    archive closure is observed through `load_snapshot`."""
    archive = _FakeArchive(_contents())
    load_mock = mock.Mock(return_value=archive)
    with mock.patch.object(loader.np, "load", load_mock):
        snapshot = loader.load_snapshot(Path("/fake/v070_gen1.npz"))
    assert load_mock.call_count == 1
    assert archive.closed == 1
    assert snapshot.generation == 1234


# -- load_snapshot_series per-file closure ------------------------------------


def _series_dir(tmp_path, names):
    for name in names:
        (tmp_path / name).write_bytes(b"")  # np.load is mocked; contents unused
    return tmp_path


def test_series_closes_each_archive_before_the_next_load(tmp_path):
    directory = _series_dir(tmp_path, ["v070_gen1.npz", "v070_gen2.npz",
                                       "v070_gen10.npz"])
    archives = [_FakeArchive(_contents(generation=n)) for n in (1, 2, 10)]
    issued = []
    closure_states = []

    def _next_archive(*args, **kwargs):
        closure_states.append([a.closed for a in issued])
        archive = archives[len(issued)]
        issued.append(archive)
        return archive

    with mock.patch.object(loader.np, "load", side_effect=_next_archive):
        snapshots = loader.load_snapshot_series(directory)

    assert len(snapshots) == 3
    # Every previously issued archive was already closed when the next load began.
    assert closure_states == [[], [1], [1, 1]]
    assert [a.closed for a in archives] == [1, 1, 1]
    assert [a.exited for a in archives] == [1, 1, 1]
    # Established natural ordering is untouched: gen2 before gen10.
    assert [s.generation for s in snapshots] == [1, 2, 10]


def test_series_load_failure_closes_the_failing_archive_and_propagates(tmp_path):
    directory = _series_dir(tmp_path, ["v070_gen1.npz", "v070_gen2.npz"])
    first = _FakeArchive(_contents(generation=1))
    second = _FakeArchive(_contents(), raise_on="lattice")
    with mock.patch.object(loader.np, "load", side_effect=[first, second]):
        with pytest.raises(KeyError) as exc:
            loader.load_snapshot_series(directory)
    assert type(exc.value) is KeyError
    assert first.closed == 1
    assert second.exited == 1
    assert second.closed == 1


def test_series_respects_max_count_without_loading_extra_archives(tmp_path):
    directory = _series_dir(tmp_path, ["v070_gen1.npz", "v070_gen2.npz",
                                       "v070_gen3.npz"])
    archives = [_FakeArchive(_contents(generation=n)) for n in (1, 2)]
    load_mock = mock.Mock(side_effect=archives)
    with mock.patch.object(loader.np, "load", load_mock):
        snapshots = loader.load_snapshot_series(directory, max_count=2)
    assert len(snapshots) == 2
    assert load_mock.call_count == 2
    assert [a.closed for a in archives] == [1, 1]
