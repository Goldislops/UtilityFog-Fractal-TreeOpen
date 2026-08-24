"""OMI-V3A - the hermetic rehearsal: one observation, executed, end to end.

Every execution in this file runs inside OMI-V1's ``hermetic_guard``, which
replaces ``socket.socket``, ``socket.create_connection``,
``socket.getaddrinfo`` and ``urllib.request.urlopen`` with raisers. No real
backend is constructed, no endpoint is contacted, no model is loaded, no
runtime is started, and nothing is registered. The only thing that ever
"answers" is an in-process double.

The guard is not decoration here. ``test_a_double_that_reaches_the_network_
fails_the_rehearsal`` proves that a double which tries to open a socket raises
``HermeticViolation`` **out of** ``execute_observation`` rather than being
folded into a tidy receipt - which is why the executor deliberately does not
catch exceptions raised by its injected exchange.

Everything here runs identically under normal Python, ``-O`` and ``-OO``.

**Same-author evidence: written by the agent that wrote the code under test.**
It demonstrates internal consistency, not independent acceptance.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import pickle
import socket
import textwrap
import urllib.request

import pytest

from scripts.agent_backends.base import AgentResponse, Message, TextBlock
from scripts.agent_backends.openai_compat_backend import StructuredCompletion
from scripts.agent_backends import structured_request as sr
from scripts.open_model import observation as ob
from scripts.open_model import observation_receipt as rc
from scripts.open_model import structured_exchange as sx
from scripts.open_model.evaluation import HermeticViolation, hermetic_guard
from scripts.open_model.structured_exchange import StructuredExchange


ENDPOINT = "http://127.0.0.1:11434/v1"
SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}}
FIXED_TASK_ID = "e0e9c7a5-b2bf-4f07-bf39-4ceb6cf63052"


# -- in-process doubles -------------------------------------------------------


class FakeBackend:
    """A double exposing exactly OMI-V2's structured method and nothing else.

    Records every argument it was handed, so the controls can assert what
    OMI-V3A sends rather than assuming it.
    """

    def __init__(self, payload, dialect="ollama", ok=True, refusal=None):
        self.payload = payload
        self.dialect = dialect
        self.ok = ok
        self.refusal = refusal
        self.calls = 0
        self.seen = []

    def complete_structured(
        self, messages, tools, *, structured, system, max_tokens, temperature
    ):
        self.calls += 1
        self.seen.append(
            {
                "messages": list(messages),
                "tools": list(tools),
                "structured": structured,
                "system": system,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        if not self.ok:
            return StructuredCompletion(
                ok=False, refusal=self.refusal, dialect=self.dialect
            )
        return StructuredCompletion(
            ok=True,
            response=AgentResponse.from_content([TextBlock(text=self.payload)]),
            dialect=self.dialect,
            response_format_sent=True,
        )


class NonStructuredBackend:
    """A backend predating OMI-V2. It has no ``complete_structured`` at all."""

    def complete(self, messages, tools, **kwargs):  # pragma: no cover
        raise AssertionError("OMI-V3A must never call complete()")


class NetworkReachingBackend:
    """A double that breaks the rule, so the guard can be seen to catch it."""

    def __init__(self):
        self.calls = 0

    def complete_structured(self, messages, tools, **kwargs):
        self.calls += 1
        socket.socket()  # blocked by hermetic_guard
        raise AssertionError("unreachable while the guard is active")


class UrlopenReachingBackend:
    """The same, through urllib rather than socket."""

    def complete_structured(self, messages, tools, **kwargs):
        urllib.request.urlopen("http://127.0.0.1:11434/v1")
        raise AssertionError("unreachable while the guard is active")


class CountingExchange:
    """An injected exchange that reports exactly how often it was invoked."""

    def __init__(self, result):
        self.result = result
        self.calls = 0
        self.envelopes = []

    def __call__(self, envelope):
        self.calls += 1
        self.envelopes.append(envelope)
        return self.result


def make_clock(readings):
    iterator = iter(readings)

    def clock():
        return next(iterator)

    return clock


def build_envelope(**overrides):
    kwargs = dict(
        task_id=FIXED_TASK_ID,
        authorizing_principal="kev",
        worker="observer-1",
        evidence=[ob.EvidenceItem(evidence_id="e1", content=b"the evidence")],
        dialect="ollama",
        schema=dict(SCHEMA),
        endpoint=ENDPOINT,
        reservation=ob.ResourceReservation(cpu_cores=2, memory_mib=4096),
        clock=make_clock([1000]),
        required_keys=("summary",),
        duration_ns=30000000000,
    )
    kwargs.update(overrides)
    result = ob.plan_observation(**kwargs)
    if not result.ok:
        raise AssertionError("the rehearsal envelope must plan: %s" % result.refusal)
    return result.envelope


def satisfied_for(envelope, satisfied=True, attestation="operator-asserted"):
    return ob.ReservationDecision(
        reservation_digest=envelope.reservation.digest,
        satisfied=satisfied,
        attestation=attestation,
    )


#: Distinct from ``None``, because ``None`` is itself one of the wrong-type
#: reservation decisions a control needs to pass through unchanged.
_DEFAULT = object()


def run(envelope, exchange, readings, decision=_DEFAULT):
    """Execute one observation inside the hermetic guard."""
    with hermetic_guard():
        return ob.execute_observation(
            envelope,
            exchange=exchange,
            clock=make_clock(readings),
            reservation_decision=(
                satisfied_for(envelope) if decision is _DEFAULT else decision
            ),
        )


def _code_only(source: str) -> str:
    """The executable text of ``source``, with docstrings and comments gone.

    A substring search over raw source cannot tell code from prose, and this
    package's prose necessarily discusses the very things its code must not do
    - "a deadline crossed **while** the exchange ran", "may not request more
    scope, **propose**, or apply". Parsing and re-rendering removes comments
    outright and drops every docstring, leaving only what runs.
    """
    tree = ast.parse(textwrap.dedent(source))
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def _called_names(module) -> set[str]:
    """Every function or method name the module's own code calls."""
    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def ok_exchange(value=None, dialect="ollama"):
    return CountingExchange(
        StructuredExchange(
            ok=True,
            value=dict(value if value is not None else {"summary": "seen"}),
            dialect=dialect,
            response_format_sent=True,
        )
    )


# ============================================================================
# non-vacuity: these controls really run, including under -O and -OO
# ============================================================================


def test_the_controls_in_this_file_are_not_silently_stripped():
    """Prove a false assertion here would still fail under ``-O`` and ``-OO``.

    Both flags discard ``assert`` statements, so a suite that passed under them
    could in principle be asserting nothing. pytest rewrites assertions in
    collected test modules into explicit raises first; this is the control that
    proves the rewriting happened rather than trusting that it did.
    """
    with pytest.raises(AssertionError):
        assert False, "if this does not raise, every control here is vacuous"


# ============================================================================
# the positive guard: one successful hermetic observation
# ============================================================================


def test_one_successful_hermetic_observation_through_the_real_adapter():
    envelope = build_envelope()
    backend = FakeBackend('{"summary": "the evidence describes a thing"}')
    result = run(envelope, ob.structured_exchange_adapter(backend), [1000, 1500])

    assert result.ok is True
    assert result.refusal is None
    assert backend.calls == 1

    receipt = result.receipt
    assert receipt.outcome == "observed"
    assert receipt.deadline_result == "within-deadline"
    assert receipt.reservation_result == "satisfied"
    assert receipt.request_outcome == "attempted"
    assert receipt.response_outcome == "ok"
    assert receipt.exchange_invocations == 1
    assert receipt.elapsed_ns == 500
    assert receipt.result_bytes > 0
    assert receipt.dialect == "ollama"
    assert receipt.schema_conformance == "unverified"
    assert receipt.task_id == FIXED_TASK_ID
    assert receipt.envelope_digest == envelope.envelope_digest
    assert receipt.evidence_ids == ("e1",)
    assert receipt.evidence_digests == (envelope.evidence[0].digest,)
    assert receipt.evidence_bytes == len(b"the evidence")
    assert receipt.required_key_count == 1
    assert receipt.missing_key_indices == ()

    assert dict(result.exchange.value) == {
        "summary": "the evidence describes a thing"
    }


def test_the_successful_observation_is_reproducible_from_the_same_inputs():
    first = run(
        build_envelope(),
        ob.structured_exchange_adapter(FakeBackend('{"summary": "x"}')),
        [1000, 1500],
    )
    second = run(
        build_envelope(),
        ob.structured_exchange_adapter(FakeBackend('{"summary": "x"}')),
        [1000, 1500],
    )
    assert rc.serialize_receipt(first.receipt) == rc.serialize_receipt(second.receipt)
    assert first.receipt == second.receipt


# ============================================================================
# what the adapter actually sends
# ============================================================================


def test_the_adapter_sends_no_tools_the_fixed_system_text_and_only_evidence():
    envelope = build_envelope(
        evidence=[
            ob.EvidenceItem(evidence_id="first", content="alpha é".encode("utf-8")),
            ob.EvidenceItem(evidence_id="second", content=b"beta"),
        ],
        max_output_tokens=777,
        max_result_bytes=4096,
    )
    backend = FakeBackend('{"summary": "x"}')
    result = run(envelope, ob.structured_exchange_adapter(backend), [1000, 1100])
    assert result.ok is True

    sent = backend.seen[0]
    assert sent["tools"] == []
    assert sent["system"] == ob.OBSERVER_SYSTEM_PROMPT
    assert sent["temperature"] == 0.0
    assert sent["max_tokens"] == 777
    assert sent["messages"] == [
        Message(role="user", content="alpha é"),
        Message(role="user", content="beta"),
    ]
    assert all(message.role == "user" for message in sent["messages"])
    assert type(sent["structured"]) is sr.StructuredOutputRequest


def test_the_adapter_sends_the_detached_snapshot_not_the_callers_document():
    document = {"type": "object", "properties": {"summary": {"type": "string"}}}
    envelope = build_envelope(schema=document)
    document["properties"]["summary"] = {"type": "number"}
    document["leaked"] = "sk-OMIV3ASECRET123456789"

    backend = FakeBackend('{"summary": "x"}')
    run(envelope, ob.structured_exchange_adapter(backend), [1000, 1100])
    sent = backend.seen[0]["structured"].schema
    assert sent == {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
    }
    assert "leaked" not in sent
    assert sent is not document


def test_the_observer_system_text_carries_no_caller_string_and_forbids_action():
    text = ob.OBSERVER_SYSTEM_PROMPT
    assert "observation-only" in text
    assert "no tools" in text.lower()
    assert "cannot propose" in text
    assert "additional scope" in text
    envelope = build_envelope(evidence=[ob.EvidenceItem(evidence_id="e", content=b"z")])
    backend = FakeBackend('{"summary": "x"}')
    run(envelope, ob.structured_exchange_adapter(backend), [1000, 1100])
    assert backend.seen[0]["system"] == text


def test_the_adapter_refuses_anything_that_is_not_an_envelope():
    exchange = ob.structured_exchange_adapter(FakeBackend('{"summary": "x"}'))
    for value in (None, "envelope", 5, object()):
        with pytest.raises(ValueError):
            exchange(value)


def test_a_backend_without_the_omi_v2_method_is_refused_not_crashed():
    envelope = build_envelope()
    result = run(
        envelope, ob.structured_exchange_adapter(NonStructuredBackend()), [1000, 1100]
    )
    assert result.ok is False
    assert result.refusal is None
    assert result.receipt.outcome == "unusable"
    assert result.receipt.response_outcome == "request-refused"
    assert result.receipt.request_refusal == "backend-not-structured-capable"
    assert result.receipt.request_refusal in sx.EXCHANGE_REFUSALS
    assert result.receipt.dialect is None
    assert result.receipt.exchange_invocations == 1


# ============================================================================
# hermeticity is enforced, not assumed
# ============================================================================


@pytest.mark.parametrize(
    "backend_type", [NetworkReachingBackend, UrlopenReachingBackend]
)
def test_a_double_that_reaches_the_network_fails_the_rehearsal(backend_type):
    """A breach must be loud, and must not be swallowed into a receipt."""
    envelope = build_envelope()
    with pytest.raises(HermeticViolation):
        run(envelope, ob.structured_exchange_adapter(backend_type()), [1000, 1100])


def test_the_guard_blocks_every_entry_point_it_claims_to():
    with hermetic_guard():
        for call in (
            lambda: socket.socket(),
            lambda: socket.create_connection(("127.0.0.1", 11434)),
            lambda: socket.getaddrinfo("127.0.0.1", 11434),
            lambda: urllib.request.urlopen("http://127.0.0.1:11434/v1"),
        ):
            with pytest.raises(HermeticViolation):
                call()


def test_the_guard_restores_the_real_entry_points_afterwards():
    original = (
        socket.socket,
        socket.create_connection,
        socket.getaddrinfo,
        urllib.request.urlopen,
    )
    with hermetic_guard():
        pass
    assert (
        socket.socket,
        socket.create_connection,
        socket.getaddrinfo,
        urllib.request.urlopen,
    ) == original


def test_an_exception_from_the_injected_exchange_propagates_rather_than_being_recorded():
    class Exploding:
        calls = 0

        def __call__(self, envelope):
            type(self).calls += 1
            raise RuntimeError("transport said no")

    envelope = build_envelope()
    exploding = Exploding()
    with pytest.raises(RuntimeError):
        run(envelope, exploding, [1000, 1100])
    assert Exploding.calls == 1


# ============================================================================
# the deadline
# ============================================================================


def test_a_deadline_already_exceeded_voids_the_observation_without_invoking_it():
    envelope = build_envelope(clock=make_clock([0]), duration_ns=100)
    exchange = ok_exchange()
    result = run(envelope, exchange, [500])

    assert exchange.calls == 0
    assert result.ok is False
    assert result.refusal is None
    assert result.exchange is None
    receipt = result.receipt
    assert receipt.outcome == "void"
    assert receipt.deadline_result == "exceeded-before-request"
    assert receipt.request_outcome == "not-attempted"
    assert receipt.reservation_result == "not-evaluated"
    assert receipt.exchange_invocations == 0
    assert receipt.elapsed_ns == 0
    assert receipt.result_bytes == 0


def test_the_deadline_instant_itself_counts_as_exceeded():
    envelope = build_envelope(clock=make_clock([0]), duration_ns=100)
    exchange = ok_exchange()
    at_deadline = run(envelope, exchange, [100])
    assert at_deadline.receipt.deadline_result == "exceeded-before-request"
    assert exchange.calls == 0

    just_inside = ok_exchange()
    result = run(envelope, just_inside, [99, 99])
    assert result.receipt.deadline_result == "within-deadline"
    assert just_inside.calls == 1


def test_a_deadline_crossed_during_the_exchange_voids_a_successful_answer():
    envelope = build_envelope(clock=make_clock([0]), duration_ns=1000)
    exchange = ok_exchange()
    result = run(envelope, exchange, [10, 5000])

    assert exchange.calls == 1
    assert result.ok is False
    assert result.refusal is None
    assert result.exchange is None, "a late answer must not be retained"
    receipt = result.receipt
    assert receipt.outcome == "void"
    assert receipt.deadline_result == "exceeded-during-request"
    assert receipt.request_outcome == "attempted"
    assert receipt.reservation_result == "satisfied"
    assert receipt.exchange_invocations == 1
    assert receipt.elapsed_ns == 4990
    assert receipt.result_bytes == 0
    assert receipt.response_outcome == "none"


def test_a_void_observation_is_never_retried_by_v3a():
    """One invocation at most, whichever way the deadline falls."""
    envelope = build_envelope(clock=make_clock([0]), duration_ns=1000)
    before = ok_exchange()
    run(envelope, before, [5000])
    assert before.calls == 0
    during = ok_exchange()
    run(envelope, during, [10, 5000])
    assert during.calls == 1


@pytest.mark.parametrize("reading", [None, "1000", 1000.0, True])
def test_an_unusable_first_clock_reading_refuses_without_invoking_the_exchange(reading):
    envelope = build_envelope()
    exchange = ok_exchange()
    result = run(envelope, exchange, [reading])
    assert exchange.calls == 0
    assert result.refusal == "clock-reading-not-exact-int"
    assert result.receipt.outcome == "refused"
    assert result.receipt.deadline_result == "not-evaluated"
    assert result.receipt.reservation_result == "not-evaluated"
    assert result.receipt.exchange_invocations == 0


@pytest.mark.parametrize("reading", [None, "1000", 1000.0, True])
def test_an_unusable_second_clock_reading_refuses_after_one_invocation(reading):
    envelope = build_envelope(clock=make_clock([0]))
    exchange = ok_exchange()
    result = run(envelope, exchange, [10, reading])
    assert exchange.calls == 1
    assert result.refusal == "clock-reading-not-exact-int"
    assert result.receipt.deadline_result == "not-evaluated"
    assert result.receipt.reservation_result == "satisfied"
    assert result.receipt.exchange_invocations == 1
    assert result.exchange is None


def test_a_clock_that_runs_backwards_is_refused_at_both_readings():
    envelope = build_envelope(clock=make_clock([1000]))
    first = ok_exchange()
    result = run(envelope, first, [999])
    assert first.calls == 0
    assert result.refusal == "clock-not-monotonic"
    assert result.receipt.deadline_result == "not-evaluated"

    second = ok_exchange()
    result = run(envelope, second, [1000, 999])
    assert second.calls == 1
    assert result.refusal == "clock-not-monotonic"
    assert result.receipt.exchange_invocations == 1


def test_a_clock_that_is_not_callable_refuses_before_anything_runs():
    envelope = build_envelope()
    exchange = ok_exchange()
    with hermetic_guard():
        result = ob.execute_observation(
            envelope,
            exchange=exchange,
            clock=1000,
            reservation_decision=satisfied_for(envelope),
        )
    assert exchange.calls == 0
    assert result.refusal == "clock-not-callable"
    assert result.receipt.deadline_result == "not-evaluated"
    assert result.receipt.reservation_result == "not-evaluated"


def test_an_exchange_that_is_not_callable_refuses_before_anything_runs():
    envelope = build_envelope()
    with hermetic_guard():
        result = ob.execute_observation(
            envelope,
            exchange="not callable",
            clock=make_clock([1000]),
            reservation_decision=satisfied_for(envelope),
        )
    assert result.refusal == "exchange-not-callable"
    assert result.receipt.exchange_invocations == 0
    assert result.receipt.deadline_result == "not-evaluated"


# ============================================================================
# the reservation gate
# ============================================================================


def test_an_unsatisfied_reservation_refuses_without_invoking_the_exchange():
    envelope = build_envelope()
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000], decision=satisfied_for(envelope, False))
    assert exchange.calls == 0
    assert result.ok is False
    assert result.refusal == "reservation-not-satisfied"
    assert result.receipt.outcome == "refused"
    assert result.receipt.reservation_result == "not-satisfied"
    assert result.receipt.request_outcome == "not-attempted"
    assert result.receipt.deadline_result == "within-deadline"


def test_a_decision_about_another_reservation_is_refused():
    envelope = build_envelope()
    other = ob.ResourceReservation(cpu_cores=64, memory_mib=1)
    exchange = ok_exchange()
    decision = ob.ReservationDecision(
        reservation_digest=other.digest,
        satisfied=True,
        attestation="checker-asserted",
    )
    result = run(envelope, exchange, [1000], decision=decision)
    assert exchange.calls == 0
    assert result.refusal == "reservation-decision-mismatch"
    assert result.receipt.reservation_result == "not-evaluated"


@pytest.mark.parametrize("value", [None, True, "satisfied", 1, object()])
def test_a_reservation_decision_of_the_wrong_type_is_refused(value):
    envelope = build_envelope()
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000], decision=value)
    assert exchange.calls == 0
    assert result.refusal == "reservation-decision-not-exact-type"


def test_v3a_records_an_attestation_and_never_inspects_a_real_resource():
    """The honesty control: a satisfied receipt is a claim, not a measurement.

    A reservation nothing on this machine could possibly satisfy is accepted
    exactly as readily as a modest one, because OMI-V3A never looks. If this
    ever started failing, something in this package would have begun measuring
    the host - which is outside its authority.
    """
    absurd = ob.ResourceReservation(
        cpu_cores=ob.OBSERVATION_LIMITS["cpu_cores"],
        memory_mib=ob.OBSERVATION_LIMITS["memory_mib"],
        gpu_memory_mib=ob.OBSERVATION_LIMITS["gpu_memory_mib"],
    )
    envelope = build_envelope(reservation=absurd)
    backend = FakeBackend('{"summary": "x"}')
    result = run(envelope, ob.structured_exchange_adapter(backend), [1000, 1100])
    assert result.ok is True
    assert result.receipt.reservation_result == "satisfied"


# ============================================================================
# the envelope's integrity, re-established before anything is described
# ============================================================================


@pytest.mark.parametrize("value", [None, "envelope", 5, object()])
def test_an_object_that_is_not_an_envelope_yields_no_receipt(value):
    exchange = ok_exchange()
    with hermetic_guard():
        result = ob.execute_observation(
            value,
            exchange=exchange,
            clock=make_clock([1000]),
            reservation_decision=ob.ReservationDecision(
                reservation_digest="a" * 64,
                satisfied=True,
                attestation="operator-asserted",
            ),
        )
    assert exchange.calls == 0
    assert result.ok is False
    assert result.refusal == "envelope-not-exact-type"
    assert result.receipt is None
    assert result.exchange is None


MUTATIONS = [
    ("task_id", "11111111-1111-4111-8111-111111111111"),
    ("authorizing_principal", "someone-else"),
    ("worker", "someone-else"),
    ("dialect", "vllm"),
    ("endpoint", "http://127.0.0.1:1/v1"),
    ("max_result_bytes", 4),
    ("max_evidence_bytes", 4),
    ("max_output_tokens", 4),
    ("context_ceiling_tokens", 4),
    ("issued_ns", 0),
    ("deadline_ns", 99999999),
    ("required_keys", ("other",)),
    ("schema_digest", "0" * 64),
    ("envelope_digest", "0" * 64),
]


@pytest.mark.parametrize(("field", "value"), MUTATIONS)
def test_a_mutation_between_planning_and_execution_is_refused(field, value):
    envelope = build_envelope()
    object.__setattr__(envelope, field, value)
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100])
    assert exchange.calls == 0
    assert result.refusal == "envelope-digest-mismatch"
    assert result.receipt is None


def test_substituting_evidence_bytes_of_the_same_length_is_still_caught():
    """The digest covers content, not a stored claim about content.

    An earlier revision of ``_envelope_digest`` read the stored ``item.digest``
    and ``len(item.content)`` only, so swapping an item's bytes for different
    bytes of the same length changed nothing it looked at. This is the control
    that would have caught that.
    """
    envelope = build_envelope(
        evidence=[ob.EvidenceItem(evidence_id="e1", content=b"AAAAAAAA")]
    )
    object.__setattr__(envelope.evidence[0], "content", b"BBBBBBBB")
    # Same length, and the stored digest is now stale: it still describes the
    # bytes that are no longer there. Nothing about the item's own fields
    # betrays the swap, which is exactly why the envelope digest must not rely
    # on them.
    assert len(envelope.evidence[0].content) == 8
    assert envelope.evidence[0].digest == hashlib.sha256(b"AAAAAAAA").hexdigest()
    assert envelope.evidence[0].digest != hashlib.sha256(b"BBBBBBBB").hexdigest()
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100])
    assert exchange.calls == 0
    assert result.refusal == "envelope-digest-mismatch"
    assert result.receipt is None


def test_substituting_the_schema_bytes_is_caught():
    envelope = build_envelope()
    replacement = json.dumps(
        {"type": "object", "properties": {"summary": {"type": "number"}}},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    object.__setattr__(envelope, "schema_bytes", replacement)
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100])
    assert exchange.calls == 0
    assert result.refusal == "envelope-digest-mismatch"


def test_tampering_with_a_reservations_fields_is_caught():
    envelope = build_envelope()
    object.__setattr__(envelope.reservation, "cpu_cores", 200)
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100], decision=satisfied_for(envelope))
    assert exchange.calls == 0
    assert result.refusal == "envelope-digest-mismatch"


def test_an_envelope_field_that_no_longer_renders_is_a_mismatch_not_a_crash():
    class Unrenderable:
        def __len__(self):
            raise TypeError("no length here")

    envelope = build_envelope()
    object.__setattr__(envelope, "schema_bytes", Unrenderable())
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100])
    assert exchange.calls == 0
    assert result.refusal == "envelope-digest-mismatch"
    assert result.receipt is None


# ============================================================================
# what came back
# ============================================================================


@pytest.mark.parametrize(
    ("payload", "failure"),
    [
        ("not json at all", "invalid-json"),
        ("[1, 2, 3]", "not-json-object"),
        ('"a string"', "not-json-object"),
        ("{", "invalid-json"),
        ('{"summary": NaN}', "non-finite-number"),
        ('{"summary": "a", "summary": "b"}', "duplicate-key"),
        ('{"other": "x"}', "missing-required-key"),
    ],
)
def test_an_invalid_structured_response_is_unusable_in_omi_v2s_own_words(
    payload, failure
):
    envelope = build_envelope()
    backend = FakeBackend(payload)
    result = run(envelope, ob.structured_exchange_adapter(backend), [1000, 1100])

    assert backend.calls == 1
    assert result.ok is False
    assert result.refusal is None
    receipt = result.receipt
    assert receipt.outcome == "unusable"
    assert receipt.response_outcome == "response-unusable"
    assert receipt.response_failure == failure
    assert receipt.response_failure in sx.RESPONSE_FAILURES
    assert receipt.request_refusal is None
    assert receipt.result_bytes == 0
    assert receipt.dialect == "ollama"
    assert result.exchange is not None
    assert result.exchange.ok is False


def test_a_missing_required_key_is_reported_as_indices_never_as_key_text():
    envelope = build_envelope(required_keys=("alpha", "beta", "gamma"))
    backend = FakeBackend('{"beta": 1}')
    result = run(envelope, ob.structured_exchange_adapter(backend), [1000, 1100])
    receipt = result.receipt
    assert receipt.response_failure == "missing-required-key"
    assert receipt.missing_key_indices == (0, 2)
    rendered = rc.serialize_receipt(receipt)
    assert b"alpha" not in rendered
    assert b"gamma" not in rendered


def test_a_response_larger_than_the_declared_char_bound_is_unusable():
    envelope = build_envelope(max_result_bytes=16)
    backend = FakeBackend('{"summary": "%s"}' % ("x" * 200))
    result = run(envelope, ob.structured_exchange_adapter(backend), [1000, 1100])
    assert result.receipt.outcome == "unusable"
    assert result.receipt.response_failure == "payload-too-large"


def test_a_result_over_the_declared_byte_bound_is_refused_after_one_invocation():
    """Chars and bytes are different bounds, and both are enforced.

    The payload below is nine characters, so OMI-V2's ``max_chars`` accepts it.
    Its canonical ASCII rendering escapes the non-ASCII character and comes to
    fourteen bytes, which the envelope's declared ``max_result_bytes`` of twelve
    does not. That gap is the whole reason OMI-V3A measures the accepted object
    itself rather than trusting the char bound to have covered it.
    """
    envelope = build_envelope(max_result_bytes=12, required_keys=("a",))
    payload = '{"a":"é"}'
    assert len(payload) == 9
    backend = FakeBackend(payload)
    result = run(envelope, ob.structured_exchange_adapter(backend), [1000, 1100])

    assert backend.calls == 1
    assert result.ok is False
    assert result.refusal == "result-too-large"
    assert result.receipt.outcome == "refused"
    assert result.receipt.exchange_invocations == 1
    assert result.receipt.result_bytes == 0
    assert result.exchange is None


@pytest.mark.parametrize(
    "value",
    [
        None,
        "exchange",
        5,
        object(),
        # OMI-V2's own carrier, one layer down: close enough to be believed by
        # duck typing, and refused because the check is exact.
        StructuredCompletion(ok=False, refusal="dialect-not-configured"),
    ],
)
def test_an_exchange_result_of_the_wrong_type_is_refused(value):
    envelope = build_envelope()
    exchange = CountingExchange(value)
    result = run(envelope, exchange, [1000, 1100])
    assert exchange.calls == 1
    assert result.refusal == "exchange-result-not-exact-type"
    assert result.receipt.exchange_invocations == 1
    assert result.exchange is None


def test_a_structured_exchange_subclass_is_refused_because_the_check_is_exact():
    class Sneaky(StructuredExchange):
        pass

    envelope = build_envelope()
    exchange = CountingExchange(
        Sneaky(ok=True, value={"summary": "x"}, dialect="ollama",
               response_format_sent=True)
    )
    result = run(envelope, exchange, [1000, 1100])
    assert result.refusal == "exchange-result-not-exact-type"


# ============================================================================
# exactly one invocation, and no retry
# ============================================================================


ZERO_INVOCATION_CASES = [
    "deadline-before",
    "reservation-unsatisfied",
    "reservation-mismatch",
    "reservation-wrong-type",
    "clock-backwards",
    "clock-bad-reading",
    "digest-mismatch",
    "wrong-envelope-type",
]


@pytest.mark.parametrize("case", ZERO_INVOCATION_CASES)
def test_the_exchange_is_never_invoked_on_a_pre_request_refusal(case):
    envelope = build_envelope(clock=make_clock([1000]), duration_ns=1000)
    exchange = ok_exchange()
    decision = satisfied_for(envelope)
    readings = [1000]
    target = envelope
    if case == "deadline-before":
        readings = [9999]
    elif case == "reservation-unsatisfied":
        decision = satisfied_for(envelope, False)
    elif case == "reservation-mismatch":
        decision = ob.ReservationDecision(
            reservation_digest="b" * 64, satisfied=True, attestation="checker-asserted"
        )
    elif case == "reservation-wrong-type":
        decision = None
    elif case == "clock-backwards":
        readings = [999]
    elif case == "clock-bad-reading":
        readings = ["1000"]
    elif case == "digest-mismatch":
        object.__setattr__(envelope, "worker", "other")
    elif case == "wrong-envelope-type":
        target = "not an envelope"

    with hermetic_guard():
        ob.execute_observation(
            target,
            exchange=exchange,
            clock=make_clock(readings),
            reservation_decision=decision,
        )
    assert exchange.calls == 0


ONE_INVOCATION_CASES = ["observed", "unusable", "void-during", "too-large", "bad-type"]


@pytest.mark.parametrize("case", ONE_INVOCATION_CASES)
def test_the_exchange_is_invoked_exactly_once_on_every_path_that_reaches_it(case):
    if case == "observed":
        envelope = build_envelope()
        backend = FakeBackend('{"summary": "x"}')
        run(envelope, ob.structured_exchange_adapter(backend), [1000, 1100])
        assert backend.calls == 1
        return
    if case == "unusable":
        envelope = build_envelope()
        backend = FakeBackend("not json")
        run(envelope, ob.structured_exchange_adapter(backend), [1000, 1100])
        assert backend.calls == 1
        return
    if case == "too-large":
        envelope = build_envelope(max_result_bytes=12, required_keys=("a",))
        backend = FakeBackend('{"a":"é"}')
        run(envelope, ob.structured_exchange_adapter(backend), [1000, 1100])
        assert backend.calls == 1
        return
    envelope = build_envelope(clock=make_clock([0]), duration_ns=1000)
    exchange = ok_exchange() if case == "void-during" else CountingExchange(None)
    readings = [10, 5000] if case == "void-during" else [10, 20]
    run(envelope, exchange, readings)
    assert exchange.calls == 1


def test_there_is_no_retry_loop_anywhere_in_the_executor():
    """Structural: the executor has one call site, latched, and no loop.

    Behaviour alone cannot prove the *absence* of a retry - it can only show
    that none happened on the paths exercised. This reads the executor's own
    source and asserts there is exactly one place the injected exchange is
    called, that a latch guards it, and that the function contains no loop of
    any kind for a retry to live in.

    Honest limit: this is a source-level control over one function. It does not
    and cannot say anything about retries inside an opaque transport, which is
    live-adapter work under separate authority.
    """
    code = _code_only(inspect.getsource(ob.execute_observation))
    assert code.count("exchange(target)") == 1
    assert "if latch:" in code
    assert "latch.append(1)" in code
    assert "raise _RuntimeError" in code
    assert "while " not in code
    assert "for " not in code
    assert "retry" not in code.lower()


def test_the_executor_has_no_tool_proposal_commit_or_registration_capability():
    """Structural: what the module *calls*, not what its prose discusses.

    The forbidden names are checked against the module's own call graph, read
    from its AST. A substring search would trip over
    ``OBSERVER_SYSTEM_PROMPT``, which contains the word "propose" precisely
    because it tells the model it cannot do that.
    """
    called = _called_names(ob)
    for forbidden in (
        "register", "propose", "commit", "rollback", "route", "create",
        "connect", "urlopen", "socket", "Popen", "system", "complete",
        "complete_structured", "getaddrinfo", "create_connection",
    ):
        assert forbidden not in called

    imported = {
        alias.name if isinstance(node, ast.Import) else node.module
        for node in ast.walk(ast.parse(inspect.getsource(ob)))
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    for forbidden in (
        "scripts.open_model.registry",
        "scripts.open_model.routing",
        "scripts.open_model.catalogue",
        "scripts.open_model.evaluation",
        "scripts.open_model.capabilities",
    ):
        assert forbidden not in imported

    signature = inspect.signature(ob.execute_observation)
    assert set(signature.parameters) == {
        "envelope", "exchange", "clock", "reservation_decision"
    }
    # No carrier anywhere in OMI-V3A has a field a tool could occupy.
    import dataclasses

    for carrier in (
        ob.EvidenceItem, ob.ObservationEnvelope, ob.ObservationPlan,
        ob.ObservationResult, ob.ReservationDecision, ob.ResourceReservation,
        rc.ObservationReceipt,
    ):
        names = {f.name for f in dataclasses.fields(carrier)}
        assert names & {"tools", "tool_specs", "capabilities", "actions"} == set()


# ============================================================================
# the receipt from a real run
# ============================================================================


def test_a_receipt_from_a_real_run_is_payload_free():
    marker = "PAYLOADMARKER"
    envelope = build_envelope(
        evidence=[
            ob.EvidenceItem(
                evidence_id="e1", content=(marker + " evidence").encode("utf-8")
            )
        ],
        schema={"type": "object", "title": marker, "properties": {"summary": {}}},
    )
    backend = FakeBackend('{"summary": "%s in the answer"}' % marker)
    result = run(envelope, ob.structured_exchange_adapter(backend), [1000, 1100])
    assert result.ok is True

    rendered = rc.serialize_receipt(result.receipt)
    assert marker.encode("ascii") not in rendered
    assert b"127.0.0.1" not in rendered
    assert b"11434" not in rendered
    assert b"http" not in rendered
    assert ob.OBSERVER_SYSTEM_PROMPT.encode("ascii")[:20] not in rendered
    assert envelope.schema_bytes not in rendered
    assert b"properties" not in rendered
    # The one place the answer's size shows up is a count, not the answer.
    assert result.receipt.result_bytes == len(
        json.dumps(
            dict(result.exchange.value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    )


def test_a_receipt_from_every_outcome_serialises_and_round_trips():
    envelope = build_envelope(clock=make_clock([0]), duration_ns=1000)
    cases = [
        run(build_envelope(), ob.structured_exchange_adapter(
            FakeBackend('{"summary": "x"}')), [1000, 1100]),
        run(build_envelope(), ob.structured_exchange_adapter(
            FakeBackend("not json")), [1000, 1100]),
        run(envelope, ok_exchange(), [9999]),
        run(envelope, ok_exchange(), [10, 5000]),
        run(build_envelope(), ok_exchange(),
            [1000], decision=satisfied_for(build_envelope(), False)),
    ]
    seen = set()
    for result in cases:
        receipt = result.receipt
        assert receipt is not None
        rendered = rc.serialize_receipt(receipt)
        assert len(rendered) <= 16384
        assert json.loads(rendered.decode("ascii"))["task_id"] == FIXED_TASK_ID
        assert pickle.loads(pickle.dumps(receipt)) == receipt
        assert copy.deepcopy(receipt) == receipt
        seen.add(receipt.outcome)
    assert seen == {"observed", "unusable", "void", "refused"}


def test_only_a_successful_result_refuses_to_pickle_and_the_receipt_never_does():
    observed = run(
        build_envelope(),
        ob.structured_exchange_adapter(FakeBackend('{"summary": "x"}')),
        [1000, 1100],
    )
    with pytest.raises(TypeError):
        pickle.dumps(observed)
    assert pickle.loads(pickle.dumps(observed.receipt)) == observed.receipt
    assert dict(observed.exchange.value) == {"summary": "x"}

    voided = run(
        build_envelope(clock=make_clock([0]), duration_ns=1000), ok_exchange(), [9999]
    )
    assert pickle.loads(pickle.dumps(voided)) == voided


def test_the_success_value_is_a_read_only_view_over_a_fresh_copy():
    supplied = {"summary": "x"}
    envelope = build_envelope()
    exchange = CountingExchange(
        StructuredExchange(
            ok=True, value=supplied, dialect="ollama", response_format_sent=True
        )
    )
    result = run(envelope, exchange, [1000, 1100])
    supplied["summary"] = "changed"
    supplied["injected"] = True
    assert dict(result.exchange.value) == {"summary": "x"}
    with pytest.raises(TypeError):
        result.exchange.value["summary"] = "changed"


# ============================================================================
# rebinding, on the execution path specifically
# ============================================================================


class Betrayer:
    def __call__(self, *args, **kwargs):
        raise AssertionError("a rebound module name was consulted")

    def __contains__(self, item):
        raise AssertionError("a rebound vocabulary was consulted")

    def __getitem__(self, item):
        raise AssertionError("a rebound mapping was consulted")

    def __iter__(self):
        raise AssertionError("a rebound iterable was consulted")

    def __eq__(self, other):
        raise AssertionError("a rebound value was compared")

    def __hash__(self):
        return 0


#: The production entry points and every input the signature needs, resolved
#: **at import time**. A rebinding control replaces module attributes, so a
#: helper that reached for ``ob.ReservationDecision`` while the rebinding was in
#: force would be testing its own name resolution rather than the code's.
_REAL_EXECUTE = ob.execute_observation
_REAL_ADAPTER = ob.structured_exchange_adapter
_REAL_SERIALIZE = rc.serialize_receipt
_SIG_ENVELOPE = build_envelope()
_SIG_DECISION_OK = satisfied_for(_SIG_ENVELOPE)
_SIG_DECISION_NO = satisfied_for(_SIG_ENVELOPE, False)


def _execution_signature():
    backend = FakeBackend('{"summary": "x"}')
    with hermetic_guard():
        observed = _REAL_EXECUTE(
            _SIG_ENVELOPE,
            exchange=_REAL_ADAPTER(backend),
            clock=make_clock([1000, 1100]),
            reservation_decision=_SIG_DECISION_OK,
        )
        refused = _REAL_EXECUTE(
            _SIG_ENVELOPE,
            exchange=_REAL_ADAPTER(FakeBackend('{"summary": "x"}')),
            clock=make_clock([1000, 1100]),
            reservation_decision=_SIG_DECISION_NO,
        )
    return (
        observed.ok,
        _REAL_SERIALIZE(observed.receipt),
        dict(observed.exchange.value),
        backend.calls,
        backend.seen[0]["tools"],
        backend.seen[0]["system"],
        refused.ok,
        refused.refusal,
        _REAL_SERIALIZE(refused.receipt),
    )


EXECUTION_TRUST_NAMES = [
    "ObservationEnvelope", "ObservationReceipt", "ObservationResult",
    "ReservationDecision", "StructuredExchange", "_envelope_digest",
    "request_structured_json", "StructuredOutputRequest", "Message",
    "json", "hashlib", "uuid", "type", "int", "len", "sum", "dict", "tuple",
    "callable", "OBSERVER_SYSTEM_PROMPT", "OBSERVATION_LIMITS",
]


@pytest.mark.parametrize("name", EXECUTION_TRUST_NAMES)
def test_rebinding_a_name_on_the_execution_path_changes_nothing(name):
    baseline = _execution_signature()
    had = name in vars(ob)
    original = getattr(ob, name, None)
    setattr(ob, name, Betrayer())
    try:
        assert _execution_signature() == baseline
    finally:
        if had:
            setattr(ob, name, original)
        else:
            delattr(ob, name)


HIDDEN_AUTHORITY_KEYWORDS = [
    "_type", "_json", "_len", "_dict", "_Receipt", "_Result", "_Envelope",
    "_Decision", "_digest_of", "_exchange_type", "_callable", "_request",
]


@pytest.mark.parametrize("keyword", HIDDEN_AUTHORITY_KEYWORDS)
def test_a_former_hidden_authority_cannot_be_injected_into_the_executor(keyword):
    envelope = build_envelope()
    with pytest.raises(TypeError):
        ob.execute_observation(
            envelope,
            exchange=ok_exchange(),
            clock=make_clock([1000, 1100]),
            reservation_decision=satisfied_for(envelope),
            **{keyword: Betrayer()},
        )
    with pytest.raises(TypeError):
        ob.structured_exchange_adapter(
            FakeBackend('{"summary": "x"}'), **{keyword: Betrayer()}
        )
