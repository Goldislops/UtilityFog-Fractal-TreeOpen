"""Tests for scripts/agent_backends/anthropic_backend.py (Phase 18 PR 5).

Uses dependency-injected mock clients — no network calls, no ANTHROPIC_API_KEY
required. Verifies:

  - Outbound translation: Message / ToolSpec / blocks → Anthropic wire format
  - System-prompt routing (top-level param, not a turn)
  - ToolResultBlock round-trip (inside user messages)
  - Inbound translation: Anthropic content blocks → AgentResponse
  - stop_reason mapping (known vs unknown)
  - Usage extraction
  - Transport errors propagate; empty content returns cleanly
  - Model override via constructor kwarg
  - Missing anthropic package raises at construction (sans injected client)
  - Inbound shape totality: hostile / malformed wire values (non-list
    content, non-str text, non-dict tool input, unhashable stop_reason,
    dict-shaped responses) decode totally and hook-free
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

import pytest

from scripts.agent_backends import (
    AgentResponse,
    AnthropicBackend,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
)


if AnthropicBackend is None:
    pytest.skip(
        "anthropic package not installed (scripts.agent_backends exported None)",
        allow_module_level=True,
    )


# -- test fixtures / mock client ---------------------------------------------


class _MockMessages:
    """Mirrors `client.messages` — just captures the kwargs and returns
    a caller-supplied response."""

    def __init__(self) -> None:
        self.last_request: Optional[dict] = None
        self.response: Any = None
        self.side_effect: Optional[BaseException] = None

    def create(self, **kwargs: Any) -> Any:
        self.last_request = kwargs
        if self.side_effect is not None:
            raise self.side_effect
        return self.response


class _MockClient:
    def __init__(self) -> None:
        self.messages = _MockMessages()


def _make_response(
    content: list,
    *,
    stop_reason: str = "end_turn",
    input_tokens: int = 10,
    output_tokens: int = 20,
) -> SimpleNamespace:
    """Build a duck-typed Anthropic response object using SimpleNamespace."""
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _text(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_use(tid: str, name: str, input_: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=tid, name=name, input=input_)


# -- outbound translation ----------------------------------------------------


def test_simple_text_message_is_forwarded_as_string_content():
    client = _MockClient()
    client.messages.response = _make_response([_text("ok")])
    backend = AnthropicBackend(model="test-model", client=client)

    backend.complete(
        messages=[Message(role="user", content="hello")],
        tools=[],
    )

    req = client.messages.last_request
    assert req["model"] == "test-model"
    assert req["messages"] == [{"role": "user", "content": "hello"}]
    assert "tools" not in req  # empty tool list omitted
    assert req["max_tokens"] == 2048
    assert req["temperature"] == 0.0


def test_block_list_content_is_forwarded_as_wire_blocks():
    client = _MockClient()
    client.messages.response = _make_response([_text("ok")])
    backend = AnthropicBackend(client=client)

    backend.complete(
        messages=[
            Message(role="assistant", content=[
                TextBlock(text="let me check"),
                ToolUseBlock(id="tu_1", name="get_params", input={"k": 1}),
            ]),
            Message(role="user", content=[
                ToolResultBlock(tool_use_id="tu_1", content="ok", is_error=False),
            ]),
        ],
        tools=[],
    )
    messages = client.messages.last_request["messages"]
    assert messages[0]["role"] == "assistant"
    assert messages[0]["content"] == [
        {"type": "text", "text": "let me check"},
        {"type": "tool_use", "id": "tu_1", "name": "get_params", "input": {"k": 1}},
    ]
    assert messages[1]["content"] == [
        {"type": "tool_result", "tool_use_id": "tu_1", "content": "ok"},
    ]


def test_tool_result_block_error_flag_propagates():
    client = _MockClient()
    client.messages.response = _make_response([_text("ok")])
    backend = AnthropicBackend(client=client)

    backend.complete(
        messages=[Message(role="user", content=[
            ToolResultBlock(tool_use_id="tu_err", content="boom", is_error=True),
        ])],
        tools=[],
    )
    block = client.messages.last_request["messages"][0]["content"][0]
    assert block["is_error"] is True


def test_tools_are_forwarded():
    client = _MockClient()
    client.messages.response = _make_response([_text("ok")])
    backend = AnthropicBackend(client=client)

    tool = ToolSpec(
        name="get_params",
        description="fetch current tunable params",
        input_schema={"type": "object", "properties": {}, "required": []},
    )
    backend.complete(messages=[Message(role="user", content="go")], tools=[tool])

    sent = client.messages.last_request["tools"]
    assert sent == [{
        "name": "get_params",
        "description": "fetch current tunable params",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    }]


def test_system_prompt_goes_to_top_level_system_parameter():
    client = _MockClient()
    client.messages.response = _make_response([_text("ok")])
    backend = AnthropicBackend(client=client)

    backend.complete(
        messages=[Message(role="user", content="hi")],
        tools=[],
        system="be concise",
    )
    assert client.messages.last_request["system"] == "be concise"


def test_system_role_in_messages_is_folded_into_user_turn():
    """If a caller puts role=system in messages (legacy shape), fold it
    into a user turn rather than silently dropping — no secret loss."""
    client = _MockClient()
    client.messages.response = _make_response([_text("ok")])
    backend = AnthropicBackend(client=client)

    backend.complete(
        messages=[
            Message(role="system", content="you are agent 84"),
            Message(role="user", content="hi"),
        ],
        tools=[],
    )
    messages = client.messages.last_request["messages"]
    assert messages[0]["role"] == "user"
    assert "you are agent 84" in messages[0]["content"]


def test_max_tokens_and_temperature_are_forwarded():
    client = _MockClient()
    client.messages.response = _make_response([_text("ok")])
    backend = AnthropicBackend(client=client)

    backend.complete(
        messages=[Message(role="user", content="x")],
        tools=[],
        max_tokens=512,
        temperature=0.7,
    )
    req = client.messages.last_request
    assert req["max_tokens"] == 512
    assert req["temperature"] == 0.7


# -- inbound translation -----------------------------------------------------


def test_response_text_blocks_concatenate_into_text():
    client = _MockClient()
    client.messages.response = _make_response([_text("hello, "), _text("world")])
    backend = AnthropicBackend(client=client)

    resp = backend.complete(messages=[Message(role="user", content="x")], tools=[])
    assert isinstance(resp, AgentResponse)
    assert resp.text == "hello, \nworld"
    assert resp.tool_calls == []
    assert resp.stop_reason == "end_turn"


def test_response_tool_use_blocks_extract_into_tool_calls():
    client = _MockClient()
    client.messages.response = _make_response(
        [_tool_use("tu_1", "get_params", {"verbose": True})],
        stop_reason="tool_use",
    )
    backend = AnthropicBackend(client=client)

    resp = backend.complete(messages=[Message(role="user", content="x")], tools=[])
    assert resp.text is None
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].id == "tu_1"
    assert resp.tool_calls[0].name == "get_params"
    assert resp.tool_calls[0].arguments == {"verbose": True}
    assert resp.stop_reason == "tool_use"


def test_response_mixed_text_and_tool_use_preserves_both():
    client = _MockClient()
    client.messages.response = _make_response(
        [_text("fetching..."), _tool_use("tu_1", "get_params", {})],
        stop_reason="tool_use",
    )
    backend = AnthropicBackend(client=client)

    resp = backend.complete(messages=[Message(role="user", content="x")], tools=[])
    assert resp.text == "fetching..."
    assert len(resp.tool_calls) == 1
    # raw_content preserves both blocks in order for history replay.
    assert len(resp.raw_content) == 2


def test_unknown_stop_reason_maps_to_other():
    client = _MockClient()
    client.messages.response = _make_response([_text("x")], stop_reason="refusal")
    backend = AnthropicBackend(client=client)

    resp = backend.complete(messages=[Message(role="user", content="x")], tools=[])
    assert resp.stop_reason == "other"


def test_usage_is_extracted_into_response():
    client = _MockClient()
    client.messages.response = _make_response(
        [_text("ok")], input_tokens=123, output_tokens=45,
    )
    backend = AnthropicBackend(client=client)

    resp = backend.complete(messages=[Message(role="user", content="x")], tools=[])
    assert resp.usage["input_tokens"] == 123
    assert resp.usage["output_tokens"] == 45


def test_dict_shaped_content_blocks_also_translate():
    """Backwards-compat: older SDK versions return dicts, not typed objects."""
    client = _MockClient()
    client.messages.response = SimpleNamespace(
        content=[
            {"type": "text", "text": "dict-shape"},
            {"type": "tool_use", "id": "tu_d", "name": "f", "input": {}},
        ],
        stop_reason="tool_use",
        usage=None,
    )
    backend = AnthropicBackend(client=client)

    resp = backend.complete(messages=[Message(role="user", content="x")], tools=[])
    assert resp.text == "dict-shape"
    assert resp.tool_calls[0].id == "tu_d"


def test_empty_content_returns_clean_response():
    client = _MockClient()
    client.messages.response = _make_response([], stop_reason="end_turn")
    backend = AnthropicBackend(client=client)

    resp = backend.complete(messages=[Message(role="user", content="x")], tools=[])
    assert resp.text is None
    assert resp.tool_calls == []
    assert resp.raw_content == []


# -- inbound shape totality: wire values in a response are model/server-
#    reachable and can be ANY shape. Supported containers are SDK-style
#    typed objects (ordinary attribute access — inherent to supporting
#    them) and exact built-in dicts; dict SUBCLASSES are refused without
#    invoking their overridden .get() or attribute hooks (Amendment 1).
#    Within that contract decoding is total and hook-free over extracted
#    field values: content decodes only from an exact list; text kept only
#    when exactly str; tool_use input kept only when exactly dict (never
#    derived from pair-lists) and continues into ToolUseBlock's hardened
#    normalization; stop_reason keeps established semantics (absent/None/
#    empty exact string → "end_turn", known exact string → itself, any
#    other shape → "other" without hashing, truth-testing, or comparison
#    hooks). No __bool__ / __len__ / __iter__ / keys() / __str__ / __eq__
#    hook of an extracted field value is ever invoked. ------------------------


class _HostileValue:
    """Wire value whose truthiness / iteration / mapping-conversion /
    string-conversion hooks all raise if invoked."""

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


class _RaisingEq:
    """Wire value whose equality hook raises if invoked."""

    def __eq__(self, other):
        raise AssertionError("hook invoked: __eq__")

    __hash__ = None


def _complete(response) -> AgentResponse:
    client = _MockClient()
    client.messages.response = response
    backend = AnthropicBackend(client=client)
    return backend.complete(messages=[Message(role="user", content="x")], tools=[])


def test_dict_shaped_response_recovers_content_and_usage():
    """A fully dict-shaped response (very old SDKs / proxies / injected
    clients) must decode content AND usage — the old bare getattr silently
    dropped both."""
    resp = _complete({
        "content": [{"type": "text", "text": "dict-response"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 1, "output_tokens": 2},
    })
    assert resp.text == "dict-response"
    assert resp.usage == {"input_tokens": 1, "output_tokens": 2}


def test_pair_list_tool_input_is_not_dict_derived():
    """The old eager dict(...) manufactured {"a": 1} from a pair-list wire
    value; ToolUseBlock.input must never be derived from other shapes."""
    resp = _complete(_make_response(
        [_tool_use("tu_1", "f", [["a", 1]])], stop_reason="tool_use",
    ))
    assert resp.tool_calls[0].arguments == {}


def test_non_mapping_tool_input_normalizes_to_empty_dict():
    """dict(5) / dict([1, 2]) raised TypeError out of complete(); any
    non-exact-dict input must become a fresh {} instead."""
    for bad in (5, [1, 2]):
        resp = _complete(_make_response(
            [_tool_use("tu_1", "f", bad)], stop_reason="tool_use",
        ))
        assert resp.tool_calls[0].arguments == {}, f"input={bad!r}"


def test_hostile_tool_input_value_never_has_hooks_invoked():
    """The old `or {}` executed the value's __bool__; hostile hook objects
    must decode to {} with no hook invoked."""
    resp = _complete(_make_response(
        [_tool_use("tu_1", "f", _HostileValue())], stop_reason="tool_use",
    ))
    assert resp.tool_calls[0].arguments == {}


def test_exact_dict_tool_input_passes_through():
    """An exact dict keeps its content (through ToolUseBlock's hardened
    normalization) — behavior lock."""
    resp = _complete(_make_response(
        [_tool_use("tu_1", "f", {"k": 1})], stop_reason="tool_use",
    ))
    assert resp.tool_calls[0].arguments == {"k": 1}


def test_non_str_text_value_normalizes_to_empty():
    """A truthy non-str text (e.g. 123) used to reach the from_content
    join and raise TypeError; it must decode as an empty text."""
    resp = _complete(_make_response([SimpleNamespace(type="text", text=123)]))
    assert resp.text == ""


def test_hostile_text_value_never_has_hooks_invoked():
    """The old `or ""` executed the text value's __bool__; hostile hook
    objects must decode as empty text with no hook invoked."""
    resp = _complete(_make_response(
        [SimpleNamespace(type="text", text=_HostileValue())],
    ))
    assert resp.text == ""


def test_unhashable_or_hostile_stop_reason_maps_to_other():
    """An unhashable stop_reason crashed the set-membership test and a
    hostile one had its __bool__ executed by `or`; both are unexpected
    model shapes and must map to "other"."""
    for bad in (["end_turn"], _HostileValue()):
        resp = _complete(_make_response([], stop_reason=bad))
        assert resp.stop_reason == "other", f"stop_reason={type(bad).__name__}"


def test_empty_string_stop_reason_stays_end_turn():
    """Amendment 1 (Jack finding 1): the established pre-PR semantics map
    an empty exact-string stop_reason to "end_turn" — restored, and pinned
    without truth-testing unproven values (exact-str proof, then ==)."""
    resp = _complete(_make_response([], stop_reason=""))
    assert resp.stop_reason == "end_turn"


def test_absent_stop_reason_defaults_to_end_turn():
    """Absent (None) stop_reason keeps its established "end_turn" default
    — behavior lock."""
    resp = _complete(_make_response([], stop_reason=None))
    assert resp.stop_reason == "end_turn"


def test_non_list_content_yields_no_blocks():
    """Content is decoded only from an exact list: a hostile object (whose
    __bool__ the old `or []` executed), a str (whose chars the old code
    iterated), a list SUBCLASS (refused before iteration — its __iter__ is
    never invoked), a bool, a number, an exact dict, a tuple, or any other
    shape must yield a clean empty response."""

    class _HostileList(list):
        def __iter__(self):
            raise AssertionError("hook invoked: __iter__")

    variants = (
        _HostileValue(),
        "hi",
        42,
        _HostileList([{"type": "text", "text": "x"}]),
        True,
        3.5,
        {"type": "text", "text": "x"},
        ({"type": "text", "text": "x"},),
    )
    for bad in variants:
        resp = _complete(_make_response(bad))
        assert resp.raw_content == [], f"content={type(bad).__name__}"
        assert resp.text is None


def test_raising_eq_block_type_is_skipped():
    """A block whose `type` raises on equality comparison must be skipped
    (exact-str proof before dispatch), not crash the decode."""
    resp = _complete(_make_response(
        [SimpleNamespace(type=_RaisingEq(), text="x")],
    ))
    assert resp.raw_content == []


def test_non_str_block_type_is_skipped():
    """A non-str block type (e.g. 42) is skipped — behavior lock."""
    resp = _complete(_make_response([SimpleNamespace(type=42, text="x")]))
    assert resp.raw_content == []


# -- Amendment 1 matrix: dict-subclass container refusal + stop_reason pins --


class _HostileDict(dict):
    """dict subclass whose mapping and attribute hooks raise if invoked.
    Data is seeded through the built-in dict constructor (C-level); only
    the overridden accessors are hostile."""

    def get(self, *args, **kwargs):
        raise AssertionError("hook invoked: get()")

    def __getattr__(self, name):
        raise AssertionError("hook invoked: __getattr__")

    def keys(self):
        raise AssertionError("hook invoked: keys()")

    def __iter__(self):
        raise AssertionError("hook invoked: __iter__")

    def __bool__(self):
        raise AssertionError("hook invoked: __bool__")

    def __len__(self):
        raise AssertionError("hook invoked: __len__")

    def __str__(self):
        raise AssertionError("hook invoked: __str__")


class _BenignSubDict(dict):
    """dict subclass with NO overrides — still refused: the supported-
    container contract is exact built-in dict, not isinstance(dict)."""


class _WeirdStr(str):
    """str subclass — not an exact string."""


def test_top_level_dict_subclass_response_refused_without_hooks():
    """A dict-subclass response container is refused before any attribute
    or .get() access: clean empty response, absent-field semantics."""
    resp = _complete(_HostileDict(
        content=[{"type": "text", "text": "hi"}],
        stop_reason="end_turn",
        usage={"input_tokens": 1, "output_tokens": 2},
    ))
    assert resp.raw_content == []
    assert resp.text is None
    assert resp.stop_reason == "end_turn"
    assert resp.usage == {}


def test_dict_subclass_content_block_skipped_without_hooks():
    """A dict-subclass content block is refused (type discriminator reads
    as absent) without invoking its .get() or attribute hooks."""
    resp = _complete(_make_response([_HostileDict(type="text", text="x")]))
    assert resp.raw_content == []


def test_exact_dict_usage_accepted():
    """A plain-dict usage container on a typed response keeps its counters
    — behavior lock for the supported-container contract."""
    resp = _complete(SimpleNamespace(
        content=[], stop_reason="end_turn",
        usage={"input_tokens": 7, "output_tokens": 9},
    ))
    assert resp.usage == {"input_tokens": 7, "output_tokens": 9}


def test_dict_subclass_usage_refused_to_empty():
    """A dict-subclass usage container — hostile or benign — is refused to
    an EMPTY usage dict (not a dict of two None counters), without hooks."""
    for u in (_HostileDict(input_tokens=1, output_tokens=2),
              _BenignSubDict(input_tokens=1, output_tokens=2)):
        resp = _complete(SimpleNamespace(content=[], stop_reason="end_turn", usage=u))
        assert resp.usage == {}, f"usage container={type(u).__name__}"


def test_dict_subclass_tool_input_normalizes_to_empty_dict():
    """A dict-subclass tool input is not an exact dict: normalized to a
    fresh {} without invoking its hooks — same rule as pair-lists."""
    for bad in (_HostileDict(k=1), _BenignSubDict(k=1)):
        resp = _complete(_make_response(
            [_tool_use("tu_1", "f", bad)], stop_reason="tool_use",
        ))
        assert resp.tool_calls[0].arguments == {}, f"input={type(bad).__name__}"


def test_str_subclass_block_type_is_skipped():
    """A str-subclass block discriminator is not an exact str: the block
    is skipped — behavior lock."""
    resp = _complete(_make_response(
        [SimpleNamespace(type=_WeirdStr("text"), text="x")],
    ))
    assert resp.raw_content == []


def test_str_subclass_stop_reason_maps_to_other():
    """A str-subclass stop_reason is not an exact str: maps to "other"
    without hashing or comparison of the supplied value — behavior lock."""
    resp = _complete(_make_response([], stop_reason=_WeirdStr("end_turn")))
    assert resp.stop_reason == "other"


def test_known_stop_reasons_pass_through():
    """Every known non-empty exact-string stop_reason maps to itself —
    behavior lock."""
    for known in ("end_turn", "tool_use", "max_tokens", "stop_sequence", "error"):
        resp = _complete(_make_response([], stop_reason=known))
        assert resp.stop_reason == known


def test_absent_stop_reason_field_defaults_to_end_turn():
    """A response with NO stop_reason field at all (not just None) keeps
    the "end_turn" default — behavior lock."""
    resp = _complete(SimpleNamespace(content=[], usage=None))
    assert resp.stop_reason == "end_turn"


def test_mixed_valid_and_refused_blocks_preserve_order():
    """Refused blocks (dict-subclass, non-str type) are skipped without
    disturbing the relative order of accepted blocks."""
    resp = _complete(_make_response([
        {"type": "text", "text": "first"},
        _HostileDict(type="tool_use", id="evil", name="evil", input={}),
        SimpleNamespace(type="tool_use", id="tu_1", name="f", input={"k": 1}),
        SimpleNamespace(type=42, text="skip"),
        {"type": "text", "text": "last"},
    ], stop_reason="tool_use"))
    assert [type(b).__name__ for b in resp.raw_content] == [
        "TextBlock", "ToolUseBlock", "TextBlock",
    ]
    assert resp.raw_content[0].text == "first"
    assert resp.raw_content[1].id == "tu_1"
    assert resp.raw_content[2].text == "last"


# -- error-path / construction ----------------------------------------------


def test_transport_error_propagates():
    client = _MockClient()
    client.messages.side_effect = RuntimeError("network down")
    backend = AnthropicBackend(client=client)
    with pytest.raises(RuntimeError, match="network down"):
        backend.complete(messages=[Message(role="user", content="x")], tools=[])


def test_backend_uses_configured_model():
    client = _MockClient()
    client.messages.response = _make_response([_text("x")])
    backend = AnthropicBackend(model="claude-test-99", client=client)
    backend.complete(messages=[Message(role="user", content="x")], tools=[])
    assert client.messages.last_request["model"] == "claude-test-99"


def test_backend_name_classvar():
    client = _MockClient()
    backend = AnthropicBackend(client=client)
    assert backend.name == "anthropic"
