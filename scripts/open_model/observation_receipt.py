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
from dataclasses import dataclass, fields
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


# -- the missing-field-safe reader -------------------------------------------
#
# One mechanism, shared by both V3A modules, for one question: **is this field
# still set on this instance?**
#
# ``getattr`` cannot answer it, and that is the whole reason this exists. A
# frozen dataclass is not sealed: ``object.__delattr__`` removes an instance
# attribute without the carrier's cooperation. For a field declared *without* a
# default, the next read raises ``AttributeError`` - loud, but raw, and out of
# functions documented as total. For a field declared *with* a default the class
# attribute is still there, so the read quietly returns that default: the empty
# string for a digest, zero for a byte count, ``None`` for an optional. A
# sentinel-defaulted ``getattr`` catches neither case, because ``getattr`` is
# precisely what falls through to the class. Only the instance ``__dict__``
# distinguishes a value that was set from a fallback to the class, so that is
# what is read.


def _closed_presence_reader():
    """Build the missing-field-safe reader, every dependency bound in a cell."""
    _dataclass_fields = fields
    _instance_dict_of = object.__getattribute__
    _type = type
    _dict = dict
    _tuple = tuple

    class _AbsentField:
        """The marker returned for a field that is not set on the instance.

        A dedicated private type rather than ``None`` or a string, because every
        consumer already decides by ``type(x) is T`` identity. An absent field
        must fail *whatever* exact-type check the caller already applies, and
        must never be mistakable for a value a carrier could legitimately hold -
        so it is of a type no field is ever declared as.
        """

        __slots__ = ()

        def __repr__(self) -> str:
            return "<absent field>"

    _absent = _AbsentField()

    def _instance_values(carrier: Any):
        """The carrier's own instance dictionary, or ``None`` if it has none.

        Reached through ``object.__getattribute__`` so that a ``__getattr__``,
        ``__getattribute__``, property or descriptor on the carrier's type
        cannot answer in its place.
        """
        try:
            instance = _instance_dict_of(carrier, "__dict__")
        except AttributeError:
            return None
        return instance if _type(instance) is _dict else None

    def _field_of(carrier: Any, name: str) -> Any:
        """``carrier``'s own instance value for ``name``, or the absent marker.

        Never falls back to a class attribute. Callers need no new branch: the
        marker fails the exact-type check they already perform, so a deleted
        field produces the same closed refusal as a wrongly-typed one, naming
        the same field.
        """
        instance = _instance_values(carrier)
        if instance is None or name not in instance:
            return _absent
        return instance[name]

    def _fields_present(carrier: Any, names: Any) -> bool:
        """True only if **every** name in ``names`` is set on the instance.

        The whole-carrier form, for a checker that reads too many fields for a
        per-field marker to be the clearer repair.
        """
        instance = _instance_values(carrier)
        if instance is None:
            return False
        for name in names:
            if name not in instance:
                return False
        return True

    def _declared_field_names(carrier_type: Any) -> tuple:
        """The declared field names of a dataclass, as an exact tuple.

        Taken from the dataclass itself, at import time, so a field added later
        is covered without anyone remembering to extend a hand-written list.
        """
        return _tuple(f.name for f in _dataclass_fields(carrier_type))

    return _absent, _field_of, _fields_present, _declared_field_names


(
    _ABSENT_FIELD,
    _field_of,
    _fields_present,
    _declared_field_names,
) = _closed_presence_reader()
_field_of = _restore_identity(_field_of, "_field_of", __name__)
_fields_present = _restore_identity(_fields_present, "_fields_present", __name__)
_declared_field_names = _restore_identity(
    _declared_field_names, "_declared_field_names", __name__
)


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
    "schema-bytes-not-exact-bytes",
    "schema-bytes-not-canonical",
    "schema-digest-not-recomputable",
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

The ``*-not-recomputable`` trio is the answer to Jack's first finding. A carrier
whose stored digest does not hash its own current content has been altered
since it was built, and the planner will not adopt it - "exact type" is not
"unaltered", and the first revision treated them as the same thing.

The ``schema-bytes-*`` pair describes the envelope's own *storage* of a schema,
not the schema's validity: whether the stored bytes are exactly ``bytes``, and
whether they are exactly the canonical rendering of a snapshot OMI-V2 accepts.
Whether a schema is acceptable at all remains entirely OMI-V2's decision, and
its token travels through unchanged.

There is still no dialect token here. When the envelope layer needs to say a
stored dialect is unacceptable it returns OMI-V2's own ``dialect-unsupported``,
which :data:`PlanRefusal` already composes in.
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
    "envelope-semantics-invalid",
    "envelope-digest-mismatch",
    "exchange-result-field-invalid",
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
        "envelope-semantics-invalid",
        "envelope-digest-mismatch",
    }
)
"""The four refusals about an envelope that could not be trusted to be described.

``envelope-semantics-invalid`` joined after Jack's second round. The envelope
digest is **unkeyed**: it is a pure function of the envelope's own public
fields, computed by a function this package exports, so anyone able to mutate a
field can recompute and reinstall it. Digest equality therefore establishes
*self-consistency*, never *validity* - and the previous revision treated the
two as the same thing, admitting a resealed envelope carrying an unsupported
dialect, a DNS endpoint, an over-limit reservation, or evidence that was no
longer UTF-8.

Deliberately **one** token rather than forty-two. The executor does not
re-spell the envelope vocabulary into its own: a caller who wants to know
*which* constraint failed re-plans the inputs, where the precise token is
returned. Carrying forty-two envelope tokens into the execution vocabulary
would double every closed set for no operational gain.
"""

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


def _closed_receipt_checker():
    """Build :func:`_check_receipt`, every authority bound in a closure cell.

    Validation and document construction are **one traversal**, and that is the
    correction for Jack's third-round second finding. The previous revision
    re-validated a receipt inside ``serialize_receipt`` and then *re-read every
    field* to build the document it wrote - so anything that changed between the
    check and the read was serialised unchecked. The window was small and it was
    real: a frozen dataclass is not sealed, and ``object.__setattr__`` needs no
    cooperation from anyone.

    Now the checker returns the document. Every value in it was placed there at
    the moment that value was proved acceptable, and the serialiser writes that
    document and never touches the receipt again.
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
    _getattr = getattr
    _ValueError = ValueError

    def _check_receipt(receipt: Any) -> dict:
        """Validate one receipt and return its detached serialization document.

        Raises ``ValueError`` for any incoherence; never repairs. The returned
        document holds only ``str``, ``int``, ``None`` and freshly built
        ``list`` objects - nothing that can change afterwards, and nothing that
        shares an object with the receipt.
        """
        # -- identity, provenance, and closed tokens -----------------------
        task_id = receipt.task_id
        if not _uuid4_ok(task_id):
            raise _ValueError("task_id must be a canonical lowercase UUIDv4")
        outcome = receipt.outcome
        if _type(outcome) is not _str or outcome not in _outcomes:
            raise _ValueError("outcome must be a token from the closed vocabulary")
        envelope_digest = receipt.envelope_digest
        if not _digest_ok(envelope_digest):
            raise _ValueError("envelope_digest must be 64 lowercase hex characters")
        schema_digest = receipt.schema_digest
        if not _digest_ok(schema_digest):
            raise _ValueError("schema_digest must be 64 lowercase hex characters")
        principal = receipt.authorizing_principal
        if not _safe_token(principal):
            raise _ValueError("authorizing_principal must be a safe token")
        worker = receipt.worker
        if not _safe_token(worker):
            raise _ValueError("worker must be a safe token")
        deadline_result = receipt.deadline_result
        if _type(deadline_result) is not _str or deadline_result not in _deadlines:
            raise _ValueError("deadline_result must be a token from the closed set")
        reservation_result = receipt.reservation_result
        if (
            _type(reservation_result) is not _str
            or reservation_result not in _reservations
        ):
            raise _ValueError("reservation_result must be a token from the closed set")
        request_outcome = receipt.request_outcome
        if _type(request_outcome) is not _str or request_outcome not in _requests:
            raise _ValueError("request_outcome must be a token from the closed set")
        response_outcome = receipt.response_outcome
        if _type(response_outcome) is not _str or response_outcome not in _responses:
            raise _ValueError("response_outcome must be a token from the closed set")
        conformance = receipt.schema_conformance
        if _type(conformance) is not _str or conformance != "unverified":
            raise _ValueError(
                "schema conformance is never established by this package"
            )
        # -- counts: exact ints, non-negative, and within their ceilings ----
        counts = {}
        for name, ceiling in (
            ("evidence_bytes", _max_evidence_bytes),
            ("exchange_invocations", 1),
            ("elapsed_ns", _max_clock),
            ("result_bytes", _max_result_bytes),
            ("context_ceiling_tokens", _max_context),
            ("required_key_count", _max_keys),
        ):
            value = _getattr(receipt, name)
            if _type(value) is not _int:
                raise _ValueError("every count must be an exact non-negative int")
            if value < 0:
                raise _ValueError("every count must be an exact non-negative int")
            if value > ceiling:
                raise _ValueError("a count exceeds its bound: " + name)
            counts[name] = value
        if counts["context_ceiling_tokens"] < 1:
            raise _ValueError("context_ceiling_tokens must be at least one")
        # -- optional closed tokens -----------------------------------------
        dialect = receipt.dialect
        if dialect is not None and not _dialect_ok(dialect):
            raise _ValueError("dialect must be a verified dialect token or None")
        attestation = receipt.reservation_attestation
        if attestation is not None and (
            _type(attestation) is not _str or attestation not in _attestations
        ):
            raise _ValueError(
                "reservation_attestation must be a token from the closed set"
            )
        refusal = receipt.refusal
        if refusal is not None and (
            _type(refusal) is not _str or refusal not in _exec_refusals
        ):
            raise _ValueError("refusal must be a token from the closed vocabulary")
        request_refusal = receipt.request_refusal
        if request_refusal is not None and (
            _type(request_refusal) is not _str
            or request_refusal not in _request_refusals
        ):
            raise _ValueError(
                "request_refusal must be a token from OMI-V2's closed vocabulary"
            )
        response_failure = receipt.response_failure
        if response_failure is not None and (
            _type(response_failure) is not _str
            or response_failure not in _response_failures
        ):
            raise _ValueError(
                "response_failure must be a token from OMI-V2's closed vocabulary"
            )
        # -- evidence identity: paired, distinct, bounded, safe -------------
        ids = receipt.evidence_ids
        digests = receipt.evidence_digests
        if _type(ids) is not _tuple:
            raise _ValueError("evidence_ids must be exactly a tuple")
        if _type(digests) is not _tuple:
            raise _ValueError("evidence_digests must be exactly a tuple")
        count = _len(ids)
        if count != _len(digests):
            raise _ValueError("every evidence id must carry exactly one digest")
        if not count or count > _max_items:
            raise _ValueError("evidence count is empty or over the bound")
        seen = _set()
        id_document = []
        for identifier in ids:
            if not _safe_token(identifier):
                raise _ValueError("every evidence id must be a safe token")
            if identifier in seen:
                raise _ValueError(
                    "evidence ids must be distinct, as they are in an envelope"
                )
            seen.add(identifier)
            id_document.append(identifier)
        digest_document = []
        for digest in digests:
            if not _digest_ok(digest):
                raise _ValueError("every evidence digest must be 64 lowercase hex")
            digest_document.append(digest)
        if counts["evidence_bytes"] < count:
            raise _ValueError(
                "evidence_bytes is below the minimum its item count implies"
            )
        # -- missing indices: coherent, increasing, inside the key count ----
        indices = receipt.missing_key_indices
        if _type(indices) is not _tuple:
            raise _ValueError("missing_key_indices must be exactly a tuple")
        if _len(indices) > _max_indices:
            raise _ValueError("missing_key_indices exceeds the bound")
        index_document = []
        if indices:
            if response_failure != "missing-required-key":
                raise _ValueError(
                    "missing_key_indices belong only to a missing-required-key "
                    "failure"
                )
            if _len(indices) > counts["required_key_count"]:
                raise _ValueError(
                    "more keys are reported missing than were ever required"
                )
            previous = -1
            for index in indices:
                if _type(index) is not _int or index <= previous:
                    raise _ValueError(
                        "missing_key_indices must be increasing non-negative ints"
                    )
                if index >= counts["required_key_count"]:
                    raise _ValueError(
                        "a missing-key index must fall inside required_key_count"
                    )
                previous = index
                index_document.append(index)
        elif response_failure == "missing-required-key":
            raise _ValueError(
                "a missing-required-key failure must report which indices"
            )
        # -- cross-field coherence -------------------------------------------
        attempted = request_outcome == "attempted"
        if attempted != (counts["exchange_invocations"] == 1):
            raise _ValueError("request_outcome and exchange_invocations must agree")
        if response_outcome != "none" and not attempted:
            raise _ValueError(
                "a response outcome requires that the exchange was invoked"
            )
        if not attempted and counts["elapsed_ns"] != 0:
            raise _ValueError(
                "an elapsed duration requires that the exchange was invoked"
            )
        if deadline_result == "not-evaluated" and counts["elapsed_ns"] != 0:
            raise _ValueError(
                "an elapsed duration requires a completed deadline determination"
            )
        evaluated = reservation_result != "not-evaluated"
        if evaluated != (attestation is not None):
            raise _ValueError(
                "an evaluated reservation names its attestation, and only then"
            )
        if not evaluated and attempted:
            raise _ValueError(
                "the exchange cannot run before the reservation was decided"
            )
        if attempted != (reservation_result == "satisfied"):
            raise _ValueError(
                "a satisfied reservation and an attempted request imply one another"
            )
        if reservation_result == "not-satisfied" and (
            outcome != "refused" or refusal != "reservation-not-satisfied"
        ):
            raise _ValueError(
                "an unsatisfied reservation is recorded as its own refusal"
            )
        if deadline_result == "exceeded-before-request" and attempted:
            raise _ValueError(
                "a deadline exceeded before the request cannot have invoked it"
            )
        if deadline_result == "exceeded-during-request" and not attempted:
            raise _ValueError(
                "a deadline exceeded during the request requires an invocation"
            )
        if (refusal is not None) != (outcome == "refused"):
            raise _ValueError(
                "a refusal token and the refused outcome imply one another"
            )
        if (counts["result_bytes"] > 0) != (outcome == "observed"):
            raise _ValueError(
                "only an observed outcome carries a non-zero result size"
            )
        if deadline_result == "not-evaluated" and outcome != "refused":
            raise _ValueError(
                "an unevaluated deadline is only ever recorded on a refusal"
            )
        carries_v2_token = request_refusal is not None or response_failure is not None
        if outcome == "observed":
            if deadline_result != "within-deadline":
                raise _ValueError("an observed outcome met its deadline")
            if response_outcome != "ok":
                raise _ValueError("an observed outcome carries an ok response")
            if carries_v2_token:
                raise _ValueError("an observed outcome carries no failure token")
            if dialect is None:
                raise _ValueError("an observed outcome must name its dialect")
        elif outcome == "unusable":
            if deadline_result != "within-deadline":
                raise _ValueError("an unusable outcome met its deadline")
            if response_outcome not in ("request-refused", "response-unusable"):
                raise _ValueError(
                    "an unusable outcome names which half of OMI-V2 failed"
                )
            if (request_refusal is None) == (response_failure is None):
                raise _ValueError(
                    "an unusable outcome carries exactly one OMI-V2 token"
                )
            if (response_outcome == "request-refused") != (request_refusal is not None):
                raise _ValueError("response_outcome and the OMI-V2 token disagree")
            # OMI-V2's own dialect coherence, imported rather than re-derived.
            if response_failure is not None:
                if dialect is None:
                    raise _ValueError(
                        "a response failure must name the dialect it was sent to"
                    )
            elif request_refusal == "backend-not-structured-capable" or (
                _pre_dialect(request_refusal)
            ):
                if dialect is not None:
                    raise _ValueError(
                        "a refusal taken before the dialect gate cannot name a "
                        "dialect"
                    )
            elif dialect is None:
                raise _ValueError(
                    "a refusal taken after the dialect gate must name its dialect"
                )
        else:
            if response_outcome != "none":
                raise _ValueError(
                    "a void or refused outcome retains no response outcome"
                )
            if carries_v2_token:
                raise _ValueError("a void or refused outcome carries no OMI-V2 token")
            if dialect is not None:
                raise _ValueError("a void or refused outcome names no dialect")
            if outcome == "void" and deadline_result not in (
                "exceeded-before-request",
                "exceeded-during-request",
            ):
                raise _ValueError("a void outcome must name how it blew the deadline")
            if outcome == "refused" and deadline_result not in (
                "within-deadline",
                "not-evaluated",
            ):
                raise _ValueError(
                    "a blown deadline is recorded as void, never as refused"
                )
        # -- the detached document, built from what was just proved ---------
        return {
            "contract": "omi-v3a-observation-receipt",
            "task_id": task_id,
            "outcome": outcome,
            "envelope_digest": envelope_digest,
            "schema_digest": schema_digest,
            "authorizing_principal": principal,
            "worker": worker,
            "evidence_ids": id_document,
            "evidence_digests": digest_document,
            "evidence_bytes": counts["evidence_bytes"],
            "deadline_result": deadline_result,
            "reservation_result": reservation_result,
            "reservation_attestation": attestation,
            "request_outcome": request_outcome,
            "response_outcome": response_outcome,
            "exchange_invocations": counts["exchange_invocations"],
            "elapsed_ns": counts["elapsed_ns"],
            "result_bytes": counts["result_bytes"],
            "context_ceiling_tokens": counts["context_ceiling_tokens"],
            "required_key_count": counts["required_key_count"],
            "dialect": dialect,
            "refusal": refusal,
            "request_refusal": request_refusal,
            "response_failure": response_failure,
            "missing_key_indices": index_document,
            "schema_conformance": conformance,
        }

    return _check_receipt


_check_receipt = _restore_identity(
    _closed_receipt_checker(), "_check_receipt", __name__
)


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
    _check = _check_receipt

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
            """Validate through the one checker. Raises; never repairs.

            The checker also *builds* the serialization document, and
            :func:`serialize_receipt` uses that document rather than re-reading
            these fields. Construction discards it: nothing is stored, so a
            receipt carries no second copy of itself that could fall out of step
            with the fields.
            """
            _check(self)

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
    #: The checker itself, not the carrier's method. Reaching it through the
    #: instance - or even through the class's `__post_init__` - would be an
    #: attribute lookup on something a caller can mutate. Bound here as the
    #: function object, it cannot be shadowed, rebound, or made to return a
    #: different document.
    _check = _check_receipt
    _present = _fields_present
    _RECEIPT_FIELDS = _declared_field_names(ObservationReceipt)
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
        # Presence, before any field is read. ``_check`` reads twenty-five
        # fields, and freezing is not sealing: ``object.__delattr__`` removes
        # an instance attribute, after which a field declared without a
        # default raised raw ``AttributeError`` straight out of this
        # function, and one declared with a default read quietly as that
        # default. One gate is clearer here than twenty-five markers, and a
        # receipt owes its caller the same deterministic ``ValueError`` it
        # gives every other incoherence. Which field is missing is not
        # disclosed - a receipt discloses nothing about what it was handed.
        if not _present(receipt, _RECEIPT_FIELDS):
            raise _ValueError("every receipt field must still be set")
        # Validated and rendered in ONE traversal. The checker returns a detached
        # document built from the values it proved acceptable, and that document
        # is what gets written - the receipt is never read again.
        #
        # Jack's third round named the window this closes: the previous revision
        # re-validated the receipt and then re-read every field to build the
        # document, so anything that changed in between was serialised
        # unchecked. Small window, real window - `object.__setattr__` needs no
        # cooperation from anyone.
        document = _check(receipt)
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
