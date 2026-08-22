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
from typing import Any, Literal, Mapping, Optional, Union

from scripts.agent_backends.base import Message, ToolSpec
from scripts.agent_backends.openai_compat_backend import StructuredCompletion
from scripts.agent_backends.structured_request import StructuredRefusal
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


@dataclass(frozen=True)
class StructuredExchange:
    """Outcome of one ask-and-check round trip.

    Exactly one of three states, distinguishable without inspecting content:

    - **ok** - a request was sent and the response parsed as a JSON object
      carrying every required key. ``value`` is a read-only view of it.
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

    def __post_init__(self) -> None:
        if self.ok:
            if self.request_refusal is not None or self.response_failure is not None:
                raise ValueError("a successful exchange cannot carry a failure")
            if self.value is None:
                raise ValueError("a successful exchange must carry a value")
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
    "ExchangeRefusal",
    "StructuredExchange",
    "request_structured_json",
]
