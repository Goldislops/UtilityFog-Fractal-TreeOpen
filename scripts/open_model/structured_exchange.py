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
    is_pre_dialect_refusal,
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
      carrying every required key. This is *usability*, not schema
      conformance - see ``schema_conformance``.

      ``value`` is supplied as an **exact ``dict``** and stored as a
      genuinely read-only view over a fresh top-level copy, so a caller who
      kept a reference to the dict they passed in cannot reach through it and
      change what the result reports.

      An exact ``MappingProxyType`` is **refused**, which is narrower than it
      first appears to need to be and is deliberate. A proxy is an exact type
      that can wrap an *arbitrary foreign mapping*, and copying one runs that
      mapping's ``keys``/``__getitem__``/``__iter__``. An earlier revision
      accepted a proxy and copied it, so a hostile mapping wrapped in one
      raised caller-supplied text straight out of this constructor - a public
      carrier-construction path executing foreign hooks. There is no
      hook-free way to inspect what a proxy wraps, so the accepted type is
      narrowed instead of inspected. ``request_structured_json`` adapts the
      validator's proxy on the trusted internal path before it gets here.

      The stored proxy is **shallow**, exactly as ``StructuredOutcome.value``
      is - nested containers reached through it are ordinary mutable objects.
      It prevents top-level mutation of a shared result; it does not claim
      deep immutability.
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

    def __post_init__(
        self,
        _refusals: frozenset = EXCHANGE_REFUSALS,
        _failures: frozenset = RESPONSE_FAILURES,
        _dialect_ok=is_supported_dialect,
        _pre_dialect=is_pre_dialect_refusal,
        _proxy=MappingProxyType,
        _type=type,
        _str=str,
        _bool=bool,
        _int=int,
        _dict=dict,
        _tuple=tuple,
        _object=object,
    ) -> None:
        """Validate the carrier's own coherence.

        The defaulted parameters capture OBJECTS at class-definition time. A
        dataclass calls ``self.__post_init__()`` with no arguments, so none of
        them is ever looked up again. Rebinding ``EXCHANGE_REFUSALS``,
        ``RESPONSE_FAILURES`` or this module's imported ``is_supported_dialect``
        alias therefore cannot widen what an exchange will accept - which
        reading them as globals did allow, including admitting arbitrary
        secret-shaped refusal, failure, or dialect text into a result.
        """
        # Exact bools first: a foreign object with a __bool__ must not be able
        # to walk itself through the state machine below.
        if _type(self.ok) is not _bool:
            raise ValueError("ok must be exactly a bool")
        if _type(self.response_format_sent) is not _bool:
            raise ValueError("response_format_sent must be exactly a bool")
        if (
            _type(self.schema_conformance) is not _str
            or self.schema_conformance != "unverified"
        ):
            raise ValueError(
                "schema conformance is never established by this package"
            )
        if self.request_refusal is not None and (
            _type(self.request_refusal) is not _str
            or self.request_refusal not in _refusals
        ):
            raise ValueError(
                "request_refusal must be a token from the closed vocabulary"
            )
        if self.response_failure is not None and (
            _type(self.response_failure) is not _str
            or self.response_failure not in _failures
        ):
            raise ValueError(
                "response_failure must be a token from the closed vocabulary"
            )
        if self.dialect is not None and not _dialect_ok(self.dialect):
            raise ValueError("dialect must be a verified dialect token or None")
        # Missing indices are coherent or absent: exact ints, non-negative,
        # strictly increasing, and only ever present on the one failure that
        # produces them. An arbitrary tuple here would be a place to smuggle
        # content past the closed vocabularies.
        if _type(self.missing_key_indices) is not _tuple:
            raise ValueError("missing_key_indices must be exactly a tuple")
        if self.missing_key_indices:
            if self.response_failure != "missing-required-key":
                raise ValueError(
                    "missing_key_indices belong only to a missing-required-key "
                    "failure"
                )
            previous = -1
            for index in self.missing_key_indices:
                if _type(index) is not _int or index <= previous:
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
            # result that every other field is closed against.
            #
            # The class docstring calls this a read-only view, so it is made
            # one rather than merely described as one. An exact dict or an
            # exact MappingProxyType is accepted and then re-wrapped over a
            # FRESH top-level copy, so whoever passed it in cannot reach
            # through their own reference and change what the result reports.
            # The proxy is shallow, exactly as `StructuredOutcome.value` is:
            # nested containers reached through it are ordinary mutable
            # objects, so this prevents top-level mutation of a shared result
            # rather than claiming deep immutability.
            #
            # EXACT dict only - a MappingProxyType is deliberately NOT
            # accepted here. A proxy is an exact type that can wrap an
            # ARBITRARY foreign mapping, and copying one runs that mapping's
            # `keys`/`__getitem__`/`__iter__`. An earlier revision accepted a
            # proxy and copied it, so a hostile mapping wrapped in one raised
            # caller-supplied text out of this constructor - a public
            # carrier-construction path executing foreign hooks. Narrowing the
            # public input to a type whose copy cannot call out closes that
            # without needing to inspect what a proxy wraps, which there is no
            # hook-free way to do. The canonical internal path in
            # `request_structured_json` adapts the validator's proxy before it
            # reaches here.
            if _type(self.value) is not _dict:
                raise ValueError(
                    "a successful exchange must carry an exact dict value"
                )
            _object.__setattr__(self, "value", _proxy(_dict(self.value)))
            if not self.response_format_sent:
                raise ValueError("a successful exchange must have sent a request")
            if self.dialect is None:
                raise ValueError("a successful exchange must name its dialect")
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
            # Dialect coherence, same rule as the backend carrier. A refusal
            # taken before a dialect was established has none to name;
            # everything reached after that gate - including every response
            # failure, which by definition follows a sent request - must name
            # the runtime it concerns, or an operator cannot tell which one
            # the result is about. `backend-not-structured-capable` joins the
            # three dialect refusals on the pre-dialect side: it is decided
            # before any backend was consulted at all.
            if self.response_failure is not None:
                if self.dialect is None:
                    raise ValueError(
                        "a response failure must name the dialect it was sent to"
                    )
            elif self.request_refusal == "backend-not-structured-capable" or (
                _pre_dialect(self.request_refusal)
            ):
                if self.dialect is not None:
                    raise ValueError(
                        "a refusal taken before the dialect gate cannot name a "
                        "dialect"
                    )
            elif self.dialect is None:
                raise ValueError(
                    "a refusal taken after the dialect gate must name its dialect"
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
    _validate=validate_structured_output,
    _completion_type=StructuredCompletion,
    _exchange_type=StructuredExchange,
    _proxy=MappingProxyType,
    _type=type,
    _dict=dict,
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
        return _exchange_type(
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
    if _type(completion) is not _completion_type:
        return _exchange_type(
            ok=False, request_refusal="backend-not-structured-capable"
        )

    if not completion.ok:
        return _exchange_type(
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
    outcome: StructuredOutcome = _validate(
        payload, required_keys=required_keys, max_chars=max_chars
    )
    if not outcome.ok:
        return _exchange_type(
            ok=False,
            response_failure=outcome.failure,
            missing_key_indices=outcome.missing_key_indices,
            dialect=completion.dialect,
            response_format_sent=True,
        )

    # Adapt the validator's proxy to the exact dict the carrier accepts.
    # This is the trusted internal path and the conversion is safe BECAUSE of
    # what `structured.py` guarantees: its `value` is always
    # `MappingProxyType` over the exact `dict` that `json.loads` produced
    # under an `object_pairs_hook` which itself returns an exact `dict`. No
    # foreign mapping can be behind it. `_validate` is captured rather than
    # looked up, so that guarantee cannot be swapped out by rebinding a name.
    # A value that is not exactly that proxy is refused rather than copied.
    if _type(outcome.value) is not _proxy:
        return _exchange_type(
            ok=False,
            response_failure="not-json-object",
            dialect=completion.dialect,
            response_format_sent=True,
        )
    return _exchange_type(
        ok=True,
        value=_dict(outcome.value),
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
