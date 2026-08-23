"""OMI-V2 - controls on the ask-and-check exchange.

This is where requirement 7 is discharged: response validation must REUSE
`scripts/open_model/structured.py` rather than grow a second validator. That
is proved two ways here - structurally, by reading the import; and
behaviourally, by monkeypatching the validator and observing that the
exchange's verdict changes, which a private reimplementation could not do.

Hermetic throughout: injected clients only, no network, no key, no runtime.

Same-author evidence: written by the agent that wrote the code under test.
It demonstrates internal consistency, not independent acceptance.
"""

from __future__ import annotations

import builtins
import json
import socket
from types import SimpleNamespace

import pytest

from scripts.agent_backends.base import Message, ToolSpec
from scripts.agent_backends.openai_compat_backend import (
    OpenAICompatBackend,
    StructuredCompletion,
)
from scripts.agent_backends.structured_request import StructuredOutputRequest
from scripts.open_model import structured_exchange as sx
from scripts.open_model.structured_exchange import (
    StructuredExchange,
    request_structured_json,
)


_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
_REQUEST = StructuredOutputRequest(schema=_SCHEMA)
_MESSAGES = [Message(role="user", content="hello")]
_TOOL = ToolSpec(name="t", description="d", input_schema={"type": "object"})


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def _refuse(*args, **kwargs):
        raise AssertionError("a socket was created during a hermetic test")

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


class RecordingClient:
    def __init__(self, text="{}", finish_reason="stop"):
        self.requests: list[dict] = []
        self._text = text
        self._finish_reason = finish_reason
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self._text, tool_calls=None),
                    finish_reason=self._finish_reason,
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2),
        )


def _backend(text="{}", dialect="vllm") -> OpenAICompatBackend:
    return OpenAICompatBackend(
        model="m", client=RecordingClient(text=text), dialect=dialect
    )


def _exchange(text="{}", dialect="vllm", **kwargs) -> StructuredExchange:
    return request_structured_json(
        _backend(text=text, dialect=dialect), _MESSAGES, [],
        structured=_REQUEST, **kwargs
    )


# == the success path ========================================================


def test_a_conforming_response_validates():
    result = _exchange(text='{"ok": true, "n": 1}')
    assert result.ok is True
    assert dict(result.value) == {"ok": True, "n": 1}
    assert result.response_format_sent is True
    assert result.dialect == "vllm"
    assert result.request_refusal is None
    assert result.response_failure is None


def test_required_keys_are_enforced():
    result = _exchange(text='{"ok": true}', required_keys=("ok",))
    assert result.ok is True


def test_a_missing_required_key_is_reported_as_an_index_not_a_name():
    secret_key = "SECRETKEYNAME"
    result = _exchange(
        text='{"ok": true}', required_keys=("ok", secret_key)
    )
    assert result.ok is False
    assert result.response_failure == "missing-required-key"
    assert result.missing_key_indices == (1,)
    assert secret_key not in repr(result)


@pytest.mark.parametrize("dialect", ["llama-cpp", "ollama", "vllm", "sglang"])
def test_the_exchange_works_across_every_dialect(dialect):
    result = _exchange(text='{"ok": true}', dialect=dialect)
    assert result.ok is True
    assert result.dialect == dialect


# == the response-failure boundary ===========================================


@pytest.mark.parametrize(
    "text,failure",
    [
        ("I am prose, not JSON.", "invalid-json"),
        # Empty content produces no TextBlock at all (the backend's existing
        # `type(text) is str and text` guard), so `AgentResponse.text` is
        # None and the accurate verdict is the not-a-string one.
        ("", "payload-not-exact-str"),
        ("[1, 2, 3]", "not-json-object"),
        ('"a string"', "not-json-object"),
        ("42", "not-json-object"),
        ("null", "not-json-object"),
        ('{"a": 1, "a": 2}', "duplicate-key"),
        ('{"a": NaN}', "non-finite-number"),
        ('{"a": Infinity}', "non-finite-number"),
        ("{unclosed", "invalid-json"),
    ],
)
def test_an_unusable_response_is_reported_without_disclosure(text, failure):
    result = _exchange(text=text)
    assert result.ok is False
    assert result.response_failure == failure
    assert result.value is None
    # A request WAS sent; this is a runtime-behaviour failure, not a refusal.
    assert result.response_format_sent is True
    assert result.request_refusal is None


def test_a_response_with_no_text_block_is_reported_not_crashed():
    """`text` is None when the model returned no text at all."""
    result = _exchange(text=None)
    assert result.ok is False
    assert result.response_failure == "payload-not-exact-str"


def test_an_oversized_response_is_refused_before_parsing():
    result = _exchange(text='{"a": "' + "A" * 500 + '"}', max_chars=10)
    assert result.response_failure == "payload-too-large"


def test_an_unsafe_required_key_refuses_the_whole_validation():
    result = _exchange(text='{"ok": true}', required_keys=("A" * 200,))
    assert result.ok is False
    assert result.response_failure == "required-key-not-safe"


def test_no_response_text_reaches_the_result():
    secret = "SECRETRESPONSEBODY"
    result = _exchange(text="prose containing " + secret)
    assert result.ok is False
    assert secret not in repr(result)


# == a refused request never becomes a response failure ======================


def test_a_request_refusal_propagates_and_is_not_a_response_failure():
    backend = OpenAICompatBackend(model="m", client=RecordingClient())
    result = request_structured_json(
        backend, _MESSAGES, [], structured=_REQUEST
    )
    assert result.ok is False
    assert result.request_refusal == "dialect-not-configured"
    assert result.response_failure is None
    assert result.response_format_sent is False


def test_the_tools_refusal_propagates():
    result = request_structured_json(
        _backend(), _MESSAGES, [_TOOL], structured=_REQUEST
    )
    assert result.request_refusal == "tools-with-structured-unsupported"
    assert result.response_format_sent is False


def test_no_request_is_sent_when_the_exchange_refuses():
    client = RecordingClient()
    backend = OpenAICompatBackend(model="m", client=client, dialect="vllm")
    result = request_structured_json(
        backend, _MESSAGES, [], structured=StructuredOutputRequest(schema={})
    )
    assert result.request_refusal == "schema-empty"
    assert client.requests == []


# == backends outside OMI-V2 refuse cleanly ==================================


def test_a_backend_without_the_method_refuses_rather_than_raising():
    from scripts.agent_backends.mock import MockBackend

    result = request_structured_json(
        MockBackend(responses=[]), _MESSAGES, [], structured=_REQUEST
    )
    assert result.request_refusal == "backend-not-structured-capable"


def test_a_backend_returning_a_foreign_object_is_not_believed():
    class Liar:
        def complete_structured(self, *args, **kwargs):
            return SimpleNamespace(
                ok=True, response=None, refusal=None, dialect="vllm",
                response_format_sent=True,
            )

    result = request_structured_json(
        Liar(), _MESSAGES, [], structured=_REQUEST
    )
    assert result.request_refusal == "backend-not-structured-capable"
    assert result.ok is False


def test_a_non_callable_attribute_refuses():
    result = request_structured_json(
        SimpleNamespace(complete_structured="not callable"),
        _MESSAGES, [], structured=_REQUEST,
    )
    assert result.request_refusal == "backend-not-structured-capable"


# == requirement 7: the existing validator is reused, not reimplemented ======


def test_the_exchange_imports_the_existing_validator():
    from pathlib import Path

    source = Path(sx.__file__).read_text(encoding="utf-8")
    assert "from scripts.open_model.structured import (" in source
    assert "validate_structured_output" in source


def test_the_captured_validator_IS_the_existing_one():
    """Identity proof, stronger than the monkeypatch proof it replaces.

    The validator is now bound as a captured default so a rebound module
    name cannot swap it - which also means a monkeypatch can no longer
    demonstrate the call. Proving the captured object IS
    `scripts.open_model.structured.validate_structured_output` is a stricter
    statement than "something reached through that name ran": it cannot be
    satisfied by a look-alike.
    """
    import inspect

    from scripts.open_model.structured import validate_structured_output

    default = inspect.signature(request_structured_json).parameters[
        "_validate"
    ].default
    assert default is validate_structured_output


def test_the_captured_validator_is_the_one_actually_used():
    """Behavioural companion: the captured parameter drives the verdict."""
    seen: list[tuple] = []

    def _fake(payload, *, required_keys=(), max_chars=0):
        seen.append((payload, required_keys, max_chars))
        return sx.StructuredOutcome(ok=False, failure="duplicate-key")

    result = request_structured_json(
        _backend(text='{"ok": true}'),
        _MESSAGES,
        [],
        structured=_REQUEST,
        required_keys=("ok",),
        max_chars=99,
        _validate=_fake,
    )
    assert result.response_failure == "duplicate-key"
    assert seen == [('{"ok": true}', ("ok",), 99)]


def test_the_exchange_defines_no_validator_of_its_own():
    """No JSON parsing lives here; the module delegates."""
    from pathlib import Path

    source = Path(sx.__file__).read_text(encoding="utf-8")
    body = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    assert "json.loads" not in body
    assert "import json" not in body


# == nothing is persisted ====================================================


def test_the_exchange_writes_no_file(monkeypatch):
    def _refuse(*args, **kwargs):
        raise AssertionError("the exchange opened a file")

    backend = _backend(text='{"ok": true}')
    monkeypatch.setattr(builtins, "open", _refuse)
    result = request_structured_json(
        backend, _MESSAGES, [], structured=_REQUEST
    )
    assert result.ok is True


def test_the_file_guard_would_actually_fire(monkeypatch):
    """Guard: an inert monkeypatch would make the test above vacuous."""
    def _refuse(*args, **kwargs):
        raise AssertionError("the guard fired")

    monkeypatch.setattr(builtins, "open", _refuse)
    with pytest.raises(AssertionError):
        open("nonexistent-omi-v2-probe.txt")


# == the carrier cannot express a contradiction ==============================


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ok": True, "value": {"a": 1}, "request_refusal": "schema-empty"},
        {"ok": True, "response_format_sent": True},
        {"ok": True, "value": {"a": 1}},
        {"ok": False},
        {"ok": False, "request_refusal": "schema-empty", "response_failure": "invalid-json"},
        {"ok": False, "request_refusal": "schema-empty", "response_format_sent": True},
        {"ok": False, "response_failure": "invalid-json", "value": {"a": 1}},
    ],
)
def test_contradictory_exchanges_are_refused_at_construction(kwargs):
    with pytest.raises(ValueError):
        StructuredExchange(**kwargs)


def test_a_valid_success_still_constructs():
    assert StructuredExchange(
        ok=True, value={"a": 1}, dialect="vllm", response_format_sent=True
    ).ok is True



# == gate 2: usability is not schema conformance =============================


_STRICT_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}
"""Demands a boolean `ok` and forbids extra keys. Used to make the gap
concrete: the exchange never compares a response against this."""


def test_a_wrong_typed_extra_keyed_response_still_validates():
    """The exact counterexample from the independent audit.

    `{"ok": "wrong type", "extra": 123}` violates _STRICT_SCHEMA twice: `ok`
    is a string where a boolean is demanded, and `extra` is present where no
    additional properties are allowed. The exchange reports ok=True anyway,
    because it checks JSON-object syntax and required-key presence and
    nothing else. Recorded as a control so the limit cannot be forgotten.
    """
    request = StructuredOutputRequest(schema=_STRICT_SCHEMA)
    result = request_structured_json(
        _backend(text='{"ok": "wrong type", "extra": 123}'),
        _MESSAGES,
        [],
        structured=request,
        required_keys=("ok",),
    )
    assert result.ok is True
    assert dict(result.value) == {"ok": "wrong type", "extra": 123}
    # ...and the result says so in its own state, not merely in prose.
    assert result.schema_conformance == "unverified"


def test_schema_conformance_is_unverified_on_every_reachable_path():
    """ok, refused, and unusable all report the same closed token."""
    ok = _exchange(text='{"ok": true}')
    unusable = _exchange(text="not json at all")
    refused = request_structured_json(
        object(), _MESSAGES, [], structured=_REQUEST
    )
    assert ok.ok is True
    assert unusable.ok is False and unusable.response_failure is not None
    assert refused.ok is False and refused.request_refusal is not None
    for result in (ok, unusable, refused):
        assert result.schema_conformance == "unverified"


@pytest.mark.parametrize(
    "value", ["verified", "conformant", "", "unverified ", None, True, 1]
)
def test_no_other_conformance_value_can_be_constructed(value):
    """The vocabulary is closed at runtime, not merely in the type hint.

    A future real conformance check has to widen this deliberately; it cannot
    arrive by someone setting a field.
    """
    with pytest.raises(ValueError):
        StructuredExchange(
            ok=True,
            value={"ok": True},
            response_format_sent=True,
            schema_conformance=value,
        )


@pytest.mark.parametrize(
    "module_name",
    ["scripts.open_model.structured", "scripts.open_model.structured_exchange"],
)
def test_the_package_ships_no_json_schema_validator(module_name):
    """Structural control: no conformance checker was added or hand-rolled.

    Gate 2 permitted either a closed validated subset or an explicit
    unverified report. The second was taken, so there must be no third-party
    schema dependency behind the `unverified` token. Checked over the import
    AST rather than the raw text, because the source *discusses* jsonschema
    in prose and a substring search would match that and pass vacuously.
    """
    import ast
    import importlib
    import inspect

    tree = ast.parse(inspect.getsource(importlib.import_module(module_name)))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert "jsonschema" not in imported
    assert imported <= {
        "__future__", "dataclasses", "json", "types", "typing", "scripts",
    }, imported


def test_mutating_the_schema_after_the_call_cannot_change_what_was_sent():
    """Gate 5, end to end at the layer that actually transmits.

    The plan-level control proves the snapshot is taken; this proves nothing
    downstream re-reads the caller's object on the way out.
    """
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    client = RecordingClient(text='{"ok": true}')
    backend = OpenAICompatBackend(model="m", client=client, dialect="vllm")
    result = request_structured_json(
        backend, _MESSAGES, [], structured=StructuredOutputRequest(schema=schema)
    )
    assert result.ok is True

    sent = client.requests[0]["response_format"]
    before = json.loads(json.dumps(sent))
    schema["properties"]["ok"]["type"] = "PWNED"
    schema["injected"] = True

    assert sent == before
    assert "injected" not in sent["json_schema"]["schema"]
