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
from scripts.open_model.redaction import describe_size
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
    """
    return ModelCapabilities(
        model_id=model_id,
        locality=locality,  # type: ignore[arg-type]
        availability=availability,  # type: ignore[arg-type]
        resource_class=resource_class,  # type: ignore[arg-type]
        structured_output=structured_output,  # type: ignore[arg-type]
        tool_calling=tool_calling,  # type: ignore[arg-type]
        max_context_tokens=max_context_tokens,
        max_output_tokens=1024,
        runtimes=("in-process-stub",),
        licence_class="osi-open-source",
        licence_name="repository-local test double",
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
    """One synthetic acceptance case. Carries requirements, never content."""

    case_id: str
    requirements: TaskRequirements
    expected_outcome: str = "selected"
    expected_backend: Optional[str] = None
    required_keys: tuple[str, ...] = ()
    expected_structured_failure: str = ""
    expected_construction_refused: str = ""


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
    missing_keys: tuple[str, ...]
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
            missing_keys=(),
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
            missing_keys=(),
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
        missing_keys=tuple(outcome.missing_keys),
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
    "hermetic_guard",
    "run_case",
    "run_suite",
    "scripted_stub",
    "stub_capabilities",
]
