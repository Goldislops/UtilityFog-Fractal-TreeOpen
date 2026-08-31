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
        "no locator-derived value may determine or alter a source identifier",
        "None of them may take part in forming an identifier, and none may "
        "cause an identifier to change",
        "A source identifier derives from the ordinal of the batch that "
        "introduced it, and from nothing else",
        "An incidental contiguous block is legitimate and is not a defect",
        "would force renumbering to satisfy a shape",
        "The implementation exposes its own identifier derivation as "
        "schema.source_identifier",
        "once with every locator-derived field removed, once with the source's "
        "locator presence inverted, and once with locator presence reassigned "
        "to a different source",
        "Stated honestly, and this is a real limit",
        "Nothing in the committed material witnesses that the declaration is "
        "truthful",
        "would satisfy every automated control here, by construction",
        "Detecting that is a human-audit obligation",
        "no control in this laboratory may be described as closing it",
        "Locator presence is a field, never an id input",
        "A source identifier takes the batch ordinal and nothing else",
        "A retired id is never reused and never renumbered",
        "Gaps are legal and are not a defect",
    )


def test_g7s_d_011_the_contract_freezes_only_reproduced_structural_figures():
    """Section 5a now holds packet-derived facts and nothing else.

    An earlier form of this control required the heading "independently
    reproduced from the packet" and the six admission-standing rows to
    co-occur, which made the conflation an enforced property. The six
    admission rows moved to section 5b and are asserted there by
    ``G7S-D-048``, which also proves no row sits in the wrong section.
    """
    phrases(
        "Packet-derived facts --- independently reproduced from the packet",
        "These six were reproduced by the authoring seat directly from the "
        "packet bytes",
        "Every one of them is a property of the supplied material",
        "Supplied batches | 63",
        "ORIGINS.tsv data rows | 63",
        "origin_type attachment rows | 60",
        "origin_type inline_user_message rows | 3",
        "Bibliography title entries | 26",
        "Distinct supplied video identifiers | 26",
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
        "Identities with an exact locator | 26",
        "Non-admitted artifacts | 3",
        "The relation 26 + 35 = 61 reconciles these inherited figures among "
        "themselves",
        "it is not the packet-reproduced bibliography or identifier count of "
        "section 5a",
        "No control asserts 61, 35, 26 or 3 of this ledger",
        "a statement about what was inherited from the adjacent laboratory, not "
        "about this corpus",
        "Freezing them would launder an unreproduced interpretation into "
        "structure",
        "The non_admitted collection may legitimately be empty",
        "which is a reproduced packet fact and a different quantity that "
        "merely shares a value",
        "The guarantee above is about quantities, never about bare integers",
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


def test_g7s_d_016_the_contract_refuses_an_uncarried_locator():
    """Renamed with the rule it now states.

    The predecessor pinned "unrepresentable rather than merely disallowed".
    That stopped being true when `locator_carrier_batch_ref` became a nullable
    field: the state is expressible, so it must be refused rather than declared
    impossible, and section 14g forbids passing an audit off as enforcement.
    """
    phrases(
        "names the batch that carried it in locator_carrier_batch_ref",
        "an uncarried locator is representable and refused, not "
        "unrepresentable",
        "the validator refuses it with locator-without-carrier",
        "a rule enforced only by reading committed data would be an audit",
        "the carrier's ordinal must be greater than the introducing batch's",
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
        "Corrections never reduce a frozen packet-fact count, and never "
        "alter a frozen admission-standing value",
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
        "Separation is enforced primarily by a key allowlist",
        "a blocklist admits every name coined tomorrow",
        "A narrow substring scan over the two known corpus names is retained "
        "as a second layer only",
        "it is defence in depth and is not the mechanism, and no control may "
        "present it as one",
        "the exclusion vocabulary --- the corpus names, the forbidden package "
        "names, the zero-valued admission rows --- necessarily appears",
        "Those appearances are guardrails",
        "their presence must never be reported as the presence of the corpora "
        "they exclude",
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
    """Type discipline over BOTH frozen classes, never one of them.

    An earlier form iterated a single conflated dict and carried an escape
    clause exempting the interpretive ``3`` by value. Value exemptions cannot
    work here: ``3`` is also the legitimate inline-row count, and ``0`` and
    ``26`` recur across classes too. Class membership is proved by key, in
    ``G7S-M-037``; this control proves the values are well typed wherever they
    sit, and that the interpretive dict closes its own reconciliation.
    """
    phrases(sup.LEDGER_ID, sup.SCHEMA_ID, sup.CORPUS, sup.NAMESPACE)
    for name, (value, evidence_class) in sorted(sup.FROZEN_INVENTORY.items()):
        assert isinstance(value, int) and not isinstance(value, bool), name
        assert evidence_class in sup.EVIDENCE_CLASSES, (name, evidence_class)
    for view in (sup.FROZEN_PACKET_FACTS, sup.FROZEN_ADMISSION_STANDING):
        assert view, "an evidence class is empty"
        for name, value in sorted(view.items()):
            assert isinstance(value, int) and not isinstance(value, bool), name
    interpretive = sup.PRIOR_INTERPRETIVE_EXPECTATIONS
    assert (
        interpretive["identities_without_exact_locator"]
        + interpretive["identities_with_exact_locator"]
        == interpretive["provisional_source_identities"]
    )
    assert not set(interpretive) & set(sup.FROZEN_INVENTORY)


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
        "schema.source_identifier(record)",
        "a derivation that stayed private could only be checked by "
        "re-implementing it, which proves nothing",
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
        "This contract carries the content-derived packet facts in section 5a",
        "which is archive-level rather than content-derived and for which the "
        "receipt is authoritative",
        "The two documents do overlap, and saying otherwise would be false",
        "both record the four retrieval-and-verification zeros of section 5b",
        "The two corpus rows of section 5b appear in this contract alone",
        "Where they overlap, authority is assigned rather than shared",
        "Neither document witnesses the other's authoritative figures",
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


#: The twelve frozen rows as they render in the flattened contract, and the
#: section each one must appear in. Positive and exhaustive: every row is
#: required in its own section AND required absent from the other two. A
#: one-sided "no row is in the wrong table" check is satisfied by an empty
#: table, which is exactly how a taxonomy quietly disappears.
ROW_SECTIONS = {
    "5a": (
        "Supplied batches | 63",
        "ORIGINS.tsv data rows | 63",
        "origin_type attachment rows | 60",
        "origin_type inline_user_message rows | 3",
        "Bibliography title entries | 26",
        "Distinct supplied video identifiers | 26",
    ),
    "5b": (
        "Sources retrieved | 0 | PACKET_RECEIPT.md section 9",
        "Sources verified | 0 | PACKET_RECEIPT.md section 9",
        "Claims verified | 0 | PACKET_RECEIPT.md section 9",
        "Relationships verified | 0 | PACKET_RECEIPT.md section 9",
        "Admitted UAP V6 records | 0 | section 12 of this contract",
        "Admitted Bridge Register records | 0 | section 12 of this contract",
    ),
    "5c": (
        "Provisional source identities | 61",
        "Identities without an exact locator | 35",
        "Identities with an exact locator | 26",
        "Non-admitted artifacts | 3",
    ),
}


#: The header row of each frozen table, which is not a data row.
TABLE_HEADERS = frozenset(
    {
        "Quantity | Value",
        "Quantity | Value | Witness",
        "Quantity | Prior expectation",
    }
)


def contract_sections() -> dict:
    """The section-5 slices, returned RAW so row boundaries survive.

    ``CONTRACT`` is one flattened string and ``phrase()`` is a bare substring
    test, so neither carries positional information: a row moved from section
    5b back into section 5a would still satisfy every phrase control. Slicing
    between the headings is what makes placement checkable at all.

    The preamble slice --- everything between the section 5 heading and 5a ---
    is returned too. Without it, a duplicate frozen table planted above 5a
    would lie outside every slice and be invisible to a control that only ever
    looks inside them.
    """
    raw = sup.contract_text()
    markers = ("## 5. ", "### 5a.", "### 5b.", "### 5c.", "### 5d.", "## 6.")
    names = ("preamble", "5a", "5b", "5c", "5d")
    cuts = []
    for marker in markers:
        index = raw.find(marker)
        assert index != -1, f"section marker missing: {marker}"
        cuts.append(index)
    assert cuts == sorted(cuts), "section 5 headings are out of order"
    return {
        names[position]: raw[cuts[position] : cuts[position + 1]]
        for position in range(len(names))
    }


def table_rows(raw_slice: str) -> set:
    """Every data row of every markdown table in one raw slice."""
    found = set()
    for line in raw_slice.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(set(cell) <= set("-: ") for cell in cells):
            continue
        row = plain(" | ".join(cells))
        if row in TABLE_HEADERS:
            continue
        found.add(row)
    return found


def test_g7s_d_048_every_frozen_row_sits_in_its_declared_evidence_section():
    """Closed over section CONTENT, not merely exhaustive over declared rows.

    An earlier form asked only "is each declared row where it belongs, and
    absent from the other two". That left three ways through. An UNDECLARED
    row could be planted in 5a --- so the contract would read "These six" above
    a table of seven, the seventh laundering an inherited figure under the
    heading "independently reproduced from the packet". A declared row could
    be duplicated into 5d, because the leak loop iterated the three declared
    sections and never looked at the fourth. And a duplicate table could be
    planted in the section 5 preamble, which lay outside every slice.

    The suite already applies the closed standard to itself --- ``G7S-M-002``
    and ``G7S-M-003`` close the control census in both directions --- so the
    document census is closed the same way: each section's actual rows must
    EQUAL its declared rows, 5d is declared empty, and the preamble carries no
    table at all.
    """
    sections = contract_sections()
    assert set(sections) == {"preamble", "5a", "5b", "5c", "5d"}, sorted(sections)
    expected = dict(ROW_SECTIONS)
    expected["5d"] = ()
    expected["preamble"] = ()
    for name, rows in sorted(expected.items()):
        actual = table_rows(sections[name])
        declared = set(rows)
        assert actual == declared, (
            name,
            sorted(actual - declared),
            sorted(declared - actual),
        )
    declared_total = sum(len(rows) for rows in ROW_SECTIONS.values())
    assert declared_total == len(sup.FROZEN_INVENTORY) + len(
        sup.PRIOR_INTERPRETIVE_EXPECTATIONS
    ), declared_total
    phrases(
        "Three classes are distinguished and are never mixed",
        "figures reproduced from the packet",
        "facts about this admission process and this ledger's boundary, which "
        "no reading of the packet could establish",
        "prior interpretive expectations, inherited and unreproduced",
        "An interpretive figure is never asserted as a packet fact, and a fact "
        "about this process is never described as reproduced from packet bytes",
        "Admission standing --- what this process did, not what the packet "
        "contains",
        "These six are frozen too, and they are not packet-derived",
        "No reading of the packet could establish any of them",
        "Nothing in this laboratory may describe them as reproduced from "
        "packet bytes",
        "The two kinds of zero in this table are different in kind and are not "
        "interchangeable",
        "the zero records a structural impossibility, not an empty search",
        "A prohibition is stronger than a count of zero",
    )


def test_g7s_d_049_identity_constants_are_validator_enforced():
    phrases(
        "Whenever an identity field is present, the validator requires the "
        "exact frozen value above",
        "a different ledger_id, schema_id, or corpus is refused with "
        "vocabulary-token-not-permitted",
        "A partial document may omit an identity field; a complete ledger "
        "must carry all three",
    )
