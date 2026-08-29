"""``general-v7-technology-ledger-v1`` -- synthetic implementation candidate.

This package module carries the shared implementation core: the frozen
vocabularies, the refusal classes, the pure in-memory schema validator, the
single-file validation pipeline and the command-line entry point. The two
public surfaces the acceptance suite names -- ``schema`` and ``validate`` --
bind their exports from this module.

Why the core lives here and not in ``schema.py``: the acceptance control
GV7-S-028 closes every production module over a standard-library import
allowlist with no sibling carve-out, refuses relative imports, and the
call-name tripwire bans every dynamic-import mechanism. ``validate`` must
still raise subclasses of the one ``schema.LedgerError`` object, and the
determinism control runs ``python -m experiments.general_v7_ledger.validate``
in a fresh process. The only location the import system itself guarantees to
execute before either surface, in both execution modes, is this package
module; the surfaces then bind the shared objects from ``sys.modules``, which
imports nothing.

Everything in this candidate is synthetic. No record here describes a real
person, product, organization, source or event, every locator uses the
reserved ``example.invalid`` name, and a green suite proves conformance to
the frozen contract -- never the truth of any recorded claim.
"""

from __future__ import annotations

import json
import ntpath
import os
import re
import stat
import sys

# --------------------------------------------------------------------------
# Frozen identity. CONTRACT.md section 1.
# --------------------------------------------------------------------------

SCHEMA_ID = "source-record-v3"
LEDGER_ID = "general-v7-technology-ledger-v1"
CORPUS = "GENERAL V7 TECHNOLOGY CORPUS"
INTAKE_STATE = "intake-complete"
NOT_SUPPLIED = "not-supplied"

# ``[0-9]`` is load-bearing: \d admits Arabic-Indic and Devanagari digits.
ID_PATTERN = r"\AGV7-(BAT|SRC|CLM|REL|UNR|ART|COR)-[0-9]{4}\Z"
_ID_RE = re.compile(ID_PATTERN)

# --------------------------------------------------------------------------
# Closed vocabularies. CONTRACT.md section 7, transcribed exactly.
# --------------------------------------------------------------------------

BATCH_KINDS = ("source-bearing", "artifact-bearing", "bibliography-metadata")

ROLES = (
    "relay-agent",
    "operator",
    "auditor",
    "analysis-seat",
    "external-author",
    "unattributed",
)

ATTRIBUTION_CLASSES = (
    "direct-source",
    "source-derived-excerpt",
    "aura-summary",
    "aura-inference",
    "aura-capability-claim",
    "kev-observation",
    "kev-authorization",
    "jack-inference-or-audit",
    "eighty-four-inference",
    "implementation-proposal",
    "verified-implementation-evidence",
)

RETIRED_ATTRIBUTION_CLASSES = ("kev-observation-or-authorization",)

CLAIM_ATTRIBUTION_CLASSES = tuple(
    value
    for value in ATTRIBUTION_CLASSES
    if value != "verified-implementation-evidence"
)

RELATIONSHIP_ATTRIBUTION_CLASSES = tuple(
    value
    for value in ATTRIBUTION_CLASSES
    if value != "verified-implementation-evidence"
)

RESERVED_UNUSED_ATTRIBUTION_CLASSES = ("verified-implementation-evidence",)

RETRIEVAL_STATES = ("not-attempted",)
SOURCE_VERIFICATION_STATES = ("supplied-unretrieved",)
CLAIM_VERIFICATION_STATES = ("unverified",)
RELATIONSHIP_VERIFICATION_STATES = ("unverified",)
UNRESOLVED_STATES = ("unresolved",)
PRESERVATION_STATES = ("preserved",)
EXECUTABLE_STATES = ("non-executable",)
IDENTITY_ORIGINS = ("supplied", "generated")

METADATA_PROVENANCE = (
    "supplied-by-carrier",
    "supplied-by-operator",
    "derived-from-supplied-text",
    "not-supplied",
)

LOCATOR_ABSENCE_REASONS = (
    "no-exact-locator-supplied",
    "locator-withheld-by-carrier",
    "locator-not-applicable",
)

RELATIONSHIP_TYPES = (
    "duplicate-of-supplied-material",
    "conflicts-with",
    "follow-up-to",
    "mirror-of-supplied-material",
    "same-supplied-topic",
    "derived-from-supplied-material",
)

RELATIONSHIP_BASES = (
    "recorded-by-inspection",
    "recorded-from-supplied-material",
    "recorded-as-proposed-elsewhere",
)

CORRECTION_KINDS = ("correction", "contest", "successor")

ARTIFACT_CLASSES = (
    "premature-synthesis",
    "premature-master-prompt",
    "premature-authorization",
)

ORDINARY_DISPOSITION = "ordinary"

SAFETY_DISPOSITIONS = (
    "ordinary",
    "quarantined-access-control-avoidance",
    "quarantined-covert-communication",
    "quarantined-credential-or-personal-data",
    "quarantined-unauthorized-external-interaction",
    "quarantined-self-replication-or-mutation",
    "quarantined-hidden-monitoring",
    "quarantined-unsigned-native-execution",
    "quarantined-destructive-storage-or-cooling",
)

CONFLICT_FAMILIES = (
    "ox-alpha-versus-qwen-core-identity",
    "local-only-versus-external-endpoints",
    "modular-hot-swap-versus-monolith",
    "zero-dependency-versus-third-party-dependencies",
    "transient-agents-versus-persistent-residency",
    "no-magic-numbers-versus-fixed-thresholds",
    "immutable-raw-provenance-versus-raw-deletion",
    "human-oversight-versus-autonomous-execution",
    "aura-capability-inconsistency",
    "missing-source-identity-or-bibliography-data",
    "unsupported-hardware-or-product-claim",
    "scientific-analogy-overreach",
    "quarantined-security-or-privacy-proposal",
)

LABEL_MAX = 128
TEXT_MAX = 8192

# A bound on NESTED lists only, never on a root collection.
LIST_MAX = 64

# A resource ceiling on root collections, never a frozen factual total.
ROOT_COLLECTION_MAX = 4096

MAX_LEDGER_BYTES = 4194304

# --------------------------------------------------------------------------
# Closed shapes. CONTRACT.md section 6.
# --------------------------------------------------------------------------

ROOT_KEYS = (
    "schema",
    "ledger_id",
    "corpus",
    "intake_state",
    "batches",
    "sources",
    "claims",
    "relationships",
    "unresolved",
    "artifacts",
    "corrections",
)

COLLECTION_KEYS = (
    "batches",
    "sources",
    "claims",
    "relationships",
    "unresolved",
    "artifacts",
    "corrections",
)

KEYS_BY_COLLECTION = {
    "batches": (
        "batch_id",
        "batch_ordinal",
        "batch_kind",
        "introduces_sources",
        "introduces_artifacts",
        "updates_sources",
        "supplied_by_role",
        "supplied_by_label",
        "notes",
    ),
    "sources": (
        "source_id",
        "batch_ref",
        "supplied_title",
        "supplied_creator",
        "supplied_channel",
        "supplied_locator",
        "normalized_locator",
        "locator_absence",
        "supplied_date",
        "normalized_date",
        "carrier_role",
        "carrier_label",
        "upstream_attribution",
        "metadata_provenance",
        "retrieval_state",
        "verification_state",
        "limitations",
        "safety_dispositions",
        "supersedes",
    ),
    "claims": (
        "claim_id",
        "source_ref",
        "batch_ref",
        "claim_text",
        "attribution_class",
        "evidence_basis",
        "limitations",
        "safety_dispositions",
        "verification_state",
        "supersedes",
    ),
    "relationships": (
        "relationship_id",
        "left_ref",
        "right_ref",
        "relationship_type",
        "basis",
        "attribution_class",
        "verification_state",
        "limitations",
        "recorded_by_role",
        "recorded_by_label",
    ),
    "unresolved": (
        "unresolved_id",
        "conflict_family",
        "statement",
        "positions",
        "refs",
        "resolution_state",
        "recorded_by_role",
        "recorded_by_label",
    ),
    "artifacts": (
        "artifact_id",
        "introducing_batch",
        "artifact_class",
        "identity_origin",
        "preservation_status",
        "rejection_basis",
        "executable_status",
        "safety_dispositions",
        "summary",
    ),
    "corrections": (
        "correction_id",
        "target_ref",
        "correction_kind",
        "statement",
        "recorded_by_role",
        "recorded_by_label",
    ),
}

ID_FIELD_BY_COLLECTION = {
    "batches": "batch_id",
    "sources": "source_id",
    "claims": "claim_id",
    "relationships": "relationship_id",
    "unresolved": "unresolved_id",
    "artifacts": "artifact_id",
    "corrections": "correction_id",
}

_SEGMENT_BY_COLLECTION = {
    "batches": "BAT",
    "sources": "SRC",
    "claims": "CLM",
    "relationships": "REL",
    "unresolved": "UNR",
    "artifacts": "ART",
    "corrections": "COR",
}

_COLLECTION_BY_SEGMENT = {
    segment: collection for collection, segment in _SEGMENT_BY_COLLECTION.items()
}

# Inclusive (minimum, maximum) length for every root collection. The exact
# figures for batches, sources and artifacts are frozen bounds from
# CONTRACT.md section 5; no emitted count is ever read from them.
_BATCH_ORDINAL_MAX = 63

ROOT_COLLECTION_BOUNDS = {
    "batches": (63, 63),
    "sources": (61, 61),
    "artifacts": (3, 3),
    "claims": (61, ROOT_COLLECTION_MAX),
    "relationships": (1, ROOT_COLLECTION_MAX),
    "unresolved": (1, ROOT_COLLECTION_MAX),
    "corrections": (0, ROOT_COLLECTION_MAX),
}

# --------------------------------------------------------------------------
# Refusal classes and the closed refusal vocabulary. CONTRACT.md section 9.
# --------------------------------------------------------------------------

REFUSAL_TOKENS = (
    "collection-length-invalid",
    "correction-target-not-permitted",
    "date-pairing-invalid",
    "disposition-ordinary-not-exclusive",
    "enum-value-invalid",
    "float-refused",
    "identifier-duplicate",
    "identifier-malformed",
    "identifier-wrong-collection",
    "int-out-of-range",
    "introduction-not-reciprocal",
    "json-duplicate-key",
    "json-malformed",
    "key-not-exact-str",
    "ledger-bytes-ceiling",
    "ledger-encoding-invalid",
    "list-duplicate-item",
    "list-length-invalid",
    "locator-not-https",
    "locator-pairing-invalid",
    "missing-key",
    "ordinal-id-mismatch",
    "path-device-namespace",
    "path-drive-relative",
    "path-missing",
    "path-not-file",
    "path-reserved-name",
    "path-symlink-refused",
    "reference-not-found",
    "reference-wrong-kind",
    "relationship-duplicate",
    "relationship-endpoint-kind-mismatch",
    "relationship-self",
    "root-not-object",
    "string-not-encodable",
    "supersedes-not-permitted",
    "text-length-invalid",
    "type-not-exact",
    "undeclared-key",
)


class LedgerError(Exception):
    """The single refusal base.

    A refusal carries exactly a closed token and a schema-declared path.
    There is no rejected-value slot: the carrier never stores, renders or
    hashes any input, and its string form is the token alone.
    """

    def __init__(self, token, path=()):
        Exception.__init__(self, token)
        self.token = token
        self.path = tuple(path)


class LedgerPathError(LedgerError):
    """Stage 1: lexical and path-entry refusals."""


class LedgerCeilingError(LedgerError):
    """Stage 2: the byte ceiling over captured bytes."""


class LedgerInputError(LedgerError):
    """Stage 3: decoding and JSON parsing, including duplicate keys."""


def _refuse(token, path=()):
    raise LedgerError(token, path) from None


def _refuse_path(token):
    raise LedgerPathError(token) from None


def _refuse_ceiling(token):
    raise LedgerCeilingError(token) from None


def _refuse_input(token):
    raise LedgerInputError(token) from None


# --------------------------------------------------------------------------
# Stage 4: exact builtin types, key exactness, float refusal, and the
# document-wide surrogate screen. The walk is iterative so its depth budget
# is the document's, not the interpreter stack's, and it checks the exact
# type of every container BEFORE iterating it, so no hook on a hostile
# subclass can run ahead of its refusal.
# --------------------------------------------------------------------------


def _screen_string(value):
    if value.isascii():
        return
    for character in value:
        code = ord(character)
        if 0xD800 <= code <= 0xDFFF:
            _refuse("string-not-encodable")


def _screen_tree(root):
    stack = [root]
    while stack:
        node = stack.pop()
        kind = type(node)
        if kind is str:
            _screen_string(node)
        elif kind is dict:
            for key in node:
                if type(key) is not str:
                    _refuse("key-not-exact-str")
                _screen_string(key)
            stack.extend(node.values())
        elif kind is list:
            stack.extend(node)
        elif kind is int or kind is bool or node is None:
            pass
        elif kind is float:
            _refuse("float-refused")
        else:
            _refuse("type-not-exact")


# --------------------------------------------------------------------------
# Field-level helpers. Every path element is a declared key name or an int
# index; no input-derived value ever enters a path.
# --------------------------------------------------------------------------


def _exact_str(value, path):
    if type(value) is not str:
        _refuse("type-not-exact", path)


def _text(value, path, high):
    _exact_str(value, path)
    if not 1 <= len(value) <= high:
        _refuse("text-length-invalid", path)


def _enum(value, vocabulary, path):
    _exact_str(value, path)
    if value not in vocabulary:
        _refuse("enum-value-invalid", path)


def _identifier(value, segment, path):
    _exact_str(value, path)
    if _ID_RE.match(value) is None:
        _refuse("identifier-malformed", path)
    if value[4:7] != segment:
        _refuse("identifier-wrong-collection", path)


def _reference_shape(value, path):
    _exact_str(value, path)
    if _ID_RE.match(value) is None:
        _refuse("identifier-malformed", path)


def _string_list(value, path, low, high, item_max):
    # Shape before content: length and duplicate-freeness are section-9
    # "Shape" rules, so they precede the per-item scalar bounds. Item
    # exactness must still precede the set-based duplicate check, because a
    # non-string item is unhashable in general and exactness is stage 4.
    if type(value) is not list:
        _refuse("type-not-exact", path)
    if not low <= len(value) <= high:
        _refuse("list-length-invalid", path)
    for index, item in enumerate(value):
        _exact_str(item, path + (index,))
    if len(value) != len(set(value)):
        _refuse("list-duplicate-item", path)
    for index, item in enumerate(value):
        if not 1 <= len(item) <= item_max:
            _refuse("text-length-invalid", path + (index,))


def _id_list(value, path, low=0):
    if type(value) is not list:
        _refuse("type-not-exact", path)
    if not low <= len(value) <= LIST_MAX:
        _refuse("list-length-invalid", path)
    for index, item in enumerate(value):
        _exact_str(item, path + (index,))
    if len(value) != len(set(value)):
        _refuse("list-duplicate-item", path)
    for index, item in enumerate(value):
        if _ID_RE.match(item) is None:
            _refuse("identifier-malformed", path + (index,))


def _dispositions(value, path):
    if type(value) is not list:
        _refuse("type-not-exact", path)
    if not 1 <= len(value) <= LIST_MAX:
        _refuse("list-length-invalid", path)
    for index, item in enumerate(value):
        _exact_str(item, path + (index,))
    if len(value) != len(set(value)):
        _refuse("list-duplicate-item", path)
    for index, item in enumerate(value):
        if item not in SAFETY_DISPOSITIONS:
            _refuse("enum-value-invalid", path + (index,))
    if ORDINARY_DISPOSITION in value and len(value) != 1:
        _refuse("disposition-ordinary-not-exclusive", path)


def _supersedes_closed(value, path):
    if value is None:
        return
    if type(value) is dict:
        _refuse("supersedes-not-permitted", path)
    _refuse("type-not-exact", path)


_ISO_DATE_RE = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")

_MONTH_LENGTHS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _is_calendar_date(value):
    if _ISO_DATE_RE.match(value) is None:
        return False
    year = int(value[0:4])
    month = int(value[5:7])
    day = int(value[8:10])
    if not 1 <= month <= 12:
        return False
    length = _MONTH_LENGTHS[month - 1]
    if month == 2 and year % 4 == 0 and (year % 100 != 0 or year % 400 == 0):
        length = 29
    return 1 <= day <= length


_HTTPS_RE = re.compile(r"\Ahttps://[^\s/?#]+[^\s]*\Z")


# --------------------------------------------------------------------------
# Stage 5 and 6: closed shapes, vocabularies, bounds and domain rules,
# record by record.
# --------------------------------------------------------------------------


def _check_record_shape(record, collection, index):
    if type(record) is not dict:
        _refuse("type-not-exact", (collection, index))
    declared = KEYS_BY_COLLECTION[collection]
    declared_set = frozenset(declared)
    for field in record:
        if field not in declared_set:
            _refuse("undeclared-key", (collection, index))
    for field in declared:
        if field not in record:
            _refuse("missing-key", (collection, index, field))


def _check_batch(record, path):
    _identifier(record["batch_id"], "BAT", path + ("batch_id",))
    ordinal = record["batch_ordinal"]
    if type(ordinal) is not int:
        _refuse("type-not-exact", path + ("batch_ordinal",))
    if not 1 <= ordinal <= _BATCH_ORDINAL_MAX:
        _refuse("int-out-of-range", path + ("batch_ordinal",))
    if int(record["batch_id"][8:12]) != ordinal:
        _refuse("ordinal-id-mismatch", path + ("batch_ordinal",))
    _enum(record["batch_kind"], BATCH_KINDS, path + ("batch_kind",))
    _id_list(record["introduces_sources"], path + ("introduces_sources",))
    _id_list(record["introduces_artifacts"], path + ("introduces_artifacts",))
    _id_list(record["updates_sources"], path + ("updates_sources",))
    _enum(record["supplied_by_role"], ROLES, path + ("supplied_by_role",))
    _text(record["supplied_by_label"], path + ("supplied_by_label",), LABEL_MAX)
    _text(record["notes"], path + ("notes",), TEXT_MAX)


def _check_source(record, path):
    _identifier(record["source_id"], "SRC", path + ("source_id",))
    _reference_shape(record["batch_ref"], path + ("batch_ref",))
    _text(record["supplied_title"], path + ("supplied_title",), TEXT_MAX)
    _text(record["supplied_creator"], path + ("supplied_creator",), LABEL_MAX)
    _text(record["supplied_channel"], path + ("supplied_channel",), LABEL_MAX)

    supplied = record["supplied_locator"]
    if supplied is not None:
        _text(supplied, path + ("supplied_locator",), TEXT_MAX)
    normalized = record["normalized_locator"]
    if normalized is not None:
        _exact_str(normalized, path + ("normalized_locator",))
    absence = record["locator_absence"]
    if absence is not None:
        _exact_str(absence, path + ("locator_absence",))
    if (supplied is None) != (normalized is None):
        _refuse("locator-pairing-invalid", path)
    if (absence is None) is (supplied is None):
        _refuse("locator-pairing-invalid", path)
    if normalized is not None:
        if _HTTPS_RE.match(normalized) is None or not normalized.isascii():
            _refuse("locator-not-https", path + ("normalized_locator",))
        if len(normalized) > TEXT_MAX:
            _refuse("text-length-invalid", path + ("normalized_locator",))
    if absence is not None and absence not in LOCATOR_ABSENCE_REASONS:
        _refuse("enum-value-invalid", path + ("locator_absence",))

    _text(record["supplied_date"], path + ("supplied_date",), LABEL_MAX)
    normalized_date = record["normalized_date"]
    if normalized_date is not None:
        _exact_str(normalized_date, path + ("normalized_date",))
        if not _is_calendar_date(normalized_date):
            _refuse("date-pairing-invalid", path + ("normalized_date",))
    if record["supplied_date"] == NOT_SUPPLIED and normalized_date is not None:
        _refuse("date-pairing-invalid", path + ("normalized_date",))

    _enum(record["carrier_role"], ROLES, path + ("carrier_role",))
    _text(record["carrier_label"], path + ("carrier_label",), LABEL_MAX)
    _text(
        record["upstream_attribution"], path + ("upstream_attribution",), TEXT_MAX
    )
    _enum(
        record["metadata_provenance"],
        METADATA_PROVENANCE,
        path + ("metadata_provenance",),
    )
    _enum(
        record["retrieval_state"], RETRIEVAL_STATES, path + ("retrieval_state",)
    )
    _enum(
        record["verification_state"],
        SOURCE_VERIFICATION_STATES,
        path + ("verification_state",),
    )
    _string_list(record["limitations"], path + ("limitations",), 1, LIST_MAX, TEXT_MAX)
    _dispositions(record["safety_dispositions"], path + ("safety_dispositions",))
    _supersedes_closed(record["supersedes"], path + ("supersedes",))


def _check_claim(record, path):
    _identifier(record["claim_id"], "CLM", path + ("claim_id",))
    _reference_shape(record["source_ref"], path + ("source_ref",))
    _reference_shape(record["batch_ref"], path + ("batch_ref",))
    _text(record["claim_text"], path + ("claim_text",), TEXT_MAX)
    _enum(
        record["attribution_class"],
        CLAIM_ATTRIBUTION_CLASSES,
        path + ("attribution_class",),
    )
    _text(record["evidence_basis"], path + ("evidence_basis",), TEXT_MAX)
    _string_list(record["limitations"], path + ("limitations",), 1, LIST_MAX, TEXT_MAX)
    _dispositions(record["safety_dispositions"], path + ("safety_dispositions",))
    _enum(
        record["verification_state"],
        CLAIM_VERIFICATION_STATES,
        path + ("verification_state",),
    )
    _supersedes_closed(record["supersedes"], path + ("supersedes",))


def _check_relationship(record, path):
    _identifier(record["relationship_id"], "REL", path + ("relationship_id",))
    _reference_shape(record["left_ref"], path + ("left_ref",))
    _reference_shape(record["right_ref"], path + ("right_ref",))
    _enum(
        record["relationship_type"],
        RELATIONSHIP_TYPES,
        path + ("relationship_type",),
    )
    _enum(record["basis"], RELATIONSHIP_BASES, path + ("basis",))
    _enum(
        record["attribution_class"],
        RELATIONSHIP_ATTRIBUTION_CLASSES,
        path + ("attribution_class",),
    )
    _enum(
        record["verification_state"],
        RELATIONSHIP_VERIFICATION_STATES,
        path + ("verification_state",),
    )
    _string_list(record["limitations"], path + ("limitations",), 1, LIST_MAX, TEXT_MAX)
    _enum(record["recorded_by_role"], ROLES, path + ("recorded_by_role",))
    _text(record["recorded_by_label"], path + ("recorded_by_label",), LABEL_MAX)


def _check_unresolved(record, path):
    _identifier(record["unresolved_id"], "UNR", path + ("unresolved_id",))
    _enum(
        record["conflict_family"], CONFLICT_FAMILIES, path + ("conflict_family",)
    )
    _text(record["statement"], path + ("statement",), TEXT_MAX)
    _string_list(record["positions"], path + ("positions",), 2, 8, TEXT_MAX)
    _id_list(record["refs"], path + ("refs",), low=1)
    _enum(
        record["resolution_state"],
        UNRESOLVED_STATES,
        path + ("resolution_state",),
    )
    _enum(record["recorded_by_role"], ROLES, path + ("recorded_by_role",))
    _text(record["recorded_by_label"], path + ("recorded_by_label",), LABEL_MAX)


def _check_artifact(record, path):
    _identifier(record["artifact_id"], "ART", path + ("artifact_id",))
    _reference_shape(record["introducing_batch"], path + ("introducing_batch",))
    _enum(record["artifact_class"], ARTIFACT_CLASSES, path + ("artifact_class",))
    _enum(
        record["identity_origin"], IDENTITY_ORIGINS, path + ("identity_origin",)
    )
    _enum(
        record["preservation_status"],
        PRESERVATION_STATES,
        path + ("preservation_status",),
    )
    _text(record["rejection_basis"], path + ("rejection_basis",), TEXT_MAX)
    _enum(
        record["executable_status"],
        EXECUTABLE_STATES,
        path + ("executable_status",),
    )
    _dispositions(record["safety_dispositions"], path + ("safety_dispositions",))
    _text(record["summary"], path + ("summary",), TEXT_MAX)


def _check_correction(record, path):
    _identifier(record["correction_id"], "COR", path + ("correction_id",))
    _reference_shape(record["target_ref"], path + ("target_ref",))
    _enum(record["correction_kind"], CORRECTION_KINDS, path + ("correction_kind",))
    _text(record["statement"], path + ("statement",), TEXT_MAX)
    _enum(record["recorded_by_role"], ROLES, path + ("recorded_by_role",))
    _text(record["recorded_by_label"], path + ("recorded_by_label",), LABEL_MAX)


_RECORD_CHECKS = {
    "batches": _check_batch,
    "sources": _check_source,
    "claims": _check_claim,
    "relationships": _check_relationship,
    "unresolved": _check_unresolved,
    "artifacts": _check_artifact,
    "corrections": _check_correction,
}


# --------------------------------------------------------------------------
# Stage 7: identifiers, references, relationship domain rules, reciprocity.
# --------------------------------------------------------------------------


def _check_identifier_uniqueness(payload):
    seen = set()
    for collection in COLLECTION_KEYS:
        field = ID_FIELD_BY_COLLECTION[collection]
        for index, record in enumerate(payload[collection]):
            value = record[field]
            if value in seen:
                _refuse("identifier-duplicate", (collection, index, field))
            seen.add(value)


def _check_reference(value, allowed_segments, path, ids_by_collection):
    segment = value[4:7]
    if segment not in allowed_segments:
        _refuse("reference-wrong-kind", path)
    if value not in ids_by_collection[_COLLECTION_BY_SEGMENT[segment]]:
        _refuse("reference-not-found", path)


def _check_reference_list(values, allowed_segments, path, ids_by_collection):
    for index, value in enumerate(values):
        _check_reference(
            value, allowed_segments, path + (index,), ids_by_collection
        )


def _check_references(payload):
    ids_by_collection = {
        collection: {
            record[ID_FIELD_BY_COLLECTION[collection]]
            for record in payload[collection]
        }
        for collection in COLLECTION_KEYS
    }

    for index, record in enumerate(payload["batches"]):
        path = ("batches", index)
        _check_reference_list(
            record["introduces_sources"],
            ("SRC",),
            path + ("introduces_sources",),
            ids_by_collection,
        )
        _check_reference_list(
            record["introduces_artifacts"],
            ("ART",),
            path + ("introduces_artifacts",),
            ids_by_collection,
        )
        _check_reference_list(
            record["updates_sources"],
            ("SRC",),
            path + ("updates_sources",),
            ids_by_collection,
        )
    for index, record in enumerate(payload["sources"]):
        _check_reference(
            record["batch_ref"],
            ("BAT",),
            ("sources", index, "batch_ref"),
            ids_by_collection,
        )
    for index, record in enumerate(payload["claims"]):
        _check_reference(
            record["source_ref"],
            ("SRC",),
            ("claims", index, "source_ref"),
            ids_by_collection,
        )
        _check_reference(
            record["batch_ref"],
            ("BAT",),
            ("claims", index, "batch_ref"),
            ids_by_collection,
        )
    for index, record in enumerate(payload["unresolved"]):
        _check_reference_list(
            record["refs"],
            ("SRC", "CLM"),
            ("unresolved", index, "refs"),
            ids_by_collection,
        )
    for index, record in enumerate(payload["artifacts"]):
        _check_reference(
            record["introducing_batch"],
            ("BAT",),
            ("artifacts", index, "introducing_batch"),
            ids_by_collection,
        )
    for index, record in enumerate(payload["corrections"]):
        target = record["target_ref"]
        path = ("corrections", index, "target_ref")
        if target[4:7] == "COR":
            _refuse("correction-target-not-permitted", path)
        _check_reference(
            target,
            ("BAT", "SRC", "CLM", "REL", "UNR", "ART"),
            path,
            ids_by_collection,
        )

    triples = set()
    for index, record in enumerate(payload["relationships"]):
        path = ("relationships", index)
        left = record["left_ref"]
        right = record["right_ref"]
        _check_reference(
            left, ("SRC", "CLM"), path + ("left_ref",), ids_by_collection
        )
        _check_reference(
            right, ("SRC", "CLM"), path + ("right_ref",), ids_by_collection
        )
        if left[4:7] != right[4:7]:
            _refuse("relationship-endpoint-kind-mismatch", path)
        if left == right:
            _refuse("relationship-self", path)
        triple = (left, right, record["relationship_type"])
        if triple in triples:
            _refuse("relationship-duplicate", path)
        triples.add(triple)


def _check_reciprocity(payload):
    batches_by_id = {record["batch_id"]: record for record in payload["batches"]}
    sources_by_id = {record["source_id"]: record for record in payload["sources"]}
    artifacts_by_id = {
        record["artifact_id"]: record for record in payload["artifacts"]
    }

    for index, source in enumerate(payload["sources"]):
        batch = batches_by_id[source["batch_ref"]]
        if source["source_id"] not in batch["introduces_sources"]:
            _refuse("introduction-not-reciprocal", ("sources", index))
    for index, artifact in enumerate(payload["artifacts"]):
        batch = batches_by_id[artifact["introducing_batch"]]
        if artifact["artifact_id"] not in batch["introduces_artifacts"]:
            _refuse("introduction-not-reciprocal", ("artifacts", index))
    for index, batch in enumerate(payload["batches"]):
        for source_id in batch["introduces_sources"]:
            if sources_by_id[source_id]["batch_ref"] != batch["batch_id"]:
                _refuse("introduction-not-reciprocal", ("batches", index))
        for artifact_id in batch["introduces_artifacts"]:
            introducing = artifacts_by_id[artifact_id]["introducing_batch"]
            if introducing != batch["batch_id"]:
                _refuse("introduction-not-reciprocal", ("batches", index))


# --------------------------------------------------------------------------
# The pure in-memory validator. Non-mutating; refusal is staged and the
# earliest applicable stage wins.
# --------------------------------------------------------------------------


def validate_ledger(payload):
    """Validate one in-memory ledger document; return it unchanged."""
    if type(payload) is not dict:
        # Decided from the real class's MRO, never from isinstance: a
        # hostile non-dict carrying a __class__ property would have that
        # descriptor invoked by isinstance before its own refusal.
        if dict in type(payload).__mro__:
            _refuse("type-not-exact")
        _refuse("root-not-object")
    _screen_tree(payload)

    # Stage 5 runs document-wide before stage 6: root key set, collection
    # bounds (a section-9 "Shape" rule) and every record's closed key set
    # all precede any vocabulary, scalar-bound or domain check, so a shape
    # fault in a later collection is never outrun by a value fault in an
    # earlier one.
    declared = frozenset(ROOT_KEYS)
    for key in payload:
        if key not in declared:
            _refuse("undeclared-key")
    for key in ROOT_KEYS:
        if key not in payload:
            _refuse("missing-key", (key,))

    for key in COLLECTION_KEYS:
        value = payload[key]
        if type(value) is not list:
            _refuse("type-not-exact", (key,))
        low, high = ROOT_COLLECTION_BOUNDS[key]
        if not low <= len(value) <= high:
            _refuse("collection-length-invalid", (key,))

    for collection in COLLECTION_KEYS:
        for index, record in enumerate(payload[collection]):
            _check_record_shape(record, collection, index)

    for key, expected in (
        ("schema", SCHEMA_ID),
        ("ledger_id", LEDGER_ID),
        ("corpus", CORPUS),
        ("intake_state", INTAKE_STATE),
    ):
        value = payload[key]
        if type(value) is not str:
            _refuse("type-not-exact", (key,))
        if value != expected:
            _refuse("enum-value-invalid", (key,))

    for collection in COLLECTION_KEYS:
        check = _RECORD_CHECKS[collection]
        for index, record in enumerate(payload[collection]):
            check(record, (collection, index))

    _check_identifier_uniqueness(payload)
    _check_references(payload)
    _check_reciprocity(payload)
    return payload


# --------------------------------------------------------------------------
# Stage 1 through 3: the single-file pipeline. The interface is exactly one
# explicitly supplied file path; nothing else locates the input, and no
# code path retrieves, opens, resolves or contacts a locator.
# --------------------------------------------------------------------------

_WINDOWS_RESERVED_NAMES = frozenset(
    ("CON", "PRN", "AUX", "NUL")
    + tuple("COM" + str(number) for number in range(1, 10))
    + tuple("LPT" + str(number) for number in range(1, 10))
)

_REPARSE_NAME_SURROGATE_BIT = 0x20000000

_SEPARATOR_RE = re.compile(r"[\\/]")


def _component_is_reserved(component):
    trimmed = component.rstrip(" .")
    stem = trimmed.split(".", 1)[0].rstrip(" .")
    return stem.upper() in _WINDOWS_RESERVED_NAMES


def _is_redirecting(status):
    if stat.S_ISLNK(status.st_mode):
        return True
    attributes = getattr(status, "st_file_attributes", 0)
    if not attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        return False
    tag = getattr(status, "st_reparse_tag", 0)
    return bool(tag & _REPARSE_NAME_SURROGATE_BIT)


def _reject_duplicate_keys(pairs):
    keys = [key for key, _value in pairs]
    if len(keys) != len(set(keys)):
        _refuse_input("json-duplicate-key")
    return dict(pairs)


def validate_ledger_file(path):
    """Validate the one supplied file; return the validated payload."""
    try:
        value = os.fspath(path)
    except TypeError:
        _refuse_path("path-not-file")
    if type(value) is not str:
        _refuse_path("path-not-file")
    if "\x00" in value:
        _refuse_path("path-missing")

    normalized = value.replace("/", "\\")
    if normalized.startswith("\\\\?\\") or normalized.startswith("\\\\.\\"):
        _refuse_path("path-device-namespace")
    drive, rest = ntpath.splitdrive(value)
    if drive and not rest.startswith(("\\", "/")):
        _refuse_path("path-drive-relative")
    for component in _SEPARATOR_RE.split(value):
        if component and _component_is_reserved(component):
            _refuse_path("path-reserved-name")

    chain = []
    current = value
    while True:
        chain.append(current)
        parent = ntpath.dirname(current)
        if not parent or parent == current:
            break
        current = parent
    status = None
    for entry in reversed(chain):
        try:
            status = os.lstat(entry)
        except FileNotFoundError as error:
            # ERROR_FILENAME_EXCED_RANGE (206) also maps to
            # FileNotFoundError on Windows; too long is not missing, so it
            # propagates rather than being disguised as a refusal.
            if getattr(error, "winerror", None) == 206:
                raise
            _refuse_path("path-missing")
        except ValueError:
            _refuse_path("path-missing")
        except OSError as error:
            # ERROR_INVALID_NAME (123): a name no Windows filesystem can
            # hold cannot exist anywhere, so it reads as absence -- a
            # decided semantics. Every other OSError (permission first
            # among them) propagates as itself, never disguised as a
            # refusal token.
            if getattr(error, "winerror", None) == 123:
                _refuse_path("path-missing")
            raise
        if _is_redirecting(status):
            _refuse_path("path-symlink-refused")
    if not stat.S_ISREG(status.st_mode):
        _refuse_path("path-not-file")

    with open(value, "rb") as handle:
        raw = handle.read(MAX_LEDGER_BYTES + 1)
    if len(raw) > MAX_LEDGER_BYTES:
        _refuse_ceiling("ledger-bytes-ceiling")

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _refuse_input("ledger-encoding-invalid")
    try:
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except (ValueError, RecursionError):
        _refuse_input("json-malformed")
    return validate_ledger(payload)


def main(argv):
    """Frozen command line: exit 0 on success, 1 on refusal, 2 on usage."""
    if type(argv) is not list or len(argv) != 1 or type(argv[0]) is not str:
        raise SystemExit(2)
    try:
        payload = validate_ledger_file(argv[0])
    except LedgerError as error:
        sys.stderr.buffer.write(error.token.encode("ascii") + b"\n")
        sys.stderr.buffer.flush()
        return 1
    summary = {
        "schema": payload["schema"],
        "ledger_id": payload["ledger_id"],
        "corpus": payload["corpus"],
        "intake_state": payload["intake_state"],
        "counts": {key: len(payload[key]) for key in COLLECTION_KEYS},
    }
    line = json.dumps(
        summary, sort_keys=True, ensure_ascii=True, separators=(",", ":")
    )
    sys.stdout.buffer.write(line.encode("ascii") + b"\n")
    sys.stdout.buffer.flush()
    return 0
