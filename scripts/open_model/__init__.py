"""OMI-V1 - provider-neutral open / local model integration foundation.

This package is the capability, eligibility and evaluation layer that sits
**above** the merged agent-backend seam in ``scripts/agent_backends/``. It
does not replace that seam and does not add a second transport stack - per
the standing boundary in ``docs/LOCAL_MODEL_DEPLOYMENT_INCEPTION.md``: reuse,
don't reinvent.

**One existing backend has been modified, and it is worth saying plainly.**
OMI-V1 modified nothing in that package. OMI-V2 deliberately changed
``OpenAICompatBackend``: it gained an explicit closed ``dialect`` parameter
and a ``complete_structured()`` method. An earlier revision of this docstring
still said no existing backend was modified; that sentence was false once
OMI-V2 landed and is withdrawn. The transport boundary is unaffected - one
request field was added to the existing seam, and no transport, client, or
parallel backend was invented. See §16 of
``docs/OPEN_MODEL_INTEGRATION.md``.

What the existing seam provides:

  - ``AgentBackend``  - the ABC every backend implements. **Unchanged**: the
    abstract ``complete()`` signature every backend implements was not
    touched, which is why structured output arrived as a new method rather
    than a new keyword.
  - ``OpenAICompatBackend`` - one class, many provider configurations.
    **Extended by OMI-V2**, as above. ``complete()`` builds a byte-identical
    request to the one it built before, whether or not a dialect is
    configured.
  - ``MockBackend``   - the scripted double, reused as the evaluation stub.
    **Unchanged**, and deliberately not given structured-output support: it
    refuses with ``backend-not-structured-capable``.

What this package adds, because none of it existed:

  - ``capabilities`` - immutable, fail-closed capability descriptors,
    including licence classification and runtime compatibility
  - ``registry``     - an explicit allowlist binding a name to a descriptor
    and an operator-written factory; no endpoint or command may be injected
  - ``routing``      - deterministic eligibility with a single fixed
    no-eligible-backend outcome, explicit escalation reasons, and no silent
    fallback to a remote or cloud service
  - ``structured``   - total, non-disclosing validation of structured output
  - ``structured_exchange`` - OMI-V2. Asks a runtime for schema-constrained
    JSON through the backend's closed request contract, then checks what came
    back with ``structured`` above. It lives here, not in the backend package,
    because the validator lives here and the imports run one way only.
    That check establishes JSON-object and required-key **usability**, not
    schema conformance: nothing in this package compares a response against
    the schema it sent, and ``StructuredExchange.schema_conformance`` is
    closed to the single token ``"unverified"`` so the limit travels with
    every result rather than living only in prose.
  - ``redaction``    - secret scrubbing for operator notes, plus the
    diagnostic record shape that structurally has nowhere to put a prompt
  - ``evaluation``   - a hermetic harness driven entirely by in-process
    doubles, with network entry points actively blocked
  - ``catalogue``    - dated candidate metadata that is deliberately inert

Nothing in this package downloads weights, installs a runtime, starts a
server, contacts an endpoint, or measures a model. Whether a real backend
ever becomes reachable is an operator decision expressed in operator-written
code, reviewed before it merges.

The whole package is standard-library only. It deliberately imports
``scripts.agent_backends.base`` and ``scripts.agent_backends.mock`` directly
rather than the ``scripts.agent_backends`` package root, because that root
lazily imports the ``anthropic`` and ``openai`` SDKs and this layer must stay
importable with no third-party package present.
"""

from scripts.open_model.capabilities import (
    AvailabilityState,
    ExecutionLocality,
    LicenceClass,
    ModelCapabilities,
    ResourceClass,
    RuntimeKind,
    SupportState,
)
from scripts.open_model.catalogue import CATALOGUE
from scripts.open_model.evaluation import (
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
from scripts.open_model.observation import (
    OBSERVATION_LIMITS,
    OBSERVER_SYSTEM_PROMPT,
    EvidenceItem,
    ObservationEnvelope,
    ObservationPlan,
    ObservationResult,
    ReservationDecision,
    ResourceReservation,
    execute_observation,
    new_task_id,
    plan_observation,
    structured_exchange_adapter,
    validate_loopback_endpoint,
)
from scripts.open_model.observation_receipt import (
    DEADLINE_RESULTS,
    ENVELOPE_REFUSALS,
    EXECUTION_REFUSALS,
    MAX_EVIDENCE_ITEMS,
    MAX_REQUIRED_KEYS,
    OBSERVATION_OUTCOMES,
    PLAN_REFUSALS,
    REQUEST_OUTCOMES,
    RESERVATION_ATTESTATIONS,
    RESERVATION_RESULTS,
    RESPONSE_OUTCOMES,
    ObservationReceipt,
    is_canonical_uuid4,
    is_sha256_digest,
    serialize_receipt,
)
from scripts.open_model.redaction import (
    DIAGNOSTIC_EVENTS,
    ESCALATION_REASONS,
    DiagnosticRecord,
    describe_size,
    is_safe_reference,
    is_safe_token,
    redact,
)
from scripts.open_model.registry import (
    BackendFactory,
    BackendRegistry,
    BackendUnavailable,
    LocalityAttestation,
    RegistrationRefused,
    detect_endpoint_host,
)
from scripts.open_model.routing import (
    NO_ELIGIBLE_BACKEND,
    EligibilityVerdict,
    EscalationReason,
    RoutingDecision,
    TaskRequirements,
    evaluate,
    route,
)
from scripts.open_model.structured import (
    StructuredFailure,
    StructuredOutcome,
    validate_structured_output,
)
from scripts.open_model.structured_exchange import (
    ExchangeRefusal,
    StructuredExchange,
    request_structured_json,
)

__all__ = [
    "AvailabilityState",
    "BackendFactory",
    "BackendRegistry",
    "BackendUnavailable",
    "CATALOGUE",
    "DEADLINE_RESULTS",
    "DIAGNOSTIC_EVENTS",
    "DiagnosticRecord",
    "ENVELOPE_REFUSALS",
    "ESCALATION_REASONS",
    "EXECUTION_REFUSALS",
    "EligibilityVerdict",
    "EscalationReason",
    "EvaluationCase",
    "EvaluationRecord",
    "EvidenceItem",
    "ExchangeRefusal",
    "ExecutionLocality",
    "HermeticViolation",
    "LicenceClass",
    "LocalityAttestation",
    "MAX_EVIDENCE_ITEMS",
    "MAX_REQUIRED_KEYS",
    "ModelCapabilities",
    "NO_ELIGIBLE_BACKEND",
    "OBSERVATION_LIMITS",
    "OBSERVATION_OUTCOMES",
    "OBSERVER_SYSTEM_PROMPT",
    "ObservationEnvelope",
    "ObservationPlan",
    "ObservationReceipt",
    "ObservationResult",
    "PLAN_REFUSALS",
    "REQUEST_OUTCOMES",
    "RESERVATION_ATTESTATIONS",
    "RESERVATION_RESULTS",
    "RESPONSE_OUTCOMES",
    "RegistrationRefused",
    "ReservationDecision",
    "ResourceClass",
    "ResourceReservation",
    "RoutingDecision",
    "RuntimeKind",
    "StructuredExchange",
    "StructuredFailure",
    "StructuredOutcome",
    "SupportState",
    "TaskRequirements",
    "describe_size",
    "detect_endpoint_host",
    "evaluate",
    "execute_observation",
    "hermetic_guard",
    "is_canonical_uuid4",
    "is_safe_reference",
    "is_safe_token",
    "is_sha256_digest",
    "new_task_id",
    "plan_observation",
    "redact",
    "register_stub",
    "request_structured_json",
    "route",
    "run_case",
    "run_suite",
    "scripted_stub",
    "serialize_receipt",
    "structured_exchange_adapter",
    "stub_capabilities",
    "validate_loopback_endpoint",
    "validate_structured_output",
]
