"""Tests for scripts/open_model/evaluation.py, structured.py, redaction.py.

This file carries the OMI-V1 synthetic acceptance cases. Every one of them
runs against in-process doubles: no model is downloaded, no runtime is
started, no endpoint is contacted, and nothing here is a performance result.

Acceptance cases:
  1. lightweight local routing        - the lighter local double wins
  2. capability mismatch              - a declared-unsupported capability blocks
  3. unavailable runtime              - both senses: runtime not permitted for
                                        the task, and runtime not running
  4. malformed structured output      - every malformed shape yields a code
  5. escalation                       - explicit reasons, never a degraded pick
  6. every backend unavailable        - the fixed no-eligible-backend outcome
  7. secret and prompt redaction      - notes scrubbed; prompts structurally
                                        absent from every record
  8. deterministic repeated execution - identical records across runs

Also covers the hermetic guard itself: it blocks the network, restores the
originals even when the body raises, and a breach fails the run loudly rather
than becoming a recorded result.
"""

from __future__ import annotations

import dataclasses
import socket
import urllib.request

import pytest

from scripts.agent_backends.base import AgentBackend, AgentResponse, Message, TextBlock
from scripts.open_model.evaluation import (
    PROBE_MESSAGES,
    EvaluationCase,
    EvaluationRecord,
    HermeticViolation,
    hermetic_guard,
    register_stub,
    run_case,
    run_suite,
    scripted_stub,
    stub_capabilities,
)
from scripts.open_model.redaction import (
    REDACTED_EMAIL,
    REDACTED_PATH,
    REDACTED_SECRET,
    DiagnosticRecord,
    describe_size,
    redact,
)
from scripts.open_model.registry import BackendRegistry
from scripts.open_model.routing import NO_ELIGIBLE_BACKEND, TaskRequirements
from scripts.open_model.structured import (
    StructuredOutcome,
    validate_structured_output,
)


_WELL_FORMED = '{"summary": "ok", "confidence": 1}'


def _registry(*entries) -> BackendRegistry:
    registry = BackendRegistry(allowed_names=tuple(name for name, _, _ in entries))
    for name, capabilities, factory in entries:
        # register_stub supplies the locality attestation that a `local`
        # descriptor now requires at the registration site.
        register_stub(registry, name, capabilities, factory)
    return registry


# -- 1. lightweight local routing --------------------------------------------


def test_acceptance_lightweight_local_routing():
    registry = _registry(
        ("heavy", stub_capabilities("heavy", resource_class="heavy"),
         scripted_stub([_WELL_FORMED])),
        ("light", stub_capabilities("light", resource_class="light"),
         scripted_stub([_WELL_FORMED])),
    )
    case = EvaluationCase(
        case_id="lightweight-local",
        requirements=TaskRequirements(
            needs_structured_output=True, needs_tool_calling=True
        ),
        expected_backend="light",
        required_keys=("summary", "confidence"),
    )
    record = run_case(registry, case)
    assert record.outcome == "selected"
    assert record.selected == "light"
    assert record.structured_failure == ""
    assert record.passed is True


# -- 2. capability mismatch --------------------------------------------------


def test_acceptance_capability_mismatch_blocks_rather_than_degrades():
    registry = _registry(
        (
            "text-only",
            stub_capabilities("text-only", structured_output="unsupported"),
            scripted_stub([_WELL_FORMED]),
        ),
    )
    case = EvaluationCase(
        case_id="capability-mismatch",
        requirements=TaskRequirements(needs_structured_output=True),
        expected_outcome=NO_ELIGIBLE_BACKEND,
    )
    record = run_case(registry, case)
    assert record.outcome == NO_ELIGIBLE_BACKEND
    assert record.selected == ""
    assert record.escalation == ("structured-output-unsupported",)
    assert record.passed is True


def test_acceptance_an_unverified_capability_is_not_a_yes():
    registry = _registry(
        (
            "unverified",
            stub_capabilities("unverified", tool_calling="unknown"),
            scripted_stub([_WELL_FORMED]),
        ),
    )
    record = run_case(
        registry,
        EvaluationCase(
            case_id="capability-unknown",
            requirements=TaskRequirements(needs_tool_calling=True),
            expected_outcome=NO_ELIGIBLE_BACKEND,
        ),
    )
    assert record.escalation == ("tool-calling-unknown",)


# -- 3. unavailable runtime --------------------------------------------------


def test_acceptance_runtime_not_permitted_for_the_task():
    registry = _registry(
        ("stub", stub_capabilities("stub"), scripted_stub([_WELL_FORMED])),
    )
    record = run_case(
        registry,
        EvaluationCase(
            case_id="runtime-not-allowed",
            requirements=TaskRequirements(allowed_runtimes=("ollama",)),
            expected_outcome=NO_ELIGIBLE_BACKEND,
        ),
    )
    # A plural compatibility list alone cannot satisfy a narrowed runtime
    # requirement; the bound runtime is what is judged.
    assert "runtime-not-allowed" in record.escalation
    assert "bound-runtime-not-allowed" in record.escalation
    assert record.passed is True


def test_acceptance_runtime_not_running():
    registry = _registry(
        (
            "stopped",
            stub_capabilities("stopped", availability="absent"),
            scripted_stub([_WELL_FORMED]),
        ),
    )
    record = run_case(
        registry,
        EvaluationCase(
            case_id="runtime-absent",
            requirements=TaskRequirements(),
            expected_outcome=NO_ELIGIBLE_BACKEND,
        ),
    )
    assert record.escalation == ("backend-unavailable",)
    assert record.passed is True


# -- 4. malformed structured output ------------------------------------------


@pytest.mark.parametrize(
    "payload,failure",
    [
        ("", "invalid-json"),
        ("not json at all", "invalid-json"),
        ('{"unclosed": ', "invalid-json"),
        ("[1, 2, 3]", "not-json-object"),
        ('"a bare string"', "not-json-object"),
        ("42", "not-json-object"),
        ("null", "not-json-object"),
        ('{"a": NaN}', "non-finite-number"),
        ('{"a": Infinity}', "non-finite-number"),
        ('{"ok": false, "ok": true}', "duplicate-key"),
    ],
)
def test_malformed_structured_output_yields_a_stable_code(payload, failure):
    outcome = validate_structured_output(payload)
    assert outcome.ok is False
    assert outcome.failure == failure
    assert outcome.value is None


def test_validation_never_raises_for_any_input_type():
    for payload in (None, 7, b"{}", [], {}, object(), 3.5, True):
        outcome = validate_structured_output(payload)
        assert outcome.ok is False
        assert outcome.failure == "payload-not-exact-str"


def test_an_oversized_payload_is_refused_before_parsing():
    outcome = validate_structured_output("{}" + " " * 10, max_chars=4)
    assert outcome.failure == "payload-too-large"


def test_deeply_nested_json_does_not_escape_as_an_exception():
    outcome = validate_structured_output("[" * 5000 + "]" * 5000)
    assert outcome.ok is False
    assert outcome.failure in ("invalid-json", "not-json-object")


def test_a_failure_never_carries_payload_content():
    secret_payload = '{"api_key": "sk-do-not-leak-me-abcdefgh", '
    outcome = validate_structured_output(secret_payload)
    assert outcome.failure == "invalid-json"
    rendered = repr(outcome)
    assert "sk-do-not-leak-me" not in rendered
    assert "api_key" not in rendered


def test_missing_required_keys_are_reported_as_indices_never_as_text():
    outcome = validate_structured_output(
        '{"summary": "ok"}', required_keys=("summary", "confidence")
    )
    assert outcome.failure == "missing-required-key"
    assert outcome.missing_key_indices == (1,)
    assert "confidence" not in repr(outcome)


def test_a_well_formed_payload_is_accepted_and_read_only():
    outcome = validate_structured_output(_WELL_FORMED, required_keys=("summary",))
    assert outcome.ok is True
    assert outcome.value["summary"] == "ok"
    with pytest.raises(TypeError):
        outcome.value["summary"] = "tampered"  # type: ignore[index]


def test_outcome_shape_invariants_are_enforced():
    with pytest.raises(ValueError):
        StructuredOutcome(ok=True, failure="invalid-json")
    with pytest.raises(ValueError):
        StructuredOutcome(ok=False)
    with pytest.raises(ValueError):
        StructuredOutcome(ok=False, failure="invalid-json", value={"a": 1})


def test_acceptance_malformed_output_from_a_routed_backend_is_recorded_not_raised():
    registry = _registry(
        ("chatty", stub_capabilities("chatty"), scripted_stub(["Sure! Here you go:"])),
    )
    record = run_case(
        registry,
        EvaluationCase(
            case_id="malformed-structured-output",
            requirements=TaskRequirements(needs_structured_output=True),
            expected_structured_failure="invalid-json",
        ),
    )
    assert record.outcome == "selected"
    assert record.structured_failure == "invalid-json"
    assert record.passed is True


# -- 5. escalation -----------------------------------------------------------


def test_acceptance_escalation_names_every_distinct_reason():
    registry = _registry(
        (
            "absent",
            stub_capabilities("absent", availability="absent"),
            scripted_stub([_WELL_FORMED]),
        ),
        (
            "remote",
            stub_capabilities("remote", locality="remote"),
            scripted_stub([_WELL_FORMED]),
        ),
    )
    record = run_case(
        registry,
        EvaluationCase(
            case_id="escalation",
            requirements=TaskRequirements(),
            expected_outcome=NO_ELIGIBLE_BACKEND,
        ),
    )
    assert record.outcome == NO_ELIGIBLE_BACKEND
    assert set(record.escalation) == {"backend-unavailable", "locality-not-local"}
    assert record.passed is True


# -- 6. every backend unavailable --------------------------------------------


def test_acceptance_every_backend_unavailable():
    registry = _registry(
        *(
            (
                f"stub-{index}",
                stub_capabilities(f"stub-{index}", availability="absent"),
                scripted_stub([_WELL_FORMED]),
            )
            for index in range(3)
        )
    )
    record = run_case(
        registry,
        EvaluationCase(
            case_id="all-unavailable",
            requirements=TaskRequirements(),
            expected_outcome=NO_ELIGIBLE_BACKEND,
        ),
    )
    assert record.outcome == NO_ELIGIBLE_BACKEND
    assert record.selected == ""
    assert record.escalation == ("backend-unavailable",)


def test_acceptance_no_backend_registered_at_all():
    record = run_case(
        BackendRegistry(allowed_names=()),
        EvaluationCase(
            case_id="nothing-registered",
            requirements=TaskRequirements(),
            expected_outcome=NO_ELIGIBLE_BACKEND,
        ),
    )
    assert record.escalation == ("no-backend-registered",)
    assert record.passed is True


# -- 7. secret and prompt redaction ------------------------------------------


def test_acceptance_secrets_paths_and_emails_are_scrubbed_from_a_note():
    windows_path = "C:" + chr(92) + "Users" + chr(92) + "operator" + chr(92) + "run.log"
    note = (
        "failed with sk-ABCDEFGH12345678 and ANTHROPIC_API_KEY=zzzzzzzzzzzz "
        f"while reading {windows_path}; contact operator@example.com; "
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9"
    )
    scrubbed = redact(note)
    assert "sk-ABCDEFGH12345678" not in scrubbed
    assert "zzzzzzzzzzzz" not in scrubbed
    assert "operator@example.com" not in scrubbed
    assert "eyJhbGciOiJIUzI1NiJ9" not in scrubbed
    assert chr(92) + "Users" + chr(92) not in scrubbed
    assert REDACTED_SECRET in scrubbed
    assert REDACTED_PATH in scrubbed
    assert REDACTED_EMAIL in scrubbed


def test_a_diagnostic_note_is_redacted_at_construction():
    record = DiagnosticRecord(
        event="route-refused",
        backend="light",
        reasons=("licence-unknown",),
        note="token=super-secret-value-12345",
    )
    assert "super-secret-value" not in record.note
    assert REDACTED_SECRET in record.note


def test_redaction_truncates_before_matching_so_no_partial_secret_survives():
    note = "padding " * 100 + "sk-ABCDEFGHIJKLMNOP"
    scrubbed = redact(note, max_chars=64)
    assert "sk-" not in scrubbed
    assert len(scrubbed) <= 64


def test_redact_refuses_non_exact_strings_without_conversion():
    class _Hostile:
        def __str__(self):  # pragma: no cover - invocation is the failure
            raise RuntimeError("__str__ invoked")

    assert redact(_Hostile()) == ""
    assert redact(None) == ""
    assert redact(b"sk-bytes-secret") == ""


def test_describe_size_reports_a_size_and_never_content():
    assert describe_size("hello") == "chars=5"
    assert describe_size(None) == "chars=unknown"
    assert "hello" not in describe_size("hello")


def test_no_evaluation_record_field_can_hold_a_prompt():
    names = {field.name for field in dataclasses.fields(EvaluationRecord)}
    assert names == {
        "case_id",
        "outcome",
        "selected",
        "escalation",
        "construction_refused",
        "structured_failure",
        "missing_key_indices",
        "response_size",
        "passed",
    }
    forbidden = {"prompt", "messages", "system", "content", "response", "text"}
    assert not names & forbidden


def test_no_evaluation_case_field_can_hold_a_prompt():
    names = {field.name for field in dataclasses.fields(EvaluationCase)}
    forbidden = {"prompt", "messages", "system", "content", "text"}
    assert not names & forbidden


def test_records_retain_neither_the_probe_text_nor_the_model_response():
    marker = "distinctive-model-answer-marker"
    registry = _registry(
        ("stub", stub_capabilities("stub"), scripted_stub(['{"a": "' + marker + '"}'])),
    )
    records = run_suite(
        registry,
        (
            EvaluationCase(
                case_id="no-content-retention", requirements=TaskRequirements()
            ),
        ),
    )
    rendered = repr(records)
    assert marker not in rendered
    probe_text = PROBE_MESSAGES[0].content
    assert probe_text not in rendered
    assert records[0].response_size.startswith("chars=")


# -- 8. deterministic repeated execution -------------------------------------


def _acceptance_suite():
    registry = _registry(
        ("heavy", stub_capabilities("heavy", resource_class="heavy"),
         scripted_stub([_WELL_FORMED])),
        ("light", stub_capabilities("light", resource_class="light"),
         scripted_stub([_WELL_FORMED])),
        ("absent", stub_capabilities("absent", availability="absent"),
         scripted_stub([_WELL_FORMED])),
    )
    cases = (
        EvaluationCase(
            case_id="route",
            requirements=TaskRequirements(),
            expected_backend="light",
            required_keys=("summary",),
        ),
        EvaluationCase(
            case_id="mismatch",
            requirements=TaskRequirements(allowed_runtimes=("vllm",)),
            expected_outcome=NO_ELIGIBLE_BACKEND,
        ),
    )
    return registry, cases


def test_acceptance_repeated_execution_is_deterministic():
    registry, cases = _acceptance_suite()
    first = run_suite(registry, cases)
    second = run_suite(registry, cases)
    third = run_suite(registry, cases)
    assert first == second == third
    assert all(record.passed for record in first)


def test_records_contain_no_clock_or_duration_field():
    names = {field.name for field in dataclasses.fields(EvaluationRecord)}
    forbidden = {"timestamp", "started_at", "duration", "elapsed", "seconds", "host"}
    assert not names & forbidden


# -- the hermetic guard itself -----------------------------------------------


def test_hermetic_guard_blocks_the_network_and_restores_afterwards():
    original_socket = socket.socket
    original_urlopen = urllib.request.urlopen
    with hermetic_guard():
        with pytest.raises(HermeticViolation):
            socket.socket()
        with pytest.raises(HermeticViolation):
            socket.create_connection(("127.0.0.1", 1))
        with pytest.raises(HermeticViolation):
            socket.getaddrinfo("localhost", 80)
        with pytest.raises(HermeticViolation):
            urllib.request.urlopen("https://example.invalid")
    assert socket.socket is original_socket
    assert urllib.request.urlopen is original_urlopen


def test_hermetic_guard_restores_even_when_the_body_raises():
    original_socket = socket.socket
    with pytest.raises(RuntimeError):
        with hermetic_guard():
            raise RuntimeError("boom")
    assert socket.socket is original_socket


class _NetworkingDouble(AgentBackend):
    """A double that misbehaves by reaching for the network."""

    name = "networking-double"

    def complete(
        self,
        messages: list[Message],
        tools: list,
        *,
        system=None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> AgentResponse:
        socket.socket()
        return AgentResponse.from_content([TextBlock(text="{}")])


def test_a_breach_fails_the_run_loudly_instead_of_becoming_a_record():
    registry = _registry(
        ("networking", stub_capabilities("networking"), _NetworkingDouble),
    )
    with pytest.raises(HermeticViolation):
        run_suite(
            registry,
            (EvaluationCase(case_id="breach", requirements=TaskRequirements()),),
        )


def test_the_stub_runtime_never_borrows_a_real_runtime_name():
    capabilities = stub_capabilities("double")
    assert capabilities.runtimes == ("in-process-stub",)
    for real in ("llama-cpp", "ollama", "vllm", "sglang", "tensorrt-llm"):
        assert real not in capabilities.runtimes
