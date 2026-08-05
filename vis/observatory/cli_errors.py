"""Cosmic Observatory: the machine-readable CLI error contract.

A caller that asks for JSON should never be answered with prose. The
Observatory's machine-oriented commands already emit strict documents on
success; this module supplies the matching shape for an expected *failure*,
so an automated consumer has something to parse on every outcome.

Deliberately standard-library-only and free of any rendering, NumPy or
visualization import. Two reasons, both load-bearing: the error path must
stay usable when the reason for failing is that an optional dependency is
missing, and the module must remain importable in isolation so its purity can
be tested from a bare interpreter.

Nothing here reads or writes a file, touches the network, or terminates the
process. It takes already-classified facts and returns text; the CLI owns
streams and exit statuses.

Contract summary
----------------
An expected failure emits one JSON object, on one physical line, on stderr:

    {"argument":null,"category":"usage","code":"unknown-command",...}

Keys are sorted, separators are compact, and the document is ASCII-escaped.
That last point is not cosmetic -- see :func:`render`.

Forward compatibility, for consumers
------------------------------------
1. ``schema`` is ``utilityfog.observatory.error/1``. The trailing ``/N`` is
   bumped only for an incompatible structural change.
2. New keys may be added at any time. Ignore keys you do not recognise.
3. Existing keys are never removed, renamed or retyped within a version.
4. Tolerate an unknown ``code`` by falling back to ``category``; tolerate an
   unknown ``category`` by falling back to the process exit status.
5. ``message`` and ``suggestion`` are human text. They are unstable, may be
   localised by the underlying OS, and must never be parsed.
6. Nullable fields are always present. ``null`` means "not applicable", never
   "unknown".
7. The process exit status is authoritative; ``exit_status`` restates it for
   readers who see the document detached from the process, such as a log line.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

#: Bumped only when the emitted structure changes incompatibly.
ERROR_SCHEMA = "utilityfog.observatory.error/1"

CATEGORY_USAGE = "usage"
CATEGORY_INPUT = "input"

#: The closed set of categories. A category fixes the exit status.
CATEGORIES = frozenset({CATEGORY_USAGE, CATEGORY_INPUT})

#: Exit status per category. Single source of truth: callers pass a code,
#: never a status, so the body and the process can never disagree.
_STATUS_BY_CATEGORY = {CATEGORY_USAGE: 2, CATEGORY_INPUT: 1}

#: The closed initial code vocabulary, mapped to its category.
#:
#: `usage` codes describe a command line the CLI could not accept at all;
#: `input` codes describe a command line that parsed but named something the
#: CLI could not use. That split is exactly the existing exit taxonomy, so the
#: vocabulary adds names to established behaviour rather than new behaviour.
CODES: Dict[str, str] = {
    # -- usage (status 2) ---------------------------------------------------
    "missing-command": CATEGORY_USAGE,
    "unknown-command": CATEGORY_USAGE,
    "unknown-option": CATEGORY_USAGE,
    "missing-argument": CATEGORY_USAGE,
    "invalid-argument-value": CATEGORY_USAGE,
    # Fallback. argparse's own messages are English prose that varies by
    # Python version and may be localised, so classification is deliberately
    # conservative: an unrecognised usage failure is reported honestly as
    # `usage-error` rather than guessed into a more specific code.
    "usage-error": CATEGORY_USAGE,
    # -- input (status 1) ---------------------------------------------------
    "snapshot-not-found": CATEGORY_INPUT,
    "snapshot-wrong-path-kind": CATEGORY_INPUT,
    "snapshot-unsupported-suffix": CATEGORY_INPUT,
    "snapshot-unreadable": CATEGORY_INPUT,
    "animation-directory-invalid": CATEGORY_INPUT,
    "level-out-of-range": CATEGORY_INPUT,
    # Fallback for an expected runtime failure with no more specific code.
    "input-error": CATEGORY_INPUT,
}

#: Cap on any single string field, applied after sanitising.
#:
#: Three routes can hand this module an unbounded value: argparse echoes the
#: raw argv token in an invalid-value message, a filesystem path is
#: caller-controlled, and an exception's own text can be arbitrarily long.
#: Truncation is visible rather than silent, and is applied to field VALUES --
#: never to the serialised document, which would destroy parseability.
MAX_FIELD_LENGTH = 256

_TRUNCATION_MARKER = "..."

#: Redacted rather than merely bounded. An exception's text can carry a
#: formatted traceback (a nested error, a subprocess's captured output), and
#: the contract promises no traceback ever reaches a consumer. Replacing the
#: marker leaves visible evidence that something was removed.
_TRACEBACK_MARKER = "Traceback (most recent call last)"
_TRACEBACK_REDACTION = "[traceback removed]"


def category_for(code: str) -> str:
    """Return the category a code belongs to."""
    try:
        return CODES[code]
    except KeyError:
        raise KeyError(f"unknown error code {code!r}") from None


def status_for(code: str) -> int:
    """Return the exit status a code implies."""
    return _STATUS_BY_CATEGORY[category_for(code)]


def sanitize(value: Any) -> Optional[str]:
    """Return ``value`` as one bounded, single-line, ASCII-safe string.

    ``None`` passes through, because a nullable field stays null rather than
    becoming the text ``"None"``.

    Three transformations, in this order and for distinct reasons:

    1. **Collapse line boundaries.** ``str.splitlines()`` splits on far more
       than CR and LF -- ``\\v``, ``\\f``, ``\\x1c``-``\\x1e``, ``\\x85``,
       ``\\u2028`` and ``\\u2029`` all count. A caller-supplied path
       containing any of them could otherwise forge an extra line, and a
       line-oriented consumer would read a document the CLI never emitted.
       JSON escaping alone is not a substitute: it neutralises ``\\x00``-
       ``\\x1f`` unconditionally, but ``\\x85`` and ``\\u2028`` only under
       ASCII escaping. Collapsing here means the guarantee does not depend on
       a serializer flag.
    2. **Force ASCII.** A lone surrogate -- from a POSIX ``surrogateescape``
       filename or an unpaired UTF-16 unit on Windows -- would otherwise be
       emitted as an unpaired ``\\udcff`` escape, which is invalid JSON that
       strict parsers reject. Encoding with ``backslashreplace`` turns it into
       literal text before the serializer ever sees it.
    3. **Bound the length**, with a visible marker.
    """
    if value is None:
        return None
    text = " ".join(str(value).splitlines()).strip()
    text = text.replace(_TRACEBACK_MARKER, _TRACEBACK_REDACTION)
    text = text.encode("ascii", "backslashreplace").decode("ascii")
    if len(text) > MAX_FIELD_LENGTH:
        text = text[:MAX_FIELD_LENGTH] + _TRUNCATION_MARKER
    return text


def build_envelope(
    code: str,
    message: Any,
    suggestion: Any = None,
    command: Any = None,
    argument: Any = None,
) -> Dict[str, Any]:
    """Return the envelope for one expected failure.

    ``category`` and ``exit_status`` are derived from ``code`` rather than
    passed in, so the two can never contradict each other or the process.

    Every nullable field is present in the result. A field that disappears
    when inapplicable forces consumers to branch on key existence; ``null``
    lets them read one shape every time.
    """
    return {
        "schema": ERROR_SCHEMA,
        "ok": False,
        "category": category_for(code),
        "code": code,
        "message": sanitize(message),
        "suggestion": sanitize(suggestion),
        "command": sanitize(command),
        "argument": sanitize(argument),
        "exit_status": status_for(code),
    }


def render(envelope: Dict[str, Any]) -> str:
    """Serialize an envelope to the exact text written to stderr.

    ``sort_keys=True`` makes the bytes a function of the content alone, so two
    runs over equivalent inputs agree regardless of construction path.
    ``allow_nan=False`` is an assertion rather than decoration: this module
    never produces a non-finite value, so it fires only on a defect.

    ``ensure_ascii`` is left at its default ``True`` **deliberately**. With it
    off, ``json.dumps`` passes U+2028, U+2029 and U+0085 through unescaped --
    legal JSON, but every one of them is a line boundary to
    ``str.splitlines()``, which would break the single-line contract for any
    consumer reading stderr line by line. :func:`sanitize` already removes
    them, so this is defence in depth; do not "improve" it by turning
    ``ensure_ascii`` off to keep paths readable.

    The trailing newline is part of the contract and is included here, so the
    caller performs exactly one write.
    """
    return json.dumps(
        envelope, sort_keys=True, allow_nan=False, separators=(",", ":")
    ) + "\n"


def format_error(
    code: str,
    message: Any,
    suggestion: Any = None,
    command: Any = None,
    argument: Any = None,
) -> str:
    """Build and render in one step -- the CLI's usual entry point."""
    return render(build_envelope(code, message, suggestion, command, argument))
