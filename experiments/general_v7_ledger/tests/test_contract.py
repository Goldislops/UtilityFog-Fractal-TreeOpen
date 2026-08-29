"""Contract-document consistency controls.

These read the contract document and the committed Git blobs of the Phase-A
files, and nothing else. They are implementation-independent and must pass in
both admissible states: if the frozen contract stops saying what it froze, the
rest of the acceptance surface is measuring nothing.

**No control here asserts that an implementation file is absent.** That
assertion was withdrawn in Correction 3: it could only ever be made green by
deleting it, and Git history carries the evidence instead.

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
    assert_phrase(text, "introduces no artifact")


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


def test_gv7_d_007_the_contract_declares_all_eleven_attribution_classes_distinctly():
    assert len(sup.ATTRIBUTION_CLASSES) == 11
    assert len(set(sup.ATTRIBUTION_CLASSES)) == 11
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


def test_gv7_d_013_the_contract_names_every_implementation_file():
    """It names them. It does not require them to stay absent.

    The runtime absence assertion this control used to carry is **withdrawn**:
    it could only ever be made green by deleting it, so it would have had to be
    destroyed by the very work it guarded. Git history carries that evidence
    instead, and ``GV7-M-005``/``GV7-M-007`` admit both lawful states.
    """
    text = contract_text()
    for name in sup.IMPLEMENTATION_PATHS:
        assert name in text, name
    for name in sup.PHASE_A_PATHS:
        assert name.rsplit("/", 1)[-1] in text, name


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


def test_gv7_d_017_every_committed_phase_a_blob_is_lf_only():
    """Provenance is read from Git, never from the checkout.

    ``core.autocrlf`` rewrites LF to CRLF in the working tree on this platform,
    so a byte check over the checked-out file reports a defect that does not
    exist in the repository and fails on a fresh clone. The committed blob is
    what every consumer actually receives, so it is what is checked. No
    ``.gitattributes`` file is added to make this true.
    """
    for name in sup.PHASE_A_PATHS:
        raw = sup.committed_blob(f"experiments/general_v7_ledger/{name}")
        assert raw, name
        assert b"\r" not in raw, name
        assert b"\t" not in raw, name
        assert raw.endswith(b"\n"), name
        assert not raw.endswith(b"\n\n"), name
        text = raw.decode("utf-8")
        trailing = [
            index + 1
            for index, line in enumerate(text.split("\n"))
            if line != line.rstrip()
        ]
        assert not trailing, (name, trailing)


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


def test_gv7_d_020_the_contract_declares_the_structured_bibliography_rules():
    text = contract_text()
    for statement in (
        "Accounting is structural, and never by substring",
        "cannot tell a locator from its own prefix",
        "are **withdrawn** for the same reason",
        "every one of the 61 source identities appears exactly once",
        "each of the three labelled fields appears exactly once inside its entry",
        "parsed with `json.loads` and compared for **exact equality**",
        "two different sources may share a locator value",
        "sharing is never conflated with duplication",
        "exact recorded",
        "no URL-like material may appear anywhere in an entry outside the "
        "labelled locator values",
        "nothing is fabricated",
        "Testing only `normalized_locator` would let the original supplied string be",
        "A negative control alters the parsed field itself",
        "static `BIBLIOGRAPHY.md` **is required in the future implementation**",
        "generation* feature is **deferred**",
        # Each shipped document carries its own acceptance boundary.
        "Each shipped document carries its own acceptance boundary",
        "must **each independently** state",
        "before any substantive record or report content",
        "synthetic calibration material",
        "not merge-authorized",
        "Each of the three is separately liftable",
        "no document may rely on a sibling to disclaim on its behalf",
        "the most liftable artifact of all",
        "A statement that appears only after the records is not a boundary",
        "The rule is mechanical, so an implementer can satisfy it without guessing",
        "The declaration must appear **in prose**",
        "URL-like spans are removed from the preamble before it is looked for",
        "a check that a URL can satisfy is not a check",
        "as whole words; a negated form",
        "does not count",
        "first substantive line",
        "at any position including the very first",
        "A `# Title` line is not substantive",
        "A disclosed limit",
        "reported as a defect** rather than passed silently",
    ):
        assert_phrase(text, statement)
    for label in sup.BIBLIOGRAPHY_FIELD_LABELS:
        assert f"- {label}:" in text, label
    for name in sup.ACCEPTANCE_BOUNDARY_DOCUMENTS:
        assert name in text, name
    assert len(sup.ACCEPTANCE_BOUNDARY_DOCUMENTS) == 3


def test_gv7_d_028_the_contract_requires_reciprocal_introduction_both_ways():
    text = contract_text()
    assert_phrase(text, "introduction is reciprocal in both directions")
    assert_phrase(text, "a batch listing a record whose own introducing field")
    assert_phrase(text, "a record listed by two batches is refused")
    assert_phrase(
        text, "Checking only that a reference resolves is not reciprocity"
    )
    assert_phrase(text, "introduction-not-reciprocal")


def test_gv7_d_021_the_contract_freezes_the_actual_artifact_provenance():
    text = contract_text()
    for artifact_id, batch_id in sorted(sup.ARTIFACT_BATCHES.items()):
        assert artifact_id in text, artifact_id
        assert batch_id in text, batch_id
    assert_phrase(text, "arrived in three *different* batches")
    assert_phrase(text, "The mapping is **reciprocal**")
    assert_phrase(text, "Any statement that all three artifacts originated in batch 62")
    assert_phrase(text, "is withdrawn")
    assert len(set(sup.ARTIFACT_BATCHES.values())) == 3
    assert sup.ARTIFACT_BATCHES["GV7-ART-0003"] == sup.ARTIFACT_BEARING_BATCH
    assert sup.ARTIFACT_BATCHES["GV7-ART-0001"] != sup.ARTIFACT_BEARING_BATCH
    assert sup.ARTIFACT_BATCHES["GV7-ART-0002"] != sup.ARTIFACT_BEARING_BATCH


def test_gv7_d_022_the_contract_separates_kev_observation_from_kev_authorization():
    text = contract_text()
    assert "kev-observation" in sup.ATTRIBUTION_CLASSES
    assert "kev-authorization" in sup.ATTRIBUTION_CLASSES
    for retired in sup.RETIRED_ATTRIBUTION_CLASSES:
        assert retired not in sup.ATTRIBUTION_CLASSES, retired
    assert_phrase(text, "evidence of language, never runtime authority")
    assert_phrase(text, "It is not current runtime authority")
    assert_phrase(
        text, "Only Kev's fresh task-level instruction can grant such authority"
    )
    for forbidden in ("pull request", "merge", "network access", "repository mutation"):
        assert_phrase(text, forbidden)


def test_gv7_d_023_the_contract_freezes_the_single_supplied_path_interface():
    text = contract_text()
    assert_phrase(text, "exactly one explicitly supplied file path")
    assert_phrase(text, "the path may lie outside the repository")
    assert_phrase(text, "is **withdrawn**")
    assert_phrase(text, "existing regular file")
    assert_phrase(text, "no component of the supplied path may be a symbolic link")
    assert_phrase(text, "no directory discovery")
    assert_phrase(text, "no locator retrieval")
    # The old rule may appear once, and only as a withdrawal. Asserting its
    # bare absence would be wrong: the contract has to name what it withdrew.
    flattened = flat(text)
    old_rule = "must remain beneath an accepted repository root"
    assert flattened.count(old_rule) == 1, "the withdrawn rule must appear once"
    tail = flattened[flattened.find(old_rule):][:240]
    assert "withdrawn" in tail, "it must appear only as a withdrawal"


def test_gv7_d_024_the_contract_freezes_plural_safety_dispositions():
    text = contract_text()
    assert_phrase(text, "`safety_dispositions` is a list, and provenance survives")
    assert_phrase(text, "**`ordinary` is exclusive**")
    assert_phrase(text, "duplicate-free")
    assert "safety_dispositions" in text
    assert sup.ORDINARY_DISPOSITION == "ordinary"
    assert sup.ORDINARY_DISPOSITION in sup.SAFETY_DISPOSITIONS


def test_gv7_d_025_the_contract_keeps_relationships_visibly_unverified():
    text = contract_text()
    assert_phrase(text, "A relationship is itself unverified, and says so")
    assert_phrase(text, "is **not permitted** as a relationship attribution")
    assert_phrase(
        text, "never promotes, verifies, rehomes, or transfers confidence"
    )
    assert "verified-implementation-evidence" not in sup.RELATIONSHIP_ATTRIBUTION_CLASSES
    assert len(sup.RELATIONSHIP_ATTRIBUTION_CLASSES) == 10
    assert sup.RELATIONSHIP_VERIFICATION_STATES == ("unverified",)


def test_gv7_d_026_the_canonical_digest_survives_as_reserved_future_design():
    """Retained as specification for a later schema, binding on nothing in v1."""
    text = contract_text()
    assert_phrase(text, "SHA-256, lowercase hex, of the predecessor record's")
    assert_phrase(text, "canonical form")
    assert_phrase(text, "same collection")
    assert_phrase(text, "cross-collection supersession is refused")
    assert_phrase(text, "retained as reserved documentation")
    assert_phrase(text, "Nothing in v1 may rely on it")
    probe = {"b": 1, "a": [2, 3]}
    assert sup.canonical_bytes(probe) == b'{"a":[2,3],"b":1}'
    assert sup.DIGEST_RE.match(sup.canonical_digest(probe))


def test_gv7_d_027_the_contract_requires_precise_absence_detection():
    text = contract_text()
    assert_phrase(text, "Absence is detected precisely, by `lstat` and not by")
    assert_phrase(text, "swallows `PermissionError`")
    assert_phrase(text, "converts **only `FileNotFoundError`**")
    assert_phrase(text, "present but invalid, never")
    assert_phrase(
        text, "A broken implementation can never disguise itself as an unwritten"
    )
    assert_phrase(
        text,
        "missing, permission-denied, import-broken, malformed and "
        "present-but-invalid all remain distinguishable",
    )
    assert_phrase(text, "it is not about paths beneath it")
    assert_phrase(text, "a divergence is a harness fault, never absence")
    assert_phrase(text, "tripwire, not a detector")


# --------------------------------------------------------------------------
# Correction 3. Each of these asserts a clause the contract did not previously
# carry, and each has a behavioural counterpart elsewhere in the suite.
# --------------------------------------------------------------------------


def test_gv7_d_029_the_contract_declares_two_admissible_laboratory_states():
    """A control that must be deleted to permit the work is not evidence."""
    text = contract_text()
    for statement in (
        "exactly two admissible states",
        "Implementation surface — all seven, or none",
        "A partial implementation surface is refused",
        "An unrelated extra path is refused",
        "Git history, not a permanently red future test, is the evidence",
        "No control asserts that the implementation is absent",
        "an assertion that must be destroyed to permit the work it guards",
    ):
        assert_phrase(text, statement)
    assert sup.PRE_IMPLEMENTATION_STATE in text
    assert sup.IMPLEMENTED_STATE in text
    assert len(sup.PHASE_A_PATHS) == 8
    assert len(sup.IMPLEMENTATION_PATHS) == 7
    assert not set(sup.PHASE_A_PATHS) & set(sup.IMPLEMENTATION_PATHS)


def test_gv7_d_030_the_contract_scopes_list_max_and_declares_a_root_ceiling():
    text = contract_text()
    for statement in (
        "`LIST_MAX` bounds nested lists, never a root collection",
        "not impossible by arithmetic",
        "precisely what makes it dangerous",
        "one record away from a frozen total is not a resource ceiling",
        "Bounds are not totals",
        "a resource ceiling and not a frozen factual total",
        "Every **nested** list is duplicate-free and within `LIST_MAX`",
    ):
        assert_phrase(text, statement)
    assert "ROOT_COLLECTION_MAX" in text
    assert str(sup.ROOT_COLLECTION_MAX) in text
    # The danger is headroom, not impossibility: the frozen totals fit under 64
    # with almost nothing to spare, which is exactly why 64 must not apply here.
    assert sup.EXPECTED_BATCHES < sup.LIST_MAX
    assert sup.LIST_MAX - sup.EXPECTED_BATCHES == 1
    assert sup.EXPECTED_SOURCES < sup.ROOT_COLLECTION_MAX
    assert sup.ROOT_COLLECTION_MAX > sup.LIST_MAX
    assert set(sup.ROOT_COLLECTION_BOUNDS) == set(sup.COLLECTION_KEYS)
    for key, (low, high) in sorted(sup.ROOT_COLLECTION_BOUNDS.items()):
        assert type(low) is int and type(high) is int, key
        assert 0 <= low <= high <= sup.ROOT_COLLECTION_MAX, key
    assert sup.ROOT_COLLECTION_BOUNDS["corrections"][0] == 0
    assert sup.ROOT_COLLECTION_BOUNDS["claims"][0] == sup.EXPECTED_SOURCES
    for key in ("relationships", "unresolved"):
        assert sup.ROOT_COLLECTION_BOUNDS[key][0] == 1, key


def test_gv7_d_031_the_contract_closes_supersession_and_defers_it():
    text = contract_text()
    for statement in (
        "closed to `null` in v1",
        "A non-null supersession is refused",
        "supersedes-not-permitted",
        "deferred to a future",
        "in v1 it is dead, not merely unused",
        "successor source would have to be a 62nd record",
        "Any statement that source successors are operational in v1 is",
        "additive history channel of v1",
    ):
        assert_phrase(text, statement)


def test_gv7_d_032_the_contract_reserves_verified_implementation_evidence():
    text = contract_text()
    for statement in (
        "A v1 claim can never be verified implementation evidence",
        "would contradict its own verification state",
        "remains reserved",
        "no v1 claim and no v1 relationship may use it",
    ):
        assert_phrase(text, statement)
    assert "CLAIM_ATTRIBUTION_CLASSES" in text
    reserved = "verified-implementation-evidence"
    assert reserved in sup.ATTRIBUTION_CLASSES
    assert reserved not in sup.CLAIM_ATTRIBUTION_CLASSES
    assert reserved not in sup.RELATIONSHIP_ATTRIBUTION_CLASSES
    assert sup.RESERVED_UNUSED_ATTRIBUTION_CLASSES == (reserved,)
    assert len(sup.CLAIM_ATTRIBUTION_CLASSES) == len(sup.ATTRIBUTION_CLASSES) - 1


def test_gv7_d_033_the_contract_separates_duplicate_keys_from_parse_faults():
    text = contract_text()
    for statement in (
        "A duplicate object key carries its own exact token",
        "is not a parse `ValueError`",
        "json-duplicate-key",
        "json-malformed",
        "The general parse-`ValueError` rule therefore excludes the "
        "duplicate-key refusal",
        "Neither path echoes input and neither chains the original exception",
        "decoded as strict UTF-8, and never handed to the parser as bytes",
        "ledger-encoding-invalid",
        'decodes with `errors="surrogatepass"`',
    ):
        assert_phrase(text, statement)


def test_gv7_d_034_the_contract_freezes_refusal_order_classes_and_exit_codes():
    text = contract_text()
    for statement in (
        "the earliest applicable stage wins",
        "lexical and path-entry checks",
        "the byte ceiling, over captured bytes",
        "JSON parsing, including the duplicate-key refusal",
        "exact builtin types, and document-wide string encodability",
        "closed key sets and closed shapes",
        "identifiers, closed enum vocabularies, and scalar bounds",
        "references, reciprocity, and domain rules",
        "canonical inventory rules",
        "`schema.LedgerError` is the single refusal base",
        "is a `schema.LedgerError` that is none of them",
        "`0` on success, `1` on any refusal, `2` on a usage error",
        "None of the three is a subclass of another",
        "A refusal writes nothing to standard output",
        "exactly one line** to standard error",
        "Encodability is a stage-4 rule",
        "`ensure_ascii=True` is load-bearing",
        "string-not-encodable",
        "any claim that it does is withdrawn",
        "The stage is fixed by a document that carries two faults at once",
        "runs with the exact types, at **stage 4**",
        "only the stage decides which one the operator is told about",
        "written through `sys.stdout.buffer`, never through `print`",
        # The exact-type rule is a stage-4 rule too, and it must survive a
        # hostile metaclass. GV7-S-005 is its behavioural counterpart.
        "before any hook on **its class or its metaclass** can run",
        "A type decision is never made by reading an attribute of the class",
        "hands control to attacker code",
        "a raw exception then escapes the closed refusal vocabulary",
        "return a forged answer",
        # The three routes a bare `type.__getattribute__` does not close.
        "Invoking `type.__getattribute__` directly does not make that read "
        "safe, and any claim that it does is withdrawn",
        "bypasses a metaclass's overridden `__getattribute__` and nothing else",
        "does not bypass a `__mro__` **property** defined on the metaclass",
        "plain `__mro__` attribute** shadowing the real one",
        "needs no hook at all",
        "compares class objects with `==` and therefore invokes the "
        "metaclass's `__eq__`",
        "on a genuine `dict` subclass alike",
        # The frozen mechanism, and the three outcomes it must still produce.
        "frozen as `issubclass(type(payload), dict)`, and this is the "
        "required mechanism",
        "reads **no** attribute of the candidate class",
        "walks **no** method resolution order by hand",
        "compares **no** candidate class object through Python equality",
        "from the exact runtime type and builtin class information alone",
        "`type(payload) is dict` accepts the exact builtin mapping",
        "is a `dict` subclass and is refused `type-not-exact`",
        "every other root is refused `root-not-object`",
        "No hook supplied on the object, on its class, or on its metaclass "
        "runs at any point in that decision",
    ):
        assert_phrase(text, statement)
    # The withdrawn fallback must survive nowhere: it is what licensed the
    # incomplete repair.
    assert "primitive the metaclass cannot intercept" not in flat(text)
    # The withdrawn stage-6 placement must not survive anywhere in the text.
    assert "stage-6 rule" not in flat(text)
    assert "surrogate code point at stage 6" not in flat(text)


def test_gv7_d_035_the_contract_freezes_windows_path_safety_precisely():
    text = contract_text()
    for statement in (
        "Reparse points: redirection, not storage",
        "name-surrogate bit",
        "It is **not** refused merely for carrying",
        "cloud placeholder",
        "must already be locally hydrated",
        "residual gap is disclosed rather than skipped",
        "frozen, not delegated",
        "are **not** reserved and must not be refused",
        "scheduled for removal in Python 3.15",
        "The device namespace is refused on the anchor",
        "path-device-namespace",
        "A disclosed gap, recorded rather than quietly closed",
        "freezes the twenty-two names listed above and no more",
        "this contract does not pretend otherwise",
    ):
        assert_phrase(text, statement)
    # The disclosed gap is carried in the suite as data, not only as prose.
    assert len(sup.WINDOWS_RESERVED_NAMES_KNOWN_UNCOVERED) == 8
    for name in sup.WINDOWS_RESERVED_NAMES_KNOWN_UNCOVERED:
        assert name.upper() not in sup.WINDOWS_RESERVED_NAMES, name
    assert sup.is_device_namespace(chr(92) * 2 + "?" + chr(92) + "C:")
    assert sup.is_device_namespace(chr(92) * 2 + "." + chr(92) + "CON")
    assert not sup.is_device_namespace("C:" + chr(92) + "x")
    for statement in (
        "The mechanism is pinned by the executable decision BLOCK",
        "not by hostile fixtures and not by its expressions alone",
        "deny-list over the routes somebody thought of",
        "a deny-list is not a detector",
        # The Correction 4 claim, named as withdrawn.
        "Matching only the two decision expressions was also insufficient, "
        "and that claim is withdrawn",
        "its body a bare `pass`",
        "Two correct expressions in a block that decides nothing are not the "
        "mechanism",
        # The block, and every part of it the matcher enforces.
        "first executable statement after an optional docstring",
        "an **empty** outer `else`",
        "an outer body of **exactly those two statements**",
        "an **empty** nested `else`",
        "no additional decision statement and no alternate classifier may "
        "appear inside it",
        "no classifier may run before it",
        # The normative block itself, line by line, so the document and the
        # matcher template cannot drift apart silently.
        "if type(<parameter>) is not dict:",
        "if issubclass(type(<parameter>), dict):",
        '_refuse("type-not-exact")',
        '_refuse("root-not-object")',
        "carries **no decorator**",
        "leaving the block below it dead",
        "exactly one plain positional parameter",
        "What is pinned is the exported binding, not merely a `def` statement",
        "single module-scope** one",
        "not\nbe bound anywhere else in the package",
        "The census is **order-insensitive**",
        "that is now verified rather\nthan assumed",
        "re-committed one control over",
        "the package now carries **at most one** of it",
        "One shape is permitted, and only in a module that does not define it",
        "the defining module may not carry it",
        "the Correction 4 defeat pattern moved one scope outward",
        "**`_refuse` must itself raise**",
        "hands the decision to whatever follows the block",
        # Correction 6: the helper, and the census that decides the binding.
        "`_refuse` is pinned as an executable helper",
        "not as a name with a `raise` somewhere inside it",
        "a helper whose `raise` sat under `if False:`",
        "in the same module as the sole `validate_ledger` definition",
        "signature is exactly `_refuse(token, path=())`",
        "**exactly one executable statement**",
        "raise LedgerError(token, path) from None",
        "as is any later rebinding of the name",
        "The exported binding is decided by a census, not by a top-level scan",
        "the two most ordinary ways to rebind a name",
        "**exactly two nodes are permitted across the\nwhole package**",
        "whose\n`_core` is demonstrably this package's own module",
        "Three independent reviews defeated the first version of this census",
        "no attribute of either pinned name may be read or written at all",
        "wildcard import is refused as itself",
        "the capability is refused instead",
        "may not touch a `__dict__`",
        "The residual is a builtin rebound before use",
        "narrower than the capability itself",
        "a re-export of anything but `_core.validate_ledger`",
        "a PEP 695 `type` alias, which binds the module attribute",
        "it has already been wrong more than\nonce",
        "were each accepted until a review reproduced them",
        "**That was false and is\nwithdrawn.**",
        "a different and\nless flattering fault than not seeing them",
        "recorded here rather than quietly repaired",
        "This pins the enumerated direct static binding shapes and nothing further",
        "It is not a claim of exhaustiveness",
        "without producing any node the census can see",
        "the separate human audit remains required",
        "defence in depth",
    ):
        assert_phrase(contract_text(), statement)
    # The withdrawn wording must not return as a positive claim. The suite's
    # precedent for a withdrawal is a negative pin, not merely a replacement.
    flattened = flat(contract_text())
    assert "fails it by construction" not in flattened
    assert "whitelist of one shape" not in flattened
    assert flattened.count("Matching only the two decision expressions") == 1
    for literal in ("0xA000000C", "0xA0000003", "0x20000000"):
        assert literal in text, literal
    assert sup.REPARSE_TAG_SYMLINK == 0xA000000C
    assert sup.REPARSE_TAG_MOUNT_POINT == 0xA0000003
    assert sup.REPARSE_NAME_SURROGATE_BIT == 0x20000000
    for tag in sup.REDIRECTING_REPARSE_TAGS:
        assert tag & sup.REPARSE_NAME_SURROGATE_BIT, hex(tag)
    for name in ("CON", "PRN", "AUX", "NUL"):
        assert name in sup.WINDOWS_RESERVED_NAMES
    assert len(sup.WINDOWS_RESERVED_NAMES) == 22
    for absent_name in ("COM0", "LPT0", "LPT10", "CONSOLE", "COMPANY"):
        assert absent_name not in sup.WINDOWS_RESERVED_NAMES


def test_gv7_d_036_the_contract_separates_audit_controls_from_refusal_controls():
    text = contract_text()
    for statement in (
        "that governs input",
        "Two kinds of control, and they are not interchangeable",
        "canonical-ledger audit control",
        "hostile-input validator control",
        "An audit control is never described as a rejection control",
        "no rule whose only control is an audit is claimed to be enforced",
        "Line-ending provenance is read from Git, not from the checkout",
        "would fail on a fresh clone",
        "No `.gitattributes` file is added by this contract",
        "A path that merely overflows `MAX_PATH` is not absent",
        "Retired controls are recorded, never deleted",
        "never reused and never renumbered",
    ):
        assert_phrase(text, statement)
    assert sup.PATH_TOO_LONG_WINERROR == 206
    assert sup.RETIRED_CONTROLS, "the retired register must not be empty"


def test_gv7_d_037_the_contract_keeps_supplied_values_verbatim():
    text = contract_text()
    for statement in (
        "A supplied field is verbatim and is never trimmed or rewritten",
        "every whitespace-canonicality requirement applies to a `normalized_*` "
        "field only",
        "Dates keep both forms",
        "retained verbatim with `normalized_date` `null`",
        "The converse does not hold",
        "Creator and channel are separate provenance",
        "may honestly remain `not-supplied`",
        "inventing one would be fabrication",
        "`supplied_locator` is subject to neither, being verbatim",
    ):
        assert_phrase(text, statement)
    for field in ("supplied_channel", "normalized_date"):
        assert field in sup.SOURCE_KEYS, field
        assert field in text, field


def test_gv7_d_038_the_contract_forbids_a_correction_targeting_a_correction():
    text = contract_text()
    for statement in (
        "A correction may not target a correction",
        "a self-targeting correction, a two-record cycle",
        "correction-target-not-permitted",
        "distinct from `reference-not-found`",
    ):
        assert_phrase(text, statement)
    assert "corrections" not in sup.CORRECTION_TARGET_COLLECTIONS
    assert set(sup.CORRECTION_TARGET_COLLECTIONS) == set(sup.COLLECTION_KEYS) - {
        "corrections"
    }


def test_gv7_d_039_the_contract_demotes_the_call_name_scan_to_a_tripwire():
    """And demotes every other single layer with it.

    The contract used to call the import allowlist "the authoritative rule" and
    to assert "there is no code path that could" retrieve. Both are withdrawn:
    an allowlist over import statements never covered the ``sys.modules``
    subscript both public surfaces actually use. The replacement claims less
    and is true -- and this control refuses to let the stronger claim return.
    """
    text = contract_text()
    for statement in (
        "The assurance is layered and static, and no layer of it is "
        "authoritative on its own",
        "Permitted direct imports",
        "No dynamic-import mechanism",
        "Constrained direct `sys.modules` self-binding",
        "A deliberately limited call-name tripwire",
        "A separate human audit",
        "constrain **what a production module can statically reach by a "
        "direct, named route**",
        "They do not establish an absolute behavioural impossibility",
        # The gap is disclosed, and `compile` is not claimed as enforced.
        "A disclosed gap, recorded rather than quietly closed",
        "a scan over names cannot close rebinding in general",
        "no static layer here catches that",
        "an undisclosed gap in an assurance is worse than a disclosed one",
        "**`compile` is deliberately not named**",
        "would fire on every `re.compile(...)`",
        "constrained by review, not by a static scan",
        "The call-name tripwire is a heuristic and nothing more",
        "one level of indirection defeats it",
        "teaches its readers to ignore it",
        "No control claims that a call-name scan proves the absence of networking",
        "none claims that any other single layer does either",
        # The required behaviour survives the withdrawal, distinguished from
        # what the static controls prove.
        "No validator retrieves, opens, resolves, or contacts a locator",
        "required behaviour of the implementation",
        "not the same thing as a property these static controls prove",
    ):
        assert_phrase(text, statement)

    # The withdrawn absolutes must not return, in any position other than the
    # sentence that names them as withdrawn.
    flattened = flat(text)
    for withdrawn in (
        "The import allowlist is the authoritative rule",
        "is what actually establishes that no code path could retrieve anything",
    ):
        assert withdrawn not in flattened, withdrawn
    assert "there is no code path that could" in flattened
    assert flattened.count("there is no code path that could") == 1
    head = flattened[: flattened.find("there is no code path that could")]
    assert head.rstrip().endswith("or that"), "it may appear only as a withdrawal"

    # The frozen sys.modules form.
    for statement in (
        "pins the binding, not merely the spelling",
        "Checking that the receiver is spelled `sys` was **insufficient, and "
        "that claim is withdrawn**",
        "rebind `sys` to a decoy object carrying its own `modules` mapping",
        "one module-scope `import sys` with no alias",
        "the enumerated binding forms may not shadow or replace it",
        "`match` capture, star or mapping-rest pattern",
        "This is an enumeration, not an absolute",
        "were missing from an earlier version of it and rebound `sys` undetected",
        "one module-scope assignment** whose target is exactly `_core`",
        'exactly `sys.modules["experiments.general_v7_ledger"]`',
        "carries **no** self-binding at all",
        "nested in a function or sitting in dead code",
        "does not count toward that allowance",
        "remain refused",
        # The assurance stays modest.
        "This pins the direct static production shape and nothing further",
        "does not prove that no runtime mutation could occur",
        "establishes no absolute behavioural impossibility",
        "the separate human audit remains required",
    ):
        assert_phrase(text, statement)
    # The withdrawn spelling claim must not return either.
    assert "pins the binding, not merely the spelling" in flat(text)
    assert flat(text).count("was **insufficient, and that claim is withdrawn**") == 1
    assert sup.SYS_MODULES_SELF_BINDING_KEY == "experiments.general_v7_ledger"
    assert sup.SYS_MODULES_ALLOWED_USES == {
        "__init__.py": 0,
        "schema.py": 1,
        "validate.py": 1,
    }
    assert set(sup.SYS_MODULES_ALLOWED_USES) == set(sup.PRODUCTION_MODULES)

    for generic in ("get", "run", "post", "request"):
        assert generic not in sup.RETRIEVAL_CALL_TRIPWIRE_NAMES, generic
    for specific in ("urlopen", "create_connection", "Popen"):
        assert specific in sup.RETRIEVAL_CALL_TRIPWIRE_NAMES, specific
