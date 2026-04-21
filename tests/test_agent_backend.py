"""Tests for scripts/agent_backends/ (Phase 18 PR 4).

Covers:
  - Dataclass construction + validation (TextBlock, ToolUseBlock,
    ToolResultBlock, Message, ToolSpec, ToolCall, AgentResponse).
  - AgentResponse.from_content derives text + tool_calls correctly.
  - AgentBackend ABC cannot be instantiated directly.
  - MockBackend list-mode: sequential responses, exhaustion raises,
    recorded calls capture all inputs.
  - MockBackend callable-mode: invoked per call with correct args.
  - Frozen dataclasses reject mutation (immutability fence).
"""

from __future__ import annotations

import pytest

from scripts.agent_backends import (
    AgentBackend,
    AgentResponse,
    Message,
    MockBackend,
    TextBlock,
    ToolCall,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
)


# -- content blocks ----------------------------------------------------------


def test_text_block_construction():
    b = TextBlock(text="hello")
    assert b.text == "hello"
    assert b.type == "text"


def test_tool_use_block_construction():
    b = ToolUseBlock(id="tu_1", name="get_params", input={"x": 1})
    assert b.id == "tu_1"
    assert b.name == "get_params"
    assert b.input == {"x": 1}
    assert b.type == "tool_use"


def test_tool_use_block_input_defaults_to_empty_dict():
    b = ToolUseBlock(id="tu_1", name="get_params")
    assert b.input == {}


def test_tool_result_block_construction():
    b = ToolResultBlock(tool_use_id="tu_1", content="OK")
    assert b.tool_use_id == "tu_1"
    assert b.content == "OK"
    assert b.is_error is False


def test_frozen_dataclasses_reject_mutation():
    b = TextBlock(text="x")
    with pytest.raises(Exception):
        b.text = "y"  # frozen dataclass → FrozenInstanceError


# -- message -----------------------------------------------------------------


def test_message_with_string_content():
    m = Message(role="user", content="hi")
    assert m.role == "user"
    assert m.content == "hi"


def test_message_with_block_list_content():
    blocks = [TextBlock(text="thinking..."), ToolUseBlock(id="tu_1", name="x")]
    m = Message(role="assistant", content=blocks)
    assert m.content == blocks


def test_message_rejects_invalid_role():
    with pytest.raises(ValueError, match="invalid role"):
        Message(role="robot", content="x")  # type: ignore[arg-type]


# -- tool spec ---------------------------------------------------------------


def test_tool_spec_construction():
    spec = ToolSpec(
        name="get_params",
        description="Fetch current effective params.",
        input_schema={"type": "object", "properties": {}},
    )
    assert spec.name == "get_params"
    assert spec.input_schema["type"] == "object"


def test_tool_spec_rejects_empty_name():
    with pytest.raises(ValueError, match="non-empty"):
        ToolSpec(name="", description="x", input_schema={})


def test_tool_spec_rejects_non_dict_schema():
    with pytest.raises(TypeError, match="JSON Schema"):
        ToolSpec(name="x", description="y", input_schema="not-a-dict")  # type: ignore[arg-type]


# -- tool call ---------------------------------------------------------------


def test_tool_call_construction():
    call = ToolCall(id="tu_1", name="get_params", arguments={"k": 1})
    assert call.id == "tu_1"
    assert call.name == "get_params"
    assert call.arguments == {"k": 1}


def test_tool_call_arguments_default_to_empty_dict():
    call = ToolCall(id="tu_1", name="x")
    assert call.arguments == {}


# -- AgentResponse.from_content --------------------------------------------


def test_from_content_text_only():
    content = [TextBlock(text="first"), TextBlock(text="second")]
    resp = AgentResponse.from_content(content)
    assert resp.text == "first\nsecond"
    assert resp.tool_calls == []
    assert resp.raw_content == content
    assert resp.stop_reason == "end_turn"


def test_from_content_tool_use_only():
    content = [
        ToolUseBlock(id="tu_1", name="get_params", input={}),
        ToolUseBlock(id="tu_2", name="get_schema", input={"verbose": True}),
    ]
    resp = AgentResponse.from_content(content)
    assert resp.text is None
    assert len(resp.tool_calls) == 2
    assert resp.tool_calls[0].id == "tu_1"
    assert resp.tool_calls[1].arguments == {"verbose": True}


def test_from_content_mixed():
    content = [
        TextBlock(text="Let me check that."),
        ToolUseBlock(id="tu_1", name="get_params"),
    ]
    resp = AgentResponse.from_content(content, stop_reason="tool_use", usage={"input_tokens": 42})
    assert resp.text == "Let me check that."
    assert len(resp.tool_calls) == 1
    assert resp.stop_reason == "tool_use"
    assert resp.usage["input_tokens"] == 42


def test_from_content_preserves_empty_text_filtered():
    """Empty-string text blocks don't contaminate the concatenated text."""
    content = [TextBlock(text=""), TextBlock(text="actual")]
    resp = AgentResponse.from_content(content)
    assert resp.text == "actual"


# -- AgentBackend ABC --------------------------------------------------------


def test_agent_backend_is_abstract():
    with pytest.raises(TypeError):
        AgentBackend()  # type: ignore[abstract]


def test_subclass_without_complete_still_abstract():
    class Partial(AgentBackend):
        pass

    with pytest.raises(TypeError):
        Partial()


# -- MockBackend (list mode) ------------------------------------------------


def _simple_response(text: str) -> AgentResponse:
    return AgentResponse.from_content([TextBlock(text=text)])


def test_mock_list_mode_pops_in_order():
    backend = MockBackend(responses=[_simple_response("one"), _simple_response("two")])
    r1 = backend.complete(messages=[], tools=[])
    r2 = backend.complete(messages=[], tools=[])
    assert r1.text == "one"
    assert r2.text == "two"
    assert backend.remaining == 0


def test_mock_list_mode_raises_when_exhausted():
    backend = MockBackend(responses=[_simple_response("only")])
    backend.complete(messages=[], tools=[])
    with pytest.raises(RuntimeError, match="exhausted"):
        backend.complete(messages=[], tools=[])


def test_mock_records_every_call():
    backend = MockBackend(responses=[_simple_response("x")])
    messages = [Message(role="user", content="hello")]
    tools = [ToolSpec(name="t", description="d", input_schema={})]
    backend.complete(messages=messages, tools=tools, system="be helpful", max_tokens=100, temperature=0.5)
    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert call.messages == messages
    assert call.tools == tools
    assert call.system == "be helpful"
    assert call.max_tokens == 100
    assert call.temperature == 0.5


def test_mock_defensive_copy_of_response_list():
    """Caller-visible list must not be consumed by MockBackend."""
    source = [_simple_response("a"), _simple_response("b")]
    backend = MockBackend(responses=source)
    backend.complete(messages=[], tools=[])
    # Source list is untouched; only the internal queue is consumed.
    assert len(source) == 2
    assert backend.remaining == 1


def test_mock_reset_calls_does_not_touch_queue():
    backend = MockBackend(responses=[_simple_response("a"), _simple_response("b")])
    backend.complete(messages=[], tools=[])
    assert len(backend.calls) == 1
    assert backend.remaining == 1
    backend.reset_calls()
    assert backend.calls == []
    assert backend.remaining == 1


# -- MockBackend (callable mode) -------------------------------------------


def test_mock_callable_mode_invoked_per_call():
    invocations = []

    def responder(messages, tools, *, system, max_tokens, temperature):
        invocations.append(len(messages))
        return _simple_response(f"turn-{len(messages)}")

    backend = MockBackend(responses=responder)
    r1 = backend.complete(messages=[], tools=[])
    r2 = backend.complete(messages=[Message(role="user", content="hi")], tools=[])
    assert r1.text == "turn-0"
    assert r2.text == "turn-1"
    assert invocations == [0, 1]
    assert backend.remaining == -1  # callable mode


def test_mock_rejects_bad_responses_type():
    with pytest.raises(TypeError, match="list"):
        MockBackend(responses=42)  # type: ignore[arg-type]
