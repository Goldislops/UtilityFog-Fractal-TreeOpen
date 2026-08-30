"""Per-record structural acceptance controls for ``source-record-v1``.

Structure only. Nothing here judges, scores, or infers whether any recorded
claim is true. Every payload is synthetic.

Control ids SR-S-NNN are declared in ``test_controls_manifest.py``.
"""

from __future__ import annotations

import copy

import pytest

from experiments.source_record.tests import _support as sup


# --------------------------------------------------------------------------
# Positive controls
# --------------------------------------------------------------------------


@pytest.mark.parametrize("record_type", sup.RECORD_TYPES)
def test_sr_s_001_a_minimal_valid_record_of_every_type_is_accepted(record_type):
    schema = sup.require_schema()
    sup.assert_accepted(schema, sup.valid_record(record_type))


def test_sr_s_002_every_legal_enum_member_is_accepted_in_its_own_field():
    schema = sup.require_schema()
    for role in sup.ROLES:
        author = (
            sup.UNKNOWN_TOKEN
            if role == "unattributed"
            else "synthetic author one"
        )
        sup.assert_accepted(
            schema,
            sup.assertion_record(asserted_by_role=role, attributed_author=author),
        )
    for scheme in sup.LOCATOR_SCHEMES:
        sup.assert_accepted(
            schema,
            sup.source_record(locators=[sup.locator_block(scheme=scheme)]),
        )
    for link_type in sup.LINK_TYPES:
        sup.assert_accepted(schema, sup.link_record(link_type=link_type))
    for bridge_type in sup.BRIDGE_TYPES:
        sup.assert_accepted(schema, sup.bridge_record(bridge_type=bridge_type))
    for basis in sup.RELATIONSHIP_BASES:
        sup.assert_accepted(schema, sup.link_record(basis=basis))
    for conflict in sup.CONFLICT_BASES:
        sup.assert_accepted(
            schema, sup.contradiction_record(conflict_basis=conflict)
        )


def test_sr_s_003_a_source_with_zero_locators_and_the_maximum_is_accepted():
    schema = sup.require_schema()
    sup.assert_accepted(schema, sup.source_record(locators=[]))
    many = [
        sup.locator_block(value=f"synthetic-handle-{index:04d}")
        for index in range(sup.LOCATORS_MAX)
    ]
    sup.assert_accepted(schema, sup.source_record(locators=many))


# --------------------------------------------------------------------------
# Closed-field discipline
# --------------------------------------------------------------------------


@pytest.mark.parametrize("record_type", sup.RECORD_TYPES)
def test_sr_s_004_every_missing_root_key_is_refused_per_record_type(record_type):
    schema = sup.require_schema()
    base = sup.valid_record(record_type)
    for key in sorted(base):
        payload = copy.deepcopy(base)
        del payload[key]
        sup.assert_refused(schema, payload, "missing-key")


@pytest.mark.parametrize("record_type", sup.RECORD_TYPES)
def test_sr_s_005_an_undeclared_root_key_is_refused_per_record_type(record_type):
    schema = sup.require_schema()
    payload = sup.valid_record(record_type)
    payload["an_undeclared_root_key"] = "synthetic value"
    sup.assert_refused(schema, payload, "undeclared-key")


def test_sr_s_006_an_undeclared_key_in_every_nested_block_is_refused():
    schema = sup.require_schema()
    payload = sup.source_record()
    payload["locators"][0]["an_undeclared_nested_key"] = "synthetic value"
    sup.assert_refused(schema, payload, "undeclared-key")

    payload = sup.source_record()
    payload["issuer_claim"]["an_undeclared_nested_key"] = "synthetic value"
    sup.assert_refused(schema, payload, "undeclared-key")

    payload = sup.source_record(
        supersedes={
            "record_id": "SR-A-SRC-0002",
            "content_digest": "0" * 64,
            "an_undeclared_nested_key": "synthetic value",
        }
    )
    sup.assert_refused(schema, payload, "undeclared-key")


def test_sr_s_007_a_missing_key_in_every_nested_block_is_refused():
    schema = sup.require_schema()
    for key in sorted(sup.LOCATOR_KEYS):
        block = sup.locator_block()
        del block[key]
        sup.assert_refused(
            schema, sup.source_record(locators=[block]), "missing-key"
        )
    for key in sorted(sup.ISSUER_CLAIM_KEYS):
        block = sup.issuer_claim_block()
        del block[key]
        sup.assert_refused(
            schema, sup.source_record(issuer_claim=block), "missing-key"
        )


def test_sr_s_008_a_foreign_mapping_key_is_refused_without_being_touched():
    schema = sup.require_schema()
    hostile_key = sup.Betrayer()
    payload = sup.source_record()
    payload[hostile_key] = "synthetic value"
    hostile_key.reset_hooks()
    error = sup.assert_refused(schema, payload, "key-not-exact-str")
    assert not hostile_key.any_hook_ran(), hostile_key.hooks
    assert sup.MARKER_VALUE not in str(error)


def test_sr_s_009_a_key_differing_only_by_case_is_refused_and_never_folded():
    schema = sup.require_schema()
    for variant in ("Schema", "RECORD_ID", "Register"):
        payload = sup.source_record()
        original = variant.lower()
        payload[variant] = payload.pop(original)
        sup.assert_refused(schema, payload, "undeclared-key")


def test_sr_s_010_a_unicode_confusable_key_is_refused_and_never_normalized():
    schema = sup.require_schema()
    # Cyrillic es U+0441 in place of ASCII c; fullwidth s U+FF53.
    for variant in ("reсord_id", "ｓchema"):
        payload = sup.source_record()
        payload[variant] = "synthetic value"
        sup.assert_refused(schema, payload, "undeclared-key")


def test_sr_s_011_the_root_must_be_an_exact_builtin_dict():
    schema = sup.require_schema()
    hostile = sup.HookedDict(sup.source_record())
    hostile.reset_hooks()
    sup.assert_refused(schema, hostile, "type-not-exact")
    assert not hostile.any_hook_ran(), hostile.hooks
    for wrong in ([], (), "", 0, None):
        sup.assert_refused(schema, wrong, "root-not-object")


# --------------------------------------------------------------------------
# Type discipline
# --------------------------------------------------------------------------


def test_sr_s_012_a_hostile_str_subclass_is_refused_before_any_hook_runs():
    schema = sup.require_schema()
    for field in ("neutral_label", "recorded_by_label"):
        hostile = sup.HookedStr("synthetic value")
        hostile.reset_hooks()
        sup.assert_refused(
            schema, sup.source_record(**{field: hostile}), "type-not-exact"
        )
        assert not hostile.any_hook_ran(), (field, hostile.hooks)


def test_sr_s_013_a_hostile_int_subclass_is_refused_before_any_hook_runs():
    schema = sup.require_schema()
    hostile = sup.HookedInt(3)
    hostile.reset_hooks()
    sup.assert_refused(
        schema, sup.message_record(sequence_ordinal=hostile), "type-not-exact"
    )
    assert not hostile.any_hook_ran(), hostile.hooks


def test_sr_s_014_hostile_container_subclasses_are_refused_before_iteration():
    schema = sup.require_schema()
    hostile_list = sup.HookedList([sup.locator_block()])
    hostile_list.reset_hooks()
    sup.assert_refused(
        schema, sup.source_record(locators=hostile_list), "type-not-exact"
    )
    assert not hostile_list.any_hook_ran(), hostile_list.hooks

    hostile_tuple = sup.HookedTuple((sup.locator_block(),))
    hostile_tuple.reset_hooks()
    sup.assert_refused(
        schema, sup.source_record(locators=hostile_tuple), "type-not-exact"
    )
    assert not hostile_tuple.any_hook_ran(), hostile_tuple.hooks

    hostile_block = sup.HookedDict(sup.issuer_claim_block())
    hostile_block.reset_hooks()
    sup.assert_refused(
        schema, sup.source_record(issuer_claim=hostile_block), "type-not-exact"
    )
    assert not hostile_block.any_hook_ran(), hostile_block.hooks


def test_sr_s_015_hostile_bytes_are_refused_and_never_decoded():
    schema = sup.require_schema()
    hostile = sup.HookedBytes(b"synthetic value")
    hostile.reset_hooks()
    sup.assert_refused(
        schema, sup.source_record(neutral_label=hostile), "type-not-exact"
    )
    assert not hostile.any_hook_ran(), hostile.hooks
    sup.assert_refused(
        schema, sup.source_record(neutral_label=b"synthetic"), "type-not-exact"
    )


def test_sr_s_016_a_mapping_that_would_answer_differently_is_refused_before_it_can():
    schema = sup.require_schema()
    hostile = sup.MutatingDict(
        sup.source_record(), "record_id", "SR-B-SRC-9999"
    )
    sup.assert_refused(schema, hostile, "type-not-exact")
    assert hostile.reads == 0, (
        "exact-builtin-dict discipline must refuse before any key is read"
    )


def test_sr_s_017_a_bool_is_refused_wherever_an_int_is_required():
    schema = sup.require_schema()
    for value in (True, False):
        sup.assert_refused(
            schema, sup.message_record(sequence_ordinal=value), "type-not-exact"
        )


def test_sr_s_018_a_float_anywhere_is_refused_including_integral_values():
    schema = sup.require_schema()
    for value in (1.0, 0.5, float("inf"), float("-inf"), float("nan")):
        sup.assert_refused(
            schema, sup.message_record(sequence_ordinal=value), "float-refused"
        )


def test_sr_s_019_an_integer_outside_its_declared_range_is_refused():
    schema = sup.require_schema()
    for value in (sup.ORDINAL_MIN - 1, sup.ORDINAL_MAX + 1, -1, 10**40):
        sup.assert_refused(
            schema,
            sup.message_record(sequence_ordinal=value),
            "int-out-of-range",
        )
    sup.assert_accepted(schema, sup.message_record(sequence_ordinal=sup.ORDINAL_MIN))
    sup.assert_accepted(schema, sup.message_record(sequence_ordinal=sup.ORDINAL_MAX))


def test_sr_s_020_non_ascii_decimal_digits_are_refused_in_ids_and_dates():
    schema = sup.require_schema()
    arabic_indic = "SR-A-SRC-٠٠١٢"
    devanagari_date = "2026-०४-28"
    sup.assert_refused(
        schema, sup.source_record(record_id=arabic_indic), "digits-not-ascii"
    )
    sup.assert_refused(
        schema,
        sup.source_record(recorded_date=devanagari_date),
        "digits-not-ascii",
    )


def test_sr_s_021_an_impossible_or_malformed_calendar_date_is_refused():
    schema = sup.require_schema()
    for value in ("2026-02-30", "2026-13-01", "2026-00-10", "2026-8-28", "20260828"):
        sup.assert_refused(
            schema, sup.source_record(recorded_date=value), "date-invalid"
        )


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------


def test_sr_s_022_a_record_id_outside_the_exact_grammar_is_refused():
    schema = sup.require_schema()
    for value in (
        "SR-A-SRC-001",
        "SR-A-SRC-00001",
        "sr-a-src-0001",
        "SR-C-SRC-0001",
        "SR-A-XXX-0001",
        "AM-0001",
        " SR-A-SRC-0001",
        "SR-A-SRC-0001 ",
        "SR-A-SRC-0001\n",
        "",
    ):
        sup.assert_refused(
            schema, sup.source_record(record_id=value), "record-id-malformed"
        )


def test_sr_s_023_a_register_field_disagreeing_with_the_id_segment_is_refused():
    schema = sup.require_schema()
    sup.assert_refused(
        schema,
        sup.source_record(register="register-b"),
        "record-id-register-mismatch",
    )
    sup.assert_refused(
        schema,
        sup.bridge_record(register="register-a"),
        "record-id-register-mismatch",
    )


def test_sr_s_024_a_record_type_field_disagreeing_with_the_id_segment_is_refused():
    schema = sup.require_schema()
    payload = sup.source_record()
    payload["record_type"] = "message"
    sup.assert_refused(schema, payload, "record-id-type-mismatch")


def test_sr_s_025_an_unknown_schema_identifier_is_refused_without_migration():
    schema = sup.require_schema()
    for value in ("source-record-v0", "source-record-v2", "source-record-v1 "):
        sup.assert_refused(
            schema, sup.source_record(schema=value), "schema-id-invalid"
        )


# --------------------------------------------------------------------------
# Synthetic-only closure
# --------------------------------------------------------------------------


def test_sr_s_026_every_synthetic_only_field_is_closed_to_its_single_token():
    schema = sup.require_schema()
    sup.assert_refused(
        schema, sup.source_record(origin="ingested"), "enum-value-invalid"
    )
    sup.assert_refused(
        schema,
        sup.assertion_record(verification_state="verified-primary"),
        "verification-state-invalid",
    )
    sup.assert_refused(
        schema,
        sup.assertion_record(verification_evidence={"reference": "synthetic-x"}),
        "verification-evidence-not-null",
    )
    sup.assert_refused(
        schema,
        sup.source_record(
            locators=[sup.locator_block(resolution="resolved")]
        ),
        "enum-value-invalid",
    )
    sup.assert_refused(
        schema,
        sup.contradiction_record(resolution_state="resolved"),
        "resolution-state-invalid",
    )


def test_sr_s_027_a_locator_value_outside_the_anchored_synthetic_pattern_is_refused():
    schema = sup.require_schema()
    for value in (
        "handle-0001",
        "Synthetic-handle-0001",
        "synthetic-Handle",
        "prefix-synthetic-handle-0001",
        "synthetic-handle-0001-" + "x" * 64,
        "",
    ):
        sup.assert_refused(
            schema,
            sup.source_record(locators=[sup.locator_block(value=value)]),
            "locator-value-not-synthetic",
        )


# --------------------------------------------------------------------------
# Attribution, null and unknown
# --------------------------------------------------------------------------


def test_sr_s_028_derived_from_is_required_for_inference_and_forbidden_otherwise():
    schema = sup.require_schema()
    sup.assert_refused(
        schema,
        sup.assertion_record(
            attribution_class="derived-inference", derived_from=None
        ),
        "derived-from-required",
    )
    sup.assert_refused(
        schema,
        sup.assertion_record(
            attribution_class="derived-inference", derived_from=[]
        ),
        "derived-from-required",
    )
    for other in (
        "receipt-fact",
        "attributed-assertion",
        "recorded-observation",
    ):
        instrument = (
            "synthetic instrument context"
            if other == "recorded-observation"
            else None
        )
        sup.assert_refused(
            schema,
            sup.assertion_record(
                attribution_class=other,
                instrument_context=instrument,
                derived_from=["SR-A-ASR-0002"],
            ),
            "derived-from-forbidden",
        )
    sup.assert_accepted(
        schema,
        sup.assertion_record(
            attribution_class="derived-inference",
            derived_from=["SR-A-ASR-0002"],
        ),
    )


def test_sr_s_029_derived_from_may_reference_only_same_register_assertion_ids():
    schema = sup.require_schema()
    for wrong in ("SR-A-SRC-0002", "SR-A-MSG-0002", "SR-A-LNK-0002"):
        sup.assert_refused(
            schema,
            sup.assertion_record(
                attribution_class="derived-inference", derived_from=[wrong]
            ),
            "reference-wrong-type",
        )
    sup.assert_refused(
        schema,
        sup.assertion_record(
            attribution_class="derived-inference",
            derived_from=["SR-B-ASR-0002"],
        ),
        "reference-wrong-register",
    )
    sup.assert_refused(
        schema,
        sup.assertion_record(
            attribution_class="derived-inference",
            derived_from=["SR-A-ASR-0002", "SR-A-ASR-0002"],
        ),
        "list-duplicate-item",
    )


def test_sr_s_030_instrument_context_is_required_only_for_recorded_observation():
    schema = sup.require_schema()
    sup.assert_refused(
        schema,
        sup.assertion_record(
            attribution_class="recorded-observation", instrument_context=None
        ),
        "instrument-context-required",
    )
    sup.assert_accepted(
        schema,
        sup.assertion_record(
            attribution_class="recorded-observation",
            instrument_context=sup.UNKNOWN_TOKEN,
        ),
    )
    sup.assert_refused(
        schema,
        sup.assertion_record(
            attribution_class="attributed-assertion",
            instrument_context="synthetic instrument context",
        ),
        "instrument-context-forbidden",
    )


def test_sr_s_031_the_unattributed_role_and_the_unknown_author_token_are_paired():
    schema = sup.require_schema()
    sup.assert_refused(
        schema,
        sup.assertion_record(
            asserted_by_role="unattributed", attributed_author="synthetic author"
        ),
        "attribution-author-mismatch",
    )
    sup.assert_refused(
        schema,
        sup.assertion_record(
            asserted_by_role="relay-agent", attributed_author=sup.UNKNOWN_TOKEN
        ),
        "attribution-author-mismatch",
    )
    sup.assert_accepted(
        schema,
        sup.assertion_record(
            asserted_by_role="unattributed", attributed_author=sup.UNKNOWN_TOKEN
        ),
    )


def test_sr_s_032_null_and_the_unknown_token_are_never_interchangeable():
    schema = sup.require_schema()
    sup.assert_refused(
        schema, sup.source_record(neutral_label=None), "null-not-permitted"
    )
    sup.assert_refused(
        schema,
        sup.source_record(issuer_claim=sup.issuer_claim_block(claimed_issuer=None)),
        "null-not-permitted",
    )
    sup.assert_refused(
        schema,
        sup.message_record(sequence_ordinal=sup.UNKNOWN_TOKEN),
        "unknown-token-not-permitted",
    )
    sup.assert_refused(
        schema,
        sup.source_record(recorded_by_label=sup.UNKNOWN_TOKEN),
        "unknown-token-not-permitted",
    )
    sup.assert_accepted(schema, sup.message_record(sequence_ordinal=None))


def test_sr_s_033_an_empty_or_overlong_free_text_field_is_refused():
    schema = sup.require_schema()
    sup.assert_refused(
        schema, sup.source_record(neutral_label=""), "string-empty"
    )
    sup.assert_refused(
        schema,
        sup.source_record(neutral_label="x" * (sup.TEXT_MAX + 1)),
        "string-length-invalid",
    )
    sup.assert_refused(
        schema,
        sup.source_record(recorded_by_label="x" * (sup.LABEL_MAX + 1)),
        "string-length-invalid",
    )
    sup.assert_accepted(
        schema, sup.source_record(recorded_by_label="x" * sup.LABEL_MAX)
    )


def test_sr_s_034_a_lone_surrogate_or_null_byte_in_free_text_is_refused():
    schema = sup.require_schema()
    for value in ("synthetic\ud800label", "synthetic\x00label"):
        sup.assert_refused(
            schema,
            sup.source_record(neutral_label=value),
            "string-not-valid-unicode",
        )


def test_sr_s_035_a_record_id_grammar_substring_in_free_text_is_refused():
    schema = sup.require_schema()
    sup.assert_refused(
        schema,
        sup.source_record(neutral_label="see SR-B-SRC-0001 for the other one"),
        "string-contains-record-id",
    )
    sup.assert_refused(
        schema,
        sup.assertion_record(claim_text="derived from SR-A-ASR-0002"),
        "string-contains-record-id",
    )


# --------------------------------------------------------------------------
# Bridge shape and lineage block shape
# --------------------------------------------------------------------------


def test_sr_s_036_the_bridge_key_set_carries_no_asserting_field():
    schema = sup.require_schema()
    assert not (schema.ROOT_KEYS["bridge"] & sup.ASSERTING_FIELDS), (
        "a bridge relates and must never assert"
    )
    for field in sorted(sup.ASSERTING_FIELDS):
        payload = sup.bridge_record()
        payload[field] = "synthetic value"
        sup.assert_refused(schema, payload, "undeclared-key")


def test_sr_s_037_a_bridge_side_in_the_wrong_register_or_of_the_wrong_type_is_refused():
    schema = sup.require_schema()
    sup.assert_refused(
        schema, sup.bridge_record(side_b="SR-A-SRC-0002"),
        "bridge-side-register-invalid",
    )
    sup.assert_refused(
        schema, sup.bridge_record(side_a="SR-B-SRC-0002"),
        "bridge-side-register-invalid",
    )
    sup.assert_refused(
        schema, sup.bridge_record(side_a="SR-X-BRG-0002"),
        "bridge-endpoint-not-source",
    )
    sup.assert_refused(
        schema, sup.bridge_record(side_b="SR-B-MSG-0001"),
        "bridge-endpoint-not-source",
    )


def test_sr_s_038_a_non_bridge_reference_into_the_other_register_is_refused():
    schema = sup.require_schema()
    sup.assert_refused(
        schema, sup.link_record(right_ref="SR-B-SRC-0002"),
        "reference-wrong-register",
    )
    sup.assert_refused(
        schema, sup.assertion_record(subject_ref="SR-B-SRC-0001"),
        "reference-wrong-register",
    )
    sup.assert_refused(
        schema,
        sup.contradiction_record(right_assertion_ref="SR-B-ASR-0002"),
        "reference-wrong-register",
    )


def test_sr_s_039_a_reference_of_the_wrong_record_type_is_refused():
    schema = sup.require_schema()
    sup.assert_refused(
        schema, sup.assertion_record(message_ref="SR-A-SRC-0001"),
        "reference-wrong-type",
    )
    sup.assert_refused(
        schema, sup.link_record(left_ref="SR-A-MSG-0001"),
        "reference-wrong-type",
    )
    sup.assert_refused(
        schema,
        sup.contradiction_record(left_assertion_ref="SR-A-SRC-0001"),
        "reference-wrong-type",
    )


def test_sr_s_040_a_self_reference_is_refused():
    schema = sup.require_schema()
    sup.assert_refused(
        schema,
        sup.link_record(record_id="SR-A-LNK-0001", left_ref="SR-A-LNK-0001"),
        "reference-self",
    )
    sup.assert_refused(
        schema,
        sup.source_record(
            record_id="SR-A-SRC-0001",
            supersedes={
                "record_id": "SR-A-SRC-0001",
                "content_digest": "0" * 64,
            },
        ),
        "supersedes-self",
    )


def test_sr_s_041_a_supersedes_block_of_the_wrong_shape_is_refused():
    schema = sup.require_schema()
    sup.assert_refused(
        schema,
        sup.source_record(
            supersedes={"record_id": "SR-B-SRC-0002", "content_digest": "0" * 64}
        ),
        "supersedes-register-mismatch",
    )
    sup.assert_refused(
        schema,
        sup.source_record(
            supersedes={"record_id": "SR-A-MSG-0002", "content_digest": "0" * 64}
        ),
        "supersedes-type-mismatch",
    )

def test_sr_s_050_a_digest_of_the_wrong_format_is_refused_on_format_not_on_type():
    """A 64-character non-hexadecimal string is an exact str of the wrong shape.

    Refusing it with a type token would be dishonest, and refusing it with a
    free-text length token would be wrong for the wrong-alphabet and
    wrong-case cases. CONTRACT.md I83 gives it its own token.
    """
    schema = sup.require_schema()
    for bad_digest in (
        "0" * 63,
        "0" * 65,
        "G" * 64,
        "A" * 64,
        "0" * 63 + " ",
        " " + "0" * 63,
        "",
    ):
        sup.assert_refused(
            schema,
            sup.source_record(
                supersedes={
                    "record_id": "SR-A-SRC-0002",
                    "content_digest": bad_digest,
                }
            ),
            "digest-format-invalid",
        )
    # A non-string digest is refused earlier, on exact type, not on format.
    for wrong_type in (0, None, [], sup.HookedStr("0" * 64)):
        sup.assert_refused(
            schema,
            sup.source_record(
                supersedes={
                    "record_id": "SR-A-SRC-0002",
                    "content_digest": wrong_type,
                }
            ),
            "type-not-exact",
        )


def test_sr_s_051_derived_from_accepts_its_upper_bound_and_refuses_one_beyond():
    schema = sup.require_schema()
    at_bound = [
        f"SR-A-ASR-{index + 2:04d}" for index in range(sup.DERIVED_FROM_MAX)
    ]
    sup.assert_accepted(
        schema,
        sup.assertion_record(
            attribution_class="derived-inference", derived_from=at_bound
        ),
    )
    beyond = at_bound + [f"SR-A-ASR-{sup.DERIVED_FROM_MAX + 2:04d}"]
    sup.assert_refused(
        schema,
        sup.assertion_record(
            attribution_class="derived-inference", derived_from=beyond
        ),
        "list-length-invalid",
    )


def test_sr_s_042_a_duplicate_list_item_is_refused():
    schema = sup.require_schema()
    block = sup.locator_block()
    sup.assert_refused(
        schema,
        sup.source_record(locators=[block, dict(block)]),
        "list-duplicate-item",
    )


def test_sr_s_043_a_list_longer_than_its_declared_bound_is_refused():
    schema = sup.require_schema()
    many = [
        sup.locator_block(value=f"synthetic-handle-{index:04d}")
        for index in range(sup.LOCATORS_MAX + 1)
    ]
    sup.assert_refused(
        schema, sup.source_record(locators=many), "list-length-invalid"
    )


# --------------------------------------------------------------------------
# Purity, canonicalization, vocabulary totality
# --------------------------------------------------------------------------


@pytest.mark.parametrize("record_type", sup.RECORD_TYPES)
def test_sr_s_044_validation_never_mutates_infers_or_upgrades_anything(record_type):
    schema = sup.require_schema()
    payload = sup.valid_record(record_type)
    snapshot = copy.deepcopy(payload)
    schema.validate_record(payload)
    assert payload == snapshot
    assert sup.canonical_bytes(payload) == sup.canonical_bytes(snapshot)


def test_sr_s_045_canonical_form_and_digest_are_key_order_independent():
    schema = sup.require_schema()
    payload = sup.source_record()
    shuffled = {key: payload[key] for key in sorted(payload, reverse=True)}
    assert schema.canonical_bytes(payload) == schema.canonical_bytes(shuffled)
    assert schema.digest(payload) == schema.digest(shuffled)
    assert schema.canonical_bytes(payload) == sup.canonical_bytes(payload)
    assert schema.digest(payload) == sup.digest_of(payload)


def test_sr_s_046_canonical_output_carries_no_timestamp_and_is_ascii_escaped():
    schema = sup.require_schema()
    payload = sup.source_record(neutral_label="synthetic label éè")
    rendered = schema.canonical_bytes(payload)
    assert rendered == rendered.decode("ascii").encode("ascii")
    assert b"\\u00e9" in rendered
    assert not rendered.endswith(b"\n")
    assert sup.FIXTURE_DATE.encode("ascii") in rendered


def test_sr_s_047_the_declared_vocabularies_match_this_suite_exactly():
    schema = sup.require_schema()
    pairs = (
        ("REGISTERS", sup.REGISTERS),
        ("RECORD_TYPES", sup.RECORD_TYPES),
        ("ORIGINS", sup.ORIGINS),
        ("VERIFICATION_STATES", sup.VERIFICATION_STATES),
        ("RESOLUTION_STATES", sup.RESOLUTION_STATES),
        ("LOCATOR_SCHEMES", sup.LOCATOR_SCHEMES),
        ("LOCATOR_RESOLUTIONS", sup.LOCATOR_RESOLUTIONS),
        ("ATTRIBUTION_CLASSES", sup.ATTRIBUTION_CLASSES),
        ("ROLES", sup.ROLES),
        ("LINK_TYPES", sup.LINK_TYPES),
        ("BRIDGE_TYPES", sup.BRIDGE_TYPES),
        ("RELATIONSHIP_BASES", sup.RELATIONSHIP_BASES),
        ("CONFLICT_BASES", sup.CONFLICT_BASES),
    )
    for name, expected in pairs:
        assert tuple(getattr(schema, name)) == tuple(expected), name
    assert schema.SCHEMA_ID == sup.SCHEMA_ID
    assert schema.UNKNOWN_TOKEN == sup.UNKNOWN_TOKEN
    for record_type in sup.RECORD_TYPES:
        assert schema.ROOT_KEYS[record_type] == sup.ROOT_KEYS[record_type]
    assert schema.LOCATOR_KEYS == sup.LOCATOR_KEYS
    assert schema.ISSUER_CLAIM_KEYS == sup.ISSUER_CLAIM_KEYS
    assert schema.SUPERSEDES_KEYS == sup.SUPERSEDES_KEYS


def test_sr_s_048_the_refusal_token_vocabulary_is_closed_and_well_formed():
    schema = sup.require_schema()
    declared = tuple(schema.REFUSAL_TOKENS)
    assert set(declared) == set(sup.REFUSAL_TOKENS)
    assert len(declared) == len(set(declared)), "duplicate refusal token"
    for token in declared:
        assert token == token.lower()
        assert token.strip() == token and token
        assert set(token) <= set("abcdefghijklmnopqrstuvwxyz-")


def test_sr_s_049_no_relationship_vocabulary_contains_an_evaluative_token():
    schema = sup.require_schema()
    forbidden_fragments = (
        "duplicate",
        "corrobor",
        "support",
        "confirm",
        "authentic",
        "genuine",
        "debunk",
        "credib",
        "reliab",
        "same-subject",
    )
    for token in tuple(schema.LINK_TYPES) + tuple(schema.BRIDGE_TYPES):
        for fragment in forbidden_fragments:
            assert fragment not in token, (token, fragment)
    assert "commentary-about" not in schema.BRIDGE_TYPES
