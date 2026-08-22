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

import weakref
from dataclasses import dataclass
from typing import Any, Final, Literal, Optional

from scripts.open_model.redaction import (
    has_credential_shape,
    is_commit_revision,
    redact,
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

_RUNTIME_OBJECT_KINDS: Final[frozenset[str]] = frozenset({"commit", "tag-object"})
"""What a runtime evidence object IS. A bare version string is neither."""

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


def _exact_https_url(value: Any, allowed_opaque: tuple[str, ...] = ()) -> str:
    """Keep ``value`` only when it is a clean, canonical ``https://`` URL.

    This field exists so a human auditor can find the official page a claim
    came from. It is **never** fetched, opened, or executed by this package;
    restricting the scheme to ``https`` simply stops a descriptor from
    carrying a ``file:``, ``data:``, or command-shaped string that a future
    reader might mistake for something actionable.

    **Secret detection is per component, not per URL** (corrected after
    audit). The previous version skipped the long-opaque-run rule for the
    *entire* URL, because a 40-character hex commit id legitimately matches
    it - which also excused a 48-character credential sitting in the owner,
    repository, or file-name position. Now every path component gets the
    full secret matcher, and the long-run rule is waived **only** for a
    component that exactly equals one of ``allowed_opaque``: this
    descriptor's own repository revision or runtime object id. Any other
    long opaque run is refused, and a refused URL is never stored, so a
    credential cannot sit in the descriptor's ``repr`` even in cases where
    routing would later have refused to act on it.
    """
    ok, host, path = parse_https_url(value)
    if not ok:
        return ""
    if redact(host, max_chars=_URL_MAX_LEN) != host:
        return ""
    for component in path.split("/"):
        if not component:
            continue
        if component in allowed_opaque:
            # Waived for the long-run rule only; every other rule still runs.
            if has_credential_shape(component):
                return ""
            continue
        if redact(component, max_chars=_URL_MAX_LEN) != component:
            return ""
    return value


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


# -- structural validation (audit round four) --------------------------------

_CONTROL_CHARS: Final[frozenset[str]] = frozenset(
    [chr(code) for code in range(0x20)] + [chr(0x7F)]
)

_PATH_MAX_LEN: Final[int] = 256
_HOST_CHARS: Final[frozenset[str]] = frozenset(
    "abcdefghijklmnopqrstuvwxyz0123456789.-"
)

MODEL_EVIDENCE_HOST: Final[str] = "huggingface.co"
"""The single origin model provenance and licence evidence may come from."""

RUNTIME_EVIDENCE_HOST: Final[str] = "github.com"
"""The single origin runtime evidence may come from."""

RUNTIME_REPOSITORIES: Final[dict[str, str]] = {
    "llama-cpp": "ggml-org/llama.cpp",
    "ollama": "ollama/ollama",
    "vllm": "vllm-project/vllm",
    "sglang": "sgl-project/sglang",
    "tensorrt-llm": "NVIDIA/TensorRT-LLM",
}
"""The exact official repository for each runtime token.

Corrected after audit: requiring only ``github.com`` plus a trailing object
id let ``bound_runtime="vllm"`` be evidenced by
``https://github.com/evil-org/fake-runtime/tree/<a real vLLM commit>`` - a
genuine commit id borrowed to vouch for an unrelated repository. The token
now names one repository and the whole path must match it.

``in-process-stub`` deliberately has no entry: it is not a public runtime,
and a descriptor claiming it while bearing a real artifact has nothing
legitimate to point at.
"""


def _has_control(text: str) -> bool:
    for character in text:
        if character in _CONTROL_CHARS:
            return True
    return False


def is_canonical_relative_path(value: Any) -> bool:
    """True only for a canonical, repository-relative artifact identity.

    Rejects, in order: wrong type, empty, over-long, control characters,
    backslashes, a URL scheme, an absolute path, a drive letter, userinfo,
    a query or fragment, and any component that is empty, ``.``, ``..``, or
    surrounded by whitespace.

    Corrected after audit: this field previously reused the generic reference
    gate, which admits ``:`` and ``/`` and therefore accepted
    ``https://evil.invalid/x.gguf`` verbatim, while a traversal path
    collapsed to ``""`` and then routed through the repository-commit
    fallback as though no artifact had been claimed at all. A path is now
    either canonical or it invalidates the descriptor - never quietly
    downgraded.
    """
    if type(value) is not str:
        return False
    if not value or len(value) > _PATH_MAX_LEN:
        return False
    if _has_control(value):
        return False
    if chr(92) in value:
        return False
    if "://" in value or ":" in value:
        return False
    if value.startswith("/") or value.startswith("~"):
        return False
    if "@" in value or "?" in value or "#" in value or "%" in value:
        return False
    for component in value.split("/"):
        if not component or component in (".", ".."):
            return False
        # No whitespace anywhere: legal in git, but it makes a path ambiguous
        # in every log line and quoting context it will ever appear in, and
        # nothing in this repository needs it.
        for character in component:
            if character.isspace():
                return False
    return redact(value, max_chars=_PATH_MAX_LEN) == value


def parse_https_url(value: Any) -> tuple[bool, str, str]:
    """Structurally parse an https URL into ``(ok, host, path)``.

    Rejects anything that is not exactly ``https://host/path``: userinfo,
    an explicit port, a query, a fragment, control characters, uppercase or
    non-canonical hosts, empty path components, and ``..`` traversal.

    Corrected after audit: evidence binding previously used substring
    containment, so ``https://evil.invalid/?x=huggingface.co/org/model/tree/<sha>``
    satisfied it. Substring occurrence is not origin verification.
    """
    if type(value) is not str or not value or len(value) > _URL_MAX_LEN:
        return (False, "", "")
    if _has_control(value):
        return (False, "", "")
    # Percent-encoding is forbidden outright rather than decoded. These URLs
    # address repository trees and blobs whose names never need it, and
    # allowing it would mean re-deriving canonicality after a decode step -
    # %2e%2e, %2f, %40 and %00 all reintroduce exactly the traversal,
    # separator, userinfo and control cases the rest of this parser refuses.
    if "%" in value:
        return (False, "", "")
    prefix = "https://"
    if not value.startswith(prefix):
        return (False, "", "")
    remainder = value[len(prefix) :]
    if "?" in remainder or "#" in remainder:
        return (False, "", "")
    separator = remainder.find("/")
    authority = remainder if separator == -1 else remainder[:separator]
    path = "" if separator == -1 else remainder[separator:]
    if not authority or "@" in authority or ":" in authority:
        return (False, "", "")
    for character in authority:
        if character not in _HOST_CHARS:
            return (False, "", "")
    if authority.startswith(".") or authority.endswith(".") or ".." in authority:
        return (False, "", "")
    if path:
        for component in path.split("/")[1:]:
            if not component or component in (".", ".."):
                return (False, "", "")
    return (True, authority, path)


def is_official_evidence_url(
    value: Any, *, host: str, repository: str, revision: str, kind: str
) -> bool:
    """True when ``value`` is exactly the official URL for this evidence.

    The path must equal ``/{repository}/{kind}/{revision}`` for a tree URL,
    or begin with that prefix followed by a canonical relative file path for
    a blob URL. Nothing is matched by substring.
    """
    ok, parsed_host, path = parse_https_url(value)
    if not ok or parsed_host != host:
        return False
    if not repository or not revision:
        return False
    expected = "/" + repository + "/" + kind + "/" + revision
    if kind == "tree":
        return path == expected
    if not path.startswith(expected + "/"):
        return False
    return is_canonical_relative_path(path[len(expected) + 1 :])


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
    bound_runtime_object_kind: str = ""
    bound_runtime_source_url: str = ""
    licence_class: LicenceClass = "unknown"
    licence_name: str = ""
    licence_source_url: str = ""
    licence_revision: str = ""
    licence_notes: str = ""
    provenance_url: str = ""
    observed_on: str = ""
    invalid_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        # Identity and provenance are references, not free text: each must be
        # a bounded, closed-character-class value that survives the secret
        # matcher unchanged, so a path or credential cannot ride in here.
        set_(self, "model_id", _exact_reference(self.model_id))
        set_(self, "variant_id", _exact_reference(self.variant_id))
        set_(self, "repository_revision", _exact_revision(self.repository_revision))
        # Canonical-or-invalid. An unusable value must NOT quietly become ""
        # and then route as though the claim had never been made; it
        # invalidates the descriptor instead. The same rule applies to every
        # URL field below - see the tail of this method.
        supplied_path = self.artifact_path
        supplied_provenance = self.provenance_url
        supplied_licence_url = self.licence_source_url
        supplied_runtime_url = self.bound_runtime_source_url
        if type(supplied_path) is str and supplied_path == "":
            set_(self, "artifact_path", "")
        elif is_canonical_relative_path(supplied_path):
            set_(self, "artifact_path", supplied_path)
        else:
            set_(self, "artifact_path", "")
        set_(self, "bound_runtime", _exact_member(self.bound_runtime, _RUNTIME_KINDS, ""))
        set_(self, "bound_runtime_version", _exact_revision(self.bound_runtime_version))
        set_(
            self,
            "bound_runtime_object_kind",
            _exact_member(self.bound_runtime_object_kind, _RUNTIME_OBJECT_KINDS, ""),
        )
        # Only THIS descriptor's own immutable object ids are waived from the
        # long-opaque-run rule, and only when a path component equals one of
        # them exactly. Computed here because both are already normalized.
        allowed_opaque = tuple(
            token
            for token in (self.repository_revision, self.bound_runtime_version)
            if is_commit_revision(token)
        )
        set_(
            self,
            "bound_runtime_source_url",
            _exact_https_url(self.bound_runtime_source_url, allowed_opaque),
        )
        set_(self, "artifact_digest", _exact_digest(self.artifact_digest))
        set_(
            self,
            "licence_source_url",
            _exact_https_url(self.licence_source_url, allowed_opaque),
        )
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
        set_(
            self,
            "provenance_url",
            _exact_https_url(self.provenance_url, allowed_opaque),
        )
        set_(self, "observed_on", _exact_iso_date(self.observed_on))

        # A field that was SUPPLIED but could not be stored canonically
        # invalidates the descriptor. Silence here is what the audit caught:
        # the value disappears, the claim it encoded disappears with it, and
        # the descriptor routes as though it had never been made.
        invalid: list[str] = []
        if not (type(supplied_path) is str and supplied_path == ""):
            if not self.artifact_path:
                invalid.append("artifact_path")
        for name, supplied, stored in (
            ("provenance_url", supplied_provenance, self.provenance_url),
            ("licence_source_url", supplied_licence_url, self.licence_source_url),
            (
                "bound_runtime_source_url",
                supplied_runtime_url,
                self.bound_runtime_source_url,
            ),
        ):
            if type(supplied) is str and supplied == "":
                continue
            if not stored:
                invalid.append(name)
        set_(self, "invalid_fields", tuple(invalid))

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
        """True for every descriptor except a harness-constructed double.

        Corrected after audit. This previously read the ``runtimes`` field -
        exempting anything whose only runtime was ``"in-process-stub"`` -
        which made the exemption a **copyable value**. Any external author
        could type that string and bypass every artifact, provenance,
        licence and runtime gate at once. Exemption is now a property of
        *how the descriptor was constructed*, not of what it says: only an
        object handed out by the evaluation harness through
        ``register_harness_double`` is exempt, and identity is checked, so an
        equal-but-separately-constructed descriptor is not.
        """
        return not is_harness_double(self)

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
        if not self.has_immutable_revision():
            return False
        return is_official_evidence_url(
            self.provenance_url,
            host=MODEL_EVIDENCE_HOST,
            repository=self.model_id,
            revision=self.repository_revision,
            kind="tree",
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
        return is_official_evidence_url(
            self.licence_source_url,
            host=MODEL_EVIDENCE_HOST,
            repository=self.model_id,
            revision=self.repository_revision,
            kind="blob",
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
        # A tag NAME such as v0.27.1 is not immutable, wherever it appears.
        # The evidence must resolve to a full commit id, or to a full tag
        # OBJECT id that the descriptor explicitly labels as such.
        if not is_commit_revision(self.bound_runtime_version):
            return False
        if self.bound_runtime_object_kind not in _RUNTIME_OBJECT_KINDS:
            return False
        repository = RUNTIME_REPOSITORIES.get(self.bound_runtime)
        if repository is None:
            return False
        ok, host, path = parse_https_url(self.bound_runtime_source_url)
        if not ok or host != RUNTIME_EVIDENCE_HOST:
            return False
        # The COMPLETE canonical path, not a suffix match: owner, repository
        # and object must all be the expected ones.
        return path == "/" + repository + "/tree/" + self.bound_runtime_version

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


_HARNESS_DOUBLES: "weakref.WeakValueDictionary[int, ModelCapabilities]" = (
    weakref.WeakValueDictionary()
)
"""Identities of descriptors constructed by the evaluation harness.

Keyed by ``id()`` and holding a *weak* value, so an entry disappears with the
object and cannot pin memory. Membership is confirmed by identity
(``held is capabilities``), never by equality - a frozen dataclass compares
by value, so an equality-based check would exempt any external descriptor
that merely copied the same fields, which is the bypass this replaces.
"""


def register_harness_double(capabilities: ModelCapabilities) -> ModelCapabilities:
    """Mark ``capabilities`` as a repository-local evaluation double.

    **This is the closed construction path, and it has exactly one intended
    caller**: ``scripts.open_model.evaluation.stub_capabilities``. A test
    asserts that call-site count across the repository, so a second caller
    cannot appear unnoticed.

    Marking is deliberately an explicit function call rather than a field.
    Python cannot make it unforgeable - nothing in this language can - but it
    makes the exemption greppable, reviewable, and impossible to acquire by
    copying a descriptor's data.
    """
    if type(capabilities) is not ModelCapabilities:
        raise TypeError("only an exact ModelCapabilities may be marked")
    _HARNESS_DOUBLES[id(capabilities)] = capabilities
    return capabilities


def is_harness_double(capabilities: object) -> bool:
    """True only for the exact object the harness handed out."""
    held = _HARNESS_DOUBLES.get(id(capabilities))
    return held is capabilities


__all__ = [
    "AvailabilityState",
    "ExecutionLocality",
    "LicenceClass",
    "MODEL_EVIDENCE_HOST",
    "ModelCapabilities",
    "RESOURCE_ORDER",
    "RUNTIME_EVIDENCE_HOST",
    "RUNTIME_REPOSITORIES",
    "ResourceClass",
    "RuntimeKind",
    "SupportState",
    "is_canonical_relative_path",
    "is_harness_double",
    "is_official_evidence_url",
    "parse_https_url",
    "register_harness_double",
]
