"""Focused tests for the v0.7 engine's resume-snapshot materialisation boundary.

`main()` used to bind the resume `NpzFile` to one of its own locals with
`allow_pickle=True`, no context manager and no `close()`. Two consequences:

* **Archive lifetime spanned the engine run.** Unlike a helper-local archive,
  whose only reference vanishes at helper return, that binding stays reachable
  from the long-lived `main()` frame — so a resumed engine could hold the input
  handle through legacy migration, GPU conversion, telemetry and population
  setup, Acoustic Map construction, every simulation step and every save.
  Extraction and conversion failures had no deterministic close either. The
  bounded claim is excessive and nondeterministic handle lifetime: one
  invocation holds one resume archive, and **no unbounded accumulation is
  demonstrated or asserted**.
* **`--resume` was a pickle-enabled sink.** The path is operator-supplied, yet
  `_save_snapshot()` writes all five required members as ordinary numeric
  arrays/scalars, so no legitimate resume field needs pickle.

`_load_resume_snapshot()` now owns the archive through a context manager and
loads with `allow_pickle=False`.

Nothing here runs a real engine, CA calculation, GPU kernel or CuPy; allocates a
production lattice; writes a repository file, snapshot, telemetry or Acoustic Map
artifact; binds a socket; touches the network; installs a signal handler; or
creates a repository directory. Every temporary file lives beneath `tmp_path`.
Object-dtype refusal is demonstrated with **harmless** objects only — no
malicious pickle is constructed or executed.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import pathlib
import signal as signal_module
import sys
import types
from unittest import mock

import numpy as np
import pytest

import scripts as _scripts_pkg

_ENGINE_MOD = "scripts.continuous_evolution_ca"
_GPU_MOD = "scripts.gpu_accelerator"
_ACOUSTIC_MOD = "scripts.acoustic_map"
_TARGET = "scripts.run_v070_engine"
_MISSING = object()


class Boom(Exception):
    """Distinct failure, so exception identity can be asserted exactly."""


# --------------------------------------------------------------------------- #
# Scoped import harness
# --------------------------------------------------------------------------- #


def _engine_stand_in(name=_ENGINE_MOD):
    module = types.ModuleType(name)
    module.STATE_NAME_TO_ID = {"VOID": 0, "COMPUTE": 2}
    module.init_memory_grid = lambda shape: np.zeros((5,) + tuple(shape), np.float32)
    module.init_telemetry_window = lambda: {"telemetry": True}
    module.load_rule_spec = lambda path: {"rule": "stand-in", "path": path}
    module.reset_telemetry_window = lambda *a, **k: None
    module.step_ca_lattice = lambda *a, **k: None
    module.summarize_telemetry_window = lambda *a, **k: {}
    module.write_telemetry_artifact = lambda *a, **k: None
    module.MARKER = "stand-in"
    return module


def _gpu_stand_in():
    module = types.ModuleType(_GPU_MOD)
    module.GPU_AVAILABLE = False
    module.GPU_NAME = "stand-in"
    return module


def _acoustic_stand_in():
    module = types.ModuleType(_ACOUSTIC_MOD)

    class _AcousticMapConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _AcousticMap:
        instances = []

        def __init__(self, lattice_size=None, config=None):
            self.lattice_size = lattice_size
            self.config = config
            self.sectors_per_dim = 1
            self.updates = []
            _AcousticMap.instances.append(self)

        def update(self, lattice, previous=None):
            self.updates.append(lattice)

    module.AcousticMap = _AcousticMap
    module.AcousticMapConfig = _AcousticMapConfig
    return module


@contextlib.contextmanager
def _contained_imports(stand_ins):
    """Contain every import-time effect the engine module has.

    Patches `sys.modules` **and** the `scripts` package attributes (a dotted
    import can otherwise bind an already-imported real module — the defect that
    surfaced on #433's first head), suppresses signal registration and directory
    creation, and restores `sys.path`, `sys.modules` and package attributes.
    """
    saved_path = list(sys.path)
    saved_attrs = {
        attr: getattr(_scripts_pkg, attr, _MISSING)
        for attr in ("continuous_evolution_ca", "gpu_accelerator", "acoustic_map",
                     "run_v070_engine")
    }
    try:
        with mock.patch.dict(sys.modules, stand_ins), \
             mock.patch.object(signal_module, "signal", lambda *a, **k: None), \
             mock.patch.object(pathlib.Path, "mkdir", lambda *a, **k: None):
            for dotted, module in stand_ins.items():
                setattr(_scripts_pkg, dotted.rsplit(".", 1)[1], module)
            yield
    finally:
        sys.path[:] = saved_path
        for attr, value in saved_attrs.items():
            if value is _MISSING:
                if hasattr(_scripts_pkg, attr):
                    delattr(_scripts_pkg, attr)
            else:
                setattr(_scripts_pkg, attr, value)


def _import_engine_module(name=_TARGET):
    """Load a fresh `run_v070_engine` module object under full containment."""
    source = pathlib.Path(_scripts_pkg.__path__[0]) / "run_v070_engine.py"
    stand_ins = {
        _ENGINE_MOD: _engine_stand_in(),
        _GPU_MOD: _gpu_stand_in(),
        _ACOUSTIC_MOD: _acoustic_stand_in(),
    }
    with _contained_imports(stand_ins):
        spec = importlib.util.spec_from_file_location(name, source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


_PATH_BEFORE = list(sys.path)
_MODULES_BEFORE = set(sys.modules)
engine = _import_engine_module("_run_v070_engine_under_test")
_PATH_AFTER = list(sys.path)


# --------------------------------------------------------------------------- #
# Closure-recording doubles
# --------------------------------------------------------------------------- #


class _FakeArchive:
    """Stand-in for the `NpzFile` returned by `np.load`.

    Records context entry/exit and explicit closure. Defines **no** `__del__`, so
    a recorded closure can never come from finalisation, reference-count timing,
    garbage collection or interpreter shutdown.
    """

    def __init__(self, members=None, access_errors=None):
        self._members = {} if members is None else members
        self._access_errors = {} if access_errors is None else access_errors
        self.entered = 0
        self.exited = 0
        self.closed = 0
        self.accesses = []

    def __enter__(self):
        self.entered += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exited += 1
        self.close()
        return False

    def close(self):
        self.closed += 1

    def __getitem__(self, key):
        self.accesses.append(key)
        if key in self._access_errors:
            raise self._access_errors[key]
        if key not in self._members:
            raise KeyError(key)
        return self._members[key]


def _lattice(shape=(2, 2, 2)):
    return np.zeros(shape, dtype=np.uint8)


def _memory(channels=5, shape=(2, 2, 2)):
    return np.zeros((channels,) + shape, dtype=np.float32)


def _members(**overrides):
    base = {
        "lattice": _lattice(),
        "memory_grid": _memory(),
        "generation": 12,
        "ca_step": 345,
        "best_fitness": 0.75,
    }
    base.update(overrides)
    return base


def _load(archive, path=None):
    """Run the genuine helper against `archive`; return (result, load mock)."""
    target = pathlib.Path("/fake/v070_resume.npz") if path is None else path
    load_mock = mock.Mock(return_value=archive)
    with mock.patch.object(engine.np, "load", load_mock):
        result = engine._load_resume_snapshot(target)
    return result, load_mock


def _load_expecting(archive, exc_type, path=None):
    target = pathlib.Path("/fake/v070_resume.npz") if path is None else path
    load_mock = mock.Mock(return_value=archive)
    with mock.patch.object(engine.np, "load", load_mock):
        with pytest.raises(exc_type) as exc:
            engine._load_resume_snapshot(target)
    return exc


# --------------------------------------------------------------------------- #
# Central pre-fix witness / helper contract
# --------------------------------------------------------------------------- #


def test_archive_is_explicitly_closed_before_the_helper_returns():
    """CENTRAL WITNESS.

    Against the pre-fix engine this fails: extraction happened inline in `main()`
    with no context manager, so a post-extraction seam was reached while the
    explicit close count was still zero. The reference below stays live across
    every assertion, `_FakeArchive` defines no `__del__`, and no test in this
    module calls `gc.collect()`.
    """
    archive = _FakeArchive(_members())
    result, _ = _load(archive)
    assert archive.entered == 1
    assert archive.exited == 1
    assert archive.closed == 1
    assert result is not None
    assert archive is not None
    assert not hasattr(_FakeArchive, "__del__")


def test_helper_returns_a_five_tuple_in_the_established_order():
    members = _members()
    result, _ = _load(_FakeArchive(members))
    assert isinstance(result, tuple)
    assert len(result) == 5
    lattice, memory_grid, generation, ca_step, best_fitness = result
    assert lattice is members["lattice"]
    assert memory_grid is members["memory_grid"]
    assert generation == 12
    assert ca_step == 345
    assert best_fitness == 0.75


def test_scalar_conversions_produce_exact_builtins():
    members = _members(generation=np.int64(7), ca_step=np.int32(9),
                       best_fitness=np.float32(0.5))
    (_, _, generation, ca_step, best_fitness), _ = _load(_FakeArchive(members))
    assert type(generation) is int and generation == 7
    assert type(ca_step) is int and ca_step == 9
    assert type(best_fitness) is float and best_fitness == 0.5


def test_np_load_receives_the_original_path_object_and_refuses_pickle():
    path = pathlib.Path("/fake/dir/v070_resume.npz")
    _, load_mock = _load(_FakeArchive(_members()), path=path)
    args, kwargs = load_mock.call_args
    assert args == (path,)
    assert args[0] is path  # no str() or re-wrapping introduced
    assert kwargs == {"allow_pickle": False}


def test_required_member_access_order_is_exact():
    archive = _FakeArchive(_members())
    _load(archive)
    assert archive.accesses == [
        "lattice", "memory_grid", "generation", "ca_step", "best_fitness",
    ]


@pytest.mark.parametrize(
    "missing",
    ["lattice", "memory_grid", "generation", "ca_step", "best_fitness"],
    ids=["lattice", "memory_grid", "generation", "ca_step", "best_fitness"],
)
def test_missing_required_member_propagates_key_error_and_closes(missing):
    members = _members()
    del members[missing]
    archive = _FakeArchive(members)
    exc = _load_expecting(archive, KeyError)
    assert type(exc.value) is KeyError
    assert archive.exited == 1
    assert archive.closed == 1


@pytest.mark.parametrize(
    "key,bad",
    [("generation", "int"), ("ca_step", "int"), ("best_fitness", "float")],
    ids=["generation_int", "ca_step_int", "best_fitness_float"],
)
def test_conversion_failure_preserves_identity_and_closes(key, bad):
    class _Unconvertible:
        def __int__(self):
            raise Boom(f"{key} conversion failed")

        def __float__(self):
            raise Boom(f"{key} conversion failed")

    archive = _FakeArchive(_members(**{key: _Unconvertible()}))
    exc = _load_expecting(archive, Boom)
    assert type(exc.value) is Boom
    assert str(exc.value) == f"{key} conversion failed"
    assert archive.exited == 1
    assert archive.closed == 1


@pytest.mark.parametrize(
    "error",
    [RuntimeError("unexpected"), MemoryError("oom"), OSError("io failed"),
     ValueError("object arrays")],
    ids=["runtime_error", "memory_error", "os_error", "value_error"],
)
def test_unexpected_member_failure_propagates_and_closes(error):
    archive = _FakeArchive(_members(), access_errors={"memory_grid": error})
    exc = _load_expecting(archive, type(error))
    assert type(exc.value) is type(error)
    assert archive.exited == 1
    assert archive.closed == 1


def test_np_load_failure_propagates_and_enters_no_context():
    archive = _FakeArchive(_members())
    load_mock = mock.Mock(side_effect=OSError("cannot open"))
    with mock.patch.object(engine.np, "load", load_mock):
        with pytest.raises(OSError) as exc:
            engine._load_resume_snapshot(pathlib.Path("/fake/x.npz"))
    assert str(exc.value) == "cannot open"
    assert archive.entered == 0
    assert archive.closed == 0


# --------------------------------------------------------------------------- #
# Real-NumPy behaviour locks (tiny, tmp_path only)
# --------------------------------------------------------------------------- #


def _write_resume(tmp_path, name="v070_resume.npz", **overrides):
    arrays = {
        "lattice": np.zeros((2, 2, 2), dtype=np.uint8),
        "memory_grid": np.zeros((5, 2, 2, 2), dtype=np.float32),
        "generation": np.int64(12),
        "ca_step": np.int64(345),
        "best_fitness": np.float64(0.75),
    }
    arrays.update(overrides)
    path = tmp_path / name
    np.savez_compressed(path, **arrays)
    return path


def test_real_resume_round_trip(tmp_path):
    path = _write_resume(tmp_path)
    lattice, memory, generation, ca_step, fitness = engine._load_resume_snapshot(path)
    assert lattice.shape == (2, 2, 2) and lattice.dtype == np.uint8
    assert memory.shape == (5, 2, 2, 2) and memory.dtype == np.float32
    assert type(generation) is int and generation == 12
    assert type(ca_step) is int and ca_step == 345
    assert type(fitness) is float and fitness == 0.75


def test_real_missing_required_member_raises_key_error(tmp_path):
    path = tmp_path / "partial.npz"
    np.savez_compressed(
        path,
        lattice=np.zeros((2, 2, 2), dtype=np.uint8),
        memory_grid=np.zeros((5, 2, 2, 2), dtype=np.float32),
        generation=np.int64(1),
        ca_step=np.int64(2),
    )
    with pytest.raises(KeyError):
        engine._load_resume_snapshot(path)


@pytest.mark.parametrize(
    "member",
    ["lattice", "memory_grid", "generation", "ca_step", "best_fitness"],
    ids=["lattice", "memory_grid", "generation", "ca_step", "best_fitness"],
)
def test_real_object_dtype_required_member_is_refused(tmp_path, member):
    """A **harmless** object-dtype member — no malicious pickle is built or run.

    With `allow_pickle=True` NumPy would unpickle it; with `allow_pickle=False`
    it is refused before engine startup continues, and the refusal is not caught
    or translated.
    """
    harmless = np.array([{"harmless": 1}], dtype=object)
    path = _write_resume(tmp_path, **{member: harmless})
    with pytest.raises(ValueError) as exc:
        engine._load_resume_snapshot(path)
    assert "pickle" in str(exc.value).lower() or "object" in str(exc.value).lower()


def test_object_dtype_refusal_reaches_no_downstream_seam(tmp_path):
    """The real `np.load` refuses it, so startup never proceeds."""
    harmless = np.array([{"harmless": 1}], dtype=object)
    path = _write_resume(tmp_path, lattice=harmless)
    seams = _StartupSeams()
    with pytest.raises(ValueError):
        _run_main(tmp_path, seams, resume_path=path)
    assert seams.nothing_ran()


# --------------------------------------------------------------------------- #
# Controlled main() startup
# --------------------------------------------------------------------------- #


class _StartupSeams:
    def __init__(self, archive=None):
        self.archive = archive
        self.init_memory_grid = []
        self.to_gpu = []
        self.zeros_like = []
        self.telemetry = []
        self.acoustic = []
        self.steps = []
        self.updates = []
        self.saves = []
        self.load_calls = 0
        self.helper_calls = 0

    def _closed(self):
        return None if self.archive is None else self.archive.closed

    def nothing_ran(self):
        return not any([self.init_memory_grid, self.to_gpu, self.telemetry,
                        self.acoustic, self.steps, self.updates, self.saves])


@contextlib.contextmanager
def _patched_startup(seams, gpu=False, fake_cp=None, step_side_effect=None):
    """Patch every file-producing / engine seam in the module under test."""
    real_helper = engine._load_resume_snapshot

    def _helper(path):
        seams.helper_calls += 1
        return real_helper(path)

    def _init_memory_grid(shape):
        seams.init_memory_grid.append({"closed": seams._closed(),
                                       "shape": tuple(shape)})
        return np.zeros((5,) + tuple(shape), dtype=np.float32)

    def _init_telemetry():
        seams.telemetry.append({"closed": seams._closed()})
        return {"telemetry": True}

    def _to_gpu(arr):
        seams.to_gpu.append({"closed": seams._closed(), "arr": arr})
        return fake_cp.asarray(arr) if fake_cp is not None else arr

    def _save(lattice, memory_grid, generation, ca_step, best_fitness):
        seams.saves.append({"closed": seams._closed(), "generation": generation,
                            "ca_step": ca_step, "best_fitness": best_fitness,
                            "lattice": lattice, "memory_grid": memory_grid})
        return pathlib.Path("/fake/never-written.npz")

    def _step(lattice, rule_spec, rng, inactivity_steps=None, memory_grid=None,
              current_gen=None, telemetry=None):
        seams.steps.append({"closed": seams._closed(), "lattice": lattice,
                            "memory_grid": memory_grid, "current_gen": current_gen,
                            "inactivity": inactivity_steps})
        if step_side_effect is not None:
            step_side_effect()
        return lattice, inactivity_steps, memory_grid, {"density": 1.0}

    acoustic_module = sys.modules.get(_ACOUSTIC_MOD)

    class _RecordingAcousticMap:
        def __init__(self, lattice_size=None, config=None):
            seams.acoustic.append({"closed": seams._closed(),
                                   "lattice_size": lattice_size})
            self.sectors_per_dim = 1

        def update(self, lattice, previous=None):
            seams.updates.append({"closed": seams._closed(), "lattice": lattice})

    patches = [
        mock.patch.object(engine, "_load_resume_snapshot", _helper),
        mock.patch.object(engine, "init_memory_grid", _init_memory_grid),
        mock.patch.object(engine, "init_telemetry_window", _init_telemetry),
        mock.patch.object(engine, "_to_gpu", _to_gpu),
        mock.patch.object(engine, "_save_snapshot", _save),
        mock.patch.object(engine, "step_ca_lattice", _step),
        mock.patch.object(engine, "AcousticMap", _RecordingAcousticMap),
        mock.patch.object(engine, "load_rule_spec", lambda p: {"rule": "stub"}),
        mock.patch.object(engine, "GPU_AVAILABLE", gpu),
        mock.patch.object(engine, "POPULATION_SIZE", 2),
    ]
    if fake_cp is not None:
        patches.append(mock.patch.object(engine, "cp", fake_cp, create=True))
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        yield


def _run_main(tmp_path, seams, argv_extra=(), gpu=False, fake_cp=None,
              running=False, step_side_effect=None, resume_path=None):
    argv = ["run_v070_engine"]
    if resume_path is not None:
        argv += ["--resume", str(resume_path)]
    argv += list(argv_extra)
    engine._running = running
    with _patched_startup(seams, gpu=gpu, fake_cp=fake_cp,
                          step_side_effect=step_side_effect), \
         mock.patch.object(sys, "argv", argv):
        engine.main()


def _resume_via_fake_archive(tmp_path, members=None, name="v070_resume.npz"):
    """A real file for argparse plus a fake archive returned by `np.load`."""
    path = tmp_path / name
    path.write_bytes(b"")
    archive = _FakeArchive(_members() if members is None else members)
    return path, archive


def test_resume_startup_closes_before_every_seam(tmp_path):
    path, archive = _resume_via_fake_archive(tmp_path)
    seams = _StartupSeams(archive)
    with mock.patch.object(engine.np, "load", mock.Mock(return_value=archive)):
        _run_main(tmp_path, seams, resume_path=path)
    assert seams.helper_calls == 1
    assert archive.entered == 1 and archive.exited == 1 and archive.closed == 1
    observed = ([e["closed"] for e in seams.telemetry]
                + [e["closed"] for e in seams.acoustic]
                + [e["closed"] for e in seams.saves])
    assert observed, "startup seams must have been reached"
    assert set(observed) == {1}


def test_modern_memory_grid_skips_migration(tmp_path):
    path, archive = _resume_via_fake_archive(tmp_path)
    seams = _StartupSeams(archive)
    with mock.patch.object(engine.np, "load", mock.Mock(return_value=archive)):
        _run_main(tmp_path, seams, resume_path=path)
    assert seams.init_memory_grid == []


def test_legacy_migration_begins_after_closure_and_is_preserved(tmp_path, capsys):
    legacy = np.arange(3 * 8, dtype=np.float32).reshape((3, 2, 2, 2))
    path, archive = _resume_via_fake_archive(
        tmp_path, members=_members(memory_grid=legacy)
    )
    seams = _StartupSeams(archive)
    with mock.patch.object(engine.np, "load", mock.Mock(return_value=archive)):
        _run_main(tmp_path, seams, resume_path=path)
    assert len(seams.init_memory_grid) == 1
    assert seams.init_memory_grid[0]["closed"] == 1        # after closure
    assert seams.init_memory_grid[0]["shape"] == (2, 2, 2)  # established spatial shape
    out = capsys.readouterr().out
    assert "[MIGRATE] Extended memory grid from 3 to 5 channels (v0.7.5)" in out
    migrated = seams.saves[-1]["memory_grid"]
    np.testing.assert_array_equal(migrated[:3], legacy)     # copied positions
    np.testing.assert_array_equal(
        migrated[3:], np.zeros((2, 2, 2, 2), dtype=np.float32)
    )                                                        # added channels intact


def test_final_save_receives_the_resumed_values(tmp_path):
    path, archive = _resume_via_fake_archive(tmp_path)
    seams = _StartupSeams(archive)
    with mock.patch.object(engine.np, "load", mock.Mock(return_value=archive)):
        _run_main(tmp_path, seams, resume_path=path)
    assert len(seams.saves) == 1
    save = seams.saves[0]
    assert save["closed"] == 1
    assert save["generation"] == 12
    assert save["ca_step"] == 345
    assert save["best_fitness"] == 0.75


def test_no_startup_seam_reopens_or_recloses_the_archive(tmp_path):
    path, archive = _resume_via_fake_archive(tmp_path)
    seams = _StartupSeams(archive)
    with mock.patch.object(engine.np, "load", mock.Mock(return_value=archive)):
        _run_main(tmp_path, seams, resume_path=path)
    assert archive.entered == 1
    assert archive.exited == 1
    assert archive.closed == 1


# --------------------------------------------------------------------------- #
# Controlled one-step run
# --------------------------------------------------------------------------- #


def test_first_step_and_acoustic_update_occur_after_closure(tmp_path):
    path, archive = _resume_via_fake_archive(tmp_path)
    seams = _StartupSeams(archive)

    def _stop():
        engine._running = False

    with mock.patch.object(engine.np, "load", mock.Mock(return_value=archive)):
        _run_main(tmp_path, seams, resume_path=path, running=True,
                  step_side_effect=_stop)
    assert len(seams.steps) == 1
    assert seams.steps[0]["closed"] == 1
    assert seams.steps[0]["current_gen"] == 345          # resumed ca_step
    assert len(seams.updates) == 1
    assert seams.updates[0]["closed"] == 1
    # CA step incremented exactly once: the final save records step + 1.
    assert seams.saves[-1]["ca_step"] == 346
    assert seams.saves[-1]["generation"] == 12


def test_step_receives_the_extracted_arrays(tmp_path):
    members = _members()
    path, archive = _resume_via_fake_archive(tmp_path, members=members)
    seams = _StartupSeams(archive)

    def _stop():
        engine._running = False

    with mock.patch.object(engine.np, "load", mock.Mock(return_value=archive)):
        _run_main(tmp_path, seams, resume_path=path, running=True,
                  step_side_effect=_stop)
    step = seams.steps[0]
    assert step["lattice"] is members["lattice"]
    assert step["memory_grid"] is members["memory_grid"]
    assert step["inactivity"].dtype == np.int16


# --------------------------------------------------------------------------- #
# Controlled GPU startup (fake CuPy surface)
# --------------------------------------------------------------------------- #


class _FakeCuPy:
    """A fake CuPy surface — no device allocation, no kernel execution."""

    def __init__(self):
        self.asarray_calls = []

    def asarray(self, arr):
        self.asarray_calls.append(arr)
        return arr

    @staticmethod
    def sum(arr):
        return np.sum(arr)


def test_gpu_startup_converts_after_closure(tmp_path):
    path, archive = _resume_via_fake_archive(tmp_path)
    seams = _StartupSeams(archive)
    fake_cp = _FakeCuPy()
    with mock.patch.object(engine.np, "load", mock.Mock(return_value=archive)):
        _run_main(tmp_path, seams, resume_path=path, gpu=True, fake_cp=fake_cp)
    assert len(seams.to_gpu) >= 2
    assert all(entry["closed"] == 1 for entry in seams.to_gpu)
    converted = [entry["arr"] for entry in seams.to_gpu]
    assert any(c.dtype == np.uint8 for c in converted)     # lattice
    assert any(c.dtype == np.float32 for c in converted)   # memory grid
    assert fake_cp.asarray_calls, "the fake CuPy surface received the arrays"


# --------------------------------------------------------------------------- #
# Failure containment
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "members,exc_type",
    [
        ({"memory_grid": _memory(), "generation": 1, "ca_step": 2,
          "best_fitness": 0.5}, KeyError),
    ],
    ids=["missing_lattice"],
)
def test_extraction_failure_reaches_no_downstream_seam(tmp_path, members, exc_type):
    path = tmp_path / "v070_resume.npz"
    path.write_bytes(b"")
    archive = _FakeArchive(members)
    seams = _StartupSeams(archive)
    with mock.patch.object(engine.np, "load", mock.Mock(return_value=archive)), \
         pytest.raises(exc_type):
        _run_main(tmp_path, seams, resume_path=path)
    assert seams.nothing_ran()
    assert archive.closed == 1


def test_conversion_failure_reaches_no_downstream_seam(tmp_path):
    class _Unconvertible:
        def __int__(self):
            raise Boom("generation conversion failed")

    path = tmp_path / "v070_resume.npz"
    path.write_bytes(b"")
    archive = _FakeArchive(_members(generation=_Unconvertible()))
    seams = _StartupSeams(archive)
    with mock.patch.object(engine.np, "load", mock.Mock(return_value=archive)), \
         pytest.raises(Boom) as exc:
        _run_main(tmp_path, seams, resume_path=path)
    assert type(exc.value) is Boom
    assert str(exc.value) == "generation conversion failed"
    assert seams.nothing_ran()
    assert archive.closed == 1


# --------------------------------------------------------------------------- #
# No-resume preservation
# --------------------------------------------------------------------------- #


def test_no_resume_never_loads_an_archive(tmp_path):
    seams = _StartupSeams()
    load_mock = mock.Mock()
    helper_mock = mock.Mock()
    with mock.patch.object(engine.np, "load", load_mock), \
         mock.patch.object(engine, "generate_primordial_seed_cube",
                           lambda size: _lattice()) as seed_mock:
        with _patched_startup(seams), \
             mock.patch.object(engine, "_load_resume_snapshot", helper_mock), \
             mock.patch.object(sys, "argv",
                               ["run_v070_engine", "--seed-cube-size", "4"]):
            engine._running = False
            engine.main()
    assert load_mock.call_count == 0
    assert helper_mock.call_count == 0
    assert seams.saves, "startup and shutdown still completed"


def test_no_resume_uses_the_cli_cube_size_and_initial_values(tmp_path):
    seams = _StartupSeams()
    seen = {}

    def _seed(cube_size):
        seen["cube_size"] = cube_size
        return _lattice()

    with mock.patch.object(engine.np, "load", mock.Mock()), \
         _patched_startup(seams), \
         mock.patch.object(engine, "generate_primordial_seed_cube", _seed), \
         mock.patch.object(sys, "argv",
                           ["run_v070_engine", "--seed-cube-size", "4"]):
        engine._running = False
        engine.main()
    assert seen["cube_size"] == 4
    save = seams.saves[-1]
    assert save["generation"] == 0
    assert save["ca_step"] == 0
    assert save["best_fitness"] == 0.0


# --------------------------------------------------------------------------- #
# Import / path / signal / package-attribute isolation
# --------------------------------------------------------------------------- #


def test_sys_path_is_unchanged_by_the_scoped_import():
    assert _PATH_AFTER == _PATH_BEFORE


def test_scoped_import_left_no_stand_in_in_sys_modules():
    for name in (_ENGINE_MOD, _GPU_MOD, _ACOUSTIC_MOD):
        module = sys.modules.get(name)
        if module is not None:
            assert getattr(module, "MARKER", None) != "stand-in"


def test_harness_binds_the_stand_in_not_an_already_imported_decoy():
    """Guards against #433's first-head defect.

    A decoy 'already-imported real engine' is installed on both `sys.modules`
    and the `scripts` package attribute. The harness must bind its own stand-in
    and must neither read nor mutate the decoy.
    """
    decoy = types.ModuleType(_ENGINE_MOD)
    decoy.MARKER = "decoy"
    decoy.STATE_NAME_TO_ID = {"VOID": 0}
    decoy.init_memory_grid = lambda shape: None
    decoy.init_telemetry_window = lambda: None
    decoy.load_rule_spec = lambda path: None
    decoy.reset_telemetry_window = lambda *a, **k: None
    decoy.step_ca_lattice = lambda *a, **k: None
    decoy.summarize_telemetry_window = lambda *a, **k: None
    decoy.write_telemetry_artifact = lambda *a, **k: None
    decoy.touched = False

    with mock.patch.dict(sys.modules, {_ENGINE_MOD: decoy}), \
         mock.patch.object(_scripts_pkg, "continuous_evolution_ca", decoy,
                           create=True):
        fresh = _import_engine_module("_run_v070_engine_decoy_probe")
        assert fresh.init_memory_grid is not decoy.init_memory_grid
        assert getattr(fresh, "STATE_NAME_TO_ID") == {"VOID": 0, "COMPUTE": 2}
        assert decoy.touched is False
        assert decoy.MARKER == "decoy"
    assert sys.modules.get(_ENGINE_MOD) is not decoy


def test_no_signal_handler_was_installed_by_the_import():
    for sig in (signal_module.SIGINT, signal_module.SIGTERM):
        handler = signal_module.getsignal(sig)
        assert handler is not engine._handle_signal


# --------------------------------------------------------------------------- #
# Structural ownership checks (supplementary)
# --------------------------------------------------------------------------- #


def _module_tree():
    source = pathlib.Path(_scripts_pkg.__path__[0]) / "run_v070_engine.py"
    return ast.parse(source.read_text(encoding="utf-8"))


def _function(tree, name):
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name)


def _np_load_calls(node):
    return [s for s in ast.walk(node) if isinstance(s, ast.Call)
            and isinstance(s.func, ast.Attribute) and s.func.attr == "load"
            and isinstance(s.func.value, ast.Name) and s.func.value.id == "np"]


def _with_context_calls(node):
    found = []
    for sub in ast.walk(node):
        if isinstance(sub, (ast.With, ast.AsyncWith)):
            for item in sub.items:
                if isinstance(item.context_expr, ast.Call):
                    found.append(item.context_expr)
    return found


def test_helper_holds_exactly_one_context_managed_load_without_pickle():
    tree = _module_tree()
    helper = _function(tree, "_load_resume_snapshot")
    loads = _np_load_calls(helper)
    assert len(loads) == 1
    assert loads[0] in _with_context_calls(helper)
    keywords = {kw.arg: kw.value for kw in loads[0].keywords}
    assert "allow_pickle" in keywords
    assert keywords["allow_pickle"].value is False


def test_all_member_accesses_and_conversions_are_inside_the_context():
    tree = _module_tree()
    helper = _function(tree, "_load_resume_snapshot")
    with_nodes = [n for n in ast.walk(helper) if isinstance(n, ast.With)]
    assert len(with_nodes) == 1
    inside = ast.walk(with_nodes[0])
    subscripts = [n for n in inside if isinstance(n, ast.Subscript)]
    keys = {n.slice.value for n in subscripts
            if isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str)}
    assert keys == {"lattice", "memory_grid", "generation", "ca_step",
                    "best_fitness"}
    conversions = [n.func.id for n in ast.walk(with_nodes[0])
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert conversions.count("int") == 2
    assert conversions.count("float") == 1


def test_helper_return_occurs_after_the_context():
    tree = _module_tree()
    helper = _function(tree, "_load_resume_snapshot")
    returns = [n for n in helper.body if isinstance(n, ast.Return)]
    assert len(returns) == 1  # a top-level return, not nested in the `with`


def test_main_opens_no_archive_and_calls_the_helper_once():
    tree = _module_tree()
    main_fn = _function(tree, "main")
    assert _np_load_calls(main_fn) == []
    helper_calls = [n for n in ast.walk(main_fn)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "_load_resume_snapshot"]
    assert len(helper_calls) == 1


def test_module_exposes_exactly_one_resume_loading_helper():
    tree = _module_tree()
    helpers = [n.name for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and _np_load_calls(n)]
    assert helpers == ["_load_resume_snapshot"]
