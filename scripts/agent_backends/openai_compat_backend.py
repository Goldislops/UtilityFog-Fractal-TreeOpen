"""Phase 18 PR 7 — OpenAICompatBackend: provider-neutral concrete `AgentBackend`.

One backend class, many configurations. Talks to anything that speaks
OpenAI's `/v1/chat/completions` shape:

  - OpenAI itself (api.openai.com)
  - NVIDIA NIM (integrate.api.nvidia.com)
  - DeepSeek (api.deepseek.com)
  - Together / Fireworks / Anyscale (cloud aggregators)
  - vLLM, SGLang, Ollama, llama.cpp server (self-hosted)

NemoCloud is no longer a separate class — it's an `OpenAICompatBackend`
configured with NIM's base_url and a Nemotron model name. See
`BACKEND_PROVIDER_MATRIX.md` for the canonical taxonomy and provider
table.

## Design choices (deliberately boring)

- Uses the official `openai` Python SDK (>= 1.0). Setting `base_url`
  redirects it at any compatible endpoint; the SDK handles auth,
  retries, JSON serialization. One small dep, less hand-rolled HTTP.
- No streaming, no reasoning models, no extended-thinking output blocks.
  These are real OpenAI features but each is a config / response-shape
  branch we don't need yet. Phase 18 PR 8 (parity proof) doesn't need
  them. Future PR if/when warranted.
- Strict translation between this project's content-block dataclasses
  (PR 4 / PR 5 shape) and OpenAI's `tool_calls`/`role: tool` wire shape.
  See `_message_to_wire` for the explosion rule on `ToolResultBlock`s.

## Translation differences vs `AnthropicBackend`

| Concern | Anthropic | OpenAI-compat |
|---------|-----------|---------------|
| System prompt | top-level `system=` param | first message with `role="system"` |
| Tool spec | `{name, description, input_schema}` | `{type:"function", function:{name, description, parameters}}` |
| Assistant tool use | inline `ToolUseBlock` in content | separate `tool_calls` field on message; arguments are a JSON STRING |
| Tool result | user message containing `ToolResultBlock`s | separate `{role:"tool", tool_call_id, content}` per result |
| Tool error flag | `ToolResultBlock.is_error: bool` field | **NO native flag**; this backend prefixes content with `"[ERROR] "` when `is_error=True` (PR 7a). The orchestrator system prompt instructs models to recognise the marker. |
| Finish reason | `stop_reason` (`end_turn`, `tool_use`, …) | `finish_reason` (`stop`, `tool_calls`, `length`, `content_filter`) |
| Token counts | `usage.input_tokens` / `output_tokens` | `usage.prompt_tokens` / `completion_tokens` |

The translation table above is the entire contract; everything in this
file follows from it.

## OMI-V2 — structured output, and the interface decisions it forced

OMI-V2 adds one closed structured-output request path. Five decisions were
unavoidable to add it at all. They are recorded here rather than taken
silently, and each is the narrowest option that still delivered the package.

1. **A new method, not a changed signature.** Structured output arrives as
   `complete_structured()`, a method on this class. The alternative —
   adding a `structured=` keyword to `AgentBackend.complete()` — would
   change the abstract contract every backend implements, including
   `AnthropicBackend` and `MockBackend`, neither of which is in scope. The
   ABC is untouched, so `complete()` remains exactly the method every
   existing caller and backend already implements.

2. **The result is a new type, not an `AgentResponse`.** A refusal has to be
   distinguishable from a completion, and `AgentResponse` has nowhere to put
   a refusal code that is not also a place a caller could mistake for model
   output. `StructuredCompletion` wraps an `AgentResponse` on success.

3. **Response validation lives one layer up, not here.** Requirement: reuse
   `scripts/open_model/structured.py` rather than write a second validator.
   That module is in `scripts/open_model/`, which imports *this* package;
   importing it from here would invert the layering that
   `scripts/open_model/__init__.py` states explicitly. So this method returns
   the response and `scripts/open_model/structured_exchange.py` validates it
   there, reusing the existing validator unchanged. The request-side checks
   in `structured_request.py` are not a competing validator: they walk an
   outbound JSON Schema document, where `structured.py` parses an inbound
   response payload string.

4. **`dialect` is a constructor parameter, and an invalid one raises.** It is
   configuration, not a per-call argument, and an explicitly wrong value is a
   configuration error worth failing at construction. Omitting it preserves
   every pre-OMI-V2 behaviour of this class.

5. **Tools and structured output are refused together.** That combination was
   not verified at the pinned revisions of any of the four runtimes, and
   tool-choice work is out of scope. Refusing states the limit of the
   evidence; sending both and calling it supported would not.

Out of scope and untouched: tool-choice semantics, seed normalisation,
capability auto-detection, streaming, async, batching, TensorRT-LLM, and NIM.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, ClassVar, Optional

from scripts.agent_backends.base import (
    AgentBackend,
    AgentResponse,
    ContentBlock,
    Message,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
)
from scripts.agent_backends.structured_request import (
    REFUSAL_TOKENS,
    StructuredDialect,
    StructuredOutputRequest,
    StructuredRefusal,
    is_pre_dialect_refusal,
    is_supported_dialect,
    plan_structured_request,
)


DEFAULT_MODEL = os.environ.get("MEDUSA_OPENAI_MODEL", "gpt-4o-mini")
"""Sensible default for the OpenAI provider itself; orchestrator config
(or a per-call kwarg) will override per-provider."""

# Map OpenAI finish_reason → our StopReason literal.
_FINISH_REASON_MAP: dict[str, StopReason] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "other",
    "function_call": "tool_use",  # legacy
    "stop_sequence": "stop_sequence",
}


def _closed_identity_restorer():
    """Build :func:`_restore_identity`, builtins bound in closure cells."""
    _isinstance = isinstance
    _type = type
    _vars = vars
    _getattr = getattr
    _setattr = setattr

    def _restore_identity(obj, name: str, module_name: str):
        """Give a factory-built object its module-level public identity back.

        A class or function created inside a factory carries a ``<locals>``
        qualname. ``pickle`` resolves an object by ``__module__`` plus
        ``__qualname__``, so that name made every exported class and function
        unpicklable - a real compatibility regression, since the pre-OMI-V2
        backend pickled at both the base commit and the previous head. It also
        leaked the factory name into every frozen-dataclass ``repr``.

        Only the three identity attributes are touched, on the object and on
        its own methods. No captured authority is read, replaced or exposed:
        the closure cells are untouched, no defaulted parameter is
        reintroduced, and the object returned is the same object.
        """
        _setattr(obj, "__module__", module_name)
        _setattr(obj, "__name__", name)
        _setattr(obj, "__qualname__", name)
        if _isinstance(obj, _type):
            for member_name, member in _vars(obj).items():
                func = _getattr(member, "__func__", member)
                qualname = _getattr(func, "__qualname__", "")
                if "<locals>" in qualname:
                    _setattr(func, "__qualname__", name + "." + member_name)
                    _setattr(func, "__module__", module_name)
        return obj

    return _restore_identity


_restore_identity = _closed_identity_restorer()
_restore_identity.__qualname__ = "_restore_identity"

def _build_structured_completion_class():
    """Build :class:`StructuredCompletion` with its authorities in cells.

    These were defaulted parameters of ``__post_init__``. That closed name
    rebinding and opened a wider hole: a defaulted parameter is directly
    addressable, so no rebinding was needed to supply a different vocabulary
    or a different dialect authority - a keyword argument sufficed. Cells are
    not addressable, and the documented signature stays exactly as it reads.
    """
    _tokens = REFUSAL_TOKENS
    _dialect_ok = is_supported_dialect
    _pre_dialect = is_pre_dialect_refusal
    _agent_response = AgentResponse
    _type = type
    _str = str
    _bool = bool
    _ValueError = ValueError

    @dataclass(frozen=True)
    class StructuredCompletion:
        """Result of one `complete_structured()` call. Carries no schema content.

        `response_format_sent` is named for what it actually records: that the
        request carried a `response_format` object. It is NOT a claim that the
        runtime honoured the constraint, and nothing in this module reports such
        a claim. The output is validated above this layer, which establishes
        that it is a usable JSON object - not that it conforms to the schema
        that was sent. No layer of this package establishes conformance.

        On refusal, `refusal` is one token from the closed vocabulary in
        `structured_request.StructuredRefusal` and `response` is None. No schema
        fragment, key name, prompt, response text, byte offset, length, type
        name, or exception text is ever carried here.
        """

        ok: bool
        response: Optional[AgentResponse] = None
        refusal: Optional[StructuredRefusal] = None
        dialect: Optional[str] = None
        response_format_sent: bool = False

        def __post_init__(self) -> None:
            """Validate the carrier's own coherence.

            Every authority this method uses is read from a **closure cell**
            filled by the enclosing factory when the class was defined. Nothing
            is looked up at call time, so rebinding this module's imported
            aliases - ``REFUSAL_TOKENS``, ``is_supported_dialect`` - cannot
            widen what a completion accepts.

            The signature takes ``self`` and nothing else. An earlier revision
            bound these as defaulted ``_name=`` parameters, which closed name
            rebinding but left the authorities directly addressable by any
            caller willing to pass a keyword.
            """
            if _type(self.ok) is not _bool:
                raise _ValueError("ok must be exactly a bool")
            if _type(self.response_format_sent) is not _bool:
                raise _ValueError("response_format_sent must be exactly a bool")
            if self.refusal is not None and (
                _type(self.refusal) is not _str or self.refusal not in _tokens
            ):
                raise _ValueError("refusal must be a token from the closed vocabulary")
            if self.dialect is not None and not _dialect_ok(self.dialect):
                raise _ValueError("dialect must be a verified dialect token or None")
            # Cross-field dialect coherence. A result that names no dialect when
            # one was established, or names one when none was, is a result an
            # operator cannot act on: they cannot tell which runtime it concerns.
            if self.ok and self.dialect is None:
                raise _ValueError("a successful completion must name its dialect")
            if not self.ok and _pre_dialect(self.refusal):
                if self.dialect is not None:
                    raise _ValueError(
                        "a refusal taken before the dialect gate cannot name a dialect"
                    )
            elif not self.ok and self.dialect is None:
                raise _ValueError(
                    "a refusal taken after the dialect gate must name its dialect"
                )
            if self.ok and self.refusal is not None:
                raise _ValueError("a successful completion cannot carry a refusal code")
            if not self.ok and self.refusal is None:
                raise _ValueError("a refused completion must carry a refusal code")
            if not self.ok and self.response is not None:
                raise _ValueError("a refused completion must not carry a response")
            if not self.ok and self.response_format_sent:
                raise _ValueError("a refused completion cannot have sent a request")
            if self.ok and self.response is None:
                raise _ValueError("a successful completion must carry a response")
            # Exact type, not merely non-None. A caller reading `.response` on a
            # successful completion is entitled to an AgentResponse, and
            # `structured_exchange.request_structured_json` reads `.text` off it
            # while promising to be total: a foreign object here would make that
            # promise false by raising AttributeError from inside it. Checking
            # only for None made the exact-type guard on this class skin-deep.
            if self.ok and _type(self.response) is not _agent_response:
                raise _ValueError(
                    "a successful completion must carry an exact AgentResponse"
                )
            if self.ok and not self.response_format_sent:
                raise _ValueError("a successful completion must have sent a request")

    return StructuredCompletion


StructuredCompletion = _restore_identity(_build_structured_completion_class(), "StructuredCompletion", __name__)


def _build_backend_class():
    """Build :class:`OpenAICompatBackend` with every authority in cells.

    An earlier revision bound the dialect authority, the planner, the result
    carrier and several builtins as DEFAULTED PARAMETERS of ``__init__``,
    ``complete_structured`` and ``_response_from_wire``. That closed name
    rebinding and opened a wider hole: a defaulted parameter is directly
    addressable, so no rebinding was needed at all. A caller could write

        OpenAICompatBackend(..., dialect="sk-...", _dialect_ok=lambda v: True)
        backend.complete_structured(..., _plan=lambda *a, **k: FakePlan())

    and admit a secret-shaped dialect, or put an arbitrary object on the wire
    as the `response_format`. A capture a caller can pass is not a capture; it
    is an injection point with a leading underscore.

    Binding them in this factory puts them in cells no caller can address,
    and leaves every documented public signature exactly as it reads -
    passing a former capture keyword now raises TypeError.

    The class is wrapped rather than each method individually so that the
    whole translation path, not just the structured-output path, shares one
    audited set of captures.
    """
    _dialect_ok = is_supported_dialect
    _plan = plan_structured_request
    _Completion = StructuredCompletion
    _agent_response = AgentResponse
    _TextBlock = TextBlock
    _ToolUseBlock = ToolUseBlock
    _ToolResultBlock = ToolResultBlock
    _attr = _attr_or_key
    _block_summary = _block_to_summary_dict
    _json = json
    _os = os
    _type = type
    _str = str
    _dict = dict
    _list = list
    _bool = bool
    _isinstance = isinstance
    _ValueError = ValueError
    _RuntimeError = RuntimeError
    _ImportError = ImportError
    _RecursionError = RecursionError
    _float = float
    _INF = float("inf")

    def _refuse_constant_token(_token: str) -> Any:
        """``json.loads`` calls this for a ``NaN`` / ``Infinity`` /
        ``-Infinity`` token inside a tool-call ``arguments`` string.

        Raising ``_ValueError`` lands in the established except-branch of the
        ``arguments`` decode, which folds the whole string into the
        raw-fallback shape: the model's bytes stay available verbatim, and no
        non-finite float enters a block. The hook receives a substring of a
        proven exact ``str`` - no caller code runs.
        """
        raise _ValueError("non-finite")

    def _finite_float_or_refuse(token: str) -> float:
        """``json.loads`` calls this for every ``arguments`` number that is
        not an integer.

        The default decoder builds floats with ``float(token)``, which maps
        an overflowing literal such as ``1e400`` to an infinity rather than
        raising - the same gap OMI-V1 closed on its own inbound path. Here
        the consequence is outbound: a non-finite float admitted into
        ``ToolUseBlock.input`` re-serializes, on assistant replay, into the
        ``arguments`` field the translation table promises is a JSON STRING -
        as an ``Infinity`` / ``NaN`` token no strict parser accepts. Refusing
        where the number is built folds the payload into the raw-fallback
        shape instead. The guard is against non-finiteness itself, not a
        spelling list.
        """
        value = _float(token)
        if value != value or value == _INF or value == -_INF:
            raise _ValueError("non-finite")
        return value


    class OpenAICompatBackend(AgentBackend):
        """Concrete `AgentBackend` over the OpenAI-compatible chat completions API."""

        name: ClassVar[str] = "openai-compat"

        def __init__(
            self,
            *,
            base_url: Optional[str] = None,
            model: str = DEFAULT_MODEL,
            api_key: Optional[str] = None,
            extra_headers: Optional[dict[str, str]] = None,
            client: Optional[Any] = None,
            dialect: Optional[str] = None,
        ) -> None:
            """Build an OpenAICompatBackend.

            Args:
                base_url: Provider endpoint (e.g. `"https://api.deepseek.com/v1"`,
                    `"http://localhost:11434/v1"` for Ollama). If None, the SDK
                    uses OpenAI's default `https://api.openai.com/v1`.
                model: Model identifier passed as `model=`. Provider-specific.
                api_key: Optional API key; if None, the SDK reads `OPENAI_API_KEY`
                    (or whichever env var the SDK is configured to use).
                extra_headers: Optional headers added to every request — for
                    providers that require non-Bearer auth schemes or routing
                    hints.
                client: Pre-built SDK client. If provided, `base_url`, `api_key`,
                    and `extra_headers` are ignored — used for test injection.
                dialect: OMI-V2. Optional runtime dialect enabling
                    `complete_structured()`. Must be supplied EXPLICITLY and must
                    name a runtime with a verified wire shape — see
                    `scripts/agent_backends/structured_request.py`. It is never
                    inferred from `base_url`, from installed software, from the
                    environment, or from a probe, because none of those identify
                    a runtime reliably: `base_url` is caller-chosen text, a local
                    port says nothing about what is listening on it, and probing
                    would mean contacting an endpoint to decide how to talk to
                    it. A present-but-unrecognised value raises `ValueError` HERE,
                    at construction, rather than at first use — an explicitly
                    wrong dialect is a configuration error, and failing at the
                    point of configuration is the earliest possible fail-closed.
                    `None` (the default) leaves the instance exactly as it was
                    before OMI-V2: `complete()` is unaffected, and
                    `complete_structured()` refuses with `dialect-not-configured`.

            Raises:
                ValueError: if `dialect` is supplied but is not one of the
                    verified dialect tokens. The message names the parameter and
                    the closed vocabulary, both of which are fixed constants; no
                    supplied value, type name, or representation is echoed.
            """
            # Validated FIRST, before any SDK client is constructed, so a
            # misconfigured instance never reaches the point of holding a client.
            if dialect is not None and not _dialect_ok(dialect):
                raise _ValueError(
                    "dialect must be one of: llama-cpp, ollama, vllm, sglang"
                )
            self.dialect: Optional[str] = dialect
            self.model = model
            self.extra_headers = _dict(extra_headers) if extra_headers else None
            if client is not None:
                self._client = client
                return
            try:
                from openai import OpenAI
            except _ImportError as e:
                raise _RuntimeError(
                    "OpenAICompatBackend requires `pip install openai`"
                ) from e
            kwargs: dict[str, Any] = {}

            # PR 7b: the OpenAI SDK raises at construction if no api_key is set
            # AND OPENAI_API_KEY env var is empty. That's hostile when talking
            # to a passwordless local server (Ollama, vLLM, llama.cpp). If the
            # caller didn't supply a key and the env var isn't set, supply a
            # placeholder so construction succeeds. Real auth-required providers
            # (DeepSeek, NIM, etc.) will fail later with a clear 401, which is
            # a much better failure mode than crashing at startup.
            effective_key = api_key
            if effective_key is None and not _os.environ.get("OPENAI_API_KEY"):
                effective_key = "not-needed"  # placeholder for SDKs that demand a string

            if effective_key is not None:
                kwargs["api_key"] = effective_key
            if base_url is not None:
                kwargs["base_url"] = base_url
            self._client = OpenAI(**kwargs)

        # -- the one contract method --------------------------------------------

        def complete(
            self,
            messages: list[Message],
            tools: list[ToolSpec],
            *,
            system: Optional[str] = None,
            max_tokens: int = 2048,
            temperature: float = 0.0,
        ) -> AgentResponse:
            request = self._build_request(
                messages,
                tools,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            response = self._client.chat.completions.create(**request)
            return self._response_from_wire(response)

        def _build_request(
            self,
            messages: list[Message],
            tools: list[ToolSpec],
            *,
            system: Optional[str] = None,
            max_tokens: int = 2048,
            temperature: float = 0.0,
            include_tools: Optional[bool] = None,
        ) -> dict[str, Any]:
            """Assemble the outbound request dict. Extracted verbatim from
            `complete()` in OMI-V2 so that `complete()` and `complete_structured()`
            provably build the SAME request, and the legacy shape is defined in
            exactly one place. This body is unchanged from the pre-OMI-V2
            `complete()`; the existing backend suite exercises it through
            `complete()` and therefore proves the legacy shape did not move.

            `include_tools` exists only to close a time-of-check/time-of-use gap
            in `complete_structured()`. Left as None - which is what `complete()`
            passes, and therefore what every pre-OMI-V2 call site does - this
            method truth-tests `tools` exactly as it always has. A caller that has
            ALREADY truth-tested `tools` to make a decision passes the result it
            got, so the decision and the request are built from one evaluation
            rather than two. A `tools` object whose `__bool__` answers differently
            on a second call can then no longer make the two disagree.
            """
            wire_messages = []
            if system is not None:
                wire_messages.append({"role": "system", "content": system})
            for m in messages:
                wire_messages.extend(self._message_to_wire(m))

            request: dict[str, Any] = {
                "model": self.model,
                "messages": wire_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            attach_tools = _bool(tools) if include_tools is None else include_tools
            if attach_tools:
                request["tools"] = [self._tool_to_wire(t) for t in tools]
            if self.extra_headers:
                request["extra_headers"] = _dict(self.extra_headers)
            return request

        # -- OMI-V2: structured output ------------------------------------------

        def complete_structured(
            self,
            messages: list[Message],
            tools: list[ToolSpec],
            *,
            structured: Any,
            system: Optional[str] = None,
            max_tokens: int = 2048,
            temperature: float = 0.0,
        ) -> "StructuredCompletion":
            """Ask the configured runtime for schema-constrained decoding.

            Returns a :class:`StructuredCompletion` for every input reachable
            through the contract; it never raises to signal a refused request.
            Two exception families still propagate, both shared with
            `complete()`: transport-level errors from the SDK, and - raised
            before any transport - the fixed, non-disclosing error for a
            message whose tool-call arguments cannot be encoded as strict
            JSON (`_message_to_wire` serializes the history for both entry
            points). Neither is a refusal; refusals are values, and the
            refusal vocabulary is untouched by either.

            The refusal gate runs to completion BEFORE `self._client` is read at
            all. That ordering is the point of the method, not an implementation
            detail: a refused request must not become a billed, logged, or
            rate-limited call against a runtime. `test_omi_v2_backend.py` proves
            it with a client whose every attribute access raises.

            This method deliberately does NOT validate the response. It reports
            whether a `response_format` was *sent*, which is not the same as the
            runtime having honoured it - see the module docstring of
            `structured_request.py` for the Ollama case where an unrecognised
            request degrades silently to unconstrained output. The response is
            checked one layer up by `scripts/open_model/structured_exchange.py`,
            which reuses `scripts/open_model/structured.py` - and that check
            establishes JSON-object and required-key usability, NOT schema
            conformance. See `StructuredExchange.schema_conformance`.
            """
            # Gate first, on ONE evaluation of `tools`. The result is reused
            # below rather than recomputed: an earlier revision truth-tested
            # `tools` here and again inside `_build_request`, and a `tools` object
            # whose `__bool__` returned False then True passed the gate as
            # tool-free and still had its tools attached alongside the
            # `response_format` - defeating the very combination this refuses.
            has_tools = _bool(tools)
            plan = _plan(self.dialect, structured, has_tools=has_tools)
            if not plan.ok:
                return _Completion(
                    ok=False,
                    refusal=plan.refusal,
                    dialect=self.dialect if _dialect_ok(self.dialect) else None,
                    response_format_sent=False,
                )

            request = self._build_request(
                messages,
                tools,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                include_tools=has_tools,
            )
            # The ONLY key OMI-V2 adds. There is no extra_body, no kwargs
            # passthrough, and no provider-specific escape hatch by which a
            # caller could reach any other request field.
            request["response_format"] = plan.response_format

            response = self._client.chat.completions.create(**request)
            return _Completion(
                ok=True,
                response=self._response_from_wire(response),
                dialect=self.dialect,
                response_format_sent=True,
            )

        # -- wire translation (outbound) ---------------------------------------

        @staticmethod
        def _message_to_wire(m: Message) -> list[dict[str, Any]]:
            """Translate a `Message` to one or MORE OpenAI wire messages.

            Most cases produce one message. The exception is a user-role message
            whose content is a list containing `ToolResultBlock`s — each
            ToolResultBlock becomes its own `{"role": "tool", ...}` message
            in OpenAI's protocol, and any plain text accompanying them
            becomes a separate user message. This is the explosion rule.
            """
            if _isinstance(m.content, _str):
                # bare string content — pass through, role unchanged.
                return [{"role": m.role, "content": m.content}]

            # Block-list content. Behaviour depends on role.
            if m.role == "assistant":
                # Combine TextBlocks into `content`, ToolUseBlocks into `tool_calls`.
                text_parts: list[str] = []
                tool_calls: list[dict[str, Any]] = []
                for b in m.content:
                    if _isinstance(b, _TextBlock):
                        text_parts.append(b.text)
                    elif _isinstance(b, _ToolUseBlock):
                        # The translation table promises `arguments` is a JSON
                        # STRING; `allow_nan=False` is what makes that true.
                        # The default encoder spells a non-finite float as the
                        # Infinity / NaN token RFC 8259 forbids - and the
                        # exact-dict `arguments` path above, or a caller-built
                        # block, can put such a float in `input`.
                        try:
                            arguments = _json.dumps(
                                b.input or {}, default=_str, allow_nan=False
                            )
                        except _ValueError:
                            # Fixed, truthful, and cause-agnostic: the encoder
                            # raises ValueError both for a non-finite float and
                            # for a circular container, so the replacement
                            # names the failure - not a presumed cause - and
                            # discloses no value, name, or structure; `from
                            # None` keeps the encoder's own text out. Loud
                            # beats the ABC's stop_reason="error" translation
                            # here: this is deterministic caller-side data the
                            # wire cannot carry, not an API failure, and an
                            # empty response would bury it.
                            raise _ValueError(
                                "tool-call arguments could not be encoded as "
                                "strict JSON"
                            ) from None
                        tool_calls.append({
                            "id": b.id,
                            "type": "function",
                            "function": {
                                "name": b.name,
                                "arguments": arguments,
                            },
                        })
                    # ToolResultBlock on assistant role doesn't make sense; skip.
                wire: dict[str, Any] = {"role": "assistant"}
                wire["content"] = "\n".join(text_parts) if text_parts else None
                if tool_calls:
                    wire["tool_calls"] = tool_calls
                return [wire]

            if m.role == "user":
                # Explode ToolResultBlocks into role:tool messages; collect any
                # other text/tool_use into a plain user message at the end.
                out: list[dict[str, Any]] = []
                text_parts: list[str] = []
                for b in m.content:
                    if _isinstance(b, _ToolResultBlock):
                        if _isinstance(b.content, _str):
                            result_content = b.content
                        else:
                            # If a ToolResult contains nested blocks, JSON-encode
                            # them so the receiving model has a stable string.
                            result_content = _json.dumps(
                                [_block_summary(bb) for bb in b.content],
                                default=_str,
                            )
                        # PR 7a: OpenAI's `role:"tool"` message has no `is_error`
                        # field analogous to Anthropic's ToolResultBlock.is_error.
                        # When the source side flagged an error, prefix the content
                        # with a stable marker so the receiving model can tell the
                        # tool failed. The system prompt instructs the model to
                        # recognise "[ERROR] ..." as failure. (Without this fix,
                        # a tool failure looks like a normal tool success to an
                        # OpenAI-compatible model.)
                        if b.is_error:
                            result_content = "[ERROR] " + result_content
                        out.append({
                            "role": "tool",
                            "tool_call_id": b.tool_use_id,
                            "content": result_content,
                        })
                    elif _isinstance(b, _TextBlock):
                        text_parts.append(b.text)
                    # ToolUseBlock on user role doesn't make sense; skip.
                if text_parts:
                    out.append({"role": "user", "content": "\n".join(text_parts)})
                return out

            # role == "system" with block-list content: collapse to a single
            # system message with concatenated text.
            text_parts = [b.text for b in m.content if _isinstance(b, _TextBlock)]
            return [{"role": "system", "content": "\n".join(text_parts) or "(system blocks)"}]

        @staticmethod
        def _tool_to_wire(t: ToolSpec) -> dict[str, Any]:
            return {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }

        # -- wire translation (inbound) ----------------------------------------

        @staticmethod
        def _response_from_wire(response: Any) -> AgentResponse:
            """Convert an OpenAI-compatible ChatCompletion into our `AgentResponse`.

            Supported containers are SDK-style typed objects (ordinary attribute
            access, which is inherent to supporting them) and exact built-in dicts
            (built-in lookup first); dict SUBCLASSES are refused as unsupported
            mapping containers without invoking their overridden `.get()` or
            attribute hooks — see `_attr_or_key`. Arbitrary hostile NON-dict
            proxies are outside the supported SDK-object contract (supporting real
            SDK typed objects requires ordinary attribute access). This matches the
            established AnthropicBackend boundary contract.

            Within that contract decoding is total and hook-free over extracted
            field values: `choices` and `tool_calls` are iterated only after an
            exact-`list` proof (a list SUBCLASS is refused); `content`, the
            tool-call `type` discriminator, `finish_reason`, and the tool-call
            `id`/`name` are exact-type-checked before any truth, equality, hashing,
            iteration, mapping-conversion, or string-conversion could run, and
            `id`/`name` are handed to `ToolUseBlock` for its established
            normalization (no truth-testing `or`). `finish_reason` keeps the
            established semantics — absent, None, or empty exact string →
            "end_turn"; a known exact string → its mapped value; any other exact
            string → "other"; a non-string → "other". A dict-subclass `usage`
            container is refused to empty usage.
            """
            choices = _attr(response, "choices", None)
            if _type(choices) is not _list or not choices:
                return _agent_response.from_content([], stop_reason="other", usage={})
            choice = choices[0]
            msg = _attr(choice, "message", None)

            blocks: list[ContentBlock] = []
            text = _attr(msg, "content", None) if msg is not None else None
            if _type(text) is _str and text:
                blocks.append(_TextBlock(text=text))

            tool_calls = _attr(msg, "tool_calls", None) if msg is not None else None
            if _type(tool_calls) is _list:
                for tc in tool_calls:
                    tc_type = _attr(tc, "type", "function")
                    # The discriminator is proven exact str before the equality
                    # check, so a non-str / hostile-__eq__ type never runs a hook.
                    if _type(tc_type) is not _str or tc_type != "function":
                        continue  # unknown / absent-typed tool-call kind; ignore
                    fn = _attr(tc, "function", None)
                    if fn is None:
                        continue
                    name = _attr(fn, "name", "")
                    # `arguments` is model/server-reachable and can be any value,
                    # so decoding is total and hook-free: the value's truthiness,
                    # iteration, mapping-conversion, and string-conversion hooks
                    # are never invoked (the two decoder hooks bound above run
                    # on substrings of a proven exact str - no caller code).
                    # Exact strings are parsed (JSON object → kept; other valid
                    # JSON → {}; undecodable, parser recursion, or any
                    # non-finite number - a NaN/Infinity/-Infinity token or an
                    # overflowing literal like 1e400 - → the established
                    # raw-fallback shape, keeping the bytes available while no
                    # non-finite float can reach a block and later re-serialize
                    # into the `arguments` JSON STRING the translation table
                    # promises); exact dicts continue into ToolUseBlock's
                    # hardened normalization; every other value — absent
                    # included — becomes a fresh {}. MemoryError is
                    # deliberately not caught.
                    args_raw = _attr(fn, "arguments", None)
                    if _type(args_raw) is _str:
                        if args_raw == "":
                            args = {}
                        else:
                            try:
                                parsed = _json.loads(
                                    args_raw,
                                    parse_constant=_refuse_constant_token,
                                    parse_float=_finite_float_or_refuse,
                                )
                            except (_ValueError, _RecursionError):
                                args = {"_raw_arguments": args_raw}
                            else:
                                args = parsed if _type(parsed) is _dict else {}
                    elif _type(args_raw) is _dict:
                        args = args_raw
                    else:
                        args = {}
                    # `id`/`name` are handed to ToolUseBlock unchanged (no `or`
                    # truth-test); ToolUseBlock keeps them only when exactly str.
                    blocks.append(_ToolUseBlock(
                        id=_attr(tc, "id", ""),
                        name=name,
                        input=args,
                    ))

            # finish_reason: preserve established absent/None/empty → "end_turn";
            # exact-type-checked before the mapping lookup so a non-str value is
            # never hashed or compared (no __hash__/__eq__ hook).
            raw_finish = _attr(choice, "finish_reason", None)
            # Inlined, not a mapping lookup. `_FINISH_REASON_MAP` is a plain
            # module-level dict, so it was both rebindable AND mutable in place -
            # `_FINISH_REASON_MAP["stop"] = <anything>` put arbitrary text into
            # `AgentResponse.stop_reason`, a field whose whole value is that it
            # comes from a closed vocabulary. Inlining makes every branch produce
            # a literal from that vocabulary and nothing else. The mapping remains
            # exported as an inspection mirror, with a drift guard.
            if raw_finish is None:
                stop_reason: StopReason = "end_turn"
            elif _type(raw_finish) is not _str:
                stop_reason = "other"
            elif raw_finish == "" or raw_finish == "stop":
                stop_reason = "end_turn"
            elif raw_finish == "tool_calls" or raw_finish == "function_call":
                stop_reason = "tool_use"
            elif raw_finish == "length":
                stop_reason = "max_tokens"
            elif raw_finish == "stop_sequence":
                stop_reason = "stop_sequence"
            else:
                stop_reason = "other"

            usage_obj = _attr(response, "usage", None)
            if _isinstance(usage_obj, _dict) and _type(usage_obj) is not _dict:
                usage_obj = None  # dict-subclass usage container refused → empty usage
            usage: dict[str, Any] = {}
            if usage_obj is not None:
                usage = {
                    "input_tokens": _attr(usage_obj, "prompt_tokens", None),
                    "output_tokens": _attr(usage_obj, "completion_tokens", None),
                }

            return _agent_response.from_content(blocks, stop_reason=stop_reason, usage=usage)

    return OpenAICompatBackend




# -- helpers ----------------------------------------------------------------


def _closed_attr_or_key():
    """Build :func:`_attr_or_key`, builtins bound in cells."""
    _type = type
    _dict = dict
    _isinstance = isinstance
    _getattr = getattr

    def _attr_or_key(obj: Any, name: str, default: Any = None) -> Any:
        """Read `name` from a supported container, else return `default`.

        Supported-container contract (matches AnthropicBackend._attr_or_key):
          - an exact built-in dict takes the built-in dict lookup path first
            (its `.get` cannot be overridden);
          - a dict SUBCLASS is refused as an unsupported mapping container —
            checked before any attribute access, so neither its overridden
            `.get()` nor its attribute hooks are ever invoked;
          - anything else keeps ordinary attribute access, which is inherent to
            supporting SDK-style typed objects (and SimpleNamespace test fixtures);
          - missing fields return `default`.

        Arbitrary hostile NON-dict proxies (objects with adversarial `__getattr__`)
        are outside the supported SDK-object contract: supporting real SDK typed
        objects requires ordinary attribute access, and JSON received through an
        ordinary provider deserializes to builtins only, so a dict subclass or a
        hostile proxy is unreachable via PUBLIC provider traffic and reachable only
        by DIRECT / injected-client construction.
        """
        if _type(obj) is _dict:
            return obj.get(name, default)
        if _isinstance(obj, _dict):
            return default
        val = _getattr(obj, name, None)
        if val is not None:
            return val
        return default

    return _attr_or_key


_attr_or_key = _restore_identity(_closed_attr_or_key(), "_attr_or_key", __name__)


def _closed_block_summary():
    """Build :func:`_block_to_summary_dict`, authorities bound in cells."""
    _type = type
    _dict = dict
    _isinstance = isinstance
    _TextBlock = TextBlock
    _ToolUseBlock = ToolUseBlock

    def _block_to_summary_dict(b: ContentBlock) -> dict[str, Any]:
        """Best-effort summary dict for nested blocks inside a ToolResultBlock.
        Only used as a fallback when a tool result wraps richer content; the
        OpenAI protocol expects a string for tool messages so we serialize."""
        if _isinstance(b, _TextBlock):
            return {"type": "text", "text": b.text}
        if _isinstance(b, _ToolUseBlock):
            return {"type": "tool_use", "id": b.id, "name": b.name, "input": _dict(b.input)}
        return {"type": _type(b).__name__}

    return _block_to_summary_dict


_block_to_summary_dict = _restore_identity(_closed_block_summary(), "_block_to_summary_dict", __name__)


OpenAICompatBackend = _restore_identity(_build_backend_class(), "OpenAICompatBackend", __name__)


__all__ = [
    "DEFAULT_MODEL",
    "OpenAICompatBackend",
    "StructuredCompletion",
    # Re-exported so a caller needs one import to build a structured request.
    "StructuredDialect",
    "StructuredOutputRequest",
]
