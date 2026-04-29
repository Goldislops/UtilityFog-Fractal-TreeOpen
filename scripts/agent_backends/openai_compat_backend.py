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
"""

from __future__ import annotations

import json
import os
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
        """
        self.model = model
        self.extra_headers = dict(extra_headers) if extra_headers else None
        if client is not None:
            self._client = client
            return
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError(
                "OpenAICompatBackend requires `pip install openai`"
            ) from e
        kwargs: dict[str, Any] = {}
        if api_key is not None:
            kwargs["api_key"] = api_key
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
        if tools:
            request["tools"] = [self._tool_to_wire(t) for t in tools]
        if self.extra_headers:
            request["extra_headers"] = dict(self.extra_headers)

        response = self._client.chat.completions.create(**request)
        return self._response_from_wire(response)

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
        if isinstance(m.content, str):
            # bare string content — pass through, role unchanged.
            return [{"role": m.role, "content": m.content}]

        # Block-list content. Behaviour depends on role.
        if m.role == "assistant":
            # Combine TextBlocks into `content`, ToolUseBlocks into `tool_calls`.
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for b in m.content:
                if isinstance(b, TextBlock):
                    text_parts.append(b.text)
                elif isinstance(b, ToolUseBlock):
                    tool_calls.append({
                        "id": b.id,
                        "type": "function",
                        "function": {
                            "name": b.name,
                            "arguments": json.dumps(b.input or {}, default=str),
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
                if isinstance(b, ToolResultBlock):
                    if isinstance(b.content, str):
                        result_content = b.content
                    else:
                        # If a ToolResult contains nested blocks, JSON-encode
                        # them so the receiving model has a stable string.
                        result_content = json.dumps(
                            [_block_to_summary_dict(bb) for bb in b.content],
                            default=str,
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
                elif isinstance(b, TextBlock):
                    text_parts.append(b.text)
                # ToolUseBlock on user role doesn't make sense; skip.
            if text_parts:
                out.append({"role": "user", "content": "\n".join(text_parts)})
            return out

        # role == "system" with block-list content: collapse to a single
        # system message with concatenated text.
        text_parts = [b.text for b in m.content if isinstance(b, TextBlock)]
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
        choices = _attr_or_key(response, "choices", None) or []
        if not choices:
            return AgentResponse.from_content([], stop_reason="other", usage={})
        choice = choices[0]
        msg = _attr_or_key(choice, "message", None)

        blocks: list[ContentBlock] = []
        text = _attr_or_key(msg, "content", None) if msg is not None else None
        if isinstance(text, str) and text:
            blocks.append(TextBlock(text=text))

        tool_calls = _attr_or_key(msg, "tool_calls", None) if msg is not None else None
        if tool_calls:
            for tc in tool_calls:
                tc_type = _attr_or_key(tc, "type", "function")
                if tc_type != "function":
                    continue  # unknown tool-call kind; ignore for now
                fn = _attr_or_key(tc, "function", None)
                if fn is None:
                    continue
                name = _attr_or_key(fn, "name", "") or ""
                args_raw = _attr_or_key(fn, "arguments", "") or ""
                try:
                    args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
                except (ValueError, TypeError):
                    args = {"_raw_arguments": str(args_raw)}
                blocks.append(ToolUseBlock(
                    id=_attr_or_key(tc, "id", "") or "",
                    name=name,
                    input=args,
                ))

        raw_finish = _attr_or_key(choice, "finish_reason", "stop") or "stop"
        stop_reason: StopReason = _FINISH_REASON_MAP.get(raw_finish, "other")

        usage_obj = _attr_or_key(response, "usage", None)
        usage: dict[str, Any] = {}
        if usage_obj is not None:
            usage = {
                "input_tokens": _attr_or_key(usage_obj, "prompt_tokens", None),
                "output_tokens": _attr_or_key(usage_obj, "completion_tokens", None),
            }

        return AgentResponse.from_content(blocks, stop_reason=stop_reason, usage=usage)


# -- helpers ----------------------------------------------------------------


def _attr_or_key(obj: Any, name: str, default: Any = None) -> Any:
    """Read `name` from an object via attribute access, falling back to dict."""
    if obj is None:
        return default
    val = getattr(obj, name, None)
    if val is not None:
        return val
    if isinstance(obj, dict):
        return obj.get(name, default)
    return default


def _block_to_summary_dict(b: ContentBlock) -> dict[str, Any]:
    """Best-effort summary dict for nested blocks inside a ToolResultBlock.
    Only used as a fallback when a tool result wraps richer content; the
    OpenAI protocol expects a string for tool messages so we serialize."""
    if isinstance(b, TextBlock):
        return {"type": "text", "text": b.text}
    if isinstance(b, ToolUseBlock):
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": dict(b.input)}
    return {"type": type(b).__name__}


__all__ = ["OpenAICompatBackend", "DEFAULT_MODEL"]
