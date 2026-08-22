"""OMI-V1 - hermetic evaluation harness. Fakes and stubs only, never a model.

This harness exercises the *integration* - allowlisting, eligibility,
routing, construction, structured-output validation, escalation - against
in-process doubles. It does not measure a model, and it cannot: no weights
are loaded, no runtime is started, no endpoint is contacted, and
``hermetic_guard`` actively blocks the attempt rather than trusting that none
is made.

Nothing this harness produces is a performance result, a benchmark, a
quality comparison, or evidence that any named model works. It is evidence
about this repository's own routing and validation code, and that is all it
should ever be cited as.

Three properties are enforced rather than documented:

- **Hermetic.** ``run_suite`` executes inside ``hermetic_guard``, which
  replaces the socket and urllib entry points with raisers. A double that
  reached for the network would raise ``HermeticViolation``, and that
  exception is deliberately *not* caught into a record - a breach must fail
  the run loudly.

- **No prompt intake.** ``EvaluationCase`` has no prompt, message, or system
  field. The harness sends a fixed synthetic probe defined in this module, so
  no fixture can carry private text and no record can retain it.

- **Deterministic.** Records contain no timestamp, duration, host detail, or
  model output. Running the same suite twice yields records that compare
  equal, which ``tests/test_open_model_evaluation.py`` asserts directly.
"""

from __future__ import annotations

import socket
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Final, Iterable, Iterator, Optional

from scripts.agent_backends.base import AgentBackend, AgentResponse, Message, TextBlock
from scripts.agent_backends.mock import MockBackend
from scripts.open_model.capabilities import ModelCapabilities
from scripts.open_model.redaction import describe_size, is_safe_token
from scripts.open_model.registry import BackendRegistry, BackendUnavailable
from scripts.open_model.routing import (
    NO_ELIGIBLE_BACKEND,
    TaskRequirements,
    route,
)
from scripts.open_model.structured import validate_structured_output


class HermeticViolation(RuntimeError):
    """A double attempted real I/O while the hermetic guard was active."""


PROBE_MESSAGES: Final[tuple[Message, ...]] = (
    Message(role="user", content="omi-v1 synthetic probe"),
)
"""The only conversation this harness ever sends.

Fixed and synthetic on purpose. Because callers cannot supply prompt text,
no evaluation fixture in this repository can come to contain a private
prompt, and no record can retain one.
"""


# -- hermeticity -------------------------------------------------------------


@contextmanager
def hermetic_guard() -> Iterator[None]:
    """Block network entry points for the duration of the block.

    Replaces ``socket.socket``, ``socket.create_connection``,
    ``socket.getaddrinfo`` and ``urllib.request.urlopen`` with callables that
    raise ``HermeticViolation``, and restores the originals in ``finally`` -
    including when the body raises.

    Two honest limits. This is **process-global and not thread-safe**: it
    patches module attributes, so concurrent unrelated work in the same
    interpreter would also be blocked. And it is a guard, not a sandbox - a
    double holding a reference captured before entry, or reaching for the OS
    through another path entirely, would not be stopped. It raises the cost
    of an accidental live call from zero to loud, which is what it is for.
    """

    def _blocked(*_args: Any, **_kwargs: Any) -> Any:
        raise HermeticViolation("network-access-blocked")

    original_socket = socket.socket
    original_create_connection = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo
    original_urlopen = urllib.request.urlopen
    socket.socket = _blocked  # type: ignore[assignment]
    socket.create_connection = _blocked  # type: ignore[assignment]
    socket.getaddrinfo = _blocked  # type: ignore[assignment]
    urllib.request.urlopen = _blocked  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket = original_socket  # type: ignore[assignment]
        socket.create_connection = original_create_connection  # type: ignore[assignment]
        socket.getaddrinfo = original_getaddrinfo  # type: ignore[assignment]
        urllib.request.urlopen = original_urlopen  # type: ignore[assignment]


# -- doubles -----------------------------------------------------------------


STUB_REVISION: Final[str] = "repo-local-double"
"""Revision recorded for in-process doubles.

A double has no upstream checkpoint to pin, so it names itself rather than
borrowing a plausible-looking commit hash. The provenance fields are
populated honestly rather than left blank, because a blank one would block
routing and the doubles must be routable for the harness to exercise
anything.
"""


def stub_capabilities(
    model_id: str,
    *,
    resource_class: str = "light",
    structured_output: str = "supported",
    tool_calling: str = "supported",
    max_context_tokens: int = 8192,
    availability: str = "present",
    locality: str = "local",
) -> ModelCapabilities:
    """Descriptor for an in-process double.

    Declares the ``"in-process-stub"`` runtime rather than borrowing a real
    runtime's name, so a stub can never be mistaken in a record or a log for
    llama.cpp, Ollama, vLLM, or SGLang. The licence is stated as this
    repository's own, because a stub is this repository's own code and no
    third-party terms attach to it.

    Makes no artifact-format claim (``quantisation=""``), so no digest is
    required of it - there is no file to digest.
    """
    return ModelCapabilities(
        model_id=model_id,
        variant_id="in-process-double",
        repository_revision=STUB_REVISION,
        locality=locality,  # type: ignore[arg-type]
        availability=availability,  # type: ignore[arg-type]
        resource_class=resource_class,  # type: ignore[arg-type]
        structured_output=structured_output,  # type: ignore[arg-type]
        tool_calling=tool_calling,  # type: ignore[arg-type]
        max_context_tokens=max_context_tokens,
        max_output_tokens=1024,
        runtimes=("in-process-stub",),
        # A double binds exactly one runtime - itself - so it declares that
        # binding rather than relying on the plural compatibility list. Its
        # version and source are repository-local because the double IS this
        # repository's code; the pinning requirement that would otherwise
        # apply is skipped only because a stub is not artifact-bearing, which
        # is the single narrow exception drawn in `evaluate()`.
        bound_runtime="in-process-stub",
        bound_runtime_version=STUB_REVISION,
        bound_runtime_source_url=(
            "https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen"
        ),
        licence_class="osi-open-source",
        licence_name="repository-local test double",
        licence_source_url="https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen",
        licence_revision=STUB_REVISION,
    )


def register_stub(
    registry: BackendRegistry,
    name: str,
    capabilities: ModelCapabilities,
    factory: Callable[[], AgentBackend],
) -> None:
    """Register an in-process double, supplying the locality attestation.

    A double genuinely does execute in-process, so asserting locality for it
    is honest rather than a convenience. This helper exists so that honesty
    is stated once here instead of being copy-pasted into every fixture,
    where it would gradually stop being read.
    """
    attestation = (
        "operator-asserted" if capabilities.locality == "local" else "not-required"
    )
    registry.register(
        name, capabilities, factory, locality_attestation=attestation
    )


def scripted_stub(payloads: Iterable[str]) -> Callable[[], AgentBackend]:
    """Factory producing a fresh ``MockBackend`` scripted with ``payloads``.

    Reuses the merged ``MockBackend`` rather than introducing a second test
    double, per the standing "reuse, don't reinvent" boundary in
    ``docs/LOCAL_MODEL_DEPLOYMENT_INCEPTION.md``. A *fresh* backend per call
    keeps repeated runs independent, which is what makes the determinism
    property meaningful rather than accidental.
    """
    texts = tuple(payload for payload in payloads if type(payload) is str)

    def factory() -> AgentBackend:
        return MockBackend(
            [
                AgentResponse.from_content([TextBlock(text=text)])
                for text in texts
            ]
        )

    return factory


# -- cases and records -------------------------------------------------------


@dataclass(frozen=True)
class EvaluationCase:
    """One synthetic acceptance case. Carries requirements, never content.

    ``case_id`` must be a safe token - bounded, closed character class, and
    unchanged by the secret matcher. It is rejected with ``ValueError``
    rather than normalized, because an unusable case id is a fixture-
    authoring mistake that should surface at the point it was written, not a
    hostile input to be absorbed quietly.

    Corrected after audit: ``case_id`` was previously free text copied
    verbatim into every record, so a careless fixture could have carried a
    secret straight into a stored result.
    """

    case_id: str
    requirements: TaskRequirements
    expected_outcome: str = "selected"
    expected_backend: Optional[str] = None
    required_keys: tuple[str, ...] = ()
    expected_structured_failure: str = ""
    expected_construction_refused: str = ""

    def __post_init__(self) -> None:
        if not is_safe_token(self.case_id):
            raise ValueError(
                "case_id must be a safe token: bounded, "
                "[A-Za-z0-9][A-Za-z0-9._-]*, and not secret-shaped"
            )


@dataclass(frozen=True)
class EvaluationRecord:
    """What one case did. Comparable, and free of content, clocks, and hosts.

    Every field is a stable code, an allowlist name, a caller-supplied key
    name, or a size. There is no response text, no duration, no timestamp, no
    path, and no environment value - so a record is safe to write to a
    fixture file and safe to compare across runs.
    """

    case_id: str
    outcome: str
    selected: str
    escalation: tuple[str, ...]
    construction_refused: str
    structured_failure: str
    missing_key_indices: tuple[int, ...]
    response_size: str
    passed: bool


def run_case(registry: BackendRegistry, case: EvaluationCase) -> EvaluationRecord:
    """Route one case, construct the winner if any, validate what it returned.

    ``HermeticViolation`` is intentionally not caught: a double that reaches
    the network is a defect in the harness, not a result to record.
    """
    decision = route(registry, case.requirements)

    if decision.outcome == NO_ELIGIBLE_BACKEND:
        return EvaluationRecord(
            case_id=case.case_id,
            outcome=NO_ELIGIBLE_BACKEND,
            selected="",
            escalation=tuple(decision.escalation),
            construction_refused="",
            structured_failure="",
            missing_key_indices=(),
            response_size="chars=unknown",
            passed=case.expected_outcome == NO_ELIGIBLE_BACKEND,
        )

    selected = decision.selected or ""
    try:
        backend = registry.create(selected)
    except BackendUnavailable as refusal:
        return EvaluationRecord(
            case_id=case.case_id,
            outcome="selected",
            selected=selected,
            escalation=(),
            construction_refused=refusal.reason,
            structured_failure="",
            missing_key_indices=(),
            response_size="chars=unknown",
            passed=case.expected_construction_refused == refusal.reason,
        )

    response = backend.complete(list(PROBE_MESSAGES), [])
    text = response.text or ""
    outcome = validate_structured_output(text, required_keys=case.required_keys)

    failure = outcome.failure or ""
    expected_backend_ok = (
        case.expected_backend is None or case.expected_backend == selected
    )
    return EvaluationRecord(
        case_id=case.case_id,
        outcome="selected",
        selected=selected,
        escalation=(),
        construction_refused="",
        structured_failure=failure,
        missing_key_indices=tuple(outcome.missing_key_indices),
        # The size of the response, never the response.
        response_size=describe_size(text),
        passed=(
            case.expected_outcome == "selected"
            and expected_backend_ok
            and failure == case.expected_structured_failure
            and case.expected_construction_refused == ""
        ),
    )


def run_suite(
    registry: BackendRegistry,
    cases: Iterable[EvaluationCase],
) -> tuple[EvaluationRecord, ...]:
    """Run every case in order, inside the hermetic guard."""
    with hermetic_guard():
        return tuple(run_case(registry, case) for case in cases)


__all__ = [
    "EvaluationCase",
    "EvaluationRecord",
    "HermeticViolation",
    "PROBE_MESSAGES",
    "STUB_REVISION",
    "hermetic_guard",
    "register_stub",
    "run_case",
    "run_suite",
    "scripted_stub",
    "stub_capabilities",
]
