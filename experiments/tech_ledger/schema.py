"""Closed in-Python schema for ``tech-ledger-v1`` entries.

Pure, dependency-free (standard library only) validation of technology-
ledger records. The central rule, stated once and enforced nowhere as a
truth judgement:

    Schema validity is not scientific validity, endorsement,
    implementation authority or evidence that a claim is true.

Validation is PURE and NON-MUTATING: it never rewrites a field, never
infers a classification, placement, evidential status or scientific
conclusion, and never upgrades a ``verification_status`` (in particular,
a primary or qualifier ``G`` classification never causes
``verification_status`` to become ``verified`` -- verification is a
separate human act recorded in the data, not a validation side effect).

Exact-type discipline: containers and scalars must be the exact built-in
types (``bool`` is refused where ``int`` is required; subclasses are
refused everywhere). Refusal messages never invoke hooks on rejected
objects -- type names come from an identity table of builtins, foreign
dictionary keys are never hashed, compared or stringified, and anything
non-builtin is described generically.
"""

from __future__ import annotations

import datetime
import re
from typing import Any, Final

SCHEMA_ID: Final[str] = "tech-ledger-v1"

#: Evidential classification vocabulary (fixed; documented in README.md).
CLASSIFICATIONS: Final[tuple[str, ...]] = ("A", "B", "C", "D", "E", "F", "G")

PLACEMENTS: Final[tuple[str, ...]] = (
    "executable-code",
    "experiment",
    "schema",
    "research-ledger",
    "future-watch",
)

DISPOSITIONS: Final[tuple[str, ...]] = (
    "eligible",
    "evidence-gated",
    "deferred",
    "prohibited",
)

STATUSES: Final[tuple[str, ...]] = (
    "active",
    "future-watch",
    "v5-deferred",
    "parked",
)

SOURCE_KINDS: Final[tuple[str, ...]] = (
    "user-supplied-audit",
    "repository",
    "primary-source",
    "secondary-source",
)

VERIFICATION_STATUSES: Final[tuple[str, ...]] = (
    "verified",
    "unverified",
    "not-computable",
)

#: Wire-format digits are ASCII ONLY. ``\d`` in Python str patterns
#: matches every Unicode decimal digit (Arabic-Indic, Devanagari,
#: Bengali, ...), and ``int()`` parses them too -- so explicit [0-9]
#: classes are load-bearing here, not style: a ledger identifier or date
#: written with non-ASCII digits is refused even though Python could
#: parse it.
ENTRY_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"\ATLV4-[0-9]{3}\Z")
_DATE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\A([0-9]{4})-([0-9]{2})-([0-9]{2})\Z"
)

_ROOT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "entry_id",
        "neutral_name",
        "primary_classification",
        "classification_qualifiers",
        "classification_rationale",
        "legitimate_uses",
        "unsuitable_uses",
        "repository_placements",
        "implementation_disposition",
        "minimal_evidence_before_implementation",
        "implementation_seam",
        "provenance",
        "related_intake_ledger_entries",
        "warnings",
        "status",
    }
)

_PROVENANCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "source_kind",
        "source_reference",
        "attributed_author",
        "recorded_date",
        "verification_status",
    }
)


class LedgerEntryError(ValueError):
    """A malformed, hostile or rule-violating ledger entry (fail closed)."""


_BUILTIN_TYPE_NAMES: Final[tuple[tuple[type, str], ...]] = (
    (bool, "bool"),  # before int: bool is an int subclass
    (int, "int"),
    (float, "float"),
    (str, "str"),
    (list, "list"),
    (dict, "dict"),
    (tuple, "tuple"),
    (set, "set"),
    (bytes, "bytes"),
    (type(None), "NoneType"),
)


def _describe_type(value: Any) -> str:
    """Hook-free type description: identity comparison against builtins
    only; ``type(value).__name__`` is never read (a hostile metaclass can
    make reading it execute code)."""
    value_type = type(value)
    for builtin, name in _BUILTIN_TYPE_NAMES:
        if value_type is builtin:
            return name
    return "non-builtin value"


def _exact_dict(value: Any, field: str, keys: frozenset[str]) -> dict[str, Any]:
    """Exact built-in dict with exactly the given key set.

    Foreign (non-``str``) keys are never hashed, compared, stringified or
    represented: iteration alone collects exact-``str`` keys, anything
    else is described generically and forces a refusal.
    """
    if type(value) is not dict:
        raise LedgerEntryError(
            f"{field}: expected builtin dict, got {_describe_type(value)}"
        )
    str_keys: set[str] = set()
    foreign: list[str] = []
    for key in value:
        if type(key) is str:
            str_keys.add(key)
        else:
            foreign.append(f"<{_describe_type(key)}>")
    if foreign or str_keys != keys:
        unknown = sorted(list(str_keys - keys) + foreign)
        missing = sorted(keys - str_keys)
        raise LedgerEntryError(
            f"{field}: key set mismatch (unknown={unknown}, missing={missing})"
        )
    return value


def _exact_str(value: Any, field: str) -> str:
    if type(value) is not str:
        raise LedgerEntryError(
            f"{field}: expected builtin str, got {_describe_type(value)}"
        )
    return value


def _non_empty_str(value: Any, field: str) -> str:
    text = _exact_str(value, field)
    if not text:
        raise LedgerEntryError(f"{field}: must be a non-empty string")
    return text


def _enum(value: Any, field: str, allowed: tuple[str, ...]) -> str:
    text = _exact_str(value, field)
    if text not in allowed:
        raise LedgerEntryError(
            f"{field}: {text!r} not in the fixed vocabulary {list(allowed)}"
        )
    return text


def _exact_list(value: Any, field: str) -> list[Any]:
    if type(value) is not list:
        raise LedgerEntryError(
            f"{field}: expected builtin list, got {_describe_type(value)}"
        )
    return value


def _non_empty_str_list(value: Any, field: str) -> list[str]:
    items = _exact_list(value, field)
    if not items:
        raise LedgerEntryError(f"{field}: must be a non-empty list")
    return [_non_empty_str(item, f"{field}[{i}]") for i, item in enumerate(items)]


def _validate_date(value: Any, field: str) -> str:
    """A real ISO ``YYYY-MM-DD`` calendar date (impossible dates refused)."""
    text = _exact_str(value, field)
    match = _DATE_PATTERN.match(text)
    if match is None:
        raise LedgerEntryError(f"{field}: {text!r} is not an ISO YYYY-MM-DD date")
    year, month, day = (int(part) for part in match.groups())
    try:
        datetime.date(year, month, day)
    except ValueError as e:
        raise LedgerEntryError(
            f"{field}: {text!r} is not a real calendar date"
        ) from e
    return text


def validate_provenance(value: Any) -> None:
    """Validate the closed provenance block. Pure; never mutates."""
    block = _exact_dict(value, "provenance", _PROVENANCE_KEYS)
    _enum(block["source_kind"], "provenance.source_kind", SOURCE_KINDS)
    _non_empty_str(block["source_reference"], "provenance.source_reference")
    _non_empty_str(block["attributed_author"], "provenance.attributed_author")
    _validate_date(block["recorded_date"], "provenance.recorded_date")
    _enum(
        block["verification_status"],
        "provenance.verification_status",
        VERIFICATION_STATUSES,
    )


def validate_entry(obj: Any) -> None:
    """Validate one ``tech-ledger-v1`` entry. Pure; raises
    ``LedgerEntryError`` on the first refusal; returns ``None`` and never
    mutates, infers or rewrites anything on success."""
    entry = _exact_dict(obj, "entry", _ROOT_KEYS)

    schema = _exact_str(entry["schema"], "schema")
    if schema != SCHEMA_ID:
        raise LedgerEntryError(
            f"schema: unknown variant {schema!r} (expected {SCHEMA_ID!r})"
        )

    entry_id = _exact_str(entry["entry_id"], "entry_id")
    if ENTRY_ID_PATTERN.match(entry_id) is None:
        raise LedgerEntryError(
            f"entry_id: {entry_id!r} does not match the fixed TLV4-NNN form"
        )

    _non_empty_str(entry["neutral_name"], "neutral_name")

    primary = _enum(
        entry["primary_classification"], "primary_classification", CLASSIFICATIONS
    )

    qualifiers = _exact_list(
        entry["classification_qualifiers"], "classification_qualifiers"
    )
    seen_qualifiers: set[str] = set()
    for i, item in enumerate(qualifiers):
        qualifier = _enum(
            item, f"classification_qualifiers[{i}]", CLASSIFICATIONS
        )
        if qualifier == primary:
            raise LedgerEntryError(
                f"classification_qualifiers[{i}]: must not repeat the "
                f"primary classification {primary!r}"
            )
        if qualifier in seen_qualifiers:
            raise LedgerEntryError(
                f"classification_qualifiers[{i}]: duplicate {qualifier!r}"
            )
        seen_qualifiers.add(qualifier)

    _non_empty_str(entry["classification_rationale"], "classification_rationale")
    _non_empty_str_list(entry["legitimate_uses"], "legitimate_uses")
    _non_empty_str_list(entry["unsuitable_uses"], "unsuitable_uses")

    placements = _exact_list(entry["repository_placements"], "repository_placements")
    if not placements:
        raise LedgerEntryError("repository_placements: must be a non-empty list")
    seen_placements: set[str] = set()
    for i, item in enumerate(placements):
        placement = _enum(item, f"repository_placements[{i}]", PLACEMENTS)
        if placement in seen_placements:
            raise LedgerEntryError(
                f"repository_placements[{i}]: duplicate {placement!r}"
            )
        seen_placements.add(placement)

    disposition = _enum(
        entry["implementation_disposition"],
        "implementation_disposition",
        DISPOSITIONS,
    )

    _non_empty_str_list(
        entry["minimal_evidence_before_implementation"],
        "minimal_evidence_before_implementation",
    )

    seam = entry["implementation_seam"]
    if seam is not None:
        _non_empty_str(seam, "implementation_seam")

    validate_provenance(entry["provenance"])

    related = _exact_list(
        entry["related_intake_ledger_entries"], "related_intake_ledger_entries"
    )
    seen_related: set[int] = set()
    for i, item in enumerate(related):
        # Exact builtin int only: bool is an int subclass and is refused.
        if type(item) is not int:
            raise LedgerEntryError(
                f"related_intake_ledger_entries[{i}]: expected builtin int, "
                f"got {_describe_type(item)}"
            )
        if item <= 0:
            raise LedgerEntryError(
                f"related_intake_ledger_entries[{i}]: must be a positive integer"
            )
        if item in seen_related:
            raise LedgerEntryError(
                f"related_intake_ledger_entries[{i}]: duplicate {item}"
            )
        seen_related.add(item)

    _non_empty_str_list(entry["warnings"], "warnings")

    status = _enum(entry["status"], "status", STATUSES)

    # ---- Cross-field rules (record discipline, never truth judgement) ----

    # Rule 1: a primary F (unsupported / misleading / technically
    # mismatched claim) is never implementable and never carries a seam.
    if primary == "F":
        if disposition != "prohibited":
            raise LedgerEntryError(
                "primary classification F requires "
                "implementation_disposition 'prohibited'"
            )
        if seam is not None:
            raise LedgerEntryError(
                "primary classification F requires a null implementation_seam"
            )

    # Rules 2-3: prohibited and deferred dispositions carry no seam.
    if disposition in ("prohibited", "deferred") and seam is not None:
        raise LedgerEntryError(
            f"implementation_disposition {disposition!r} requires a null "
            f"implementation_seam"
        )

    # Rule 4: eligible and evidence-gated dispositions require a seam.
    if disposition in ("eligible", "evidence-gated") and seam is None:
        raise LedgerEntryError(
            f"implementation_disposition {disposition!r} requires a "
            f"non-empty implementation_seam"
        )

    # Rule 5: v5-deferred status is deferred work with no seam.
    if status == "v5-deferred":
        if disposition != "deferred":
            raise LedgerEntryError(
                "status 'v5-deferred' requires implementation_disposition "
                "'deferred'"
            )
        if seam is not None:
            raise LedgerEntryError(
                "status 'v5-deferred' requires a null implementation_seam"
            )

    # Rule 6 is enforced by construction: this validator never writes to
    # the entry, so a primary or qualifier G can never cause
    # verification_status to be rewritten. Rule 7 likewise: nothing above
    # infers a classification, placement, evidential status or scientific
    # conclusion -- every value is the operator's recorded statement,
    # checked for shape only.
