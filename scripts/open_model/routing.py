"""OMI-V1 - deterministic eligibility and routing over an allowlisted registry.

Two guarantees hold over everything in this module.

**Determinism.** Routing reads no clock, draws no randomness, consults no
environment, and performs no I/O. Ordered output is never derived from set
iteration. The same registry and the same requirements always produce an
identical ``RoutingDecision``, including the order of its escalation reasons.

**Fail-closed.** Eligibility is a conjunction of positive checks. Every
unknown is a blocking reason with its own escalation code - never a pass.
When nothing qualifies, the result is the fixed ``NO_ELIGIBLE_BACKEND``
outcome carrying the reasons why, not a fallback and not an exception.

**What eligibility does NOT establish.** This layer reads *descriptors*. It
refuses a candidate whose descriptor says ``remote`` under a local-only task,
and that is the whole of its locality guarantee. It does not and cannot
establish where a backend will actually execute: the descriptor is an
assertion, vouched for by an operator attestation recorded at the
registration site, and a factory that constructs an opaque backend - one
exposing no inspectable endpoint - remains undetectable from here.
``scripts.open_model.registry`` adds a best-effort non-loopback check at
construction time, which catches the conventional case and is explicitly not
universal. Any statement that a local-only task *cannot* reach a remote
service is a statement about descriptors, not about the world.

**Disclosure.** ``TaskRequirements`` carries no prompt, no message, no system
text, no user identifier and no free text of any kind - only booleans,
integers, and vocabulary tokens. The routing layer is therefore structurally
incapable of logging, caching, or leaking prompt content: it never receives
any. ``tests/test_open_model_routing.py`` enforces that field set so the
property cannot be eroded by a later edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal, Optional

from scripts.open_model.capabilities import (
    LicenceClass,
    ModelCapabilities,
    RuntimeKind,
)
from scripts.open_model.redaction import ESCALATION_REASONS
from scripts.open_model.registry import BackendRegistry


# -- vocabulary --------------------------------------------------------------

EscalationReason = Literal[
    "no-backend-registered",
    "requirements-invalid",
    "model-id-missing",
    "backend-unavailable",
    "availability-unknown",
    "locality-not-local",
    "locality-unknown",
    "structured-output-unsupported",
    "structured-output-unknown",
    "tool-calling-unsupported",
    "tool-calling-unknown",
    "context-below-minimum",
    "context-unknown",
    "licence-not-allowed",
    "licence-unknown",
    "licence-source-unpinned",
    "runtime-not-allowed",
    "runtime-unknown",
    "variant-unspecified",
    "repository-revision-unpinned",
    "artifact-digest-missing",
    "artifact-unpinned",
    "repository-revision-not-immutable",
    "provenance-unpinned",
    "bound-runtime-unspecified",
    "bound-runtime-not-allowed",
    "bound-runtime-not-declared",
    "bound-runtime-unpinned",
]
"""Why a candidate was refused, or why the whole decision escalated.

These codes are the entire vocabulary a caller may act on. They contain no
operator input, so an escalation record is safe to log verbatim.
"""

Outcome = Literal["selected", "no-eligible-backend"]

NO_ELIGIBLE_BACKEND: Final[str] = "no-eligible-backend"
"""The single fixed outcome token for "nothing qualified".

There is exactly one such outcome. It is not an error, not ``None`` returned
from a happy path, and not a degraded selection: callers branch on it
explicitly, which is what makes the absence of a silent fallback visible in
calling code rather than buried here.
"""

_DEFAULT_LICENCE_CLASSES: Final[tuple[str, ...]] = ("osi-open-source",)

_ALLOWED_LICENCE_INPUTS: Final[frozenset[str]] = frozenset(
    {
        "osi-open-source",
        "open-weight-restricted",
        "source-available",
        "proprietary-service",
    }
)
"""Licence classes a task may allow.

``"unknown"`` is deliberately absent, so asking to allow it is *malformed*
rather than silently stripped: a licence whose class was never established
can never be allow-listed, and a caller who tries is told so instead of
receiving a quietly different constraint. An unresolved licence is a question
for a human, not a routing option.
"""

_ALLOWED_RUNTIME_INPUTS: Final[frozenset[str]] = frozenset(
    {
        "llama-cpp",
        "ollama",
        "vllm",
        "sglang",
        "tensorrt-llm",
        "in-process-stub",
    }
)
"""Runtimes a task may allow. ``"unknown"`` is malformed for the same reason."""

_MAX_ALLOWED_ITEMS: Final[int] = 16


def _exact_bool(value: Any, fallback: bool) -> bool:
    """Keep ``value`` only when it is exactly built-in ``bool``.

    ``bool`` cannot be subclassed, so ``type(value) is bool`` is exact. Every
    other shape becomes ``fallback`` without calling ``bool()``, equality,
    hashing, or any supplied hook. For a *requirement* the conservative
    fallback is the stricter reading, so a malformed value tightens routing
    rather than loosening it.
    """
    if type(value) is bool:
        return value
    return fallback


def _exact_nonneg_int(value: Any) -> int:
    """Keep ``value`` only when exactly built-in ``int`` and non-negative.

    ``type(value) is int`` excludes ``bool``. Everything else becomes ``0``,
    which is safe here because an undeclared candidate context is blocking on
    its own regardless of what the task asked for.
    """
    if type(value) is int and value >= 0:
        return value
    return 0


def _validated_token_tuple(
    value: Any,
    *,
    allowed: frozenset[str],
) -> tuple[tuple[str, ...], bool]:
    """Validate an allow-tuple. Returns ``(normalized, ok)``.

    ``ok`` is ``False`` - meaning the whole requirement set is malformed and
    must block - when the value is not exactly ``tuple``/``list``, exceeds
    ``_MAX_ALLOWED_ITEMS``, or contains **any** element that is not an exact
    ``str`` member of ``allowed``. ``"unknown"`` is not a member of either
    vocabulary, so asking to allow it is malformed rather than ignorable.

    Corrected after audit. The previous version *filtered* unrecognised
    elements out, which was a fail-open in the worst possible place: a caller
    who wrote ``allowed_runtimes=("ollama-v2",)`` - a typo, a stale name, a
    wrong type - had their constraint silently reduced to the empty tuple,
    and an empty tuple means "the task does not constrain the runtime". A
    narrowing instruction became a widening one. Constraints are now taken
    literally or refused; they are never quietly reinterpreted.

    De-duplication is still silent, because a repeated element expresses the
    same constraint and changes nothing.
    """
    if type(value) is not tuple and type(value) is not list:
        return ((), False)
    if len(value) > _MAX_ALLOWED_ITEMS:
        return ((), False)
    kept: list[str] = []
    for element in value:
        if type(element) is not str or element not in allowed:
            return ((), False)
        if element in kept:
            continue
        kept.append(element)
    return (tuple(kept), True)


# -- what the task needs -----------------------------------------------------


@dataclass(frozen=True)
class TaskRequirements:
    """What a unit of work needs from a backend. **Never what it says.**

    Every field is a boolean, a non-negative integer, or a token from a
    closed vocabulary. There is deliberately no prompt, message list, system
    text, tool payload, user id, tenant id, or free-text field: the router
    cannot disclose what it is never given.

    Defaults are the strict reading:

    - ``require_local=True``  - cloud execution must be asked for explicitly.
    - ``allowed_licence_classes=("osi-open-source",)`` - the most permissive
      licence class is the only one accepted until an operator widens it.
    - ``allowed_runtimes=()``  - the *task* declines to constrain the runtime.
      This does not weaken anything: a *candidate* must still declare at
      least one known runtime or it is refused with ``runtime-unknown``.

    An explicitly empty ``allowed_licence_classes`` is honoured as written
    and blocks every candidate. That is the correct fail-closed reading of
    "no licence class is acceptable", not a configuration error to repair.
    """

    require_local: bool = True
    needs_structured_output: bool = False
    needs_tool_calling: bool = False
    min_context_tokens: int = 0
    allowed_licence_classes: tuple[LicenceClass, ...] = _DEFAULT_LICENCE_CLASSES
    allowed_runtimes: tuple[RuntimeKind, ...] = ()
    malformed_fields: tuple[str, ...] = ()
    """Names of fields whose supplied value was not the declared shape.

    Always recomputed at construction; any value supplied by a caller is
    discarded. Non-empty makes **every** candidate ineligible via the
    ``requirements-invalid`` reason.

    Corrected after audit: a malformed ``min_context_tokens`` - a negative
    number, a float, a string - previously normalized to ``0``, which reads
    as "no minimum" and would let a one-token backend satisfy a requirement
    that had asked for 32k. Silently relaxing a demand is the one direction
    normalization must never take, so a malformed requirement now refuses to
    route at all rather than routing on a weaker demand than the caller
    wrote.
    """

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        supplied_local = self.require_local
        supplied_structured = self.needs_structured_output
        supplied_tools = self.needs_tool_calling
        supplied_context = self.min_context_tokens

        set_(self, "require_local", _exact_bool(self.require_local, True))
        # A malformed capability demand becomes True: demanding more is the
        # conservative direction for a requirement.
        set_(
            self,
            "needs_structured_output",
            _exact_bool(self.needs_structured_output, True),
        )
        set_(self, "needs_tool_calling", _exact_bool(self.needs_tool_calling, True))
        set_(self, "min_context_tokens", _exact_nonneg_int(self.min_context_tokens))
        licences, licences_ok = _validated_token_tuple(
            self.allowed_licence_classes, allowed=_ALLOWED_LICENCE_INPUTS
        )
        set_(
            self,
            "allowed_licence_classes",
            licences if licences_ok else _DEFAULT_LICENCE_CLASSES,
        )
        runtimes, runtimes_ok = _validated_token_tuple(
            self.allowed_runtimes, allowed=_ALLOWED_RUNTIME_INPUTS
        )
        set_(self, "allowed_runtimes", runtimes)

        # Record every field whose supplied value was not the declared shape.
        # Compared by exact type first so no hostile __eq__ participates.
        malformed: list[str] = []
        if type(supplied_local) is not bool:
            malformed.append("require_local")
        if type(supplied_structured) is not bool:
            malformed.append("needs_structured_output")
        if type(supplied_tools) is not bool:
            malformed.append("needs_tool_calling")
        if type(supplied_context) is not int or supplied_context < 0:
            malformed.append("min_context_tokens")
        if not licences_ok:
            malformed.append("allowed_licence_classes")
        if not runtimes_ok:
            malformed.append("allowed_runtimes")
        set_(self, "malformed_fields", tuple(malformed))


# -- verdicts ----------------------------------------------------------------


@dataclass(frozen=True)
class EligibilityVerdict:
    """One candidate, judged. ``reasons`` is empty exactly when eligible."""

    name: str
    eligible: bool
    reasons: tuple[EscalationReason, ...] = ()


@dataclass(frozen=True)
class RoutingDecision:
    """The result of routing. Immutable, comparable, and free of operator text.

    ``outcome`` is the branch a caller must switch on. When it is
    ``NO_ELIGIBLE_BACKEND``, ``selected`` is always ``None`` - enforced here,
    not merely intended - and ``escalation`` explains why, in a fixed order.
    """

    outcome: Outcome
    selected: Optional[str]
    verdicts: tuple[EligibilityVerdict, ...]
    escalation: tuple[EscalationReason, ...]

    def __post_init__(self) -> None:
        if self.outcome == NO_ELIGIBLE_BACKEND and self.selected is not None:
            raise ValueError("no-eligible-backend decision cannot carry a selection")
        if self.outcome == "selected" and type(self.selected) is not str:
            raise ValueError("selected decision must carry a backend name")

    @property
    def has_backend(self) -> bool:
        """True only for a real selection. Callers branch on this or ``outcome``."""
        return self.outcome == "selected"


# -- eligibility -------------------------------------------------------------


def evaluate(
    capabilities: ModelCapabilities,
    requirements: TaskRequirements,
) -> tuple[EscalationReason, ...]:
    """Blocking reasons for one candidate, in fixed evaluation order.

    Pure and total: every check is a positive assertion about a normalized
    field, so no input shape can make this raise, and an empty result means
    "nothing blocked it" rather than "nothing was checked". All blocking
    reasons are collected rather than short-circuiting on the first, because
    an operator fixing a candidate needs the whole list, not one at a time.
    """
    reasons: list[EscalationReason] = []

    # A requirement set that was not the declared shape blocks everything.
    # Routing on a silently-relaxed demand is worse than not routing.
    if requirements.malformed_fields:
        reasons.append("requirements-invalid")

    if not capabilities.model_id:
        reasons.append("model-id-missing")

    # Provenance. An artifact nobody can identify or re-fetch byte-for-byte
    # is not a candidate; it is a rumour about a candidate.
    if not capabilities.variant_id:
        reasons.append("variant-unspecified")
    if not capabilities.repository_revision:
        reasons.append("repository-revision-unpinned")
    if capabilities.artifact_path and not capabilities.artifact_digest:
        reasons.append("artifact-digest-missing")
    # Every artifact-bearing variant must be byte-pinned, whether or not it
    # is quantised: a BF16 or safetensors build is as much a file as a GGUF
    # one. Satisfied by a named file plus its digest, or by a full commit id
    # covering the whole tree (the only coherent pin for a sharded variant).
    if capabilities.is_artifact_bearing() and not capabilities.is_byte_pinned():
        reasons.append("artifact-unpinned")

    # Provenance and licence evidence must be immutable for a real artifact.
    # The single, narrow exception is the repository-local in-process double,
    # which is this repository own code: it has no upstream repository, no
    # licence page, and no serving runtime to pin. `is_artifact_bearing()`
    # draws that line, and nothing else widens it.
    if capabilities.is_artifact_bearing():
        if not capabilities.has_immutable_revision():
            reasons.append("repository-revision-not-immutable")
        if not capabilities.has_pinned_provenance():
            reasons.append("provenance-unpinned")
        if (
            not capabilities.has_pinned_licence()
            and "licence-source-unpinned" not in reasons
        ):
            reasons.append("licence-source-unpinned")
    if not capabilities.licence_source_url or not capabilities.licence_revision:
        reasons.append("licence-source-unpinned")

    if capabilities.availability == "absent":
        reasons.append("backend-unavailable")
    elif capabilities.availability != "present":
        reasons.append("availability-unknown")

    if requirements.require_local:
        if capabilities.locality == "remote":
            reasons.append("locality-not-local")
        elif capabilities.locality != "local":
            reasons.append("locality-unknown")

    if requirements.needs_structured_output:
        if capabilities.structured_output == "unsupported":
            reasons.append("structured-output-unsupported")
        elif capabilities.structured_output != "supported":
            reasons.append("structured-output-unknown")

    if requirements.needs_tool_calling:
        if capabilities.tool_calling == "unsupported":
            reasons.append("tool-calling-unsupported")
        elif capabilities.tool_calling != "supported":
            reasons.append("tool-calling-unknown")

    # An undeclared context is blocking even when the task asks for none: a
    # candidate that cannot say how much context it has is a candidate we
    # know nothing about.
    if capabilities.max_context_tokens == 0:
        reasons.append("context-unknown")
    elif capabilities.max_context_tokens < requirements.min_context_tokens:
        reasons.append("context-below-minimum")

    if capabilities.licence_class == "unknown":
        reasons.append("licence-unknown")
    elif capabilities.licence_class not in requirements.allowed_licence_classes:
        reasons.append("licence-not-allowed")

    known_runtimes = tuple(r for r in capabilities.runtimes if r != "unknown")
    if not known_runtimes:
        reasons.append("runtime-unknown")
    elif requirements.allowed_runtimes:
        if not any(r in requirements.allowed_runtimes for r in known_runtimes):
            reasons.append("runtime-not-allowed")

    # `runtimes` is a plural COMPATIBILITY list - what a vendor claims a model
    # can run under. It is not a statement about what the operator factory
    # actually constructs. A narrowed runtime requirement is therefore judged
    # on `bound_runtime`, the single runtime that will really serve, and a
    # compatibility list alone can never satisfy one.
    if capabilities.bound_runtime and capabilities.bound_runtime not in known_runtimes:
        reasons.append("bound-runtime-not-declared")
    if requirements.allowed_runtimes:
        if not capabilities.bound_runtime:
            reasons.append("bound-runtime-unspecified")
        elif capabilities.bound_runtime not in requirements.allowed_runtimes:
            reasons.append("bound-runtime-not-allowed")
    if (
        capabilities.is_artifact_bearing()
        and capabilities.bound_runtime
        and not capabilities.has_pinned_runtime_binding()
    ):
        reasons.append("bound-runtime-unpinned")

    return tuple(reasons)


def _dedupe(reasons: list[EscalationReason]) -> tuple[EscalationReason, ...]:
    """First-occurrence-preserving de-duplication. No set iteration."""
    seen: list[EscalationReason] = []
    for reason in reasons:
        if reason not in seen:
            seen.append(reason)
    return tuple(seen)


def route(
    registry: BackendRegistry,
    requirements: TaskRequirements,
) -> RoutingDecision:
    """Choose at most one backend, deterministically, or escalate.

    Selection order among eligible candidates is
    ``(declared resource class, model id, registration index)`` - lighter
    declared footprint first, so a task that a small local model can serve is
    not handed to a large one. Nothing in that key is measured, timed, or
    randomised.

    The winner is re-evaluated after selection. That second pass is redundant
    by construction and deliberately kept: it means a future edit to the
    selection logic cannot produce a selection that the eligibility rules
    would have refused, and in particular cannot select a candidate whose
    **descriptor** declares a remote locality under a ``require_local`` task.
    That is a guarantee about the descriptor, not about the backend the
    factory will build - see the module docstring.
    """
    # Checked before the registry so a malformed requirement is always
    # reported as such, rather than being masked by an empty registry.
    if requirements.malformed_fields:
        return RoutingDecision(
            outcome=NO_ELIGIBLE_BACKEND,
            selected=None,
            verdicts=(),
            escalation=("requirements-invalid",),
        )

    names = registry.names()
    if not names:
        return RoutingDecision(
            outcome=NO_ELIGIBLE_BACKEND,
            selected=None,
            verdicts=(),
            escalation=("no-backend-registered",),
        )

    verdicts: list[EligibilityVerdict] = []
    eligible: list[tuple[tuple[int, str], int, str]] = []
    for index, name in enumerate(names):
        capabilities = registry.capabilities_for(name)
        reasons = evaluate(capabilities, requirements)
        verdicts.append(
            EligibilityVerdict(name=name, eligible=not reasons, reasons=reasons)
        )
        if not reasons:
            eligible.append((capabilities.preference_key(), index, name))

    if not eligible:
        collected: list[EscalationReason] = []
        for verdict in verdicts:
            collected.extend(verdict.reasons)
        return RoutingDecision(
            outcome=NO_ELIGIBLE_BACKEND,
            selected=None,
            verdicts=tuple(verdicts),
            escalation=_dedupe(collected),
        )

    eligible.sort()
    winner = eligible[0][2]

    # Defence in depth: re-check the winner against the same rules.
    winner_capabilities = registry.capabilities_for(winner)
    residual = evaluate(winner_capabilities, requirements)
    if residual:
        return RoutingDecision(
            outcome=NO_ELIGIBLE_BACKEND,
            selected=None,
            verdicts=tuple(verdicts),
            escalation=_dedupe(list(residual)),
        )
    # Stated separately from the loop above so the "never select a
    # remote-DECLARING descriptor for a local-only task" rule is legible as
    # its own guard. It binds the descriptor, not the constructed backend.
    if requirements.require_local and winner_capabilities.locality != "local":
        return RoutingDecision(
            outcome=NO_ELIGIBLE_BACKEND,
            selected=None,
            verdicts=tuple(verdicts),
            escalation=("locality-not-local",),
        )

    return RoutingDecision(
        outcome="selected",
        selected=winner,
        verdicts=tuple(verdicts),
        escalation=(),
    )


__all__ = [
    "ESCALATION_REASONS",
    "EligibilityVerdict",
    "EscalationReason",
    "NO_ELIGIBLE_BACKEND",
    "Outcome",
    "RoutingDecision",
    "TaskRequirements",
    "evaluate",
    "route",
]
