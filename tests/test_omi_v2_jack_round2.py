"""OMI-V2 - controls for Jack's second independent HOLD round.

Three gates, each reproduced before it was fixed and each closed here by a
control that fails without its correction:

1. the mutation window between validating caller data and serialising it;
2. refusal, failure and dialect decisions taken through rebindable names;
3. cross-field coherence of the three result carriers.

Everything runs identically under normal, ``-O`` and ``-OO``: no library
``assert`` is relied upon and no ``__doc__`` is read.

Same-author evidence: written by the agent that wrote the code under test.
It demonstrates internal consistency, not independent acceptance.
"""

from __future__ import annotations

import json
from types import MappingProxyType, SimpleNamespace

import pytest

from scripts.agent_backends import openai_compat_backend as backend_module
from scripts.agent_backends import structured_request as sr
from scripts.agent_backends.base import AgentResponse, Message
from scripts.agent_backends.openai_compat_backend import (
    OpenAICompatBackend,
    StructuredCompletion,
)
from scripts.agent_backends.structured_request import (
    REFUSAL_TOKENS,
    StructuredOutputRequest,
    StructuredRequestPlan,
    is_pre_dialect_refusal,
    is_supported_dialect,
    is_supported_wire_shape,
    plan_structured_request,
)
from scripts.open_model import structured_exchange as sx
from scripts.open_model.structured_exchange import (
    EXCHANGE_REFUSALS,
    RESPONSE_FAILURES,
    StructuredExchange,
    request_structured_json,
)


_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
_MESSAGES = [Message(role="user", content="hello")]
_SECRET = "sk-OMIV2SECRET123456789"
_RESPONSE = AgentResponse.from_content([])


def _request(schema=None) -> StructuredOutputRequest:
    return StructuredOutputRequest(schema=_SCHEMA if schema is None else schema)


def _chain(levels: int) -> dict:
    root: dict = {"type": "object"}
    node = root
    for _ in range(levels):
        child: dict = {"type": "object"}
        node["properties"] = child
        node = child
    return root


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


# == GATE 1 - no window between validation and snapshot ======================
#
# The old implementation validated by walking the caller's containers and then
# handed the CALLER'S OBJECT to json.dumps, re-reading it a second time. Any
# change the caller made in between was serialised without ever having been
# checked.
#
# The window is reproduced deterministically - no threads, no timing - by
# making json.dumps itself perform the mutation. That is the exact instant the
# old design re-read caller data. If dumps still received the caller's object,
# the injected payload would land in the snapshot (or, for a wrong type, would
# refuse the plan). Receiving a detached snapshot, it cannot.

_INJECTIONS = [
    pytest.param(lambda: _chain(200), "over-depth", id="over-depth"),
    pytest.param(lambda: {"e": list(range(9000))}, "over-node", id="over-node"),
    pytest.param(lambda: object(), "wrong-type", id="wrong-type"),
]


@pytest.mark.parametrize("make_payload,label", [(p.values[0], p.values[1]) for p in _INJECTIONS])
def test_mutation_at_serialisation_time_cannot_enter_the_snapshot(
    monkeypatch, make_payload, label
):
    schema = {"a": {"b": 1}}
    payload = make_payload()
    real_dumps = json.dumps
    seen: dict = {}

    def mutating_dumps(obj, **kwargs):
        # Record what was handed to the serialiser, then mutate an
        # ALREADY-VISITED slot of the caller's document.
        seen["obj"] = obj
        schema["a"]["b"] = payload
        return real_dumps(obj, **kwargs)

    monkeypatch.setattr(sr.json, "dumps", mutating_dumps)
    plan = plan_structured_request("vllm", _request(schema))

    # The injection really happened - otherwise this control proves nothing.
    assert schema["a"]["b"] is payload, label
    # The serialiser was never handed the caller's own document.
    assert seen["obj"] is not schema, label
    # And the accepted snapshot contains only what was validated.
    assert plan.ok is True, label
    assert plan.response_format["json_schema"]["schema"] == {"a": {"b": 1}}, label


def test_the_serialiser_receives_a_detached_object(monkeypatch):
    """Structural companion: dumps must never see caller-owned containers."""
    schema = {"a": {"b": [1, 2]}, "c": "x"}
    real_dumps = json.dumps
    seen: dict = {}

    def watching_dumps(obj, **kwargs):
        seen["obj"] = obj
        return real_dumps(obj, **kwargs)

    monkeypatch.setattr(sr.json, "dumps", watching_dumps)
    plan_structured_request("vllm", _request(schema))

    handed = seen["obj"]
    assert handed is not schema
    assert handed["a"] is not schema["a"]
    assert handed["a"]["b"] is not schema["a"]["b"]
    assert handed == schema


def _shares_container(a, b) -> bool:
    """True if any container object is reachable from both a and b."""
    seen_a: set[int] = set()

    def collect(node):
        if type(node) is dict:
            seen_a.add(id(node))
            for v in node.values():
                collect(v)
        elif type(node) is list:
            seen_a.add(id(node))
            for v in node:
                collect(v)

    collect(a)

    found = False

    def probe(node):
        nonlocal found
        if type(node) is dict:
            if id(node) in seen_a:
                found = True
            for v in node.values():
                probe(v)
        elif type(node) is list:
            if id(node) in seen_a:
                found = True
            for v in node:
                probe(v)

    probe(b)
    return found


def test_the_snapshot_shares_no_container_with_the_caller():
    schema = {"a": {"b": [1, {"c": 2}]}, "d": ["e"]}
    plan = plan_structured_request("vllm", _request(schema))
    snapshot = plan.response_format["json_schema"]["schema"]
    assert snapshot == schema
    assert not _shares_container(schema, snapshot)


def test_the_share_detector_would_actually_fire():
    """Guard: an inert detector makes the control above vacuous."""
    shared: dict = {"x": 1}
    assert _shares_container({"a": shared}, {"b": shared}) is True
    assert _shares_container({"a": {"x": 1}}, {"b": {"x": 1}}) is False


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda s: s.__setitem__("injected", _chain(200)), id="top-level"),
        pytest.param(lambda s: s["a"].__setitem__("b", _chain(200)), id="nested"),
        pytest.param(lambda s: s["list"].append(_chain(200)), id="list-element"),
        pytest.param(lambda s: s["a"].__setitem__("b", object()), id="wrong-type"),
        pytest.param(lambda s: s.clear(), id="cleared"),
    ],
)
def test_post_validation_mutation_cannot_reach_the_outbound_request(mutate):
    schema = {"a": {"b": 1}, "list": [1, 2]}
    before = {"a": {"b": 1}, "list": [1, 2]}
    client = RecordingClient()
    backend = _backend(client=client)
    plan = plan_structured_request("vllm", _request(schema))
    mutate(schema)
    assert plan.response_format["json_schema"]["schema"] == before

    # ...and through the full backend path, mutating after the call returned.
    schema2 = {"a": {"b": 1}, "list": [1, 2]}
    backend.complete_structured(_MESSAGES, [], structured=_request(schema2))
    mutate(schema2)
    sent = client.requests[0]["response_format"]["json_schema"]["schema"]
    assert sent == before


# == GATE 2 - no rebindable name on any decision path ========================

_MIRRORS = [
    (sr, "REFUSAL_TOKENS", frozenset({_SECRET})),
    (sr, "SUPPORTED_DIALECTS", (_SECRET,)),
    (sr, "STRUCTURED_WIRE_NAME", _SECRET),
    (sr, "DIALECT_WIRE_SHAPES", {_SECRET: _SECRET}),
    (sr, "is_supported_dialect", lambda v: True),
    (sr, "is_pre_dialect_refusal", lambda v: True),
    (sr, "is_supported_wire_shape", lambda v: True),
    (backend_module, "REFUSAL_TOKENS", frozenset({_SECRET})),
    (backend_module, "is_supported_dialect", lambda v: True),
    (backend_module, "is_pre_dialect_refusal", lambda v: True),
    (backend_module, "AgentResponse", str),
    (sx, "EXCHANGE_REFUSALS", frozenset({_SECRET})),
    (sx, "RESPONSE_FAILURES", frozenset({_SECRET})),
    (sx, "is_supported_dialect", lambda v: True),
    (sx, "is_pre_dialect_refusal", lambda v: True),
    (sx, "MappingProxyType", dict),
]


@pytest.fixture
def rebind_every_mirror(monkeypatch):
    """Rebind EVERY exported or global mirror in EVERY consuming module."""
    for module, name, replacement in _MIRRORS:
        monkeypatch.setattr(module, name, replacement, raising=True)
    return None


def test_rebinding_every_mirror_cannot_admit_a_secret_refusal(rebind_every_mirror):
    with pytest.raises(ValueError):
        StructuredRequestPlan(ok=False, refusal=_SECRET)
    with pytest.raises(ValueError):
        StructuredCompletion(ok=False, refusal=_SECRET, dialect="vllm")
    with pytest.raises(ValueError):
        StructuredExchange(ok=False, request_refusal=_SECRET, dialect="vllm")


def test_rebinding_every_mirror_cannot_admit_a_secret_failure(rebind_every_mirror):
    with pytest.raises(ValueError):
        StructuredExchange(
            ok=False,
            response_failure=_SECRET,
            dialect="vllm",
            response_format_sent=True,
        )


def test_rebinding_every_mirror_cannot_admit_a_secret_dialect(rebind_every_mirror):
    with pytest.raises(ValueError):
        StructuredCompletion(
            ok=True, response=_RESPONSE, dialect=_SECRET, response_format_sent=True
        )
    with pytest.raises(ValueError):
        StructuredExchange(
            ok=True, value={"a": 1}, dialect=_SECRET, response_format_sent=True
        )


def test_rebinding_every_mirror_cannot_admit_a_foreign_wire_shape(
    rebind_every_mirror,
):
    with pytest.raises(ValueError):
        StructuredRequestPlan(ok=True, response_format={"anything": _SECRET})
    with pytest.raises(ValueError):
        StructuredRequestPlan(
            ok=True,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": _SECRET, "schema": {}},
            },
        )


def test_rebinding_every_mirror_cannot_admit_a_foreign_response(rebind_every_mirror):
    with pytest.raises(ValueError):
        StructuredCompletion(
            ok=True, response=_SECRET, dialect="vllm", response_format_sent=True
        )


def test_rebinding_every_mirror_leaves_the_valid_cases_valid(rebind_every_mirror):
    """Guard: a check that rejected everything would pass every test above."""
    assert StructuredRequestPlan(ok=False, refusal="schema-empty").ok is False
    assert StructuredCompletion(
        ok=True, response=_RESPONSE, dialect="vllm", response_format_sent=True
    ).ok is True
    assert StructuredExchange(
        ok=True, value={"a": 1}, dialect="vllm", response_format_sent=True
    ).ok is True


def test_rebinding_every_mirror_cannot_redirect_a_built_request(rebind_every_mirror):
    plan = plan_structured_request("vllm", _request())
    assert plan.ok is True
    assert plan.response_format["json_schema"]["name"] == "structured_output"
    assert _SECRET not in repr(plan)


def test_rebinding_every_mirror_cannot_open_a_fifth_dialect(rebind_every_mirror):
    assert plan_structured_request(_SECRET, _request()).refusal == (
        "dialect-unsupported"
    )


@pytest.mark.parametrize(
    "carrier",
    [StructuredRequestPlan, StructuredCompletion, StructuredExchange],
)
def test_no_carrier_resolves_a_trust_name_when_constructed(carrier):
    """Structural: the decision path must look up no rebindable trust name."""
    forbidden = {
        "REFUSAL_TOKENS",
        "EXCHANGE_REFUSALS",
        "RESPONSE_FAILURES",
        "SUPPORTED_DIALECTS",
        "STRUCTURED_WIRE_NAME",
        "DIALECT_WIRE_SHAPES",
        "is_supported_dialect",
        "is_pre_dialect_refusal",
        "is_supported_wire_shape",
        "AgentResponse",
        "MappingProxyType",
        "object",
        "type",
        "str",
        "bool",
        "int",
        "dict",
        "tuple",
        "frozenset",
    }
    referenced = set(carrier.__post_init__.__code__.co_names)
    assert not (referenced & forbidden), sorted(referenced & forbidden)


def test_the_mirrors_still_match_the_inlined_decisions():
    """Drift guard: mirrors are documentation, and must stay accurate."""
    for token in REFUSAL_TOKENS:
        assert StructuredRequestPlan(ok=False, refusal=token).refusal == token
    for dialect in sr.SUPPORTED_DIALECTS:
        assert is_supported_dialect(dialect) is True
    assert sr.STRUCTURED_WIRE_NAME == "structured_output"
    pre = {t for t in REFUSAL_TOKENS if is_pre_dialect_refusal(t)}
    assert pre == {
        "dialect-not-configured",
        "dialect-not-exact-str",
        "dialect-unsupported",
    }


# == GATE 3 - cross-field carrier coherence ==================================


def test_a_successful_completion_must_name_a_verified_dialect():
    with pytest.raises(ValueError):
        StructuredCompletion(
            ok=True, response=_RESPONSE, response_format_sent=True
        )
    assert StructuredCompletion(
        ok=True, response=_RESPONSE, dialect="vllm", response_format_sent=True
    ).dialect == "vllm"


def test_a_successful_exchange_must_name_a_verified_dialect():
    with pytest.raises(ValueError):
        StructuredExchange(ok=True, value={"a": 1}, response_format_sent=True)
    assert StructuredExchange(
        ok=True, value={"a": 1}, dialect="sglang", response_format_sent=True
    ).dialect == "sglang"


@pytest.mark.parametrize(
    "token", ["dialect-not-configured", "dialect-not-exact-str", "dialect-unsupported"]
)
def test_a_pre_dialect_refusal_carries_no_dialect(token):
    with pytest.raises(ValueError):
        StructuredCompletion(ok=False, refusal=token, dialect="vllm")
    with pytest.raises(ValueError):
        StructuredExchange(ok=False, request_refusal=token, dialect="vllm")
    assert StructuredCompletion(ok=False, refusal=token).dialect is None
    assert StructuredExchange(ok=False, request_refusal=token).dialect is None


def test_the_backend_not_capable_refusal_carries_no_dialect():
    with pytest.raises(ValueError):
        StructuredExchange(
            ok=False, request_refusal="backend-not-structured-capable", dialect="vllm"
        )
    assert StructuredExchange(
        ok=False, request_refusal="backend-not-structured-capable"
    ).dialect is None


@pytest.mark.parametrize(
    "token",
    [
        "request-not-exact-type",
        "schema-empty",
        "schema-not-exact-dict",
        "schema-too-deep",
        "schema-too-large",
        "schema-not-utf8-encodable",
        "schema-changed-during-validation",
        "tools-with-structured-unsupported",
    ],
)
def test_a_post_dialect_refusal_must_name_a_verified_dialect(token):
    with pytest.raises(ValueError):
        StructuredCompletion(ok=False, refusal=token)
    with pytest.raises(ValueError):
        StructuredExchange(ok=False, request_refusal=token)
    assert StructuredCompletion(ok=False, refusal=token, dialect="ollama").dialect == (
        "ollama"
    )
    assert StructuredExchange(
        ok=False, request_refusal=token, dialect="ollama"
    ).dialect == "ollama"


@pytest.mark.parametrize("token", sorted(RESPONSE_FAILURES))
def test_a_response_failure_must_name_a_verified_dialect(token):
    indices = (0,) if token == "missing-required-key" else ()
    with pytest.raises(ValueError):
        StructuredExchange(
            ok=False,
            response_failure=token,
            missing_key_indices=indices,
            response_format_sent=True,
        )
    assert StructuredExchange(
        ok=False,
        response_failure=token,
        missing_key_indices=indices,
        dialect="llama-cpp",
        response_format_sent=True,
    ).dialect == "llama-cpp"


@pytest.mark.parametrize(
    "response_format",
    [
        {},
        {"a": 1},
        {"type": "json_schema"},
        {"type": "json_object", "json_schema": {"schema": {}}},
        {"type": "json_schema", "schema": {}},
        {"type": "json_schema", "json_schema": {}},
        {"type": "json_schema", "json_schema": {"schema": "not-a-dict"}},
        {"type": "json_schema", "json_schema": {"name": "other", "schema": {}}},
        {"type": "json_schema", "json_schema": {"name": _SECRET, "schema": {}}},
        {"type": "json_schema", "json_schema": {"schema": {}}, "extra": 1},
        {
            "type": "json_schema",
            "json_schema": {"name": "structured_output", "schema": {}, "strict": True},
        },
    ],
)
def test_a_successful_plan_refuses_a_non_dialect_wire_shape(response_format):
    with pytest.raises(ValueError):
        StructuredRequestPlan(ok=True, response_format=response_format)


@pytest.mark.parametrize(
    "response_format",
    [
        {"type": "json_schema", "json_schema": {"schema": {}}},
        {"type": "json_schema", "json_schema": {"schema": {"a": 1}}},
        {
            "type": "json_schema",
            "json_schema": {"name": "structured_output", "schema": {"a": 1}},
        },
    ],
)
def test_a_successful_plan_accepts_the_exact_dialect_wire_shapes(response_format):
    assert StructuredRequestPlan(ok=True, response_format=response_format).ok is True


def test_every_dialect_the_builder_emits_satisfies_the_carrier():
    """The builder and the carrier must agree, in both directions."""
    for dialect in sr.SUPPORTED_DIALECTS:
        wire = sr.build_response_format(dialect, _request())
        assert is_supported_wire_shape(wire) is True, dialect
        assert StructuredRequestPlan(ok=True, response_format=wire).ok is True


# == GATE 3 - the read-only value claim is now true ==========================


def test_the_exchange_value_is_a_genuine_read_only_view():
    supplied = {"a": 1}
    result = StructuredExchange(
        ok=True, value=supplied, dialect="vllm", response_format_sent=True
    )
    assert type(result.value) is MappingProxyType
    with pytest.raises(TypeError):
        result.value["a"] = 2  # type: ignore[index]


def test_mutating_the_supplied_mapping_cannot_change_the_result():
    supplied = {"a": 1}
    result = StructuredExchange(
        ok=True, value=supplied, dialect="vllm", response_format_sent=True
    )
    supplied["a"] = 999
    supplied["injected"] = _SECRET
    assert dict(result.value) == {"a": 1}
    assert _SECRET not in repr(result)


def test_a_supplied_proxy_is_refused_outright():
    """Narrowed in Jack round 3. Round 2 accepted and copied a proxy; a proxy
    can wrap an arbitrary foreign mapping, so copying one ran its hooks."""
    underlying = {"a": 1}
    with pytest.raises(ValueError):
        StructuredExchange(
            ok=True,
            value=MappingProxyType(underlying),
            dialect="vllm",
            response_format_sent=True,
        )


def test_the_read_only_claim_is_scoped_to_the_top_level():
    """Honest boundary: the proxy is shallow, exactly as documented."""
    nested = {"inner": {"a": 1}}
    result = StructuredExchange(
        ok=True, value=nested, dialect="vllm", response_format_sent=True
    )
    nested["inner"]["a"] = 999
    # The nested container IS shared - the docstring says so rather than
    # claiming a deep copy it does not make.
    assert result.value["inner"]["a"] == 999


# == the real paths still produce coherent carriers ==========================


def test_the_backend_produces_coherent_carriers_on_every_path():
    client = RecordingClient()
    ok = _backend(client=client).complete_structured(
        _MESSAGES, [], structured=_request()
    )
    assert ok.ok is True and ok.dialect == "vllm"

    unconfigured = OpenAICompatBackend(
        model="m", client=RecordingClient()
    ).complete_structured(_MESSAGES, [], structured=_request())
    assert unconfigured.refusal == "dialect-not-configured"
    assert unconfigured.dialect is None

    post = _backend(client=RecordingClient()).complete_structured(
        _MESSAGES, [], structured=_request({})
    )
    assert post.refusal == "schema-empty"
    assert post.dialect == "vllm"


def test_the_exchange_produces_coherent_carriers_on_every_path():
    ok = request_structured_json(
        _backend(client=RecordingClient()), _MESSAGES, [], structured=_request()
    )
    assert ok.ok is True and ok.dialect == "vllm"

    bad = request_structured_json(
        _backend(client=RecordingClient(text="not json")),
        _MESSAGES,
        [],
        structured=_request(),
    )
    assert bad.response_failure == "invalid-json"
    assert bad.dialect == "vllm"
    assert bad.response_format_sent is True

    incapable = request_structured_json(
        SimpleNamespace(), _MESSAGES, [], structured=_request()
    )
    assert incapable.request_refusal == "backend-not-structured-capable"
    assert incapable.dialect is None
