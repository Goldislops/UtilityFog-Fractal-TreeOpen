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
import errno
import json
import os
import stat
import sys
from pathlib import Path

from vis.observatory import cli_errors

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


#: Commands that already speak JSON on success, and therefore must speak it on
#: failure too: answering `--json` with prose leaves a machine consumer with
#: nothing to parse.
_JSON_COMMANDS = frozenset({"info", "doctor"})

_ERROR_FORMATS = ("human", "json")

#: Global options that consume a following token. Kept as data because two
#: separate pieces of logic must agree about it: the pre-scan below, and
#: `_first_command_token`, which would otherwise mistake an option's VALUE for
#: the subcommand.
_VALUE_TAKING_GLOBAL_OPTIONS = ("--error-format",)

#: The error format for the current `main()` call, or None when the global
#: option was not supplied. Module scope because argparse discovers usage
#: failures inside `parse_args`, before any namespace exists to carry it.
_ERROR_FORMAT = None


class _UserError(Exception):
    """An expected, actionable user-facing failure (exit status 1).

    Carries the machine-readable ``code`` from the raise site. Assigning it
    there rather than deriving it from the message text is deliberate: message
    wording is human prose that varies with the OS, the locale and the
    library version, and must never be load-bearing.
    """

    def __init__(self, message, code="input-error"):
        super().__init__(message)
        self.code = code


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


def _is_value_taking_option(token: str) -> bool:
    """True when ``token`` names a global option that consumes the next token.

    Prefix matching mirrors argparse's own abbreviation support (``allow_abbrev``
    defaults to True), so the pre-scan and the parser agree on what ``--error-f``
    means rather than diverging on an abbreviation.
    """
    if "=" in token or not token.startswith("--") or len(token) <= 2:
        return False
    return any(name.startswith(token) for name in _VALUE_TAKING_GLOBAL_OPTIONS)


def _first_command_token(argv):
    """Return the first non-option token, i.e. the intended subcommand.

    Skipping bare ``-``-prefixed tokens is not enough once a global option
    takes a value: in ``--error-format json slize``, the value ``json`` is not
    an option and would be returned as the intended subcommand, so the typo
    ``slize`` would never be examined and the did-you-mean suggestion would be
    silently lost.
    """
    skip_value = False
    for token in argv:
        if skip_value:
            skip_value = False
            continue
        if token == "--":
            return None
        if token.startswith("-"):
            skip_value = _is_value_taking_option(token)
            continue
        return token
    return None


def _scan_error_format(argv):
    """Read ``--error-format`` from argv before argparse runs.

    Necessary, not merely convenient: argparse reports a usage failure from
    inside ``parse_args``, so no parsed namespace exists yet at the moment the
    format is needed. Returns ``None`` when the option is absent, which is what
    lets an explicit ``--error-format human`` override the automatic upgrade
    for ``info --json`` / ``doctor --json``.

    The rules, in full:

    1. No occurrence -> ``None``.
    2. Every occurrence valid -> the LAST one, matching argparse's ordinary
       repeated-option semantics. This scan is a second reader of the same
       argv and has to reach the same answer argparse will; returning the
       first occurrence instead would mean the format the CLI emits disagrees
       with the format it parsed, and which a caller observed would depend on
       whether the failure happened before or after ``parse_args``.
    3. ANY occurrence carrying an invalid value, or lacking its value
       entirely, makes the result ``human`` -- and that is STICKY. argparse
       cannot parse such a command line at all, so the whole invocation is
       refused; a later valid occurrence must not launder an earlier invalid
       one into an accepted JSON selection, and an earlier valid occurrence
       must not survive a later missing value. A format that was never
       validly selected must not be trusted to carry the refusal.
    4. Separated, equals and supported abbreviated forms all agree.

    Only the GLOBAL PREFIX is scanned. ``--error-format`` is a global option
    and is only meaningful before the subcommand, because the subparsers
    action consumes everything from the command name onward. So the scan stops
    at the first unconsumed non-option token -- the intended subcommand --
    rather than walking the whole argv.

    Without that stop, ``--error-format json info snap.npz --error-format
    human`` overwrote the selection from the subcommand's own arguments.
    argparse refuses the misplaced trailing option as a usage error, but the
    caller HAD validly asked for JSON, so the refusal must be a JSON envelope.
    Conversely a trailing occurrence must never retroactively select a format
    when no valid one appeared in the prefix.
    """
    selected = None
    failed = False
    expect_value = False
    for token in argv:
        if expect_value:
            expect_value = False
            if token in _ERROR_FORMATS:
                selected = token
            else:
                failed = True
            continue
        if token == "--":
            break
        if not token.startswith("-"):
            # The subcommand. Everything after it belongs to the subparser.
            break
        if token.startswith("--") and "=" in token:
            name, _, value = token.partition("=")
            if any(opt.startswith(name) for opt in _VALUE_TAKING_GLOBAL_OPTIONS):
                if value in _ERROR_FORMATS:
                    selected = value
                else:
                    failed = True
            continue
        if _is_value_taking_option(token):
            expect_value = True
    if expect_value:
        # The option was the final token, so its value never arrived.
        failed = True
    return "human" if failed else selected


def _classify_usage_error(message):
    """Map one argparse message to a (code, argument) pair.

    argparse's text is English prose, gettext-wrapped and version-dependent, so
    the anchors here are narrow and the fallback is honest: an unrecognised
    shape becomes ``usage-error`` rather than being guessed into a more
    specific code that a consumer might then rely on.
    """
    text = message or ""
    if "the following arguments are required" in text:
        required = text.split(":", 1)[-1]
        if "command" in required:
            return "missing-command", None
        return "missing-argument", required.strip() or None
    if text.startswith("unrecognized arguments"):
        return "unknown-option", text.split(":", 1)[-1].strip() or None
    if text.startswith("argument "):
        name, _, detail = text.partition(":")
        argument = name[len("argument "):].strip() or None
        # An invalid CHOICE of subcommand is an unknown command, not a bad
        # value: `command` is the dest argparse gives the subparsers action.
        if "invalid choice" in detail:
            if argument == "command":
                return "unknown-command", None
            return "invalid-argument-value", argument
        # The option was present but its value was not. Nothing was supplied
        # to be invalid, so this is a missing argument.
        if "expected" in detail and "argument" in detail:
            return "missing-argument", argument
        # A value was attached to a flag that takes none, e.g. `--json=x`.
        if "ignored explicit argument" in detail:
            return "unknown-option", argument
        return "invalid-argument-value", argument
    if "invalid choice" in text:
        return "invalid-argument-value", None
    return "usage-error", None


class _ObservatoryParser(argparse.ArgumentParser):
    """An ArgumentParser that can report a usage failure as a JSON envelope.

    Only ``error()`` is overridden. ``exit()`` and ``print_help()`` are left
    alone on purpose: ``--help`` must stay human text on stdout at status 0
    whatever the error format says.

    ``add_subparsers`` defaults ``parser_class`` to ``type(self)``, so every
    subparser inherits this behaviour -- which is what covers missing
    positionals and every ``ArgumentTypeError`` from the custom converters,
    since those are raised by the subparser rather than by this one.
    """

    def error(self, message):
        if _ERROR_FORMAT != "json":
            super().error(message)      # unchanged human behaviour
        code, argument = _classify_usage_error(message)
        sys.stderr.write(cli_errors.format_error(
            code, message, argument=argument,
        ))
        sys.exit(2)


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
    # Bound the token before difflib sees it: `get_close_matches` builds an
    # index over the whole word before any cutoff applies, so a pathological
    # argv value would be paid for in full. No real subcommand typo is this
    # long, and `main(argv=[...])` is a supported entry point.
    if len(token) > 64:
        return
    matches = difflib.get_close_matches(token, commands, n=1, cutoff=0.6)
    if not matches:
        return
    suggestion = f"Did you mean {matches[0]!r}?"
    message = f"unknown command {_one_line(token)!r}. {suggestion}"
    if _ERROR_FORMAT == "json":
        sys.stderr.write(cli_errors.format_error(
            "unknown-command", message,
            suggestion=suggestion, argument=token,
        ))
        sys.exit(2)
    parser.error(message)


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


# Failures that positively establish "there is nothing at this path". These
# are the errnos `pathlib` has always read as absence, named here so the CLI's
# answer stops depending on which Python version runs it. Windows reports an
# unresolvable reparse point -- its symlink loop -- as ERROR_CANT_RESOLVE_
# FILENAME rather than as ELOOP, so that one is matched on the winerror.
_ABSENCE_ERRNOS = frozenset({errno.ENOENT, errno.ENOTDIR, errno.EBADF, errno.ELOOP})

# Windows answers with a winerror where POSIX answers with an errno, and the
# two do not line up: it collapses most absence onto ENOENT, signals its own
# symlink loop as ERROR_CANT_RESOLVE_FILENAME rather than ELOOP, and reports
# a name the filesystem cannot hold -- a component past 255 characters, or one
# containing a character NTFS forbids -- as ERROR_INVALID_NAME with EINVAL.
# That last one is absence, not ignorance: no file can ever carry that name,
# which is why POSIX, where those same bytes are legal, simply reports the
# path as missing.
_ABSENCE_WINERRORS = frozenset({
    123,   # ERROR_INVALID_NAME
    1921,  # ERROR_CANT_RESOLVE_FILENAME
})

# The opposite case, and the reason this is a separate set rather than another
# errno: ERROR_FILENAME_EXCED_RANGE arrives as ENOENT, so the errno alone
# would read as "absent". It is not. It means this system could not reach the
# path -- the same path is examinable on a machine with long paths enabled --
# so it is ignorance, and it is tested first.
_UNEXAMINABLE_WINERRORS = frozenset({206})  # ERROR_FILENAME_EXCED_RANGE


def _examined(raw: str):
    """Look at `raw` once and return what was actually established.

    Returns an `os.stat_result` for a path that is there, or None for one
    positively established to be absent. For a path the OS could not examine
    it raises `_UserError` with the honest ``input-error`` fallback.

    This deliberately does not use `Path.exists()` / `Path.is_dir()`. Those
    answer False for two entirely different situations -- "nothing is there"
    and "I could not look" -- and telling those apart is the whole of this
    contract:

      * every Python version swallows `ValueError`, which is what Windows
        raises for an over-long path ("path too long for Windows") and what
        every platform raises for a name containing NUL. A `ValueError` is
        not an `OSError`, so no amount of catching `OSError` around a
        predicate can recover it;
      * from 3.14 the predicates delegate to `os.path.exists()` /
        `os.path.isdir()`, which swallow every `OSError`, so EACCES and
        ENAMETOOLONG answer False as well. Before 3.14 `pathlib._ignore_error`
        let those through on POSIX but already swallowed ERROR_INVALID_NAME
        on Windows.

    Asking `os.stat` directly is what makes the distinction visible: it
    either hands back affirmative evidence or names a concrete failure. Doing
    it once also means the kind, the presence and the absence of a path are
    read from a single observation rather than two that could disagree.

    What is examined is `Path(raw)`, not `raw`, because `Path(raw)` is what
    the rest of the CLI then operates on -- `Path("")` is the current
    directory and a trailing separator is dropped, neither of which survives
    stat'ing the user's literal text.
    """
    try:
        return os.stat(Path(raw))
    except ValueError as exc:
        raise _UserError(
            f"cannot examine path {raw}: {exc}", "input-error"
        ) from exc
    except OSError as exc:
        winerror = getattr(exc, "winerror", None)
        if winerror not in _UNEXAMINABLE_WINERRORS and (
            exc.errno in _ABSENCE_ERRNOS or winerror in _ABSENCE_WINERRORS
        ):
            return None
        # EACCES, ENAMETOOLONG, a drive that is not ready, a path this
        # system cannot reach. NOTHING was established about what is there,
        # so the specific codes stay reserved: `snapshot-wrong-path-kind`
        # would assert it is a directory and `snapshot-not-found` would
        # assert it is absent, and neither was determined. Reporting
        # `strerror` rather than the exception itself
        # keeps the path from appearing a second time -- `OSError.__str__`
        # embeds it, and the prose lane does not clip.
        raise _UserError(
            f"cannot examine path {raw}: {exc.strerror or exc}", "input-error"
        ) from exc


def _validated_snapshot_path(raw: str) -> Path:
    """Check a snapshot argument is a supported, readable file before loading."""
    path = Path(raw)
    status = _examined(raw)
    # Directory first: a bare directory has no suffix, so checking the suffix
    # ahead of this would report "unsupported format" for what is really a
    # wrong kind of path.
    if status is not None and stat.S_ISDIR(status.st_mode):
        raise _UserError(
            f"snapshot path is a directory, not a file: {raw}",
            "snapshot-wrong-path-kind",
        )
    if path.suffix not in SUPPORTED_SNAPSHOT_SUFFIXES:
        raise _UserError(
            f"unsupported snapshot format {path.suffix or '(none)'!r} for {raw}; "
            f"expected one of {', '.join(SUPPORTED_SNAPSHOT_SUFFIXES)}",
            "snapshot-unsupported-suffix",
        )
    if status is None:
        raise _UserError(f"snapshot not found: {raw}", "snapshot-not-found")
    return path


def _validated_directory(raw: str) -> Path:
    """Check an animation argument is an existing, usable directory."""
    path = Path(raw)
    status = _examined(raw)
    if status is None:
        raise _UserError(
            f"directory not found: {raw}", "animation-directory-invalid"
        )
    if not stat.S_ISDIR(status.st_mode):
        raise _UserError(f"not a directory: {raw}", "animation-directory-invalid")
    return path


def _unreadable_input_errors():
    """The exception types that mean 'these bytes are not a usable snapshot'.

    Deliberately assembled rather than replaced by a bare ``except Exception``:
    the tuple is what separates a bad *file* from a bad *program*. NumPy signals
    a damaged archive in several unrelated ways -- an empty file raises
    ``EOFError``, a corrupt member raises ``BadZipFile`` or ``zlib.error`` --
    and neither of those derives from ``OSError`` or ``ValueError``.

    The Observatory loader now opens archives with ``allow_pickle=False``, so
    non-archive bytes and pickle-backed members are refused BEFORE any
    unpickling, normally as ``ValueError``. That refusal is already covered by
    ``ValueError`` below.

    ``pickle.UnpicklingError`` is retained conservatively: this tuple is shared
    by every input-translation site, and keeping it costs nothing. Its presence
    describes what would be *translated* if it ever arrived -- it does not
    enable, authorise or imply pickle anywhere. Nothing in this package
    unpickles.
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
        raise _UserError(
            f"cannot read snapshot {path}: {exc}", "snapshot-unreadable"
        ) from exc


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
            f"(valid range {-extent} to {extent - 1})",
            "level-out-of-range",
        )
    return level


def _error_format_for(args) -> str:
    """Resolve the error format for a failure that happened after parsing.

    An explicit global option always wins. Absent one, a command that was
    asked for JSON on success gets JSON on failure too -- answering `--json`
    with prose is the gap this contract exists to close. The upgrade is scoped
    to those commands; every other subcommand stays human.
    """
    if _ERROR_FORMAT is not None:
        return _ERROR_FORMAT
    if getattr(args, "command", None) in _JSON_COMMANDS and getattr(args, "json", False):
        return "json"
    return "human"


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    # Read before the parser is built: argparse reports usage failures from
    # inside `parse_args`, so a namespace does not exist yet when the format
    # is first needed.
    global _ERROR_FORMAT
    _ERROR_FORMAT = _scan_error_format(argv)

    parser = _ObservatoryParser(
        prog="cosmic-observatory",
        description="Phase 8 Cosmic Observatory -- UtilityFog CA Visualization",
    )
    parser.add_argument(
        "--error-format", choices=_ERROR_FORMATS, default="human",
        help="How to report an expected failure. 'json' emits one error "
             "envelope on stderr. Must appear before the subcommand.",
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

    _suggest_command(parser, argv, sorted(sub.choices))

    args = parser.parse_args(argv)

    try:
        return _dispatch(args)
    except _UserError as exc:
        if _error_format_for(args) == "json":
            # One write, terminator included, so nothing can interleave
            # between the document and its newline.
            sys.stderr.write(cli_errors.format_error(
                exc.code, str(exc), command=getattr(args, "command", None),
            ))
        else:
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
        # `_one_line` on the path for the same reason the error lane uses it:
        # a filename is untrusted data and must not forge extra output rows.
        print(f"Source:     {_one_line(snap.source_path)}")
        print(f"Shape:      {snap.shape}")
        # Through the shared formatter: `{:,}` raises ValueError on an integer
        # past CPython's decimal-rendering ceiling. That value can still arrive
        # by DIRECT LIBRARY CONSTRUCTION -- a snapshot assembled in memory is a
        # supported seam -- so the formatter's robustness remains necessary.
        # It can no longer arrive through the NPZ route: an integer that large
        # has only an object-array representation, and the loader refuses those
        # with `allow_pickle=False` before anything reaches formatting.
        # Ordinary counters render exactly as before.
        print(f"Generation: {diagnostics.format_count(snap.generation)}")
        print(f"CA Step:    {diagnostics.format_count(snap.ca_step)}")
        print(f"Fitness:    {snap.best_fitness:.4f}")
        print(f"Non-void:   {diagnostics.format_count(stats['non_void_count'])}"
              f" / {diagnostics.format_count(total)}")
        print()
        # Rendered through the shared formatters: the statistics are JSON-safe,
        # so a value that could not be computed arrives as None. Formatting
        # None with a numeric spec raises, which would turn `info` on a
        # snapshot carrying NaN into a traceback -- the very snapshot `doctor`
        # exists to report.
        for entry in stats["state_counts"]:
            print(f"  {entry['name']:12s}: "
                  f"{diagnostics.format_count(entry['count'], 8)} "
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
            raise _UserError(
                f"cannot animate {args.data_dir}: {exc}",
                "animation-directory-invalid",
            ) from exc

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
