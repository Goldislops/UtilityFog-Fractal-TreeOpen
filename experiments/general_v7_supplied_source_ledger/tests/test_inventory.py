"""Family I --- what the ledger inventories, once there is a ledger.

Every control here begins with a gate call and therefore fails, at the
contract-only head, with the single reason ``implementation-absent``. The
bodies are authored now so the future implementation has a fixed target and so
that no control has to be written after the fact to match whatever was built.

``G7S-M-019`` proves the gate is the first executable statement in every one.
"""

from __future__ import annotations

import re

from experiments.general_v7_supplied_source_ledger.tests import _support as sup

URL_LIKE = re.compile(r"https?://", re.IGNORECASE)


def records(ledger: dict, collection: str) -> list:
    value = ledger.get(collection)
    assert isinstance(value, list), f"{collection}: expected a list"
    return value


def every_record(ledger: dict):
    for collection in sup.COLLECTIONS:
        for record in records(ledger, collection):
            yield collection, record


def string_leaves(value, path=()):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from string_leaves(item, path + (key,))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from string_leaves(item, path + (index,))


def test_g7s_i_001_the_ledger_declares_its_own_identity():
    ledger = sup.require_ledger()
    assert ledger.get("schema_id") == sup.SCHEMA_ID
    assert ledger.get("ledger_id") == sup.LEDGER_ID
    assert ledger.get("corpus") == sup.CORPUS


def test_g7s_i_002_the_root_holds_exactly_the_declared_collections():
    ledger = sup.require_ledger()
    for collection in sup.COLLECTIONS:
        assert collection in ledger, collection
        assert isinstance(ledger[collection], list), collection


def test_g7s_i_003_every_record_id_is_well_formed_and_globally_unique():
    ledger = sup.require_ledger()
    seen = []
    for collection, record in every_record(ledger):
        segment = sup.ID_SEGMENT_BY_COLLECTION[collection]
        identifier = record.get("record_id")
        assert isinstance(identifier, str), (collection, identifier)
        assert sup.ID_RE.match(identifier), identifier
        assert identifier.split("-")[1] == segment, (identifier, segment)
        seen.append(identifier)
    assert len(seen) == len(set(seen)), "a record id is reused"


def test_g7s_i_004_the_batches_reproduce_the_structural_count():
    ledger = sup.require_ledger()
    batches = records(ledger, "batches")
    assert len(batches) == sup.EXPECTED_BATCHES
    ordinals = sorted(record["batch_ordinal"] for record in batches)
    assert ordinals == list(range(1, sup.EXPECTED_BATCHES + 1))
    for record in batches:
        ordinal = record["batch_ordinal"]
        assert isinstance(ordinal, int) and not isinstance(ordinal, bool)
        assert record["record_id"] == f"G7S-BAT-{ordinal:04d}"
        assert record["member_filename"] == f"BATCH_{ordinal:03d}.txt"


def test_g7s_i_005_every_batch_carries_packet_and_member_provenance():
    ledger = sup.require_ledger()
    for record in records(ledger, "batches"):
        assert record["packet_sha256"] == sup.PACKET_ARCHIVE_SHA256
        assert sup.DIGEST_RE.match(record["member_sha256"]), record["record_id"]


def test_g7s_i_006_origin_type_is_closed_and_reproduces_its_split():
    ledger = sup.require_ledger()
    batches = records(ledger, "batches")
    counted = {name: 0 for name in sup.ORIGIN_TYPES}
    for record in batches:
        origin = record["origin_type"]
        assert origin in sup.ORIGIN_TYPES, origin
        counted[origin] += 1
    assert counted["attachment"] == sup.EXPECTED_ATTACHMENT_ROWS
    assert counted["inline_user_message"] == sup.EXPECTED_INLINE_ROWS


def test_g7s_i_007_the_bibliography_relation_is_one_to_one():
    ledger = sup.require_ledger()
    entries = [
        record
        for record in records(ledger, "sources")
        if record.get("bibliography_entry") is True
    ]
    assert len(entries) == sup.EXPECTED_BIBLIOGRAPHY_ENTRIES
    identifiers = [record["normalized_identifier"] for record in entries]
    assert len(set(identifiers)) == sup.EXPECTED_VIDEO_IDENTIFIERS


def test_g7s_i_008_supplied_and_normalized_locators_are_separate_fields():
    ledger = sup.require_ledger()
    for record in records(ledger, "sources"):
        assert "supplied_locator" in record, record["record_id"]
        assert "normalized_locator" in record, record["record_id"]


def test_g7s_i_009_a_locatorless_source_keeps_null_and_never_empty_string():
    ledger = sup.require_ledger()
    for record in records(ledger, "sources"):
        if record["supplied_locator"] is None:
            assert record["normalized_locator"] is None, record["record_id"]
            assert record["locator_absence_reason"] is not None, record["record_id"]
        else:
            assert record["locator_absence_reason"] is None, record["record_id"]


def test_g7s_i_010_every_cross_reference_resolves_without_a_cycle():
    ledger = sup.require_ledger()
    known = {record["record_id"] for _, record in every_record(ledger)}
    for collection, record in every_record(ledger):
        for key, value in record.items():
            if not key.endswith("_ref"):
                continue
            if value is None:
                continue
            assert value in known, (record["record_id"], key, value)
            assert value != record["record_id"], (record["record_id"], key)


def test_g7s_i_011_no_id_range_is_partitioned_by_locator_presence():
    """Identity must not encode an interpretation. CONTRACT.md section 4a.

    Checked by counting runs rather than by comparing one end to the other. A
    single-ended comparison catches only one of the two contiguous layouts:
    numbering the locator-bearing sources FIRST is just as much a partition as
    numbering them last, and an earlier form of this control passed it.

    In id order the has-locator flags must not form exactly two runs. One run
    means every source is alike, which is no partition at all. Three or more
    means the two kinds interleave, so presence cannot be read off the id.
    """
    ledger = sup.require_ledger()
    ordered = sorted(records(ledger, "sources"), key=lambda r: r["record_id"])
    flags = [record["supplied_locator"] is not None for record in ordered]
    if not flags or len(set(flags)) == 1:
        return
    runs = 1 + sum(1 for a, b in zip(flags, flags[1:]) if a != b)
    assert runs != 2, (
        "sources are numbered so that locator presence is a contiguous id "
        "block; locator presence is a field, never an id range"
    )


def test_g7s_i_012_every_emitted_count_equals_its_collection_length():
    """A counts block is required, complete and closed.

    An earlier form defaulted to an empty mapping and skipped absent keys, so a
    ledger that emitted no counts at all passed trivially and extra keys went
    unchecked. CONTRACT.md section 4b requires the block and requires it to
    agree.
    """
    ledger = sup.require_ledger()
    assert "counts" in ledger, "the ledger emits no counts block"
    counts = ledger["counts"]
    assert isinstance(counts, dict), type(counts).__name__
    assert set(counts) == set(sup.COLLECTIONS), sorted(
        set(counts) ^ set(sup.COLLECTIONS)
    )
    for collection in sup.COLLECTIONS:
        value = counts[collection]
        assert isinstance(value, int) and not isinstance(value, bool), collection
        assert value == len(records(ledger, collection)), collection


def test_g7s_i_013_the_bibliography_renders_every_source_exactly_once():
    text = sup.require_bibliography()
    ledger = sup.require_ledger()
    for record in records(ledger, "sources"):
        if record.get("bibliography_entry") is not True:
            continue
        assert text.count(record["record_id"]) == 1, record["record_id"]


def test_g7s_i_014_the_intake_report_reconciles_with_the_ledger():
    text = sup.require_intake_report()
    ledger = sup.require_ledger()
    assert str(len(records(ledger, "batches"))) in text
    assert str(sup.EXPECTED_BATCHES) in text
    assert sup.LEDGER_ID in text


def test_g7s_i_015_neither_sealed_corpus_appears_in_the_ledger():
    ledger = sup.require_ledger()
    for collection, record in every_record(ledger):
        for key in record:
            lowered = key.lower()
            assert "uap" not in lowered, (record["record_id"], key)
            assert "bridge" not in lowered, (record["record_id"], key)
    for _path, value in string_leaves(ledger):
        lowered = value.lower()
        assert "uap-v6" not in lowered, value[:60]
        assert "bridge register" not in lowered, value[:60]


def test_g7s_i_016_no_locator_appears_outside_a_declared_locator_field():
    ledger = sup.require_ledger()
    for path, value in string_leaves(ledger):
        if not URL_LIKE.search(value):
            continue
        assert path and path[-1] in sup.LOCATOR_FIELDS, (path, value[:60])
