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


#: Every field of a source whose value is a locator, is derived from a locator,
#: or reports the presence or absence of one. None may take part in forming an
#: identifier. CONTRACT.md section 4a.
LOCATOR_DERIVED_FIELDS = (
    "supplied_locator",
    "normalized_locator",
    "normalized_identifier",
    "locator_absence_reason",
    "bibliography_entry",
    "supplied_text",
    "locator_carrier_batch_ref",
)


def identifier_from_batch(record: dict) -> str:
    """Recompute a source identifier from its introducing batch ordinal alone."""
    ordinal = int(record["introducing_batch_ref"].split("-")[2])
    return f"G7S-SRC-{ordinal:04d}"


def test_g7s_i_011_a_source_identifier_derives_from_its_introducing_batch():
    """The derivation, which is what CONTRACT.md section 4a actually requires.

    An earlier form of this control forbade the observable *pattern*: it
    counted runs of has-locator flags in identifier order and refused exactly
    two. That rejected a correct ordinal assignment. When the supplied material
    carries its bibliography in a single late batch, the locator-bearing
    sources land in one contiguous identifier range as a consequence of batch
    ordering, and the only way to satisfy a run-count rule would have been to
    renumber records to fit a shape --- the renumbering section 4a exists to
    prevent. Contiguity is now explicitly legitimate; the derivation is what is
    checked, here and in ``G7S-I-017``.

    **What this cannot establish.** The identifier is checked against the batch
    the source *declares* as its introducer. Nothing committed witnesses that
    the declaration is truthful, so an implementation that assigned identifiers
    by locator presence and then wrote each ``introducing_batch_ref`` to match
    would pass this control by construction. CONTRACT.md section 4a records
    that residue as a human-audit obligation, and this control must never be
    described as closing it.

    The ordinal is parsed from the batch record id rather than from the batch's
    own ``batch_ordinal`` field. ``G7S-I-004`` makes those the same number: it
    pins ``record_id == G7S-BAT-{ordinal:04d}`` and
    ``member_filename == BATCH_{ordinal:03d}.txt`` together, so the parsed
    segment is transitively the member-filename ordinal that section 4a names.
    """
    ledger = sup.require_ledger()
    sources = records(ledger, "sources")
    batch_ids = {record["record_id"] for record in records(ledger, "batches")}
    seen = []
    for record in sources:
        introducing = record["introducing_batch_ref"]
        assert introducing in batch_ids, (record["record_id"], introducing)
        assert introducing.split("-")[1] == "BAT", introducing
        assert record["record_id"] == identifier_from_batch(record), (
            record["record_id"],
            introducing,
        )
        seen.append(introducing)
    # One source per introducing batch. Gaps in the ordinal sequence are legal
    # and are NOT checked here: CONTRACT.md section 4a says so in terms.
    assert len(seen) == len(set(seen)), "two sources share an introducing batch"


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


def test_g7s_i_015_no_sealed_corpus_name_appears_in_a_key_or_value():
    """Defence in depth, and NOT the separation mechanism.

    CONTRACT.md section 12 makes the key allowlist the mechanism, precisely
    because a blocklist admits every name coined tomorrow. This substring scan
    is a second layer, and its earlier name --- "neither sealed corpus appears
    in the ledger" --- promised a corpus-evidence finding that four substring
    tests cannot deliver.

    It deliberately does NOT count admitted corpus records. An earlier form of
    this control incremented a counter and then asserted the same condition
    false on the next line, so the counter was provably zero and witnessed
    nothing; worse, enumerating is the wrong shape entirely. CONTRACT.md
    section 5b says the two corpus zeros "are not counts at all" and that
    "there is nothing to enumerate". The witness for those two standings is
    therefore ``G7S-Q-013``, over the schema's declared key sets, which is
    where the contract locates the prohibition.
    """
    ledger = sup.require_ledger()
    for _collection, record in every_record(ledger):
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


def test_g7s_i_017_the_implementation_derivation_ignores_every_locator_value():
    """Blind, flip and permute --- against the IMPLEMENTATION's own derivation.

    An earlier form of this control ran the three transformations against a
    helper in this module that read only ``introducing_batch_ref``. Since that
    field is not locator-derived, no transformation could ever change the
    result: the three parts were three copies of one tautology, and the
    set-level comparison they used was strictly weaker than ``G7S-I-011``'s
    per-record check, because a set cannot see a permutation.

    The transformations are only meaningful against the derivation the
    implementation actually uses, so ``schema.source_identifier`` is part of
    the declared surface in CONTRACT.md section 11a and is what is called here,
    per record rather than per set. A derivation that consulted a locator
    returns a different identifier on the flipped input and fails.
    """
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    sources = records(ledger, "sources")
    assert sources, "no source to check"

    # The blinding set must cover every locator-derived field the declared
    # shape has. An unreconciled list would silently under-blind.
    declared = set(sup.RECORD_FIELDS["sources"])
    assert set(LOCATOR_DERIVED_FIELDS) <= declared, sorted(
        set(LOCATOR_DERIVED_FIELDS) - declared
    )
    assert declared - set(LOCATOR_DERIVED_FIELDS) == {
        "record_id",
        "introducing_batch_ref",
        "retrieval_state",
        "verification_state",
        "verification_evidence",
    }, sorted(declared - set(LOCATOR_DERIVED_FIELDS))

    for record in sources:
        expected = record["record_id"]
        assert schema.source_identifier(record) == expected, expected

        blinded = {
            key: value
            for key, value in record.items()
            if key not in LOCATOR_DERIVED_FIELDS
        }
        assert schema.source_identifier(blinded) == expected, ("blinded", expected)

        flipped = dict(record)
        flipped["supplied_locator"] = (
            None if record["supplied_locator"] is not None else "supplied-flipped"
        )
        flipped["bibliography_entry"] = not bool(record.get("bibliography_entry"))
        flipped["normalized_identifier"] = (
            None if record["normalized_identifier"] is not None else "FLIPPEDID00"
        )
        assert schema.source_identifier(flipped) == expected, ("flipped", expected)

    presences = [record["supplied_locator"] for record in sources][::-1]
    for record, presence in zip(sources, presences):
        permuted = dict(record)
        permuted["supplied_locator"] = presence
        assert schema.source_identifier(permuted) == record["record_id"], (
            "permuted",
            record["record_id"],
        )


def test_g7s_i_018_every_supplied_locator_names_the_batch_that_carried_it():
    """CONTRACT.md section 6.5, as an audit over committed data.

    Split out of ``G7S-I-017``, where it was the only part doing work while the
    control's name promised a blinding experiment. Its own id makes what it
    proves visible.

    This is an AUDIT: it reads what is recorded. The matching refusal, which is
    what section 6.5 actually requires of the validator, is ``G7S-S-034``.
    Section 14g forbids describing one as the other.
    """
    ledger = sup.require_ledger()
    sources = records(ledger, "sources")
    batch_ids = {record["record_id"] for record in records(ledger, "batches")}
    for record in sources:
        carrier = record["locator_carrier_batch_ref"]
        if record["supplied_locator"] is None:
            assert carrier is None, record["record_id"]
            continue
        assert carrier in batch_ids, (record["record_id"], carrier)
        assert carrier.split("-")[1] == "BAT", carrier
        introducing = record["introducing_batch_ref"]
        if carrier != introducing:
            # A bibliography batch supplies locators for sources introduced
            # before it, never after. CONTRACT.md section 4b.
            assert int(carrier.split("-")[2]) > int(introducing.split("-")[2]), (
                record["record_id"],
                carrier,
                introducing,
            )
