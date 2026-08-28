"""Epistemic, attribution, artifact, quarantine and conflict controls.

Implementation-dependent. These controls assert *coverage and neutrality*.
They never assert that any recorded claim is true, and never assert that either
side of a recorded conflict is correct.

Control ids GV7-P-NNN are declared in ``test_controls_manifest.py``.
"""

from __future__ import annotations

import json
import re

import pytest

from experiments.general_v7_ledger.tests import _support as sup

#: Shapes that would make a quarantined summary operational rather than
#: descriptive. None may appear anywhere in the ledger.
OPERATIONAL_SHAPES = (
    re.compile(r"(?m)^\s*(sudo|curl|wget|nc|ncat|nmap|ssh|scp)\s+"),
    re.compile(r"(?i)\b(api[_-]?key|secret[_-]?key|password|bearer\s+[A-Za-z0-9._-]{8,})\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bpip\s+install\b"),
    re.compile(r"(?i)\brm\s+-rf\b"),
    re.compile(r"(?i)\bpowershell\s+-(enc|e)\b"),
)


def test_gv7_p_001_every_source_identity_remains_unverified():
    ledger = sup.require_ledger()
    for source in ledger["sources"]:
        assert source["verification_state"] == "supplied-unretrieved"
        assert source["verification_state"] in sup.SOURCE_VERIFICATION_STATES


def test_gv7_p_002_every_source_remains_not_attempted():
    ledger = sup.require_ledger()
    for source in ledger["sources"]:
        assert source["retrieval_state"] == "not-attempted"
        assert source["retrieval_state"] in sup.RETRIEVAL_STATES


def test_gv7_p_003_every_claim_remains_unverified():
    ledger = sup.require_ledger()
    for claim in ledger["claims"]:
        assert claim["verification_state"] == "unverified"
        assert claim["verification_state"] in sup.CLAIM_VERIFICATION_STATES


def test_gv7_p_004_every_claim_carries_class_basis_limitation_and_disposition():
    ledger = sup.require_ledger()
    for claim in ledger["claims"]:
        assert claim["attribution_class"] in sup.ATTRIBUTION_CLASSES
        assert isinstance(claim["evidence_basis"], str) and claim["evidence_basis"]
        assert isinstance(claim["limitations"], list) and claim["limitations"]
        for limitation in claim["limitations"]:
            assert isinstance(limitation, str) and limitation
        assert claim["safety_disposition"] in sup.SAFETY_DISPOSITIONS


def test_gv7_p_005_the_ten_attribution_classes_remain_distinct_and_closed():
    schema = sup.require_schema()
    assert tuple(schema.ATTRIBUTION_CLASSES) == sup.ATTRIBUTION_CLASSES
    assert len(set(sup.ATTRIBUTION_CLASSES)) == 10
    ledger = sup.require_ledger()
    payload = json.loads(json.dumps(ledger))
    payload["claims"][0]["attribution_class"] = "aura-summary-verified"
    with pytest.raises(schema.LedgerError) as excinfo:
        schema.validate_ledger(payload)
    assert excinfo.value.token == "enum-value-invalid"


def test_gv7_p_006_a_past_tense_aura_implementation_claim_is_not_evidence():
    ledger = sup.require_ledger()
    past_tense = re.compile(
        r"(?i)\b(implemented|deployed|installed|configured|validated)\b"
    )
    for claim in ledger["claims"]:
        if not past_tense.search(claim["claim_text"]):
            continue
        assert claim["attribution_class"] != "verified-implementation-evidence", (
            claim["claim_id"]
        )
        assert claim["verification_state"] == "unverified"
        assert claim["limitations"], claim["claim_id"]


def test_gv7_p_007_no_claim_is_recorded_as_verified_implementation_evidence():
    ledger = sup.require_ledger()
    for claim in ledger["claims"]:
        assert claim["attribution_class"] != "verified-implementation-evidence", (
            "nothing in this corpus has been independently reproduced"
        )


def test_gv7_p_008_duplicate_and_conflicting_material_is_cross_referenced():
    ledger = sup.require_ledger()
    types = {r["relationship_type"] for r in ledger["relationships"]}
    assert "duplicate-of-supplied-material" in types or "mirror-of-supplied-material" in types
    assert "conflicts-with" in types
    known = set(sup.identifiers(ledger["sources"], "source_id")) | set(
        sup.identifiers(ledger["claims"], "claim_id")
    )
    for relationship in ledger["relationships"]:
        assert relationship["left_ref"] in known
        assert relationship["right_ref"] in known
        assert relationship["left_ref"] != relationship["right_ref"]
        assert relationship["relationship_type"] in sup.RELATIONSHIP_TYPES
        assert relationship["basis"] in sup.RELATIONSHIP_BASES


def test_gv7_p_009_corrections_are_additive_and_never_remove_their_target():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    known = set()
    for collection, field in (
        ("batches", "batch_id"), ("sources", "source_id"), ("claims", "claim_id"),
        ("relationships", "relationship_id"), ("unresolved", "unresolved_id"),
        ("artifacts", "artifact_id"),
    ):
        known |= set(sup.identifiers(ledger[collection], field))
    for correction in ledger["corrections"]:
        assert correction["correction_kind"] in sup.CORRECTION_KINDS
        assert correction["target_ref"] in known, correction["correction_id"]
    assert tuple(schema.CORRECTION_KINDS) == sup.CORRECTION_KINDS


def test_gv7_p_010_no_record_can_be_promoted_by_schema_mutation():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    for field, value in (
        ("verification_state", "identity-verified"),
        ("verification_state", "independently-reproduced"),
        ("retrieval_state", "retrieved"),
    ):
        payload = json.loads(json.dumps(ledger))
        payload["sources"][0][field] = value
        with pytest.raises(schema.LedgerError) as excinfo:
            schema.validate_ledger(payload)
        assert excinfo.value.token in ("enum-value-invalid", "state-not-permitted")
    payload = json.loads(json.dumps(ledger))
    payload["claims"][0]["verification_state"] = "claim-source-matched"
    with pytest.raises(schema.LedgerError) as excinfo:
        schema.validate_ledger(payload)
    assert excinfo.value.token in ("enum-value-invalid", "state-not-permitted")


def test_gv7_p_011_no_v6_verification_state_can_be_inherited():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    blob = json.dumps(ledger)
    for token in ("SR-A-", "SR-B-", "SR-X-", "uap-v6", "UAP V6", "source-record-v1"):
        assert token not in blob, token
    payload = json.loads(blob)
    payload["sources"][0]["batch_ref"] = "SR-A-MSG-0001"
    with pytest.raises(schema.LedgerError) as excinfo:
        schema.validate_ledger(payload)
    assert excinfo.value.token in ("identifier-malformed", "reference-not-found")


def test_gv7_p_012_every_artifact_records_its_full_preservation_metadata():
    ledger = sup.require_ledger()
    for artifact in ledger["artifacts"]:
        assert artifact["introducing_batch"] == sup.ARTIFACT_BEARING_BATCH
        assert artifact["artifact_class"] in sup.ARTIFACT_CLASSES
        assert artifact["identity_origin"] in sup.IDENTITY_ORIGINS
        assert artifact["preservation_status"] == "preserved"
        assert artifact["executable_status"] == "non-executable"
        assert isinstance(artifact["rejection_basis"], str)
        assert artifact["rejection_basis"]
        assert artifact["safety_disposition"] in sup.SAFETY_DISPOSITIONS


def test_gv7_p_013_no_artifact_can_be_marked_executable_or_authorizing():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    for field, value in (
        ("executable_status", "executable"),
        ("preservation_status", "adopted"),
        ("artifact_class", "authorization"),
    ):
        payload = json.loads(json.dumps(ledger))
        payload["artifacts"][0][field] = value
        with pytest.raises(schema.LedgerError) as excinfo:
            schema.validate_ledger(payload)
        assert excinfo.value.token == "enum-value-invalid"


def test_gv7_p_014_quarantined_material_carries_a_quarantine_disposition():
    ledger = sup.require_ledger()
    quarantined = [
        record
        for record in ledger["claims"] + ledger["artifacts"]
        if record["safety_disposition"].startswith("quarantined-")
    ]
    assert quarantined, "the corpus contains quarantined proposals; record them"
    for record in quarantined:
        assert record["safety_disposition"] in sup.SAFETY_DISPOSITIONS


def test_gv7_p_015_the_ledger_stores_no_operational_payload_anywhere():
    ledger = sup.require_ledger()
    blob = json.dumps(ledger)
    for shape in OPERATIONAL_SHAPES:
        assert not shape.search(blob), shape.pattern


def test_gv7_p_016_every_conflict_family_has_at_least_one_unresolved_record():
    ledger = sup.require_ledger()
    covered = {record["conflict_family"] for record in ledger["unresolved"]}
    missing = sorted(set(sup.CONFLICT_FAMILIES) - covered)
    assert not missing, missing
    unknown = sorted(covered - set(sup.CONFLICT_FAMILIES))
    assert not unknown, unknown


def test_gv7_p_017_every_unresolved_record_states_positions_without_adjudicating():
    ledger = sup.require_ledger()
    known = set(sup.identifiers(ledger["sources"], "source_id")) | set(
        sup.identifiers(ledger["claims"], "claim_id")
    )
    for record in ledger["unresolved"]:
        assert record["resolution_state"] == "unresolved"
        assert 2 <= len(record["positions"]) <= 8, record["unresolved_id"]
        assert len(set(record["positions"])) == len(record["positions"])
        assert record["refs"], record["unresolved_id"]
        for ref in record["refs"]:
            assert ref in known, ref
        assert set(record) == sup.UNRESOLVED_KEYS
        for key in record:
            assert "correct" not in key
            assert "winner" not in key
            assert "resolved_position" not in key


def test_gv7_p_018_no_unresolved_vocabulary_token_can_adjudicate():
    schema = sup.require_schema()
    assert tuple(schema.UNRESOLVED_STATES) == sup.UNRESOLVED_STATES
    assert sup.UNRESOLVED_STATES == ("unresolved",)
    ledger = sup.require_ledger()
    payload = json.loads(json.dumps(ledger))
    payload["unresolved"][0]["resolution_state"] = "resolved"
    with pytest.raises(schema.LedgerError) as excinfo:
        schema.validate_ledger(payload)
    assert excinfo.value.token == "enum-value-invalid"


def test_gv7_p_019_the_ox_alpha_versus_qwen_identity_conflict_is_recorded_unresolved():
    ledger = sup.require_ledger()
    records = [
        r for r in ledger["unresolved"]
        if r["conflict_family"] == "ox-alpha-versus-qwen-core-identity"
    ]
    assert records, "the core-identity question must remain recorded and unresolved"
    for record in records:
        assert record["resolution_state"] == "unresolved"
        assert len(record["positions"]) >= 2


def test_gv7_p_020_scientific_analogy_overreach_is_recorded_not_endorsed():
    ledger = sup.require_ledger()
    records = [
        r for r in ledger["unresolved"]
        if r["conflict_family"] == "scientific-analogy-overreach"
    ]
    assert records
    for record in records:
        assert record["resolution_state"] == "unresolved"
    for claim in ledger["claims"]:
        assert claim["attribution_class"] != "verified-implementation-evidence"


def test_gv7_p_021_no_validator_can_retrieve_open_or_contact_a_locator():
    import ast

    for name in ("schema.py", "validate.py"):
        text = sup.require_file(sup.LAB_DIR / name, name)
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            label = (
                target.attr
                if isinstance(target, ast.Attribute)
                else getattr(target, "id", None)
            )
            assert label not in (
                "urlopen", "urlretrieve", "request", "get", "post",
                "connect", "create_connection", "getaddrinfo", "Popen", "run",
                "system", "__import__", "import_module", "eval", "exec",
            ), (name, label)


def test_gv7_p_022_every_source_records_at_least_one_limitation():
    ledger = sup.require_ledger()
    for source in ledger["sources"]:
        assert isinstance(source["limitations"], list)
        assert source["limitations"], source["source_id"]
        for limitation in source["limitations"]:
            assert isinstance(limitation, str) and limitation
        assert source["safety_disposition"] in sup.SAFETY_DISPOSITIONS
