"""OMI-V2 - the tool-call ``arguments`` JSON-string boundary, both directions.

The module's translation table - documented as "the entire contract" -
promises that an assistant tool call goes on the wire with ``arguments`` as a
JSON STRING. Before this correction the emission encoder ran with the default
``allow_nan=True``, so a non-finite float inside ``ToolUseBlock.input``
serialized as the ``Infinity`` / ``NaN`` token RFC 8259 forbids - and the
backend's own inbound ``arguments`` decode manufactured exactly those floats
from model-controlled bytes (an ``Infinity`` / ``NaN`` token or an
overflowing literal such as ``1e400``).

These tests pin both closures and everything that must not move: the
byte-verbatim raw fallback, finite decoding, empty / non-object handling,
hostile-container refusals, and the deliberate duplicate-key last-wins
semantics of the exact-dict JSON decode.
"""

from __future__ import annotations

import json
import math
import socket
from types import SimpleNamespace

import pytest

from scripts.agent_backends.base import Message, ToolUseBlock
from scripts.agent_backends.openai_compat_backend import OpenAICompatBackend


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def _refuse(*args, **kwargs):
        raise AssertionError("a socket was created during a hermetic test")

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


class RecordingClient:
    """Canned SDK-shaped client: records outbound requests, answers with one
    tool call carrying whatever ``arguments`` the test supplies (or plain
    text content when ``arguments`` is not given)."""

    _ABSENT = object()

    def __init__(self, arguments=_ABSENT, content=None):
        self.requests: list[dict] = []
        self._arguments = arguments
        self._content = content
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        tool_calls = None
        if self._arguments is not self._ABSENT:
            tool_calls = [
                SimpleNamespace(
                    type="function",
                    id="call_1",
                    function=SimpleNamespace(name="t", arguments=self._arguments),
                )
            ]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=self._content, tool_calls=tool_calls
                    ),
                    finish_reason="tool_calls" if tool_calls else "stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2),
        )


def _backend(client) -> OpenAICompatBackend:
    return OpenAICompatBackend(model="m", client=client, dialect="vllm")


def _ingress(arguments):
    """One forged tool-call response through ``complete()``; the block input."""
    resp = _backend(RecordingClient(arguments=arguments)).complete(
        [Message(role="user", content="hi")], []
    )
    (block,) = [b for b in resp.raw_content if type(b) is ToolUseBlock]
    return block.input


def _emitted_arguments(input_dict):
    """Serialize one assistant ToolUseBlock through the wire translation."""
    backend = _backend(RecordingClient(content="ok"))
    message = Message(
        role="assistant",
        content=[ToolUseBlock(id="i1", name="t", input=input_dict)],
    )
    (wire,) = backend._message_to_wire(message)
    return wire["tool_calls"][0]["function"]["arguments"]


def _strict_json(text):
    """True iff ``text`` is RFC-8259 JSON: no NaN / Infinity tokens."""

    def refuse(_token):
        raise ValueError("non-finite token")

    try:
        json.loads(text, parse_constant=refuse)
        return True
    except ValueError:
        return False


_FIXED_ERROR = "tool-call arguments could not be encoded as strict JSON"


# -- 1. inbound: non-finite spellings fold into the byte-verbatim fallback ----


@pytest.mark.parametrize(
    "payload",
    [
        '{"x": Infinity}',
        '{"x": -Infinity}',
        '{"x": NaN}',
        '{"x": 1e400}',
        '{"x": -1e400}',
        '{"x": 1e309}',
        '{"a": [{"b": -1e400}]}',
        "[1e400]",
    ],
)
def test_a_non_finite_spelling_becomes_the_raw_fallback(payload):
    args = _ingress(payload)
    assert args == {"_raw_arguments": payload}
    # Byte-verbatim: the model's exact bytes stay available, undecoded.
    assert args["_raw_arguments"] == payload


def test_the_fallback_carries_no_float_at_all():
    args = _ingress('{"x": Infinity, "y": 1e400}')
    assert set(map(type, args.values())) == {str}


# -- 2. inbound: finite and structural behavior is unchanged -------------------


def test_finite_arguments_decode_exactly():
    args = _ingress('{"x": 3.5, "n": 7, "s": "ok"}')
    assert args == {"x": 3.5, "n": 7, "s": "ok"}
    assert math.isfinite(args["x"])


@pytest.mark.parametrize(
    "payload,expected",
    [
        ("", {}),                       # empty string
        ("[1.5]", {}),                  # valid JSON, not an object
        ('"a bare string"', {}),        # valid JSON, not an object
        ('{"x": 1e-400}', {"x": 0.0}),  # underflow is finite: accepted
        (
            '{"x": 1.7976931348623157e308}',
            {"x": 1.7976931348623157e308},
        ),                              # maximum finite: accepted
    ],
)
def test_established_string_decoding_is_unchanged(payload, expected):
    assert _ingress(payload) == expected


def test_undecodable_arguments_keep_the_raw_fallback():
    args = _ingress("not json at all")
    assert args == {"_raw_arguments": "not json at all"}


def test_duplicate_keys_still_read_last_wins():
    # Deliberate, documented decode semantics of the arguments dict - pinned
    # so this correction cannot be mistaken for having changed them.
    assert _ingress('{"x": 1, "x": 2}') == {"x": 2}


# -- 3. inbound: container discipline is unchanged -----------------------------


def test_a_str_subclass_is_still_refused_to_empty():
    class SneakyStr(str):
        pass

    assert _ingress(SneakyStr('{"x": 1}')) == {}


def test_an_exact_dict_still_passes_through():
    assert _ingress({"a": 1}) == {"a": 1}


def test_a_dict_subclass_is_still_refused_to_empty():
    class SneakyDict(dict):
        def __getitem__(self, key):  # pragma: no cover - must never run
            raise AssertionError("a mapping hook ran")

    assert _ingress(SneakyDict({"a": 1})) == {}


def test_a_hostile_object_is_refused_without_invoking_hooks():
    class Hostile:
        def __bool__(self):
            raise AssertionError("__bool__ ran")

        def __iter__(self):
            raise AssertionError("__iter__ ran")

        def __str__(self):
            raise AssertionError("__str__ ran")

    assert _ingress(Hostile()) == {}


def test_absent_arguments_still_become_an_empty_dict():
    assert _ingress(None) == {}


# -- 4. outbound: finite inputs emit strict JSON that round-trips --------------


def test_finite_input_emits_strict_json():
    source = {"x": 3.5, "n": 7, "s": "ok", "b": True, "z": None}
    text = _emitted_arguments(source)
    assert _strict_json(text)
    assert json.loads(text) == source


def test_empty_input_emits_the_empty_object():
    assert _emitted_arguments({}) == "{}"


def test_the_default_str_escape_hatch_is_preserved():
    text = _emitted_arguments({"o": object()})
    assert _strict_json(text)
    assert json.loads(text)["o"].startswith("<object object")


# -- 5. outbound: non-finite input refuses with one fixed error ----------------


@pytest.mark.parametrize(
    "poisoned",
    [
        {"x": float("inf")},
        {"x": float("-inf")},
        {"x": float("nan")},
        {"a": [{"b": float("nan")}]},
    ],
)
def test_a_non_finite_input_raises_the_fixed_error(poisoned):
    with pytest.raises(ValueError) as caught:
        _emitted_arguments(poisoned)
    assert str(caught.value) == _FIXED_ERROR
    # Non-disclosing and unchained: no encoder text, no value, no name.
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


def test_a_circular_exact_dict_raises_the_same_fixed_error():
    # The encoder raises ValueError for a circular container too, so the
    # replacement text truthfully names the failure - not a presumed
    # non-finite cause. A circular exact dict is reachable: ToolUseBlock
    # keeps any exact dict, and the exact-dict arguments path above copies
    # nothing.
    loop: dict = {}
    loop["loop"] = loop
    with pytest.raises(ValueError) as caught:
        _emitted_arguments(loop)
    assert str(caught.value) == _FIXED_ERROR
    assert caught.value.__cause__ is None


def test_the_refusal_happens_before_any_transport():
    client = RecordingClient(content="ok")
    backend = _backend(client)
    poisoned = [
        Message(role="user", content="hi"),
        Message(
            role="assistant",
            content=[ToolUseBlock(id="i1", name="t", input={"x": float("inf")})],
        ),
    ]
    with pytest.raises(ValueError):
        backend.complete(poisoned, [])
    assert client.requests == []


# -- 6. the loop is closed: hostile ingress now re-emits strict JSON -----------


def test_a_hostile_arguments_string_round_trips_as_strict_json():
    hostile = '{"x": Infinity, "y": 1e400}'
    args = _ingress(hostile)
    text = _emitted_arguments(args)
    assert _strict_json(text)
    # The model's bytes ride inside a JSON string VALUE: data preserved,
    # wire valid - where the pre-correction chain emitted bare Infinity
    # tokens the project's own validator refuses.
    assert json.loads(text) == {"_raw_arguments": hostile}
