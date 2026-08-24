"""OMI-V1 - total validation of a model's structured output.

Constrained decoding is a property of the serving *runtime* (llama.cpp GBNF
and ``json_schema``, vLLM ``structured_outputs``, SGLang grammar backends),
and every one of those spells it differently. A provider-neutral layer
therefore cannot assume a well-formed object ever arrives: it must be able to
receive whatever the model actually emitted and decide, without raising and
without disclosing, whether it is usable.

This module is that decision. It is deliberately small and dependency-free -
``jsonschema`` is not installed in this repository's environment and is not
worth adding for a required-key check.

Two properties matter to an auditor:

- **Total.** ``validate_structured_output`` never raises for any input of any
  type. Malformed JSON, a non-object top level, a hostile object passed in
  place of a string, a payload large enough to be a denial-of-service, a
  ``NaN``, a numeric literal that overflows ``float`` into an infinity, a
  duplicated key, or a nesting depth that exhausts the parser stack all
  produce a *result* carrying a stable failure code.

- **Non-disclosing.** A failure result never contains the payload, an excerpt
  of it, a character offset into it, or a parser message derived from it -
  and, after audit, never any key *text* either. A missing-key failure
  reports **indices** into the caller's own ``required_keys`` tuple, which is
  exactly as informative to the caller (who holds that tuple) and carries
  nothing to anyone reading a log. Required keys must additionally be safe
  tokens, so a sensitive schema key is refused at the door rather than
  processed.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Literal, Mapping, Optional

from scripts.open_model.redaction import is_safe_token


StructuredFailure = Literal[
    "payload-not-exact-str",
    "payload-too-large",
    "invalid-json",
    "non-finite-number",
    "duplicate-key",
    "not-json-object",
    "missing-required-key",
    "required-key-not-safe",
]
"""Why a payload was refused. The complete vocabulary; safe to log verbatim."""

DEFAULT_MAX_CHARS: Final[int] = 65536
"""Refuse before parsing beyond this many characters.

Checked against the string length rather than an encoded byte length so the
guard itself cannot be made expensive by a hostile payload.
"""

_KEY_MAX_LEN: Final[int] = 128
_MAX_REQUIRED_KEYS: Final[int] = 64


class _NonFiniteNumber(ValueError):
    """Raised for any number that is not finite, however it was spelled.

    Two decoder hooks raise it: ``_reject_constant`` for the ``NaN`` /
    ``Infinity`` / ``-Infinity`` tokens, and ``_finite_float`` for a numeric
    literal such as ``1e400`` that overflows ``float`` into an infinity.
    """


class _DuplicateKey(ValueError):
    """Raised by the ``object_pairs_hook`` when an object repeats a key."""


def _reject_constant(_token: str) -> Any:
    """``json.loads`` calls this for NaN / Infinity / -Infinity.

    Python's decoder accepts those by default, which is valid JavaScript but
    not valid JSON and not something a downstream consumer should silently
    receive. The token itself is discarded rather than reported.

    This hook sees the three constant tokens and nothing else. The overflow
    spellings of the same values - ``1e400`` and kin - are numeric literals,
    which the decoder routes through ``_finite_float`` below.
    """
    raise _NonFiniteNumber("non-finite")


def _finite_float(token: str) -> float:
    """``json.loads`` calls this for every number that is not an integer.

    Python's decoder builds floats with ``float(token)``, which maps an
    overflowing literal such as ``1e400`` or ``-1e309`` to an infinity rather
    than raising. Audit reproduced exactly that: the constant-token hook above
    never fires for those spellings, so a non-finite number reached a
    *successful* outcome - and OMI-V2's success carrier - despite
    ``non-finite-number`` sitting in the refusal vocabulary. The finiteness
    decision therefore has to be made here, where the number is built.

    The guard is written against non-finiteness itself, not against a list of
    spellings, so it cannot be bypassed by an exponent this module never
    anticipated. An underflow such as ``1e-400`` rounds to ``0.0``, which is
    finite and accepted unchanged. The token is discarded, not reported.
    """
    value = float(token)
    if not math.isfinite(value):
        raise _NonFiniteNumber("non-finite")
    return value


def _pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build objects while refusing duplicate keys.

    Python's decoder keeps the last occurrence of a repeated key, so
    ``{"ok": false, "ok": true}`` would silently read as ``true``. That is a
    real ambiguity in a model's output, not a curiosity, so it is refused.
    """
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise _DuplicateKey("duplicate")
        seen[key] = value
    return seen


@dataclass(frozen=True)
class StructuredOutcome:
    """Result of validating one payload. Never carries payload content on failure.

    ``value`` is a read-only view of the parsed object. The proxy is shallow -
    nested containers reached through it are ordinary mutable objects - so it
    prevents accidental top-level mutation of a shared result rather than
    claiming deep immutability.
    """

    ok: bool
    value: Optional[Mapping[str, Any]] = None
    failure: Optional[StructuredFailure] = None
    missing_key_indices: tuple[int, ...] = ()
    """Positions in the caller's ``required_keys`` that were absent.

    Indices, not names. Corrected after audit: the previous version returned
    the missing key *text*, which meant a caller who passed a sensitive
    schema key had it copied into a result, a record, and any log built from
    one. The caller already holds the tuple it supplied, so an index is
    exactly as informative to them and carries nothing to anyone else.
    """

    def __post_init__(self) -> None:
        if self.ok and self.failure is not None:
            raise ValueError("a successful outcome cannot carry a failure code")
        if not self.ok and self.failure is None:
            raise ValueError("a failed outcome must carry a failure code")
        if not self.ok and self.value is not None:
            raise ValueError("a failed outcome must not carry a value")


def _normalized_required_keys(value: Any) -> Optional[tuple[str, ...]]:
    """Validate the caller's required-key tuple, or ``None`` to fail closed.

    Returns ``None`` - meaning *refuse the whole validation* - when the shape
    is wrong, the tuple is over-long, or **any** element is not a safe token.

    Refusing rather than dropping is the point. The previous version silently
    discarded a key it could not accept, which made
    ``validate_structured_output`` report success for a payload that had
    never been checked against that key: a malformed schema turned into a
    false pass. A key this layer will not handle now stops the validation
    instead of quietly shrinking it.
    """
    if type(value) is not tuple and type(value) is not list:
        return None
    if len(value) > _MAX_REQUIRED_KEYS:
        return None
    # Order and length are preserved exactly - no de-duplication - so a
    # reported index maps one-to-one onto the tuple the caller passed in.
    for element in value:
        if not is_safe_token(element, max_len=_KEY_MAX_LEN):
            return None
    return tuple(value)


def validate_structured_output(
    payload: Any,
    *,
    required_keys: tuple[str, ...] = (),
    max_chars: int = DEFAULT_MAX_CHARS,
) -> StructuredOutcome:
    """Decide whether ``payload`` is a usable structured response.

    Returns a ``StructuredOutcome`` for every input; never raises.

    The checks run in this order, and the first failure wins because later
    checks are not meaningful once an earlier one has failed:

    1. ``payload-not-exact-str``  - not exactly built-in ``str``. Checked by
       type identity, so a ``str`` subclass with an overridden ``__len__`` or
       ``__getitem__`` cannot influence the size guard below.
    2. ``payload-too-large``      - refused before parsing.
    3. ``non-finite-number`` / ``duplicate-key`` / ``invalid-json`` - raised
       from the decoder. ``non-finite-number`` covers both spellings of a
       non-finite number: the ``NaN`` / ``Infinity`` / ``-Infinity`` tokens
       and a numeric literal such as ``1e400`` that overflows ``float`` into
       an infinity, at any nesting depth. Because these are decoder failures,
       they precede check 4: a bare ``1e400`` reports ``non-finite-number``,
       exactly as a bare ``Infinity`` always did, while a bare finite number
       still reports ``not-json-object``. ``RecursionError`` from a deeply
       nested payload is folded into ``invalid-json`` rather than escaping.
    4. ``not-json-object``        - valid JSON, but an array, string, number,
       boolean, or null at the top level.
    5. ``required-key-not-safe``  - the caller's ``required_keys`` was the
       wrong shape, over-long, or contained an element that is not a safe
       token. The whole validation is refused; keys are never silently
       dropped, because dropping one would report success for a payload that
       was never checked against it.
    6. ``missing-required-key``   - reported as **indices** into the caller's
       ``required_keys``, never as key text.
    """
    if type(payload) is not str:
        return StructuredOutcome(ok=False, failure="payload-not-exact-str")

    bound = max_chars if type(max_chars) is int and max_chars >= 0 else DEFAULT_MAX_CHARS
    if len(payload) > bound:
        return StructuredOutcome(ok=False, failure="payload-too-large")

    try:
        parsed = json.loads(
            payload,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
            object_pairs_hook=_pairs_hook,
        )
    except _NonFiniteNumber:
        return StructuredOutcome(ok=False, failure="non-finite-number")
    except _DuplicateKey:
        return StructuredOutcome(ok=False, failure="duplicate-key")
    except (ValueError, RecursionError):
        # ValueError covers json.JSONDecodeError. Neither the exception text
        # nor its offset is propagated: both are derived from the payload.
        return StructuredOutcome(ok=False, failure="invalid-json")

    if type(parsed) is not dict:
        return StructuredOutcome(ok=False, failure="not-json-object")

    wanted = _normalized_required_keys(required_keys)
    if wanted is None:
        return StructuredOutcome(ok=False, failure="required-key-not-safe")
    missing = tuple(
        index for index, key in enumerate(wanted) if key not in parsed
    )
    if missing:
        return StructuredOutcome(
            ok=False,
            failure="missing-required-key",
            missing_key_indices=missing,
        )

    return StructuredOutcome(ok=True, value=MappingProxyType(parsed))


__all__ = [
    "DEFAULT_MAX_CHARS",
    "StructuredFailure",
    "StructuredOutcome",
    "validate_structured_output",
]
