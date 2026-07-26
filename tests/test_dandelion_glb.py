"""Tests for the empty-GLB-mesh refusal in ``scripts/dandelion.py``.

Scope: ONLY the empty-mesh guard on ``lattice_to_glb`` — the residual that
merged PR #418 explicitly disclosed and left outside its genome-root package.
``lattice_to_stl`` already refuses with ``ValueError("No non-void cells to
export")`` when no mesh is produced; these tests pin the same refusal, with the
same exception type and the same exact message, for the GLB path, plus the
behaviour that must NOT change around it.

This is deliberately NOT a claim of whole-module or whole-pipeline totality.
Lattice-shape validation, state-ID validation, snapshot-schema validation, path
validation and filesystem behaviour are all out of scope and unexercised here.

Every test uses synthetic arrays and ``tmp_path`` only — no real NPZ snapshot,
Medusa output, organism artifact, network, model, engine, observer or
calibration run is touched.

The optional ``trimesh`` / ``scikit-image`` stack is replaced by controlled
stand-ins injected into ``sys.modules``, so the contract stays exercised on a
seat where those packages are absent, and so surface extraction can be made to
succeed or fail deterministically without real marching-cubes geometry.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pytest

import scripts.dandelion as dandelion
from scripts.dandelion import STATE_NAMES, STATE_PRINT_COLORS

#: The exact refusal message ``lattice_to_stl`` already uses. The GLB path must
#: match it byte for byte — a drift here is a contract break, not a nit.
EXPECTED_MESSAGE = "No non-void cells to export"


class _FakeVisual:
    """Minimal stand-in for ``trimesh`` mesh ``.visual`` (records colours)."""

    def __init__(self) -> None:
        self.face_colors = None


class _FakeTrimesh:
    """Minimal stand-in for ``trimesh.Trimesh`` (records what it was built from)."""

    def __init__(self, vertices=None, faces=None, vertex_normals=None) -> None:
        self.vertices = vertices
        self.faces = faces
        self.vertex_normals = vertex_normals
        self.visual = _FakeVisual()


@pytest.fixture
def fake_glb_stack(monkeypatch):
    """Install controlled ``trimesh`` / ``skimage.measure`` stand-ins.

    Returns a callable taking the ``marching_cubes`` implementation to expose;
    calling it returns the list of ``Scene`` instances the module constructs, so
    a test can assert on what was added and whether ``export`` ever ran.
    """

    def install(marching_cubes):
        scenes: list = []

        class _FakeScene:
            def __init__(self) -> None:
                self.added: list = []
                self.exports: list = []
                scenes.append(self)

            def add_geometry(self, mesh, node_name=None):
                self.added.append((mesh, node_name))

            def export(self, output_path):
                # A real export writes the file; the module stats it next.
                self.exports.append(str(output_path))
                Path(output_path).write_bytes(b"glTF-fake-bytes")

        trimesh_mod = types.ModuleType("trimesh")
        trimesh_mod.Scene = _FakeScene
        trimesh_mod.Trimesh = _FakeTrimesh

        skimage_mod = types.ModuleType("skimage")
        measure_mod = types.ModuleType("skimage.measure")
        measure_mod.marching_cubes = marching_cubes
        skimage_mod.measure = measure_mod

        monkeypatch.setitem(sys.modules, "trimesh", trimesh_mod)
        monkeypatch.setitem(sys.modules, "skimage", skimage_mod)
        monkeypatch.setitem(sys.modules, "skimage.measure", measure_mod)
        return scenes

    return install


def _unreachable_marching_cubes(*args, **kwargs):
    """Surface extraction that must never be reached for an empty selection."""
    raise AssertionError("marching_cubes must not run when no state is selected")


def _synthetic_surface(*args, **kwargs):
    """One deterministic, tiny synthetic surface — never real geometry."""
    verts = np.array(
        [[1.0, 1.0, 1.0], [2.0, 1.0, 1.0], [1.0, 2.0, 1.0]], dtype=np.float64
    )
    faces = np.array([[0, 1, 2]], dtype=np.int64)
    normals = np.array(
        [[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]], dtype=np.float64
    )
    return verts, faces, normals, None


# ---------------------------------------------------------------------------
# 1. All-void lattice — direct refusal, before any export
# ---------------------------------------------------------------------------


def test_all_void_lattice_refuses_before_export(fake_glb_stack, tmp_path, capsys):
    scenes = fake_glb_stack(_unreachable_marching_cubes)
    out = tmp_path / "organism.glb"
    lattice = np.zeros((4, 4, 4), dtype=np.int8)

    with pytest.raises(ValueError) as excinfo:
        dandelion.lattice_to_glb(lattice, str(out))

    # Exact parity with lattice_to_stl: plain ValueError, exact message.
    assert type(excinfo.value) is ValueError
    assert str(excinfo.value) == EXPECTED_MESSAGE
    # Export never ran, no file was produced, no success line leaked.
    assert scenes and scenes[0].exports == []
    assert scenes[0].added == []
    assert not out.exists()
    assert "GLB exported:" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 2. No selected geometry — empty or nonmatching states_to_include
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "states_to_include",
    [
        pytest.param([], id="empty-selection"),
        pytest.param([3, 4], id="nonmatching-selection"),
    ],
)
def test_no_selected_geometry_refuses_before_export(
    fake_glb_stack, tmp_path, capsys, states_to_include
):
    scenes = fake_glb_stack(_unreachable_marching_cubes)
    out = tmp_path / "organism.glb"
    # Populated, but only with a state the selection does not ask for.
    lattice = np.zeros((4, 4, 4), dtype=np.int8)
    lattice[1:3, 1:3, 1:3] = 1

    with pytest.raises(ValueError) as excinfo:
        dandelion.lattice_to_glb(
            lattice, str(out), states_to_include=states_to_include
        )

    assert type(excinfo.value) is ValueError
    assert str(excinfo.value) == EXPECTED_MESSAGE
    assert scenes and scenes[0].exports == []
    assert not out.exists()
    assert "GLB exported:" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 3. Every surface extraction refused — the already-caught classes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raised", [RuntimeError, ValueError], ids=["runtime-error", "value-error"]
)
def test_all_surface_extractions_refused_still_refuses(
    fake_glb_stack, tmp_path, capsys, raised
):
    attempts: list = []

    def always_refuses(padded, level=None):
        attempts.append(level)
        raise raised("synthetic surface-extraction failure")

    scenes = fake_glb_stack(always_refuses)
    out = tmp_path / "organism.glb"
    # Two populated, selected states: both candidates get refused.
    lattice = np.zeros((4, 4, 4), dtype=np.int8)
    lattice[1, 1, 1] = 1
    lattice[2, 2, 2] = 2

    with pytest.raises(ValueError) as excinfo:
        dandelion.lattice_to_glb(lattice, str(out))

    assert type(excinfo.value) is ValueError
    assert str(excinfo.value) == EXPECTED_MESSAGE
    # The loop really did try both candidates and swallowed each refusal.
    assert len(attempts) == 2
    assert scenes and scenes[0].added == []
    assert scenes[0].exports == []
    assert not out.exists()
    assert "GLB exported:" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 4. Valid path behaviour lock — the guard must not disturb a real export
# ---------------------------------------------------------------------------


def test_valid_single_surface_exports_unchanged(fake_glb_stack, tmp_path, capsys):
    scenes = fake_glb_stack(_synthetic_surface)
    out = tmp_path / "organism.glb"
    lattice = np.zeros((4, 4, 4), dtype=np.int8)
    lattice[1:3, 1:3, 1:3] = 2  # COMPUTE only

    returned = dandelion.lattice_to_glb(lattice, str(out), states_to_include=[2])

    assert returned == str(out)
    scene = scenes[0]
    # Exactly one geometry, with the existing state-derived node name.
    assert len(scene.added) == 1
    mesh, node_name = scene.added[0]
    assert node_name == STATE_NAMES[2]
    # The existing colour path is untouched.
    r, g, b = STATE_PRINT_COLORS[2]
    assert np.array_equal(
        mesh.visual.face_colors, np.array([r, g, b, 255], dtype=np.uint8)
    )
    # The existing padding-offset undo is untouched.
    expected_verts, _faces, normals, _ = _synthetic_surface()
    assert np.array_equal(mesh.vertices, expected_verts - 1.0)
    assert np.array_equal(mesh.vertex_normals, normals)
    # Export ran exactly once, against the requested path, and the file exists.
    assert scene.exports == [str(out)]
    assert out.exists()
    # The existing success output is preserved.
    assert "GLB exported:" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 5. Optional-dependency precedence — ImportError still comes first
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blocked", ["skimage", "trimesh"])
def test_missing_optional_dependency_precedes_empty_mesh_refusal(
    monkeypatch, tmp_path, blocked
):
    # ``None`` in sys.modules makes the import raise ImportError, whether or not
    # the real package is installed on this seat.
    monkeypatch.setitem(sys.modules, blocked, None)
    if blocked == "skimage":
        monkeypatch.setitem(sys.modules, "skimage.measure", None)

    out = tmp_path / "organism.glb"
    # An all-void lattice: if the empty-mesh guard ran first this would be a
    # ValueError. The dependency ImportError must win.
    lattice = np.zeros((4, 4, 4), dtype=np.int8)

    with pytest.raises(ImportError) as excinfo:
        dandelion.lattice_to_glb(lattice, str(out))

    assert not isinstance(excinfo.value, ValueError)
    message = str(excinfo.value)
    assert "trimesh and scikit-image required" in message
    assert "pip install trimesh scikit-image" in message
    assert not out.exists()


# ---------------------------------------------------------------------------
# 6. The public ``glb`` CLI gains no catch and no exit-code translation
# ---------------------------------------------------------------------------


def test_glb_cli_does_not_translate_valueerror(monkeypatch, tmp_path):
    """A ``ValueError`` out of ``lattice_to_glb`` must reach the caller.

    If the CLI branch grew a ``try``/``except`` — or argparse were used to turn
    the refusal into ``SystemExit(2)`` — this raises ``SystemExit`` instead and
    the test fails. The precise subclass does not matter beyond proving that no
    new translation or broad catch was introduced.
    """
    snapshot = tmp_path / "snap.npz"
    np.savez(snapshot, lattice=np.zeros((2, 2, 2), dtype=np.int8))

    sentinel = ValueError(EXPECTED_MESSAGE)

    def _raise_sentinel(*args, **kwargs):
        raise sentinel

    monkeypatch.setattr(dandelion, "lattice_to_glb", _raise_sentinel)

    with pytest.raises(ValueError) as excinfo:
        dandelion.main(["glb", str(snapshot), "--output", str(tmp_path / "o.glb")])

    assert excinfo.value is sentinel
