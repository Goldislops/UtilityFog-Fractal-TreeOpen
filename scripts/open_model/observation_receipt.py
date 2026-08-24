"""OMI-V3A - the closed vocabularies, and the payload-free observation receipt.

This module is the **lower** half of OMI-V3A and imports nothing from
``scripts.open_model.observation``. The direction is deliberate and it is the
reason the vocabularies live here rather than beside the planner that emits
them: a receipt is the artifact that *records* an outcome, so the closed sets
of things that can be recorded are stated once, here, and the planner and the
executor import them rather than restating them. Restating them is exactly the
drift OMI-V2 spent five audit rounds removing.

What this module deliberately does **not** define, because OMI-V2 already does
and a second copy would be a second source of truth:

  - the structured-request refusal vocabulary - imported as ``REFUSAL_TOKENS``
    from ``scripts.agent_backends.structured_request``;
  - the exchange refusal vocabulary - imported as ``EXCHANGE_REFUSALS`` from
    ``scripts.open_model.structured_exchange``;
  - the response failure vocabulary - imported as ``RESPONSE_FAILURES`` from
    the same place;
  - the dialect predicate - imported as ``is_supported_dialect``.

:data:`PLAN_REFUSALS` is *composed* from the imported request vocabulary in the
same way :data:`~scripts.open_model.structured_exchange.EXCHANGE_REFUSALS` is
composed from it, so a token added to OMI-V2 arrives here without an edit and
the two cannot drift apart.

## What a receipt is, and is not

A receipt is issued by ``execute_observation`` about **one** envelope whose
integrity was re-established first. It records what happened in closed tokens,
digests, counts, and one elapsed duration.

It carries no evidence bytes, no prompt, no model output, no schema content,
no endpoint text, no header, no credential, no exception text, no object
representation, and no type name. That is a structural property of the field
list rather than a scrubbing pass: there is no field a payload could occupy.
The identity and provenance fields are checked against ``is_safe_token`` and
the canonical UUIDv4 format, which is the same gate OMI-V1 applies to every
identifier it stores.

A receipt is **not** issued for a refused *plan*: a plan that never produced an
envelope has nothing to be a receipt about, and ``ObservationPlan`` carries
that refusal instead. Nor is one issued when the envelope handed to the
executor is not exactly an envelope, or fails its digest re-derivation - see
``ObservationResult`` in ``scripts.open_model.observation``.

## Determinism

:func:`serialize_receipt` is deterministic: the same receipt serialises to the
same bytes, and two equal receipts serialise to equal bytes. Keys are sorted,
separators are fixed, and the output is ASCII - every field is an integer,
``None``, or a token from a closed ASCII vocabulary, so no encoding choice can
vary. The serialisation is bounded because every field it reads is bounded at
construction.

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
    is_supported_dialect,
)
from scripts.open_model.redaction import is_safe_token
from scripts.open_model.structured_exchange import (
    EXCHANGE_REFUSALS,
    RESPONSE_FAILURES,
    _restore_identity,
)


# ``_restore_identity`` is imported rather than copied a third time. It is a
# private name in a sibling module of the same package, and that is a real
# cost, stated rather than hidden: a third verbatim copy of the same eight-line
# helper is the alternative, and OMI-V1's standing boundary is "reuse, don't
# reinvent". A control in ``tests/test_omi_v3_observation_envelope.py`` asserts
# this module's binding IS the object ``structured_exchange`` binds, so the two
# cannot silently diverge.


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
        OMI-V3A makes none of those claims - see ``new_task_id``.

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


# -- closed vocabularies -----------------------------------------------------


EnvelopeRefusal = Literal[
    "task-id-not-canonical-uuid4",
    "principal-not-safe-token",
    "worker-not-safe-token",
    "evidence-not-exact-sequence",
    "evidence-empty",
    "evidence-too-many-items",
    "evidence-item-not-exact-type",
    "evidence-id-duplicated",
    "evidence-item-too-large",
    "evidence-total-too-large",
    "evidence-not-utf8",
    "required-keys-not-exact-sequence",
    "required-keys-too-many",
    "required-key-not-safe-token",
    "limit-not-exact-int",
    "limit-out-of-range",
    "duration-not-exact-int",
    "duration-out-of-range",
    "clock-not-callable",
    "clock-reading-not-exact-int",
    "clock-reading-negative",
    "reservation-not-exact-type",
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
"""

ENVELOPE_REFUSALS: Final[frozenset[str]] = frozenset(get_args(EnvelopeRefusal))
"""Runtime mirror of :data:`EnvelopeRefusal`, derived from the Literal itself.

On the trust path: ``ObservationPlan`` rejects anything outside the composed
set. Derived with ``get_args`` rather than restated, so the check and the
declared type cannot disagree.
"""

PlanRefusal = Union[EnvelopeRefusal, StructuredRefusal]
"""Why no envelope was produced.

Composed from OMI-V2's ``StructuredRefusal`` rather than restating it, exactly
as ``ExchangeRefusal`` is. A dialect or schema token added to OMI-V2 arrives
here without an edit, and one removed there cannot linger here.
"""

PLAN_REFUSALS: Final[frozenset[str]] = ENVELOPE_REFUSALS | REFUSAL_TOKENS
"""Runtime mirror of :data:`PlanRefusal`, composed the same way it is."""

ExecutionRefusal = Literal[
    "envelope-not-exact-type",
    "envelope-digest-mismatch",
    "exchange-not-callable",
    "clock-not-callable",
    "clock-reading-not-exact-int",
    "clock-not-monotonic",
    "reservation-decision-not-exact-type",
    "reservation-decision-mismatch",
    "reservation-not-satisfied",
    "exchange-result-not-exact-type",
    "result-not-serializable",
    "result-too-large",
]
"""Why an execution refused. Complete; safe to log verbatim.

There is deliberately no deadline token here. A blown deadline is not a refusal
to act - the action may already have happened - so it is recorded as
``outcome="void"`` plus a :data:`DeadlineResult`, which says both *that* the
deadline decided the outcome and *when* it did.
"""

EXECUTION_REFUSALS: Final[frozenset[str]] = frozenset(get_args(ExecutionRefusal))
"""Runtime mirror of :data:`ExecutionRefusal`, derived from the Literal."""

ObservationOutcome = Literal["observed", "unusable", "void", "refused"]
"""What one execution amounted to.

- **observed** - the exchange ran inside the deadline and returned a usable
  structured object within the declared result bound. *Usable*, not conformant:
  see ``schema_conformance``.
- **unusable** - the exchange ran inside the deadline and either was refused
  before a request went out, or answered with something that did not validate.
  OMI-V2's own token says which.
- **void** - the deadline was exceeded. The observation is void, and OMI-V3A
  does not retry it.
- **refused** - OMI-V3A refused, for a reason in :data:`ExecutionRefusal`.

Four states rather than two, for the same reason OMI-V2 keeps three: an
operator who cannot tell a blown deadline from a bad answer from a refused
configuration cannot act on any of them.
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
that **no determination was completed**, because the execution refused before
it could read a usable clock reading, or the reading it got back after the
exchange was unusable. It exists so that a receipt never reports
``within-deadline`` on the strength of a check that did not happen: a
determination the code did not make is not evidence, and writing it down as
though it were would be the receipt lying about itself.
"""

DEADLINE_RESULTS: Final[frozenset[str]] = frozenset(get_args(DeadlineResult))

ReservationResult = Literal["satisfied", "not-satisfied", "not-evaluated"]
"""What the **injected** reservation decision reported.

``satisfied`` records that a checker or an operator attested the declared
reservation was available. It does **not** record that OMI-V3A looked. This
package inspects no CPU, no memory, no GPU, no process, no service, and no
concurrent workload - see "Attested, not verified" in
``docs/OMI_V3_OBSERVATION_INCEPTION.md``.
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

RESERVATION_ATTESTATIONS: Final[frozenset[str]] = frozenset(
    {"operator-asserted", "checker-asserted"}
)
"""Who says the declared reservation was available.

Both tokens name a *claim by someone else*. Neither means OMI-V3A measured
anything. The pair mirrors the shape OMI-V1 chose for
``LocalityAttestation``: a named, reviewable assertion rather than a silent
assumption.
"""


MAX_EVIDENCE_ITEMS: Final[int] = 32
"""Most evidence items one observation may carry.

Public because the envelope layer enforces the same number and there must be
exactly one of it - a receipt that accepted more items than an envelope could
produce, or fewer, would be a bound with two values. Both modules bind it into
a closure cell at definition time, so rebinding this name changes neither
check; it can only make the mirror disagree with the code, which a control
asserts against.
"""

MAX_REQUIRED_KEYS: Final[int] = 64
"""Most required keys one observation may declare. Shared exactly as above."""

_MAX_MISSING_INDICES: Final[int] = 64
_RECEIPT_MAX_BYTES: Final[int] = 16384


# -- the receipt -------------------------------------------------------------


def _build_receipt_class():
    """Build :class:`ObservationReceipt` with its authorities in closure cells.

    Every vocabulary, predicate and builtin the coherence check consults is
    filled into a cell when the class is defined. Nothing is looked up when an
    instance is built, so rebinding ``EXECUTION_REFUSALS``,
    ``OBSERVATION_OUTCOMES``, ``EXCHANGE_REFUSALS``, ``RESPONSE_FAILURES``,
    ``is_safe_token``, ``is_canonical_uuid4``, ``is_sha256_digest`` or
    ``is_supported_dialect`` - on this module, or on the ``scripts.open_model``
    package that mirrors them - cannot widen what a receipt accepts.

    ``__post_init__`` takes ``self`` and nothing else. OMI-V2's fourth round
    established why that matters: an authority bound as a defaulted parameter
    is not captured at all, because any caller willing to pass a keyword can
    replace it.
    """
    _outcomes = OBSERVATION_OUTCOMES
    _deadlines = DEADLINE_RESULTS
    _reservations = RESERVATION_RESULTS
    _requests = REQUEST_OUTCOMES
    _responses = RESPONSE_OUTCOMES
    _exec_refusals = EXECUTION_REFUSALS
    _request_refusals = EXCHANGE_REFUSALS
    _response_failures = RESPONSE_FAILURES
    _safe_token = is_safe_token
    _uuid4_ok = is_canonical_uuid4
    _digest_ok = is_sha256_digest
    _dialect_ok = is_supported_dialect
    _max_items = MAX_EVIDENCE_ITEMS
    _max_keys = MAX_REQUIRED_KEYS
    _max_indices = _MAX_MISSING_INDICES
    _type = type
    _str = str
    _int = int
    _tuple = tuple
    _len = len
    _getattr = getattr
    _ValueError = ValueError

    @dataclass(frozen=True)
    class ObservationReceipt:
        """One payload-free record of one execution.

        Every field is a closed token, a digest, a bounded count, a safe
        identifier, or an integer duration. There is no field that can hold
        evidence bytes, a prompt, model output, schema content, an endpoint, a
        header, a credential, an exception message, an object representation,
        or a type name - so a receipt cannot come to contain one, whatever a
        caller does.

        The coherence rules below are not decoration. A receipt claiming a
        request was attempted while reporting zero invocations, or claiming an
        observation succeeded while carrying a refusal, would be evidence that
        lies about itself - and evidence that can lie is worse than none.

        Every field is an ``str``, ``int``, ``bytes``-free tuple, or ``None``,
        so a receipt pickles and copies normally. That is deliberately unlike
        a successful ``StructuredExchange``, which cannot pickle because it
        holds a ``MappingProxyType``: the receipt is the artifact meant to be
        stored, so it is the one that must survive serialisation.
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
        refusal: Optional[ExecutionRefusal] = None
        request_refusal: Optional[str] = None
        response_failure: Optional[str] = None
        missing_key_indices: tuple[int, ...] = ()
        schema_conformance: Literal["unverified"] = "unverified"
        """Always ``"unverified"``, inherited from OMI-V2 unchanged.

        Nothing in OMI-V3A compares a response against the schema that was
        sent, because nothing in OMI-V2 does and OMI-V3A adds no validator.
        Carrying the limit as a closed field means a future conformance check
        has to widen this vocabulary in the open rather than arrive quietly.
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
                raise _ValueError(
                    "response_outcome must be a token from the closed set"
                )
            if (
                _type(self.schema_conformance) is not _str
                or self.schema_conformance != "unverified"
            ):
                raise _ValueError(
                    "schema conformance is never established by this package"
                )
            # -- counts: exact ints only, so no bool and no int subclass -----
            for name in (
                "evidence_bytes",
                "exchange_invocations",
                "elapsed_ns",
                "result_bytes",
                "context_ceiling_tokens",
                "required_key_count",
            ):
                number = _getattr(self, name)
                if _type(number) is not _int or number < 0:
                    raise _ValueError("counts must be exact non-negative ints")
            if self.exchange_invocations > 1:
                raise _ValueError(
                    "OMI-V3A invokes the exchange at most once; there is no retry"
                )
            if self.required_key_count > _max_keys:
                raise _ValueError("required_key_count exceeds the bound")
            # -- optional closed tokens --------------------------------------
            if self.dialect is not None and not _dialect_ok(self.dialect):
                raise _ValueError("dialect must be a verified dialect token or None")
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
            # -- evidence identity: paired, bounded, and safe -----------------
            if _type(self.evidence_ids) is not _tuple:
                raise _ValueError("evidence_ids must be exactly a tuple")
            if _type(self.evidence_digests) is not _tuple:
                raise _ValueError("evidence_digests must be exactly a tuple")
            if _len(self.evidence_ids) != _len(self.evidence_digests):
                raise _ValueError("every evidence id must carry exactly one digest")
            if not self.evidence_ids or _len(self.evidence_ids) > _max_items:
                raise _ValueError("evidence count is empty or over the bound")
            for identifier in self.evidence_ids:
                if not _safe_token(identifier):
                    raise _ValueError("every evidence id must be a safe token")
            for digest in self.evidence_digests:
                if not _digest_ok(digest):
                    raise _ValueError("every evidence digest must be 64 lowercase hex")
            # -- missing indices: coherent, increasing, only where earned -----
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
                previous = -1
                for index in self.missing_key_indices:
                    if _type(index) is not _int or index <= previous:
                        raise _ValueError(
                            "missing_key_indices must be increasing non-negative ints"
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
            if self.reservation_result == "not-evaluated" and attempted:
                raise _ValueError(
                    "the exchange cannot run before the reservation was decided"
                )
            if attempted and self.reservation_result != "satisfied":
                raise _ValueError(
                    "the exchange runs only on a satisfied reservation decision"
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
    _max_bytes = _RECEIPT_MAX_BYTES
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

        Keys are sorted, separators are fixed, and ``ensure_ascii`` is on.
        Every value written is an int, ``None``, or a token from a closed ASCII
        vocabulary - identifiers included, since ``is_safe_token`` admits only
        ``[A-Za-z0-9][A-Za-z0-9._-]*``. No encoding, locale, hash ordering or
        insertion order can therefore change the output.
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
            # Unreachable for a receipt this module accepted - every field is
            # bounded at construction. Written as a raise rather than an assert
            # so behaviour is identical under -O and -OO.
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
    "MAX_EVIDENCE_ITEMS",
    "MAX_REQUIRED_KEYS",
    "OBSERVATION_OUTCOMES",
    "PLAN_REFUSALS",
    "REQUEST_OUTCOMES",
    "RESERVATION_ATTESTATIONS",
    "RESERVATION_RESULTS",
    "RESPONSE_OUTCOMES",
    "DeadlineResult",
    "EnvelopeRefusal",
    "ExecutionRefusal",
    "ObservationOutcome",
    "ObservationReceipt",
    "PlanRefusal",
    "RequestOutcome",
    "ReservationResult",
    "ResponseOutcome",
    "is_canonical_uuid4",
    "is_sha256_digest",
    "serialize_receipt",
]
