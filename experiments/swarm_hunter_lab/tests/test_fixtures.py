"""The ten S0 §7 fixture rows, asserted against the frozen contract."""

from swarm_hunter_lab import DetectorConfig, detect_structures, fixtures
from swarm_hunter_lab import schema


def run(snaps, **overrides):
    artifact = detect_structures(snaps, DetectorConfig(**overrides)) \
        if overrides else detect_structures(snaps)
    records = artifact.records()
    assert schema.validate_records(list(records)) == []
    return artifact, records


def flat(x, y, z, n=8):
    return z * n * n + y * n + x


def findings_of(records):
    return [r for r in records if r["kind"] == "finding"]


def test_empty_lattice_header_only():
    _, records = run(fixtures.fx_empty())
    assert len(records) == 1
    header = records[0]
    assert header["empty"] is True and header["truncated"] is False
    assert header["counts"] == {"components_discovered": 0,
                                "components_emitted": 0,
                                "findings": 0, "refusals": 0}


def test_single_cluster():
    _, records = run(fixtures.fx_single())
    (finding,) = findings_of(records)
    assert finding["label"] == flat(2, 2, 2)
    assert finding["cell_count"] == 27
    assert finding["region"] == {"bbox_min": [2, 2, 2], "bbox_max": [4, 4, 4],
                                 "wraps": [False, False, False]}
    assert finding["state_counts"] == {"1": 27, "2": 0, "3": 0, "4": 0}
    assert finding["density"] == {"num": 27, "den": 512}
    assert finding["persistence"]["seen_in_snapshots"] == 1


def test_two_separated_clusters():
    _, records = run(fixtures.fx_two_separated())
    found = findings_of(records)
    assert [f["label"] for f in found] == [flat(0, 0, 0), flat(5, 5, 5)]
    assert found[0]["finding_id"] != found[1]["finding_id"]
    assert found[0]["chain_id"] != found[1]["chain_id"]


def test_wraparound_cluster_is_one_finding():
    _, records = run(fixtures.fx_wraparound())
    (finding,) = findings_of(records)
    assert finding["cell_count"] == 12
    assert finding["region"]["wraps"] == [True, False, False]
    assert finding["region"]["bbox_min"][0] == 6
    assert finding["region"]["bbox_max"][0] == 0


def test_transient_cluster_chain_length_one():
    _, records = run(fixtures.fx_transient())
    (finding,) = findings_of(records)
    assert finding["persistence"]["seen_in_snapshots"] == 1
    assert len(finding["observations"]) == 1
    assert finding["observations"][0]["snapshot_id"] == "fx-transient-a"


def test_stable_cluster_one_chain_seen_three_times():
    _, records = run(fixtures.fx_stable())
    (finding,) = findings_of(records)
    assert finding["persistence"]["seen_in_snapshots"] == 3
    assert [o["snapshot_id"] for o in finding["observations"]] == \
        ["fx-stable-0", "fx-stable-1", "fx-stable-2"]
    assert finding["snapshot"] == finding["observations"][0]


def test_oscillator_two_chains_no_period_claim():
    _, records = run(fixtures.fx_oscillator())
    found = findings_of(records)
    assert len(found) == 2
    # both shapes share the minimum member cell -> same label; ordering falls
    # to first_seen_generation (frozen sort keys)
    assert found[0]["label"] == found[1]["label"] == flat(1, 1, 1)
    assert found[0]["persistence"]["seen_in_snapshots"] == 2  # A at snaps 1,3
    assert found[1]["persistence"]["seen_in_snapshots"] == 1  # B at snap 2
    for f in found:
        assert set(f.keys()) == schema.FINDING_KEYS  # no period field exists


def test_adversarial_noise_below_threshold():
    _, records = run(fixtures.fx_noise())
    assert findings_of(records) == []
    header = records[0]
    assert header["counts"]["components_discovered"] == 20
    assert header["empty"] is True and header["truncated"] is False


def test_malformed_provenance_refuses_without_analysis():
    _, records = run(fixtures.fx_malformed_provenance())
    assert len(records) == 2
    header, refusal = records
    assert refusal["kind"] == "refusal"
    assert refusal["reason"] == "invalid_provenance"
    assert refusal["message"] == schema.REFUSAL_MESSAGES["invalid_provenance"]
    assert header["counts"]["refusals"] == 1
    assert header["counts"]["findings"] == 0
    assert header["params"] is not None  # config was valid


def test_checkerboard_cap_prefix_deterministic():
    snaps = fixtures.fx_checkerboard()
    art1, records = run(snaps, min_component_size=1, component_cap=64)
    art2, _ = run(snaps, min_component_size=1, component_cap=64)
    assert art1.jsonl == art2.jsonl  # cap prefix is deterministic
    header = records[0]
    found = findings_of(records)
    assert len(found) == 64
    assert header["truncated"] is True
    assert header["truncation"] == {"kind": "component_cap",
                                    "components_after_filter": 2048,
                                    "component_cap": 64}
    labels = [f["label"] for f in found]
    assert labels == sorted(labels)
    assert labels[0] == 0  # (0,0,0) is occupied and is the global minimum
    for f in found:
        assert f["truncated"] is False  # record-level flag: content complete
