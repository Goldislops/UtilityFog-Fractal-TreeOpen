"""OMI-V1 - redaction for operator notes, and the diagnostic record shape.

Two different protections live here, and it matters that they are not
confused with one another:

**Structural (the strong one).** Nothing in this package has a field that
holds prompt, message, system, or tool-argument text. ``TaskRequirements``
carries only booleans, integers, and vocabulary tokens. ``DiagnosticRecord``
and the evaluation records carry only stable codes, backend names, and sizes.
Prompt content is not scrubbed on its way in - it is never accepted in the
first place, which is a guarantee a pattern matcher cannot give. If a
diagnostic needs to say something about model-facing text, ``describe_size``
is the only sanctioned way to reference it.

**Pattern-based (the narrow one).** ``redact`` scrubs *shaped* secrets from
a short human-written note: credentials, bearer tokens, provider key
prefixes, secret-named environment assignments, long opaque strings,
filesystem paths, and email addresses. This is a defence for the case where
an operator pastes something careless into a note. It is explicitly **not** a
general prompt sanitiser: free-form natural language carries no shape to
match on, and claiming otherwise would be false assurance. Keep prompts out
structurally; use ``redact`` for the note field only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final, Pattern


REDACTED_SECRET: Final[str] = "[redacted:secret]"
REDACTED_PATH: Final[str] = "[redacted:path]"
REDACTED_EMAIL: Final[str] = "[redacted:email]"

NOTE_MAX_CHARS: Final[int] = 512
"""Hard ceiling on any note. Applied *before* matching, see ``redact``."""


# Ordered most-specific first. Every pattern is linear in the input - no
# nested quantifiers - so a hostile note cannot make matching blow up.
_RULES: Final[tuple[tuple[Pattern[str], str], ...]] = (
    # KEY=value / "api key": value, including quoted values.
    (
        re.compile(
            r"(?i)\b(?:api[-_ ]?key|apikey|access[-_ ]?token|auth[-_ ]?token"
            r"|token|secret|password|passwd|pwd|credentials?)\b\s*[:=]\s*"
            r"[\"']?[^\s\"',;]+"
        ),
        REDACTED_SECRET,
    ),
    # Authorization: Bearer <token>
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+"), REDACTED_SECRET),
    # Environment-variable assignments whose NAME implies a secret. Needed in
    # addition to the rule above because there is no word boundary inside
    # ANTHROPIC_API_KEY, so the labelled-assignment rule cannot see it.
    (
        re.compile(
            r"(?i)\b[A-Za-z_][A-Za-z0-9_]*"
            r"(?:KEY|TOKEN|SECRET|PASSWORD|PWD|CREDENTIAL)"
            r"[A-Za-z0-9_]*\s*=\s*\S+"
        ),
        REDACTED_SECRET,
    ),
    # Well-known provider key prefixes.
    (re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_\-]{8,}"), REDACTED_SECRET),
    (re.compile(r"\bnvapi-[A-Za-z0-9_\-]{8,}"), REDACTED_SECRET),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"), REDACTED_SECRET),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{8,}"), REDACTED_SECRET),
    (re.compile(r"\bAKIA[0-9A-Z]{12,}"), REDACTED_SECRET),
    # Long opaque runs - base64/hex blobs. 40 characters keeps ordinary prose
    # and identifiers out while still catching real key material.
    (re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}"), REDACTED_SECRET),
    # UNC share, then drive-letter path, then POSIX home paths. The
    # drive-letter rule cannot match a URL scheme: there is no word boundary
    # before the "s" in "https:".
    (re.compile(r"\\\\[^\s\"'<>|]+"), REDACTED_PATH),
    (re.compile(r"\b[A-Za-z]:[\\/][^\s\"'<>|]*"), REDACTED_PATH),
    (re.compile(r"/(?:home|Users|root)/[^\s\"'<>|]*"), REDACTED_PATH),
    (
        re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
        REDACTED_EMAIL,
    ),
)


def redact(value: Any, *, max_chars: int = NOTE_MAX_CHARS) -> str:
    """Scrub shaped secrets, paths, and emails from a short note.

    A value that is not exactly built-in ``str`` becomes ``""`` without any
    conversion or representation hook running on it.

    Truncation happens **before** matching, and cuts back to the last
    whitespace when it lands mid-token. Truncating afterwards could leave the
    unmatched prefix of a secret behind - ``sk-ab`` is too short for the
    prefix rule to fire - so the order is deliberate and the trailing partial
    token is discarded rather than kept.
    """
    if type(value) is not str:
        return ""
    bound = max_chars if type(max_chars) is int and max_chars >= 0 else NOTE_MAX_CHARS
    text = value
    if len(text) > bound:
        text = text[:bound]
        cut = text.rfind(" ")
        text = text[:cut] if cut > 0 else ""
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text


def describe_size(value: Any) -> str:
    """The only sanctioned way to reference model-facing text in a diagnostic.

    Returns a size, never content: ``"chars=1234"`` for an exact ``str``, and
    ``"chars=unknown"`` for anything else - including objects whose ``__len__``
    might lie or raise, which is why the length is read only from an exact
    built-in ``str``.
    """
    if type(value) is str:
        return "chars=" + str(len(value))
    return "chars=unknown"


@dataclass(frozen=True)
class DiagnosticRecord:
    """One operator-facing diagnostic line. No prompt field exists, by design.

    ``event`` and ``reasons`` come from this package's closed vocabularies and
    are safe to log verbatim. ``backend`` is an operator-authored allowlist
    name. ``note`` is the one free-text field and is redacted and bounded at
    construction, so an unredacted note cannot exist even transiently on a
    constructed record.
    """

    event: str
    backend: str = ""
    reasons: tuple[str, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "event", self.event[:64] if type(self.event) is str else "")
        set_(self, "backend", self.backend[:128] if type(self.backend) is str else "")
        if type(self.reasons) is tuple or type(self.reasons) is list:
            set_(
                self,
                "reasons",
                tuple(r for r in self.reasons if type(r) is str)[:32],
            )
        else:
            set_(self, "reasons", ())
        set_(self, "note", redact(self.note))


__all__ = [
    "DiagnosticRecord",
    "NOTE_MAX_CHARS",
    "REDACTED_EMAIL",
    "REDACTED_PATH",
    "REDACTED_SECRET",
    "describe_size",
    "redact",
]
