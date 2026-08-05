"""Tests for the Cosmic Observatory CLI user-error contract (issue #67 tranche).

Scope: the CLI's exit/error surface only. Snapshot semantics, rendering
algorithms, file formats and successful output are unchanged and are not
re-tested here.

Exit taxonomy under test:
    0  success -- a subcommand dispatched and completed
    2  usage   -- argparse's conventional status: unknown/mistyped command,
                  unknown flag, missing argument, out-of-range option value
    1  runtime -- an expected, actionable user error found while running:
                  unusable snapshot path or data, unusable animation directory,
                  slice level outside the selected axis

What is faked, and why: only the boundaries. The loader and the four rendering
modules are substituted so nothing renders and no window opens. Argument
parsing, validation, dispatch, error translation and exit statuses -- the logic
under test -- are the genuine production code.

``matplotlib.pyplot`` is also substituted, but note it is normally already
imported (``vis/__init__.py`` pulls ``vis.timeseries_plot``, which selects the
Agg backend), so the CLI usually binds the real, headless pyplot. The double is
a belt-and-braces guard, not the reason no window appears -- and it is
deliberately inert so it cannot be mistaken for a dispatch target.
"""

from __future__ import annotations

import base64
import json
import os
import runpy
import subprocess
import sys
import types
from pathlib import Path

import pytest

# The CLI's package imports pull NumPy (loader) and matplotlib (sibling vis
# modules). Self-skip cleanly when either is absent rather than erroring at
# collection, matching tests/test_observatory.py.
np = pytest.importorskip("numpy")
pytest.importorskip("matplotlib")

from vis.observatory import cli as cli_mod
from vis.observatory import loader as loader_mod
from vis.observatory.loader import ObservatorySnapshot

REPO_ROOT = Path(__file__).resolve().parent.parent

# Captured before any fixture patches it, so a test can opt back in to the
# genuine loader and exercise the real decode path end to end.
_REAL_LOAD_SNAPSHOT = loader_mod.load_snapshot


# ---------------------------------------------------------------------------
# Boundary doubles
# ---------------------------------------------------------------------------


class _Fig:
    """Stands in for a matplotlib/plotly figure."""

    def __init__(self):
        self.shown = False

    def show(self):
        self.shown = True


class _Calls:
    """Records which renderer the CLI dispatched to, and with what."""

    def __init__(self):
        self.name = None
        self.kwargs = None
        self.args = None


def _snapshot(shape=(4, 5, 6)):
    """A real ObservatorySnapshot -- the domain object, not a fake."""
    lattice = np.zeros(shape, dtype=np.uint8)
    lattice[0, 0, 0] = 1
    lattice[1, 1, 1] = 2
    memory = np.zeros((8,) + shape, dtype=np.float32)
    memory[0, 0, 0, 0] = 0.5
    return ObservatorySnapshot(
        lattice=lattice,
        memory_grid=memory,
        generation=7,
        ca_step=11,
        best_fitness=0.25,
        source_path="/fake/snap.npz",
    )


def _write_frames(directory, count=2):
    """Write real .npz frames the genuine loader can read.

    The animate path deliberately runs the real `load_snapshot_series`, so its
    input must be real files -- patching the loader away would stop exercising
    the boundary whose contract is under test.
    """
    snap = _snapshot()
    for index in range(count):
        np.savez(
            directory / f"v070_{index:03d}.npz",
            lattice=snap.lattice,
            memory_grid=snap.memory_grid,
            generation=snap.generation + index,
            ca_step=snap.ca_step,
            best_fitness=snap.best_fitness,
        )
    return directory


@pytest.fixture
def cli(monkeypatch, tmp_path):
    """Install boundary doubles and return a small driver.

    Returns an object exposing:
        run(argv)      -> int | SystemExit code via pytest.raises at call site
        calls          -> which renderer ran
        snapshot_path  -> an existing .npz path that passes path validation
        set_loader(fn) -> replace the snapshot loader
    """
    calls = _Calls()

    def _record(name, returns):
        def _fn(*args, **kwargs):
            calls.name = name
            calls.args = args
            calls.kwargs = kwargs
            return returns
        return _fn

    fig = _Fig()

    slicer = types.ModuleType("vis.observatory.slicer")
    slicer.slice_composite = _record("slice_composite", (fig, None))
    slicer.slice_lattice = _record("slice_lattice", (fig, None))
    slicer.slice_channel = _record("slice_channel", (fig, None))
    slicer.tri_slice = _record("tri_slice", fig)

    scatter = types.ModuleType("vis.observatory.scatter3d")
    scatter.organism_body = _record("organism_body", fig)
    scatter.signal_field_3d = _record("signal_field_3d", fig)
    scatter.warmth_glow_3d = _record("warmth_glow_3d", fig)
    scatter.compute_elders_3d = _record("compute_elders_3d", fig)
    scatter.channel_overlay = _record("channel_overlay", fig)

    dashboard = types.ModuleType("vis.observatory.dashboard")
    dashboard.observatory_dashboard = _record("observatory_dashboard", fig)

    # Only the render/save phase is faked. `load_snapshot_series` is NOT
    # patched, so the animate path exercises the genuine input boundary.
    # `animate_from_directory` is deliberately NOT provided: the CLI must not
    # use it (it fuses the load and render phases). If a regression reached for
    # it again, the import would fail loudly instead of passing silently.
    animation = types.ModuleType("vis.observatory.animation")
    animation.animate_slices = _record("animate_slices", "out.gif")

    # Inert on purpose: recording here would overwrite `calls.name` and mask
    # which renderer the CLI actually dispatched to.
    pyplot = types.ModuleType("matplotlib.pyplot")
    pyplot.show = lambda *a, **k: None
    pyplot.close = lambda *a, **k: None

    for name, module in (
        ("vis.observatory.slicer", slicer),
        ("vis.observatory.scatter3d", scatter),
        ("vis.observatory.dashboard", dashboard),
        ("vis.observatory.animation", animation),
        ("matplotlib.pyplot", pyplot),
    ):
        monkeypatch.setitem(sys.modules, name, module)

    monkeypatch.setattr(loader_mod, "load_snapshot", lambda p: _snapshot())

    snap_path = tmp_path / "snap.npz"
    snap_path.write_bytes(b"not really an npz -- the loader is faked")
    # Distinct from the class attribute below: a class body resolves names in
    # its own namespace first, so `anim_dir = str(anim_dir)` would raise
    # NameError rather than reading the enclosing local.
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    _write_frames(frames_dir)          # real, loadable frames
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()                  # exists, but holds no matching frames

    class _Driver:
        calls = None
        snapshot_path = str(snap_path)
        anim_dir = str(frames_dir)
        empty_anim_dir = str(empty_dir)
        tmp = tmp_path
        fig = None

        @staticmethod
        def run(argv):
            return cli_mod.main(argv)

        @staticmethod
        def set_loader(fn):
            monkeypatch.setattr(loader_mod, "load_snapshot", fn)

        @staticmethod
        def use_real_loader():
            """Restore the genuine loader so the real decode path runs."""
            monkeypatch.setattr(loader_mod, "load_snapshot", _REAL_LOAD_SNAPSHOT)

        @staticmethod
        def patch_render(module_name, attr, fn):
            """Patch the installed double, reached via sys.modules.

            `import pkg.sub as x` resolves through the package attribute and
            only falls back to sys.modules, so patching via `import` can hit
            the real module instead of the double once anything else in the
            session has imported it.
            """
            monkeypatch.setattr(sys.modules[module_name], attr, fn)

    _Driver.calls = calls
    _Driver.fig = fig
    return _Driver


# ---------------------------------------------------------------------------
# Successful dispatch -- every subcommand returns 0
# ---------------------------------------------------------------------------


def test_info_dispatches_and_returns_zero(cli, capsys):
    assert cli.run(["info", cli.snapshot_path]) == 0
    out = capsys.readouterr().out
    assert "Generation: 7" in out
    assert "CA Step:    11" in out


@pytest.mark.parametrize(
    "argv_tail, expected_renderer",
    [
        (["body"], "organism_body"),
        (["slice"], "slice_lattice"),
        (["slice", "--channel", "3"], "slice_composite"),
        (["tri"], "tri_slice"),
        (["signal"], "signal_field_3d"),
        (["warmth"], "warmth_glow_3d"),
        (["elders"], "compute_elders_3d"),
        (["dashboard"], "observatory_dashboard"),
    ],
)
def test_each_subcommand_dispatches_and_returns_zero(cli, argv_tail, expected_renderer):
    argv = [argv_tail[0], cli.snapshot_path] + argv_tail[1:]
    assert cli.run(argv) == 0
    assert cli.calls.name == expected_renderer


@pytest.mark.parametrize(
    "mode, expected_renderer",
    [("3d", "channel_overlay"), ("slice", "slice_channel")],
)
def test_channel_subcommand_dispatches(cli, mode, expected_renderer):
    assert cli.run(["channel", cli.snapshot_path, "3", "--mode", mode]) == 0
    assert cli.calls.name == expected_renderer


def test_animate_dispatches_and_returns_zero(cli):
    """Real frames are discovered and loaded by the genuine loader; only the
    render/save phase is faked, so no GIF is produced."""
    assert cli.run(["animate", cli.anim_dir]) == 0
    assert cli.calls.name == "animate_slices"
    snapshots = cli.calls.args[0]
    assert len(snapshots) == 2
    assert all(isinstance(s, ObservatorySnapshot) for s in snapshots)
    assert cli.calls.kwargs == {
        "output_path": "observatory_timelapse.gif",
        "fps": 4,
        "overlay_channel": None,
        "axis": "z",
    }


def test_animate_passes_options_through_unchanged(cli):
    assert cli.run([
        "animate", cli.anim_dir,
        "--output", "custom.gif", "--fps", "7",
        "--channel", "2", "--axis", "x",
    ]) == 0
    assert cli.calls.kwargs == {
        "output_path": "custom.gif",
        "fps": 7,
        "overlay_channel": 2,
        "axis": "x",
    }


def test_animate_max_frames_limits_the_series(cli):
    """`--max-frames` is the series limit, applied during loading."""
    assert cli.run(["animate", cli.anim_dir, "--max-frames", "1"]) == 0
    assert len(cli.calls.args[0]) == 1


# ---------------------------------------------------------------------------
# Help and ordinary usage errors -- conventional statuses preserved
# ---------------------------------------------------------------------------


def test_help_exits_zero(cli):
    with pytest.raises(SystemExit) as exc:
        cli.run(["--help"])
    assert exc.value.code == 0


def test_no_arguments_is_usage_error(cli):
    with pytest.raises(SystemExit) as exc:
        cli.run([])
    assert exc.value.code == 2


def test_unknown_flag_is_usage_error(cli):
    with pytest.raises(SystemExit) as exc:
        cli.run(["info", cli.snapshot_path, "--nope"])
    assert exc.value.code == 2


def test_subcommand_help_exits_zero(cli):
    with pytest.raises(SystemExit) as exc:
        cli.run(["slice", "--help"])
    assert exc.value.code == 0


# ---------------------------------------------------------------------------
# "did you mean?" -- only when a close match exists
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "typo, expected",
    [("slize", "slice"), ("anmiate", "animate"), ("dashbord", "dashboard")],
)
def test_close_typo_suggests_command(cli, capsys, typo, expected):
    with pytest.raises(SystemExit) as exc:
        cli.run([typo, cli.snapshot_path])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "did you mean" in err.lower()
    assert repr(expected) in err or expected in err


def test_distant_typo_gets_no_suggestion(cli, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.run(["zzzzzzzzzz", cli.snapshot_path])
    assert exc.value.code == 2
    assert "did you mean" not in capsys.readouterr().err.lower()


# ---------------------------------------------------------------------------
# Snapshot path contract -- runtime status 1, no traceback
# ---------------------------------------------------------------------------


def _assert_user_error(capsys):
    err = capsys.readouterr().err
    assert "Traceback (most recent call last)" not in err
    assert len(err.strip().splitlines()) == 1
    return err


def test_missing_snapshot_is_user_error(cli, capsys):
    assert cli.run(["info", str(cli.tmp / "absent.npz")]) == 1
    assert "not found" in _assert_user_error(capsys)


def test_directory_where_snapshot_expected_is_user_error(cli, capsys):
    assert cli.run(["info", cli.anim_dir]) == 1
    _assert_user_error(capsys)


def test_unsupported_snapshot_suffix_is_user_error(cli, capsys):
    bad = cli.tmp / "snap.txt"
    bad.write_text("x")
    assert cli.run(["info", str(bad)]) == 1
    assert "unsupported snapshot format" in _assert_user_error(capsys)


@pytest.mark.parametrize(
    "boom",
    [
        KeyError("memory_grid"),
        ValueError("Genome has no epigenetic snapshot"),
        OSError("truncated archive"),
        # NumPy signals a damaged archive in several non-OSError ways.
        EOFError("No data left in file"),
        __import__("zipfile").BadZipFile("File is not a zip file"),
        __import__("zlib").error("invalid distance too far back"),
        __import__("pickle").UnpicklingError("Failed to interpret file as a pickle"),
    ],
)
def test_malformed_snapshot_data_is_user_error(cli, capsys, boom):
    def _raise(_path):
        raise boom

    cli.set_loader(_raise)
    assert cli.run(["info", cli.snapshot_path]) == 1
    assert "cannot read snapshot" in _assert_user_error(capsys)


def test_missing_animation_directory_is_user_error(cli, capsys):
    assert cli.run(["animate", str(cli.tmp / "no_such_dir")]) == 1
    assert "directory not found" in _assert_user_error(capsys)


def test_file_where_animation_directory_expected_is_user_error(cli, capsys):
    assert cli.run(["animate", cli.snapshot_path]) == 1
    assert "not a directory" in _assert_user_error(capsys)


def test_animation_directory_without_matching_frames_is_user_error(cli, capsys):
    """Discovery failure, raised by the REAL loader against a real directory."""
    assert cli.run(["animate", cli.empty_anim_dir]) == 1
    err = _assert_user_error(capsys)
    assert "cannot animate" in err
    assert "No files matching" in err


def test_unreadable_series_member_is_user_error(cli, capsys):
    """A frame that is not a readable archive, decoded by the REAL loader."""
    broken = cli.tmp / "broken"
    broken.mkdir()
    (broken / "v070_000.npz").write_bytes(b"this is not an npz archive")
    assert cli.run(["animate", str(broken)]) == 1
    err = _assert_user_error(capsys)
    assert "cannot animate" in err


def test_empty_series_member_is_user_error(cli, capsys):
    """A zero-byte frame -- NumPy raises EOFError, which is not an OSError."""
    broken = cli.tmp / "empty_member"
    broken.mkdir()
    (broken / "v070_000.npz").write_bytes(b"")
    assert cli.run(["animate", str(broken)]) == 1
    assert "cannot animate" in _assert_user_error(capsys)


# --- render phase: NOT part of the input-translation boundary ---------------
#
# Regression for the boundary defect: `animate_from_directory()` performs both
# discovery/loading and rendering/saving in one call, so wrapping it translated
# renderer defects into user errors and swallowed their tracebacks. The classes
# below are all members of `_unreadable_input_errors()`, which is precisely why
# a custom sentinel would not have caught this.


@pytest.mark.parametrize(
    "boom",
    [
        ValueError("renderer defect: inconsistent frame shape"),
        OSError("cannot write output gif"),
        KeyError("palette"),
    ],
)
def test_render_phase_exception_propagates(cli, boom):
    def _raise(*a, **k):
        raise boom

    cli.patch_render("vis.observatory.animation", "animate_slices", _raise)
    with pytest.raises(type(boom)) as excinfo:
        cli.run(["animate", cli.anim_dir])
    assert excinfo.value is boom


# ---------------------------------------------------------------------------
# Numeric option contract -- usage status 2
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["8", "9", "-1", "99"])
@pytest.mark.parametrize("command", ["slice", "tri"])
def test_channel_option_rejects_out_of_range(cli, command, value):
    with pytest.raises(SystemExit) as exc:
        cli.run([command, cli.snapshot_path, "--channel", value])
    assert exc.value.code == 2


def test_animate_channel_option_rejects_out_of_range(cli):
    with pytest.raises(SystemExit) as exc:
        cli.run(["animate", cli.anim_dir, "--channel", "8"])
    assert exc.value.code == 2


@pytest.mark.parametrize("value", ["8", "-1"])
def test_channel_positional_rejects_out_of_range(cli, value):
    with pytest.raises(SystemExit) as exc:
        cli.run(["channel", cli.snapshot_path, value])
    assert exc.value.code == 2


@pytest.mark.parametrize("channel", ["0", "7"])
def test_channel_boundaries_are_accepted(cli, channel):
    assert cli.run(["channel", cli.snapshot_path, channel]) == 0


@pytest.mark.parametrize("channel", ["0", "7"])
@pytest.mark.parametrize("command", ["slice", "tri"])
def test_channel_option_boundaries_are_accepted(cli, command, channel):
    assert cli.run([command, cli.snapshot_path, "--channel", channel]) == 0


@pytest.mark.parametrize("channel", ["0", "7"])
def test_animate_channel_option_boundaries_are_accepted(cli, channel):
    assert cli.run(["animate", cli.anim_dir, "--channel", channel]) == 0


def test_json_snapshot_suffix_is_accepted(cli):
    """Both documented suffixes pass path validation, not just .npz."""
    genome = cli.tmp / "organism.genome.json"
    genome.write_text("{}")
    assert cli.run(["info", str(genome)]) == 0


def test_help_with_trailing_typo_still_exits_zero(cli):
    """A help request wins over the did-you-mean path."""
    with pytest.raises(SystemExit) as exc:
        cli.run(["--help", "slize"])
    assert exc.value.code == 0


@pytest.mark.parametrize("value", ["nan", "NaN"])
def test_threshold_rejects_nan(cli, value):
    with pytest.raises(SystemExit) as exc:
        cli.run(["signal", cli.snapshot_path, "--threshold", value])
    assert exc.value.code == 2


@pytest.mark.parametrize("flag", ["--max-frames", "--fps"])
@pytest.mark.parametrize("value", ["0", "-1", "-99"])
def test_animate_positive_ints_reject_zero_and_negative(cli, flag, value):
    with pytest.raises(SystemExit) as exc:
        cli.run(["animate", cli.anim_dir, flag, value])
    assert exc.value.code == 2


@pytest.mark.parametrize("value", ["-0.1", "-1", "-99.5"])
def test_threshold_rejects_negative(cli, value):
    with pytest.raises(SystemExit) as exc:
        cli.run(["signal", cli.snapshot_path, "--threshold", value])
    assert exc.value.code == 2


def test_threshold_zero_is_accepted(cli):
    assert cli.run(["signal", cli.snapshot_path, "--threshold", "0"]) == 0
    assert cli.calls.kwargs["threshold"] == 0.0


# ---------------------------------------------------------------------------
# Axis-specific level bounds -- checked after the snapshot is loaded
# ---------------------------------------------------------------------------

# _snapshot() has shape (4, 5, 6): x extent 4, y extent 5, z extent 6.


@pytest.mark.parametrize("axis, last", [("x", 3), ("y", 4), ("z", 5)])
def test_level_lower_and_upper_bounds_accepted(cli, axis, last):
    assert cli.run(["slice", cli.snapshot_path, "--axis", axis, "--level", "0"]) == 0
    assert cli.run(
        ["slice", cli.snapshot_path, "--axis", axis, "--level", str(last)]
    ) == 0


@pytest.mark.parametrize("axis, beyond", [("x", 4), ("y", 5), ("z", 6)])
def test_level_beyond_axis_is_user_error(cli, capsys, axis, beyond):
    assert cli.run(
        ["slice", cli.snapshot_path, "--axis", axis, "--level", str(beyond)]
    ) == 1
    err = _assert_user_error(capsys)
    assert f"axis {axis!r}" in err


@pytest.mark.parametrize("axis, extent", [("x", 4), ("y", 5), ("z", 6)])
def test_negative_level_keeps_python_indexing(cli, axis, extent):
    """`--level -1` selected the last slice before this contract existed
    (numpy.take with mode='raise' indexes from the end); it still does."""
    assert cli.run(["slice", cli.snapshot_path, "--axis", axis, "--level", "-1"]) == 0
    assert cli.run(
        ["slice", cli.snapshot_path, "--axis", axis, "--level", str(-extent)]
    ) == 0


@pytest.mark.parametrize("axis, too_negative", [("x", -5), ("y", -6), ("z", -7)])
def test_level_below_negative_extent_is_user_error(cli, capsys, axis, too_negative):
    assert cli.run(
        ["slice", cli.snapshot_path, "--axis", axis, "--level", str(too_negative)]
    ) == 1
    _assert_user_error(capsys)


def test_channel_slice_mode_validates_level(cli, capsys):
    assert cli.run(
        ["channel", cli.snapshot_path, "2", "--mode", "slice", "--level", "99"]
    ) == 1
    _assert_user_error(capsys)


# ---------------------------------------------------------------------------
# Message hygiene and defect visibility
# ---------------------------------------------------------------------------


def test_error_stays_one_line_for_path_with_cr_lf(cli, capsys):
    hostile = str(cli.tmp / "we\rird\nname.npz")
    assert cli.run(["info", hostile]) == 1
    err = capsys.readouterr().err
    assert len(err.strip().splitlines()) == 1
    assert "Traceback (most recent call last)" not in err


# ---------------------------------------------------------------------------
# Malformed portable-genome JSON, through the REAL loader
#
# Reachability half of the contract in
# tests/test_portable_genome_epigenetic_snapshot.py. The fixture replaces
# `load_snapshot` with a double for speed; `use_real_loader()` puts the genuine
# function back, so a `.json` snapshot really is decoded by the real
# `load_genome()` -> `extract_epigenetic_snapshot()` path. These therefore prove
# the end-to-end lane rather than a patched-away boundary.
#
# Before the fix a non-object JSON root reached `genome.get(...)` and raised an
# ambient `AttributeError`, which is not in the CLI's translated set, so the
# command emitted a traceback instead of the promised one-line status 1.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "root",
    [
        pytest.param([], id="array-empty"),
        pytest.param([1, 2, 3], id="array"),
        pytest.param("genome", id="string"),
        pytest.param(5, id="number"),
        pytest.param(1.5, id="float"),
        pytest.param(True, id="bool"),
        pytest.param(None, id="null"),
    ],
)
def test_non_object_json_snapshot_is_a_one_line_user_error(cli, capsys, root):
    cli.use_real_loader()
    path = cli.tmp / "bad_root.json"
    path.write_text(json.dumps(root), encoding="utf-8")
    assert cli.run(["info", str(path)]) == 1
    err = _assert_user_error(capsys)
    # Assert the specific refusal, not just the CLI's prefix: a weaker check
    # would pass for any translated exception and would not notice the
    # structural refusal disappearing.
    assert "genome must be a JSON object" in err


def _epi(**overrides):
    shape = (2, 2, 2)
    epi = {
        "included": True,
        "lattice_shape": list(shape),
        "lattice_b64": base64.b64encode(
            np.zeros(shape, dtype=np.uint8).tobytes()
        ).decode("ascii"),
        "snapshot_generation": 9,
        "snapshot_ca_step": 21,
    }
    epi.update(overrides)
    return epi


@pytest.mark.parametrize(
    "document, expected",
    [
        pytest.param({"epigenetic_snapshot": []},
                     "epigenetic_snapshot must be a JSON object", id="epi-array"),
        pytest.param({"epigenetic_snapshot": "x"},
                     "epigenetic_snapshot must be a JSON object", id="epi-string"),
        pytest.param({"epigenetic_snapshot": _epi(lattice_shape=5)},
                     "lattice_shape must be a JSON array", id="shape-scalar"),
        pytest.param({"epigenetic_snapshot": _epi(lattice_shape=[2, "2", 2])},
                     "lattice_shape entries must be integers", id="shape-entry"),
        pytest.param({"epigenetic_snapshot": _epi(lattice_b64=5)},
                     "lattice_b64 must be a JSON string", id="b64-number"),
        pytest.param({"epigenetic_snapshot": _epi(snapshot_generation="x")},
                     "snapshot_generation must be an integer", id="counter"),
        pytest.param({"epigenetic_snapshot": _epi(memory_grid_b64="AAAA"),
                      "memory_layout": []},
                     "memory_layout must be a JSON object", id="layout-array"),
        pytest.param({"epigenetic_snapshot": _epi(memory_grid_b64="AAAA"),
                      "memory_layout": {"num_channels": "eight"}},
                     "num_channels must be an integer", id="channels"),
    ],
)
def test_malformed_extraction_shape_is_a_one_line_user_error(
    cli, capsys, document, expected
):
    """Each refusal reaches the CLI's status-1 lane with its own message."""
    cli.use_real_loader()
    path = cli.tmp / "bad_section.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert cli.run(["info", str(path)]) == 1
    assert expected in _assert_user_error(capsys)


def test_valid_genome_without_epigenetic_data_keeps_established_outcome(cli, capsys):
    """Unchanged behaviour: a well-formed genome that simply has no epigenetic
    snapshot is still the established `ValueError` -> status 1 lane."""
    cli.use_real_loader()
    path = cli.tmp / "no_epi.json"
    path.write_text(json.dumps({"format": {"format_id": "x"}}), encoding="utf-8")
    assert cli.run(["info", str(path)]) == 1
    assert "no epigenetic snapshot" in _assert_user_error(capsys)


def test_valid_genome_with_epigenetic_data_still_loads(cli, capsys):
    """The positive control: a well-formed genome decodes through the real
    extractor and `info` reports it."""
    cli.use_real_loader()
    shape = (2, 2, 2)
    document = {
        "epigenetic_snapshot": {
            "included": True,
            "lattice_shape": list(shape),
            "lattice_b64": base64.b64encode(
                np.zeros(shape, dtype=np.uint8).tobytes()
            ).decode("ascii"),
            "snapshot_generation": 9,
            "snapshot_ca_step": 21,
        }
    }
    path = cli.tmp / "good.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert cli.run(["info", str(path)]) == 0
    assert "Generation: 9" in capsys.readouterr().out


class _Sentinel(Exception):
    """A stand-in for a programming defect, not a user error."""


def test_unexpected_exception_from_renderer_propagates(cli):
    def _boom(*a, **k):
        raise _Sentinel("defect inside the renderer")

    cli.patch_render("vis.observatory.scatter3d", "organism_body", _boom)
    with pytest.raises(_Sentinel, match="defect inside the renderer"):
        cli.run(["body", cli.snapshot_path])


def test_unexpected_exception_from_loader_propagates(cli):
    def _boom(_path):
        raise _Sentinel("defect inside the loader")

    cli.set_loader(_boom)
    with pytest.raises(_Sentinel, match="defect inside the loader"):
        cli.run(["info", cli.snapshot_path])


@pytest.mark.parametrize(
    "boom",
    [
        AttributeError("'Widget' object has no attribute 'get'"),
        TypeError("unsupported operand type(s)"),
    ],
)
def test_ambient_defect_classes_still_propagate_from_the_loader(cli, boom):
    """The fix must NOT have widened the translated set. `AttributeError` and
    `TypeError` are the exact classes the malformed-genome shapes used to raise
    ambiently; they remain defect signals and must keep their traceback."""

    def _raise(_path):
        raise boom

    cli.set_loader(_raise)
    with pytest.raises(type(boom)) as excinfo:
        cli.run(["info", cli.snapshot_path])
    assert excinfo.value is boom


@pytest.mark.parametrize(
    "defect", [AttributeError, TypeError, IndexError, RecursionError, NameError]
)
def test_translated_error_set_never_covers_a_defect_class(defect):
    """Guards the boundary by SUBCLASS, not identity: adding `Exception`,
    `LookupError` or `ArithmeticError` would slip past a `not in` check."""
    translated = cli_mod._unreadable_input_errors()
    assert not any(issubclass(defect, caught) for caught in translated)


# ---------------------------------------------------------------------------
# Module entry point propagates main()'s result
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("result", [0, 1])
def test_module_entry_point_propagates_status(monkeypatch, result):
    """The wiring: whatever main() returns becomes the exit status."""
    monkeypatch.setattr(cli_mod, "main", lambda: result)
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("vis.observatory", run_name="__main__")
    assert exc.value.code == result


def _run_module(*args):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["MPLBACKEND"] = "Agg"
    return subprocess.run(
        [sys.executable, "-m", "vis.observatory", *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_module_entry_point_end_to_end_help_exits_zero():
    """End-to-end through the real main(), not a double."""
    assert _run_module("--help").returncode == 0


def test_module_entry_point_end_to_end_user_error_exits_one(tmp_path):
    proc = _run_module("info", str(tmp_path / "absent.npz"))
    assert proc.returncode == 1
    assert "Traceback (most recent call last)" not in proc.stderr
    assert len(proc.stderr.strip().splitlines()) == 1


def test_module_entry_point_end_to_end_usage_error_exits_two():
    assert _run_module("zzzzzzzzzz").returncode == 2


# ---------------------------------------------------------------------------
# `doctor` preflight and `--json` reporting
#
# Reachability and process contract only. The check semantics themselves live
# in tests/test_observatory_diagnostics.py; what matters here is that the CLI
# reaches them, maps them onto the right exit status, and keeps stdout clean.
#
# `doctor` is the one command that can return 1 after a *successful* load:
#   0 = loaded and every check passed
#   1 = expected load failure, OR diagnostics completed with >=1 failure
#   2 = argparse usage error
# ---------------------------------------------------------------------------


def _write_snapshot(path, lattice=None, memory=None, generation=7, ca_step=11,
                    best_fitness=0.25, channels=8):
    """A real .npz the genuine loader reads -- no doubles on this path."""
    if lattice is None:
        lattice = np.zeros((3, 4, 5), dtype=np.uint8)
        lattice[0, 0, 0] = 1
        lattice[1, 1, 1] = 2
    if memory is None:
        memory = np.zeros((channels,) + lattice.shape, dtype=np.float32)
    np.savez(
        path,
        lattice=lattice,
        memory_grid=memory,
        generation=generation,
        ca_step=ca_step,
        best_fitness=best_fitness,
    )
    return str(path)


def _canonical(document):
    """Serialize a parsed document under the CLI's own strict settings."""
    return json.dumps(document, sort_keys=True, allow_nan=False,
                      separators=(",", ":"))


def _only_json(capsys):
    """Assert stdout is exactly one JSON document and return it."""
    captured = capsys.readouterr()
    text = captured.out
    assert text.endswith("\n")
    assert text.strip().count("\n") == 0, "JSON mode must emit a single line"
    document = json.loads(text)          # raises if prose leaked in
    assert isinstance(document, dict)
    return document, captured


# --- dispatch and exit status ----------------------------------------------


def test_doctor_returns_zero_for_a_healthy_snapshot(cli, capsys):
    assert cli.run(["doctor", cli.snapshot_path]) == 0
    out = capsys.readouterr().out
    assert "[PASS]" in out
    assert "[FAIL]" not in out
    assert out.strip().splitlines()[-1].startswith("OK:")


def test_doctor_returns_one_when_a_check_fails(cli, capsys):
    """A snapshot that loads cleanly but violates the contract: status 1
    without an error message, because nothing failed to *load*."""
    bad = _snapshot()
    bad.lattice[0, 0, 0] = 99            # outside the state vocabulary
    cli.set_loader(lambda _p: bad)
    assert cli.run(["doctor", cli.snapshot_path]) == 1
    captured = capsys.readouterr()
    assert "[FAIL]" in captured.out
    assert "lattice_states_known" in captured.out
    assert captured.out.strip().splitlines()[-1].startswith("FAILED:")
    assert "Traceback (most recent call last)" not in captured.err


def test_doctor_reports_every_failure_not_just_the_first(cli, capsys):
    bad = _snapshot()
    bad.lattice[0, 0, 0] = 99
    object.__setattr__(bad, "generation", -1)
    object.__setattr__(bad, "best_fitness", float("nan"))
    cli.set_loader(lambda _p: bad)
    assert cli.run(["doctor", cli.snapshot_path]) == 1
    out = capsys.readouterr().out
    assert out.count("[FAIL]") == 3
    assert "FAILED: 3 of" in out


def test_doctor_missing_path_is_the_ordinary_user_error_lane(cli, capsys):
    """Path validation, which runs before any load: one stderr line, no
    traceback, no diagnostic report."""
    assert cli.run(["doctor", str(cli.tmp / "absent.npz")]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert len(captured.err.strip().splitlines()) == 1
    assert "Traceback (most recent call last)" not in captured.err


def _unreadable_npz(cli):
    """A path that passes validation but fails inside the genuine loader, so
    the failure really is a *load* failure and not a path check."""
    cli.use_real_loader()
    path = cli.tmp / "corrupt.npz"
    path.write_bytes(b"this is not a zip archive")
    return str(path)


@pytest.mark.parametrize("argv_tail", [[], ["--json"]])
def test_doctor_load_failure_emits_no_report(cli, capsys, argv_tail):
    """A genuine load failure must not produce a half-built document, in
    either output mode. `_emit_json` is never reached, so stdout stays empty
    and the single-line stderr contract holds."""
    assert cli.run(["doctor", _unreadable_npz(cli), *argv_tail]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert len(captured.err.strip().splitlines()) == 1
    assert "Traceback (most recent call last)" not in captured.err


# --- argparse surface -------------------------------------------------------


def test_doctor_help_exits_zero(cli):
    with pytest.raises(SystemExit) as exc:
        cli.run(["doctor", "--help"])
    assert exc.value.code == 0


def test_doctor_is_listed_in_top_level_help(cli, capsys):
    with pytest.raises(SystemExit):
        cli.run(["--help"])
    assert "doctor" in capsys.readouterr().out


def test_doctor_without_a_snapshot_is_a_usage_error(cli):
    with pytest.raises(SystemExit) as exc:
        cli.run(["doctor"])
    assert exc.value.code == 2


@pytest.mark.parametrize("command", ["info", "doctor"])
def test_unknown_flag_on_json_commands_is_a_usage_error(cli, command):
    with pytest.raises(SystemExit) as exc:
        cli.run([command, cli.snapshot_path, "--jsonn"])
    assert exc.value.code == 2


@pytest.mark.parametrize("command", ["info", "doctor"])
def test_json_flag_takes_no_value(cli, command):
    with pytest.raises(SystemExit) as exc:
        cli.run([command, cli.snapshot_path, "--json", "pretty"])
    assert exc.value.code == 2


# --- JSON output ------------------------------------------------------------


def test_doctor_json_is_a_single_valid_document(cli, capsys):
    assert cli.run(["doctor", cli.snapshot_path, "--json"]) == 0
    document, captured = _only_json(capsys)
    assert captured.err == ""
    assert document["kind"] == "doctor"
    assert document["ok"] is True
    assert document["summary"]["failed"] == 0
    assert [c["name"] for c in document["checks"]] == [
        c.name for c in _diagnostics().diagnose(_snapshot())
    ]


def test_doctor_json_failure_still_returns_one_with_a_full_report(cli, capsys):
    bad = _snapshot()
    bad.lattice[0, 0, 0] = 99
    cli.set_loader(lambda _p: bad)
    assert cli.run(["doctor", cli.snapshot_path, "--json"]) == 1
    document, captured = _only_json(capsys)
    assert captured.err == ""
    assert document["ok"] is False
    assert document["summary"]["failed"] == 1
    failed = [c["name"] for c in document["checks"] if not c["ok"]]
    assert failed == ["lattice_states_known"]


def test_info_json_is_a_single_valid_document(cli, capsys):
    assert cli.run(["info", cli.snapshot_path, "--json"]) == 0
    document, captured = _only_json(capsys)
    assert captured.err == ""
    assert document["kind"] == "info"
    assert document["generation"] == 7
    assert document["ca_step"] == 11


@pytest.mark.parametrize("command", ["info", "doctor"])
def test_json_mode_emits_no_human_prose(cli, capsys, command):
    """The healthy snapshot returns 0 for both commands; the point of the test
    is that stdout carries the document and nothing else."""
    assert cli.run([command, cli.snapshot_path, "--json"]) == 0
    out = capsys.readouterr().out
    for prose in ("Source:", "Generation:", "CA Step:", "Non-void:",
                  "[PASS]", "[FAIL]", "OK:", "FAILED:"):
        assert prose not in out


@pytest.mark.parametrize("command", ["info", "doctor"])
def test_json_output_is_byte_identical_for_equivalent_snapshots(tmp_path, command):
    """Determinism, proven end to end over two genuinely distinct files with
    identical content: the documents must differ only in the source path.

    Driven through real files rather than the fixture's loader double, which
    reports one fixed source no matter which path it is handed and so could not
    tell a deterministic serializer from a constant one.
    """
    first_path = _write_snapshot(tmp_path / "one.npz")
    second_path = _write_snapshot(tmp_path / "two.npz")

    first = json.loads(_run_module(command, first_path, "--json").stdout)
    second = json.loads(_run_module(command, second_path, "--json").stdout)

    assert first["source"] != second["source"]
    first.pop("source")
    second.pop("source")
    assert _canonical(first) == _canonical(second)


@pytest.mark.parametrize("command", ["info", "doctor"])
def test_json_output_is_stable_across_repeated_runs(tmp_path, command):
    path = _write_snapshot(tmp_path / "stable.npz")
    first = _run_module(command, path, "--json").stdout
    second = _run_module(command, path, "--json").stdout
    assert first == second
    assert first.strip().count("\n") == 0


@pytest.mark.parametrize("command", ["info", "doctor"])
def test_json_never_emits_non_standard_tokens(cli, capsys, command):
    """`allow_nan=False`: non-finite values become null, never bare NaN /
    Infinity, which no strict JSON parser accepts."""
    bad = _snapshot()
    bad.memory_grid[0] = np.nan
    bad.memory_grid[1] = np.inf
    object.__setattr__(bad, "best_fitness", float("-inf"))
    cli.set_loader(lambda _p: bad)
    cli.run([command, cli.snapshot_path, "--json"])
    out = capsys.readouterr().out
    assert "NaN" not in out and "Infinity" not in out
    json.loads(out)


def _diagnostics():
    from vis.observatory import diagnostics

    return diagnostics


def test_info_json_agrees_with_the_human_rendering(cli, capsys):
    """The shared-statistics refactor, asserted: one source of truth, so the
    two renderings cannot drift."""
    assert cli.run(["info", cli.snapshot_path]) == 0
    human = capsys.readouterr().out
    assert cli.run(["info", cli.snapshot_path, "--json"]) == 0
    document = json.loads(capsys.readouterr().out)

    assert f"Generation: {document['generation']}" in human
    assert f"CA Step:    {document['ca_step']}" in human
    for entry in document["state_counts"]:
        if entry["count"]:
            assert entry["name"] in human
            assert str(entry["count"]) in human


# --- end to end through the genuine loader ----------------------------------


def test_doctor_passes_a_real_npz_snapshot(tmp_path):
    proc = _run_module("doctor", _write_snapshot(tmp_path / "real.npz"))
    assert proc.returncode == 0, proc.stderr
    assert "[FAIL]" not in proc.stdout


@pytest.mark.parametrize("channels", [3, 5])
def test_doctor_passes_a_legacy_channel_snapshot(tmp_path, channels):
    """The landed loader normalization seam, reached from `doctor`: a legacy
    3- or 5-channel grid is migrated to 8 before the contract is checked, so
    the channel-count check must pass rather than flag a historical file."""
    path = _write_snapshot(tmp_path / f"legacy{channels}.npz", channels=channels)
    proc = _run_module("doctor", path)
    assert proc.returncode == 0, proc.stderr


def test_doctor_fails_a_real_snapshot_that_breaks_the_contract(tmp_path):
    lattice = np.zeros((3, 4, 5), dtype=np.uint8)
    lattice[0, 0, 0] = 200               # loads fine; not in the vocabulary
    path = _write_snapshot(tmp_path / "bad.npz", lattice=lattice)
    proc = _run_module("doctor", path)
    assert proc.returncode == 1
    assert "[FAIL]" in proc.stdout
    assert "Traceback (most recent call last)" not in proc.stderr


def test_doctor_json_end_to_end_parses(tmp_path):
    proc = _run_module("doctor", _write_snapshot(tmp_path / "real.npz"), "--json")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["ok"] is True


def test_doctor_passes_a_portable_genome_without_a_memory_grid(cli, capsys):
    """The other public route, through the genuine loader. A genome carrying no
    memory grid is filled with the established 8-channel zero grid, so it
    satisfies the contract rather than being reported as broken."""
    cli.use_real_loader()
    path = cli.tmp / "genome.json"
    path.write_text(json.dumps({"epigenetic_snapshot": _epi()}), encoding="utf-8")
    assert cli.run(["doctor", str(path), "--json"]) == 0
    document, _ = _only_json(capsys)
    assert document["ok"] is True
    route = next(c for c in document["checks"] if c["name"] == "source_loadable")
    assert "portable-genome JSON" in route["detail"]


def test_doctor_names_the_npz_route(cli, capsys):
    assert cli.run(["doctor", cli.snapshot_path, "--json"]) == 0
    document, _ = _only_json(capsys)
    route = next(c for c in document["checks"] if c["name"] == "source_loadable")
    assert route["ok"] is True
    assert "npz" in route["detail"]


# --- regressions: the report must survive what the checks are meant to flag --


@pytest.mark.parametrize("command", ["info", "doctor"])
def test_non_finite_memory_does_not_crash_either_output_mode(tmp_path, command):
    """Regression. `snapshot_statistics` maps non-finite values to None so the
    JSON stays strict; the human table then received None for a channel's
    min/max/mean and died on `:+.4f`. A snapshot carrying NaN is exactly what
    `doctor` exists to report, so neither mode may traceback on it."""
    memory = np.zeros((8, 3, 4, 5), dtype=np.float32)
    memory[0] = np.nan
    memory[1] = np.inf
    memory[2] = -np.inf
    path = _write_snapshot(tmp_path / "nonfinite.npz", memory=memory)

    for argv_tail in ([], ["--json"]):
        proc = _run_module(command, path, *argv_tail)
        assert "Traceback (most recent call last)" not in proc.stderr, proc.stderr
        # info always 0; doctor reports the finiteness failure as 1.
        assert proc.returncode == (0 if command == "info" else 1)
        if argv_tail:
            assert json.loads(proc.stdout)          # strict parse, no NaN token
            assert "NaN" not in proc.stdout and "Infinity" not in proc.stdout
        else:
            assert "non-finite" in proc.stdout


def test_memory_spatial_mismatch_still_produces_a_json_document(tmp_path):
    """Regression. Masking a (4,4,4) channel with an (8,8,8) lattice mask
    raises IndexError, so `doctor --json` died with a traceback and emitted no
    document at all -- on precisely the snapshot the shape check reports.
    Human `doctor` handled it correctly, so the two modes disagreed."""
    lattice = np.zeros((8, 8, 8), dtype=np.uint8)
    lattice[0, 0, 0] = 1
    memory = np.zeros((8, 4, 4, 4), dtype=np.float32)
    path = _write_snapshot(tmp_path / "mismatch.npz", lattice=lattice, memory=memory)

    proc = _run_module("doctor", path, "--json")
    assert "Traceback (most recent call last)" not in proc.stderr, proc.stderr
    assert proc.returncode == 1
    document = json.loads(proc.stdout)
    assert document["ok"] is False
    failed = [c["name"] for c in document["checks"] if not c["ok"]]
    assert "memory_shape_matches_lattice" in failed
    assert all(c["populated"] is False for c in document["snapshot"]["channels"])

    human = _run_module("doctor", path)
    assert human.returncode == 1
    assert "Traceback (most recent call last)" not in human.stderr


@pytest.mark.parametrize("command", ["info", "doctor"])
@pytest.mark.parametrize(
    "shape", [(0, 3, 4), (3, 0, 4), (3, 4, 0), (0, 0, 0)]
)
def test_zero_size_lattice_does_not_crash_either_command(tmp_path, command, shape):
    """Settles a limitation the PR body claimed was outstanding.

    On the base, human `info` raised ZeroDivisionError computing a percentage
    over zero cells. The shared-statistics refactor made the percentage `None`
    and `format_percent` renders that as `n/a`, so `info` now exits 0. `doctor`
    reports the zero dimension as a failed check and exits 1. Neither
    tracebacks -- which is what the body should have said.
    """
    lattice = np.zeros(shape, dtype=np.uint8)
    memory = np.zeros((8,) + shape, dtype=np.float32)
    path = _write_snapshot(tmp_path / "empty.npz", lattice=lattice, memory=memory)

    proc = _run_module(command, path)
    assert "Traceback (most recent call last)" not in proc.stderr, proc.stderr
    assert proc.returncode == (0 if command == "info" else 1)
    if command == "info":
        assert "n/a" in proc.stdout

    js = _run_module(command, path, "--json")
    assert "Traceback (most recent call last)" not in js.stderr, js.stderr
    assert json.loads(js.stdout)["total_cells" if command == "info"
                                 else "snapshot"] is not None


# --- oversized counters through the genuine NPZ route ----------------------
#
# Reachability note. An ordinary portable-genome JSON file is NOT the route:
# CPython applies the same integer-string ceiling when PARSING, so `json.load`
# rejects an over-limit decimal literal before the loader ever sees it. The
# NPZ route does reach it -- `load_npz` uses `allow_pickle=True` and then
# `int(...)`, so a pickled Python int of any magnitude survives as a real int.
# A snapshot built directly in a library call is the other valid witness.


def _write_oversized_snapshot(path, field="generation"):
    """A real .npz whose counter is a huge pickled Python int."""
    lattice = np.zeros((2, 3, 4), dtype=np.uint8)
    lattice[0, 0, 0] = 1
    payload = {
        "lattice": lattice,
        "memory_grid": np.zeros((8, 2, 3, 4), dtype=np.float32),
        "generation": 7,
        "ca_step": 11,
        "best_fitness": 0.25,
    }
    payload[field] = np.array(10 ** 100000, dtype=object)
    np.savez(path, **payload)
    return str(path)


@pytest.mark.parametrize("field", ["generation", "ca_step"])
@pytest.mark.parametrize("argv_tail", [[], ["--json"]])
def test_oversized_counter_does_not_traceback_in_info(tmp_path, field, argv_tail):
    """Human `info` formats the counters directly with `:,`, which raises on a
    value past the digit ceiling; `info --json` serialized it verbatim and
    raised inside the encoder. Neither may traceback."""
    path = _write_oversized_snapshot(tmp_path / f"big_{field}.npz", field)
    proc = _run_module("info", path, *argv_tail)
    assert "Traceback (most recent call last)" not in proc.stderr, proc.stderr
    assert proc.returncode == 0
    if argv_tail:
        assert json.loads(proc.stdout)[field] is None


@pytest.mark.parametrize("field", ["generation", "ca_step"])
@pytest.mark.parametrize("argv_tail", [[], ["--json"]])
def test_oversized_counter_is_reported_by_doctor(tmp_path, field, argv_tail):
    """`doctor` must report it as a failed check, not die describing it."""
    path = _write_oversized_snapshot(tmp_path / f"big_{field}.npz", field)
    proc = _run_module("doctor", path, *argv_tail)
    assert "Traceback (most recent call last)" not in proc.stderr, proc.stderr
    assert proc.returncode == 1
    if argv_tail:
        document = json.loads(proc.stdout)
        assert document["ok"] is False
        failed = [c["name"] for c in document["checks"] if not c["ok"]]
        assert f"{field}_non_negative_int" in failed
        assert document["snapshot"][field] is None
    else:
        assert f"{field}_non_negative_int" in proc.stdout
        assert "[FAIL]" in proc.stdout


def test_ordinary_counters_still_render_normally(tmp_path):
    """The guard must not disturb the established `info` layout."""
    path = _write_snapshot(tmp_path / "normal.npz", generation=1234567, ca_step=11)
    proc = _run_module("info", path)
    assert proc.returncode == 0, proc.stderr
    assert "Generation: 1,234,567" in proc.stdout
    assert "CA Step:    11" in proc.stdout


# --- untrusted pathnames may not forge output rows -------------------------


FORGED_SOURCE = (
    "/tmp/snap\n\n  [PASS] lattice_states_known  all state ids within [0, 1, 2, "
    "3, 4]\n\nOK: all 13 checks passed.\n\nquarantined.npz"
)


def test_a_source_path_cannot_forge_doctor_report_lines(cli, capsys):
    """A pathname is untrusted data. Rendered verbatim it could inject a
    convincing extra PASS row and a second summary line ahead of the real
    report, so a reader -- or a grep -- would see a verdict the run never
    reached. The exit status was never at risk; the report's integrity was.
    """
    bad = _snapshot()
    bad.lattice[0, 0, 0] = 99                      # genuinely fails a check
    object.__setattr__(bad, "source_path", FORGED_SOURCE)
    cli.set_loader(lambda _p: bad)

    assert cli.run(["doctor", cli.snapshot_path]) == 1
    lines = capsys.readouterr().out.splitlines()

    # The forged text is not erased -- it is still visible, inert, on the
    # Snapshot line. What it may not do is become its own row: structure is
    # what a reader and a grep go by, so structure is what is asserted.
    body = [ln for ln in lines if ln.startswith("  [")]
    assert len(body) == 13
    assert sum(1 for ln in body if ln.startswith("  [PASS]")) == 12
    assert sum(1 for ln in body if ln.startswith("  [FAIL]")) == 1
    assert [ln for ln in lines if ln.startswith(("OK:", "FAILED:"))] == [
        "FAILED: 1 of 13 checks did not pass."
    ]


def test_a_source_path_cannot_forge_info_rows(cli, capsys):
    bad = _snapshot()
    object.__setattr__(bad, "source_path", "/tmp/a\n  Void        :       99 (99.9%)")
    cli.set_loader(lambda _p: bad)
    assert cli.run(["info", cli.snapshot_path]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len([ln for ln in lines if ln.startswith("  Void")]) == 1
    assert len([ln for ln in lines if ln.startswith("Source:")]) == 1


def test_json_mode_round_trips_a_hostile_path_verbatim(cli, capsys):
    """JSON needs no collapsing -- escaping already makes it inert -- and the
    value must survive unchanged so a consumer sees the real path."""
    bad = _snapshot()
    object.__setattr__(bad, "source_path", FORGED_SOURCE)
    cli.set_loader(lambda _p: bad)
    assert cli.run(["doctor", cli.snapshot_path, "--json"]) == 0
    document, _ = _only_json(capsys)
    assert document["source"] == FORGED_SOURCE


def test_doctor_end_to_end_malformed_snapshot_is_status_one(tmp_path):
    path = tmp_path / "junk.npz"
    path.write_bytes(b"not an npz at all")
    proc = _run_module("doctor", str(path))
    assert proc.returncode == 1
    assert "Traceback (most recent call last)" not in proc.stderr
    assert len(proc.stderr.strip().splitlines()) == 1


def test_doctor_does_not_write_report_files(tmp_path):
    """Read-only: `doctor` reports, it does not persist.

    Both directories are watched. `_run_module` runs with `cwd=REPO_ROOT`, so a
    relative-path write would land there, not in `tmp_path` -- watching only
    the temporary directory would be looking in the one place it could not go.
    """
    path = _write_snapshot(tmp_path / "real.npz")
    tmp_before = sorted(p.name for p in tmp_path.iterdir())
    repo_before = sorted(p.name for p in REPO_ROOT.iterdir())

    assert _run_module("doctor", path, "--json").returncode == 0

    assert sorted(p.name for p in tmp_path.iterdir()) == tmp_before
    assert sorted(p.name for p in REPO_ROOT.iterdir()) == repo_before


# --- no renderer on the doctor path -----------------------------------------


RENDERER_MODULES = (
    "vis.observatory.slicer",
    "vis.observatory.scatter3d",
    "vis.observatory.dashboard",
    "vis.observatory.animation",
)


@pytest.mark.parametrize("argv_tail", [[], ["--json"]])
def test_doctor_imports_no_renderer_module(cli, monkeypatch, argv_tail):
    """`doctor` preflights without opening a renderer.

    The fixture's doubles are evicted and a meta-path finder records any
    attempt to import them, so a renderer import is caught whether it would
    have resolved to a double or to the real module.
    """
    attempted = []

    class _Recorder:
        def find_module(self, fullname, path=None):     # legacy protocol
            return self.find_spec(fullname, path)

        def find_spec(self, fullname, path=None, target=None):
            if fullname in RENDERER_MODULES:
                attempted.append(fullname)
            return None                                  # never actually import

    for name in RENDERER_MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(sys, "meta_path", [_Recorder(), *sys.meta_path])

    # `attempted` is the live assertion. A `cli.calls.name` check would be dead
    # here: the doubles that record into it were just evicted, so a real
    # renderer import would resolve to the genuine module and never touch it.
    assert cli.run(["doctor", cli.snapshot_path, *argv_tail]) == 0
    assert attempted == []


def test_info_json_imports_no_renderer_module(cli, monkeypatch):
    attempted = []

    class _Recorder:
        def find_module(self, fullname, path=None):
            return self.find_spec(fullname, path)

        def find_spec(self, fullname, path=None, target=None):
            if fullname in RENDERER_MODULES:
                attempted.append(fullname)
            return None

    for name in RENDERER_MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(sys, "meta_path", [_Recorder(), *sys.meta_path])

    assert cli.run(["info", cli.snapshot_path, "--json"]) == 0
    assert attempted == []


@pytest.mark.parametrize("argv_tail", [[], ["--json"]])
def test_doctor_invokes_no_renderer(cli, argv_tail):
    """The invocation half of "no renderer", with the recording doubles left
    installed so `calls` is genuinely live: every renderer entry point the CLI
    can reach is a double that records into `cli.calls`, and none of them ran.
    """
    assert cli.run(["doctor", cli.snapshot_path, *argv_tail]) == 0
    assert cli.calls.name is None, f"doctor invoked renderer {cli.calls.name}"
    assert cli.fig.shown is False


# --- defects still propagate ------------------------------------------------


@pytest.mark.parametrize("argv_tail", [[], ["--json"]])
def test_unexpected_exception_from_diagnostics_propagates(cli, monkeypatch, argv_tail):
    """A defect inside the reporting seam is not a user error."""

    def _boom(_snapshot):
        raise _Sentinel("defect inside diagnostics")

    monkeypatch.setattr(_diagnostics(), "diagnose", _boom)
    with pytest.raises(_Sentinel, match="defect inside diagnostics"):
        cli.run(["doctor", cli.snapshot_path, *argv_tail])


def test_unexpected_exception_from_the_loader_propagates_through_doctor(cli):
    def _boom(_path):
        raise _Sentinel("defect inside the loader")

    cli.set_loader(_boom)
    with pytest.raises(_Sentinel, match="defect inside the loader"):
        cli.run(["doctor", cli.snapshot_path])
