"""Family S --- schema closure, serialization and fail-closed parsing.

Every control begins with a gate call and fails, at the contract-only head,
with the single reason ``implementation-absent``.

**Every fixture here is synthetic and authored inline.** No packet text is
used as test input, and no locator in this module refers to a real resource.
The refusal controls feed a deliberately malformed payload to the validator
and require an exact token from the closed vocabulary in CONTRACT.md section
11a; the audit controls read committed data and assert a property of what is
recorded. The two are never interchanged.
"""

from __future__ import annotations

import ast
import json

import pytest

from experiments.general_v7_supplied_source_ledger.tests import _support as sup


def refuses(validate, document: str, token: str) -> None:
    """Feed a malformed document and require an exact refusal token."""
    with pytest.raises(validate.RefusalError) as info:
        validate.validate_document(document)
    assert info.value.token == token, (info.value.token, token)
    assert info.value.token in sup.REFUSAL_TOKENS
    rendered = str(info.value)
    for marker in sup.MARKERS:
        assert marker not in rendered, "the refusal echoed the rejected value"


def minimal_batch() -> dict:
    return {
        "record_id": "G7S-BAT-0001",
        "batch_ordinal": 1,
        "member_filename": "BATCH_001.txt",
        "member_sha256": "0" * 64,
        "packet_sha256": sup.PACKET_ARCHIVE_SHA256,
        "origin_type": "attachment",
        "origin_id": "00000000-0000-4000-8000-000000000000",
        "line_ending_form": "crlf-only",
    }


def test_g7s_s_001_the_validator_exposes_the_declared_surface():
    validate = sup.require_validate()
    for name in sup.REQUIRED_VALIDATE_ATTRIBUTES:
        assert hasattr(validate, name), name
    assert issubclass(validate.RefusalError, Exception)


def test_g7s_s_002_the_schema_exposes_the_declared_surface():
    schema = sup.require_schema()
    for name in sup.REQUIRED_SCHEMA_ATTRIBUTES:
        assert hasattr(schema, name), name
    assert tuple(schema.REFUSAL_TOKENS) == sup.REFUSAL_TOKENS


def test_g7s_s_003_the_declared_key_set_matches_the_contract_record_shapes():
    """Named for what it does. Acceptance is G7S-S-033's job, not this one.

    An earlier name promised that a minimal record of every type was accepted
    while the body only inspected the declared key sets, which is exactly the
    kind of overclaim CONTRACT.md section 14g exists to forbid.
    """
    schema = sup.require_schema()
    for collection in sup.COLLECTIONS:
        assert collection in schema.KEYS_BY_COLLECTION, collection
        declared = schema.KEYS_BY_COLLECTION[collection]
        assert isinstance(declared, frozenset), collection
        assert set(declared) == set(sup.RECORD_FIELDS[collection]), (
            collection,
            sorted(set(declared) ^ set(sup.RECORD_FIELDS[collection])),
        )


def test_g7s_s_004_a_missing_declared_key_is_refused():
    validate = sup.require_validate()
    record = minimal_batch()
    for key in sorted(record):
        payload = {k: v for k, v in record.items() if k != key}
        refuses(validate, json.dumps({"batches": [payload]}), "missing-key")


def test_g7s_s_005_an_undeclared_root_key_is_refused():
    validate = sup.require_validate()
    refuses(
        validate,
        json.dumps({"batches": [], sup.MARKER_KEY: sup.MARKER_VALUE}),
        "unknown-key",
    )


def test_g7s_s_006_an_undeclared_nested_key_is_refused():
    validate = sup.require_validate()
    record = minimal_batch()
    record[sup.MARKER_KEY] = sup.MARKER_VALUE
    refuses(validate, json.dumps({"batches": [record]}), "unknown-key")


def test_g7s_s_007_a_key_differing_only_by_case_is_refused():
    validate = sup.require_validate()
    record = minimal_batch()
    record["Record_Id"] = record["record_id"]
    refuses(validate, json.dumps({"batches": [record]}), "unknown-key")


def test_g7s_s_008_a_confusable_key_is_refused_never_normalized():
    validate = sup.require_validate()
    record = minimal_batch()
    record["\u0440ecord_id"] = record["record_id"]
    refuses(validate, json.dumps({"batches": [record]}), "unknown-key")


def test_g7s_s_009_a_duplicate_json_key_is_refused_never_last_wins():
    validate = sup.require_validate()
    refuses(validate, '{"batches": [], "batches": []}', "duplicate-key")


def test_g7s_s_010_duplicate_key_refusal_is_distinct_from_malformed():
    validate = sup.require_validate()
    refuses(validate, '{"batches": [], "batches": []}', "duplicate-key")
    refuses(validate, "{not json", "malformed-document")


def test_g7s_s_011_a_float_is_refused_including_an_integral_float():
    validate = sup.require_validate()
    for literal in ("1.0", "0.5", "-2.0", "1e2"):
        record = minimal_batch()
        document = json.dumps({"batches": [record]})
        document = document.replace('"batch_ordinal": 1', f'"batch_ordinal": {literal}')
        refuses(validate, document, "float-not-permitted")


def test_g7s_s_012_a_non_finite_literal_is_refused_at_parse_time():
    validate = sup.require_validate()
    for literal in ("NaN", "Infinity", "-Infinity"):
        refuses(
            validate,
            '{"batches": [{"batch_ordinal": ' + literal + "}]}",
            "non-finite-not-permitted",
        )


def test_g7s_s_013_an_overflow_literal_is_refused_never_read_as_infinity():
    validate = sup.require_validate()
    refuses(
        validate,
        '{"batches": [{"batch_ordinal": 1e400}]}',
        "non-finite-not-permitted",
    )


def test_g7s_s_014_a_bool_is_refused_where_an_integer_is_required():
    validate = sup.require_validate()
    for literal in ("true", "false"):
        record = minimal_batch()
        document = json.dumps({"batches": [record]})
        document = document.replace('"batch_ordinal": 1', f'"batch_ordinal": {literal}')
        refuses(validate, document, "bool-not-integer")


def test_g7s_s_015_integer_bounds_are_closed_at_both_edges():
    validate = sup.require_validate()
    for out_of_range in (0, sup.EXPECTED_BATCHES + 1, -1):
        record = minimal_batch()
        record["batch_ordinal"] = out_of_range
        refuses(validate, json.dumps({"batches": [record]}), "integer-out-of-bounds")


def test_g7s_s_016_a_non_ascii_digit_is_refused():
    validate = sup.require_validate()
    record = minimal_batch()
    record["record_id"] = "G7S-BAT-\u0966\u0967\u0968\u0969"
    refuses(validate, json.dumps({"batches": [record]}), "non-ascii-digit")


def test_g7s_s_017_a_wrong_type_is_refused_before_it_is_used():
    validate = sup.require_validate()
    record = minimal_batch()
    record["member_filename"] = 17
    refuses(validate, json.dumps({"batches": [record]}), "wrong-type")


def test_g7s_s_018_a_non_object_root_is_refused():
    validate = sup.require_validate()
    for document in ("[]", '"a string"', "17", "null"):
        refuses(validate, document, "wrong-type")


def test_g7s_s_019_the_three_absence_representations_stay_distinct():
    validate = sup.require_validate()
    record = minimal_batch()
    record["origin_id"] = ""
    refuses(
        validate,
        json.dumps({"batches": [record]}),
        "absence-representation-not-permitted",
    )


def test_g7s_s_020_a_vocabulary_token_outside_its_set_is_refused():
    validate = sup.require_validate()
    record = minimal_batch()
    record["origin_type"] = "inline-user-message"
    refuses(
        validate, json.dumps({"batches": [record]}), "vocabulary-token-not-permitted"
    )


def test_g7s_s_021_canonical_bytes_round_trip_byte_identically():
    schema = sup.require_schema()
    for value in ({}, {"a": 1}, {"b": [1, 2], "a": None}, {"z": {"y": "x"}}):
        raw = schema.canonical_bytes(value)
        assert schema.canonical_bytes(json.loads(raw.decode("utf-8"))) == raw
        assert sup.canonical_digest(value) == sup.canonical_digest(
            json.loads(raw.decode("utf-8"))
        )


def test_g7s_s_022_canonical_form_is_independent_of_input_key_order():
    schema = sup.require_schema()
    first = {"alpha": 1, "beta": 2, "gamma": 3}
    second = {"gamma": 3, "beta": 2, "alpha": 1}
    assert schema.canonical_bytes(first) == schema.canonical_bytes(second)
    assert schema.canonical_bytes(first) == sup.canonical_bytes(first)


def test_g7s_s_023_canonical_output_carries_no_ambient_value():
    schema = sup.require_schema()
    raw = schema.canonical_bytes({"a": 1}).decode("utf-8")
    assert raw == '{"a":1}', raw
    assert " " not in raw
    assert "\n" not in raw


def test_g7s_s_024_the_ledger_equals_its_own_canonical_serialization():
    """Exactly canonical bytes plus one newline. No disjunction.

    CONTRACT.md section 11.1 separates the two rules that used to be conflated
    here: canonical form carries no trailing newline, and every committed blob
    in this laboratory ends with exactly one. The committed file is therefore
    the canonical bytes followed by a single newline, and an earlier form of
    this control accepted either shape, which hid the question rather than
    deciding it.
    """
    ledger = sup.require_ledger()
    raw = sup.committed_blob(f"{sup.LAB_POSIX}/ledger.json")
    canonical = sup.canonical_bytes(ledger)
    assert not canonical.endswith(b"\n"), "canonical form must carry no newline"
    assert raw == canonical + b"\n", "ledger.json is not canonical bytes plus one LF"


def test_g7s_s_025_the_ledger_blob_is_clean_and_lf_only():
    sup.require_ledger()
    raw = sup.committed_blob(f"{sup.LAB_POSIX}/ledger.json")
    assert not sup.blob_defects(raw), sup.blob_defects(raw)


def test_g7s_s_026_every_production_open_declares_its_encoding():
    sup.require_production_source("__init__.py")
    for name in sup.PRODUCTION_MODULES:
        source = sup.require_production_source(name)
        tree = ast.parse(source, optimize=0)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            label = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if label not in ("open", "read_text", "write_text"):
                continue
            keywords = {keyword.arg for keyword in node.keywords}
            positional = [
                argument.value
                for argument in node.args
                if isinstance(argument, ast.Constant)
                and isinstance(argument.value, str)
            ]
            binary = any("b" in mode for mode in positional[1:2]) or any(
                keyword.arg == "mode"
                and isinstance(keyword.value, ast.Constant)
                and "b" in str(keyword.value.value)
                for keyword in node.keywords
            )
            if binary:
                # A binary read is how a member digest is computed over bytes.
                # CONTRACT.md section 11.7 requires an explicit binary mode and
                # NO encoding; requiring `encoding=` here would make the
                # legitimate byte read a TypeError.
                assert "encoding" not in keywords, (name, node.lineno)
                continue
            assert "encoding" in keywords, (name, node.lineno)


def test_g7s_s_027_an_absolute_or_unc_or_device_path_is_refused():
    validate = sup.require_validate()
    for candidate in (
        "C:/absolute/member.txt",
        "C:member.txt",
        "//server/share/member.txt",
        "//./NUL",
        "/rooted/member.txt",
    ):
        record = minimal_batch()
        record["member_filename"] = candidate
        refuses(validate, json.dumps({"batches": [record]}), "path-not-relative")


def test_g7s_s_028_a_traversal_component_is_refused_after_normalization():
    validate = sup.require_validate()
    for candidate in ("a/../b.txt", "./b.txt", "a/./../../b.txt", ".."):
        record = minimal_batch()
        record["member_filename"] = candidate
        refuses(validate, json.dumps({"batches": [record]}), "path-traversal")


def test_g7s_s_029_a_backslash_separator_is_refused_never_normalized():
    validate = sup.require_validate()
    record = minimal_batch()
    record["member_filename"] = "a\\b.txt"
    refuses(
        validate, json.dumps({"batches": [record]}), "path-separator-not-permitted"
    )


def test_g7s_s_030_a_windows_reserved_component_is_refused():
    validate = sup.require_validate()
    for candidate in ("CON", "NUL.txt", "LPT1", "name.", "name "):
        record = minimal_batch()
        record["member_filename"] = candidate
        refuses(
            validate, json.dumps({"batches": [record]}), "path-reserved-component"
        )


def test_g7s_s_031_the_refusal_vocabulary_is_closed_and_matches_the_contract():
    schema = sup.require_schema()
    assert tuple(schema.REFUSAL_TOKENS) == sup.REFUSAL_TOKENS
    assert len(set(schema.REFUSAL_TOKENS)) == len(schema.REFUSAL_TOKENS)
    for token in schema.REFUSAL_TOKENS:
        assert token == token.lower()


def test_g7s_s_032_a_refusal_never_mutates_the_document_it_refused():
    validate = sup.require_validate()
    record = minimal_batch()
    record[sup.MARKER_KEY] = sup.MARKER_VALUE
    document = json.dumps({"batches": [record]})
    before = document.encode("utf-8")
    refuses(validate, document, "unknown-key")
    assert document.encode("utf-8") == before


def test_g7s_s_033_a_well_formed_minimal_document_is_accepted_unchanged():
    """The acceptance half. Without it, refusing everything would pass family S.

    Every other control in this family feeds a malformed payload and requires a
    refusal, so a validator that refused every document with a per-case-correct
    token would satisfy all of them and be useless. CONTRACT.md section 11a
    requires the accepting path too, and requires the value back unchanged.
    """
    validate = sup.require_validate()
    document = json.dumps({"batches": [minimal_batch()]})
    value = validate.validate_document(document)
    assert isinstance(value, dict), type(value).__name__
    assert value["batches"][0]["record_id"] == "G7S-BAT-0001"
    assert sup.canonical_bytes(value) == sup.canonical_bytes(json.loads(document))


def minimal_source() -> dict:
    return {
        "record_id": "G7S-SRC-0001",
        "introducing_batch_ref": "G7S-BAT-0001",
        "locator_carrier_batch_ref": None,
        "supplied_locator": None,
        "normalized_locator": None,
        "normalized_identifier": None,
        "locator_absence_reason": "no-locator-supplied",
        "bibliography_entry": False,
        "supplied_text": None,
        "retrieval_state": "not-attempted",
        "verification_state": "supplied-unretrieved",
        "verification_evidence": None,
    }


def test_g7s_s_034_a_supplied_locator_without_a_carrier_is_refused():
    """The refusal section 6.5 requires, as distinct from the I-018 audit.

    ``locator_carrier_batch_ref`` is nullable, so a supplied locator paired
    with a null carrier is representable and parses. Section 6.5 once claimed
    the state could not be expressed at all; since it can, the validator must
    refuse it, and an audit over committed data would not be that refusal.
    """
    validate = sup.require_validate()
    record = minimal_source()
    record["supplied_locator"] = "https://example.invalid/supplied"
    record["locator_absence_reason"] = None
    record["locator_carrier_batch_ref"] = None
    refuses(
        validate,
        json.dumps({"sources": [record]}),
        "locator-without-carrier",
    )


def test_g7s_s_035_wrong_root_identity_constants_are_refused():
    validate = sup.require_validate()
    identity = {
        "schema_id": sup.SCHEMA_ID,
        "ledger_id": sup.LEDGER_ID,
        "corpus": sup.CORPUS,
    }
    for key in sorted(identity):
        malformed = dict(identity)
        malformed[key] = "wrong-" + key
        refuses(
            validate,
            json.dumps(malformed),
            "vocabulary-token-not-permitted",
        )
