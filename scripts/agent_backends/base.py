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


_TOOL_NAME_MAX_LEN = 128
_TOOL_ID_MAX_LEN = 256


def _bounded_exact_str(value: Any, limit: int) -> str:
    """Keep `value` (sliced to `limit`) only when it is exactly `str`.

    Every other exact type — including str subclasses, whose methods may be
    overridden — becomes "" without any conversion, length, or representation
    method being requested on the value.
    """
    if type(value) is str:
        return value[:limit]
    return ""


def _exact_str(value: Any) -> str:
    """Keep `value` unchanged only when it is exactly `str` — no length ceiling.

    A `TextBlock`'s text and a `ToolResultBlock`'s `tool_use_id` have no
    established maximum length, so an accepted exact string is retained
    byte-for-byte (unlike `_bounded_exact_str`, this applies no slice). str
    subclasses (whose methods may be overridden) and every other type become
    "" without any truth, length, iteration, conversion, representation,
    comparison, attribute, or type-name method being requested on the value.
    """
    if type(value) is str:
        return value
    return ""


@dataclass(frozen=True)
class TextBlock:
    """Plain-text assistant or user content.

    `text` is model-reachable (backends build these straight from wire/SDK
    responses, which can yield any JSON/Python type), so construction keeps
    it only when exactly `str` — byte-for-byte, with no length ceiling — and
    replaces every other shape with "" without invoking any hook. This keeps
    `AgentResponse.from_content` (whose text join would otherwise raise on a
    non-str, or run a hostile `__bool__`) and both provider encoders total.
    """

    text: str
    type: Literal["text"] = "text"

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", _exact_str(self.text))


@dataclass(frozen=True)
class ToolUseBlock:
    """Model is requesting a tool call. Matches Anthropic's block shape.

    Field values are model-reachable (backends build these straight from
    wire/SDK responses, e.g. `json.loads` of an arguments string can yield
    any JSON type), so construction normalizes to a bounded shape:
    `id`/`name` are kept only when exactly `str` (sliced to 256/128 chars,
    else ""), and `input` is kept only when exactly `dict` (else replaced
    by a fresh empty dict — never derived from other shapes). This keeps
    `AgentResponse.from_content` total over every constructed block.
    """

    id: str
    name: str
    input: dict[str, Any] = field(default_factory=dict)
    type: Literal["tool_use"] = "tool_use"

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _bounded_exact_str(self.id, _TOOL_ID_MAX_LEN))
        object.__setattr__(self, "name", _bounded_exact_str(self.name, _TOOL_NAME_MAX_LEN))
        if type(self.input) is not dict:
            object.__setattr__(self, "input", {})


@dataclass(frozen=True)
class ToolResultBlock:
    """Result of a tool_use being fed back to the model.

    `content` is tool/model-reachable, so construction normalizes it to the
    exact declared `str | list[ContentBlock]` contract (see
    `_normalized_result_content`): an exact built-in `str` is kept
    byte-for-byte; an exact built-in `list` is kept, retaining only its
    exact built-in content-block elements in order; every other shape
    becomes "" without invoking any hook. This keeps both provider encoders
    total — the Anthropic encoder would otherwise iterate a non-list (or
    a hostile `__iter__`) and raise, or hit `_block_to_wire`'s "unexpected
    content block" on a foreign element; the OpenAI-compat encoder would
    otherwise raise on a non-iterable content or emit corrupt output for
    foreign elements.

    The two metadata fields are normalized at the same shared boundary so
    the encoders' established paths are total over every constructed block:

    - `tool_use_id` is kept only when exactly built-in `str` (byte-for-byte,
      no length ceiling, via `_exact_str`); every other shape — including str
      subclasses and hostile objects — becomes "" without any conversion,
      length, comparison, or representation hook. A refused id can therefore
      no longer flow as a foreign object into the Anthropic
      `payload["tool_use_id"]` or the OpenAI-compat `"tool_call_id"` wire
      field; it becomes an exact empty-string field.
    - `is_error` is kept only when exactly built-in `bool` (`True`/`False`,
      by `type(...) is bool` identity — `bool` cannot be subclassed);
      every other shape becomes exact built-in `False` without calling
      `bool()`, equality, hashing, iteration, or any supplied hook. Both
      encoders truth-test `if b.is_error:`, so this stops a hostile
      `__bool__` from escaping and stops a malformed truthy value (e.g. `1`,
      `"yes"`) from producing the Anthropic `is_error: true` flag or the
      OpenAI-compat `"[ERROR] "` prefix. Exact `True` retains both.

    No supplied value, type name, representation, or exception text is ever
    exposed; the claim is bounded to `tool_use_id` and `is_error` (plus the
    unchanged `content` normalization) — not to any other field or block.
    """

    tool_use_id: str
    content: Union[str, list["ContentBlock"]]
    is_error: bool = False
    type: Literal["tool_result"] = "tool_result"

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_use_id", _exact_str(self.tool_use_id))
        object.__setattr__(
            self, "content", _normalized_result_content(self.content)
        )
        if type(self.is_error) is not bool:
            object.__setattr__(self, "is_error", False)


ContentBlock = Union[TextBlock, ToolUseBlock, ToolResultBlock]


def _normalized_result_content(value: Any) -> Union[str, list["ContentBlock"]]:
    """Normalize `ToolResultBlock.content` to its exact declared contract.

    - An exact built-in `str` is kept byte-for-byte (no length ceiling).
    - An exact built-in `list` is kept, retaining only its exact built-in
      content-block elements, in order. Foreign elements — including list
      subclasses' items and hostile objects — are dropped by exact-type
      identity (`type(x) is TextBlock/ToolUseBlock/ToolResultBlock`), so no
      element hook runs and no content is manufactured from pair sequences
      or other shapes. A fully valid block list is retained unchanged; an
      exact-but-empty list stays an empty list.
    - Every other shape — non-exact strings, list subclasses, mappings,
      other containers, and hostile objects — becomes "" deterministically,
      without invoking any truth, length, iteration, conversion,
      representation, comparison, attribute, or type-name hook on the value,
      and without exposing the value, its type, or any exception text.

    Both provider encoders stay total for these cases: each sees either an
    exact `str` or a list containing only encodable built-in blocks. (Nested
    blocks were already normalized at their own construction.)
    """
    if type(value) is str:
        return value
    if type(value) is list:
        kept: list[ContentBlock] = []
        for element in value:
            element_type = type(element)
            if (
                element_type is TextBlock
                or element_type is ToolUseBlock
                or element_type is ToolResultBlock
            ):
                kept.append(element)
        return kept
    return ""


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
