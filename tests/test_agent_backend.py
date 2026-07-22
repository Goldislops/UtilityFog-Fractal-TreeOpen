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
  - ToolUseBlock value-shape normalization: exact-str id/name bounded to
    256/128 chars, exact-dict input, hostile shapes replaced without
    invoking any conversion/length/representation hook.
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


# -- ToolUseBlock value-shape normalization ----------------------------------
#
# ToolUseBlock.__post_init__ must produce a consistent bounded shape before
# AgentResponse.from_content derives tool calls:
#   - id/name kept only when type(value) is str, sliced to 256/128 chars;
#     every other exact type becomes "" with no conversion and no
#     type-name reporting.
#   - input kept only when type(input) is dict; every other exact type
#     (including dict subclasses) is replaced by a fresh empty dict.
# The hostile instruments below raise _HookCalled from every conversion,
# length, and representation hook, so a passing test is proof the
# normalization never requested any of those methods.


class _HookCalled(Exception):
    """Raised by hostile instruments when any forbidden hook is requested."""


class _HostileValue:
    """Non-str/non-dict object whose hooks all raise."""

    def __str__(self):
        raise _HookCalled("__str__")

    def __repr__(self):
        raise _HookCalled("__repr__")

    def __format__(self, spec):
        raise _HookCalled("__format__")

    def __bytes__(self):
        raise _HookCalled("__bytes__")

    def __len__(self):
        raise _HookCalled("__len__")

    def __bool__(self):
        raise _HookCalled("__bool__")

    def __int__(self):
        raise _HookCalled("__int__")

    def __index__(self):
        raise _HookCalled("__index__")

    def __iter__(self):
        raise _HookCalled("__iter__")

    def keys(self):
        raise _HookCalled("keys")


class _HostileStr(str):
    """str subclass whose hooks raise — the exact-type gate must refuse it
    without requesting any of these methods."""

    def __str__(self):
        raise _HookCalled("__str__")

    def __repr__(self):
        raise _HookCalled("__repr__")

    def __len__(self):
        raise _HookCalled("__len__")

    def __getitem__(self, item):
        raise _HookCalled("__getitem__")

    def __bool__(self):
        raise _HookCalled("__bool__")


class _PlainStrSub(str):
    """Well-behaved str subclass — still refused, proving the gate is
    exact-type, not isinstance."""


class _PlainDictSub(dict):
    """Well-behaved dict subclass — still replaced, proving the gate is
    exact-type, not isinstance."""


class _HostileDict(dict):
    """dict subclass whose view/iteration hooks raise — must be replaced
    without requesting any of these methods."""

    def keys(self):
        raise _HookCalled("keys")

    def items(self):
        raise _HookCalled("items")

    def values(self):
        raise _HookCalled("values")

    def __iter__(self):
        raise _HookCalled("__iter__")

    def __len__(self):
        raise _HookCalled("__len__")

    def __bool__(self):
        raise _HookCalled("__bool__")

    def __getitem__(self, key):
        raise _HookCalled("__getitem__")

    def copy(self):
        raise _HookCalled("copy")


_NON_STR_VALUES = [123, 1.5, True, False, None, b"bytes", ["list"], {"d": 1}, ("t",)]
_NON_STR_IDS = ["int", "float", "true", "false", "none", "bytes", "list", "dict", "tuple"]

_NON_DICT_INPUTS = [["array"], "string", b"bytes", 42, 3.14, True, False, None, ("k", "v")]
_NON_DICT_IDS = ["array", "string", "bytes", "int", "float", "true", "false", "none", "tuple"]


def test_normalization_preserves_wellformed_name_id_and_input():
    d = {"x": 1, "nested": {"y": 2}}
    b = ToolUseBlock(id="tu_wellformed", name="get_params", input=d)
    assert b.id == "tu_wellformed"
    assert b.name == "get_params"
    assert b.input is d  # preserved, not copied — current behavior retained
    assert b.type == "tool_use"


def test_normalization_preserves_exact_boundary_lengths():
    name_128 = "a" * 127 + "b"
    id_256 = "c" * 255 + "d"
    b = ToolUseBlock(id=id_256, name=name_128)
    assert b.name == name_128
    assert len(b.name) == 128
    assert b.id == id_256
    assert len(b.id) == 256


def test_normalization_truncates_above_boundary_deterministically():
    long_name = "n" * 127 + "XY"  # 129 chars
    long_id = "i" * 255 + "XY"  # 257 chars
    b1 = ToolUseBlock(id=long_id, name=long_name)
    b2 = ToolUseBlock(id=long_id, name=long_name)
    assert b1.name == long_name[:128]
    assert len(b1.name) == 128
    assert b1.id == long_id[:256]
    assert len(b1.id) == 256
    # deterministic: identical inputs → identical normalized values
    assert b1.name == b2.name
    assert b1.id == b2.id


@pytest.mark.parametrize("value", _NON_STR_VALUES, ids=_NON_STR_IDS)
def test_normalization_replaces_non_str_name(value):
    b = ToolUseBlock(id="tu_1", name=value)
    assert type(b.name) is str
    assert b.name == ""  # no conversion, no type-name reporting
    assert b.id == "tu_1"


@pytest.mark.parametrize("value", _NON_STR_VALUES, ids=_NON_STR_IDS)
def test_normalization_replaces_non_str_id(value):
    b = ToolUseBlock(id=value, name="get_params")
    assert type(b.id) is str
    assert b.id == ""
    assert b.name == "get_params"


def test_normalization_replaces_str_subclass_name_and_id():
    b = ToolUseBlock(id=_PlainStrSub("tu_sub"), name=_PlainStrSub("sub_name"))
    assert type(b.id) is str
    assert b.id == ""
    assert type(b.name) is str
    assert b.name == ""


def test_normalization_refuses_hostile_str_subclass_without_hooks():
    # Constructing must not raise _HookCalled: no len/slice/str on the value.
    b = ToolUseBlock(id=_HostileStr("evil-id"), name=_HostileStr("evil-name"))
    assert b.id == ""
    assert b.name == ""


def test_normalization_refuses_hostile_object_name_id_without_hooks():
    b = ToolUseBlock(id=_HostileValue(), name=_HostileValue())
    assert b.id == ""
    assert b.name == ""


def test_normalization_refuses_hostile_name_and_id_separately():
    # Each field is gated on its own: a hostile value in one never
    # disturbs a well-formed value in the other, and no hook runs.
    b1 = ToolUseBlock(id="tu_ok", name=_HostileValue())
    assert b1.id == "tu_ok"
    assert b1.name == ""
    b2 = ToolUseBlock(id=_HostileValue(), name="get_params")
    assert b2.id == ""
    assert b2.name == "get_params"


@pytest.mark.parametrize("bad_input", _NON_DICT_INPUTS, ids=_NON_DICT_IDS)
def test_normalization_replaces_non_dict_input(bad_input):
    b = ToolUseBlock(id="tu_1", name="get_params", input=bad_input)
    assert type(b.input) is dict
    assert b.input == {}


def test_normalization_replaces_dict_subclass_input_without_deriving():
    b = ToolUseBlock(id="tu_1", name="get_params", input=_PlainDictSub({"a": 1}))
    assert type(b.input) is dict
    assert b.input == {}  # replaced, not derived — contents dropped


def test_normalization_replaces_hostile_dict_subclass_without_hooks():
    b = ToolUseBlock(id="tu_1", name="get_params", input=_HostileDict())
    assert type(b.input) is dict
    assert b.input == {}


def test_normalization_replaces_hostile_object_input_without_hooks():
    b = ToolUseBlock(id="tu_1", name="get_params", input=_HostileValue())
    assert type(b.input) is dict
    assert b.input == {}


def test_normalization_replacement_dicts_are_independent():
    b1 = ToolUseBlock(id="tu_1", name="n", input=["not-a-dict"])
    b2 = ToolUseBlock(id="tu_2", name="n", input="also-not")
    assert b1.input is not b2.input
    b1.input["k"] = "v"
    assert b2.input == {}


def test_default_input_dicts_are_independent_instances():
    b1 = ToolUseBlock(id="tu_1", name="n")
    b2 = ToolUseBlock(id="tu_2", name="n")
    assert b1.input is not b2.input
    b1.input["k"] = "v"
    assert b2.input == {}


def test_normalized_block_remains_frozen():
    b = ToolUseBlock(id="tu_1", name="get_params")
    with pytest.raises(Exception):
        b.name = "other"  # frozen dataclass → FrozenInstanceError


def test_from_content_returns_normally_for_every_normalized_shape():
    blocks = [
        ToolUseBlock(id=123, name=None, input=["array"]),
        ToolUseBlock(id=_HostileValue(), name=_HostileStr("x"), input=_HostileDict()),
        ToolUseBlock(id=_PlainStrSub("s"), name=b"bytes", input="string"),
        ToolUseBlock(id=None, name=True, input=42),
        ToolUseBlock(id="tu_ok", name="fine", input={"k": 1}),
    ]
    resp = AgentResponse.from_content(blocks)
    assert len(resp.tool_calls) == len(blocks)
    for tc in resp.tool_calls[:4]:
        assert tc.id == ""
        assert tc.name == ""
        assert tc.arguments == {}
    assert resp.tool_calls[4].id == "tu_ok"
    assert resp.tool_calls[4].arguments == {"k": 1}


def test_from_content_tool_call_reflects_normalized_block():
    long_name = "m" * 200
    b = ToolUseBlock(id="tu_long", name=long_name, input={"a": 1})
    resp = AgentResponse.from_content([b])
    tc = resp.tool_calls[0]
    assert tc.name == long_name[:128]
    assert tc.name == b.name  # ToolCall mirrors the normalized block
    assert tc.arguments == b.input
    assert tc.arguments is not b.input  # copy semantics retained


def test_from_content_raw_content_carries_normalized_blocks():
    b = ToolUseBlock(id="x" * 300, name=_HostileValue(), input=("not", "dict"))
    resp = AgentResponse.from_content([b])
    assert resp.raw_content[0] is b  # same object, already normalized
    assert resp.raw_content[0].id == "x" * 256
    assert resp.raw_content[0].name == ""
    assert resp.raw_content[0].input == {}
    # derived ToolCall and raw_content reflect the SAME normalized shape
    assert resp.tool_calls[0].id == resp.raw_content[0].id
    assert resp.tool_calls[0].name == resp.raw_content[0].name
    assert resp.tool_calls[0].arguments == resp.raw_content[0].input


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
