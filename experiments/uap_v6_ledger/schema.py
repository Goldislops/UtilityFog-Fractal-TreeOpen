"""Closed, read-only schema for the attributed UAP V6 intake ledger."""

from __future__ import annotations

import datetime as _datetime
import re


SCHEMA_ID = "source-record-v2"
LEDGER_ID = "uap-v6-ledger-v1"
CORPUS = "UAP V6 CORPUS"
INTAKE_STATES = ("intake-open",)
VERIFICATION_STATES = ("unverified",)

ATTRIBUTION_CLASSES = (
    "aura-summary",
    "aura-inference",
    "aura-capability-claim",
    "kev-observation",
    "jack-inference",
    "supplied-direct-source-excerpt",
    "other",
)
EVIDENCE_BASES = (
    "supplied-summary-only",
    "supplied-link-only",
    "supplied-summary-and-link",
)
SOURCE_CLASSES = (
    "video-host-link",
    "playlist-link",
    "official-document-link",
    "document-mirror-link",
    "official-portal-link",
    "institutional-web-page",
)
LOCATOR_FORMS = (
    "as-supplied",
    "normalized-from-supplied-markdown",
)
IDENTITY_STATES = ("unverified",)
RETRIEVAL_STATES = ("not-attempted",)
RELATIONSHIP_TYPES = (
    "duplicate-summary",
    "same-incident",
    "conflicts-with",
    "follow-up-detail",
    "source-mirror",
)
RELATIONSHIP_ATTRIBUTIONS = ("jack-inference",)
ISSUE_STATES = ("open",)
TAGS = (
    "source-capability",
    "kinematics",
    "sensor-artifact",
    "prosaic-classification",
    "physics-hypothesis",
    "institutional-claim",
    "data-architecture",
    "environmental-baseline",
    "policy-claim",
    "provenance-warning",
)

_TOP_KEYS = frozenset(
    {
        "schema",
        "ledger_id",
        "corpus",
        "intake_state",
        "recorded_date",
        "scope_note",
        "batches",
        "sources",
        "claims",
        "relationships",
        "unresolved",
    }
)
_BATCH_KEYS = frozenset(
    {
        "batch_id",
        "received_date",
        "carrier_role",
        "upstream_role",
        "summary_title",
        "summary_scope",
        "source_refs",
        "provenance_notes",
    }
)
_SOURCE_KEYS = frozenset(
    {
        "source_id",
        "introduced_in",
        "supplied_label",
        "locator",
        "locator_form",
        "source_class",
        "claimed_issuer",
        "identity_state",
        "retrieval_state",
        "provenance_note",
    }
)
_CLAIM_KEYS = frozenset(
    {
        "claim_id",
        "batch_id",
        "subject_refs",
        "attribution_class",
        "claim_text",
        "verification_state",
        "evidence_basis",
        "tags",
        "limitations",
    }
)
_RELATIONSHIP_KEYS = frozenset(
    {
        "relationship_id",
        "left_ref",
        "right_ref",
        "relationship_type",
        "recorded_as",
        "verification_state",
        "basis",
    }
)
_ISSUE_KEYS = frozenset(
    {"issue_id", "scope_refs", "question", "required_action", "state"}
)

_ID_PATTERNS = {
    "batch": re.compile(r"\AUV6-BATCH-[0-9]{4}\Z"),
    "source": re.compile(r"\AUV6-SRC-[0-9]{4}\Z"),
    "claim": re.compile(r"\AUV6-CLM-[0-9]{4}\Z"),
    "relationship": re.compile(r"\AUV6-REL-[0-9]{4}\Z"),
    "issue": re.compile(r"\AUV6-ISS-[0-9]{4}\Z"),
}
_HTTPS = re.compile(r"\Ahttps://[^\s]+\Z")


class LedgerError(ValueError):
    """A stable refusal carrying only a token and declared path."""

    def __init__(self, token: str, path: tuple[object, ...] = ()) -> None:
        self.token = token
        self.path = tuple(path)
        rendered = token
        if self.path:
            rendered += " at " + "/".join(str(part) for part in self.path)
        super().__init__(rendered)


def _exact_dict(value: object, keys: frozenset[str], path: tuple[object, ...]) -> dict:
    if type(value) is not dict:
        raise LedgerError("type-not-exact", path)
    for key in value:
        if type(key) is not str:
            raise LedgerError("key-not-exact-str", path)
    present = frozenset(value)
    if present != keys:
        token = "missing-key" if keys - present else "undeclared-key"
        raise LedgerError(token, path)
    return value


def _text(value: object, path: tuple[object, ...], *, maximum: int = 4000) -> str:
    if type(value) is not str:
        raise LedgerError("type-not-exact", path)
    if not value or len(value) > maximum or "\x00" in value:
        raise LedgerError("text-invalid", path)
    return value


def _enum(value: object, allowed: tuple[str, ...], path: tuple[object, ...]) -> str:
    text = _text(value, path, maximum=100)
    if text not in allowed:
        raise LedgerError("enum-invalid", path)
    return text


def _date(value: object, path: tuple[object, ...]) -> str:
    text = _text(value, path, maximum=10)
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
        raise LedgerError("date-invalid", path)
    try:
        _datetime.date.fromisoformat(text)
    except ValueError:
        raise LedgerError("date-invalid", path) from None
    return text


def _id(value: object, kind: str, path: tuple[object, ...]) -> str:
    text = _text(value, path, maximum=32)
    if _ID_PATTERNS[kind].fullmatch(text) is None:
        raise LedgerError("id-invalid", path)
    return text


def _list(value: object, path: tuple[object, ...], *, nonempty: bool = False) -> list:
    if type(value) is not list:
        raise LedgerError("type-not-exact", path)
    if nonempty and not value:
        raise LedgerError("list-empty", path)
    return value


def _text_list(
    value: object,
    path: tuple[object, ...],
    *,
    nonempty: bool = False,
    allowed: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    items = _list(value, path, nonempty=nonempty)
    result = []
    for index, item in enumerate(items):
        item_path = path + (index,)
        text = _text(item, item_path)
        if allowed is not None and text not in allowed:
            raise LedgerError("enum-invalid", item_path)
        result.append(text)
    if len(result) != len(set(result)):
        raise LedgerError("list-duplicate", path)
    return tuple(result)


def _unique(identifier: str, seen: set[str], path: tuple[object, ...]) -> None:
    if identifier in seen:
        raise LedgerError("id-duplicate", path)
    seen.add(identifier)


def validate_ledger(payload: object) -> None:
    """Validate one complete intake ledger without mutation or retrieval."""

    root = _exact_dict(payload, _TOP_KEYS, ())
    if _text(root["schema"], ("schema",)) != SCHEMA_ID:
        raise LedgerError("schema-invalid", ("schema",))
    if _text(root["ledger_id"], ("ledger_id",)) != LEDGER_ID:
        raise LedgerError("ledger-id-invalid", ("ledger_id",))
    if _text(root["corpus"], ("corpus",)) != CORPUS:
        raise LedgerError("corpus-invalid", ("corpus",))
    _enum(root["intake_state"], INTAKE_STATES, ("intake_state",))
    _date(root["recorded_date"], ("recorded_date",))
    _text(root["scope_note"], ("scope_note",))

    batches = _list(root["batches"], ("batches",), nonempty=True)
    sources = _list(root["sources"], ("sources",), nonempty=True)
    claims = _list(root["claims"], ("claims",), nonempty=True)
    relationships = _list(root["relationships"], ("relationships",))
    unresolved = _list(root["unresolved"], ("unresolved",), nonempty=True)

    all_ids: set[str] = set()
    batch_ids: set[str] = set()
    source_ids: set[str] = set()
    claim_ids: set[str] = set()

    for index, item in enumerate(batches):
        path = ("batches", index)
        batch = _exact_dict(item, _BATCH_KEYS, path)
        identifier = _id(batch["batch_id"], "batch", path + ("batch_id",))
        _unique(identifier, batch_ids, path + ("batch_id",))
        _unique(identifier, all_ids, path + ("batch_id",))
        _date(batch["received_date"], path + ("received_date",))
        if _text(batch["carrier_role"], path + ("carrier_role",)) != "Kev":
            raise LedgerError("carrier-role-invalid", path + ("carrier_role",))
        if _text(batch["upstream_role"], path + ("upstream_role",)) != "AURA":
            raise LedgerError("upstream-role-invalid", path + ("upstream_role",))
        _text(batch["summary_title"], path + ("summary_title",))
        _text(batch["summary_scope"], path + ("summary_scope",))
        _text_list(batch["source_refs"], path + ("source_refs",))
        _text_list(
            batch["provenance_notes"],
            path + ("provenance_notes",),
            nonempty=True,
        )

    for index, item in enumerate(sources):
        path = ("sources", index)
        source = _exact_dict(item, _SOURCE_KEYS, path)
        identifier = _id(source["source_id"], "source", path + ("source_id",))
        _unique(identifier, source_ids, path + ("source_id",))
        _unique(identifier, all_ids, path + ("source_id",))
        _id(source["introduced_in"], "batch", path + ("introduced_in",))
        _text(source["supplied_label"], path + ("supplied_label",))
        locator = _text(source["locator"], path + ("locator",))
        if _HTTPS.fullmatch(locator) is None:
            raise LedgerError("locator-invalid", path + ("locator",))
        _enum(source["locator_form"], LOCATOR_FORMS, path + ("locator_form",))
        _enum(source["source_class"], SOURCE_CLASSES, path + ("source_class",))
        _text(source["claimed_issuer"], path + ("claimed_issuer",))
        _enum(source["identity_state"], IDENTITY_STATES, path + ("identity_state",))
        _enum(
            source["retrieval_state"],
            RETRIEVAL_STATES,
            path + ("retrieval_state",),
        )
        _text(source["provenance_note"], path + ("provenance_note",))

    for index, item in enumerate(claims):
        path = ("claims", index)
        claim = _exact_dict(item, _CLAIM_KEYS, path)
        identifier = _id(claim["claim_id"], "claim", path + ("claim_id",))
        _unique(identifier, claim_ids, path + ("claim_id",))
        _unique(identifier, all_ids, path + ("claim_id",))
        _id(claim["batch_id"], "batch", path + ("batch_id",))
        _text_list(claim["subject_refs"], path + ("subject_refs",))
        _enum(
            claim["attribution_class"],
            ATTRIBUTION_CLASSES,
            path + ("attribution_class",),
        )
        _text(claim["claim_text"], path + ("claim_text",))
        _enum(
            claim["verification_state"],
            VERIFICATION_STATES,
            path + ("verification_state",),
        )
        _enum(claim["evidence_basis"], EVIDENCE_BASES, path + ("evidence_basis",))
        _text_list(claim["tags"], path + ("tags",), nonempty=True, allowed=TAGS)
        _text_list(claim["limitations"], path + ("limitations",), nonempty=True)

    relationship_ids: set[str] = set()
    for index, item in enumerate(relationships):
        path = ("relationships", index)
        relationship = _exact_dict(item, _RELATIONSHIP_KEYS, path)
        identifier = _id(
            relationship["relationship_id"],
            "relationship",
            path + ("relationship_id",),
        )
        _unique(identifier, relationship_ids, path + ("relationship_id",))
        _unique(identifier, all_ids, path + ("relationship_id",))
        _text(relationship["left_ref"], path + ("left_ref",), maximum=32)
        _text(relationship["right_ref"], path + ("right_ref",), maximum=32)
        _enum(
            relationship["relationship_type"],
            RELATIONSHIP_TYPES,
            path + ("relationship_type",),
        )
        _enum(
            relationship["recorded_as"],
            RELATIONSHIP_ATTRIBUTIONS,
            path + ("recorded_as",),
        )
        _enum(
            relationship["verification_state"],
            VERIFICATION_STATES,
            path + ("verification_state",),
        )
        _text(relationship["basis"], path + ("basis",))

    issue_ids: set[str] = set()
    for index, item in enumerate(unresolved):
        path = ("unresolved", index)
        issue = _exact_dict(item, _ISSUE_KEYS, path)
        identifier = _id(issue["issue_id"], "issue", path + ("issue_id",))
        _unique(identifier, issue_ids, path + ("issue_id",))
        _unique(identifier, all_ids, path + ("issue_id",))
        _text_list(issue["scope_refs"], path + ("scope_refs",))
        _text(issue["question"], path + ("question",))
        _text(issue["required_action"], path + ("required_action",))
        _enum(issue["state"], ISSUE_STATES, path + ("state",))

    for index, batch in enumerate(batches):
        for position, source_ref in enumerate(batch["source_refs"]):
            if source_ref not in source_ids:
                raise LedgerError(
                    "reference-not-found",
                    ("batches", index, "source_refs", position),
                )
    for index, source in enumerate(sources):
        if source["introduced_in"] not in batch_ids:
            raise LedgerError(
                "reference-not-found", ("sources", index, "introduced_in")
            )
    for index, claim in enumerate(claims):
        if claim["batch_id"] not in batch_ids:
            raise LedgerError("reference-not-found", ("claims", index, "batch_id"))
        for position, source_ref in enumerate(claim["subject_refs"]):
            if source_ref not in source_ids:
                raise LedgerError(
                    "reference-not-found",
                    ("claims", index, "subject_refs", position),
                )
    for index, relationship in enumerate(relationships):
        if relationship["left_ref"] not in all_ids:
            raise LedgerError(
                "reference-not-found", ("relationships", index, "left_ref")
            )
        if relationship["right_ref"] not in all_ids:
            raise LedgerError(
                "reference-not-found", ("relationships", index, "right_ref")
            )
        if relationship["left_ref"] == relationship["right_ref"]:
            raise LedgerError(
                "self-relationship", ("relationships", index, "right_ref")
            )
    for index, issue in enumerate(unresolved):
        for position, scope_ref in enumerate(issue["scope_refs"]):
            if scope_ref not in all_ids:
                raise LedgerError(
                    "reference-not-found",
                    ("unresolved", index, "scope_refs", position),
                )
