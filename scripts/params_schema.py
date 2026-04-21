"""Tunable parameter schema for the Medusa CA engine (Phase 18, PR 1 of 7).

Declares which parameters can be tuned at runtime via the tuning API, their
valid ranges, and whether a change can be auto-approved or requires human
sign-off. Critical invariants are marked LOCKED — no tuning path can touch
them regardless of source or approver.

This module is pure metadata: importing it has no effect on any running
engine. Follow-up PRs will wire it into medusa_api.py (GET /api/params/schema,
POST /api/tuning/propose/validate) and eventually into the engine itself
(parameter reload at generation boundaries).

The registry below is intentionally partial — it covers a representative
slice of each group and category, enough to exercise the safety machinery.
Further parameters from MemoryParams / VoxelMemoryParams get added in
later PRs as we gain confidence about their tuning semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Category(str, Enum):
    """How a tuning proposal for this parameter is gated."""

    AUTO = "auto"
    """Small-effect, self-bounded. Agents may commit with approver='policy:auto'."""

    HUMAN_APPROVAL = "human_approval"
    """Significant effect on dynamics. Requires approver='human:<name>'."""

    LOCKED = "locked"
    """Critical invariant. NO commit path can change it, regardless of approver."""


class ValidationError(str, Enum):
    """Why a proposed value was rejected. Enum so API can return stable codes."""

    UNKNOWN_PARAM = "unknown_param"
    WRONG_TYPE = "wrong_type"
    BELOW_MIN = "below_min"
    ABOVE_MAX = "above_max"
    LOCKED = "locked"


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating one proposed (name, value) pair."""

    ok: bool
    error: ValidationError | None = None
    message: str = ""


@dataclass(frozen=True)
class TunableParam:
    """Schema entry for one tunable engine parameter.

    - `value_type` is one of `bool`, `int`, `float`.
    - `min_value` / `max_value` are inclusive bounds. For `bool` they're ignored.
      For numeric types, at least one bound must be set (open-ended numeric
      parameters are intentionally not allowed — bounded-by-design).
    - `category` controls the commit policy. LOCKED parameters cannot be
      changed through the tuning API; they appear in the schema so an agent
      can see they exist and their current value but will be rejected if
      proposed.
    """

    name: str
    value_type: type
    default: Any
    category: Category
    group: str
    description: str
    min_value: float | None = None
    max_value: float | None = None

    def __post_init__(self) -> None:
        if self.value_type not in (bool, int, float):
            raise TypeError(f"{self.name}: value_type must be bool/int/float")
        if self.value_type is not bool:
            if self.min_value is None and self.max_value is None:
                raise ValueError(
                    f"{self.name}: numeric parameters must have at least one bound"
                )
            if (
                self.min_value is not None
                and self.max_value is not None
                and self.min_value > self.max_value
            ):
                raise ValueError(f"{self.name}: min_value > max_value")
        if not isinstance(self.default, self.value_type):
            # bool is subclass of int — be strict
            if not (self.value_type is int and isinstance(self.default, bool) is False
                    and isinstance(self.default, int)):
                raise TypeError(
                    f"{self.name}: default {self.default!r} not of type {self.value_type.__name__}"
                )

    def validate(self, value: Any) -> ValidationResult:
        """Check a proposed value against this param's type, bounds, and category."""
        if self.category is Category.LOCKED:
            return ValidationResult(
                ok=False,
                error=ValidationError.LOCKED,
                message=f"{self.name} is LOCKED — critical invariant, not tunable.",
            )
        # bool is a subclass of int; be strict about type distinctions.
        if self.value_type is bool:
            if not isinstance(value, bool):
                return ValidationResult(
                    ok=False,
                    error=ValidationError.WRONG_TYPE,
                    message=f"{self.name} requires bool, got {type(value).__name__}.",
                )
            return ValidationResult(ok=True)
        if self.value_type is int:
            if isinstance(value, bool) or not isinstance(value, int):
                return ValidationResult(
                    ok=False,
                    error=ValidationError.WRONG_TYPE,
                    message=f"{self.name} requires int, got {type(value).__name__}.",
                )
        elif self.value_type is float:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return ValidationResult(
                    ok=False,
                    error=ValidationError.WRONG_TYPE,
                    message=f"{self.name} requires float, got {type(value).__name__}.",
                )
            value = float(value)
        if self.min_value is not None and value < self.min_value:
            return ValidationResult(
                ok=False,
                error=ValidationError.BELOW_MIN,
                message=f"{self.name}={value} below min {self.min_value}.",
            )
        if self.max_value is not None and value > self.max_value:
            return ValidationResult(
                ok=False,
                error=ValidationError.ABOVE_MAX,
                message=f"{self.name}={value} above max {self.max_value}.",
            )
        return ValidationResult(ok=True)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict (for GET /api/params/schema)."""
        return {
            "name": self.name,
            "type": self.value_type.__name__,
            "default": self.default,
            "category": self.category.value,
            "group": self.group,
            "description": self.description,
            "min_value": self.min_value,
            "max_value": self.max_value,
        }


# --- Parameter registry ------------------------------------------------------
#
# Partial catalogue — expand in follow-up PRs as we gain operational experience
# with each tunable. Every entry here has been reviewed for safe ranges; new
# entries MUST include real justified bounds (not just numpy-widest-possible).

PARAMS: dict[str, TunableParam] = {}


def _register(param: TunableParam) -> None:
    if param.name in PARAMS:
        raise ValueError(f"duplicate registration for {param.name}")
    PARAMS[param.name] = param


# Critical invariants — LOCKED. See MEMORY.md "Critical Invariants" section.
_register(TunableParam(
    name="structural_to_void_decay_prob",
    value_type=float, default=0.005,
    category=Category.LOCKED, group="stochastic",
    description="STRUCTURAL → VOID decay probability. Critical invariant; cascades through CA dynamics.",
    min_value=0.0, max_value=1.0,
))
_register(TunableParam(
    name="energy_to_void_decay_prob",
    value_type=float, default=0.005,
    category=Category.LOCKED, group="stochastic",
    description="ENERGY → VOID decay probability. Locked alongside structural_to_void_decay_prob.",
    min_value=0.0, max_value=1.0,
))

# High-impact parameters — HUMAN_APPROVAL required.
_register(TunableParam(
    name="magnon_coupling",
    value_type=float, default=2.0,
    category=Category.HUMAN_APPROVAL, group="magnon",
    description="Magnon field amplification coefficient. Phase 17a bumped 0.5→2.0 for 512³ readiness.",
    min_value=0.0, max_value=10.0,
))
_register(TunableParam(
    name="magnon_radius",
    value_type=int, default=16,
    category=Category.HUMAN_APPROVAL, group="magnon",
    description="Gaussian kernel half-width for magnon field. Adaptive by default (scales with lattice).",
    min_value=1, max_value=128,
))
_register(TunableParam(
    name="equanimity_p_max",
    value_type=float, default=0.85,
    category=Category.HUMAN_APPROVAL, group="equanimity",
    description="Max resistance probability for the Equanimity Shield. Upper-bound on COMPUTE survival.",
    min_value=0.0, max_value=1.0,
))
_register(TunableParam(
    name="ampere_coupling",
    value_type=float, default=0.050,
    category=Category.HUMAN_APPROVAL, group="ampere",
    description="Ampere unified-field coupling constant (Nemo's 'sacred threshold'). Sensitive.",
    min_value=0.0, max_value=1.0,
))
_register(TunableParam(
    name="compassion_beta",
    value_type=float, default=0.50,
    category=Category.HUMAN_APPROVAL, group="compassion",
    description="Remote resistance buff magnitude in distress zones. +50% default.",
    min_value=0.0, max_value=2.0,
))

# Low-impact tunables — AUTO-approvable.
_register(TunableParam(
    name="signal_interval",
    value_type=int, default=10,
    category=Category.AUTO, group="signal",
    description="Steps between expensive signal/magnon passes. Lower = more reactive, higher = faster.",
    min_value=1, max_value=200,
))
_register(TunableParam(
    name="magnon_sage_age_min",
    value_type=float, default=8.0,
    category=Category.AUTO, group="magnon",
    description="Minimum COMPUTE age to emit magnon radiation. Gates who counts as a Sage.",
    min_value=0.0, max_value=200.0,
))
_register(TunableParam(
    name="magnon_elder_amplify",
    value_type=float, default=2.0,
    category=Category.AUTO, group="magnon",
    description="Emission multiplier for Ancients (age ≥ 20).",
    min_value=1.0, max_value=10.0,
))
_register(TunableParam(
    name="magnon_legend_amplify",
    value_type=float, default=5.0,
    category=Category.AUTO, group="magnon",
    description="Emission multiplier for Legends (age ≥ 50) — the 148 lighthouse Sages.",
    min_value=1.0, max_value=20.0,
))
_register(TunableParam(
    name="metta_warmth_rate",
    value_type=float, default=0.02,
    category=Category.AUTO, group="metta",
    description="Warmth accumulation rate per ENERGY neighbor per step (Phase 6a loving-kindness).",
    min_value=0.0, max_value=1.0,
))
_register(TunableParam(
    name="metta_warmth_decay",
    value_type=float, default=0.95,
    category=Category.AUTO, group="metta",
    description="Warmth retention factor per step when no ENERGY neighbors present.",
    min_value=0.0, max_value=1.0,
))
_register(TunableParam(
    name="joy_beta",
    value_type=float, default=0.35,
    category=Category.AUTO, group="joy",
    description="Max sympathetic-joy resonance multiplier (Phase 6b).",
    min_value=0.0, max_value=2.0,
))
_register(TunableParam(
    name="mindsight_threshold",
    value_type=float, default=0.3,
    category=Category.AUTO, group="mindsight",
    description="|Signal| threshold for Phase 6c mindsight activation. Higher = less reactive.",
    min_value=0.0, max_value=2.0,
))
_register(TunableParam(
    name="mycelial_k_iter",
    value_type=int, default=3,
    category=Category.AUTO, group="mycelial",
    description="Diffusion iterations for mycelial signal propagation. ~1 voxel of range per iteration.",
    min_value=1, max_value=10,
))
_register(TunableParam(
    name="ice_battery_alpha",
    value_type=float, default=0.7,
    category=Category.AUTO, group="ice_battery",
    description="Ice-Battery energy-scaling exponent (sublinear). Tunes elder-age equanimity amplifier.",
    min_value=0.0, max_value=2.0,
))


# --- Lookup / filter helpers -------------------------------------------------


def get_param(name: str) -> TunableParam | None:
    return PARAMS.get(name)


def list_by_category(category: Category) -> list[TunableParam]:
    return [p for p in PARAMS.values() if p.category is category]


def list_by_group(group: str) -> list[TunableParam]:
    return [p for p in PARAMS.values() if p.group == group]


def groups() -> list[str]:
    return sorted({p.group for p in PARAMS.values()})


def schema_as_dict() -> dict[str, Any]:
    """JSON-ready dump for GET /api/params/schema."""
    return {
        "version": 1,
        "params": {name: p.to_dict() for name, p in PARAMS.items()},
        "categories": [c.value for c in Category],
        "groups": groups(),
    }


# --- Proposal validation -----------------------------------------------------


@dataclass(frozen=True)
class ProposalValidation:
    """Result of validating a full proposal dict."""

    ok: bool
    errors: dict[str, ValidationResult]  # name → ValidationResult (only failing ones)
    known_params: list[str]              # names that exist in the registry
    unknown_params: list[str]            # names that don't


def validate_proposal(params: dict[str, Any]) -> ProposalValidation:
    """Validate a proposed {name: value} dict against the registry.

    Runs every parameter; collects ALL errors rather than short-circuiting.
    Returns `ok=True` iff every known parameter validates and no unknown
    names are present. LOCKED parameters always fail validation.
    """
    errors: dict[str, ValidationResult] = {}
    known: list[str] = []
    unknown: list[str] = []
    for name, value in params.items():
        param = PARAMS.get(name)
        if param is None:
            unknown.append(name)
            errors[name] = ValidationResult(
                ok=False,
                error=ValidationError.UNKNOWN_PARAM,
                message=f"{name} is not a registered tunable parameter.",
            )
            continue
        known.append(name)
        result = param.validate(value)
        if not result.ok:
            errors[name] = result
    return ProposalValidation(
        ok=len(errors) == 0,
        errors=errors,
        known_params=known,
        unknown_params=unknown,
    )


__all__ = [
    "Category",
    "ValidationError",
    "ValidationResult",
    "TunableParam",
    "ProposalValidation",
    "PARAMS",
    "get_param",
    "list_by_category",
    "list_by_group",
    "groups",
    "schema_as_dict",
    "validate_proposal",
]
