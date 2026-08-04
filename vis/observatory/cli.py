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
    python -m vis.observatory info <snapshot> [--json]
    python -m vis.observatory doctor <snapshot> [--json]
"""

from __future__ import annotations

import argparse
import difflib
import json
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
#                 slice level outside the selected axis -- and, for `doctor`,
#                 a snapshot that loaded but failed one or more diagnostics
#
# `--help` keeps argparse's conventional exit status 0.
#
# `doctor` is the one command that can return 1 after a fully successful load:
# a completed diagnostic run with at least one failed requirement is a reported
# result, not an error, so it prints its report normally (to stdout) and its
# status alone tells a caller whether the snapshot is usable.
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


def _emit_json(report) -> None:
    """Write exactly one JSON document to stdout, and nothing else.

    ``allow_nan=False`` is a genuine assertion, not decoration: Python's
    encoder otherwise emits the bare tokens ``NaN`` / ``Infinity``, which are
    not valid JSON and break strict parsers. The report builders already map
    every non-finite value to ``null``, so this raises only if that mapping is
    ever missed -- a defect, which is exactly what should propagate.

    ``sort_keys=True`` makes the byte output a function of the content alone,
    so equivalent snapshots serialize identically.
    """
    print(json.dumps(report, sort_keys=True, allow_nan=False, separators=(",", ":")))


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
    p_info.add_argument("--json", action="store_true",
                        help="Emit one JSON document on stdout instead of text")

    # ---- doctor: runtime-data-contract preflight ---------------------------
    p_doctor = sub.add_parser(
        "doctor",
        help="Preflight a snapshot against the Observatory data contract",
    )
    p_doctor.add_argument("snapshot")
    p_doctor.add_argument("--json", action="store_true",
                          help="Emit one JSON document on stdout instead of text")

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
    # Validate user-supplied paths before the per-command imports performed
    # below by this module. This does NOT mean an invalid path avoids NumPy or
    # matplotlib altogether: running `python -m vis.observatory` first executes
    # the `vis` and `vis.observatory` package initializers, which import the
    # loader (and, through sibling `vis` modules, matplotlib). Narrowing that
    # is a separate change to package initialization and is not made here.
    if getattr(args, "snapshot", None) is not None:
        _validated_snapshot_path(args.snapshot)
    if getattr(args, "data_dir", None) is not None:
        _validated_directory(args.data_dir)

    # ---- Dispatch ---------------------------------------------------------

    if args.command == "info":
        snap = _load_snapshot_checked(args.snapshot)
        from vis.observatory import diagnostics

        if args.json:
            _emit_json(diagnostics.info_report(snap, str(snap.source_path)))
            return 0

        stats = diagnostics.snapshot_statistics(snap)
        total = stats["total_cells"]
        print(f"Source:     {snap.source_path}")
        print(f"Shape:      {snap.shape}")
        print(f"Generation: {snap.generation:,}")
        print(f"CA Step:    {snap.ca_step:,}")
        print(f"Fitness:    {snap.best_fitness:.4f}")
        print(f"Non-void:   {stats['non_void_count']:,} / {total:,}")
        print()
        # Rendered through the shared formatters: the statistics are JSON-safe,
        # so a non-finite channel value arrives as None. Formatting None with a
        # numeric spec raises, which would turn `info` on a snapshot carrying
        # NaN into a traceback -- the very snapshot `doctor` exists to report.
        for entry in stats["state_counts"]:
            print(f"  {entry['name']:12s}: {entry['count']:>8,} "
                  f"({diagnostics.format_percent(entry['percent'])}%)")
        print()
        for channel in stats["channels"]:
            if not channel["populated"]:
                continue
            print(f"  Ch {channel['index']} {channel['name']:22s}: "
                  f"min={diagnostics.format_stat(channel['min'])}  "
                  f"max={diagnostics.format_stat(channel['max'])}  "
                  f"mean={diagnostics.format_stat(channel['mean'])}")
        return 0

    if args.command == "doctor":
        # Preflight only: the snapshot is loaded through the ordinary public
        # route and inspected. No renderer is imported, no window opens, no
        # file is written.
        snap = _load_snapshot_checked(args.snapshot)
        from vis.observatory import diagnostics

        checks = diagnostics.diagnose(snap)
        source = str(snap.source_path)
        if args.json:
            _emit_json(diagnostics.doctor_report(snap, source, checks))
        else:
            for line in diagnostics.format_doctor(checks, source):
                print(line)
        return 0 if diagnostics.all_ok(checks) else 1

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
        # Two phases with different contracts, so they are invoked separately.
        # `animate_from_directory()` performs both in a single call, which is
        # why it is not used here: wrapping it would translate a renderer or
        # output defect into a user error and swallow its traceback.
        #
        # Phase 1 -- discovery and loading. This is input handling, so the same
        # unreadable-input set the single-snapshot path uses applies. Omitting
        # `pattern` keeps the loader's own default, which is the value
        # `animate_from_directory()` would have passed.
        from vis.observatory.loader import load_snapshot_series

        try:
            snapshots = load_snapshot_series(args.data_dir, max_count=args.max_frames)
        except _unreadable_input_errors() as exc:
            raise _UserError(f"cannot animate {args.data_dir}: {exc}") from exc

        # Phase 2 -- rendering and saving. Deliberately OUTSIDE the translation
        # boundary: a failure here is a defect, not bad user input, and must
        # keep its traceback.
        from vis.observatory.animation import animate_slices

        animate_slices(
            snapshots,
            output_path=args.output,
            fps=args.fps,
            overlay_channel=args.channel,
            axis=args.axis,
        )
        return 0

    # argparse enforces `required=True` on the subcommand, so this is
    # unreachable for parsed input; it keeps the contract total.
    raise AssertionError(f"unhandled command: {args.command!r}")


if __name__ == "__main__":
    sys.exit(main())
