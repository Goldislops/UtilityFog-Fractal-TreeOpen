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

from scripts.agent_backends.base import AgentResponse, Message, TextBlock, ToolSpec
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


def _captured(func, name):
    """Read a closure cell by free-variable name.

    This is how identity is proved now that the authorities are no longer
    addressable parameters: the object is read out of the cell rather than
    supplied into a keyword. Inspection, not injection.
    """
    index = func.__code__.co_freevars.index(name)
    return func.__closure__[index].cell_contents


def test_the_captured_validator_IS_the_existing_one():
    """Identity proof, read from the closure cell.

    The validator is bound in a cell precisely so a caller cannot substitute
    it, which also means it can no longer be proved by passing one in - an
    earlier version of this test did exactly that, and the parameter it relied
    on was itself the defect. Reading the cell proves the captured object IS
    `scripts.open_model.structured.validate_structured_output`, which a
    look-alike cannot satisfy.
    """
    from scripts.open_model.structured import validate_structured_output

    assert _captured(request_structured_json, "_validate") is (
        validate_structured_output
    )


def test_the_real_validator_actually_runs():
    """Behavioural proof that needs no injection point.

    `duplicate-key` is a verdict only `structured.py` produces: it comes from
    that module's `object_pairs_hook`, and a plain `json.loads` would accept
    `{"a": 1, "a": 2}` and keep the last value silently. Observing that
    verdict end-to-end therefore proves the reused validator ran, without
    reopening the public signature.
    """
    result = _exchange(text='{"a": 1, "a": 2}')
    assert result.response_failure == "duplicate-key"


def test_the_duplicate_key_verdict_is_not_what_plain_json_would_do():
    """Guard: if json.loads also rejected this, the proof above is vacuous."""
    import json

    assert json.loads('{"a": 1, "a": 2}') == {"a": 2}


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


# ============================================================================
# Fifth round - a returned completion is revalidated before it is consumed
# ============================================================================
#
# `StructuredCompletion` is frozen, and freezing is not sealing:
# `object.__setattr__` replaces any field after construction, and a backend is
# caller-supplied code. An earlier revision checked only that the returned
# object was exactly a `StructuredCompletion`, then truth-tested `.ok` and read
# `.response.text` - so a backend that built a valid completion and then altered
# one field could run its own `__bool__` or its own property from inside this
# module, and could make `StructuredExchange` construction raise `ValueError`.
# Both escaped as raw incidental exceptions from a function that promises a
# result for every reachable input.
#
# Same-author evidence: written by the agent that wrote the code under test.


def _good_completion():
    return StructuredCompletion(
        ok=True,
        response=AgentResponse.from_content([TextBlock(text='{"ok": true}')]),
        dialect="ollama",
        response_format_sent=True,
    )


class TamperingBackend:
    """Builds a VALID exact completion, then alters one field before returning.

    Post-construction is the only way to produce these: the carrier refuses
    every one of them at the door. A control that built them directly would be
    testing the carrier, not this module.
    """

    def __init__(self, field, value):
        self.field = field
        self.value = value
        self.calls = 0

    def complete_structured(self, messages, tools, **kwargs):
        self.calls += 1
        completion = _good_completion()
        object.__setattr__(completion, self.field, self.value)
        return completion


class _BoolHook:
    fired: list = []

    def __bool__(self):  # pragma: no cover - must never be reached
        _BoolHook.fired.append("ok.__bool__")
        raise RuntimeError("the __bool__ hook ran")


class _TextHook:
    fired: list = []

    @property
    def text(self):  # pragma: no cover - must never be reached
        _TextHook.fired.append("response.text")
        raise RuntimeError("the text property ran")


def _round5_exchange(backend):
    return request_structured_json(
        backend, _MESSAGES, [], structured=_REQUEST, required_keys=("ok",)
    )


def test_a_tampered_ok_never_runs_its_bool_hook():
    _BoolHook.fired = []
    backend = TamperingBackend("ok", _BoolHook())
    result = _round5_exchange(backend)
    assert _BoolHook.fired == []
    assert backend.calls == 1
    assert result.ok is False
    assert result.request_refusal == "backend-not-structured-capable"
    assert result.dialect is None
    assert result.response_format_sent is False


def test_a_tampered_response_never_runs_its_text_property():
    _TextHook.fired = []
    backend = TamperingBackend("response", _TextHook())
    result = _round5_exchange(backend)
    assert _TextHook.fired == []
    assert result.ok is False
    assert result.request_refusal == "backend-not-structured-capable"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        # Hook-free but incoherent: every one of these is a state the carrier
        # itself refuses to construct, so none can come from OMI-V2.
        ("ok", 1),
        ("ok", 0),
        ("ok", "yes"),
        ("ok", False),
        ("response_format_sent", False),
        ("response_format_sent", 1),
        ("dialect", None),
        ("dialect", "not-a-runtime"),
        ("dialect", "sk-OMIV2SECRET1234567890"),
        ("dialect", 5),
        ("refusal", "schema-empty"),
        ("refusal", "not-a-token"),
        ("response", None),
        ("response", "not an AgentResponse"),
        ("response", 5),
    ],
    ids=[
        "ok-int-1", "ok-int-0", "ok-str", "ok-false-no-refusal",
        "sent-false-on-success", "sent-int",
        "dialect-none-on-success", "dialect-unsupported", "dialect-secret",
        "dialect-int",
        "refusal-on-success", "refusal-not-a-token",
        "response-none-on-success", "response-wrong-type", "response-int",
    ],
)
def test_every_incoherent_completion_lands_on_one_closed_refusal(field, value):
    backend = TamperingBackend(field, value)
    result = _round5_exchange(backend)
    assert result.ok is False
    assert result.request_refusal == "backend-not-structured-capable"
    assert result.request_refusal in sx.EXCHANGE_REFUSALS
    assert result.value is None
    assert result.dialect is None
    assert result.response_format_sent is False
    # Nothing of the tampered value survives into the result.
    assert "sk-" not in repr(result)
    assert "not-a-runtime" not in repr(result)


def test_the_state_checker_accepts_exactly_what_the_carrier_can_construct():
    """A differential, so the re-check cannot drift from the carrier it mirrors.

    Every combination is put to the carrier by construction and to
    `_completion_state_ok` by inspection, and the two verdicts must agree. That
    is stronger than asserting the checker holds the right vocabularies: it
    shows the same boundary, not merely the same values.
    """
    import itertools

    response = AgentResponse.from_content([TextBlock(text='{"ok": true}')])
    space = itertools.product(
        [True, False],
        [None, response],
        [None, "backend-not-structured-capable", "dialect-not-configured",
         "schema-empty", "tools-with-structured-unsupported"],
        [None, "ollama"],
        [True, False],
    )
    constructible = 0
    rejects_valid = []
    accepts_invalid = []
    for ok, resp, refusal, dialect, sent in space:
        try:
            built = StructuredCompletion(
                ok=ok, response=resp, refusal=refusal, dialect=dialect,
                response_format_sent=sent,
            )
            carrier_accepts = True
        except ValueError:
            built = None
            carrier_accepts = False
        if carrier_accepts:
            constructible += 1
            if not sx._completion_state_ok(built):
                rejects_valid.append((ok, resp is not None, refusal, dialect, sent))
            continue
        victim = _good_completion()
        object.__setattr__(victim, "ok", ok)
        object.__setattr__(victim, "response", resp)
        object.__setattr__(victim, "refusal", refusal)
        object.__setattr__(victim, "dialect", dialect)
        object.__setattr__(victim, "response_format_sent", sent)
        if sx._completion_state_ok(victim):
            accepts_invalid.append((ok, resp is not None, refusal, dialect, sent))

    assert constructible > 0
    assert rejects_valid == []
    assert accepts_invalid == []


def test_the_state_checker_holds_the_backend_packages_own_authorities():
    cells = dict(
        zip(
            sx._completion_state_ok.__code__.co_freevars,
            (cell.cell_contents for cell in sx._completion_state_ok.__closure__ or ()),
        )
    )
    from scripts.agent_backends import structured_request as sr

    assert cells["_completion_type"] is StructuredCompletion
    assert cells["_agent_response"] is AgentResponse
    assert cells["_tokens"] is sr.REFUSAL_TOKENS
    assert cells["_dialect_ok"] is sr.is_supported_dialect
    assert cells["_pre_dialect"] is sr.is_pre_dialect_refusal


def test_an_untampered_backend_still_succeeds_and_still_refuses_normally():
    """Positive guard: the re-check rejects nothing OMI-V2 legitimately makes."""

    class Honest:
        def __init__(self, completion):
            self.completion = completion

        def complete_structured(self, messages, tools, **kwargs):
            return self.completion

    ok = _round5_exchange(Honest(_good_completion()))
    assert ok.ok is True
    assert dict(ok.value) == {"ok": True}
    assert ok.dialect == "ollama"

    refused = _round5_exchange(
        Honest(
            StructuredCompletion(
                ok=False, refusal="schema-empty", dialect="ollama",
                response_format_sent=False,
            )
        )
    )
    assert refused.ok is False
    assert refused.request_refusal == "schema-empty"
    assert refused.dialect == "ollama"

    pre_dialect = _round5_exchange(
        Honest(
            StructuredCompletion(
                ok=False, refusal="dialect-not-configured", response_format_sent=False
            )
        )
    )
    assert pre_dialect.request_refusal == "dialect-not-configured"
    assert pre_dialect.dialect is None


def test_a_raising_backend_still_raises():
    """The re-check catches nothing. Transport failures are still transport failures."""

    class Exploding:
        def complete_structured(self, messages, tools, **kwargs):
            raise RuntimeError("transport said no")

    with pytest.raises(RuntimeError):
        _round5_exchange(Exploding())


def test_a_backend_that_reaches_the_network_is_not_converted_into_a_refusal():
    """`HermeticViolation` must stay loud; no broad catch was added."""
    from scripts.open_model.evaluation import HermeticViolation, hermetic_guard

    class Breaching:
        def complete_structured(self, messages, tools, **kwargs):
            socket.socket()
            raise AssertionError("unreachable while the guard is active")

    with hermetic_guard():
        with pytest.raises(HermeticViolation):
            _round5_exchange(Breaching())


# ============================================================================
# round eight: fields DELETED from an exact completion, not merely replaced
# ============================================================================
#
# Round five proved this module against `object.__setattr__`. It was never
# proved against `object.__delattr__`, and a frozen dataclass refuses both
# equally, so both need the same bypass.
#
# `StructuredCompletion` declares four of its five fields with a class-level
# default, so a deleted instance attribute quietly reads as that default. Where
# the default equals the value the carrier was built with, the deletion is
# invisible. The fifth, `ok`, has no default at all, so reading it raised.


def _completion_field_names():
    import dataclasses

    return [f.name for f in dataclasses.fields(StructuredCompletion)]


def _deleted(carrier, name):
    """A copy of ``carrier`` with one instance field removed."""
    import copy

    clone = copy.copy(carrier)
    object.__delattr__(clone, name)
    return clone


def _success_completion():
    return StructuredCompletion(
        ok=True,
        response=AgentResponse.from_content([TextBlock(text='{"ok": true}')]),
        dialect="ollama",
        response_format_sent=True,
    )


def _post_dialect_refusal_completion():
    return StructuredCompletion(
        ok=False, response=None, refusal="schema-empty",
        dialect="ollama", response_format_sent=False,
    )


def _pre_dialect_refusal_completion():
    return StructuredCompletion(
        ok=False, response=None, refusal="dialect-unsupported",
        dialect=None, response_format_sent=False,
    )


#: The three coherent shapes the carrier can be in, by name.
_COHERENT_SHAPES = {
    "success": _success_completion,
    "post-dialect-refusal": _post_dialect_refusal_completion,
    "pre-dialect-refusal": _pre_dialect_refusal_completion,
}


class DeletingBackend:
    """Returns an exact, coherent completion with one instance field removed.

    Post-construction deletion is the only way to produce these: the carrier
    itself would refuse to be built this way, and a control that constructed one
    directly would be testing the carrier rather than this module.
    """

    def __init__(self, build, field):
        self.build = build
        self.field = field
        self.calls = 0

    def complete_structured(self, messages, tools, **kwargs):
        self.calls += 1
        completion = self.build()
        object.__delattr__(completion, self.field)
        return completion


def test_the_carrier_still_declares_exactly_the_five_fields_named_here():
    """Pins the premise. If the carrier grows a field, this fails loudly rather
    than letting the deletion controls below silently stop covering it."""
    assert _completion_field_names() == [
        "ok",
        "response",
        "refusal",
        "dialect",
        "response_format_sent",
    ]


def test_four_of_the_five_fields_really_do_carry_class_defaults():
    """The premise of the silent half: ``getattr`` has somewhere to fall to."""
    assert not hasattr(StructuredCompletion, "ok")
    assert StructuredCompletion.response is None
    assert StructuredCompletion.refusal is None
    assert StructuredCompletion.dialect is None
    assert StructuredCompletion.response_format_sent is False


@pytest.mark.parametrize("shape", sorted(_COHERENT_SHAPES))
@pytest.mark.parametrize("field", _completion_field_names())
def test_a_deleted_completion_field_is_refused(shape, field):
    """Every field, every coherent shape: the existing closed refusal.

    No raw incidental exception, and no silent success. Before round eight,
    deleting ``ok`` raised ``AttributeError`` out of ``_completion_state_ok``
    for all three shapes, and six of the remaining twelve combinations were
    accepted outright because the class default equalled the value that had
    been deleted.
    """
    backend = DeletingBackend(_COHERENT_SHAPES[shape], field)
    result = _round5_exchange(backend)

    assert backend.calls == 1
    assert result.ok is False
    assert result.request_refusal == "backend-not-structured-capable"
    assert result.response_failure is None
    assert result.value is None
    assert result.response_format_sent is False


def test_a_deleted_refusal_no_longer_passes_as_a_coherent_success():
    """Jack's addition to the auditor's finding, pinned on its own.

    ``refusal`` is ``None`` on a successful carrier *and* ``None`` as a class
    default, so removing it changed nothing that attribute access could see. The
    completion read as a coherent success and was consumed as one.
    """
    completion = _success_completion()
    stripped = _deleted(completion, "refusal")

    # Attribute access cannot tell these apart - that is the defect.
    assert completion.refusal is None
    assert stripped.refusal is None
    assert getattr(stripped, "refusal", "SENTINEL") is None

    # The module can.
    assert sx._completion_state_ok(completion) is True
    assert sx._completion_state_ok(stripped) is False

    result = _round5_exchange(DeletingBackend(_success_completion, "refusal"))
    assert result.ok is False
    assert result.request_refusal == "backend-not-structured-capable"


@pytest.mark.parametrize(
    "shape, field",
    [
        ("success", "refusal"),
        ("post-dialect-refusal", "response"),
        ("post-dialect-refusal", "response_format_sent"),
        ("pre-dialect-refusal", "response"),
        ("pre-dialect-refusal", "dialect"),
        ("pre-dialect-refusal", "response_format_sent"),
    ],
)
def test_a_deleted_field_whose_default_equals_its_value_is_still_refused(shape, field):
    """The six combinations attribute access is blind to.

    In each of these the class default is exactly the value the coherent carrier
    held, so the deletion leaves every ordinary read unchanged. Presence is the
    only thing that distinguishes them, which is why the gate reads the instance
    dictionary rather than the attribute.
    """
    coherent = _COHERENT_SHAPES[shape]()
    stripped = _deleted(coherent, field)
    assert getattr(stripped, field) == getattr(coherent, field)
    assert sx._completion_state_ok(coherent) is True
    assert sx._completion_state_ok(stripped) is False

    result = _round5_exchange(DeletingBackend(_COHERENT_SHAPES[shape], field))
    assert result.ok is False
    assert result.request_refusal == "backend-not-structured-capable"


def test_a_class_level_default_does_not_count_as_instance_presence():
    """The explicit statement of what the gate measures.

    ``hasattr`` is ``True`` for every deleted defaulted field, and ``getattr``
    with a sentinel never reaches the sentinel, because the class supplies the
    answer first. Neither is usable here.
    """
    for field in ("response", "refusal", "dialect", "response_format_sent"):
        stripped = _deleted(_success_completion(), field)
        assert hasattr(stripped, field) is True
        assert getattr(stripped, field, "SENTINEL") != "SENTINEL"
        assert field not in vars(stripped)
        assert sx._completion_state_ok(stripped) is False

    # `ok` has no default, so it is the one field ordinary access could detect -
    # by raising, which is not a verdict.
    stripped = _deleted(_success_completion(), "ok")
    assert hasattr(stripped, "ok") is False
    assert "ok" not in vars(stripped)
    assert sx._completion_state_ok(stripped) is False


def test_the_presence_gate_would_fail_these_controls_if_reverted():
    """Non-vacuity for the gate itself, not merely for the assertions.

    This reproduces what ordinary attribute access reports for each deletion,
    and requires it to disagree with the module's verdict. If the gate were
    reverted to plain attribute reads, this control's expectations become the
    module's behaviour and the controls above stop distinguishing anything.
    """
    reverted_would_raise = []
    reverted_would_accept = []
    for shape, build in _COHERENT_SHAPES.items():
        for field in _completion_field_names():
            stripped = _deleted(build(), field)
            try:
                # What a reverted implementation reads first.
                _ = stripped.ok
            except AttributeError:
                reverted_would_raise.append((shape, field))
                continue
            if getattr(stripped, field) == getattr(build(), field):
                reverted_would_accept.append((shape, field))

    # Three raw exceptions and six invisible deletions - the round-eight finding.
    assert len(reverted_would_raise) == 3
    assert len(reverted_would_accept) == 6

    # And every one of the nine is refused by the module as it now stands.
    for shape, field in reverted_would_raise + reverted_would_accept:
        stripped = _deleted(_COHERENT_SHAPES[shape](), field)
        assert sx._completion_state_ok(stripped) is False, (shape, field)


class _ConstantBackend:
    """Returns one prepared completion, untouched."""

    def __init__(self, completion):
        self.completion = completion
        self.calls = 0

    def complete_structured(self, messages, tools, **kwargs):
        self.calls += 1
        return self.completion


def test_deletion_does_not_disturb_the_coherent_states():
    """The gate must refuse absence without refusing anything legitimate."""
    for build in _COHERENT_SHAPES.values():
        assert sx._completion_state_ok(build()) is True

    ok = _round5_exchange(_ConstantBackend(_success_completion()))
    assert ok.ok is True
    assert ok.dialect == "ollama"
    assert dict(ok.value) == {"ok": True}

    refused = _round5_exchange(_ConstantBackend(_post_dialect_refusal_completion()))
    assert refused.ok is False
    assert refused.request_refusal == "schema-empty"

    pre = _round5_exchange(_ConstantBackend(_pre_dialect_refusal_completion()))
    assert pre.ok is False
    assert pre.request_refusal == "dialect-unsupported"
    assert pre.dialect is None


def test_the_exact_type_gate_still_comes_before_the_presence_gate():
    """Ordering, pinned. Nothing that is not exactly the carrier is inspected.

    The presence gate reads ``__dict__`` through ``object.__getattribute__``,
    and is only ever reached for an exact ``StructuredCompletion`` - whose
    ``__dict__`` is the real one - because the exact-type test refuses
    everything else first. A subclass that answers that lookup by raising is
    therefore never asked, which is why the one ``except AttributeError`` in the
    gate cannot become a place for something else to hide.
    """
    from scripts.open_model.evaluation import HermeticViolation

    fired = []

    class Hostile(StructuredCompletion):
        @property
        def __dict__(self):  # pragma: no cover - must never be reached
            fired.append("__dict__")
            raise HermeticViolation("reached for a socket")

    assert sx._completion_state_ok(Hostile.__new__(Hostile)) is False
    assert fired == []

    class HookedType:
        def __getattr__(self, name):  # pragma: no cover - must never be reached
            fired.append(name)
            return "anything you like"

    assert sx._completion_state_ok(HookedType()) is False
    assert fired == []


def test_the_controls_in_this_file_are_not_silently_stripped():
    """Prove a false assertion here would still fail under ``-O`` and ``-OO``.

    Both flags discard ``assert`` statements, so a suite that passed under them
    could in principle be asserting nothing. pytest rewrites assertions in
    collected test modules into explicit raises first; this is the control that
    proves the rewriting happened rather than trusting that it did.
    """
    with pytest.raises(AssertionError):
        assert False, "if this does not raise, every control here is vacuous"
