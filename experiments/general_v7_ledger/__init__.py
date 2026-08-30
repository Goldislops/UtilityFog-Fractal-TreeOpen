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
    "path-identity-changed",
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


#: The content stages, in the order section 9 freezes them, and the value the
#: selector rests at outside a staged pass.
_CONTENT_STAGES = (4, 5, 6)
_FINAL_STAGE = 6

#: A field that is not present at all. Its absence is a stage-5 fault, decided
#: by the record's own closed key set; every rule about its VALUE simply has
#: nothing to decide and steps over it, so one missing key can no longer mask
#: an exact-type fault elsewhere in the same record or document.
_ABSENT = object()


def _refuse_at(rule_stage, pass_stage, token, path=()):
    """Refuse only once the pass being decided has reached ``stage``.

    "The earliest applicable stage wins" ranges over the whole document, not
    over one record. A validator that runs every stage inside each record
    before moving on lets a stage-6 vocabulary fault in the first record outrun
    a stage-4 exact-type fault in the last, so the token reports the traversal
    rather than the fault. Running the one traversal once per stage, with the
    later stages deferred, makes the stage a property of the document.

    Deferring leaves the value's TYPE known good -- stage 4 has decided every
    exactness question before stage 5 or 6 is consulted -- but it does not make
    the value well formed. A rule that depends on a later-stage rule must guard
    on it explicitly; `ordinal-id-mismatch` is the one such rule here, and it
    checks the identifier is well formed before parsing its digits.

    ``pass_stage`` is an ARGUMENT, never module state. It was a module global
    once, and two concurrent validations then overwrote each other's selector:
    a document that had to be refused was accepted, because the fault was
    deferred on every pass its own validation ever ran. Nothing about which
    stage is being decided is shared between calls.
    """
    if pass_stage < rule_stage:
        return
    _refuse(token, path)


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
    if value is _ABSENT:
        return
    if type(value) is not str:
        _refuse("type-not-exact", path)


def _text(value, path, high, *, stage):
    if value is _ABSENT:
        return
    _exact_str(value, path)
    if not 1 <= len(value) <= high:
        _refuse_at(6, stage, "text-length-invalid", path)


def _enum(value, vocabulary, path, *, stage):
    if value is _ABSENT:
        return
    _exact_str(value, path)
    if value not in vocabulary:
        _refuse_at(6, stage, "enum-value-invalid", path)


def _identifier(value, segment, path, *, stage):
    if value is _ABSENT:
        return
    _exact_str(value, path)
    if _ID_RE.match(value) is None:
        _refuse_at(6, stage, "identifier-malformed", path)
    if value[4:7] != segment:
        _refuse_at(6, stage, "identifier-wrong-collection", path)


def _reference_shape(value, path, *, stage):
    if value is _ABSENT:
        return
    _exact_str(value, path)
    if _ID_RE.match(value) is None:
        _refuse_at(6, stage, "identifier-malformed", path)


def _string_list(value, path, low, high, item_max, *, stage):
    # Shape before content: length and duplicate-freeness are section-9
    # "Shape" rules, so they precede the per-item scalar bounds. Item
    # exactness must still precede the set-based duplicate check, because a
    # non-string item is unhashable in general and exactness is stage 4.
    if value is _ABSENT:
        return
    if type(value) is not list:
        _refuse("type-not-exact", path)
    if not low <= len(value) <= high:
        _refuse_at(5, stage, "list-length-invalid", path)
    for index, item in enumerate(value):
        _exact_str(item, path + (index,))
    if len(value) != len(set(value)):
        _refuse_at(5, stage, "list-duplicate-item", path)
    for index, item in enumerate(value):
        if not 1 <= len(item) <= item_max:
            _refuse_at(6, stage, "text-length-invalid", path + (index,))


def _id_list(value, path, low=0, *, stage):
    if value is _ABSENT:
        return
    if type(value) is not list:
        _refuse("type-not-exact", path)
    if not low <= len(value) <= LIST_MAX:
        _refuse_at(5, stage, "list-length-invalid", path)
    for index, item in enumerate(value):
        _exact_str(item, path + (index,))
    if len(value) != len(set(value)):
        _refuse_at(5, stage, "list-duplicate-item", path)
    for index, item in enumerate(value):
        if _ID_RE.match(item) is None:
            _refuse_at(6, stage, "identifier-malformed", path + (index,))


def _dispositions(value, path, *, stage):
    if value is _ABSENT:
        return
    if type(value) is not list:
        _refuse("type-not-exact", path)
    if not 1 <= len(value) <= LIST_MAX:
        _refuse_at(5, stage, "list-length-invalid", path)
    for index, item in enumerate(value):
        _exact_str(item, path + (index,))
    if len(value) != len(set(value)):
        _refuse_at(5, stage, "list-duplicate-item", path)
    for index, item in enumerate(value):
        if item not in SAFETY_DISPOSITIONS:
            _refuse_at(6, stage, "enum-value-invalid", path + (index,))
    if ORDINARY_DISPOSITION in value and len(value) != 1:
        _refuse_at(6, stage, "disposition-ordinary-not-exclusive", path)


def _supersedes_closed(value, path, *, stage):
    if value is _ABSENT or value is None:
        return
    if type(value) is dict:
        # A dict IS an exact builtin type, so this is not a stage-4 exactness
        # fault: v1 admits no supersession block, which is a closed-VALUE rule
        # at stage 5. Falling through to the type refusal after deferring would
        # have reported `type-not-exact` for it on the stage-4 pass.
        _refuse_at(5, stage, "supersedes-not-permitted", path)
        return
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


def _check_record_shape(record, collection, index, *, stage):
    """The record's closed key set, for the stage being decided.

    This no longer reports completeness, and the caller no longer skips a
    record because a declared key is absent: every value rule steps over
    ``_ABSENT``, so the fields that ARE present are still type checked on the
    stage-4 pass and a missing key can mask nothing.
    """
    if type(record) is not dict:
        _refuse("type-not-exact", (collection, index))
    declared = KEYS_BY_COLLECTION[collection]
    declared_set = frozenset(declared)
    for field in record:
        if field not in declared_set:
            _refuse_at(5, stage, "undeclared-key", (collection, index))
    for field in declared:
        if field not in record:
            _refuse_at(5, stage, "missing-key", (collection, index, field))


def _check_batch(record, path, *, stage):
    _identifier(record.get("batch_id", _ABSENT), "BAT", path + ("batch_id",), stage=stage)
    ordinal = record.get("batch_ordinal", _ABSENT)
    if ordinal is not _ABSENT:
        if type(ordinal) is not int:
            _refuse("type-not-exact", path + ("batch_ordinal",))
        if not 1 <= ordinal <= _BATCH_ORDINAL_MAX:
            _refuse_at(6, stage, "int-out-of-range", path + ("batch_ordinal",))
    # The ordinal must agree with the identifier's digits -- a rule that only
    # means anything once the identifier is well formed. `identifier-malformed`
    # is itself stage 6, so on the stage-4 pass it has deferred and those digits
    # need not be there; parsing them regardless raised a raw `ValueError` for
    # `batch_id = ""`. A malformed identifier is refused by its own rule.
    identifier = record.get("batch_id", _ABSENT)
    if identifier is not _ABSENT and ordinal is not _ABSENT:
        if _ID_RE.match(identifier) is not None:
            if int(identifier[8:12]) != ordinal:
                _refuse_at(6, stage, "ordinal-id-mismatch", path + ("batch_ordinal",))
    _enum(record.get("batch_kind", _ABSENT), BATCH_KINDS, path + ("batch_kind",), stage=stage)
    _id_list(record.get("introduces_sources", _ABSENT), path + ("introduces_sources",), stage=stage)
    _id_list(record.get("introduces_artifacts", _ABSENT), path + ("introduces_artifacts",), stage=stage)
    _id_list(record.get("updates_sources", _ABSENT), path + ("updates_sources",), stage=stage)
    _enum(record.get("supplied_by_role", _ABSENT), ROLES, path + ("supplied_by_role",), stage=stage)
    _text(record.get("supplied_by_label", _ABSENT), path + ("supplied_by_label",), LABEL_MAX, stage=stage)
    _text(record.get("notes", _ABSENT), path + ("notes",), TEXT_MAX, stage=stage)


def _check_source(record, path, *, stage):
    _identifier(record.get("source_id", _ABSENT), "SRC", path + ("source_id",), stage=stage)
    _reference_shape(record.get("batch_ref", _ABSENT), path + ("batch_ref",), stage=stage)
    _text(record.get("supplied_title", _ABSENT), path + ("supplied_title",), TEXT_MAX, stage=stage)
    _text(record.get("supplied_creator", _ABSENT), path + ("supplied_creator",), LABEL_MAX, stage=stage)
    _text(record.get("supplied_channel", _ABSENT), path + ("supplied_channel",), LABEL_MAX, stage=stage)

    supplied = record.get("supplied_locator", _ABSENT)
    if supplied is not None and supplied is not _ABSENT:
        _text(supplied, path + ("supplied_locator",), TEXT_MAX, stage=stage)
    normalized = record.get("normalized_locator", _ABSENT)
    if normalized is not None and normalized is not _ABSENT:
        _exact_str(normalized, path + ("normalized_locator",))
    absence = record.get("locator_absence", _ABSENT)
    if absence is not None and absence is not _ABSENT:
        _exact_str(absence, path + ("locator_absence",))
    if (
        supplied is not _ABSENT
        and normalized is not _ABSENT
        and absence is not _ABSENT
    ):
        if (supplied is None) != (normalized is None):
            _refuse_at(6, stage, "locator-pairing-invalid", path)
        if (absence is None) is (supplied is None):
            _refuse_at(6, stage, "locator-pairing-invalid", path)
    if normalized is not None and normalized is not _ABSENT:
        if _HTTPS_RE.match(normalized) is None or not normalized.isascii():
            _refuse_at(6, stage, "locator-not-https", path + ("normalized_locator",))
        if len(normalized) > TEXT_MAX:
            _refuse_at(6, stage, "text-length-invalid", path + ("normalized_locator",))
    if absence is not _ABSENT and absence is not None and absence not in LOCATOR_ABSENCE_REASONS:
        _refuse_at(6, stage, "enum-value-invalid", path + ("locator_absence",))

    _text(record.get("supplied_date", _ABSENT), path + ("supplied_date",), LABEL_MAX, stage=stage)
    normalized_date = record.get("normalized_date", _ABSENT)
    if normalized_date is not None and normalized_date is not _ABSENT:
        _exact_str(normalized_date, path + ("normalized_date",))
        if not _is_calendar_date(normalized_date):
            _refuse_at(6, stage, "date-pairing-invalid", path + ("normalized_date",))
    supplied_date = record.get("supplied_date", _ABSENT)
    if supplied_date is not _ABSENT and normalized_date is not _ABSENT:
        if supplied_date == NOT_SUPPLIED and normalized_date is not None:
            _refuse_at(6, stage, "date-pairing-invalid", path + ("normalized_date",))

    _enum(record.get("carrier_role", _ABSENT), ROLES, path + ("carrier_role",), stage=stage)
    _text(record.get("carrier_label", _ABSENT), path + ("carrier_label",), LABEL_MAX, stage=stage)
    _text(
        record.get("upstream_attribution", _ABSENT), path + ("upstream_attribution",), TEXT_MAX, stage=stage
    )
    _enum(
        record.get("metadata_provenance", _ABSENT),
        METADATA_PROVENANCE,
        path + ("metadata_provenance",), stage=stage,
    )
    _enum(
        record.get("retrieval_state", _ABSENT), RETRIEVAL_STATES, path + ("retrieval_state",), stage=stage
    )
    _enum(
        record.get("verification_state", _ABSENT),
        SOURCE_VERIFICATION_STATES,
        path + ("verification_state",), stage=stage,
    )
    _string_list(record.get("limitations", _ABSENT), path + ("limitations",), 1, LIST_MAX, TEXT_MAX, stage=stage)
    _dispositions(record.get("safety_dispositions", _ABSENT), path + ("safety_dispositions",), stage=stage)
    _supersedes_closed(record.get("supersedes", _ABSENT), path + ("supersedes",), stage=stage)


def _check_claim(record, path, *, stage):
    _identifier(record.get("claim_id", _ABSENT), "CLM", path + ("claim_id",), stage=stage)
    _reference_shape(record.get("source_ref", _ABSENT), path + ("source_ref",), stage=stage)
    _reference_shape(record.get("batch_ref", _ABSENT), path + ("batch_ref",), stage=stage)
    _text(record.get("claim_text", _ABSENT), path + ("claim_text",), TEXT_MAX, stage=stage)
    _enum(
        record.get("attribution_class", _ABSENT),
        CLAIM_ATTRIBUTION_CLASSES,
        path + ("attribution_class",), stage=stage,
    )
    _text(record.get("evidence_basis", _ABSENT), path + ("evidence_basis",), TEXT_MAX, stage=stage)
    _string_list(record.get("limitations", _ABSENT), path + ("limitations",), 1, LIST_MAX, TEXT_MAX, stage=stage)
    _dispositions(record.get("safety_dispositions", _ABSENT), path + ("safety_dispositions",), stage=stage)
    _enum(
        record.get("verification_state", _ABSENT),
        CLAIM_VERIFICATION_STATES,
        path + ("verification_state",), stage=stage,
    )
    _supersedes_closed(record.get("supersedes", _ABSENT), path + ("supersedes",), stage=stage)


def _check_relationship(record, path, *, stage):
    _identifier(record.get("relationship_id", _ABSENT), "REL", path + ("relationship_id",), stage=stage)
    _reference_shape(record.get("left_ref", _ABSENT), path + ("left_ref",), stage=stage)
    _reference_shape(record.get("right_ref", _ABSENT), path + ("right_ref",), stage=stage)
    _enum(
        record.get("relationship_type", _ABSENT),
        RELATIONSHIP_TYPES,
        path + ("relationship_type",), stage=stage,
    )
    _enum(record.get("basis", _ABSENT), RELATIONSHIP_BASES, path + ("basis",), stage=stage)
    _enum(
        record.get("attribution_class", _ABSENT),
        RELATIONSHIP_ATTRIBUTION_CLASSES,
        path + ("attribution_class",), stage=stage,
    )
    _enum(
        record.get("verification_state", _ABSENT),
        RELATIONSHIP_VERIFICATION_STATES,
        path + ("verification_state",), stage=stage,
    )
    _string_list(record.get("limitations", _ABSENT), path + ("limitations",), 1, LIST_MAX, TEXT_MAX, stage=stage)
    _enum(record.get("recorded_by_role", _ABSENT), ROLES, path + ("recorded_by_role",), stage=stage)
    _text(record.get("recorded_by_label", _ABSENT), path + ("recorded_by_label",), LABEL_MAX, stage=stage)


def _check_unresolved(record, path, *, stage):
    _identifier(record.get("unresolved_id", _ABSENT), "UNR", path + ("unresolved_id",), stage=stage)
    _enum(
        record.get("conflict_family", _ABSENT), CONFLICT_FAMILIES, path + ("conflict_family",), stage=stage
    )
    _text(record.get("statement", _ABSENT), path + ("statement",), TEXT_MAX, stage=stage)
    _string_list(record.get("positions", _ABSENT), path + ("positions",), 2, 8, TEXT_MAX, stage=stage)
    _id_list(record.get("refs", _ABSENT), path + ("refs",), stage=stage, low=1)
    _enum(
        record.get("resolution_state", _ABSENT),
        UNRESOLVED_STATES,
        path + ("resolution_state",), stage=stage,
    )
    _enum(record.get("recorded_by_role", _ABSENT), ROLES, path + ("recorded_by_role",), stage=stage)
    _text(record.get("recorded_by_label", _ABSENT), path + ("recorded_by_label",), LABEL_MAX, stage=stage)


def _check_artifact(record, path, *, stage):
    _identifier(record.get("artifact_id", _ABSENT), "ART", path + ("artifact_id",), stage=stage)
    _reference_shape(record.get("introducing_batch", _ABSENT), path + ("introducing_batch",), stage=stage)
    _enum(record.get("artifact_class", _ABSENT), ARTIFACT_CLASSES, path + ("artifact_class",), stage=stage)
    _enum(
        record.get("identity_origin", _ABSENT), IDENTITY_ORIGINS, path + ("identity_origin",), stage=stage
    )
    _enum(
        record.get("preservation_status", _ABSENT),
        PRESERVATION_STATES,
        path + ("preservation_status",), stage=stage,
    )
    _text(record.get("rejection_basis", _ABSENT), path + ("rejection_basis",), TEXT_MAX, stage=stage)
    _enum(
        record.get("executable_status", _ABSENT),
        EXECUTABLE_STATES,
        path + ("executable_status",), stage=stage,
    )
    _dispositions(record.get("safety_dispositions", _ABSENT), path + ("safety_dispositions",), stage=stage)
    _text(record.get("summary", _ABSENT), path + ("summary",), TEXT_MAX, stage=stage)


def _check_correction(record, path, *, stage):
    _identifier(record.get("correction_id", _ABSENT), "COR", path + ("correction_id",), stage=stage)
    _reference_shape(record.get("target_ref", _ABSENT), path + ("target_ref",), stage=stage)
    _enum(record.get("correction_kind", _ABSENT), CORRECTION_KINDS, path + ("correction_kind",), stage=stage)
    _text(record.get("statement", _ABSENT), path + ("statement",), TEXT_MAX, stage=stage)
    _enum(record.get("recorded_by_role", _ABSENT), ROLES, path + ("recorded_by_role",), stage=stage)
    _text(record.get("recorded_by_label", _ABSENT), path + ("recorded_by_label",), LABEL_MAX, stage=stage)


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
            record.get("introduces_sources", _ABSENT),
            ("SRC",),
            path + ("introduces_sources",),
            ids_by_collection,
        )
        _check_reference_list(
            record.get("introduces_artifacts", _ABSENT),
            ("ART",),
            path + ("introduces_artifacts",),
            ids_by_collection,
        )
        _check_reference_list(
            record.get("updates_sources", _ABSENT),
            ("SRC",),
            path + ("updates_sources",),
            ids_by_collection,
        )
    for index, record in enumerate(payload["sources"]):
        _check_reference(
            record.get("batch_ref", _ABSENT),
            ("BAT",),
            ("sources", index, "batch_ref"),
            ids_by_collection,
        )
    for index, record in enumerate(payload["claims"]):
        _check_reference(
            record.get("source_ref", _ABSENT),
            ("SRC",),
            ("claims", index, "source_ref"),
            ids_by_collection,
        )
        _check_reference(
            record.get("batch_ref", _ABSENT),
            ("BAT",),
            ("claims", index, "batch_ref"),
            ids_by_collection,
        )
    for index, record in enumerate(payload["unresolved"]):
        _check_reference_list(
            record.get("refs", _ABSENT),
            ("SRC", "CLM"),
            ("unresolved", index, "refs"),
            ids_by_collection,
        )
    for index, record in enumerate(payload["artifacts"]):
        _check_reference(
            record.get("introducing_batch", _ABSENT),
            ("BAT",),
            ("artifacts", index, "introducing_batch"),
            ids_by_collection,
        )
    for index, record in enumerate(payload["corrections"]):
        target = record.get("target_ref", _ABSENT)
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
        left = record.get("left_ref", _ABSENT)
        right = record.get("right_ref", _ABSENT)
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
        triple = (left, right, record.get("relationship_type", _ABSENT))
        if triple in triples:
            _refuse("relationship-duplicate", path)
        triples.add(triple)


def _check_reciprocity(payload):
    batches_by_id = {record.get("batch_id", _ABSENT): record for record in payload["batches"]}
    sources_by_id = {record.get("source_id", _ABSENT): record for record in payload["sources"]}
    artifacts_by_id = {
        record.get("artifact_id", _ABSENT): record for record in payload["artifacts"]
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


def _check_document(payload, stage):
    """One traversal of the whole document, for the stage being decided.

    There is exactly one implementation of each rule here; the stage a rule
    belongs to is carried by its refusal, not by a second pass that could
    drift away from this one.
    """
    declared = frozenset(ROOT_KEYS)
    for key in payload:
        if key not in declared:
            _refuse_at(5, stage, "undeclared-key")
    for key in ROOT_KEYS:
        if key not in payload:
            _refuse_at(5, stage, "missing-key", (key,))

    # An absent root key is a stage-5 fault about THAT key. Returning here
    # skipped every remaining check, so one missing key masked every stage-4
    # exact-type fault in the whole document. Absent keys are stepped over
    # instead, and each rule decides what it can still decide.
    for key in COLLECTION_KEYS:
        if key not in payload:
            continue
        value = payload[key]
        if type(value) is not list:
            _refuse("type-not-exact", (key,))
        low, high = ROOT_COLLECTION_BOUNDS[key]
        if not low <= len(value) <= high:
            _refuse_at(5, stage, "collection-length-invalid", (key,))

    for key, expected in (
        ("schema", SCHEMA_ID),
        ("ledger_id", LEDGER_ID),
        ("corpus", CORPUS),
        ("intake_state", INTAKE_STATE),
    ):
        if key not in payload:
            continue
        value = payload[key]
        if type(value) is not str:
            _refuse("type-not-exact", (key,))
        if value != expected:
            _refuse_at(6, stage, "enum-value-invalid", (key,))

    for collection in COLLECTION_KEYS:
        if collection not in payload or type(payload[collection]) is not list:
            continue
        check = _RECORD_CHECKS[collection]
        for index, record in enumerate(payload[collection]):
            # The shape result no longer gates the field checks: a record with
            # a missing declared key still has its PRESENT fields type checked,
            # because every value rule steps over `_ABSENT`. A missing key used
            # to skip the record entirely, so a stage-5 fault masked a stage-4
            # fault in the very same record.
            _check_record_shape(record, collection, index, stage=stage)
            if type(record) is dict:
                check(record, (collection, index), stage=stage)


def validate_ledger(payload):
    """Validate one in-memory ledger document; return it unchanged."""
    if type(payload) is not dict:
        # The builtin subtype decision: issubclass over the exact runtime
        # type and the builtin dict class uses interpreter-level type
        # information only -- it reads no attribute of the candidate class
        # and compares no candidate class object through Python equality.
        if issubclass(type(payload), dict):
            _refuse("type-not-exact")
        _refuse("root-not-object")
    _screen_tree(payload)
    for stage in _CONTENT_STAGES:
        _check_document(payload, stage)
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

    # The walk must cover the path the process will actually OPEN. For a
    # relative supplied path that is `<current directory>\<value>`, so the
    # current directory entry and its own ancestors are screened as well:
    # `ntpath.dirname` of a bare filename is empty, so a walk starting at the
    # supplied string inspected exactly one entry and never reached the
    # directory the redirection was sitting in, while `open` resolved straight
    # through it. Bare, dot-relative, nested-relative, component-relative and
    # absolute spellings of one file therefore now agree.
    #
    # The anchor is a TEXTUAL join. Neither `realpath` nor `abspath` is used:
    # resolving the path would follow the very reparse point being screened
    # for, and `os.getcwd()` reports the directory as it was entered, junction
    # and all.
    if ntpath.isabs(value):
        # The same lexical collapse the relative branch gets, and for the same
        # reason: Windows resolves `.` and `..` before touching the filesystem,
        # so a spelling that steps back out of a junction never traverses it.
        # Applying it to one branch only made the identical object refused
        # under its absolute spelling and accepted under its relative one.
        walked = ntpath.normpath(value)
    else:
        # `normpath` is the same purely LEXICAL collapse Windows itself applies
        # to `.` and `..` before touching the filesystem: it follows nothing and
        # reads nothing. Without it the chain kept a `J\..` pair, and a file
        # sitting behind no redirection at all was refused because the walk
        # lstat'd a junction the process never traverses.
        walked = ntpath.normpath(ntpath.join(os.getcwd(), value))
    chain = []
    current = walked
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

    # The identity of the object the screen just finished inspecting. A
    # component the platform does not supply, or supplies as zero, identifies
    # nothing: the comparison below would hold of two different files, so it
    # would prove nothing and the document is refused instead.
    inspected = (
        getattr(status, "st_dev", None),
        getattr(status, "st_ino", None),
    )
    if not inspected[0] or not inspected[1]:
        _refuse_path("path-identity-changed")

    # Opened ONCE, by name, at the point of use. Screening a pathname and then
    # opening that pathname resolves the same name twice and binds nothing:
    # between the two resolutions the name can be made to refer to a different
    # file, and the validator then screens one object and reads another. So the
    # identity compared here is taken from the descriptor this handle holds --
    # never from the name again, before the open or after it -- and the bytes
    # are read from that same handle.
    #
    # The decision is made before the byte ceiling: a document read from an
    # object that was never screened is refused on that ground, not measured.
    with open(value, "rb") as handle:
        bound = os.fstat(handle.fileno())
        if not stat.S_ISREG(bound.st_mode):
            _refuse_path("path-identity-changed")
        opened = (
            getattr(bound, "st_dev", None),
            getattr(bound, "st_ino", None),
        )
        if not opened[0] or not opened[1]:
            _refuse_path("path-identity-changed")
        if opened != inspected:
            _refuse_path("path-identity-changed")
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
