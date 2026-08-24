"""OMI-V3A - the closed vocabularies, the shared bounds, and the receipt.

This module is the **lower** half of OMI-V3A and imports nothing from
``scripts.open_model.observation``. The direction is deliberate and it is the
reason both the vocabularies and the shared numeric bounds live here rather
than beside the planner that emits them: a receipt is the artifact that
*records* an outcome, so the closed sets of things that can be recorded, and
the ceilings those recordings must respect, are stated once, here. The planner
and the executor import them rather than restating them. Restating them is
exactly the drift OMI-V2 spent five audit rounds removing, and a bound with two
values is a bound with none.

What this module deliberately does **not** define, because OMI-V2 already does
and a second copy would be a second source of truth:

  - the structured-request refusal vocabulary - imported as ``REFUSAL_TOKENS``;
  - the pre-dialect predicate - imported as ``is_pre_dialect_refusal``;
  - the exchange refusal vocabulary - imported as ``EXCHANGE_REFUSALS``;
  - the response failure vocabulary - imported as ``RESPONSE_FAILURES``;
  - the dialect predicate - imported as ``is_supported_dialect``.

:data:`PLAN_REFUSALS` is *composed* from the imported request vocabulary in the
same way :data:`~scripts.open_model.structured_exchange.EXCHANGE_REFUSALS` is
composed from it, so a token added to OMI-V2 arrives here without an edit.

## What a receipt is, and is not

A receipt is issued by ``execute_observation`` about **one** envelope whose
shape and integrity were re-established first. It records what happened in
closed tokens, digests, bounded counts, and one bounded duration.

It carries no evidence bytes, no prompt, no model output, no schema content, no
endpoint text, no header, no credential, no exception text, no object
representation, and no type name. That is a structural property of the field
list rather than a scrubbing pass: there is no field a payload could occupy.

A receipt is **not** issued for a refused *plan*, nor when the envelope handed
to the executor is not exactly an envelope, does not retain its exact field
types, or fails its digest re-derivation. A record about an envelope that could
not be trusted to be described is worse than no record.

## Every bound this carrier claims, it enforces

Jack's first independent round found the previous revision claiming bounded
fields while checking only non-negativity, which let a receipt hold an
``elapsed_ns`` of 10**5000 - constructible, and then unserialisable, because
CPython refuses to render an integer that long. Every count is now checked
against the same ceiling the envelope layer enforces, so a receipt that
constructs is a receipt that serialises.

The coherence rules go further than field-by-field validity: they encode the
**states the executor can genuinely emit**. A receipt claiming an attempted
request with zero invocations, a satisfied reservation on a path that never
reached the decision, a missing-key index past the end of the key list, or a
pre-dialect refusal that names a dialect, will not construct. Evidence that can
lie about itself is worse than no evidence.

## Determinism

:func:`serialize_receipt` is deterministic: the same receipt serialises to the
same bytes, and two equal receipts serialise to equal bytes. Keys are sorted,
separators are fixed, and the output is ASCII. Because every field is bounded
at construction, **every accepted receipt serialises inside**
:data:`RECEIPT_MAX_BYTES` - which is now a property a control proves at the
ceiling rather than a hope.

Determinism is a property of the *function*, not of two different runs of an
observation: ``elapsed_ns`` legitimately differs between runs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final, Literal, Optional, Union, get_args

from scripts.agent_backends.structured_request import (
    REFUSAL_TOKENS,
    StructuredRefusal,
    is_pre_dialect_refusal,
    is_supported_dialect,
)
from scripts.open_model.redaction import is_safe_token
from scripts.open_model.structured_exchange import (
    EXCHANGE_REFUSALS,
    RESPONSE_FAILURES,
    _restore_identity,
)


# ``_restore_identity`` is imported rather than copied a third time. It is a
# private name in a sibling module of the same package, and that is a real cost,
# stated rather than hidden: a third verbatim copy of the same eight-line helper
# is the alternative, and OMI-V1's standing boundary is "reuse, don't reinvent".
# A control asserts this module's binding IS the object ``structured_exchange``
# binds, so the two cannot silently diverge.


# -- identity and digest formats ---------------------------------------------


def _closed_uuid4_predicate():
    """Build :func:`is_canonical_uuid4`, builtins and alphabet bound in cells.

    Lives in this module rather than beside the generator because both the
    envelope and the receipt check a task identity against it, and a format
    predicate that two carriers trust must have exactly one definition.
    """
    _type = type
    _str = str
    _len = len
    _hex = frozenset("0123456789abcdef")
    _variants = frozenset("89ab")
    _separators = frozenset((8, 13, 18, 23))
    _range = range

    def is_canonical_uuid4(value: Any) -> bool:
        """True only for the canonical lowercase textual form of a UUIDv4.

        Exactly ``8-4-4-4-12`` lowercase hexadecimal characters, with the
        version nibble ``4`` and a variant nibble in ``{8, 9, a, b}``.

        This is a **format** check and nothing more. It does not establish that
        the value came from a cryptographic random source, that it is unique
        anywhere, or that any external system agrees it names this task.

        Braced, URN-prefixed, uppercase and unhyphenated spellings are all
        refused rather than normalised, so two receipts about the same task
        cannot disagree on how it is written.
        """
        if _type(value) is not _str:
            return False
        if _len(value) != 36:
            return False
        for position in _range(36):
            character = value[position]
            if position in _separators:
                if character != "-":
                    return False
            elif character not in _hex:
                return False
        if value[14] != "4":
            return False
        return value[19] in _variants

    return is_canonical_uuid4


is_canonical_uuid4 = _restore_identity(
    _closed_uuid4_predicate(), "is_canonical_uuid4", __name__
)


def _closed_digest_predicate():
    """Build :func:`is_sha256_digest`, builtins and alphabet bound in cells."""
    _type = type
    _str = str
    _len = len
    _hex = frozenset("0123456789abcdef")

    def is_sha256_digest(value: Any) -> bool:
        """True only for exactly 64 lowercase hexadecimal characters.

        Narrower on purpose than ``redaction.is_commit_revision``, which also
        accepts the 40-character SHA-1 form because a git revision may be
        either. Every digest OMI-V3A records is produced by this package with
        ``hashlib.sha256``, so accepting a 40-character value here would accept
        something this package never emits.
        """
        if _type(value) is not _str:
            return False
        if _len(value) != 64:
            return False
        for character in value:
            if character not in _hex:
                return False
        return True

    return is_sha256_digest


is_sha256_digest = _restore_identity(
    _closed_digest_predicate(), "is_sha256_digest", __name__
)


# -- the shared bounds -------------------------------------------------------


MAX_EVIDENCE_ITEMS: Final[int] = 32
"""Most evidence items one observation may carry."""

MAX_EVIDENCE_ITEM_BYTES: Final[int] = 65536
"""Most bytes one evidence item may carry. Each item carries at least one."""

MAX_EVIDENCE_TOTAL_BYTES: Final[int] = 262144
"""Most bytes all evidence items together may carry."""

MAX_RESULT_BYTES: Final[int] = 65536
"""Most bytes an accepted structured result may render to."""

MAX_CONTEXT_CEILING_TOKENS: Final[int] = 1048576
"""Largest declared context ceiling. Declared - never tokenizer-verified."""

MAX_REQUIRED_KEYS: Final[int] = 64
"""Most required keys one observation may declare."""

MAX_CLOCK_NS: Final[int] = 9223372036854775807
"""The clock ceiling: ``2**63 - 1`` nanoseconds, and the elapsed ceiling too.

Every clock reading OMI-V3A accepts, every deadline it derives, and every
elapsed duration it records must lie in ``[0, MAX_CLOCK_NS]``. That is the
natural range of a 64-bit nanosecond clock - about 292 years - and no
monotonic source this package could sensibly be handed exceeds it.

The bound exists for a specific failure Jack's first round found. An exact
``int`` has no width in Python, so a clock returning ``10**5000`` produced a
perfectly ordinary envelope and a perfectly ordinary receipt - and then
``json.dumps`` raised ``ValueError: Exceeds the limit (4300 digits) for integer
string conversion`` when the receipt was serialised, or produced a document far
past :data:`RECEIPT_MAX_BYTES`. A reading whose magnitude cannot be represented
inside the documented receipt bound is refused where it enters, not discovered
where it is written.

Nineteen digits is also what keeps :data:`RECEIPT_MAX_BYTES` provable: with
every count bounded, the largest receipt this module can accept is computed by
a control and asserted to fit.

These bounds are **captured into closure cells** by every carrier and every
entry point that enforces them, in this module and in
``scripts.open_model.observation``. Rebinding any of these names is inert; it
can only make the mirror disagree with the code, which a control asserts
against.
"""

RECEIPT_MAX_BYTES: Final[int] = 16384
"""Ceiling on one serialised receipt. Every accepted receipt fits inside it."""

_MAX_MISSING_INDICES: Final[int] = MAX_REQUIRED_KEYS


# -- closed vocabularies -----------------------------------------------------


EnvelopeRefusal = Literal[
    "task-id-not-canonical-uuid4",
    "principal-not-safe-token",
    "worker-not-safe-token",
    "evidence-not-exact-sequence",
    "evidence-empty",
    "evidence-too-many-items",
    "evidence-item-not-exact-type",
    "evidence-id-not-safe-token",
    "evidence-id-duplicated",
    "evidence-content-not-exact-bytes",
    "evidence-item-empty",
    "evidence-item-too-large",
    "evidence-total-too-large",
    "evidence-not-utf8",
    "evidence-digest-not-recomputable",
    "required-keys-not-exact-sequence",
    "required-keys-too-many",
    "required-key-not-safe-token",
    "limit-not-exact-int",
    "limit-out-of-range",
    "duration-not-exact-int",
    "duration-out-of-range",
    "clock-not-callable",
    "clock-raised",
    "clock-reading-not-exact-int",
    "clock-reading-negative",
    "clock-reading-too-large",
    "deadline-beyond-clock-ceiling",
    "reservation-not-exact-type",
    "reservation-field-not-exact-int",
    "reservation-field-out-of-range",
    "reservation-digest-not-recomputable",
    "endpoint-not-exact-str",
    "endpoint-too-long",
    "endpoint-scheme-not-plain-http",
    "endpoint-userinfo-present",
    "endpoint-query-or-fragment-present",
    "endpoint-percent-encoded",
    "endpoint-host-not-numeric-loopback",
    "endpoint-port-missing",
    "endpoint-port-not-canonical",
    "endpoint-path-not-v1",
]
"""Why an observation envelope was refused before it existed.

Deliberately contains **no** dialect token and **no** schema token. Both
concerns are decided by OMI-V2's ``plan_structured_request``, and its refusal
travels through unchanged rather than being re-spelled here - see
:data:`PlanRefusal`.

The ``*-not-recomputable`` pair is the answer to Jack's first finding. A carrier
whose stored digest does not hash its own current content has been altered
since it was built, and the planner will not adopt it - "exact type" is not
"unaltered", and the previous revision treated them as the same thing.
"""

ENVELOPE_REFUSALS: Final[frozenset[str]] = frozenset(get_args(EnvelopeRefusal))
"""Runtime mirror of :data:`EnvelopeRefusal`, derived from the Literal itself."""

PlanRefusal = Union[EnvelopeRefusal, StructuredRefusal]
"""Why no envelope was produced.

Composed from OMI-V2's ``StructuredRefusal`` rather than restating it, exactly
as ``ExchangeRefusal`` is.
"""

PLAN_REFUSALS: Final[frozenset[str]] = ENVELOPE_REFUSALS | REFUSAL_TOKENS
"""Runtime mirror of :data:`PlanRefusal`, composed the same way it is."""

ExecutionRefusal = Literal[
    "envelope-not-exact-type",
    "envelope-field-not-exact-type",
    "envelope-digest-mismatch",
    "exchange-not-callable",
    "clock-not-callable",
    "clock-raised",
    "clock-reading-not-exact-int",
    "clock-reading-out-of-range",
    "clock-not-monotonic",
    "reservation-decision-not-exact-type",
    "reservation-decision-field-invalid",
    "reservation-decision-mismatch",
    "reservation-not-satisfied",
    "exchange-result-not-exact-type",
    "result-not-serializable",
    "result-too-large",
]
"""Why an execution refused. Complete; safe to log verbatim.

There is deliberately no deadline token here. A blown deadline is not a refusal
to act - the action may already have happened - so it is recorded as
``outcome="void"`` plus a :data:`DeadlineResult`.

``clock-raised`` covers a clock callable that raised anything. Its exception is
neither recorded nor rendered: no text, class name, argument or representation
of it survives the boundary. See the note on the executor for the one honest
narrowing that implies.
"""

EXECUTION_REFUSALS: Final[frozenset[str]] = frozenset(get_args(ExecutionRefusal))
"""Runtime mirror of :data:`ExecutionRefusal`, derived from the Literal."""

#: The refusals about an envelope that could not be trusted to be described.
#: No receipt is issued for these, because a receipt is a record *about* an
#: envelope and these are the cases where there is no dependable envelope.
UNDESCRIBABLE_REFUSALS: Final[frozenset[str]] = frozenset(
    {
        "envelope-not-exact-type",
        "envelope-field-not-exact-type",
        "envelope-digest-mismatch",
    }
)

ObservationOutcome = Literal["observed", "unusable", "void", "refused"]
"""What one execution amounted to.

- **observed** - the exchange ran inside the deadline and returned a usable
  structured object within the declared byte bound. *Usable*, not conformant.
- **unusable** - the exchange ran inside the deadline and either was refused
  before a request went out, or answered with something that did not validate.
- **void** - the deadline was exceeded. OMI-V3A does not retry it.
- **refused** - OMI-V3A refused, for a reason in :data:`ExecutionRefusal`.
"""

OBSERVATION_OUTCOMES: Final[frozenset[str]] = frozenset(get_args(ObservationOutcome))

DeadlineResult = Literal[
    "within-deadline",
    "exceeded-before-request",
    "exceeded-during-request",
    "not-evaluated",
]
"""Which deadline determination was actually made, and what it found.

``not-evaluated`` is not a fourth place the deadline could fall - it records
that **no determination was completed**, because the execution refused before a
usable clock reading existed, or the reading after the exchange was unusable. A
determination the code did not make is not evidence, and writing it down as
though it were would be the receipt lying about itself.
"""

DEADLINE_RESULTS: Final[frozenset[str]] = frozenset(get_args(DeadlineResult))

ReservationResult = Literal["satisfied", "not-satisfied", "not-evaluated"]
"""What the **injected** reservation decision reported.

``satisfied`` records that a checker or an operator attested the declared
reservation was available. It does **not** record that OMI-V3A looked. This
package inspects no CPU, memory, GPU, process, service, or concurrent workload.

Which party attested is carried separately, in
``ObservationReceipt.reservation_attestation``, and is **not** collapsed into
this token: "a checker's automated claim" and "an operator's personal claim"
are different kinds of evidence, and a receipt that renders them identically
destroys the distinction the attestation vocabulary exists to preserve.
"""

RESERVATION_RESULTS: Final[frozenset[str]] = frozenset(get_args(ReservationResult))

RequestOutcome = Literal["not-attempted", "attempted"]
"""Whether the injected exchange callable was invoked at all."""

REQUEST_OUTCOMES: Final[frozenset[str]] = frozenset(get_args(RequestOutcome))

ResponseOutcome = Literal["none", "ok", "request-refused", "response-unusable"]
"""What came back from the exchange, in OMI-V2's own three-state shape.

``none`` covers every case where no exchange result was retained: it was never
invoked, it was invoked and the deadline then decided the outcome, or OMI-V3A
refused what came back.
"""

RESPONSE_OUTCOMES: Final[frozenset[str]] = frozenset(get_args(ResponseOutcome))

ReservationAttestation = Literal["operator-asserted", "checker-asserted"]
"""Who says the declared reservation was available.

Both tokens name a *claim by someone else*. Neither means OMI-V3A measured
anything. The pair mirrors the shape OMI-V1 chose for ``LocalityAttestation``:
a named, reviewable assertion rather than a silent assumption.
"""

RESERVATION_ATTESTATIONS: Final[frozenset[str]] = frozenset(
    get_args(ReservationAttestation)
)
"""Runtime mirror of :data:`ReservationAttestation`, derived from the Literal."""


# -- the receipt -------------------------------------------------------------


def _build_receipt_class():
    """Build :class:`ObservationReceipt` with its authorities in closure cells.

    Every vocabulary, predicate, bound and builtin the coherence check consults
    is filled into a cell when the class is defined. Nothing is looked up when
    an instance is built, so rebinding any of them - on this module, or on the
    ``scripts.open_model`` package that mirrors them - cannot widen what a
    receipt accepts.

    ``__post_init__`` takes ``self`` and nothing else. OMI-V2's fourth round
    established why that matters: an authority bound as a defaulted parameter is
    not captured at all, because any caller willing to pass a keyword can
    replace it.
    """
    _outcomes = OBSERVATION_OUTCOMES
    _deadlines = DEADLINE_RESULTS
    _reservations = RESERVATION_RESULTS
    _requests = REQUEST_OUTCOMES
    _responses = RESPONSE_OUTCOMES
    _attestations = RESERVATION_ATTESTATIONS
    _exec_refusals = EXECUTION_REFUSALS
    _request_refusals = EXCHANGE_REFUSALS
    _response_failures = RESPONSE_FAILURES
    _safe_token = is_safe_token
    _uuid4_ok = is_canonical_uuid4
    _digest_ok = is_sha256_digest
    _dialect_ok = is_supported_dialect
    _pre_dialect = is_pre_dialect_refusal
    _max_items = MAX_EVIDENCE_ITEMS
    _max_keys = MAX_REQUIRED_KEYS
    _max_indices = _MAX_MISSING_INDICES
    _max_evidence_bytes = MAX_EVIDENCE_TOTAL_BYTES
    _max_result_bytes = MAX_RESULT_BYTES
    _max_context = MAX_CONTEXT_CEILING_TOKENS
    _max_clock = MAX_CLOCK_NS
    _type = type
    _str = str
    _int = int
    _tuple = tuple
    _set = set
    _len = len
    _ValueError = ValueError

    @dataclass(frozen=True)
    class ObservationReceipt:
        """One payload-free record of one execution.

        Every field is a closed token, a digest, a bounded count, a safe
        identifier, or a bounded integer duration. There is no field that can
        hold evidence bytes, a prompt, model output, schema content, an
        endpoint, a header, a credential, an exception message, an object
        representation, or a type name - so a receipt cannot come to contain
        one, whatever a caller does.

        **Every bound named in this docstring is checked below.** The previous
        revision described the counts as bounded and checked only that they were
        non-negative; Jack's first round constructed a receipt with an
        ``elapsed_ns`` of 10**5000 that then could not be serialised at all.
        A receipt that constructs is now a receipt that serialises inside
        :data:`RECEIPT_MAX_BYTES`.

        The coherence rules encode the states the executor can genuinely emit,
        not merely field-by-field validity. A receipt claiming an attempted
        request with zero invocations, a satisfied reservation on a path that
        never reached the decision, a missing-key index past the end of the key
        list, a pre-dialect refusal that names a dialect, or a reservation
        result without the attestation that produced it, will not construct.

        Every field is a ``str``, an ``int``, a tuple of those, or ``None``, so
        a receipt pickles and copies normally - deliberately unlike a successful
        ``StructuredExchange``, which cannot pickle because it holds a
        ``MappingProxyType``. The receipt is the artifact meant to be stored, so
        it is the one that must survive serialisation.
        """

        task_id: str
        outcome: ObservationOutcome
        envelope_digest: str
        schema_digest: str
        authorizing_principal: str
        worker: str
        evidence_ids: tuple[str, ...]
        evidence_digests: tuple[str, ...]
        evidence_bytes: int
        deadline_result: DeadlineResult
        reservation_result: ReservationResult
        request_outcome: RequestOutcome
        response_outcome: ResponseOutcome
        exchange_invocations: int
        elapsed_ns: int
        result_bytes: int
        context_ceiling_tokens: int
        required_key_count: int
        dialect: Optional[str] = None
        reservation_attestation: Optional[ReservationAttestation] = None
        """Which party attested the reservation, or ``None`` if none was asked.

        Present exactly when ``reservation_result`` is not ``"not-evaluated"``.
        Carried separately from the result so that ``operator-asserted`` and
        ``checker-asserted`` stay distinguishable: collapsing them into one
        ``satisfied`` token would erase the only thing that says *whose* claim
        an operator is being asked to rely on.
        """
        refusal: Optional[ExecutionRefusal] = None
        request_refusal: Optional[str] = None
        response_failure: Optional[str] = None
        missing_key_indices: tuple[int, ...] = ()
        schema_conformance: Literal["unverified"] = "unverified"
        """Always ``"unverified"``, inherited from OMI-V2 unchanged.

        Nothing in OMI-V3A compares a response against the schema that was sent,
        because nothing in OMI-V2 does and OMI-V3A adds no validator.
        """

        def __post_init__(self) -> None:
            """Validate the receipt's own coherence. Raises; never repairs."""
            # -- identity, provenance, and closed tokens ---------------------
            if not _uuid4_ok(self.task_id):
                raise _ValueError("task_id must be a canonical lowercase UUIDv4")
            if _type(self.outcome) is not _str or self.outcome not in _outcomes:
                raise _ValueError("outcome must be a token from the closed vocabulary")
            if not _digest_ok(self.envelope_digest):
                raise _ValueError("envelope_digest must be 64 lowercase hex characters")
            if not _digest_ok(self.schema_digest):
                raise _ValueError("schema_digest must be 64 lowercase hex characters")
            if not _safe_token(self.authorizing_principal):
                raise _ValueError("authorizing_principal must be a safe token")
            if not _safe_token(self.worker):
                raise _ValueError("worker must be a safe token")
            if (
                _type(self.deadline_result) is not _str
                or self.deadline_result not in _deadlines
            ):
                raise _ValueError("deadline_result must be a token from the closed set")
            if (
                _type(self.reservation_result) is not _str
                or self.reservation_result not in _reservations
            ):
                raise _ValueError(
                    "reservation_result must be a token from the closed set"
                )
            if (
                _type(self.request_outcome) is not _str
                or self.request_outcome not in _requests
            ):
                raise _ValueError("request_outcome must be a token from the closed set")
            if (
                _type(self.response_outcome) is not _str
                or self.response_outcome not in _responses
            ):
                raise _ValueError("response_outcome must be a token from the closed set")
            if (
                _type(self.schema_conformance) is not _str
                or self.schema_conformance != "unverified"
            ):
                raise _ValueError(
                    "schema conformance is never established by this package"
                )
            # -- counts: exact ints, non-negative, AND within their ceilings --
            #
            # Each ceiling is the one the envelope layer enforces, imported
            # rather than restated. A count this carrier accepts is therefore a
            # count some accepted envelope or execution could actually produce.
            for value, ceiling, what in (
                (self.evidence_bytes, _max_evidence_bytes, "evidence_bytes"),
                (self.exchange_invocations, 1, "exchange_invocations"),
                (self.elapsed_ns, _max_clock, "elapsed_ns"),
                (self.result_bytes, _max_result_bytes, "result_bytes"),
                (self.context_ceiling_tokens, _max_context, "context_ceiling_tokens"),
                (self.required_key_count, _max_keys, "required_key_count"),
            ):
                if _type(value) is not _int:
                    raise _ValueError("every count must be an exact non-negative int")
                if value < 0:
                    raise _ValueError("every count must be an exact non-negative int")
                if value > ceiling:
                    raise _ValueError("a count exceeds its bound: " + what)
            # A declared context ceiling of zero is not something any accepted
            # envelope can carry, so it is not something a receipt may record.
            if self.context_ceiling_tokens < 1:
                raise _ValueError("context_ceiling_tokens must be at least one")
            # -- optional closed tokens --------------------------------------
            if self.dialect is not None and not _dialect_ok(self.dialect):
                raise _ValueError("dialect must be a verified dialect token or None")
            if self.reservation_attestation is not None and (
                _type(self.reservation_attestation) is not _str
                or self.reservation_attestation not in _attestations
            ):
                raise _ValueError(
                    "reservation_attestation must be a token from the closed set"
                )
            if self.refusal is not None and (
                _type(self.refusal) is not _str or self.refusal not in _exec_refusals
            ):
                raise _ValueError("refusal must be a token from the closed vocabulary")
            if self.request_refusal is not None and (
                _type(self.request_refusal) is not _str
                or self.request_refusal not in _request_refusals
            ):
                raise _ValueError(
                    "request_refusal must be a token from OMI-V2's closed vocabulary"
                )
            if self.response_failure is not None and (
                _type(self.response_failure) is not _str
                or self.response_failure not in _response_failures
            ):
                raise _ValueError(
                    "response_failure must be a token from OMI-V2's closed vocabulary"
                )
            # -- evidence identity: paired, distinct, bounded, and safe -------
            if _type(self.evidence_ids) is not _tuple:
                raise _ValueError("evidence_ids must be exactly a tuple")
            if _type(self.evidence_digests) is not _tuple:
                raise _ValueError("evidence_digests must be exactly a tuple")
            count = _len(self.evidence_ids)
            if count != _len(self.evidence_digests):
                raise _ValueError("every evidence id must carry exactly one digest")
            if not count or count > _max_items:
                raise _ValueError("evidence count is empty or over the bound")
            seen = _set()
            for identifier in self.evidence_ids:
                if not _safe_token(identifier):
                    raise _ValueError("every evidence id must be a safe token")
                if identifier in seen:
                    raise _ValueError(
                        "evidence ids must be distinct, as they are in an envelope"
                    )
                seen.add(identifier)
            for digest in self.evidence_digests:
                if not _digest_ok(digest):
                    raise _ValueError("every evidence digest must be 64 lowercase hex")
            # Every evidence item carries at least one byte and at most the
            # per-item ceiling, so the total is bracketed by the count. A
            # receipt reporting zero bytes for two items describes nothing an
            # envelope could hold.
            if self.evidence_bytes < count:
                raise _ValueError(
                    "evidence_bytes is below the minimum its item count implies"
                )
            # -- missing indices: coherent, increasing, and inside the keys ---
            if _type(self.missing_key_indices) is not _tuple:
                raise _ValueError("missing_key_indices must be exactly a tuple")
            if _len(self.missing_key_indices) > _max_indices:
                raise _ValueError("missing_key_indices exceeds the bound")
            if self.missing_key_indices:
                if self.response_failure != "missing-required-key":
                    raise _ValueError(
                        "missing_key_indices belong only to a missing-required-key "
                        "failure"
                    )
                if _len(self.missing_key_indices) > self.required_key_count:
                    raise _ValueError(
                        "more keys are reported missing than were ever required"
                    )
                previous = -1
                for index in self.missing_key_indices:
                    if _type(index) is not _int or index <= previous:
                        raise _ValueError(
                            "missing_key_indices must be increasing non-negative ints"
                        )
                    # An index is a position in the caller's own required-key
                    # tuple. One at or past the end of that tuple names nothing,
                    # and OMI-V2's validator cannot produce it.
                    if index >= self.required_key_count:
                        raise _ValueError(
                            "a missing-key index must fall inside required_key_count"
                        )
                    previous = index
            elif self.response_failure == "missing-required-key":
                raise _ValueError(
                    "a missing-required-key failure must report which indices"
                )
            # -- cross-field coherence ---------------------------------------
            attempted = self.request_outcome == "attempted"
            if attempted != (self.exchange_invocations == 1):
                raise _ValueError("request_outcome and exchange_invocations must agree")
            if self.response_outcome != "none" and not attempted:
                raise _ValueError(
                    "a response outcome requires that the exchange was invoked"
                )
            if not attempted and self.elapsed_ns != 0:
                raise _ValueError(
                    "an elapsed duration requires that the exchange was invoked"
                )
            if self.deadline_result == "not-evaluated" and self.elapsed_ns != 0:
                raise _ValueError(
                    "an elapsed duration requires a completed deadline determination"
                )
            evaluated = self.reservation_result != "not-evaluated"
            if evaluated != (self.reservation_attestation is not None):
                raise _ValueError(
                    "an evaluated reservation names its attestation, and only then"
                )
            if not evaluated and attempted:
                raise _ValueError(
                    "the exchange cannot run before the reservation was decided"
                )
            if attempted and self.reservation_result != "satisfied":
                raise _ValueError(
                    "the exchange runs only on a satisfied reservation decision"
                )
            if self.reservation_result == "not-satisfied" and (
                self.outcome != "refused" or self.refusal != "reservation-not-satisfied"
            ):
                raise _ValueError(
                    "an unsatisfied reservation is recorded as its own refusal"
                )
            if self.deadline_result == "exceeded-before-request" and attempted:
                raise _ValueError(
                    "a deadline exceeded before the request cannot have invoked it"
                )
            if self.deadline_result == "exceeded-during-request" and not attempted:
                raise _ValueError(
                    "a deadline exceeded during the request requires an invocation"
                )
            if (self.refusal is not None) != (self.outcome == "refused"):
                raise _ValueError(
                    "a refusal token and the refused outcome imply one another"
                )
            if (self.result_bytes > 0) != (self.outcome == "observed"):
                raise _ValueError(
                    "only an observed outcome carries a non-zero result size"
                )
            if self.deadline_result == "not-evaluated" and self.outcome != "refused":
                raise _ValueError(
                    "an unevaluated deadline is only ever recorded on a refusal"
                )
            carries_v2_token = (
                self.request_refusal is not None or self.response_failure is not None
            )
            if self.outcome == "observed":
                if self.deadline_result != "within-deadline":
                    raise _ValueError("an observed outcome met its deadline")
                if self.response_outcome != "ok":
                    raise _ValueError("an observed outcome carries an ok response")
                if carries_v2_token:
                    raise _ValueError("an observed outcome carries no failure token")
                if self.dialect is None:
                    raise _ValueError("an observed outcome must name its dialect")
            elif self.outcome == "unusable":
                if self.deadline_result != "within-deadline":
                    raise _ValueError("an unusable outcome met its deadline")
                if self.response_outcome not in (
                    "request-refused",
                    "response-unusable",
                ):
                    raise _ValueError(
                        "an unusable outcome names which half of OMI-V2 failed"
                    )
                if (self.request_refusal is None) == (self.response_failure is None):
                    raise _ValueError(
                        "an unusable outcome carries exactly one OMI-V2 token"
                    )
                if (self.response_outcome == "request-refused") != (
                    self.request_refusal is not None
                ):
                    raise _ValueError("response_outcome and the OMI-V2 token disagree")
                # OMI-V2's own dialect coherence, applied to the receipt. A
                # refusal taken before the dialect gate has none to name; a
                # response failure by definition follows a sent request and must
                # name the runtime it concerns. This is the backend carrier's
                # rule, imported rather than re-derived, so the two cannot drift.
                if self.response_failure is not None:
                    if self.dialect is None:
                        raise _ValueError(
                            "a response failure must name the dialect it was sent to"
                        )
                elif self.request_refusal == "backend-not-structured-capable" or (
                    _pre_dialect(self.request_refusal)
                ):
                    if self.dialect is not None:
                        raise _ValueError(
                            "a refusal taken before the dialect gate cannot name a "
                            "dialect"
                        )
                elif self.dialect is None:
                    raise _ValueError(
                        "a refusal taken after the dialect gate must name its dialect"
                    )
            else:
                # void and refused both discard whatever came back.
                if self.response_outcome != "none":
                    raise _ValueError(
                        "a void or refused outcome retains no response outcome"
                    )
                if carries_v2_token:
                    raise _ValueError("a void or refused outcome carries no OMI-V2 token")
                if self.outcome == "void" and self.deadline_result not in (
                    "exceeded-before-request",
                    "exceeded-during-request",
                ):
                    raise _ValueError(
                        "a void outcome must name how it blew the deadline"
                    )
                if self.outcome == "refused" and self.deadline_result not in (
                    "within-deadline",
                    "not-evaluated",
                ):
                    raise _ValueError(
                        "a blown deadline is recorded as void, never as refused"
                    )

    return ObservationReceipt


ObservationReceipt = _restore_identity(
    _build_receipt_class(), "ObservationReceipt", __name__
)


def _closed_receipt_serializer():
    """Build :func:`serialize_receipt`, its dependencies bound in cells.

    ``json`` is captured as the stdlib **module object**, matching the boundary
    OMI-V2 drew in ``_closed_snapshot_validator``: rebinding this module's
    ``json`` name is closed, while patching an attribute on the captured stdlib
    module remains the documented arbitrary-code-replacement boundary rather
    than a name-rebinding one.
    """
    _receipt_type = ObservationReceipt
    _max_bytes = RECEIPT_MAX_BYTES
    _json = json
    _type = type
    _list = list
    _len = len
    _ValueError = ValueError

    def serialize_receipt(receipt: Any) -> bytes:
        """Serialise one receipt to deterministic, bounded ASCII bytes.

        Raises ``ValueError`` for anything that is not exactly an
        :class:`ObservationReceipt`. There is no partial or best-effort
        rendering, because a half-serialised receipt is not evidence.

        Keys are sorted, separators are fixed, and ``ensure_ascii`` is on. Every
        value written is an int, ``None``, or a token from a closed ASCII
        vocabulary - identifiers included, since ``is_safe_token`` admits only
        ``[A-Za-z0-9][A-Za-z0-9._-]*``. No encoding, locale, hash ordering or
        insertion order can therefore change the output.

        **Every accepted receipt fits.** The ceiling check below is now
        unreachable rather than load-bearing: the carrier bounds every field it
        holds, and a control constructs the largest receipt the carrier will
        accept and asserts it serialises well inside
        :data:`RECEIPT_MAX_BYTES`. It is kept as a raise rather than an assert
        so behaviour is identical under ``-O`` and ``-OO``.
        """
        if _type(receipt) is not _receipt_type:
            raise _ValueError("serialize_receipt accepts exactly an ObservationReceipt")
        document = {
            "contract": "omi-v3a-observation-receipt",
            "task_id": receipt.task_id,
            "outcome": receipt.outcome,
            "envelope_digest": receipt.envelope_digest,
            "schema_digest": receipt.schema_digest,
            "authorizing_principal": receipt.authorizing_principal,
            "worker": receipt.worker,
            "evidence_ids": _list(receipt.evidence_ids),
            "evidence_digests": _list(receipt.evidence_digests),
            "evidence_bytes": receipt.evidence_bytes,
            "deadline_result": receipt.deadline_result,
            "reservation_result": receipt.reservation_result,
            "reservation_attestation": receipt.reservation_attestation,
            "request_outcome": receipt.request_outcome,
            "response_outcome": receipt.response_outcome,
            "exchange_invocations": receipt.exchange_invocations,
            "elapsed_ns": receipt.elapsed_ns,
            "result_bytes": receipt.result_bytes,
            "context_ceiling_tokens": receipt.context_ceiling_tokens,
            "required_key_count": receipt.required_key_count,
            "dialect": receipt.dialect,
            "refusal": receipt.refusal,
            "request_refusal": receipt.request_refusal,
            "response_failure": receipt.response_failure,
            "missing_key_indices": _list(receipt.missing_key_indices),
            "schema_conformance": receipt.schema_conformance,
        }
        encoded = _json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        if _len(encoded) > _max_bytes:
            raise _ValueError("serialised receipt exceeds the bound")
        return encoded

    return serialize_receipt


serialize_receipt = _restore_identity(
    _closed_receipt_serializer(), "serialize_receipt", __name__
)


__all__ = [
    "DEADLINE_RESULTS",
    "ENVELOPE_REFUSALS",
    "EXECUTION_REFUSALS",
    "MAX_CLOCK_NS",
    "MAX_CONTEXT_CEILING_TOKENS",
    "MAX_EVIDENCE_ITEMS",
    "MAX_EVIDENCE_ITEM_BYTES",
    "MAX_EVIDENCE_TOTAL_BYTES",
    "MAX_REQUIRED_KEYS",
    "MAX_RESULT_BYTES",
    "OBSERVATION_OUTCOMES",
    "PLAN_REFUSALS",
    "RECEIPT_MAX_BYTES",
    "REQUEST_OUTCOMES",
    "RESERVATION_ATTESTATIONS",
    "RESERVATION_RESULTS",
    "RESPONSE_OUTCOMES",
    "UNDESCRIBABLE_REFUSALS",
    "DeadlineResult",
    "EnvelopeRefusal",
    "ExecutionRefusal",
    "ObservationOutcome",
    "ObservationReceipt",
    "PlanRefusal",
    "RequestOutcome",
    "ReservationAttestation",
    "ReservationResult",
    "ResponseOutcome",
    "is_canonical_uuid4",
    "is_sha256_digest",
    "serialize_receipt",
]
