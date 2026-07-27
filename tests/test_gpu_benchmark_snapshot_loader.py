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
`np.load` returns a closure-recording fake. Nothing is written anywhere.

Scope is archive resource lifetime relative to extraction — not snapshot
validation, benchmark mathematics, timing methodology, or the separate question
of exception-safe restoration of the temporary engine globals.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

_ENGINE = "scripts.continuous_evolution_ca"


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


def test_np_load_receives_the_original_path_object_and_allow_pickle():
    """No path conversion is introduced: the very object passed in is forwarded."""
    path = Path("/fake/dir/v070_gen7.npz")
    _, load_mock = _load(_FakeArchive(_contents()), path=path)
    assert load_mock.call_count == 1
    args, kwargs = load_mock.call_args
    assert args == (path,)
    assert args[0] is path
    assert kwargs == {"allow_pickle": True}


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


def _run_benchmarks(contents=None, archive=None, num_steps=1, raise_on=None):
    """Drive the genuine `run_benchmarks()` with every seam controlled.

    Returns (archive, recorder). Nothing real is benchmarked: the engine is a
    scoped stand-in, `benchmark_component` is a deterministic recorder rather
    than a timing loop, and the arrays are 2x2x2.
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
        fn()  # exactly once — deterministic, no warmup/iteration timing loop
        return 1.0

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

    with mock.patch.dict(sys.modules, {_ENGINE: engine}), \
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
