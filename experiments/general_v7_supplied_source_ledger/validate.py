"""Fail-closed validation for ``general-v7-supplied-source-ledger-v1``.

Standard library only. Nothing here retrieves, opens, resolves or contacts a
locator: the only file this module opens is the ledger it was asked to
validate.

A refusal carries exactly one token from the closed vocabulary and **never
echoes the value it refused**. The exception has no rejected-value slot,
because a refusal that renders what it refused is a channel for the refused
material. Messages name the schema path only.

``schema`` is imported relatively. The production import allowlist governs
what this package may reach OUTSIDE itself; a package reading its own module
is not reach.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import stat

from . import schema

class RefusalError(Exception):
    """One closed token, and a schema path. Never the refused value."""

    def __init__(self, token: str, where: str = "") -> None:
        if token not in schema.REFUSAL_TOKENS:
            raise AssertionError("refusal token outside the closed vocabulary")
        self.token = token
        self.where = where
        super().__init__(token if not where else token + " at " + where)


def _refuse(token: str, where: str = "") -> RefusalError:
    return RefusalError(token, where)


# --------------------------------------------------------------------------
# Strict parsing. Every hook refuses before any structural walk begins, so a
# non-finite literal is refused as a non-finite literal and not as a missing
# key that happened to sit beside it.
# --------------------------------------------------------------------------


def _object_pairs(pairs):
    seen = set()
    for key, _value in pairs:
        if key in seen:
            raise _refuse("duplicate-key", "object member")
        seen.add(key)
    return dict(pairs)


def _parse_float(literal: str):
    value = float(literal)
    if value != value or value in (float("inf"), float("-inf")):
        raise _refuse("non-finite-not-permitted", "number")
    raise _refuse("float-not-permitted", "number")


def _parse_constant(name: str):
    raise _refuse("non-finite-not-permitted", "constant")


def _parse(text: str):
    if not isinstance(text, str):
        raise _refuse("wrong-type", "document")
    if text.startswith("﻿"):
        raise _refuse("encoding-not-permitted", "document")
    try:
        return json.loads(
            text,
            object_pairs_hook=_object_pairs,
            parse_float=_parse_float,
            parse_constant=_parse_constant,
        )
    except RefusalError:
        raise
    except (ValueError, RecursionError):
        raise _refuse("malformed-document", "document") from None


# --------------------------------------------------------------------------
# Field rules.
# --------------------------------------------------------------------------


def _require_text(value, where: str, scan_digits: bool = True) -> str:
    if not isinstance(value, str) or type(value) is not str:
        raise _refuse("wrong-type", where)
    if scan_digits and schema.has_non_ascii_digit(value):
        raise _refuse("non-ascii-digit", where)
    return value


def _check_path(value: str, where: str) -> None:
    if re.match(schema.DRIVE_OR_UNC_PATTERN, value) or value.startswith("/"):
        raise _refuse("path-not-relative", where)
    if "\\" in value:
        raise _refuse("path-separator-not-permitted", where)
    components = value.split("/")
    for component in components:
        if component in ("", ".", ".."):
            raise _refuse("path-traversal", where)
    for component in components:
        if component != component.rstrip(". "):
            raise _refuse("path-reserved-component", where)
        stem = component.split(".")[0].upper()
        if stem in schema.WINDOWS_RESERVED_NAMES:
            raise _refuse("path-reserved-component", where)


def _check_field(collection: str, key: str, value, where: str) -> None:
    rule = schema.FIELD_RULES[collection][key]
    kind = rule["kind"]
    nullable = kind.startswith("null-or-")
    if value is None:
        if nullable:
            return
        raise _refuse("wrong-type", where)
    base = kind[len("null-or-") :] if nullable else kind

    if base == "any":
        if key == "byte_evidence":
            _check_byte_evidence(value, where)
        return
    if base == "list":
        if not isinstance(value, list) or type(value) is not list:
            raise _refuse("wrong-type", where)
        for index, item in enumerate(value):
            _require_text(item, where + "[" + str(index) + "]")
        return
    if base == "bool":
        if not isinstance(value, bool):
            raise _refuse("wrong-type", where)
        return
    if base == "int":
        if isinstance(value, bool):
            raise _refuse("bool-not-integer", where)
        if not isinstance(value, int) or type(value) is not int:
            raise _refuse("wrong-type", where)
        low, high = rule["bounds"]
        if value < low or value > high:
            raise _refuse("integer-out-of-bounds", where)
        return

    text = _require_text(
        value, where, scan_digits=key not in schema.SUPPLIED_VERBATIM_FIELDS
    )
    if text == "" and key in schema.NO_EMPTY_STRING_FIELDS:
        raise _refuse("absence-representation-not-permitted", where)
    if base == "digest":
        if not re.match(schema.DIGEST_PATTERN, text):
            raise _refuse("wrong-type", where)
        return
    if base == "id":
        if not re.match(schema.ID_PATTERN, text):
            raise _refuse("wrong-type", where)
        segment = rule.get("segment")
        if segment is not None and text.split("-")[1] != segment:
            raise _refuse("wrong-type", where)
        return
    if base == "enum":
        if text not in rule["values"]:
            if key in schema.ATTRIBUTION_FIELDS:
                raise _refuse("attribution-class-not-permitted", where)
            if key in schema.VERIFICATION_FIELDS:
                raise _refuse("verification-state-not-permitted", where)
            raise _refuse("vocabulary-token-not-permitted", where)
        return
    if base == "path":
        _check_path(text, where)
        return
    if base == "str":
        return
    raise AssertionError("unreachable field kind")


def _check_byte_evidence(value, where: str) -> None:
    """A nested block is closed too. CONTRACT.md section 11.2."""
    if type(value) is not dict:
        raise _refuse("wrong-type", where)
    for key in value:
        if type(key) is not str:
            raise _refuse("wrong-type", where)
    if set(value) - schema.BYTE_EVIDENCE_KEYS:
        raise _refuse("unknown-key", where)
    if schema.BYTE_EVIDENCE_KEYS - set(value):
        raise _refuse("missing-key", where)
    carrier = value["carrier_batch_ref"]
    if not isinstance(carrier, str) or not re.match(schema.ID_PATTERN, carrier):
        raise _refuse("wrong-type", where + ".carrier_batch_ref")
    if carrier.split("-")[1] != "BAT":
        raise _refuse("wrong-type", where + ".carrier_batch_ref")
    digest = value["carrier_member_sha256"]
    if not isinstance(digest, str) or not re.match(schema.DIGEST_PATTERN, digest):
        raise _refuse("wrong-type", where + ".carrier_member_sha256")
    index = value["bibliography_entry_index"]
    if isinstance(index, bool):
        raise _refuse("bool-not-integer", where + ".bibliography_entry_index")
    if type(index) is not int:
        raise _refuse("wrong-type", where + ".bibliography_entry_index")


def _check_record(collection: str, record, where: str) -> None:
    if type(record) is not dict:
        raise _refuse("wrong-type", where)
    for key in record:
        if type(key) is not str:
            raise _refuse("wrong-type", where)
    declared = schema.KEYS_BY_COLLECTION[collection]
    present = set(record)
    if present - declared:
        raise _refuse("unknown-key", where)
    # A correction targeting a correction is refused for being the WRONG KIND,
    # which CONTRACT.md section 10.2 keeps distinct from an unresolved
    # reference. The kind is readable from the id segment alone, so this is
    # decided before completeness: it does not depend on the target existing.
    if collection == "corrections":
        target = record.get("target_ref")
        if isinstance(target, str) and target.split("-")[1:2] == ["COR"]:
            raise _refuse("correction-target-not-permitted", where)
    if declared - present:
        raise _refuse("missing-key", where)
    for key in sorted(record):
        _check_field(collection, key, record[key], where + "." + key)
    if collection == "sources":
        _check_source_cross_fields(record, where)
    if collection == "relationships":
        if record["left_ref"] == record["right_ref"]:
            raise _refuse("relationship-endpoints-identical", where)


def _check_source_cross_fields(record, where: str) -> None:
    """CONTRACT.md sections 6.5 and 7, which no single field can express."""
    supplied = record["supplied_locator"]
    carrier = record["locator_carrier_batch_ref"]
    reason = record["locator_absence_reason"]
    if supplied is not None and carrier is None:
        raise _refuse("locator-without-carrier", where)
    if supplied is None and carrier is not None:
        raise _refuse("locator-without-carrier", where)
    if supplied is None and reason is None:
        raise _refuse("absence-representation-not-permitted", where)
    if supplied is not None and reason is not None:
        raise _refuse("absence-representation-not-permitted", where)
    if supplied is None and record["normalized_locator"] is not None:
        raise _refuse("absence-representation-not-permitted", where)


def validate_document(text: str):
    """Parse and validate one JSON document supplied as text.

    Returns the validated value unchanged. Collections absent from the
    document are simply absent: a partial document is a legal thing to
    validate, and it is ``validate_ledger_file`` that requires the whole
    ledger.
    """
    value = _parse(text)
    if type(value) is not dict:
        raise _refuse("wrong-type", "root")
    for key in value:
        if type(key) is not str:
            raise _refuse("wrong-type", "root")
    if set(value) - schema.ROOT_KEYS:
        raise _refuse("unknown-key", "root")
    for name in schema.ROOT_METADATA_KEYS:
        if name not in value:
            continue
        if name == "counts":
            if type(value[name]) is not dict:
                raise _refuse("wrong-type", "root.counts")
            for key, count in value[name].items():
                if type(key) is not str or key not in schema.COLLECTIONS:
                    raise _refuse("unknown-key", "root.counts")
                if isinstance(count, bool):
                    raise _refuse("bool-not-integer", "root.counts." + key)
                if type(count) is not int:
                    raise _refuse("wrong-type", "root.counts." + key)
        else:
            _require_text(value[name], "root." + name)
    for collection in schema.COLLECTIONS:
        if collection not in value:
            continue
        records = value[collection]
        if type(records) is not list:
            raise _refuse("wrong-type", "root." + collection)
        for index, record in enumerate(records):
            _check_record(
                collection, record, "root." + collection + "[" + str(index) + "]"
            )
    # Intra-collection rules. These hold of a partial document too, so they run
    # here rather than only over a whole ledger: a supersession that names no
    # partner is one-sided whether or not the rest of the ledger is present.
    if "corrections" in value:
        _check_supersession({"corrections": value["corrections"]})
    if "relationships" in value:
        _check_relationship_uniqueness(value["relationships"])
    return value


def _check_relationship_uniqueness(records) -> None:
    triples = set()
    for record in records:
        triple = (
            record["left_ref"],
            record["right_ref"],
            record["relationship_type"],
        )
        if triple in triples:
            raise _refuse("duplicate-relationship", "root.relationships")
        triples.add(triple)


def _read_ledger_bytes(path) -> bytes:
    """Open once, fail closed on a reparse point, and read what was opened.

    The entry is inspected with ``lstat`` so a symlink or junction is refused
    rather than followed, and the opened descriptor is stat'd again so the
    artifact read is the artifact inspected.
    """
    target = pathlib.Path(path)
    info = os.lstat(target)
    if stat.S_ISLNK(info.st_mode):
        raise _refuse("reparse-point-refused", "ledger")
    if getattr(info, "st_reparse_tag", 0):
        raise _refuse("reparse-point-refused", "ledger")
    if not stat.S_ISREG(info.st_mode):
        raise _refuse("wrong-type", "ledger")
    # `mode=` is passed by keyword deliberately. A binary read takes no
    # encoding, and CONTRACT.md section 11.7 requires the mode to be
    # explicit; the keyword form states it unambiguously.
    with open(target, mode="rb") as handle:
        opened = os.fstat(handle.fileno())
        if opened.st_size != info.st_size:
            raise _refuse("path-identity-changed", "ledger")
        # Size alone would miss a same-size substitution between the stat and
        # the open. Compare identity where the platform reports one; a zero
        # inode means the platform did not, and the size check is then all
        # that is available -- which is disclosed rather than dressed up.
        if info.st_ino and opened.st_ino and info.st_ino != opened.st_ino:
            raise _refuse("path-identity-changed", "ledger")
        if info.st_dev and opened.st_dev and info.st_dev != opened.st_dev:
            raise _refuse("path-identity-changed", "ledger")
        return handle.read()


def validate_ledger_file(path):
    """Validate a complete ledger document at a path."""
    raw = _read_ledger_bytes(path)
    if raw.startswith(b"\xef\xbb\xbf"):
        raise _refuse("encoding-not-permitted", "ledger")
    if b"\r" in raw:
        raise _refuse("encoding-not-permitted", "ledger")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _refuse("encoding-not-permitted", "ledger") from None
    value = validate_document(text)
    for name in schema.ROOT_METADATA_KEYS:
        if name not in value:
            raise _refuse("missing-key", "root")
    for collection in schema.COLLECTIONS:
        if collection not in value:
            raise _refuse("missing-key", "root")
    _check_whole_ledger(value)
    return value


def _check_whole_ledger(value) -> None:
    known = {}
    for collection in schema.COLLECTIONS:
        for record in value[collection]:
            identifier = record["record_id"]
            if identifier in known:
                raise _refuse("duplicate-key", "root." + collection)
            known[identifier] = collection
    for collection in schema.COLLECTIONS:
        for record in value[collection]:
            for key, item in sorted(record.items()):
                if not key.endswith("_ref") or item is None:
                    continue
                if item == record["record_id"]:
                    raise _refuse("self-reference", "root." + collection)
                if item not in known:
                    raise _refuse("reference-not-found", "root." + collection)
    for collection in schema.COLLECTIONS:
        declared = value["counts"].get(collection)
        if declared != len(value[collection]):
            raise _refuse("wrong-type", "root.counts." + collection)
    for record in value["sources"]:
        if record["record_id"] != schema.source_identifier(record):
            raise _refuse("wrong-type", "root.sources")
    _check_reference_cycles(value, known)


def _check_supersession(value) -> None:
    by_id = {record["record_id"]: record for record in value["corrections"]}
    partners = set()
    for record in value["corrections"]:
        if record["correction_kind"] != "supersession":
            continue
        partner = record["reciprocal_ref"]
        if partner is None or partner == record["record_id"]:
            raise _refuse("supersession-not-reciprocal", "root.corrections")
        other = by_id.get(partner)
        if other is None or other["reciprocal_ref"] != record["record_id"]:
            raise _refuse("supersession-not-reciprocal", "root.corrections")
        partners.add(record["record_id"])
    # CONTRACT.md section 10a: the pair names each other and "a third
    # correction naming either is refused". Only the partner itself may name a
    # partner, so any other correction pointing at one is refused here.
    for record in value["corrections"]:
        reference = record["reciprocal_ref"]
        if reference is None or reference not in partners:
            continue
        named = by_id.get(reference)
        if named is None or named["reciprocal_ref"] != record["record_id"]:
            raise _refuse("supersession-not-reciprocal", "root.corrections")


def _check_reference_cycles(value, known) -> None:
    """CONTRACT.md section 11.11. No reference cycle.

    ``reciprocal_ref`` is excluded by design: section 10a *requires* a
    supersession pair to name each other, which is a two-cycle. Walking it
    would refuse the one cycle the contract mandates, so the cycle rule
    applies to the referring edges and the reciprocity rule governs that pair.
    """
    edges = {}
    for collection in schema.COLLECTIONS:
        for record in value[collection]:
            targets = []
            for key, item in sorted(record.items()):
                if not key.endswith("_ref") or item is None:
                    continue
                if key == "reciprocal_ref":
                    continue
                targets.append(item)
            edges[record["record_id"]] = targets

    visiting, done = set(), set()

    def walk(node):
        if node in done:
            return
        if node in visiting:
            raise _refuse("reference-cycle", "root")
        visiting.add(node)
        for target in edges.get(node, ()):
            if target in edges:
                walk(target)
        visiting.discard(node)
        done.add(node)

    for node in sorted(edges):
        walk(node)
