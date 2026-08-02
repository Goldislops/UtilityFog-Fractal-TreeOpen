"""Schema tests: closed record structure, exact types, cross-field rules.

Structure only -- nothing here judges, scores or infers scientific truth.
"""

from __future__ import annotations

import copy

import pytest

from experiments.tech_ledger.schema import (
    CLASSIFICATIONS,
    LedgerEntryError,
    validate_entry,
)


def _valid_entry(**overrides):
    entry = {
        "schema": "tech-ledger-v1",
        "entry_id": "TLV4-042",
        "neutral_name": "Example demonstrated technology",
        "primary_classification": "A",
        "classification_qualifiers": [],
        "classification_rationale": "Recorded rationale.",
        "legitimate_uses": ["one legitimate use"],
        "unsuitable_uses": ["one unsuitable use"],
        "repository_placements": ["research-ledger"],
        "implementation_disposition": "eligible",
        "minimal_evidence_before_implementation": ["ordinary test evidence"],
        "implementation_seam": "a deterministic test seam",
        "provenance": {
            "source_kind": "user-supplied-audit",
            "source_reference": "example reference",
            "attributed_author": "example author",
            "recorded_date": "2026-08-01",
            "verification_status": "unverified",
        },
        "related_intake_ledger_entries": [],
        "warnings": ["schema validity is not scientific validity"],
        "status": "active",
    }
    entry.update(overrides)
    return entry


def _refused(entry, match=None):
    with pytest.raises(LedgerEntryError, match=match):
        validate_entry(entry)


def test_valid_entry_accepted():
    assert validate_entry(_valid_entry()) is None


def test_every_primary_classification_accepted():
    for label in CLASSIFICATIONS:
        if label == "F":
            entry = _valid_entry(
                primary_classification="F",
                implementation_disposition="prohibited",
                implementation_seam=None,
            )
        else:
            entry = _valid_entry(primary_classification=label)
        assert validate_entry(entry) is None, label


def test_qualifier_cannot_repeat_primary():
    _refused(
        _valid_entry(classification_qualifiers=["A"]),
        match="must not repeat the primary",
    )


def test_qualifier_duplicates_refused():
    _refused(
        _valid_entry(classification_qualifiers=["B", "B"]), match="duplicate"
    )


def test_qualifier_unknown_label_refused():
    _refused(_valid_entry(classification_qualifiers=["X"]))


def test_every_missing_root_field_refused():
    for field in _valid_entry():
        entry = _valid_entry()
        del entry[field]
        _refused(entry, match="key set mismatch")


def test_every_missing_provenance_field_refused():
    for field in _valid_entry()["provenance"]:
        entry = _valid_entry()
        del entry["provenance"][field]
        _refused(entry, match="key set mismatch")


def test_unknown_root_key_refused():
    _refused(_valid_entry(surprise=1), match="key set mismatch")


def test_unknown_provenance_key_refused():
    entry = _valid_entry()
    entry["provenance"]["surprise"] = 1
    _refused(entry, match="key set mismatch")


def test_root_must_be_exact_builtin_dict():
    class HostileDict(dict):
        pass

    _refused(HostileDict(_valid_entry()), match="expected builtin dict")
    _refused([], match="expected builtin dict")
    _refused(None, match="expected builtin dict")


def test_hostile_str_subclass_refused():
    class HostileStr(str):
        pass

    _refused(
        _valid_entry(neutral_name=HostileStr("sneaky")),
        match="expected builtin str",
    )


def test_hostile_key_never_hashed_into_acceptance():
    # A non-str key is described generically and forces a refusal; its
    # __eq__/__hash__ must never let it satisfy a required field name.
    class HostileKey:
        def __hash__(self):
            return hash("schema")

        def __eq__(self, other):
            return True

    entry = _valid_entry()
    del entry["schema"]
    entry[HostileKey()] = "tech-ledger-v1"
    _refused(entry, match="key set mismatch")


def test_list_fields_must_be_exact_lists():
    _refused(
        _valid_entry(classification_qualifiers=("B",)),
        match="expected builtin list",
    )
    _refused(_valid_entry(warnings="not-a-list"), match="expected builtin list")


def test_wrong_enum_values_refused():
    _refused(_valid_entry(schema="tech-ledger-v2"), match="unknown variant")
    _refused(_valid_entry(primary_classification="H"))
    _refused(_valid_entry(implementation_disposition="maybe"))
    _refused(_valid_entry(status="unknown"))
    for field, value in (
        ("source_kind", "hearsay"),
        ("verification_status", "assumed-true"),
    ):
        entry = _valid_entry()
        entry["provenance"][field] = value
        _refused(entry)


def test_entry_id_form_enforced():
    for bad in ("TLV4-1", "TLV4-0001", "TLV5-001", "tlv4-001", "TLV4-001 "):
        _refused(_valid_entry(entry_id=bad), match="TLV4-NNN")


def test_wire_formats_ascii_digits_only():
    # Python's \d and int() both accept Unicode decimal digits; the wire
    # formats must not. Valid ASCII forms stay valid.
    assert validate_entry(_valid_entry(entry_id="TLV4-042")) is None
    arabic_indic = "TLV4-٠١٦"  # TLV4-016 in Arabic-Indic digits
    _refused(_valid_entry(entry_id=arabic_indic), match="TLV4-NNN")
    devanagari = "TLV4-०१६"
    _refused(_valid_entry(entry_id=devanagari), match="TLV4-NNN")
    entry = _valid_entry()
    entry["provenance"]["recorded_date"] = (
        "২০২৬-০৮-০১"  # Bengali 2026-08-01
    )
    _refused(entry, match="ISO YYYY-MM-DD")
    entry = _valid_entry()
    entry["provenance"]["recorded_date"] = (
        "2026-٠٨-01"  # mixed ASCII/Arabic-Indic
    )
    _refused(entry, match="ISO YYYY-MM-DD")
    entry = _valid_entry()
    entry["provenance"]["recorded_date"] = "2026-08-01"
    assert validate_entry(entry) is None


def test_malformed_and_impossible_dates_refused():
    for bad in ("2026-8-01", "01-08-2026", "2026/08/01", "not-a-date"):
        entry = _valid_entry()
        entry["provenance"]["recorded_date"] = bad
        _refused(entry, match="ISO YYYY-MM-DD")
    for impossible in ("2026-02-30", "2026-13-01", "2025-02-29", "0000-01-01"):
        entry = _valid_entry()
        entry["provenance"]["recorded_date"] = impossible
        _refused(entry, match="real calendar date")


def test_empty_strings_and_empty_lists_refused():
    _refused(_valid_entry(neutral_name=""), match="non-empty")
    _refused(_valid_entry(classification_rationale=""), match="non-empty")
    _refused(_valid_entry(legitimate_uses=[]), match="non-empty list")
    _refused(_valid_entry(unsuitable_uses=[""]), match="non-empty")
    _refused(_valid_entry(repository_placements=[]), match="non-empty list")
    _refused(
        _valid_entry(minimal_evidence_before_implementation=[]),
        match="non-empty list",
    )
    _refused(_valid_entry(warnings=[]), match="non-empty list")
    _refused(_valid_entry(implementation_seam=""), match="non-empty")
    entry = _valid_entry()
    entry["provenance"]["source_reference"] = ""
    _refused(entry, match="non-empty")


def test_placement_duplicates_and_unknown_refused():
    _refused(
        _valid_entry(repository_placements=["experiment", "experiment"]),
        match="duplicate",
    )
    _refused(_valid_entry(repository_placements=["everywhere"]))


def test_related_entries_exact_positive_ints():
    _refused(
        _valid_entry(related_intake_ledger_entries=[3, 3]), match="duplicate"
    )
    _refused(
        _valid_entry(related_intake_ledger_entries=[0]), match="positive"
    )
    _refused(
        _valid_entry(related_intake_ledger_entries=[-2]), match="positive"
    )
    _refused(
        _valid_entry(related_intake_ledger_entries=[True]),
        match="expected builtin int",
    )
    _refused(
        _valid_entry(related_intake_ledger_entries=[3.0]),
        match="expected builtin int",
    )
    assert validate_entry(_valid_entry(related_intake_ledger_entries=[3, 14])) is None


def test_disposition_seam_rules():
    _refused(
        _valid_entry(
            implementation_disposition="prohibited",
            implementation_seam="still here",
        ),
        match="null implementation_seam",
    )
    _refused(
        _valid_entry(
            implementation_disposition="deferred",
            implementation_seam="still here",
        ),
        match="null implementation_seam",
    )
    _refused(
        _valid_entry(
            implementation_disposition="eligible", implementation_seam=None
        ),
        match="non-empty implementation_seam",
    )
    _refused(
        _valid_entry(
            implementation_disposition="evidence-gated",
            implementation_seam=None,
        ),
        match="non-empty implementation_seam",
    )
    assert (
        validate_entry(
            _valid_entry(
                implementation_disposition="prohibited",
                implementation_seam=None,
            )
        )
        is None
    )


def test_primary_f_rules():
    _refused(
        _valid_entry(primary_classification="F"),
        match="requires implementation_disposition 'prohibited'",
    )
    _refused(
        _valid_entry(
            primary_classification="F",
            implementation_disposition="prohibited",
            implementation_seam="sneaky seam",
        ),
        match="null implementation_seam",
    )
    assert (
        validate_entry(
            _valid_entry(
                primary_classification="F",
                implementation_disposition="prohibited",
                implementation_seam=None,
            )
        )
        is None
    )


def test_v5_deferred_rules():
    _refused(
        _valid_entry(status="v5-deferred"),
        match="requires implementation_disposition 'deferred'",
    )
    assert (
        validate_entry(
            _valid_entry(
                status="v5-deferred",
                implementation_disposition="deferred",
                implementation_seam=None,
            )
        )
        is None
    )


def test_validation_never_mutates_or_infers():
    # Rule 6/7: pure validation -- the entry (including an unverified G
    # claim) is byte-for-byte untouched, nothing is inferred or upgraded.
    entry = _valid_entry(
        primary_classification="G",
        classification_qualifiers=["A"],
    )
    snapshot = copy.deepcopy(entry)
    assert validate_entry(entry) is None
    assert entry == snapshot
    assert entry["provenance"]["verification_status"] == "unverified"
