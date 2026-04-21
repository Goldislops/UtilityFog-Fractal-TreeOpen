"""Phase 18 PR 4 — Agent backend abstraction (ABC + data types).

The seam that lets us swap Anthropic Opus (today), Nemotron-via-NVIDIA-Cloud
(tomorrow), or any other tool-using LLM (ever), without rewriting the
orchestrator loop or matrix physics.

Design principles:
  - Orchestrator code imports ONLY the types from this module. Concrete
    backends translate the underlying SDK's shapes into these types.
  - Dataclasses are frozen to avoid accidental shared-state mutations
    across a multi-turn conversation.
  - `AgentResponse.raw_content` preserves the full assistant content
    (text + tool_use blocks in order) so the orchestrator can echo it
    straight back as the next message's "assistant" turn — critical for
    maintaining a valid conversation history with tool-using models.
  - Tool-call translation lives in concrete backends (PR 5+). This file
    defines the common wire shape; Anthropic's content-block format
    is the natural fit and other backends translate INTO it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, Optional, Union


# -- content blocks ---------------------------------------------------------


@dataclass(frozen=True)
class TextBlock:
    """Plain-text assistant or user content."""

    text: str
    type: Literal["text"] = "text"


@dataclass(frozen=True)
class ToolUseBlock:
    """Model is requesting a tool call. Matches Anthropic's block shape."""

    id: str
    name: str
    input: dict[str, Any] = field(default_factory=dict)
    type: Literal["tool_use"] = "tool_use"


@dataclass(frozen=True)
class ToolResultBlock:
    """Result of a tool_use being fed back to the model."""

    tool_use_id: str
    content: Union[str, list["ContentBlock"]]
    is_error: bool = False
    type: Literal["tool_result"] = "tool_result"


ContentBlock = Union[TextBlock, ToolUseBlock, ToolResultBlock]


# -- messages ---------------------------------------------------------------


@dataclass(frozen=True)
class Message:
    """One turn in a conversation.

    `content` is either a plain string (simple text turn) or a list of
    `ContentBlock`s (for tool-use interleaving). `role` is one of
    "user" | "assistant" | "system"; concrete backends MAY map "system"
    to a system-prompt parameter instead of a turn, when the underlying
    API prefers that shape.
    """

    role: Literal["user", "assistant", "system"]
    content: Union[str, list[ContentBlock]]

    def __post_init__(self) -> None:
        if self.role not in ("user", "assistant", "system"):
            raise ValueError(f"invalid role: {self.role}")


# -- tool use ---------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    """Declaration of a tool available for the model to call.

    `input_schema` is a JSON Schema object describing the arguments. It's
    passed through untouched to the backend; orchestrator writers should
    author it once and rely on the backends to forward it.
    """

    name: str
    description: str
    input_schema: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("ToolSpec.name must be non-empty")
        if not isinstance(self.input_schema, dict):
            raise TypeError("ToolSpec.input_schema must be a dict (JSON Schema)")


@dataclass(frozen=True)
class ToolCall:
    """Extracted tool-call for the orchestrator to execute.

    This is `ToolUseBlock` re-projected into a flat shape that's ergonomic
    for orchestrator code. `id` matches the originating `ToolUseBlock.id`
    so the orchestrator can link results back when feeding them as
    `ToolResultBlock(tool_use_id=id, ...)`.
    """

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


# -- response ---------------------------------------------------------------


StopReason = Literal["end_turn", "tool_use", "max_tokens", "stop_sequence", "error", "other"]


@dataclass(frozen=True)
class AgentResponse:
    """Normalized shape returned by every backend's `complete()` call.

    - `text` is the concatenated text of all `TextBlock`s in `raw_content`,
      or `None` if the model only returned tool_use blocks.
    - `tool_calls` is the list of `ToolCall`s extracted from `raw_content`
      in order. Orchestrators typically iterate these to execute tools.
    - `raw_content` preserves the full assistant content block list in
      order — orchestrators append this as the `assistant` message
      content on the next turn, then append their own `user` turn with
      the corresponding `ToolResultBlock`s.
    - `stop_reason` reflects why the model stopped generating.
    - `usage` is an optional dict with token counts (input_tokens,
      output_tokens, etc.). Shape is backend-specific but keys are stable
      enough for cost accounting.
    """

    text: Optional[str]
    tool_calls: list[ToolCall]
    raw_content: list[ContentBlock]
    stop_reason: StopReason = "end_turn"
    usage: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_content(
        cls,
        content: list[ContentBlock],
        *,
        stop_reason: StopReason = "end_turn",
        usage: Optional[dict[str, Any]] = None,
    ) -> "AgentResponse":
        """Build an AgentResponse from a raw content block list. Derives `text`
        and `tool_calls` automatically. The canonical constructor for
        backends to use after translating the SDK response."""
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in content:
            if isinstance(block, TextBlock):
                text_parts.append(block.text)
            elif isinstance(block, ToolUseBlock):
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
                )
            # ToolResultBlock shouldn't appear in assistant content; ignore.
        text = "\n".join(p for p in text_parts if p) if text_parts else None
        return cls(
            text=text,
            tool_calls=tool_calls,
            raw_content=list(content),
            stop_reason=stop_reason,
            usage=dict(usage or {}),
        )


# -- ABC --------------------------------------------------------------------


class AgentBackend(ABC):
    """Abstract base class for LLM-backed agents.

    Every concrete backend (AnthropicBackend, NemoCloudBackend, MockBackend)
    implements `complete()` with the same signature and semantics. The
    orchestrator layer imports only this class and the types above;
    swapping backends is a one-line config change."""

    name: ClassVar[str] = "abstract"
    """Human-readable identifier for logging / audit."""

    @abstractmethod
    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> AgentResponse:
        """Generate the next agent turn given conversation history and tools.

        Contract:
          - `messages` is the full conversation history. The backend MUST
            NOT mutate this list or any of its members.
          - `tools` is the set of tools declared to the model for this turn.
          - `system` is an optional system prompt. If the underlying API
            distinguishes system prompts from user turns, the backend
            SHOULD route `system` through that channel rather than
            prepending a user/system message.
          - The return is ALWAYS an `AgentResponse`; backends must translate
            errors into `stop_reason="error"` + empty content rather than
            raising at the call site, wherever practical. (Transport-level
            errors — auth failures, network unreachable — MAY raise.)
        """
        raise NotImplementedError


__all__ = [
    "AgentBackend",
    "AgentResponse",
    "ContentBlock",
    "Message",
    "StopReason",
    "TextBlock",
    "ToolCall",
    "ToolResultBlock",
    "ToolSpec",
    "ToolUseBlock",
]
