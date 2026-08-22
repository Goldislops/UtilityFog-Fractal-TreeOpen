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

    {"type": "json_schema", "json_schema": {"schema": {...}}}

  **The README and the server source conflict at this same commit, and the
  executable source wins.** ``tools/server/README.md`` (blob
  ``93736c3edfa9bd094bf79f7d2de4659fbf8e74c9``) shows the schema flat under
  ``response_format`` for the ``json_schema`` type as well as for
  ``json_object``. The parser that actually runs, in
  ``tools/server/server-common.cpp`` (blob
  ``585f65e83c655d3b8b7e398e8bf76552dc846f36``), does not read that::

      if (response_type == "json_object") {
          if (response_format.contains("schema") || json_schema.empty()) {
              json_schema = json_value(response_format, "schema", json::object());
          }
      } else if (response_type == "json_schema") {
          auto schema_wrapper = json_value(response_format, "json_schema", json::object());
          json_schema = json_value(schema_wrapper, "schema", json::object());
      }

  The flat ``schema`` key is read **only** for ``type=json_object``. For
  ``type=json_schema`` the server reads ``response_format.json_schema.schema``
  and nothing else, so a flat schema sent with that type produces an empty
  wrapper, an empty constraint, and silently unconstrained decoding - exactly
  the false success this contract exists to prevent. An earlier revision of
  this module emitted the flat form on the README's authority and carried that
  defect. Nothing is shotgunned: one path is emitted, and it is the one the
  pinned executable source reads. No ``name`` key exists on either path.

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

    {"type": "json_schema",
     "json_schema": {"name": "structured_output", "schema": {...}}}

  Both document the OpenAI nesting including ``name``. That ``name`` is the
  fixed constant :data:`STRUCTURED_WIRE_NAME`, not caller data - see "The
  wire name is not caller data" below. The two shapes are byte-identical
  today and are still built by separate branches, so a future divergence in
  one cannot be masked by the other.

## What this module refuses to be

There is no ``extra_body``, no ``**kwargs`` passthrough, and no
provider-specific escape hatch. That is a deliberate closure, and it has a
cost worth naming: vLLM's ``structured_outputs`` route (which replaced the
removed ``guided_json``) is reachable *only* through ``extra_body``, so it is
not reachable from here at all. ``response_format`` is the supported path for
all four runtimes, and it is the only path this module builds.

## The wire name is not caller data

``json_schema.name`` is transmitted to vLLM and SGLang, so whatever it holds
leaves this process. An earlier revision let the caller supply it and guarded
it with a local character-class check: exact ``str``, 1..64 characters, drawn
from ``[A-Za-z0-9_-]``. That alphabet admits ``sk-OMIV2SECRET123456789``. A
caller who named a schema after a credential, or interpolated one by mistake,
had it placed on the wire by the very function meant to prevent that.

Two repairs were available and both were rejected before a third was taken.
Reusing the hardened primitive in ``scripts/open_model/redaction.py`` - which
does reject that string, because it cross-checks every candidate against the
secret matcher - is not reachable from here: ``scripts.open_model`` imports
this package, so importing it back is a genuine import cycle rather than a
layering preference. Copying its rules into this module would create a second
secret detector free to drift from the first, which is precisely the failure
a shared primitive exists to prevent.

So the field stopped being caller data. :data:`STRUCTURED_WIRE_NAME` is a
fixed constant, ``StructuredOutputRequest`` has no ``name``, and no path
carries caller-controlled text into ``json_schema.name``. The detector that
cannot drift is the one that does not need to exist.

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
error. What came back is checked one layer up in
``scripts/open_model/structured_exchange.py`` against
``scripts/open_model/structured.py``. This module does not validate responses
and does not contain a response validator.

That check does **not** establish schema conformance, and this module does
not claim it does. It establishes that the payload is a JSON object carrying
every required key - usability, not conformance. A response of
``{"ok": "wrong type", "extra": 123}`` satisfies it against a schema
demanding a boolean ``ok`` and no additional properties. Nothing in this
package compares a response against the schema it sent; the outbound schema
is validated for safe serialisation only.

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
from typing import Any, Final, Literal, Optional, get_args


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
    "schema-not-exact-dict",
    "schema-empty",
    "schema-not-serializable",
    "schema-non-finite-number",
    "schema-too-deep",
    "schema-too-large",
    "tools-with-structured-unsupported",
]
"""Why a structured request was refused. Complete; safe to log verbatim."""

REFUSAL_TOKENS: Final[frozenset[str]] = frozenset(get_args(StructuredRefusal))
"""The refusal vocabulary as a runtime set, derived from the Literal itself.

Unlike :data:`SUPPORTED_DIALECTS` this one IS on the trust path -
:class:`StructuredRequestPlan` rejects any token outside it. Deriving it from
``get_args`` rather than restating it means the check and the declared type
cannot disagree: there is only one list.
"""

STRUCTURED_WIRE_NAME: Final[str] = "structured_output"
"""The exact ``json_schema.name`` sent to vLLM and SGLang. Never caller data.

vLLM and SGLang both require the key, so something must occupy it. A fixed
constant occupies it with a value that is identical on every call, carries no
caller text, and therefore cannot leak one. It satisfies the alphabet and
length both runtimes document for the field.
"""

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

    There is deliberately no ``name`` field. vLLM and SGLang transmit a
    ``json_schema.name``, and a transmitted value that a caller can set is a
    value a caller can leak a secret through - the module docstring records
    the case that forced this. The wire name is the fixed constant
    :data:`STRUCTURED_WIRE_NAME`.
    """

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
        # Exact bool, not truthiness: a foreign object with __bool__ must not
        # be able to present itself as a successful plan.
        if type(self.ok) is not bool:
            raise ValueError("ok must be exactly a bool")
        if self.refusal is not None and (
            type(self.refusal) is not str or self.refusal not in REFUSAL_TOKENS
        ):
            raise ValueError("refusal must be a token from the closed vocabulary")
        if self.ok and self.refusal is not None:
            raise ValueError("a successful plan cannot carry a refusal code")
        if not self.ok and self.refusal is None:
            raise ValueError("a refused plan must carry a refusal code")
        if not self.ok and self.response_format is not None:
            raise ValueError("a refused plan must not carry a response format")
        if self.ok and type(self.response_format) is not dict:
            raise ValueError(
                "a successful plan must carry an exact dict response format"
            )


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


def _schema_refusal(
    schema: Any,
) -> tuple[Optional[StructuredRefusal], Optional[str]]:
    """Walk a schema document and refuse anything unsafe to serialise.

    Returns ``(refusal, None)`` on refusal and ``(None, encoded)`` on
    acceptance, where ``encoded`` is the exact JSON text of the accepted
    document. The encoding is handed back rather than discarded because
    :func:`plan_structured_request` needs a snapshot detached from the
    caller, and re-parsing this string is that snapshot - obtained from work
    already done rather than from a second traversal that could disagree
    with the one that did the validating.

    The walk is iterative, so a deeply nested document is refused by the
    depth bound rather than by exhausting the interpreter stack. Only exact
    built-in JSON types are accepted; every element is checked by
    ``type(x) is ...`` identity, so no supplied ``__eq__``, ``__hash__``,
    ``__len__``, ``__iter__``, or ``__bool__`` runs on caller data.

    Nothing about the offending element - its value, position, key, or type
    name - reaches the returned token.
    """
    if type(schema) is not dict:
        return "schema-not-exact-dict", None
    if not schema:
        # An empty schema constrains nothing. Sending it would ask for
        # structured output and receive whatever the model liked, which is
        # exactly the false-success this contract exists to prevent.
        return "schema-empty", None

    stack: list[tuple[Any, int]] = [(schema, 0)]
    nodes = 0
    while stack:
        node, depth = stack.pop()
        if depth > _SCHEMA_MAX_DEPTH:
            return "schema-too-deep", None
        nodes += 1
        if nodes > _SCHEMA_MAX_NODES:
            return "schema-too-large", None
        node_type = type(node)
        if node_type is dict:
            for key, value in node.items():
                if type(key) is not str:
                    return "schema-not-serializable", None
                stack.append((value, depth + 1))
        elif node_type is list:
            for value in node:
                stack.append((value, depth + 1))
        elif node_type is float:
            # `node` is proven exact float, so isfinite invokes no hook.
            if not math.isfinite(node):
                return "schema-non-finite-number", None
        elif node_type is bool or node_type is int or node_type is str:
            continue
        elif node is None:
            continue
        else:
            return "schema-not-serializable", None

    try:
        encoded = json.dumps(schema, allow_nan=False, ensure_ascii=False)
    except (ValueError, TypeError, RecursionError):
        # Unreachable for a document the walk accepted; kept so the function
        # is total rather than relying on that reasoning holding forever.
        return "schema-not-serializable", None
    if len(encoded) > _SCHEMA_MAX_CHARS:
        return "schema-too-large", None
    return None, encoded


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
        # Nested, per the pinned tools/server/server-common.cpp, which reads
        # the flat `schema` key only for type=json_object. Kept as its own
        # branch even though it matches Ollama today, so a future divergence
        # in either runtime cannot be hidden behind a shared one.
        return {"type": "json_schema", "json_schema": {"schema": schema}}
    if dialect == "ollama":
        # Nested; no name field exists in the Go struct, so none is sent.
        return {"type": "json_schema", "json_schema": {"schema": schema}}
    if dialect == "vllm":
        return {
            "type": "json_schema",
            "json_schema": {"name": STRUCTURED_WIRE_NAME, "schema": schema},
        }
    if dialect == "sglang":
        # Byte-identical to vLLM today; kept as its own branch so a future
        # divergence cannot be hidden behind a shared one.
        return {
            "type": "json_schema",
            "json_schema": {"name": STRUCTURED_WIRE_NAME, "schema": schema},
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
    6. ``schema-*``                 - see :func:`_schema_refusal`.

    There is no name check because there is no caller-supplied name; see
    "The wire name is not caller data" in the module docstring.

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

    schema_refusal, encoded_schema = _schema_refusal(request.schema)
    if schema_refusal is not None:
        return StructuredRequestPlan(ok=False, refusal=schema_refusal)

    # Snapshot between validating and building. `StructuredOutputRequest` is
    # frozen, but freezing a field does not freeze the object it points at:
    # the caller still holds the very dict that was walked, and could mutate
    # it after the checks passed and before - or after - the request goes out.
    # Every guarantee above would then describe a document that is no longer
    # the one being sent.
    #
    # Re-parsing the encoding the walk already produced yields a fresh object
    # graph sharing no container with the caller's. Using that encoding rather
    # than a separate deep copy means the snapshot is provably the document
    # that was validated, not a re-traversal that could differ from it.
    if encoded_schema is None:
        # Unreachable while the acceptance path always returns an encoding.
        # Written as a refusal rather than an assert so that behaviour is
        # identical under -O and -OO, where asserts are stripped out.
        return StructuredRequestPlan(ok=False, refusal="schema-not-serializable")
    snapshot = json.loads(encoded_schema)

    response_format = build_response_format(
        dialect, StructuredOutputRequest(schema=snapshot)
    )
    if response_format is None:
        # Unreachable while the dispatch and the guard agree; if they ever
        # drift, drift refuses rather than sending an unshaped request.
        return StructuredRequestPlan(ok=False, refusal="dialect-unsupported")
    return StructuredRequestPlan(ok=True, response_format=response_format)


DIALECT_WIRE_SHAPES: Final[dict[str, str]] = {
    "llama-cpp": "response_format.json_schema.schema",
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
    "REFUSAL_TOKENS",
    "STRUCTURED_WIRE_NAME",
    "SUPPORTED_DIALECTS",
    "StructuredDialect",
    "StructuredOutputRequest",
    "StructuredRefusal",
    "StructuredRequestPlan",
    "build_response_format",
    "is_supported_dialect",
    "plan_structured_request",
]
