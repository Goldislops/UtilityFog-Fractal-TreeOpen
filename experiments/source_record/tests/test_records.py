"""Set-level and committed-inventory acceptance controls for ``source-record-v1``.

Set-level behaviour is exercised against synthetic records trees built under
pytest's ``tmp_path``, never inside the repository. A separate group of
controls inspects the committed fixture inventory once it exists.

Control ids SR-R-NNN are declared in ``test_controls_manifest.py``.
"""

from __future__ import annotations

import json

import pytest

from experiments.source_record.tests import _support as sup


# --------------------------------------------------------------------------
# Synthetic records-tree helpers. tmp_path only; nothing is written in-repo.
# --------------------------------------------------------------------------


def build_root(tmp_path, records, extra_root_entries=(), extra_dir_entries=()):
    """Write a synthetic records tree and return its root path."""
    root = tmp_path / "records"
    for name in sup.REGISTER_DIR_NAMES:
        (root / name).mkdir(parents=True)
    for record in records:
        register = record["register"]
        directory = root / register
        path = directory / (record["record_id"] + ".json")
        path.write_text(
            json.dumps(record, sort_keys=True, ensure_ascii=True),
            encoding="utf-8",
        )
    for name in extra_root_entries:
        (root / name).write_text("synthetic", encoding="utf-8")
    for directory_name, entry_name in extra_dir_entries:
        (root / directory_name / entry_name).write_text(
            "synthetic", encoding="utf-8"
        )
    return root


def minimal_valid_set():
    """One coherent, fully-referential synthetic set across all three registers."""
    records = []
    for register, letter in (("register-a", "A"), ("register-b", "B")):
        records.append(
            sup.message_record(f"SR-{letter}-MSG-0001", register=register)
        )
        records.append(
            sup.source_record(f"SR-{letter}-SRC-0001", register=register)
        )
        records.append(
            sup.source_record(
                f"SR-{letter}-SRC-0002",
                register=register,
                neutral_label="synthetic source beta",
                locators=[sup.locator_block(value="synthetic-handle-0002")],
            )
        )
        records.append(
            sup.assertion_record(f"SR-{letter}-ASR-0001", register=register)
        )
        records.append(
            sup.assertion_record(
                f"SR-{letter}-ASR-0002",
                register=register,
                subject_ref=f"SR-{letter}-SRC-0002",
                claim_text="a second synthetic placeholder claim",
            )
        )
        records.append(
            sup.link_record(f"SR-{letter}-LNK-0001", register=register)
        )
        records.append(
            sup.contradiction_record(f"SR-{letter}-CTR-0001", register=register)
        )
    records.append(sup.bridge_record("SR-X-BRG-0001"))
    return records


# --------------------------------------------------------------------------
# Positive controls
# --------------------------------------------------------------------------


def test_sr_r_001_a_coherent_synthetic_set_validates_and_summarizes(tmp_path):
    validate = sup.require_validate()
    root = build_root(tmp_path, minimal_valid_set())
    summary = validate.validate_records_root(root)
    registers = summary["registers"]
    assert set(registers) == set(sup.REGISTER_DIR_NAMES)
    assert registers["register-a"]["record_count"] == 7
    assert registers["register-b"]["record_count"] == 7
    assert registers["bridge"]["record_count"] == 1


def test_sr_r_002_all_three_directories_are_mandatory_but_may_be_empty(tmp_path):
    validate = sup.require_validate()
    root = build_root(tmp_path, [])
    summary = validate.validate_records_root(root)
    for name in sup.REGISTER_DIR_NAMES:
        assert summary["registers"][name]["record_count"] == 0
        assert summary["registers"][name]["record_ids"] == []


def test_sr_r_003_the_summary_has_no_combined_total_key(tmp_path):
    validate = sup.require_validate()
    root = build_root(tmp_path, minimal_valid_set())
    summary = validate.validate_records_root(root)
    flattened = json.dumps(summary, sort_keys=True)
    for forbidden in ("total", "grand", "combined", "all_records", "corpus_count"):
        assert forbidden not in flattened
    assert set(summary) == {"schema", "registers"}


def test_sr_r_004_a_legal_supersession_chain_is_accepted_and_predecessors_remain(
    tmp_path,
):
    validate = sup.require_validate()
    records = minimal_valid_set()
    first = sup.source_record("SR-A-SRC-0003", neutral_label="synthetic gamma one")
    second = sup.source_record(
        "SR-A-SRC-0004",
        neutral_label="synthetic gamma two",
        supersedes={
            "record_id": "SR-A-SRC-0003",
            "content_digest": sup.digest_of(first),
        },
    )
    third = sup.source_record(
        "SR-A-SRC-0005",
        neutral_label="synthetic gamma three",
        supersedes={
            "record_id": "SR-A-SRC-0004",
            "content_digest": sup.digest_of(second),
        },
    )
    records.extend([first, second, third])
    root = build_root(tmp_path, records)
    summary = validate.validate_records_root(root)
    ids = summary["registers"]["register-a"]["record_ids"]
    for record_id in ("SR-A-SRC-0003", "SR-A-SRC-0004", "SR-A-SRC-0005"):
        assert record_id in ids


def test_sr_r_005_a_diamond_shaped_acyclic_link_graph_is_accepted(tmp_path):
    validate = sup.require_validate()
    records = minimal_valid_set()
    for index in range(3, 6):
        records.append(
            sup.source_record(
                f"SR-A-SRC-000{index}",
                neutral_label=f"synthetic diamond node {index}",
                locators=[sup.locator_block(value=f"synthetic-handle-000{index}")],
            )
        )
    edges = (
        ("SR-A-LNK-0002", "SR-A-SRC-0003", "SR-A-SRC-0004"),
        ("SR-A-LNK-0003", "SR-A-SRC-0003", "SR-A-SRC-0005"),
        ("SR-A-LNK-0004", "SR-A-SRC-0004", "SR-A-SRC-0001"),
        ("SR-A-LNK-0005", "SR-A-SRC-0005", "SR-A-SRC-0001"),
    )
    for link_id, left, right in edges:
        records.append(sup.link_record(link_id, left_ref=left, right_ref=right))
    root = build_root(tmp_path, records)
    validate.validate_records_root(root)


# --------------------------------------------------------------------------
# Records-root and record-directory shape
# --------------------------------------------------------------------------


def test_sr_r_006_an_unexpected_entry_at_the_records_root_is_refused(tmp_path):
    validate = sup.require_validate()
    root = build_root(
        tmp_path, minimal_valid_set(), extra_root_entries=(sup.MARKER_VALUE,)
    )
    with pytest.raises(validate.RecordsPathError) as excinfo:
        validate.validate_records_root(root)
    assert excinfo.value.token == "records-root-unexpected-entry"
    assert sup.MARKER_VALUE not in str(excinfo.value)


def test_sr_r_007_a_missing_records_root_directory_is_refused(tmp_path):
    validate = sup.require_validate()
    root = build_root(tmp_path, minimal_valid_set())
    for name in sup.REGISTER_DIR_NAMES:
        target = root / name
        for child in sorted(target.iterdir()):
            child.unlink()
        target.rmdir()
        with pytest.raises(validate.RecordsPathError) as excinfo:
            validate.validate_records_root(root)
        assert excinfo.value.token == "records-root-missing-directory"
        target.mkdir()


def test_sr_r_008_a_non_json_or_subdirectory_entry_in_a_data_directory_is_refused(
    tmp_path,
):
    validate = sup.require_validate()
    root = build_root(
        tmp_path,
        minimal_valid_set(),
        extra_dir_entries=(("register-a", sup.MARKER_VALUE + ".txt"),),
    )
    with pytest.raises(validate.RecordsPathError) as excinfo:
        validate.validate_records_root(root)
    assert excinfo.value.token == "record-directory-unexpected-entry"
    assert sup.MARKER_VALUE not in str(excinfo.value)

    root = build_root(tmp_path / "second", minimal_valid_set())
    (root / "register-b" / "nested").mkdir()
    with pytest.raises(validate.RecordsPathError) as excinfo:
        validate.validate_records_root(root)
    assert excinfo.value.token == "record-directory-unexpected-entry"


def test_sr_r_009_a_filename_not_matching_its_record_id_is_refused(tmp_path):
    validate = sup.require_validate()
    root = build_root(tmp_path, minimal_valid_set())
    original = root / "register-a" / "SR-A-SRC-0001.json"
    original.rename(root / "register-a" / "SR-A-SRC-0009.json")
    with pytest.raises(validate.RecordsInputError) as excinfo:
        validate.validate_records_root(root)
    assert excinfo.value.token == "record-id-filename-mismatch"


def test_sr_r_010_a_record_placed_in_the_wrong_directory_is_refused(tmp_path):
    validate = sup.require_validate()
    records = minimal_valid_set()
    root = build_root(tmp_path, records)
    stray = root / "register-a" / "SR-B-SRC-0009.json"
    stray.write_text(
        json.dumps(
            sup.source_record("SR-B-SRC-0009", register="register-b"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    with pytest.raises(validate.RecordsInputError) as excinfo:
        validate.validate_records_root(root)
    assert excinfo.value.token == "record-id-directory-mismatch"


# --------------------------------------------------------------------------
# Set-level refusals
# --------------------------------------------------------------------------


def test_sr_r_011_a_dangling_reference_is_refused(tmp_path):
    validate = sup.require_validate()
    records = minimal_valid_set()
    records.append(
        sup.link_record(
            "SR-A-LNK-0009", left_ref="SR-A-SRC-0001", right_ref="SR-A-SRC-0099"
        )
    )
    root = build_root(tmp_path, records)
    with pytest.raises(validate.RecordsInputError) as excinfo:
        validate.validate_records_root(root)
    assert excinfo.value.token == "reference-not-found"


def test_sr_r_012_a_link_cycle_of_two_and_of_four_is_refused(tmp_path):
    validate = sup.require_validate()
    for edges in (
        (
            ("SR-A-LNK-0002", "SR-A-SRC-0001", "SR-A-SRC-0002"),
            ("SR-A-LNK-0003", "SR-A-SRC-0002", "SR-A-SRC-0001"),
        ),
        (
            ("SR-A-LNK-0002", "SR-A-SRC-0001", "SR-A-SRC-0002"),
            ("SR-A-LNK-0003", "SR-A-SRC-0002", "SR-A-SRC-0003"),
            ("SR-A-LNK-0004", "SR-A-SRC-0003", "SR-A-SRC-0004"),
            ("SR-A-LNK-0005", "SR-A-SRC-0004", "SR-A-SRC-0001"),
        ),
    ):
        records = minimal_valid_set()
        for index in (3, 4):
            records.append(
                sup.source_record(
                    f"SR-A-SRC-000{index}",
                    neutral_label=f"synthetic cycle node {index}",
                    locators=[
                        sup.locator_block(value=f"synthetic-handle-010{index}")
                    ],
                )
            )
        for link_id, left, right in edges:
            records.append(
                sup.link_record(link_id, left_ref=left, right_ref=right)
            )
        root = build_root(tmp_path / f"case{len(edges)}", records)
        with pytest.raises(validate.RecordsInputError) as excinfo:
            validate.validate_records_root(root)
        assert excinfo.value.token == "reference-cycle"


def test_sr_r_013_a_second_bridge_for_the_same_ordered_pair_is_refused(tmp_path):
    validate = sup.require_validate()
    records = minimal_valid_set()
    records.append(
        sup.bridge_record("SR-X-BRG-0002", bridge_type="shared-locator-value")
    )
    root = build_root(tmp_path, records)
    with pytest.raises(validate.RecordsInputError) as excinfo:
        validate.validate_records_root(root)
    assert excinfo.value.token == "bridge-duplicate-pair"


def test_sr_r_014_a_supersedes_digest_that_does_not_match_is_refused(tmp_path):
    validate = sup.require_validate()
    records = minimal_valid_set()
    first = sup.source_record("SR-A-SRC-0003", neutral_label="synthetic delta one")
    second = sup.source_record(
        "SR-A-SRC-0004",
        neutral_label="synthetic delta two",
        supersedes={"record_id": "SR-A-SRC-0003", "content_digest": "0" * 64},
    )
    records.extend([first, second])
    root = build_root(tmp_path, records)
    with pytest.raises(validate.RecordsInputError) as excinfo:
        validate.validate_records_root(root)
    assert excinfo.value.token == "supersedes-digest-mismatch"


def test_sr_r_015_editing_a_predecessor_in_place_breaks_its_successor(tmp_path):
    validate = sup.require_validate()
    records = minimal_valid_set()
    first = sup.source_record("SR-A-SRC-0003", neutral_label="synthetic epsilon")
    second = sup.source_record(
        "SR-A-SRC-0004",
        neutral_label="synthetic epsilon two",
        supersedes={
            "record_id": "SR-A-SRC-0003",
            "content_digest": sup.digest_of(first),
        },
    )
    records.extend([first, second])
    root = build_root(tmp_path, records)
    edited = dict(first)
    edited["neutral_label"] = "synthetic epsilon edited in place"
    (root / "register-a" / "SR-A-SRC-0003.json").write_text(
        json.dumps(edited, sort_keys=True), encoding="utf-8"
    )
    with pytest.raises(validate.RecordsInputError) as excinfo:
        validate.validate_records_root(root)
    assert excinfo.value.token == "supersedes-digest-mismatch"


def test_sr_r_016_a_predecessor_key_reordering_does_not_break_the_chain(tmp_path):
    validate = sup.require_validate()
    records = minimal_valid_set()
    first = sup.source_record("SR-A-SRC-0003", neutral_label="synthetic zeta")
    second = sup.source_record(
        "SR-A-SRC-0004",
        neutral_label="synthetic zeta two",
        supersedes={
            "record_id": "SR-A-SRC-0003",
            "content_digest": sup.digest_of(first),
        },
    )
    records.extend([first, second])
    root = build_root(tmp_path, records)
    reordered = {key: first[key] for key in sorted(first, reverse=True)}
    (root / "register-a" / "SR-A-SRC-0003.json").write_text(
        json.dumps(reordered, indent=2), encoding="utf-8"
    )
    validate.validate_records_root(root)


def test_sr_r_017_two_successors_of_one_predecessor_are_refused(tmp_path):
    validate = sup.require_validate()
    records = minimal_valid_set()
    first = sup.source_record("SR-A-SRC-0003", neutral_label="synthetic eta")
    digest = sup.digest_of(first)
    records.append(first)
    for index in (4, 5):
        records.append(
            sup.source_record(
                f"SR-A-SRC-000{index}",
                neutral_label=f"synthetic eta fork {index}",
                supersedes={
                    "record_id": "SR-A-SRC-0003",
                    "content_digest": digest,
                },
            )
        )
    root = build_root(tmp_path, records)
    with pytest.raises(validate.RecordsInputError) as excinfo:
        validate.validate_records_root(root)
    assert excinfo.value.token == "supersedes-fork-refused"


def test_sr_r_018_a_supersession_cycle_is_refused_before_digests_are_compared(
    tmp_path,
):
    """A cycle must yield exactly ``supersedes-cycle``, never a digest token.

    A digest covers a record canonical form, which includes that record own
    ``supersedes`` block, so a supersession cycle can never be
    digest-consistent: computing either digest would require the other. If
    digest matching ran first it would fire first on every cyclic fixture and
    ``supersedes-cycle`` would be unreachable, so an implementation carrying no
    cycle detector at all would pass. CONTRACT.md section 9 therefore orders
    acyclicity before digest matching, and this control asserts the exact token
    that ordering makes reachable.
    """
    validate = sup.require_validate()
    records = minimal_valid_set()
    left = sup.source_record("SR-A-SRC-0003", neutral_label="synthetic theta one")
    right = sup.source_record("SR-A-SRC-0004", neutral_label="synthetic theta two")
    # Well-formed placeholder digests: the format is valid, so the refusal
    # cannot be attributed to digest shape.
    left["supersedes"] = {"record_id": "SR-A-SRC-0004", "content_digest": "a" * 64}
    right["supersedes"] = {"record_id": "SR-A-SRC-0003", "content_digest": "b" * 64}
    records.extend([left, right])
    root = build_root(tmp_path, records)
    with pytest.raises(validate.RecordsInputError) as excinfo:
        validate.validate_records_root(root)
    assert excinfo.value.token == "supersedes-cycle"


def test_sr_r_025_a_supersedes_target_that_does_not_exist_is_refused(tmp_path):
    validate = sup.require_validate()
    records = minimal_valid_set()
    records.append(
        sup.source_record(
            "SR-A-SRC-0003",
            neutral_label="synthetic iota",
            supersedes={
                "record_id": "SR-A-SRC-0099",
                "content_digest": "c" * 64,
            },
        )
    )
    root = build_root(tmp_path, records)
    with pytest.raises(validate.RecordsInputError) as excinfo:
        validate.validate_records_root(root)
    assert excinfo.value.token == "supersedes-target-missing"


def test_sr_r_019_the_same_local_ordinal_in_both_registers_stays_distinguishable(
    tmp_path,
):
    """The homograph control: identical ordinals, distinct qualified identities."""
    validate = sup.require_validate()
    root = build_root(tmp_path, minimal_valid_set())
    summary = validate.validate_records_root(root)
    a_ids = summary["registers"]["register-a"]["record_ids"]
    b_ids = summary["registers"]["register-b"]["record_ids"]
    assert "SR-A-SRC-0001" in a_ids
    assert "SR-B-SRC-0001" in b_ids
    assert not set(a_ids) & set(b_ids)
    assert len(a_ids) == len(set(a_ids))
    assert len(b_ids) == len(set(b_ids))


def test_sr_r_020_record_id_uniqueness_is_a_derived_structural_guarantee(
    tmp_path,
):
    """Uniqueness is derived, not refused, and no token claims otherwise.

    I09 makes a filename equal its record id, so ids are unique within a
    directory. I10 makes the directory agree with the id register segment, so
    ids in different directories differ in that segment. A duplicate full
    record id is therefore unreachable: there is nothing to refuse, and
    CONTRACT.md section 8b removes the token rather than carry an untested
    claim. This control asserts the guarantee and the absence of the token.
    """
    validate = sup.require_validate()
    schema = sup.require_schema()

    assert "record-id-duplicate" not in schema.REFUSAL_TOKENS
    assert "record-id-duplicate" not in sup.REFUSAL_TOKENS

    # The same four-digit ordinal in every register and every applicable type.
    records = minimal_valid_set()
    root = build_root(tmp_path, records)
    summary = validate.validate_records_root(root)

    every_id = [
        record_id
        for name in sup.REGISTER_DIR_NAMES
        for record_id in summary["registers"][name]["record_ids"]
    ]
    assert len(every_id) == len(set(every_id))

    # The reason, asserted rather than assumed: within a directory the filename
    # carries the id, and across directories the register segment differs.
    for name in sup.REGISTER_DIR_NAMES:
        directory = root / name
        filenames = sorted(path.name for path in directory.glob("*.json"))
        assert len(filenames) == len(set(filenames))
        for filename in filenames:
            assert filename.endswith(".json")
    segments = {
        record_id[3] for record_id in every_id
    }
    assert segments <= {"A", "B", "X"}
    for name, expected_segment in (
        ("register-a", "A"),
        ("register-b", "B"),
        ("bridge", "X"),
    ):
        for record_id in summary["registers"][name]["record_ids"]:
            assert record_id[3] == expected_segment, record_id


# --------------------------------------------------------------------------
# Committed inventory
# --------------------------------------------------------------------------


def test_sr_r_021_every_committed_record_validates_and_matches_its_filename():
    schema = sup.require_schema()
    root = sup.require_records_root()
    seen = 0
    for name in sup.REGISTER_DIR_NAMES:
        directory = root / name
        for path in sorted(directory.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            schema.validate_record(payload)
            assert path.name == payload["record_id"] + ".json"
            assert payload["register"] == name or (
                name == "bridge" and payload["register"] == "bridge"
            )
            seen += 1
    assert seen > 0, "the committed inventory must not be empty"


def test_sr_r_022_the_committed_inventory_covers_every_record_type():
    schema = sup.require_schema()
    root = sup.require_records_root()
    found = set()
    for name in sup.REGISTER_DIR_NAMES:
        for path in sorted((root / name).glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            schema.validate_record(payload)
            found.add(payload["record_type"])
    assert found == set(sup.RECORD_TYPES)


def test_sr_r_023_every_committed_locator_value_is_synthetic():
    root = sup.require_records_root()
    import re

    pattern = re.compile(sup.LOCATOR_VALUE_PATTERN)
    seen = 0
    for name in sup.REGISTER_DIR_NAMES:
        for path in sorted((root / name).glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            for locator in payload.get("locators", ()):
                assert pattern.match(locator["value"]), locator["value"]
                seen += 1
    assert seen > 0, "the committed inventory must exercise at least one locator"


def test_sr_r_024_the_committed_records_root_holds_exactly_the_three_directories():
    root = sup.require_records_root()
    children = sorted(child.name for child in root.iterdir())
    assert children == sorted(sup.REGISTER_DIR_NAMES)
    for name in sup.REGISTER_DIR_NAMES:
        for child in sorted((root / name).iterdir()):
            assert child.is_file(), child.name
            assert child.suffix == ".json", child.name
