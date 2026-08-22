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


SAFE_TOKEN_MAX_LEN: Final[int] = 64
SAFE_REFERENCE_MAX_LEN: Final[int] = 160

INVALID_IDENTIFIER: Final[str] = "invalid-identifier"
"""Fixed stand-in for a rejected identifier. Carries none of the input."""

_SAFE_TOKEN: Final[Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
"""Short identifiers: case ids, backend names, JSON key names.

Excludes whitespace, quotes, control characters, ``/``, ``:`` and ``@``, so a
filesystem path, a URL, an email address, or a sentence of prose cannot be
smuggled through one of these fields.
"""

_SAFE_REFERENCE: Final[Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]*$")
"""Longer references: model ids, variant ids, revisions.

Necessarily admits ``/`` and ``:`` because model ids look like
``org/model-name``. The redaction cross-check below is what keeps a
drive-letter path such as ``C:/Users/...`` out of these fields.
"""


def is_safe_token(value: Any, *, max_len: int = SAFE_TOKEN_MAX_LEN) -> bool:
    """True only for a short, bounded, non-secret-shaped identifier.

    Three independent conditions, all required:

    1. exactly built-in ``str``, non-empty, within ``max_len``;
    2. matches the closed ``_SAFE_TOKEN`` character class;
    3. **survives ``redact`` unchanged.**

    Condition 3 is the one that matters. The character class alone would
    admit ``sk-ABCDEFGH12345678`` - it is all letters, digits and hyphens -
    so every candidate identifier is additionally run through the secret
    matcher and rejected if redaction would have altered it. An identifier
    that trips any secret pattern is refused rather than stored.
    """
    if type(value) is not str:
        return False
    if not value or len(value) > max_len:
        return False
    if _SAFE_TOKEN.match(value) is None:
        return False
    return redact(value, max_chars=max_len) == value


def is_safe_reference(value: Any, *, max_len: int = SAFE_REFERENCE_MAX_LEN) -> bool:
    """True only for a bounded, non-secret-shaped model/variant/revision id.

    Same three conditions as ``is_safe_token`` against the wider
    ``_SAFE_REFERENCE`` class. The redaction cross-check still rejects
    drive-letter and POSIX home paths, which the wider class would otherwise
    admit.
    """
    if type(value) is not str:
        return False
    if not value or len(value) > max_len:
        return False
    if _SAFE_REFERENCE.match(value) is None:
        return False
    return redact(value, max_chars=max_len) == value


_HEX_DIGITS: Final[frozenset[str]] = frozenset("0123456789abcdef")


def is_commit_revision(value: Any) -> bool:
    """True for a full lowercase hex commit id: 40 (SHA-1) or 64 (SHA-256).

    Exists because ``is_safe_reference`` alone **rejects** an ordinary git
    SHA. The long-opaque-run secret rule matches any 40+ character run of
    letters and digits, and a 40-character hex commit id is exactly that -
    so the generic identifier gate mistook every real repository revision for
    a credential. That was a defect, not a safety property: refusing to
    record the one value that makes a claim reproducible is strictly worse
    than recording it.

    The exemption is deliberately narrow. Only lowercase hex, only at exactly
    40 or 64 characters, checked digit by digit. That is a far smaller class
    than "any long opaque string", and it is the class of values that
    identify an immutable commit.
    """
    if type(value) is not str:
        return False
    if len(value) not in (40, 64):
        return False
    for character in value:
        if character not in _HEX_DIGITS:
            return False
    return True


def is_safe_revision(value: Any) -> bool:
    """True for a full commit id, or for a tag/branch-shaped safe reference."""
    return is_commit_revision(value) or is_safe_reference(value)


def safe_token_or(value: Any, fallback: str = INVALID_IDENTIFIER) -> str:
    """``value`` when it is a safe token, else the fixed ``fallback``."""
    if is_safe_token(value):
        return value
    return fallback


DIAGNOSTIC_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "route-selected",
        "route-refused",
        "registration-refused",
        "construction-refused",
        "structured-output-refused",
        "evaluation-completed",
        "invalid-event",
    }
)
"""Closed vocabulary for ``DiagnosticRecord.event``.

A record cannot carry an event string that is not one of these, so the field
has no capacity to hold arbitrary text at all.
"""

REGISTRATION_REFUSAL_REASONS: Final[frozenset[str]] = frozenset(
    {
        "name-not-safe-token",
        "name-not-allowlisted",
        "name-already-registered",
        "capabilities-not-exact-type",
        "capabilities-missing-model-id",
        "factory-not-callable",
        "locality-attestation-required",
        "locality-attestation-not-applicable",
        "invalid-reason",
    }
)
"""Closed vocabulary for ``RegistrationRefused.reason``."""

CONSTRUCTION_REFUSAL_REASONS: Final[frozenset[str]] = frozenset(
    {
        "name-not-registered",
        "availability-not-present",
        "factory-returned-wrong-type",
        "locality-mismatch-detected",
        "invalid-reason",
    }
)
"""Closed vocabulary for ``BackendUnavailable.reason``.

Closed rather than free-text because an **operator-written factory** can
raise ``BackendUnavailable`` itself, and the evaluation harness persists that
reason into a record. Without a closed set, a factory could write arbitrary
text - a credential, a path, a prompt fragment - straight into stored
evidence. Anything outside this set becomes ``"invalid-reason"``, and the
supplied value is not retained anywhere, including in the exception message.
"""

ESCALATION_REASONS: Final[frozenset[str]] = frozenset(
    {
        "no-backend-registered",
        "requirements-invalid",
        "artifact-unpinned",
        "model-id-missing",
        "backend-unavailable",
        "availability-unknown",
        "locality-not-local",
        "locality-unknown",
        "structured-output-unsupported",
        "structured-output-unknown",
        "tool-calling-unsupported",
        "tool-calling-unknown",
        "context-below-minimum",
        "context-unknown",
        "licence-not-allowed",
        "licence-unknown",
        "licence-source-unpinned",
        "runtime-not-allowed",
        "runtime-unknown",
        "variant-unspecified",
        "repository-revision-unpinned",
        "artifact-digest-missing",
    }
)
"""Closed vocabulary for every escalation reason this package emits.

Held here, in the disclosure-control module, rather than in ``routing``,
because every component that stores or reports a reason must agree on the
same closed set - and because a record must be able to reject a
non-vocabulary reason without importing the routing layer.
``scripts.open_model.routing.EscalationReason`` mirrors this set, and
``tests/test_open_model_routing.py`` asserts the two stay identical.
"""


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

    Every field is closed or bounded at construction, so an unredacted or
    arbitrary value cannot exist on a constructed record even transiently:

    - ``event``    must be a member of ``DIAGNOSTIC_EVENTS``; anything else
      becomes the literal ``"invalid-event"``. The field therefore has no
      capacity to hold arbitrary text at all.
    - ``backend``  must be a safe token - bounded, closed character class,
      and unchanged by ``redact`` - else it becomes ``INVALID_IDENTIFIER``.
      A path, URL, email, bearer string, or provider-prefixed key is refused
      rather than stored.
    - ``reasons``  keeps only members of ``ESCALATION_REASONS``, in order,
      capped; non-members are dropped rather than truncated, so a dropped
      value leaves no fragment behind.
    - ``note``     is the single free-text field: redacted and bounded.

    Corrected after audit: the previous version bounded these fields by
    slicing only, which meant ``event``, ``backend`` and ``reasons`` could
    each retain up to 64-128 characters of arbitrary caller text.
    """

    event: str
    backend: str = ""
    reasons: tuple[str, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        if type(self.event) is str and self.event in DIAGNOSTIC_EVENTS:
            set_(self, "event", self.event)
        else:
            set_(self, "event", "invalid-event")
        # Exact-type check first: a bare `if not self.backend` would run a
        # hostile __bool__ before we ever reached the identifier gate.
        if type(self.backend) is str and not self.backend:
            set_(self, "backend", "")
        else:
            set_(self, "backend", safe_token_or(self.backend))
        if type(self.reasons) is tuple or type(self.reasons) is list:
            kept: list[str] = []
            for reason in self.reasons:
                if len(kept) >= 32:
                    break
                if type(reason) is str and reason in ESCALATION_REASONS:
                    kept.append(reason)
            set_(self, "reasons", tuple(kept))
        else:
            set_(self, "reasons", ())
        set_(self, "note", redact(self.note))


__all__ = [
    "DIAGNOSTIC_EVENTS",
    "CONSTRUCTION_REFUSAL_REASONS",
    "ESCALATION_REASONS",
    "INVALID_IDENTIFIER",
    "REGISTRATION_REFUSAL_REASONS",
    "DiagnosticRecord",
    "NOTE_MAX_CHARS",
    "REDACTED_EMAIL",
    "REDACTED_PATH",
    "REDACTED_SECRET",
    "SAFE_REFERENCE_MAX_LEN",
    "SAFE_TOKEN_MAX_LEN",
    "describe_size",
    "is_safe_reference",
    "is_safe_token",
    "redact",
    "safe_token_or",
]
