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
  ``NaN``, a duplicated key, or a nesting depth that exhausts the parser
  stack all produce a *result* carrying a stable failure code.

- **Non-disclosing.** A failure result never contains the payload, an excerpt
  of it, a character offset into it, or a parser message derived from it.
  Only a fixed code, and - on a missing-key failure - the caller's own
  required key names, which came from the caller and not from the model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Literal, Mapping, Optional


StructuredFailure = Literal[
    "payload-not-exact-str",
    "payload-too-large",
    "invalid-json",
    "non-finite-number",
    "duplicate-key",
    "not-json-object",
    "missing-required-key",
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
    """Raised by the ``parse_constant`` hook for NaN / Infinity / -Infinity."""


class _DuplicateKey(ValueError):
    """Raised by the ``object_pairs_hook`` when an object repeats a key."""


def _reject_constant(_token: str) -> Any:
    """``json.loads`` calls this for NaN / Infinity / -Infinity.

    Python's decoder accepts those by default, which is valid JavaScript but
    not valid JSON and not something a downstream consumer should silently
    receive. The token itself is discarded rather than reported.
    """
    raise _NonFiniteNumber("non-finite")


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
    missing_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.ok and self.failure is not None:
            raise ValueError("a successful outcome cannot carry a failure code")
        if not self.ok and self.failure is None:
            raise ValueError("a failed outcome must carry a failure code")
        if not self.ok and self.value is not None:
            raise ValueError("a failed outcome must not carry a value")


def _normalized_required_keys(value: Any) -> tuple[str, ...]:
    """Keep only exact-``str`` key names, de-duplicated, order preserved."""
    if type(value) is not tuple and type(value) is not list:
        return ()
    kept: list[str] = []
    for element in value:
        if len(kept) >= _MAX_REQUIRED_KEYS:
            break
        if type(element) is not str or not element:
            continue
        sliced = element[:_KEY_MAX_LEN]
        if sliced in kept:
            continue
        kept.append(sliced)
    return tuple(kept)


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
       from the decoder. ``RecursionError`` from a deeply nested payload is
       folded into ``invalid-json`` rather than escaping.
    4. ``not-json-object``        - valid JSON, but an array, string, number,
       boolean, or null at the top level.
    5. ``missing-required-key``   - with the caller's own missing key names.
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
    missing = tuple(key for key in wanted if key not in parsed)
    if missing:
        return StructuredOutcome(
            ok=False, failure="missing-required-key", missing_keys=missing
        )

    return StructuredOutcome(ok=True, value=MappingProxyType(parsed))


__all__ = [
    "DEFAULT_MAX_CHARS",
    "StructuredFailure",
    "StructuredOutcome",
    "validate_structured_output",
]
