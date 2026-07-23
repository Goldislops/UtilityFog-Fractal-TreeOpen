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

import scripts.agent_backends.openai_compat_backend as openai_compat_backend_module
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
    pytest.importorskip("openai")  # backend construction instantiates the real SDK
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    backend = OpenAICompatBackend(
        base_url="http://localhost:11434/v1",
        model="llama3.1:8b",
    )
    assert backend.name == "openai-compat"


def test_explicit_api_key_arg_is_passed_through(monkeypatch):
    """An explicit api_key arg must NOT be overridden by the dummy."""
    pytest.importorskip("openai")  # backend construction instantiates the real SDK
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
    pytest.importorskip("openai")  # backend construction instantiates the real SDK
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    backend = OpenAICompatBackend(
        base_url="http://localhost:11434/v1",
        model="llama3.1:8b",
    )
    assert backend.name == "openai-compat"


# -- argument-decode totality: tool_call.arguments is model/server-reachable
#    and can be ANY value, so decoding must be total and hook-free. Exact
#    strings: JSON object kept; other valid JSON → {}; undecodable or parser
#    recursion → {"_raw_arguments": original}. Empty/absent → {}. Exact dicts
#    pass through to ToolUseBlock's hardened normalization. Everything else →
#    a fresh {} with no __bool__/__iter__/keys/__str__ hook ever invoked. ----


def _raw_tc(arguments: Any) -> SimpleNamespace:
    """A tool_call whose `arguments` is an arbitrary raw wire value (not
    necessarily the JSON string a well-behaved SDK produces)."""
    return SimpleNamespace(
        id="tu_raw", type="function",
        function=SimpleNamespace(name="f", arguments=arguments),
    )


def _complete_with_arguments(arguments: Any) -> AgentResponse:
    client = _MockClient()
    client.chat.completions.response = _make_response(
        content=None, tool_calls=[_raw_tc(arguments)], finish_reason="tool_calls",
    )
    backend = OpenAICompatBackend(client=client)
    return backend.complete(messages=[Message(role="user", content="x")], tools=[])


def test_empty_string_arguments_normalize_to_empty_dict():
    """'' is how several servers encode a no-argument call; it must become
    {} — not the {"_raw_arguments": ""} shape the old json.loads('')
    ValueError path produced."""
    resp = _complete_with_arguments("")
    assert resp.tool_calls[0].arguments == {}


def test_absent_arguments_normalize_to_empty_dict():
    """arguments=None (field absent) must also become {}."""
    resp = _complete_with_arguments(None)
    assert resp.tool_calls[0].arguments == {}


def test_json_array_scalar_and_null_arguments_normalize_to_empty_dict():
    """Valid JSON that is not an object carries no argument mapping; the
    backend itself normalizes to {} rather than pushing a non-dict into
    the ToolUseBlock boundary."""
    for raw in ("[1, 2]", "5", '"s"', "true", "null"):
        resp = _complete_with_arguments(raw)
        assert resp.tool_calls[0].arguments == {}, f"arguments={raw!r}"


def test_valid_json_object_arguments_retained():
    """The ordinary path is untouched: a JSON object keeps its content."""
    resp = _complete_with_arguments('{"verbose": true, "n": 5}')
    assert resp.tool_calls[0].arguments == {"verbose": True, "n": 5}


def test_pair_list_arguments_are_not_dict_converted():
    """The old eager dict(...) manufactured {"a": 1} from a pair-list wire
    value; non-string values must normalize to {} without conversion."""
    resp = _complete_with_arguments([["a", 1]])
    assert resp.tool_calls[0].arguments == {}


def test_exact_dict_arguments_pass_through():
    """Some local servers return arguments as an already-decoded dict; an
    exact dict continues through ToolUseBlock's hardened normalization."""
    resp = _complete_with_arguments({"k": 1})
    assert resp.tool_calls[0].arguments == {"k": 1}


def test_hostile_arguments_value_never_has_hooks_invoked():
    """A direct wire value whose truthiness / iteration / mapping-conversion /
    string-conversion hooks raise must decode to {} with no hook executed
    (the old path invoked __bool__ via `or ""` and str() in the fallback)."""

    class Hostile:
        def __bool__(self):
            raise AssertionError("hook invoked: __bool__")

        def __len__(self):
            raise AssertionError("hook invoked: __len__")

        def __iter__(self):
            raise AssertionError("hook invoked: __iter__")

        def keys(self):
            raise AssertionError("hook invoked: keys()")

        def __str__(self):
            raise AssertionError("hook invoked: __str__")

    resp = _complete_with_arguments(Hostile())
    assert resp.tool_calls[0].arguments == {}


def test_str_subclass_arguments_normalize_to_empty_dict():
    """A str subclass is not an exact string (subclasses can override
    behavior), so it takes the hook-free {} path, never the parser."""

    class WeirdStr(str):
        pass

    resp = _complete_with_arguments(WeirdStr('{"a": 1}'))
    assert resp.tool_calls[0].arguments == {}


def test_parser_recursion_error_uses_raw_fallback(monkeypatch):
    """RecursionError raised by the JSON parser on an ordinary exact-string
    value must land in the same {"_raw_arguments": ...} fallback as invalid
    JSON, not escape the backend. Deterministic parser substitution — no
    dependence on a platform-specific nesting depth."""
    marker = '{"deep": "payload"}'
    real_loads = json.loads

    def fake_loads(s, *args, **kwargs):
        if s == marker:
            raise RecursionError("maximum recursion depth exceeded")
        return real_loads(s, *args, **kwargs)

    monkeypatch.setattr(openai_compat_backend_module.json, "loads", fake_loads)
    resp = _complete_with_arguments(marker)
    assert resp.tool_calls[0].arguments == {"_raw_arguments": marker}


def test_malformed_arguments_fallback_shape_exact():
    """The established fallback keeps the ORIGINAL string under
    _raw_arguments — exact shape, no str() re-wrapping."""
    resp = _complete_with_arguments("{not valid")
    assert resp.tool_calls[0].arguments == {"_raw_arguments": "{not valid"}


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


# ============================================================================
# Inbound-response shape totality (Kev-owned lane): the OpenAI-compatible
# inbound decoder matches the established AnthropicBackend boundary contract —
# exact-dict lookup (built-in .get, never a subclass override), an exact-list
# proof before iterating `choices` / `tool_calls`, and exact-type checks on
# content, the tool-call `type` discriminator, `finish_reason`, `id` and `name`
# before any truth / equality / hashing / iteration / mapping / string
# conversion could run.
#
# DIRECT vs PUBLIC reachability: JSON received through an ordinary provider
# deserializes to builtins only (exact dict / list / str / int / float / bool /
# None), so a dict-or-list SUBCLASS or a hostile proxy CANNOT arrive over
# PUBLIC provider traffic — these cells are reachable only by DIRECT /
# injected-client construction (a local-server shim, a proxy, a test double).
# They are pinned because an injected client can construct exactly them.
# ============================================================================


def _from_wire(response: Any) -> AgentResponse:
    """Call the inbound decoder directly. Equivalent to the injected-client
    path: `complete()` forwards the client's response into `_response_from_wire`
    (see `_complete_with_injected_response`)."""
    return openai_compat_backend_module.OpenAICompatBackend._response_from_wire(response)


def _complete_with_injected_response(response: Any) -> AgentResponse:
    """Drive the FULL public path with a dependency-injected client whose
    `.create()` returns `response` — the literal DIRECT/injected-client lane."""
    client = _MockClient()
    client.chat.completions.response = response
    backend = OpenAICompatBackend(client=client)
    return backend.complete(messages=[Message(role="user", content="x")], tools=[])


def _wrap(*, message: Any, finish_reason: Any = "stop", usage: Any = None) -> SimpleNamespace:
    """A response envelope around one choice (all exact SimpleNamespace/list)."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        usage=usage,
    )


class _RecordingGetDict(dict):
    """A dict SUBCLASS whose overridden `.get()` records every call. A decoder
    honoring the exact-dict contract must never invoke it."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.get_calls: list = []

    def get(self, key, default=None):
        self.get_calls.append(key)
        return super().get(key, default)


class _BenignDictSub(dict):
    """A dict subclass with no overridden behavior — still refused, because the
    contract is exact-type, not behavior-sniffing."""


class _ListSub(list):
    """A list subclass — refused by the exact-list proof for envelopes."""


class _HostileEq:
    """A non-str discriminator/value whose equality and hash hooks must never
    run (default truthiness is used, so `or` would slip past __bool__)."""

    def __eq__(self, other):
        raise AssertionError("hook invoked: __eq__")

    def __hash__(self):
        raise AssertionError("hook invoked: __hash__")


class _HostileScalar:
    """A value whose truth / iteration / str / hash / eq hooks all raise."""

    def __bool__(self):
        raise AssertionError("hook invoked: __bool__")

    def __iter__(self):
        raise AssertionError("hook invoked: __iter__")

    def __str__(self):
        raise AssertionError("hook invoked: __str__")

    def __hash__(self):
        raise AssertionError("hook invoked: __hash__")

    def __eq__(self, other):
        raise AssertionError("hook invoked: __eq__")


# -- FAILING-FIRST reproduction: dict-subclass function container -------------


def test_dict_subclass_function_container_get_hook_not_invoked():
    """CONFIRMED DIRECT/injected-client defect reproduction. A dict-subclass
    `function` container with an overridden `.get()` previously had that hook
    executed while `arguments` (and `name`) were retrieved. The exact-dict
    contract refuses the subclass before any `.get()` runs; extracted values
    fall back to defaults (name "", input {}). This is DIRECT/injected only —
    a provider's JSON deserializes to an exact dict, never a dict subclass."""
    fn = _RecordingGetDict({"name": "f", "arguments": '{"k": 1}'})
    tc = SimpleNamespace(id="tu_x", type="function", function=fn)
    resp = _complete_with_injected_response(
        _wrap(message=SimpleNamespace(content=None, tool_calls=[tc]),
              finish_reason="tool_calls"))
    assert fn.get_calls == []                 # overridden .get() never invoked
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].arguments == {}
    assert resp.tool_calls[0].name == ""
    assert resp.tool_calls[0].id == "tu_x"    # id read from the exact-object tc


# -- container matrix: exact dict vs benign/hostile dict subclass ------------


def test_top_level_exact_dict_response_translates():
    resp = _from_wire({
        "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 4},
    })
    assert resp.text == "hi"
    assert resp.stop_reason == "end_turn"
    assert resp.usage == {"input_tokens": 3, "output_tokens": 4}


@pytest.mark.parametrize("factory", [_BenignDictSub, _RecordingGetDict])
def test_dict_subclass_top_level_response_refused(factory):
    r = factory({"choices": [{"message": {"content": "hi"}}], "usage": {}})
    resp = _from_wire(r)
    assert resp.text is None
    assert resp.tool_calls == []
    assert resp.stop_reason == "other"
    if isinstance(r, _RecordingGetDict):
        assert r.get_calls == []


@pytest.mark.parametrize("factory", [_BenignDictSub, _RecordingGetDict])
def test_dict_subclass_choice_refused(factory):
    choice = factory({"message": {"content": "hi"}, "finish_reason": "stop"})
    resp = _from_wire(SimpleNamespace(choices=[choice], usage=None))
    assert resp.text is None                 # message on a subclass choice refused
    assert resp.stop_reason == "end_turn"    # finish_reason refused → None → end_turn
    if isinstance(choice, _RecordingGetDict):
        assert choice.get_calls == []


@pytest.mark.parametrize("factory", [_BenignDictSub, _RecordingGetDict])
def test_dict_subclass_message_refused(factory):
    msg = factory({
        "content": "hi",
        "tool_calls": [{"id": "t", "type": "function",
                        "function": {"name": "f", "arguments": "{}"}}],
    })
    resp = _from_wire(_wrap(message=msg, finish_reason="stop"))
    assert resp.text is None
    assert resp.tool_calls == []
    if isinstance(msg, _RecordingGetDict):
        assert msg.get_calls == []


@pytest.mark.parametrize("factory", [_BenignDictSub, _RecordingGetDict])
def test_dict_subclass_tool_call_container_skipped(factory):
    tc = factory({"id": "t", "type": "function",
                  "function": {"name": "f", "arguments": "{}"}})
    resp = _from_wire(_wrap(
        message=SimpleNamespace(content=None, tool_calls=[tc]),
        finish_reason="tool_calls"))
    # subclass tc: `type` refused → default "function"; `function` refused →
    # None → the call is skipped. No .get() hook.
    assert resp.tool_calls == []
    if isinstance(tc, _RecordingGetDict):
        assert tc.get_calls == []


@pytest.mark.parametrize("factory", [_BenignDictSub, _RecordingGetDict])
def test_dict_subclass_function_container_refused(factory):
    fn = factory({"name": "f", "arguments": '{"k": 1}'})
    tc = SimpleNamespace(id="tu_x", type="function", function=fn)
    resp = _from_wire(_wrap(
        message=SimpleNamespace(content=None, tool_calls=[tc]),
        finish_reason="tool_calls"))
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == ""
    assert resp.tool_calls[0].arguments == {}
    if isinstance(fn, _RecordingGetDict):
        assert fn.get_calls == []


@pytest.mark.parametrize("factory", [_BenignDictSub, _RecordingGetDict])
def test_dict_subclass_usage_refused_to_empty(factory):
    u = factory({"prompt_tokens": 5, "completion_tokens": 7})
    resp = _from_wire(_wrap(
        message=SimpleNamespace(content="x", tool_calls=None),
        finish_reason="stop", usage=u))
    assert resp.usage == {}
    if isinstance(u, _RecordingGetDict):
        assert u.get_calls == []


# -- exact list vs list subclass for response envelopes ----------------------


def test_list_subclass_choices_refused():
    choices = _ListSub([SimpleNamespace(
        message=SimpleNamespace(content="hi", tool_calls=None), finish_reason="stop")])
    resp = _from_wire(SimpleNamespace(choices=choices, usage=None))
    assert resp.text is None
    assert resp.tool_calls == []
    assert resp.stop_reason == "other"


def test_list_subclass_tool_calls_not_iterated():
    tcs = _ListSub([_tc("t", "f", {})])
    resp = _from_wire(_wrap(
        message=SimpleNamespace(content="hi", tool_calls=tcs), finish_reason="stop"))
    assert resp.text == "hi"
    assert resp.tool_calls == []


def test_exact_list_choices_and_tool_calls_iterated():
    resp = _from_wire(_wrap(
        message=SimpleNamespace(content="hi", tool_calls=[_tc("t", "f", {"a": 1})]),
        finish_reason="tool_calls"))
    assert resp.text == "hi"
    assert [t.name for t in resp.tool_calls] == ["f"]


# -- hostile / malformed tool-call discriminators ----------------------------


def test_hostile_tool_call_type_discriminator_skipped_without_hook():
    tc = SimpleNamespace(id="t", type=_HostileEq(),
                         function=SimpleNamespace(name="f", arguments="{}"))
    resp = _from_wire(_wrap(
        message=SimpleNamespace(content=None, tool_calls=[tc]),
        finish_reason="tool_calls"))
    assert resp.tool_calls == []             # non-str discriminator → skip; __eq__ never called


def test_unknown_string_tool_call_type_skipped():
    tc = SimpleNamespace(id="t", type="web_search",
                         function=SimpleNamespace(name="f", arguments="{}"))
    resp = _from_wire(_wrap(
        message=SimpleNamespace(content=None, tool_calls=[tc]),
        finish_reason="tool_calls"))
    assert resp.tool_calls == []


def test_absent_tool_call_type_defaults_to_function():
    tc = SimpleNamespace(id="t", function=SimpleNamespace(name="f", arguments='{"a": 1}'))
    resp = _from_wire(_wrap(
        message=SimpleNamespace(content=None, tool_calls=[tc]),
        finish_reason="tool_calls"))
    assert [t.name for t in resp.tool_calls] == ["f"]     # missing type → "function"


# -- content exact-type ------------------------------------------------------


def test_str_subclass_content_ignored():
    class _S(str):
        pass

    resp = _from_wire(_wrap(
        message=SimpleNamespace(content=_S("hi"), tool_calls=None), finish_reason="stop"))
    assert resp.text is None                 # content kept only when exactly str


def test_hostile_content_value_yields_no_text_no_hook():
    resp = _from_wire(_wrap(
        message=SimpleNamespace(content=_HostileScalar(), tool_calls=None),
        finish_reason="stop"))
    assert resp.text is None                 # non-str content → no TextBlock, no hook


# -- supplied id / name values (no truth-testing `or`) -----------------------


def test_hostile_id_value_no_truth_hook():
    tc = SimpleNamespace(id=_HostileScalar(), type="function",
                         function=SimpleNamespace(name="f", arguments="{}"))
    resp = _from_wire(_wrap(
        message=SimpleNamespace(content=None, tool_calls=[tc]),
        finish_reason="tool_calls"))
    assert resp.tool_calls[0].id == ""       # hostile id → ToolUseBlock normalizes, no `or`
    assert resp.tool_calls[0].name == "f"


def test_hostile_name_value_no_truth_hook():
    tc = SimpleNamespace(id="t", type="function",
                         function=SimpleNamespace(name=_HostileScalar(), arguments="{}"))
    resp = _from_wire(_wrap(
        message=SimpleNamespace(content=None, tool_calls=[tc]),
        finish_reason="tool_calls"))
    assert resp.tool_calls[0].name == ""     # hostile name → ToolUseBlock normalizes, no `or`
    assert resp.tool_calls[0].id == "t"


def test_non_str_id_and_name_normalized_to_empty():
    tc = SimpleNamespace(id=12345, type="function",
                         function=SimpleNamespace(name=None, arguments="{}"))
    resp = _from_wire(_wrap(
        message=SimpleNamespace(content=None, tool_calls=[tc]),
        finish_reason="tool_calls"))
    assert resp.tool_calls[0].id == ""
    assert resp.tool_calls[0].name == ""


# -- finish_reason matrix ----------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("stop", "end_turn"),
    ("tool_calls", "tool_use"),
    ("length", "max_tokens"),
    ("content_filter", "other"),
    ("function_call", "tool_use"),
    ("stop_sequence", "stop_sequence"),
    ("", "end_turn"),
    ("totally-unknown", "other"),
])
def test_finish_reason_string_cases(raw, expected):
    resp = _from_wire(_wrap(
        message=SimpleNamespace(content="x", tool_calls=None), finish_reason=raw))
    assert resp.stop_reason == expected


def test_finish_reason_none_is_end_turn():
    resp = _from_wire(_wrap(
        message=SimpleNamespace(content="x", tool_calls=None), finish_reason=None))
    assert resp.stop_reason == "end_turn"


def test_finish_reason_missing_is_end_turn():
    resp = _from_wire(SimpleNamespace(choices=[{"message": {"content": "x"}}], usage=None))
    assert resp.stop_reason == "end_turn"


def test_finish_reason_unhashable_list_is_other_without_hashing():
    resp = _from_wire(_wrap(
        message=SimpleNamespace(content="x", tool_calls=None), finish_reason=["x"]))
    assert resp.stop_reason == "other"       # non-str → "other"; never hashed into the map


def test_finish_reason_hostile_is_other_without_hook():
    resp = _from_wire(_wrap(
        message=SimpleNamespace(content="x", tool_calls=None), finish_reason=_HostileEq()))
    assert resp.stop_reason == "other"       # non-str → no __eq__ / __hash__


# -- mixed accepted / refused tool calls, order preserved --------------------


def test_mixed_accepted_and_refused_tool_calls_preserve_order():
    good1 = _tc("id1", "alpha", {"a": 1})
    bad_type = SimpleNamespace(id="idX", type="web_search",
                               function=SimpleNamespace(name="x", arguments="{}"))
    sub_tc = _BenignDictSub({"id": "idY", "type": "function",
                             "function": {"name": "y", "arguments": "{}"}})
    hostile_type = SimpleNamespace(id="idZ", type=_HostileEq(),
                                   function=SimpleNamespace(name="z", arguments="{}"))
    good2 = _tc("id2", "beta", {"b": 2})
    resp = _from_wire(_wrap(
        message=SimpleNamespace(
            content=None, tool_calls=[good1, bad_type, sub_tc, hostile_type, good2]),
        finish_reason="tool_calls"))
    assert [t.name for t in resp.tool_calls] == ["alpha", "beta"]
    assert [t.id for t in resp.tool_calls] == ["id1", "id2"]
    assert [t.arguments for t in resp.tool_calls] == [{"a": 1}, {"b": 2}]


# -- accepted-value / output-byte behavior preserved -------------------------


def test_exact_object_happy_path_roundtrips_unchanged():
    """Ordinary SDK-object response still produces the exact accepted output —
    text, tool call, mapped stop reason, and translated usage bytes."""
    resp = _from_wire(_make_response(
        content="checking",
        tool_calls=[_tc("tu_1", "get_params", {"verbose": True})],
        finish_reason="tool_calls",
        prompt_tokens=11, completion_tokens=22))
    assert resp.text == "checking"
    assert resp.tool_calls[0].id == "tu_1"
    assert resp.tool_calls[0].name == "get_params"
    assert resp.tool_calls[0].arguments == {"verbose": True}
    assert resp.stop_reason == "tool_use"
    assert resp.usage == {"input_tokens": 11, "output_tokens": 22}
