"""OMI-V3A - an inert, provider-neutral observation envelope and its executor.

This package layer turns the *design requirement* recorded in
``docs/LOCAL_MODEL_DEPLOYMENT_INCEPTION.md`` § 7 - "Task envelope - design
requirements only" - into code, and stops exactly there. Nothing here contacts
an endpoint, resolves a name, opens a socket, downloads an artifact, starts a
runtime, registers a backend, inspects a process, or reads any hardware,
service or workload state. The one thing that could reach a network is an
**injected** exchange callable the caller supplies, and the hermetic rehearsal
in ``tests/test_omi_v3_observation_rehearsal.py`` runs the whole path inside
OMI-V1's ``hermetic_guard`` with an in-process double.

## Exact type is not unaltered, and this layer now says so twice

Jack's first independent round found the same mistake in three places: a
carrier was trusted because its *outer* type was exact, while its contents had
been altered underneath. An ``EvidenceItem`` whose bytes were swapped for
different bytes of the same length kept a stale digest and was adopted as an
envelope's initial state; a ``ResourceReservation`` whose ``cpu_cores`` had
been pushed past every ceiling kept a digest describing the old value, and a
``ReservationDecision`` bound to that stale digest was then honoured.

Two revalidations answer it, and they are deliberately not the same one:

  - **Before planning**, :func:`plan_observation` re-derives every digest from
    the bytes and fields it is actually given, in one controlled traversal, and
    refuses any carrier whose stored digest does not describe its own current
    content.
  - **Before executing**, :func:`execute_observation` first proves that every
    field of the envelope still holds its exact accepted runtime type - without
    iterating, comparing, hashing, representing or truth-testing anything
    foreign - and only then re-derives the digest tree.

## What OMI-V3A adds, and what it refuses to add

It adds the five envelope properties § 7 asked for - immutable task identity,
input hashes, bounded context, bounded result, a deadline, and provenance -
plus the two that § 4 and § 6 make prerequisites for any later live work: a
declared **loopback** endpoint, and an explicit **resource reservation** that
must be attested before anything runs.

It adds no second validator. The schema is validated and detached by OMI-V2's
own ``plan_structured_request`` - by the planner *and again* by the envelope
carrier, so a directly constructed envelope is held to exactly the standard the
planner applies. The response is validated by OMI-V2's own
``request_structured_json``. The dialect predicate, the two refusal
vocabularies and the response-failure vocabulary are imported, never restated.
``schema_conformance`` stays closed to ``"unverified"``.

## Structural versus attested

**Structural** - enforced by this code, and false only if the code is wrong:

  - the exchange callable is invoked **at most once**, latched, with no retry
    loop anywhere in OMI-V3A;
  - no tool is ever declared: the exchange is called with an empty tool list
    built at the call site, and there is no field, parameter or keyword by
    which a caller could add one;
  - an accepted envelope holds no caller-owned mutable object - evidence is
    exact ``bytes``, the schema is exact ``bytes``, everything else is a
    ``str``, an ``int``, a frozen carrier, or a tuple of those;
  - **every digest an accepted carrier holds describes that carrier's own
    current content**, re-derived at planning, at construction, and again
    before execution;
  - a directly constructed :class:`ObservationEnvelope` is subject to every
    check the planner applies, including OMI-V2's dialect and schema
    authorities;
  - every declared limit, every clock reading, every derived deadline and every
    recorded duration is an exact ``int`` inside a stated ceiling, checked
    before any comparison or representation;
  - both entry points are **total**: no input produces an exception, including
    a clock callable that raises;
  - the receipt has no field a payload could occupy, and every bound it
    documents it enforces.

**Attested** - recorded honestly, and true only if whoever attested was right:

  - the **resource reservation**. OMI-V3A refuses unless an injected
    :class:`ReservationDecision` reports it satisfied. It inspects no CPU, no
    memory, no GPU, no process, no service, and no concurrent workload - so
    what it verifies is a checker's or an operator's claim, not availability.
    *Which* party claimed it is carried into the receipt rather than collapsed
    into the satisfied token. Folding@home and BOINC remain senior per the
    inception note § 6, and nothing here can see them, let alone change them.
  - the **endpoint**. :func:`validate_loopback_endpoint` decides whether the
    *declared* request-time endpoint text is a numeric loopback HTTP ``/v1``
    endpoint. It resolves no name and opens no socket. An opaque backend
    factory handed to :func:`structured_exchange_adapter` could still be
    pointed somewhere else entirely; proving where a real adapter connects is
    live-adapter work under separate authority.
  - the **context ceiling**. It is carried and recorded. No tokenizer is run
    and no token count is verified.
  - the **clock**. The caller supplies the monotonic reading function; this
    module never reads a clock ambiently. Deadline arithmetic, ordering and
    magnitude are checked against the readings it is handed, which is not a
    claim that those readings came from ``time.monotonic_ns``.

## What one invocation does not prove

``exchange_invocations <= 1`` is a fact about *this* module's call site. It is
not a claim that an opaque SDK or HTTP client performs exactly one network
attempt: transports retry internally, and disabling and then proving that is
live-adapter work under separate authority.

## Observation only

There is no tool capability, no proposal capability, no commit capability, no
mutation action, no controller role, and no backend registration anywhere in
this module. The role is the ``Observer`` row of the inception note § 7 table
and nothing wider.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Optional

from scripts.agent_backends.base import Message
from scripts.agent_backends.structured_request import (
    StructuredOutputRequest,
    is_supported_dialect,
    plan_structured_request,
)
from scripts.open_model.observation_receipt import (
    MAX_CLOCK_NS,
    MAX_CONTEXT_CEILING_TOKENS,
    MAX_EVIDENCE_ITEMS,
    MAX_EVIDENCE_ITEM_BYTES,
    MAX_EVIDENCE_TOTAL_BYTES,
    MAX_REQUIRED_KEYS,
    MAX_RESULT_BYTES,
    PLAN_REFUSALS,
    RECEIPT_MAX_BYTES,
    RESERVATION_ATTESTATIONS,
    UNDESCRIBABLE_REFUSALS,
    EnvelopeRefusal,
    ExecutionRefusal,
    ObservationReceipt,
    PlanRefusal,
    ReservationAttestation,
    is_canonical_uuid4,
    is_sha256_digest,
)
from scripts.open_model.redaction import is_safe_token
from scripts.open_model.structured_exchange import (
    EXCHANGE_REFUSALS,
    RESPONSE_FAILURES,
    StructuredExchange,
    _restore_identity,
    request_structured_json,
)


# ``_restore_identity`` is imported from ``structured_exchange`` rather than
# copied a third time; see the same note in ``observation_receipt.py``. A
# control asserts this module's binding IS that module's object.


# -- bounds ------------------------------------------------------------------
#
# The bounds shared with the receipt layer are imported above rather than
# restated here, so there is exactly one of each number. The ones below belong
# only to this layer.


_MAX_ENDPOINT_CHARS: Final[int] = 128
_MAX_OUTPUT_TOKENS: Final[int] = 8192
_MAX_DURATION_NS: Final[int] = 3600000000000
_MAX_CPU_CORES: Final[int] = 256
_MAX_MEMORY_MIB: Final[int] = 1048576
_MAX_GPU_MEMORY_MIB: Final[int] = 1048576
_MAX_SCHEMA_BYTES: Final[int] = 65536
"""Ceiling on stored canonical schema bytes, mirroring OMI-V2's own.

It exists so that :class:`ObservationEnvelope` can bound the decode *before*
handing the document to OMI-V2, rather than decoding an arbitrarily large
buffer first. OMI-V2 remains the authority on what a schema may be; a control
asserts this mirror still equals ``structured_request._SCHEMA_MAX_CHARS``, so
the two cannot drift into disagreeing about which one refuses.
"""

OBSERVATION_LIMITS: Final[Mapping[str, int]] = MappingProxyType(
    {
        "endpoint_chars": _MAX_ENDPOINT_CHARS,
        "evidence_items": MAX_EVIDENCE_ITEMS,
        "evidence_item_bytes": MAX_EVIDENCE_ITEM_BYTES,
        "evidence_total_bytes": MAX_EVIDENCE_TOTAL_BYTES,
        "result_bytes": MAX_RESULT_BYTES,
        "context_ceiling_tokens": MAX_CONTEXT_CEILING_TOKENS,
        "output_tokens": _MAX_OUTPUT_TOKENS,
        "duration_ns": _MAX_DURATION_NS,
        "clock_ns": MAX_CLOCK_NS,
        "required_keys": MAX_REQUIRED_KEYS,
        "schema_bytes": _MAX_SCHEMA_BYTES,
        "receipt_bytes": RECEIPT_MAX_BYTES,
        "cpu_cores": _MAX_CPU_CORES,
        "memory_mib": _MAX_MEMORY_MIB,
        "gpu_memory_mib": _MAX_GPU_MEMORY_MIB,
    }
)
"""Read-only inspection mirror of every ceiling OMI-V3A enforces.

**Off the trust path.** Each bound is bound into a closure cell when the carrier
or the entry point it belongs to is defined, so rebinding this name - or
mutating what it maps to, which a ``MappingProxyType`` refuses anyway - cannot
widen or narrow a single check. It can only make the mirror disagree with the
code, which a control asserts against by exercising every bound at its ceiling
and one past it.
"""

OBSERVER_SYSTEM_PROMPT: Final[str] = (
    "You are an observation-only worker. Summarise only the evidence supplied "
    "in this request. You have no tools. You cannot propose, apply, or request "
    "any change, and you cannot request additional scope. Reply with a single "
    "JSON object and nothing else."
)
"""The only system text OMI-V3A ever sends. Fixed, inlined, caller-free.

A caller supplies evidence, never instructions - so no prompt this repository
sends can come to contain private text through this layer, exactly as
``PROBE_MESSAGES`` guarantees for the OMI-V1 evaluation harness. The text states
the ``Observer`` role from the inception note; it is not a security control, and
nothing downstream depends on a model honouring it.
"""


# -- identity ----------------------------------------------------------------


def _closed_task_id_factory():
    """Build :func:`new_task_id`, its generator bound in a closure cell."""
    _uuid4 = uuid.uuid4
    _str = str

    def new_task_id() -> str:
        """Return one canonical lowercase UUIDv4 string.

        Closed: the generator is captured, so rebinding this module's ``uuid``
        name cannot change what identifies a task.

        **No uniqueness claim is made.** ``uuid.uuid4`` draws from the
        platform's random source, and this function neither checks a registry
        nor consults any external authority. What OMI-V3A guarantees is that a
        task identifier is *canonical in form* and *fixed for the life of an
        envelope* - not that it has never been produced anywhere else.
        """
        return _str(_uuid4())

    return new_task_id


new_task_id = _restore_identity(_closed_task_id_factory(), "new_task_id", __name__)


# -- the clock ---------------------------------------------------------------


def _closed_clock_reader():
    """Build :func:`_read_clock`, builtins and the ceiling bound in cells."""
    _max_clock = MAX_CLOCK_NS
    _type = type
    _int = int
    _callable = callable
    _Exception = Exception

    def _read_clock(clock: Any) -> tuple[Optional[str], Optional[int]]:
        """Read one clock reading, or say in one neutral word why not.

        Returns ``(None, reading)`` on success and ``(code, None)`` otherwise,
        where ``code`` is one of ``"not-callable"``, ``"raised"``, ``"not-int"``,
        ``"negative"`` or ``"too-large"``. The caller maps that neutral code
        into its own closed vocabulary, which is why this function does not
        return a token itself: the planner and the executor spell the same
        conditions differently, and neither should have to import the other's
        words.

        **Nothing about a raised exception survives.** It is not re-raised, not
        rendered, not stored, and its type, message, arguments and
        representation are never read. The caller receives the fixed word
        ``"raised"`` and nothing else.

        One narrowing is stated rather than hidden. ``except Exception`` here
        means a clock that somehow performed I/O and raised OMI-V1's
        ``HermeticViolation`` would be *refused* rather than allowed to fail the
        run loudly. That is deliberate: a clock is not permitted to perform I/O,
        so such an exception is a caller error rather than a breach of the
        boundary this package guards. The hermetic guarantee that matters lives
        on the **exchange** path, which is not caught anywhere, and a control
        pins both halves of that split. ``BaseException`` is not caught, so
        ``KeyboardInterrupt`` and ``SystemExit`` still propagate.

        The magnitude bound is not decoration. An exact ``int`` has no width in
        Python, so a clock returning ``10**5000`` produced a perfectly ordinary
        envelope whose receipt could not be serialised at all - CPython refuses
        to render an integer that long. The reading is refused where it enters.
        """
        if not _callable(clock):
            return "not-callable", None
        try:
            reading = clock()
        except _Exception:
            return "raised", None
        if _type(reading) is not _int:
            return "not-int", None
        if reading < 0:
            return "negative", None
        if reading > _max_clock:
            return "too-large", None
        return None, reading

    return _read_clock


_read_clock = _restore_identity(_closed_clock_reader(), "_read_clock", __name__)


# -- evidence ----------------------------------------------------------------


def _build_evidence_item_class():
    """Build :class:`EvidenceItem` with its authorities in closure cells.

    ``hashlib`` is captured as the stdlib **module object**, matching the
    boundary OMI-V2 drew for ``json`` and ``math``: rebinding this module's
    ``hashlib`` name is closed; patching an attribute on the captured stdlib
    module remains the documented arbitrary-code-replacement boundary.
    """
    _safe_token = is_safe_token
    _max_bytes = MAX_EVIDENCE_ITEM_BYTES
    _hashlib = hashlib
    _type = type
    _bytes = bytes
    _len = len
    _object = object
    _ValueError = ValueError

    @dataclass(frozen=True)
    class EvidenceItem:
        """One explicit piece of evidence, with a digest this package computed.

        ``content`` must be exactly built-in ``bytes``. A ``bytearray``, a
        ``memoryview`` and a ``bytes`` **subclass** are all refused: the first
        two are mutable, so a digest taken over them could stop describing what
        is stored, and the third can override methods, so nothing read from it
        could be trusted to be what it claimed.

        ``digest`` is **not** an init field. It is computed here, from the
        object that was accepted, at the moment it was accepted - so a caller
        cannot supply one, and there is no window between the check and the
        hash.

        **Freezing is not sealing.** ``object.__setattr__`` will still replace
        any field on this frozen carrier, and the digest computed here will not
        follow. That is exactly the hole Jack's first round walked through, and
        the answer is not here - a carrier cannot defend its own past. It is in
        :func:`plan_observation` and :meth:`ObservationEnvelope.__post_init__`,
        both of which re-derive this digest from the bytes actually present
        before adopting the item, and in :func:`execute_observation`, which does
        it again before acting on an envelope.

        Refusal is by ``ValueError`` rather than a token, matching
        ``EvaluationCase.case_id``: an unusable evidence item is an authoring
        mistake that should surface where it was written. Callers who want a
        token hand the item to :func:`plan_observation`, which is total over
        anything at all.
        """

        evidence_id: str
        content: bytes
        digest: str = field(init=False, default="")

        def __post_init__(self) -> None:
            if not _safe_token(self.evidence_id):
                raise _ValueError(
                    "evidence_id must be a safe token: bounded, "
                    "[A-Za-z0-9][A-Za-z0-9._-]*, and not secret-shaped"
                )
            if _type(self.content) is not _bytes:
                raise _ValueError("evidence content must be exactly built-in bytes")
            size = _len(self.content)
            if size == 0:
                raise _ValueError("evidence content must not be empty")
            if size > _max_bytes:
                raise _ValueError("evidence content exceeds the per-item bound")
            _object.__setattr__(
                self, "digest", _hashlib.sha256(self.content).hexdigest()
            )

    return EvidenceItem


EvidenceItem = _restore_identity(
    _build_evidence_item_class(), "EvidenceItem", __name__
)


# -- resource reservation ----------------------------------------------------


def _closed_reservation_digest():
    """Build :func:`_reservation_digest`, its dependencies bound in cells.

    One function computes it, and the carrier, the planner, the envelope and the
    executor all call it - so "the digest a reservation stores" and "the digest
    re-derived from its fields" cannot be two renderings that happen to agree
    today.
    """
    _hashlib = hashlib
    _json = json

    def _reservation_digest(cpu_cores: int, memory_mib: int, gpu_memory_mib) -> str:
        """Digest the three declared figures, canonically."""
        rendered = _json.dumps(
            {
                "cpu_cores": cpu_cores,
                "gpu_memory_mib": gpu_memory_mib,
                "memory_mib": memory_mib,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        return _hashlib.sha256(rendered).hexdigest()

    return _reservation_digest


_reservation_digest = _restore_identity(
    _closed_reservation_digest(), "_reservation_digest", __name__
)


def _build_reservation_class():
    """Build :class:`ResourceReservation`, bounds and builtins in cells."""
    _max_cpu = _MAX_CPU_CORES
    _max_memory = _MAX_MEMORY_MIB
    _max_gpu = _MAX_GPU_MEMORY_MIB
    _digest_of = _reservation_digest
    _type = type
    _int = int
    _object = object
    _ValueError = ValueError

    @dataclass(frozen=True)
    class ResourceReservation:
        """What an observation declares it needs, before anything runs.

        The inception note § 6 makes the rule this carrier serves: *the
        experiment declares its CPU, GPU, and memory reservations up front, and
        if they are not available it defers.* Declaring them is all this carrier
        does. Deciding whether they are available is somebody else's job,
        reported through :class:`ReservationDecision`, and OMI-V3A never looks
        for itself.

        ``gpu_memory_mib`` is optional because an observation may legitimately
        need none. ``None`` means *no GPU reservation is declared*, which is not
        the same as *zero GPU memory is required*; zero is refused, so the two
        cannot be confused.

        ``digest`` is computed here and is what binds a decision to the
        reservation it was made about. As with :class:`EvidenceItem`, freezing
        does not stop ``object.__setattr__``, so every consumer re-derives this
        digest from the fields actually present rather than trusting it.
        """

        cpu_cores: int
        memory_mib: int
        gpu_memory_mib: Optional[int] = None
        digest: str = field(init=False, default="")

        def __post_init__(self) -> None:
            if _type(self.cpu_cores) is not _int:
                raise _ValueError("cpu_cores must be exactly a built-in int")
            if self.cpu_cores < 1 or self.cpu_cores > _max_cpu:
                raise _ValueError("cpu_cores is out of range")
            if _type(self.memory_mib) is not _int:
                raise _ValueError("memory_mib must be exactly a built-in int")
            if self.memory_mib < 1 or self.memory_mib > _max_memory:
                raise _ValueError("memory_mib is out of range")
            if self.gpu_memory_mib is not None:
                if _type(self.gpu_memory_mib) is not _int:
                    raise _ValueError(
                        "gpu_memory_mib must be exactly a built-in int or None"
                    )
                if self.gpu_memory_mib < 1 or self.gpu_memory_mib > _max_gpu:
                    raise _ValueError("gpu_memory_mib is out of range")
            _object.__setattr__(
                self,
                "digest",
                _digest_of(self.cpu_cores, self.memory_mib, self.gpu_memory_mib),
            )

    return ResourceReservation


ResourceReservation = _restore_identity(
    _build_reservation_class(), "ResourceReservation", __name__
)


def _build_reservation_decision_class():
    """Build :class:`ReservationDecision`, its vocabulary bound in a cell."""
    _attestations = RESERVATION_ATTESTATIONS
    _digest_ok = is_sha256_digest
    _type = type
    _str = str
    _bool = bool
    _ValueError = ValueError

    @dataclass(frozen=True)
    class ReservationDecision:
        """Somebody else's answer to "is this reservation available?".

        Injected, never derived. OMI-V3A inspects no hardware, no process, no
        service and no concurrent workload, so the only honest thing it can do
        with a reservation is refuse to proceed until a named party says the
        reservation holds - and then record *that a party said so*, and *which
        party*, in the receipt.

        ``reservation_digest`` binds this decision to one
        :class:`ResourceReservation`. Without it, a decision made about a small
        reservation could be presented against a large one. The executor binds
        it to the digest **re-derived** from the reservation's current fields,
        not to the digest the reservation happens to be storing.

        ``satisfied`` must be exactly a ``bool``: a foreign object with a
        ``__bool__`` must not be able to walk itself through the gate. The
        executor re-checks that, and every other field here, before reading any
        of them - because freezing this carrier does not stop
        ``object.__setattr__`` from replacing a field after construction.
        """

        reservation_digest: str
        satisfied: bool
        attestation: ReservationAttestation

        def __post_init__(self) -> None:
            if not _digest_ok(self.reservation_digest):
                raise _ValueError(
                    "reservation_digest must be 64 lowercase hex characters"
                )
            if _type(self.satisfied) is not _bool:
                raise _ValueError("satisfied must be exactly a bool")
            if (
                _type(self.attestation) is not _str
                or self.attestation not in _attestations
            ):
                raise _ValueError(
                    "attestation must be a token from the closed vocabulary"
                )

    return ReservationDecision


ReservationDecision = _restore_identity(
    _build_reservation_decision_class(), "ReservationDecision", __name__
)


# -- declared loopback endpoint ----------------------------------------------


def _closed_endpoint_validator():
    """Build :func:`validate_loopback_endpoint`, everything bound in cells.

    Hand-parsed by string slicing rather than routed through ``urllib.parse``,
    for the reason ``registry._host_of`` gives: this layer must keep importing
    nothing that can perform I/O. Nothing here resolves a name or opens a
    socket, and there is no code path by which it could.
    """
    _digits = frozenset("0123456789")
    _max_chars = _MAX_ENDPOINT_CHARS
    _type = type
    _str = str
    _len = len
    _int = int

    def _is_numeric_loopback_v4(host: str) -> bool:
        """True only for a dotted-quad in ``127.0.0.0/8``, written canonically.

        Exactly four decimal octets, each 1-3 ASCII digits with no leading zero,
        each at most 255, and the first exactly ``127``. That single rule
        disposes of every ambiguous spelling at once: ``127.1``, ``2130706433``,
        ``0x7f000001``, ``0177.0.0.1``, ``127.00.0.1`` and ``127.0.0.1.`` are
        all refused, as are ``0.0.0.0`` (every interface, the opposite of the
        property wanted) and every non-loopback address.
        """
        octets = host.split(".")
        if _len(octets) != 4:
            return False
        for text in octets:
            if not text or _len(text) > 3:
                return False
            for character in text:
                if character not in _digits:
                    return False
            if _len(text) > 1 and text[0] == "0":
                return False
            if _int(text) > 255:
                return False
        return octets[0] == "127"

    def validate_loopback_endpoint(value: Any) -> Optional[EnvelopeRefusal]:
        """Return ``None`` for an acceptable declared endpoint, else a token.

        Accepts exactly ``http://<numeric-loopback>:<port>/v1``, where the host
        is a canonical dotted-quad in ``127.0.0.0/8`` or the bracketed literal
        ``[::1]``, and the port is a canonical decimal 1-65535.

        Refused, each with its own token: any scheme other than lowercase
        ``http://``; user information; a query or fragment; any percent-encoding
        anywhere; a DNS name, including ``localhost`` and ``*.localhost``;
        ``0.0.0.0``; any non-loopback address; the long-form
        ``[0:0:0:0:0:0:0:1]`` and the mapped ``[::ffff:127.0.0.1]``; a missing
        port; a port with a leading zero, a sign, non-ASCII digits, or a value
        outside 1-65535; and any path other than exactly ``/v1``.

        Non-ASCII digits matter more than they look. ``int("١٢")`` is
        ``12`` - Python's ``int`` accepts Unicode decimal digits and
        ``str.isdigit`` returns True for them - so a port written in
        Arabic-Indic digits would parse to a perfectly ordinary number. Every
        character is therefore checked against an explicit ASCII set before any
        conversion runs.

        **This validates declared text.** It is not a claim about where a
        request goes. Nothing is resolved and nothing is connected.
        """
        if _type(value) is not _str:
            return "endpoint-not-exact-str"
        if _len(value) > _max_chars:
            return "endpoint-too-long"
        # Checked over the whole string, before it is split: a percent-escape is
        # how an authority hides a delimiter, so it is refused wherever it
        # appears rather than only where it would currently matter.
        if "%" in value:
            return "endpoint-percent-encoded"
        if "?" in value or "#" in value:
            return "endpoint-query-or-fragment-present"
        if "@" in value:
            return "endpoint-userinfo-present"
        if not value.startswith("http://"):
            return "endpoint-scheme-not-plain-http"
        remainder = value[7:]
        slash = remainder.find("/")
        if slash == -1:
            return "endpoint-path-not-v1"
        authority = remainder[:slash]
        if remainder[slash:] != "/v1":
            return "endpoint-path-not-v1"
        if authority.startswith("["):
            close = authority.find("]")
            if close == -1:
                return "endpoint-host-not-numeric-loopback"
            # Exactly the compressed literal. The long form and the mapped form
            # both denote the same address and are refused anyway: two spellings
            # of one endpoint is one spelling too many for an envelope whose
            # digest has to be comparable.
            if authority[: close + 1] != "[::1]":
                return "endpoint-host-not-numeric-loopback"
            rest = authority[close + 1 :]
            if not rest:
                return "endpoint-port-missing"
            if rest[0] != ":":
                return "endpoint-host-not-numeric-loopback"
            port_text = rest[1:]
        else:
            colon = authority.find(":")
            if colon == -1:
                if not _is_numeric_loopback_v4(authority):
                    return "endpoint-host-not-numeric-loopback"
                return "endpoint-port-missing"
            # A second colon outside brackets is an unbracketed IPv6 authority
            # or a malformed one; either way it is not a dotted quad.
            if authority.find(":", colon + 1) != -1:
                return "endpoint-host-not-numeric-loopback"
            if not _is_numeric_loopback_v4(authority[:colon]):
                return "endpoint-host-not-numeric-loopback"
            port_text = authority[colon + 1 :]
        if not port_text:
            return "endpoint-port-missing"
        if _len(port_text) > 5:
            return "endpoint-port-not-canonical"
        for character in port_text:
            if character not in _digits:
                return "endpoint-port-not-canonical"
        if port_text[0] == "0":
            return "endpoint-port-not-canonical"
        if _int(port_text) > 65535:
            return "endpoint-port-not-canonical"
        return None

    return validate_loopback_endpoint


validate_loopback_endpoint = _restore_identity(
    _closed_endpoint_validator(), "validate_loopback_endpoint", __name__
)


# -- the canonical schema rendering ------------------------------------------


def _closed_schema_canonicaliser():
    """Build :func:`_canonical_schema`, its dependencies bound in cells.

    OMI-V2 decides what a schema may be; this only renders the snapshot OMI-V2
    produced into stable bytes, and re-derives those bytes wherever a stored
    copy has to be trusted. There is no schema validation here and there will
    not be: ``plan_structured_request`` is the single authority, called from
    both the planner and the envelope carrier.
    """
    _plan_request = plan_structured_request
    _request_type = StructuredOutputRequest
    _json = json
    _type = type
    _dict = dict

    def _canonical_schema(dialect: Any, schema: Any):
        """Return ``(refusal, bytes)``: OMI-V2's verdict, and stable bytes.

        ``refusal`` is OMI-V2's own token, unchanged, or ``None``. On success
        the bytes are the canonical ASCII rendering of the **detached snapshot**
        OMI-V2 built - a structure containing exactly the values it inspected,
        because validation and copying are one traversal there.

        Key order is canonicalised so the digest is comparable between two
        parties. JSON object member order is not semantically significant, and a
        comparable digest is worth more than preserved authoring order.
        """
        plan = _plan_request(dialect, _request_type(schema=schema), has_tools=False)
        if not plan.ok:
            return plan.refusal, None
        snapshot = plan.response_format["json_schema"]["schema"]
        if _type(snapshot) is not _dict:
            # Unreachable while OMI-V2's wire-shape guard holds; a refusal
            # rather than an assert so behaviour is identical under -O and -OO.
            return "schema-not-exact-dict", None
        return None, _json.dumps(
            snapshot,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")

    return _canonical_schema


_canonical_schema = _restore_identity(
    _closed_schema_canonicaliser(), "_canonical_schema", __name__
)


# -- the one semantic authority ----------------------------------------------
#
# Jack's second round found the planner and the envelope carrier disagreeing
# about what an acceptable envelope is - the planner required strict UTF-8
# evidence and the carrier did not - and found the executor treating digest
# equality as a proof of validity it cannot be. All three now consult the same
# functions, so there is one definition of "acceptable" and it cannot drift.


class _EnvelopeRefused(ValueError):
    """Raised by :class:`ObservationEnvelope` with the token that refused it.

    A ``ValueError`` subclass, so every caller that already expected a
    ``ValueError`` from a bad direct construction still gets one. The ``token``
    attribute is what lets :func:`plan_observation` stay total: it catches this
    and returns the token rather than letting an exception escape.

    The token is always a member of the closed ``PLAN_REFUSALS`` set, so it is
    safe to log, safe to compare, and carries nothing of the caller's input.
    """

    def __init__(self, token: str) -> None:
        super().__init__(token)
        self.token = token


def _closed_evidence_state():
    """Build :func:`_evidence_state`, every dependency bound in a cell."""
    _EvidenceItem = EvidenceItem
    _safe_token = is_safe_token
    _hashlib = hashlib
    _max_items = MAX_EVIDENCE_ITEMS
    _max_item_bytes = MAX_EVIDENCE_ITEM_BYTES
    _max_total_bytes = MAX_EVIDENCE_TOTAL_BYTES
    _type = type
    _str = str
    _int = int
    _bytes = bytes
    _tuple = tuple
    _set = set
    _len = len
    _UnicodeDecodeError = UnicodeDecodeError

    def _evidence_state(items: Any, declared_max: Any):
        """Validate an evidence tuple; return ``(refusal, total_bytes)``.

        Total over any input. Every value is checked by ``type(x) is T``
        identity before it is read, so no supplied ``__len__``, ``__eq__``,
        ``__hash__``, ``__iter__`` or ``decode`` runs on caller data, and no
        rejected value's text, size, position or type name reaches the token.

        Each item's digest is **recomputed from the bytes actually present**,
        and strict UTF-8 decodability is settled here - the check the envelope
        carrier was missing, which let invalid bytes reach the adapter and raise
        ``UnicodeDecodeError`` out of a function documented as total.
        """
        if _type(items) is not _tuple:
            return "evidence-not-exact-sequence", 0
        if not items:
            return "evidence-empty", 0
        if _len(items) > _max_items:
            return "evidence-too-many-items", 0
        bounded = declared_max if _type(declared_max) is _int else _max_total_bytes
        seen = _set()
        total = 0
        for item in items:
            if _type(item) is not _EvidenceItem:
                return "evidence-item-not-exact-type", 0
            if _type(item.evidence_id) is not _str or not _safe_token(
                item.evidence_id
            ):
                return "evidence-id-not-safe-token", 0
            if item.evidence_id in seen:
                return "evidence-id-duplicated", 0
            seen.add(item.evidence_id)
            if _type(item.content) is not _bytes:
                return "evidence-content-not-exact-bytes", 0
            size = _len(item.content)
            if size == 0:
                return "evidence-item-empty", 0
            if size > _max_item_bytes or size > bounded:
                return "evidence-item-too-large", 0
            if _type(item.digest) is not _str or (
                _hashlib.sha256(item.content).hexdigest() != item.digest
            ):
                return "evidence-digest-not-recomputable", 0
            total += size
            if total > _max_total_bytes or total > bounded:
                return "evidence-total-too-large", 0
            try:
                item.content.decode("utf-8")
            except _UnicodeDecodeError:
                return "evidence-not-utf8", 0
        return None, total

    return _evidence_state


_evidence_state = _restore_identity(
    _closed_evidence_state(), "_evidence_state", __name__
)


def _closed_reservation_state():
    """Build :func:`_reservation_state`, every dependency bound in a cell."""
    _ResourceReservation = ResourceReservation
    _digest_of = _reservation_digest
    _max_cpu = _MAX_CPU_CORES
    _max_memory = _MAX_MEMORY_MIB
    _max_gpu = _MAX_GPU_MEMORY_MIB
    _type = type
    _str = str
    _int = int

    def _reservation_state(reservation: Any) -> Optional[EnvelopeRefusal]:
        """Validate a reservation carrier and its digest. Total over any input."""
        if _type(reservation) is not _ResourceReservation:
            return "reservation-not-exact-type"
        if _type(reservation.cpu_cores) is not _int or (
            _type(reservation.memory_mib) is not _int
        ):
            return "reservation-field-not-exact-int"
        if reservation.gpu_memory_mib is not None and (
            _type(reservation.gpu_memory_mib) is not _int
        ):
            return "reservation-field-not-exact-int"
        if reservation.cpu_cores < 1 or reservation.cpu_cores > _max_cpu:
            return "reservation-field-out-of-range"
        if reservation.memory_mib < 1 or reservation.memory_mib > _max_memory:
            return "reservation-field-out-of-range"
        if reservation.gpu_memory_mib is not None and (
            reservation.gpu_memory_mib < 1 or reservation.gpu_memory_mib > _max_gpu
        ):
            return "reservation-field-out-of-range"
        if _type(reservation.digest) is not _str or _digest_of(
            reservation.cpu_cores, reservation.memory_mib, reservation.gpu_memory_mib
        ) != reservation.digest:
            return "reservation-digest-not-recomputable"
        return None

    return _reservation_state


_reservation_state = _restore_identity(
    _closed_reservation_state(), "_reservation_state", __name__
)


def _closed_envelope_semantics():
    """Build :func:`_envelope_semantics`, every dependency bound in a cell."""
    _evidence_ok = _evidence_state
    _reservation_ok = _reservation_state
    _safe_token = is_safe_token
    _uuid4_ok = is_canonical_uuid4
    _endpoint_ok = validate_loopback_endpoint
    _dialect_ok = is_supported_dialect
    _canonical = _canonical_schema
    _hashlib = hashlib
    _json = json
    _max_keys = MAX_REQUIRED_KEYS
    _max_total_bytes = MAX_EVIDENCE_TOTAL_BYTES
    _max_result = MAX_RESULT_BYTES
    _max_context = MAX_CONTEXT_CEILING_TOKENS
    _max_output = _MAX_OUTPUT_TOKENS
    _max_duration = _MAX_DURATION_NS
    _max_clock = MAX_CLOCK_NS
    _max_schema = _MAX_SCHEMA_BYTES
    _type = type
    _str = str
    _int = int
    _bytes = bytes
    _tuple = tuple
    _len = len
    _getattr = getattr
    _Exception = Exception

    def _envelope_semantics(envelope: Any) -> Optional[Any]:
        """Every constraint an accepted envelope must satisfy, in one place.

        Returns ``None`` when the envelope is acceptable, else one token from
        the closed ``PLAN_REFUSALS`` set. Total over any envelope: nothing here
        raises, and every value is checked by exact-type identity before it is
        read, iterated, hashed or compared.

        Deliberately does **not** check ``envelope_digest``. The digest is a
        pure function of these fields, so checking it here would be circular -
        and, because it is unkeyed, it is checked *in addition to* this function
        rather than instead of it. That distinction is Jack's third second-round
        finding: **digest equality is self-consistency, never validity.** Anyone
        able to mutate a field can recompute the digest with this package's own
        exported function, so an envelope that agrees with its digest has proved
        only that nobody was careless.

        Called by :meth:`ObservationEnvelope.__post_init__` (which raises the
        token), by :func:`plan_observation` (through construction), and by
        :func:`execute_observation` (which refuses with one fixed token). One
        definition, three consumers, no drift.
        """
        if not _uuid4_ok(envelope.task_id):
            return "task-id-not-canonical-uuid4"
        if not _safe_token(envelope.authorizing_principal):
            return "principal-not-safe-token"
        if not _safe_token(envelope.worker):
            return "worker-not-safe-token"
        # OMI-V2 owns the dialect decision, and its token travels through.
        if not _dialect_ok(envelope.dialect):
            return "dialect-unsupported"
        # -- declared limits, before anything is measured against them --------
        for name, ceiling in (
            ("context_ceiling_tokens", _max_context),
            ("max_evidence_bytes", _max_total_bytes),
            ("max_result_bytes", _max_result),
            ("max_output_tokens", _max_output),
        ):
            number = _getattr(envelope, name)
            if _type(number) is not _int:
                return "limit-not-exact-int"
            if number < 1 or number > ceiling:
                return "limit-out-of-range"
        # -- evidence ----------------------------------------------------------
        refusal, _total = _evidence_ok(envelope.evidence, envelope.max_evidence_bytes)
        if refusal is not None:
            return refusal
        # -- the stored schema -------------------------------------------------
        if _type(envelope.schema_bytes) is not _bytes:
            return "schema-bytes-not-exact-bytes"
        if not envelope.schema_bytes or _len(envelope.schema_bytes) > _max_schema:
            return "schema-bytes-not-canonical"
        try:
            parsed = _json.loads(envelope.schema_bytes.decode("ascii"))
        except _Exception:
            # Fixed token. Neither the decoder's message, nor a byte value, nor
            # any fragment of the stored bytes reaches it.
            return "schema-bytes-not-canonical"
        schema_refusal, canonical = _canonical(envelope.dialect, parsed)
        if schema_refusal is not None:
            return schema_refusal
        if canonical != envelope.schema_bytes:
            return "schema-bytes-not-canonical"
        if _type(envelope.schema_digest) is not _str or (
            _hashlib.sha256(envelope.schema_bytes).hexdigest() != envelope.schema_digest
        ):
            return "schema-digest-not-recomputable"
        # -- required keys -----------------------------------------------------
        if _type(envelope.required_keys) is not _tuple:
            return "required-keys-not-exact-sequence"
        if _len(envelope.required_keys) > _max_keys:
            return "required-keys-too-many"
        for key in envelope.required_keys:
            if not _safe_token(key):
                return "required-key-not-safe-token"
        # -- the declared endpoint ---------------------------------------------
        endpoint_refusal = _endpoint_ok(envelope.endpoint)
        if endpoint_refusal is not None:
            return endpoint_refusal
        # -- the reservation ---------------------------------------------------
        reservation_refusal = _reservation_ok(envelope.reservation)
        if reservation_refusal is not None:
            return reservation_refusal
        # -- the clock figures -------------------------------------------------
        if _type(envelope.issued_ns) is not _int or envelope.issued_ns < 0:
            return "clock-reading-not-exact-int"
        if envelope.issued_ns > _max_clock:
            return "clock-reading-too-large"
        if _type(envelope.deadline_ns) is not _int:
            return "clock-reading-not-exact-int"
        if envelope.deadline_ns > _max_clock:
            return "deadline-beyond-clock-ceiling"
        duration = envelope.deadline_ns - envelope.issued_ns
        if duration < 1 or duration > _max_duration:
            return "duration-out-of-range"
        return None

    return _envelope_semantics


_envelope_semantics = _restore_identity(
    _closed_envelope_semantics(), "_envelope_semantics", __name__
)


def _closed_exchange_check():
    """Build :func:`_exchange_fields_intact`, every dependency in a cell."""
    _exchange_type = StructuredExchange
    _refusals = EXCHANGE_REFUSALS
    _failures = RESPONSE_FAILURES
    _dialect_ok = is_supported_dialect
    _proxy = MappingProxyType
    _type = type
    _str = str
    _bool = bool
    _int = int
    _tuple = tuple

    def _exchange_fields_intact(completed: Any) -> bool:
        """True only if OMI-V2's carrier still holds its accepted field types.

        Freezing does not stop ``object.__setattr__``, and the previous revision
        checked only the carrier's outer type before reading ``ok`` in a boolean
        context, copying ``value``, and copying ``dialect`` into a receipt. Jack
        demonstrated all three: a ``__bool__`` hook ran, a substituted mapping's
        ``keys``/``__getitem__`` ran, and a secret-shaped ``dialect`` reached
        receipt construction and raised ``ValueError`` out of a function
        documented as total.

        OMI-V2 remains the authority on what these values may be: the two
        vocabularies and the dialect predicate are imported, never restated.

        **One residual, stated rather than hidden.** When ``ok`` is true the
        value must be exactly a ``MappingProxyType``, which closes every
        substitution of a different type - but a proxy can wrap an arbitrary
        foreign mapping, and OMI-V2's own carrier records that there is no
        hook-free way to inspect what a proxy wraps. Walking such a proxy to
        measure the result therefore can still run its hooks. What that cannot
        do is put anything in the receipt: the receipt receives a byte count and
        nothing else from the value, and the walk is bounded by a catch that
        turns any failure into one fixed refusal.
        """
        if _type(completed) is not _exchange_type:
            return False
        if _type(completed.ok) is not _bool:
            return False
        if _type(completed.response_format_sent) is not _bool:
            return False
        if _type(completed.schema_conformance) is not _str or (
            completed.schema_conformance != "unverified"
        ):
            return False
        if completed.dialect is not None and not _dialect_ok(completed.dialect):
            return False
        if completed.request_refusal is not None and (
            _type(completed.request_refusal) is not _str
            or completed.request_refusal not in _refusals
        ):
            return False
        if completed.response_failure is not None and (
            _type(completed.response_failure) is not _str
            or completed.response_failure not in _failures
        ):
            return False
        if _type(completed.missing_key_indices) is not _tuple:
            return False
        previous = -1
        for index in completed.missing_key_indices:
            if _type(index) is not _int or index <= previous:
                return False
            previous = index
        if completed.ok:
            return _type(completed.value) is _proxy
        return completed.value is None

    return _exchange_fields_intact


_exchange_fields_intact = _restore_identity(
    _closed_exchange_check(), "_exchange_fields_intact", __name__
)


# -- the envelope ------------------------------------------------------------


def _closed_envelope_digest():
    """Build :func:`_envelope_digest`, its dependencies bound in cells.

    One function computes the digest, and the constructor and the executor both
    call it - so "the digest recorded at planning time" and "the digest
    recomputed at execution time" cannot be two different renderings that happen
    to agree today.
    """
    _hashlib = hashlib
    _json = json
    _list = list
    _len = len

    def _envelope_digest(envelope: Any) -> str:
        """Digest what the envelope *contains*, not what it says it contains.

        Every stored digest is written down **beside a digest recomputed here
        from the bytes themselves**, and every carrier that holds a digest has
        its own fields written down beside it. That redundancy closes a hole an
        earlier revision had: it read ``item.digest`` and ``len(item.content)``
        only, so replacing an evidence item's content with *different bytes of
        the same length* left the envelope digest completely unchanged.

        This function assumes its input has already passed the field-type
        revalidation below. It is never called on an unchecked object.
        """
        document = {
            "contract": "omi-v3a-observation-envelope",
            "task_id": envelope.task_id,
            "authorizing_principal": envelope.authorizing_principal,
            "worker": envelope.worker,
            "dialect": envelope.dialect,
            "schema": [
                envelope.schema_digest,
                _hashlib.sha256(envelope.schema_bytes).hexdigest(),
            ],
            "evidence": [
                [
                    item.evidence_id,
                    item.digest,
                    _hashlib.sha256(item.content).hexdigest(),
                    _len(item.content),
                ]
                for item in envelope.evidence
            ],
            "required_keys": _list(envelope.required_keys),
            "endpoint": envelope.endpoint,
            "reservation": [
                envelope.reservation.cpu_cores,
                envelope.reservation.memory_mib,
                envelope.reservation.gpu_memory_mib,
                envelope.reservation.digest,
            ],
            "context_ceiling_tokens": envelope.context_ceiling_tokens,
            "max_evidence_bytes": envelope.max_evidence_bytes,
            "max_result_bytes": envelope.max_result_bytes,
            "max_output_tokens": envelope.max_output_tokens,
            "issued_ns": envelope.issued_ns,
            "deadline_ns": envelope.deadline_ns,
        }
        rendered = _json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        return _hashlib.sha256(rendered).hexdigest()

    return _envelope_digest


_envelope_digest = _restore_identity(
    _closed_envelope_digest(), "_envelope_digest", __name__
)


def _build_envelope_class():
    """Build :class:`ObservationEnvelope` with its authorities in cells."""
    _semantics = _envelope_semantics
    _digest_of = _envelope_digest
    _EvidenceItem = EvidenceItem
    _ResourceReservation = ResourceReservation
    _Refused = _EnvelopeRefused
    _tuple = tuple
    _object = object

    @dataclass(frozen=True)
    class ObservationEnvelope:
        """One complete, immutable, self-describing observation plan.

        Normally produced by :func:`plan_observation`, which is total and
        returns a token for anything it will not accept. **Constructing one
        directly is supported and re-runs every check the planner applies** -
        and that sentence is now true, which it was not before. Jack's first
        independent round constructed direct envelopes carrying a secret-shaped
        dialect, schema bytes that were not JSON at all, a ``schema_digest``
        that hashed nothing, and evidence whose stored digest described bytes
        that were no longer there. Every one of those constructs a
        ``ValueError`` now.

        The checks below are the planner's, not a weaker echo of them:

        - the dialect is put to OMI-V2's ``is_supported_dialect``;
        - ``schema_bytes`` is bounded, decoded, parsed, and put back through
          OMI-V2's ``plan_structured_request``; the snapshot it returns is
          re-rendered canonically and must equal ``schema_bytes`` **exactly**,
          so the stored bytes are provably the canonical form of a schema OMI-V2
          accepts for this dialect;
        - ``schema_digest`` must hash exactly those bytes;
        - every evidence item's digest is recomputed from its own bytes;
        - the reservation's digest is recomputed from its own fields;
        - every limit, the derived duration, and both clock figures are exact
          ints inside their stated ceilings.

        **Nothing reachable from an accepted envelope is caller-owned and
        mutable.** ``evidence`` is a tuple of frozen items holding exact
        ``bytes``; ``schema_bytes`` is exact ``bytes``; ``required_keys`` is a
        tuple of ``str``; ``reservation`` is frozen and holds ints.

        ``envelope_digest`` is not an init field: it is computed here, over the
        fields as accepted. The executor recomputes it before it does anything
        else, so an ``object.__setattr__`` on this frozen carrier between
        planning and execution is refused rather than acted on.
        """

        task_id: str
        authorizing_principal: str
        worker: str
        evidence: tuple[EvidenceItem, ...]
        dialect: str
        schema_bytes: bytes
        schema_digest: str
        required_keys: tuple[str, ...]
        endpoint: str
        reservation: ResourceReservation
        context_ceiling_tokens: int
        max_evidence_bytes: int
        max_result_bytes: int
        max_output_tokens: int
        issued_ns: int
        deadline_ns: int
        envelope_digest: str = field(init=False, default="")

        def __post_init__(self) -> None:
            """Validate through the one semantic authority, then detach.

            Every constraint lives in :func:`_envelope_semantics`, which the
            planner and the executor also consult - so "what the planner
            accepts" and "what direct construction accepts" are the same set by
            construction rather than by two authors agreeing. Jack's first round
            found them disagreeing about the dialect and the schema; his second
            found them still disagreeing about strict UTF-8 evidence. They
            cannot disagree now: there is one function.

            The refusal is raised as :class:`_EnvelopeRefused`, a ``ValueError``
            carrying the closed token, so :func:`plan_observation` stays total by
            translating it back into a plan refusal.

            **Detachment.** After validation the accepted primitive values are
            copied into fresh package-owned carriers. A caller who keeps a
            reference to the ``EvidenceItem`` or ``ResourceReservation`` they
            passed in holds an object this envelope no longer contains, so
            mutating it afterwards reaches nothing here. The values copied
            across are exact ``str``, ``bytes`` and ``int`` - all immutable -
            and each fresh carrier recomputes its own digest from them, so
            detaching cannot itself introduce a stale one.
            """
            refusal = _semantics(self)
            if refusal is not None:
                raise _Refused(refusal)
            _object.__setattr__(
                self,
                "evidence",
                _tuple(
                    _EvidenceItem(evidence_id=item.evidence_id, content=item.content)
                    for item in self.evidence
                ),
            )
            _object.__setattr__(
                self,
                "reservation",
                _ResourceReservation(
                    cpu_cores=self.reservation.cpu_cores,
                    memory_mib=self.reservation.memory_mib,
                    gpu_memory_mib=self.reservation.gpu_memory_mib,
                ),
            )
            _object.__setattr__(self, "envelope_digest", _digest_of(self))

        @property
        def duration_ns(self) -> int:
            """Nanoseconds between issue and deadline, as accepted."""
            return self.deadline_ns - self.issued_ns

    return ObservationEnvelope


ObservationEnvelope = _restore_identity(
    _build_envelope_class(), "ObservationEnvelope", __name__
)


def _closed_envelope_shape_check():
    """Build :func:`_envelope_shape_intact`, everything bound in cells."""
    _envelope_type = ObservationEnvelope
    _evidence_type = EvidenceItem
    _reservation_type = ResourceReservation
    _digest_ok = is_sha256_digest
    _type = type
    _str = str
    _int = int
    _bytes = bytes
    _tuple = tuple
    _getattr = getattr

    def _envelope_shape_intact(envelope: Any) -> bool:
        """True only if every field still holds its exact accepted type.

        Run **before** the digest tree is walked, and that ordering is the whole
        point. An earlier revision compared ``rederived != envelope.envelope_digest``
        directly, so replacing ``envelope_digest`` with an object carrying a
        ``__ne__`` ran that hook; and it iterated ``envelope.evidence`` before
        knowing it was a tuple, so an object carrying an ``__iter__`` ran that
        one. Both were reachable with a single ``object.__setattr__``.

        Nothing here iterates, compares, hashes, represents or truth-tests a
        foreign value. Every step is a ``type(x) is T`` identity check, and the
        only containers walked are ones already proved to be exact tuples -
        whose iteration invokes no user code.
        """
        if _type(envelope) is not _envelope_type:
            return False
        for name in (
            "task_id",
            "authorizing_principal",
            "worker",
            "dialect",
            "endpoint",
            "schema_digest",
            "envelope_digest",
        ):
            if _type(_getattr(envelope, name)) is not _str:
                return False
        if _type(envelope.schema_bytes) is not _bytes:
            return False
        for name in (
            "context_ceiling_tokens",
            "max_evidence_bytes",
            "max_result_bytes",
            "max_output_tokens",
            "issued_ns",
            "deadline_ns",
        ):
            if _type(_getattr(envelope, name)) is not _int:
                return False
        if _type(envelope.evidence) is not _tuple:
            return False
        for item in envelope.evidence:
            if _type(item) is not _evidence_type:
                return False
            if _type(item.evidence_id) is not _str:
                return False
            if _type(item.content) is not _bytes:
                return False
            if _type(item.digest) is not _str:
                return False
        if _type(envelope.required_keys) is not _tuple:
            return False
        for key in envelope.required_keys:
            if _type(key) is not _str:
                return False
        reservation = envelope.reservation
        if _type(reservation) is not _reservation_type:
            return False
        if _type(reservation.cpu_cores) is not _int:
            return False
        if _type(reservation.memory_mib) is not _int:
            return False
        if reservation.gpu_memory_mib is not None and (
            _type(reservation.gpu_memory_mib) is not _int
        ):
            return False
        if _type(reservation.digest) is not _str:
            return False
        # The recorded digest must be a well-formed digest before it is compared
        # to anything, so the comparison below is str-to-str and runs no hook.
        return _digest_ok(envelope.envelope_digest)

    return _envelope_shape_intact


_envelope_shape_intact = _restore_identity(
    _closed_envelope_shape_check(), "_envelope_shape_intact", __name__
)


def _closed_decision_check():
    """Build :func:`_decision_fields_intact`, everything bound in cells."""
    _decision_type = ReservationDecision
    _attestations = RESERVATION_ATTESTATIONS
    _digest_ok = is_sha256_digest
    _type = type
    _str = str
    _bool = bool

    def _decision_fields_intact(decision: Any) -> bool:
        """True only if every decision field still holds its accepted type.

        Freezing a dataclass does not stop ``object.__setattr__``. An earlier
        revision read ``decision.satisfied`` in a boolean context and
        ``decision.reservation_digest`` in a comparison without re-checking
        either, so a tampered decision could run a ``__bool__`` hook and walk
        an unsatisfied reservation straight through the gate to the exchange.
        """
        if _type(decision) is not _decision_type:
            return False
        if not _digest_ok(decision.reservation_digest):
            return False
        if _type(decision.satisfied) is not _bool:
            return False
        return (
            _type(decision.attestation) is _str
            and decision.attestation in _attestations
        )

    return _decision_fields_intact


_decision_fields_intact = _restore_identity(
    _closed_decision_check(), "_decision_fields_intact", __name__
)


# -- the plan ----------------------------------------------------------------


def _build_plan_class():
    """Build :class:`ObservationPlan` with its vocabulary bound in a cell."""
    _refusals = PLAN_REFUSALS
    _envelope_type = ObservationEnvelope
    _type = type
    _str = str
    _bool = bool
    _ValueError = ValueError

    @dataclass(frozen=True)
    class ObservationPlan:
        """Outcome of planning one observation. Exactly two states.

        On success ``envelope`` is an :class:`ObservationEnvelope` and
        ``refusal`` is ``None``. On refusal it is the other way round, and the
        token is drawn from ``PLAN_REFUSALS`` - which is *composed from* OMI-V2's
        own request vocabulary, so a dialect or schema refusal travels through in
        OMI-V2's words rather than being translated into a second set of words
        meaning the same thing.

        No receipt is issued for a refused plan. A receipt is a record about an
        envelope, and a refused plan has none.
        """

        ok: bool
        envelope: Optional[ObservationEnvelope] = None
        refusal: Optional[PlanRefusal] = None

        def __post_init__(self) -> None:
            if _type(self.ok) is not _bool:
                raise _ValueError("ok must be exactly a bool")
            if self.refusal is not None and (
                _type(self.refusal) is not _str or self.refusal not in _refusals
            ):
                raise _ValueError("refusal must be a token from the closed vocabulary")
            if self.ok:
                if self.refusal is not None:
                    raise _ValueError("a successful plan cannot carry a refusal")
                if _type(self.envelope) is not _envelope_type:
                    raise _ValueError("a successful plan must carry an envelope")
            else:
                if self.refusal is None:
                    raise _ValueError("a refused plan must carry a refusal token")
                if self.envelope is not None:
                    raise _ValueError("a refused plan must not carry an envelope")

    return ObservationPlan


ObservationPlan = _restore_identity(_build_plan_class(), "ObservationPlan", __name__)


def _closed_planner():
    """Build :func:`plan_observation`, every dependency bound in a cell."""
    _Plan = ObservationPlan
    _Envelope = ObservationEnvelope
    _Refused = _EnvelopeRefused
    _evidence_ok = _evidence_state
    _reservation_ok = _reservation_state
    _safe_token = is_safe_token
    _uuid4_ok = is_canonical_uuid4
    _endpoint_ok = validate_loopback_endpoint
    _canonical = _canonical_schema
    _reservation_digest_of = _reservation_digest
    _clock_read = _read_clock
    _hashlib = hashlib
    _max_items = MAX_EVIDENCE_ITEMS
    _max_keys = MAX_REQUIRED_KEYS
    _max_item_bytes = MAX_EVIDENCE_ITEM_BYTES
    _max_total_bytes = MAX_EVIDENCE_TOTAL_BYTES
    _max_result = MAX_RESULT_BYTES
    _max_context = MAX_CONTEXT_CEILING_TOKENS
    _max_output = _MAX_OUTPUT_TOKENS
    _max_duration = _MAX_DURATION_NS
    _max_clock = MAX_CLOCK_NS
    _max_cpu = _MAX_CPU_CORES
    _max_memory = _MAX_MEMORY_MIB
    _max_gpu = _MAX_GPU_MEMORY_MIB
    _type = type
    _str = str
    _int = int
    _bytes = bytes
    _list = list
    _tuple = tuple
    _set = set
    _len = len
    _UnicodeDecodeError = UnicodeDecodeError

    #: Neutral clock codes mapped into this layer's closed vocabulary.
    _CLOCK_TOKENS = {
        "not-callable": "clock-not-callable",
        "raised": "clock-raised",
        "not-int": "clock-reading-not-exact-int",
        "negative": "clock-reading-negative",
        "too-large": "clock-reading-too-large",
    }

    def _bounded_int(value: Any, ceiling: int) -> Optional[EnvelopeRefusal]:
        """Exact type first, range second. Never a comparison on a foreign type.

        ``type(x) is int`` is False for ``True``, for every ``int`` subclass, and
        for every foreign object with ``__index__`` or ``__lt__`` - so no
        supplied hook runs, and the range comparison below only ever runs on a
        genuine built-in integer.
        """
        if _type(value) is not _int:
            return "limit-not-exact-int"
        if value < 1 or value > ceiling:
            return "limit-out-of-range"
        return None

    def plan_observation(
        *,
        task_id: Any,
        authorizing_principal: Any,
        worker: Any,
        evidence: Any,
        dialect: Any,
        schema: Any,
        endpoint: Any,
        reservation: Any,
        clock: Any,
        context_ceiling_tokens: Any = 8192,
        max_evidence_bytes: Any = 65536,
        max_result_bytes: Any = 8192,
        max_output_tokens: Any = 1024,
        duration_ns: Any = 30000000000,
        required_keys: Any = (),
    ) -> ObservationPlan:
        """Validate an observation and produce its immutable envelope.

        **Total: returns a plan for every input and never raises**, including
        for a ``clock`` that raises. Keyword-only, because an envelope has
        fifteen inputs and a positional mistake among fifteen is a silent one.

        The order is fixed and the first refusal wins:

        1. identity and provenance;
        2. declared limits and duration - exact ``int`` first, range second;
        3. the reservation: exact carrier type, then **every field revalidated**
           and its digest **recomputed**;
        4. the declared endpoint;
        5. evidence, in one controlled traversal that revalidates every
           identifier, byte payload, size and stored digest, **recomputes each
           digest from the bytes actually present**, and requires exact
           equality;
        6. required keys;
        7. the dialect and the schema, decided **entirely** by OMI-V2;
        8. the clock, read exactly once, last.

        Steps 3 and 5 are the answer to Jack's first finding. An exact
        ``EvidenceItem`` or ``ResourceReservation`` is *not* trusted because its
        outer type is exact: ``object.__setattr__`` can alter either after
        construction, and the previous revision adopted the result - including an
        equal-length byte substitution behind a stale digest, and a
        ``cpu_cores`` of a billion behind a digest describing two. Nothing in
        this traversal invokes a supplied hook: every value is checked by
        ``type(x) is T`` identity before it is read, and no rejected value's
        text, position or type name reaches the returned token.

        On ``schema``: the accepted envelope carries the canonical rendering of
        the snapshot OMI-V2 detached, never the caller's document. Mutating the
        dict that was passed in afterwards changes nothing here.

        On ``clock``: OMI-V3A reads no clock ambiently. ``clock`` is called once,
        with no arguments, and must return an exact ``int`` of nanoseconds in
        ``[0, MAX_CLOCK_NS]``. A clock that raises produces
        ``clock-raised`` - a fixed token carrying nothing about the exception.

        There is no ``tools`` parameter, and there never will be one at this
        layer: OMI-V3A is observation-only, and it calls OMI-V2 with
        ``has_tools=False`` from a call site no caller can reach.
        """
        if not _uuid4_ok(task_id):
            return _Plan(ok=False, refusal="task-id-not-canonical-uuid4")
        if not _safe_token(authorizing_principal):
            return _Plan(ok=False, refusal="principal-not-safe-token")
        if not _safe_token(worker):
            return _Plan(ok=False, refusal="worker-not-safe-token")

        for value, ceiling in (
            (context_ceiling_tokens, _max_context),
            (max_evidence_bytes, _max_total_bytes),
            (max_result_bytes, _max_result),
            (max_output_tokens, _max_output),
        ):
            refusal = _bounded_int(value, ceiling)
            if refusal is not None:
                return _Plan(ok=False, refusal=refusal)
        if _type(duration_ns) is not _int:
            return _Plan(ok=False, refusal="duration-not-exact-int")
        if duration_ns < 1 or duration_ns > _max_duration:
            return _Plan(ok=False, refusal="duration-out-of-range")

        # -- the reservation, through the one shared checker -------------------
        reservation_refusal = _reservation_ok(reservation)
        if reservation_refusal is not None:
            return _Plan(ok=False, refusal=reservation_refusal)

        endpoint_refusal = _endpoint_ok(endpoint)
        if endpoint_refusal is not None:
            return _Plan(ok=False, refusal=endpoint_refusal)

        # Exact container types only, then ONE traversal into a tuple this
        # function owns. A sequence subclass could return different elements on a
        # second iteration, so there is no second iteration of the caller's
        # object anywhere below.
        if _type(evidence) is not _tuple and _type(evidence) is not _list:
            return _Plan(ok=False, refusal="evidence-not-exact-sequence")
        items = _tuple(evidence)
        if not items:
            return _Plan(ok=False, refusal="evidence-empty")
        if _len(items) > _max_items:
            return _Plan(ok=False, refusal="evidence-too-many-items")
        # One traversal, through the same checker the envelope carrier and the
        # executor use - so strict UTF-8, the recomputed digests, distinctness
        # and every bound mean exactly one thing across all three.
        evidence_refusal, _total = _evidence_ok(items, max_evidence_bytes)
        if evidence_refusal is not None:
            return _Plan(ok=False, refusal=evidence_refusal)

        if _type(required_keys) is not _tuple and _type(required_keys) is not _list:
            return _Plan(ok=False, refusal="required-keys-not-exact-sequence")
        keys = _tuple(required_keys)
        if _len(keys) > _max_keys:
            return _Plan(ok=False, refusal="required-keys-too-many")
        for key in keys:
            if not _safe_token(key):
                return _Plan(ok=False, refusal="required-key-not-safe-token")

        # The dialect and the schema are OMI-V2's decision, start to finish.
        schema_refusal, schema_bytes = _canonical(dialect, schema)
        if schema_refusal is not None or schema_bytes is None:
            return _Plan(ok=False, refusal=schema_refusal)

        code, issued_ns = _clock_read(clock)
        if code is not None:
            return _Plan(ok=False, refusal=_CLOCK_TOKENS[code])
        if issued_ns + duration_ns > _max_clock:
            return _Plan(ok=False, refusal="deadline-beyond-clock-ceiling")

        # The carrier is the authority, so its refusal is translated rather
        # than pre-empted. This is what keeps the planner total while leaving
        # exactly one definition of an acceptable envelope.
        try:
            envelope = _Envelope(
                task_id=task_id,
                authorizing_principal=authorizing_principal,
                worker=worker,
                evidence=items,
                dialect=dialect,
                schema_bytes=schema_bytes,
                schema_digest=_hashlib.sha256(schema_bytes).hexdigest(),
                required_keys=keys,
                endpoint=endpoint,
                reservation=reservation,
                context_ceiling_tokens=context_ceiling_tokens,
                max_evidence_bytes=max_evidence_bytes,
                max_result_bytes=max_result_bytes,
                max_output_tokens=max_output_tokens,
                issued_ns=issued_ns,
                deadline_ns=issued_ns + duration_ns,
            )
        except _Refused as refused:
            return _Plan(ok=False, refusal=refused.token)
        return _Plan(ok=True, envelope=envelope)

    return plan_observation


plan_observation = _restore_identity(_closed_planner(), "plan_observation", __name__)


# -- the result --------------------------------------------------------------


def _build_result_class():
    """Build :class:`ObservationResult` with its authorities in cells."""
    _receipt_type = ObservationReceipt
    _exchange_type = StructuredExchange
    _undescribable = UNDESCRIBABLE_REFUSALS
    _type = type
    _bool = bool
    _str = str
    _ValueError = ValueError

    @dataclass(frozen=True)
    class ObservationResult:
        """What one execution produced: a receipt, and possibly a value.

        ``receipt`` is present for every execution **except** the three in which
        no envelope could be trusted to be described: the object handed in was
        not exactly an envelope, one of its fields no longer held its accepted
        type, or its digest did not re-derive. A receipt is a record about an
        envelope, so an envelope whose integrity failed gets no record rather
        than a record that might be wrong about it.

        ``exchange`` is OMI-V2's own result, retained only when the exchange ran
        *and* the deadline held. A void observation discards it: the deadline
        decided the outcome, and keeping a value that arrived too late is how a
        void result turns into a used one.

        **Pickling.** A successful result cannot be pickled, for exactly the
        reason a successful ``StructuredExchange`` cannot: it holds one, and that
        carrier's ``value`` is a ``MappingProxyType``. Every other state -
        refused, void, unusable - carries no proxy and pickles normally, as does
        the ``ObservationReceipt`` on its own, which is the artifact meant to be
        stored. A caller who must serialise a successful value copies it out:
        ``dict(result.exchange.value)`` is an ordinary picklable dict.
        """

        ok: bool
        receipt: Optional[ObservationReceipt] = None
        refusal: Optional[ExecutionRefusal] = None
        exchange: Optional[StructuredExchange] = None

        def __post_init__(self) -> None:
            if _type(self.ok) is not _bool:
                raise _ValueError("ok must be exactly a bool")
            if self.receipt is not None and _type(self.receipt) is not _receipt_type:
                raise _ValueError("receipt must be exactly an ObservationReceipt")
            if self.exchange is not None and _type(self.exchange) is not _exchange_type:
                raise _ValueError("exchange must be exactly a StructuredExchange")
            if self.receipt is None:
                if (
                    _type(self.refusal) is not _str
                    or self.refusal not in _undescribable
                ):
                    raise _ValueError(
                        "only an untrusted envelope produces a result with no receipt"
                    )
                if self.ok or self.exchange is not None:
                    raise _ValueError(
                        "a result with no receipt carries neither success nor a value"
                    )
                return
            if self.refusal != self.receipt.refusal:
                raise _ValueError("the result and its receipt must agree on the refusal")
            outcome = self.receipt.outcome
            if self.ok != (outcome == "observed"):
                raise _ValueError("ok and the receipt outcome must agree")
            if outcome in ("observed", "unusable"):
                if self.exchange is None:
                    raise _ValueError(
                        "an observed or unusable outcome retains its exchange"
                    )
                if self.exchange.ok != (outcome == "observed"):
                    raise _ValueError("the exchange and the outcome must agree")
            elif self.exchange is not None:
                raise _ValueError("a void or refused outcome retains no exchange")

    return ObservationResult


ObservationResult = _restore_identity(
    _build_result_class(), "ObservationResult", __name__
)


# -- the executor ------------------------------------------------------------


def _closed_executor():
    """Build :func:`execute_observation`, every dependency bound in a cell."""
    _Envelope = ObservationEnvelope
    _Decision = ReservationDecision
    _semantics = _envelope_semantics
    _exchange_intact = _exchange_fields_intact
    _Receipt = ObservationReceipt
    _Result = ObservationResult
    _exchange_type = StructuredExchange
    _digest_of = _envelope_digest
    _shape_intact = _envelope_shape_intact
    _decision_intact = _decision_fields_intact
    _reservation_digest_of = _reservation_digest
    _clock_read = _read_clock
    _json = json
    _type = type
    _len = len
    _sum = sum
    _dict = dict
    _tuple = tuple
    _callable = callable
    _RuntimeError = RuntimeError
    _Exception = Exception

    #: Neutral clock codes mapped into the execution vocabulary. ``negative``
    #: and ``too-large`` share one token because both say the same operative
    #: thing about a reading: it is outside the range a monotonic nanosecond
    #: clock can occupy.
    _CLOCK_TOKENS = {
        "not-callable": "clock-not-callable",
        "raised": "clock-raised",
        "not-int": "clock-reading-not-exact-int",
        "negative": "clock-reading-out-of-range",
        "too-large": "clock-reading-out-of-range",
    }

    def _receipt(
        envelope,
        *,
        outcome,
        deadline_result,
        reservation_result,
        request_outcome,
        response_outcome,
        invocations,
        elapsed_ns,
        result_bytes,
        attestation=None,
        dialect=None,
        refusal=None,
        request_refusal=None,
        response_failure=None,
        missing_key_indices=(),
    ):
        """Assemble the payload-free receipt from envelope metadata only."""
        return _Receipt(
            task_id=envelope.task_id,
            outcome=outcome,
            envelope_digest=envelope.envelope_digest,
            schema_digest=envelope.schema_digest,
            authorizing_principal=envelope.authorizing_principal,
            worker=envelope.worker,
            evidence_ids=_tuple(item.evidence_id for item in envelope.evidence),
            evidence_digests=_tuple(item.digest for item in envelope.evidence),
            evidence_bytes=_sum(_len(item.content) for item in envelope.evidence),
            deadline_result=deadline_result,
            reservation_result=reservation_result,
            reservation_attestation=attestation,
            request_outcome=request_outcome,
            response_outcome=response_outcome,
            exchange_invocations=invocations,
            elapsed_ns=elapsed_ns,
            result_bytes=result_bytes,
            context_ceiling_tokens=envelope.context_ceiling_tokens,
            required_key_count=_len(envelope.required_keys),
            dialect=dialect,
            refusal=refusal,
            request_refusal=request_refusal,
            response_failure=response_failure,
            missing_key_indices=missing_key_indices,
        )

    def _refuse(
        envelope,
        token,
        *,
        deadline_result,
        reservation_result,
        invocations,
        elapsed_ns=0,
        attestation=None,
    ):
        """One refusal, assembled in one place, in one coherent combination.

        Every refusal branch routes through here rather than spelling out a
        receipt of its own. Nineteen hand-written receipts are nineteen chances
        to record a combination that cannot have happened, and the receipt's own
        coherence check would then be discovering this module's bugs at runtime
        rather than never seeing one.
        """
        return _Result(
            ok=False,
            refusal=token,
            receipt=_receipt(
                envelope,
                outcome="refused",
                deadline_result=deadline_result,
                reservation_result=reservation_result,
                request_outcome="attempted" if invocations else "not-attempted",
                response_outcome="none",
                invocations=invocations,
                elapsed_ns=elapsed_ns,
                result_bytes=0,
                attestation=attestation,
                refusal=token,
            ),
        )

    def execute_observation(
        envelope: Any,
        *,
        exchange: Any,
        clock: Any,
        reservation_decision: Any,
    ) -> ObservationResult:
        """Run one observation, once, and return a result carrying a receipt.

        **Total for every reachable input except an exception raised by the
        injected ``exchange``**, which propagates. That exception is the one and
        only thing this function lets past, and it is deliberate:

        - it matches OMI-V2, where ``request_structured_json`` documents that
          transport errors raised by the underlying SDK propagate; and
        - OMI-V1's ``HermeticViolation`` **must** stay loud. Swallowing an
          exchange exception into a receipt would turn a hermetic breach - a
          double that reached the network - into a tidy record of a failed
          observation, which is precisely the failure mode the guard exists to
          prevent.

        A ``clock`` that raises does **not** propagate; it produces the fixed
        token ``clock-raised``, carrying nothing about the exception. The
        narrowing that implies is stated in :func:`_read_clock`.

        The order is fixed:

        1. the envelope's exact type, then **every field's exact type**, then
           its re-derived digest. All three produce a result with **no
           receipt**: nothing else here may describe an envelope it could not
           first trust. The field check comes before the digest walk so that no
           foreign ``__iter__``, ``__eq__``, ``__hash__`` or ``__len__`` is ever
           reached.
        2. ``exchange`` callability.
        3. the first clock reading: callable, non-raising, exact ``int``, in
           range, and not earlier than ``issued_ns``.
        4. the deadline. Already passed → **void** before anything runs, the
           exchange never invoked, the reservation recorded ``not-evaluated``.
        5. the reservation decision: exact type, **every field revalidated**,
           bound by digest to the reservation **as re-derived from its current
           fields**, and reporting satisfied.
        6. the exchange, invoked **at most once** through a latch.
        7. the second clock reading, then the deadline again. A deadline crossed
           while the exchange ran voids the observation *even when the exchange
           succeeded*.
        8. the exchange result's exact type, then OMI-V2's own outcome.
        9. the result size, measured on the canonical rendering of what OMI-V2
           accepted, against the envelope's declared ``max_result_bytes``.

        On step 9's honesty: this bounds the structured object OMI-V2 handed
        back, and OMI-V2's own ``max_chars`` bounds the payload string before it
        parses. Neither bounds how many bytes a transport read before either of
        them saw anything, and OMI-V3A has no transport to ask.
        """
        # Shape before content, and content before comparison. Nothing below
        # this block touches a value whose type has not been proved.
        if not _shape_intact(envelope):
            return _Result(
                ok=False,
                refusal=(
                    "envelope-not-exact-type"
                    if _type(envelope) is not _Envelope
                    else "envelope-field-not-exact-type"
                ),
            )
        # Semantics BEFORE the digest, and in addition to it. The digest is
        # unkeyed - a pure function of these fields, computed by a function this
        # package exports - so an envelope agreeing with its own digest has
        # proved only that nobody was careless, never that it is valid. Jack's
        # second round resealed envelopes carrying an unsupported dialect, a DNS
        # endpoint, an over-limit reservation and non-UTF-8 evidence, and the
        # previous revision ran all of them.
        if _semantics(envelope) is not None:
            return _Result(ok=False, refusal="envelope-semantics-invalid")
        if _digest_of(envelope) != envelope.envelope_digest:
            return _Result(ok=False, refusal="envelope-digest-mismatch")
        # The reservation's own digest must describe its own fields before it
        # can bind a decision. The envelope digest already covers both, so this
        # is unreachable for an envelope that got here - it is kept because the
        # value it produces is what the decision is bound to, and deriving that
        # value is not the same as trusting the stored one.
        recomputed_reservation = _reservation_digest_of(
            envelope.reservation.cpu_cores,
            envelope.reservation.memory_mib,
            envelope.reservation.gpu_memory_mib,
        )
        if recomputed_reservation != envelope.reservation.digest:
            return _Result(ok=False, refusal="envelope-digest-mismatch")

        if not _callable(exchange):
            return _refuse(
                envelope,
                "exchange-not-callable",
                deadline_result="not-evaluated",
                reservation_result="not-evaluated",
                invocations=0,
            )

        code, before = _clock_read(clock)
        if code is not None:
            return _refuse(
                envelope,
                _CLOCK_TOKENS[code],
                deadline_result="not-evaluated",
                reservation_result="not-evaluated",
                invocations=0,
            )
        if before < envelope.issued_ns:
            return _refuse(
                envelope,
                "clock-not-monotonic",
                deadline_result="not-evaluated",
                reservation_result="not-evaluated",
                invocations=0,
            )

        if before >= envelope.deadline_ns:
            # Void, not refused: the deadline decided this, and OMI-V3A does not
            # retry it. The reservation is recorded as never evaluated, because
            # it never was.
            return _Result(
                ok=False,
                receipt=_receipt(
                    envelope,
                    outcome="void",
                    deadline_result="exceeded-before-request",
                    reservation_result="not-evaluated",
                    request_outcome="not-attempted",
                    response_outcome="none",
                    invocations=0,
                    elapsed_ns=0,
                    result_bytes=0,
                ),
            )

        if _type(reservation_decision) is not _Decision:
            return _refuse(
                envelope,
                "reservation-decision-not-exact-type",
                deadline_result="within-deadline",
                reservation_result="not-evaluated",
                invocations=0,
            )
        if not _decision_intact(reservation_decision):
            # A decision whose fields were replaced after construction is not a
            # decision. Checked before `satisfied` is read in a boolean context,
            # so a supplied `__bool__` never runs.
            return _refuse(
                envelope,
                "reservation-decision-field-invalid",
                deadline_result="within-deadline",
                reservation_result="not-evaluated",
                invocations=0,
            )
        attestation = reservation_decision.attestation
        if reservation_decision.reservation_digest != recomputed_reservation:
            # A decision about some other reservation is not a decision about
            # this one, however satisfied it says it is. Bound to the RECOMPUTED
            # digest, never to the one the reservation happens to be storing.
            return _refuse(
                envelope,
                "reservation-decision-mismatch",
                deadline_result="within-deadline",
                reservation_result="not-evaluated",
                invocations=0,
            )
        if not reservation_decision.satisfied:
            return _refuse(
                envelope,
                "reservation-not-satisfied",
                deadline_result="within-deadline",
                reservation_result="not-satisfied",
                invocations=0,
                attestation=attestation,
            )

        # The latch. There is one call site and it can fire once. An edit that
        # later added a retry would raise here rather than retry, which is the
        # difference between a documented property and an enforced one.
        latch = []

        def _invoke_once(target):
            if latch:
                raise _RuntimeError("omi-v3a invokes its exchange at most once")
            latch.append(1)
            return exchange(target)

        completed = _invoke_once(envelope)

        # The clock is read before anything is asked of `completed`, so a
        # deadline crossed while the exchange ran is discovered even when what
        # came back is not something this module will look at.
        code, after = _clock_read(clock)
        if code is not None:
            return _refuse(
                envelope,
                _CLOCK_TOKENS[code],
                deadline_result="not-evaluated",
                reservation_result="satisfied",
                invocations=1,
                attestation=attestation,
            )
        if after < before:
            return _refuse(
                envelope,
                "clock-not-monotonic",
                deadline_result="not-evaluated",
                reservation_result="satisfied",
                invocations=1,
                attestation=attestation,
            )
        # Both readings are exact ints in [0, MAX_CLOCK_NS] and after >= before,
        # so the difference is an exact int in the same range - bounded before it
        # can reach a receipt or a serialiser.
        elapsed = after - before

        if after >= envelope.deadline_ns:
            # Void even if the exchange succeeded. A late answer is not an
            # answer, and keeping the value would turn a void observation into a
            # used one.
            return _Result(
                ok=False,
                receipt=_receipt(
                    envelope,
                    outcome="void",
                    deadline_result="exceeded-during-request",
                    reservation_result="satisfied",
                    attestation=attestation,
                    request_outcome="attempted",
                    response_outcome="none",
                    invocations=1,
                    elapsed_ns=elapsed,
                    result_bytes=0,
                ),
            )

        # Exact type, not duck typing: a foreign object reaching the branches
        # below could otherwise supply its own `ok` and be believed.
        if _type(completed) is not _exchange_type:
            return _refuse(
                envelope,
                "exchange-result-not-exact-type",
                deadline_result="within-deadline",
                reservation_result="satisfied",
                invocations=1,
                elapsed_ns=elapsed,
                attestation=attestation,
            )
        # ...and every field of it, before any of them is read. OMI-V2's carrier
        # is frozen, not sealed; a tampered `ok` ran a `__bool__` hook here, and
        # a tampered `dialect` reached receipt construction and raised.
        if not _exchange_intact(completed):
            return _refuse(
                envelope,
                "exchange-result-field-invalid",
                deadline_result="within-deadline",
                reservation_result="satisfied",
                invocations=1,
                elapsed_ns=elapsed,
                attestation=attestation,
            )

        if not completed.ok:
            refused = completed.request_refusal is not None
            return _Result(
                ok=False,
                exchange=completed,
                receipt=_receipt(
                    envelope,
                    outcome="unusable",
                    deadline_result="within-deadline",
                    reservation_result="satisfied",
                    attestation=attestation,
                    request_outcome="attempted",
                    response_outcome=(
                        "request-refused" if refused else "response-unusable"
                    ),
                    invocations=1,
                    elapsed_ns=elapsed,
                    result_bytes=0,
                    dialect=completed.dialect,
                    request_refusal=completed.request_refusal,
                    response_failure=completed.response_failure,
                    missing_key_indices=completed.missing_key_indices,
                ),
            )

        # Size the accepted object, not the wire. `completed.value` is OMI-V2's
        # read-only proxy over a dict `json.loads` produced under a hook that
        # itself returns an exact dict, so `_dict()` of it runs no foreign hook.
        try:
            rendered = _json.dumps(
                _dict(completed.value),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
        except _Exception:
            # Two cases land here. For a value OMI-V2's validator produced this
            # is unreachable - it is always exact built-in JSON types. For a
            # `value` a caller substituted with a proxy over a foreign mapping,
            # the walk above may run that mapping's hooks and they may raise
            # anything; the catch is broad so the outcome is still one fixed
            # refusal rather than an exception escaping a total function.
            # Nothing from the walk reaches the receipt, which takes a byte
            # count and nothing else.
            return _refuse(
                envelope,
                "result-not-serializable",
                deadline_result="within-deadline",
                reservation_result="satisfied",
                invocations=1,
                elapsed_ns=elapsed,
                attestation=attestation,
            )
        size = _len(rendered)
        if size > envelope.max_result_bytes:
            return _refuse(
                envelope,
                "result-too-large",
                deadline_result="within-deadline",
                reservation_result="satisfied",
                invocations=1,
                elapsed_ns=elapsed,
                attestation=attestation,
            )

        return _Result(
            ok=True,
            exchange=completed,
            receipt=_receipt(
                envelope,
                outcome="observed",
                deadline_result="within-deadline",
                reservation_result="satisfied",
                attestation=attestation,
                request_outcome="attempted",
                response_outcome="ok",
                invocations=1,
                elapsed_ns=elapsed,
                result_bytes=size,
                dialect=completed.dialect,
            ),
        )

    return execute_observation


execute_observation = _restore_identity(
    _closed_executor(), "execute_observation", __name__
)


# -- the canonical exchange adapter ------------------------------------------


def _closed_adapter_factory():
    """Build :func:`structured_exchange_adapter`, dependencies in cells."""
    _Envelope = ObservationEnvelope
    _request = request_structured_json
    _request_type = StructuredOutputRequest
    _Message = Message
    _system = OBSERVER_SYSTEM_PROMPT
    _json = json
    _type = type
    _list = list
    _ValueError = ValueError

    def structured_exchange_adapter(
        backend: Any,
    ) -> Callable[[ObservationEnvelope], StructuredExchange]:
        """Bind ``backend`` into the one exchange callable OMI-V3A supports.

        The returned callable takes an :class:`ObservationEnvelope` and calls
        OMI-V2's ``request_structured_json`` exactly once. It is the reuse
        point: OMI-V3A writes no request builder, no dialect dispatch, and no
        response validator of its own.

        What it sends, and nothing else:

        - one ``user`` message per evidence item, in the envelope's order,
          carrying that item's bytes decoded as strict UTF-8;
        - the fixed :data:`OBSERVER_SYSTEM_PROMPT` as the system text. No caller
          string reaches it;
        - an **empty tool list**, built here as a fresh literal. There is no
          parameter, field or keyword by which a caller could add a tool;
        - the schema rebuilt from ``envelope.schema_bytes``, which this package
          produced from OMI-V2's own detached snapshot and which the envelope
          carrier proved is the canonical rendering of a schema OMI-V2 accepts;
        - ``max_chars`` from the envelope's declared result bound, and
          ``max_tokens`` from its declared output bound. ``temperature`` is fixed
          at ``0.0``.

        ``backend`` is accepted as ``Any`` and checked structurally by OMI-V2,
        which refuses a backend without ``complete_structured`` as
        ``backend-not-structured-capable`` rather than raising.

        **This adapter is where a future live backend would connect, and it is
        the boundary this package cannot see past.** The envelope's endpoint was
        validated as declared text; what ``backend`` actually contacts is a
        property of the operator-written factory that built it. OMI-V3A ships no
        factory and registers no backend.
        """

        def exchange(envelope: Any) -> StructuredExchange:
            if _type(envelope) is not _Envelope:
                raise _ValueError("the adapter accepts exactly an ObservationEnvelope")
            messages = _list(
                _Message(role="user", content=item.content.decode("utf-8"))
                for item in envelope.evidence
            )
            return _request(
                backend,
                messages,
                [],
                structured=_request_type(
                    schema=_json.loads(envelope.schema_bytes.decode("ascii"))
                ),
                required_keys=envelope.required_keys,
                max_chars=envelope.max_result_bytes,
                system=_system,
                max_tokens=envelope.max_output_tokens,
                temperature=0.0,
            )

        return exchange

    return structured_exchange_adapter


structured_exchange_adapter = _restore_identity(
    _closed_adapter_factory(), "structured_exchange_adapter", __name__
)


__all__ = [
    "OBSERVATION_LIMITS",
    "OBSERVER_SYSTEM_PROMPT",
    "EvidenceItem",
    "ObservationEnvelope",
    "ObservationPlan",
    "ObservationResult",
    "ReservationDecision",
    "ResourceReservation",
    "execute_observation",
    "new_task_id",
    "plan_observation",
    "structured_exchange_adapter",
    "validate_loopback_endpoint",
]
