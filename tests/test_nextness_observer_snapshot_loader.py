"""Focused tests for `nextness_observer.load_snapshot()` archive ownership.

`load_snapshot()` used to bind the `NpzFile` from `np.load` to a local with no
context manager and no `close()`, then hold it through required-key enumeration,
all three required-member extractions, the `int()` conversion, both shape
validations, every optional-metadata traversal and the return. Release depended
on object destruction rather than an explicit ownership boundary, and callers had
no contractual proof that the input archive had been released before Observer
processing began. The same absence applied to every validation and metadata
failure path.

The loader now owns the archive through a context manager, so it is closed before
the function returns on the success path and on every failure path after the
archive is opened.

**Stated precisely:** the defect is the absence of deterministic
close-before-return across implementations and failure paths. It is *not* a claim
that `process_snapshot()` certainly retained the archive for a whole
classification run — in CPython a refcount drop may release it promptly at
function return — and it is *not* a proven accumulating descriptor leak.

Nothing here runs a Medusa engine, touches the network, imports ZMQ, publishes an
event, runs GPU code, writes repository data or creates a production log. Real
`.npz` files are tiny and live in `tmp_path`. `tests/test_nextness_observer.py` is
untouched.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
from unittest import mock

import numpy as np
import pytest

from scripts import nextness_observer
from scripts.nextness_observer import (
    ObserverConfig,
    TOKEN_NAMES,
    load_snapshot,
    process_snapshot,
)


class Boom(Exception):
    """Distinct failure, so exception identity can be asserted exactly."""


# --------------------------------------------------------------------------- #
# Closure-recording doubles
# --------------------------------------------------------------------------- #


class _FakeMember:
    """An archive member with controlled `.ndim`, `.shape` and `.item()`."""

    def __init__(self, ndim=3, shape=(2, 2, 2), item_value=None, item_error=None,
                 ndim_error=None):
        self._ndim = ndim
        self.shape = shape
        self._item_value = item_value
        self._item_error = item_error
        self._ndim_error = ndim_error

    @property
    def ndim(self):
        if self._ndim_error is not None:
            raise self._ndim_error
        return self._ndim

    def item(self):
        if self._item_error is not None:
            raise self._item_error
        return self._item_value


class _FakeArchive:
    """Stand-in for the `NpzFile` returned by `np.load`.

    Records context entry/exit and explicit closure. Defines **no** `__del__`, so
    a recorded closure can never have come from finalisation, reference-count
    timing, garbage collection or interpreter shutdown.
    """

    def __init__(self, members=None, file_names=None, files_error=None,
                 access_errors=None):
        self._members = {} if members is None else members
        self._file_names = (list(self._members) if file_names is None
                            else list(file_names))
        self._files_error = files_error
        self._access_errors = {} if access_errors is None else access_errors
        self.entered = 0
        self.exited = 0
        self.closed = 0
        self.accesses = []

    @property
    def files(self):
        if self._files_error is not None:
            raise self._files_error
        return list(self._file_names)

    def __enter__(self):
        self.entered += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exited += 1
        self.close()
        return False  # never suppress

    def close(self):
        self.closed += 1

    def __getitem__(self, key):
        self.accesses.append(key)
        if key in self._access_errors:
            raise self._access_errors[key]
        return self._members[key]


def _state(shape=(2, 2, 2)):
    return _FakeMember(ndim=len(shape), shape=shape)


def _memory(shape=(4, 2, 2, 2)):
    return _FakeMember(ndim=len(shape), shape=shape)


def _generation(value=1234):
    return value


def _members(**overrides):
    base = {
        "lattice": _state(),
        "memory_grid": _memory(),
        "generation": _generation(),
    }
    base.update(overrides)
    return base


def _snapshot_file(tmp_path, name="v070_gen1234.npz"):
    """A real file on disk so `is_file()` passes; contents never read."""
    path = tmp_path / name
    path.write_bytes(b"")
    return path


def _load(tmp_path, archive, name="v070_gen1234.npz"):
    """Run the genuine `load_snapshot` against `archive`; return (result, mock)."""
    path = _snapshot_file(tmp_path, name)
    load_mock = mock.Mock(return_value=archive)
    with mock.patch.object(nextness_observer.np, "load", load_mock):
        result = load_snapshot(path)
    return result, load_mock


def _load_expecting(tmp_path, archive, exc_type, name="v070_gen1234.npz"):
    path = _snapshot_file(tmp_path, name)
    load_mock = mock.Mock(return_value=archive)
    with mock.patch.object(nextness_observer.np, "load", load_mock):
        with pytest.raises(exc_type) as exc:
            load_snapshot(path)
    return exc


# --------------------------------------------------------------------------- #
# Central failing-before witness
# --------------------------------------------------------------------------- #


def test_archive_is_explicitly_closed_before_load_snapshot_returns(tmp_path):
    """CENTRAL WITNESS.

    Against the pre-fix loader this fails: the function returns while the
    archive's explicit exit/close count is still zero. The reference below stays
    live for the whole assertion, `_FakeArchive` defines no `__del__`, and no
    `gc.collect()` is called anywhere in this module — so a recorded closure can
    only have come from an explicit ownership boundary.
    """
    archive = _FakeArchive(_members())
    result, _ = _load(tmp_path, archive)
    assert archive.entered == 1
    assert archive.exited == 1
    assert archive.closed == 1
    assert result is not None
    assert archive is not None  # still referenced here; nothing was finalised
    assert not hasattr(_FakeArchive, "__del__")


# --------------------------------------------------------------------------- #
# Successful materialisation contract
# --------------------------------------------------------------------------- #


def test_successful_return_is_a_four_tuple_in_the_established_order(tmp_path):
    members = _members()
    result, _ = _load(tmp_path, _FakeArchive(members))
    assert isinstance(result, tuple)
    assert len(result) == 4
    state, memory, generation, meta = result
    assert state is members["lattice"]
    assert memory is members["memory_grid"]
    assert generation == 1234
    assert meta == {}


def test_state_and_memory_are_returned_by_identity(tmp_path):
    members = _members()
    (state, memory, _, _), _ = _load(tmp_path, _FakeArchive(members))
    assert state is members["lattice"]
    assert memory is members["memory_grid"]


def test_generation_is_an_exact_builtin_int(tmp_path):
    members = _members(generation=np.int64(77))
    (_, _, generation, _), _ = _load(tmp_path, _FakeArchive(members))
    assert type(generation) is int
    assert generation == 77


def test_metadata_is_an_exact_builtin_dict(tmp_path):
    (_, _, _, meta), _ = _load(tmp_path, _FakeArchive(_members()))
    assert type(meta) is dict


def test_np_load_receives_str_path_and_allow_pickle_false(tmp_path):
    path = _snapshot_file(tmp_path)
    load_mock = mock.Mock(return_value=_FakeArchive(_members()))
    with mock.patch.object(nextness_observer.np, "load", load_mock):
        load_snapshot(path)
    args, kwargs = load_mock.call_args
    assert args == (str(path),)
    assert type(args[0]) is str
    assert kwargs == {"allow_pickle": False}


def test_required_member_access_order_is_preserved(tmp_path):
    archive = _FakeArchive(_members())
    _load(tmp_path, archive)
    assert archive.accesses[:3] == ["lattice", "memory_grid", "generation"]


def test_required_key_enumeration_happens_while_the_archive_is_open(tmp_path):
    """`snap.files` is read inside the context: a `files` failure is raised with
    the archive entered and then closed, which can only happen inside it."""
    archive = _FakeArchive(_members(), files_error=Boom("files exploded"))
    exc = _load_expecting(tmp_path, archive, Boom)
    assert str(exc.value) == "files exploded"
    assert archive.entered == 1
    assert archive.exited == 1
    assert archive.closed == 1


# --------------------------------------------------------------------------- #
# Pre-load path handling
# --------------------------------------------------------------------------- #


def test_missing_path_raises_the_established_file_not_found(tmp_path):
    missing = tmp_path / "absent.npz"
    with pytest.raises(FileNotFoundError) as exc:
        load_snapshot(missing)
    assert str(exc.value) == f"snapshot not found: {missing}"


def test_missing_path_never_calls_np_load(tmp_path):
    load_mock = mock.Mock()
    with mock.patch.object(nextness_observer.np, "load", load_mock):
        with pytest.raises(FileNotFoundError):
            load_snapshot(tmp_path / "absent.npz")
    assert load_mock.call_count == 0


def test_np_load_failure_propagates_before_any_context_entry(tmp_path):
    """An `np.load` failure happens before context entry and is unchanged."""
    path = _snapshot_file(tmp_path)
    load_mock = mock.Mock(side_effect=OSError("cannot open"))
    with mock.patch.object(nextness_observer.np, "load", load_mock):
        with pytest.raises(OSError) as exc:
            load_snapshot(path)
    assert type(exc.value) is OSError
    assert str(exc.value) == "cannot open"


# --------------------------------------------------------------------------- #
# Required-key refusal
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "present,missing_repr",
    [
        (["memory_grid", "generation"], "['lattice']"),
        (["lattice", "generation"], "['memory_grid']"),
        (["lattice", "memory_grid"], "['generation']"),
    ],
    ids=["no_lattice", "no_memory_grid", "no_generation"],
)
def test_one_missing_required_key_preserves_the_refusal(tmp_path, present,
                                                        missing_repr):
    archive = _FakeArchive(_members(), file_names=present)
    exc = _load_expecting(tmp_path, archive, ValueError)
    assert str(exc.value) == f"snapshot v070_gen1234.npz missing keys: {missing_repr}"
    assert archive.closed == 1


def test_multiple_missing_required_keys_are_sorted(tmp_path):
    archive = _FakeArchive(_members(), file_names=["generation"])
    exc = _load_expecting(tmp_path, archive, ValueError)
    assert str(exc.value) == (
        "snapshot v070_gen1234.npz missing keys: ['lattice', 'memory_grid']"
    )
    assert archive.closed == 1


def test_all_required_keys_missing_is_sorted(tmp_path):
    archive = _FakeArchive(_members(), file_names=[])
    exc = _load_expecting(tmp_path, archive, ValueError)
    assert str(exc.value) == (
        "snapshot v070_gen1234.npz missing keys: "
        "['generation', 'lattice', 'memory_grid']"
    )
    assert archive.closed == 1


def test_missing_key_refusal_closes_the_archive(tmp_path):
    archive = _FakeArchive(_members(), file_names=["lattice"])
    _load_expecting(tmp_path, archive, ValueError)
    assert archive.entered == 1
    assert archive.exited == 1
    assert archive.closed == 1


# --------------------------------------------------------------------------- #
# Required-member extraction failures
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "failing", ["lattice", "memory_grid", "generation"],
    ids=["lattice", "memory_grid", "generation"],
)
def test_required_member_failure_propagates_and_closes(tmp_path, failing):
    archive = _FakeArchive(_members(), access_errors={failing: Boom(f"{failing} bad")})
    exc = _load_expecting(tmp_path, archive, Boom)
    assert type(exc.value) is Boom
    assert str(exc.value) == f"{failing} bad"
    assert archive.exited == 1
    assert archive.closed == 1


def test_generation_conversion_failure_preserves_identity_and_closes(tmp_path):
    class _Unconvertible:
        def __int__(self):
            raise Boom("generation conversion failed")

    archive = _FakeArchive(_members(generation=_Unconvertible()))
    exc = _load_expecting(tmp_path, archive, Boom)
    assert type(exc.value) is Boom
    assert str(exc.value) == "generation conversion failed"
    assert archive.exited == 1
    assert archive.closed == 1


# --------------------------------------------------------------------------- #
# Shape validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("ndim,shape", [(2, (2, 2)), (4, (1, 2, 2, 2)), (1, (8,))],
                         ids=["two_d", "four_d", "one_d"])
def test_invalid_state_dimensionality_preserves_the_message_and_closes(
    tmp_path, ndim, shape
):
    archive = _FakeArchive(_members(lattice=_FakeMember(ndim=ndim, shape=shape)))
    exc = _load_expecting(tmp_path, archive, ValueError)
    assert str(exc.value) == (
        f"snapshot v070_gen1234.npz: state must be 3D, got shape {shape}"
    )
    assert archive.closed == 1


@pytest.mark.parametrize("ndim,shape", [(3, (2, 2, 2)), (5, (1, 1, 2, 2, 2))],
                         ids=["three_d", "five_d"])
def test_wrong_memory_dimensionality_preserves_the_message_and_closes(
    tmp_path, ndim, shape
):
    archive = _FakeArchive(_members(memory_grid=_FakeMember(ndim=ndim, shape=shape)))
    exc = _load_expecting(tmp_path, archive, ValueError)
    assert str(exc.value) == (
        f"snapshot v070_gen1234.npz: memory shape {shape} "
        f"inconsistent with state shape (2, 2, 2)"
    )
    assert archive.closed == 1


def test_mismatched_memory_spatial_shape_preserves_the_message_and_closes(tmp_path):
    archive = _FakeArchive(
        _members(memory_grid=_FakeMember(ndim=4, shape=(4, 3, 3, 3)))
    )
    exc = _load_expecting(tmp_path, archive, ValueError)
    assert str(exc.value) == (
        "snapshot v070_gen1234.npz: memory shape (4, 3, 3, 3) "
        "inconsistent with state shape (2, 2, 2)"
    )
    assert archive.closed == 1


def test_shape_inspection_failure_propagates_unchanged_and_closes(tmp_path):
    archive = _FakeArchive(
        _members(lattice=_FakeMember(ndim_error=Boom("ndim exploded")))
    )
    exc = _load_expecting(tmp_path, archive, Boom)
    assert type(exc.value) is Boom
    assert str(exc.value) == "ndim exploded"
    assert archive.exited == 1
    assert archive.closed == 1


# --------------------------------------------------------------------------- #
# Optional metadata
# --------------------------------------------------------------------------- #


def test_absent_optional_metadata_returns_an_empty_dict(tmp_path):
    (_, _, _, meta), _ = _load(tmp_path, _FakeArchive(_members()))
    assert meta == {}
    assert type(meta) is dict


def test_numeric_scalar_metadata_uses_item(tmp_path):
    members = _members(seed=_FakeMember(ndim=0, shape=(), item_value=99))
    (_, _, _, meta), _ = _load(tmp_path, _FakeArchive(members))
    assert meta == {"seed": 99}
    assert type(meta["seed"]) is int


def test_boolean_scalar_metadata_preserves_the_builtin_value(tmp_path):
    members = _members(flag=_FakeMember(ndim=0, shape=(), item_value=True))
    (_, _, _, meta), _ = _load(tmp_path, _FakeArchive(members))
    assert meta["flag"] is True


def test_string_scalar_metadata_preserves_the_item_result(tmp_path):
    members = _members(label=_FakeMember(ndim=0, shape=(), item_value="medusa"))
    (_, _, _, meta), _ = _load(tmp_path, _FakeArchive(members))
    assert meta["label"] == "medusa"
    assert type(meta["label"]) is str


def test_non_scalar_optional_array_is_returned_by_identity(tmp_path):
    array_member = _FakeMember(ndim=1, shape=(3,))
    members = _members(history=array_member)
    (_, _, _, meta), _ = _load(tmp_path, _FakeArchive(members))
    assert meta["history"] is array_member  # not copied, cast or transformed


def test_multiple_ordinary_metadata_members_all_survive(tmp_path):
    members = _members(
        seed=_FakeMember(ndim=0, shape=(), item_value=1),
        label=_FakeMember(ndim=0, shape=(), item_value="x"),
        history=_FakeMember(ndim=2, shape=(2, 2)),
    )
    (_, _, _, meta), _ = _load(tmp_path, _FakeArchive(members))
    assert set(meta) == {"seed", "label", "history"}
    assert meta["seed"] == 1
    assert meta["label"] == "x"
    assert meta["history"] is members["history"]


def test_optional_member_value_error_skips_only_that_member(tmp_path):
    """The narrow skippable lane: a pickled member is dropped, others survive."""
    members = _members(
        pickled=_FakeMember(),
        good=_FakeMember(ndim=0, shape=(), item_value=5),
    )
    archive = _FakeArchive(
        members,
        access_errors={"pickled": ValueError("Object arrays cannot be loaded")},
    )
    (_, _, _, meta), _ = _load(tmp_path, archive)
    assert "pickled" not in meta
    assert meta == {"good": 5}


def test_archive_closes_after_the_expected_skipped_value_error(tmp_path):
    members = _members(pickled=_FakeMember())
    archive = _FakeArchive(
        members,
        access_errors={"pickled": ValueError("Object arrays cannot be loaded")},
    )
    (_, _, _, meta), _ = _load(tmp_path, archive)
    assert meta == {}
    assert archive.entered == 1
    assert archive.exited == 1
    assert archive.closed == 1


@pytest.mark.parametrize(
    "error",
    [RuntimeError("unexpected"), MemoryError("oom"), KeyError("gone"),
     OSError("io failed")],
    ids=["runtime_error", "memory_error", "key_error", "os_error"],
)
def test_unexpected_optional_failure_propagates_and_closes(tmp_path, error):
    """Only `ValueError` is skippable; nothing else joins that lane."""
    members = _members(odd=_FakeMember())
    archive = _FakeArchive(members, access_errors={"odd": error})
    exc = _load_expecting(tmp_path, archive, type(error))
    assert type(exc.value) is type(error)
    assert archive.exited == 1
    assert archive.closed == 1


def test_optional_ndim_failure_propagates_and_closes(tmp_path):
    members = _members(odd=_FakeMember(ndim_error=Boom("ndim exploded")))
    archive = _FakeArchive(members)
    exc = _load_expecting(tmp_path, archive, Boom)
    assert str(exc.value) == "ndim exploded"
    assert archive.closed == 1


def test_optional_scalar_item_failure_propagates_with_identity_and_closes(tmp_path):
    members = _members(
        odd=_FakeMember(ndim=0, shape=(), item_error=Boom("item exploded"))
    )
    archive = _FakeArchive(members)
    exc = _load_expecting(tmp_path, archive, Boom)
    assert type(exc.value) is Boom
    assert str(exc.value) == "item exploded"
    assert archive.exited == 1
    assert archive.closed == 1


def test_metadata_values_are_not_copied_cast_or_stringified(tmp_path):
    """Beyond the established scalar `.item()`, values pass through untouched."""
    array_member = _FakeMember(ndim=3, shape=(1, 1, 1))
    members = _members(payload=array_member)
    (_, _, _, meta), _ = _load(tmp_path, _FakeArchive(members))
    assert meta["payload"] is array_member
    assert not isinstance(meta["payload"], str)


# --------------------------------------------------------------------------- #
# Real-NumPy behaviour locks (tiny, tmp_path only)
# --------------------------------------------------------------------------- #


def _write_npz(tmp_path, name="v070_gen0000042.npz", **arrays):
    path = tmp_path / name
    np.savez(path, **arrays)
    return path


def _tiny_valid(**extra):
    arrays = {
        "lattice": np.zeros((2, 2, 2), dtype=np.uint8),
        "memory_grid": np.zeros((4, 2, 2, 2), dtype=np.float32),
        "generation": np.array(42),
    }
    arrays.update(extra)
    return arrays


def test_real_npz_round_trip(tmp_path):
    path = _write_npz(tmp_path, **_tiny_valid())
    state, memory, generation, meta = load_snapshot(path)
    assert state.shape == (2, 2, 2)
    assert state.dtype == np.uint8
    assert memory.shape == (4, 2, 2, 2)
    assert memory.dtype == np.float32
    assert generation == 42
    assert type(generation) is int
    assert meta == {}


def test_real_npz_optional_numeric_scalar_metadata(tmp_path):
    path = _write_npz(tmp_path, **_tiny_valid(seed=np.array(7)))
    _, _, _, meta = load_snapshot(path)
    assert meta["seed"] == 7
    assert not isinstance(meta["seed"], np.ndarray)  # .item() applied


def test_real_npz_optional_array_metadata(tmp_path):
    history = np.arange(3, dtype=np.int32)
    path = _write_npz(tmp_path, **_tiny_valid(history=history))
    _, _, _, meta = load_snapshot(path)
    assert isinstance(meta["history"], np.ndarray)
    np.testing.assert_array_equal(meta["history"], history)


def test_real_npz_object_dtype_optional_member_is_skipped(tmp_path):
    """A harmless object-dtype array: `allow_pickle=False` refuses it, and the
    established narrow lane skips that member without failing the load."""
    obj = np.array([{"harmless": 1}], dtype=object)
    path = _write_npz(tmp_path, **_tiny_valid(notes=obj))
    state, memory, generation, meta = load_snapshot(path)
    assert "notes" not in meta
    assert generation == 42
    assert state.shape == (2, 2, 2)


def test_real_npz_missing_required_member_is_refused(tmp_path):
    path = _write_npz(
        tmp_path,
        lattice=np.zeros((2, 2, 2), dtype=np.uint8),
        generation=np.array(42),
    )
    with pytest.raises(ValueError) as exc:
        load_snapshot(path)
    assert "missing keys: ['memory_grid']" in str(exc.value)


def test_real_npz_invalid_state_shape_is_refused(tmp_path):
    path = _write_npz(
        tmp_path,
        lattice=np.zeros((2, 2), dtype=np.uint8),
        memory_grid=np.zeros((4, 2, 2), dtype=np.float32),
        generation=np.array(42),
    )
    with pytest.raises(ValueError) as exc:
        load_snapshot(path)
    assert "state must be 3D" in str(exc.value)


def test_real_npz_invalid_memory_shape_is_refused(tmp_path):
    path = _write_npz(
        tmp_path,
        lattice=np.zeros((2, 2, 2), dtype=np.uint8),
        memory_grid=np.zeros((4, 3, 3, 3), dtype=np.float32),
        generation=np.array(42),
    )
    with pytest.raises(ValueError) as exc:
        load_snapshot(path)
    assert "inconsistent with state shape" in str(exc.value)


# --------------------------------------------------------------------------- #
# End-to-end process_snapshot ownership ordering
# --------------------------------------------------------------------------- #


class _Seams:
    def __init__(self, archive):
        self.archive = archive
        self.is_medusa_live = []
        self.compute_safe_stride = []
        self.iter_patches = []
        self.classify = []
        self.warmth = []
        self.write_log_entry = []


def _run_process_snapshot(tmp_path, archive=None, medusa_is_live=None,
                          classify_error=None, patches=2):
    """Drive the genuine `process_snapshot()` with controlled downstream seams.

    The real corrected `load_snapshot` runs; `np.load` returns a
    closure-recording archive; every downstream seam records the archive's
    closure count at entry. No JSONL is written and no engine runs.
    """
    state = np.zeros((2, 2, 2), dtype=np.uint8)
    memory = np.zeros((4, 2, 2, 2), dtype=np.float32)
    archive = archive if archive is not None else _FakeArchive(
        {"lattice": state, "memory_grid": memory, "generation": np.array(1234)}
    )
    seams = _Seams(archive)
    path = _snapshot_file(tmp_path)
    # A large budget so nothing is timing-sensitive and nothing sleeps.
    config = dataclasses.replace(
        ObserverConfig(), log_directory=str(tmp_path / "log"),
        budget_seconds=3600.0, uniform_grid_stride=8,
    )

    def _is_medusa_live(check_dir, threshold_minutes=None):
        seams.is_medusa_live.append({"closed": archive.closed})
        return False

    def _compute_safe_stride(shape, radius=None, budget_seconds=None,
                             initial_stride=None):
        seams.compute_safe_stride.append({"closed": archive.closed,
                                          "shape": shape})
        return initial_stride

    def _iter_patches(st, mem, cfg, medusa_is_live=None):
        seams.iter_patches.append({"closed": archive.closed, "state": st,
                                   "memory": mem, "live": medusa_is_live})
        for index in range(patches):
            yield ("patch", index)

    def _classify_patch(patch):
        seams.classify.append({"closed": archive.closed, "patch": patch})
        if classify_error is not None:
            raise classify_error
        return TOKEN_NAMES[0]

    def _warmth(mem):
        seams.warmth.append({"closed": archive.closed, "memory": mem})
        return 0.0, 0

    def _write_log_entry(log_directory, entry):
        seams.write_log_entry.append({"closed": archive.closed, "entry": entry})
        return None

    with mock.patch.object(nextness_observer.np, "load",
                           mock.Mock(return_value=archive)), \
         mock.patch.object(nextness_observer, "is_medusa_live", _is_medusa_live), \
         mock.patch.object(nextness_observer, "compute_safe_stride",
                           _compute_safe_stride), \
         mock.patch.object(nextness_observer, "iter_patches", _iter_patches), \
         mock.patch.object(nextness_observer, "classify_patch", _classify_patch), \
         mock.patch.object(nextness_observer, "_warmth_diagnostics", _warmth), \
         mock.patch.object(nextness_observer, "write_log_entry", _write_log_entry):
        if medusa_is_live is None:
            entry = process_snapshot(path, config)
        else:
            entry = process_snapshot(path, config, medusa_is_live=medusa_is_live)
    return entry, archive, seams, state, memory


def test_liveness_autodetection_begins_after_closure(tmp_path):
    _, archive, seams, _, _ = _run_process_snapshot(tmp_path)
    assert len(seams.is_medusa_live) == 1
    assert seams.is_medusa_live[0]["closed"] == 1


def test_supplied_liveness_avoids_the_automatic_call(tmp_path):
    _, archive, seams, _, _ = _run_process_snapshot(tmp_path, medusa_is_live=False)
    assert seams.is_medusa_live == []
    assert archive.closed == 1


def test_compute_safe_stride_begins_after_closure(tmp_path):
    _, _, seams, state, _ = _run_process_snapshot(tmp_path)
    assert len(seams.compute_safe_stride) == 1
    assert seams.compute_safe_stride[0]["closed"] == 1
    assert seams.compute_safe_stride[0]["shape"] == state.shape


def test_iter_patches_begins_after_closure(tmp_path):
    _, _, seams, _, _ = _run_process_snapshot(tmp_path)
    assert len(seams.iter_patches) == 1
    assert seams.iter_patches[0]["closed"] == 1


def test_first_classification_seam_begins_after_closure(tmp_path):
    _, _, seams, _, _ = _run_process_snapshot(tmp_path)
    assert seams.classify, "classification must have run"
    assert seams.classify[0]["closed"] == 1


def test_warmth_diagnostics_begins_after_closure(tmp_path):
    _, _, seams, _, memory = _run_process_snapshot(tmp_path)
    assert len(seams.warmth) == 1
    assert seams.warmth[0]["closed"] == 1
    assert seams.warmth[0]["memory"] is memory


def test_write_log_entry_begins_after_closure(tmp_path):
    _, _, seams, _, _ = _run_process_snapshot(tmp_path)
    assert len(seams.write_log_entry) == 1
    assert seams.write_log_entry[0]["closed"] == 1


def test_every_downstream_closure_count_is_exactly_one(tmp_path):
    _, archive, seams, _, _ = _run_process_snapshot(tmp_path)
    observed = ([e["closed"] for e in seams.is_medusa_live]
                + [e["closed"] for e in seams.compute_safe_stride]
                + [e["closed"] for e in seams.iter_patches]
                + [e["closed"] for e in seams.classify]
                + [e["closed"] for e in seams.warmth]
                + [e["closed"] for e in seams.write_log_entry])
    assert observed, "seams must have been reached"
    assert set(observed) == {1}


def test_no_downstream_seam_reopens_or_recloses_the_archive(tmp_path):
    _, archive, _, _, _ = _run_process_snapshot(tmp_path)
    assert archive.entered == 1
    assert archive.exited == 1
    assert archive.closed == 1


def test_state_and_memory_reach_the_observer_seams_by_identity(tmp_path):
    _, _, seams, state, memory = _run_process_snapshot(tmp_path)
    assert seams.iter_patches[0]["state"] is state
    assert seams.iter_patches[0]["memory"] is memory
    assert seams.warmth[0]["memory"] is memory


def test_generation_shape_and_channels_reach_the_entry_unchanged(tmp_path):
    entry, _, _, state, memory = _run_process_snapshot(tmp_path)
    assert entry["generation"] == 1234
    assert entry["lattice_shape"] == list(state.shape)
    assert entry["memory_channels"] == int(memory.shape[0])


def test_controlled_token_count_produces_the_established_entry_fields(tmp_path):
    entry, _, seams, _, _ = _run_process_snapshot(tmp_path, patches=3)
    assert entry["token_counts"] == {TOKEN_NAMES[0]: 3}
    assert entry["snapshot_file"] == "v070_gen1234.npz"
    assert entry["stride_used"] == 8
    assert entry["stride_backoff_fired"] is False
    assert entry["medusa_is_live"] is False
    assert "budget" in entry and "fraction_used" in entry["budget"]


def test_process_snapshot_returns_the_dict_passed_to_write_log_entry(tmp_path):
    entry, _, seams, _, _ = _run_process_snapshot(tmp_path)
    assert seams.write_log_entry[0]["entry"] is entry


def test_downstream_failure_propagates_while_the_archive_stays_closed(tmp_path):
    archive = _FakeArchive({
        "lattice": np.zeros((2, 2, 2), dtype=np.uint8),
        "memory_grid": np.zeros((4, 2, 2, 2), dtype=np.float32),
        "generation": np.array(1234),
    })
    with pytest.raises(Boom) as exc:
        _run_process_snapshot(tmp_path, archive=archive,
                              classify_error=Boom("classifier exploded"))
    assert type(exc.value) is Boom
    assert str(exc.value) == "classifier exploded"
    assert archive.entered == 1
    assert archive.exited == 1
    assert archive.closed == 1


# --------------------------------------------------------------------------- #
# Structural ownership checks (supplementary, not a substitute)
# --------------------------------------------------------------------------- #


def _module_tree():
    source = pathlib.Path(nextness_observer.__file__).read_text(encoding="utf-8")
    return ast.parse(source)


def _function(tree, name):
    return next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _np_load_calls(node):
    return [
        sub for sub in ast.walk(node)
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
        and sub.func.attr == "load" and isinstance(sub.func.value, ast.Name)
        and sub.func.value.id == "np"
    ]


def _with_item_calls(node):
    """Every call that is the context expression of a `with` in `node`."""
    found = []
    for sub in ast.walk(node):
        if isinstance(sub, (ast.With, ast.AsyncWith)):
            for item in sub.items:
                if isinstance(item.context_expr, ast.Call):
                    found.append(item.context_expr)
    return found


def test_load_snapshot_holds_exactly_one_np_load_inside_a_context_manager():
    tree = _module_tree()
    loader = _function(tree, "load_snapshot")
    loads = _np_load_calls(loader)
    assert len(loads) == 1
    context_calls = _with_item_calls(loader)
    assert loads[0] in context_calls  # lexically the `with` expression


def test_is_valid_snapshot_npz_retains_its_own_context_managed_load():
    tree = _module_tree()
    validator = _function(tree, "_is_valid_snapshot_npz")
    loads = _np_load_calls(validator)
    assert len(loads) == 1
    assert loads[0] in _with_item_calls(validator)


def test_process_snapshot_opens_no_archive_of_its_own():
    tree = _module_tree()
    processor = _function(tree, "process_snapshot")
    assert _np_load_calls(processor) == []
    calls = [
        sub.func.id for sub in ast.walk(processor)
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
    ]
    assert "load_snapshot" in calls  # state comes only through the loader


def test_module_has_exactly_two_np_load_call_sites():
    """The loader and the validator — no other archive-opening path exists."""
    tree = _module_tree()
    all_loads = _np_load_calls(tree)
    assert len(all_loads) == 2
    owners = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and _np_load_calls(node)
    }
    assert owners == {"load_snapshot", "_is_valid_snapshot_npz"}
