"""Cosmic Observatory: CLI entry point.

Phase 8 -- The Cosmic Observatory

Usage:
    python -m vis.observatory body <snapshot>
    python -m vis.observatory slice <snapshot> [--axis z] [--level 32]
    python -m vis.observatory signal <snapshot>
    python -m vis.observatory warmth <snapshot>
    python -m vis.observatory elders <snapshot>
    python -m vis.observatory channel <snapshot> <channel_index>
    python -m vis.observatory dashboard <snapshot>
    python -m vis.observatory animate <data_dir> [--max-frames 50]
    python -m vis.observatory info <snapshot>
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Error contract
#
# Exit taxonomy (the smallest set the evidence supports):
#   0  success -- a subcommand dispatched and completed
#   2  usage   -- argparse's own conventional status: unknown/mistyped command,
#                 unknown flag, missing argument, out-of-range option value
#   1  runtime -- an expected, actionable user error discovered while running:
#                 unusable snapshot path or data, unusable animation directory,
#                 slice level outside the selected axis
#
# `--help` keeps argparse's conventional exit status 0.
#
# Expected failures print ONE physical stderr line and no traceback. Unexpected
# failures are deliberately NOT caught: only the narrow operations known to fail
# on bad user input are wrapped, so a defect inside a renderer still propagates
# with its traceback intact for developers.
# ---------------------------------------------------------------------------

SUPPORTED_SNAPSHOT_SUFFIXES = (".npz", ".json")
NUM_MEMORY_CHANNELS = 8
_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


class _UserError(Exception):
    """An expected, actionable user-facing failure (exit status 1)."""


def _one_line(text: object) -> str:
    """Collapse a message to a single physical line.

    A path supplied on the command line may contain CR/LF (or other line
    boundaries Python recognises), which would otherwise split one error across
    several stderr lines and break line-oriented consumers.
    """
    return " ".join(str(text).splitlines()).strip()


def _channel_index(raw: str) -> int:
    """argparse type: a memory channel index in 0-7."""
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not an integer") from None
    if not 0 <= value < NUM_MEMORY_CHANNELS:
        raise argparse.ArgumentTypeError(
            f"channel must be 0-{NUM_MEMORY_CHANNELS - 1}, got {value}"
        )
    return value


def _positive_int(raw: str) -> int:
    """argparse type: an integer strictly greater than zero."""
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not an integer") from None
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be greater than 0, got {value}")
    return value


def _non_negative_float(raw: str) -> float:
    """argparse type: a float >= 0 (zero is preserved as meaningful).

    Written as ``not (value >= 0)`` rather than ``value < 0`` so NaN -- which
    compares False against everything -- is rejected instead of slipping
    through to produce a silently empty render.
    """
    try:
        value = float(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not a number") from None
    if not value >= 0:
        raise argparse.ArgumentTypeError(f"must not be negative, got {value}")
    return value


def _first_command_token(argv):
    """Return the first non-option token, i.e. the intended subcommand."""
    for token in argv:
        if token == "--":
            return None
        if token.startswith("-"):
            continue
        return token
    return None


def _suggest_command(parser, argv, commands):
    """Emit a 'did you mean?' usage error when a typo has a close match.

    Only fires when `difflib` finds a near neighbour; a distant token falls
    through to argparse's ordinary invalid-choice error so behaviour there is
    unchanged. A help request always wins, so `--help` keeps exiting 0 whatever
    else appears on the line.
    """
    if "-h" in argv or "--help" in argv:
        return
    token = _first_command_token(argv)
    if token is None or token in commands:
        return
    matches = difflib.get_close_matches(token, commands, n=1, cutoff=0.6)
    if not matches:
        return
    parser.error(
        f"unknown command {_one_line(token)!r}. Did you mean {matches[0]!r}?"
    )


def _validated_snapshot_path(raw: str) -> Path:
    """Check a snapshot argument is a supported, readable file before loading."""
    path = Path(raw)
    # Directory first: a bare directory has no suffix, so checking the suffix
    # ahead of this would report "unsupported format" for what is really a
    # wrong kind of path.
    if path.is_dir():
        raise _UserError(f"snapshot path is a directory, not a file: {raw}")
    if path.suffix not in SUPPORTED_SNAPSHOT_SUFFIXES:
        raise _UserError(
            f"unsupported snapshot format {path.suffix or '(none)'!r} for {raw}; "
            f"expected one of {', '.join(SUPPORTED_SNAPSHOT_SUFFIXES)}"
        )
    if not path.exists():
        raise _UserError(f"snapshot not found: {raw}")
    return path


def _validated_directory(raw: str) -> Path:
    """Check an animation argument is an existing, usable directory."""
    path = Path(raw)
    if not path.exists():
        raise _UserError(f"directory not found: {raw}")
    if not path.is_dir():
        raise _UserError(f"not a directory: {raw}")
    return path


def _unreadable_input_errors():
    """The exception types that mean 'these bytes are not a usable snapshot'.

    Deliberately assembled rather than replaced by a bare ``except Exception``:
    the tuple is what separates a bad *file* from a bad *program*. NumPy signals
    a damaged archive in several unrelated ways -- an empty file raises
    ``EOFError``, non-archive bytes fall through to the pickle path and raise
    ``UnpicklingError``, a corrupt member raises ``BadZipFile`` or ``zlib.error``
    -- and none of those derive from ``OSError`` or ``ValueError``.
    """
    import pickle
    import zlib
    from zipfile import BadZipFile

    # OSError covers FileNotFoundError / IsADirectoryError / NotADirectoryError
    # / PermissionError. ValueError and KeyError cover an unsupported format, a
    # genome without an epigenetic snapshot, and a key-missing NPZ.
    return (
        OSError,
        ValueError,
        KeyError,
        EOFError,
        BadZipFile,
        zlib.error,
        pickle.UnpicklingError,
    )


def _load_snapshot_checked(path):
    """Load a snapshot, translating known input failures into user errors.

    The translation is scoped to the load call alone. Anything raised later --
    by a renderer, by matplotlib, by a genuine defect -- is untouched.
    """
    from vis.observatory.loader import load_snapshot

    try:
        return load_snapshot(path)
    except _unreadable_input_errors() as exc:
        raise _UserError(f"cannot read snapshot {path}: {exc}") from exc


def _validated_level(snapshot, axis: str, level):
    """Check an explicit slice level against the selected axis of the snapshot.

    Negative levels keep their ordinary Python meaning -- `numpy.take` with the
    default ``mode='raise'`` already indexes from the end, and `--level -1`
    rendered the last slice before this contract existed. The accepted range is
    therefore ``-extent <= level < extent``, which preserves that behaviour
    while still refusing an index the axis cannot satisfy.
    """
    if level is None:
        return None
    extent = snapshot.shape[_AXIS_INDEX[axis]]
    if not -extent <= level < extent:
        raise _UserError(
            f"level {level} is outside axis {axis!r} of size {extent} "
            f"(valid range {-extent} to {extent - 1})"
        )
    return level


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="cosmic-observatory",
        description="Phase 8 Cosmic Observatory -- UtilityFog CA Visualization",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- body: 3D organism view -------------------------------------------
    p_body = sub.add_parser("body", help="3D organism body (Plotly WebGL)")
    p_body.add_argument("snapshot", help="Path to .npz or .genome.json file")
    p_body.add_argument("--save", help="Save as HTML file")
    p_body.add_argument("--show-void", action="store_true",
                        help="Include void cells in render")

    # ---- slice: 2D cross-section ------------------------------------------
    p_slice = sub.add_parser("slice", help="2D lattice slice (matplotlib)")
    p_slice.add_argument("snapshot")
    p_slice.add_argument("--axis", choices=["x", "y", "z"], default="z")
    p_slice.add_argument("--level", type=int, default=None)
    p_slice.add_argument("--channel", type=_channel_index, default=None,
                         help="Overlay memory channel (0-7)")
    p_slice.add_argument("--save", help="Save as PNG file")

    # ---- tri: three orthogonal slices -------------------------------------
    p_tri = sub.add_parser("tri", help="Three orthogonal slices (matplotlib)")
    p_tri.add_argument("snapshot")
    p_tri.add_argument("--channel", type=_channel_index, default=None,
                       help="Show memory channel instead of states (0-7)")
    p_tri.add_argument("--save", help="Save as PNG file")

    # ---- signal: signal field 3D view -------------------------------------
    p_signal = sub.add_parser("signal", help="Signal field 3D view (Plotly)")
    p_signal.add_argument("snapshot")
    p_signal.add_argument("--save", help="Save as HTML")
    p_signal.add_argument("--threshold", type=_non_negative_float, default=0.01)

    # ---- warmth: metta warmth 3D view ------------------------------------
    p_warmth = sub.add_parser("warmth", help="Metta warmth 3D view (Plotly)")
    p_warmth.add_argument("snapshot")
    p_warmth.add_argument("--save", help="Save as HTML")

    # ---- elders: compute age 3D view -------------------------------------
    p_elders = sub.add_parser("elders", help="Compute elder cells 3D view (Plotly)")
    p_elders.add_argument("snapshot")
    p_elders.add_argument("--save", help="Save as HTML")

    # ---- channel: arbitrary channel view ----------------------------------
    p_chan = sub.add_parser("channel", help="View any memory channel")
    p_chan.add_argument("snapshot")
    p_chan.add_argument("channel_index", type=_channel_index,
                        metavar="CHANNEL")
    p_chan.add_argument("--mode", choices=["slice", "3d"], default="3d")
    p_chan.add_argument("--axis", choices=["x", "y", "z"], default="z")
    p_chan.add_argument("--level", type=int, default=None)
    p_chan.add_argument("--save", help="Save output")

    # ---- dashboard: multi-panel summary -----------------------------------
    p_dash = sub.add_parser("dashboard", help="Full observatory dashboard (matplotlib)")
    p_dash.add_argument("snapshot")
    p_dash.add_argument("--save", help="Save as PNG")

    # ---- animate: time-lapse GIF ------------------------------------------
    p_anim = sub.add_parser("animate", help="Animated time-lapse GIF")
    p_anim.add_argument("data_dir", help="Directory containing .npz files")
    p_anim.add_argument("--max-frames", type=_positive_int, default=50)
    p_anim.add_argument("--fps", type=_positive_int, default=4)
    p_anim.add_argument("--output", default="observatory_timelapse.gif")
    p_anim.add_argument("--channel", type=_channel_index, default=None,
                        help="Overlay memory channel (0-7)")
    p_anim.add_argument("--axis", choices=["x", "y", "z"], default="z")

    # ---- info: snapshot metadata ------------------------------------------
    p_info = sub.add_parser("info", help="Show snapshot metadata and statistics")
    p_info.add_argument("snapshot")

    if argv is None:
        argv = sys.argv[1:]
    _suggest_command(parser, argv, sorted(sub.choices))

    args = parser.parse_args(argv)

    try:
        return _dispatch(args)
    except _UserError as exc:
        print(f"{parser.prog}: error: {_one_line(exc)}", file=sys.stderr)
        return 1


def _dispatch(args):
    """Run one parsed command, returning 0 on success.

    Raises `_UserError` for expected, actionable user failures. Every other
    exception propagates untouched so genuine defects stay visible.
    """
    # Validate user-supplied paths BEFORE paying for the heavy lazy imports:
    # an unusable path should not first cost a NumPy/matplotlib import.
    if getattr(args, "snapshot", None) is not None:
        _validated_snapshot_path(args.snapshot)
    if getattr(args, "data_dir", None) is not None:
        _validated_directory(args.data_dir)

    # Lazy imports to keep CLI fast
    from vis.observatory.constants import (
        STATE_NAMES, CHANNEL_NAMES, SIGNAL_FIELD_CHANNEL, WARMTH_CHANNEL,
        COMPUTE_AGE_CHANNEL,
    )

    # ---- Dispatch ---------------------------------------------------------

    if args.command == "info":
        snap = _load_snapshot_checked(args.snapshot)
        print(f"Source:     {snap.source_path}")
        print(f"Shape:      {snap.shape}")
        print(f"Generation: {snap.generation:,}")
        print(f"CA Step:    {snap.ca_step:,}")
        print(f"Fitness:    {snap.best_fitness:.4f}")
        print(f"Non-void:   {snap.non_void_count:,} / {int(__import__('numpy').prod(snap.shape)):,}")
        print()
        for sid, name in STATE_NAMES.items():
            cnt = snap.state_count(sid)
            pct = cnt / int(__import__('numpy').prod(snap.shape)) * 100
            print(f"  {name:12s}: {cnt:>8,} ({pct:5.1f}%)")
        print()
        import numpy as _np
        for ci, cname in enumerate(CHANNEL_NAMES):
            ch = snap.channel(ci)
            nonvoid = ch[snap.lattice > 0]
            if len(nonvoid) > 0:
                print(f"  Ch {ci} {cname:22s}: "
                      f"min={nonvoid.min():+.4f}  max={nonvoid.max():+.4f}  "
                      f"mean={nonvoid.mean():+.4f}")
        return 0

    if args.command == "slice":
        snap = _load_snapshot_checked(args.snapshot)
        _validated_level(snap, args.axis, args.level)
        if args.channel is not None:
            from vis.observatory.slicer import slice_composite
            fig, _ = slice_composite(
                snap, axis=args.axis, level=args.level,
                overlay_channel=args.channel, save_path=args.save,
            )
        else:
            from vis.observatory.slicer import slice_lattice
            fig, _ = slice_lattice(
                snap, axis=args.axis, level=args.level, save_path=args.save,
            )
        if not args.save:
            import matplotlib.pyplot as plt
            plt.show()
        else:
            import matplotlib.pyplot as plt
            plt.close(fig)
        return 0

    if args.command == "tri":
        snap = _load_snapshot_checked(args.snapshot)
        from vis.observatory.slicer import tri_slice
        fig = tri_slice(snap, channel=args.channel, save_path=args.save)
        if not args.save:
            import matplotlib.pyplot as plt
            plt.show()
        else:
            import matplotlib.pyplot as plt
            plt.close(fig)
        return 0

    if args.command == "body":
        snap = _load_snapshot_checked(args.snapshot)
        from vis.observatory.scatter3d import organism_body
        fig = organism_body(snap, show_void=args.show_void, save_html=args.save)
        if not args.save:
            fig.show()
        return 0

    if args.command == "signal":
        snap = _load_snapshot_checked(args.snapshot)
        from vis.observatory.scatter3d import signal_field_3d
        fig = signal_field_3d(snap, threshold=args.threshold, save_html=args.save)
        if not args.save:
            fig.show()
        return 0

    if args.command == "warmth":
        snap = _load_snapshot_checked(args.snapshot)
        from vis.observatory.scatter3d import warmth_glow_3d
        fig = warmth_glow_3d(snap, save_html=args.save)
        if not args.save:
            fig.show()
        return 0

    if args.command == "elders":
        snap = _load_snapshot_checked(args.snapshot)
        from vis.observatory.scatter3d import compute_elders_3d
        fig = compute_elders_3d(snap, save_html=args.save)
        if not args.save:
            fig.show()
        return 0

    if args.command == "channel":
        snap = _load_snapshot_checked(args.snapshot)
        if args.mode == "slice":
            # `--level` only applies to the slice mode; the 3D mode ignores it.
            _validated_level(snap, args.axis, args.level)
            from vis.observatory.slicer import slice_channel
            fig, _ = slice_channel(
                snap, args.channel_index, axis=args.axis, level=args.level,
                save_path=args.save,
            )
            if not args.save:
                import matplotlib.pyplot as plt
                plt.show()
            else:
                import matplotlib.pyplot as plt
                plt.close(fig)
        else:
            from vis.observatory.scatter3d import channel_overlay
            fig = channel_overlay(
                snap, args.channel_index, save_html=args.save,
            )
            if not args.save:
                fig.show()
        return 0

    if args.command == "dashboard":
        snap = _load_snapshot_checked(args.snapshot)
        from vis.observatory.dashboard import observatory_dashboard
        fig = observatory_dashboard(snap, save_path=args.save)
        if not args.save:
            import matplotlib.pyplot as plt
            plt.show()
        else:
            import matplotlib.pyplot as plt
            plt.close(fig)
        return 0

    if args.command == "animate":
        from vis.observatory.animation import animate_from_directory
        try:
            animate_from_directory(
                args.data_dir,
                max_frames=args.max_frames,
                output_path=args.output,
                fps=args.fps,
                overlay_channel=args.channel,
                axis=args.axis,
            )
        except _unreadable_input_errors() as exc:
            # No matching frames in the directory, or one of the frames is
            # itself unreadable -- the same input class the single-snapshot
            # path already reports as a user error.
            raise _UserError(f"cannot animate {args.data_dir}: {exc}") from exc
        return 0

    # argparse enforces `required=True` on the subcommand, so this is
    # unreachable for parsed input; it keeps the contract total.
    raise AssertionError(f"unhandled command: {args.command!r}")


if __name__ == "__main__":
    sys.exit(main())
