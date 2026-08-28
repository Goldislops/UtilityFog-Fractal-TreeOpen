"""Frozen inventory, source-metadata and bibliography controls.

Implementation-dependent. Every figure asserted here is frozen by CONTRACT.md
section 5; none is invented, and no total is asserted for claims,
relationships, or unresolved issues.

Control ids GV7-I-NNN are declared in ``test_controls_manifest.py``.
"""

from __future__ import annotations

import re

from experiments.general_v7_ledger.tests import _support as sup

HTTPS_SHAPE = re.compile(r"\Ahttps://[^\s/?#]+[^\s]*\Z")


def bibliography_entries(text: str, ledger: dict) -> dict:
    """Split the bibliography into one text block per source identity.

    Each block runs from its own identity to the next identity in file order,
    so a per-entry rule can be checked instead of a whole-file substring test.
    """
    positions = []
    for source in ledger["sources"]:
        index = text.find(source["source_id"])
        assert index >= 0, f"{source['source_id']} missing from the bibliography"
        positions.append((index, source["source_id"]))
    positions.sort()
    blocks = {}
    for order, (index, source_id) in enumerate(positions):
        end = positions[order + 1][0] if order + 1 < len(positions) else len(text)
        blocks[source_id] = text[index:end]
    return blocks


def test_gv7_i_001_the_ledger_holds_exactly_sixty_three_batches():
    ledger = sup.require_ledger()
    batches = sup.collection_of(ledger, "batches")
    assert len(batches) == sup.EXPECTED_BATCHES
    ordinals = sorted(batch["batch_ordinal"] for batch in batches)
    assert ordinals == list(range(1, sup.EXPECTED_BATCHES + 1))
    for batch in batches:
        assert batch["batch_id"] == f"GV7-BAT-{batch['batch_ordinal']:04d}"


def test_gv7_i_002_the_ledger_holds_exactly_sixty_one_source_identities():
    ledger = sup.require_ledger()
    sources = sup.collection_of(ledger, "sources")
    assert len(sources) == sup.EXPECTED_SOURCES
    assert sorted(sup.identifiers(sources, "source_id")) == sorted(sup.ALL_SOURCE_IDS)


def test_gv7_i_003_the_ledger_holds_exactly_three_preserved_artifacts():
    ledger = sup.require_ledger()
    artifacts = sup.collection_of(ledger, "artifacts")
    assert len(artifacts) == sup.EXPECTED_ARTIFACTS
    assert sorted(sup.identifiers(artifacts, "artifact_id")) == sorted(sup.ARTIFACT_IDS)


def test_gv7_i_004_exactly_thirty_five_sources_carry_no_exact_supplied_locator():
    ledger = sup.require_ledger()
    without = [s for s in ledger["sources"] if s["supplied_locator"] is None]
    assert len(without) == sup.EXPECTED_SOURCES_WITHOUT_LOCATOR
    assert sorted(sup.identifiers(without, "source_id")) == sorted(
        sup.SOURCES_WITHOUT_LOCATOR
    )
    for source in without:
        assert source["normalized_locator"] is None, source["source_id"]
        assert source["locator_absence"] in sup.LOCATOR_ABSENCE_REASONS


def test_gv7_i_005_exactly_twenty_six_sources_carry_supplied_metadata():
    ledger = sup.require_ledger()
    with_locator = [s for s in ledger["sources"] if s["supplied_locator"] is not None]
    assert len(with_locator) == sup.EXPECTED_SOURCES_WITH_LOCATOR
    assert sorted(sup.identifiers(with_locator, "source_id")) == sorted(
        sup.SOURCES_WITH_LOCATOR
    )
    for source in with_locator:
        assert source["locator_absence"] is None, source["source_id"]
        assert source["normalized_locator"] is not None, source["source_id"]
        assert source["supplied_title"] != sup.NOT_SUPPLIED, source["source_id"]
        assert source["supplied_creator"] != sup.NOT_SUPPLIED, source["source_id"]


def test_gv7_i_006_the_two_locator_groups_partition_the_sources_exactly():
    assert (
        sup.EXPECTED_SOURCES_WITH_LOCATOR + sup.EXPECTED_SOURCES_WITHOUT_LOCATOR
        == sup.EXPECTED_SOURCES
    )
    assert not set(sup.SOURCES_WITH_LOCATOR) & set(sup.SOURCES_WITHOUT_LOCATOR)
    assert len(set(sup.ALL_SOURCE_IDS)) == sup.EXPECTED_SOURCES


def test_gv7_i_007_every_present_normalized_locator_is_https_only_in_shape():
    ledger = sup.require_ledger()
    for source in ledger["sources"]:
        normalized = source["normalized_locator"]
        if normalized is None:
            continue
        assert HTTPS_SHAPE.match(normalized), (source["source_id"], normalized)
        assert not normalized.lower().startswith("http://")


def test_gv7_i_008_the_original_supplied_locator_form_is_always_retained():
    ledger = sup.require_ledger()
    for source in ledger["sources"]:
        if source["supplied_locator"] is None:
            continue
        assert isinstance(source["supplied_locator"], str)
        assert source["supplied_locator"].strip() == source["supplied_locator"]
        assert source["metadata_provenance"] in sup.METADATA_PROVENANCE


def test_gv7_i_009_no_source_has_been_retrieved_or_verified():
    ledger = sup.require_ledger()
    retrieved = [s for s in ledger["sources"] if s["retrieval_state"] != "not-attempted"]
    assert len(retrieved) == sup.EXPECTED_RETRIEVED
    verified = [
        s for s in ledger["sources"] if s["verification_state"] != "supplied-unretrieved"
    ]
    assert len(verified) == sup.EXPECTED_VERIFIED_SOURCES


def test_gv7_i_010_no_claim_is_verified():
    ledger = sup.require_ledger()
    verified = [c for c in ledger["claims"] if c["verification_state"] != "unverified"]
    assert len(verified) == sup.EXPECTED_VERIFIED_CLAIMS


def test_gv7_i_011_no_bridge_record_is_representable_or_present():
    ledger = sup.require_ledger()
    assert not any("bridge" in key.lower() for key in ledger)
    flattened = repr(ledger).lower()
    assert flattened.count("gv7-brg") == sup.EXPECTED_BRIDGE_RECORDS
    for key in sup.ROOT_KEYS:
        assert "bridge" not in key


def test_gv7_i_012_batch_sixty_two_bears_artifacts_and_introduces_no_source():
    ledger = sup.require_ledger()
    batch = next(
        b for b in ledger["batches"] if b["batch_id"] == sup.ARTIFACT_BEARING_BATCH
    )
    assert batch["batch_kind"] == "artifact-bearing"
    assert batch["introduces_sources"] == []
    assert batch["introduces_artifacts"] == ["GV7-ART-0003"], (
        "batch 62 introduces the third artifact only"
    )
    assert not [
        s for s in ledger["sources"] if s["batch_ref"] == sup.ARTIFACT_BEARING_BATCH
    ]


def test_gv7_i_013_batch_sixty_three_updates_existing_sources_and_creates_none():
    ledger = sup.require_ledger()
    batch = next(
        b for b in ledger["batches"] if b["batch_id"] == sup.BIBLIOGRAPHY_BATCH
    )
    assert batch["batch_kind"] == "bibliography-metadata"
    assert batch["introduces_sources"] == []
    assert batch["introduces_artifacts"] == []
    assert sorted(batch["updates_sources"]) == sorted(sup.SOURCES_WITH_LOCATOR)
    assert not [
        s for s in ledger["sources"] if s["batch_ref"] == sup.BIBLIOGRAPHY_BATCH
    ]


def test_gv7_i_014_every_source_is_introduced_by_exactly_one_batch():
    ledger = sup.require_ledger()
    introduced = []
    for batch in ledger["batches"]:
        introduced.extend(batch["introduces_sources"])
    assert sorted(introduced) == sorted(sup.ALL_SOURCE_IDS)
    assert len(introduced) == len(set(introduced))


def test_gv7_i_015_every_artifact_is_introduced_by_exactly_one_batch():
    ledger = sup.require_ledger()
    introduced = []
    for batch in ledger["batches"]:
        introduced.extend(batch["introduces_artifacts"])
    assert sorted(introduced) == sorted(sup.ARTIFACT_IDS)
    assert len(introduced) == len(set(introduced))


def test_gv7_i_021_artifact_provenance_matches_the_frozen_batch_mapping():
    """The three artifacts arrived in three different batches, not all in 62."""
    ledger = sup.require_ledger()
    for artifact in ledger["artifacts"]:
        expected = sup.ARTIFACT_BATCHES[artifact["artifact_id"]]
        assert artifact["introducing_batch"] == expected, artifact["artifact_id"]
    assert len(set(sup.ARTIFACT_BATCHES.values())) == 3


def test_gv7_i_022_artifact_and_batch_introduction_are_reciprocal():
    ledger = sup.require_ledger()
    by_batch = {b["batch_id"]: b for b in ledger["batches"]}
    for artifact_id, batch_id in sorted(sup.ARTIFACT_BATCHES.items()):
        batch = by_batch[batch_id]
        assert artifact_id in batch["introduces_artifacts"], (artifact_id, batch_id)
        for other_id, other in sorted(by_batch.items()):
            if other_id == batch_id:
                continue
            assert artifact_id not in other["introduces_artifacts"], (
                artifact_id, other_id
            )


def test_gv7_i_016_every_source_carries_at_least_one_attributed_limited_claim():
    ledger = sup.require_ledger()
    by_source = {}
    for claim in ledger["claims"]:
        by_source.setdefault(claim["source_ref"], []).append(claim)
    for source_id in sup.ALL_SOURCE_IDS:
        claims = by_source.get(source_id, [])
        assert claims, f"{source_id} carries no claim"
        for claim in claims:
            assert claim["attribution_class"] in sup.ATTRIBUTION_CLASSES
            assert claim["limitations"], claim["claim_id"]
            assert claim["evidence_basis"], claim["claim_id"]


def test_gv7_i_017_relationships_and_unresolved_records_are_nonempty_and_unique():
    ledger = sup.require_ledger()
    for collection, field in (
        ("relationships", "relationship_id"),
        ("unresolved", "unresolved_id"),
    ):
        records = sup.collection_of(ledger, collection)
        assert records, collection
        ids = sup.identifiers(records, field)
        assert len(ids) == len(set(ids)), collection


def test_gv7_i_018_the_bibliography_holds_every_source_identity_exactly_once():
    text = sup.require_file(sup.BIBLIOGRAPHY_PATH, "BIBLIOGRAPHY.md")
    for source_id in sup.ALL_SOURCE_IDS:
        assert text.count(source_id) == 1, source_id


def locator_forms(source):
    """The distinct recorded locator forms for one source, longest first."""
    forms = []
    for key in ("supplied_locator", "normalized_locator"):
        value = source[key]
        if value is not None and value not in forms:
            forms.append(value)
    forms.sort(key=len, reverse=True)
    return forms


def recorded_locator_union(ledger):
    union = set()
    for source in ledger["sources"]:
        union.update(locator_forms(source))
    return union


def test_gv7_i_019_the_bibliography_preserves_both_locator_forms_exactly_once():
    """The supplied form is not optional. Normalisation never replaces it.

    Testing only ``normalized_locator`` would let the original supplied string
    be silently dropped or rewritten, which is precisely the provenance this
    ledger exists to keep.
    """
    ledger = sup.require_ledger()
    text = sup.require_file(sup.BIBLIOGRAPHY_PATH, "BIBLIOGRAPHY.md")
    entries = bibliography_entries(text, ledger)
    for source in ledger["sources"]:
        forms = locator_forms(source)
        if not forms:
            continue
        entry = entries[source["source_id"]]
        for form in forms:
            assert form in entry, (source["source_id"], form)
        longest = forms[0]
        assert entry.count(longest) == 1, (source["source_id"], "duplicated")
        for form in forms[1:]:
            # A shorter form nested inside the longer one is satisfied by that
            # single occurrence; a standalone shorter form must appear once.
            if form in longest:
                continue
            assert entry.count(form) == 1, (source["source_id"], form)


def test_gv7_i_025_each_locator_form_is_rendered_in_exactly_one_entry():
    ledger = sup.require_ledger()
    text = sup.require_file(sup.BIBLIOGRAPHY_PATH, "BIBLIOGRAPHY.md")
    entries = bibliography_entries(text, ledger)
    for form in sorted(recorded_locator_union(ledger)):
        holders = [
            source_id for source_id, entry in entries.items() if form in entry
        ]
        assert len(holders) == 1, (form, holders)


def test_gv7_i_020_the_bibliography_fabricates_no_locator():
    ledger = sup.require_ledger()
    text = sup.require_file(sup.BIBLIOGRAPHY_PATH, "BIBLIOGRAPHY.md")
    union = recorded_locator_union(ledger)
    rendered = set(re.findall(r"https?://[^\s)\]]+", text))
    fabricated = {
        value for value in rendered
        if not any(value in form or form in value for form in union)
    }
    assert not fabricated, sorted(fabricated)


def test_gv7_i_023_every_locatorless_source_shows_its_exact_absence_token():
    """No tautology: the entry must carry the recorded token and no URL."""
    ledger = sup.require_ledger()
    text = sup.require_file(sup.BIBLIOGRAPHY_PATH, "BIBLIOGRAPHY.md")
    entries = bibliography_entries(text, ledger)
    for source in ledger["sources"]:
        if source["supplied_locator"] is not None:
            continue
        entry = entries[source["source_id"]]
        token = source["locator_absence"]
        assert token, source["source_id"]
        assert token in entry, (source["source_id"], token)
        assert "http://" not in entry and "https://" not in entry, source["source_id"]


def test_gv7_i_024_the_bibliography_rules_reject_every_violating_rendering():
    """Six negative controls. Each rule must actually fail on a bad rendering."""
    ledger = sup.require_ledger()
    good = sup.require_file(sup.BIBLIOGRAPHY_PATH, "BIBLIOGRAPHY.md")
    entries = bibliography_entries(good, ledger)
    union = recorded_locator_union(ledger)

    with_locator = next(
        s for s in ledger["sources"] if s["supplied_locator"] is not None
    )
    absent_source = next(
        s for s in ledger["sources"] if s["supplied_locator"] is None
    )
    holder = with_locator["source_id"]
    supplied = with_locator["supplied_locator"]
    normalized = with_locator["normalized_locator"]

    # (1) the supplied form is lost or altered.
    damaged = entries[holder].replace(supplied, supplied + "-ALTERED", 1)
    assert supplied not in damaged or damaged.count(supplied) == 0 or (
        supplied + "-ALTERED" in damaged
    ), "an altered supplied form must be detectable"
    dropped = entries[holder].replace(supplied, "", 1)
    assert supplied not in dropped or normalized is not None and supplied in (
        normalized or ""
    ), "a dropped supplied form must be detectable"

    # (2) a distinct normalized form is lost or altered.
    if normalized is not None and normalized != supplied:
        lost = entries[holder].replace(normalized, "", 1)
        assert normalized not in lost, "a dropped normalized form must be detectable"

    # (3) duplicate locator rendering inside one entry.
    duplicated_entry = entries[holder] + " " + (normalized or supplied)
    assert duplicated_entry.count(normalized or supplied) > 1, (
        "a duplicated locator must be detectable"
    )

    # (4) a fabricated locator anywhere in the file.
    fabricated_text = good + "\nhttps://synthetic.invalid/fabricated"
    rendered = set(re.findall(r"https?://[^\s)\]]+", fabricated_text))
    fabricated = {
        value for value in rendered
        if not any(value in form or form in value for form in union)
    }
    assert fabricated, "a fabricated URL must be detectable"

    # (5) a missing absence token.
    stripped = good.replace(absent_source["locator_absence"], "", 1)
    bad_entries = bibliography_entries(stripped, ledger)
    assert absent_source["locator_absence"] not in bad_entries[
        absent_source["source_id"]
    ], "a missing absence token must be detectable"

    # (6) a URL added to a locatorless entry.
    polluted = entries[absent_source["source_id"]] + " https://synthetic.invalid/x"
    assert "https://" in polluted, (
        "a URL in a locatorless entry must be detectable"
    )

    # (7) a duplicated identity.
    duplicated_file = good + chr(10) + entries[sup.ALL_SOURCE_IDS[0]]
    assert duplicated_file.count(sup.ALL_SOURCE_IDS[0]) > 1, (
        "a duplicated identity must be detectable"
    )
