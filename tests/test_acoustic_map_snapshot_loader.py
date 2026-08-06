"""Focused tests for `scripts/acoustic_map.run_acoustic_diagnostic()` archive lifetime.

The diagnostic used to keep the `NpzFile` from `np.load` referenced for its whole
run — lattice-size inspection, legacy memory-grid expansion, rule-spec loading,
RNG and inactivity construction, `AcousticMap` construction, every simulated
step, the summaries, the final report and the heatmap save. A default CLI run
therefore held the input handle across 100 steps (200 via the function default),
and callers may request more; release depended on eventual object destruction. On
Windows a retained snapshot handle can interfere with deleting, rotating or
replacing that file.

The three values are now materialised while the archive is open and it closes
before any post-extraction work begins.

No real simulation, engine, GPU kernel, snapshot or heatmap is involved: the
engine's lazy import is served by a scoped `sys.modules` stand-in (restored
afterwards), `AcousticMap` is replaced by a recorder, and `np.load` returns a
closure-recording fake. The pickle-refusal tests appended at the end DO
write real NPZ archives, but only inside pytest's own `tmp_path`.

Scope is archive resource lifetime relative to extraction — not snapshot
validation, archive security, the acoustic mathematics or whole-diagnostic
correctness.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

# The module's GPU probe is fully try/except ImportError guarded, so importing it
# needs only NumPy — no CuPy, no engine, and no module-level skip.
from scripts import acoustic_map

_ENGINE_MODULE = "scripts.continuous_evolution_ca"


class Boom(Exception):
    """Distinct conversion failure, so propagation can be asserted exactly."""


class _ExplodingInt:
    def __int__(self):
        raise Boom("generation conversion failed")


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


def _lattice(size=2):
    return np.zeros((size, size, size), dtype=np.uint8)


def _grid(channels=8, size=2):
    return np.zeros((channels, size, size, size), dtype=np.float32)


def _contents(**overrides):
    base = {"lattice": _lattice(), "memory_grid": _grid(), "generation": 1000}
    base.update(overrides)
    return base


class _Recorder:
    """Collects, for every post-extraction seam, the archive's closure count at
    the moment that seam was entered."""

    def __init__(self, archive):
        self.archive = archive
        self.init_memory_grid = []
        self.load_rule_spec = []
        self.acoustic_map_init = []
        self.steps = []
        self.updates = []
        self.summaries = 0
        self.save_heatmap = []


def _run(contents=None, archive=None, num_steps=0, snapshot_path=None,
         raise_on=None, load_error=None):
    """Drive the genuine `run_acoustic_diagnostic()` with every seam controlled.

    Returns (result, archive, recorder, load_mock). Raised exceptions are left to
    the caller so propagation can be asserted.
    """
    archive = archive if archive is not None else _FakeArchive(
        _contents() if contents is None else contents, raise_on=raise_on
    )
    rec = _Recorder(archive)
    archive.rec = rec  # reachable after a propagated exception
    path = snapshot_path if snapshot_path is not None else Path("/fake/v070_gen1000.npz")

    def _init_memory_grid(shape):
        rec.init_memory_grid.append({"closed": archive.closed, "shape": tuple(shape)})
        return _grid(channels=8, size=shape[0])

    def _load_rule_spec(rule_path):
        rec.load_rule_spec.append({"closed": archive.closed, "path": rule_path})
        return {"rule": "stub"}

    def _step_ca_lattice(lattice, rule_spec, rng, inactivity, memory_grid, generation):
        rec.steps.append({
            "closed": archive.closed, "lattice": lattice, "rule_spec": rule_spec,
            "rng": rng, "inactivity": inactivity, "memory_grid": memory_grid,
            "generation": generation,
        })
        stepped = lattice + 1  # a distinct new array, so `update` can be checked
        return stepped, inactivity, memory_grid, {"metric": len(rec.steps)}

    engine_stub = types.ModuleType(_ENGINE_MODULE)
    engine_stub.step_ca_lattice = _step_ca_lattice
    engine_stub.load_rule_spec = _load_rule_spec
    engine_stub.init_memory_grid = _init_memory_grid

    class _RecordingAcousticMap:
        def __init__(self, lattice_size=None, config=None):
            rec.acoustic_map_init.append({
                "closed": archive.closed, "lattice_size": lattice_size,
                "config": config,
            })
            self.lattice_size = lattice_size
            self.config = config

        def update(self, current, previous):
            rec.updates.append({"closed": archive.closed, "current": current,
                                "previous": previous})

        def print_summary(self):
            rec.summaries += 1

        def save_heatmap(self):
            rec.save_heatmap.append({"closed": archive.closed})
            return Path("/fake/heatmap.png")  # never written

    load_mock = mock.Mock(side_effect=load_error) if load_error is not None \
        else mock.Mock(return_value=archive)

    with mock.patch.dict(sys.modules, {_ENGINE_MODULE: engine_stub}), \
         mock.patch.object(acoustic_map.np, "load", load_mock), \
         mock.patch.object(acoustic_map, "AcousticMap", _RecordingAcousticMap):
        result = acoustic_map.run_acoustic_diagnostic(path, num_steps)
    return result, archive, rec, load_mock


def _run_expecting(exception_type, **kwargs):
    with pytest.raises(exception_type) as exc:
        _run(**kwargs)
    return exc


# -- extraction identity and conversions --------------------------------------


def test_lattice_is_extracted_by_identity():
    contents = _contents()
    _, archive, rec, _ = _run(contents=contents, num_steps=1)
    assert rec.steps[0]["lattice"] is contents["lattice"]


def test_memory_grid_is_extracted_by_identity_when_already_eight_channel():
    contents = _contents()
    _, archive, rec, _ = _run(contents=contents, num_steps=1)
    assert rec.steps[0]["memory_grid"] is contents["memory_grid"]
    assert rec.init_memory_grid == []  # no legacy expansion for an 8-channel grid


def test_generation_is_an_exact_builtin_int():
    contents = _contents(generation=np.int64(4242))
    _, _, rec, _ = _run(contents=contents, num_steps=1)
    generation = rec.steps[0]["generation"]
    assert type(generation) is int
    assert generation == 4242


def test_np_load_receives_the_original_path_and_allow_pickle_false():
    """No path conversion is introduced: the very object passed in is forwarded."""
    path = Path("/fake/dir/v070_gen7.npz")
    _, _, _, load_mock = _run(num_steps=0, snapshot_path=path)
    assert load_mock.call_count == 1
    args, kwargs = load_mock.call_args
    assert args == (path,)
    assert args[0] is path  # not str(path), not a re-wrapped Path
    assert kwargs == {"allow_pickle": False}


def test_extraction_order_is_preserved():
    _, archive, _, _ = _run(num_steps=0)
    assert archive.lookups == ["lattice", "memory_grid", "generation"]


# -- closure on success -------------------------------------------------------


def test_archive_context_entered_exactly_once():
    _, archive, _, _ = _run(num_steps=0)
    assert archive.entered == 1


def test_archive_exits_and_closes_exactly_once_on_success():
    _, archive, _, _ = _run(num_steps=3)
    assert archive.exited == 1
    assert archive.closed == 1


def test_closure_does_not_depend_on_finalisation():
    """No `__del__` on the fake and the reference stays alive, so the recorded
    closure cannot come from gc, reference-count timing or interpreter shutdown.
    No test here calls gc.collect()."""
    assert not hasattr(_FakeArchive, "__del__")
    _, archive, _, _ = _run(num_steps=0)
    assert archive.closed == 1
    assert archive is not None


# -- closure precedes every post-extraction seam ------------------------------


def test_archive_closed_before_load_rule_spec_for_an_eight_channel_grid():
    """Central witness (8-channel path). Pre-fix `load_rule_spec` was entered
    with the archive still open."""
    _, archive, rec, _ = _run(num_steps=0)
    assert len(rec.load_rule_spec) == 1
    assert rec.load_rule_spec[0]["closed"] == 1
    assert rec.load_rule_spec[0]["path"].endswith("example.toml")


def test_archive_closed_before_init_memory_grid_for_a_legacy_grid():
    """Central witness (legacy path). Pre-fix `init_memory_grid` was entered with
    the archive still open."""
    contents = _contents(memory_grid=_grid(channels=3))
    _, archive, rec, _ = _run(contents=contents, num_steps=0)
    assert len(rec.init_memory_grid) == 1
    assert rec.init_memory_grid[0]["closed"] == 1
    assert rec.init_memory_grid[0]["shape"] == (2, 2, 2)
    assert rec.load_rule_spec[0]["closed"] == 1


def test_archive_closed_before_acoustic_map_construction():
    _, archive, rec, _ = _run(num_steps=0)
    assert len(rec.acoustic_map_init) == 1
    assert rec.acoustic_map_init[0]["closed"] == 1
    assert rec.acoustic_map_init[0]["lattice_size"] == 2


def test_archive_closed_before_the_first_step_and_every_step():
    _, archive, rec, _ = _run(num_steps=3)
    assert len(rec.steps) == 3
    assert rec.steps[0]["closed"] == 1
    assert all(step["closed"] == 1 for step in rec.steps)


def test_archive_closed_before_every_update_and_the_save():
    _, archive, rec, _ = _run(num_steps=2)
    assert all(entry["closed"] == 1 for entry in rec.updates)
    assert len(rec.save_heatmap) == 1
    assert rec.save_heatmap[0]["closed"] == 1


# -- closure on every extraction / conversion failure -------------------------


@pytest.mark.parametrize(
    "missing", ["lattice", "memory_grid", "generation"],
    ids=["lattice", "memory_grid", "generation"],
)
def test_archive_closes_when_a_key_lookup_raises(missing):
    archive = _FakeArchive(_contents(), raise_on=missing)
    with pytest.raises(KeyError):
        _run(archive=archive, num_steps=0)
    assert archive.exited == 1
    assert archive.closed == 1


def test_archive_closes_when_the_generation_conversion_raises():
    archive = _FakeArchive(_contents(generation=_ExplodingInt()))
    with pytest.raises(Boom):
        _run(archive=archive, num_steps=0)
    assert archive.exited == 1
    assert archive.closed == 1


def test_original_extraction_exception_propagates_unchanged():
    archive = _FakeArchive(_contents(generation=_ExplodingInt()))
    with pytest.raises(Boom) as exc:
        _run(archive=archive, num_steps=0)
    assert type(exc.value) is Boom
    assert str(exc.value) == "generation conversion failed"
    assert archive.closed == 1

    missing = _FakeArchive(_contents(), raise_on="lattice")
    with pytest.raises(KeyError) as exc2:
        _run(archive=missing, num_steps=0)
    assert type(exc2.value) is KeyError
    assert missing.closed == 1


def test_a_failure_before_extraction_reaches_no_diagnostic_seam():
    """An extraction failure closes the archive and runs nothing downstream."""
    archive = _FakeArchive(_contents(), raise_on="lattice")
    with pytest.raises(KeyError):
        _run(archive=archive, num_steps=3)
    rec = archive.rec
    assert rec.init_memory_grid == []
    assert rec.load_rule_spec == []
    assert rec.acoustic_map_init == []
    assert rec.steps == []
    assert rec.updates == []
    assert rec.save_heatmap == []
    assert rec.summaries == 0
    assert archive.closed == 1


@pytest.mark.parametrize(
    "error",
    [OSError("archive read failed"), RuntimeError("boom"), MemoryError("oom"),
     ValueError("bad zip")],
    ids=["os_error", "runtime_error", "memory_error", "value_error"],
)
def test_np_load_failure_propagates_unchanged(error):
    """No blanket except was added: an `np.load` failure of any kind propagates
    with its exact type and message, and no archive was ever entered."""
    with pytest.raises(type(error)) as exc:
        _run(num_steps=0, load_error=error)
    assert type(exc.value) is type(error)
    assert str(exc.value) == str(error)


# -- established diagnostic behaviour ----------------------------------------


def test_zero_steps_performs_no_ca_step_but_still_reports_and_saves():
    result, archive, rec, _ = _run(num_steps=0)
    assert rec.steps == []
    assert rec.updates == []
    assert rec.summaries == 1          # the final report only
    assert len(rec.save_heatmap) == 1  # heatmap still saved
    assert result is not None


def test_generation_progression_is_gen_plus_index():
    contents = _contents(generation=500)
    _, _, rec, _ = _run(contents=contents, num_steps=4)
    assert [step["generation"] for step in rec.steps] == [500, 501, 502, 503]


def test_step_seam_receives_the_established_values():
    contents = _contents()
    _, _, rec, _ = _run(contents=contents, num_steps=2)
    first, second = rec.steps
    # First step gets the extracted lattice and grid, the loaded rule spec, an
    # RNG and an int16 inactivity grid shaped like the lattice.
    assert first["lattice"] is contents["lattice"]
    assert first["memory_grid"] is contents["memory_grid"]
    assert first["rule_spec"] == {"rule": "stub"}
    assert isinstance(first["rng"], np.random.Generator)
    assert first["inactivity"].dtype == np.int16
    assert first["inactivity"].shape == contents["lattice"].shape
    # The loop feeds the previous step's outputs forward.
    assert second["rng"] is first["rng"]
    assert second["inactivity"] is first["inactivity"]
    assert second["rule_spec"] is first["rule_spec"]
    np.testing.assert_array_equal(second["lattice"], first["lattice"] + 1)


def test_rng_is_seeded_deterministically():
    """Seed 42 is preserved: two runs draw identical values from the RNG."""
    draws = []
    for _ in range(2):
        _, _, rec, _ = _run(num_steps=1)
        draws.append(rec.steps[0]["rng"].random())
    assert draws[0] == draws[1]
    assert draws[0] == np.random.default_rng(42).random()


def test_update_receives_the_stepped_lattice_and_previous_state():
    contents = _contents()
    _, _, rec, _ = _run(contents=contents, num_steps=1)
    assert len(rec.updates) == 1
    current = rec.updates[0]["current"]
    previous = rec.updates[0]["previous"]
    # `current` is the array the step returned; `previous` is the pre-step state.
    np.testing.assert_array_equal(current, contents["lattice"] + 1)
    np.testing.assert_array_equal(previous, contents["lattice"])
    if acoustic_map.GPU_AVAILABLE:
        assert previous is contents["lattice"]      # no copy on the GPU path
    else:
        assert previous is not contents["lattice"]  # established .copy()


def test_legacy_grid_expansion_semantics_are_preserved():
    legacy = _grid(channels=3)
    legacy[:] = 7.0
    contents = _contents(memory_grid=legacy)
    _, _, rec, _ = _run(contents=contents, num_steps=1)
    expanded = rec.steps[0]["memory_grid"]
    assert expanded.shape[0] == 8
    np.testing.assert_array_equal(expanded[:3], legacy)
    np.testing.assert_array_equal(expanded[3:], np.zeros((5, 2, 2, 2), np.float32))


def test_function_returns_the_acoustic_map_object():
    result, _, rec, _ = _run(num_steps=1)
    assert result is not None
    assert result.lattice_size == 2
    assert hasattr(result, "save_heatmap")


def test_no_real_engine_acoustic_map_or_output_was_used():
    """Every seam was a stand-in: no real AcousticMap was built and no file written."""
    result, _, rec, _ = _run(num_steps=1)
    assert type(result).__name__ == "_RecordingAcousticMap"
    # Outside the patch context this attribute is the genuine class again.
    assert type(result) is not acoustic_map.AcousticMap
    assert rec.save_heatmap == [{"closed": 1}]
    assert not Path("/fake/heatmap.png").exists()


def test_engine_module_stub_was_scoped_and_restored():
    before = sys.modules.get(_ENGINE_MODULE)
    _run(num_steps=0)
    assert sys.modules.get(_ENGINE_MODULE) is before


# ===========================================================================
# Pickle refusal -- acoustic_map must never unpickle an NPZ member
#
# An object-dtype member is stored as a pickle, so loading one with pickle
# enabled is arbitrary code execution by construction. The payload below is
# harmless: its reduction writes ONE marker file inside pytest's own tmp_path
# and returns. `__reduce__` runs at PICKLE time and only records the callable,
# so writing the archive is inert; the call would happen at UNPICKLE time.
#
# Scope: an object-member refusal, NOT whole-archive validation.
# ===========================================================================

_AM_MARKER = "ACOUSTIC_PAYLOAD_EXECUTED"


def _create_marker_am(directory: str) -> str:
    """Stand in for a malicious payload; deliberately inert.

    Module scope is required -- pickle stores a module-qualified reference, so
    a function defined inside a test body could not be resolved at load time.
    """
    marker = Path(directory) / _AM_MARKER
    marker.write_text("payload executed", encoding="utf-8")
    return str(marker)


class _PayloadAm:
    """Its reduction calls the marker writer when unpickled."""

    def __init__(self, directory):
        self._directory = str(directory)

    def __reduce__(self):
        return (_create_marker_am, (self._directory,))


def _payload_array_am(directory):
    return np.array([_PayloadAm(directory)], dtype=object)


def _marker_am(tmp_path):
    return tmp_path / _AM_MARKER


def _write_snapshot_am(path, compressed=False, **members):
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


def _engine_stub_installed():
    """Serve `run_acoustic_diagnostic`'s function-local engine import.

    That import happens at `acoustic_map.py:355`, BEFORE the `np.load` at
    :358, so a hostile-archive test would otherwise pull in the real engine
    and contradict this module's "no real engine" claim.
    """
    stub = types.ModuleType(_ENGINE_MODULE)
    stub.step_ca_lattice = lambda *a, **k: None
    stub.load_rule_spec = lambda *a, **k: {}
    stub.init_memory_grid = lambda *a, **k: None
    return mock.patch.dict(sys.modules, {_ENGINE_MODULE: stub})


def test_am_payload_fixture_actually_fires_when_pickle_is_enabled(tmp_path):
    """Control. Without it, every "marker is absent" assertion below could
    pass against a payload that never worked. This is the only place in this
    module that enables pickle."""
    archive = _write_snapshot_am(
        tmp_path / "control.npz", lattice=_payload_array_am(tmp_path)
    )
    assert not _marker_am(tmp_path).exists()

    with np.load(archive, allow_pickle=True) as snap:
        snap["lattice"]

    assert _marker_am(tmp_path).exists(), "the payload fixture is inert; fix it"


@pytest.mark.parametrize("field", ["lattice", "memory_grid", "generation"])
def test_object_payload_is_refused_by_the_diagnostic(tmp_path, field):
    archive = _write_snapshot_am(
        tmp_path / f"{field}.npz", **{field: _payload_array_am(tmp_path)}
    )
    with _engine_stub_installed(), pytest.raises(ValueError) as excinfo:
        acoustic_map.run_acoustic_diagnostic(archive, num_steps=0)
    assert "allow_pickle=False" in str(excinfo.value)
    assert not _marker_am(tmp_path).exists(), "the pickle payload executed"


def test_no_diagnostic_seam_runs_after_a_refusal(tmp_path):
    """The refusal precedes every engine seam, so nothing is stepped and no
    heatmap is written into the repository."""
    archive = _write_snapshot_am(
        tmp_path / "hostile.npz", lattice=_payload_array_am(tmp_path)
    )
    built = []

    class _RecordingMap:
        def __init__(self, *a, **k):
            built.append(1)

    with _engine_stub_installed(), \
         mock.patch.object(acoustic_map, "AcousticMap", _RecordingMap):
        with pytest.raises(ValueError):
            acoustic_map.run_acoustic_diagnostic(archive, num_steps=0)

    assert built == [], "a diagnostic seam ran after the refusal"
    assert not _marker_am(tmp_path).exists()


def test_a_refusal_is_never_retried_with_pickle_enabled(tmp_path, monkeypatch):
    archive = _write_snapshot_am(
        tmp_path / "retry.npz", lattice=_payload_array_am(tmp_path)
    )
    real_load = np.load
    calls = []

    def _recording_load(*args, **kwargs):
        calls.append(kwargs.get("allow_pickle"))
        return real_load(*args, **kwargs)

    monkeypatch.setattr(acoustic_map.np, "load", _recording_load)
    with _engine_stub_installed(), pytest.raises(ValueError):
        acoustic_map.run_acoustic_diagnostic(archive, num_steps=0)
    assert calls == [False], f"expected one pickle-free open, got {calls}"


def test_the_real_archive_is_closed_after_a_refusal(tmp_path, monkeypatch):
    """Real-object introspection rather than unlink: POSIX unlink succeeds
    with descriptors outstanding, so it proves nothing on the Linux runner."""
    archive = _write_snapshot_am(
        tmp_path / "closed.npz", lattice=_payload_array_am(tmp_path)
    )
    real_load = np.load
    opened = []

    def _tracking_load(*args, **kwargs):
        handle = real_load(*args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(acoustic_map.np, "load", _tracking_load)
    with _engine_stub_installed(), pytest.raises(ValueError):
        acoustic_map.run_acoustic_diagnostic(archive, num_steps=0)

    assert len(opened) == 1
    handle = opened[0]
    assert handle.fid is None or handle.fid.closed
