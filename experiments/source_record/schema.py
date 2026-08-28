"""Closed record schema for ``source-record-v1``.

One record in isolation: exact builtin types, closed key sets, closed
vocabularies, and the static field order frozen in ``CONTRACT.md`` section 9.
Validation is pure and non-mutating; it never writes, infers, defaults, or
upgrades a field, and it refuses fail-fast with a token from the closed refusal
vocabulary plus a schema-declared path. A refusal never carries a rejected
value, never invokes a hook on a rejected object, and never reads the runtime
type name of a rejected object.

Record validity is not source credibility, claim truth, verification, or
endorsement.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re

SCHEMA_ID = "source-record-v1"
UNKNOWN_TOKEN = "unknown"

REGISTERS = ("register-a", "register-b", "bridge")
RECORD_TYPES = (
    "message",
    "source",
    "assertion",
    "link",
    "bridge",
    "contradiction",
)
ORIGINS = ("synthetic-fixture",)
VERIFICATION_STATES = ("unverified",)
RESOLUTION_STATES = ("unresolved",)
LOCATOR_SCHEMES = (
    "opaque-handle",
    "network-locator",
    "filename",
    "document-number",
    "container-reference",
    "none",
)
LOCATOR_RESOLUTIONS = ("unattempted",)
ATTRIBUTION_CLASSES = (
    "receipt-fact",
    "attributed-assertion",
    "recorded-observation",
    "derived-inference",
)
ROLES = (
    "relay-agent",
    "operator",
    "auditor",
    "analysis-seat",
    "external-author",
    "unattributed",
)
LINK_TYPES = (
    "claimed-container-includes",
    "claimed-derivative-of",
    "commentary-about",
    "apparent-textual-overlap",
    "contested-correspondence",
)
BRIDGE_TYPES = (
    "shared-attributed-author",
    "shared-locator-value",
    "apparent-textual-overlap",
    "contested-correspondence",
)
RELATIONSHIP_BASES = (
    "recorded-by-inspection",
    "recorded-from-supplied-material",
    "recorded-as-proposed-elsewhere",
)
CONFLICT_BASES = (
    "same-quantity-different-values",
    "same-property-mutually-exclusive-values",
    "presence-and-absence-of-the-same-property",
    "incompatible-attributions",
)

LABEL_MAX = 128
TEXT_MAX = 4096
LOCATORS_MAX = 16
DERIVED_FROM_MAX = 16
ORDINAL_MIN = 1
ORDINAL_MAX = 9999

# The [0-9] classes are load-bearing, not stylistic: the Python \d class
# matches Arabic-Indic and Devanagari digits and int() parses them. The
# lenient twins exist only to tell a non-ASCII digit apart from a malformed
# shape, so the refusal can be exact.
RECORD_ID_PATTERN = re.compile(
    r"\ASR-(A|B|X)-(MSG|SRC|ASR|LNK|BRG|CTR)-[0-9]{4}\Z"
)
_RECORD_ID_LENIENT = re.compile(
    r"\ASR-(A|B|X)-(MSG|SRC|ASR|LNK|BRG|CTR)-\d{4}\Z"
)
_RECORD_ID_ANYWHERE = re.compile(
    r"SR-(A|B|X)-(MSG|SRC|ASR|LNK|BRG|CTR)-[0-9]{4}"
)
_DATE_STRICT = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_DATE_LENIENT = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_LOCATOR_VALUE = re.compile(r"\Asynthetic-[a-z0-9-]{1,64}\Z")
_DIGEST_FORMAT = re.compile(r"\A[0-9a-f]{64}\Z")

COMMON_KEYS = (
    "schema",
    "record_id",
    "record_type",
    "register",
    "origin",
    "recorded_date",
    "recorded_by_role",
    "recorded_by_label",
    "supersedes",
)

TYPE_KEYS = {
    "message": (
        "carrier_role",
        "carrier_label",
        "received_date",
        "sequence_ordinal",
    ),
    "source": ("neutral_label", "locators", "issuer_claim"),
    "assertion": (
        "message_ref",
        "subject_ref",
        "attribution_class",
        "asserted_by_role",
        "attributed_author",
        "claim_text",
        "instrument_context",
        "derived_from",
        "verification_state",
        "verification_evidence",
    ),
    "link": (
        "left_ref",
        "right_ref",
        "link_type",
        "basis",
        "verification_state",
    ),
    "bridge": (
        "side_a",
        "side_b",
        "bridge_type",
        "basis",
        "verification_state",
    ),
    "contradiction": (
        "left_assertion_ref",
        "right_assertion_ref",
        "conflict_basis",
        "resolution_state",
        "verification_state",
    ),
}

ROOT_KEYS = {
    record_type: frozenset(COMMON_KEYS + extra)
    for record_type, extra in TYPE_KEYS.items()
}

LOCATOR_KEYS = frozenset({"scheme", "value", "resolution"})
ISSUER_CLAIM_KEYS = frozenset(
    {"claimed_issuer", "verification_state", "verification_evidence"}
)
SUPERSEDES_KEYS = frozenset({"record_id", "content_digest"})

_ALL_ROOT_KEYS = frozenset().union(*ROOT_KEYS.values())
_REGISTER_BY_SEGMENT = {"A": "register-a", "B": "register-b", "X": "bridge"}
_SEGMENT_BY_TYPE = {
    "message": "MSG",
    "source": "SRC",
    "assertion": "ASR",
    "link": "LNK",
    "bridge": "BRG",
    "contradiction": "CTR",
}

REFUSAL_TOKENS = (
    # path and binding, exit 4
    "path-missing",
    "path-not-directory",
    "path-symlink-refused",
    "path-binding-failed",
    "records-root-missing-directory",
    "records-root-unexpected-entry",
    "record-directory-unexpected-entry",
    # resource, exit 5
    "record-count-ceiling",
    "record-bytes-ceiling",
    "total-bytes-ceiling",
    # parse, schema and record, exit 2
    "json-malformed",
    "json-duplicate-key",
    "root-not-object",
    "key-not-exact-str",
    "undeclared-key",
    "missing-key",
    "schema-id-invalid",
    "record-id-malformed",
    "record-id-filename-mismatch",
    "record-id-directory-mismatch",
    "record-id-register-mismatch",
    "record-id-type-mismatch",
    "type-not-exact",
    "float-refused",
    "int-out-of-range",
    "enum-value-invalid",
    "digits-not-ascii",
    "date-invalid",
    "string-empty",
    "string-length-invalid",
    "string-not-valid-unicode",
    "string-contains-record-id",
    "list-length-invalid",
    "list-duplicate-item",
    "locator-value-not-synthetic",
    "null-not-permitted",
    "unknown-token-not-permitted",
    "attribution-author-mismatch",
    "derived-from-required",
    "derived-from-forbidden",
    "instrument-context-required",
    "instrument-context-forbidden",
    "reference-not-found",
    "reference-wrong-register",
    "reference-wrong-type",
    "reference-self",
    "reference-cycle",
    "bridge-side-register-invalid",
    "bridge-endpoint-not-source",
    "bridge-duplicate-pair",
    "digest-format-invalid",
    "supersedes-target-missing",
    "supersedes-register-mismatch",
    "supersedes-type-mismatch",
    "supersedes-digest-mismatch",
    "supersedes-fork-refused",
    "supersedes-self",
    "supersedes-cycle",
    "verification-state-invalid",
    "verification-evidence-not-null",
    "resolution-state-invalid",
)


def _describe(token, path):
    if path:
        return token + " at " + "/".join(str(part) for part in path)
    return token


class SourceRecordError(ValueError):
    """A malformed, hostile, or rule-violating record (fail closed).

    Carries exactly a ``token`` from the closed refusal vocabulary and a
    schema-declared ``path``. There is no rejected-value slot.
    """

    def __init__(self, token, path=()):
        self.token = token
        self.path = tuple(path)
        super().__init__(_describe(token, self.path))


def _refuse(token, path=()):
    # ``from None`` is applied here, at the raise site, so a refusal raised
    # while an exception is being handled discloses nothing through chaining.
    raise SourceRecordError(token, path) from None


def _required(mapping, key, container_path):
    if key not in mapping:
        _refuse("missing-key", tuple(container_path) + (key,))
    return mapping[key]


def _check_keys(mapping, declared, container_path):
    # Key type first: a foreign non-str key is refused without being hashed,
    # compared against the declared set, or stringified.
    for key in mapping:
        if type(key) is not str:
            _refuse("key-not-exact-str", container_path)
    for key in mapping:
        if key not in declared:
            _refuse("undeclared-key", container_path)


def _has_surrogate(text):
    for character in text:
        if "\ud800" <= character <= "\udfff":
            return True
    return False


def _str_value(value, path):
    if value is None:
        _refuse("null-not-permitted", path)
    if type(value) is float:
        _refuse("float-refused", path)
    if type(value) is not str:
        _refuse("type-not-exact", path)
    return value


def _free_text(value, path, maximum, allow_unknown=False):
    text = _str_value(value, path)
    if "\x00" in text or _has_surrogate(text):
        _refuse("string-not-valid-unicode", path)
    if text == UNKNOWN_TOKEN:
        if allow_unknown:
            return text
        _refuse("unknown-token-not-permitted", path)
    if text == "":
        _refuse("string-empty", path)
    if len(text) > maximum:
        _refuse("string-length-invalid", path)
    if _RECORD_ID_ANYWHERE.search(text):
        _refuse("string-contains-record-id", path)
    return text


def _enum(value, vocabulary, path, token="enum-value-invalid"):
    text = _str_value(value, path)
    if text not in vocabulary:
        _refuse(token, path)
    return text


def _date(value, path):
    text = _str_value(value, path)
    if not _DATE_STRICT.match(text):
        if _DATE_LENIENT.match(text):
            _refuse("digits-not-ascii", path)
        _refuse("date-invalid", path)
    try:
        datetime.date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except ValueError:
        _refuse("date-invalid", path)
    return text


def _record_id_text(value, path):
    text = _str_value(value, path)
    if not RECORD_ID_PATTERN.match(text):
        if _RECORD_ID_LENIENT.match(text):
            _refuse("digits-not-ascii", path)
        _refuse("record-id-malformed", path)
    return text


def _reference(value, path, record_id, register_segment, expected_segment):
    text = _record_id_text(value, path)
    if text[3] != register_segment:
        _refuse("reference-wrong-register", path)
    if text == record_id:
        _refuse("reference-self", path)
    if text[5:8] != expected_segment:
        _refuse("reference-wrong-type", path)
    return text


def _bridge_side(value, path, expected_register_segment):
    text = _record_id_text(value, path)
    if text[5:8] != "SRC":
        _refuse("bridge-endpoint-not-source", path)
    if text[3] != expected_register_segment:
        _refuse("bridge-side-register-invalid", path)
    return text


def _ordinal(value, path):
    if value is None:
        return None
    if type(value) is bool:
        _refuse("type-not-exact", path)
    if type(value) is int:
        if value < ORDINAL_MIN or value > ORDINAL_MAX:
            _refuse("int-out-of-range", path)
        return value
    if type(value) is float:
        _refuse("float-refused", path)
    if type(value) is str and value == UNKNOWN_TOKEN:
        _refuse("unknown-token-not-permitted", path)
    _refuse("type-not-exact", path)
    return None


def _verification_state(mapping, container_path):
    _enum(
        _required(mapping, "verification_state", container_path),
        VERIFICATION_STATES,
        tuple(container_path) + ("verification_state",),
        "verification-state-invalid",
    )


def _verification_evidence(mapping, container_path):
    evidence = _required(mapping, "verification_evidence", container_path)
    if evidence is not None:
        _refuse(
            "verification-evidence-not-null",
            tuple(container_path) + ("verification_evidence",),
        )


def _precheck(obj):
    """Root shape, key discipline, ``schema``, ``record_id``. Returns the id.

    This is the head of the frozen per-record order; ``_validate_body``
    continues from ``record_type`` so a caller that must interleave the
    filename and directory checks (the directory validator) can do so at the
    contract's exact position without re-reading any head field.
    """
    if type(obj) is not dict:
        if isinstance(obj, dict):
            _refuse("type-not-exact", ())
        _refuse("root-not-object", ())
    for key in obj:
        if type(key) is not str:
            _refuse("key-not-exact-str", ())
    for key in obj:
        if key not in _ALL_ROOT_KEYS:
            _refuse("undeclared-key", ())
    schema_value = _str_value(_required(obj, "schema", ()), ("schema",))
    if schema_value != SCHEMA_ID:
        _refuse("schema-id-invalid", ("schema",))
    return _record_id_text(_required(obj, "record_id", ()), ("record_id",))


def _validate_body(obj, record_id):
    register_segment = record_id[3]
    type_segment = record_id[5:8]
    record_type = _enum(
        _required(obj, "record_type", ()), RECORD_TYPES, ("record_type",)
    )
    if _SEGMENT_BY_TYPE[record_type] != type_segment:
        _refuse("record-id-type-mismatch", ("record_type",))
    register = _enum(
        _required(obj, "register", ()), REGISTERS, ("register",)
    )
    if _REGISTER_BY_SEGMENT[register_segment] != register:
        _refuse("record-id-register-mismatch", ("register",))
    if (record_type == "bridge") != (register == "bridge"):
        _refuse("record-id-register-mismatch", ("register",))
    declared = ROOT_KEYS[record_type]
    for key in obj:
        if key not in declared:
            _refuse("undeclared-key", ())
    _enum(_required(obj, "origin", ()), ORIGINS, ("origin",))
    _date(_required(obj, "recorded_date", ()), ("recorded_date",))
    _enum(
        _required(obj, "recorded_by_role", ()), ROLES, ("recorded_by_role",)
    )
    _free_text(
        _required(obj, "recorded_by_label", ()),
        ("recorded_by_label",),
        LABEL_MAX,
    )
    _supersedes(
        _required(obj, "supersedes", ()),
        record_id,
        register_segment,
        type_segment,
    )
    if record_type == "message":
        _validate_message(obj)
    elif record_type == "source":
        _validate_source(obj)
    elif record_type == "assertion":
        _validate_assertion(obj, record_id, register_segment)
    elif record_type == "link":
        _validate_link(obj, record_id, register_segment)
    elif record_type == "bridge":
        _validate_bridge(obj)
    else:
        _validate_contradiction(obj, record_id, register_segment)


def _supersedes(value, record_id, register_segment, type_segment):
    path = ("supersedes",)
    if value is None:
        return
    if type(value) is not dict:
        _refuse("type-not-exact", path)
    _check_keys(value, SUPERSEDES_KEYS, path)
    target = _record_id_text(
        _required(value, "record_id", path), path + ("record_id",)
    )
    if target[3] != register_segment:
        _refuse("supersedes-register-mismatch", path + ("record_id",))
    if target == record_id:
        _refuse("supersedes-self", path + ("record_id",))
    if target[5:8] != type_segment:
        _refuse("supersedes-type-mismatch", path + ("record_id",))
    digest_value = _required(value, "content_digest", path)
    if type(digest_value) is not str:
        _refuse("type-not-exact", path + ("content_digest",))
    if not _DIGEST_FORMAT.match(digest_value):
        _refuse("digest-format-invalid", path + ("content_digest",))


def _validate_message(obj):
    _enum(_required(obj, "carrier_role", ()), ROLES, ("carrier_role",))
    _free_text(
        _required(obj, "carrier_label", ()), ("carrier_label",), LABEL_MAX
    )
    _date(_required(obj, "received_date", ()), ("received_date",))
    _ordinal(_required(obj, "sequence_ordinal", ()), ("sequence_ordinal",))


def _validate_source(obj):
    _free_text(
        _required(obj, "neutral_label", ()), ("neutral_label",), TEXT_MAX
    )
    locators = _required(obj, "locators", ())
    path = ("locators",)
    if locators is None:
        _refuse("null-not-permitted", path)
    if type(locators) is not list:
        _refuse("type-not-exact", path)
    if len(locators) > LOCATORS_MAX:
        _refuse("list-length-invalid", path)
    validated = []
    for position, item in enumerate(locators):
        item_path = path + (position,)
        if type(item) is not dict:
            _refuse("type-not-exact", item_path)
        _check_keys(item, LOCATOR_KEYS, item_path)
        scheme = _enum(
            _required(item, "scheme", item_path),
            LOCATOR_SCHEMES,
            item_path + ("scheme",),
        )
        value_text = _str_value(
            _required(item, "value", item_path), item_path + ("value",)
        )
        if not _LOCATOR_VALUE.match(value_text):
            _refuse("locator-value-not-synthetic", item_path + ("value",))
        resolution = _enum(
            _required(item, "resolution", item_path),
            LOCATOR_RESOLUTIONS,
            item_path + ("resolution",),
        )
        entry = (scheme, value_text, resolution)
        if entry in validated:
            _refuse("list-duplicate-item", path)
        validated.append(entry)
    issuer = _required(obj, "issuer_claim", ())
    issuer_path = ("issuer_claim",)
    if issuer is None:
        _refuse("null-not-permitted", issuer_path)
    if type(issuer) is not dict:
        _refuse("type-not-exact", issuer_path)
    _check_keys(issuer, ISSUER_CLAIM_KEYS, issuer_path)
    _free_text(
        _required(issuer, "claimed_issuer", issuer_path),
        issuer_path + ("claimed_issuer",),
        LABEL_MAX,
        allow_unknown=True,
    )
    _verification_state(issuer, issuer_path)
    _verification_evidence(issuer, issuer_path)


def _validate_assertion(obj, record_id, register_segment):
    _reference(
        _required(obj, "message_ref", ()),
        ("message_ref",),
        record_id,
        register_segment,
        "MSG",
    )
    _reference(
        _required(obj, "subject_ref", ()),
        ("subject_ref",),
        record_id,
        register_segment,
        "SRC",
    )
    attribution = _enum(
        _required(obj, "attribution_class", ()),
        ATTRIBUTION_CLASSES,
        ("attribution_class",),
    )
    role = _enum(
        _required(obj, "asserted_by_role", ()),
        ROLES,
        ("asserted_by_role",),
    )
    author = _free_text(
        _required(obj, "attributed_author", ()),
        ("attributed_author",),
        LABEL_MAX,
        allow_unknown=True,
    )
    if (role == "unattributed") != (author == UNKNOWN_TOKEN):
        _refuse("attribution-author-mismatch", ("attributed_author",))
    _free_text(_required(obj, "claim_text", ()), ("claim_text",), TEXT_MAX)
    instrument = _required(obj, "instrument_context", ())
    instrument_path = ("instrument_context",)
    if instrument is not None:
        _free_text(instrument, instrument_path, TEXT_MAX, allow_unknown=True)
    if attribution == "recorded-observation":
        if instrument is None:
            _refuse("instrument-context-required", instrument_path)
    elif instrument is not None:
        _refuse("instrument-context-forbidden", instrument_path)
    derived = _required(obj, "derived_from", ())
    derived_path = ("derived_from",)
    if attribution == "derived-inference":
        if derived is None:
            _refuse("derived-from-required", derived_path)
        if type(derived) is not list:
            _refuse("type-not-exact", derived_path)
        if len(derived) == 0:
            _refuse("derived-from-required", derived_path)
        if len(derived) > DERIVED_FROM_MAX:
            _refuse("list-length-invalid", derived_path)
        seen = []
        for position, item in enumerate(derived):
            text = _reference(
                item,
                derived_path + (position,),
                record_id,
                register_segment,
                "ASR",
            )
            if text in seen:
                _refuse("list-duplicate-item", derived_path)
            seen.append(text)
    else:
        if derived is not None:
            _refuse("derived-from-forbidden", derived_path)
    _verification_state(obj, ())
    _verification_evidence(obj, ())


def _validate_link(obj, record_id, register_segment):
    _reference(
        _required(obj, "left_ref", ()),
        ("left_ref",),
        record_id,
        register_segment,
        "SRC",
    )
    _reference(
        _required(obj, "right_ref", ()),
        ("right_ref",),
        record_id,
        register_segment,
        "SRC",
    )
    _enum(_required(obj, "link_type", ()), LINK_TYPES, ("link_type",))
    _enum(_required(obj, "basis", ()), RELATIONSHIP_BASES, ("basis",))
    _verification_state(obj, ())


def _validate_bridge(obj):
    _bridge_side(_required(obj, "side_a", ()), ("side_a",), "A")
    _bridge_side(_required(obj, "side_b", ()), ("side_b",), "B")
    _enum(_required(obj, "bridge_type", ()), BRIDGE_TYPES, ("bridge_type",))
    _enum(_required(obj, "basis", ()), RELATIONSHIP_BASES, ("basis",))
    _verification_state(obj, ())


def _validate_contradiction(obj, record_id, register_segment):
    _reference(
        _required(obj, "left_assertion_ref", ()),
        ("left_assertion_ref",),
        record_id,
        register_segment,
        "ASR",
    )
    _reference(
        _required(obj, "right_assertion_ref", ()),
        ("right_assertion_ref",),
        record_id,
        register_segment,
        "ASR",
    )
    _enum(
        _required(obj, "conflict_basis", ()),
        CONFLICT_BASES,
        ("conflict_basis",),
    )
    _enum(
        _required(obj, "resolution_state", ()),
        RESOLUTION_STATES,
        ("resolution_state",),
        "resolution-state-invalid",
    )
    _verification_state(obj, ())


def validate_record(obj):
    """Validate one record in isolation; return None, mutate nothing."""
    record_id = _precheck(obj)
    _validate_body(obj, record_id)


def canonical_bytes(obj):
    """The canonical form: UTF-8, sorted keys, ASCII escapes, compact, no
    trailing newline."""
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=True, separators=(",", ":")
    ).encode("utf-8")


def digest(obj):
    """SHA-256 of the canonical form, lowercase hex."""
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()
