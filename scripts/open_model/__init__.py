"""OMI-V1 - provider-neutral open / local model integration foundation.

This package is the capability, eligibility and evaluation layer that sits
**above** the merged agent-backend seam in ``scripts/agent_backends/``. It
does not replace that seam, add a second transport stack, or modify any
existing backend - per the standing boundary in
``docs/LOCAL_MODEL_DEPLOYMENT_INCEPTION.md``: reuse, don't reinvent.

What the existing seam already provides, and this package uses unchanged:

  - ``AgentBackend``  - the ABC every backend implements
  - ``OpenAICompatBackend`` - one class, many provider configurations
  - ``MockBackend``   - the scripted double, reused as the evaluation stub

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
    "DIAGNOSTIC_EVENTS",
    "DiagnosticRecord",
    "ESCALATION_REASONS",
    "EligibilityVerdict",
    "EscalationReason",
    "EvaluationCase",
    "EvaluationRecord",
    "ExchangeRefusal",
    "ExecutionLocality",
    "HermeticViolation",
    "LicenceClass",
    "LocalityAttestation",
    "ModelCapabilities",
    "NO_ELIGIBLE_BACKEND",
    "RegistrationRefused",
    "ResourceClass",
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
    "hermetic_guard",
    "is_safe_reference",
    "is_safe_token",
    "redact",
    "register_stub",
    "request_structured_json",
    "route",
    "run_case",
    "run_suite",
    "scripted_stub",
    "stub_capabilities",
    "validate_structured_output",
]
