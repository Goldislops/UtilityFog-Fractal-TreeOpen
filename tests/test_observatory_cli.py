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
