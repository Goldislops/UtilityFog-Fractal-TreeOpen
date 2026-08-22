"""Tests for scripts/open_model/registry.py and routing.py (OMI-V1).

Covers:
  - Explicit allowlisting: a name outside the allowlist cannot register, and
    no registry method accepts a URL, command, or credential.
  - Registration refusals carry stable codes and never echo the input.
  - Two independent availability gates: routing refuses an unobserved
    backend, and ``create()`` refuses it again.
  - TaskRequirements is structurally incapable of carrying prompt text - its
    field set is asserted exactly, so a later edit cannot add one silently.
  - Requirement normalization is conservative: a malformed demand tightens
    routing, and "unknown" can never be allow-listed for licence or runtime.
  - Eligibility produces one stable escalation reason per blocking condition,
    and collects all of them rather than short-circuiting.
  - The fixed no-eligible-backend outcome: empty registry, all-unavailable
    registry, capability mismatch.
  - No silent fallback to a remote or cloud backend under require_local.
  - Deterministic routing: repeated calls are byte-identical, selection
    prefers the lighter declared footprint, ties break on model id then
    registration order.
  - Every catalogue entry is inert - unroutable under every requirement
    combination, including the most permissive one expressible.
"""

from __future__ import annotations

import dataclasses
import itertools

import pytest

from scripts.agent_backends.base import AgentResponse, TextBlock
from scripts.agent_backends.mock import MockBackend
from scripts.open_model.capabilities import ModelCapabilities
from scripts.open_model.catalogue import CATALOGUE
from scripts.open_model.registry import (
    BackendRegistry,
    BackendUnavailable,
    RegistrationRefused,
)
from scripts.open_model.routing import (
    NO_ELIGIBLE_BACKEND,
    RoutingDecision,
    TaskRequirements,
    evaluate,
    route,
)


def _usable(model_id: str, **overrides) -> ModelCapabilities:
    """A descriptor that satisfies the default requirements."""
    base = dict(
        model_id=model_id,
        locality="local",
        availability="present",
        resource_class="light",
        structured_output="supported",
        tool_calling="supported",
        max_context_tokens=8192,
        runtimes=("in-process-stub",),
        licence_class="osi-open-source",
    )
    base.update(overrides)
    return ModelCapabilities(**base)  # type: ignore[arg-type]


def _factory():
    return MockBackend([AgentResponse.from_content([TextBlock(text="{}")])])


def _registry(*entries: tuple[str, ModelCapabilities]) -> BackendRegistry:
    registry = BackendRegistry(allowed_names=tuple(name for name, _ in entries))
    for name, capabilities in entries:
        registry.register(name, capabilities, _factory)
    return registry


# -- allowlisting ------------------------------------------------------------


def test_a_name_outside_the_allowlist_cannot_register():
    registry = BackendRegistry(allowed_names=("approved",))
    with pytest.raises(RegistrationRefused) as excinfo:
        registry.register("smuggled", _usable("m"), _factory)
    assert excinfo.value.reason == "name-not-allowlisted"
    assert len(registry) == 0


def test_an_empty_allowlist_admits_nothing():
    registry = BackendRegistry(allowed_names=())
    assert registry.allowed_names == ()
    with pytest.raises(RegistrationRefused):
        registry.register("anything", _usable("m"), _factory)


def test_registration_is_never_silently_replaced():
    registry = _registry(("one", _usable("m")))
    with pytest.raises(RegistrationRefused) as excinfo:
        registry.register("one", _usable("m2"), _factory)
    assert excinfo.value.reason == "name-already-registered"
    assert registry.capabilities_for("one").model_id == "m"


@pytest.mark.parametrize(
    "name,reason",
    [
        ("", "name-not-exact-str"),
        (7, "name-not-exact-str"),
        (None, "name-not-exact-str"),
        ("x" * 200, "name-not-exact-str"),
    ],
)
def test_malformed_names_are_refused_with_a_stable_code(name, reason):
    registry = BackendRegistry(allowed_names=("ok",))
    with pytest.raises(RegistrationRefused) as excinfo:
        registry.register(name, _usable("m"), _factory)
    assert excinfo.value.reason == reason


def test_capabilities_must_be_exactly_the_descriptor_type():
    class Sneaky(ModelCapabilities):
        pass

    registry = BackendRegistry(allowed_names=("ok",))
    with pytest.raises(RegistrationRefused) as excinfo:
        registry.register("ok", Sneaky(model_id="m"), _factory)
    assert excinfo.value.reason == "capabilities-not-exact-type"


def test_a_descriptor_that_identifies_nothing_is_refused():
    registry = BackendRegistry(allowed_names=("ok",))
    with pytest.raises(RegistrationRefused) as excinfo:
        registry.register("ok", ModelCapabilities(model_id=""), _factory)
    assert excinfo.value.reason == "capabilities-missing-model-id"


def test_a_non_callable_factory_is_refused():
    registry = BackendRegistry(allowed_names=("ok",))
    with pytest.raises(RegistrationRefused) as excinfo:
        registry.register("ok", _usable("m"), "ollama serve")
    assert excinfo.value.reason == "factory-not-callable"


def test_registry_exposes_no_endpoint_or_command_parameter():
    # The structural half of "no arbitrary executable or endpoint injection":
    # there is no parameter through which one could be supplied.
    register_params = set(
        BackendRegistry.register.__code__.co_varnames[
            : BackendRegistry.register.__code__.co_argcount
        ]
    )
    assert register_params == {"self", "name", "capabilities", "factory"}
    forbidden = {"url", "base_url", "host", "port", "command", "argv", "api_key"}
    for member in dir(BackendRegistry):
        attribute = getattr(BackendRegistry, member, None)
        code = getattr(attribute, "__code__", None)
        if code is None:
            continue
        assert not forbidden & set(code.co_varnames[: code.co_argcount])


# -- the second availability gate --------------------------------------------


def test_create_refuses_a_backend_that_was_never_observed():
    registry = _registry(("unseen", _usable("m", availability="unknown")))
    with pytest.raises(BackendUnavailable) as excinfo:
        registry.create("unseen")
    assert excinfo.value.reason == "availability-not-present"


def test_create_refuses_an_absent_backend():
    registry = _registry(("gone", _usable("m", availability="absent")))
    with pytest.raises(BackendUnavailable) as excinfo:
        registry.create("gone")
    assert excinfo.value.reason == "availability-not-present"


def test_create_refuses_a_factory_that_returns_the_wrong_type():
    registry = BackendRegistry(allowed_names=("bad",))
    registry.register("bad", _usable("m"), lambda: "not a backend")
    with pytest.raises(BackendUnavailable) as excinfo:
        registry.create("bad")
    assert excinfo.value.reason == "factory-returned-wrong-type"


def test_create_of_an_unregistered_name_is_refused():
    registry = BackendRegistry(allowed_names=())
    with pytest.raises(BackendUnavailable) as excinfo:
        registry.create("nope")
    assert excinfo.value.reason == "name-not-registered"


# -- requirements carry no content -------------------------------------------


def test_task_requirements_has_no_field_that_could_hold_a_prompt():
    names = {field.name for field in dataclasses.fields(TaskRequirements)}
    assert names == {
        "require_local",
        "needs_structured_output",
        "needs_tool_calling",
        "min_context_tokens",
        "allowed_licence_classes",
        "allowed_runtimes",
    }
    for field in dataclasses.fields(TaskRequirements):
        value = getattr(TaskRequirements(), field.name)
        assert type(value) in (bool, int, tuple)


def test_requirement_defaults_are_strict():
    requirements = TaskRequirements()
    assert requirements.require_local is True
    assert requirements.allowed_licence_classes == ("osi-open-source",)


def test_a_malformed_demand_tightens_rather_than_loosens():
    requirements = TaskRequirements(
        require_local="yes",  # type: ignore[arg-type]
        needs_structured_output="maybe",  # type: ignore[arg-type]
        needs_tool_calling=None,  # type: ignore[arg-type]
    )
    assert requirements.require_local is True
    assert requirements.needs_structured_output is True
    assert requirements.needs_tool_calling is True


def test_unknown_can_never_be_allow_listed():
    requirements = TaskRequirements(
        allowed_licence_classes=("unknown", "osi-open-source"),  # type: ignore[arg-type]
        allowed_runtimes=("unknown", "ollama"),  # type: ignore[arg-type]
    )
    assert requirements.allowed_licence_classes == ("osi-open-source",)
    assert requirements.allowed_runtimes == ("ollama",)


def test_an_explicitly_empty_licence_allowlist_blocks_everything():
    requirements = TaskRequirements(allowed_licence_classes=())
    assert requirements.allowed_licence_classes == ()
    assert "licence-not-allowed" in evaluate(_usable("m"), requirements)


# -- eligibility -------------------------------------------------------------


def test_a_fully_satisfying_candidate_has_no_blocking_reasons():
    assert evaluate(_usable("m"), TaskRequirements()) == ()


@pytest.mark.parametrize(
    "overrides,requirements,expected",
    [
        ({"availability": "absent"}, TaskRequirements(), "backend-unavailable"),
        ({"availability": "unknown"}, TaskRequirements(), "availability-unknown"),
        ({"locality": "remote"}, TaskRequirements(), "locality-not-local"),
        ({"locality": "unknown"}, TaskRequirements(), "locality-unknown"),
        (
            {"structured_output": "unsupported"},
            TaskRequirements(needs_structured_output=True),
            "structured-output-unsupported",
        ),
        (
            {"structured_output": "unknown"},
            TaskRequirements(needs_structured_output=True),
            "structured-output-unknown",
        ),
        (
            {"tool_calling": "unsupported"},
            TaskRequirements(needs_tool_calling=True),
            "tool-calling-unsupported",
        ),
        (
            {"tool_calling": "unknown"},
            TaskRequirements(needs_tool_calling=True),
            "tool-calling-unknown",
        ),
        ({"max_context_tokens": 0}, TaskRequirements(), "context-unknown"),
        (
            {"max_context_tokens": 4096},
            TaskRequirements(min_context_tokens=8192),
            "context-below-minimum",
        ),
        ({"licence_class": "unknown"}, TaskRequirements(), "licence-unknown"),
        (
            {"licence_class": "open-weight-restricted"},
            TaskRequirements(),
            "licence-not-allowed",
        ),
        ({"runtimes": ()}, TaskRequirements(), "runtime-unknown"),
        (
            {"runtimes": ("vllm",)},
            TaskRequirements(allowed_runtimes=("ollama",)),
            "runtime-not-allowed",
        ),
        ({"model_id": ""}, TaskRequirements(), "model-id-missing"),
    ],
)
def test_each_blocking_condition_has_its_own_escalation_reason(
    overrides, requirements, expected
):
    # Merged as keywords so a case may override model_id itself.
    assert expected in evaluate(_usable(**{"model_id": "m", **overrides}), requirements)


def test_all_blocking_reasons_are_collected_not_short_circuited():
    reasons = evaluate(
        ModelCapabilities(model_id="m"),
        TaskRequirements(needs_structured_output=True, needs_tool_calling=True),
    )
    assert "availability-unknown" in reasons
    assert "locality-unknown" in reasons
    assert "structured-output-unknown" in reasons
    assert "tool-calling-unknown" in reasons
    assert "context-unknown" in reasons
    assert "licence-unknown" in reasons
    assert "runtime-unknown" in reasons


def test_an_undeclared_context_blocks_even_when_no_minimum_is_asked_for():
    requirements = TaskRequirements(min_context_tokens=0)
    assert "context-unknown" in evaluate(
        _usable("m", max_context_tokens=0), requirements
    )


def test_a_task_may_decline_to_constrain_the_runtime():
    requirements = TaskRequirements(allowed_runtimes=())
    assert evaluate(_usable("m", runtimes=("vllm",)), requirements) == ()


# -- the fixed no-eligible-backend outcome -----------------------------------


def test_an_empty_registry_escalates_with_no_backend_registered():
    decision = route(BackendRegistry(allowed_names=()), TaskRequirements())
    assert decision.outcome == NO_ELIGIBLE_BACKEND
    assert decision.selected is None
    assert decision.has_backend is False
    assert decision.escalation == ("no-backend-registered",)


def test_every_backend_unavailable_escalates_rather_than_degrading():
    registry = _registry(
        ("a", _usable("a", availability="absent")),
        ("b", _usable("b", availability="absent")),
    )
    decision = route(registry, TaskRequirements())
    assert decision.outcome == NO_ELIGIBLE_BACKEND
    assert decision.selected is None
    assert decision.escalation == ("backend-unavailable",)
    assert [v.eligible for v in decision.verdicts] == [False, False]


def test_a_decision_cannot_claim_both_no_backend_and_a_selection():
    with pytest.raises(ValueError):
        RoutingDecision(
            outcome=NO_ELIGIBLE_BACKEND,
            selected="sneaky",
            verdicts=(),
            escalation=(),
        )


def test_a_selected_decision_must_name_a_backend():
    with pytest.raises(ValueError):
        RoutingDecision(
            outcome="selected", selected=None, verdicts=(), escalation=()
        )


def test_escalation_reasons_are_deduplicated_in_first_seen_order():
    registry = _registry(
        ("a", _usable("a", availability="absent")),
        ("b", _usable("b", availability="absent", licence_class="unknown")),
    )
    decision = route(registry, TaskRequirements())
    assert decision.escalation == ("backend-unavailable", "licence-unknown")


# -- no silent fallback to the cloud -----------------------------------------


def test_a_local_only_task_is_never_served_by_a_remote_backend():
    registry = _registry(
        ("cloud-a", _usable("cloud-a", locality="remote")),
        ("cloud-b", _usable("cloud-b", locality="remote")),
    )
    decision = route(registry, TaskRequirements(require_local=True))
    assert decision.outcome == NO_ELIGIBLE_BACKEND
    assert decision.selected is None
    assert "locality-not-local" in decision.escalation


def test_a_remote_backend_is_reachable_only_when_explicitly_asked_for():
    registry = _registry(("cloud", _usable("cloud", locality="remote")))
    assert route(registry, TaskRequirements()).outcome == NO_ELIGIBLE_BACKEND
    permitted = route(registry, TaskRequirements(require_local=False))
    assert permitted.outcome == "selected"
    assert permitted.selected == "cloud"


def test_a_local_task_prefers_local_even_when_a_remote_one_is_lighter():
    registry = _registry(
        ("cloud", _usable("cloud", locality="remote", resource_class="light")),
        ("local", _usable("local", locality="local", resource_class="heavy")),
    )
    decision = route(registry, TaskRequirements(require_local=True))
    assert decision.selected == "local"


# -- determinism -------------------------------------------------------------


def test_routing_is_deterministic_across_repeated_calls():
    registry = _registry(
        ("a", _usable("a", resource_class="heavy")),
        ("b", _usable("b", resource_class="light")),
        ("c", _usable("c", availability="absent")),
    )
    requirements = TaskRequirements()
    decisions = [route(registry, requirements) for _ in range(8)]
    assert all(decision == decisions[0] for decision in decisions)


def test_the_lighter_declared_footprint_wins():
    registry = _registry(
        ("heavy", _usable("heavy", resource_class="heavy")),
        ("light", _usable("light", resource_class="light")),
        ("medium", _usable("medium", resource_class="medium")),
    )
    assert route(registry, TaskRequirements()).selected == "light"


def test_an_undeclared_footprint_never_beats_a_declared_one():
    registry = _registry(
        ("mystery", _usable("mystery", resource_class="unknown")),
        ("heavy", _usable("heavy", resource_class="heavy")),
    )
    assert route(registry, TaskRequirements()).selected == "heavy"


def test_ties_break_on_model_id_then_registration_order():
    registry = _registry(
        ("second", _usable("bbb")),
        ("first", _usable("aaa")),
    )
    assert route(registry, TaskRequirements()).selected == "first"


def test_registration_order_is_preserved_in_the_verdict_list():
    registry = _registry(
        ("z", _usable("z")),
        ("a", _usable("a")),
        ("m", _usable("m")),
    )
    decision = route(registry, TaskRequirements())
    assert [verdict.name for verdict in decision.verdicts] == ["z", "a", "m"]


# -- the catalogue is inert --------------------------------------------------


def test_no_catalogue_entry_asserts_availability_or_locality():
    for entry in CATALOGUE:
        assert entry.availability == "unknown"
        assert entry.locality == "unknown"


def test_no_catalogue_entry_can_route_under_any_requirement_combination():
    licence_sets = [
        (),
        ("osi-open-source",),
        (
            "osi-open-source",
            "open-weight-restricted",
            "source-available",
            "proprietary-service",
        ),
    ]
    runtime_sets = [
        (),
        ("llama-cpp", "ollama", "vllm", "sglang", "tensorrt-llm", "in-process-stub"),
    ]
    combinations = itertools.product(
        [True, False], [True, False], [True, False], [0], licence_sets, runtime_sets
    )
    for local, structured, tools, context, licences, runtimes in combinations:
        requirements = TaskRequirements(
            require_local=local,
            needs_structured_output=structured,
            needs_tool_calling=tools,
            min_context_tokens=context,
            allowed_licence_classes=licences,  # type: ignore[arg-type]
            allowed_runtimes=runtimes,  # type: ignore[arg-type]
        )
        for entry in CATALOGUE:
            assert evaluate(entry, requirements), (
                f"catalogue entry {entry.model_id} became routable"
            )


def test_catalogue_entries_carry_no_endpoint_or_credential_shaped_field():
    field_names = {field.name for field in dataclasses.fields(ModelCapabilities)}
    forbidden = {"base_url", "url", "host", "port", "command", "argv", "api_key"}
    assert not field_names & forbidden


def test_every_catalogue_entry_is_dated_and_sourced():
    for entry in CATALOGUE:
        assert entry.observed_on == "2026-08-22"
        assert entry.provenance_url.startswith("https://")
