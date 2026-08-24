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
import itertools
import json
import pickle
import socket
import textwrap
import urllib.request
from types import MappingProxyType

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


def observation_exchange(value=None, dialect="ollama"):
    """A V3A carrier holding a successful OMI-V2 result, measured as the
    adapter measures it.

    Round three moved the result measurement onto the adapter, where the value's
    provenance is knowable, and made the executor consume a V3A-owned carrier.
    Doubles build the same carrier the adapter would.
    """
    completed = StructuredExchange(
        ok=True,
        value=dict(value if value is not None else {"summary": "seen"}),
        dialect=dialect,
        response_format_sent=True,
    )
    return ob.ObservationExchange(
        exchange=completed,
        result_snapshot=ob._result_snapshot_bytes(completed.value),
    )


def ok_exchange(value=None, dialect="ollama"):
    return CountingExchange(observation_exchange(value, dialect))


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


#: Mutations that leave the envelope SEMANTICALLY VALID. Nothing is wrong with
#: the resulting envelope except that it is not the one that was planned, so the
#: unkeyed digest is the only thing that can notice - which is exactly what a
#: digest is for, and exactly the limit of what it can do.
DIGEST_ONLY_MUTATIONS = [
    ("task_id", "11111111-1111-4111-8111-111111111111"),
    ("authorizing_principal", "someone-else"),
    ("worker", "someone-else"),
    ("endpoint", "http://127.0.0.1:1/v1"),
    ("dialect", "vllm"),
    ("max_result_bytes", 4096),
    ("max_output_tokens", 512),
    ("context_ceiling_tokens", 4096),
    ("issued_ns", 999),
    ("deadline_ns", 99999999),
    ("required_keys", ()),
    ("required_keys", ("other",)),
]

#: Mutations that make the envelope INVALID. The semantics gate catches these
#: first, and - as the resealing controls below show - would still catch them
#: with a perfectly recomputed digest.
SEMANTIC_MUTATIONS = [
    ("task_id", "not-a-uuid"),
    ("authorizing_principal", "sk-OMIV3ASECRET123456789"),
    ("worker", "has space"),
    ("dialect", "not-a-runtime"),
    ("endpoint", "http://localhost:11434/v1"),
    ("endpoint", "http://evil.example.com:11434/v1"),
    ("max_evidence_bytes", 4),
    ("max_result_bytes", 0),
    ("max_result_bytes", 10 ** 9),
    ("context_ceiling_tokens", 10 ** 9),
    ("schema_digest", "0" * 64),
    ("schema_bytes", b"not json at all"),
    ("required_keys", ("has space",)),
    ("issued_ns", -1),
    ("deadline_ns", 1000),
]


@pytest.mark.parametrize(("field", "value"), DIGEST_ONLY_MUTATIONS)
def test_a_semantically_valid_mutation_is_caught_by_the_digest(field, value):
    envelope = build_envelope()
    object.__setattr__(envelope, field, value)
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100])
    assert exchange.calls == 0
    assert result.refusal == "envelope-digest-mismatch"
    assert result.receipt is None


@pytest.mark.parametrize(("field", "value"), SEMANTIC_MUTATIONS)
def test_a_semantically_invalid_mutation_is_caught_before_the_digest(field, value):
    envelope = build_envelope()
    object.__setattr__(envelope, field, value)
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100])
    assert exchange.calls == 0
    assert result.refusal == "envelope-semantics-invalid"
    assert result.receipt is None


def test_a_tampered_envelope_digest_field_is_refused():
    envelope = build_envelope()
    object.__setattr__(envelope, "envelope_digest", "0" * 64)
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
    assert result.refusal == "envelope-semantics-invalid"
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
    assert result.refusal == "envelope-semantics-invalid"


def test_tampering_with_a_reservations_fields_is_caught():
    envelope = build_envelope()
    object.__setattr__(envelope.reservation, "cpu_cores", 200)
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100], decision=satisfied_for(envelope))
    assert exchange.calls == 0
    assert result.refusal == "envelope-semantics-invalid"


def test_an_envelope_field_that_no_longer_renders_is_refused_before_it_is_read():
    """The field-type check runs first, so the hostile ``__len__`` never fires.

    An earlier revision reached this object with ``hashlib.sha256`` and
    ``len()`` inside the digest walk, and relied on catching the exception. The
    shape check now refuses it by type identity before anything touches it, so
    the refusal names what is actually wrong and no supplied hook runs at all.
    """

    class Unrenderable:
        fired = []

        def __len__(self):  # pragma: no cover - must never be reached
            Unrenderable.fired.append("__len__")
            raise TypeError("no length here")

    envelope = build_envelope()
    object.__setattr__(envelope, "schema_bytes", Unrenderable())
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100])
    assert exchange.calls == 0
    assert result.refusal == "envelope-field-not-exact-type"
    assert result.receipt is None
    assert Unrenderable.fired == []


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
    completed = StructuredExchange(
        ok=True, value=supplied, dialect="ollama", response_format_sent=True
    )
    exchange = CountingExchange(
        ob.ObservationExchange(
            exchange=completed,
            result_snapshot=ob._result_snapshot_bytes(completed.value),
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
    "ObservationExchange", "_exchange_state_ok", "_result_snapshot_bytes",
    "_exchange_carrier_intact", "_envelope_semantics",
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


# ============================================================================
# Jack's first independent round - execution-path regressions
# ============================================================================


class Tripwire:
    """Records every hook the code under test runs on a tampered field."""

    fired: list = []

    @classmethod
    def clear(cls):
        cls.fired = []


class HookedDigest:
    """Something put where an envelope digest belongs. Every hook reports."""

    def __eq__(self, other):  # pragma: no cover - must never be reached
        Tripwire.fired.append("digest.__eq__")
        return False

    def __ne__(self, other):  # pragma: no cover
        Tripwire.fired.append("digest.__ne__")
        return True

    def __hash__(self):  # pragma: no cover
        Tripwire.fired.append("digest.__hash__")
        return 0

    def __len__(self):  # pragma: no cover
        Tripwire.fired.append("digest.__len__")
        return 64

    def __iter__(self):  # pragma: no cover
        Tripwire.fired.append("digest.__iter__")
        return iter(())


class HookedEvidence:
    """Something put where an evidence tuple belongs."""

    def __iter__(self):  # pragma: no cover
        Tripwire.fired.append("evidence.__iter__")
        return iter(())

    def __len__(self):  # pragma: no cover
        Tripwire.fired.append("evidence.__len__")
        return 0


class HookedBool:
    """Something put where a ``satisfied`` bool belongs."""

    def __bool__(self):  # pragma: no cover
        Tripwire.fired.append("satisfied.__bool__")
        return True


class HookedStrValue(str):
    """A str subclass put where an attestation or a digest belongs."""

    def __eq__(self, other):  # pragma: no cover
        Tripwire.fired.append("str.__eq__")
        return True

    def __hash__(self):  # pragma: no cover
        Tripwire.fired.append("str.__hash__")
        return 0


# -- finding 3, executor half: a clock that raises ---------------------------


def test_a_raising_first_clock_read_refuses_without_invoking_the_exchange():
    """The executor says only an exchange exception propagates. It is now true."""
    marker = "CLOCKSECRET-sk-OMIV3A"

    def raising_clock():
        raise RuntimeError(marker)

    envelope = build_envelope()
    exchange = ok_exchange()
    with hermetic_guard():
        result = ob.execute_observation(
            envelope,
            exchange=exchange,
            clock=raising_clock,
            reservation_decision=satisfied_for(envelope),
        )
    assert exchange.calls == 0
    assert result.ok is False
    assert result.refusal == "clock-raised"
    assert result.receipt.outcome == "refused"
    assert result.receipt.deadline_result == "not-evaluated"
    assert result.receipt.reservation_result == "not-evaluated"
    assert result.receipt.reservation_attestation is None
    assert result.receipt.exchange_invocations == 0
    assert result.receipt.elapsed_ns == 0
    rendered = rc.serialize_receipt(result.receipt)
    assert marker.encode("ascii") not in rendered
    assert b"RuntimeError" not in rendered
    assert b"CLOCKSECRET" not in rendered


def test_a_raising_second_clock_read_refuses_after_exactly_one_invocation():
    calls = []

    def clock_that_dies_second():
        if calls:
            raise ValueError("second read exploded")
        calls.append(1)
        return 1000

    envelope = build_envelope()
    exchange = ok_exchange()
    with hermetic_guard():
        result = ob.execute_observation(
            envelope,
            exchange=exchange,
            clock=clock_that_dies_second,
            reservation_decision=satisfied_for(envelope),
        )
    assert exchange.calls == 1
    assert result.refusal == "clock-raised"
    assert result.receipt.exchange_invocations == 1
    assert result.receipt.deadline_result == "not-evaluated"
    assert result.receipt.reservation_result == "satisfied"
    assert result.receipt.reservation_attestation == "operator-asserted"
    assert result.receipt.elapsed_ns == 0
    assert result.exchange is None
    assert rc.serialize_receipt(result.receipt)


@pytest.mark.parametrize(
    "exception",
    [RuntimeError("x"), ValueError("x"), TypeError("x"), OSError("x"), MemoryError()],
)
def test_a_clock_raising_anything_produces_the_same_fixed_token(exception):
    def raising_clock():
        raise exception

    envelope = build_envelope()
    with hermetic_guard():
        result = ob.execute_observation(
            envelope,
            exchange=ok_exchange(),
            clock=raising_clock,
            reservation_decision=satisfied_for(envelope),
        )
    assert result.refusal == "clock-raised"


def test_a_clock_that_breaches_hermeticity_is_refused_and_the_exchange_is_not():
    """The one narrowing, pinned in both directions.

    A clock is not permitted to perform I/O, so a ``HermeticViolation`` raised
    by one is treated as a caller error and refused like any other clock
    failure. The guarantee that matters - a breach on the **exchange** path
    failing the run loudly - is unaffected, and this control asserts both halves
    together so neither can drift without the other being noticed.
    """
    envelope = build_envelope()

    def breaching_clock():
        socket.socket()
        raise AssertionError("unreachable while the guard is active")

    with hermetic_guard():
        result = ob.execute_observation(
            envelope,
            exchange=ok_exchange(),
            clock=breaching_clock,
            reservation_decision=satisfied_for(envelope),
        )
    assert result.refusal == "clock-raised"

    # ...and the exchange path is still loud.
    with pytest.raises(HermeticViolation):
        run(envelope, ob.structured_exchange_adapter(NetworkReachingBackend()),
            [1000, 1100])


def test_a_clock_raising_a_base_exception_still_propagates_from_the_executor():
    def interrupting_clock():
        raise KeyboardInterrupt()

    envelope = build_envelope()
    with pytest.raises(KeyboardInterrupt):
        with hermetic_guard():
            ob.execute_observation(
                envelope,
                exchange=ok_exchange(),
                clock=interrupting_clock,
                reservation_decision=satisfied_for(envelope),
            )


# -- finding 3, executor half: magnitude -------------------------------------


ENORMOUS = [
    pytest.param(rc.MAX_CLOCK_NS + 1, id="one-past-the-ceiling"),
    pytest.param(10 ** 50, id="ten-to-the-50"),
    pytest.param(10 ** 5000, id="ten-to-the-5000"),
]


@pytest.mark.parametrize("reading", ENORMOUS)
def test_an_enormous_first_reading_refuses_with_a_bounded_serialisable_receipt(
    reading,
):
    envelope = build_envelope()
    exchange = ok_exchange()
    result = run(envelope, exchange, [reading])
    assert exchange.calls == 0
    assert result.refusal == "clock-reading-out-of-range"
    assert result.receipt.elapsed_ns == 0
    assert len(rc.serialize_receipt(result.receipt)) <= rc.RECEIPT_MAX_BYTES


@pytest.mark.parametrize("reading", ENORMOUS)
def test_an_enormous_second_reading_refuses_with_a_bounded_serialisable_receipt(
    reading,
):
    """The failure Jack found: a huge elapsed value that could not be written.

    The previous revision accepted the reading, subtracted, and produced a
    receipt holding a 5000-digit integer - which ``json.dumps`` then refused to
    render at all. The reading is refused where it enters, and the receipt that
    comes back is ordinary.
    """
    envelope = build_envelope(clock=make_clock([0]), duration_ns=1000000)
    exchange = ok_exchange()
    result = run(envelope, exchange, [10, reading])
    assert exchange.calls == 1
    assert result.refusal == "clock-reading-out-of-range"
    assert result.receipt.exchange_invocations == 1
    assert result.receipt.elapsed_ns == 0
    assert result.receipt.deadline_result == "not-evaluated"
    assert len(rc.serialize_receipt(result.receipt)) <= rc.RECEIPT_MAX_BYTES
    assert result.exchange is None


def test_a_negative_reading_shares_the_out_of_range_token():
    envelope = build_envelope()
    result = run(envelope, ok_exchange(), [-1])
    assert result.refusal == "clock-reading-out-of-range"


def test_the_largest_legal_elapsed_duration_still_produces_a_bounded_receipt():
    """At the ceiling, not merely below it."""
    envelope = ob.plan_observation(
        **{
            **dict(
                task_id=FIXED_TASK_ID,
                authorizing_principal="kev",
                worker="observer-1",
                evidence=[ob.EvidenceItem(evidence_id="e1", content=b"x")],
                dialect="ollama",
                schema=dict(SCHEMA),
                endpoint=ENDPOINT,
                reservation=ob.ResourceReservation(cpu_cores=2, memory_mib=4096),
                required_keys=("summary",),
            ),
            "clock": make_clock([0]),
            "duration_ns": ob.OBSERVATION_LIMITS["duration_ns"],
        }
    ).envelope
    # A reading inside the deadline, then one at the clock ceiling would blow
    # the deadline; use the largest elapsed that still lands inside it.
    inside = envelope.deadline_ns - 1
    exchange = ok_exchange()
    result = run(envelope, exchange, [0, inside])
    assert result.ok is True
    assert result.receipt.elapsed_ns == inside
    assert result.receipt.elapsed_ns <= rc.MAX_CLOCK_NS
    assert len(rc.serialize_receipt(result.receipt)) <= rc.RECEIPT_MAX_BYTES


# -- finding 4: execution-time revalidation invokes no supplied hook ----------


def test_a_hostile_envelope_digest_is_refused_before_it_is_compared():
    """``!=`` on a tampered digest ran the object's ``__ne__``. It cannot now."""
    envelope = build_envelope()
    object.__setattr__(envelope, "envelope_digest", HookedDigest())
    Tripwire.clear()
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100])
    assert Tripwire.fired == []
    assert exchange.calls == 0
    assert result.refusal == "envelope-field-not-exact-type"
    assert result.receipt is None


def test_a_malformed_but_string_envelope_digest_is_refused_before_comparison():
    envelope = build_envelope()
    for value in ("short", "A" * 64, "z" * 64, ""):
        object.__setattr__(envelope, "envelope_digest", value)
        exchange = ok_exchange()
        result = run(envelope, exchange, [1000, 1100])
        assert exchange.calls == 0
        assert result.refusal == "envelope-field-not-exact-type"
        assert result.receipt is None


def test_a_hostile_evidence_container_is_refused_before_it_is_traversed():
    envelope = build_envelope()
    object.__setattr__(envelope, "evidence", HookedEvidence())
    Tripwire.clear()
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100])
    assert Tripwire.fired == []
    assert exchange.calls == 0
    assert result.refusal == "envelope-field-not-exact-type"
    assert result.receipt is None


FIELD_TYPE_TAMPERS = [
    ("task_id", 5),
    ("authorizing_principal", None),
    ("worker", b"worker"),
    ("dialect", 5),
    ("endpoint", None),
    ("schema_digest", 5),
    ("schema_bytes", "not bytes"),
    ("context_ceiling_tokens", "8192"),
    ("max_evidence_bytes", None),
    ("max_result_bytes", 1.0),
    ("max_output_tokens", True),
    ("issued_ns", "1000"),
    ("deadline_ns", None),
    ("evidence", [1, 2]),
    ("required_keys", ["summary"]),
    ("reservation", None),
]


@pytest.mark.parametrize(("field", "value"), FIELD_TYPE_TAMPERS)
def test_every_envelope_field_type_substitution_is_refused_with_no_receipt(
    field, value
):
    envelope = build_envelope()
    # The decision is built from the intact envelope, before the tamper: a
    # helper that read the reservation afterwards would be testing its own
    # bookkeeping rather than the executor.
    decision = satisfied_for(envelope)
    object.__setattr__(envelope, field, value)
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100], decision=decision)
    assert exchange.calls == 0
    assert result.refusal == "envelope-field-not-exact-type"
    assert result.receipt is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidence_id", 5),
        ("content", "not bytes"),
        ("content", bytearray(b"abc")),
        ("digest", 5),
        ("digest", None),
    ],
)
def test_an_evidence_item_field_substitution_is_refused_before_traversal(
    field, value
):
    envelope = build_envelope()
    decision = satisfied_for(envelope)
    object.__setattr__(envelope.evidence[0], field, value)
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100], decision=decision)
    assert exchange.calls == 0
    assert result.refusal == "envelope-field-not-exact-type"
    assert result.receipt is None


@pytest.mark.parametrize(
    ("field", "value"),
    [("cpu_cores", "2"), ("memory_mib", None), ("gpu_memory_mib", "8"), ("digest", 5)],
)
def test_a_reservation_field_type_substitution_is_refused_before_traversal(
    field, value
):
    envelope = build_envelope()
    decision = satisfied_for(envelope)
    object.__setattr__(envelope.reservation, field, value)
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100], decision=decision)
    assert exchange.calls == 0
    assert result.refusal == "envelope-field-not-exact-type"
    assert result.receipt is None


# -- finding 4: the reservation decision is revalidated, then bound ----------


def test_a_tampered_decision_satisfied_never_runs_its_bool_hook():
    """The worst of the set: an unsatisfied gate walked straight to the exchange.

    The previous revision read ``decision.satisfied`` in a boolean context
    without re-checking its type, so an object with a ``__bool__`` returning
    True passed the gate and the exchange ran.
    """
    envelope = build_envelope()
    decision = satisfied_for(envelope)
    object.__setattr__(decision, "satisfied", HookedBool())
    Tripwire.clear()
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100], decision=decision)
    assert Tripwire.fired == []
    assert exchange.calls == 0
    assert result.refusal == "reservation-decision-field-invalid"
    assert result.receipt.reservation_result == "not-evaluated"
    assert result.receipt.reservation_attestation is None


@pytest.mark.parametrize("value", [1, 0, "yes", "", None, [], HookedBool()])
def test_a_tampered_decision_satisfied_of_any_type_is_refused(value):
    envelope = build_envelope()
    decision = satisfied_for(envelope)
    object.__setattr__(decision, "satisfied", value)
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100], decision=decision)
    assert exchange.calls == 0
    assert result.refusal == "reservation-decision-field-invalid"


@pytest.mark.parametrize(
    "value", ["short", "A" * 64, 5, None, HookedStrValue("a" * 64)]
)
def test_a_tampered_decision_digest_is_refused_before_it_is_compared(value):
    envelope = build_envelope()
    decision = satisfied_for(envelope)
    object.__setattr__(decision, "reservation_digest", value)
    Tripwire.clear()
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100], decision=decision)
    assert Tripwire.fired == []
    assert exchange.calls == 0
    assert result.refusal == "reservation-decision-field-invalid"


@pytest.mark.parametrize(
    "value", ["assumed", "sk-OMIV3ASECRET123456789", "", 5, None, True]
)
def test_a_tampered_decision_attestation_is_refused(value):
    """A tampered attestation was previously copied straight into the outcome."""
    envelope = build_envelope()
    decision = satisfied_for(envelope)
    object.__setattr__(decision, "attestation", value)
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100], decision=decision)
    assert exchange.calls == 0
    assert result.refusal == "reservation-decision-field-invalid"
    assert result.receipt.reservation_attestation is None


def test_a_secret_shaped_attestation_never_reaches_a_serialised_receipt():
    secret = "sk-OMIV3ASECRET123456789"
    envelope = build_envelope()
    decision = satisfied_for(envelope)
    object.__setattr__(decision, "attestation", secret)
    result = run(envelope, ok_exchange(), [1000, 1100], decision=decision)
    rendered = rc.serialize_receipt(result.receipt)
    assert secret.encode("ascii") not in rendered
    assert b"sk-" not in rendered


def test_the_decision_is_bound_to_the_recomputed_reservation_digest():
    """Not to the digest the reservation happens to be storing.

    A reservation whose fields were altered fails the envelope digest first, so
    the pairing can never be established against a stale value at all.
    """
    envelope = build_envelope()
    honest = satisfied_for(envelope)
    object.__setattr__(envelope.reservation, "cpu_cores", 4)
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100], decision=honest)
    assert exchange.calls == 0
    assert result.refusal == "envelope-semantics-invalid"
    assert result.receipt is None


def test_a_decision_for_a_different_reservation_is_still_refused():
    envelope = build_envelope()
    other = ob.ResourceReservation(cpu_cores=8, memory_mib=1024)
    decision = ob.ReservationDecision(
        reservation_digest=other.digest,
        satisfied=True,
        attestation="checker-asserted",
    )
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100], decision=decision)
    assert exchange.calls == 0
    assert result.refusal == "reservation-decision-mismatch"
    assert result.receipt.reservation_result == "not-evaluated"
    assert result.receipt.reservation_attestation is None


# -- the attestation travels into every receipt that evaluated one -----------


@pytest.mark.parametrize("attestation", sorted(rc.RESERVATION_ATTESTATIONS))
def test_the_attestation_reaches_the_receipt_on_every_evaluated_path(attestation):
    envelope = build_envelope()
    decision = satisfied_for(envelope, attestation=attestation)

    observed = run(
        envelope,
        ob.structured_exchange_adapter(FakeBackend('{"summary": "x"}')),
        [1000, 1100],
        decision=decision,
    )
    assert observed.receipt.reservation_attestation == attestation

    unusable = run(
        envelope,
        ob.structured_exchange_adapter(FakeBackend("not json")),
        [1000, 1100],
        decision=decision,
    )
    assert unusable.receipt.reservation_attestation == attestation

    refused = run(
        envelope,
        ok_exchange(),
        [1000],
        decision=satisfied_for(envelope, False, attestation=attestation),
    )
    assert refused.receipt.reservation_result == "not-satisfied"
    assert refused.receipt.reservation_attestation == attestation

    voided = run(
        build_envelope(clock=make_clock([0]), duration_ns=1000),
        ok_exchange(),
        [10, 5000],
        decision=decision,
    )
    assert voided.receipt.reservation_attestation == attestation


def test_a_path_that_never_reached_the_decision_records_no_attestation():
    envelope = build_envelope(clock=make_clock([0]), duration_ns=100)
    voided = run(envelope, ok_exchange(), [5000], decision=satisfied_for(envelope))
    assert voided.receipt.reservation_result == "not-evaluated"
    assert voided.receipt.reservation_attestation is None


def test_two_observations_differing_only_in_attestation_differ_in_evidence():
    envelope = build_envelope()
    first = run(
        envelope,
        ob.structured_exchange_adapter(FakeBackend('{"summary": "x"}')),
        [1000, 1100],
        decision=satisfied_for(envelope, attestation="operator-asserted"),
    )
    second = run(
        envelope,
        ob.structured_exchange_adapter(FakeBackend('{"summary": "x"}')),
        [1000, 1100],
        decision=satisfied_for(envelope, attestation="checker-asserted"),
    )
    assert first.receipt != second.receipt
    assert rc.serialize_receipt(first.receipt) != rc.serialize_receipt(second.receipt)


# -- every receipt the executor can emit serialises inside the bound ---------


def test_every_receipt_the_executor_emits_serialises_within_the_documented_bound():
    """Not a sample: one execution per reachable receipt-bearing outcome."""
    envelope = build_envelope()
    short = build_envelope(clock=make_clock([0]), duration_ns=1000)
    results = [
        run(envelope, ob.structured_exchange_adapter(
            FakeBackend('{"summary": "x"}')), [1000, 1100]),
        run(envelope, ob.structured_exchange_adapter(
            FakeBackend("not json")), [1000, 1100]),
        run(envelope, ob.structured_exchange_adapter(
            NonStructuredBackend()), [1000, 1100]),
        run(short, ok_exchange(), [9999]),
        run(short, ok_exchange(), [10, 5000]),
        run(envelope, ok_exchange(), [1000],
            decision=satisfied_for(envelope, False)),
        run(envelope, CountingExchange(None), [1000, 1100]),
        run(envelope, ok_exchange(), [rc.MAX_CLOCK_NS + 1]),
        run(envelope, "not callable", [1000]),
        run(envelope, ok_exchange(), [999]),
        run(build_envelope(max_result_bytes=12, required_keys=("a",)),
            ob.structured_exchange_adapter(FakeBackend('{"a":"é"}')), [1000, 1100]),
    ]
    outcomes = set()
    for result in results:
        assert result.receipt is not None
        rendered = rc.serialize_receipt(result.receipt)
        assert len(rendered) <= rc.RECEIPT_MAX_BYTES
        assert pickle.loads(pickle.dumps(result.receipt)) == result.receipt
        outcomes.add(result.receipt.outcome)
    assert outcomes == {"observed", "unusable", "void", "refused"}


def test_the_undescribable_refusals_are_exactly_the_receiptless_ones():
    assert rc.UNDESCRIBABLE_REFUSALS <= rc.EXECUTION_REFUSALS
    assert rc.UNDESCRIBABLE_REFUSALS == {
        "envelope-not-exact-type",
        "envelope-field-not-exact-type",
        "envelope-semantics-invalid",
        "envelope-digest-mismatch",
    }
    envelope = build_envelope()
    for target, token in (
        ("not an envelope", "envelope-not-exact-type"),
        (envelope, "envelope-digest-mismatch"),
    ):
        if token == "envelope-digest-mismatch":
            object.__setattr__(envelope, "worker", "someone-else")
        with hermetic_guard():
            result = ob.execute_observation(
                target,
                exchange=ok_exchange(),
                clock=make_clock([1000]),
                reservation_decision=satisfied_for(build_envelope()),
            )
        assert result.refusal == token
        assert result.receipt is None


# ============================================================================
# Jack's second independent round - execution-path regressions
# ============================================================================


class HookedOk:
    """Something put where a ``StructuredExchange.ok`` bool belongs."""

    fired: list = []

    def __bool__(self):  # pragma: no cover - must never be reached
        HookedOk.fired.append("ok.__bool__")
        return True


class HostileMapping:
    """A foreign mapping, wrapped in a proxy and substituted for a value."""

    fired: list = []

    def keys(self):
        HostileMapping.fired.append("keys")
        return ["summary"]

    def __getitem__(self, key):
        HostileMapping.fired.append("getitem")
        return "sk-OMIV3ASECRET123456789"

    def __iter__(self):
        HostileMapping.fired.append("iter")
        return iter(["summary"])

    def __len__(self):
        HostileMapping.fired.append("len")
        return 1


def ok_exchange_carrier(value=None, dialect="ollama"):
    """A VALID V3A carrier, for controls that then tamper with it.

    Tampering has to happen after construction, because the carrier's own
    ``__post_init__`` now refuses an incoherent OMI-V2 state outright - which is
    exactly gate 3. A control that built an incoherent carrier directly would be
    testing the constructor, not the executor.
    """
    return observation_exchange(value, dialect)


# -- finding 3, executor half: resealed envelopes are refused ----------------


def reseal(envelope):
    """Reseal only if the envelope is still semantically valid.

    After round three an *invalid* envelope cannot be resealed with this
    package's function at all: validation refuses, so no document exists to
    hash. That is stronger than the round-two behaviour and the controls below
    assert the consequence rather than the mechanism.
    """
    refusal, snapshot = ob._envelope_semantics(envelope)
    if refusal is None:
        object.__setattr__(envelope, "envelope_digest", ob._envelope_digest(snapshot[2]))
    return envelope


RESEALED_EXECUTION_TAMPERS = [
    ("authorizing_principal", "sk-OMIV3ASECRET123456789"),
    ("worker", "sk-OMIV3ASECRET123456789"),
    ("task_id", "not-a-uuid"),
    ("dialect", "not-a-runtime"),
    ("endpoint", "http://evil.example.com:11434/v1"),
    ("max_result_bytes", 10 ** 9),
    ("context_ceiling_tokens", 10 ** 9),
    ("max_evidence_bytes", 1),
    ("schema_bytes", b"not json at all"),
    ("required_keys", ("has space",)),
]


@pytest.mark.parametrize(("field", "value"), RESEALED_EXECUTION_TAMPERS)
def test_a_resealed_envelope_never_reaches_the_exchange(field, value):
    """The digest is unkeyed, so agreeing with it proves nothing about validity.

    Each of these executed on the previous head - several of them all the way
    to a successful observation, and several others as far as receipt
    construction, which then raised ``ValueError`` out of a function documented
    as total.
    """
    envelope = build_envelope()
    object.__setattr__(envelope, field, value)
    reseal(envelope)
    assert ob._envelope_semantics(envelope)[0] is not None

    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100])
    assert exchange.calls == 0
    assert result.ok is False
    assert result.refusal == "envelope-semantics-invalid"
    assert result.receipt is None


def test_a_resealed_envelope_with_invalid_utf8_evidence_never_reaches_the_adapter():
    envelope = build_envelope()
    object.__setattr__(envelope.evidence[0], "content", b"\xff\xfe")
    object.__setattr__(
        envelope.evidence[0], "digest", hashlib.sha256(b"\xff\xfe").hexdigest()
    )
    reseal(envelope)
    backend = FakeBackend('{"summary": "x"}')
    result = run(envelope, ob.structured_exchange_adapter(backend), [1000, 1100])
    assert backend.calls == 0
    assert result.refusal == "envelope-semantics-invalid"
    assert result.receipt is None


def test_a_resealed_over_limit_reservation_never_reaches_the_exchange():
    envelope = build_envelope()
    object.__setattr__(envelope.reservation, "cpu_cores", 10 ** 9)
    object.__setattr__(
        envelope.reservation,
        "digest",
        ob._reservation_digest(
            10 ** 9,
            envelope.reservation.memory_mib,
            envelope.reservation.gpu_memory_mib,
        ),
    )
    reseal(envelope)
    decision = ob.ReservationDecision(
        reservation_digest=envelope.reservation.digest,
        satisfied=True,
        attestation="operator-asserted",
    )
    exchange = ok_exchange()
    result = run(envelope, exchange, [1000, 1100], decision=decision)
    assert exchange.calls == 0
    assert result.refusal == "envelope-semantics-invalid"


def test_the_semantics_gate_runs_before_the_digest_gate():
    """Both tokens stay reachable, and each names what actually went wrong."""
    invalid = build_envelope()
    object.__setattr__(invalid, "dialect", "not-a-runtime")
    assert run(invalid, ok_exchange(), [1000, 1100]).refusal == (
        "envelope-semantics-invalid"
    )

    inconsistent = build_envelope()
    object.__setattr__(inconsistent, "worker", "someone-else")
    assert run(inconsistent, ok_exchange(), [1000, 1100]).refusal == (
        "envelope-digest-mismatch"
    )


# -- finding 4: the returned exchange carrier is revalidated ------------------


def test_a_tampered_exchange_ok_never_runs_its_bool_hook():
    envelope = build_envelope()
    carrier = ok_exchange_carrier()
    object.__setattr__(carrier.exchange, "ok", HookedOk())
    HookedOk.fired = []
    result = run(envelope, CountingExchange(carrier), [1000, 1100])
    assert HookedOk.fired == []
    assert result.ok is False
    assert result.refusal == "exchange-result-field-invalid"
    assert result.receipt.exchange_invocations == 1
    assert result.exchange is None
    assert rc.serialize_receipt(result.receipt)


@pytest.mark.parametrize(
    "value",
    ["ollama", "not-a-runtime", "sk-OMIV3ASECRET123456789", 5, "", "OLLAMA"],
)
def test_a_tampered_exchange_dialect_is_refused_rather_than_recorded(value):
    """A secret-shaped dialect reached receipt construction and raised there."""
    envelope = build_envelope()
    carrier = ok_exchange_carrier()
    object.__setattr__(carrier.exchange, "dialect", value)
    result = run(envelope, CountingExchange(carrier), [1000, 1100])
    if value == "ollama":
        assert result.ok is True
        return
    assert result.refusal == "exchange-result-field-invalid"
    rendered = rc.serialize_receipt(result.receipt)
    assert b"sk-" not in rendered
    assert b"not-a-runtime" not in rendered


@pytest.mark.parametrize(
    "value",
    [
        {"summary": "x"},
        None,
        "not a mapping",
        5,
        [("summary", "x")],
    ],
)
def test_a_tampered_exchange_value_of_the_wrong_type_is_refused(value):
    """Everything but a proxy is closed by an exact-type check."""
    envelope = build_envelope()
    carrier = ok_exchange_carrier()
    object.__setattr__(carrier.exchange, "value", value)
    result = run(envelope, CountingExchange(carrier), [1000, 1100])
    assert result.refusal == "exchange-result-field-invalid"
    assert result.exchange is None


class NonJsonMapping(HostileMapping):
    """A foreign mapping whose values are not JSON at all."""

    def __getitem__(self, key):
        NonJsonMapping.fired.append("getitem")
        return object()


def test_substituting_a_foreign_mapping_after_measurement_runs_no_hook_at_all():
    """Gate 4, and the residual round two could only bound is now gone.

    The result is measured on the **adapter path**, where the value is
    demonstrably the dict OMI-V2 just built - and the executor then reads an
    ``int`` off a V3A carrier. So a caller who substitutes a proxy over an
    arbitrary mapping afterwards has substituted something nothing will ever
    walk. Round two could only promise that such a mapping could not smuggle a
    non-JSON result or escape as an exception; it *did* run the mapping's hooks.
    It no longer runs anything.
    """
    envelope = build_envelope()

    for hostile in (HostileMapping, NonJsonMapping):
        carrier = ok_exchange_carrier()
        measured = carrier.result_bytes
        object.__setattr__(carrier.exchange, "value", MappingProxyType(hostile()))
        hostile.fired = []
        result = run(envelope, CountingExchange(carrier), [1000, 1100])

        assert hostile.fired == [], "no hook may run on the accepted path"
        assert result.ok is True
        # The recorded size is the one measured where provenance was known -
        # never a figure derived from the substituted mapping.
        assert result.receipt.result_bytes == measured
        rendered = rc.serialize_receipt(result.receipt)
        assert b"sk-" not in rendered
        assert b"object" not in rendered
        assert len(rendered) <= rc.RECEIPT_MAX_BYTES


def test_a_hostile_mapping_can_no_longer_reach_the_executor_at_all():
    """Even one that raises: the executor never touches it."""

    class Exploding(HostileMapping):
        def keys(self):
            raise RuntimeError("mapping said no")

        def __getitem__(self, key):
            raise RuntimeError("mapping said no")

    envelope = build_envelope()
    carrier = ok_exchange_carrier()
    object.__setattr__(carrier.exchange, "value", MappingProxyType(Exploding()))
    result = run(envelope, CountingExchange(carrier), [1000, 1100])
    assert result.ok is True
    assert rc.serialize_receipt(result.receipt)


def test_an_unmeasurable_successful_result_is_one_fixed_refusal():
    """The adapter reports "could not detach" as ``None``, never as an escape."""
    envelope = build_envelope()
    completed = StructuredExchange(
        ok=True, value={"summary": "x"}, dialect="ollama", response_format_sent=True
    )
    carrier = ob.ObservationExchange(exchange=completed, result_snapshot=None)
    assert carrier.result_bytes == 0
    result = run(envelope, CountingExchange(carrier), [1000, 1100])
    assert result.ok is False
    assert result.refusal == "result-not-serializable"
    assert result.receipt.result_bytes == 0
    assert rc.serialize_receipt(result.receipt)


def test_the_snapshot_builder_refuses_non_json_without_raising():
    """It is total, and it reports refusal as ``None``."""
    assert ob._result_snapshot_bytes(MappingProxyType({"a": 1})) == b'{"a":1}'
    assert ob._result_snapshot_bytes({"a": 1}) is None
    assert ob._result_snapshot_bytes(None) is None
    assert ob._result_snapshot_bytes(MappingProxyType({"a": object()})) is None
    assert ob._result_snapshot_bytes(MappingProxyType({"a": float("nan")})) is None
    deep = {"leaf": 1}
    for _ in range(64):
        deep = {"n": deep}
    assert ob._result_snapshot_bytes(MappingProxyType(deep)) is None
    wide = {"k%d" % i: i for i in range(8192)}
    assert ob._result_snapshot_bytes(MappingProxyType(wide)) is None


def test_a_hermetic_breach_from_the_snapshot_path_stays_loud():
    """Gate 5: no broad catch may turn a breach into an ordinary refusal.

    The snapshot builder guards only its encoder, with named exceptions. A
    mapping that reaches for a socket therefore raises ``HermeticViolation``
    out of the adapter and out of the executor, rather than becoming
    ``result-not-serializable``.
    """

    class Breaching(dict):
        def keys(self):
            socket.socket()
            return []

    with hermetic_guard():
        with pytest.raises(HermeticViolation):
            ob._result_snapshot_bytes(MappingProxyType(Breaching()))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("response_format_sent", 1),
        ("schema_conformance", "verified"),
        ("schema_conformance", 5),
        ("request_refusal", "not-a-token"),
        ("request_refusal", "sk-OMIV3ASECRET123456789"),
        ("response_failure", "not-a-token"),
        ("missing_key_indices", [0]),
        ("missing_key_indices", (1, 1)),
        ("missing_key_indices", ("0",)),
    ],
)
def test_every_tampered_exchange_field_is_refused(field, value):
    envelope = build_envelope()
    carrier = ok_exchange_carrier()
    object.__setattr__(carrier.exchange, field, value)
    result = run(envelope, CountingExchange(carrier), [1000, 1100])
    assert result.refusal == "exchange-result-field-invalid"
    assert result.receipt.exchange_invocations == 1


def test_the_exchange_checker_holds_omi_v2s_vocabularies_by_identity():
    cells = dict(
        zip(
            ob._exchange_state_ok.__code__.co_freevars,
            (cell.cell_contents for cell in ob._exchange_state_ok.__closure__ or ()),
        )
    )
    assert cells["_refusals"] is sx.EXCHANGE_REFUSALS
    assert cells["_failures"] is sx.RESPONSE_FAILURES
    assert cells["_dialect_ok"] is sr.is_supported_dialect
    assert cells["_exchange_type"] is StructuredExchange


def test_an_untampered_exchange_still_passes_every_state():
    """Positive guard: the checker does not reject what OMI-V2 legitimately makes."""
    envelope = build_envelope()
    for backend in (
        FakeBackend('{"summary": "x"}'),
        FakeBackend("not json"),
        FakeBackend('{"other": 1}'),
        NonStructuredBackend(),
    ):
        result = run(envelope, ob.structured_exchange_adapter(backend), [1000, 1100])
        assert result.refusal != "exchange-result-field-invalid"
        assert result.receipt is not None
        assert rc.serialize_receipt(result.receipt)


# -- every executor path builds and serialises a coherent bounded receipt -----


def test_every_executor_path_yields_a_receipt_that_serialises_or_none_at_all():
    """One execution per reachable path, checked end to end.

    For each: the result is coherent, the receipt either exists and serialises
    inside the bound or is absent for one of the four undescribable refusals,
    and no path raises.
    """
    short = build_envelope(clock=make_clock([0]), duration_ns=1000)
    resealed = build_envelope()
    object.__setattr__(resealed, "dialect", "not-a-runtime")
    reseal(resealed)
    field_broken = build_envelope()
    object.__setattr__(field_broken, "evidence", "not a tuple")
    digest_broken = build_envelope()
    object.__setattr__(digest_broken, "worker", "someone-else")
    tampered_carrier = ok_exchange_carrier()
    object.__setattr__(tampered_carrier, "ok", HookedOk())

    cases = [
        ("observed", build_envelope(), ob.structured_exchange_adapter(
            FakeBackend('{"summary": "x"}')), [1000, 1100], None),
        ("unusable-response", build_envelope(), ob.structured_exchange_adapter(
            FakeBackend("not json")), [1000, 1100], None),
        ("unusable-request", build_envelope(), ob.structured_exchange_adapter(
            NonStructuredBackend()), [1000, 1100], None),
        ("void-before", short, ok_exchange(), [9999], None),
        ("void-during", short, ok_exchange(), [10, 5000], None),
        ("reservation-unsatisfied", build_envelope(), ok_exchange(), [1000],
         "unsatisfied"),
        ("reservation-mismatch", build_envelope(), ok_exchange(), [1000],
         "mismatch"),
        ("decision-wrong-type", build_envelope(), ok_exchange(), [1000], "none"),
        ("exchange-not-callable", build_envelope(), "nope", [1000], None),
        ("clock-raised", build_envelope(), ok_exchange(), "raise", None),
        ("clock-bad-first", build_envelope(), ok_exchange(), ["x"], None),
        ("clock-backwards", build_envelope(), ok_exchange(), [999], None),
        ("clock-huge", build_envelope(), ok_exchange(), [rc.MAX_CLOCK_NS + 1], None),
        ("exchange-wrong-type", build_envelope(), CountingExchange(None),
         [1000, 1100], None),
        ("exchange-field-invalid", build_envelope(),
         CountingExchange(tampered_carrier), [1000, 1100], None),
        ("result-too-large", build_envelope(max_result_bytes=12,
                                            required_keys=("a",)),
         ob.structured_exchange_adapter(FakeBackend('{"a":"é"}')), [1000, 1100],
         None),
        ("envelope-wrong-type", "not an envelope", ok_exchange(), [1000], None),
        ("envelope-field", field_broken, ok_exchange(), [1000], None),
        ("envelope-semantics", resealed, ok_exchange(), [1000], None),
        ("envelope-digest", digest_broken, ok_exchange(), [1000], None),
    ]

    seen_outcomes = set()
    seen_receiptless = set()
    for label, envelope, exchange, readings, decision_kind in cases:
        reference = envelope if type(envelope) is ob.ObservationEnvelope else (
            build_envelope()
        )
        if decision_kind == "unsatisfied":
            decision = satisfied_for(reference, False)
        elif decision_kind == "mismatch":
            decision = ob.ReservationDecision(
                reservation_digest="b" * 64, satisfied=True,
                attestation="checker-asserted")
        elif decision_kind == "none":
            decision = None
        else:
            decision = satisfied_for(reference)

        if readings == "raise":
            def clock():
                raise RuntimeError("boom")
        else:
            clock = make_clock(readings)

        with hermetic_guard():
            result = ob.execute_observation(
                envelope, exchange=exchange, clock=clock,
                reservation_decision=decision)

        assert type(result) is ob.ObservationResult, label
        if result.receipt is None:
            assert result.refusal in rc.UNDESCRIBABLE_REFUSALS, label
            seen_receiptless.add(result.refusal)
            continue
        rendered = rc.serialize_receipt(result.receipt)
        assert len(rendered) <= rc.RECEIPT_MAX_BYTES, label
        assert pickle.loads(pickle.dumps(result.receipt)) == result.receipt, label
        assert b"sk-" not in rendered, label
        seen_outcomes.add(result.receipt.outcome)

    assert seen_outcomes == {"observed", "unusable", "void", "refused"}
    assert seen_receiptless == rc.UNDESCRIBABLE_REFUSALS


# ============================================================================
# Jack's third independent round - regressions for every named gate
# ============================================================================


def failed_carrier(**tampers):
    """A VALID failed-exchange carrier, then tampered post-construction.

    Post-construction is the only way: :class:`ObservationExchange` refuses an
    incoherent OMI-V2 state at the door, which is gate 3 working. A control that
    tried to build one directly would be testing the constructor.
    """
    completed = StructuredExchange(
        ok=False, response_failure="invalid-json", dialect="ollama",
        response_format_sent=True,
    )
    carrier = ob.ObservationExchange(exchange=completed)
    for field, value in tampers.items():
        object.__setattr__(carrier.exchange, field, value)
    return carrier


def ok_carrier(**tampers):
    carrier = ok_exchange_carrier()
    for field, value in tampers.items():
        object.__setattr__(carrier.exchange, field, value)
    return carrier


# -- gate 3: the whole state machine, not just field types -------------------


INCOHERENT_SUCCESS = [
    ("no dialect", dict(dialect=None)),
    ("nothing sent", dict(response_format_sent=False)),
    ("success carrying a request refusal", dict(request_refusal="schema-empty")),
    ("success carrying a response failure", dict(response_failure="invalid-json")),
    ("success with no value", dict(value=None)),
]


@pytest.mark.parametrize(("label", "tampers"), INCOHERENT_SUCCESS)
def test_an_exact_but_incoherent_success_is_refused(label, tampers):
    """Every field legal, the combination impossible - and previously executed.

    An exact-but-incoherent carrier reached receipt construction, where the
    receipt correctly refused it and raised ``ValueError`` out of a function
    documented as total. It is refused here now, with a fixed token.
    """
    envelope = build_envelope()
    result = run(envelope, CountingExchange(ok_carrier(**tampers)), [1000, 1100])
    assert result.ok is False, label
    assert result.refusal == "exchange-result-field-invalid", label
    assert result.exchange is None
    assert result.receipt.exchange_invocations == 1
    assert rc.serialize_receipt(result.receipt)


INCOHERENT_FAILURE = [
    ("neither token", dict(response_failure=None)),
    ("both tokens", dict(request_refusal="schema-empty")),
    ("failure carrying a value", dict(value=MappingProxyType({"a": 1}))),
    ("response failure claiming nothing was sent",
     dict(response_format_sent=False)),
    ("response failure naming no dialect", dict(dialect=None)),
]


@pytest.mark.parametrize(("label", "tampers"), INCOHERENT_FAILURE)
def test_an_exact_but_incoherent_failure_is_refused(label, tampers):
    envelope = build_envelope()
    result = run(envelope, CountingExchange(failed_carrier(**tampers)), [1000, 1100])
    assert result.ok is False, label
    assert result.refusal == "exchange-result-field-invalid", label
    assert result.exchange is None


def test_request_versus_response_failure_coherence_is_enforced():
    """A request refusal means nothing was sent; a response failure means it was."""
    envelope = build_envelope()

    # A request refusal that claims a request WAS sent.
    carrier = failed_carrier(
        response_failure=None,
        request_refusal="backend-not-structured-capable",
        dialect=None,
        response_format_sent=True,
    )
    assert run(envelope, CountingExchange(carrier), [1000, 1100]).refusal == (
        "exchange-result-field-invalid"
    )

    # ...and the coherent version of the same refusal is accepted.
    good = failed_carrier(
        response_failure=None,
        request_refusal="backend-not-structured-capable",
        dialect=None,
        response_format_sent=False,
    )
    result = run(envelope, CountingExchange(good), [1000, 1100])
    assert result.receipt.outcome == "unusable"
    assert result.receipt.request_refusal == "backend-not-structured-capable"
    assert result.receipt.dialect is None


@pytest.mark.parametrize("token", sorted(sx.EXCHANGE_REFUSALS))
def test_the_dialect_phase_is_enforced_for_every_request_refusal(token):
    """OMI-V2's own phase predicate decides, and both errors are refused."""
    envelope = build_envelope()
    pre = token == "backend-not-structured-capable" or sr.is_pre_dialect_refusal(token)

    wrong = failed_carrier(
        response_failure=None,
        request_refusal=token,
        response_format_sent=False,
        dialect="ollama" if pre else None,
    )
    assert run(envelope, CountingExchange(wrong), [1000, 1100]).refusal == (
        "exchange-result-field-invalid"
    )

    right = failed_carrier(
        response_failure=None,
        request_refusal=token,
        response_format_sent=False,
        dialect=None if pre else "ollama",
    )
    result = run(envelope, CountingExchange(right), [1000, 1100])
    assert result.receipt.outcome == "unusable"
    assert result.receipt.request_refusal == token


@pytest.mark.parametrize(
    "indices",
    [
        pytest.param((0,), id="indices-without-the-failure"),
        pytest.param((1, 1), id="not-increasing"),
        pytest.param((2, 0), id="decreasing"),
        pytest.param((-1,), id="negative"),
        pytest.param((True,), id="bool-not-int"),
        pytest.param(("0",), id="str-not-int"),
        pytest.param([0], id="list-not-tuple"),
    ],
)
def test_invalid_missing_key_indices_on_the_exchange_are_refused(indices):
    envelope = build_envelope()
    carrier = failed_carrier(missing_key_indices=indices)
    result = run(envelope, CountingExchange(carrier), [1000, 1100])
    assert result.refusal == "exchange-result-field-invalid"


def test_a_missing_required_key_failure_must_carry_indices():
    envelope = build_envelope()
    carrier = failed_carrier(
        response_failure="missing-required-key", missing_key_indices=()
    )
    assert run(envelope, CountingExchange(carrier), [1000, 1100]).refusal == (
        "exchange-result-field-invalid"
    )
    good = failed_carrier(
        response_failure="missing-required-key", missing_key_indices=(0,)
    )
    result = run(envelope, CountingExchange(good), [1000, 1100])
    assert result.receipt.response_failure == "missing-required-key"
    assert result.receipt.missing_key_indices == (0,)


def test_a_tampered_carrier_snapshot_or_count_is_refused():
    """The V3A carrier is revalidated too - its own fields are not trusted."""
    envelope = build_envelope()
    for field, value in (
        ("result_snapshot", b"{}"),      # count no longer matches the bytes
        ("result_snapshot", "not bytes"),
        ("result_bytes", 999),
        ("result_bytes", "12"),
        ("exchange", "not an exchange"),
    ):
        carrier = ok_exchange_carrier()
        object.__setattr__(carrier, field, value)
        result = run(envelope, CountingExchange(carrier), [1000, 1100])
        assert result.ok is False, (field, value)
        assert result.refusal in (
            "exchange-result-field-invalid",
            "exchange-result-not-exact-type",
        ), (field, value)


# -- gates 1 and 2: the windows are structurally gone ------------------------


def test_validation_returns_the_detached_carriers_it_installed():
    """Gate 1: one traversal produces the snapshot, and the envelope holds it.

    Not "validation then a second walk to copy" - the copies come *out of*
    validation, so there is no instant between proving a value and installing it.
    """
    item = ob.EvidenceItem(evidence_id="e1", content=b"mine")
    reservation = ob.ResourceReservation(cpu_cores=2, memory_mib=4096)
    envelope = build_envelope(evidence=[item], reservation=reservation)

    refusal, snapshot = ob._envelope_semantics(envelope)
    assert refusal is None
    detached_evidence, detached_reservation, document, schema_bytes = snapshot
    assert schema_bytes == envelope.schema_bytes

    # What validation returns is detached from what it was given...
    assert detached_evidence[0] is not item
    assert detached_reservation is not reservation
    # ...and the envelope holds carriers detached from the caller's too.
    assert envelope.evidence[0] is not item
    assert envelope.reservation is not reservation
    assert envelope.evidence[0].content == b"mine"
    # ...and the digest is over the document, not over a re-read of the envelope.
    assert ob._envelope_digest(document) == envelope.envelope_digest


def test_nothing_is_read_off_the_envelope_after_validation():
    """Gate 1, structurally: no attribute of ``self`` survives the snapshot.

    Read from the AST with docstrings and comments gone, so prose can neither
    satisfy nor defeat it. After ``_semantics(self)`` returns, the only names
    the constructor touches are the snapshot's own parts.
    """
    # Delegated to the AST predicate rather than a substring search. The
    # string version passed a source that still handed `self` to a helper - a
    # probe in the fourth round demonstrated exactly that - so what looked like
    # a structural proof was only a proof about spelling.
    tail = _tail_ast(ob.ObservationEnvelope.__post_init__, "_semantics(self)")
    assert _attribute_reads_in(tail, "self") == []
    unparsed = " ".join(ast.unparse(s) for s in tail)
    assert "_digest_of(document)" in unparsed


def test_nothing_is_read_off_the_receipt_after_revalidation():
    """Gate 2, structurally: the serialiser writes the checker's document."""
    # Same delegation, same reason.
    tail = _tail_ast(rc.serialize_receipt, "_check(receipt)")
    assert _names_in(tail, "receipt") == []
    unparsed = " ".join(ast.unparse(s) for s in tail)
    assert "document" in unparsed


def test_the_checker_returns_the_document_the_serialiser_writes():
    """The bytes written are a rendering of what validation proved, exactly."""
    result = run(
        build_envelope(),
        ob.structured_exchange_adapter(FakeBackend('{"summary": "x"}')),
        [1000, 1100],
    )
    receipt = result.receipt
    document = rc._check_receipt(receipt)
    assert type(document) is dict
    assert json.loads(rc.serialize_receipt(receipt).decode('ascii')) == document
    # The document is detached: mutating it cannot reach the receipt.
    document['worker'] = 'someone-else'
    assert receipt.worker == 'observer-1'
    assert json.loads(rc.serialize_receipt(receipt).decode('ascii'))['worker'] == (
        'observer-1'
    )


def test_the_serialiser_holds_the_checker_function_itself():
    cells = dict(
        zip(
            rc.serialize_receipt.__code__.co_freevars,
            (cell.cell_contents for cell in rc.serialize_receipt.__closure__ or ()),
        )
    )
    assert cells["_check"] is rc._check_receipt


# ============================================================================
# Fourth-round adversarial review - regressions for every demonstrated defect
# ============================================================================
#
# Provenance: this round was performed in a fresh Kev seat by the same agent
# lineage that wrote the code. It is adversarial and it found real defects, but
# it is NOT independent acceptance. See section 17 of the inception document.


def _tail_ast(function, marker):
    """The AST of everything a function does after ``marker`` appears.

    Parsed rather than string-searched, so a read moved behind a helper is
    still visible as a ``Name`` node. The previous revision's structural
    controls split the source text and looked for ``self.field`` - which a
    refactor to ``_helper(self)`` walked straight past, as a probe in this
    round demonstrated.
    """
    source = textwrap.dedent(inspect.getsource(function))
    tree = ast.parse(source)
    body = tree.body[0].body
    cut = None
    for index, statement in enumerate(body):
        if marker in ast.unparse(statement):
            cut = index + 1
            break
    if cut is None:
        raise AssertionError("marker %r not found in %s" % (marker, function))
    return body[cut:]


def _names_in(statements, target):
    found = []
    for statement in statements:
        for node in ast.walk(statement):
            if isinstance(node, ast.Name) and node.id == target:
                found.append(node)
    return found


def _attribute_reads_in(statements, target):
    found = []
    for statement in statements:
        for node in ast.walk(statement):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == target
            ):
                found.append(node.attr)
    return sorted(set(found))


# -- D1: the executor consumes the validated document, never the envelope ----


def test_the_executor_reads_no_envelope_attribute_after_validation():
    """The structural half of the fourth round's first finding.

    Two caller-supplied callables run inside ``execute_observation`` - the clock
    and the exchange - so "after validation" is not a thread-race window, it is
    code the executor calls on purpose. Every value consumed after validation
    now comes from the document validation produced.

    Read from the AST, so a read moved behind a helper would still show up as a
    ``Name`` node rather than slipping past a substring search.
    """
    tail = _tail_ast(ob.execute_observation, "rederived = _digest_of(document)")
    # Not merely no attribute READS - the caller's envelope does not appear in
    # the tail at all. The exchange is handed a package-owned envelope rebuilt
    # from the snapshot, so a caller-supplied clock cannot reach what the
    # exchange sees either.
    assert _attribute_reads_in(tail, "envelope") == []
    assert _names_in(tail, "envelope") == []
    unparsed = " ".join(ast.unparse(s) for s in tail)
    assert "_invoke_once(validated)" in unparsed
    assert "envelope." not in unparsed


@pytest.mark.parametrize(
    "field",
    ["max_result_bytes", "deadline_ns", "issued_ns", "context_ceiling_tokens"],
)
def test_a_hostile_clock_cannot_rewrite_a_limit_the_executor_then_uses(field):
    """A clock runs between validation and every later decision."""
    envelope = build_envelope()
    original = getattr(envelope, field)
    calls = []

    def tampering_clock():
        calls.append(1)
        if len(calls) == 1:
            object.__setattr__(envelope, field, 8 if "bytes" in field else 1)
        return 1000 if len(calls) == 1 else 1100

    backend = FakeBackend('{"summary": "%s"}' % ("x" * 200))
    with hermetic_guard():
        result = ob.execute_observation(
            envelope,
            exchange=ob.structured_exchange_adapter(backend),
            clock=tampering_clock,
            reservation_decision=satisfied_for(envelope),
        )
    # The tamper landed on the caller's envelope...
    assert getattr(envelope, field) != original
    # ...and changed nothing the executor decided, and nothing the canonical
    # adapter transmitted: both work from the snapshot validation produced.
    assert result.ok is True
    assert result.receipt.outcome == "observed"
    assert result.receipt.context_ceiling_tokens == 8192
    assert backend.seen[0]["max_tokens"] == 1024
    assert backend.seen[0]["messages"][0].content == "the evidence"
    assert rc.serialize_receipt(result.receipt)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("worker", "sk-OMIV3ASECRET123456789"),
        ("worker", "has space"),
        ("authorizing_principal", "sk-OMIV3ASECRET123456789"),
        ("task_id", "not-a-uuid"),
        ("schema_digest", "nope"),
        ("required_keys", ("a",) * 200),
    ],
)
def test_a_hostile_exchange_cannot_rewrite_what_the_receipt_records(field, value):
    """The half that broke totality outright.

    A hostile exchange rewriting ``worker`` or ``task_id`` made the receipt
    carrier refuse the tampered value by raising ``ValueError`` **out of**
    ``execute_observation`` - a function documented as total. The receipt is
    now assembled from the validated document, so the tamper reaches nothing.
    """
    envelope = build_envelope()
    seen = {}

    def tampering_exchange(target):
        # The exchange receives a package-owned envelope, not the caller's, so
        # this tamper cannot even reach `envelope` - and it changes nothing the
        # receipt records either.
        seen["target"] = target
        object.__setattr__(target, field, value)
        return observation_exchange()

    with hermetic_guard():
        result = ob.execute_observation(
            envelope,
            exchange=tampering_exchange,
            clock=make_clock([1000, 1100]),
            reservation_decision=satisfied_for(envelope),
        )
    assert seen["target"] is not envelope, "the caller's envelope is not handed on"
    assert getattr(seen["target"], field) == value, "the tamper must land somewhere"
    assert getattr(envelope, field) != value, "...but never on the caller's object"
    assert result.ok is True
    assert result.receipt.worker == "observer-1"
    assert result.receipt.authorizing_principal == "kev"
    assert result.receipt.task_id == FIXED_TASK_ID
    rendered = rc.serialize_receipt(result.receipt)
    assert b"sk-" not in rendered


def test_a_hostile_exchange_cannot_rewrite_the_deadline_the_executor_rechecks():
    envelope = build_envelope()
    original = envelope.deadline_ns

    def tampering_exchange(target):
        object.__setattr__(target, "deadline_ns", 1)
        return observation_exchange()

    with hermetic_guard():
        result = ob.execute_observation(
            envelope,
            exchange=tampering_exchange,
            clock=make_clock([1000, 1100]),
            reservation_decision=satisfied_for(envelope),
        )
    assert envelope.deadline_ns == original
    assert result.receipt.outcome == "observed"
    assert result.receipt.deadline_result == "within-deadline"


def test_a_hostile_exchange_cannot_swap_the_evidence_the_receipt_records():
    envelope = build_envelope()

    def tampering_exchange(target):
        other = ob.EvidenceItem(evidence_id="swapped", content=b"other bytes")
        object.__setattr__(target, "evidence", (other,))
        return observation_exchange()

    with hermetic_guard():
        result = ob.execute_observation(
            envelope,
            exchange=tampering_exchange,
            clock=make_clock([1000, 1100]),
            reservation_decision=satisfied_for(envelope),
        )
    assert envelope.evidence[0].evidence_id == "e1"
    assert result.receipt.evidence_ids == ("e1",)
    assert result.receipt.evidence_bytes == len(b"the evidence")


# -- D3: the structural controls are robust to reads behind helpers ----------


def test_the_envelope_constructor_hands_self_only_to_setattr_after_validation():
    tail = _tail_ast(ob.ObservationEnvelope.__post_init__, "_semantics(self)")
    assert _attribute_reads_in(tail, "self") == []
    uses = _names_in(tail, "self")
    setattrs = 0
    for statement in tail:
        for node in ast.walk(statement):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "__setattr__"
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "self"
            ):
                setattrs += 1
    assert setattrs >= 3
    assert len(uses) == setattrs, "self may only be written, never passed on"


def test_the_serialiser_touches_the_receipt_nowhere_after_the_check():
    tail = _tail_ast(rc.serialize_receipt, "_check(receipt)")
    assert _names_in(tail, "receipt") == []


def test_the_structural_controls_catch_a_read_moved_behind_a_helper():
    """Non-vacuity: the controls above must flag what a probe showed they missed.

    The previous revision split the source text and looked for ``self.field``.
    A refactor to ``_helper(self)`` passed it while still handing the mutable
    object on. These synthetic sources reproduce exactly that, and the AST
    predicates must reject both.
    """
    hidden_self = textwrap.dedent(
        '''
        def __post_init__(self):
            refusal, snapshot = _semantics(self)
            evidence, reservation, document = snapshot
            _object.__setattr__(self, "evidence", _helper(self))
        '''
    )
    body = ast.parse(hidden_self).body[0].body
    cut = next(i for i, s in enumerate(body) if "_semantics(self)" in ast.unparse(s))
    tail = body[cut + 1 :]
    setattrs = sum(
        1
        for statement in tail
        for node in ast.walk(statement)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "__setattr__"
    )
    assert len(_names_in(tail, "self")) > setattrs, (
        "the predicate must notice self being handed to a helper"
    )

    hidden_receipt = textwrap.dedent(
        '''
        def serialize_receipt(receipt):
            document = _check(receipt)
            document["worker"] = _reread(receipt)
            return _json.dumps(document).encode("ascii")
        '''
    )
    body = ast.parse(hidden_receipt).body[0].body
    cut = next(i for i, s in enumerate(body) if "_check(receipt)" in ast.unparse(s))
    assert _names_in(body[cut + 1 :], "receipt") != [], (
        "the predicate must notice receipt being handed to a helper"
    )


# -- attack 4: the state machine matches OMI-V2's, differentially ------------


_STATE_SPACE = list(
    itertools.product(
        [True, False],
        [None, {"a": 1}],
        [None, "backend-not-structured-capable", "dialect-not-configured",
         "schema-empty", "tools-with-structured-unsupported"],
        [None, "invalid-json", "missing-required-key"],
        [None, "ollama"],
        [True, False],
        [(), (0,)],
    )
)


def test_v3a_accepts_exactly_the_carriers_omi_v2_can_construct():
    """A differential over the whole small state space, both directions.

    Stronger than asserting the checker holds OMI-V2's vocabularies in cells:
    that shows it consults the right *values*, not that it draws the same
    *boundary*. Here every combination is put to OMI-V2 by construction and to
    V3A by inspection, and the two verdicts must agree.
    """
    rejects_valid = []
    accepts_invalid = []
    constructible = 0
    for ok, value, rr, rf, dialect, sent, idx in _STATE_SPACE:
        try:
            built = StructuredExchange(
                ok=ok, value=value, request_refusal=rr, response_failure=rf,
                missing_key_indices=idx, dialect=dialect,
                response_format_sent=sent,
            )
            omi_v2 = True
        except ValueError:
            built = None
            omi_v2 = False
        if omi_v2:
            constructible += 1
            if not ob._exchange_state_ok(built):
                rejects_valid.append((ok, value, rr, rf, dialect, sent, idx))
            continue
        victim = StructuredExchange(
            ok=True, value={"a": 1}, dialect="ollama", response_format_sent=True
        )
        object.__setattr__(victim, "ok", ok)
        object.__setattr__(
            victim, "value", MappingProxyType(value) if value is not None else None
        )
        object.__setattr__(victim, "request_refusal", rr)
        object.__setattr__(victim, "response_failure", rf)
        object.__setattr__(victim, "dialect", dialect)
        object.__setattr__(victim, "response_format_sent", sent)
        object.__setattr__(victim, "missing_key_indices", idx)
        if ob._exchange_state_ok(victim):
            accepts_invalid.append((ok, value, rr, rf, dialect, sent, idx))

    assert constructible > 0, "the space must contain constructible carriers"
    assert rejects_valid == [], "V3A rejects a carrier OMI-V2 can build"
    assert accepts_invalid == [], "V3A accepts a state OMI-V2 refuses"


# -- attack 1: the adapter path's provenance, asserted positively ------------


class TamperingBackend:
    """Returns a completion whose fields are tampered after construction."""

    def __init__(self, **tampers):
        self.tampers = tampers

    def complete_structured(self, messages, tools, **kwargs):
        completion = StructuredCompletion(
            ok=True,
            response=AgentResponse.from_content(
                [TextBlock(text='{"summary": "x"}')]
            ),
            dialect="ollama",
            response_format_sent=True,
        )
        for field, value in self.tampers.items():
            object.__setattr__(completion, field, value)
        return completion


@pytest.mark.parametrize(
    "tampers",
    [
        {},
        {"response": None},
        {"dialect": "vllm"},
    ],
)
def test_the_adapter_path_always_yields_a_package_owned_value(tampers):
    """No backend can put a foreign mapping into the measured value.

    ``request_structured_json`` builds the value from
    ``validate_structured_output``, which parses an exact ``str`` payload with
    ``json.loads`` under a hook returning exact dicts; ``StructuredExchange``
    then re-wraps a fresh copy. So the proxy ``_result_snapshot_bytes`` copies
    on the adapter path wraps a dict this package created - which is the entire
    provenance argument, asserted here rather than assumed.
    """
    envelope = build_envelope()
    with hermetic_guard():
        result = ob.execute_observation(
            envelope,
            exchange=ob.structured_exchange_adapter(TamperingBackend(**tampers)),
            clock=make_clock([1000, 1100]),
            reservation_decision=satisfied_for(envelope),
        )
    assert result.receipt is not None
    assert rc.serialize_receipt(result.receipt)
    if result.exchange is not None and result.exchange.ok:
        assert type(result.exchange.value) is MappingProxyType
        assert dict(result.exchange.value) == {"summary": "x"}


def test_a_backend_returning_a_foreign_object_is_refused_not_measured():
    class ForeignCompletionBackend:
        def complete_structured(self, messages, tools, **kwargs):
            return object()

    envelope = build_envelope()
    result = run(
        envelope,
        ob.structured_exchange_adapter(ForeignCompletionBackend()),
        [1000, 1100],
    )
    assert result.receipt.outcome == "unusable"
    assert result.receipt.request_refusal == "backend-not-structured-capable"


# -- attack 3: what an injected exchange is trusted for, pinned honestly -----


def test_an_injected_exchange_supplies_its_own_measurement_and_that_is_the_limit():
    """The trust boundary, asserted rather than overstated.

    ``ObservationExchange`` guarantees ``result_bytes == len(result_snapshot)``,
    so a carrier cannot claim a size its own bytes do not have. It does **not**
    guarantee those bytes describe the exchange's value: an injected exchange
    builds its own carrier, and can pair a large value with a small snapshot.

    That buys an attacker nothing - a caller who controls the exchange could
    simply have returned a small value - but the previous revision's wording
    implied a binding it does not have, so the actual behaviour is pinned here
    and recorded as limitation 13.
    """
    large = StructuredExchange(
        ok=True, value={"summary": "y" * 5000}, dialect="ollama",
        response_format_sent=True,
    )
    honest = len(ob._result_snapshot_bytes(large.value))
    assert honest > 5000

    lying = ob.ObservationExchange(exchange=large, result_snapshot=b"{}")
    assert lying.result_bytes == 2, "the carrier binds the count to its bytes..."
    assert lying.result_bytes != honest, "...but not to the value"

    envelope = build_envelope(max_result_bytes=16)
    result = run(envelope, CountingExchange(lying), [1000, 1100])
    assert result.ok is True
    assert result.receipt.result_bytes == 2
    # What it cannot do: put any of the value into the receipt.
    rendered = rc.serialize_receipt(result.receipt)
    assert b"yyyy" not in rendered
    assert len(rendered) <= rc.RECEIPT_MAX_BYTES


def test_the_canonical_adapter_measures_the_value_it_actually_received():
    """And on the path this package owns, the count is the real one."""
    payload = '{"summary": "%s"}' % ("z" * 300)
    envelope = build_envelope(max_result_bytes=4096)
    backend = FakeBackend(payload)
    result = run(envelope, ob.structured_exchange_adapter(backend), [1000, 1100])
    assert result.ok is True
    expected = len(
        json.dumps(
            dict(result.exchange.value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    )
    assert result.receipt.result_bytes == expected
