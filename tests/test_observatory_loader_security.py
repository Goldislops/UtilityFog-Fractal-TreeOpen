"""Observatory NPZ loading refuses pickle.

`np.load(..., allow_pickle=True)` hands an untrusted archive to the unpickler,
and unpickling is arbitrary code execution by construction. This module proves
the Observatory's NPZ route refuses object-dtype members instead, using a
harmless payload that would leave a marker file if it were ever invoked.

Scope of the claim, stated once and honestly: this is an **object-array
refusal**, not whole-archive validation. Nothing here claims resistance to
decompression amplification, absurd declared shapes, hostile member names or
defects in NumPy's own header parsing. The same wording is used by
`scripts/dandelion.py`, which made this change first (PR #432).
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

# The Observatory package initializer imports `loader.py` and through it NumPy.
# Guard before the package import so a missing optional stack is a clean skip.
np = pytest.importorskip("numpy")

from vis.observatory import loader

NUM_CHANNELS = 8
SHAPE = (2, 3, 4)

#: Written only if a pickle payload is actually executed. Its absence after a
#: load attempt is the proof that nothing ran.
MARKER_NAME = "PICKLE_PAYLOAD_EXECUTED"


def _create_marker(directory: str) -> str:
    """Stand in for a malicious pickle payload.

    Deliberately inert: it writes one small file inside the directory pytest
    already owns and cleans up, and returns. A real payload would call
    something far less pleasant -- the point is that the reduction is invoked
    at all, not what it does.

    Module scope is required: pickle stores a module-qualified reference, so a
    function defined inside a test body could not be resolved at load time.
    """
    marker = Path(directory) / MARKER_NAME
    marker.write_text("payload executed", encoding="utf-8")
    return str(marker)


class _PayloadOnUnpickle:
    """An object whose reduction calls :func:`_create_marker` when unpickled.

    `__reduce__` is evaluated at PICKLE time and merely records the callable
    and its arguments; the call happens at UNPICKLE time. So writing this into
    an archive is safe, and only loading it with pickle enabled would fire.
    """

    def __init__(self, directory):
        self._directory = str(directory)

    def __reduce__(self):
        return (_create_marker, (self._directory,))


def _payload_array(directory):
    """A 1-element object array carrying the payload."""
    return np.array([_PayloadOnUnpickle(directory)], dtype=object)


def _lattice():
    return np.zeros(SHAPE, dtype=np.uint8)


def _grid(channels=NUM_CHANNELS):
    return np.zeros((channels,) + SHAPE, dtype=np.float32)


def _write(path, **members):
    """Write an NPZ. Object members pickle on the way in, which is harmless."""
    payload = {
        "lattice": _lattice(),
        "memory_grid": _grid(),
        "generation": 7,
        "ca_step": 11,
        "best_fitness": 0.25,
    }
    payload.update(members)
    np.savez(path, **payload)
    return str(path) if str(path).endswith(".npz") else f"{path}.npz"


def _marker(tmp_path):
    return tmp_path / MARKER_NAME


# ---------------------------------------------------------------------------
# The payload fixture is real: it fires when pickle is enabled
# ---------------------------------------------------------------------------


def test_the_payload_fixture_actually_fires_when_pickle_is_enabled(tmp_path):
    """A control on the other tests. If this did not fire, every "marker is
    absent" assertion below would be vacuous -- they would pass against a
    payload that never worked in the first place.

    This deliberately calls `np.load` directly with pickle ENABLED. It does not
    go through the Observatory loader, and it is the only place in the suite
    that does so.
    """
    archive = _write(tmp_path / "control.npz", lattice=_payload_array(tmp_path))
    assert not _marker(tmp_path).exists()

    with np.load(archive, allow_pickle=True) as snap:
        snap["lattice"]

    assert _marker(tmp_path).exists(), "the payload fixture is inert; fix it"


# ---------------------------------------------------------------------------
# Required arrays
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["lattice", "memory_grid"])
def test_object_payload_in_a_required_array_is_refused(tmp_path, field):
    archive = _write(tmp_path / f"{field}.npz", **{field: _payload_array(tmp_path)})

    with pytest.raises(ValueError) as excinfo:
        loader.load_npz(archive)

    assert "allow_pickle=False" in str(excinfo.value)
    assert not _marker(tmp_path).exists(), "the pickle payload executed"


# ---------------------------------------------------------------------------
# Recognized metadata
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["generation", "ca_step", "best_fitness"])
def test_object_payload_in_recognized_metadata_is_refused(tmp_path, field):
    """`.get(key, default)` decodes the member when the key is present, so a
    metadata field is just as much an execution site as a required array."""
    archive = _write(tmp_path / f"{field}.npz", **{field: _payload_array(tmp_path)})

    with pytest.raises(ValueError) as excinfo:
        loader.load_npz(archive)

    assert "allow_pickle=False" in str(excinfo.value)
    assert not _marker(tmp_path).exists(), "the pickle payload executed"


@pytest.mark.parametrize("field", ["generation", "ca_step", "best_fitness"])
def test_object_bearing_structured_metadata_is_refused(tmp_path, field):
    """A structured dtype can hide an object field, so `kind == 'O'` alone is
    not the test -- NumPy's own refusal covers `dtype.hasobject`."""
    structured = np.empty((1,), dtype=[("payload", "O"), ("n", "i4")])
    structured["payload"][0] = _PayloadOnUnpickle(tmp_path)
    structured["n"][0] = 1
    archive = _write(tmp_path / f"struct_{field}.npz", **{field: structured})

    with pytest.raises(ValueError):
        loader.load_npz(archive)

    assert not _marker(tmp_path).exists(), "the pickle payload executed"


# ---------------------------------------------------------------------------
# Unreferenced members
# ---------------------------------------------------------------------------


def test_an_unreferenced_hostile_member_is_never_deserialized(tmp_path):
    """NumPy's NPZ access is lazy: a member is decoded only when read. An extra
    member the Observatory never asks for is therefore ignored, not executed.

    The snapshot itself is well-formed, so this must LOAD successfully -- an
    unreferenced member is not grounds for refusal.
    """
    archive = _write(tmp_path / "extra.npz", unreferenced=_payload_array(tmp_path))

    snapshot = loader.load_npz(archive)

    assert snapshot.lattice.dtype == np.uint8
    assert snapshot.memory_grid.dtype == np.float32
    assert not _marker(tmp_path).exists(), "an unread member was deserialized"


# ---------------------------------------------------------------------------
# No escape hatch
# ---------------------------------------------------------------------------


def test_loader_never_enables_pickle_anywhere(tmp_path):
    """Parsed, not grepped: every `np.load` call in the loader must pass
    `allow_pickle=False` explicitly. A bare call inherits NumPy's default,
    which is False today but is not a contract this module should rely on.
    """
    source = Path(inspect.getsourcefile(loader)).read_text(encoding="utf-8")
    calls = 0
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "load":
            continue
        calls += 1
        keywords = {kw.arg: kw.value for kw in node.keywords}
        assert "allow_pickle" in keywords, "np.load must set allow_pickle explicitly"
        value = keywords["allow_pickle"]
        assert isinstance(value, ast.Constant) and value.value is False, (
            "allow_pickle must be the literal False, not a variable or flag"
        )
    assert calls >= 1, "no np.load call found in the loader"


def test_no_pickle_enabling_escape_hatch_exists():
    """No flag, environment variable or compatibility mode may re-enable it."""
    source = Path(inspect.getsourcefile(loader)).read_text(encoding="utf-8")
    for banned in ("allow_pickle=True", "ALLOW_PICKLE", "allow-pickle",
                   "getenv", "environ"):
        assert banned not in source, f"loader references {banned}"


def test_a_refusal_is_never_retried_with_pickle_enabled(tmp_path, monkeypatch):
    """A fallback retry would defeat the whole change. The refusal must be
    terminal: exactly one archive open, and no second attempt."""
    archive = _write(tmp_path / "retry.npz", lattice=_payload_array(tmp_path))

    real_load = np.load
    calls = []

    def _recording_load(*args, **kwargs):
        calls.append(kwargs.get("allow_pickle"))
        return real_load(*args, **kwargs)

    monkeypatch.setattr(loader.np, "load", _recording_load)

    with pytest.raises(ValueError):
        loader.load_npz(archive)

    assert calls == [False], f"expected exactly one pickle-free open, got {calls}"
    assert not _marker(tmp_path).exists()


# ---------------------------------------------------------------------------
# Archive closure on refusal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["lattice", "memory_grid", "generation"])
def test_the_archive_is_closed_when_a_member_is_refused(tmp_path, field):
    """The refusal happens at member access, inside the context. The handle
    must still be released -- on Windows a retained handle blocks deleting or
    rotating the snapshot."""
    target = tmp_path / f"closed_{field}.npz"
    archive = _write(target, **{field: _payload_array(tmp_path)})

    with pytest.raises(ValueError):
        loader.load_npz(archive)

    # If the handle leaked, this raises PermissionError on Windows.
    Path(archive).unlink()
    assert not Path(archive).exists()


# ---------------------------------------------------------------------------
# Numeric compatibility is untouched
# ---------------------------------------------------------------------------


def test_a_numeric_snapshot_still_loads_and_converts(tmp_path):
    archive = _write(
        tmp_path / "numeric.npz",
        lattice=np.ones(SHAPE, dtype=np.int32),
        memory_grid=np.ones((NUM_CHANNELS,) + SHAPE, dtype=np.float64),
        generation=np.int64(5),
        ca_step=np.int64(6),
        best_fitness=np.float32(0.5),
    )
    snapshot = loader.load_npz(archive)
    assert snapshot.lattice.dtype == np.uint8
    assert snapshot.memory_grid.dtype == np.float32
    assert snapshot.generation == 5 and type(snapshot.generation) is int
    assert snapshot.ca_step == 6 and type(snapshot.ca_step) is int
    assert snapshot.best_fitness == pytest.approx(0.5)
    assert type(snapshot.best_fitness) is float


def test_metadata_defaults_survive(tmp_path):
    path = tmp_path / "bare.npz"
    np.savez(path, lattice=_lattice(), memory_grid=_grid())
    snapshot = loader.load_npz(str(path))
    assert (snapshot.generation, snapshot.ca_step, snapshot.best_fitness) == (0, 0, 0.0)


@pytest.mark.parametrize("channels", [3, 5])
def test_legacy_numeric_grids_still_migrate_to_eight_channels(tmp_path, channels):
    archive = _write(tmp_path / f"legacy{channels}.npz", memory_grid=_grid(channels))
    snapshot = loader.load_npz(archive)
    assert snapshot.memory_grid.shape == (NUM_CHANNELS,) + SHAPE
    assert snapshot.memory_grid.dtype == np.float32


def test_load_snapshot_inherits_the_refusal(tmp_path):
    """The public dispatch route, not just `load_npz` directly."""
    archive = _write(tmp_path / "dispatch.npz", lattice=_payload_array(tmp_path))
    with pytest.raises(ValueError):
        loader.load_snapshot(archive)
    assert not _marker(tmp_path).exists()


def test_series_loading_inherits_the_refusal(tmp_path):
    """One hostile member in a series must not execute, and the archives
    already opened must be closed before the failure propagates."""
    series = tmp_path / "series"
    series.mkdir()
    np.savez(series / "v070_000.npz", lattice=_lattice(), memory_grid=_grid())
    np.savez(series / "v070_001.npz", lattice=_payload_array(tmp_path),
             memory_grid=_grid())

    with pytest.raises(ValueError):
        loader.load_snapshot_series(str(series))

    assert not _marker(tmp_path).exists()
    for member in sorted(series.glob("*.npz")):
        member.unlink()          # raises if a handle leaked


def test_a_clean_series_still_loads(tmp_path):
    series = tmp_path / "clean"
    series.mkdir()
    for index in range(2):
        np.savez(series / f"v070_{index:03d}.npz",
                 lattice=_lattice(), memory_grid=_grid(), generation=index)
    snapshots = loader.load_snapshot_series(str(series))
    assert len(snapshots) == 2
    assert [s.generation for s in snapshots] == [0, 1]


# ---------------------------------------------------------------------------
# Established failure modes are unchanged
# ---------------------------------------------------------------------------


def test_a_missing_required_key_still_raises_keyerror(tmp_path):
    path = tmp_path / "nokeys.npz"
    np.savez(path, memory_grid=_grid())
    with pytest.raises(KeyError):
        loader.load_npz(str(path))


def test_a_corrupt_archive_still_raises(tmp_path):
    path = tmp_path / "corrupt.npz"
    path.write_bytes(b"not an npz at all")
    with pytest.raises(Exception) as excinfo:
        loader.load_npz(str(path))
    assert not isinstance(excinfo.value, AssertionError)
