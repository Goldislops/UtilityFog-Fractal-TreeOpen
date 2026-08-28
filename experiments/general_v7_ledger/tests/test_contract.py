"""Contract-document consistency controls.

These read `CONTRACT.md` only. They are implementation-independent and must
pass in this phase: if the frozen contract stops saying what it froze, the rest
of the acceptance surface is measuring nothing.

Control ids GV7-D-NNN are declared in ``test_controls_manifest.py``.
"""

from __future__ import annotations

import re

from experiments.general_v7_ledger.tests import _support as sup


def contract_text() -> str:
    return sup.require_file(sup.CONTRACT_PATH, "CONTRACT.md")


def flat(text: str) -> str:
    """Collapse whitespace runs so a phrase check is not line-wrap sensitive.

    The contract is a wrapped Markdown document. Asserting a phrase appears
    would otherwise fail whenever the phrase happens to straddle a line break,
    which tests the formatter rather than the contract.
    """
    return re.sub(r"\s+", " ", text)


def assert_phrase(text: str, phrase: str) -> None:
    assert flat(phrase) in flat(text), phrase


def test_gv7_d_001_the_contract_declares_the_frozen_identity():
    text = contract_text()
    for token in (sup.SCHEMA_ID, sup.LEDGER_ID, sup.CORPUS, sup.INTAKE_STATE):
        assert token in text, token


def test_gv7_d_002_the_contract_declares_every_frozen_inventory_figure():
    text = contract_text()
    for figure in (
        sup.EXPECTED_BATCHES,
        sup.EXPECTED_SOURCES,
        sup.EXPECTED_ARTIFACTS,
        sup.EXPECTED_SOURCES_WITH_LOCATOR,
        sup.EXPECTED_SOURCES_WITHOUT_LOCATOR,
    ):
        assert f"**{figure}**" in text, figure
    assert (
        sup.EXPECTED_SOURCES_WITH_LOCATOR + sup.EXPECTED_SOURCES_WITHOUT_LOCATOR
        == sup.EXPECTED_SOURCES
    )


def test_gv7_d_003_the_contract_names_the_three_artifacts_and_the_two_special_batches():
    text = contract_text()
    for artifact_id in sup.ARTIFACT_IDS:
        assert artifact_id in text, artifact_id
    assert sup.ARTIFACT_BEARING_BATCH in text
    assert sup.BIBLIOGRAPHY_BATCH in text
    assert_phrase(text, "introduces no")
    assert_phrase(text, "creates no further source")


def test_gv7_d_004_the_contract_declares_the_positional_locator_split():
    text = contract_text()
    assert "GV7-SRC-0001" in text and "GV7-SRC-0035" in text
    assert "GV7-SRC-0036" in text and "GV7-SRC-0061" in text
    assert_phrase(text, "no exact supplied URL")


def test_gv7_d_005_the_contract_declares_every_closed_vocabulary():
    text = contract_text()
    groups = (
        sup.BATCH_KINDS,
        sup.ROLES,
        sup.ATTRIBUTION_CLASSES,
        sup.RETRIEVAL_STATES,
        sup.SOURCE_VERIFICATION_STATES,
        sup.CLAIM_VERIFICATION_STATES,
        sup.UNRESOLVED_STATES,
        sup.PRESERVATION_STATES,
        sup.EXECUTABLE_STATES,
        sup.IDENTITY_ORIGINS,
        sup.METADATA_PROVENANCE,
        sup.LOCATOR_ABSENCE_REASONS,
        sup.RELATIONSHIP_TYPES,
        sup.RELATIONSHIP_BASES,
        sup.CORRECTION_KINDS,
        sup.ARTIFACT_CLASSES,
        sup.SAFETY_DISPOSITIONS,
        sup.CONFLICT_FAMILIES,
    )
    for group in groups:
        for token in group:
            assert token in text, token


def test_gv7_d_006_the_contract_declares_all_thirteen_conflict_families():
    text = contract_text()
    assert len(sup.CONFLICT_FAMILIES) == 13
    assert len(set(sup.CONFLICT_FAMILIES)) == 13
    for family in sup.CONFLICT_FAMILIES:
        assert family in text, family


def test_gv7_d_007_the_contract_declares_all_ten_attribution_classes_distinctly():
    assert len(sup.ATTRIBUTION_CLASSES) == 10
    assert len(set(sup.ATTRIBUTION_CLASSES)) == 10
    text = contract_text()
    for attribution in sup.ATTRIBUTION_CLASSES:
        assert attribution in text, attribution


def test_gv7_d_008_the_contract_states_the_epistemic_limits_in_terms():
    text = contract_text()
    for statement in (
        "Zero sources have been retrieved",
        "is **not** evidence that a resource exists",
        "is not implementation evidence",
        "never proof that a proposed software mechanism works",
        "never promotes a claim",
        "human audit remains a separate and required acceptance step",
    ):
        assert_phrase(text, statement)


def test_gv7_d_009_the_contract_seals_the_v6_corpus_and_defers_bridges():
    text = contract_text()
    assert_phrase(text, "The UAP V6 corpus is absent from this ledger")
    assert_phrase(text, "Cross-corpus bridges are deferred")
    assert_phrase(text, "no bridge collection")
    assert "bridges" not in sup.ROOT_KEYS
    assert not any("bridge" in key for key in sup.ROOT_KEYS)


def test_gv7_d_010_the_contract_declares_the_fixed_byte_ceiling_and_id_grammar():
    text = contract_text()
    assert str(sup.MAX_LEDGER_BYTES) in text
    assert "MAX_LEDGER_BYTES" in text  # a bare identifier never wraps
    assert r"\AGV7-(BAT|SRC|CLM|REL|UNR|ART|COR)-[0-9]{4}\Z" in text


def test_gv7_d_011_the_contract_declares_the_quarantine_families_calmly():
    text = contract_text()
    for phrase in (
        "avoidance of access controls",
        "covert DNS, ICMP, steganographic or hidden communication",
        "credential discovery",
        "self-replication or uncontrolled mutation",
        "unsigned dynamic native-code execution",
        "destructive storage settings or unapproved cooling control",
        "never store a ready-to-run command",
        "Access controls and denials are stop conditions",
    ):
        assert_phrase(text, phrase)


def test_gv7_d_012_the_contract_refuses_to_freeze_uncounted_totals():
    text = contract_text()
    assert_phrase(
        text, "No frozen total is declared for claims, relationships, or unresolved"
    )
    assert_phrase(text, "counts are computed, never asserted from a constant")
    assert_phrase(text, "at least one** attributed, limited claim")


def test_gv7_d_013_the_contract_names_every_future_file_without_creating_it():
    text = contract_text()
    for name in (
        "schema.py",
        "validate.py",
        "ledger.json",
        "BIBLIOGRAPHY.md",
        "INTAKE_REPORT.md",
        "README.md",
    ):
        assert name in text, name
    for path in (
        sup.LEDGER_PATH,
        sup.BIBLIOGRAPHY_PATH,
        sup.INTAKE_REPORT_PATH,
        sup.README_PATH,
        sup.LAB_DIR / "schema.py",
        sup.LAB_DIR / "validate.py",
        sup.LAB_DIR / "__init__.py",
    ):
        assert not path.exists(), f"this phase must not create {path.name}"


def test_gv7_d_014_no_vocabulary_token_can_promote_a_record_by_assertion():
    groups = (
        sup.RELATIONSHIP_TYPES,
        sup.RELATIONSHIP_BASES,
        sup.ATTRIBUTION_CLASSES,
        sup.SOURCE_VERIFICATION_STATES,
        sup.CLAIM_VERIFICATION_STATES,
        sup.UNRESOLVED_STATES,
        sup.CORRECTION_KINDS,
        sup.ARTIFACT_CLASSES,
        sup.BATCH_KINDS,
    )
    for group in groups:
        for token in group:
            for fragment in sup.FORBIDDEN_PROMOTION_FRAGMENTS:
                assert fragment not in token, (token, fragment)


def test_gv7_d_015_the_declared_id_grammar_accepts_and_rejects_exactly():
    accepted = (
        "GV7-BAT-0001",
        "GV7-SRC-0061",
        "GV7-CLM-9999",
        "GV7-REL-0000",
        "GV7-UNR-0007",
        "GV7-ART-0003",
        "GV7-COR-0012",
    )
    for value in accepted:
        assert sup.ID_RE.match(value), value
    rejected = (
        "GV7-SRC-001",
        "GV7-SRC-00001",
        "gv7-src-0001",
        "GV7-XXX-0001",
        "SR-A-SRC-0001",
        " GV7-SRC-0001",
        "GV7-SRC-0001 ",
        "GV7-SRC-0001\n",
        "GV7-SRC-٠٠١٢",
        "",
    )
    for value in rejected:
        assert not sup.ID_RE.match(value), value


def test_gv7_d_016_the_contract_forbids_network_capable_validator_imports():
    text = contract_text()
    assert_phrase(text, "No validator retrieves, opens, resolves, or contacts a locator")
    for module in ("socket", "http", "urllib", "requests", "subprocess"):
        assert module in text, module
    assert len(set(sup.NETWORK_CAPABLE_MODULES)) == len(sup.NETWORK_CAPABLE_MODULES)


def test_gv7_d_017_the_contract_is_lf_only_with_a_final_newline():
    raw = sup.CONTRACT_PATH.read_bytes()
    assert b"\r\n" not in raw
    assert b"\r" not in raw
    assert b"\t" not in raw
    assert raw.endswith(b"\n")
    text = raw.decode("utf-8")
    trailing = [i + 1 for i, line in enumerate(text.split("\n")) if line != line.rstrip()]
    assert not trailing, trailing


def test_gv7_d_018_every_vocabulary_is_duplicate_free_and_lowercase_kebab():
    groups = {
        "BATCH_KINDS": sup.BATCH_KINDS,
        "ROLES": sup.ROLES,
        "ATTRIBUTION_CLASSES": sup.ATTRIBUTION_CLASSES,
        "METADATA_PROVENANCE": sup.METADATA_PROVENANCE,
        "LOCATOR_ABSENCE_REASONS": sup.LOCATOR_ABSENCE_REASONS,
        "RELATIONSHIP_TYPES": sup.RELATIONSHIP_TYPES,
        "RELATIONSHIP_BASES": sup.RELATIONSHIP_BASES,
        "CORRECTION_KINDS": sup.CORRECTION_KINDS,
        "ARTIFACT_CLASSES": sup.ARTIFACT_CLASSES,
        "SAFETY_DISPOSITIONS": sup.SAFETY_DISPOSITIONS,
        "CONFLICT_FAMILIES": sup.CONFLICT_FAMILIES,
    }
    pattern = re.compile(r"\A[a-z0-9]+(-[a-z0-9]+)*\Z")
    for name, group in groups.items():
        assert len(group) == len(set(group)), name
        for token in group:
            assert pattern.match(token), (name, token)


def test_gv7_d_019_the_eight_quarantine_dispositions_cover_the_named_families():
    quarantined = [d for d in sup.SAFETY_DISPOSITIONS if d.startswith("quarantined-")]
    assert len(quarantined) == 8
    assert "ordinary" in sup.SAFETY_DISPOSITIONS
    assert len(sup.SAFETY_DISPOSITIONS) == 9


def test_gv7_d_020_the_contract_declares_the_bibliography_rules():
    text = contract_text()
    for statement in (
        "every one of the 61 source identities exactly once",
        "every present locator exactly once",
        "fabricate no locator",
    ):
        assert_phrase(text, statement)
