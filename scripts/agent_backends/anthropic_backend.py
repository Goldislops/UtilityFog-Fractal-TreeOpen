"""Phase 18 PR 5 — AnthropicBackend: the first real LLM plug for the ABC.

Concrete `AgentBackend` that speaks to Claude models through the official
`anthropic` Python SDK. Reads `ANTHROPIC_API_KEY` from the environment by
default; accepts an explicit key or a pre-built client for tests + advanced
setups. Model name is configurable — default is a sensible recent Opus,
but orchestrator config (PR 6) will override it per environment.

## Why this module isn't named `anthropic.py`

If the file were `scripts/agent_backends/anthropic.py`, doing `import anthropic`
from inside that same file would resolve to itself under Python's relative-
import semantics in some configurations. `anthropic_backend.py` avoids the
shadow entirely. The exported class is still `AnthropicBackend`.

## Error-handling philosophy

Per the `AgentBackend` contract:
  - **Transport errors** (auth failure, connection, 5xx) raise. These usually
    indicate misconfiguration the orchestrator should surface immediately.
  - **Model errors** (unexpected stop_reason, unexpected content shape) are
    translated into `AgentResponse(stop_reason="other", text=None, ...)`
    rather than raising. The orchestrator can log and decide whether to
    retry with a different prompt.

## Content-block translation

The PR 4 dataclasses were shaped exactly to match Anthropic's wire format,
so translation is nearly mechanical:
  `TextBlock`       ↔ `{"type": "text", "text": ...}`
  `ToolUseBlock`    ↔ `{"type": "tool_use", "id", "name", "input"}`
  `ToolResultBlock` ↔ `{"type": "tool_result", "tool_use_id", "content", "is_error"}`

The SDK returns typed objects (not dicts) as of anthropic>=0.40, so we
read via attributes with dict fallback for robustness across versions.
"""

from __future__ import annotations

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


DEFAULT_MODEL = os.environ.get("MEDUSA_ANTHROPIC_MODEL", "claude-opus-4-5-20250929")
"""Default model identifier. Override via `MEDUSA_ANTHROPIC_MODEL` env var
or by passing `model=` to the backend constructor. Orchestrator config
(PR 6) will centralise the choice."""

_KNOWN_STOP_REASONS: set[str] = {
    "end_turn", "tool_use", "max_tokens", "stop_sequence", "error",
}


class AnthropicBackend(AgentBackend):
    """Concrete `AgentBackend` that calls Claude via `anthropic.Anthropic`."""

    name: ClassVar[str] = "anthropic"

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        client: Optional[Any] = None,
    ) -> None:
        """Build an AnthropicBackend.

        Args:
            model: Claude model identifier passed as `model=` to the SDK.
            api_key: Optional API key; if None, the SDK reads ANTHROPIC_API_KEY.
            base_url: Optional alternate API endpoint (e.g. for proxies).
            client: Pre-built SDK client. If provided, `api_key` and
                `base_url` are ignored — used for test dependency injection.
        """
        self.model = model
        if client is not None:
            self._client = client
            return
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError(
                "AnthropicBackend requires `pip install anthropic`"
            ) from e
        kwargs: dict[str, Any] = {}
        if api_key is not None:
            kwargs["api_key"] = api_key
        if base_url is not None:
            kwargs["base_url"] = base_url
        self._client = anthropic.Anthropic(**kwargs)

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
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [self._message_to_wire(m) for m in messages],
        }
        if tools:
            request["tools"] = [self._tool_to_wire(t) for t in tools]
        if system is not None:
            request["system"] = system
        response = self._client.messages.create(**request)
        return self._response_from_wire(response)

    # -- wire translation (outbound) ----------------------------------------

    @staticmethod
    def _message_to_wire(m: Message) -> dict[str, Any]:
        """Translate a Message to Anthropic's message dict.

        The SDK expects role in {"user", "assistant"} and routes system
        prompts via the top-level `system` parameter. If a caller puts a
        system-role Message in the list anyway (legacy shape), fold it
        into a user turn with a clear marker so nothing is silently lost.
        """
        if m.role == "system":
            text = m.content if isinstance(m.content, str) else "(system blocks)"
            return {"role": "user", "content": f"[system prompt] {text}"}
        if isinstance(m.content, str):
            return {"role": m.role, "content": m.content}
        return {
            "role": m.role,
            "content": [AnthropicBackend._block_to_wire(b) for b in m.content],
        }

    @staticmethod
    def _block_to_wire(b: ContentBlock) -> dict[str, Any]:
        if isinstance(b, TextBlock):
            return {"type": "text", "text": b.text}
        if isinstance(b, ToolUseBlock):
            return {
                "type": "tool_use",
                "id": b.id,
                "name": b.name,
                "input": dict(b.input),
            }
        if isinstance(b, ToolResultBlock):
            payload: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": b.tool_use_id,
            }
            if isinstance(b.content, str):
                payload["content"] = b.content
            else:
                payload["content"] = [
                    AnthropicBackend._block_to_wire(bb) for bb in b.content
                ]
            if b.is_error:
                payload["is_error"] = True
            return payload
        raise TypeError(f"unexpected content block: {type(b).__name__}")

    @staticmethod
    def _tool_to_wire(t: ToolSpec) -> dict[str, Any]:
        return {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }

    # -- wire translation (inbound) -----------------------------------------

    @staticmethod
    def _response_from_wire(response: Any) -> AgentResponse:
        """Convert an `anthropic.types.Message` back into our `AgentResponse`.

        Reads via attribute access first, falls back to dict access for
        robustness across SDK versions.
        """
        blocks: list[ContentBlock] = []
        for raw in getattr(response, "content", []) or []:
            btype = _attr_or_key(raw, "type")
            if btype == "text":
                blocks.append(TextBlock(text=_attr_or_key(raw, "text", "") or ""))
            elif btype == "tool_use":
                blocks.append(
                    ToolUseBlock(
                        id=_attr_or_key(raw, "id", ""),
                        name=_attr_or_key(raw, "name", ""),
                        input=dict(_attr_or_key(raw, "input", {}) or {}),
                    )
                )
            # Unknown or "thinking" blocks: skip for now. A later PR can
            # preserve them if we start using extended-thinking mode.

        raw_stop = _attr_or_key(response, "stop_reason", "end_turn") or "end_turn"
        stop_reason: StopReason = (
            raw_stop if raw_stop in _KNOWN_STOP_REASONS else "other"
        )

        usage: dict[str, Any] = {}
        u = getattr(response, "usage", None)
        if u is not None:
            usage = {
                "input_tokens": _attr_or_key(u, "input_tokens", None),
                "output_tokens": _attr_or_key(u, "output_tokens", None),
            }

        return AgentResponse.from_content(
            blocks, stop_reason=stop_reason, usage=usage,
        )


def _attr_or_key(obj: Any, name: str, default: Any = None) -> Any:
    """Read `name` from an object via attribute access, falling back to
    dict-key access. Returns `default` if neither is present.

    The anthropic SDK historically returned typed objects; very old
    versions returned dicts. Test fixtures may use SimpleNamespace. This
    helper lets the translator work against all three shapes.
    """
    val = getattr(obj, name, None)
    if val is not None:
        return val
    if isinstance(obj, dict):
        return obj.get(name, default)
    return default


__all__ = ["AnthropicBackend", "DEFAULT_MODEL"]
