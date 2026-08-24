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

## What OMI-V3A adds, and what it refuses to add

It adds the five envelope properties § 7 asked for - immutable task identity,
input hashes, bounded context, bounded result, a deadline, and provenance -
plus the two that § 4 and § 6 make prerequisites for any later live work: a
declared **loopback** endpoint, and an explicit **resource reservation** that
must be attested before anything runs.

It adds no second validator. The schema is validated and detached by OMI-V2's
own ``plan_structured_request``; the response is validated by OMI-V2's own
``request_structured_json``; the dialect predicate, the two refusal
vocabularies and the response-failure vocabulary are imported, never restated.
``schema_conformance`` stays closed to ``"unverified"`` because nothing below
this layer established conformance and this layer adds nothing that could.

## Structural versus attested

Two different kinds of guarantee live here and they must not be read as one.

**Structural** - enforced by this code, and false only if the code is wrong:

  - the exchange callable is invoked **at most once**, latched, with no retry
    loop anywhere in OMI-V3A;
  - no tool is ever declared: the exchange is called with an empty tool list
    built at the call site, and there is no field, parameter or keyword by
    which a caller could add one;
  - an accepted envelope holds no caller-owned mutable object - evidence is
    exact ``bytes``, the schema is exact ``bytes``, everything else is a
    ``str``, an ``int``, a frozen carrier, or a tuple of those;
  - the envelope's digest is recomputed at execution time, so a mutation
    between planning and execution refuses rather than executes;
  - evidence, result, context, duration and endpoint length are all bounded by
    exact-``int`` limits checked before any comparison or representation;
  - the receipt has no field a payload could occupy.

**Attested** - recorded honestly, and true only if whoever attested was right:

  - the **resource reservation**. OMI-V3A refuses unless an injected
    :class:`ReservationDecision` reports it satisfied. It inspects no CPU, no
    memory, no GPU, no process, no service, and no concurrent workload - so
    what it verifies is a checker's or an operator's claim, not availability.
    Folding@home and BOINC remain senior per the inception note § 6, and
    nothing here can see them, let alone change them.
  - the **endpoint**. :func:`validate_loopback_endpoint` decides whether the
    *declared* request-time endpoint text is a numeric loopback HTTP ``/v1``
    endpoint. It resolves no name and opens no socket. An opaque backend
    factory handed to :func:`structured_exchange_adapter` could still be
    pointed somewhere else entirely; proving where a real adapter connects is
    live-adapter work under separate authority.
  - the **context ceiling**. It is carried and recorded. No tokenizer is run
    and no token count is verified.
  - the **clock**. The caller supplies the monotonic reading function; this
    module never reads a clock ambiently. Deadline arithmetic and ordering are
    checked against the readings it is handed, which is not a claim that those
    readings came from ``time.monotonic_ns``.

## What one invocation does not prove

``exchange_invocations <= 1`` is a fact about *this* module's call site. It is
not a claim that an opaque SDK or HTTP client performs exactly one network
attempt: transports retry internally, and disabling and then proving that is
live-adapter work under separate authority. OMI-V3A is inert, so the question
does not arise here - but it will, and it is written down now rather than
discovered later.

## Observation only

There is no tool capability, no proposal capability, no commit capability, no
mutation action, no controller role, and no backend registration anywhere in
this module. The role is the ``Observer`` row of the inception note § 7 table
and nothing wider: summarise bounded evidence it is handed; may not request
more scope, propose, or apply.
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
    plan_structured_request,
)
from scripts.open_model.observation_receipt import (
    MAX_EVIDENCE_ITEMS,
    MAX_REQUIRED_KEYS,
    PLAN_REFUSALS,
    EnvelopeRefusal,
    ExecutionRefusal,
    ObservationReceipt,
    PlanRefusal,
    RESERVATION_ATTESTATIONS,
    is_canonical_uuid4,
    is_sha256_digest,
)
from scripts.open_model.redaction import is_safe_token
from scripts.open_model.structured_exchange import (
    StructuredExchange,
    _restore_identity,
    request_structured_json,
)


# ``_restore_identity`` is imported from ``structured_exchange`` rather than
# copied a third time; see the same note in ``observation_receipt.py``. A
# control asserts this module's binding IS that module's object.


# -- bounds ------------------------------------------------------------------


_MAX_ENDPOINT_CHARS: Final[int] = 128
_MAX_EVIDENCE_ITEM_BYTES: Final[int] = 65536
_MAX_EVIDENCE_TOTAL_BYTES: Final[int] = 262144
_MAX_RESULT_BYTES: Final[int] = 65536
_MAX_CONTEXT_CEILING_TOKENS: Final[int] = 1048576
_MAX_OUTPUT_TOKENS: Final[int] = 8192
_MAX_DURATION_NS: Final[int] = 3600000000000
_MAX_CPU_CORES: Final[int] = 256
_MAX_MEMORY_MIB: Final[int] = 1048576
_MAX_GPU_MEMORY_MIB: Final[int] = 1048576

OBSERVATION_LIMITS: Final[Mapping[str, int]] = MappingProxyType(
    {
        "endpoint_chars": _MAX_ENDPOINT_CHARS,
        "evidence_items": MAX_EVIDENCE_ITEMS,
        "evidence_item_bytes": _MAX_EVIDENCE_ITEM_BYTES,
        "evidence_total_bytes": _MAX_EVIDENCE_TOTAL_BYTES,
        "result_bytes": _MAX_RESULT_BYTES,
        "context_ceiling_tokens": _MAX_CONTEXT_CEILING_TOKENS,
        "output_tokens": _MAX_OUTPUT_TOKENS,
        "duration_ns": _MAX_DURATION_NS,
        "required_keys": MAX_REQUIRED_KEYS,
        "cpu_cores": _MAX_CPU_CORES,
        "memory_mib": _MAX_MEMORY_MIB,
        "gpu_memory_mib": _MAX_GPU_MEMORY_MIB,
    }
)
"""Read-only inspection mirror of every ceiling this module enforces.

**Off the trust path.** Each bound is bound into a closure cell when the
carrier or the planner it belongs to is defined, so rebinding this name - or
mutating what it maps to, which a ``MappingProxyType`` refuses anyway - cannot
widen or narrow a single check. It can only make the mirror disagree with the
code, which a control asserts against.

This is the same discipline OMI-V2 applied to ``SUPPORTED_DIALECTS`` and
``STRUCTURED_WIRE_NAME``, and it is deliberately stricter than the boundary
OMI-V2 drew for ``_SCHEMA_MAX_*``: those stayed module-level and adjustable on
the argument that a size bound decides how much, never what type. Here the
size bounds are what keeps evidence, a result and a deadline bounded at all,
so they are closed too.
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
``PROBE_MESSAGES`` guarantees for the OMI-V1 evaluation harness. The text
states the ``Observer`` role from the inception note; it is not a security
control, and nothing downstream depends on a model honouring it.
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
        envelope* - not that it has never been produced anywhere else, and not
        that anyone outside this process agrees it names this task.
        """
        return _str(_uuid4())

    return new_task_id


new_task_id = _restore_identity(_closed_task_id_factory(), "new_task_id", __name__)


# -- evidence ----------------------------------------------------------------


def _build_evidence_item_class():
    """Build :class:`EvidenceItem` with its authorities in closure cells.

    ``hashlib`` is captured as the stdlib **module object**, matching the
    boundary OMI-V2 drew for ``json`` and ``math``: rebinding this module's
    ``hashlib`` name is closed; patching an attribute on the captured stdlib
    module remains the documented arbitrary-code-replacement boundary.
    """
    _safe_token = is_safe_token
    _max_bytes = _MAX_EVIDENCE_ITEM_BYTES
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
        could be trusted to be what it claimed. Exact ``bytes`` is immutable,
        which is what makes "the digest describes the content" a fact rather
        than a hope.

        ``digest`` is **not** an init field. It is computed here, from the
        object that was accepted, at the moment it was accepted - so a caller
        cannot supply one, and there is no window between the check and the
        hash in which anything could change. Any digest on any accepted item is
        therefore this package's own.

        ``evidence_id`` must be a safe token: bounded, ``[A-Za-z0-9]
        [A-Za-z0-9._-]*``, and unchanged by OMI-V1's secret matcher. It is
        copied into the receipt, so an identifier shaped like a credential is
        refused at the door rather than stored.

        Refusal is by ``ValueError`` rather than a token, matching
        ``EvaluationCase.case_id``: an unusable evidence item is an authoring
        mistake that should surface where it was written. Callers who want a
        token instead hand the item to :func:`plan_observation`, which is total
        over anything at all.
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


def _build_reservation_class():
    """Build :class:`ResourceReservation`, bounds and builtins in cells."""
    _max_cpu = _MAX_CPU_CORES
    _max_memory = _MAX_MEMORY_MIB
    _max_gpu = _MAX_GPU_MEMORY_MIB
    _hashlib = hashlib
    _json = json
    _type = type
    _int = int
    _object = object
    _ValueError = ValueError

    @dataclass(frozen=True)
    class ResourceReservation:
        """What an observation declares it needs, before anything runs.

        The inception note § 6 makes the rule that this carrier exists to
        serve: *the experiment declares its CPU, GPU, and memory reservations
        up front, and if they are not available it defers.* Declaring them is
        all this carrier does. Deciding whether they are available is somebody
        else's job, reported through :class:`ReservationDecision`, and OMI-V3A
        never looks for itself.

        ``gpu_memory_mib`` is optional because an observation may legitimately
        need none. ``None`` means *no GPU reservation is declared*, which is
        not the same as *zero GPU memory is required*; zero is refused, so the
        two cannot be confused.

        ``digest`` is computed here over a canonical rendering, and is what
        binds a decision to the reservation it was made about.
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
            rendered = _json.dumps(
                {
                    "cpu_cores": self.cpu_cores,
                    "gpu_memory_mib": self.gpu_memory_mib,
                    "memory_mib": self.memory_mib,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
            _object.__setattr__(
                self, "digest", _hashlib.sha256(rendered).hexdigest()
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
        reservation holds - and then record *that a party said so*, which is
        what :data:`~scripts.open_model.observation_receipt.ReservationResult`
        reports.

        ``reservation_digest`` binds this decision to one
        :class:`ResourceReservation`. Without it, a decision made about a small
        reservation could be presented against a large one, and the receipt
        would record a satisfied reservation that nobody had ever considered.

        ``satisfied`` must be exactly a ``bool``: a foreign object with a
        ``__bool__`` must not be able to walk itself through the gate.
        """

        reservation_digest: str
        satisfied: bool
        attestation: str

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

        Exactly four decimal octets, each 1-3 ASCII digits with no leading
        zero, each at most 255, and the first exactly ``127``. That single rule
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
        ``http://`` (so ``https``, ``HTTP``, and schemeless text all fail);
        user information; a query or fragment; any percent-encoding anywhere;
        a DNS name, including ``localhost`` and ``*.localhost``; ``0.0.0.0``;
        any non-loopback address; the long-form ``[0:0:0:0:0:0:0:1]`` and the
        mapped ``[::ffff:127.0.0.1]``; a missing port; a port with a leading
        zero, a sign, non-ASCII digits, or a value outside 1-65535; and any
        path other than exactly ``/v1``.

        Non-ASCII digits matter more than they look. ``int("١٢")``
        is ``12`` - Python's ``int`` accepts Unicode decimal digits and
        ``str.isdigit`` returns True for them - so a port written in Arabic-
        Indic digits would parse to a perfectly ordinary number. Every
        character is therefore checked against an explicit ASCII set before any
        conversion runs.

        **This validates declared text.** It is not a claim about where a
        request goes. Nothing is resolved and nothing is connected; an opaque
        backend factory could still target another host entirely, and proving
        otherwise is live-adapter work under separate authority.
        """
        if _type(value) is not _str:
            return "endpoint-not-exact-str"
        if _len(value) > _max_chars:
            return "endpoint-too-long"
        # Checked over the whole string, before it is split: a percent-escape
        # is how an authority hides a delimiter, so it is refused wherever it
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
            # Exactly the compressed literal. The long form and the mapped
            # form both denote the same address and are refused anyway: two
            # spellings of one endpoint is one spelling too many for an
            # envelope whose digest has to be comparable.
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


# -- the envelope ------------------------------------------------------------


def _closed_envelope_digest():
    """Build :func:`_envelope_digest`, its dependencies bound in cells.

    One function computes the digest, and both the constructor and the executor
    call it - so "the digest recorded at planning time" and "the digest
    recomputed at execution time" cannot be two different renderings that
    happen to agree today.
    """
    _hashlib = hashlib
    _json = json
    _list = list
    _len = len

    def _envelope_digest(envelope: Any) -> str:
        """Digest what the envelope *contains*, not what it says it contains.

        Every stored digest is written down **beside a digest recomputed here
        from the bytes themselves**, and every carrier that holds a digest has
        its own fields written down beside it. That redundancy is the whole
        point, and it closes a hole an earlier revision of this function had:
        it read ``item.digest`` and ``len(item.content)`` only, so replacing an
        evidence item's content with *different bytes of the same length* left
        the envelope digest completely unchanged - and the executor's
        re-derivation, which exists precisely to catch tampering, would have
        agreed that nothing had happened. The same held for ``schema_bytes``
        against a stored ``schema_digest``, and for a reservation's fields
        against its stored digest.

        Now a tamper on either side of any pair - the bytes or the digest that
        describes them - changes this document, so the re-derivation notices.

        Everything read here is immutable in a well-formed envelope, so two
        calls on an untampered envelope always agree.
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
    _evidence_type = EvidenceItem
    _reservation_type = ResourceReservation
    _safe_token = is_safe_token
    _uuid4_ok = is_canonical_uuid4
    _digest_ok = is_sha256_digest
    _endpoint_ok = validate_loopback_endpoint
    _digest_of = _envelope_digest
    _max_items = MAX_EVIDENCE_ITEMS
    _max_keys = MAX_REQUIRED_KEYS
    _max_item_bytes = _MAX_EVIDENCE_ITEM_BYTES
    _max_total_bytes = _MAX_EVIDENCE_TOTAL_BYTES
    _max_result = _MAX_RESULT_BYTES
    _max_context = _MAX_CONTEXT_CEILING_TOKENS
    _max_output = _MAX_OUTPUT_TOKENS
    _max_duration = _MAX_DURATION_NS
    _type = type
    _str = str
    _int = int
    _bytes = bytes
    _tuple = tuple
    _set = set
    _len = len
    _getattr = getattr
    _object = object
    _ValueError = ValueError

    @dataclass(frozen=True)
    class ObservationEnvelope:
        """One complete, immutable, self-describing observation plan.

        Normally produced by :func:`plan_observation`, which is total and
        returns a token for anything it will not accept. Constructing one
        directly is supported and re-runs every check, because a carrier that
        trusted its producer would only be as trustworthy as the least careful
        producer.

        **Nothing reachable from an accepted envelope is caller-owned and
        mutable.** ``evidence`` is a tuple of frozen items holding exact
        ``bytes``; ``schema_bytes`` is exact ``bytes``; ``required_keys`` is a
        tuple of ``str``; ``reservation`` is frozen and holds ints; everything
        else is a ``str`` or an ``int``. A caller who kept a reference to the
        schema dict, the evidence list, or the key tuple they passed to the
        planner cannot reach through it and change what this envelope means.

        ``schema_bytes`` is the **canonical rendering of the detached snapshot
        OMI-V2 built**, not the caller's document. ``plan_structured_request``
        validates and copies in one traversal, so the snapshot contains exactly
        the values it inspected; this envelope renders that snapshot with
        sorted keys and fixed separators and keeps the bytes. JSON object
        member order is not semantically significant, and a digest that two
        parties can compare is worth more than preserving authoring order.

        ``envelope_digest`` is not an init field: it is computed here, over the
        fields as accepted. The executor recomputes it before it does anything
        else, so a deliberate ``object.__setattr__`` on this frozen carrier
        between planning and execution is refused rather than acted on.
        """

        task_id: str
        authorizing_principal: str
        worker: str
        evidence: tuple[Any, ...]
        dialect: str
        schema_bytes: bytes
        schema_digest: str
        required_keys: tuple[str, ...]
        endpoint: str
        reservation: Any
        context_ceiling_tokens: int
        max_evidence_bytes: int
        max_result_bytes: int
        max_output_tokens: int
        issued_ns: int
        deadline_ns: int
        envelope_digest: str = field(init=False, default="")

        def __post_init__(self) -> None:
            if not _uuid4_ok(self.task_id):
                raise _ValueError("task_id must be a canonical lowercase UUIDv4")
            if not _safe_token(self.authorizing_principal):
                raise _ValueError("authorizing_principal must be a safe token")
            if not _safe_token(self.worker):
                raise _ValueError("worker must be a safe token")
            if _type(self.evidence) is not _tuple:
                raise _ValueError("evidence must be exactly a tuple")
            if not self.evidence or _len(self.evidence) > _max_items:
                raise _ValueError("evidence is empty or over the item bound")
            seen = _set()
            total = 0
            for item in self.evidence:
                if _type(item) is not _evidence_type:
                    raise _ValueError("every evidence entry must be an EvidenceItem")
                if item.evidence_id in seen:
                    raise _ValueError("evidence ids must be distinct")
                seen.add(item.evidence_id)
                total += _len(item.content)
            if total > _max_total_bytes:
                raise _ValueError("evidence exceeds the total byte bound")
            if _type(self.schema_bytes) is not _bytes:
                raise _ValueError("schema_bytes must be exactly built-in bytes")
            if not _digest_ok(self.schema_digest):
                raise _ValueError("schema_digest must be 64 lowercase hex characters")
            if _type(self.required_keys) is not _tuple:
                raise _ValueError("required_keys must be exactly a tuple")
            if _len(self.required_keys) > _max_keys:
                raise _ValueError("required_keys exceeds the bound")
            for key in self.required_keys:
                if not _safe_token(key):
                    raise _ValueError("every required key must be a safe token")
            if _endpoint_ok(self.endpoint) is not None:
                raise _ValueError(
                    "endpoint must be a declared numeric loopback http /v1 endpoint"
                )
            if _type(self.reservation) is not _reservation_type:
                raise _ValueError("reservation must be exactly a ResourceReservation")
            if _type(self.dialect) is not _str:
                raise _ValueError("dialect must be exactly a str")
            for name, ceiling in (
                ("context_ceiling_tokens", _max_context),
                ("max_evidence_bytes", _max_total_bytes),
                ("max_result_bytes", _max_result),
                ("max_output_tokens", _max_output),
            ):
                number = _getattr(self, name)
                if _type(number) is not _int:
                    raise _ValueError("every declared limit must be an exact int")
                if number < 1 or number > ceiling:
                    raise _ValueError("a declared limit is out of range")
            if total > self.max_evidence_bytes:
                raise _ValueError("evidence exceeds the declared evidence bound")
            for item in self.evidence:
                if _len(item.content) > _max_item_bytes:
                    raise _ValueError("an evidence item exceeds the per-item bound")
            if _type(self.issued_ns) is not _int or self.issued_ns < 0:
                raise _ValueError("issued_ns must be an exact non-negative int")
            if _type(self.deadline_ns) is not _int:
                raise _ValueError("deadline_ns must be an exact int")
            duration = self.deadline_ns - self.issued_ns
            if duration < 1 or duration > _max_duration:
                raise _ValueError("the derived duration is out of range")
            _object.__setattr__(self, "envelope_digest", _digest_of(self))

        @property
        def duration_ns(self) -> int:
            """Nanoseconds between issue and deadline, as accepted."""
            return self.deadline_ns - self.issued_ns

    return ObservationEnvelope


ObservationEnvelope = _restore_identity(
    _build_envelope_class(), "ObservationEnvelope", __name__
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
        token is drawn from :data:`~scripts.open_model.observation_receipt.PLAN_REFUSALS`
        - which is *composed from* OMI-V2's own request vocabulary, so a
        dialect or schema refusal travels through in OMI-V2's words rather
        than being translated into a second set of words meaning the same
        thing.

        No receipt is issued for a refused plan. A receipt is a record about an
        envelope, and a refused plan has none.
        """

        ok: bool
        envelope: Optional[Any] = None
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
    _evidence_type = EvidenceItem
    _reservation_type = ResourceReservation
    _safe_token = is_safe_token
    _uuid4_ok = is_canonical_uuid4
    _endpoint_ok = validate_loopback_endpoint
    _plan_request = plan_structured_request
    _request_type = StructuredOutputRequest
    _hashlib = hashlib
    _json = json
    _max_items = MAX_EVIDENCE_ITEMS
    _max_keys = MAX_REQUIRED_KEYS
    _max_item_bytes = _MAX_EVIDENCE_ITEM_BYTES
    _max_total_bytes = _MAX_EVIDENCE_TOTAL_BYTES
    _max_result = _MAX_RESULT_BYTES
    _max_context = _MAX_CONTEXT_CEILING_TOKENS
    _max_output = _MAX_OUTPUT_TOKENS
    _max_duration = _MAX_DURATION_NS
    _type = type
    _int = int
    _list = list
    _tuple = tuple
    _dict = dict
    _set = set
    _len = len
    _callable = callable
    _UnicodeDecodeError = UnicodeDecodeError

    def _bounded_int(value: Any, ceiling: int) -> Optional[EnvelopeRefusal]:
        """Exact type first, range second. Never a comparison on a foreign type.

        ``type(x) is int`` is False for ``True``, for every ``int`` subclass,
        and for every foreign object with ``__index__`` or ``__lt__`` - so no
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

        Total: returns a plan for every input and never raises. Keyword-only,
        because an envelope has fifteen inputs and a positional mistake among
        fifteen is a silent one.

        The order below is fixed and the first refusal wins, because later
        checks are not meaningful once an earlier one has failed:

        1. identity and provenance - ``task-id-not-canonical-uuid4``,
           ``principal-not-safe-token``, ``worker-not-safe-token``;
        2. declared limits and duration - exact ``int`` first, range second;
        3. the reservation carrier's exact type;
        4. the declared endpoint - see :func:`validate_loopback_endpoint`;
        5. evidence - shape, count, item type, distinct ids, per-item and total
           byte bounds against both the module ceiling and the caller's
           declared bound, and strict UTF-8 decodability;
        6. required keys - shape, count, and safe-token form;
        7. the dialect and the schema, decided **entirely** by OMI-V2's
           ``plan_structured_request``, whose refusal travels through
           unchanged;
        8. the clock, read exactly once, last, so ``issued_ns`` is taken as
           close to construction as the code allows.

        On ``schema``: the accepted envelope carries the canonical rendering of
        the snapshot OMI-V2 detached, never the caller's document. Mutating the
        dict that was passed in afterwards changes nothing here, because
        validation and copying were one traversal and this function never reads
        that dict again.

        On ``clock``: OMI-V3A reads no clock ambiently. ``clock`` is called
        once, with no arguments, and must return an exact non-negative ``int``
        of nanoseconds from a monotonic source. Passing ``time.monotonic_ns``
        is the intended production use. What this function verifies is the
        arithmetic and the type, not the provenance of the reading.

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

        if _type(reservation) is not _reservation_type:
            return _Plan(ok=False, refusal="reservation-not-exact-type")

        endpoint_refusal = _endpoint_ok(endpoint)
        if endpoint_refusal is not None:
            return _Plan(ok=False, refusal=endpoint_refusal)

        # Exact container types only, then ONE traversal into a tuple this
        # function owns. A sequence subclass could return different elements on
        # a second iteration, so there is no second iteration of the caller's
        # object anywhere below.
        if _type(evidence) is not _tuple and _type(evidence) is not _list:
            return _Plan(ok=False, refusal="evidence-not-exact-sequence")
        items = _tuple(evidence)
        if not items:
            return _Plan(ok=False, refusal="evidence-empty")
        if _len(items) > _max_items:
            return _Plan(ok=False, refusal="evidence-too-many-items")
        seen = _set()
        total = 0
        for item in items:
            if _type(item) is not _evidence_type:
                return _Plan(ok=False, refusal="evidence-item-not-exact-type")
            if item.evidence_id in seen:
                return _Plan(ok=False, refusal="evidence-id-duplicated")
            seen.add(item.evidence_id)
            size = _len(item.content)
            if size > _max_item_bytes or size > max_evidence_bytes:
                return _Plan(ok=False, refusal="evidence-item-too-large")
            total += size
            if total > _max_total_bytes or total > max_evidence_bytes:
                return _Plan(ok=False, refusal="evidence-total-too-large")
            # Decodability is settled here so a refusal is possible while one
            # still is. The bytes are immutable, so decoding them again at
            # exchange time cannot produce anything else; the decoded text is
            # deliberately not retained, since the envelope already holds the
            # only copy that matters.
            try:
                item.content.decode("utf-8")
            except _UnicodeDecodeError:
                return _Plan(ok=False, refusal="evidence-not-utf8")

        if _type(required_keys) is not _tuple and _type(required_keys) is not _list:
            return _Plan(ok=False, refusal="required-keys-not-exact-sequence")
        keys = _tuple(required_keys)
        if _len(keys) > _max_keys:
            return _Plan(ok=False, refusal="required-keys-too-many")
        for key in keys:
            if not _safe_token(key):
                return _Plan(ok=False, refusal="required-key-not-safe-token")

        # The dialect and the schema are OMI-V2's decision, start to finish.
        # `has_tools=False` is written here, at a call site no caller can
        # reach: OMI-V3A declares no tool, ever.
        request_plan = _plan_request(
            dialect, _request_type(schema=schema), has_tools=False
        )
        if not request_plan.ok:
            return _Plan(ok=False, refusal=request_plan.refusal)
        # The snapshot OMI-V2 built, reached without touching caller data.
        snapshot = request_plan.response_format["json_schema"]["schema"]
        if _type(snapshot) is not _dict:
            # Unreachable while OMI-V2's wire-shape guard holds; written as a
            # refusal rather than an assert so behaviour is identical under -O.
            return _Plan(ok=False, refusal="schema-not-exact-dict")
        schema_bytes = _json.dumps(
            snapshot,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")

        if not _callable(clock):
            return _Plan(ok=False, refusal="clock-not-callable")
        issued_ns = clock()
        if _type(issued_ns) is not _int:
            return _Plan(ok=False, refusal="clock-reading-not-exact-int")
        if issued_ns < 0:
            return _Plan(ok=False, refusal="clock-reading-negative")

        return _Plan(
            ok=True,
            envelope=_Envelope(
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
            ),
        )

    return plan_observation


plan_observation = _restore_identity(_closed_planner(), "plan_observation", __name__)


# -- the result --------------------------------------------------------------


def _build_result_class():
    """Build :class:`ObservationResult` with its authorities in cells."""
    _receipt_type = ObservationReceipt
    _exchange_type = StructuredExchange
    _type = type
    _bool = bool
    _str = str
    _ValueError = ValueError
    _no_receipt = frozenset(("envelope-not-exact-type", "envelope-digest-mismatch"))

    @dataclass(frozen=True)
    class ObservationResult:
        """What one execution produced: a receipt, and possibly a value.

        ``receipt`` is present for every execution **except** the two in which
        no envelope could be trusted to be described: the object handed in was
        not exactly an envelope, or its digest did not re-derive. A receipt is
        a record about an envelope, so an envelope whose integrity failed gets
        no record rather than a record that might be wrong about it.

        ``exchange`` is OMI-V2's own result, retained only when the exchange
        ran *and* the deadline held. A void observation discards it: the
        deadline decided the outcome, and keeping a value that arrived too late
        is how a void result turns into a used one.

        **Pickling.** A successful result cannot be pickled, for exactly the
        reason a successful ``StructuredExchange`` cannot: it holds one, and
        that carrier's ``value`` is a ``MappingProxyType``. Every other state -
        refused, void, unusable - carries no proxy and pickles normally, as
        does the :class:`~scripts.open_model.observation_receipt.ObservationReceipt`
        on its own, which is the artifact meant to be stored. A caller who must
        serialise a successful value copies it out: ``dict(result.exchange.value)``
        is an ordinary picklable dict. Both halves of this are pinned by
        controls rather than only described here.
        """

        ok: bool
        receipt: Optional[Any] = None
        refusal: Optional[ExecutionRefusal] = None
        exchange: Optional[Any] = None

        def __post_init__(self) -> None:
            if _type(self.ok) is not _bool:
                raise _ValueError("ok must be exactly a bool")
            if self.receipt is not None and _type(self.receipt) is not _receipt_type:
                raise _ValueError("receipt must be exactly an ObservationReceipt")
            if self.exchange is not None and _type(self.exchange) is not _exchange_type:
                raise _ValueError("exchange must be exactly a StructuredExchange")
            if self.receipt is None:
                if _type(self.refusal) is not _str or self.refusal not in _no_receipt:
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
    _Receipt = ObservationReceipt
    _Result = ObservationResult
    _exchange_type = StructuredExchange
    _digest_of = _envelope_digest
    _json = json
    _type = type
    _int = int
    _len = len
    _sum = sum
    _dict = dict
    _tuple = tuple
    _callable = callable
    _RuntimeError = RuntimeError
    _ValueError = ValueError
    _TypeError = TypeError
    _AttributeError = AttributeError
    _OverflowError = OverflowError
    _RecursionError = RecursionError

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
    ):
        """One refusal, assembled in one place, in one coherent combination.

        Every refusal branch below routes through here rather than spelling out
        a receipt of its own. Sixteen hand-written receipts are sixteen chances
        to record a combination that cannot have happened - an attempted
        request with zero invocations, a satisfied reservation on a path that
        never reached the decision - and the receipt's own coherence check
        would then be discovering this module's bugs at runtime rather than
        never seeing one.
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

        Total for every reachable input **except** an exception raised by the
        injected ``exchange`` itself, which propagates. That is deliberate and
        it is the one place this function is not total:

        - it matches OMI-V2, where ``request_structured_json`` documents that
          transport errors raised by the underlying SDK propagate; and
        - OMI-V1's ``HermeticViolation`` **must** stay loud. Swallowing an
          exchange exception into a receipt would turn a hermetic breach - a
          double that reached the network - into a tidy record of a failed
          observation, which is precisely the failure mode the guard exists to
          prevent. A breach must fail the run.

        The order below is fixed:

        1. the envelope's exact type, then its **re-derived digest**. Both
           produce a result with **no receipt**: nothing else in this function
           may describe an envelope it could not first trust.
        2. ``exchange`` and ``clock`` callability.
        3. the first clock reading: exact ``int``, and not earlier than the
           envelope's ``issued_ns``.
        4. the deadline. If it has already passed, the observation is **void**
           before anything runs, the exchange is never invoked, and the
           reservation is recorded as ``not-evaluated`` because it never was.
        5. the reservation decision: exact type, bound to *this* reservation by
           digest, and reporting satisfied. Nothing is inspected; see
           :class:`ReservationDecision`.
        6. the exchange, invoked **at most once** through a latch. A second
           call raises rather than retrying, so "no retry loop exists in
           OMI-V3A" is enforced by the code and not merely asserted about it.
        7. the second clock reading, and the deadline again. A deadline crossed
           while the exchange ran voids the observation *even when the exchange
           succeeded* - a late answer is not an answer.
        8. the result size, measured on the canonical rendering of what OMI-V2
           accepted, against the envelope's declared ``max_result_bytes``.

        On step 8's honesty: this bounds the structured object OMI-V2 handed
        back, and OMI-V2's own ``max_chars`` bounds the payload string before
        it parses. Neither bounds how many bytes a transport read before either
        of them saw anything, and OMI-V3A has no transport to ask.
        """
        if _type(envelope) is not _Envelope:
            return _Result(ok=False, refusal="envelope-not-exact-type")
        try:
            rederived = _digest_of(envelope)
        except (_TypeError, _ValueError, _AttributeError, _OverflowError, _RecursionError):
            # A tampered field can be an object that no longer hashes, renders
            # or measures. Something that will not re-derive is, by definition,
            # not the envelope whose digest was recorded - so it lands on the
            # mismatch it is, rather than escaping as an exception from a
            # function that promises a result. The catch is named rather than
            # bare: anything stranger than these stays loud, which is the same
            # rule OMI-V1 applies to a hermetic breach.
            return _Result(ok=False, refusal="envelope-digest-mismatch")
        if rederived != envelope.envelope_digest:
            return _Result(ok=False, refusal="envelope-digest-mismatch")

        # Nothing below has read a clock yet, so nothing below may claim a
        # deadline determination. `not-evaluated` is the honest token for
        # every refusal taken before the first usable reading exists.
        if not _callable(exchange):
            return _refuse(
                envelope,
                "exchange-not-callable",
                deadline_result="not-evaluated",
                reservation_result="not-evaluated",
                invocations=0,
            )
        if not _callable(clock):
            return _refuse(
                envelope,
                "clock-not-callable",
                deadline_result="not-evaluated",
                reservation_result="not-evaluated",
                invocations=0,
            )

        before = clock()
        if _type(before) is not _int:
            return _refuse(
                envelope,
                "clock-reading-not-exact-int",
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
            # Void, not refused: the deadline decided this, and OMI-V3A does
            # not retry it. The reservation is recorded as never evaluated,
            # because it never was.
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
        if reservation_decision.reservation_digest != envelope.reservation.digest:
            # A decision about some other reservation is not a decision about
            # this one, however satisfied it says it is.
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
        after = clock()
        if _type(after) is not _int:
            return _refuse(
                envelope,
                "clock-reading-not-exact-int",
                deadline_result="not-evaluated",
                reservation_result="satisfied",
                invocations=1,
            )
        if after < before:
            return _refuse(
                envelope,
                "clock-not-monotonic",
                deadline_result="not-evaluated",
                reservation_result="satisfied",
                invocations=1,
            )
        elapsed = after - before

        if after >= envelope.deadline_ns:
            # Void even if the exchange succeeded. A late answer is not an
            # answer, and keeping the value would turn a void observation into
            # a used one.
            return _Result(
                ok=False,
                receipt=_receipt(
                    envelope,
                    outcome="void",
                    deadline_result="exceeded-during-request",
                    reservation_result="satisfied",
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
        # itself returns an exact dict, so `_dict()` of it runs no foreign
        # hook; the encode is what the measurement is about.
        try:
            rendered = _json.dumps(
                _dict(completed.value),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
        except (_ValueError, _TypeError, _RecursionError):
            # Unreachable for a value OMI-V2's validator accepted, which is
            # always exact built-in JSON types. Written as a refusal rather
            # than an assert so behaviour is identical under -O and -OO.
            return _refuse(
                envelope,
                "result-not-serializable",
                deadline_result="within-deadline",
                reservation_result="satisfied",
                invocations=1,
                elapsed_ns=elapsed,
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
            )

        return _Result(
            ok=True,
            exchange=completed,
            receipt=_receipt(
                envelope,
                outcome="observed",
                deadline_result="within-deadline",
                reservation_result="satisfied",
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

    def structured_exchange_adapter(backend: Any) -> Callable[[Any], StructuredExchange]:
        """Bind ``backend`` into the one exchange callable OMI-V3A supports.

        The returned callable takes an :class:`ObservationEnvelope` and calls
        OMI-V2's ``request_structured_json`` exactly once. It is the reuse
        point: OMI-V3A writes no request builder, no dialect dispatch, and no
        response validator of its own.

        What it sends, and nothing else:

        - one ``user`` message per evidence item, in the envelope's order,
          carrying that item's bytes decoded as strict UTF-8. The bytes are
          immutable and were proved decodable at planning time, so this decode
          cannot produce different text than the one the digest describes.
        - the fixed :data:`OBSERVER_SYSTEM_PROMPT` as the system text. No
          caller string reaches it.
        - an **empty tool list**, built here as a fresh literal. There is no
          parameter, field or keyword by which a caller could add a tool, and
          OMI-V2 would refuse the combination anyway.
        - the schema rebuilt from ``envelope.schema_bytes``, which this package
          produced from OMI-V2's own detached snapshot. OMI-V2 then validates
          and re-detaches it, so the document that goes on the wire has been
          through the controlled traversal twice and through a caller's hands
          never.
        - ``max_chars`` from the envelope's declared result bound, and
          ``max_tokens`` from its declared output bound. ``temperature`` is
          fixed at ``0.0``: an observation that changed answer between runs
          would not be evidence about anything.

        ``backend`` is accepted as ``Any`` and checked structurally by OMI-V2,
        which refuses a backend without ``complete_structured`` as
        ``backend-not-structured-capable`` rather than raising.

        **This adapter is where a future live backend would connect, and it is
        the boundary this package cannot see past.** The envelope's endpoint
        was validated as declared text; what ``backend`` actually contacts is a
        property of the operator-written factory that built it. OMI-V3A ships
        no factory and registers no backend.
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
