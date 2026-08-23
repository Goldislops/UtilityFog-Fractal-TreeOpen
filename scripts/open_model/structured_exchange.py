"""OMI-V2 - one structured exchange: ask a runtime, then check what came back.

This module is the join between the two halves of OMI-V2, and it exists at
this layer because of the direction the imports are allowed to run.

``scripts/agent_backends/openai_compat_backend.py`` builds and sends the
request. It cannot validate the response, because the validator lives in
``scripts/open_model/structured.py`` and this package imports the backend
package, never the reverse (see ``scripts/open_model/__init__.py``). Reaching
up from the backend to borrow the validator would invert that layering.

So the backend returns what it received, and the checking happens here,
against the **existing** validator, unchanged. No second validator was
written. The request-side checks in
``scripts/agent_backends/structured_request.py`` are not a competing
implementation: they walk an outbound JSON Schema document that is about to
be serialised, whereas ``validate_structured_output`` parses an inbound
response payload string that a model produced. Opposite directions, different
artifacts, no shared decision.

## Why the check is not optional

Emitting ``response_format`` asks for constrained decoding; it does not
establish that any constraint was applied. Ollama's handler at the pinned
revision leaves decoding unconstrained - with no error - when the request
type is unrecognised or the ``json_schema`` nesting is absent. A caller that
treated a successful HTTP round-trip as proof of conformance would be wrong
in exactly that case, and would have no way to notice.

``request_structured_json`` therefore reports success only when a response
actually parsed as a JSON object carrying every required key. The two failure
vocabularies are kept separate rather than merged, because "the runtime was
never asked" and "the runtime was asked and answered badly" are different
facts about a system and an operator needs to tell them apart.

## What success here does NOT mean

Success means *usable*, not *conformant*. ``validate_structured_output``
checks JSON-object syntax and the presence of required keys. It does not
compare the payload against the schema that was sent, because this package
carries no JSON Schema implementation and will not hand-roll one.

The gap is concrete: against a schema demanding a boolean ``ok`` and no
additional properties, the payload ``{"ok": "wrong type", "extra": 123}``
passes - wrong type, extra key, still ``ok=True``. An earlier revision of
this package described that check as establishing conformance, which was
false.

:class:`StructuredExchange` therefore carries a ``schema_conformance`` field
whose only permitted value is ``"unverified"``. It is closed to that single
token so the limit is visible in the result itself rather than only in prose,
and so any future real conformance check has to widen the vocabulary
deliberately.

## Nothing is persisted and nothing is disclosed

This module writes no file, opens no socket, and touches no evaluation or
routing record. Its result carries a parsed value on success and closed
tokens on failure - never a prompt, a schema fragment, a key name, a raw
response, an offset, or an exception text. That property is inherited rather
than reimplemented: ``StructuredOutcome`` already guarantees it for the
response side, and ``StructuredRefusal`` already guarantees it for the
request side.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Literal, Mapping, Optional, Union, get_args

from scripts.agent_backends.base import Message, ToolSpec
from scripts.agent_backends.openai_compat_backend import StructuredCompletion
from scripts.agent_backends.structured_request import (
    REFUSAL_TOKENS,
    StructuredRefusal,
    is_supported_dialect,
)
from scripts.open_model.structured import (
    DEFAULT_MAX_CHARS,
    StructuredFailure,
    StructuredOutcome,
    validate_structured_output,
)


ExchangeRefusal = Union[
    Literal["backend-not-structured-capable"], StructuredRefusal
]
"""Why the request never reached a runtime.

Composed from :data:`StructuredRefusal` rather than restated, so the backend's
closed vocabulary cannot drift out of step with this one. The single extra
token covers a backend that does not implement the OMI-V2 method at all, or
returns something other than a ``StructuredCompletion`` from it.
"""


EXCHANGE_REFUSALS: Final[frozenset[str]] = REFUSAL_TOKENS | frozenset(
    ("backend-not-structured-capable",)
)
"""Runtime mirror of :data:`ExchangeRefusal`, composed the same way it is.

On the trust path: :class:`StructuredExchange` rejects anything outside it.
Built from the backend's own set rather than restated, so the two cannot
drift apart.
"""

RESPONSE_FAILURES: Final[frozenset[str]] = frozenset(get_args(StructuredFailure))
"""Runtime mirror of the validator's closed failure vocabulary."""


@dataclass(frozen=True)
class StructuredExchange:
    """Outcome of one ask-and-check round trip.

    Exactly one of three states, distinguishable without inspecting content:

    - **ok** - a request was sent and the response parsed as a JSON object
      carrying every required key. ``value`` is a read-only view of it. This
      is *usability*, not schema conformance - see ``schema_conformance``.
    - **refused** - no request was sent. ``request_refusal`` says why.
      ``response_format_sent`` is False.
    - **unusable** - a request was sent and the answer did not validate.
      ``response_failure`` says why. ``response_format_sent`` is True.

    The middle and last states are deliberately not collapsed into one
    "failed" state: an operator who cannot tell a rejected configuration from
    a badly behaved runtime cannot act on either.
    """

    ok: bool
    value: Optional[Mapping[str, Any]] = None
    request_refusal: Optional[ExchangeRefusal] = None
    response_failure: Optional[StructuredFailure] = None
    missing_key_indices: tuple[int, ...] = ()
    dialect: Optional[str] = None
    response_format_sent: bool = False
    schema_conformance: Literal["unverified"] = "unverified"
    """Always ``"unverified"``. Closed to that one token on purpose.

    Nothing in this package checks a response against the schema that was
    sent. ``ok=True`` means the payload parsed as a JSON object and carried
    every required key - usability, not conformance. ``{"ok": "wrong type",
    "extra": 123}`` satisfies it against a schema demanding a boolean ``ok``
    and no additional properties.

    Carrying the limit as a field rather than only as prose means a caller
    reading the result cannot miss it, and a future conformance check cannot
    arrive silently: it has to widen this vocabulary, in the open.
    """

    def __post_init__(self) -> None:
        # Exact bools first: a foreign object with a __bool__ must not be able
        # to walk itself through the state machine below.
        if type(self.ok) is not bool:
            raise ValueError("ok must be exactly a bool")
        if type(self.response_format_sent) is not bool:
            raise ValueError("response_format_sent must be exactly a bool")
        if (
            type(self.schema_conformance) is not str
            or self.schema_conformance != "unverified"
        ):
            raise ValueError(
                "schema conformance is never established by this package"
            )
        if self.request_refusal is not None and (
            type(self.request_refusal) is not str
            or self.request_refusal not in EXCHANGE_REFUSALS
        ):
            raise ValueError(
                "request_refusal must be a token from the closed vocabulary"
            )
        if self.response_failure is not None and (
            type(self.response_failure) is not str
            or self.response_failure not in RESPONSE_FAILURES
        ):
            raise ValueError(
                "response_failure must be a token from the closed vocabulary"
            )
        if self.dialect is not None and not is_supported_dialect(self.dialect):
            raise ValueError("dialect must be a verified dialect token or None")
        # Missing indices are coherent or absent: exact ints, non-negative,
        # strictly increasing, and only ever present on the one failure that
        # produces them. An arbitrary tuple here would be a place to smuggle
        # content past the closed vocabularies.
        if type(self.missing_key_indices) is not tuple:
            raise ValueError("missing_key_indices must be exactly a tuple")
        if self.missing_key_indices:
            if self.response_failure != "missing-required-key":
                raise ValueError(
                    "missing_key_indices belong only to a missing-required-key "
                    "failure"
                )
            previous = -1
            for index in self.missing_key_indices:
                if type(index) is not int or index <= previous:
                    raise ValueError(
                        "missing_key_indices must be increasing non-negative ints"
                    )
                previous = index
        elif self.response_failure == "missing-required-key":
            raise ValueError(
                "a missing-required-key failure must report which indices"
            )
        if self.ok:
            if self.request_refusal is not None or self.response_failure is not None:
                raise ValueError("a successful exchange cannot carry a failure")
            if self.value is None:
                raise ValueError("a successful exchange must carry a value")
            # Exact types, not merely non-None. `value` was the last field in
            # this class open to an arbitrary object, which made it the one
            # place a caller string - a secret among them - could ride into a
            # result that every other field is closed against. It is also a
            # correctness promise: a caller reading `.value` on ok=True is
            # entitled to a mapping, and `dict(result.value)` on a str raises.
            # The successful path always supplies the validator's
            # MappingProxyType; an exact dict is accepted so a caller can
            # construct one directly.
            if (
                type(self.value) is not MappingProxyType
                and type(self.value) is not dict
            ):
                raise ValueError(
                    "a successful exchange must carry an exact mapping value"
                )
            if not self.response_format_sent:
                raise ValueError("a successful exchange must have sent a request")
        else:
            if self.value is not None:
                raise ValueError("a failed exchange must not carry a value")
            if (self.request_refusal is None) == (self.response_failure is None):
                raise ValueError(
                    "a failed exchange carries exactly one of a request refusal "
                    "or a response failure"
                )
            if self.request_refusal is not None and self.response_format_sent:
                raise ValueError("a refused exchange cannot have sent a request")
            if self.response_failure is not None and not self.response_format_sent:
                raise ValueError(
                    "a response failure requires that a request was sent"
                )


def request_structured_json(
    backend: Any,
    messages: list[Message],
    tools: list[ToolSpec],
    *,
    structured: Any,
    required_keys: tuple[str, ...] = (),
    max_chars: int = DEFAULT_MAX_CHARS,
    system: Optional[str] = None,
    max_tokens: int = 2048,
    temperature: float = 0.0,
) -> StructuredExchange:
    """Ask ``backend`` for schema-constrained JSON, then validate the answer.

    Returns a :class:`StructuredExchange` for every reachable input. Transport
    errors raised by the underlying SDK propagate, matching ``complete()``.

    ``backend`` is accepted as ``Any`` and checked structurally, so this
    function works with any backend exposing the OMI-V2 method and refuses
    cleanly for one that does not - ``MockBackend`` and ``AnthropicBackend``
    are out of scope for OMI-V2 and land on
    ``backend-not-structured-capable`` rather than on an ``AttributeError``.

    ``required_keys`` and ``max_chars`` are handed to
    ``validate_structured_output`` unchanged; their semantics, including the
    refusal of an unsafe required key and the index-not-text reporting of a
    missing one, are that function's and are not restated here.
    """
    method = getattr(backend, "complete_structured", None)
    if not callable(method):
        return StructuredExchange(
            ok=False, request_refusal="backend-not-structured-capable"
        )

    completion = method(
        messages,
        tools,
        structured=structured,
        system=system,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    # Exact type, not duck typing: a foreign object reaching the branches
    # below could otherwise supply its own `ok` and be believed.
    if type(completion) is not StructuredCompletion:
        return StructuredExchange(
            ok=False, request_refusal="backend-not-structured-capable"
        )

    if not completion.ok:
        return StructuredExchange(
            ok=False,
            request_refusal=completion.refusal,
            dialect=completion.dialect,
            response_format_sent=False,
        )

    response = completion.response
    # `text` is None when the model returned no text block at all; passing it
    # through unchanged is correct - the validator is total over any input and
    # reports `payload-not-exact-str`, which is the accurate description.
    payload = response.text if response is not None else None
    outcome: StructuredOutcome = validate_structured_output(
        payload, required_keys=required_keys, max_chars=max_chars
    )
    if not outcome.ok:
        return StructuredExchange(
            ok=False,
            response_failure=outcome.failure,
            missing_key_indices=outcome.missing_key_indices,
            dialect=completion.dialect,
            response_format_sent=True,
        )

    return StructuredExchange(
        ok=True,
        value=outcome.value,
        dialect=completion.dialect,
        response_format_sent=True,
    )


__all__ = [
    "EXCHANGE_REFUSALS",
    "RESPONSE_FAILURES",
    "ExchangeRefusal",
    "StructuredExchange",
    "request_structured_json",
]
