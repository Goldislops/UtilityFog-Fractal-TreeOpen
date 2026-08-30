"""Frozen inventory, source-metadata and bibliography controls.

Implementation-dependent. Every figure asserted here is frozen by CONTRACT.md
section 5; none is invented, and no total is asserted for claims,
relationships, or unresolved issues.

Control ids GV7-I-NNN are declared in ``test_controls_manifest.py``.
"""

from __future__ import annotations

import json
import re

import pytest

from experiments.general_v7_ledger.tests import _support as sup

HTTPS_SHAPE = re.compile(r"\Ahttps://[^\s/?#]+[^\s]*\Z")


#: The frozen entry format. A heading is a whole LINE, never a substring: a
#: cross-reference or a table of contents would otherwise be mistaken for the
#: entry itself, and every per-entry rule would then be evaluated against the
#: wrong text.
HEADING_RE = re.compile(r"\A###[ \t]+(GV7-SRC-[0-9]{4})[ \t]*\Z")
FIELD_RE = re.compile(
    r"\A-[ \t]+(supplied_locator|normalized_locator|locator_absence):[ \t](.*)\Z"
)

#: Deliberately wider than the recorded locator shape. A fabricated locator is
#: usually a *near* miss -- a real locator with something appended, or truncated
#: to its host -- so the scan must catch URL-like material of any scheme, and
#: the rules then require it to sit inside a labelled value.
URL_LIKE_RE = re.compile(r"(?i)(?:[a-z][a-z0-9+.-]*://|\bwww\.)[^\s]+")


def render_bibliography(ledger: dict) -> str:
    """The exact rendering the contract requires, for a given ledger."""
    lines = ["# Bibliography", ""]
    for source in ledger["sources"]:
        lines.append(f"### {source['source_id']}")
        for label in sup.BIBLIOGRAPHY_FIELD_LABELS:
            lines.append(f"- {label}: {json.dumps(source[label], ensure_ascii=True)}")
        lines.append("")
    return "\n".join(lines)


def parse_bibliography(text: str):
    """``(blocks, preamble)`` where a block is ``(source_id, [lines])``.

    Blocks are delimited by heading LINES, so nothing before the first heading
    is ever attributed to a source and nothing after the last heading is
    silently swallowed into it.
    """
    lines = text.split("\n")
    headings = [
        (index, match.group(1))
        for index, line in enumerate(lines)
        if (match := HEADING_RE.match(line))
    ]
    blocks = []
    for order, (index, source_id) in enumerate(headings):
        end = headings[order + 1][0] if order + 1 < len(headings) else len(lines)
        blocks.append((source_id, lines[index + 1 : end]))
    preamble = lines[: headings[0][0]] if headings else lines
    return blocks, preamble


def bibliography_violations(text: str, ledger: dict):
    """Every defect, as ``(kind, detail)``. Empty means the rendering is exact.

    One function, called by the positive control and by every negative control,
    so a negative control proves that **this** predicate refuses the fault --
    not that ``str.replace`` replaced something.
    """
    violations = []
    blocks, preamble = parse_bibliography(text)
    by_id = {source["source_id"]: source for source in ledger["sources"]}

    counted = {}
    for source_id, _lines in blocks:
        counted[source_id] = counted.get(source_id, 0) + 1
    for source_id in sorted(counted):
        if counted[source_id] != 1:
            violations.append(("heading-not-once", (source_id, counted[source_id])))
    for source_id in sorted(set(by_id) - set(counted)):
        violations.append(("source-absent", source_id))
    for source_id in sorted(set(counted) - set(by_id)):
        violations.append(("source-added", source_id))

    for line in preamble:
        if URL_LIKE_RE.search(line):
            violations.append(("url-outside-entry", line.strip()))

    for source_id, block in blocks:
        source = by_id.get(source_id)
        if source is None:
            continue
        found = {}
        labelled_indices = set()
        for index, line in enumerate(block):
            match = FIELD_RE.match(line)
            if match is None:
                continue
            labelled_indices.add(index)
            found.setdefault(match.group(1), []).append(match.group(2))

        parsed_values = {}
        for label in sup.BIBLIOGRAPHY_FIELD_LABELS:
            raw_values = found.get(label, [])
            if len(raw_values) != 1:
                violations.append((f"{label}-not-once", (source_id, len(raw_values))))
                continue
            try:
                value = json.loads(raw_values[0])
            except ValueError:
                violations.append((f"{label}-unparsable", source_id))
                continue
            if not (value is None or type(value) is str):
                violations.append((f"{label}-not-a-scalar", source_id))
                continue
            parsed_values[label] = value
            if value != source[label]:
                violations.append((f"{label}-mismatch", source_id))

        # The bibliography is an independent witness to the pairing rule.
        if set(parsed_values) == set(sup.BIBLIOGRAPHY_FIELD_LABELS):
            supplied = parsed_values["supplied_locator"]
            normalized = parsed_values["normalized_locator"]
            absence = parsed_values["locator_absence"]
            if (supplied is None) != (normalized is None):
                violations.append(("locator-pairing", source_id))
            if (absence is None) == (supplied is None):
                violations.append(("absence-pairing", source_id))
            if absence is not None and absence not in sup.LOCATOR_ABSENCE_REASONS:
                violations.append(("absence-token-invalid", source_id))

        for index, line in enumerate(block):
            if index in labelled_indices:
                continue
            if URL_LIKE_RE.search(line):
                violations.append(("url-outside-labelled-field", source_id))

    return violations


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
        # Section 5 says these 26 carry supplied URL, TITLE and CHANNEL.
        assert source["supplied_title"] != sup.NOT_SUPPLIED, source["source_id"]
        assert source["supplied_channel"] != sup.NOT_SUPPLIED, source["source_id"]
        # `supplied_creator` may honestly remain not-supplied: many supplied
        # items name a publisher without naming an author, and inventing one
        # would be fabrication. Asserting it here would require exactly that.
        assert type(source["supplied_creator"]) is str, source["source_id"]


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
    """Verbatim means verbatim.

    This control used to assert ``supplied_locator.strip() == supplied_locator``.
    That is **withdrawn**: it required the one field that exists to be
    un-normalised to already equal its own whitespace-canonical form, so the
    only way to satisfy it was to store the stripped value -- destroying the
    exact provenance the field exists to keep. Whitespace canonicality is a
    property of ``normalized_locator`` alone.
    """
    ledger = sup.require_ledger()
    for source in ledger["sources"]:
        assert source["metadata_provenance"] in sup.METADATA_PROVENANCE
        supplied = source["supplied_locator"]
        normalized = source["normalized_locator"]
        if supplied is None:
            continue
        assert type(supplied) is str and supplied
        assert type(normalized) is str and normalized
        # The normalized form -- and only the normalized form -- is canonical.
        assert normalized.strip() == normalized, source["source_id"]
        assert normalized.isascii(), source["source_id"]


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
            assert claim["attribution_class"] in sup.CLAIM_ATTRIBUTION_CLASSES
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


# --------------------------------------------------------------------------
# The bibliography. Accounting is structural: every value is parsed and
# compared by equality. Substring counting cannot tell a locator from its own
# prefix, cannot tell two sources that legitimately share one locator from a
# duplicated rendering, and mis-reads a locator followed by punctuation.
# --------------------------------------------------------------------------


def block_span(lines, source_id):
    headings = [
        (index, match.group(1))
        for index, line in enumerate(lines)
        if (match := HEADING_RE.match(line))
    ]
    for order, (index, found) in enumerate(headings):
        if found == source_id:
            end = headings[order + 1][0] if order + 1 < len(headings) else len(lines)
            return index + 1, end
    raise AssertionError(f"no heading line for {source_id}")


def field_index(lines, source_id, label):
    start, end = block_span(lines, source_id)
    for index in range(start, end):
        match = FIELD_RE.match(lines[index])
        if match is not None and match.group(1) == label:
            return index
    raise AssertionError(f"no {label} line inside {source_id}")


def bibliography_text():
    return sup.require_file(sup.BIBLIOGRAPHY_PATH, "BIBLIOGRAPHY.md")


def test_gv7_i_018_the_bibliography_renders_every_source_exactly_once():
    """A heading is a whole line, so a cross-reference is not an entry."""
    ledger = sup.require_ledger()
    blocks, _preamble = parse_bibliography(bibliography_text())
    rendered = [source_id for source_id, _lines in blocks]
    assert sorted(rendered) == sorted(sup.ALL_SOURCE_IDS)
    assert len(rendered) == len(set(rendered)) == len(ledger["sources"])


def test_gv7_i_019_the_bibliography_preserves_both_locator_forms_exactly():
    """Parsed and compared by equality, never by containment.

    Containment is vacuous for the commonest normalisation: when the supplied
    form is a substring of the normalized form -- ``example.invalid/a`` inside
    ``https://example.invalid/a`` -- a rendering that prints only the normalized
    URL satisfies every substring test while the supplied form is gone.
    """
    ledger = sup.require_ledger()
    blocks, _preamble = parse_bibliography(bibliography_text())
    by_id = {source["source_id"]: source for source in ledger["sources"]}
    lines = bibliography_text().split("\n")
    for source_id, _block in blocks:
        source = by_id[source_id]
        for label in sup.BIBLIOGRAPHY_FIELD_LABELS:
            index = field_index(lines, source_id, label)
            raw = FIELD_RE.match(lines[index]).group(2)
            value = json.loads(raw)
            assert value == source[label], (source_id, label)
            assert value is None or type(value) is str, (source_id, label)


def test_gv7_i_020_no_url_like_material_appears_outside_a_locator_value():
    ledger = sup.require_ledger()
    violations = bibliography_violations(bibliography_text(), ledger)
    leaked = [item for item in violations if item[0].startswith("url-outside")]
    assert not leaked, leaked


def test_gv7_i_023_every_locatorless_entry_is_null_null_and_its_exact_token():
    ledger = sup.require_ledger()
    lines = bibliography_text().split("\n")
    for source in ledger["sources"]:
        if source["supplied_locator"] is not None:
            continue
        source_id = source["source_id"]
        values = {
            label: json.loads(
                FIELD_RE.match(lines[field_index(lines, source_id, label)]).group(2)
            )
            for label in sup.BIBLIOGRAPHY_FIELD_LABELS
        }
        assert values["supplied_locator"] is None, source_id
        assert values["normalized_locator"] is None, source_id
        assert values["locator_absence"] == source["locator_absence"], source_id
        assert values["locator_absence"] in sup.LOCATOR_ABSENCE_REASONS, source_id
        start, end = block_span(lines, source_id)
        for line in lines[start:end]:
            if FIELD_RE.match(line):
                continue
            assert not URL_LIKE_RE.search(line), (source_id, line)


def test_gv7_i_025_shared_and_prefix_nested_locators_are_never_conflated():
    """Sharing is not duplication, and a prefix is not the thing it prefixes."""
    ledger = sup.require_ledger()
    lines = bibliography_text().split("\n")
    for source in ledger["sources"]:
        source_id = source["source_id"]
        for label in ("supplied_locator", "normalized_locator"):
            index = field_index(lines, source_id, label)
            assert json.loads(FIELD_RE.match(lines[index]).group(2)) == source[label]
    # Every recorded value is accounted for exactly as many times as it is
    # recorded -- so two sources may share one locator, and each keeps it.
    recorded, rendered = {}, {}
    for source in ledger["sources"]:
        for label in ("supplied_locator", "normalized_locator"):
            value = source[label]
            if value is None:
                continue
            recorded[(source["source_id"], label)] = value
            index = field_index(lines, source["source_id"], label)
            rendered[(source["source_id"], label)] = json.loads(
                FIELD_RE.match(lines[index]).group(2)
            )
    assert rendered == recorded


def test_gv7_i_024_the_committed_bibliography_has_no_violation_at_all():
    """And every shipped document carries its own acceptance boundary.

    Each of ``BIBLIOGRAPHY.md``, ``INTAKE_REPORT.md`` and ``README.md`` is
    separately liftable -- pasted into a ticket, an appendix, a slide -- and a
    reader who receives one does not receive the other two. So each must state
    for itself, before its substantive content, that it is synthetic
    calibration material and that it is not merge-authorized. A bibliography of
    sixty-one entries with live-looking ``https://`` URLs is the most liftable
    artifact of all, and the least self-describing unless it says so.
    """
    ledger = sup.require_ledger()
    violations = bibliography_violations(bibliography_text(), ledger)
    assert not violations, violations

    boundary = []
    for name in sup.ACCEPTANCE_BOUNDARY_DOCUMENTS:
        text = sup.require_file(sup.LAB_DIR / name, name)
        boundary.extend(sup.acceptance_boundary_violations(name, text))
    assert not boundary, boundary

    # The predicate discriminates, proved on self-contained fixtures rather
    # than assumed: a document that says neither, or only one, is refused, and
    # a statement placed after the first record does not count as a boundary.
    compliant = (
        "# Doc\n\nThis is synthetic calibration material and is "
        "not merge-authorized.\n\n## Body\n\ncontent\n"
    )
    assert not sup.acceptance_boundary_violations("probe", compliant)
    for label, fixture in (
        ("neither statement", "# Doc\n\n## Body\n\ncontent\n"),
        (
            "synthetic only",
            "# Doc\n\nWholly synthetic.\n\n## Body\n\ncontent\n",
        ),
        (
            "boundary only",
            "# Doc\n\nThis is not merge-authorized.\n\n## Body\n\ncontent\n",
        ),
        (
            "both, but after the first record",
            "# Doc\n\n## Body\n\nsynthetic calibration material, "
            "not merge-authorized\n",
        ),
        # SHAPE faults, not content faults. Both were reachable before.
        (
            "a record heading on the very first line",
            "### GV7-SRC-0001\n- supplied_locator: "
            '"https://example.invalid/synthetic/item-0001"\n'
            "- note: not merge-authorized\n",
        ),
        (
            "no substantive line at all",
            "# Doc\n\nordinary prose\n\nsynthetic calibration material, "
            "not merge-authorized\n",
        ),
        (
            "the phrase satisfied only by a locator",
            "# Doc\n\nSee https://example.invalid/synthetic/item-0001 "
            "-- not merge-authorized.\n\n## Body\n\ncontent\n",
        ),
        (
            "a negated declaration",
            "# Doc\n\nThis is non-synthetic calibration material and is "
            "not merge-authorized.\n\n## Body\n\ncontent\n",
        ),
    ):
        assert sup.acceptance_boundary_violations("probe", fixture), label
    # British orthography, which this repository also uses, must be accepted.
    assert not sup.acceptance_boundary_violations(
        "probe", compliant.replace("merge-authorized", "merge-authorised")
    )


# --------------------------------------------------------------------------
# The predicate itself, proved against a synthetic ledger and its exact
# rendering. This control is implementation-independent and passes now: it is
# what makes the controls above evidence rather than assertion.
# --------------------------------------------------------------------------


def synthetic_pair():
    """A miniature ledger carrying every hazard the rules must survive."""
    sources = [
        # locatorless
        {
            "source_id": "GV7-SRC-0001",
            "supplied_locator": None,
            "normalized_locator": None,
            "locator_absence": "no-exact-locator-supplied",
        },
        # supplied form differs from normalized ONLY by whitespace, and is a
        # substring of it: the case a containment test cannot see.
        {
            "source_id": "GV7-SRC-0002",
            "supplied_locator": "  example.invalid/a  ",
            "normalized_locator": "https://example.invalid/a",
            "locator_absence": None,
        },
        # SHARED with the source above, legitimately.
        {
            "source_id": "GV7-SRC-0003",
            "supplied_locator": "https://example.invalid/a",
            "normalized_locator": "https://example.invalid/a",
            "locator_absence": None,
        },
        # PREFIX-NESTED: a strict extension of the shared value.
        {
            "source_id": "GV7-SRC-0004",
            "supplied_locator": "https://example.invalid/ab",
            "normalized_locator": "https://example.invalid/ab",
            "locator_absence": None,
        },
        # PUNCTUATION and PARENTHESES inside the supplied form.
        {
            "source_id": "GV7-SRC-0005",
            "supplied_locator": "(https://example.invalid/c).",
            "normalized_locator": "https://example.invalid/c",
            "locator_absence": None,
        },
    ]
    ledger = {"sources": sources}
    return ledger, render_bibliography(ledger)


def test_gv7_i_026_the_bibliography_predicate_detects_every_named_fault():
    """A checker that only refuses is broken; a checker that never refuses is
    worse. Both halves are proved here, and every negative alters the PARSED
    FIELD rather than demonstrating that ``str.replace`` replaced something.
    """
    ledger, good = synthetic_pair()
    assert not bibliography_violations(good, ledger), "the exact rendering is clean"

    def mutated(source_id, label, raw):
        lines = good.split("\n")
        index = field_index(lines, source_id, label)
        before = lines[index]
        lines[index] = f"- {label}: {raw}"
        assert lines[index] != before, "the fixture changed nothing"
        return "\n".join(lines)

    def kinds(text):
        return {kind for kind, _detail in bibliography_violations(text, ledger)}

    # 1. the supplied form altered -- the substring survives, the value does not.
    assert "supplied_locator-mismatch" in kinds(
        mutated("GV7-SRC-0002", "supplied_locator", json.dumps("example.invalid/a"))
    )
    # 2. a trailing slash: invisible to containment, fatal to equality.
    assert "normalized_locator-mismatch" in kinds(
        mutated(
            "GV7-SRC-0003", "normalized_locator",
            json.dumps("https://example.invalid/a/"),
        )
    )
    # 3. the prefix-nested value replaced by the value it extends.
    assert "supplied_locator-mismatch" in kinds(
        mutated(
            "GV7-SRC-0004", "supplied_locator",
            json.dumps("https://example.invalid/a"),
        )
    )
    # 4. a locator value moved onto another source's entry.
    assert "supplied_locator-mismatch" in kinds(
        mutated(
            "GV7-SRC-0005", "supplied_locator",
            json.dumps("https://example.invalid/ab"),
        )
    )
    # 5. the field line dropped entirely.
    lines = good.split("\n")
    del lines[field_index(lines, "GV7-SRC-0002", "normalized_locator")]
    assert "normalized_locator-not-once" in kinds("\n".join(lines))
    # 6. the field line duplicated inside one entry.
    lines = good.split("\n")
    index = field_index(lines, "GV7-SRC-0002", "supplied_locator")
    lines.insert(index, lines[index])
    assert "supplied_locator-not-once" in kinds("\n".join(lines))
    # 7. a non-scalar value.
    assert "supplied_locator-not-a-scalar" in kinds(
        mutated("GV7-SRC-0002", "supplied_locator", '["a"]')
    )
    # 8. an unparsable value.
    assert "supplied_locator-unparsable" in kinds(
        mutated("GV7-SRC-0002", "supplied_locator", "https://example.invalid/a")
    )
    # 9. the absence token removed from the locatorless entry.
    assert "locator_absence-mismatch" in kinds(
        mutated("GV7-SRC-0001", "locator_absence", "null")
    )
    # 10. a URL added to the locatorless entry, in prose.
    lines = good.split("\n")
    start, _end = block_span(lines, "GV7-SRC-0001")
    lines.insert(start, "see https://example.invalid/fabricated for details")
    assert "url-outside-labelled-field" in kinds("\n".join(lines))
    # 11. a fabricated URL in the preamble, extending a real locator -- the
    #     class a containment test rescues and therefore never flags.
    assert "url-outside-entry" in kinds(
        "https://example.invalid/aXXX\n" + good
    )
    # 12. a bare-host truncation of a real locator, also in prose.
    assert "url-outside-entry" in kinds("https://example.invalid\n" + good)
    # 13. a duplicated heading.
    lines = good.split("\n")
    start, end = block_span(lines, "GV7-SRC-0003")
    duplicate = ["### GV7-SRC-0003"] + lines[start:end]
    assert "heading-not-once" in kinds("\n".join(lines + duplicate))
    # 14. a removed heading.
    lines = good.split("\n")
    start, end = block_span(lines, "GV7-SRC-0004")
    assert "source-absent" in kinds("\n".join(lines[: start - 1] + lines[end:]))
    # 15. an added identity nobody recorded.
    assert "source-added" in kinds(good + "\n### GV7-SRC-0099\n")
    # 16. the pairing rule broken inside the bibliography itself.
    assert "absence-pairing" in kinds(
        mutated("GV7-SRC-0003", "locator_absence", json.dumps("locator-not-applicable"))
    )
    assert "locator-pairing" in kinds(
        mutated("GV7-SRC-0003", "normalized_locator", "null")
    )
    # 17. an absence token outside the closed vocabulary.
    assert "absence-token-invalid" in kinds(
        mutated("GV7-SRC-0001", "locator_absence", json.dumps("because-i-said-so"))
    )
    # And the shared value is NOT reported: sharing is lawful.
    assert not bibliography_violations(good, ledger)


#: Every locator authority the calibration data may carry. Written as a scan
#: over the committed text, not over parsed fields only, so a real host cannot
#: hide in prose the parser never reads.
LOCATOR_AUTHORITY_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*)://([^/\s\"'<>)\]]+)")

#: A scheme is not required to name a host. `github.com/org/repo`,
#: `//raw.githubusercontent.com/x` and `www.nature.com/a` are all locators to a
#: reader, and the scheme-bearing scan above saw none of them.
SCHEMELESS_AUTHORITY_RE = re.compile(
    r"(?i)(?:^|[\s(<\[])(?://)?((?:www\.[a-z0-9-]+|[a-z0-9-]+)(?:\.[a-z0-9-]+)+)/"
)

#: A bounded list of real public suffixes, for a scan over ONE small committed
#: corpus that is supposed to contain none of them. It is a deny-list and
#: therefore decides nothing about a suffix it does not name -- CONTRACT.md
#: section 8a says so, and this comment does not claim otherwise.
REAL_SUFFIX_RE = re.compile(
    r"(?i)\b[a-z0-9-]+\.(?:com|org|net|gov|edu|mil|int|io|ai|co|dev|app|info|biz"
    r"|uk|de|fr|jp|cn|ru|us|eu|nl|se|ch|it|es|ca|au|in|br)\b"
)


def locator_authorities(text: str):
    """``(scheme, authority)`` pairs, lowercased, for every URL-like span.

    Scheme-less spellings are reported with the scheme ``"none"`` so a caller
    that requires ``https`` refuses them rather than never seeing them.
    """
    found = {
        (m.group(1).lower(), m.group(2).lower())
        for m in LOCATOR_AUTHORITY_RE.finditer(text)
    }
    found |= {
        ("none", m.group(1).lower()) for m in SCHEMELESS_AUTHORITY_RE.finditer(text)
    }
    return sorted(found)


def test_gv7_i_027_the_calibration_locators_are_all_the_reserved_host():
    """An evidence rule about this fabricated candidate, not about the validator.

    The validator constrains a locator's SHAPE and not its host, deliberately,
    because a real-source ledger must be able to carry a real one. So nothing
    in the code prevents a live host here, and this control is what makes the
    reserved-host property of the committed calibration data an asserted fact
    rather than an accident: rewriting every locator to a live host previously
    left the entire acceptance surface green.
    """
    ledger = sup.require_ledger()
    host = sup.CALIBRATION_LOCATOR_HOST

    present = [
        source["normalized_locator"]
        for source in ledger["sources"]
        if source["normalized_locator"] is not None
    ]
    assert present, "no locator is present at all; the rule would pass vacuously"
    for locator in present:
        assert locator.startswith(f"https://{host}/") or locator == f"https://{host}", locator

    # The whole committed text of both artifacts, scheme and authority exact.
    # `example.invalid.evil.com`, `sub.example.invalid`, a port, and userinfo
    # are each a different authority and each refused here.
    for name, text in (
        ("ledger.json", sup.require_file(sup.LEDGER_PATH, "ledger.json")),
        ("BIBLIOGRAPHY.md", bibliography_text()),
    ):
        for scheme, authority in locator_authorities(text):
            assert scheme == "https", (name, scheme, authority)
            assert authority == host, (name, authority)
        # A bounded second pass, for a corpus that should contain no real
        # public suffix at all. Disclosed as bounded: it decides nothing about
        # a suffix it does not name.
        assert not REAL_SUFFIX_RE.findall(text), (
            name,
            sorted(set(REAL_SUFFIX_RE.findall(text))),
        )

    # And the supplied forms, which are preserved verbatim and may be
    # deliberately malformed, still name no other host.
    for source in ledger["sources"]:
        supplied = source["supplied_locator"]
        if supplied is None:
            continue
        assert host in supplied, supplied
        for _scheme, authority in locator_authorities(supplied):
            assert authority == host, supplied


def test_gv7_i_028_each_liftable_document_carries_its_exact_boundary_sentence():
    """The exact sentence, in the preamble, before the first substantive line."""
    for name, sentence in sorted(sup.CALIBRATION_BOUNDARY_SENTENCES.items()):
        text = sup.require_file(sup.LAB_DIR / name, name)
        assert sentence in text, (name, sentence)
        preamble = sup.acceptance_boundary_preamble(text)
        assert preamble != text, name
        assert sentence in preamble, (
            name,
            "the boundary sentence is present but sits after the content",
        )
        # And the document as a whole satisfies the strengthened predicate.
        assert not sup.acceptance_boundary_violations(name, text), name

    # README is bound by the same predicate even though its wording is its own.
    readme = sup.require_file(sup.README_PATH, "README.md")
    assert not sup.acceptance_boundary_violations("README.md", readme)
