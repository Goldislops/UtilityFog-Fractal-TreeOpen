"""Family P --- attribution, verification standing and additive correction.

Every control begins with a gate call and fails, at the contract-only head,
with the single reason ``implementation-absent``.

Nothing here retrieves, opens, resolves or contacts a locator, and every
fixture is synthetic.
"""

from __future__ import annotations

import json

import pytest

from experiments.general_v7_supplied_source_ledger.tests import _support as sup


def records(ledger: dict, collection: str) -> list:
    value = ledger.get(collection)
    assert isinstance(value, list), f"{collection}: expected a list"
    return value


def controlled_values(value, key=None):
    """String leaves sitting in a controlled-vocabulary or status field.

    Deliberately NOT every string leaf. Supplied titles and supplied locators
    are preserved byte-for-byte under CONTRACT.md section 6.2, so scanning them
    for promotion vocabulary would make preservation and the vocabulary rule
    unsatisfiable at the same time: a supplied title containing "confirmed"
    would have to be both kept verbatim and refused.
    """
    if isinstance(value, str):
        if key in sup.CONTROLLED_VOCABULARY_FIELDS:
            yield key, value
    elif isinstance(value, dict):
        for name, item in value.items():
            yield from controlled_values(item, name)
    elif isinstance(value, list):
        for item in value:
            yield from controlled_values(item, key)


def refuses(validate, document: str, token: str) -> None:
    with pytest.raises(validate.RefusalError) as info:
        validate.validate_document(document)
    assert info.value.token == token, (info.value.token, token)


def test_g7s_p_001_every_claim_carries_exactly_one_attribution_class():
    ledger = sup.require_ledger()
    for record in records(ledger, "claims"):
        assert record["attribution_class"] in sup.ATTRIBUTION_CLASSES, record


def test_g7s_p_002_no_claim_is_verified_at_intake():
    ledger = sup.require_ledger()
    verified = [
        record
        for record in records(ledger, "claims")
        if record["verification_state"] != "unverified"
    ]
    # Emptiness is computed. CONTRACT.md section 7 requires counts to be
    # computed and never asserted from a constant; the declared admission
    # standing is then reconciled against it rather than standing in for it.
    assert not verified, verified
    assert len(verified) == sup.FROZEN_ADMISSION_STANDING["verified_claims"]


def test_g7s_p_003_every_verification_state_is_in_its_fixed_vocabulary():
    ledger = sup.require_ledger()
    for record in records(ledger, "sources"):
        assert record["verification_state"] in sup.SOURCE_VERIFICATION_STATES
        assert record["retrieval_state"] in sup.RETRIEVAL_STATES
    for record in records(ledger, "relationships"):
        assert record["verification_state"] in sup.RELATIONSHIP_VERIFICATION_STATES
    for record in records(ledger, "unresolved"):
        assert record["state"] in sup.UNRESOLVED_STATES


def test_g7s_p_004_verification_evidence_is_null_while_unverified():
    ledger = sup.require_ledger()
    for record in records(ledger, "sources"):
        if record["verification_state"] == "supplied-unretrieved":
            assert record.get("verification_evidence") is None, record["record_id"]


def test_g7s_p_005_supplied_and_summarised_standings_are_separated():
    ledger = sup.require_ledger()
    for record in records(ledger, "claims"):
        attribution = record["attribution_class"]
        evidence = record.get("byte_evidence")
        if attribution.startswith("supplied-by-kev"):
            assert evidence is not None, record["record_id"]
        if attribution.startswith("aura-"):
            assert evidence is None, record["record_id"]
            assert record.get("limitations"), record["record_id"]


def test_g7s_p_006_no_promotion_vocabulary_enters_a_controlled_field():
    ledger = sup.require_ledger()
    for field, value in controlled_values(ledger):
        lowered = value.lower()
        for fragment in sup.FORBIDDEN_PROMOTION_FRAGMENTS:
            assert fragment not in lowered, (field, fragment, value[:60])


def test_g7s_p_007_a_correction_never_edits_its_target():
    """Additive means the target still validates on its own terms.

    An earlier form asserted only that the resolved target's own id equalled
    the id it was looked up by, which the lookup makes true by construction.
    What actually has to hold is that the target still carries its full
    declared shape and that the correction added no field to it.
    """
    ledger = sup.require_ledger()
    known = {}
    for collection in sup.COLLECTIONS:
        for record in records(ledger, collection):
            known[record["record_id"]] = (collection, record)
    for correction in records(ledger, "corrections"):
        target = correction["target_ref"]
        assert target in known, target
        collection, record = known[target]
        declared = set(sup.RECORD_FIELDS[collection])
        assert set(record) == declared, (target, sorted(set(record) ^ declared))
        assert "corrected_by" not in record, target
        assert "superseded_by" not in record, target


def test_g7s_p_008_a_correction_may_not_target_a_correction():
    ledger = sup.require_ledger()
    correction_ids = {record["record_id"] for record in records(ledger, "corrections")}
    for correction in records(ledger, "corrections"):
        assert correction["target_ref"] not in correction_ids, correction["record_id"]


def test_g7s_p_009_a_correction_targeting_a_correction_is_refused():
    validate = sup.require_validate()
    document = json.dumps(
        {
            "corrections": [
                {
                    "record_id": "G7S-COR-0001",
                    "target_ref": "G7S-COR-0002",
                    "correction_kind": "correction",
                }
            ]
        }
    )
    refuses(validate, document, "correction-target-not-permitted")


def test_g7s_p_010_supersession_is_reciprocal_in_both_directions():
    ledger = sup.require_ledger()
    by_id = {record["record_id"]: record for record in records(ledger, "corrections")}
    for record in by_id.values():
        if record["correction_kind"] != "supersession":
            continue
        partner = record.get("reciprocal_ref")
        assert partner in by_id, (record["record_id"], partner)
        assert by_id[partner].get("reciprocal_ref") == record["record_id"]
        assert partner != record["record_id"]


def test_g7s_p_011_a_one_sided_supersession_is_refused():
    validate = sup.require_validate()
    document = json.dumps(
        {
            "corrections": [
                {
                    "record_id": "G7S-COR-0001",
                    "target_ref": "G7S-CLM-0001",
                    "correction_kind": "supersession",
                    "reciprocal_ref": "G7S-COR-0002",
                }
            ]
        }
    )
    refuses(validate, document, "supersession-not-reciprocal")


def test_g7s_p_012_a_supersession_target_keeps_its_verification_state():
    """Named for what it checks: the supersession pair promotes nothing.

    An earlier form re-asserted the global fixed states, which G7S-P-003 and
    G7S-P-016 already cover, and never looked at a supersession at all.
    """
    ledger = sup.require_ledger()
    by_id = {}
    for collection in sup.COLLECTIONS:
        for record in records(ledger, collection):
            by_id[record["record_id"]] = record
    for correction in records(ledger, "corrections"):
        if correction["correction_kind"] != "supersession":
            continue
        target = by_id[correction["target_ref"]]
        if "verification_state" in target:
            assert target["verification_state"] in (
                "supplied-unretrieved",
                "unverified",
            ), (correction["record_id"], target["verification_state"])


def test_g7s_p_013_relationship_endpoints_are_distinct():
    ledger = sup.require_ledger()
    seen = set()
    for record in records(ledger, "relationships"):
        left, right = record["left_ref"], record["right_ref"]
        assert left != right, record["record_id"]
        triple = (left, right, record["relationship_type"])
        assert triple not in seen, triple
        seen.add(triple)


def test_g7s_p_014_a_self_relationship_is_refused():
    validate = sup.require_validate()
    document = json.dumps(
        {
            "relationships": [
                {
                    "record_id": "G7S-REL-0001",
                    "left_ref": "G7S-SRC-0001",
                    "right_ref": "G7S-SRC-0001",
                    "relationship_type": "same-supplied-identifier",
                    "verification_state": "unverified",
                }
            ]
        }
    )
    refuses(validate, document, "relationship-endpoints-identical")


def test_g7s_p_015_every_relationship_type_is_in_the_closed_vocabulary():
    ledger = sup.require_ledger()
    for record in records(ledger, "relationships"):
        assert record["relationship_type"] in sup.RELATIONSHIP_TYPES


def test_g7s_p_016_nothing_is_retrieved_or_verified_and_the_standing_agrees():
    """Emptiness first, reconciliation second.

    An earlier form was named for computing counts while comparing each
    computed length to a frozen constant that section 5a then advertised as
    packet-reproduced --- the exact path by which an admission value could
    masquerade as a packet fact. The emptiness checks below need no constant
    at all; the declared admission standing is reconciled against them
    afterwards, and is now classified as admission standing rather than as a
    packet fact.
    """
    ledger = sup.require_ledger()
    retrieved = [
        record
        for record in records(ledger, "sources")
        if record["retrieval_state"] != "not-attempted"
    ]
    assert not retrieved, retrieved
    verified = [
        record
        for record in records(ledger, "sources")
        if record["verification_state"] != "supplied-unretrieved"
    ]
    assert not verified, verified
    verified_relationships = [
        record
        for record in records(ledger, "relationships")
        if record["verification_state"] != "unverified"
    ]
    assert not verified_relationships, verified_relationships
    standing = sup.FROZEN_ADMISSION_STANDING
    assert len(retrieved) == standing["retrieved"]
    assert len(verified) == standing["verified_sources"]
    assert len(verified_relationships) == standing["verified_relationships"]
