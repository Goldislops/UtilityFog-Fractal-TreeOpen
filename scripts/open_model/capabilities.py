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

**Provenance is part of identity (added after audit).** A descriptor names
exactly one artifact, and says where that artifact came from:
``model_id`` + ``variant_id`` + ``repository_revision`` identify it,
``artifact_digest`` pins the bytes when an artifact-format claim is made, and
``licence_source_url`` + ``licence_revision`` pin the terms that were read.
``quantisation`` is singular for the same reason - BF16, NVFP4 and GGUF
builds of one checkpoint are different files with different digests and
different runtime support, and collapsing them under a generic model id
makes a descriptor unfalsifiable. Every one of these is blocking in
``scripts.open_model.routing``: an unpinned descriptor cannot route.

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

from scripts.open_model.redaction import (
    is_commit_revision,
    is_safe_reference,
    is_safe_revision,
    is_safe_token,
)


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

_MUTABLE_REF_NAMES: Final[frozenset[str]] = frozenset(
    {
        "main",
        "master",
        "head",
        "latest",
        "stable",
        "dev",
        "develop",
        "trunk",
        "edge",
        "nightly",
        "current",
        "release",
    }
)
"""Ref names that move. Never acceptable as a pin for a reviewed claim."""

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
    # Bound the INPUT, not just the output. Capping only the kept list still
    # walks every element of an arbitrarily long sequence; refusing an
    # over-long input outright is both cheaper and fail-closed.
    if len(value) > _MAX_SEQUENCE_ITEMS:
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


def _exact_reference(value: Any) -> str:
    """Keep ``value`` only when it is a safe, bounded, non-secret reference.

    Delegates to ``redaction.is_safe_reference``: exactly built-in ``str``,
    within the length bound, drawn from a closed character class, and
    unchanged by the secret matcher. A drive-letter path, a POSIX home path,
    a bearer string, or a provider-prefixed key is refused and becomes ``""``.
    """
    if is_safe_reference(value):
        return value
    return ""


def _exact_revision(value: Any) -> str:
    """Keep a full commit id, or a tag/branch-shaped safe reference.

    Corrected after audit: this previously reused the generic reference
    gate, which rejected ordinary 40-character git SHAs because the
    long-opaque-run secret rule matched them. See
    ``redaction.is_commit_revision`` for why the exemption is narrow.
    """
    if is_safe_revision(value):
        return value
    return ""


def _exact_artifact_path(value: Any) -> str:
    """Keep a repository-relative file path, or ``""``.

    Uses the reference gate, which admits ``/`` for subdirectories while
    the redaction cross-check still refuses absolute drive-letter and
    POSIX home paths - a repository-relative path is what belongs here,
    never a local filesystem location.
    """
    if is_safe_reference(value):
        return value
    return ""


def _exact_digest(value: Any) -> str:
    """Keep ``value`` only when it is exactly ``sha256:`` + 64 lowercase hex.

    Shape-checked character by character rather than parsed, and deliberately
    strict: a digest that is not verifiable at a glance is worse than no
    digest, because it invites a reader to believe an artifact was pinned
    when it was not.
    """
    if type(value) is not str:
        return ""
    prefix = "sha256:"
    if len(value) != len(prefix) + 64 or not value.startswith(prefix):
        return ""
    for character in value[len(prefix) :]:
        if character not in "0123456789abcdef":
            return ""
    return value


def _exact_quantisation(value: Any) -> str:
    """Keep a single artifact-format token, or ``""``.

    One descriptor, one artifact. ``""`` means "this descriptor makes no
    artifact-format claim", which is what suppresses the digest requirement
    in ``scripts.open_model.routing``.
    """
    if is_safe_token(value, max_len=_TOKEN_MAX_LEN):
        return value
    return ""


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
    variant_id: str = ""
    repository_revision: str = ""
    artifact_path: str = ""
    artifact_digest: str = ""
    locality: ExecutionLocality = "unknown"
    availability: AvailabilityState = "unknown"
    resource_class: ResourceClass = "unknown"
    structured_output: SupportState = "unknown"
    tool_calling: SupportState = "unknown"
    max_context_tokens: int = 0
    max_output_tokens: int = 0
    quantisation: str = ""
    runtimes: tuple[RuntimeKind, ...] = ()
    bound_runtime: str = ""
    bound_runtime_version: str = ""
    bound_runtime_source_url: str = ""
    licence_class: LicenceClass = "unknown"
    licence_name: str = ""
    licence_source_url: str = ""
    licence_revision: str = ""
    licence_notes: str = ""
    provenance_url: str = ""
    observed_on: str = ""

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        # Identity and provenance are references, not free text: each must be
        # a bounded, closed-character-class value that survives the secret
        # matcher unchanged, so a path or credential cannot ride in here.
        set_(self, "model_id", _exact_reference(self.model_id))
        set_(self, "variant_id", _exact_reference(self.variant_id))
        set_(self, "repository_revision", _exact_revision(self.repository_revision))
        # Applied here, which the audit found it was not: `_exact_artifact_path`
        # existed but was never called, so an absolute, secret-shaped, or
        # hostile value was stored verbatim - and a hostile `__bool__` then
        # made `evaluate()` non-total the moment it truth-tested this field.
        set_(self, "artifact_path", _exact_artifact_path(self.artifact_path))
        set_(self, "bound_runtime", _exact_member(self.bound_runtime, _RUNTIME_KINDS, ""))
        set_(self, "bound_runtime_version", _exact_revision(self.bound_runtime_version))
        set_(
            self,
            "bound_runtime_source_url",
            _exact_https_url(self.bound_runtime_source_url),
        )
        set_(self, "artifact_digest", _exact_digest(self.artifact_digest))
        set_(self, "licence_source_url", _exact_https_url(self.licence_source_url))
        set_(self, "licence_revision", _exact_reference(self.licence_revision))
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
        # Singular, not a tuple: one descriptor describes exactly one
        # artifact. Collapsing BF16, NVFP4 and GGUF builds of a checkpoint
        # under one descriptor was the audit finding this closes - those are
        # different files with different digests and different runtimes.
        set_(self, "quantisation", _exact_quantisation(self.quantisation))
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
        if not self.variant_id:
            unresolved.append("variant_id")
        if not self.repository_revision:
            unresolved.append("repository_revision")
        if self.artifact_path and not self.artifact_digest:
            unresolved.append("artifact_digest")
        if self.is_artifact_bearing():
            # Reported only for real artifacts. The repository-local
            # in-process double is the single, narrow exception: it has no
            # upstream repository, no licence page and no serving runtime to
            # pin, because it is this repository's own code.
            if not self.is_byte_pinned():
                unresolved.append("artifact_pin")
            if not self.has_immutable_revision():
                unresolved.append("immutable_revision")
            if not self.has_pinned_provenance():
                unresolved.append("provenance_url")
            if not self.has_pinned_licence():
                unresolved.append("pinned_licence")
            if not self.has_pinned_runtime_binding():
                unresolved.append("bound_runtime")
        if not self.licence_source_url:
            unresolved.append("licence_source_url")
        if not self.licence_revision:
            unresolved.append("licence_revision")
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

    def is_artifact_bearing(self) -> bool:
        """True when this descriptor designates real files somewhere.

        Derived from the declared runtimes rather than from a separate
        flag an author could forget to set: anything served by a real
        runtime is backed by files that need pinning, while the
        in-process double is this repository's own code and has no
        artifact to digest.
        """
        return any(runtime != "in-process-stub" for runtime in self.runtimes)

    def has_immutable_revision(self) -> bool:
        """True when the repository revision is a full commit id.

        A symbolic revision - ``main``, a branch, a moving tag - identifies
        whatever that name points at *today*, which is not what a reviewed
        claim needs.
        """
        return is_commit_revision(self.repository_revision)

    def has_pinned_provenance(self) -> bool:
        """True when ``provenance_url`` binds this exact repo and revision.

        Both halves matter. A URL that names the repository but not the
        revision resolves to a moving target; a URL carrying a revision but
        naming a different repository is evidence about something else.
        """
        if not self.provenance_url or not self.model_id:
            return False
        if not self.has_immutable_revision():
            return False
        return (
            self.model_id in self.provenance_url
            and self.repository_revision in self.provenance_url
        )

    def has_pinned_licence(self) -> bool:
        """True when the licence claim is bound to immutable evidence.

        Requires a licence source URL naming this repository *at this
        revision*, and a licence revision that is not a mutable ref name.
        A ``/blob/main/`` licence URL is the case this refuses: the terms it
        shows can change after review without the descriptor changing.
        """
        if not self.licence_source_url or not self.licence_revision:
            return False
        if self.licence_revision.lower() in _MUTABLE_REF_NAMES:
            return False
        if not self.has_immutable_revision():
            return False
        return (
            self.model_id in self.licence_source_url
            and self.repository_revision in self.licence_source_url
        )

    def has_pinned_runtime_binding(self) -> bool:
        """True when the *bound* runtime carries an immutable version+source.

        ``runtimes`` is a plural compatibility list - what a vendor claims a
        model can run under. ``bound_runtime`` is the single runtime the
        operator factory actually constructs against, and it is the only one
        a narrowed runtime requirement may be judged on.
        """
        if not self.bound_runtime:
            return False
        if not self.bound_runtime_version or not self.bound_runtime_source_url:
            return False
        if self.bound_runtime_version.lower() in _MUTABLE_REF_NAMES:
            return False
        return self.bound_runtime_version in self.bound_runtime_source_url

    def is_byte_pinned(self) -> bool:
        """True when the bytes this descriptor refers to are pinned.

        Two admissible forms, and the requirement no longer keys off
        ``quantisation`` (the audit finding):

        - a named single file plus its ``sha256`` digest, which is the
          right pin for one-file variants such as a GGUF build; or
        - a **full commit id** in ``repository_revision``, which pins
          every file in the tree at once and is the only coherent pin
          for a sharded variant. Granite 4.1 8B BF16, for instance, is
          four safetensors shards - there is no single file whose
          digest would mean anything, while the commit id covers all
          four exactly.

        A symbolic revision such as a branch name is not a pin, because
        it can be moved after the claim was reviewed.
        """
        if self.artifact_path and self.artifact_digest:
            return True
        return is_commit_revision(self.repository_revision)

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
