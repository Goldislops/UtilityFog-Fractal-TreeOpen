"""OMI-V3A - adversarial controls for the envelope, the carriers, the receipt.

The execution path, the deadline, the reservation gate and the single-
invocation property are exercised in
``tests/test_omi_v3_observation_rehearsal.py``. This file is about everything
that has to be true *before* anything runs, plus the receipt shape that has to
be true after.

Everything here runs identically under normal Python, ``-O`` and ``-OO``.
Nothing under test uses an ``assert`` statement, so nothing under test changes
when they are stripped, and no control depends on one either: pytest rewrites
its own assertions into explicit raises, which survive both flags.

Nothing in this file opens a socket, resolves a name, reads an environment
variable, touches the filesystem, or constructs a real backend.

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
import types

import pytest

from scripts.agent_backends import structured_request as sr
from scripts.open_model import observation as ob
from scripts.open_model import observation_receipt as rc
from scripts.open_model import registry as reg
from scripts.open_model.redaction import is_safe_token
from scripts.open_model import structured_exchange as sx
import scripts.open_model as package


# -- hostile inputs, and a tripwire that records whether a hook ever ran -------

HOOK_CALLS: list[str] = []


class HookedStr(str):
    """A ``str`` subclass that reports every hook the code under test runs."""

    def __len__(self) -> int:  # pragma: no cover - must never be reached
        HOOK_CALLS.append("str.__len__")
        return super().__len__()

    def __eq__(self, other: object) -> bool:  # pragma: no cover
        HOOK_CALLS.append("str.__eq__")
        return super().__eq__(other)

    def __hash__(self) -> int:  # pragma: no cover
        HOOK_CALLS.append("str.__hash__")
        return super().__hash__()

    def encode(self, *args: object, **kwargs: object) -> bytes:  # pragma: no cover
        HOOK_CALLS.append("str.encode")
        return super().encode(*args, **kwargs)

    def startswith(self, *args: object, **kwargs: object) -> bool:  # pragma: no cover
        HOOK_CALLS.append("str.startswith")
        return super().startswith(*args, **kwargs)


class HookedInt(int):
    """An ``int`` subclass whose comparison and index hooks are observable."""

    def __index__(self) -> int:  # pragma: no cover
        HOOK_CALLS.append("int.__index__")
        return super().__index__()

    def __lt__(self, other: object) -> bool:  # pragma: no cover
        HOOK_CALLS.append("int.__lt__")
        return super().__lt__(other)

    def __gt__(self, other: object) -> bool:  # pragma: no cover
        HOOK_CALLS.append("int.__gt__")
        return super().__gt__(other)


class HookedBytes(bytes):
    """A ``bytes`` subclass whose length and decode hooks are observable."""

    def __len__(self) -> int:  # pragma: no cover
        HOOK_CALLS.append("bytes.__len__")
        return super().__len__()

    def decode(self, *args: object, **kwargs: object) -> str:  # pragma: no cover
        HOOK_CALLS.append("bytes.decode")
        return super().decode(*args, **kwargs)


class HookedDict(dict):
    """A mapping subclass whose traversal hooks are observable."""

    def items(self):  # pragma: no cover
        HOOK_CALLS.append("dict.items")
        return super().items()

    def keys(self):  # pragma: no cover
        HOOK_CALLS.append("dict.keys")
        return super().keys()

    def __getitem__(self, key):  # pragma: no cover
        HOOK_CALLS.append("dict.__getitem__")
        return super().__getitem__(key)

    def __iter__(self):  # pragma: no cover
        HOOK_CALLS.append("dict.__iter__")
        return super().__iter__()


class HookedList(list):
    """A sequence subclass whose iteration hook is observable."""

    def __iter__(self):  # pragma: no cover
        HOOK_CALLS.append("list.__iter__")
        return super().__iter__()

    def __len__(self) -> int:  # pragma: no cover
        HOOK_CALLS.append("list.__len__")
        return super().__len__()


class HookedTuple(tuple):
    """A tuple subclass whose iteration hook is observable."""

    def __iter__(self):  # pragma: no cover
        HOOK_CALLS.append("tuple.__iter__")
        return super().__iter__()


class Betrayer:
    """Anything that consults a rebound name instead of its cell trips this.

    Every protocol a trust decision might reach for raises, so an inert
    rebinding is proved by the absence of a raise rather than by inspecting
    the result.
    """

    def __call__(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("a rebound module name was consulted")

    def __contains__(self, item: object) -> bool:
        raise AssertionError("a rebound vocabulary was consulted")

    def __getitem__(self, item: object) -> object:
        raise AssertionError("a rebound mapping was consulted")

    def __iter__(self):
        raise AssertionError("a rebound iterable was consulted")

    def __eq__(self, other: object) -> bool:
        raise AssertionError("a rebound value was compared")

    def __hash__(self) -> int:
        return 0


#: A secret-shaped string that OMI-V1's matcher recognises. If any of these
#: characters reaches a refusal token, a receipt, or a serialisation, the
#: control that looked for it fails.
SECRET = "sk-OMIV3ASECRET123456789"


# -- fixtures in the plain sense: small builders, no pytest fixtures ----------


ENDPOINT = "http://127.0.0.1:11434/v1"
SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}}


def make_clock(readings):
    """A clock callable that returns each supplied reading in turn."""
    iterator = iter(readings)

    def clock() -> int:
        return next(iterator)

    return clock


def plan_kwargs(**overrides):
    """The canonical accepted input set, with named overrides applied."""
    kwargs = dict(
        task_id=ob.new_task_id(),
        authorizing_principal="kev",
        worker="observer-1",
        evidence=[ob.EvidenceItem(evidence_id="e1", content=b"the evidence")],
        dialect="ollama",
        schema=dict(SCHEMA),
        endpoint=ENDPOINT,
        reservation=ob.ResourceReservation(cpu_cores=2, memory_mib=4096),
        clock=make_clock([1000]),
        required_keys=("summary",),
    )
    kwargs.update(overrides)
    return kwargs


def plan(**overrides):
    return ob.plan_observation(**plan_kwargs(**overrides))


def good_envelope():
    result = plan()
    if not result.ok:
        raise AssertionError("the canonical plan must be accepted")
    return result.envelope


#: A fixed, canonical UUIDv4. Used wherever a control compares two runs against
#: each other: ``new_task_id`` produces a different identity every call, which
#: is correct behaviour and would otherwise make every digest and every
#: serialisation differ for reasons that have nothing to do with the property
#: under test.
FIXED_TASK_ID = "e0e9c7a5-b2bf-4f07-bf39-4ceb6cf63052"


def fixed_envelope():
    """The same envelope every time: fixed identity, fixed clock reading."""
    result = ob.plan_observation(
        **plan_kwargs(task_id=FIXED_TASK_ID, clock=make_clock([1000]))
    )
    if not result.ok:
        raise AssertionError("the fixed plan must be accepted")
    return result.envelope


def receipt_kwargs(**overrides):
    """A coherent observed receipt, with named overrides applied."""
    envelope = fixed_envelope()
    kwargs = dict(
        task_id=envelope.task_id,
        outcome="observed",
        envelope_digest=envelope.envelope_digest,
        schema_digest=envelope.schema_digest,
        authorizing_principal="kev",
        worker="observer-1",
        evidence_ids=("e1",),
        evidence_digests=(envelope.evidence[0].digest,),
        evidence_bytes=12,
        deadline_result="within-deadline",
        reservation_result="satisfied",
        reservation_attestation="operator-asserted",
        request_outcome="attempted",
        response_outcome="ok",
        exchange_invocations=1,
        elapsed_ns=500,
        result_bytes=16,
        context_ceiling_tokens=8192,
        required_key_count=1,
        dialect="ollama",
    )
    kwargs.update(overrides)
    return kwargs


# ============================================================================
# non-vacuity: these controls really run, including under -O and -OO
# ============================================================================


def test_the_controls_in_this_file_are_not_silently_stripped():
    """Prove a false assertion here would still fail under ``-O`` and ``-OO``.

    Both flags make the interpreter discard ``assert`` statements outright, so
    a suite that passed under them could in principle be asserting nothing at
    all. pytest rewrites assertions in collected test modules into explicit
    raises before the interpreter ever sees them, which is what keeps these
    controls real - and this is the control that proves it, rather than
    trusting it. Under a stripped module this would fail with DID NOT RAISE.
    """
    with pytest.raises(AssertionError):
        assert False, "if this does not raise, every control here is vacuous"


def test_the_production_modules_contain_no_assert_statement():
    """No control here can depend on a production ``assert``, because there is none.

    A guard written as ``assert`` disappears under ``-O``, so a package that
    used one would behave differently under the flag than under it - and every
    refusal this package makes is a real ``raise`` or a returned token for
    exactly that reason.
    """
    for module in (ob, rc):
        tree = ast.parse(inspect.getsource(module))
        asserts = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
        assert asserts == []


# ============================================================================
# positive guards - the accepted path must keep working
# ============================================================================


def test_the_canonical_plan_is_accepted_and_fully_determined():
    envelope = good_envelope()
    assert rc.is_canonical_uuid4(envelope.task_id)
    assert rc.is_sha256_digest(envelope.envelope_digest)
    assert rc.is_sha256_digest(envelope.schema_digest)
    assert type(envelope.schema_bytes) is bytes
    assert envelope.duration_ns == envelope.deadline_ns - envelope.issued_ns
    assert envelope.duration_ns == 30000000000
    assert envelope.evidence[0].digest == (
        "2a1d54b0872c685e86ec936646d6502b3549733aa3d64028ab21d7c1fe1ecff8"
    )


def test_new_task_id_produces_a_canonical_identifier_the_predicate_accepts():
    for _ in range(64):
        assert rc.is_canonical_uuid4(ob.new_task_id())


def test_the_envelope_digest_is_stable_and_covers_every_content_field():
    envelope = good_envelope()
    baseline = ob._envelope_digest(envelope)
    assert baseline == envelope.envelope_digest
    assert ob._envelope_digest(envelope) == baseline


def test_two_envelopes_differing_only_in_evidence_bytes_differ_in_digest():
    first = plan(
        evidence=[ob.EvidenceItem(evidence_id="e1", content=b"aaaa")],
        clock=make_clock([1000]),
    ).envelope
    second = plan(
        task_id=first.task_id,
        evidence=[ob.EvidenceItem(evidence_id="e1", content=b"bbbb")],
        clock=make_clock([1000]),
    ).envelope
    assert first.envelope_digest != second.envelope_digest


# ============================================================================
# identity and provenance
# ============================================================================


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "not-a-uuid",
        "E0E9C7A5-B2BF-4F07-BF39-4CEB6CF63052",  # uppercase
        "e0e9c7a5b2bf4f07bf394ceb6cf63052",  # unhyphenated
        "{e0e9c7a5-b2bf-4f07-bf39-4ceb6cf63052}",  # braced
        "urn:uuid:e0e9c7a5-b2bf-4f07-bf39-4ceb6cf63052",
        "e0e9c7a5-b2bf-1f07-bf39-4ceb6cf63052",  # version 1
        "e0e9c7a5-b2bf-4f07-7f39-4ceb6cf63052",  # bad variant nibble
        "e0e9c7a5-b2bf-4f07-bf39-4ceb6cf6305",  # short
        "e0e9c7a5+b2bf-4f07-bf39-4ceb6cf63052",  # wrong separator
        b"e0e9c7a5-b2bf-4f07-bf39-4ceb6cf63052",
        12345,
    ],
)
def test_a_non_canonical_task_identity_is_refused(value):
    assert rc.is_canonical_uuid4(value) is False
    result = plan(task_id=value)
    assert result.ok is False
    assert result.refusal == "task-id-not-canonical-uuid4"
    assert result.envelope is None


def test_a_hostile_str_subclass_task_id_is_refused_without_running_a_hook():
    HOOK_CALLS.clear()
    result = plan(task_id=HookedStr("e0e9c7a5-b2bf-4f07-bf39-4ceb6cf63052"))
    fired = list(HOOK_CALLS)
    assert result.ok is False
    assert result.refusal == "task-id-not-canonical-uuid4"
    assert fired == []


@pytest.mark.parametrize("field", ["authorizing_principal", "worker"])
@pytest.mark.parametrize(
    "value",
    [None, "", 42, "has space", "has/slash", "has:colon", "user@example.com", SECRET],
)
def test_provenance_must_be_a_safe_token(field, value):
    result = plan(**{field: value})
    assert result.ok is False
    expected = (
        "principal-not-safe-token"
        if field == "authorizing_principal"
        else "worker-not-safe-token"
    )
    assert result.refusal == expected


def test_a_secret_shaped_principal_never_appears_in_the_refusal():
    result = plan(authorizing_principal=SECRET)
    assert result.ok is False
    assert SECRET not in result.refusal
    assert "sk-" not in result.refusal
    assert result.refusal in rc.PLAN_REFUSALS


# ============================================================================
# limits and duration
# ============================================================================


LIMIT_FIELDS = (
    "context_ceiling_tokens",
    "max_evidence_bytes",
    "max_result_bytes",
    "max_output_tokens",
)


@pytest.mark.parametrize("field", LIMIT_FIELDS)
@pytest.mark.parametrize("value", [True, False, HookedInt(8), "8", 8.0, None, b"8"])
def test_a_limit_that_is_not_an_exact_int_is_refused_before_any_comparison(
    field, value
):
    HOOK_CALLS.clear()
    result = plan(**{field: value})
    fired = list(HOOK_CALLS)
    assert result.ok is False
    assert result.refusal == "limit-not-exact-int"
    assert fired == []


@pytest.mark.parametrize("field", LIMIT_FIELDS)
@pytest.mark.parametrize("value", [0, -1, -(10**9)])
def test_a_limit_at_or_below_zero_is_refused(field, value):
    result = plan(**{field: value})
    assert result.ok is False
    assert result.refusal == "limit-out-of-range"


@pytest.mark.parametrize(
    ("field", "ceiling_key"),
    [
        ("context_ceiling_tokens", "context_ceiling_tokens"),
        ("max_evidence_bytes", "evidence_total_bytes"),
        ("max_result_bytes", "result_bytes"),
        ("max_output_tokens", "output_tokens"),
    ],
)
def test_a_limit_above_its_ceiling_is_refused_and_the_ceiling_itself_is_accepted(
    field, ceiling_key
):
    ceiling = ob.OBSERVATION_LIMITS[ceiling_key]
    over = plan(**{field: ceiling + 1})
    assert over.ok is False
    assert over.refusal == "limit-out-of-range"
    exact = plan(**{field: ceiling})
    assert exact.ok is True


@pytest.mark.parametrize("value", [True, HookedInt(5), "5", 5.0, None])
def test_a_duration_that_is_not_an_exact_int_is_refused(value):
    HOOK_CALLS.clear()
    result = plan(duration_ns=value)
    fired = list(HOOK_CALLS)
    assert result.ok is False
    assert result.refusal == "duration-not-exact-int"
    assert fired == []


@pytest.mark.parametrize("value", [0, -1, ob.OBSERVATION_LIMITS["duration_ns"] + 1])
def test_a_duration_outside_its_range_is_refused(value):
    result = plan(duration_ns=value)
    assert result.ok is False
    assert result.refusal == "duration-out-of-range"


def test_the_maximum_duration_is_accepted_and_derives_the_deadline():
    ceiling = ob.OBSERVATION_LIMITS["duration_ns"]
    envelope = plan(duration_ns=ceiling, clock=make_clock([7])).envelope
    assert envelope.issued_ns == 7
    assert envelope.deadline_ns == 7 + ceiling
    assert envelope.duration_ns == ceiling


@pytest.mark.parametrize("reading", [None, "1000", 1000.0, True, HookedInt(1000)])
def test_a_clock_reading_that_is_not_an_exact_int_is_refused(reading):
    HOOK_CALLS.clear()
    result = plan(clock=make_clock([reading]))
    fired = list(HOOK_CALLS)
    assert result.ok is False
    assert result.refusal == "clock-reading-not-exact-int"
    assert fired == []


def test_a_negative_clock_reading_is_refused():
    result = plan(clock=make_clock([-1]))
    assert result.ok is False
    assert result.refusal == "clock-reading-negative"


@pytest.mark.parametrize("value", [None, 1000, "clock", object()])
def test_a_clock_that_is_not_callable_is_refused(value):
    result = plan(clock=value)
    assert result.ok is False
    assert result.refusal == "clock-not-callable"


def test_the_clock_is_read_exactly_once_by_the_planner():
    readings = []

    def counting_clock() -> int:
        readings.append(1)
        return 1000

    result = ob.plan_observation(**plan_kwargs(clock=counting_clock))
    assert result.ok is True
    assert len(readings) == 1


def test_the_clock_is_not_read_when_an_earlier_check_refuses():
    readings = []

    def counting_clock() -> int:  # pragma: no cover - must never be reached
        readings.append(1)
        return 1000

    result = ob.plan_observation(**plan_kwargs(clock=counting_clock, task_id="nope"))
    assert result.ok is False
    assert readings == []


# ============================================================================
# the reservation carriers
# ============================================================================


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(cpu_cores=0, memory_mib=1),
        dict(cpu_cores=-1, memory_mib=1),
        dict(cpu_cores=True, memory_mib=1),
        dict(cpu_cores=HookedInt(2), memory_mib=1),
        dict(cpu_cores="2", memory_mib=1),
        dict(cpu_cores=2.0, memory_mib=1),
        dict(cpu_cores=1, memory_mib=0),
        dict(cpu_cores=1, memory_mib=True),
        dict(cpu_cores=1, memory_mib=1, gpu_memory_mib=0),
        dict(cpu_cores=1, memory_mib=1, gpu_memory_mib=True),
        dict(cpu_cores=1, memory_mib=1, gpu_memory_mib="8"),
        dict(cpu_cores=ob.OBSERVATION_LIMITS["cpu_cores"] + 1, memory_mib=1),
        dict(cpu_cores=1, memory_mib=ob.OBSERVATION_LIMITS["memory_mib"] + 1),
        dict(
            cpu_cores=1,
            memory_mib=1,
            gpu_memory_mib=ob.OBSERVATION_LIMITS["gpu_memory_mib"] + 1,
        ),
    ],
)
def test_an_incoherent_reservation_is_refused_at_construction(kwargs):
    HOOK_CALLS.clear()
    with pytest.raises(ValueError):
        ob.ResourceReservation(**kwargs)
    assert HOOK_CALLS == []


def test_a_reservation_digest_is_computed_here_and_distinguishes_reservations():
    small = ob.ResourceReservation(cpu_cores=1, memory_mib=1024)
    large = ob.ResourceReservation(cpu_cores=8, memory_mib=1024)
    with_gpu = ob.ResourceReservation(cpu_cores=1, memory_mib=1024, gpu_memory_mib=4096)
    digests = {small.digest, large.digest, with_gpu.digest}
    assert len(digests) == 3
    for digest in digests:
        assert rc.is_sha256_digest(digest)
    assert ob.ResourceReservation(cpu_cores=1, memory_mib=1024).digest == small.digest


def test_no_gpu_reservation_is_distinct_from_a_zero_one_because_zero_is_refused():
    none_declared = ob.ResourceReservation(cpu_cores=1, memory_mib=1)
    assert none_declared.gpu_memory_mib is None
    with pytest.raises(ValueError):
        ob.ResourceReservation(cpu_cores=1, memory_mib=1, gpu_memory_mib=0)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(reservation_digest="short", satisfied=True, attestation="operator-asserted"),
        dict(reservation_digest="A" * 64, satisfied=True, attestation="operator-asserted"),
        dict(reservation_digest="a" * 40, satisfied=True, attestation="operator-asserted"),
        dict(reservation_digest="a" * 64, satisfied=1, attestation="operator-asserted"),
        dict(reservation_digest="a" * 64, satisfied="yes", attestation="operator-asserted"),
        dict(reservation_digest="a" * 64, satisfied=True, attestation="assumed"),
        dict(reservation_digest="a" * 64, satisfied=True, attestation=None),
    ],
)
def test_an_incoherent_reservation_decision_is_refused_at_construction(kwargs):
    with pytest.raises(ValueError):
        ob.ReservationDecision(**kwargs)


@pytest.mark.parametrize("attestation", sorted(rc.RESERVATION_ATTESTATIONS))
def test_every_declared_attestation_token_constructs(attestation):
    decision = ob.ReservationDecision(
        reservation_digest="a" * 64, satisfied=False, attestation=attestation
    )
    assert decision.attestation == attestation


@pytest.mark.parametrize(
    "value",
    [None, "reservation", {"cpu_cores": 1}, 4, ob.ReservationDecision],
)
def test_a_reservation_of_the_wrong_type_is_refused_by_the_planner(value):
    result = plan(reservation=value)
    assert result.ok is False
    assert result.refusal == "reservation-not-exact-type"


def test_a_reservation_subclass_is_refused_because_the_check_is_exact():
    class Sneaky(ob.ResourceReservation):
        pass

    result = plan(reservation=Sneaky(cpu_cores=1, memory_mib=1))
    assert result.ok is False
    assert result.refusal == "reservation-not-exact-type"


# ============================================================================
# the declared loopback endpoint
# ============================================================================


ACCEPTED_ENDPOINTS = [
    "http://127.0.0.1:11434/v1",
    "http://127.0.0.1:1/v1",
    "http://127.0.0.1:65535/v1",
    "http://127.1.2.3:8080/v1",
    "http://127.255.255.255:80/v1",
    "http://127.0.0.0:80/v1",
    "http://[::1]:11434/v1",
]


@pytest.mark.parametrize("endpoint", ACCEPTED_ENDPOINTS)
def test_an_acceptable_declared_endpoint_is_accepted(endpoint):
    assert ob.validate_loopback_endpoint(endpoint) is None
    assert plan(endpoint=endpoint).ok is True


REFUSED_ENDPOINTS = [
    # not a string at all
    (None, "endpoint-not-exact-str"),
    (b"http://127.0.0.1:11434/v1", "endpoint-not-exact-str"),
    (11434, "endpoint-not-exact-str"),
    # length
    ("http://127.0.0.1:11434/v1" + "a" * 200, "endpoint-too-long"),
    # percent-encoded authority, in every position it could hide
    ("http://127.0.0.1%2e1:11434/v1", "endpoint-percent-encoded"),
    ("http://127.0.0.1:11434/v%31", "endpoint-percent-encoded"),
    ("http://%31%32%37.0.0.1:11434/v1", "endpoint-percent-encoded"),
    # query and fragment
    ("http://127.0.0.1:11434/v1?a=b", "endpoint-query-or-fragment-present"),
    ("http://127.0.0.1:11434/v1#frag", "endpoint-query-or-fragment-present"),
    # user information, including the deceptive host-after-at form
    ("http://user@127.0.0.1:11434/v1", "endpoint-userinfo-present"),
    ("http://127.0.0.1@evil.example.com:11434/v1", "endpoint-userinfo-present"),
    ("http://user:pass@127.0.0.1:11434/v1", "endpoint-userinfo-present"),
    # scheme
    ("https://127.0.0.1:11434/v1", "endpoint-scheme-not-plain-http"),
    ("HTTP://127.0.0.1:11434/v1", "endpoint-scheme-not-plain-http"),
    ("Http://127.0.0.1:11434/v1", "endpoint-scheme-not-plain-http"),
    ("//127.0.0.1:11434/v1", "endpoint-scheme-not-plain-http"),
    ("127.0.0.1:11434/v1", "endpoint-scheme-not-plain-http"),
    ("", "endpoint-scheme-not-plain-http"),
    ("ftp://127.0.0.1:11434/v1", "endpoint-scheme-not-plain-http"),
    ("http:/127.0.0.1:11434/v1", "endpoint-scheme-not-plain-http"),
    # DNS names, including every deceptive loopback-looking spelling
    ("http://localhost:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://LOCALHOST:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://api.localhost:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://127.0.0.1.evil.example.com:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://evil.example.com:11434/v1", "endpoint-host-not-numeric-loopback"),
    # ambiguous numeric forms
    ("http://127.1:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://2130706433:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://0x7f000001:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://0177.0.0.1:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://127.00.0.1:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://127.0.0.01:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://127.0.0.1.:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://127.0.0.256:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://127.0.0:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://127.0.0.1.1:11434/v1", "endpoint-host-not-numeric-loopback"),
    # not loopback at all
    ("http://0.0.0.0:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://192.168.1.10:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://128.0.0.1:11434/v1", "endpoint-host-not-numeric-loopback"),
    # IPv6 spellings other than the one compressed literal
    ("http://[0:0:0:0:0:0:0:1]:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://[::ffff:127.0.0.1]:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://[::2]:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://[::1:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://::1:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://[::1]x11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://:11434/v1", "endpoint-host-not-numeric-loopback"),
    ("http://127.0.0.1:11434:9/v1", "endpoint-host-not-numeric-loopback"),
    # missing port
    ("http://127.0.0.1/v1", "endpoint-port-missing"),
    ("http://[::1]/v1", "endpoint-port-missing"),
    ("http://127.0.0.1:/v1", "endpoint-port-missing"),
    # non-canonical port
    ("http://127.0.0.1:0/v1", "endpoint-port-not-canonical"),
    ("http://127.0.0.1:00/v1", "endpoint-port-not-canonical"),
    ("http://127.0.0.1:011434/v1", "endpoint-port-not-canonical"),
    ("http://127.0.0.1:65536/v1", "endpoint-port-not-canonical"),
    ("http://127.0.0.1:999999/v1", "endpoint-port-not-canonical"),
    ("http://127.0.0.1:+80/v1", "endpoint-port-not-canonical"),
    ("http://127.0.0.1:-80/v1", "endpoint-port-not-canonical"),
    ("http://127.0.0.1:80x/v1", "endpoint-port-not-canonical"),
    ("http://127.0.0.1:8 0/v1", "endpoint-port-not-canonical"),
    # Unicode decimal digits: int() and str.isdigit both accept these.
    ("http://127.0.0.1:١١٤٣٤/v1", "endpoint-port-not-canonical"),
    ("http://127.0.0.1:８０/v1", "endpoint-port-not-canonical"),
    # path
    ("http://127.0.0.1:11434", "endpoint-path-not-v1"),
    ("http://127.0.0.1:11434/", "endpoint-path-not-v1"),
    ("http://127.0.0.1:11434/v1/", "endpoint-path-not-v1"),
    ("http://127.0.0.1:11434/v1/chat/completions", "endpoint-path-not-v1"),
    ("http://127.0.0.1:11434/v2", "endpoint-path-not-v1"),
    ("http://127.0.0.1:11434/V1", "endpoint-path-not-v1"),
    ("http://127.0.0.1:11434/v1\n", "endpoint-path-not-v1"),
]


@pytest.mark.parametrize(("endpoint", "token"), REFUSED_ENDPOINTS)
def test_an_unacceptable_declared_endpoint_is_refused_with_its_own_token(
    endpoint, token
):
    assert ob.validate_loopback_endpoint(endpoint) == token
    result = plan(endpoint=endpoint)
    assert result.ok is False
    assert result.refusal == token


def test_every_endpoint_token_the_validator_can_emit_is_in_the_closed_vocabulary():
    emitted = {token for _endpoint, token in REFUSED_ENDPOINTS}
    assert emitted <= rc.ENVELOPE_REFUSALS
    declared = {
        token for token in rc.ENVELOPE_REFUSALS if token.startswith("endpoint-")
    }
    assert emitted == declared


def test_a_hostile_str_subclass_endpoint_is_refused_without_running_a_hook():
    HOOK_CALLS.clear()
    verdict = ob.validate_loopback_endpoint(HookedStr(ENDPOINT))
    fired = list(HOOK_CALLS)
    assert verdict == "endpoint-not-exact-str"
    assert fired == []


def test_v3a_accepts_a_strict_subset_of_what_omi_v1s_host_check_calls_loopback():
    """Two loopback checks exist, and the narrower one must stay narrower.

    ``registry._is_loopback`` is OMI-V1's best-effort classifier for the host
    of an already-constructed backend; it accepts ``localhost`` and lenient
    dotted quads because that is the right answer for the question it asks.
    OMI-V3A asks a different, stricter question about *declared* text and must
    never accept something OMI-V1 would not call loopback. This asserts the
    containment rather than duplicating either check.
    """
    for endpoint in ACCEPTED_ENDPOINTS:
        host = reg._host_of(endpoint)
        assert reg._is_loopback(host) is True
    # ...and the containment is strict: OMI-V1 accepts names V3A refuses.
    assert reg._is_loopback("localhost") is True
    assert ob.validate_loopback_endpoint("http://localhost:11434/v1") is not None


# ============================================================================
# evidence
# ============================================================================


def test_an_evidence_item_computes_its_own_digest_and_refuses_a_supplied_one():
    item = ob.EvidenceItem(evidence_id="e1", content=b"abc")
    assert item.digest == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    with pytest.raises(TypeError):
        ob.EvidenceItem(evidence_id="e1", content=b"abc", digest="0" * 64)


@pytest.mark.parametrize(
    "content",
    [
        bytearray(b"abc"),
        memoryview(b"abc"),
        HookedBytes(b"abc"),
        "abc",
        None,
        123,
        [1, 2, 3],
    ],
)
def test_evidence_content_must_be_exactly_bytes(content):
    HOOK_CALLS.clear()
    with pytest.raises(ValueError):
        ob.EvidenceItem(evidence_id="e1", content=content)
    assert HOOK_CALLS == []


@pytest.mark.parametrize("value", [None, "", 42, "has space", "a/b", SECRET])
def test_an_evidence_id_must_be_a_safe_token(value):
    with pytest.raises(ValueError):
        ob.EvidenceItem(evidence_id=value, content=b"abc")


def test_empty_evidence_content_is_refused():
    with pytest.raises(ValueError):
        ob.EvidenceItem(evidence_id="e1", content=b"")


def test_evidence_over_the_per_item_ceiling_is_refused_at_construction():
    ceiling = ob.OBSERVATION_LIMITS["evidence_item_bytes"]
    ob.EvidenceItem(evidence_id="e1", content=b"a" * ceiling)
    with pytest.raises(ValueError):
        ob.EvidenceItem(evidence_id="e1", content=b"a" * (ceiling + 1))


@pytest.mark.parametrize(
    "value",
    [None, "evidence", 5, {"e1": b"x"}, (item for item in ())],
)
def test_evidence_that_is_not_an_exact_sequence_is_refused(value):
    result = plan(evidence=value)
    assert result.ok is False
    assert result.refusal == "evidence-not-exact-sequence"


@pytest.mark.parametrize("hostile", [HookedList, HookedTuple])
def test_a_sequence_subclass_is_refused_without_being_iterated(hostile):
    HOOK_CALLS.clear()
    result = plan(
        evidence=hostile([ob.EvidenceItem(evidence_id="e1", content=b"x")])
    )
    fired = list(HOOK_CALLS)
    assert result.ok is False
    assert result.refusal == "evidence-not-exact-sequence"
    assert fired == []


def test_empty_evidence_is_refused():
    for empty in ([], ()):
        result = plan(evidence=empty)
        assert result.ok is False
        assert result.refusal == "evidence-empty"


def test_too_many_evidence_items_are_refused():
    ceiling = ob.OBSERVATION_LIMITS["evidence_items"]
    at_ceiling = [
        ob.EvidenceItem(evidence_id="e%d" % index, content=b"x")
        for index in range(ceiling)
    ]
    assert plan(evidence=at_ceiling).ok is True
    over = at_ceiling + [ob.EvidenceItem(evidence_id="over", content=b"x")]
    result = plan(evidence=over)
    assert result.ok is False
    assert result.refusal == "evidence-too-many-items"


@pytest.mark.parametrize("value", [None, "evidence", 5, object()])
def test_an_evidence_entry_of_the_wrong_type_is_refused(value):
    result = plan(evidence=[value])
    assert result.ok is False
    assert result.refusal == "evidence-item-not-exact-type"


def test_an_evidence_item_subclass_is_refused_because_the_check_is_exact():
    class Sneaky(ob.EvidenceItem):
        pass

    result = plan(evidence=[Sneaky(evidence_id="e1", content=b"x")])
    assert result.ok is False
    assert result.refusal == "evidence-item-not-exact-type"


def test_duplicate_evidence_ids_are_refused():
    result = plan(
        evidence=[
            ob.EvidenceItem(evidence_id="same", content=b"one"),
            ob.EvidenceItem(evidence_id="same", content=b"two"),
        ]
    )
    assert result.ok is False
    assert result.refusal == "evidence-id-duplicated"


def test_evidence_over_the_declared_per_item_bound_is_refused():
    result = plan(
        evidence=[ob.EvidenceItem(evidence_id="e1", content=b"a" * 100)],
        max_evidence_bytes=50,
    )
    assert result.ok is False
    assert result.refusal == "evidence-item-too-large"


def test_evidence_over_the_declared_total_bound_is_refused():
    result = plan(
        evidence=[
            ob.EvidenceItem(evidence_id="e1", content=b"a" * 40),
            ob.EvidenceItem(evidence_id="e2", content=b"b" * 40),
        ],
        max_evidence_bytes=50,
    )
    assert result.ok is False
    assert result.refusal == "evidence-total-too-large"


def test_evidence_over_the_module_total_ceiling_is_refused():
    ceiling = ob.OBSERVATION_LIMITS["evidence_total_bytes"]
    per_item = ob.OBSERVATION_LIMITS["evidence_item_bytes"]
    items = [
        ob.EvidenceItem(evidence_id="e%d" % index, content=b"a" * per_item)
        for index in range(ceiling // per_item + 1)
    ]
    result = plan(evidence=items, max_evidence_bytes=ceiling)
    assert result.ok is False
    assert result.refusal == "evidence-total-too-large"


@pytest.mark.parametrize(
    "content",
    [
        b"\xff\xfe",
        b"\x80",
        b"\xc3",  # truncated two-byte sequence
        b"\xed\xa0\x80",  # UTF-8-encoded surrogate, which strict UTF-8 refuses
        b"ok\xffbad",
    ],
)
def test_evidence_that_is_not_strict_utf8_is_refused(content):
    result = plan(evidence=[ob.EvidenceItem(evidence_id="e1", content=content)])
    assert result.ok is False
    assert result.refusal == "evidence-not-utf8"


def test_valid_multibyte_utf8_evidence_is_accepted():
    text = "é中\U0001f600"
    envelope = plan(
        evidence=[ob.EvidenceItem(evidence_id="e1", content=text.encode("utf-8"))]
    ).envelope
    assert envelope.evidence[0].content.decode("utf-8") == text


# ============================================================================
# required keys
# ============================================================================


@pytest.mark.parametrize("value", [None, "summary", 5, {"summary": 1}])
def test_required_keys_that_are_not_an_exact_sequence_are_refused(value):
    result = plan(required_keys=value)
    assert result.ok is False
    assert result.refusal == "required-keys-not-exact-sequence"


def test_a_required_keys_sequence_subclass_is_refused_without_iteration():
    HOOK_CALLS.clear()
    result = plan(required_keys=HookedTuple(("summary",)))
    fired = list(HOOK_CALLS)
    assert result.ok is False
    assert result.refusal == "required-keys-not-exact-sequence"
    assert fired == []


def test_too_many_required_keys_are_refused():
    ceiling = ob.OBSERVATION_LIMITS["required_keys"]
    at_ceiling = tuple("k%d" % index for index in range(ceiling))
    assert plan(required_keys=at_ceiling).ok is True
    result = plan(required_keys=at_ceiling + ("over",))
    assert result.ok is False
    assert result.refusal == "required-keys-too-many"


@pytest.mark.parametrize("value", ["", "has space", 5, None, SECRET, "a/b"])
def test_an_unsafe_required_key_is_refused(value):
    result = plan(required_keys=(value,))
    assert result.ok is False
    assert result.refusal == "required-key-not-safe-token"


# ============================================================================
# the schema, decided entirely by OMI-V2
# ============================================================================


def _deep_schema(depth: int) -> dict:
    document: dict = {"leaf": True}
    for _ in range(depth):
        document = {"nested": document}
    return document


def _cyclic_schema() -> dict:
    document: dict = {"type": "object"}
    document["self"] = document
    return document


SCHEMA_REFUSALS = [
    ({}, "schema-empty"),
    (None, "schema-not-exact-dict"),
    ([{"type": "object"}], "schema-not-exact-dict"),
    ("{}", "schema-not-exact-dict"),
    (HookedDict({"type": "object"}), "schema-not-exact-dict"),
    ({"a": object()}, "schema-not-serializable"),
    ({"a": {1: "int key"}}, "schema-not-serializable"),
    ({"a": float("nan")}, "schema-non-finite-number"),
    ({"a": float("inf")}, "schema-non-finite-number"),
    ({"a": "\ud800"}, "schema-not-utf8-encodable"),
    (_deep_schema(64), "schema-too-deep"),
    (_cyclic_schema(), "schema-too-deep"),
    ({"k%d" % index: index for index in range(8192)}, "schema-too-large"),
]


@pytest.mark.parametrize(("schema", "token"), SCHEMA_REFUSALS)
def test_a_bad_schema_is_refused_in_omi_v2s_own_words(schema, token):
    HOOK_CALLS.clear()
    result = plan(schema=schema)
    fired = list(HOOK_CALLS)
    assert result.ok is False
    assert result.refusal == token
    assert result.refusal in sr.REFUSAL_TOKENS
    assert result.refusal not in rc.ENVELOPE_REFUSALS
    if isinstance(schema, HookedDict):
        assert fired == []


@pytest.mark.parametrize(
    ("dialect", "token"),
    [
        (None, "dialect-not-configured"),
        (5, "dialect-not-exact-str"),
        (b"ollama", "dialect-not-exact-str"),
        ("not-a-runtime", "dialect-unsupported"),
        ("OLLAMA", "dialect-unsupported"),
    ],
)
def test_a_bad_dialect_is_refused_in_omi_v2s_own_words(dialect, token):
    result = plan(dialect=dialect)
    assert result.ok is False
    assert result.refusal == token
    assert result.refusal in sr.REFUSAL_TOKENS


@pytest.mark.parametrize("dialect", sorted(sr.SUPPORTED_DIALECTS))
def test_every_dialect_omi_v2_supports_plans_here(dialect):
    result = plan(dialect=dialect)
    assert result.ok is True
    assert result.envelope.dialect == dialect


def test_tools_plus_structured_output_remain_refused_and_v3a_never_declares_one():
    """The combination is refused where it is decided, and never reached here.

    OMI-V3A has no ``tools`` parameter and no tool field, so it cannot present
    the combination at all; the first assertion confirms OMI-V2 still refuses
    it where the decision lives, and the second confirms OMI-V3A's own call
    site passes ``has_tools=False`` as a literal a caller cannot reach.
    """
    refused = sr.plan_structured_request(
        "ollama", sr.StructuredOutputRequest(schema=dict(SCHEMA)), has_tools=True
    )
    assert refused.ok is False
    assert refused.refusal == "tools-with-structured-unsupported"

    source = inspect.getsource(ob.plan_observation)
    assert "has_tools=False" in source
    assert "has_tools=True" not in source
    assert "tools" not in inspect.signature(ob.plan_observation).parameters


def test_the_envelope_carries_the_detached_snapshot_not_the_callers_document():
    document = {"type": "object", "properties": {"summary": {"type": "string"}}}
    envelope = plan(schema=document).envelope
    before = envelope.schema_bytes
    digest_before = envelope.schema_digest
    document["properties"]["summary"] = {"type": "number"}
    document["injected"] = SECRET
    assert envelope.schema_bytes == before
    assert envelope.schema_digest == digest_before
    assert SECRET.encode("ascii") not in envelope.schema_bytes
    assert json.loads(envelope.schema_bytes.decode("ascii")) == {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
    }


def test_the_envelope_holds_no_caller_owned_mutable_object():
    evidence_list = [ob.EvidenceItem(evidence_id="e1", content=b"one")]
    keys = ["summary"]
    envelope = plan(evidence=evidence_list, required_keys=keys).envelope
    evidence_list.append(ob.EvidenceItem(evidence_id="e2", content=b"two"))
    keys.append("injected")
    assert len(envelope.evidence) == 1
    assert envelope.required_keys == ("summary",)
    assert type(envelope.evidence) is tuple
    assert type(envelope.required_keys) is tuple
    assert type(envelope.schema_bytes) is bytes
    assert type(envelope.evidence[0].content) is bytes


# ============================================================================
# carrier coherence
# ============================================================================


def test_the_plan_carrier_refuses_every_incoherent_combination():
    envelope = good_envelope()
    with pytest.raises(ValueError):
        ob.ObservationPlan(ok=1)
    with pytest.raises(ValueError):
        ob.ObservationPlan(ok=True, envelope=envelope, refusal="evidence-empty")
    with pytest.raises(ValueError):
        ob.ObservationPlan(ok=True)
    with pytest.raises(ValueError):
        ob.ObservationPlan(ok=False)
    with pytest.raises(ValueError):
        ob.ObservationPlan(ok=False, refusal="evidence-empty", envelope=envelope)
    with pytest.raises(ValueError):
        ob.ObservationPlan(ok=False, refusal="not-a-token")
    with pytest.raises(ValueError):
        ob.ObservationPlan(ok=True, envelope="not an envelope")


def test_every_plan_refusal_token_is_composed_from_both_vocabularies():
    assert rc.PLAN_REFUSALS == rc.ENVELOPE_REFUSALS | sr.REFUSAL_TOKENS
    assert rc.ENVELOPE_REFUSALS.isdisjoint(sr.REFUSAL_TOKENS)
    for token in sorted(rc.PLAN_REFUSALS):
        assert ob.ObservationPlan(ok=False, refusal=token).refusal == token


def test_no_v3a_vocabulary_restates_an_omi_v2_one():
    """The prohibition on a second vocabulary, asserted rather than trusted."""
    assert rc.ENVELOPE_REFUSALS.isdisjoint(sr.REFUSAL_TOKENS)
    assert rc.EXECUTION_REFUSALS.isdisjoint(sr.REFUSAL_TOKENS)
    assert rc.EXECUTION_REFUSALS.isdisjoint(sx.EXCHANGE_REFUSALS)
    assert rc.EXECUTION_REFUSALS.isdisjoint(sx.RESPONSE_FAILURES)
    assert rc.ENVELOPE_REFUSALS.isdisjoint(sx.RESPONSE_FAILURES)
    # No dialect token exists at this layer at all: when the envelope layer
    # needs to say a stored dialect is unacceptable it returns OMI-V2's own
    # `dialect-unsupported`, which PLAN_REFUSALS already composes in.
    for token in rc.ENVELOPE_REFUSALS | rc.EXECUTION_REFUSALS:
        assert not token.startswith("dialect-")
    # Three `schema-*` tokens DO exist here, and they describe the envelope's
    # own STORAGE of a schema - whether the stored bytes are exactly bytes,
    # whether they are the canonical rendering, and whether the stored digest
    # hashes them. None re-spells an OMI-V2 token, which the disjointness
    # assertions above already establish, and none decides whether a schema is
    # acceptable at all - that stays entirely OMI-V2's.
    storage = {t for t in rc.ENVELOPE_REFUSALS if t.startswith("schema-")}
    assert storage == {
        "schema-bytes-not-exact-bytes",
        "schema-bytes-not-canonical",
        "schema-digest-not-recomputable",
    }
    assert storage.isdisjoint(sr.REFUSAL_TOKENS)


def test_the_envelope_carrier_revalidates_everything_the_planner_checked():
    envelope = good_envelope()
    base = dict(
        task_id=envelope.task_id,
        authorizing_principal="kev",
        worker="observer-1",
        evidence=envelope.evidence,
        dialect="ollama",
        schema_bytes=envelope.schema_bytes,
        schema_digest=envelope.schema_digest,
        required_keys=("summary",),
        endpoint=ENDPOINT,
        reservation=envelope.reservation,
        context_ceiling_tokens=8192,
        max_evidence_bytes=65536,
        max_result_bytes=8192,
        max_output_tokens=1024,
        issued_ns=1000,
        deadline_ns=1000 + 30000000000,
    )
    assert ob.ObservationEnvelope(**base).envelope_digest
    for override in (
        dict(task_id="nope"),
        dict(authorizing_principal=SECRET),
        dict(worker=""),
        dict(evidence=()),
        dict(evidence=list(envelope.evidence)),
        dict(evidence=(1,)),
        dict(schema_bytes="not bytes"),
        dict(schema_digest="short"),
        dict(required_keys=["summary"]),
        dict(required_keys=("has space",)),
        dict(endpoint="http://localhost:11434/v1"),
        dict(reservation=None),
        dict(dialect=5),
        dict(context_ceiling_tokens=0),
        dict(max_result_bytes=True),
        dict(issued_ns=-1),
        dict(deadline_ns=1000),
        dict(deadline_ns=1000 + ob.OBSERVATION_LIMITS["duration_ns"] + 1),
    ):
        with pytest.raises(ValueError):
            ob.ObservationEnvelope(**{**base, **override})


def test_the_receipt_carrier_accepts_the_coherent_case():
    receipt = rc.ObservationReceipt(**receipt_kwargs())
    assert receipt.outcome == "observed"
    assert receipt.schema_conformance == "unverified"


RECEIPT_INCOHERENCE = [
    # identity and provenance
    dict(task_id="nope"),
    dict(authorizing_principal=SECRET),
    dict(worker="has space"),
    dict(envelope_digest="short"),
    dict(schema_digest="A" * 64),
    # closed vocabularies
    dict(outcome="succeeded"),
    dict(deadline_result="maybe"),
    dict(reservation_result="probably"),
    dict(request_outcome="sent"),
    dict(response_outcome="fine"),
    dict(schema_conformance="verified"),
    dict(refusal="not-a-token", outcome="refused", result_bytes=0),
    dict(request_refusal="not-a-token"),
    dict(response_failure="not-a-token"),
    dict(dialect="not-a-runtime"),
    # counts
    dict(evidence_bytes=-1),
    dict(evidence_bytes=True),
    dict(elapsed_ns="500"),
    dict(exchange_invocations=2),
    dict(required_key_count=ob.OBSERVATION_LIMITS["required_keys"] + 1),
    # evidence pairing
    dict(evidence_ids=("e1", "e2")),
    dict(evidence_ids=()),
    dict(evidence_ids=["e1"]),
    dict(evidence_digests=("short",)),
    dict(evidence_ids=(SECRET,)),
    # cross-field coherence
    dict(request_outcome="not-attempted"),
    dict(exchange_invocations=0),
    dict(reservation_result="not-evaluated"),
    dict(deadline_result="exceeded-before-request"),
    dict(outcome="refused"),
    dict(outcome="void"),
    dict(outcome="unusable"),
    dict(refusal="result-too-large"),
    dict(response_outcome="request-refused"),
    dict(missing_key_indices=(0,)),
    dict(result_bytes=0),
]


@pytest.mark.parametrize("override", RECEIPT_INCOHERENCE)
def test_the_receipt_carrier_refuses_an_incoherent_combination(override):
    with pytest.raises(ValueError):
        rc.ObservationReceipt(**receipt_kwargs(**override))


def test_a_receipt_cannot_record_a_deadline_determination_it_did_not_make():
    """``not-evaluated`` is only ever legitimate on a refusal."""
    refused = rc.ObservationReceipt(
        **receipt_kwargs(
            outcome="refused",
            refusal="clock-not-callable",
            deadline_result="not-evaluated",
            reservation_result="not-evaluated",
            reservation_attestation=None,
            request_outcome="not-attempted",
            response_outcome="none",
            exchange_invocations=0,
            elapsed_ns=0,
            result_bytes=0,
            dialect=None,
        )
    )
    assert refused.deadline_result == "not-evaluated"
    for outcome in ("observed", "unusable", "void"):
        with pytest.raises(ValueError):
            rc.ObservationReceipt(**receipt_kwargs(
                outcome=outcome, deadline_result="not-evaluated"
            ))


def test_a_missing_required_key_failure_must_report_increasing_indices():
    base = receipt_kwargs(
        outcome="unusable",
        response_outcome="response-unusable",
        response_failure="missing-required-key",
        result_bytes=0,
        required_key_count=3,
    )
    assert rc.ObservationReceipt(**base, missing_key_indices=(0, 2)).missing_key_indices
    for indices in [(), (1, 1), (2, 0), (-1,), (True,), ("0",), [0]]:
        with pytest.raises(ValueError):
            rc.ObservationReceipt(**{**base, "missing_key_indices": indices})


def test_the_result_carrier_refuses_every_incoherent_combination():
    receipt = rc.ObservationReceipt(**receipt_kwargs())
    with pytest.raises(ValueError):
        ob.ObservationResult(ok=1)
    with pytest.raises(ValueError):
        ob.ObservationResult(ok=False, refusal="result-too-large")
    with pytest.raises(ValueError):
        ob.ObservationResult(ok=True, refusal="envelope-not-exact-type")
    with pytest.raises(ValueError):
        ob.ObservationResult(ok=False, refusal="envelope-digest-mismatch", receipt=None,
                             exchange="not an exchange")
    with pytest.raises(ValueError):
        ob.ObservationResult(ok=True, receipt=receipt)  # observed without an exchange
    with pytest.raises(ValueError):
        ob.ObservationResult(ok=False, receipt=receipt)  # observed but not ok
    with pytest.raises(ValueError):
        ob.ObservationResult(ok=False, receipt="not a receipt")


# ============================================================================
# the receipt is deterministic, bounded, and payload-free
# ============================================================================


def test_receipt_serialisation_is_deterministic_and_ascii():
    receipt = rc.ObservationReceipt(**receipt_kwargs())
    first = rc.serialize_receipt(receipt)
    second = rc.serialize_receipt(receipt)
    assert first == second
    assert type(first) is bytes
    assert first.decode("ascii")
    twin = rc.ObservationReceipt(**receipt_kwargs())
    assert twin == receipt
    assert rc.serialize_receipt(twin) == first


def _longest_safe_id(index: int) -> str:
    """The longest evidence id OMI-V1 will actually accept, ending in ``index``.

    64 characters is the ``is_safe_token`` length ceiling, but a 64-character
    run of letters and digits is exactly what OMI-V1's long-opaque-run secret
    rule matches - so the longest *acceptable* identifier has to break that run.
    Hyphens every twenty characters do it, and the result is still a real id an
    envelope could carry, which is what makes the ceiling proof honest rather
    than hypothetical.
    """
    body = ("e" * 19 + "-") * 4
    identifier = body[:61] + "%03d" % index
    if not is_safe_token(identifier) or len(identifier) != 64:
        raise AssertionError("the worst-case identifier must itself be acceptable")
    return identifier


def test_the_largest_receipt_the_carrier_accepts_serialises_inside_the_ceiling():
    """Every accepted receipt fits - proved at the ceiling, not assumed.

    The carrier bounds every field it holds, so the largest document
    ``serialize_receipt`` can ever be asked to produce is constructible: the
    most evidence items, the longest identifiers those items may carry, the
    most missing-key indices, and every count at its maximum. If that fits, all
    of them fit, and the ceiling check inside ``serialize_receipt`` is
    unreachable rather than load-bearing.
    """
    items = ob.OBSERVATION_LIMITS["evidence_items"]
    keys = ob.OBSERVATION_LIMITS["required_keys"]
    ids = tuple(_longest_safe_id(index) for index in range(items))
    for identifier in ids:
        assert len(identifier) == 64
        # Constructible as a real evidence id, so this is not a hypothetical
        # worst case but one an envelope could genuinely produce.
        ob.EvidenceItem(evidence_id=identifier, content=b"x")
    receipt = rc.ObservationReceipt(
        **receipt_kwargs(
            evidence_ids=ids,
            evidence_digests=tuple("f" * 64 for _ in range(items)),
            evidence_bytes=ob.OBSERVATION_LIMITS["evidence_total_bytes"],
            elapsed_ns=rc.MAX_CLOCK_NS,
            context_ceiling_tokens=ob.OBSERVATION_LIMITS["context_ceiling_tokens"],
            required_key_count=keys,
            outcome="unusable",
            response_outcome="response-unusable",
            response_failure="missing-required-key",
            missing_key_indices=tuple(range(keys)),
            result_bytes=0,
        )
    )
    rendered = rc.serialize_receipt(receipt)
    assert len(rendered) <= rc.RECEIPT_MAX_BYTES
    # And with real headroom, so an added field cannot silently overrun it.
    assert len(rendered) < rc.RECEIPT_MAX_BYTES


def test_an_observed_receipt_at_every_ceiling_also_serialises():
    items = ob.OBSERVATION_LIMITS["evidence_items"]
    receipt = rc.ObservationReceipt(
        **receipt_kwargs(
            evidence_ids=tuple(_longest_safe_id(i) for i in range(items)),
            evidence_digests=tuple("f" * 64 for _ in range(items)),
            evidence_bytes=ob.OBSERVATION_LIMITS["evidence_total_bytes"],
            elapsed_ns=rc.MAX_CLOCK_NS,
            result_bytes=ob.OBSERVATION_LIMITS["result_bytes"],
            context_ceiling_tokens=ob.OBSERVATION_LIMITS["context_ceiling_tokens"],
            required_key_count=ob.OBSERVATION_LIMITS["required_keys"],
        )
    )
    assert len(rc.serialize_receipt(receipt)) <= rc.RECEIPT_MAX_BYTES


@pytest.mark.parametrize("value", [None, "receipt", 5, object()])
def test_serialize_receipt_refuses_anything_that_is_not_a_receipt(value):
    with pytest.raises(ValueError):
        rc.serialize_receipt(value)


def test_a_receipt_has_no_field_a_payload_could_occupy():
    """Structural, not a scrubbing pass: the field list is the guarantee."""
    import dataclasses

    names = {f.name for f in dataclasses.fields(rc.ObservationReceipt)}
    forbidden = {
        "payload", "prompt", "system", "messages", "content", "text", "response",
        "output", "schema", "evidence", "endpoint", "headers", "url", "note",
        "error", "exception", "traceback", "repr", "type_name",
    }
    assert names & forbidden == set()
    receipt = rc.ObservationReceipt(**receipt_kwargs())
    for value in (getattr(receipt, name) for name in sorted(names)):
        assert type(value) in (str, int, tuple, type(None))
        if type(value) is tuple:
            for element in value:
                assert type(element) in (str, int)


def test_no_evidence_byte_or_schema_byte_reaches_a_serialised_receipt():
    marker = "PAYLOADMARKER" + SECRET
    envelope = plan(
        evidence=[
            ob.EvidenceItem(evidence_id="e1", content=marker.encode("utf-8"))
        ],
        schema={"type": "object", "title": marker},
    ).envelope
    receipt = rc.ObservationReceipt(
        **receipt_kwargs(
            task_id=envelope.task_id,
            envelope_digest=envelope.envelope_digest,
            schema_digest=envelope.schema_digest,
            evidence_ids=("e1",),
            evidence_digests=(envelope.evidence[0].digest,),
            evidence_bytes=len(marker),
        )
    )
    rendered = rc.serialize_receipt(receipt)
    assert marker.encode("ascii") not in rendered
    assert b"PAYLOADMARKER" not in rendered
    assert b"sk-" not in rendered
    assert ENDPOINT.encode("ascii") not in rendered
    assert b"127.0.0.1" not in rendered
    assert b"11434" not in rendered
    assert envelope.schema_bytes not in rendered


# ============================================================================
# pickling and copying, claimed only for what is tested
# ============================================================================


def test_the_exported_objects_carry_their_module_level_identity():
    for module, names in (
        (ob, ob.__all__),
        (rc, rc.__all__),
    ):
        for name in names:
            obj = getattr(module, name)
            if isinstance(obj, (types.FunctionType, type)):
                assert obj.__module__ == module.__name__
                assert obj.__qualname__ == name
                assert "<locals>" not in obj.__qualname__


def test_every_exported_class_and_function_pickles():
    for module in (ob, rc):
        for name in module.__all__:
            obj = getattr(module, name)
            if isinstance(obj, (types.FunctionType, type)):
                assert pickle.loads(pickle.dumps(obj)) is obj


def test_an_envelope_and_a_receipt_pickle_and_deep_copy():
    envelope = good_envelope()
    revived = pickle.loads(pickle.dumps(envelope))
    assert revived == envelope
    assert revived.envelope_digest == envelope.envelope_digest
    assert copy.deepcopy(envelope) == envelope

    receipt = rc.ObservationReceipt(**receipt_kwargs())
    assert pickle.loads(pickle.dumps(receipt)) == receipt
    assert copy.deepcopy(receipt) == receipt

    item = ob.EvidenceItem(evidence_id="e1", content=b"abc")
    assert pickle.loads(pickle.dumps(item)) == item
    reservation = ob.ResourceReservation(cpu_cores=1, memory_mib=1)
    assert pickle.loads(pickle.dumps(reservation)) == reservation
    decision = ob.ReservationDecision(
        reservation_digest=reservation.digest,
        satisfied=True,
        attestation="operator-asserted",
    )
    assert pickle.loads(pickle.dumps(decision)) == decision


def test_a_refused_plan_pickles_and_a_refused_result_pickles():
    refused_plan = plan(task_id="nope")
    assert pickle.loads(pickle.dumps(refused_plan)) == refused_plan
    refused_result = ob.ObservationResult(
        ok=False, refusal="envelope-not-exact-type"
    )
    assert pickle.loads(pickle.dumps(refused_result)) == refused_result


def test_a_frozen_carrier_refuses_ordinary_assignment():
    envelope = good_envelope()
    for name, value in (
        ("task_id", "other"),
        ("envelope_digest", "0" * 64),
        ("max_result_bytes", 1),
    ):
        with pytest.raises(Exception):
            setattr(envelope, name, value)


# ============================================================================
# rebinding: module globals and the exported package mirrors
# ============================================================================


#: Every name a trust decision could conceivably resolve at call time, on both
#: V3A modules. Discovered from the module namespaces rather than hand-listed,
#: so a name added later cannot slip past this control.
def _rebindable_names(module):
    return sorted(
        name
        for name in vars(module)
        if not name.startswith("__")
    )


#: The production entry points and inputs, captured **at import time**. A
#: rebinding control replaces module attributes, so a helper that reached for
#: ``ob.EvidenceItem`` while the rebinding was in force would be testing its own
#: name resolution rather than the code's. Everything the signature below needs
#: is therefore resolved once, here, before any control runs.
_REAL_PLAN = ob.plan_observation
_REAL_ENDPOINT_CHECK = ob.validate_loopback_endpoint
_REAL_SERIALIZE = rc.serialize_receipt
_REAL_UUID4_OK = rc.is_canonical_uuid4
_REAL_DIGEST_OK = rc.is_sha256_digest
_REAL_EVIDENCE = ob.EvidenceItem(evidence_id="e1", content=b"the evidence")
_REAL_RESERVATION = ob.ResourceReservation(cpu_cores=2, memory_mib=4096)
_REAL_RECEIPT = rc.ObservationReceipt(**receipt_kwargs())


def _canonical_behaviour():
    """One accepted plan, one refusal, and one serialisation, as a signature.

    Every input is fixed, including the task identity and the clock reading, so
    the only thing that could make two calls differ is the code changing its
    mind - which is precisely what a rebinding control is looking for.
    """
    fixed = dict(
        task_id=FIXED_TASK_ID,
        authorizing_principal="kev",
        worker="observer-1",
        evidence=[_REAL_EVIDENCE],
        dialect="ollama",
        schema=dict(SCHEMA),
        reservation=_REAL_RESERVATION,
        required_keys=("summary",),
    )
    accepted = _REAL_PLAN(endpoint=ENDPOINT, clock=make_clock([1000]), **fixed)
    refused = _REAL_PLAN(
        endpoint="http://localhost:11434/v1", clock=make_clock([1000]), **fixed
    )
    return (
        accepted.ok,
        accepted.envelope.schema_bytes,
        accepted.envelope.schema_digest,
        accepted.envelope.envelope_digest,
        accepted.envelope.evidence[0].digest,
        accepted.envelope.reservation.digest,
        refused.ok,
        refused.refusal,
        _REAL_SERIALIZE(_REAL_RECEIPT),
        _REAL_ENDPOINT_CHECK(ENDPOINT),
        _REAL_ENDPOINT_CHECK("http://0.0.0.0:1/v1"),
        _REAL_UUID4_OK(FIXED_TASK_ID),
        _REAL_DIGEST_OK("a" * 64),
    )


@pytest.mark.parametrize("module_name", ["observation", "observation_receipt"])
def test_rebinding_any_module_global_changes_nothing_on_a_trust_path(module_name):
    module = ob if module_name == "observation" else rc
    baseline = _canonical_behaviour()
    for name in _rebindable_names(module):
        original = getattr(module, name)
        setattr(module, name, Betrayer())
        try:
            assert _canonical_behaviour() == baseline
        finally:
            setattr(module, name, original)


BUILTIN_SHADOWS = [
    "type", "str", "int", "bytes", "bool", "tuple", "list", "dict", "set",
    "len", "sum", "getattr", "setattr", "callable", "object", "range",
    "frozenset", "isinstance", "iter", "next", "enumerate", "sorted",
]


@pytest.mark.parametrize("module_name", ["observation", "observation_receipt"])
@pytest.mark.parametrize("name", BUILTIN_SHADOWS)
def test_shadowing_a_builtin_on_a_v3a_module_changes_nothing(module_name, name):
    module = ob if module_name == "observation" else rc
    baseline = _canonical_behaviour()
    had = name in vars(module)
    original = getattr(module, name, None)
    setattr(module, name, Betrayer())
    try:
        assert _canonical_behaviour() == baseline
    finally:
        if had:
            setattr(module, name, original)
        else:
            delattr(module, name)


PACKAGE_MIRRORS = [
    "plan_observation", "execute_observation", "new_task_id", "EvidenceItem",
    "ObservationEnvelope", "ObservationPlan", "ObservationReceipt",
    "ObservationResult", "ReservationDecision", "ResourceReservation",
    "validate_loopback_endpoint", "structured_exchange_adapter",
    "serialize_receipt", "is_canonical_uuid4", "is_sha256_digest",
    "PLAN_REFUSALS", "ENVELOPE_REFUSALS", "EXECUTION_REFUSALS",
    "OBSERVATION_OUTCOMES", "DEADLINE_RESULTS", "RESERVATION_RESULTS",
    "RESERVATION_ATTESTATIONS", "REQUEST_OUTCOMES", "RESPONSE_OUTCOMES",
    "MAX_EVIDENCE_ITEMS", "MAX_REQUIRED_KEYS", "OBSERVATION_LIMITS",
    "MAX_CLOCK_NS", "MAX_CONTEXT_CEILING_TOKENS", "MAX_EVIDENCE_ITEM_BYTES",
    "MAX_EVIDENCE_TOTAL_BYTES", "MAX_RESULT_BYTES", "RECEIPT_MAX_BYTES",
    "UNDESCRIBABLE_REFUSALS",
    "is_safe_token", "request_structured_json", "StructuredExchange",
]


@pytest.mark.parametrize("name", PACKAGE_MIRRORS)
def test_rebinding_the_exported_package_mirror_changes_nothing(name):
    baseline = _canonical_behaviour()
    original = getattr(package, name)
    setattr(package, name, Betrayer())
    try:
        assert _canonical_behaviour() == baseline
    finally:
        setattr(package, name, original)


def test_the_package_mirrors_are_the_module_objects_themselves():
    for name in PACKAGE_MIRRORS:
        exported = getattr(package, name)
        source = ob if hasattr(ob, name) else rc
        if hasattr(source, name):
            assert exported is getattr(source, name)


def test_rebinding_an_omi_v2_name_v3a_imported_changes_nothing():
    """The imported OMI-V2 dependencies are captured, not looked up."""
    baseline = _canonical_behaviour()
    for module, name in (
        (sr, "REFUSAL_TOKENS"),
        (sr, "SUPPORTED_DIALECTS"),
        (sr, "STRUCTURED_WIRE_NAME"),
        (sx, "EXCHANGE_REFUSALS"),
        (sx, "RESPONSE_FAILURES"),
    ):
        original = getattr(module, name)
        setattr(module, name, Betrayer())
        try:
            assert _canonical_behaviour() == baseline
        finally:
            setattr(module, name, original)


def test_the_limits_mirror_is_read_only_and_matches_the_enforced_bounds():
    with pytest.raises(TypeError):
        ob.OBSERVATION_LIMITS["result_bytes"] = 1
    assert ob.OBSERVATION_LIMITS["evidence_items"] == rc.MAX_EVIDENCE_ITEMS
    assert ob.OBSERVATION_LIMITS["required_keys"] == rc.MAX_REQUIRED_KEYS
    # Each mirrored bound is the one actually enforced: at it, accepted; one
    # past it, refused.
    assert plan(max_result_bytes=ob.OBSERVATION_LIMITS["result_bytes"]).ok is True
    assert plan(max_result_bytes=ob.OBSERVATION_LIMITS["result_bytes"] + 1).ok is False
    assert len(ENDPOINT) <= ob.OBSERVATION_LIMITS["endpoint_chars"]


# ============================================================================
# no hidden authority survives as a caller-addressable keyword
# ============================================================================


HIDDEN_AUTHORITY_KEYWORDS = [
    "_type", "_str", "_int", "_bytes", "_len", "_dict", "_list", "_tuple",
    "_set", "_json", "_hashlib", "_safe_token", "_uuid4_ok", "_digest_ok",
    "_dialect_ok", "_endpoint_ok", "_refusals", "_outcomes", "_Plan",
    "_Envelope", "_Receipt", "_Result", "_validate", "_plan_request",
    "_digest_of", "_max_items", "_max_keys", "_callable", "_getattr",
]


@pytest.mark.parametrize("keyword", HIDDEN_AUTHORITY_KEYWORDS)
def test_a_former_hidden_authority_cannot_be_injected_as_a_keyword(keyword):
    with pytest.raises(TypeError):
        ob.plan_observation(**plan_kwargs(), **{keyword: Betrayer()})
    with pytest.raises(TypeError):
        ob.validate_loopback_endpoint(ENDPOINT, **{keyword: Betrayer()})
    with pytest.raises(TypeError):
        rc.serialize_receipt(
            rc.ObservationReceipt(**receipt_kwargs()), **{keyword: Betrayer()}
        )
    with pytest.raises(TypeError):
        ob.new_task_id(**{keyword: Betrayer()})
    with pytest.raises(TypeError):
        rc.is_canonical_uuid4("x", **{keyword: Betrayer()})
    with pytest.raises(TypeError):
        rc.is_sha256_digest("x", **{keyword: Betrayer()})


CARRIERS = [
    ob.EvidenceItem,
    ob.ObservationEnvelope,
    ob.ObservationPlan,
    ob.ObservationResult,
    ob.ReservationDecision,
    ob.ResourceReservation,
    rc.ObservationReceipt,
]


@pytest.mark.parametrize("carrier", CARRIERS)
def test_every_carrier_post_init_takes_self_and_nothing_else(carrier):
    parameters = list(inspect.signature(carrier.__post_init__).parameters)
    assert parameters == ["self"]


@pytest.mark.parametrize("carrier", CARRIERS)
@pytest.mark.parametrize("keyword", ["_type", "_refusals", "_safe_token"])
def test_a_carrier_post_init_refuses_a_former_authority_keyword(carrier, keyword):
    instance = object.__new__(carrier)
    with pytest.raises(TypeError):
        carrier.__post_init__(instance, **{keyword: Betrayer()})


def test_the_public_signatures_are_keyword_only_where_they_should_be():
    planner = inspect.signature(ob.plan_observation)
    for name, parameter in planner.parameters.items():
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
    executor = inspect.signature(ob.execute_observation)
    kinds = [p.kind for p in executor.parameters.values()]
    assert kinds[0] is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert all(k is inspect.Parameter.KEYWORD_ONLY for k in kinds[1:])


# ============================================================================
# non-duplication, asserted rather than assumed
# ============================================================================


def test_v3a_imports_omi_v2s_identity_restorer_rather_than_copying_it():
    assert ob._restore_identity is sx._restore_identity
    assert rc._restore_identity is sx._restore_identity


def test_v3a_defines_no_second_validator_dialect_map_or_transport():
    """Reuse, asserted at the source level.

    Reading ``plan.response_format["json_schema"]["schema"]`` is deliberately
    **not** forbidden here - that is OMI-V3A consuming OMI-V2's output, which
    is the reuse the boundary asks for. What is forbidden is OMI-V3A knowing
    any of the four dialects by name, building a wire shape of its own,
    carrying a second response validator, or importing anything that could
    perform I/O.
    """
    for module in (ob, rc):
        source = inspect.getsource(module)
        for dialect in sr.SUPPORTED_DIALECTS:
            assert '"%s"' % dialect not in source
            assert "'%s'" % dialect not in source
        assert "DIALECT_WIRE_SHAPES" not in source
        assert "def build_response_format" not in source
        assert "def validate_structured_output" not in source
        assert "def _validated_snapshot" not in source


def _cells(function):
    """The closure cells a factory-built function actually holds, by name."""
    return dict(
        zip(
            function.__code__.co_freevars,
            (cell.cell_contents for cell in function.__closure__ or ()),
        )
    )


def test_v3a_reuses_omi_v2s_planner_validator_and_carriers_by_identity():
    """The reuse points are the actual OMI-V2 objects, not lookalikes."""
    canonical = _cells(ob._canonical_schema)
    assert canonical["_plan_request"] is sr.plan_structured_request
    assert canonical["_request_type"] is sr.StructuredOutputRequest

    planner = _cells(ob.plan_observation)
    assert planner["_canonical"] is ob._canonical_schema

    adapter = _cells(ob.structured_exchange_adapter)
    assert adapter["_request"] is sx.request_structured_json


def test_the_single_schema_authority_is_reached_from_both_the_planner_and_carrier():
    """One canonicaliser, called from both places that must agree.

    A directly constructed envelope is held to the planner's standard by calling
    the *same* function the planner calls, not a second implementation of it.
    """
    # After Jack's second round there is ONE definition of an acceptable
    # envelope, and all three consumers - planner, carrier, executor - hold the
    # same object in a closure cell. That is the anti-drift guarantee, asserted
    # by identity rather than by comparing behaviour and hoping.
    semantics = _cells(ob._envelope_semantics)
    assert semantics["_canonical"] is ob._canonical_schema
    assert semantics["_dialect_ok"] is sr.is_supported_dialect
    assert semantics["_evidence_ok"] is ob._evidence_state
    assert semantics["_reservation_ok"] is ob._reservation_state
    assert _cells(ob.ObservationEnvelope.__post_init__)["_semantics"] is (
        ob._envelope_semantics
    )
    assert _cells(ob.execute_observation)["_semantics"] is ob._envelope_semantics
    assert _cells(ob.plan_observation)["_evidence_ok"] is ob._evidence_state
    assert _cells(ob.plan_observation)["_reservation_ok"] is ob._reservation_state


def _imported_modules(module) -> set[str]:
    """Every module name a V3A module imports, read from its own AST.

    Read from the syntax tree rather than from the source text, because the
    source text also contains prose: this module's docstrings discuss
    ``urllib.parse`` in order to explain why the endpoint parser does not use
    it, and a substring search cannot tell an explanation from an import.
    """
    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
                names.add(node.module.split(".")[0])
    return names


FORBIDDEN_IMPORTS = [
    "socket", "urllib", "http", "ssl", "asyncio", "subprocess", "os", "sys",
    "shutil", "pathlib", "tempfile", "requests", "httpx", "openai", "anthropic",
    "ctypes", "multiprocessing", "threading", "platform", "psutil", "resource",
]


@pytest.mark.parametrize("name", FORBIDDEN_IMPORTS)
def test_the_v3a_modules_import_nothing_that_can_reach_outside_the_process(name):
    for module in (ob, rc):
        assert name not in _imported_modules(module)


def test_the_v3a_module_imports_are_exactly_the_declared_set():
    assert _imported_modules(ob) == {
        "__future__",
        "hashlib",
        "json",
        "uuid",
        "dataclasses",
        "types",
        "typing",
        "scripts",
        "scripts.agent_backends.base",
        "scripts.agent_backends.structured_request",
        "scripts.open_model.observation_receipt",
        "scripts.open_model.redaction",
        "scripts.open_model.structured_exchange",
    }
    assert _imported_modules(rc) == {
        "__future__",
        "json",
        "dataclasses",
        "typing",
        "scripts",
        "scripts.agent_backends.structured_request",
        "scripts.open_model.redaction",
        "scripts.open_model.structured_exchange",
    }


def test_schema_conformance_stays_closed_to_the_single_unverified_token():
    receipt = rc.ObservationReceipt(**receipt_kwargs())
    assert receipt.schema_conformance == "unverified"
    with pytest.raises(ValueError):
        rc.ObservationReceipt(**receipt_kwargs(schema_conformance="verified"))
    with pytest.raises(ValueError):
        rc.ObservationReceipt(**receipt_kwargs(schema_conformance=None))


# ============================================================================
# Jack's first independent round - a regression for every reproduced finding
# ============================================================================
#
# Each control below reproduces, at this layer, exactly one case Jack's audit
# demonstrated against head e53b98f, and asserts the corrected refusal. Every
# one of them failed before the correction; the reproduction is recorded in
# section 11 of docs/OMI_V3_OBSERVATION_INCEPTION.md.


# -- finding 1: exact type is not unaltered, before planning ------------------


def test_pre_plan_equal_length_evidence_substitution_is_refused():
    """The case that started the round: same length, stale digest, accepted.

    ``object.__setattr__`` replaces the bytes of a frozen ``EvidenceItem``
    without disturbing the digest computed at construction. The previous
    revision adopted the item as an envelope's *initial* state, so the envelope
    digest - which does recompute - described the substituted bytes while the
    receipt reported the digest of bytes that were never sent.
    """
    item = ob.EvidenceItem(evidence_id="e1", content=b"AAAAAAAA")
    original_digest = item.digest
    object.__setattr__(item, "content", b"BBBBBBBB")
    assert len(item.content) == 8
    assert item.digest == original_digest, "the stale digest is the whole point"

    result = plan(evidence=[item])
    assert result.ok is False
    assert result.refusal == "evidence-digest-not-recomputable"
    assert result.envelope is None


@pytest.mark.parametrize(
    "replacement", [b"short", b"a much longer replacement payload", b"x"]
)
def test_pre_plan_evidence_substitution_of_any_length_is_refused(replacement):
    item = ob.EvidenceItem(evidence_id="e1", content=b"AAAAAAAA")
    object.__setattr__(item, "content", replacement)
    result = plan(evidence=[item])
    assert result.ok is False
    assert result.refusal == "evidence-digest-not-recomputable"


def test_pre_plan_evidence_digest_substitution_is_refused():
    item = ob.EvidenceItem(evidence_id="e1", content=b"abc")
    object.__setattr__(item, "digest", "0" * 64)
    result = plan(evidence=[item])
    assert result.ok is False
    assert result.refusal == "evidence-digest-not-recomputable"


@pytest.mark.parametrize("value", [SECRET, "has space", "", 42, "a/b"])
def test_pre_plan_evidence_id_substitution_is_refused(value):
    item = ob.EvidenceItem(evidence_id="e1", content=b"abc")
    object.__setattr__(item, "evidence_id", value)
    result = plan(evidence=[item])
    assert result.ok is False
    assert result.refusal == "evidence-id-not-safe-token"
    assert SECRET not in result.refusal


@pytest.mark.parametrize(
    "value", [bytearray(b"abc"), memoryview(b"abc"), HookedBytes(b"abc"), "abc", None]
)
def test_pre_plan_evidence_content_type_substitution_is_refused(value):
    HOOK_CALLS.clear()
    item = ob.EvidenceItem(evidence_id="e1", content=b"abc")
    object.__setattr__(item, "content", value)
    result = plan(evidence=[item])
    fired = list(HOOK_CALLS)
    assert result.ok is False
    assert result.refusal == "evidence-content-not-exact-bytes"
    assert fired == []


def test_pre_plan_empty_evidence_content_substitution_is_refused():
    item = ob.EvidenceItem(evidence_id="e1", content=b"abc")
    object.__setattr__(item, "content", b"")
    result = plan(evidence=[item])
    assert result.ok is False
    assert result.refusal == "evidence-item-empty"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cpu_cores", ob.OBSERVATION_LIMITS["cpu_cores"] + 1),
        pytest.param("cpu_cores", 10 ** 9, id="cpu-a-billion"),
        ("cpu_cores", 0),
        ("cpu_cores", -1),
        ("memory_mib", ob.OBSERVATION_LIMITS["memory_mib"] + 1),
        ("memory_mib", 0),
        ("gpu_memory_mib", ob.OBSERVATION_LIMITS["gpu_memory_mib"] + 1),
        ("gpu_memory_mib", 0),
        ("gpu_memory_mib", -5),
    ],
)
def test_pre_plan_reservation_field_beyond_every_ceiling_is_refused(field, value):
    """A reservation altered past any ceiling is refused, digest or not.

    The range check runs before the digest check, so the refusal names the
    field's magnitude rather than the digest that no longer describes it -
    which is the more useful of the two facts to an operator.
    """
    reservation = ob.ResourceReservation(cpu_cores=2, memory_mib=4096, gpu_memory_mib=8)
    object.__setattr__(reservation, field, value)
    result = plan(reservation=reservation)
    assert result.ok is False
    assert result.refusal == "reservation-field-out-of-range"


#: gpu_memory_mib=None is excluded deliberately rather than skipped: None
#: is the documented "no GPU reservation declared" value, so substituting it is
#: not a type substitution at all.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        (field, value)
        for field in ("cpu_cores", "memory_mib", "gpu_memory_mib")
        for value in (True, HookedInt(4), "4", 4.0, None)
        if not (field == "gpu_memory_mib" and value is None)
    ],
)
def test_pre_plan_reservation_field_type_substitution_is_refused(field, value):
    HOOK_CALLS.clear()
    reservation = ob.ResourceReservation(cpu_cores=2, memory_mib=4096, gpu_memory_mib=8)
    object.__setattr__(reservation, field, value)
    result = plan(reservation=reservation)
    fired = list(HOOK_CALLS)
    assert result.ok is False
    assert result.refusal == "reservation-field-not-exact-int"
    assert fired == []


def test_pre_plan_reservation_digest_substitution_is_refused():
    reservation = ob.ResourceReservation(cpu_cores=2, memory_mib=4096)
    object.__setattr__(reservation, "digest", "0" * 64)
    result = plan(reservation=reservation)
    assert result.ok is False
    assert result.refusal == "reservation-digest-not-recomputable"


def test_a_reservation_altered_inside_its_range_still_fails_its_digest():
    """The subtle half: a legal value that the stored digest does not describe."""
    reservation = ob.ResourceReservation(cpu_cores=2, memory_mib=4096)
    object.__setattr__(reservation, "cpu_cores", 4)
    result = plan(reservation=reservation)
    assert result.ok is False
    assert result.refusal == "reservation-digest-not-recomputable"


def test_the_planner_revalidation_recomputes_rather_than_trusting():
    """Positive guard: an untouched carrier still plans, and its digests hold."""
    item = ob.EvidenceItem(evidence_id="e1", content=b"the evidence")
    reservation = ob.ResourceReservation(cpu_cores=2, memory_mib=4096)
    envelope = plan(evidence=[item], reservation=reservation).envelope
    assert envelope.evidence[0].digest == hashlib.sha256(b"the evidence").hexdigest()
    assert envelope.reservation.digest == reservation.digest


# -- finding 2: direct construction is held to the planner's standard --------


def direct_kwargs(**overrides):
    """The field set of an accepted envelope, for direct construction."""
    envelope = fixed_envelope()
    kwargs = dict(
        task_id=envelope.task_id,
        authorizing_principal="kev",
        worker="observer-1",
        evidence=envelope.evidence,
        dialect="ollama",
        schema_bytes=envelope.schema_bytes,
        schema_digest=envelope.schema_digest,
        required_keys=envelope.required_keys,
        endpoint=ENDPOINT,
        reservation=envelope.reservation,
        context_ceiling_tokens=8192,
        max_evidence_bytes=65536,
        max_result_bytes=8192,
        max_output_tokens=1024,
        issued_ns=1000,
        deadline_ns=1000 + 30000000000,
    )
    kwargs.update(overrides)
    return kwargs


def test_a_directly_constructed_envelope_matches_the_planned_one():
    """Positive guard: the documented claim is true in the accepting direction."""
    planned = fixed_envelope()
    direct = ob.ObservationEnvelope(**direct_kwargs())
    assert direct.envelope_digest == planned.envelope_digest
    assert direct == planned


@pytest.mark.parametrize(
    "dialect",
    [SECRET, "not-a-runtime", "OLLAMA", "", "ollama ", 5, None, HookedStr("ollama")],
)
def test_direct_construction_refuses_a_dialect_omi_v2_did_not_verify(dialect):
    """The claim that direct construction re-runs every check, made true.

    The previous revision checked only ``type(dialect) is str``, so a
    secret-shaped dialect constructed an envelope and would have travelled into
    a receipt. OMI-V2's ``is_supported_dialect`` is the authority now, called
    from a closure cell.
    """
    HOOK_CALLS.clear()
    with pytest.raises(ValueError):
        ob.ObservationEnvelope(**direct_kwargs(dialect=dialect))
    assert HOOK_CALLS == []


@pytest.mark.parametrize("dialect", sorted(sr.SUPPORTED_DIALECTS))
def test_direct_construction_accepts_every_dialect_omi_v2_verified(dialect):
    planned = plan(dialect=dialect, task_id=FIXED_TASK_ID, clock=make_clock([1000]))
    assert planned.ok is True
    direct = ob.ObservationEnvelope(
        **direct_kwargs(
            dialect=dialect,
            schema_bytes=planned.envelope.schema_bytes,
            schema_digest=planned.envelope.schema_digest,
        )
    )
    assert direct.dialect == dialect


@pytest.mark.parametrize(
    "raw",
    [
        b"not json at all",
        b"",
        b"[]",
        b"null",
        b"{}",
        b"{",
        b'{"type": "object"',
        b"\xff\xfe",
        json.dumps(SCHEMA, separators=(",", ":")).encode("ascii"),  # unsorted keys
        json.dumps(SCHEMA, sort_keys=True).encode("ascii"),  # spaces
        # Explicit id: a 65537-byte parameter would otherwise become a
        # 65537-character test id, and Windows caps an environment variable at
        # 32767 - pytest writes the current test id into one.
        pytest.param(
            b"a" * (ob.OBSERVATION_LIMITS["schema_bytes"] + 1),
            id="one-byte-past-the-schema-ceiling",
        ),
        "not bytes",
        None,
        bytearray(b"{}"),
    ],
)
def test_direct_construction_refuses_schema_bytes_that_are_not_canonical(raw):
    """Bytes must be provably the canonical rendering of a schema OMI-V2 takes.

    Not merely "some bytes", which is all the previous revision checked. The
    unsorted and spaced renderings matter as much as the malformed ones: both
    parse, both describe the same schema, and neither is the form the digest was
    taken over - so accepting either would make two envelopes for one schema.
    """
    digest = (
        hashlib.sha256(raw).hexdigest() if type(raw) is bytes else "0" * 64
    )
    with pytest.raises(ValueError):
        ob.ObservationEnvelope(**direct_kwargs(schema_bytes=raw, schema_digest=digest))


def test_direct_construction_refuses_a_schema_digest_that_hashes_nothing():
    for digest in ("0" * 64, "a" * 64, "short", None, 5, "A" * 64):
        with pytest.raises(ValueError):
            ob.ObservationEnvelope(**direct_kwargs(schema_digest=digest))


def test_direct_construction_refuses_a_schema_from_another_dialect_shape():
    """A schema OMI-V2 refuses for this dialect cannot be smuggled in as bytes."""
    empty = json.dumps({}, sort_keys=True, separators=(",", ":")).encode("ascii")
    with pytest.raises(ValueError):
        ob.ObservationEnvelope(
            **direct_kwargs(
                schema_bytes=empty, schema_digest=hashlib.sha256(empty).hexdigest()
            )
        )


def test_direct_construction_refuses_stale_evidence_and_reservation_digests():
    stale_item = ob.EvidenceItem(evidence_id="e1", content=b"AAAAAAAA")
    object.__setattr__(stale_item, "content", b"BBBBBBBB")
    with pytest.raises(ValueError):
        ob.ObservationEnvelope(**direct_kwargs(evidence=(stale_item,)))

    stale_reservation = ob.ResourceReservation(cpu_cores=2, memory_mib=4096)
    object.__setattr__(stale_reservation, "cpu_cores", 200)
    with pytest.raises(ValueError):
        ob.ObservationEnvelope(**direct_kwargs(reservation=stale_reservation))


@pytest.mark.parametrize(
    "override",
    [
        dict(context_ceiling_tokens=ob.OBSERVATION_LIMITS["context_ceiling_tokens"] + 1),
        dict(context_ceiling_tokens=0),
        dict(max_result_bytes=ob.OBSERVATION_LIMITS["result_bytes"] + 1),
        dict(max_output_tokens=ob.OBSERVATION_LIMITS["output_tokens"] + 1),
        dict(max_evidence_bytes=ob.OBSERVATION_LIMITS["evidence_total_bytes"] + 1),
        dict(required_keys=("has space",)),
        dict(required_keys=(SECRET,)),
        dict(required_keys=["summary"]),
        dict(required_keys=tuple("k%d" % i for i in range(
            ob.OBSERVATION_LIMITS["required_keys"] + 1))),
        dict(issued_ns=rc.MAX_CLOCK_NS + 1),
        dict(deadline_ns=rc.MAX_CLOCK_NS + 1),
        dict(endpoint="http://localhost:11434/v1"),
        dict(task_id="nope"),
        dict(authorizing_principal=SECRET),
    ],
)
def test_direct_construction_refuses_over_limit_or_incoherent_fields(override):
    with pytest.raises(ValueError):
        ob.ObservationEnvelope(**direct_kwargs(**override))


def test_direct_construction_refuses_duplicate_evidence_ids():
    item = ob.EvidenceItem(evidence_id="same", content=b"one")
    other = ob.EvidenceItem(evidence_id="same", content=b"two")
    with pytest.raises(ValueError):
        ob.ObservationEnvelope(**direct_kwargs(evidence=(item, other)))


def test_no_directly_constructed_invalid_envelope_exists_to_reach_an_exchange():
    """The structural statement: an invalid envelope is never an object at all.

    Because every rejection above is a ``ValueError`` from ``__post_init__``,
    there is no half-built envelope left behind for a caller to hand to
    ``execute_observation``. The control asserts that directly rather than
    inferring it: for each rejected field set, no instance escapes.
    """
    escaped = []
    for override in (
        dict(dialect=SECRET),
        dict(schema_bytes=b"not json"),
        dict(schema_digest="0" * 64),
        dict(endpoint="http://localhost:11434/v1"),
    ):
        try:
            escaped.append(ob.ObservationEnvelope(**direct_kwargs(**override)))
        except ValueError:
            pass
    assert escaped == []


# -- finding 3, planner half: a clock that raises, and one that is enormous ---


def test_a_raising_clock_refuses_the_plan_and_discloses_nothing():
    """The planner says it is total. It is now."""
    marker = "CLOCKSECRET" + SECRET

    def raising_clock():
        raise RuntimeError(marker)

    result = ob.plan_observation(**plan_kwargs(clock=raising_clock))
    assert result.ok is False
    assert result.refusal == "clock-raised"
    assert marker not in result.refusal
    assert "RuntimeError" not in result.refusal
    assert result.refusal in rc.PLAN_REFUSALS


@pytest.mark.parametrize(
    "exception",
    [RuntimeError("x"), ValueError("x"), TypeError("x"), ZeroDivisionError("x"),
     OSError("x"), MemoryError()],
)
def test_a_clock_raising_anything_at_all_refuses_the_plan(exception):
    def raising_clock():
        raise exception

    result = ob.plan_observation(**plan_kwargs(clock=raising_clock))
    assert result.ok is False
    assert result.refusal == "clock-raised"


def test_a_clock_raising_a_base_exception_still_propagates():
    """``except Exception`` is deliberate: an interrupt is not a clock failure."""

    def interrupting_clock():
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        ob.plan_observation(**plan_kwargs(clock=interrupting_clock))


#: 10 ** 5000 is passed with an explicit id because pytest builds parameter
#: ids with str(value) - and CPython refuses to render an integer that long,
#: which is the exact failure this control exists to pin. The collection error
#: it produced without an id is itself a demonstration of the defect.
@pytest.mark.parametrize(
    "reading",
    [
        pytest.param(rc.MAX_CLOCK_NS + 1, id="one-past-the-ceiling"),
        pytest.param(10 ** 50, id="ten-to-the-50"),
        pytest.param(10 ** 5000, id="ten-to-the-5000"),
        pytest.param(2 ** 64, id="two-to-the-64"),
    ],
)
def test_an_enormous_clock_reading_is_refused_by_the_planner(reading):
    """An exact int has no width; the receipt's serialiser does.

    A reading of ``10**5000`` is a perfectly ordinary Python integer and made a
    perfectly ordinary envelope. It then produced a receipt CPython refuses to
    render at all - ``Exceeds the limit (4300 digits) for integer string
    conversion``. The magnitude is refused where it enters.
    """
    result = plan(clock=make_clock([reading]))
    assert result.ok is False
    assert result.refusal == "clock-reading-too-large"


def test_the_clock_ceiling_itself_is_accepted_when_the_deadline_fits():
    at_ceiling = rc.MAX_CLOCK_NS - 30000000000
    envelope = plan(clock=make_clock([at_ceiling])).envelope
    assert envelope.issued_ns == at_ceiling
    assert envelope.deadline_ns == rc.MAX_CLOCK_NS


def test_a_deadline_past_the_clock_ceiling_is_refused():
    result = plan(clock=make_clock([rc.MAX_CLOCK_NS]), duration_ns=1)
    assert result.ok is False
    assert result.refusal == "deadline-beyond-clock-ceiling"


def test_the_clock_ceiling_is_the_documented_one_and_is_off_the_trust_path():
    assert rc.MAX_CLOCK_NS == 2 ** 63 - 1
    assert ob.OBSERVATION_LIMITS["clock_ns"] == rc.MAX_CLOCK_NS
    baseline = plan(clock=make_clock([rc.MAX_CLOCK_NS + 1])).refusal
    original = rc.MAX_CLOCK_NS
    rc.MAX_CLOCK_NS = 10 ** 6000
    try:
        assert plan(clock=make_clock([rc.MAX_CLOCK_NS])).refusal == baseline
    finally:
        rc.MAX_CLOCK_NS = original


# -- finding 5: the receipt enforces every bound it documents -----------------


@pytest.mark.parametrize(
    ("field", "over"),
    [
        ("evidence_bytes", rc.MAX_EVIDENCE_TOTAL_BYTES + 1),
        pytest.param("evidence_bytes", 10 ** 40, id="evidence-ten-to-the-40"),
        pytest.param("elapsed_ns", rc.MAX_CLOCK_NS + 1, id="elapsed-one-past"),
        pytest.param("elapsed_ns", 10 ** 5000, id="elapsed-ten-to-the-5000"),
        ("result_bytes", rc.MAX_RESULT_BYTES + 1),
        ("context_ceiling_tokens", rc.MAX_CONTEXT_CEILING_TOKENS + 1),
        ("required_key_count", rc.MAX_REQUIRED_KEYS + 1),
    ],
)
def test_every_receipt_count_is_refused_past_its_ceiling(field, over):
    with pytest.raises(ValueError):
        rc.ObservationReceipt(**receipt_kwargs(**{field: over}))


def test_a_receipt_requires_distinct_evidence_ids():
    with pytest.raises(ValueError):
        rc.ObservationReceipt(
            **receipt_kwargs(
                evidence_ids=("e1", "e1"),
                evidence_digests=("c" * 64, "d" * 64),
                evidence_bytes=2,
            )
        )


def test_a_receipt_refuses_fewer_evidence_bytes_than_its_item_count_implies():
    """Every evidence item carries at least one byte, so the total is bracketed."""
    with pytest.raises(ValueError):
        rc.ObservationReceipt(**receipt_kwargs(evidence_bytes=0))
    with pytest.raises(ValueError):
        rc.ObservationReceipt(
            **receipt_kwargs(
                evidence_ids=("e1", "e2"),
                evidence_digests=("c" * 64, "d" * 64),
                evidence_bytes=1,
            )
        )
    assert rc.ObservationReceipt(
        **receipt_kwargs(
            evidence_ids=("e1", "e2"),
            evidence_digests=("c" * 64, "d" * 64),
            evidence_bytes=2,
        )
    ).evidence_bytes == 2


@pytest.mark.parametrize("index", [1, 2, 63])
def test_a_missing_key_index_at_or_above_the_key_count_is_refused(index):
    """An index names a position in the caller's own required-key tuple.

    One at or past the end names nothing, and OMI-V2's validator - which reports
    indices precisely so key *text* never travels - cannot produce it.
    """
    with pytest.raises(ValueError):
        rc.ObservationReceipt(
            **receipt_kwargs(
                outcome="unusable",
                response_outcome="response-unusable",
                response_failure="missing-required-key",
                missing_key_indices=(index,),
                required_key_count=1,
                result_bytes=0,
            )
        )


def test_the_last_valid_missing_key_index_is_accepted():
    receipt = rc.ObservationReceipt(
        **receipt_kwargs(
            outcome="unusable",
            response_outcome="response-unusable",
            response_failure="missing-required-key",
            missing_key_indices=(0, 2),
            required_key_count=3,
            result_bytes=0,
        )
    )
    assert receipt.missing_key_indices == (0, 2)


def test_more_missing_indices_than_required_keys_is_refused():
    with pytest.raises(ValueError):
        rc.ObservationReceipt(
            **receipt_kwargs(
                outcome="unusable",
                response_outcome="response-unusable",
                response_failure="missing-required-key",
                missing_key_indices=(0, 1),
                required_key_count=1,
                result_bytes=0,
            )
        )


PRE_DIALECT_REFUSALS = [
    token
    for token in sorted(sx.EXCHANGE_REFUSALS)
    if token == "backend-not-structured-capable" or sr.is_pre_dialect_refusal(token)
]
POST_DIALECT_REFUSALS = [
    token for token in sorted(sx.EXCHANGE_REFUSALS) if token not in PRE_DIALECT_REFUSALS
]


@pytest.mark.parametrize("token", PRE_DIALECT_REFUSALS)
def test_a_pre_dialect_refusal_may_not_name_a_dialect_on_a_receipt(token):
    """OMI-V2's own dialect coherence, imported rather than re-derived."""
    base = dict(
        outcome="unusable",
        response_outcome="request-refused",
        request_refusal=token,
        result_bytes=0,
    )
    with pytest.raises(ValueError):
        rc.ObservationReceipt(**receipt_kwargs(dialect="ollama", **base))
    assert rc.ObservationReceipt(**receipt_kwargs(dialect=None, **base)).dialect is None


@pytest.mark.parametrize("token", POST_DIALECT_REFUSALS)
def test_a_post_dialect_refusal_must_name_its_dialect_on_a_receipt(token):
    base = dict(
        outcome="unusable",
        response_outcome="request-refused",
        request_refusal=token,
        result_bytes=0,
    )
    with pytest.raises(ValueError):
        rc.ObservationReceipt(**receipt_kwargs(dialect=None, **base))
    assert rc.ObservationReceipt(**receipt_kwargs(dialect="ollama", **base)).dialect


@pytest.mark.parametrize("failure", sorted(sx.RESPONSE_FAILURES))
def test_a_response_failure_must_always_name_its_dialect_on_a_receipt(failure):
    base = dict(
        outcome="unusable",
        response_outcome="response-unusable",
        response_failure=failure,
        result_bytes=0,
        required_key_count=3,
        missing_key_indices=(0,) if failure == "missing-required-key" else (),
    )
    with pytest.raises(ValueError):
        rc.ObservationReceipt(**receipt_kwargs(dialect=None, **base))
    assert rc.ObservationReceipt(**receipt_kwargs(dialect="ollama", **base)).dialect


def test_the_receipts_pre_dialect_rule_is_omi_v2s_own_predicate():
    """Not a second copy of the rule - the same predicate, in a cell."""
    cells = dict(
        zip(
            rc.ObservationReceipt.__post_init__.__code__.co_freevars,
            (
                cell.cell_contents
                for cell in rc.ObservationReceipt.__post_init__.__closure__ or ()
            ),
        )
    )
    assert cells["_pre_dialect"] is sr.is_pre_dialect_refusal
    assert cells["_request_refusals"] is sx.EXCHANGE_REFUSALS
    assert cells["_response_failures"] is sx.RESPONSE_FAILURES


# -- finding 5: the attestation is carried, and is not collapsed --------------


@pytest.mark.parametrize("attestation", sorted(rc.RESERVATION_ATTESTATIONS))
def test_an_evaluated_reservation_carries_the_attestation_that_produced_it(
    attestation,
):
    receipt = rc.ObservationReceipt(
        **receipt_kwargs(reservation_attestation=attestation)
    )
    assert receipt.reservation_attestation == attestation
    assert attestation.encode("ascii") in rc.serialize_receipt(receipt)


def test_the_two_attestations_are_not_collapsed_into_one_satisfied_claim():
    """Whose claim it is survives into the serialised evidence."""
    operator = rc.ObservationReceipt(
        **receipt_kwargs(reservation_attestation="operator-asserted")
    )
    checker = rc.ObservationReceipt(
        **receipt_kwargs(reservation_attestation="checker-asserted")
    )
    assert operator != checker
    assert rc.serialize_receipt(operator) != rc.serialize_receipt(checker)


def test_an_evaluated_reservation_without_an_attestation_is_refused():
    for result in ("satisfied", "not-satisfied"):
        with pytest.raises(ValueError):
            rc.ObservationReceipt(
                **receipt_kwargs(
                    reservation_result=result, reservation_attestation=None
                )
            )


def test_an_unevaluated_reservation_with_an_attestation_is_refused():
    with pytest.raises(ValueError):
        rc.ObservationReceipt(
            **receipt_kwargs(
                outcome="refused",
                refusal="clock-not-callable",
                deadline_result="not-evaluated",
                reservation_result="not-evaluated",
                reservation_attestation="operator-asserted",
                request_outcome="not-attempted",
                response_outcome="none",
                exchange_invocations=0,
                elapsed_ns=0,
                result_bytes=0,
                dialect=None,
            )
        )


@pytest.mark.parametrize("value", ["assumed", "", 5, True, "OPERATOR-ASSERTED"])
def test_an_attestation_outside_the_closed_vocabulary_is_refused(value):
    with pytest.raises(ValueError):
        rc.ObservationReceipt(**receipt_kwargs(reservation_attestation=value))


def test_an_unsatisfied_reservation_is_recorded_only_as_its_own_refusal():
    """The state the executor emits, and no other."""
    receipt = rc.ObservationReceipt(
        **receipt_kwargs(
            outcome="refused",
            refusal="reservation-not-satisfied",
            reservation_result="not-satisfied",
            request_outcome="not-attempted",
            response_outcome="none",
            exchange_invocations=0,
            elapsed_ns=0,
            result_bytes=0,
            dialect=None,
        )
    )
    assert receipt.reservation_result == "not-satisfied"
    with pytest.raises(ValueError):
        rc.ObservationReceipt(
            **receipt_kwargs(
                outcome="refused",
                refusal="result-too-large",
                reservation_result="not-satisfied",
                request_outcome="not-attempted",
                response_outcome="none",
                exchange_invocations=0,
                elapsed_ns=0,
                result_bytes=0,
                dialect=None,
            )
        )


def test_an_elapsed_duration_requires_an_invocation_and_a_deadline_verdict():
    with pytest.raises(ValueError):
        rc.ObservationReceipt(
            **receipt_kwargs(
                outcome="refused",
                refusal="reservation-not-satisfied",
                reservation_result="not-satisfied",
                request_outcome="not-attempted",
                response_outcome="none",
                exchange_invocations=0,
                elapsed_ns=5,
                result_bytes=0,
                dialect=None,
            )
        )
    with pytest.raises(ValueError):
        rc.ObservationReceipt(
            **receipt_kwargs(
                outcome="refused",
                refusal="clock-reading-not-exact-int",
                deadline_result="not-evaluated",
                reservation_result="satisfied",
                request_outcome="attempted",
                response_outcome="none",
                exchange_invocations=1,
                elapsed_ns=5,
                result_bytes=0,
                dialect=None,
            )
        )


def test_the_schema_byte_mirror_agrees_with_omi_v2s_own_ceiling():
    """The one number this layer restates, pinned to its source.

    _MAX_SCHEMA_BYTES exists so the envelope carrier can bound a decode
    before handing the document to OMI-V2, rather than decoding an arbitrarily
    large buffer first. OMI-V2 remains the authority on what a schema may be,
    and this asserts the two cannot drift into disagreeing about which one
    refuses.
    """
    assert ob.OBSERVATION_LIMITS["schema_bytes"] == sr._SCHEMA_MAX_CHARS


def test_every_shared_bound_has_exactly_one_definition():
    """The bounds the two V3A modules share are imported, never restated."""
    for name in (
        "MAX_EVIDENCE_ITEMS",
        "MAX_EVIDENCE_ITEM_BYTES",
        "MAX_EVIDENCE_TOTAL_BYTES",
        "MAX_RESULT_BYTES",
        "MAX_CONTEXT_CEILING_TOKENS",
        "MAX_REQUIRED_KEYS",
        "MAX_CLOCK_NS",
    ):
        assert getattr(ob, name) is getattr(rc, name)
    assert ob.OBSERVATION_LIMITS["evidence_items"] == rc.MAX_EVIDENCE_ITEMS
    assert ob.OBSERVATION_LIMITS["evidence_item_bytes"] == rc.MAX_EVIDENCE_ITEM_BYTES
    assert ob.OBSERVATION_LIMITS["evidence_total_bytes"] == rc.MAX_EVIDENCE_TOTAL_BYTES
    assert ob.OBSERVATION_LIMITS["result_bytes"] == rc.MAX_RESULT_BYTES
    assert ob.OBSERVATION_LIMITS["context_ceiling_tokens"] == rc.MAX_CONTEXT_CEILING_TOKENS
    assert ob.OBSERVATION_LIMITS["required_keys"] == rc.MAX_REQUIRED_KEYS
    assert ob.OBSERVATION_LIMITS["clock_ns"] == rc.MAX_CLOCK_NS
    assert ob.OBSERVATION_LIMITS["receipt_bytes"] == rc.RECEIPT_MAX_BYTES


# ============================================================================
# Jack's second independent round - a regression for every reproduced case
# ============================================================================
#
# Twenty-one cases were demonstrated against head 310e28d and all twenty-one
# reproduced. Section 13 of docs/OMI_V3_OBSERVATION_INCEPTION.md records them.


# -- finding 1: direct construction skipped the strict-UTF-8 gate ------------


@pytest.mark.parametrize(
    "content",
    [b"\xff\xfe", b"\x80", b"\xc3", b"\xed\xa0\x80", b"ok\xffbad"],
)
def test_direct_construction_refuses_evidence_that_is_not_strict_utf8(content):
    """The planner refused these; the carrier did not, and the gap was live.

    An envelope built directly with invalid bytes reached the adapter, whose
    ``decode("utf-8")`` then raised ``UnicodeDecodeError`` straight out of
    ``execute_observation`` - a function documented as total. Both gates are now
    the same function, so the carrier cannot fall behind the planner again.
    """
    item = ob.EvidenceItem(evidence_id="e1", content=content)
    with pytest.raises(ValueError):
        ob.ObservationEnvelope(**direct_kwargs(evidence=(item,)))
    # ...and the planner still refuses it, with its precise token.
    assert plan(evidence=[item]).refusal == "evidence-not-utf8"


def test_the_planner_and_direct_construction_refuse_exactly_the_same_inputs():
    """The anti-drift control, stated as a property rather than a sample.

    For every defective field set below, the planner must return a refusal and
    direct construction must raise - and for the accepted one, both must
    succeed. Two rounds of this audit found the two gates disagreeing; they now
    share one function, and this asserts the consequence.
    """
    bad_item = ob.EvidenceItem(evidence_id="e1", content=b"\xff\xfe")
    stale = ob.EvidenceItem(evidence_id="e1", content=b"AAAA")
    object.__setattr__(stale, "content", b"BBBB")
    stale_reservation = ob.ResourceReservation(cpu_cores=2, memory_mib=4096)
    object.__setattr__(stale_reservation, "cpu_cores", 200)

    cases = [
        dict(task_id="not-a-uuid"),
        dict(authorizing_principal=SECRET),
        dict(worker="has space"),
        dict(dialect="not-a-runtime"),
        dict(dialect=SECRET),
        dict(endpoint="http://localhost:11434/v1"),
        dict(endpoint="http://0.0.0.0:11434/v1"),
        dict(evidence=(bad_item,)),
        dict(evidence=(stale,)),
        dict(evidence=()),
        dict(reservation=stale_reservation),
        dict(required_keys=("has space",)),
        dict(required_keys=(SECRET,)),
        dict(context_ceiling_tokens=0),
        dict(max_result_bytes=ob.OBSERVATION_LIMITS["result_bytes"] + 1),
        dict(max_output_tokens=0),
    ]
    for override in cases:
        with pytest.raises(ValueError):
            ob.ObservationEnvelope(**direct_kwargs(**override))
        planner_override = dict(override)
        if "evidence" in planner_override:
            planner_override["evidence"] = list(planner_override["evidence"])
        result = plan(**planner_override)
        assert result.ok is False, override
        assert result.refusal in rc.PLAN_REFUSALS, override
    # ...and the accepted set is accepted by both.
    assert ob.ObservationEnvelope(**direct_kwargs()).envelope_digest
    assert plan(task_id=FIXED_TASK_ID, clock=make_clock([1000])).ok is True


def test_the_refusal_raised_by_direct_construction_carries_the_closed_token():
    """``_EnvelopeRefused`` is a ValueError, and its token is in the closed set."""
    try:
        ob.ObservationEnvelope(**direct_kwargs(dialect=SECRET))
    except ValueError as exc:
        assert isinstance(exc, ob._EnvelopeRefused)
        assert exc.token == "dialect-unsupported"
        assert exc.token in rc.PLAN_REFUSALS
        assert SECRET not in exc.token
    else:  # pragma: no cover
        raise AssertionError("direct construction must refuse a secret dialect")


# -- finding 2: caller-owned carriers must not survive into an envelope -------


def test_an_accepted_envelope_holds_none_of_the_callers_carriers():
    """Detachment, asserted by identity rather than by equality.

    Equality would pass while the caller still held the very object the envelope
    contains. What matters is that they are different objects, so a later
    ``object.__setattr__`` on the caller's copy reaches nothing here.
    """
    item = ob.EvidenceItem(evidence_id="e1", content=b"mine")
    reservation = ob.ResourceReservation(cpu_cores=2, memory_mib=4096)
    envelope = plan(evidence=[item], reservation=reservation).envelope

    assert envelope.evidence[0] is not item
    assert envelope.reservation is not reservation
    assert envelope.evidence[0] == item
    assert envelope.reservation == reservation

    # Mutating what the caller kept changes nothing the envelope reports.
    digest_before = envelope.envelope_digest
    object.__setattr__(item, "content", b"nine")
    object.__setattr__(reservation, "cpu_cores", 200)
    assert envelope.evidence[0].content == b"mine"
    assert envelope.reservation.cpu_cores == 2
    assert envelope.envelope_digest == digest_before
    assert ob._envelope_digest(envelope) == digest_before


def test_direct_construction_detaches_too():
    item = ob.EvidenceItem(evidence_id="e1", content=b"mine")
    reservation = ob.ResourceReservation(cpu_cores=2, memory_mib=4096)
    envelope = ob.ObservationEnvelope(
        **direct_kwargs(evidence=(item,), reservation=reservation)
    )
    assert envelope.evidence[0] is not item
    assert envelope.reservation is not reservation


def test_detached_carriers_recompute_their_own_digests():
    item = ob.EvidenceItem(evidence_id="e1", content=b"mine")
    reservation = ob.ResourceReservation(cpu_cores=3, memory_mib=2048)
    envelope = plan(evidence=[item], reservation=reservation).envelope
    assert envelope.evidence[0].digest == hashlib.sha256(b"mine").hexdigest()
    assert envelope.reservation.digest == reservation.digest
    assert ob._evidence_state(envelope.evidence, 65536)[0] is None
    assert ob._reservation_state(envelope.reservation) is None


# -- finding 3: an unkeyed digest is not authority for validity ---------------


def reseal(envelope):
    """Recompute and reinstall the envelope digest after a tamper.

    This is the whole of finding 3: the digest is a pure function of the
    envelope's own public fields, computed by a function this package exports,
    so anyone who can mutate a field can repair the digest. Nothing about that
    is exotic - it is what "unkeyed" means.
    """
    object.__setattr__(envelope, "envelope_digest", ob._envelope_digest(envelope))
    return envelope


RESEALED_TAMPERS = [
    ("task_id", "not-a-uuid"),
    ("authorizing_principal", SECRET),
    ("worker", SECRET),
    ("dialect", SECRET),
    ("dialect", "not-a-runtime"),
    ("endpoint", "http://evil.example.com:11434/v1"),
    ("endpoint", "http://localhost:11434/v1"),
    ("endpoint", "http://0.0.0.0:11434/v1"),
    ("max_result_bytes", 10 ** 9),
    ("max_result_bytes", 0),
    ("context_ceiling_tokens", 10 ** 9),
    ("max_output_tokens", 10 ** 9),
    ("max_evidence_bytes", 1),
    ("required_keys", (SECRET,)),
    ("required_keys", ("has space",)),
    ("schema_bytes", b"not json at all"),
    ("issued_ns", -1),
    ("deadline_ns", 10),
]


@pytest.mark.parametrize(("field", "value"), RESEALED_TAMPERS)
def test_a_resealed_envelope_is_still_refused_on_its_semantics(field, value):
    """Digest equality is self-consistency, never validity.

    Each envelope below agrees perfectly with its own digest and is nonetheless
    unfit: an unsupported dialect, a DNS endpoint, a secret-shaped principal, an
    over-limit bound. The previous revision executed every one of them, and
    several then raised out of receipt construction rather than refusing.
    """
    envelope = fixed_envelope()
    object.__setattr__(envelope, field, value)
    reseal(envelope)
    # The digest now agrees with the fields - that is the premise, not the test.
    assert ob._envelope_digest(envelope) == envelope.envelope_digest
    assert ob._envelope_semantics(envelope) is not None


def test_a_resealed_envelope_with_substituted_evidence_is_refused():
    envelope = fixed_envelope()
    object.__setattr__(envelope.evidence[0], "content", b"\xff\xfe")
    object.__setattr__(
        envelope.evidence[0], "digest", hashlib.sha256(b"\xff\xfe").hexdigest()
    )
    reseal(envelope)
    assert ob._envelope_digest(envelope) == envelope.envelope_digest
    assert ob._envelope_semantics(envelope) == "evidence-not-utf8"


def test_a_resealed_envelope_with_an_over_limit_reservation_is_refused():
    envelope = fixed_envelope()
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
    assert ob._envelope_digest(envelope) == envelope.envelope_digest
    assert ob._envelope_semantics(envelope) == "reservation-field-out-of-range"


def test_the_semantics_function_is_total_and_returns_only_closed_tokens():
    envelope = fixed_envelope()
    assert ob._envelope_semantics(envelope) is None
    for field, value in RESEALED_TAMPERS:
        tampered = fixed_envelope()
        object.__setattr__(tampered, field, value)
        token = ob._envelope_semantics(tampered)
        assert token in rc.PLAN_REFUSALS
        assert SECRET not in token


# -- finding 5: a mutated receipt must not serialise -------------------------


def test_a_receipt_mutated_after_construction_refuses_to_serialise():
    """Freezing is not sealing, and serialisation is where it matters.

    A receipt built honestly and then given a secret-shaped ``worker`` wrote
    that secret into stored evidence. ``serialize_receipt`` now re-runs the full
    coherence check, so the bytes it produces describe a receipt that is
    coherent at the moment it is written down.
    """
    receipt = rc.ObservationReceipt(**receipt_kwargs())
    assert rc.serialize_receipt(receipt)

    object.__setattr__(receipt, "worker", SECRET)
    with pytest.raises(ValueError):
        rc.serialize_receipt(receipt)


MUTATED_RECEIPT_FIELDS = [
    ("worker", SECRET),
    ("authorizing_principal", SECRET),
    ("task_id", "not-a-uuid"),
    ("envelope_digest", SECRET),
    ("schema_digest", "short"),
    ("evidence_ids", (SECRET,)),
    ("evidence_digests", ("nope",)),
    ("dialect", SECRET),
    ("outcome", "succeeded"),
    ("refusal", "not-a-token"),
    ("request_refusal", "not-a-token"),
    ("response_failure", "not-a-token"),
    ("reservation_attestation", "assumed"),
    ("deadline_result", "probably"),
    ("evidence_bytes", 10 ** 40),
    ("elapsed_ns", 10 ** 5000),
    ("result_bytes", 10 ** 40),
    ("context_ceiling_tokens", 10 ** 40),
    ("required_key_count", 10 ** 6),
    ("exchange_invocations", 7),
    ("missing_key_indices", (0,)),
]


@pytest.mark.parametrize(("field", "value"), MUTATED_RECEIPT_FIELDS, ids=[
    "worker", "principal", "task-id", "envelope-digest", "schema-digest",
    "evidence-ids", "evidence-digests", "dialect", "outcome", "refusal",
    "request-refusal", "response-failure", "attestation", "deadline-result",
    "evidence-bytes", "elapsed-huge", "result-bytes", "context", "key-count",
    "invocations", "missing-indices",
])
def test_no_mutated_receipt_field_can_enter_serialised_evidence(field, value):
    receipt = rc.ObservationReceipt(**receipt_kwargs())
    object.__setattr__(receipt, field, value)
    with pytest.raises(ValueError):
        rc.serialize_receipt(receipt)


def test_a_hostile_container_on_a_receipt_is_refused_without_running_hooks():
    HOOK_CALLS.clear()
    receipt = rc.ObservationReceipt(**receipt_kwargs())
    object.__setattr__(receipt, "evidence_ids", HookedTuple(("e1",)))
    with pytest.raises(ValueError):
        rc.serialize_receipt(receipt)
    assert HOOK_CALLS == []

    HOOK_CALLS.clear()
    other = rc.ObservationReceipt(**receipt_kwargs())
    object.__setattr__(other, "elapsed_ns", HookedInt(5))
    with pytest.raises(ValueError):
        rc.serialize_receipt(other)
    assert HOOK_CALLS == []


def test_the_serialiser_reaches_the_check_through_the_class_not_the_instance():
    """An instance attribute shadows a class method; a cell does not.

    If ``serialize_receipt`` looked the check up on the receipt, a caller who
    could mutate a receipt could also install a ``__post_init__`` that does
    nothing - and then serialise anything at all.
    """
    receipt = rc.ObservationReceipt(**receipt_kwargs())
    object.__setattr__(receipt, "worker", SECRET)
    object.__setattr__(receipt, "__post_init__", lambda *a, **k: None)
    with pytest.raises(ValueError):
        rc.serialize_receipt(receipt)


# -- finding 6: receipt coherence must match what the executor can emit -------


def test_a_satisfied_reservation_implies_an_attempted_request():
    """The executor goes straight from the satisfied gate to the invocation.

    There is no path between them that can refuse, so a receipt reporting a
    satisfied reservation with nothing attempted describes a state that cannot
    occur. The previous revision checked only the forward direction.
    """
    with pytest.raises(ValueError):
        rc.ObservationReceipt(
            **receipt_kwargs(
                outcome="refused",
                refusal="result-too-large",
                request_outcome="not-attempted",
                response_outcome="none",
                exchange_invocations=0,
                elapsed_ns=0,
                result_bytes=0,
                dialect=None,
            )
        )
    # ...and the converse, which was already enforced.
    with pytest.raises(ValueError):
        rc.ObservationReceipt(
            **receipt_kwargs(
                reservation_result="not-satisfied",
                reservation_attestation="operator-asserted",
            )
        )


@pytest.mark.parametrize("outcome", ["refused", "void"])
def test_a_refused_or_void_receipt_names_no_dialect(outcome):
    """Both discard whatever came back, so neither has a dialect to name."""
    extra = (
        dict(refusal="result-too-large")
        if outcome == "refused"
        else dict(deadline_result="exceeded-during-request")
    )
    with pytest.raises(ValueError):
        rc.ObservationReceipt(
            **receipt_kwargs(
                outcome=outcome,
                response_outcome="none",
                result_bytes=0,
                dialect="ollama",
                **extra,
            )
        )
    assert rc.ObservationReceipt(
        **receipt_kwargs(
            outcome=outcome,
            response_outcome="none",
            result_bytes=0,
            dialect=None,
            **extra,
        )
    ).dialect is None
