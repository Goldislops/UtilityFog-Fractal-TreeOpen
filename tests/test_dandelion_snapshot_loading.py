"""Tests for the snapshot-archive loading boundary shared by ``stl``/``glb``/``slices``.

Scope: ONLY how the public Dandelion CLI extracts the ``lattice`` member from an
NPZ snapshot. Two properties are pinned:

* **no pickle** — the archive is opened with ``allow_pickle=False``, so an
  object-dtype ``lattice`` is refused by NumPy instead of being unpickled and
  handed to an exporter;
* **deterministic archive lifetime** — the NPZ archive is opened as a context
  manager and is already closed before the selected exporter is invoked, on the
  success path and on every failure path.

Ordinary numeric-lattice behaviour is unchanged and is locked here.

This is deliberately NOT whole-NPZ validation, archive-size control, ZIP-bomb
resistance, lattice-shape or state validation, path containment, atomic-file
handling or snapshot-schema enforcement. No claim is made that a hostile archive
is safe to load — only that object arrays are refused and the handle is closed.

Every test uses synthetic arrays, temporary NPZ files and monkeypatched
exporters. No real marching cubes, trimesh, Pillow, Medusa artifact, network,
engine, observer or calibration run is touched, and no malicious pickle is ever
constructed or executed — the object-array test uses a harmless payload and
proves *refusal*, not exploitability.
"""

from __future__ import annotations

import numpy as np
import pytest

import scripts.dandelion as dandelion

#: (command, exporter attribute, extra argv, kwargs the exporter receives)
COMMANDS = [
    pytest.param("stl", "lattice_to_stl", ["--output"], id="stl"),
    pytest.param("glb", "lattice_to_glb", ["--output"], id="glb"),
    pytest.param("slices", "lattice_to_voxel_slices", ["--output-dir"], id="slices"),
]


def _write_npz(path, **members):
    np.savez(path, **members)
    return str(path)


def _numeric_lattice():
    return np.arange(27, dtype=np.int8).reshape(3, 3, 3)


def _argv(command, snapshot, flag, target):
    return [command, snapshot, flag, str(target)]


# ---------------------------------------------------------------------------
# 1. All three commands disable pickle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command, exporter, flags", COMMANDS)
def test_every_snapshot_command_disables_pickle(
    tmp_path, monkeypatch, command, exporter, flags
):
    snapshot = _write_npz(tmp_path / "snap.npz", lattice=_numeric_lattice())
    calls: list = []
    real_load = np.load

    def recording_load(file, *args, **kwargs):
        calls.append({"file": str(file), "args": args, "kwargs": dict(kwargs)})
        return real_load(file, *args, **kwargs)

    monkeypatch.setattr(dandelion.np, "load", recording_load)
    monkeypatch.setattr(dandelion, exporter, lambda *a, **k: None)

    dandelion.main(_argv(command, snapshot, flags[0], tmp_path / "out"))

    assert len(calls) == 1, f"expected exactly one np.load, got {len(calls)}"
    assert calls[0]["kwargs"].get("allow_pickle") is False, (
        f"expected allow_pickle=False, got {calls[0]['kwargs'].get('allow_pickle')!r}"
    )


# ---------------------------------------------------------------------------
# Controlled fake archive used by the lifetime tests
# ---------------------------------------------------------------------------


class _FakeArchive:
    """Records the exact order of enter / member access / exit."""

    def __init__(self, log, member, raise_on_access=None):
        self._log = log
        self._member = member
        self._raise = raise_on_access
        self.closed = False
        self.entered = False

    def __enter__(self):
        self.entered = True
        self._log.append("enter")
        return self

    def __exit__(self, *exc):
        self.closed = True
        self._log.append("exit")
        return False

    def __getitem__(self, key):
        self._log.append(f"access:{key}")
        if self._raise is not None:
            raise self._raise
        if key != "lattice":
            raise KeyError(f"{key} is not a file in the archive")
        return self._member

    def close(self):
        self.closed = True
        self._log.append("close")


@pytest.fixture
def fake_archive(monkeypatch):
    """Install a fake ``np.load`` returning a controlled archive; return state."""

    def install(member=None, raise_on_access=None):
        state = {"log": [], "archive": None, "exporter_saw_closed": None}

        def fake_load(file, *args, **kwargs):
            state["log"].append("load")
            state["kwargs"] = dict(kwargs)
            arc = _FakeArchive(state["log"], member, raise_on_access)
            state["archive"] = arc
            return arc

        monkeypatch.setattr(dandelion.np, "load", fake_load)
        return state

    return install


# ---------------------------------------------------------------------------
# 2. The archive closes BEFORE the exporter is invoked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command, exporter, flags", COMMANDS)
def test_archive_is_closed_before_exporter_runs(
    tmp_path, monkeypatch, fake_archive, command, exporter, flags
):
    lattice = _numeric_lattice()
    state = fake_archive(member=lattice)

    def recording_exporter(*args, **kwargs):
        # The exporter itself asserts the handle is already gone.
        assert state["archive"].closed, "archive was still open when the exporter ran"
        state["exporter_saw_closed"] = True
        state["log"].append("exporter")
        return "out"

    monkeypatch.setattr(dandelion, exporter, recording_exporter)
    dandelion.main(_argv(command, str(tmp_path / "snap.npz"), flags[0], tmp_path / "out"))

    assert state["log"] == ["load", "enter", "access:lattice", "exit", "exporter"], (
        f"unexpected ordering: {state['log']}"
    )
    assert state["exporter_saw_closed"] is True


# ---------------------------------------------------------------------------
# 3. Numeric lattice and exporter arguments are preserved exactly
# ---------------------------------------------------------------------------


def test_numeric_lattice_and_arguments_reach_stl_unchanged(
    tmp_path, monkeypatch, fake_archive
):
    lattice = _numeric_lattice()
    fake_archive(member=lattice)
    seen: list = []
    monkeypatch.setattr(dandelion, "lattice_to_stl", lambda *a, **k: seen.append((a, k)))

    out = tmp_path / "organism.stl"
    dandelion.main(["stl", str(tmp_path / "s.npz"), "--output", str(out)])

    assert len(seen) == 1
    args, kwargs = seen[0]
    assert args[0] is lattice          # the very same object, no copy or cast
    assert args[1] == str(out)
    assert kwargs == {}


def test_numeric_lattice_and_arguments_reach_glb_unchanged(
    tmp_path, monkeypatch, fake_archive
):
    lattice = _numeric_lattice()
    fake_archive(member=lattice)
    seen: list = []
    monkeypatch.setattr(dandelion, "lattice_to_glb", lambda *a, **k: seen.append((a, k)))

    out = tmp_path / "organism.glb"
    dandelion.main(["glb", str(tmp_path / "s.npz"), "--output", str(out)])

    assert len(seen) == 1
    args, kwargs = seen[0]
    assert args[0] is lattice
    assert args[1] == str(out)
    assert kwargs == {}


def test_numeric_lattice_and_arguments_reach_slices_unchanged(
    tmp_path, monkeypatch, fake_archive
):
    lattice = _numeric_lattice()
    fake_archive(member=lattice)
    seen: list = []
    monkeypatch.setattr(
        dandelion, "lattice_to_voxel_slices", lambda *a, **k: seen.append((a, k))
    )

    out_dir = tmp_path / "slices_out"
    dandelion.main(
        ["slices", str(tmp_path / "s.npz"), "--output-dir", str(out_dir), "--scale", "3"]
    )

    assert len(seen) == 1
    args, kwargs = seen[0]
    assert args[0] is lattice
    assert args[1] == str(out_dir)
    assert kwargs == {"scale": 3}


def test_slices_scale_default_is_preserved(tmp_path, monkeypatch, fake_archive):
    fake_archive(member=_numeric_lattice())
    seen: list = []
    monkeypatch.setattr(
        dandelion, "lattice_to_voxel_slices", lambda *a, **k: seen.append((a, k))
    )
    dandelion.main(["slices", str(tmp_path / "s.npz")])
    assert seen[0][1] == {"scale": 1}


# ---------------------------------------------------------------------------
# 4. Object-dtype lattice is refused — real NPZ, harmless payload
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command, exporter, flags", COMMANDS)
def test_object_dtype_lattice_is_refused(
    tmp_path, monkeypatch, capsys, command, exporter, flags
):
    # A harmless object array. This proves object arrays are REFUSED; it is not
    # a malicious pickle and nothing hostile is ever constructed or executed.
    harmless = np.array([{"note": "harmless"}, None, "text"], dtype=object)
    snapshot = _write_npz(tmp_path / "obj.npz", lattice=harmless)
    out = tmp_path / "out"
    called: list = []
    monkeypatch.setattr(dandelion, exporter, lambda *a, **k: called.append(1) or "x")

    with pytest.raises(ValueError) as excinfo:
        dandelion.main(_argv(command, snapshot, flags[0], out))

    assert "allow_pickle=False" in str(excinfo.value)
    assert called == [], "exporter must never see an object-dtype lattice"
    assert not out.exists()
    captured = capsys.readouterr()
    for leaked in ("STL exported:", "GLB exported:", "Slices exported"):
        assert leaked not in captured.out


# ---------------------------------------------------------------------------
# 5. Missing member: archive closes, KeyError propagates, no argparse exit 2
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command, exporter, flags", COMMANDS)
def test_missing_lattice_member_closes_and_propagates(
    tmp_path, monkeypatch, command, exporter, flags
):
    snapshot = _write_npz(tmp_path / "nolattice.npz", other=np.zeros(3))
    called: list = []
    monkeypatch.setattr(dandelion, exporter, lambda *a, **k: called.append(1))

    with pytest.raises(KeyError):
        dandelion.main(_argv(command, snapshot, flags[0], tmp_path / "out"))

    assert called == []


def test_missing_member_closes_the_archive(tmp_path, monkeypatch):
    """A REAL NpzFile lacking the member: KeyError propagates, handle released."""
    calls: list = []
    archives: list = []
    real_load = np.load  # captured before any patching
    snapshot = _write_npz(tmp_path / "nolattice.npz", other=np.zeros(3))

    def tracking_load(file, *args, **kwargs):
        arc = real_load(file, *args, **kwargs)
        archives.append(arc)
        return arc

    monkeypatch.setattr(dandelion.np, "load", tracking_load)
    monkeypatch.setattr(dandelion, "lattice_to_stl", lambda *a, **k: calls.append(1))

    with pytest.raises(KeyError):
        dandelion.main(["stl", snapshot, "--output", str(tmp_path / "o.stl")])

    assert calls == []
    assert archives, "np.load was never called"
    # NpzFile.close() releases the underlying handle and sets fid to None.
    assert archives[0].fid is None or getattr(archives[0].fid, "closed", True)


# ---------------------------------------------------------------------------
# 6. Member-access failure: archive still closes, sentinel propagates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sentinel", [RuntimeError("boom"), MemoryError("oom")],
                         ids=["runtime-error", "memory-error"])
def test_member_access_failure_closes_archive_and_propagates(
    tmp_path, monkeypatch, fake_archive, sentinel
):
    state = fake_archive(raise_on_access=sentinel)
    called: list = []
    monkeypatch.setattr(dandelion, "lattice_to_stl", lambda *a, **k: called.append(1))

    with pytest.raises(type(sentinel)) as excinfo:
        dandelion.main(["stl", str(tmp_path / "s.npz"), "--output", str(tmp_path / "o")])

    assert excinfo.value is sentinel
    assert state["archive"].closed, "archive must close even when access raises"
    assert state["log"] == ["load", "enter", "access:lattice", "exit"]
    assert called == []


# ---------------------------------------------------------------------------
# 7. Load failure stays loud — no catch, no argparse translation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command, exporter, flags", COMMANDS)
def test_load_failure_propagates_untranslated(
    tmp_path, monkeypatch, command, exporter, flags
):
    sentinel = OSError("synthetic archive/filesystem failure")

    def failing_load(*args, **kwargs):
        raise sentinel

    monkeypatch.setattr(dandelion.np, "load", failing_load)
    called: list = []
    monkeypatch.setattr(dandelion, exporter, lambda *a, **k: called.append(1))

    with pytest.raises(OSError) as excinfo:
        dandelion.main(_argv(command, str(tmp_path / "s.npz"), flags[0], tmp_path / "o"))

    assert excinfo.value is sentinel
    assert not isinstance(excinfo.value, SystemExit)
    assert called == []


# ---------------------------------------------------------------------------
# 8. Direct exporters do not load snapshot files themselves (smoke guard)
# ---------------------------------------------------------------------------


def test_direct_exporters_do_not_load_snapshots(monkeypatch):
    """Smoke guard — the full exporter contracts live in their own suites."""
    loads: list = []
    monkeypatch.setattr(dandelion.np, "load", lambda *a, **k: loads.append(1))

    # Each exporter takes an in-memory lattice; none should reach np.load.
    with pytest.raises(Exception):
        dandelion.lattice_to_stl(np.zeros((2, 2, 2), dtype=np.int8), "unused.stl",
                                 states_to_include=[])
    assert loads == []
