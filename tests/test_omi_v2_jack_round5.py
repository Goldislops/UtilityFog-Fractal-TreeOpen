"""OMI-V2 - controls for Jack's fifth independent HOLD round.

Round four moved every authority out of a caller-addressable defaulted
parameter and into a closure cell. That was the right fix and it carried a
regression: a class or function created inside a factory takes its
``__qualname__`` from the factory, so every exported object was named

    _build_backend_class.<locals>.OpenAICompatBackend

``pickle`` resolves an object by ``__module__`` plus ``__qualname__``, so all
ten exported classes and functions became unpicklable - and the frozen
dataclasses leaked the factory name into every ``repr``. This was a real
compatibility break, not a theoretical one: ``OpenAICompatBackend`` pickles at
the base commit and at the previous head, and stopped at the round-four head.

Identity is restored by setting only ``__module__``, ``__name__`` and
``__qualname__``. Nothing else is touched: the cells still hold what they
held, no defaulted authority parameter comes back, and this file re-asserts
both of those directly rather than assuming the fix was surgical.

Everything runs identically under normal, ``-O`` and ``-OO``.

Same-author evidence: written by the agent that wrote the code under test.
It demonstrates internal consistency, not independent acceptance.
"""

from __future__ import annotations

import dis
import inspect
import pickle
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


def _module_level_objects(module):
    """Every class and function this module binds at module level.

    Discovered, not listed. Round four learned that a hand-written inventory
    only ever covers what its author remembered; the same applies here, and
    an object added to a factory later must not be able to slip past.
    """
    found = []
    for name, obj in sorted(vars(module).items()):
        if getattr(obj, "__module__", None) != module.__name__:
            continue
        if isinstance(obj, (types.FunctionType, type)):
            found.append((module.__name__ + "." + name, name, obj, module))
    return found


_ALL_OBJECTS = [
    entry for module in _MODULES for entry in _module_level_objects(module)
]

#: The objects Jack named explicitly. Used only as a NON-VACUITY guard on the
#: discovery above - the assertions themselves run over everything discovered.
_NAMED_BY_JACK = [
    ("scripts.agent_backends.openai_compat_backend", "OpenAICompatBackend"),
    ("scripts.agent_backends.structured_request", "StructuredRequestPlan"),
    ("scripts.agent_backends.openai_compat_backend", "StructuredCompletion"),
    ("scripts.open_model.structured_exchange", "StructuredExchange"),
    ("scripts.agent_backends.structured_request", "is_supported_dialect"),
    ("scripts.agent_backends.structured_request", "is_pre_dialect_refusal"),
    ("scripts.agent_backends.structured_request", "is_supported_wire_shape"),
    ("scripts.agent_backends.structured_request", "build_response_format"),
    ("scripts.agent_backends.structured_request", "plan_structured_request"),
    ("scripts.open_model.structured_exchange", "request_structured_json"),
]


# == the discovery covers what it must ======================================


def test_discovery_covers_every_object_jack_named():
    labels = {label for label, _, _, _ in _ALL_OBJECTS}
    assert len(labels) >= 20, sorted(labels)
    for module_name, attribute in _NAMED_BY_JACK:
        assert module_name + "." + attribute in labels, attribute


# == identity: __module__, __name__, module-level __qualname__ ==============


@pytest.mark.parametrize(
    "label,name,obj,module",
    _ALL_OBJECTS,
    ids=[label for label, _, _, _ in _ALL_OBJECTS],
)
def test_every_module_level_object_has_genuine_identity(label, name, obj, module):
    assert obj.__module__ == module.__name__, label
    assert obj.__name__ == name, label
    assert obj.__qualname__ == name, label
    assert "<locals>" not in obj.__qualname__, label


@pytest.mark.parametrize(
    "label,name,obj,module",
    _ALL_OBJECTS,
    ids=[label for label, _, _, _ in _ALL_OBJECTS],
)
def test_every_module_level_object_resolves_back_to_itself(label, name, obj, module):
    """The property `pickle` actually relies on: name lookup returns THIS object."""
    assert getattr(module, obj.__qualname__) is obj, label


@pytest.mark.parametrize(
    "label,name,obj,module",
    [e for e in _ALL_OBJECTS if isinstance(e[2], type)],
    ids=[label for label, _, o, _ in _ALL_OBJECTS if isinstance(o, type)],
)
def test_no_method_qualname_leaks_the_factory(label, name, obj, module):
    for member_name, member in vars(obj).items():
        func = getattr(member, "__func__", member)
        qualname = getattr(func, "__qualname__", "")
        assert "<locals>" not in qualname, label + "." + member_name


def test_the_identity_assertion_would_actually_fire():
    """Guard: prove the check catches a factory-local object."""

    def factory():
        def inner():
            return None

        return inner

    built = factory()
    assert "<locals>" in built.__qualname__
    # CPython reports an unpicklable local object as PicklingError on some
    # versions and AttributeError ("Can't get local object") on others. Both
    # mean the same thing, and pinning one of them made this guard pass
    # locally and fail on CI - the guard has to be about the OUTCOME, not
    # about which flavour of refusal a particular interpreter chose.
    with pytest.raises((pickle.PicklingError, AttributeError)):
        pickle.dumps(built)


# == pickle round-trips to the identical exported object ====================


@pytest.mark.parametrize(
    "label,name,obj,module",
    _ALL_OBJECTS,
    ids=[label for label, _, _, _ in _ALL_OBJECTS],
)
def test_every_module_level_object_pickles_to_the_identical_object(
    label, name, obj, module
):
    assert pickle.loads(pickle.dumps(obj)) is obj, label


def test_the_backend_class_pickles_as_it_did_before_omi_v2():
    """The exact regression Jack reported, stated as its own control."""
    assert pickle.loads(pickle.dumps(OpenAICompatBackend)) is OpenAICompatBackend


@pytest.mark.parametrize(
    "instance",
    [
        StructuredRequestPlan(ok=False, refusal="schema-empty"),
        StructuredRequestPlan(
            ok=True,
            response_format={
                "type": "json_schema",
                "json_schema": {"schema": {"a": 1}},
            },
        ),
        StructuredOutputRequest(schema={"a": 1}),
        StructuredCompletion(ok=False, refusal="dialect-not-configured"),
        StructuredCompletion(
            ok=False, refusal="schema-empty", dialect="vllm"
        ),
        StructuredExchange(
            ok=False, request_refusal="backend-not-structured-capable"
        ),
        StructuredExchange(
            ok=False,
            response_failure="invalid-json",
            dialect="vllm",
            response_format_sent=True,
        ),
    ],
    ids=[
        "plan-refused",
        "plan-successful",
        "request",
        "completion-pre-dialect",
        "completion-post-dialect",
        "exchange-refused",
        "exchange-response-failure",
    ],
)
def test_the_supported_instance_states_round_trip(instance):
    """These specific states round-trip. That is the whole claim.

    It is deliberately NOT "all carrier instances round-trip" - see
    `test_a_successful_exchange_instance_cannot_be_pickled` for the state that
    does not, and why.
    """
    restored = pickle.loads(pickle.dumps(instance))
    assert restored == instance
    assert type(restored) is type(instance)


def _successful_exchange() -> StructuredExchange:
    """A canonical success, produced by the real path rather than by hand.

    Building it through `request_structured_json` matters: the limitation
    below is a property of what the supported path actually produces, not of
    a value a test happened to choose.
    """

    class _Client:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"ok": true}', tool_calls=None
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            )

    backend = OpenAICompatBackend(model="m", client=_Client(), dialect="vllm")
    return request_structured_json(
        backend,
        _MESSAGES,
        [],
        structured=StructuredOutputRequest(schema=_SCHEMA),
    )


def test_a_successful_exchange_instance_cannot_be_pickled():
    """A DOCUMENTED limitation, asserted rather than left to be discovered.

    A successful exchange carries its value as a `MappingProxyType`, because
    the read-only view is the point: it is what stops a caller mutating a
    shared result through their own reference. `mappingproxy` has no pickle
    support, so the successful state cannot be pickled.

    The honest options were to weaken the proxy or to add custom `__reduce__`
    behaviour, and this bounded correction does neither - both would trade a
    live protection for a convenience nobody has asked for. The limitation is
    stated in the module docstring, in section 16.14 of the integration
    document, and in the pull-request body, and it is pinned here so it cannot
    change silently.
    """
    result = _successful_exchange()
    assert result.ok is True
    assert type(result.value) is MappingProxyType
    with pytest.raises(TypeError) as caught:
        pickle.dumps(result)
    assert "mappingproxy" in str(caught.value)


def test_the_successful_exchange_is_otherwise_intact():
    """Guard: the state above must be a real success, not a degenerate one."""
    result = _successful_exchange()
    assert result.dialect == "vllm"
    assert result.response_format_sent is True
    assert dict(result.value) == {"ok": True}
    assert result.schema_conformance == "unverified"


def test_no_carrier_repr_exposes_locals():
    for instance in (
        StructuredRequestPlan(ok=False, refusal="schema-empty"),
        StructuredCompletion(ok=False, refusal="dialect-not-configured"),
        StructuredExchange(ok=False, request_refusal="backend-not-structured-capable"),
        StructuredOutputRequest(schema={"a": 1}),
    ):
        assert "<locals>" not in repr(instance), repr(instance)
        assert type(instance).__name__ in repr(instance)


# == the closure protections are NOT weakened by the identity fix ===========

_ALLOWED_GLOBALS = frozenset(
    {"_SCHEMA_MAX_CHARS", "_SCHEMA_MAX_DEPTH", "_SCHEMA_MAX_NODES"}
)


def _authored_functions():
    """Every authored function, carrying whether it is bound at MODULE level.

    The module-level flag is the whole point. Round four established that a
    binding factory is a module-level builder and that matching on the name
    prefix alone silently exempts `OpenAICompatBackend._build_request` - a
    method, not a factory - from the closure assertion. Round five reproduced
    that exact defect by filtering on the prefix again. A prefix is not a
    category, twice over.
    """
    out = []
    for module in _MODULES:
        for name, obj in sorted(vars(module).items()):
            if isinstance(obj, types.FunctionType):
                out.append((module.__name__ + "." + name, name, obj, module, True))
            elif isinstance(obj, type):
                for member_name, member in sorted(vars(obj).items()):
                    func = getattr(member, "__func__", member)
                    if isinstance(func, types.FunctionType):
                        out.append(
                            (
                                module.__name__ + "." + name + "." + member_name,
                                member_name,
                                func,
                                module,
                                False,
                            )
                        )
    return [
        entry
        for entry in out
        if entry[2].__code__.co_filename == entry[3].__file__
    ]


_AUTHORED = [
    (label, func)
    for label, attribute, func, module, module_level in _authored_functions()
    if not (
        module_level
        and (attribute.startswith("_closed_") or attribute.startswith("_build_"))
    )
]

#: Methods whose names collide with the factory prefixes. They are the reason
#: the exemption must test module level and not just the name, and they are
#: asserted present below so the surface cannot silently shrink again.
_PREFIX_COLLIDING_METHODS = (
    "scripts.agent_backends.openai_compat_backend."
    "OpenAICompatBackend._build_request",
)


def test_the_decision_surface_includes_prefix_colliding_methods():
    """Non-vacuity guard for the classification defect, now seen twice.

    `_build_request` starts with `_build_`, which is a binding-factory prefix.
    It is a method, so it is NOT a factory and must be audited like any other
    decision path. Round four fixed this; round five reintroduced it; this
    assertion makes a third occurrence impossible to ship quietly.
    """
    labels = {label for label, _ in _AUTHORED}
    for required in _PREFIX_COLLIDING_METHODS:
        assert required in labels, required
    assert len(labels) >= 22, sorted(labels)


@pytest.mark.parametrize(
    "label,func", _AUTHORED, ids=[label for label, _ in _AUTHORED]
)
def test_the_closure_is_still_complete_after_the_identity_fix(label, func):
    leaked = {
        instruction.argval
        for instruction in dis.get_instructions(func)
        if instruction.opname == "LOAD_GLOBAL"
    } - _ALLOWED_GLOBALS
    assert not leaked, label + " resolves " + repr(sorted(leaked))


@pytest.mark.parametrize(
    "label,func", _AUTHORED, ids=[label for label, _ in _AUTHORED]
)
def test_no_defaulted_authority_parameter_came_back(label, func):
    for parameter_name, parameter in inspect.signature(func).parameters.items():
        assert not parameter_name.startswith("_"), label + " exposes " + parameter_name
        default = parameter.default
        if default is inspect.Parameter.empty or default is None:
            continue
        assert not callable(default), label + "." + parameter_name


def test_the_captured_cells_still_hold_what_they_held():
    """Identity restoration must not have replaced a captured authority."""
    from scripts.open_model.structured import validate_structured_output

    freevars = request_structured_json.__code__.co_freevars
    captured = {
        name: request_structured_json.__closure__[index].cell_contents
        for index, name in enumerate(freevars)
    }
    assert captured["_validate"] is validate_structured_output
    assert captured["_exchange_type"] is StructuredExchange
    assert captured["_completion_type"] is StructuredCompletion
    assert captured["_type"] is type
    assert captured["_getattr"] is getattr
    assert captured["_callable"] is callable


def test_former_capture_keywords_are_still_refused():
    with pytest.raises(TypeError):
        OpenAICompatBackend(
            model="m",
            client=SimpleNamespace(),
            dialect=_SECRET,
            _dialect_ok=lambda v: True,
        )
    with pytest.raises(TypeError):
        request_structured_json(
            SimpleNamespace(),
            _MESSAGES,
            [],
            structured=StructuredOutputRequest(schema=_SCHEMA),
            _validate=lambda *a, **k: None,
        )


def test_a_secret_shaped_dialect_is_still_refused():
    """The headline protection, re-asserted after the identity change."""
    with pytest.raises(ValueError):
        OpenAICompatBackend(model="m", client=SimpleNamespace(), dialect=_SECRET)


def test_rebinding_a_mirror_still_changes_nothing(monkeypatch):
    monkeypatch.setattr(sr, "is_supported_dialect", lambda v: True)
    monkeypatch.setattr(bk, "is_supported_dialect", lambda v: True)
    monkeypatch.setattr(sr, "STRUCTURED_WIRE_NAME", _SECRET)
    with pytest.raises(ValueError):
        OpenAICompatBackend(model="m", client=SimpleNamespace(), dialect=_SECRET)
    plan = sr.plan_structured_request(
        "vllm", StructuredOutputRequest(schema=_SCHEMA)
    )
    assert plan.response_format["json_schema"]["name"] == "structured_output"
