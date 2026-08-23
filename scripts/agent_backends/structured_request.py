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

  The documentation mentions ``response_format`` exactly twice - a
  supported-parameter checklist entry in ``docs/api/openai-compatibility.mdx``
  and a tip bullet in ``docs/capabilities/structured-outputs.mdx`` - and
  **neither specifies a shape**. The shape above is therefore taken from the
  source, ``openai/openai.go``, whose structs are::

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

So the field stopped being caller data. The wire name is an inlined literal
in :func:`build_response_format`, ``StructuredOutputRequest`` has no
``name``, and no path carries caller-controlled text into
``json_schema.name``. The detector that cannot drift is the one that does not
need to exist.

## The residual this does NOT close, stated plainly

The **schema document itself is caller data and is transmitted verbatim**, to
all four runtimes, with no secret check of any kind. A caller who writes

    {"properties": {"sk-AKIA...": {"type": "string"}},
     "description": "bearer sk-..."}

puts that text on the wire, and nothing here stops it. That is not an
oversight being deferred; it is inherent. The entire purpose of the parameter
is to transmit the caller's schema, so a layer that refused schema content
could not do its job, and a secret matcher applied to arbitrary schema text
would be the second drifting detector this package was told not to build.

What is closed is narrower and worth stating exactly: no field this package
*chooses the value of* can carry caller text off the machine. The schema is
the caller's own payload, and its contents remain the caller's
responsibility. Validation here is for safe serialisation, never for secrets.

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

## No decision path resolves a rebindable name, transitively

Every function here that takes a trust decision is produced by a small
factory that binds what it needs into closure cells - the dialect predicate,
the pre-dialect classifier, the wire-shape check, the snapshot validator, the
response-format builder, and the planner. That includes the **builtins** the
exact-type checks use, not only the package's own data.

The builtins are the part that was missed once and is worth spelling out.
Inlining the dialect literals closed the DATA while the machinery reading it
still looked up ``type`` and ``str`` as module globals, so an ordinary
assignment - ``structured_request.type = <replacement>`` - changed the
answer without replacing the function, its defaults, its code, or
``sys.modules``. That admitted a ``str`` SUBCLASS, which can carry hidden
attributes and lie in ``__repr__``, into fields required to hold exact
tokens, including the transmitted ``json_schema.name``.

Stated exactly, because the boundary matters more than the reassurance:

- **Closed** - ordinary rebinding of any module-level name this module or its
  consumers resolve, including added builtins.
- **Deliberately open** - ``_SCHEMA_MAX_CHARS``, ``_SCHEMA_MAX_DEPTH`` and
  ``_SCHEMA_MAX_NODES``, which bound how MUCH is accepted and never what
  TYPE, so rebinding one cannot admit a foreign type.
- **Out of scope, and not claimed** - closure-cell surgery, overwriting
  ``__defaults__``, replacing a function object, patching a stdlib function
  such as ``json.dumps``, or swapping this module in ``sys.modules``. Those
  are arbitrary code replacement, not name rebinding, and no amount of care
  inside this module prevents them.
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
    "schema-not-utf8-encodable",
    "schema-changed-during-validation",
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
"""Inspection mirror of the ``json_schema.name`` sent to vLLM and SGLang.

Off the trust path. :func:`build_response_format` emits this text as an
**inlined literal** and does not read this name, so rebinding it cannot put
arbitrary text on the wire - it can only make this mirror disagree with the
code, which ``test_omi_v2_structured_request.py`` asserts against. That
matters more here than for the other mirrors: this is the one value in the
request that both leaves the process and is not caller data.

Why a constant at all: both runtimes make the field **required**, so
something must occupy it, and a value identical on every call carries no
caller text and therefore cannot leak one.

The requirement is pinned to source, not inferred:

- vLLM ``JsonSchemaResponseFormat.name: str`` (no default) -
  ``vllm/entrypoints/openai/engine/protocol.py`` @
  ``6e448d0ea9bf3d88d898b65449ca6dc2aec170ac``, blob
  ``805c639d7d16a52f495d8942880682732280da0f``.
- SGLang ``JsonSchemaResponseFormat.name: str`` (no default) -
  ``python/sglang/srt/entrypoints/openai/protocol.py`` @
  ``71de97b264b04dcd514cf904003028aefe9775c8``, blob
  ``da62e3b0fbd632702a56de76050d2ea37c6e0690``.

Neither pinned source constrains the field's alphabet or length - both
declare a bare ``str``. An earlier revision of this docstring claimed they
documented both; that claim was not supported by either file and is
withdrawn. The value chosen is conservative regardless.
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


def _closed_wire_shape_predicate():
    """Build :func:`is_supported_wire_shape`, builtins bound in cells.

    This one matters most: ``json_schema.name`` is transmitted, so a
    ``str`` subclass admitted here leaves the process carrying whatever its
    author hid on it. Looking up ``type``, ``str``, ``dict`` and ``len`` as
    module globals meant one ordinary assignment could admit exactly that.
    """
    _type = type
    _str = str
    _dict = dict
    _len = len

    def is_supported_wire_shape(value: Any) -> bool:
        """True only for one of the exact dialect ``response_format`` shapes.

        Two shapes exist across the four dialects, and this accepts those and
        nothing else - not "some dictionary", which is all an earlier
        revision checked. A carrier that accepts an arbitrary dict on its
        success path cannot claim the success path carries a dialect shape.

        The literals are inlined and the builtins are bound in cells, so the
        decision resolves no rebindable name.
        """
        if _type(value) is not _dict:
            return False
        if _len(value) != 2 or "type" not in value or "json_schema" not in value:
            return False
        kind = value["type"]
        if _type(kind) is not _str or kind != "json_schema":
            return False
        nested = value["json_schema"]
        if _type(nested) is not _dict:
            return False
        if _len(nested) == 1 and "schema" in nested:
            pass  # llama-cpp and ollama: no name field exists on either
        elif _len(nested) == 2 and "schema" in nested and "name" in nested:
            name = nested["name"]
            # vLLM and SGLang: the name is this package's fixed constant,
            # never caller text. Exact-type checked before the comparison, so
            # a deceptive str subclass cannot present itself as the constant.
            if _type(name) is not _str or name != "structured_output":
                return False
        else:
            return False
        return _type(nested["schema"]) is _dict

    return is_supported_wire_shape


is_supported_wire_shape = _closed_wire_shape_predicate()


def _build_request_plan_class():
    """Build :class:`StructuredRequestPlan` with its authorities in cells.

    An earlier revision bound these as DEFAULTED PARAMETERS of
    ``__post_init__``. That closed name rebinding and opened something
    worse: the parameters were directly addressable, so a caller needed no
    rebinding at all - just a keyword argument - to supply their own
    vocabulary or their own shape check. A capture that a caller can pass is
    not a capture; it is an injection point with a leading underscore.

    Binding them here puts them in cells no caller can address, and leaves
    the documented public signature exactly as it reads: ``__post_init__()``
    takes nothing, and passing a former capture keyword raises TypeError.
    """
    _tokens = REFUSAL_TOKENS
    _wire_shape_ok = is_supported_wire_shape
    _type = type
    _str = str
    _bool = bool
    _ValueError = ValueError

    @dataclass(frozen=True)
    class StructuredRequestPlan:
        """Outcome of validating one structured request against one dialect.

        On success ``response_format`` is the exact object to place under the
        ``response_format`` request key - already dialect-shaped, and verified to
        be one of the two shapes the four dialects actually use. On refusal it is
        ``None`` and ``refusal`` carries a single closed token.

        Every trust decision below is taken against a value captured when this
        class was defined, not a name looked up when an instance is built - see
        the note on ``__post_init__``.
        """

        ok: bool
        response_format: Optional[dict[str, Any]] = None
        refusal: Optional[StructuredRefusal] = None

        def __post_init__(self) -> None:
            """Validate the carrier's own coherence.

            The defaulted parameters are the point, not clutter. A dataclass
            calls ``self.__post_init__()`` with no arguments, so each default is
            bound to the OBJECT it names when the class is defined and is never
            looked up again. Rebinding ``REFUSAL_TOKENS`` or
            ``is_supported_wire_shape`` on the module therefore cannot widen what
            a carrier will accept - which reading them as globals did allow,
            including admitting arbitrary secret-shaped refusal text.
            """
            # Exact bool, not truthiness: a foreign object with __bool__ must not
            # be able to present itself as a successful plan.
            if _type(self.ok) is not _bool:
                raise _ValueError("ok must be exactly a bool")
            if self.refusal is not None and (
                _type(self.refusal) is not _str or self.refusal not in _tokens
            ):
                raise _ValueError("refusal must be a token from the closed vocabulary")
            if self.ok and self.refusal is not None:
                raise _ValueError("a successful plan cannot carry a refusal code")
            if not self.ok and self.refusal is None:
                raise _ValueError("a refused plan must carry a refusal code")
            if not self.ok and self.response_format is not None:
                raise _ValueError("a refused plan must not carry a response format")
            if self.ok and not _wire_shape_ok(self.response_format):
                raise _ValueError(
                    "a successful plan must carry a supported dialect wire shape"
                )

    return StructuredRequestPlan


StructuredRequestPlan = _build_request_plan_class()


def _closed_dialect_predicate():
    """Build :func:`is_supported_dialect` with its builtins bound in cells.

    Inlining the four dialect literals closed the DATA. It did not close the
    machinery that reads them: the predicate still looked up ``type`` and
    ``str`` as module globals, and an ordinary assignment -
    ``structured_request.type = <replacement>`` - changed its answer without
    replacing the function, its defaults, its code, or ``sys.modules``. That
    admitted a ``str`` SUBCLASS, which can carry hidden attributes and lie in
    ``__repr__``, everywhere an exact dialect token was required.

    Binding the two builtins here puts them in this function's closure cells,
    which a name rebinding cannot reach. Cell surgery remains out of scope,
    as it has been since the OMI-V1 seventh round.
    """
    _type = type
    _str = str

    def is_supported_dialect(value: Any) -> bool:
        """True only for an exact built-in ``str`` naming a verified dialect.

        Membership is decided by inlined comparisons rather than by reading
        :data:`SUPPORTED_DIALECTS`, so the answer cannot be changed by
        rebinding a module attribute. A ``str`` subclass is refused by
        exact-type identity before any comparison runs, so no overridden
        ``__eq__`` or ``__hash__`` is ever invoked - and the identity check
        itself resolves no module-level name.
        """
        if _type(value) is not _str:
            return False
        return (
            value == "llama-cpp"
            or value == "ollama"
            or value == "vllm"
            or value == "sglang"
        )

    return is_supported_dialect


is_supported_dialect = _closed_dialect_predicate()


def _closed_pre_dialect_predicate():
    """Build :func:`is_pre_dialect_refusal`, builtins bound in cells.

    Same reasoning as :func:`_closed_dialect_predicate`.
    """
    _type = type
    _str = str

    def is_pre_dialect_refusal(token: Any) -> bool:
        """True for the refusals decided BEFORE a dialect was established.

        These three are reached while the dialect is still unknown, absent,
        or rejected, so a carrier reporting one of them has no verified
        dialect to name and must carry none. Every other refusal in the
        vocabulary is reached only after the dialect passed its gate, so a
        carrier reporting one of those must name the dialect it was refused
        for - otherwise an operator cannot tell which runtime it belongs to.

        The literals are inlined and the builtins are bound in cells, so the
        decision resolves no rebindable name.
        """
        if _type(token) is not _str:
            return False
        return (
            token == "dialect-not-configured"
            or token == "dialect-not-exact-str"
            or token == "dialect-unsupported"
        )

    return is_pre_dialect_refusal


is_pre_dialect_refusal = _closed_pre_dialect_predicate()


def _closed_snapshot_validator():
    """Build :func:`_validated_snapshot`, builtins bound in closure cells.

    Every type decision this function makes was previously a module-global
    lookup, so an ordinary assignment such as
    ``structured_request._dict = <replacement>`` could change which values it
    accepted into a snapshot that is then transmitted. The builtins are now
    bound in cells and cannot be reached by rebinding a name.

    Deliberately NOT captured: ``_SCHEMA_MAX_CHARS``, ``_SCHEMA_MAX_DEPTH``
    and ``_SCHEMA_MAX_NODES`` stay module-level and adjustable. They bound
    HOW MUCH is accepted, never WHAT TYPE, so rebinding one cannot admit a
    foreign type or a ``_str`` subclass - it can only widen or narrow a size
    limit, which a deployment may legitimately want to do. That boundary is
    stated rather than quietly assumed.

    ``json.dumps`` and ``math.isfinite`` are likewise reached through their
    modules: replacing a stdlib function is arbitrary code replacement, not
    name rebinding, and is out of scope exactly as it has been since the
    OMI-V1 seventh round.
    """
    _type = type
    _str = str
    _dict = dict
    _list = list
    _float = float
    _bool = bool
    _int = int
    _len = len
    _enumerate = enumerate
    # Stdlib MODULES and exception classes, bound as objects. Reaching them
    # through the module-level names `json` / `math` left an ordinary
    # reassignment - `structured_request.json = <replacement>` - able to
    # bypass the UTF-8 refusal entirely and admit an unpaired surrogate into
    # a transmitted schema.
    #
    # The module object is captured rather than `json.dumps` itself, and the
    # difference is deliberate: rebinding this module's `json` NAME is closed,
    # while patching an attribute ON the captured stdlib module remains the
    # documented arbitrary-code-replacement boundary - the same boundary as
    # replacing a function object or swapping `sys.modules`. Keeping that door
    # where it already was is also what lets the gate-1 controls drive a
    # mutation at exactly the instant the serialiser runs.
    _json = json
    _math = math
    _ValueError = ValueError
    _TypeError = TypeError
    _RecursionError = RecursionError
    _RuntimeError = RuntimeError
    _UnicodeEncodeError = UnicodeEncodeError

    def _validated_snapshot(
        schema: Any,
    ) -> tuple[Optional[StructuredRefusal], Optional[_dict[_str, Any]]]:
        """Validate a schema document and build its detached snapshot at once.

        Returns ``(refusal, None)`` on refusal and ``(None, snapshot)`` on
        acceptance, where ``snapshot`` shares no container with the caller.

        **Why validation and copying are one traversal.** An earlier revision
        walked the caller's containers to validate them, and then handed the
        caller's own object to ``json.dumps`` to produce the text it re-parsed as
        a snapshot. Those are two separate reads of caller-owned data, and
        anything the caller changed in between landed in the snapshot without
        ever having been checked: an over-depth structure, an over-node
        structure, or a type the walk would have refused could all be
        substituted into an already-visited slot and be serialised as though
        validated.

        Closing that window means never reading a caller container twice. Each
        value is checked and copied into the detached structure at the moment it
        is first seen, so the accepted snapshot contains exactly - and only - the
        values this function inspected. Everything afterwards, including the
        encoding, reads the snapshot; the caller's object is never touched again.
        Scalars are shared rather than copied because ``_str``, ``_int``,
        ``_float``, ``_bool`` and ``None`` are immutable, so sharing them cannot
        give the caller a way back in.

        The walk is iterative, so a deeply nested document is refused by the
        depth bound rather than by exhausting the interpreter stack. Only exact
        built-in JSON types are accepted; every element is checked by
        ``_type(x) is ...`` identity, so no supplied ``__eq__``, ``__hash__``,
        ``__len__``, ``__iter__``, or ``__bool__`` runs on caller data.

        Nothing about the offending element - its value, position, key, or type
        name - reaches the returned token.
        """
        if _type(schema) is not _dict:
            return "schema-not-exact-dict", None
        if not schema:
            # An empty schema constrains nothing. Sending it would ask for
            # structured output and receive whatever the model liked, which is
            # exactly the false-success this contract exists to prevent.
            return "schema-empty", None

        root: _dict[_str, Any] = {}
        # This function promises a refusal rather than an exception for every
        # input. A container mutated by another thread mid-read raises
        # RuntimeError ("dictionary changed size during iteration") from the
        # iteration itself, which no per-element type check can prevent - so it
        # is caught and reported as a refusal like every other rejection.
        try:
            # (source container, its detached counterpart, depth of the source)
            stack: _list[tuple[Any, Any, _int]] = [(schema, root, 0)]
            nodes = 1  # the root document itself
            while stack:
                source, destination, depth = stack.pop()
                child_depth = depth + 1
                source_is_dict = _type(source) is _dict
                # `enumerate` supplies positions for a _list so both containers
                # drive the same loop; the position is discarded, because _list
                # order is preserved by appending in iteration order.
                entries = source.items() if source_is_dict else _enumerate(source)
                for key, value in entries:
                    if source_is_dict and _type(key) is not _str:
                        return "schema-not-serializable", None
                    nodes += 1
                    if nodes > _SCHEMA_MAX_NODES:
                        return "schema-too-large", None
                    if child_depth > _SCHEMA_MAX_DEPTH:
                        return "schema-too-deep", None
                    value_type = _type(value)
                    if value_type is _dict:
                        copied: Any = {}
                        stack.append((value, copied, child_depth))
                    elif value_type is _list:
                        copied = []
                        stack.append((value, copied, child_depth))
                    elif value_type is _float:
                        # `value` is proven exact _float, so isfinite runs no hook.
                        if not _math.isfinite(value):
                            return "schema-non-finite-number", None
                        copied = value
                    elif value_type is _bool or value_type is _int or value_type is _str:
                        copied = value
                    elif value is None:
                        copied = None
                    else:
                        return "schema-not-serializable", None
                    if source_is_dict:
                        destination[key] = copied
                    else:
                        destination.append(copied)
        except _RuntimeError:
            return "schema-changed-during-validation", None

        # From here on only the detached snapshot is read. `json.dumps` cannot
        # see a caller container, so nothing the caller does now can reach the
        # encoding, the size check, or the request.
        try:
            encoded = _json.dumps(root, allow_nan=False, ensure_ascii=False)
        except (_ValueError, _TypeError, _RecursionError):
            # Unreachable for a document the walk accepted; kept so the function
            # is total rather than relying on that reasoning holding forever.
            return "schema-not-serializable", None

        # Every accepted element is an exact built-in, but an exact `_str` may
        # still hold an unpaired UTF-16 surrogate. `json.dumps` accepts one and
        # emits it verbatim; the transport cannot. Encoding the document here is
        # the only place that discovers it while a refusal is still possible -
        # left to the SDK it surfaces as an uncaught UnicodeEncodeError from
        # inside `complete_structured`, which this contract promises never to do.
        try:
            encoded.encode("utf-8")
        except _UnicodeEncodeError:
            return "schema-not-utf8-encodable", None

        if _len(encoded) > _SCHEMA_MAX_CHARS:
            return "schema-too-large", None
        return None, root

    return _validated_snapshot


_validated_snapshot = _closed_snapshot_validator()


def _closed_response_format_builder():
    """Build :func:`build_response_format`, builtins bound in cells."""
    _type = type
    _str = str

    def build_response_format(
        dialect: str, request: StructuredOutputRequest
    ) -> Optional[dict[str, Any]]:
        """Build the dialect-exact ``response_format`` object, or ``None``.

        Callers must validate first; :func:`plan_structured_request` is the
        supported entry point and calls this only after every check passed.

        The dispatch is an inlined chain of exact-string comparisons against
        builtins bound in closure cells. It reads no module-level mapping and
        no module-level builtin, so neither rebinding
        :data:`SUPPORTED_DIALECTS` or :data:`DIALECT_WIRE_SHAPES` nor
        rebinding ``type``/``str`` on this module can redirect a dialect to
        another runtime's shape, admit a ``str`` subclass, or introduce a
        fifth. An unrecognised dialect falls through to ``None``, which every
        caller treats as a refusal.
        """
        if _type(dialect) is not _str:
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
            # The wire name is an inlined literal, NOT a read of
            # STRUCTURED_WIRE_NAME. This is the one value in the object that both
            # leaves the process and is not caller data, so resolving it through
            # a module attribute would have put arbitrary text on the wire for
            # anyone able to rebind that attribute - reopening by the back door
            # the exact leak that removing the caller-supplied name closed.
            return {
                "type": "json_schema",
                "json_schema": {"name": "structured_output", "schema": schema},
            }
        if dialect == "sglang":
            # Byte-identical to vLLM today; kept as its own branch so a future
            # divergence cannot be hidden behind a shared one. Same inlined
            # literal, for the same reason.
            return {
                "type": "json_schema",
                "json_schema": {"name": "structured_output", "schema": schema},
            }
        return None

    return build_response_format


build_response_format = _closed_response_format_builder()


def _closed_planner():
    """Build :func:`plan_structured_request`, dependencies bound in cells.

    The planner is the single supported entry point, so every name it
    resolved was a way to change what a caller got back without touching
    the planner itself: the dialect predicate, the request type it checks
    against, the validator that builds the snapshot, the builder that shapes
    it, the carrier that validates the result, and the two builtins the
    exact-type checks use. All of them are bound here instead.
    """
    _type = type
    _str = str
    _dialect_ok = is_supported_dialect
    _request_type = StructuredOutputRequest
    _snapshot = _validated_snapshot
    _build = build_response_format
    _Plan = StructuredRequestPlan

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
        6. ``schema-*``                 - see :func:`_validated_snapshot`.

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
            return _Plan(ok=False, refusal="dialect-not-configured")
        if _type(dialect) is not _str:
            return _Plan(ok=False, refusal="dialect-not-exact-str")
        if not _dialect_ok(dialect):
            return _Plan(ok=False, refusal="dialect-unsupported")
        if _type(request) is not _request_type:
            return _Plan(ok=False, refusal="request-not-exact-type")
        if has_tools is not False:
            return _Plan(
                ok=False, refusal="tools-with-structured-unsupported"
            )

        # Validation and snapshotting are one traversal, so the accepted
        # snapshot is exactly the document that was inspected. `_validated_snapshot`
        # never reads a caller container twice, which is what removes the window
        # an earlier revision had between checking the caller's data and
        # serialising it.
        #
        # The snapshot matters because `StructuredOutputRequest` is frozen and
        # freezing a field does not freeze the object it points at: the caller
        # still holds the very dict that was walked, and could mutate it after
        # the checks passed. Every guarantee above would then describe a document
        # that is no longer the one being sent.
        schema_refusal, snapshot = _snapshot(request.schema)
        if schema_refusal is not None:
            return _Plan(ok=False, refusal=schema_refusal)
        if snapshot is None:
            # Unreachable while the acceptance path always returns a snapshot.
            # Written as a refusal rather than an assert so that behaviour is
            # identical under -O and -OO, where asserts are stripped out.
            return _Plan(ok=False, refusal="schema-not-serializable")

        response_format = _build(
            dialect, _request_type(schema=snapshot)
        )
        if response_format is None:
            # Unreachable while the dispatch and the guard agree; if they ever
            # drift, drift refuses rather than sending an unshaped request.
            return _Plan(ok=False, refusal="dialect-unsupported")
        return _Plan(ok=True, response_format=response_format)

    return plan_structured_request


plan_structured_request = _closed_planner()


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
    "is_pre_dialect_refusal",
    "is_supported_dialect",
    "is_supported_wire_shape",
    "plan_structured_request",
]
