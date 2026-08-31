"""Closed shapes, closed vocabularies and canonical form for
``general-v7-supplied-source-ledger-v1``.

Standard library only. This module imports no other ledger package, retrieves
nothing, and resolves no locator. It declares what a record may contain; the
refusals themselves live in ``validate.py``.

CONTRACT.md is the authority. Where this module and the contract disagree, the
contract is right and this module is a defect.
"""

from __future__ import annotations

import json
import re
import unicodedata

SCHEMA_ID = "supplied-source-v1"
LEDGER_ID = "general-v7-supplied-source-ledger-v1"
CORPUS = "GENERAL V7 SUPPLIED SOURCE CORPUS"
NAMESPACE = "G7S-"

#: ``[0-9]`` rather than a digit shorthand: the shorthand matches Arabic-Indic
#: and Devanagari digits and ``int()`` parses them. CONTRACT.md section 4.
#: Patterns are kept as strings and matched with ``re.match``. ``re.compile``
#: is avoided deliberately: ``G7S-Q-004`` forbids the bare call name
#: ``compile`` in a production module, and complying costs nothing here.
ID_PATTERN = r"\AG7S-(BAT|SRC|CLM|REL|UNR|COR|NAD)-[0-9]{4}\Z"
DIGEST_PATTERN = r"\A[0-9a-f]{64}\Z"
DRIVE_OR_UNC_PATTERN = r"\A([A-Za-z]:|//|\\)"

COLLECTIONS = (
    "batches",
    "sources",
    "claims",
    "relationships",
    "unresolved",
    "corrections",
    "non_admitted",
)

ID_SEGMENT_BY_COLLECTION = {
    "batches": "BAT",
    "sources": "SRC",
    "claims": "CLM",
    "relationships": "REL",
    "unresolved": "UNR",
    "corrections": "COR",
    "non_admitted": "NAD",
}

ROOT_METADATA_KEYS = ("schema_id", "ledger_id", "corpus", "counts")
ROOT_KEYS = frozenset(ROOT_METADATA_KEYS) | frozenset(COLLECTIONS)

#: The complete declared key set per record kind. CONTRACT.md section 4b.
KEYS_BY_COLLECTION = {
    "batches": frozenset(
        {
            "record_id",
            "batch_ordinal",
            "member_filename",
            "member_sha256",
            "packet_sha256",
            "origin_type",
            "origin_id",
            "line_ending_form",
        }
    ),
    "sources": frozenset(
        {
            "record_id",
            "introducing_batch_ref",
            "locator_carrier_batch_ref",
            "supplied_locator",
            "normalized_locator",
            "normalized_identifier",
            "locator_absence_reason",
            "bibliography_entry",
            "supplied_text",
            "retrieval_state",
            "verification_state",
            "verification_evidence",
        }
    ),
    "claims": frozenset(
        {
            "record_id",
            "batch_ref",
            "attribution_class",
            "verification_state",
            "byte_evidence",
            "limitations",
        }
    ),
    "relationships": frozenset(
        {
            "record_id",
            "left_ref",
            "right_ref",
            "relationship_type",
            "verification_state",
        }
    ),
    "unresolved": frozenset({"record_id", "state"}),
    "corrections": frozenset(
        {"record_id", "target_ref", "correction_kind", "reciprocal_ref"}
    ),
    "non_admitted": frozenset(
        {
            "record_id",
            "carrier_batch_ref",
            "carrier_member_sha256",
            "presence",
            "admission_status",
            "executable_status",
            "normative_status",
        }
    ),
}

# --------------------------------------------------------------------------
# Closed vocabularies. CONTRACT.md sections 8a, 8b, 9, 10, 13.
# --------------------------------------------------------------------------

ATTRIBUTION_CLASSES = (
    "supplied-by-kev-verbatim",
    "supplied-by-kev-inline",
    "packet-structural-fact",
    "aura-summary",
    "aura-inference",
    "seat-observation",
)

RELATIONSHIP_TYPES = (
    "same-supplied-identifier",
    "same-supplied-title-text",
    "shares-carrier-batch",
    "conflicts-with-supplied-material",
)

ORIGIN_TYPES = ("attachment", "inline_user_message")
LINE_ENDING_FORMS = ("crlf-only", "lf-only", "mixed", "none")

RETRIEVAL_STATES = ("not-attempted",)
SOURCE_VERIFICATION_STATES = ("supplied-unretrieved",)
CLAIM_VERIFICATION_STATES = ("unverified",)
RELATIONSHIP_VERIFICATION_STATES = ("unverified",)
UNRESOLVED_STATES = ("unresolved",)

CORRECTION_KINDS = ("correction", "contest", "withdrawal", "supersession")

LOCATOR_ABSENCE_REASONS = (
    "no-locator-supplied",
    "locator-not-applicable",
    "locator-supplied-empty",
)

PRESENCE_STATES = ("present-in-packet",)
ADMISSION_STATES = ("not-admitted",)
EXECUTABLE_STATES = ("non-executable",)
NORMATIVE_STATES = ("non-normative",)

#: Closed refusal vocabulary. CONTRACT.md section 11a. Sorted, duplicate-free.
REFUSAL_TOKENS = (
    "absence-representation-not-permitted",
    "attribution-class-not-permitted",
    "bool-not-integer",
    "correction-target-not-permitted",
    "duplicate-key",
    "duplicate-relationship",
    "encoding-not-permitted",
    "float-not-permitted",
    "integer-out-of-bounds",
    "locator-without-carrier",
    "malformed-document",
    "missing-key",
    "non-ascii-digit",
    "non-finite-not-permitted",
    "path-identity-changed",
    "path-not-relative",
    "path-reserved-component",
    "path-separator-not-permitted",
    "path-traversal",
    "reference-cycle",
    "reference-not-found",
    "relationship-endpoints-identical",
    "reparse-point-refused",
    "self-reference",
    "supersession-not-reciprocal",
    "unknown-key",
    "verification-state-not-permitted",
    "vocabulary-token-not-permitted",
    "wrong-type",
)

# --------------------------------------------------------------------------
# Field rules. Each entry says what a field may hold, so ``validate`` can be a
# single walk rather than a pile of special cases.
#
# "kind" is one of: id, digest, int, str, bool, enum, null-or-id,
# null-or-str, null-or-enum, null-or-list, null-or-any.
# --------------------------------------------------------------------------

BATCH_ORDINAL_BOUNDS = (1, 63)

FIELD_RULES = {
    "batches": {
        "record_id": {"kind": "id", "segment": "BAT"},
        "batch_ordinal": {"kind": "int", "bounds": BATCH_ORDINAL_BOUNDS},
        "member_filename": {"kind": "path"},
        "member_sha256": {"kind": "digest"},
        "packet_sha256": {"kind": "digest"},
        "origin_type": {"kind": "enum", "values": ORIGIN_TYPES},
        "origin_id": {"kind": "str"},
        "line_ending_form": {"kind": "enum", "values": LINE_ENDING_FORMS},
    },
    "sources": {
        "record_id": {"kind": "id", "segment": "SRC"},
        "introducing_batch_ref": {"kind": "id", "segment": "BAT"},
        "locator_carrier_batch_ref": {"kind": "null-or-id", "segment": "BAT"},
        "supplied_locator": {"kind": "null-or-str"},
        "normalized_locator": {"kind": "null-or-str"},
        "normalized_identifier": {"kind": "null-or-str"},
        "locator_absence_reason": {
            "kind": "null-or-enum",
            "values": LOCATOR_ABSENCE_REASONS,
        },
        "bibliography_entry": {"kind": "bool"},
        "supplied_text": {"kind": "null-or-str"},
        "retrieval_state": {"kind": "enum", "values": RETRIEVAL_STATES},
        "verification_state": {"kind": "enum", "values": SOURCE_VERIFICATION_STATES},
        "verification_evidence": {"kind": "null-or-any"},
    },
    "claims": {
        "record_id": {"kind": "id", "segment": "CLM"},
        "batch_ref": {"kind": "id", "segment": "BAT"},
        "attribution_class": {"kind": "enum", "values": ATTRIBUTION_CLASSES},
        "verification_state": {"kind": "enum", "values": CLAIM_VERIFICATION_STATES},
        "byte_evidence": {"kind": "null-or-any"},
        "limitations": {"kind": "null-or-list"},
    },
    "relationships": {
        "record_id": {"kind": "id", "segment": "REL"},
        "left_ref": {"kind": "id"},
        "right_ref": {"kind": "id"},
        "relationship_type": {"kind": "enum", "values": RELATIONSHIP_TYPES},
        "verification_state": {
            "kind": "enum",
            "values": RELATIONSHIP_VERIFICATION_STATES,
        },
    },
    "unresolved": {
        "record_id": {"kind": "id", "segment": "UNR"},
        "state": {"kind": "enum", "values": UNRESOLVED_STATES},
    },
    "corrections": {
        "record_id": {"kind": "id", "segment": "COR"},
        "target_ref": {"kind": "id"},
        "correction_kind": {"kind": "enum", "values": CORRECTION_KINDS},
        "reciprocal_ref": {"kind": "null-or-id", "segment": "COR"},
    },
    "non_admitted": {
        "record_id": {"kind": "id", "segment": "NAD"},
        "carrier_batch_ref": {"kind": "id", "segment": "BAT"},
        "carrier_member_sha256": {"kind": "digest"},
        "presence": {"kind": "enum", "values": PRESENCE_STATES},
        "admission_status": {"kind": "enum", "values": ADMISSION_STATES},
        "executable_status": {"kind": "enum", "values": EXECUTABLE_STATES},
        "normative_status": {"kind": "enum", "values": NORMATIVE_STATES},
    },
}

#: Fields that may never hold the empty string. CONTRACT.md section 7 keeps
#: null, "not-supplied" and "" apart; a field admitting none of the latter two
#: refuses them rather than coercing.
#: The closed key set of the `byte_evidence` block. CONTRACT.md section 11.2
#: requires closure "at the root and in every nested block", so this block is
#: declared rather than left free-form; `carrier_batch_ref` inside it is a
#: record id and is resolved by the reference-integrity rule like any other.
BYTE_EVIDENCE_KEYS = frozenset(
    {"carrier_batch_ref", "carrier_member_sha256", "bibliography_entry_index"}
)

#: Fields holding material exactly as supplied. CONTRACT.md section 6.2 stores
#: these byte-for-byte, so a character-class scan must not refuse them: a
#: supplied value carrying a non-ASCII digit would otherwise make preservation
#: and validation unsatisfiable at the same time.
SUPPLIED_VERBATIM_FIELDS = frozenset({"supplied_locator", "supplied_text"})

#: Fields whose vocabulary has its own refusal token, so a bad value is not
#: flattened into the generic one.
ATTRIBUTION_FIELDS = frozenset({"attribution_class"})
VERIFICATION_FIELDS = frozenset({"verification_state", "retrieval_state", "state"})

NO_EMPTY_STRING_FIELDS = frozenset(
    {
        "origin_id",
        "record_id",
        "member_filename",
        "supplied_locator",
        "normalized_locator",
        "normalized_identifier",
        "supplied_text",
    }
)

WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }
)


def has_non_ascii_digit(value: str) -> bool:
    """True when a decimal digit outside ASCII appears.

    ``int()`` parses Arabic-Indic and Devanagari digits, so a value that looks
    numeric to a reader can carry characters no ASCII pattern would admit.
    """
    for character in value:
        if character.isdigit() and not ("0" <= character <= "9"):
            return True
        if unicodedata.category(character) == "Nd" and not ("0" <= character <= "9"):
            return True
    return False


def canonical_bytes(value) -> bytes:
    """Sorted keys, ASCII escaping, compact separators, no trailing newline.

    CONTRACT.md section 11.1. The committed ``ledger.json`` is exactly these
    bytes followed by a single newline; the newline is a property of the file,
    never of the canonical form.
    """
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":")
    ).encode("utf-8")


def source_identifier(record) -> str:
    """Derive a source identifier from its introducing batch ordinal alone.

    Declared on the acceptance surface (CONTRACT.md section 11a) so the suite
    can call it on blinded, flipped and permuted inputs. It reads exactly one
    field. It does not read ``record_id``, so it cannot agree with a stored
    identifier by echoing it, and it reads no locator-derived value, so no
    locator can move an identifier.
    """
    introducing = record["introducing_batch_ref"]
    return "G7S-SRC-" + introducing.split("-")[2]
