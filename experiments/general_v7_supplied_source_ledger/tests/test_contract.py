"""Family D --- the contract says what it must say, and says it in force.

Every control here passes with no implementation present. Nothing in this
module references an implementation path or calls a gate helper, and
``G7S-M-020`` proves that independence statically rather than trusting it.

Phrase controls run against a whitespace-flattened, emphasis-stripped
rendering of ``CONTRACT.md``, so reflowing a paragraph or changing bold to
italic cannot silently retire a control.
"""

from __future__ import annotations

import re

from experiments.general_v7_supplied_source_ledger.tests import _support as sup


def plain(text: str) -> str:
    """Flatten whitespace and drop markdown emphasis and code ticks."""
    return sup.flat(text.replace("*", "").replace("`", ""))


CONTRACT = plain(sup.contract_text())


def phrase(snippet: str) -> None:
    assert snippet in CONTRACT, f"contract phrase missing: {snippet!r}"


def phrases(*snippets: str) -> None:
    for snippet in snippets:
        phrase(snippet)


def test_g7s_d_001_the_contract_declares_the_frozen_laboratory_identity():
    phrases(
        "Ledger id | general-v7-supplied-source-ledger-v1",
        "Schema id | supplied-source-v1",
        "Corpus | GENERAL V7 SUPPLIED SOURCE CORPUS",
        "Record id namespace | G7S-",
        "Laboratory | experiments/general_v7_supplied_source_ledger",
    )


def test_g7s_d_002_the_namespace_is_distinct_from_the_adjacent_ledger():
    phrases(
        "The namespace prefix is G7S- and is deliberately not GV7-",
        "owns the GV7- namespace",
        "A distinct prefix makes it a grammar violation",
    )


def test_g7s_d_003_the_contract_names_every_phase_a_path():
    for name in sup.PHASE_A_PATHS:
        phrase(name)
    phrase("These eleven paths are authored in this phase")


def test_g7s_d_004_the_contract_names_the_seven_future_paths_all_or_none():
    for name in sup.IMPLEMENTATION_PATHS:
        phrase(name)
    phrases(
        "The future implementation surface is exactly these seven paths",
        "all seven, or none",
    )


def test_g7s_d_005_the_contract_declares_exactly_two_admissible_states():
    phrases(
        "exactly two admissible states",
        "pre-implementation",
        "implemented",
        "A partial surface is not an admissible state",
    )


def test_g7s_d_006_the_contract_refuses_to_assert_the_surface_stays_absent():
    phrases(
        "No control asserts that the implementation surface is absent",
        "a control that can only be made green by deleting it is an obstacle",
        "the evidence that the tests preceded the implementation lives in Git "
        "history",
    )
    for name in sup.NEVER_AUTHORIZED_PATHS:
        phrase(name)


def test_g7s_d_007_the_contract_declares_the_dependency_boundary():
    phrases(
        "only the Python standard library",
        "It must not import another ledger package",
        "each refused by exact name",
        "Prefix matching is not used",
    )
    for package in sorted(sup.FORBIDDEN_LEDGER_PACKAGES):
        phrase(package)


def test_g7s_d_008_the_contract_declares_seven_record_concepts():
    for collection, segment in sorted(sup.ID_SEGMENT_BY_COLLECTION.items()):
        phrase(collection)
        phrase(segment)
    phrases(
        "Seven distinct record concepts",
        "Ids are globally unique across every collection",
        "supplied batch",
        "provisional source",
        "attributed claim",
        "attributed relationship",
        "unresolved issue",
        "additive correction",
        "non-admitted artifact",
    )


def test_g7s_d_009_the_contract_declares_the_frozen_id_grammar():
    phrases(
        sup.ID_PATTERN,
        "[0-9] is load-bearing",
        "Arabic-Indic and Devanagari digits",
    )


def test_g7s_d_010_the_contract_forbids_interpretive_inputs_to_identity():
    phrases(
        "An identity is stable only if nothing that may later be corrected "
        "takes part in forming it",
        "Forbidden id inputs",
        "the ledger must not partition an id range by an interpretive "
        "property",
        "Locator presence is a field, never an id range",
        "A retired id is never reused and never renumbered",
        "Gaps are legal and are not a defect",
    )


def test_g7s_d_011_the_contract_freezes_only_reproduced_structural_figures():
    phrases(
        "Structural --- independently reproduced from the packet",
        "Supplied batches | 63",
        "ORIGINS.tsv data rows | 63",
        "origin_type attachment rows | 60",
        "origin_type inline_user_message rows | 3",
        "Bibliography title entries | 26",
        "Distinct supplied video identifiers | 26",
        "Sources retrieved | 0",
        "Sources verified | 0",
        "Claims verified | 0",
        "Relationships verified | 0",
        "UAP V6 records | 0",
        "Bridge Register records | 0",
        "each of the 26 bibliography entries yields exactly one distinct "
        "supplied video identifier",
    )


def test_g7s_d_012_the_contract_records_interpretive_figures_without_freezing():
    phrases(
        "Prior interpretive expectations --- recorded, not frozen",
        "were not reproduced from packet structure by this phase",
        "general-v7-technology-ledger-v1",
        "Provisional source identities | 61",
        "Identities without an exact locator | 35",
        "Non-admitted artifacts | 3",
        "The relation 26 + 35 = 61 is an internal arithmetic reconciliation",
        "No control asserts 61, 35 or 3 as a structural fact",
        "Freezing them would launder an unreproduced interpretation into "
        "structure",
        "The non_admitted collection may legitimately be empty",
    )


def test_g7s_d_013_the_contract_refuses_to_freeze_a_surface_form_count():
    phrases(
        "is not frozen at any value",
        "an artifact of how a tokenizer cuts the supplied text",
        "104 raw URL tokens",
        "100 identifier occurrences",
        "66 per-line-distinct token strings",
        "33 corpus-distinct token strings",
        "A figure that changes with the tokenizer is not a structural fact",
        "their number is computed, never asserted from a constant",
        "No claim count is invented",
        "the packet itself is not committed to this repository",
    )


def test_g7s_d_014_the_contract_preserves_supplied_values_and_separates_normalized():
    phrases(
        "A supplied value is stored byte-for-byte as supplied",
        "It is never trimmed, stripped, case-folded, Unicode-normalized, "
        "unescaped or re-rendered",
        "supplied_locator and normalized_locator are distinct fields and "
        "remain distinct even when their values are identical",
    )


def test_g7s_d_015_the_contract_forbids_inferred_locator_completion():
    phrases(
        "Normalization never supplies a character that was not supplied",
        "No scheme insertion, no host completion, no identifier "
        "reconstruction from a partial",
        "Where normalization would have to guess, normalized_locator is null",
    )


def test_g7s_d_016_the_contract_makes_an_uncarried_locator_unrepresentable():
    phrases(
        "A locator record carries the batch that carried it",
        "unrepresentable rather than merely disallowed",
    )


def test_g7s_d_017_the_contract_forbids_retrieval_without_overclaiming():
    phrases(
        "No validator retrieves, opens, resolves, dereferences or contacts a "
        "locator",
        "The static import allowlist is one layer of a layered assurance",
        "it walks import statements only and does not establish behavioural "
        "impossibility",
        "human audit remains required",
    )


def test_g7s_d_018_the_contract_keeps_three_absence_representations_distinct():
    phrases(
        "Three absence representations are distinct and are never "
        "interchangeable",
        "the field is inapplicable to this record",
        "the field applies and nothing was supplied",
        "something was supplied, and it was empty",
        "Null is retained for missing metadata",
        "never replaced by an empty string, never replaced by a placeholder, "
        "and never dropped",
        "no code path may coerce between them",
    )


def test_g7s_d_019_the_contract_requires_counts_to_be_computed():
    phrases(
        "Zero is a recorded value, not an absent one",
        "counts are computed, never asserted from a constant",
    )


def test_g7s_d_020_the_contract_forbids_deletion_and_deduplication():
    phrases(
        "The ledger has no deletion path, no tombstone and no deduplication "
        "interface",
    )
    for parameter in sup.FORBIDDEN_COLLAPSE_PARAMETERS:
        phrase(parameter)


def test_g7s_d_021_the_contract_cross_references_duplicates_without_collapsing():
    phrases(
        "Material that repeats is recorded twice and joined by a relationship",
        "Nothing is removed to make a count tidy",
        "They are never collapsed to a single stored locator",
        "The schema must not assume a one-to-one relation between "
        "bibliography entries and identifiers",
        "assuming it makes the first genuine collision an unrepresentable "
        "state",
    )


def test_g7s_d_022_the_contract_closes_the_attribution_vocabulary():
    phrase("The attribution vocabulary is closed to exactly")
    for token in sup.ATTRIBUTION_CLASSES:
        phrase(token)
    phrases(
        "are different authorship standings and are separately countable",
        "A claim carries exactly one attribution class",
        "Absent by decision, and never to be added",
        "Recording that material was received is not endorsement of it",
    )


def test_g7s_d_023_the_contract_closes_the_relationship_vocabulary():
    phrase("The relationship vocabulary is closed to exactly")
    for token in sup.RELATIONSHIP_TYPES:
        phrase(token)
    phrases(
        "A relationship is observational",
        "It never promotes, verifies, rehomes or transfers confidence between "
        "its endpoints",
        "it does not claim they are the same thing in the world",
        "Endpoints must be distinct",
    )


def test_g7s_d_024_the_contract_fixes_every_v1_verification_state():
    for token in (
        sup.RETRIEVAL_STATES
        + sup.SOURCE_VERIFICATION_STATES
        + sup.CLAIM_VERIFICATION_STATES
        + sup.UNRESOLVED_STATES
    ):
        phrase(token)
    phrases(
        "Each vocabulary is closed to a single token in v1",
        "Promotion has no representation",
        "there is no second token to promote to",
        "no separate boolean exists that could drift out of step with the "
        "ladder",
        "A value outside its vocabulary is refused",
    )


def test_g7s_d_025_the_contract_documents_a_future_ladder_it_cannot_use():
    for level in sup.FUTURE_VERIFICATION_LADDER:
        phrase(level)
    phrases(
        "In v1 only the first level is admissible",
        "The forward set is documentation and nothing in v1 may rely on it",
    )


def test_g7s_d_026_the_contract_makes_corrections_additive_only():
    phrases(
        "It never edits, deletes or rewrites its target",
        "the target remains present and independently valid",
        "Historical rewriting is prohibited",
        "A correction may not target another correction",
        "distinct from an unresolved-reference refusal",
        "the target exists and is refused for being the wrong kind",
        "Corrections never reduce a frozen structural count",
        "retired, never deleted and never renumbered",
    )


def test_g7s_d_027_the_contract_requires_reciprocal_supersession():
    phrases(
        "Supersession is expressed as an ordered pair of correction records, "
        "not as a field on the superseded record",
        "would require editing the predecessor in order to record that it had "
        "been superseded",
        "Each names the other, neither names itself",
        "a third correction naming either is refused",
        "Supersession is reciprocal in both directions",
        "a one-sided supersession is refused",
        "A supersession may not promote a verification state",
    )


def test_g7s_d_028_the_contract_declares_deterministic_canonical_output():
    phrases(
        "Canonical bytes are produced with sorted keys, ASCII escaping, and "
        "the compact separators comma and colon with no spaces",
        "encoded UTF-8 with no trailing newline",
        "Canonical form is independent of input key order",
        "it carries no timestamp, no path and no environment value",
    )


def test_g7s_d_029_the_contract_declares_schema_closure():
    phrases(
        "Every record type declares its complete key set",
        "An undeclared key is refused, at the root and in every nested block",
        "A key differing only in case is refused, never folded",
    )


def test_g7s_d_030_the_contract_declares_every_numeric_refusal():
    phrases(
        "Duplicate JSON keys are refused with their own reason, never "
        "resolved last-wins",
        "That refusal is distinct from a malformed-document refusal",
        "Floats are refused everywhere, including integral floats",
        "The literals NaN, Infinity and -Infinity are refused at parse time "
        "and never coerced",
        "An overflow literal such as 1e400 is refused and is never read as "
        "infinity",
        "A bool is not an int",
        "True and False are refused wherever an integer is required",
        "Integer bounds are closed intervals and are stated numerically",
        "Both edges are accepted and both edges plus one are refused",
    )


def test_g7s_d_031_the_contract_declares_encoding_and_path_identity():
    phrases(
        "Every file is UTF-8",
        "Every open in text mode passes an explicit encoding argument",
        "A byte-order mark is refused",
        "Committed blobs are LF-only",
        "A stored path is relative and POSIX-separated",
        "Absolute paths, drive-relative paths, UNC paths, device-namespace "
        "paths, backslash separators",
        "Windows reserved component names, and components with a trailing "
        "dot or trailing space are each refused",
        "A parent component is refused after normalization, not before",
        "Symlinks, junctions and reparse points are refused",
        "A dangling reparse point is present-but-invalid, never absent",
        "The artifact that was inspected must be the artifact that is read",
    )


def test_g7s_d_032_the_contract_declares_reference_integrity_and_fail_closed():
    phrases(
        "Every cross-reference resolves to a present record",
        "There is no self-reference and no reference cycle",
        "A refusal never mutates, infers, repairs or upgrades its input",
        "never echoes the rejected value",
    )


def test_g7s_d_033_the_contract_separates_the_corpora():
    phrases(
        "The UAP V6 corpus is absent from this ledger",
        "The Bridge Register is absent from this ledger",
        "the schema exposes no record type into which either could be placed",
        "Separation is enforced by a key allowlist, not by a name blocklist",
        "a blocklist admits every name coined tomorrow",
        "no transfer of truth from synthetic calibration data",
        "It is never evidence about a source, a claim or a relationship",
    )


def test_g7s_d_034_the_contract_removes_the_non_admission_content_channel():
    phrases(
        "It is recorded by batch identity, presence and cryptographic "
        "provenance only",
        "The record shape contains no content channel",
        "There is no summary field, no statement field, no quoted-text field, "
        "no rejection-basis field and no locator field",
        "cannot be paraphrased into the ledger, because the schema has no "
        "field to paraphrase into",
        "Removing the channel is preferred to policing it",
        "Packet proposal material is structurally non-executable and "
        "non-normative",
        "No packet text is executed, imported, evaluated, compiled or "
        "followed as an instruction",
    )
    for token in sup.NON_ADMITTED_STATUSES:
        phrase(token)


def test_g7s_d_035_the_contract_refuses_to_equate_delivery_with_admission():
    phrases(
        "carries no admission, authorship or trust meaning; it is a delivery "
        "channel",
        "The three inline_user_message rows are not established to be the "
        "three non-admitted artifacts",
        "no field, vocabulary token, ordering or derived count may equate "
        "them",
        "the bibliography batch is itself an inline_user_message",
        "carries no origin_type field at all",
    )


def test_g7s_d_036_the_contract_declares_the_control_families():
    for letter, module in (
        ("D", "test_contract.py"),
        ("M", "test_controls_manifest.py"),
        ("R", "test_packet_manifest.py"),
        ("I", "test_inventory.py"),
        ("S", "test_schema.py"),
        ("P", "test_provenance.py"),
        ("Q", "test_quarantine.py"),
    ):
        phrase(f"| {letter} | tests/{module} |")


def test_g7s_d_037_the_contract_declares_the_census_requirements():
    phrases(
        "every declared control exists exactly once in its declared module",
        "no undeclared control exists",
        "the module set is closed in both directions",
        "family totals reconcile against a census derived from the source "
        "rather than from the declaration",
        "optimized modes collect an identical control set",
        "no control is silently retired",
        "A retired id is recorded with a reason, is never reused and never "
        "renumbered",
        "The manifest is never padded to reproduce an earlier total",
    )


def test_g7s_d_038_the_contract_partitions_the_suite_into_two_groups():
    for module in sup.CONTRACT_ONLY_MODULES:
        phrase(module)
    for module in sup.IMPLEMENTATION_DEPENDENT_MODULES:
        phrase(module)
    phrases(
        "Every control in these three modules passes with no implementation "
        "present",
        "No control in this group references an implementation path or calls "
        "a gate helper",
        "that independence is checked statically rather than assumed",
        "Every control in these four modules begins with a gate call",
        "At the contract-only head, no other complete-suite failure reason is "
        "acceptable",
    )


def test_g7s_d_039_the_contract_forbids_skip_and_xfail_for_absence():
    phrases(
        "Missing implementation is an ordinary assertion failure",
        "never skipped, never xfail",
        "no marker or outcome-manipulating call appears anywhere in the suite",
        "is produced by a single factory and is always raised, never returned",
        "a link-preserving stat rather than an existence test",
        "an existence test swallows a permission failure into a bare false",
        "A broken implementation must never be able to disguise itself as an "
        "unwritten one",
    )
    phrase(sup.IMPLEMENTATION_ABSENT)


def test_g7s_d_040_the_contract_explains_optimization_mode_identity():
    phrases(
        "The suite behaves identically under ordinary Python, -O and -OO",
        "-O deletes assert statements at compile time",
        "Pytest assertion rewriting replaces every assert node in a collected "
        "test module before compilation",
        "no bare assert may appear outside a test module",
        "helper failures are raised explicitly",
        "the debug builtin appears nowhere, and no assert appears at module "
        "level",
        "since Python 3.13 the AST parser inherits the interpreter "
        "optimization level",
        "Every AST parse in the suite pins the optimization level to zero",
        "pytest emits one configuration warning",
        "That warning is expected and is a property of the mode rather than of "
        "this suite",
    )


def test_g7s_d_041_the_contract_declares_the_remaining_acceptance_rules():
    phrases(
        "provenance is read from the Git blob, never from the checkout",
        "The blob is resolved from the index first",
        "never reports as an absent implementation",
        "An audit control reads committed data and asserts a property of what "
        "is recorded",
        "A refusal control feeds a malformed payload",
        "No rule whose only control is an audit may be described as "
        "validator-enforced",
        "No repository workflow is added while the complete suite is "
        "deliberately failing-first",
        "Human audit is a separate and required acceptance step, distinct "
        "from the automated tests",
        "A green acceptance suite establishes conformance to the structure "
        "this contract describes and nothing semantic",
        "No text field in this ledger is executable authority",
    )


def test_g7s_d_042_the_declared_id_grammar_accepts_and_rejects_exactly():
    for good in (
        "G7S-BAT-0001",
        "G7S-SRC-0063",
        "G7S-CLM-9999",
        "G7S-REL-0000",
        "G7S-UNR-0007",
        "G7S-COR-0012",
        "G7S-NAD-0003",
    ):
        assert sup.ID_RE.match(good), good
    for bad in (
        "GV7-BAT-0001",
        "G7S-BAT-001",
        "G7S-BAT-00001",
        "G7S-XXX-0001",
        "G7S-BAT-0001 ",
        " G7S-BAT-0001",
        "G7S-BAT-0001\n",
        "g7s-bat-0001",
        "G7S-BAT-٠١٢٣",
    ):
        assert not sup.ID_RE.match(bad), bad


def test_g7s_d_043_the_support_constants_agree_with_the_contract_text():
    phrases(sup.LEDGER_ID, sup.SCHEMA_ID, sup.CORPUS, sup.NAMESPACE)
    for value in sup.FROZEN_STRUCTURAL_INVENTORY.values():
        assert isinstance(value, int) and not isinstance(value, bool)
    assert (
        sup.PRIOR_INTERPRETIVE_EXPECTATIONS["identities_without_exact_locator"]
        + sup.EXPECTED_VIDEO_IDENTIFIERS
        == sup.PRIOR_INTERPRETIVE_EXPECTATIONS["provisional_source_identities"]
    )
    for value in sup.PRIOR_INTERPRETIVE_EXPECTATIONS.values():
        assert value not in sup.FROZEN_STRUCTURAL_INVENTORY.values() or value in (
            sup.EXPECTED_INLINE_ROWS,
        )


def test_g7s_d_044_the_contract_blob_is_clean_and_lf_only():
    for name in ("CONTRACT.md", "PACKET_RECEIPT.md"):
        raw = sup.committed_blob(f"{sup.LAB_POSIX}/{name}")
        assert not sup.blob_defects(raw), (name, sup.blob_defects(raw))


def test_g7s_d_045_no_declared_rule_is_put_out_of_force_by_a_negation():
    withdrawn = re.findall(
        r"[^.]*\b(?:is withdrawn|no longer applies|does not apply|is "
        r"superseded|is suspended|is waived)\b[^.]*\.",
        CONTRACT,
    )
    assert not withdrawn, withdrawn


def test_g7s_d_046_the_contract_declares_the_minimal_validator_surface():
    phrases(
        "The future implementation exposes exactly this surface",
        "so the acceptance surface has a fixed target rather than a guess",
        "validate.RefusalError",
        "validate.validate_document(text)",
        "validate.validate_ledger_file(path)",
        "schema.REFUSAL_TOKENS",
        "schema.KEYS_BY_COLLECTION",
        "schema.canonical_bytes(value)",
        "The refusal vocabulary is closed to exactly",
        "A refusal carries exactly one token",
        "the exception carries no rejected-value slot",
        "a refusal that renders what it refused is a channel for the refused "
        "material",
    )
    for token in sup.REFUSAL_TOKENS:
        phrase(token)
    assert len(sup.REFUSAL_TOKENS) == len(set(sup.REFUSAL_TOKENS))
    assert list(sup.REFUSAL_TOKENS) == sorted(sup.REFUSAL_TOKENS)
    for token in sup.REFUSAL_TOKENS:
        assert token == token.lower()
        assert " " not in token and "_" not in token


def test_g7s_d_047_the_contract_declares_every_record_field_it_requires():
    """The record shape is a fixed target, not a guess.

    CONTRACT.md section 11a promised the implementer a fixed target. That held
    for the six module-level names and quietly failed for the record fields,
    which were discoverable only by reading test source. Section 4b now
    declares them and this control keeps the two in step.
    """
    for collection, fields in sorted(sup.RECORD_FIELDS.items()):
        for field in fields:
            phrase(field)
    for field in sorted(sup.LOCATOR_FIELDS):
        phrase(field)
    phrases(
        "Declared record shapes",
        "The implementer gets a fixed target rather than a guess",
        "the acceptance surface uses exactly these and no others",
        "A field name ending _ref holds exactly one record id",
        "counts is a mapping from collection name to that collection's length",
        "a counts block that disagrees with any collection length is refused",
        "a locator may appear in no field other than these four",
    )
    phrases(
        "The correction_kind vocabulary is closed to exactly correction, "
        "contest, withdrawal and supersession",
    )
    for kind in sup.CORRECTION_KINDS:
        phrase(kind)
    phrases(
        "BIBLIOGRAPHY.md, INTAKE_REPORT.md and README.md are liftable",
        "each must carry its own boundary statement",
        "not merge-authorized",
        "No liftable document reproduces packet prose",
    )
    for name in sup.LIFTABLE_DOCUMENTS:
        phrase(name)
    phrases(
        "The validator must also accept",
        "would satisfy every refusal control and be useless",
        "is accepted and returned unchanged",
        "neither substitutes for the other",
    )
    phrases(
        "PACKET_RECEIPT.md is the sole committed witness for archive-level",
        "This contract carries the content-derived structural figures in "
        "section 5a",
        "Neither document witnesses the other's figures, and neither claims to",
        "This prohibition binds controlled-vocabulary and status fields only",
        "It does not reach supplied text",
        "The committed ledger.json is exactly those canonical bytes followed "
        "by a single newline",
        "Every open in text mode passes an explicit encoding argument",
        "A binary-mode open passes an explicit binary mode and no encoding",
        "components with a trailing dot or trailing space are each refused",
        "The claim that it is the only warning is environment-conditional",
        "no control asserts a warning count",
    )
