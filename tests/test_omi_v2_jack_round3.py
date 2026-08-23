"""OMI-V2 - controls for Jack's third independent HOLD round.

Round 2 closed the carriers' own ``__post_init__`` against name rebinding and
asserted that with a ``co_names`` check. That check was true and insufficient:
it proved only the IMMEDIATE layer. The helper functions those carriers
captured - ``is_supported_dialect``, ``is_supported_wire_shape``,
``is_pre_dialect_refusal`` - still resolved ``type``, ``str``, ``dict`` and
``len`` as module globals, so an ordinary assignment such as
``structured_request.type = <replacement>`` changed their decisions without
replacing the function, its defaults, its code, or ``sys.modules``.

That admitted a deceptive ``str`` SUBCLASS - which can carry hidden
attributes and lie in ``__repr__`` - into fields that must hold exact tokens,
and it admitted an exact secret-shaped string as backend dialect
configuration through the backend's own imported alias.

These controls therefore assert the HELPER decision paths themselves, not
only the carriers, and they rebind the builtins as well as every mirror
tested in earlier rounds. Everything runs identically under normal, ``-O``
and ``-OO``.

Same-author evidence: written by the agent that wrote the code under test.
It demonstrates internal consistency, not independent acceptance.
"""

from __future__ import annotations

import inspect
from types import MappingProxyType, SimpleNamespace

import pytest

from scripts.agent_backends import openai_compat_backend as bk
from scripts.agent_backends import structured_request as sr
from scripts.agent_backends.base import AgentResponse, Message
from scripts.agent_backends.openai_compat_backend import (
    OpenAICompatBackend,
    StructuredCompletion,
)
from scripts.agent_backends.structured_request import (
    StructuredOutputRequest,
    StructuredRequestPlan,
    build_response_format,
    is_pre_dialect_refusal,
    is_supported_dialect,
    is_supported_wire_shape,
    plan_structured_request,
)
from scripts.open_model import structured_exchange as sx
from scripts.open_model.structured_exchange import (
    StructuredExchange,
    request_structured_json,
)


_SECRET = "sk-OMIV2SECRET123456789"
_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
_MESSAGES = [Message(role="user", content="hello")]
_RESPONSE = AgentResponse.from_content([])
_REAL_TYPE = type


def _request(schema=None) -> StructuredOutputRequest:
    return StructuredOutputRequest(schema=_SCHEMA if schema is None else schema)


class Deceptive(str):
    """An exact-looking dialect token that is not an exact ``str``.

    Carries hidden text and lies in ``__repr__``, so a result that admitted
    one would look correct in a log while carrying something else.
    """

    def __new__(cls, shown: str, hidden: str):
        obj = super().__new__(cls, shown)
        obj.hidden = hidden  # type: ignore[attr-defined]
        return obj

    def __repr__(self) -> str:
        return "'" + str.__str__(self) + "'"


class RecordingClient:
    def __init__(self, text: str = '{"ok": true}'):
        self.requests: list[dict] = []
        self._text = text
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self._text, tool_calls=None),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2),
        )


def _backend(dialect="vllm", client=None) -> OpenAICompatBackend:
    return OpenAICompatBackend(
        model="m",
        client=client if client is not None else RecordingClient(),
        dialect=dialect,
    )


# == the hostile environment: every mirror AND the builtins ==================


def _fake_type(obj):
    """Report every str subclass as `str` and every dict subclass as `dict`."""
    if isinstance(obj, str):
        return str
    if isinstance(obj, dict):
        return dict
    return _REAL_TYPE(obj)


_MIRRORS = [
    # builtins, ADDED to the module namespace (they are not there normally)
    (sr, "type", _fake_type),
    (sr, "str", str),
    (sr, "dict", dict),
    (sr, "len", len),
    # data and predicate mirrors, from earlier rounds
    (sr, "REFUSAL_TOKENS", frozenset({_SECRET})),
    (sr, "SUPPORTED_DIALECTS", (_SECRET,)),
    (sr, "STRUCTURED_WIRE_NAME", _SECRET),
    (sr, "DIALECT_WIRE_SHAPES", {_SECRET: _SECRET}),
    (sr, "is_supported_dialect", lambda v: True),
    (sr, "is_pre_dialect_refusal", lambda v: True),
    (sr, "is_supported_wire_shape", lambda v: True),
    (sr, "build_response_format", lambda d, r: {"pwned": _SECRET}),
    (sr, "_validated_snapshot", lambda s: (None, {"pwned": _SECRET})),
    (bk, "type", _fake_type),
    (bk, "REFUSAL_TOKENS", frozenset({_SECRET})),
    (bk, "is_supported_dialect", lambda v: True),
    (bk, "is_pre_dialect_refusal", lambda v: True),
    (bk, "plan_structured_request", lambda *a, **k: None),
    (bk, "AgentResponse", str),
    (sx, "type", _fake_type),
    (sx, "EXCHANGE_REFUSALS", frozenset({_SECRET})),
    (sx, "RESPONSE_FAILURES", frozenset({_SECRET})),
    (sx, "is_supported_dialect", lambda v: True),
    (sx, "is_pre_dialect_refusal", lambda v: True),
    (sx, "MappingProxyType", dict),
    (sx, "validate_structured_output", lambda *a, **k: None),
    (sx, "StructuredCompletion", str),
]


@pytest.fixture
def hostile_environment(monkeypatch):
    """Rebind or ADD every mirror and builtin across all three modules."""
    for module, name, replacement in _MIRRORS:
        monkeypatch.setattr(module, name, replacement, raising=False)
    return None


def test_the_hostile_environment_is_actually_installed(hostile_environment):
    """Guard: if the patches were inert every control below is vacuous."""
    assert sr.type("anything") is str
    assert sr.is_supported_dialect(_SECRET) is True
    assert bk.is_supported_dialect(_SECRET) is True
    assert sx.is_supported_dialect(_SECRET) is True
    assert sr.STRUCTURED_WIRE_NAME == _SECRET
    assert _fake_type(Deceptive("vllm", _SECRET)) is str


# == GATE 1 - the backend dialect authority ==================================


def test_an_exact_secret_string_is_refused_as_backend_dialect(hostile_environment):
    with pytest.raises(ValueError):
        OpenAICompatBackend(model="m", client=RecordingClient(), dialect=_SECRET)


def test_a_deceptive_subclass_is_refused_as_backend_dialect(hostile_environment):
    with pytest.raises(ValueError):
        OpenAICompatBackend(
            model="m", client=RecordingClient(), dialect=Deceptive("vllm", _SECRET)
        )


def test_the_backend_still_accepts_the_four_real_dialects(hostile_environment):
    """Guard: a constructor that refused everything would pass the two above."""
    for dialect in ("llama-cpp", "ollama", "vllm", "sglang"):
        backend = OpenAICompatBackend(
            model="m", client=RecordingClient(), dialect=dialect
        )
        assert backend.dialect == dialect
        assert _REAL_TYPE(backend.dialect) is str


def test_the_refusal_path_in_complete_structured_names_no_secret(
    hostile_environment,
):
    backend = OpenAICompatBackend(model="m", client=RecordingClient())
    result = backend.complete_structured(_MESSAGES, [], structured=_request())
    assert result.refusal == "dialect-not-configured"
    assert result.dialect is None
    assert _SECRET not in repr(result)


def test_a_real_request_still_succeeds_in_the_hostile_environment(
    hostile_environment,
):
    client = RecordingClient()
    result = _backend(client=client).complete_structured(
        _MESSAGES, [], structured=_request()
    )
    assert result.ok is True
    assert result.dialect == "vllm"
    sent = client.requests[0]["response_format"]
    assert sent["json_schema"]["name"] == "structured_output"
    assert _REAL_TYPE(sent["json_schema"]["name"]) is str
    assert _SECRET not in repr(sent)


# == GATE 2 - nothing deceptive enters any carrier or wire shape =============


@pytest.mark.parametrize(
    "dialect",
    [
        pytest.param(_SECRET, id="exact-secret-string"),
        pytest.param(Deceptive("vllm", _SECRET), id="deceptive-subclass"),
        pytest.param(Deceptive(_SECRET, _SECRET), id="deceptive-secret"),
    ],
)
def test_no_carrier_admits_a_foreign_dialect(hostile_environment, dialect):
    with pytest.raises(ValueError):
        StructuredCompletion(
            ok=True, response=_RESPONSE, dialect=dialect, response_format_sent=True
        )
    with pytest.raises(ValueError):
        StructuredExchange(
            ok=True, value={"a": 1}, dialect=dialect, response_format_sent=True
        )


def test_the_plan_refuses_a_deceptive_wire_name(hostile_environment):
    deceptive = Deceptive("structured_output", _SECRET)
    with pytest.raises(ValueError):
        StructuredRequestPlan(
            ok=True,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": deceptive, "schema": {}},
            },
        )


def test_the_plan_refuses_a_deceptive_schema_container(hostile_environment):
    class SneakyDict(dict):
        pass

    with pytest.raises(ValueError):
        StructuredRequestPlan(
            ok=True,
            response_format={
                "type": "json_schema",
                "json_schema": {"schema": SneakyDict(a=1)},
            },
        )


def test_no_carrier_admits_a_secret_refusal_or_failure(hostile_environment):
    with pytest.raises(ValueError):
        StructuredRequestPlan(ok=False, refusal=_SECRET)
    with pytest.raises(ValueError):
        StructuredCompletion(ok=False, refusal=_SECRET, dialect="vllm")
    with pytest.raises(ValueError):
        StructuredExchange(ok=False, request_refusal=_SECRET, dialect="vllm")
    with pytest.raises(ValueError):
        StructuredExchange(
            ok=False,
            response_failure=_SECRET,
            dialect="vllm",
            response_format_sent=True,
        )


def test_a_deceptive_dialect_cannot_reach_the_planner(hostile_environment):
    plan = plan_structured_request(Deceptive("vllm", _SECRET), _request())
    assert plan.ok is False
    assert plan.refusal == "dialect-not-exact-str"
    plan2 = plan_structured_request(_SECRET, _request())
    assert plan2.refusal == "dialect-unsupported"


def test_the_planner_still_builds_the_real_shape(hostile_environment):
    """Guard: the planner must not simply refuse everything."""
    plan = plan_structured_request("vllm", _request())
    assert plan.ok is True
    assert plan.response_format == {
        "type": "json_schema",
        "json_schema": {"name": "structured_output", "schema": _SCHEMA},
    }


def test_the_exchange_result_carries_nothing_deceptive(hostile_environment):
    result = request_structured_json(
        _backend(client=RecordingClient()), _MESSAGES, [], structured=_request()
    )
    assert result.ok is True
    assert result.dialect == "vllm"
    assert _REAL_TYPE(result.dialect) is str
    assert _SECRET not in repr(result)


# == GATE 2 - the helper decision paths themselves ===========================


_CLOSED_CALLABLES = [
    ("is_supported_dialect", is_supported_dialect),
    ("is_supported_wire_shape", is_supported_wire_shape),
    ("is_pre_dialect_refusal", is_pre_dialect_refusal),
    ("build_response_format", build_response_format),
    ("plan_structured_request", plan_structured_request),
    ("_validated_snapshot", sr._validated_snapshot),
    ("OpenAICompatBackend.__init__", OpenAICompatBackend.__init__),
    ("complete_structured", OpenAICompatBackend.complete_structured),
    ("request_structured_json", request_structured_json),
    ("StructuredRequestPlan.__post_init__", StructuredRequestPlan.__post_init__),
    ("StructuredCompletion.__post_init__", StructuredCompletion.__post_init__),
    ("StructuredExchange.__post_init__", StructuredExchange.__post_init__),
]

_FORBIDDEN_NAMES = {
    "type",
    "str",
    "dict",
    "len",
    "bool",
    "int",
    "tuple",
    "frozenset",
    "enumerate",
    "object",
    "REFUSAL_TOKENS",
    "EXCHANGE_REFUSALS",
    "RESPONSE_FAILURES",
    "SUPPORTED_DIALECTS",
    "STRUCTURED_WIRE_NAME",
    "DIALECT_WIRE_SHAPES",
    "is_supported_dialect",
    "is_pre_dialect_refusal",
    "is_supported_wire_shape",
    "build_response_format",
    "plan_structured_request",
    "_validated_snapshot",
    "validate_structured_output",
    "AgentResponse",
    "MappingProxyType",
    "StructuredCompletion",
    "StructuredRequestPlan",
    "StructuredExchange",
    "StructuredOutputRequest",
}


@pytest.mark.parametrize("label,func", _CLOSED_CALLABLES)
def test_no_decision_path_resolves_a_rebindable_trust_name(label, func):
    """Transitive closure, asserted at every layer - not just the carriers.

    Round 2 asserted only the three `__post_init__` bodies. That was true and
    proved nothing about the helpers they called, which is where the hole
    was.
    """
    referenced = set(func.__code__.co_names)
    leaked = referenced & _FORBIDDEN_NAMES
    assert not leaked, label + " resolves " + repr(sorted(leaked))


@pytest.mark.parametrize("label,func", _CLOSED_CALLABLES)
def test_every_closed_decision_path_actually_captures_something(label, func):
    """Guard: a function that captured nothing could pass the test above by
    doing nothing at all."""
    captured = set(func.__code__.co_freevars)
    defaults = func.__defaults__ or ()
    kwdefaults = func.__kwdefaults__ or {}
    assert captured or defaults or kwdefaults, label


def test_the_forbidden_name_check_would_actually_fire():
    """Guard: prove the assertion catches a function that does look up a name."""

    def leaky(value):
        return type(value) is str

    assert set(leaky.__code__.co_names) & _FORBIDDEN_NAMES == {"type", "str"}


# == GATE 3 - no foreign mapping hooks on the public carrier path ============


class HostileMapping:
    """A mapping whose every access raises caller-supplied text."""

    def __init__(self) -> None:
        self.touched = False

    def keys(self):
        self.touched = True
        raise RuntimeError("leaked " + _SECRET)

    def __getitem__(self, key):
        self.touched = True
        raise RuntimeError("leaked " + _SECRET)

    def __iter__(self):
        self.touched = True
        raise RuntimeError("leaked " + _SECRET)

    def __len__(self) -> int:
        return 1


def test_a_proxy_over_a_hostile_mapping_is_refused_without_running_hooks():
    hostile = HostileMapping()
    with pytest.raises(ValueError):
        StructuredExchange(
            ok=True,
            value=MappingProxyType(hostile),
            dialect="vllm",
            response_format_sent=True,
        )
    assert hostile.touched is False, "a foreign mapping hook was executed"


def test_the_hostile_mapping_would_actually_fire():
    """Guard: an inert stand-in makes the control above vacuous."""
    hostile = HostileMapping()
    with pytest.raises(RuntimeError):
        dict(MappingProxyType(hostile))
    assert hostile.touched is True


@pytest.mark.parametrize(
    "value",
    [
        MappingProxyType({"a": 1}),
        SimpleNamespace(),
        "text",
        [("a", 1)],
        42,
    ],
)
def test_only_an_exact_dict_is_accepted_publicly(value):
    with pytest.raises(ValueError):
        StructuredExchange(
            ok=True, value=value, dialect="vllm", response_format_sent=True
        )


def test_an_exact_dict_is_accepted_and_stored_read_only():
    """Positive control: the narrowed type still works and stays read-only."""
    supplied = {"a": 1}
    result = StructuredExchange(
        ok=True, value=supplied, dialect="vllm", response_format_sent=True
    )
    assert _REAL_TYPE(result.value) is MappingProxyType
    supplied["a"] = 999
    assert dict(result.value) == {"a": 1}
    with pytest.raises(TypeError):
        result.value["a"] = 2  # type: ignore[index]


def test_a_dict_subclass_is_refused_publicly():
    class SneakyDict(dict):
        def keys(self):  # pragma: no cover - must never run
            raise AssertionError("keys() invoked on a dict subclass")

    with pytest.raises(ValueError):
        StructuredExchange(
            ok=True,
            value=SneakyDict(a=1),
            dialect="vllm",
            response_format_sent=True,
        )


def test_the_canonical_internal_path_still_produces_a_usable_value():
    """Positive control for the trusted path the narrowing had to preserve."""
    result = request_structured_json(
        _backend(client=RecordingClient(text='{"ok": true, "n": 2}')),
        _MESSAGES,
        [],
        structured=_request(),
    )
    assert result.ok is True
    assert _REAL_TYPE(result.value) is MappingProxyType
    assert dict(result.value) == {"ok": True, "n": 2}


def test_the_internal_path_captures_the_real_validator():
    from scripts.open_model.structured import validate_structured_output

    default = inspect.signature(request_structured_json).parameters[
        "_validate"
    ].default
    assert default is validate_structured_output
