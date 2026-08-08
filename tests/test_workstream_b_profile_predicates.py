"""Archive-lifetime contract for `scripts.workstream_b_profile_predicates.load_snapshot`.

PR #458 made every repository snapshot consumer pickle-free and gave five of
them deterministic archive ownership. It disclosed one loader left behind:
this one. It already passed a literal ``allow_pickle=False`` -- so the pickle
sweep was satisfied -- but it did NOT close the archive. It previously read::

    data = np.load(str(path), allow_pickle=False)
    state = data["lattice"]
    ...
    return state, memory, gen

Release therefore depended on `NpzFile.__del__` running when the last reference
to `data` dropped. Two reasons that was not good enough:

  * On the EXCEPTIONAL path a propagating exception keeps this frame alive
    through its traceback, so `data` stays referenced and the archive stays
    open for as long as any handler retains that traceback.
  * Finalisation is a CPython refcounting artifact, not an ownership boundary.
    It is exactly the mechanism every sibling suite in this repository
    explicitly disclaims when it proves closure.

Scope, stated honestly: this loader is an operator-invoked offline CLI reading
one archive at a time, so it is the LEAST reachable of the consumers -- the
claim here is deterministic release, not a fix for a live service leak.

Nothing here starts the profiler. `load_snapshot` calls no other function
defined in that module -- only `np.load`, `int`, `str`, `isinstance` and
`contextlib.nullcontext` -- and the results document is written solely by
`main()`, which is `__name__`-guarded and unreachable from these tests.
"""

from __future__ import annotations

import ast
import inspect
import sys
import types
from unittest import mock

import pytest


def _optional_dependency_stubs() -> dict:
    """Test-only stand-ins for the target module's hard imports.

    `scripts/workstream_b_profile_predicates.py` imports NumPy unconditionally
    and, worse for collection, does ``from scipy import ndimage`` at module
    scope inside a ``try`` that raises **SystemExit** when SciPy is missing.
    CI installs `numpy pytest pytest-asyncio matplotlib flask pyzmq openai` and
    NOT scipy, so importing this module normally would abort collection --
    `SystemExit` derives from `BaseException`, so it is not caught as an
    ordinary import error.

    Only a genuinely-absent module is stubbed; where the real package is
    installed it is used untouched. `patch.dict` restores `sys.modules`
    immediately afterwards, and the target keeps its own references to whatever
    was bound during the import.

    The scipy stub must carry `ndimage` as an ATTRIBUTE: a bare parent module
    makes ``from scipy import ndimage`` raise ImportError, which the target's
    own ``except ImportError`` would catch -- producing the very SystemExit
    this stub exists to avoid. Registering `sys.modules["scipy.ndimage"]` as
    well covers the submodule-import path.
    """
    stubs: dict = {}
    try:
        import numpy  # noqa: F401
    except ImportError:
        stubs["numpy"] = types.ModuleType("numpy")
    try:
        from scipy import ndimage  # noqa: F401
    except ImportError:
        scipy_stub = types.ModuleType("scipy")
        ndimage_stub = types.ModuleType("scipy.ndimage")
        ndimage_stub.label = lambda *a, **k: (None, 0)
        scipy_stub.ndimage = ndimage_stub
        stubs["scipy"] = scipy_stub
        stubs["scipy.ndimage"] = ndimage_stub
    return stubs


with mock.patch.dict(sys.modules, _optional_dependency_stubs()):
    from scripts import workstream_b_profile_predicates as wb

# `patch.dict` restores by clear()+update(), so the module imported inside the
# block is evicted from `sys.modules` on exit. That is left alone DELIBERATELY.
# Re-publishing it under the canonical name looked tidier, but on CI -- where
# scipy is genuinely absent -- the module's `ndimage` is this file's stub, and
# a later importer reaching `compute_cluster_profile` would silently get a fake
# labelling instead of the SystemExit that means "scipy is missing". An
# inert eviction is better than a live silent fake. Nothing else imports this
# module today; `wb` below is the only reference these tests need.


try:
    import numpy as np
    _HAVE_NUMPY = True
except ImportError:  # pragma: no cover - exercised only in a bare environment
    np = None
    _HAVE_NUMPY = False

requires_numpy = pytest.mark.skipif(not _HAVE_NUMPY, reason="numpy not installed")

#: The members `load_snapshot` dereferences, in the loader's own source order.
#: Order is load-bearing: the FIRST missing member decides which `KeyError`
#: wins, and later accesses are never reached.
REQUIRED_MEMBERS = ("lattice", "memory_grid", "generation")


# ---------------------------------------------------------------------------
# Static contract
# ---------------------------------------------------------------------------


def _loader_ast() -> ast.FunctionDef:
    """The live `load_snapshot` definition, lifted from the installed source."""
    tree = ast.parse(inspect.getsource(wb))
    found = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "load_snapshot"
    ]
    assert len(found) == 1, "expected exactly one load_snapshot definition"
    return found[0]


def _np_load_calls(node) -> list:
    return [
        call for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "load"
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "np"
    ]


def test_the_loader_makes_exactly_one_np_load_call():
    """Non-vacuity anchor for every static assertion below.

    Each of them inspects "the load call"; if the loader ever stopped making
    one they would have nothing to inspect and could pass by looking at an
    empty list. This is where that fails loudly instead.
    """
    assert len(_np_load_calls(_loader_ast())) == 1


def test_np_load_receives_the_str_coerced_path():
    """`str(path)` is preserved verbatim.

    It is inert for the annotated `pathlib.Path` and for the module's only
    caller, but it is behaviour-defining for bytes paths, file-like objects and
    non-`Path` `os.PathLike` values -- `str()` turns each of those into a
    nonsense filename and a `FileNotFoundError` rather than a working load.
    Removing it would be a silent interface change, so it is pinned.
    """
    call = _np_load_calls(_loader_ast())[0]
    assert len(call.args) == 1, "the path is passed positionally, once"
    arg = call.args[0]
    assert isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
    assert arg.func.id == "str", "the str() coercion was dropped"


def test_allow_pickle_is_the_literal_false():
    """Unchanged from the base commit, and re-pinned here because this package
    edits the same statement. An NPZ member of object dtype is stored as a
    pickle; loading one with pickle enabled is arbitrary code execution."""
    call = _np_load_calls(_loader_ast())[0]
    keywords = {kw.arg: kw.value for kw in call.keywords}
    assert set(keywords) == {"allow_pickle"}
    value = keywords["allow_pickle"]
    assert isinstance(value, ast.Constant) and value.value is False


def test_no_mmap_mode_is_supplied():
    """Load-bearing, and pinned by its own name rather than incidentally.

    `np.load` returns a `np.memmap` when `mmap_mode` is passed. A memmap IS an
    ndarray subclass, so it would take the `nullcontext` branch and its mapping
    would never be released -- and it has neither `close()` nor `__enter__`, so
    the `with` could not own it even if the branch were changed. The exclusion
    was previously guaranteed only as a side effect of a keyword-set equality
    inside a test about pickle; relaxing that to a membership check would have
    silently unpinned it.
    """
    call = _np_load_calls(_loader_ast())[0]
    assert len(call.args) == 1, "mmap_mode could arrive as the second positional"
    assert "mmap_mode" not in {kw.arg for kw in call.keywords}


def test_the_loader_reads_the_three_required_members_in_source_order():
    """Derived from the source, not transcribed, so it cannot drift."""
    loader = _loader_ast()
    # Sorted by (lineno, col_offset) because `ast.walk` does not preserve
    # source order, and two accesses could share a line.
    accesses = sorted(
        (node.lineno, node.col_offset, node.slice.value)
        for node in ast.walk(loader)
        if isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    )
    assert accesses, "no constant-string member access found in the loader"

    ordered, seen = [], set()
    for _lineno, _col, member in accesses:
        if member not in seen:
            seen.add(member)
            ordered.append(member)
    assert tuple(ordered) == REQUIRED_MEMBERS


# ---------------------------------------------------------------------------
# Runtime helpers
# ---------------------------------------------------------------------------


def _write_npz(tmp_path, name="snap.npz", **members):
    archive = tmp_path / name
    np.savez(archive, **members)
    return archive


def _valid_members(generation=7):
    return {
        "lattice": np.arange(8, dtype=np.uint8).reshape(2, 2, 2),
        "memory_grid": np.zeros((8, 2, 2, 2), dtype=np.float32),
        "generation": np.int64(generation),
    }


class _Tracker:
    """Records every real archive `np.load` produced, and its open state."""

    def __init__(self):
        self.opened = []
        self.handles = []
        self.open_at_load = []
        self.fid_open_at_load = []
        self.calls = []

    def install(self, monkeypatch):
        real_load = np.load

        def tracking_load(*args, **kwargs):
            self.calls.append((args, dict(kwargs)))
            handle = real_load(*args, **kwargs)
            # Held for the test's lifetime, so `NpzFile.__del__` cannot close
            # the archive on our behalf -- a pass must come from production.
            self.opened.append(handle)
            fid = getattr(handle, "fid", None)
            self.handles.append(fid)
            # Sampled AT LOAD TIME. Asserting this later would be wrong: by
            # then the loader has correctly closed it.
            self.fid_open_at_load.append(fid is not None and not fid.closed)
            # `zip` is set unconditionally by `NpzFile.__init__` and dropped by
            # `close()`. A plain ndarray (from a `.npy`) has no `zip` at all.
            self.open_at_load.append(getattr(handle, "zip", None) is not None)
            return handle

        monkeypatch.setattr(wb.np, "load", tracking_load)
        return self

    def assert_archive_was_open(self):
        assert self.open_at_load == [True], (
            "the archive was never observed open; a closure claim here would "
            "be vacuous"
        )
        assert self.fid_open_at_load == [True], (
            "the archive never owned an OPEN file object at load; a closure "
            "claim on it would be vacuous"
        )

    def assert_archive_is_closed(self):
        """Both halves, because `zip is None` alone is not enough.

        `NpzFile.close()` drops `zip` BEFORE it closes `fid`, and the `ZipFile`
        was built over an already-open file object, so `ZipFile.close()`
        deliberately leaves that descriptor alone. A `close()` that dropped
        `zip` and returned early would satisfy a `zip`-only assertion while
        leaking the descriptor -- which is the whole subject of this module.
        """
        assert self.opened, "np.load was never reached"
        assert self.opened[0].zip is None, "the archive was not closed"
        assert self.handles and self.handles[0] is not None, (
            "the archive never owned a file object; a closure claim on it "
            "would be vacuous"
        )
        assert self.handles[0].closed, "the underlying file object is still open"


@requires_numpy
def test_the_real_archive_is_open_at_load_and_closed_by_the_loader(
    tmp_path, monkeypatch
):
    """The core defect.

    The handle is retained by the tracker, so `NpzFile.__del__` cannot fire and
    a passing result cannot come from finalisation. Non-vacuous from both ends:
    the archive is asserted GENUINELY OPEN at load before the closure claim.

    Named precisely. The assertion runs after `load_snapshot` returns, so what
    it proves is that the LOADER closed the archive -- not the instant at which
    it did so. The ordering claim that closure precedes downstream work is not
    made here, because this loader has no downstream work to order against.
    """
    archive = _write_npz(tmp_path, **_valid_members())
    tracker = _Tracker().install(monkeypatch)

    wb.load_snapshot(archive)

    tracker.assert_archive_was_open()
    tracker.assert_archive_is_closed()


@requires_numpy
def test_returned_values_survive_closure_unchanged(tmp_path, monkeypatch):
    """`NpzFile.__getitem__` materialises a real in-memory copy, so closing the
    archive first cannot truncate or invalidate what was returned."""
    members = _valid_members(generation=11)
    archive = _write_npz(tmp_path, **members)
    tracker = _Tracker().install(monkeypatch)

    state, memory, gen = wb.load_snapshot(archive)

    tracker.assert_archive_was_open()
    tracker.assert_archive_is_closed()
    assert np.array_equal(state, members["lattice"])
    assert state.dtype == members["lattice"].dtype
    assert np.array_equal(memory, members["memory_grid"])
    assert memory.dtype == members["memory_grid"].dtype
    assert gen == 11 and type(gen) is int


@requires_numpy
@pytest.mark.parametrize("missing", REQUIRED_MEMBERS)
def test_a_missing_member_closes_the_archive_and_propagates_keyerror(
    tmp_path, monkeypatch, missing
):
    """The exceptional path is where finalisation is least trustworthy: a live
    traceback keeps this frame, and therefore the archive, alive."""
    members = _valid_members()
    del members[missing]
    archive = _write_npz(tmp_path, **members)
    tracker = _Tracker().install(monkeypatch)

    with pytest.raises(KeyError):
        wb.load_snapshot(archive)

    tracker.assert_archive_was_open()
    tracker.assert_archive_is_closed()


@requires_numpy
def test_a_synthetic_member_exception_propagates_by_identity_and_closes(
    tmp_path, monkeypatch
):
    """An arbitrary exception from a member access must reach the caller
    UNCHANGED -- same object, not merely the same class -- and must still leave
    the archive closed."""
    archive = _write_npz(tmp_path, **_valid_members())
    sentinel = RuntimeError("member access exploded")
    real_load = np.load
    opened = []
    captured_fid = []
    wrapper_reads = []

    class _Exploding:
        def __init__(self, inner):
            self._inner = inner
            self.reads = 0

        def __getitem__(self, key):
            self.reads += 1
            if key == "memory_grid":
                raise sentinel
            return self._inner[key]

        def __getattr__(self, name):
            # Guard the classic trap: without this, any access before
            # `_inner` is assigned recurses until the stack is exhausted.
            if name == "_inner":
                raise AttributeError(name)
            return getattr(self._inner, name)

        def __enter__(self):
            self._inner.__enter__()
            return self

        def __exit__(self, *exc):
            return self._inner.__exit__(*exc)

    exploders = []

    def exploding_load(*args, **kwargs):
        inner = real_load(*args, **kwargs)
        opened.append(inner)
        captured_fid.append(inner.fid)
        wrapper = _Exploding(inner)
        exploders.append(wrapper)
        return wrapper

    monkeypatch.setattr(wb.np, "load", exploding_load)

    with pytest.raises(RuntimeError) as excinfo:
        wb.load_snapshot(archive)

    wrapper_reads.extend(w.reads for w in exploders)
    original_fid = captured_fid[0] if captured_fid else None

    assert excinfo.value is sentinel, "the exception was replaced, not propagated"
    assert opened, "np.load was never reached"
    # The wrapper really was used, and `lattice` really was read before the
    # explosion -- so this proves closure after a MID-EXTRACTION failure, not
    # after a failure on the very first access.
    assert wrapper_reads == [2], f"expected two member reads, got {wrapper_reads}"
    assert opened[0].zip is None, "the archive survived a member-access failure"
    # The ORIGINAL file object, captured while open. `opened[0].fid` would be
    # useless here: `close()` sets it to None, so `fid is None or fid.closed`
    # is unconditionally true afterwards and the descriptor leg would be dead.
    assert original_fid is not None, "the archive never owned a file object"
    assert original_fid.closed, (
        "the underlying file object survived a member-access failure"
    )


@requires_numpy
def test_a_load_time_failure_propagates_and_is_never_retried(tmp_path, monkeypatch):
    """No fallback lane: one attempt, and the original error reaches the caller."""
    boom = OSError("archive unreadable")
    calls = []

    def failing_load(*args, **kwargs):
        calls.append(kwargs.get("allow_pickle", "<absent>"))
        raise boom

    monkeypatch.setattr(wb.np, "load", failing_load)

    with pytest.raises(OSError) as excinfo:
        wb.load_snapshot(tmp_path / "missing.npz")

    assert excinfo.value is boom
    assert calls == [False], f"expected exactly one pickle-free attempt, got {calls}"


# ---------------------------------------------------------------------------
# Legacy `.npy` behaviour -- must NOT change
# ---------------------------------------------------------------------------


def _legacy_npy_error_class():
    """The class a numeric `.npy` produces, derived rather than remembered.

    `np.load` returns a plain ndarray for a `.npy`, so the loader's first
    statement after the load -- ``data["lattice"]`` -- is a constant-string
    subscript on an ndarray. Reproducing that exact operation pins the contract
    to real NumPy behaviour.

    This matters because the obvious fix is wrong: a bare
    ``with np.load(...) as data:`` raises `TypeError` from the context-manager
    protocol BEFORE the subscript is reached, changing both the class and the
    failure point. Conditional ownership avoids that.
    """
    probe = np.zeros(2)
    try:
        probe["lattice"]
    except Exception as exc:  # noqa: BLE001 - the class IS the thing under test
        return type(exc)
    raise AssertionError(
        "a constant-string subscript on a plain ndarray no longer raises"
    )


#: Named as well as derived, so the contract is readable without running
#: anything; the parity test below keeps the two from drifting apart. Matches
#: `tests/test_lucid_server.py` and `tests/test_portable_genome_config_shapes.py`.
_LEGACY_NPY_ERROR = IndexError


@requires_numpy
def test_the_named_legacy_npy_class_is_what_numpy_actually_raises():
    derived = _legacy_npy_error_class()
    assert derived is _LEGACY_NPY_ERROR, (
        f"the legacy class is actually {derived.__name__}, not "
        f"{_LEGACY_NPY_ERROR.__name__}; update _LEGACY_NPY_ERROR"
    )
    # Non-vacuity: `TypeError` is what the bare-`with` regression raises. If the
    # legacy class were also `TypeError` this suite could not tell the correct
    # implementation from the broken one.
    assert derived is not TypeError


@requires_numpy
def test_a_numeric_npy_keeps_its_legacy_exception_class(tmp_path):
    """Guards the fix against becoming a regression."""
    not_an_archive = tmp_path / "snap.npy"
    np.save(not_an_archive, np.arange(8, dtype=np.uint8))

    with pytest.raises(_legacy_npy_error_class()):
        wb.load_snapshot(not_an_archive)


@requires_numpy
def test_an_object_dtype_npy_is_refused_before_anything_is_reconstructed(tmp_path):
    """`allow_pickle=False` refuses at `np.load` itself for a `.npy`, so nothing
    is returned and no reduction callback runs."""
    hostile = tmp_path / "hostile.npy"
    np.save(hostile, np.array({"a": 1}, dtype=object), allow_pickle=True)

    with pytest.raises(ValueError) as excinfo:
        wb.load_snapshot(hostile)

    assert "allow_pickle=False" in str(excinfo.value)


# ---------------------------------------------------------------------------
# No profiling side effects
# ---------------------------------------------------------------------------


def test_the_loader_cannot_reach_the_results_document_or_the_profiler():
    """Structural proof that exercising `load_snapshot` starts nothing.

    The results markdown is written only by `main()`, which is `__name__`
    -guarded. `load_snapshot` calls nothing defined in this module.
    """
    loader = _loader_ast()
    called = {
        node.func.id for node in ast.walk(loader)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    module_functions = {
        node.name for node in ast.parse(inspect.getsource(wb)).body
        if isinstance(node, ast.FunctionDef)
    }
    assert module_functions, "no module-level functions found; the lift is broken"
    assert not (called & module_functions), (
        f"load_snapshot reaches module functions: {sorted(called & module_functions)}"
    )
    assert "write_text" not in inspect.getsource(wb.load_snapshot)
