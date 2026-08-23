"""OMI-V2 - controls for Jack's fourth independent HOLD round.

Round three moved every trust decision off module globals and asserted it
against a hand-written forbidden-name set. Both halves were wrong in the same
way, and the second hid the first.

The captures were bound as **defaulted parameters**. A defaulted parameter is
directly addressable, so closing name rebinding had opened something strictly
worse: no rebinding was needed at all. A caller could write

    OpenAICompatBackend(..., dialect="sk-...", _dialect_ok=lambda v: True)
    backend.complete_structured(..., _plan=lambda *a, **k: FakePlan())
    request_structured_json(..., _validate=lambda *a, **k: <success>)

and admit a secret-shaped dialect, put an arbitrary object on the wire as the
`response_format`, or be told an invalid JSON response had succeeded. A
capture a caller can pass is not a capture; it is an injection point with a
leading underscore.

And the proof could not have caught it: a hand-written forbidden-name set
only ever finds what its author already thought of. It listed no stdlib module
alias, so `structured_request.json` stayed open and a rebinding of it bypassed
the UTF-8 refusal entirely; it omitted `getattr`, `callable` and
`_FINISH_REASON_MAP`; and it never examined `_response_from_wire` at all.

So the proof here does not use a list. It discovers every authored callable in
the three modules and reads the actual ``LOAD_GLOBAL`` instructions out of
their bytecode, and the allowlist is three documented constants.

Everything runs identically under normal, ``-O`` and ``-OO``.

Same-author evidence: written by the agent that wrote the code under test.
It demonstrates internal consistency, not independent acceptance.
"""

from __future__ import annotations

import dis
import inspect
import types
from types import MappingProxyType, SimpleNamespace

import pytest

from scripts.agent_backends import openai_compat_backend as bk
from scripts.agent_backends import structured_request as sr
from scripts.agent_backends.base import Message
from scripts.agent_backends.openai_compat_backend import (
    OpenAICompatBackend,
    StructuredCompletion,
)
from scripts.agent_backends.structured_request import (
    StructuredOutputRequest,
    StructuredRequestPlan,
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
_MODULES = (sr, bk, sx)

#: The COMPLETE allowlist of globals an authored decision path may still
#: resolve. Each is individually justified, and there are no others.
#:
#: ``_SCHEMA_MAX_CHARS`` / ``_SCHEMA_MAX_DEPTH`` / ``_SCHEMA_MAX_NODES`` -
#: numeric size bounds on the schema walk. They bound HOW MUCH is accepted and
#: never WHAT TYPE, so rebinding one cannot admit a foreign type, a ``str``
#: subclass, or a secret; it can only widen or narrow a limit, which a
#: deployment may legitimately want to do. Left deliberately open, and the
#: openness is exercised by `test_the_depth_edge_moves_with_the_constant`.
_ALLOWED_GLOBALS = frozenset(
    {"_SCHEMA_MAX_CHARS", "_SCHEMA_MAX_DEPTH", "_SCHEMA_MAX_NODES"}
)

#: Naming prefixes of the BINDING FACTORIES. These are the sites that read
#: module globals on purpose - it is how the cells get filled. Their reads
#: happen exactly once, at import, before any caller exists, so nothing a
#: caller or a later rebinding does can influence them. They are exempt from
#: the closure assertion and are separately asserted to be unexported.
_FACTORY_PREFIXES = ("_closed_", "_build_")


def _is_factory(name: str) -> bool:
    return any(name.startswith(p) for p in _FACTORY_PREFIXES)


def _authored_callables(module) -> list[tuple[str, types.FunctionType]]:
    """Every function authored IN ``module``, including methods.

    Discovery, not a list. Dataclass-generated methods are excluded by the
    only honest discriminator available: their code objects carry the
    synthetic filename ``<string>`` because ``dataclasses`` compiles them from
    generated source, whereas authored code carries the module's real path.
    They are covered separately by
    `test_generated_dataclass_methods_are_generated_and_still_safe`.
    """
    found: list[tuple[str, types.FunctionType, bool, str]] = []
    path = module.__file__

    def consider(label: str, obj, module_level: bool, attribute: str) -> None:
        func = getattr(obj, "__func__", obj)
        if not isinstance(func, types.FunctionType):
            return
        if func.__code__.co_filename != path:
            return
        found.append((label, func, module_level, attribute))

    for name, obj in sorted(vars(module).items()):
        if isinstance(obj, types.FunctionType):
            consider(module.__name__ + "." + name, obj, True, name)
        elif isinstance(obj, type):
            for member_name, member in sorted(vars(obj).items()):
                consider(
                    module.__name__ + "." + name + "." + member_name,
                    member,
                    False,
                    member_name,
                )
    return found


def _load_globals(func) -> set[str]:
    return {
        instruction.argval
        for instruction in dis.get_instructions(func)
        if instruction.opname == "LOAD_GLOBAL"
    }


_ALL_AUTHORED = [
    (label, func, module_level, attribute, module)
    for module in _MODULES
    for label, func, module_level, attribute in _authored_callables(module)
]

#: A factory is a MODULE-LEVEL builder. The distinction matters: an earlier
#: version of this file matched on the name prefix alone, which silently
#: exempted `OpenAICompatBackend._build_request` - a method, not a factory -
#: from the closure assertion. A prefix is not a category.
_FACTORIES = [
    (label, func, module)
    for label, func, module_level, attribute, module in _ALL_AUTHORED
    if module_level and _is_factory(attribute)
]
_DECISION_PATHS = [
    (label, func)
    for label, func, module_level, attribute, module in _ALL_AUTHORED
    if not (module_level and _is_factory(attribute))
]


# == GATE 5 - the closure proof is complete, not a curated list ==============


def test_discovery_actually_finds_the_expected_surface():
    """Guard: an empty or tiny discovery would make every assertion vacuous."""
    labels = {label for label, _, _, _, _ in _ALL_AUTHORED}
    assert len(labels) >= 20, sorted(labels)
    for required in (
        "scripts.agent_backends.structured_request.plan_structured_request",
        "scripts.agent_backends.structured_request.is_supported_dialect",
        "scripts.agent_backends.structured_request._validated_snapshot",
        "scripts.agent_backends.openai_compat_backend."
        "OpenAICompatBackend.__init__",
        "scripts.agent_backends.openai_compat_backend."
        "OpenAICompatBackend.complete_structured",
        # the path round three never examined at all
        "scripts.agent_backends.openai_compat_backend."
        "OpenAICompatBackend._response_from_wire",
        "scripts.agent_backends.openai_compat_backend._attr_or_key",
        "scripts.open_model.structured_exchange.request_structured_json",
        "scripts.open_model.structured_exchange."
        "StructuredExchange.__post_init__",
    ):
        assert required in labels, required


@pytest.mark.parametrize(
    "label,func", _DECISION_PATHS, ids=[label for label, _ in _DECISION_PATHS]
)
def test_no_authored_decision_path_resolves_an_undocumented_global(label, func):
    """Read the real LOAD_GLOBAL instructions. No hand-written name set."""
    leaked = _load_globals(func) - _ALLOWED_GLOBALS
    assert not leaked, label + " resolves " + repr(sorted(leaked))


def test_the_closure_assertion_would_actually_fire():
    """Guard: prove the check catches a function that does resolve a global."""

    def leaky(value):
        return type(value) is str

    assert _load_globals(leaky) - _ALLOWED_GLOBALS == {"type", "str"}


def test_every_binding_factory_is_unexported_and_builds_something_else():
    """The factories read globals on purpose; they must not be reachable API."""
    assert _FACTORIES, "no binding factories discovered"
    for label, func, module in _FACTORIES:
        attribute = label.rsplit(".", 1)[-1]
        exported = getattr(module, "__all__", ())
        assert attribute not in exported, label
        # It is a builder: what it returns is not itself.
        assert func() is not func, label


def test_generated_dataclass_methods_are_generated_and_still_safe():
    """The only authored-module code left resolving globals is not ours.

    `dataclasses` compiles `__eq__`, `__setattr__` and friends against the
    defining module's globals, so they DO resolve names like `type`. The one
    that matters is the frozen guard, and it is not defeated by rebinding:
    it refuses on `name in fields` before the `type` comparison can matter.
    """
    for carrier in (StructuredRequestPlan, StructuredCompletion, StructuredExchange):
        setattr_impl = carrier.__setattr__
        assert setattr_impl.__code__.co_filename == "<string>"

    plan = StructuredRequestPlan(ok=False, refusal="schema-empty")
    with pytest.raises(Exception):
        plan.refusal = _SECRET
    assert plan.refusal == "schema-empty"


def test_the_frozen_guard_holds_while_type_is_rebound(monkeypatch):
    real_type = type
    monkeypatch.setattr(
        sr, "type", lambda o: str if o is not None else real_type(o), raising=False
    )
    plan = StructuredRequestPlan(ok=False, refusal="schema-empty")
    with pytest.raises(Exception):
        plan.refusal = _SECRET
    assert plan.refusal == "schema-empty"


# == GATE 1 - no public signature exposes an authority ======================

_PUBLIC_ENTRY_POINTS = [
    ("OpenAICompatBackend.__init__", OpenAICompatBackend.__init__),
    ("OpenAICompatBackend.complete", OpenAICompatBackend.complete),
    (
        "OpenAICompatBackend.complete_structured",
        OpenAICompatBackend.complete_structured,
    ),
    ("OpenAICompatBackend._response_from_wire", OpenAICompatBackend._response_from_wire),
    ("request_structured_json", request_structured_json),
    ("plan_structured_request", plan_structured_request),
    ("is_supported_dialect", sr.is_supported_dialect),
    ("is_supported_wire_shape", sr.is_supported_wire_shape),
    ("is_pre_dialect_refusal", sr.is_pre_dialect_refusal),
    ("build_response_format", sr.build_response_format),
    ("StructuredRequestPlan.__post_init__", StructuredRequestPlan.__post_init__),
    ("StructuredCompletion.__post_init__", StructuredCompletion.__post_init__),
    ("StructuredExchange.__post_init__", StructuredExchange.__post_init__),
]


@pytest.mark.parametrize(
    "label,func", _PUBLIC_ENTRY_POINTS, ids=[n for n, _ in _PUBLIC_ENTRY_POINTS]
)
def test_no_public_signature_exposes_a_hidden_authority(label, func):
    """No underscore-prefixed parameter, and no callable/type/set default."""
    for name, parameter in inspect.signature(func).parameters.items():
        assert not name.startswith("_"), label + " exposes " + name
        default = parameter.default
        if default is inspect.Parameter.empty or default is None:
            continue
        assert not callable(default), label + "." + name + " defaults to a callable"
        assert not isinstance(
            default, (frozenset, set, dict, MappingProxyType)
        ), label + "." + name + " defaults to a vocabulary"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"_dialect_ok": lambda v: True},
        {"_dict": dict},
    ],
)
def test_backend_construction_refuses_former_capture_keywords(kwargs):
    with pytest.raises(TypeError):
        OpenAICompatBackend(
            model="m", client=SimpleNamespace(), dialect=_SECRET, **kwargs
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"_dialect_ok": lambda v: True},
        {"_plan": lambda *a, **k: None},
        {"_bool": bool},
        {"_Completion": StructuredCompletion},
    ],
)
def test_complete_structured_refuses_former_capture_keywords(kwargs):
    backend = OpenAICompatBackend(
        model="m", client=SimpleNamespace(), dialect="vllm"
    )
    with pytest.raises(TypeError):
        backend.complete_structured(
            _MESSAGES,
            [],
            structured=StructuredOutputRequest(schema=_SCHEMA),
            **kwargs,
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"_validate": lambda *a, **k: None},
        {"_completion_type": StructuredCompletion},
        {"_exchange_type": StructuredExchange},
        {"_proxy": MappingProxyType},
        {"_type": type},
        {"_dict": dict},
    ],
)
def test_request_structured_json_refuses_former_capture_keywords(kwargs):
    with pytest.raises(TypeError):
        request_structured_json(
            SimpleNamespace(),
            _MESSAGES,
            [],
            structured=StructuredOutputRequest(schema=_SCHEMA),
            **kwargs,
        )


# == GATE 2 - stdlib module aliases cannot change acceptance ================


class _FakeJson:
    """A `json` stand-in whose `dumps` hides everything from every check."""

    @staticmethod
    def dumps(obj, **kwargs):
        return "{}"


class _FakeMath:
    @staticmethod
    def isfinite(value):
        return True


@pytest.fixture
def hostile_stdlib_aliases(monkeypatch):
    monkeypatch.setattr(sr, "json", _FakeJson, raising=False)
    monkeypatch.setattr(sr, "math", _FakeMath, raising=False)
    return None


def test_the_hostile_stdlib_aliases_are_installed(hostile_stdlib_aliases):
    assert sr.json.dumps({"anything": 1}) == "{}"
    assert sr.math.isfinite(float("nan")) is True


@pytest.mark.parametrize(
    "schema,expected",
    [
        pytest.param({"x": "\udc80"}, "schema-not-utf8-encodable", id="surrogate"),
        pytest.param({"x": "A" * 70000}, "schema-too-large", id="oversized"),
        pytest.param({"x": float("nan")}, "schema-non-finite-number", id="nan"),
        pytest.param({"x": float("inf")}, "schema-non-finite-number", id="inf"),
        pytest.param({"e": list(range(9000))}, "schema-too-large", id="over-node"),
    ],
)
def test_hostile_stdlib_aliases_cannot_admit_a_refused_schema(
    hostile_stdlib_aliases, schema, expected
):
    plan = plan_structured_request("vllm", StructuredOutputRequest(schema=schema))
    assert plan.ok is False
    assert plan.refusal == expected


def test_a_valid_schema_still_passes_under_hostile_aliases(hostile_stdlib_aliases):
    """Guard: refusing everything would satisfy the controls above."""
    plan = plan_structured_request("vllm", StructuredOutputRequest(schema=_SCHEMA))
    assert plan.ok is True
    assert plan.response_format["json_schema"]["schema"] == _SCHEMA


# == GATE 3 - the capability decision is closed ==============================


@pytest.fixture
def hostile_capability_builtins(monkeypatch):
    fake_method = lambda *a, **k: SimpleNamespace(  # noqa: E731
        ok=True,
        response=SimpleNamespace(text='{"ok": true}'),
        refusal=None,
        dialect="vllm",
        response_format_sent=True,
    )
    monkeypatch.setattr(
        sx, "getattr", lambda o, n, d=None: fake_method, raising=False
    )
    monkeypatch.setattr(sx, "callable", lambda o: True, raising=False)
    return None


def test_the_hostile_capability_builtins_are_installed(hostile_capability_builtins):
    assert sx.getattr(object(), "complete_structured", None) is not None
    assert sx.callable(object()) is True


@pytest.mark.parametrize(
    "backend",
    [object(), SimpleNamespace(), "a string", 42, None],
    ids=["object", "namespace", "str", "int", "none"],
)
def test_a_backend_without_the_method_stays_incapable(
    hostile_capability_builtins, backend
):
    result = request_structured_json(
        backend,
        _MESSAGES,
        [],
        structured=StructuredOutputRequest(schema=_SCHEMA),
    )
    assert result.ok is False
    assert result.request_refusal == "backend-not-structured-capable"
    assert result.dialect is None


# == GATE 4 - the finish reason cannot leave its closed vocabulary ==========

_STOP_REASONS = frozenset(
    {"end_turn", "tool_use", "max_tokens", "stop_sequence", "error", "other"}
)


class _Client:
    def __init__(self, finish_reason):
        self.requests: list[dict] = []
        self._finish = finish_reason
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"ok": true}', tool_calls=None),
                    finish_reason=self._finish,
                )
            ],
            usage=None,
        )


@pytest.mark.parametrize(
    "hostile",
    [
        pytest.param("rebind", id="rebind-the-map"),
        pytest.param("mutate", id="mutate-the-map-in-place"),
    ],
)
@pytest.mark.parametrize(
    "finish_reason",
    ["stop", "tool_calls", "length", "content_filter", "function_call",
     "stop_sequence", "", None, "unknown", 7],
    ids=["stop", "tool_calls", "length", "content_filter", "function_call",
         "stop_sequence", "empty", "none", "unknown", "nonstring"],
)
def test_the_stop_reason_stays_in_its_vocabulary(monkeypatch, hostile, finish_reason):
    if hostile == "rebind":
        monkeypatch.setattr(bk, "_FINISH_REASON_MAP", {"stop": _SECRET})
    else:
        # A plain module-level dict is mutable in place, which no amount of
        # rebinding protection would have covered.
        monkeypatch.setitem(bk._FINISH_REASON_MAP, "stop", _SECRET)
        monkeypatch.setitem(bk._FINISH_REASON_MAP, "length", _SECRET)

    client = _Client(finish_reason)
    backend = OpenAICompatBackend(model="m", client=client, dialect="vllm")
    result = backend.complete_structured(
        _MESSAGES, [], structured=StructuredOutputRequest(schema=_SCHEMA)
    )
    assert result.ok is True
    assert result.response.stop_reason in _STOP_REASONS
    assert _SECRET not in repr(result.response.stop_reason)


def test_the_finish_reason_mirror_still_matches_the_inlined_chain():
    """Drift guard: `_FINISH_REASON_MAP` is documentation now, not a lookup."""
    for wire_value, expected in bk._FINISH_REASON_MAP.items():
        client = _Client(wire_value)
        backend = OpenAICompatBackend(model="m", client=client, dialect="vllm")
        result = backend.complete_structured(
            _MESSAGES, [], structured=StructuredOutputRequest(schema=_SCHEMA)
        )
        assert result.response.stop_reason == expected, wire_value


def test_the_stop_reason_control_is_not_vacuous():
    """Guard: distinct wire values must still yield distinct stop reasons, or
    the vocabulary assertions above would hold for a constant."""
    assert bk._FINISH_REASON_MAP["stop"] != bk._FINISH_REASON_MAP["length"]
    reasons = set()
    for wire_value in ("stop", "length", "tool_calls"):
        backend = OpenAICompatBackend(
            model="m", client=_Client(wire_value), dialect="vllm"
        )
        result = backend.complete_structured(
            _MESSAGES, [], structured=StructuredOutputRequest(schema=_SCHEMA)
        )
        reasons.add(result.response.stop_reason)
    assert len(reasons) == 3, sorted(reasons)
