"""Focused tests for `scripts/gpu_benchmark` snapshot-archive resource lifetime.

`run_benchmarks()` used to do `snap = np.load(...)` inline and keep the returned
`NpzFile` referenced for the whole suite — shape and cell-count calculations,
`load_rule_spec`, legacy memory-grid expansion, RNG and inactivity construction,
the temporary CPU/GPU global switch, every component benchmark with all its
warmups and iterations, every full `step_ca_lattice` step, the timing
aggregation and the printed summary. A run therefore held the input handle
across an operator-selected number of steps, released only by eventual object
destruction. On Windows a retained snapshot handle can interfere with deleting,
rotating or replacing that file.

`_load_snapshot()` now bounds the archive to extraction and closes it before
returning.

No real benchmark, engine, GPU kernel, snapshot or persistent output is used:
`scripts.continuous_evolution_ca` is replaced by a scoped stand-in (the
production module imports it at load time), `benchmark_component` is a
deterministic recorder rather than a timing loop, arrays are 2x2x2, and
`np.load` returns a closure-recording fake. The pickle-refusal tests
appended at the end DO write real NPZ archives, but only inside pytest's
own `tmp_path`.

Two further sections were added later, and are named here because this
docstring previously listed the first of them as explicitly OUT of scope:

  * TEMPORARY-BACKEND FAILURE ATOMICITY. `run_benchmarks()` forces the engine
    module's `GPU_AVAILABLE`/`_xp` globals to CPU for the three CPU component
    benchmarks. The restore used to run on the success path only, so any
    failure in between left process-global backend state pinned to CPU.
  * NONPOSITIVE STEP COUNTS, which used to travel through snapshot loading,
    the backend switch and every component benchmark before failing in the
    timing aggregation.

Scope is archive resource lifetime relative to extraction, the exception
atomicity of that temporary backend switch, and the step-count guard — not
snapshot validation, benchmark mathematics, timing methodology, or
`benchmark_component()`'s own contract.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

import scripts as _scripts_package

_ENGINE = "scripts.continuous_evolution_ca"
_ENGINE_ATTR = "continuous_evolution_ca"


def _engine_stand_in():
    """A stand-in for the engine module the benchmark imports at load time."""
    module = types.ModuleType(_ENGINE)
    module.step_ca_lattice = lambda *a, **k: None
    module.count_neighbors_3d = lambda *a, **k: None
    module.load_rule_spec = lambda *a, **k: None
    module.init_memory_grid = lambda *a, **k: None
    module._separable_box_filter_3d = lambda *a, **k: None
    module._max_neighbor_value = lambda *a, **k: None
    module.GPU_AVAILABLE = False
    module._xp = np
    return module


# The production module does a top-level `from scripts.continuous_evolution_ca
# import ...`, so the engine is replaced for the duration of the import and
# `sys.modules` is restored immediately afterwards. The real engine is never
# imported or executed by this file.
with mock.patch.dict(sys.modules, {_ENGINE: _engine_stand_in()}):
    from scripts import gpu_benchmark


class Boom(Exception):
    """Distinct conversion failure, so propagation can be asserted exactly."""


class _ExplodingInt:
    def __int__(self):
        raise Boom("generation conversion failed")


class _FakeArchive:
    """Stand-in for the `NpzFile` that `np.load` returns.

    Records context entry/exit, explicit closure and key lookups. Defines **no**
    `__del__`, so a recorded closure can never have come from garbage
    collection, reference-count timing or interpreter shutdown.
    """

    def __init__(self, contents=None, raise_on=None):
        self.contents = {} if contents is None else contents
        self.raise_on = raise_on
        self.entered = 0
        self.exited = 0
        self.closed = 0
        self.lookups = []
        self.rec = None  # reachable after a propagated exception

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


def _lattice(size=2):
    return np.zeros((size, size, size), dtype=np.uint8)


def _grid(channels=8, size=2):
    return np.zeros((channels, size, size, size), dtype=np.float32)


def _contents(**overrides):
    base = {"lattice": _lattice(), "memory_grid": _grid(), "generation": 1000}
    base.update(overrides)
    return base


def _load(archive, path=None):
    """Run the real `_load_snapshot` against `archive`; return (result, mock)."""
    load_mock = mock.Mock(return_value=archive)
    target = path if path is not None else Path("/fake/v070_gen1000.npz")
    with mock.patch.object(gpu_benchmark.np, "load", load_mock):
        result = gpu_benchmark._load_snapshot(target)
    return result, load_mock


# -- helper contract ----------------------------------------------------------


def test_helper_returns_the_exact_objects_in_order():
    contents = _contents()
    archive = _FakeArchive(contents)
    result, _ = _load(archive)
    assert isinstance(result, tuple) and len(result) == 3
    lattice, memory_grid, generation = result
    assert lattice is contents["lattice"]            # identity, not a copy
    assert memory_grid is contents["memory_grid"]    # identity, not a copy
    assert generation == 1000


def test_generation_is_an_exact_builtin_int():
    archive = _FakeArchive(_contents(generation=np.int64(4242)))
    (_, _, generation), _ = _load(archive)
    assert type(generation) is int
    assert generation == 4242


def test_np_load_receives_the_original_path_object_and_allow_pickle_false():
    """No path conversion is introduced: the very object passed in is forwarded."""
    path = Path("/fake/dir/v070_gen7.npz")
    _, load_mock = _load(_FakeArchive(_contents()), path=path)
    assert load_mock.call_count == 1
    args, kwargs = load_mock.call_args
    assert args == (path,)
    assert args[0] is path
    assert kwargs == {"allow_pickle": False}


def test_extraction_order_is_preserved():
    archive = _FakeArchive(_contents())
    _load(archive)
    assert archive.lookups == ["lattice", "memory_grid", "generation"]


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


def test_archive_already_closed_when_the_helper_returns():
    """Asserted immediately after the return, while this frame still holds a
    live reference to the archive — so closure was explicit."""
    archive = _FakeArchive(_contents())
    result, _ = _load(archive)
    assert archive.closed == 1
    assert result[2] == 1000


def test_closure_does_not_depend_on_finalisation():
    """No `__del__` on the fake and the reference stays alive, so the recorded
    closure cannot come from gc, reference-count timing or interpreter
    shutdown. No test here calls gc.collect()."""
    assert not hasattr(_FakeArchive, "__del__")
    archive = _FakeArchive(_contents())
    _load(archive)
    assert archive.closed == 1
    assert archive is not None


# -- closure on every extraction / conversion failure -------------------------


@pytest.mark.parametrize(
    "missing", ["lattice", "memory_grid", "generation"],
    ids=["lattice", "memory_grid", "generation"],
)
def test_archive_closes_when_a_key_lookup_raises(missing):
    archive = _FakeArchive(_contents(), raise_on=missing)
    with pytest.raises(KeyError):
        _load(archive)
    assert archive.exited == 1
    assert archive.closed == 1


def test_archive_closes_when_the_generation_conversion_raises():
    archive = _FakeArchive(_contents(generation=_ExplodingInt()))
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


@pytest.mark.parametrize(
    "error",
    [OSError("archive read failed"), RuntimeError("boom"), MemoryError("oom"),
     ValueError("bad zip")],
    ids=["os_error", "runtime_error", "memory_error", "value_error"],
)
def test_np_load_failure_propagates_unchanged(error):
    """No blanket except was added, and no archive was ever entered."""
    load_mock = mock.Mock(side_effect=error)
    with mock.patch.object(gpu_benchmark.np, "load", load_mock):
        with pytest.raises(type(error)) as exc:
            gpu_benchmark._load_snapshot(Path("/fake/x.npz"))
    assert type(exc.value) is type(error)
    assert str(exc.value) == str(error)


# -- controlled run_benchmarks() ----------------------------------------------


class _Recorder:
    def __init__(self, archive):
        self.archive = archive
        self.load_rule_spec = []
        self.init_memory_grid = []
        self.components = []
        self.steps = []
        self.measured = []  # what the measured callables actually received
        self.random_rand = []  # CPU preparation between two components


def _run_benchmarks(contents=None, archive=None, num_steps=1, raise_on=None,
                    component_errors=None, random_rand_error=None,
                    capture=None):
    """Drive the genuine `run_benchmarks()` with every seam controlled.

    Returns (archive, recorder). Nothing real is benchmarked: the engine is a
    scoped stand-in, `benchmark_component` is a deterministic recorder rather
    than a timing loop, and the arrays are 2x2x2.

    `component_errors` maps a component name to an exception raised instead of
    running it; `random_rand_error` does the same for the `np.random.rand` call
    that prepares the box-filter input between two of them. `capture`, if
    given, is populated with the engine stand-in and its sentinel BEFORE the
    run starts, so a test can inspect the engine's globals even when the run
    raises and never reaches the return.
    """
    archive = archive if archive is not None else _FakeArchive(
        _contents() if contents is None else contents, raise_on=raise_on
    )
    rec = _Recorder(archive)
    archive.rec = rec
    engine = _engine_stand_in()
    sentinel_xp = object()
    engine.GPU_AVAILABLE = True      # a distinctive prior value...
    engine._xp = sentinel_xp         # ...so restoration is observable
    component_errors = dict(component_errors or {})
    if capture is not None:
        capture["engine"] = engine
        capture["sentinel_xp"] = sentinel_xp
        capture["archive"] = archive
        capture["rec"] = rec

    def _load_rule_spec(rule_path):
        rec.load_rule_spec.append({"closed": archive.closed, "path": rule_path,
                                   "gpu": engine.GPU_AVAILABLE})
        return {"rule": "stub"}

    def _init_memory_grid(shape):
        rec.init_memory_grid.append({"closed": archive.closed, "shape": tuple(shape)})
        return _grid(channels=8, size=shape[0])

    def _benchmark_component(name, fn, warmup=2, iterations=10):
        rec.components.append({
            "closed": archive.closed, "name": name, "warmup": warmup,
            "iterations": iterations, "gpu": engine.GPU_AVAILABLE,
            "xp_is_numpy": engine._xp is np,
        })
        if name in component_errors:
            raise component_errors[name]
        fn()  # exactly once — deterministic, no warmup/iteration timing loop
        return 1.0

    def _random_rand(*shape):
        rec.random_rand.append({"shape": tuple(shape),
                                "gpu": engine.GPU_AVAILABLE,
                                "xp_is_numpy": engine._xp is np})
        if random_rand_error is not None:
            raise random_rand_error
        return np.random.random_sample(shape)

    def _measured(label):
        def _record(arg, *rest, **kwargs):
            rec.measured.append({"label": label, "arg": arg,
                                 "closed": archive.closed})
            return arg
        return _record

    def _step_ca_lattice(lattice, rule_spec, rng, inactivity, memory_grid,
                         current_gen=None):
        rec.steps.append({
            "closed": archive.closed, "lattice": lattice, "rule_spec": rule_spec,
            "rng": rng, "inactivity": inactivity, "memory_grid": memory_grid,
            "current_gen": current_gen,
        })
        return lattice, inactivity, memory_grid, {"entropy": 0.5}

    # `run_benchmarks` does `import scripts.continuous_evolution_ca as ca_module`.
    # For that dotted `import ... as` form CPython resolves the binding via
    # `getattr(scripts, "continuous_evolution_ca")` and only falls back to
    # `sys.modules`, so patching `sys.modules` alone is not enough once any other
    # test module has imported the real engine (which sets that attribute on the
    # package). Both are patched here, and both are restored on exit, so the real
    # engine's globals are never read or mutated by these tests.
    with mock.patch.dict(sys.modules, {_ENGINE: engine}), \
         mock.patch.object(_scripts_package, _ENGINE_ATTR, engine, create=True), \
         mock.patch.object(gpu_benchmark.np, "load",
                           mock.Mock(return_value=archive)), \
         mock.patch.object(gpu_benchmark, "load_rule_spec", _load_rule_spec), \
         mock.patch.object(gpu_benchmark, "init_memory_grid", _init_memory_grid), \
         mock.patch.object(gpu_benchmark, "benchmark_component", _benchmark_component), \
         mock.patch.object(gpu_benchmark, "step_ca_lattice", _step_ca_lattice), \
         mock.patch.object(gpu_benchmark, "count_neighbors_3d",
                           _measured("count_neighbors_3d")), \
         mock.patch.object(gpu_benchmark, "_separable_box_filter_3d",
                           _measured("box_filter")), \
         mock.patch.object(gpu_benchmark, "_max_neighbor_value",
                           _measured("max_neighbor")), \
         mock.patch.object(gpu_benchmark.np.random, "rand", _random_rand), \
         mock.patch.object(gpu_benchmark, "GPU_AVAILABLE", False):
        gpu_benchmark.run_benchmarks("/fake/v070_gen1000.npz", num_steps)

    # The engine stand-in is discarded with the scope; assert the temporary
    # switch was restored on it before that happened.
    rec.engine_after = {"gpu": engine.GPU_AVAILABLE,
                        "xp_is_sentinel": engine._xp is sentinel_xp}
    return archive, rec


def test_run_benchmarks_closes_the_archive_before_load_rule_spec(capsys):
    """Central witness. Pre-fix `load_rule_spec` was entered with the archive
    still open, because the inline `np.load` result stayed referenced."""
    archive, rec = _run_benchmarks(num_steps=1)
    assert len(rec.load_rule_spec) == 1
    assert rec.load_rule_spec[0]["closed"] == 1
    assert rec.load_rule_spec[0]["path"].endswith("example.toml")
    assert archive.entered == 1
    assert archive.exited == 1
    assert archive.closed == 1


def test_run_benchmarks_closes_the_archive_before_init_memory_grid(capsys):
    """Central witness on the legacy path."""
    archive, rec = _run_benchmarks(
        contents=_contents(memory_grid=_grid(channels=3)), num_steps=1
    )
    assert len(rec.init_memory_grid) == 1
    assert rec.init_memory_grid[0]["closed"] == 1
    assert rec.init_memory_grid[0]["shape"] == (2, 2, 2)


def test_first_component_benchmark_observes_a_closed_archive(capsys):
    archive, rec = _run_benchmarks(num_steps=1)
    assert rec.components, "component benchmarks must have run"
    assert rec.components[0]["closed"] == 1
    assert all(entry["closed"] == 1 for entry in rec.components)


def test_first_full_step_observes_a_closed_archive(capsys):
    archive, rec = _run_benchmarks(num_steps=3)
    assert len(rec.steps) == 3
    assert rec.steps[0]["closed"] == 1
    assert all(step["closed"] == 1 for step in rec.steps)


def test_every_post_extraction_seam_observes_exactly_one_closure(capsys):
    archive, rec = _run_benchmarks(num_steps=2)
    observed = ([entry["closed"] for entry in rec.load_rule_spec]
                + [entry["closed"] for entry in rec.components]
                + [step["closed"] for step in rec.steps])
    assert observed, "seams must have been reached"
    assert set(observed) == {1}
    assert archive.closed == 1


# -- established benchmark behaviour -----------------------------------------


def test_extracted_lattice_reaches_the_component_seam_by_identity(capsys):
    """With no legacy expansion, the component benchmark measures the extracted
    lattice object itself — asserted at the seam that actually receives it."""
    contents = _contents()
    archive, rec = _run_benchmarks(contents=contents, num_steps=1)
    measured = {entry["label"]: entry for entry in rec.measured}
    assert measured["count_neighbors_3d"]["arg"] is contents["lattice"]
    assert all(entry["closed"] == 1 for entry in rec.measured)


def test_full_step_seam_receives_the_established_copies(capsys):
    """The established loop benchmarks copies, not the extracted arrays."""
    contents = _contents()
    archive, rec = _run_benchmarks(contents=contents, num_steps=1)
    step = rec.steps[0]
    np.testing.assert_array_equal(step["lattice"], contents["lattice"])
    np.testing.assert_array_equal(step["memory_grid"], contents["memory_grid"])
    assert step["lattice"] is not contents["lattice"]        # established .copy()
    assert step["memory_grid"] is not contents["memory_grid"]
    assert step["rule_spec"] == {"rule": "stub"}


def test_legacy_memory_grid_expansion_is_unchanged(capsys):
    legacy = _grid(channels=3)
    legacy[:] = 7.0
    archive, rec = _run_benchmarks(contents=_contents(memory_grid=legacy),
                                   num_steps=1)
    expanded = rec.steps[0]["memory_grid"]
    assert expanded.shape[0] == 8
    np.testing.assert_array_equal(expanded[:3], legacy)
    np.testing.assert_array_equal(expanded[3:], np.zeros((5, 2, 2, 2), np.float32))


def test_generation_progression_is_generation_plus_index(capsys):
    archive, rec = _run_benchmarks(contents=_contents(generation=500), num_steps=4)
    assert [step["current_gen"] for step in rec.steps] == [500, 501, 502, 503]


def test_rng_seed_and_inactivity_dtype_are_unchanged(capsys):
    archive, rec = _run_benchmarks(num_steps=2)
    first = rec.steps[0]
    assert isinstance(first["rng"], np.random.Generator)
    assert first["rng"].random() == np.random.default_rng(seed=42).random()
    assert first["inactivity"].dtype == np.int16
    assert first["inactivity"].shape == (2, 2, 2)
    assert rec.steps[1]["rng"] is first["rng"]


def test_temporary_cpu_mode_switch_and_restoration_are_unchanged(capsys):
    """During the CPU component section the engine globals are forced to CPU;
    afterwards the prior values are restored on the successful path."""
    archive, rec = _run_benchmarks(num_steps=1)
    assert rec.components, "component benchmarks must have run"
    assert all(entry["gpu"] is False for entry in rec.components)
    assert all(entry["xp_is_numpy"] for entry in rec.components)
    assert rec.engine_after["gpu"] is True          # restored
    assert rec.engine_after["xp_is_sentinel"] is True  # restored


def test_component_warmup_and_iteration_counts_are_unchanged(capsys):
    archive, rec = _run_benchmarks(num_steps=1)
    names = [entry["name"] for entry in rec.components]
    assert names == [
        "count_neighbors_3d (CPU)",
        "box_filter_3d R=12 (CPU)",
        "max_neighbor_value (CPU)",
    ]
    assert all(entry["warmup"] == 1 and entry["iterations"] == 5
               for entry in rec.components)


def test_an_extraction_failure_reaches_no_benchmark_seam(capsys):
    archive = _FakeArchive(_contents(), raise_on="lattice")
    with pytest.raises(KeyError):
        _run_benchmarks(archive=archive, num_steps=3)
    rec = archive.rec
    assert rec.load_rule_spec == []
    assert rec.init_memory_grid == []
    assert rec.components == []
    assert rec.steps == []
    assert archive.closed == 1


def test_no_real_engine_gpu_or_benchmark_was_executed(capsys):
    """Every seam was a stand-in and the engine stub is scoped, not resident."""
    before = sys.modules.get(_ENGINE)
    archive, rec = _run_benchmarks(num_steps=1)
    assert sys.modules.get(_ENGINE) is before
    # Only the three CPU components ran: the GPU branch was never entered.
    assert all(entry["name"].endswith("(CPU)") for entry in rec.components)
    assert not any("(GPU)" in entry["name"] for entry in rec.components)
    assert len(rec.measured) == 3  # each measured callable invoked exactly once


# ===========================================================================
# Pickle refusal -- gpu_benchmark must never unpickle an NPZ member
#
# An object-dtype member is stored as a pickle, so loading one with pickle
# enabled is arbitrary code execution by construction. The payload below is
# harmless: its reduction writes ONE marker file inside pytest's own tmp_path
# and returns. `__reduce__` runs at PICKLE time and only records the callable,
# so writing the archive is inert; the call would happen at UNPICKLE time.
#
# Scope: an object-member refusal, NOT whole-archive validation.
# ===========================================================================

_GB_MARKER = "GPU_PAYLOAD_EXECUTED"


def _create_marker_gb(directory: str) -> str:
    """Stand in for a malicious payload; deliberately inert.

    Module scope is required -- pickle stores a module-qualified reference, so
    a function defined inside a test body could not be resolved at load time.
    """
    marker = Path(directory) / _GB_MARKER
    marker.write_text("payload executed", encoding="utf-8")
    return str(marker)


class _PayloadGb:
    """Its reduction calls the marker writer when unpickled."""

    def __init__(self, directory):
        self._directory = str(directory)

    def __reduce__(self):
        return (_create_marker_gb, (self._directory,))


def _payload_array_gb(directory):
    return np.array([_PayloadGb(directory)], dtype=object)


def _marker_gb(tmp_path):
    return tmp_path / _GB_MARKER


def _write_snapshot_gb(path, compressed=False, **members):
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


def test_gb_payload_fixture_actually_fires_when_pickle_is_enabled(tmp_path):
    """Control. Without it, every "marker is absent" assertion below could
    pass against a payload that never worked. This is the only place in this
    module that enables pickle."""
    archive = _write_snapshot_gb(
        tmp_path / "control.npz", lattice=_payload_array_gb(tmp_path)
    )
    assert not _marker_gb(tmp_path).exists()

    with np.load(archive, allow_pickle=True) as snap:
        snap["lattice"]

    assert _marker_gb(tmp_path).exists(), "the payload fixture is inert; fix it"


@pytest.mark.parametrize("field", ["lattice", "memory_grid", "generation"])
def test_object_payload_is_refused_by_the_helper(tmp_path, field):
    archive = _write_snapshot_gb(
        tmp_path / f"{field}.npz", **{field: _payload_array_gb(tmp_path)}
    )
    with pytest.raises(ValueError) as excinfo:
        gpu_benchmark._load_snapshot(archive)
    assert "allow_pickle=False" in str(excinfo.value)
    assert not _marker_gb(tmp_path).exists(), "the pickle payload executed"


def test_run_benchmarks_refuses_before_any_benchmark_runs(tmp_path):
    """The refusal happens inside the loader, so no warmup, no timing loop and
    no GPU branch is ever entered."""
    archive = _write_snapshot_gb(
        tmp_path / "hostile.npz", lattice=_payload_array_gb(tmp_path)
    )
    ran = []
    with mock.patch.object(gpu_benchmark, "benchmark_component",
                           lambda *a, **k: ran.append(1)):
        with pytest.raises(ValueError):
            gpu_benchmark.run_benchmarks(archive, num_steps=1)
    assert ran == [], "a benchmark ran after the refusal"
    assert not _marker_gb(tmp_path).exists()


def test_a_refusal_is_never_retried_with_pickle_enabled(tmp_path, monkeypatch):
    archive = _write_snapshot_gb(
        tmp_path / "retry.npz", lattice=_payload_array_gb(tmp_path)
    )
    real_load = np.load
    calls = []

    def _recording_load(*args, **kwargs):
        calls.append(kwargs.get("allow_pickle"))
        return real_load(*args, **kwargs)

    monkeypatch.setattr(gpu_benchmark.np, "load", _recording_load)
    with pytest.raises(ValueError):
        gpu_benchmark._load_snapshot(archive)
    assert calls == [False]


def test_a_numeric_snapshot_still_loads_and_converts(tmp_path):
    archive = _write_snapshot_gb(tmp_path / "clean.npz", generation=np.int64(9))
    lattice, grid, generation = gpu_benchmark._load_snapshot(archive)
    assert lattice.dtype == np.uint8 and grid.dtype == np.float32
    assert generation == 9 and type(generation) is int


# -- temporary-backend failure atomicity --------------------------------------
#
# `run_benchmarks()` forces `scripts.continuous_evolution_ca` onto the CPU
# backend for the three CPU component benchmarks, then restores it. The restore
# used to sit after the third benchmark on the SUCCESS path only, so any failure
# in between -- a component, or the `np.random.rand` preparation between two of
# them -- left the engine's module globals pinned to CPU for the rest of the
# process. Module globals, so every later user inherited it, starting with the
# optional GPU section a few lines below.
#
# These drive the genuine function; the engine is the same scoped stand-in used
# above, carrying a distinctive `GPU_AVAILABLE = True` and an identity-sensitive
# `_xp` sentinel so restoration is observable rather than merely plausible.

_CPU_COMPONENTS = [
    "count_neighbors_3d (CPU)",
    "box_filter_3d R=12 (CPU)",
    "max_neighbor_value (CPU)",
]


class BenchBoom(Exception):
    """Distinct benchmark failure, so propagation can be asserted by identity."""


@pytest.mark.parametrize("failing", _CPU_COMPONENTS)
def test_backend_is_restored_when_a_cpu_component_fails(failing):
    boom = BenchBoom(f"{failing} exploded")
    capture = {}

    with pytest.raises(BenchBoom) as caught:
        _run_benchmarks(num_steps=1, component_errors={failing: boom},
                        capture=capture)

    assert caught.value is boom, "the original exception must propagate unwrapped"
    engine = capture["engine"]
    assert engine.GPU_AVAILABLE is True
    assert engine._xp is capture["sentinel_xp"]


def test_backend_is_restored_when_cpu_preparation_fails():
    """`np.random.rand` sits between the first and second components."""
    boom = BenchBoom("rand exploded")
    capture = {}

    with pytest.raises(BenchBoom) as caught:
        _run_benchmarks(num_steps=1, random_rand_error=boom, capture=capture)

    assert caught.value is boom
    engine = capture["engine"]
    assert engine.GPU_AVAILABLE is True
    assert engine._xp is capture["sentinel_xp"]
    # It really did fail where we think: one component ran, the second did not.
    assert [c["name"] for c in capture["rec"].components] == _CPU_COMPONENTS[:1]
    assert len(capture["rec"].random_rand) == 1


def test_a_failure_in_the_first_component_still_restores_both_values():
    """Both globals are restored, not just the flag.

    `_xp` is compared by identity against a sentinel that is not numpy, so a
    restore that wrote `np` back instead of the previous object would fail here
    even though the flag looked right.
    """
    capture = {}
    with pytest.raises(BenchBoom):
        _run_benchmarks(num_steps=1,
                        component_errors={_CPU_COMPONENTS[0]: BenchBoom("x")},
                        capture=capture)

    engine = capture["engine"]
    assert engine._xp is capture["sentinel_xp"]
    assert engine._xp is not np
    assert engine.GPU_AVAILABLE is True


def test_the_successful_path_still_sees_cpu_mode_for_all_three_components():
    """The repair must not weaken what the forced-CPU interval is for."""
    _archive, rec = _run_benchmarks(num_steps=1)

    cpu = [c for c in rec.components if c["name"] in _CPU_COMPONENTS]
    assert [c["name"] for c in cpu] == _CPU_COMPONENTS
    assert all(c["gpu"] is False for c in cpu)
    assert all(c["xp_is_numpy"] for c in cpu)
    # ...and the CPU preparation between them ran under the same forced backend.
    assert rec.random_rand and all(r["gpu"] is False for r in rec.random_rand)
    # Restored before anything after the interval.
    assert rec.engine_after == {"gpu": True, "xp_is_sentinel": True}


# -- nonpositive step counts --------------------------------------------------
#
# A nonpositive `num_steps` used to travel through the banner, snapshot
# loading, rule loading, RNG construction, the backend switch and every
# component benchmark before failing in the timing aggregation -- `np.min([])`
# on an empty list, or an unbound `first_metrics` because the loop never ran.


@pytest.mark.parametrize("steps", [0, -1, -10])
def test_nonpositive_steps_are_refused_before_anything_is_touched(steps):
    archive = _FakeArchive(_contents())
    engine = _engine_stand_in()
    sentinel_xp = object()
    engine.GPU_AVAILABLE = True
    engine._xp = sentinel_xp
    load_mock = mock.Mock(return_value=archive)
    touched = []

    def _tripwire(label, result=None):
        def _fn(*a, **k):
            touched.append(label)
            return result
        return _fn

    with mock.patch.dict(sys.modules, {_ENGINE: engine}), \
         mock.patch.object(_scripts_package, _ENGINE_ATTR, engine, create=True), \
         mock.patch.object(gpu_benchmark.np, "load", load_mock), \
         mock.patch.object(gpu_benchmark, "load_rule_spec",
                           _tripwire("load_rule_spec", {"rule": "stub"})), \
         mock.patch.object(gpu_benchmark, "init_memory_grid",
                           _tripwire("init_memory_grid", _grid())), \
         mock.patch.object(gpu_benchmark, "benchmark_component",
                           _tripwire("benchmark_component", 1.0)), \
         mock.patch.object(gpu_benchmark, "step_ca_lattice",
                           _tripwire("step_ca_lattice")), \
         mock.patch.object(gpu_benchmark.np.random, "default_rng",
                           _tripwire("default_rng")), \
         mock.patch.object(gpu_benchmark.np.random, "rand",
                           _tripwire("rand")), \
         mock.patch.object(gpu_benchmark, "GPU_AVAILABLE", False):
        with pytest.raises(ValueError) as caught:
            gpu_benchmark.run_benchmarks("/fake/v070_gen1000.npz", steps)

    assert str(steps) in str(caught.value)
    # Nothing downstream was reached: no snapshot, rule, RNG, benchmark or step.
    assert touched == []
    assert load_mock.call_count == 0
    assert archive.entered == 0 and archive.closed == 0
    # ...and the engine globals were never mutated.
    assert engine.GPU_AVAILABLE is True
    assert engine._xp is sentinel_xp


def test_nonpositive_steps_print_nothing(capsys):
    with pytest.raises(ValueError):
        gpu_benchmark.run_benchmarks("/fake/v070_gen1000.npz", 0)
    assert capsys.readouterr().out == ""


def test_a_single_step_run_is_unaffected(capsys):
    """The established positive-path contract still holds."""
    archive, rec = _run_benchmarks(num_steps=1)

    assert len(rec.steps) == 1
    assert archive.closed == 1
    assert rec.engine_after == {"gpu": True, "xp_is_sentinel": True}
    out = capsys.readouterr().out
    assert "FULL STEP BENCHMARK (1 steps)" in out
    assert "SUMMARY" in out
