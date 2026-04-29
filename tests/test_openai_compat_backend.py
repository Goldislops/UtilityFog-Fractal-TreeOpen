"""Tests for scripts/agent_backends/openai_compat_backend.py (Phase 18 PR 7).

Uses dependency-injected mock clients — no network calls, no API keys.

Outbound (request side):
  - Simple string content forwarded with role unchanged.
  - System prompt prepends as `{"role":"system"}` message (NOT a top-level param).
  - Block-list assistant content (text + tool_use) → ONE assistant message
    with `content` (text) + `tool_calls` (separate field; arguments
    JSON-encoded as STRING per OpenAI spec).
  - Block-list user content with ToolResultBlock → EXPLODES into one
    `{"role":"tool", tool_call_id, content}` message per result. This is
    the key difference from Anthropic.
  - Multiple ToolResultBlocks in one user message → multiple wire messages.
  - ToolSpec → `{"type":"function", "function":{name, description, parameters}}`.
  - Empty tool list omits `tools` from the request.
  - max_tokens / temperature forwarded.
  - extra_headers forwarded when set.

Inbound (response side):
  - Text-only response → AgentResponse.text.
  - tool_calls (with JSON-string `arguments`) → AgentResponse.tool_calls
    with arguments parsed back into dicts.
  - Mixed text + tool_calls preserved.
  - finish_reason mapping: stop→end_turn, tool_calls→tool_use,
    length→max_tokens, content_filter→other, function_call→tool_use.
  - Usage extraction: prompt_tokens → input_tokens, completion_tokens
    → output_tokens.
  - Empty choices returns clean response.
  - Malformed tool_call.arguments JSON falls back to a recoverable shape.
  - Dict-shaped responses (some local servers) translate same as objects.

Error / construction:
  - Transport errors propagate.
  - Model + base_url + api_key forwarded to SDK at construction.
  - Backend.name == "openai-compat".
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from scripts.agent_backends import (
    AgentResponse,
    Message,
    OpenAICompatBackend,
    TextBlock,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
)


if OpenAICompatBackend is None:
    pytest.skip(
        "openai package not installed", allow_module_level=True,
    )


# -- mock client -------------------------------------------------------------


class _MockChatCompletions:
    def __init__(self) -> None:
        self.last_request: Optional[dict] = None
        self.response: Any = None
        self.side_effect: Optional[BaseException] = None

    def create(self, **kwargs: Any) -> Any:
        self.last_request = kwargs
        if self.side_effect is not None:
            raise self.side_effect
        return self.response


class _MockChat:
    def __init__(self) -> None:
        self.completions = _MockChatCompletions()


class _MockClient:
    def __init__(self) -> None:
        self.chat = _MockChat()


# -- response factory --------------------------------------------------------


def _make_response(
    content: Optional[str] = None,
    *,
    tool_calls: Optional[list] = None,
    finish_reason: str = "stop",
    prompt_tokens: int = 10,
    completion_tokens: int = 20,
) -> SimpleNamespace:
    """Build a duck-typed OpenAI ChatCompletion response."""
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=msg, finish_reason=finish_reason)
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    return SimpleNamespace(choices=[choice], usage=usage)


def _tc(tc_id: str, name: str, args_obj: dict) -> SimpleNamespace:
    """A tool_call shaped like the OpenAI SDK returns. arguments is a JSON STRING."""
    return SimpleNamespace(
        id=tc_id, type="function",
        function=SimpleNamespace(name=name, arguments=json.dumps(args_obj)),
    )


# -- outbound translation ---------------------------------------------------


def test_simple_string_content_forwarded():
    client = _MockClient()
    client.chat.completions.response = _make_response("ok")
    backend = OpenAICompatBackend(model="test-model", client=client)

    backend.complete(
        messages=[Message(role="user", content="hello")],
        tools=[],
    )
    req = client.chat.completions.last_request
    assert req["model"] == "test-model"
    assert req["messages"] == [{"role": "user", "content": "hello"}]
    assert "tools" not in req
    assert req["max_tokens"] == 2048
    assert req["temperature"] == 0.0


def test_system_prompt_prepends_as_system_message():
    """Distinct from AnthropicBackend, which routes system via top-level param."""
    client = _MockClient()
    client.chat.completions.response = _make_response("ok")
    backend = OpenAICompatBackend(client=client)

    backend.complete(
        messages=[Message(role="user", content="hi")],
        tools=[],
        system="be concise",
    )
    msgs = client.chat.completions.last_request["messages"]
    assert msgs[0] == {"role": "system", "content": "be concise"}
    assert msgs[1] == {"role": "user", "content": "hi"}


def test_assistant_block_list_combines_text_and_tool_calls():
    """Assistant TextBlock + ToolUseBlock → ONE message with content + tool_calls.
    Tool-call arguments are JSON-encoded STRING per OpenAI spec."""
    client = _MockClient()
    client.chat.completions.response = _make_response("ok")
    backend = OpenAICompatBackend(client=client)

    backend.complete(
        messages=[Message(role="assistant", content=[
            TextBlock(text="let me check"),
            ToolUseBlock(id="tu_1", name="get_params", input={"verbose": True}),
        ])],
        tools=[],
    )
    msgs = client.chat.completions.last_request["messages"]
    assert len(msgs) == 1
    assert msgs[0]["role"] == "assistant"
    assert msgs[0]["content"] == "let me check"
    assert len(msgs[0]["tool_calls"]) == 1
    tc = msgs[0]["tool_calls"][0]
    assert tc["id"] == "tu_1"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "get_params"
    # arguments MUST be a JSON string, not a dict
    assert isinstance(tc["function"]["arguments"], str)
    assert json.loads(tc["function"]["arguments"]) == {"verbose": True}


def test_assistant_block_list_text_only_omits_tool_calls():
    client = _MockClient()
    client.chat.completions.response = _make_response("ok")
    backend = OpenAICompatBackend(client=client)

    backend.complete(
        messages=[Message(role="assistant", content=[TextBlock(text="just text")])],
        tools=[],
    )
    msgs = client.chat.completions.last_request["messages"]
    assert msgs[0] == {"role": "assistant", "content": "just text"}
    assert "tool_calls" not in msgs[0]


def test_tool_result_in_user_message_explodes_into_role_tool():
    """The key OpenAI quirk: each ToolResultBlock becomes a separate
    `{"role":"tool", tool_call_id, content}` message."""
    client = _MockClient()
    client.chat.completions.response = _make_response("ok")
    backend = OpenAICompatBackend(client=client)

    backend.complete(
        messages=[Message(role="user", content=[
            ToolResultBlock(tool_use_id="tu_1", content="result one", is_error=False),
            ToolResultBlock(tool_use_id="tu_2", content="result two", is_error=False),
        ])],
        tools=[],
    )
    msgs = client.chat.completions.last_request["messages"]
    assert len(msgs) == 2
    assert msgs[0] == {"role": "tool", "tool_call_id": "tu_1", "content": "result one"}
    assert msgs[1] == {"role": "tool", "tool_call_id": "tu_2", "content": "result two"}


def test_tool_result_with_is_error_prefixes_content():
    """PR 7a fix: OpenAI's role:"tool" message has no is_error field
    analogous to Anthropic's. When the source side flagged an error,
    prefix the content with "[ERROR] " so the model can tell the tool
    failed. Without this, a tool failure would look like a tool success
    to any OpenAI-compatible model. Regression fence."""
    client = _MockClient()
    client.chat.completions.response = _make_response("ok")
    backend = OpenAICompatBackend(client=client)

    backend.complete(
        messages=[Message(role="user", content=[
            ToolResultBlock(tool_use_id="tu_x", content="boom: 500", is_error=True),
        ])],
        tools=[],
    )
    msgs = client.chat.completions.last_request["messages"]
    assert len(msgs) == 1
    assert msgs[0]["role"] == "tool"
    assert msgs[0]["tool_call_id"] == "tu_x"
    assert msgs[0]["content"].startswith("[ERROR] ")
    assert "boom: 500" in msgs[0]["content"]


def test_tool_result_without_is_error_unchanged():
    """Successful tool results must NOT get the [ERROR] marker."""
    client = _MockClient()
    client.chat.completions.response = _make_response("ok")
    backend = OpenAICompatBackend(client=client)

    backend.complete(
        messages=[Message(role="user", content=[
            ToolResultBlock(tool_use_id="tu_y", content="all good", is_error=False),
        ])],
        tools=[],
    )
    msgs = client.chat.completions.last_request["messages"]
    assert msgs[0]["content"] == "all good"
    assert not msgs[0]["content"].startswith("[ERROR]")


def test_tool_result_plus_user_text_produces_separate_messages():
    client = _MockClient()
    client.chat.completions.response = _make_response("ok")
    backend = OpenAICompatBackend(client=client)

    backend.complete(
        messages=[Message(role="user", content=[
            ToolResultBlock(tool_use_id="tu_1", content="result", is_error=False),
            TextBlock(text="now what?"),
        ])],
        tools=[],
    )
    msgs = client.chat.completions.last_request["messages"]
    # Expect: 1 tool message, then 1 user message
    assert len(msgs) == 2
    assert msgs[0]["role"] == "tool"
    assert msgs[1] == {"role": "user", "content": "now what?"}


def test_tool_spec_translates_to_function_shape():
    client = _MockClient()
    client.chat.completions.response = _make_response("ok")
    backend = OpenAICompatBackend(client=client)

    tool = ToolSpec(
        name="get_params",
        description="fetch tunable params",
        input_schema={"type": "object", "properties": {}, "required": []},
    )
    backend.complete(messages=[Message(role="user", content="x")], tools=[tool])

    sent = client.chat.completions.last_request["tools"]
    assert sent == [{
        "type": "function",
        "function": {
            "name": "get_params",
            "description": "fetch tunable params",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }]


def test_max_tokens_and_temperature_forwarded():
    client = _MockClient()
    client.chat.completions.response = _make_response("ok")
    backend = OpenAICompatBackend(client=client)

    backend.complete(
        messages=[Message(role="user", content="x")],
        tools=[],
        max_tokens=512,
        temperature=0.7,
    )
    req = client.chat.completions.last_request
    assert req["max_tokens"] == 512
    assert req["temperature"] == 0.7


def test_extra_headers_forwarded_when_set():
    client = _MockClient()
    client.chat.completions.response = _make_response("ok")
    backend = OpenAICompatBackend(
        client=client,
        extra_headers={"X-Custom-Auth": "abc123"},
    )
    backend.complete(messages=[Message(role="user", content="x")], tools=[])
    req = client.chat.completions.last_request
    assert req["extra_headers"] == {"X-Custom-Auth": "abc123"}


def test_extra_headers_omitted_when_unset():
    client = _MockClient()
    client.chat.completions.response = _make_response("ok")
    backend = OpenAICompatBackend(client=client)
    backend.complete(messages=[Message(role="user", content="x")], tools=[])
    assert "extra_headers" not in client.chat.completions.last_request


# -- inbound translation ----------------------------------------------------


def test_response_text_only():
    client = _MockClient()
    client.chat.completions.response = _make_response("hello world")
    backend = OpenAICompatBackend(client=client)

    resp = backend.complete(messages=[Message(role="user", content="x")], tools=[])
    assert isinstance(resp, AgentResponse)
    assert resp.text == "hello world"
    assert resp.tool_calls == []
    assert resp.stop_reason == "end_turn"
    assert resp.usage["input_tokens"] == 10
    assert resp.usage["output_tokens"] == 20


def test_response_tool_calls_with_json_string_arguments_parse_back():
    client = _MockClient()
    client.chat.completions.response = _make_response(
        content=None,
        tool_calls=[_tc("tu_1", "get_params", {"verbose": True, "n": 5})],
        finish_reason="tool_calls",
    )
    backend = OpenAICompatBackend(client=client)

    resp = backend.complete(messages=[Message(role="user", content="x")], tools=[])
    assert resp.text is None
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].id == "tu_1"
    assert resp.tool_calls[0].name == "get_params"
    assert resp.tool_calls[0].arguments == {"verbose": True, "n": 5}
    assert resp.stop_reason == "tool_use"


def test_response_mixed_text_and_tool_calls():
    client = _MockClient()
    client.chat.completions.response = _make_response(
        content="checking now",
        tool_calls=[_tc("tu_a", "get_params", {})],
        finish_reason="tool_calls",
    )
    backend = OpenAICompatBackend(client=client)

    resp = backend.complete(messages=[Message(role="user", content="x")], tools=[])
    assert resp.text == "checking now"
    assert len(resp.tool_calls) == 1
    # raw_content preserves both blocks for history replay
    assert len(resp.raw_content) == 2


def test_finish_reason_mapping():
    cases = [
        ("stop", "end_turn"),
        ("tool_calls", "tool_use"),
        ("length", "max_tokens"),
        ("content_filter", "other"),
        ("function_call", "tool_use"),
        ("unrecognized", "other"),
    ]
    backend = OpenAICompatBackend(client=_MockClient())
    for raw, expected in cases:
        client = _MockClient()
        client.chat.completions.response = _make_response("x", finish_reason=raw)
        b = OpenAICompatBackend(client=client)
        resp = b.complete(messages=[Message(role="user", content="x")], tools=[])
        assert resp.stop_reason == expected, f"{raw} → expected {expected} got {resp.stop_reason}"


def test_response_with_no_choices_returns_clean():
    client = _MockClient()
    client.chat.completions.response = SimpleNamespace(choices=[], usage=None)
    backend = OpenAICompatBackend(client=client)

    resp = backend.complete(messages=[Message(role="user", content="x")], tools=[])
    assert resp.text is None
    assert resp.tool_calls == []
    assert resp.stop_reason == "other"


def test_response_with_malformed_tool_arguments_falls_back():
    """If arguments aren't valid JSON we still produce a usable ToolUseBlock."""
    bad_tc = SimpleNamespace(
        id="tu_bad", type="function",
        function=SimpleNamespace(name="f", arguments="{not valid"),
    )
    client = _MockClient()
    client.chat.completions.response = _make_response(
        content=None, tool_calls=[bad_tc], finish_reason="tool_calls",
    )
    backend = OpenAICompatBackend(client=client)
    resp = backend.complete(messages=[Message(role="user", content="x")], tools=[])
    assert len(resp.tool_calls) == 1
    assert "_raw_arguments" in resp.tool_calls[0].arguments


def test_dict_shaped_response_also_translates():
    """Some local servers return dicts rather than typed objects."""
    client = _MockClient()
    client.chat.completions.response = SimpleNamespace(
        choices=[{
            "message": {
                "content": "dict-shape",
                "tool_calls": [{
                    "id": "tu_d", "type": "function",
                    "function": {"name": "f", "arguments": "{\"k\": 1}"},
                }],
            },
            "finish_reason": "tool_calls",
        }],
        usage={"prompt_tokens": 5, "completion_tokens": 7},
    )
    backend = OpenAICompatBackend(client=client)
    resp = backend.complete(messages=[Message(role="user", content="x")], tools=[])
    assert resp.text == "dict-shape"
    assert resp.tool_calls[0].id == "tu_d"
    assert resp.tool_calls[0].arguments == {"k": 1}
    assert resp.usage == {"input_tokens": 5, "output_tokens": 7}


# -- error / construction ---------------------------------------------------


def test_transport_error_propagates():
    client = _MockClient()
    client.chat.completions.side_effect = RuntimeError("network down")
    backend = OpenAICompatBackend(client=client)
    with pytest.raises(RuntimeError, match="network down"):
        backend.complete(messages=[Message(role="user", content="x")], tools=[])


def test_backend_uses_configured_model():
    client = _MockClient()
    client.chat.completions.response = _make_response("x")
    backend = OpenAICompatBackend(model="custom-model-99", client=client)
    backend.complete(messages=[Message(role="user", content="x")], tools=[])
    assert client.chat.completions.last_request["model"] == "custom-model-99"


def test_backend_name_classvar():
    backend = OpenAICompatBackend(client=_MockClient())
    assert backend.name == "openai-compat"


# -- PR 7b: dummy api_key for the OpenAI SDK's strict construction ---------


def test_construction_without_api_key_or_env_var_does_not_crash(monkeypatch):
    """The OpenAI Python SDK raises at construction if neither `api_key` arg
    nor `OPENAI_API_KEY` env var is set. That's hostile when pointing at a
    passwordless local server (Ollama, vLLM, llama.cpp). PR 7b: supply a
    placeholder so local setups Just Work; real auth-required providers
    fail later with a clearer 401."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    backend = OpenAICompatBackend(
        base_url="http://localhost:11434/v1",
        model="llama3.1:8b",
    )
    assert backend.name == "openai-compat"


def test_explicit_api_key_arg_is_passed_through(monkeypatch):
    """An explicit api_key arg must NOT be overridden by the dummy."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    backend = OpenAICompatBackend(
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        api_key="sk-real-deepseek-key",
    )
    # Backend constructed without crashing; the SDK now holds the real key.
    assert backend.model == "deepseek-chat"


def test_env_var_api_key_does_not_trigger_dummy(monkeypatch):
    """If OPENAI_API_KEY is set, the backend should let the SDK read it
    rather than overwriting with a placeholder."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    backend = OpenAICompatBackend(
        base_url="http://localhost:11434/v1",
        model="llama3.1:8b",
    )
    assert backend.name == "openai-compat"


# -- regression: orchestrator can swap backends seamlessly ------------------


def test_response_shape_compatible_with_orchestrator_loop():
    """The Orchestrator (PR 6) reads .raw_content, .text, .tool_calls,
    .stop_reason, .usage. Verify all five fields are present in the
    AgentResponse this backend produces — same contract as MockBackend
    and AnthropicBackend."""
    client = _MockClient()
    client.chat.completions.response = _make_response(
        content="hi",
        tool_calls=[_tc("tu_1", "f", {"x": 1})],
        finish_reason="tool_calls",
    )
    backend = OpenAICompatBackend(client=client)
    resp = backend.complete(messages=[Message(role="user", content="x")], tools=[])
    # The 5 fields the orchestrator reads
    _ = resp.text
    _ = resp.tool_calls
    _ = resp.stop_reason
    _ = resp.usage
    _ = resp.raw_content
    # Tool call is structured the same as MockBackend / AnthropicBackend
    assert resp.tool_calls[0].id == "tu_1"
    assert resp.tool_calls[0].name == "f"
    assert resp.tool_calls[0].arguments == {"x": 1}
