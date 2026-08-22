"""OMI-V2 - a closed, provider-neutral structured-output request contract.

Four self-hosted runtimes speak the OpenAI ``/v1/chat/completions`` shape and
all four accept a ``response_format`` asking for schema-constrained decoding.
They do **not** agree on where the schema goes. This module is the whole of
that disagreement, written down once, so that no caller has to guess and no
caller is handed an escape hatch through which to guess.

## The wire shapes, and the evidence for each

Every mapping below was read from the runtime's own repository at a pinned
revision. Nothing here is inferred from a URL, an installed binary, an
environment variable, or a probe.

``llama-cpp`` - llama.cpp @ ``5a32f7b66ef6cfb3e60deea26e3454cc6ad3438c``

    {"type": "json_schema", "schema": {...}}

  ``tools/server/README.md`` documents the schema **flat**, directly under
  ``response_format``, for both ``json_object`` and ``json_schema`` types.
  No ``name`` key appears. The server source additionally reads the nested
  ``json_schema.schema`` path, with the flat form taking precedence; this
  module emits only the documented flat form (see the recorded decisions).

``ollama`` - Ollama @ ``b7871fc0d1d82fe109536efa3e0e8e411c766c75``

    {"type": "json_schema", "json_schema": {"schema": {...}}}

  The documentation states only that ``response_format`` is supported; it
  specifies no shape. The shape above is therefore taken from the source,
  ``openai/openai.go``, whose structs are::

      type ResponseFormat struct {
          Type       string      `json:"type"`
          JsonSchema *JsonSchema `json:"json_schema,omitempty"`
      }
      type JsonSchema struct {
          Schema json.RawMessage `json:"schema"`
      }

  There is no flat ``schema`` field and no ``name`` field. A flat schema is
  silently ignored. This is source-derived evidence, not documented
  evidence, and is labelled as such wherever it is relied upon.

``vllm`` - vLLM @ ``6e448d0ea9bf3d88d898b65449ca6dc2aec170ac``
``sglang`` - SGLang @ ``71de97b264b04dcd514cf904003028aefe9775c8``

    {"type": "json_schema", "json_schema": {"name": ..., "schema": {...}}}

  Both document the OpenAI nesting including ``name``. The two shapes are
  byte-identical today and are still built by separate branches, so a future
  divergence in one cannot be masked by the other.

## What this module refuses to be

There is no ``extra_body``, no ``**kwargs`` passthrough, and no
provider-specific escape hatch. That is a deliberate closure, and it has a
cost worth naming: vLLM's ``structured_outputs`` route (which replaced the
removed ``guided_json``) is reachable *only* through ``extra_body``, so it is
not reachable from here at all. ``response_format`` is the supported path for
all four runtimes, and it is the only path this module builds.

## What sending a request does and does not establish

Emitting ``response_format`` asks a runtime for constrained decoding. It does
not prove the runtime honoured it, and this module never reports that it did.
Ollama makes the gap concrete: its handler is

    switch strings.ToLower(strings.TrimSpace(r.ResponseFormat.Type)) {
    case "json_object": ...
    case "json_schema":
        if r.ResponseFormat.JsonSchema != nil { format = ...Schema }
    }

An unrecognised ``type``, or a ``json_schema`` type with a missing nesting,
leaves the decoding format unset and produces unconstrained output with no
error. Conformance is established only by validating what came back, which
happens one layer up in ``scripts/open_model/structured_exchange.py`` against
``scripts/open_model/structured.py``. This module does not validate responses
and does not contain a response validator.

## Direction of the two validators

``scripts/open_model/structured.py`` parses an untrusted **response payload
string** emitted by a model and decides whether it is usable. The validation
here runs the other way: it walks a caller-supplied **JSON Schema document**
that is about to be serialised outbound. Different artifact, different
direction, no shared decision. Neither is a reimplementation of the other,
and this module deliberately imports nothing from ``scripts.open_model`` -
that package sits *above* this one and importing it would invert the layering.

## Diagnostics carry no content

Every refusal is one token from a closed vocabulary. No schema fragment, key
name, prompt, response, byte offset, length, type name, or exception text
ever reaches a refusal value.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Optional


StructuredDialect = Literal["llama-cpp", "ollama", "vllm", "sglang"]
"""The complete set of runtime dialects with a verified wire shape.

Closed on purpose. A dialect is always supplied explicitly by the caller; it
is never inferred from a base URL, an installed binary, an environment
variable, or a network probe.
"""

SUPPORTED_DIALECTS: Final[tuple[str, ...]] = (
    "llama-cpp",
    "ollama",
    "vllm",
    "sglang",
)
"""Inspection mirror of the accepted dialect tokens.

Off the trust path. ``build_response_format`` dispatches on inlined string
constants and does not read this name, so rebinding it cannot make an
unlisted dialect eligible - it can only make this mirror disagree with the
code, which ``test_omi_v2_structured_request.py`` asserts against.
"""

StructuredRefusal = Literal[
    "dialect-not-configured",
    "dialect-not-exact-str",
    "dialect-unsupported",
    "request-not-exact-type",
    "name-not-safe",
    "schema-not-exact-dict",
    "schema-empty",
    "schema-not-serializable",
    "schema-non-finite-number",
    "schema-too-deep",
    "schema-too-large",
    "tools-with-structured-unsupported",
]
"""Why a structured request was refused. Complete; safe to log verbatim."""

_NAME_MAX_LEN: Final[int] = 64
_NAME_ALPHABET: Final[frozenset[str]] = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "_-"
)
_SCHEMA_MAX_CHARS: Final[int] = 65536
_SCHEMA_MAX_DEPTH: Final[int] = 32
_SCHEMA_MAX_NODES: Final[int] = 4096


@dataclass(frozen=True)
class StructuredOutputRequest:
    """A caller's ask for schema-constrained decoding.

    Deliberately a dumb carrier: it stores exactly what it is given and
    normalises nothing. Silent normalisation would be the wrong shape here -
    coercing an unusable schema to ``{}`` would send an empty constraint and
    produce unconstrained output that *looked* like a satisfied request.
    Every check lives in :func:`plan_structured_request`, which refuses
    rather than repairs.

    ``name`` is required for the contract even though only two of the four
    dialects transmit it; see the recorded decisions in the module docstring
    of ``scripts/agent_backends/openai_compat_backend.py``.
    """

    name: str
    schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StructuredRequestPlan:
    """Outcome of validating one structured request against one dialect.

    On success ``response_format`` is the exact object to place under the
    ``response_format`` request key - already dialect-shaped. On refusal it is
    ``None`` and ``refusal`` carries a single closed token.
    """

    ok: bool
    response_format: Optional[dict[str, Any]] = None
    refusal: Optional[StructuredRefusal] = None

    def __post_init__(self) -> None:
        if self.ok and self.refusal is not None:
            raise ValueError("a successful plan cannot carry a refusal code")
        if not self.ok and self.refusal is None:
            raise ValueError("a refused plan must carry a refusal code")
        if not self.ok and self.response_format is not None:
            raise ValueError("a refused plan must not carry a response format")
        if self.ok and self.response_format is None:
            raise ValueError("a successful plan must carry a response format")


def is_supported_dialect(value: Any) -> bool:
    """True only for an exact built-in ``str`` naming a verified dialect.

    Membership is decided by inlined comparisons rather than by reading
    :data:`SUPPORTED_DIALECTS`, so the answer cannot be changed by rebinding
    a module attribute. A ``str`` subclass is refused by exact-type identity
    before any comparison runs, so no overridden ``__eq__`` or ``__hash__``
    is ever invoked.
    """
    if type(value) is not str:
        return False
    return (
        value == "llama-cpp"
        or value == "ollama"
        or value == "vllm"
        or value == "sglang"
    )


def _name_refusal(value: Any) -> Optional[StructuredRefusal]:
    """Refuse any schema name that is not a short, safe, opaque token.

    Exact ``str`` only, 1..64 characters, drawn from ``[A-Za-z0-9_-]``. The
    ceiling and alphabet match the constraint OpenAI-compatible servers
    document for ``json_schema.name``; the point here is that a name is
    transmitted, so it must not be able to carry a path, a prompt fragment,
    or a secret.
    """
    if type(value) is not str:
        return "name-not-safe"
    if not value or len(value) > _NAME_MAX_LEN:
        return "name-not-safe"
    for character in value:
        if character not in _NAME_ALPHABET:
            return "name-not-safe"
    return None


def _schema_refusal(schema: Any) -> Optional[StructuredRefusal]:
    """Walk a schema document and refuse anything unsafe to serialise.

    The walk is iterative, so a deeply nested document is refused by the
    depth bound rather than by exhausting the interpreter stack. Only exact
    built-in JSON types are accepted; every element is checked by
    ``type(x) is ...`` identity, so no supplied ``__eq__``, ``__hash__``,
    ``__len__``, ``__iter__``, or ``__bool__`` runs on caller data.

    Nothing about the offending element - its value, position, key, or type
    name - reaches the returned token.
    """
    if type(schema) is not dict:
        return "schema-not-exact-dict"
    if not schema:
        # An empty schema constrains nothing. Sending it would ask for
        # structured output and receive whatever the model liked, which is
        # exactly the false-success this contract exists to prevent.
        return "schema-empty"

    stack: list[tuple[Any, int]] = [(schema, 0)]
    nodes = 0
    while stack:
        node, depth = stack.pop()
        if depth > _SCHEMA_MAX_DEPTH:
            return "schema-too-deep"
        nodes += 1
        if nodes > _SCHEMA_MAX_NODES:
            return "schema-too-large"
        node_type = type(node)
        if node_type is dict:
            for key, value in node.items():
                if type(key) is not str:
                    return "schema-not-serializable"
                stack.append((value, depth + 1))
        elif node_type is list:
            for value in node:
                stack.append((value, depth + 1))
        elif node_type is float:
            # `node` is proven exact float, so isfinite invokes no hook.
            if not math.isfinite(node):
                return "schema-non-finite-number"
        elif node_type is bool or node_type is int or node_type is str:
            continue
        elif node is None:
            continue
        else:
            return "schema-not-serializable"

    try:
        encoded = json.dumps(schema, allow_nan=False, ensure_ascii=False)
    except (ValueError, TypeError, RecursionError):
        # Unreachable for a document the walk accepted; kept so the function
        # is total rather than relying on that reasoning holding forever.
        return "schema-not-serializable"
    if len(encoded) > _SCHEMA_MAX_CHARS:
        return "schema-too-large"
    return None


def build_response_format(
    dialect: str, request: StructuredOutputRequest
) -> Optional[dict[str, Any]]:
    """Build the dialect-exact ``response_format`` object, or ``None``.

    Callers must validate first; :func:`plan_structured_request` is the
    supported entry point and calls this only after every check has passed.

    The dispatch is an inlined chain of exact-string comparisons. It reads no
    module-level mapping, so no rebinding of :data:`SUPPORTED_DIALECTS` or of
    :data:`DIALECT_WIRE_SHAPES` can redirect a dialect to another runtime's
    shape or introduce a fifth. An unrecognised dialect falls through to
    ``None``, which every caller treats as a refusal.
    """
    if type(dialect) is not str:
        return None
    schema = request.schema

    if dialect == "llama-cpp":
        # Flat, per the pinned tools/server/README.md. No name key exists.
        return {"type": "json_schema", "schema": schema}
    if dialect == "ollama":
        # Nested; no name field exists in the Go struct, so none is sent.
        return {"type": "json_schema", "json_schema": {"schema": schema}}
    if dialect == "vllm":
        return {
            "type": "json_schema",
            "json_schema": {"name": request.name, "schema": schema},
        }
    if dialect == "sglang":
        # Byte-identical to vLLM today; kept as its own branch so a future
        # divergence cannot be hidden behind a shared one.
        return {
            "type": "json_schema",
            "json_schema": {"name": request.name, "schema": schema},
        }
    return None


def plan_structured_request(
    dialect: Any,
    request: Any,
    *,
    has_tools: bool = False,
) -> StructuredRequestPlan:
    """Validate a structured request and produce its dialect-exact wire shape.

    Total: returns a plan for every input and never raises. The order below
    is fixed, and the first refusal wins because later checks are not
    meaningful once an earlier one has failed:

    1. ``dialect-not-configured``   - no dialect was configured at all.
    2. ``dialect-not-exact-str``    - a non-string was supplied.
    3. ``dialect-unsupported``      - a string naming no verified runtime.
    4. ``request-not-exact-type``   - not exactly a
       :class:`StructuredOutputRequest`.
    5. ``tools-with-structured-unsupported`` - see below.
    6. ``name-not-safe``            - see :func:`_name_refusal`.
    7. ``schema-*``                 - see :func:`_schema_refusal`.

    On the tool refusal: the interaction between a tool declaration and a
    ``response_format`` constraint was **not** verified at the pinned
    revisions of any of the four runtimes, and tool-choice behaviour is out
    of scope for this package. Rather than send both and describe the result
    as supported, this refuses the combination. That is a claim about the
    evidence, not about the runtimes: it says the combination is unverified
    here, not that it is impossible.
    """
    if dialect is None:
        return StructuredRequestPlan(ok=False, refusal="dialect-not-configured")
    if type(dialect) is not str:
        return StructuredRequestPlan(ok=False, refusal="dialect-not-exact-str")
    if not is_supported_dialect(dialect):
        return StructuredRequestPlan(ok=False, refusal="dialect-unsupported")
    if type(request) is not StructuredOutputRequest:
        return StructuredRequestPlan(ok=False, refusal="request-not-exact-type")
    if has_tools is not False:
        return StructuredRequestPlan(
            ok=False, refusal="tools-with-structured-unsupported"
        )

    name_refusal = _name_refusal(request.name)
    if name_refusal is not None:
        return StructuredRequestPlan(ok=False, refusal=name_refusal)

    schema_refusal = _schema_refusal(request.schema)
    if schema_refusal is not None:
        return StructuredRequestPlan(ok=False, refusal=schema_refusal)

    response_format = build_response_format(dialect, request)
    if response_format is None:
        # Unreachable while the dispatch and the guard agree; if they ever
        # drift, drift refuses rather than sending an unshaped request.
        return StructuredRequestPlan(ok=False, refusal="dialect-unsupported")
    return StructuredRequestPlan(ok=True, response_format=response_format)


DIALECT_WIRE_SHAPES: Final[dict[str, str]] = {
    "llama-cpp": "response_format.schema",
    "ollama": "response_format.json_schema.schema",
    "vllm": "response_format.json_schema.{name,schema}",
    "sglang": "response_format.json_schema.{name,schema}",
}
"""Human-readable inspection mirror of where each dialect carries the schema.

Documentation only, and off the trust path: :func:`build_response_format`
never reads this name. It exists so an auditor can see the four shapes side
by side, and so a drift test can assert the mirror still matches the code.
"""


__all__ = [
    "DIALECT_WIRE_SHAPES",
    "SUPPORTED_DIALECTS",
    "StructuredDialect",
    "StructuredOutputRequest",
    "StructuredRefusal",
    "StructuredRequestPlan",
    "build_response_format",
    "is_supported_dialect",
    "plan_structured_request",
]
