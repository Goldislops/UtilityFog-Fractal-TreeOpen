"""OMI-V1 - immutable capability descriptors for open / local model backends.

This module answers one question and nothing else: *what is a candidate
backend claimed to be able to do, and on whose authority?* It performs no
I/O, imports no third-party package, and never dereferences anything it holds.

Design principles (deliberately mirroring the established discipline in
``scripts/agent_backends/base.py``, the merged seam this layer sits *above*
rather than replaces):

  - **Frozen and normalized at construction.** Descriptor values originate
    from human-authored catalogues or operator configuration, so every field
    is normalized by exact-type identity in ``__post_init__``. A shape that
    is not exactly what the contract declares is replaced by the conservative
    default without invoking any conversion, length, truth, comparison, or
    representation hook on the supplied value, and without exposing the
    value or its type in any message.

  - **Every default is the fail-closed value.** ``"unknown"`` support,
    ``"unknown"`` availability, ``0`` context, ``()`` runtimes, ``"unknown"``
    licence. A half-filled descriptor is therefore *ineligible* under
    ``scripts.open_model.routing``, never accidentally eligible. Nothing in
    this package ever upgrades an unknown into a yes.

  - **Tri-state support flags.** ``"supported" | "unsupported" | "unknown"``.
    ``"unknown"`` is not a synonym for ``"supported"``; the router treats it
    as a blocking condition with its own escalation reason, so an unverified
    vendor claim can never be silently relied upon.

  - **A descriptor is metadata, not an endorsement.** Holding a
    ``ModelCapabilities`` for a model implies nothing about whether that
    model has been installed, downloaded, benchmarked, licensed for a
    particular use, trusted, or approved. Only an operator explicitly binding
    a factory in ``scripts.open_model.registry`` - against a descriptor whose
    availability was *separately* established as ``"present"`` - makes a
    backend reachable at all.

  - **No endpoint or executable ever lives here.** There is deliberately no
    ``base_url``, ``host``, ``port``, ``command``, ``argv``, or ``api_key``
    field. The one URL-shaped field, ``provenance_url``, is documentation
    provenance for a human auditor; it is normalized to ``https://`` or empty
    and is never fetched, opened, or executed by any code in this package.

A note on ``structured_output``: constrained/JSON-schema decoding is in
practice a property of the *serving runtime* (llama.cpp grammars, vLLM
structured outputs, SGLang grammar backends), not of the weights. This field
therefore describes the **composed** backend - model as served by a specific
bound runtime. A catalogue entry that names a model but binds no runtime
legitimately reports ``"unknown"``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal, Optional


# -- vocabulary --------------------------------------------------------------

ExecutionLocality = Literal["local", "remote", "unknown"]
"""Where inference would execute. ``"unknown"`` never satisfies a local-only task."""

AvailabilityState = Literal["present", "absent", "unknown"]
"""Whether the backend was *observed* usable. Never inferred, only asserted."""

ResourceClass = Literal["light", "medium", "heavy", "unknown"]
"""Declared footprint band, used only to order otherwise-eligible candidates."""

SupportState = Literal["supported", "unsupported", "unknown"]
"""Tri-state feature claim. ``"unknown"`` blocks; it does not permit."""

LicenceClass = Literal[
    "osi-open-source",
    "open-weight-restricted",
    "source-available",
    "proprietary-service",
    "unknown",
]
"""Coarse licence classification.

``"open-weight-restricted"`` covers custom vendor or community terms that
publish weights but attach conditions (acceptable-use policies, derivative
naming duties, monthly-active-user or revenue thresholds). It is deliberately
NOT the same class as OSI open source, and a licence whose OSI status could
not be confirmed is classified into the *more* restrictive class, never the
less restrictive one.
"""

RuntimeKind = Literal[
    "llama-cpp",
    "ollama",
    "vllm",
    "sglang",
    "tensorrt-llm",
    "in-process-stub",
    "unknown",
]
"""Serving runtime a candidate is claimed to run under.

``"in-process-stub"`` names the hermetic evaluation fake - a runtime that
performs no I/O at all. It exists so the evaluation harness can describe its
own doubles honestly rather than borrowing a real runtime's name.
"""


_LOCALITIES: Final[frozenset[str]] = frozenset({"local", "remote", "unknown"})
_AVAILABILITIES: Final[frozenset[str]] = frozenset({"present", "absent", "unknown"})
_RESOURCE_CLASSES: Final[frozenset[str]] = frozenset(
    {"light", "medium", "heavy", "unknown"}
)
_SUPPORT_STATES: Final[frozenset[str]] = frozenset(
    {"supported", "unsupported", "unknown"}
)
_LICENCE_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "osi-open-source",
        "open-weight-restricted",
        "source-available",
        "proprietary-service",
        "unknown",
    }
)
_RUNTIME_KINDS: Final[frozenset[str]] = frozenset(
    {
        "llama-cpp",
        "ollama",
        "vllm",
        "sglang",
        "tensorrt-llm",
        "in-process-stub",
        "unknown",
    }
)

RESOURCE_ORDER: Final[dict[str, int]] = {
    "light": 0,
    "medium": 1,
    "heavy": 2,
    "unknown": 3,
}
"""Ordering key for candidate preference.

``"unknown"`` sorts last so an undeclared footprint is never preferred over a
declared one. These are *declared* bands authored by a human, not measured
values - this package benchmarks nothing.
"""

_MODEL_ID_MAX_LEN: Final[int] = 128
_LICENCE_NAME_MAX_LEN: Final[int] = 128
_NOTE_MAX_LEN: Final[int] = 512
_URL_MAX_LEN: Final[int] = 512
_TOKEN_MAX_LEN: Final[int] = 32
_MAX_SEQUENCE_ITEMS: Final[int] = 32


# -- normalization primitives ------------------------------------------------


def _exact_bounded_str(value: Any, limit: int) -> str:
    """Keep ``value`` sliced to ``limit`` only when it is exactly built-in ``str``.

    Every other exact type - including ``str`` subclasses, whose methods may
    be overridden - becomes ``""`` without any conversion, length, truth,
    comparison, or representation method being requested on the value.
    """
    if type(value) is str:
        return value[:limit]
    return ""


def _exact_member(value: Any, allowed: frozenset[str], fallback: str) -> str:
    """Keep ``value`` only when it is exactly built-in ``str`` AND a known member.

    Membership is tested against a ``frozenset[str]``, so only the built-in
    ``str`` hash and equality participate. Anything else - an unknown
    spelling, a ``str`` subclass, a hostile object - becomes ``fallback``,
    which is always the conservative choice for that field.
    """
    if type(value) is str and value in allowed:
        return value
    return fallback


def _exact_nonneg_int(value: Any) -> int:
    """Keep ``value`` only when it is exactly built-in ``int`` and non-negative.

    ``type(value) is int`` excludes ``bool`` (an ``int`` subclass), so ``True``
    does not silently become a context length of 1. Every other shape becomes
    ``0``, which this package reads as "unknown" and treats as blocking.
    """
    if type(value) is int and value >= 0:
        return value
    return 0


def _exact_str_tuple(
    value: Any,
    *,
    allowed: Optional[frozenset[str]],
    limit: int,
) -> tuple[str, ...]:
    """Normalize a sequence field to an order-preserving, de-duplicated tuple.

    An exact built-in ``tuple`` or ``list`` is walked in order; an element is
    kept only when it is exactly built-in ``str`` (sliced to ``limit``) and,
    when ``allowed`` is given, a known member. Duplicates after slicing are
    dropped keeping the first occurrence, so ordering stays deterministic. At
    most ``_MAX_SEQUENCE_ITEMS`` elements are retained. Every other shape
    becomes ``()`` without invoking any hook on the supplied value.
    """
    if type(value) is not tuple and type(value) is not list:
        return ()
    kept: list[str] = []
    for element in value:
        if len(kept) >= _MAX_SEQUENCE_ITEMS:
            break
        if type(element) is not str:
            continue
        sliced = element[:limit]
        if allowed is not None and sliced not in allowed:
            continue
        if sliced in kept:
            continue
        kept.append(sliced)
    return tuple(kept)


def _exact_https_url(value: Any) -> str:
    """Keep ``value`` only when it is exactly ``str`` and an ``https://`` URL.

    This field exists so a human auditor can find the official page a claim
    came from. It is **never** fetched, opened, or executed by this package;
    restricting the scheme to ``https`` simply stops a descriptor from
    carrying a ``file:``, ``data:``, or command-shaped string that a future
    reader might mistake for something actionable.
    """
    if type(value) is not str:
        return ""
    sliced = value[:_URL_MAX_LEN]
    if sliced.startswith("https://") and len(sliced) > len("https://"):
        return sliced
    return ""


def _exact_iso_date(value: Any) -> str:
    """Keep ``value`` only when it is exactly ``str`` shaped ``YYYY-MM-DD``.

    Shape-checked digit-by-digit against ASCII, not parsed into a date: this
    module holds no clock and performs no calendar arithmetic, so a
    descriptor's ``observed_on`` stays a literal record of when a human
    checked the source rather than something this code can drift.
    """
    if type(value) is not str or len(value) != 10:
        return ""
    if value[4] != "-" or value[7] != "-":
        return ""
    for index in (0, 1, 2, 3, 5, 6, 8, 9):
        if value[index] not in "0123456789":
            return ""
    return value


# -- the descriptor ----------------------------------------------------------


@dataclass(frozen=True)
class ModelCapabilities:
    """What a candidate backend is *claimed* to do, and on whose authority.

    Immutable by construction (``frozen=True``) and normalized in
    ``__post_init__``, so a descriptor cannot be edited after review and
    cannot carry a shape the router is not total over.

    Holding one of these implies nothing about installation, download,
    benchmarking, licensing for a particular use, trust, or approval. See the
    module docstring.
    """

    model_id: str
    locality: ExecutionLocality = "unknown"
    availability: AvailabilityState = "unknown"
    resource_class: ResourceClass = "unknown"
    structured_output: SupportState = "unknown"
    tool_calling: SupportState = "unknown"
    max_context_tokens: int = 0
    max_output_tokens: int = 0
    quantisations: tuple[str, ...] = ()
    runtimes: tuple[RuntimeKind, ...] = ()
    licence_class: LicenceClass = "unknown"
    licence_name: str = ""
    licence_notes: str = ""
    provenance_url: str = ""
    observed_on: str = ""

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "model_id", _exact_bounded_str(self.model_id, _MODEL_ID_MAX_LEN))
        set_(self, "locality", _exact_member(self.locality, _LOCALITIES, "unknown"))
        set_(
            self,
            "availability",
            _exact_member(self.availability, _AVAILABILITIES, "unknown"),
        )
        set_(
            self,
            "resource_class",
            _exact_member(self.resource_class, _RESOURCE_CLASSES, "unknown"),
        )
        set_(
            self,
            "structured_output",
            _exact_member(self.structured_output, _SUPPORT_STATES, "unknown"),
        )
        set_(
            self,
            "tool_calling",
            _exact_member(self.tool_calling, _SUPPORT_STATES, "unknown"),
        )
        set_(self, "max_context_tokens", _exact_nonneg_int(self.max_context_tokens))
        set_(self, "max_output_tokens", _exact_nonneg_int(self.max_output_tokens))
        set_(
            self,
            "quantisations",
            _exact_str_tuple(self.quantisations, allowed=None, limit=_TOKEN_MAX_LEN),
        )
        set_(
            self,
            "runtimes",
            _exact_str_tuple(
                self.runtimes, allowed=_RUNTIME_KINDS, limit=_TOKEN_MAX_LEN
            ),
        )
        set_(
            self,
            "licence_class",
            _exact_member(self.licence_class, _LICENCE_CLASSES, "unknown"),
        )
        set_(
            self,
            "licence_name",
            _exact_bounded_str(self.licence_name, _LICENCE_NAME_MAX_LEN),
        )
        set_(self, "licence_notes", _exact_bounded_str(self.licence_notes, _NOTE_MAX_LEN))
        set_(self, "provenance_url", _exact_https_url(self.provenance_url))
        set_(self, "observed_on", _exact_iso_date(self.observed_on))

    # -- derived views (pure; no I/O, no clock, no randomness) ---------------

    def unresolved_fields(self) -> tuple[str, ...]:
        """Field names still holding their conservative "unknown" default.

        Returned in fixed declaration order. Used by diagnostics to explain
        *why* a descriptor cannot route, without restating operator input.
        """
        unresolved: list[str] = []
        if not self.model_id:
            unresolved.append("model_id")
        if self.locality == "unknown":
            unresolved.append("locality")
        if self.availability == "unknown":
            unresolved.append("availability")
        if self.resource_class == "unknown":
            unresolved.append("resource_class")
        if self.structured_output == "unknown":
            unresolved.append("structured_output")
        if self.tool_calling == "unknown":
            unresolved.append("tool_calling")
        if self.max_context_tokens == 0:
            unresolved.append("max_context_tokens")
        if not self.runtimes:
            unresolved.append("runtimes")
        if self.licence_class == "unknown":
            unresolved.append("licence_class")
        return tuple(unresolved)

    def preference_key(self) -> tuple[int, str]:
        """Deterministic ordering key: lighter declared footprint first, then id.

        Contains no clock, no randomness, and no measured performance - this
        package never benchmarks anything, so "lighter" means only "declared
        lighter by a human in the descriptor".
        """
        return (RESOURCE_ORDER.get(self.resource_class, 3), self.model_id)


__all__ = [
    "AvailabilityState",
    "ExecutionLocality",
    "LicenceClass",
    "ModelCapabilities",
    "RESOURCE_ORDER",
    "ResourceClass",
    "RuntimeKind",
    "SupportState",
]
