"""Property, determinism, refusal-order, and resource tests for the frozen S1 contract."""

import builtins
import time
import tracemalloc
import warnings

import numpy as np
import pytest

from swarm_hunter_lab import (
    DetectorConfig, FindingsArtifact, compute_sha256_triple,
    detect_structures, fixtures, leanctx_summary, lp, schema,
)
from swarm_hunter_lab.detector import _axis_interval


def refusal_of(snaps, config=DetectorConfig()):
    records = detect_structures(snaps, config).records()
    assert [r["kind"] for r in records] == ["header", "refusal"]
    return records[0], records[1]


# ---- determinism and identity ------------------------------------------------

def test_replay_byte_identity():
    a = detect_structures(fixtures.fx_stable())
    b = detect_structures(fixtures.fx_stable())
    assert a.jsonl == b.jsonl


def test_stable_ids_across_runs():
    f1 = detect_structures(fixtures.fx_single()).records()[1]
    f2 = detect_structures(fixtures.fx_single()).records()[1]
    assert (f1["finding_id"], f1["chain_id"], f1["component_id"]) == \
        (f2["finding_id"], f2["chain_id"], f2["component_id"])


def test_torus_translation_invariance():
    base = detect_structures(fixtures.fx_single()).records()[1]
    shifted_states = fixtures.block(fixtures.empty_lattice(), 6, 2, 2, 3, 3, 3)
    shifted = detect_structures(
        [fixtures.snapshot(shifted_states, "fx-shift", 1)]).records()[1]
    assert shifted["cell_count"] == base["cell_count"]
    assert shifted["state_counts"] == base["state_counts"]
    assert shifted["density"] == base["density"]
    for axis in range(3):
        base_len = base["region"]["bbox_max"][axis] - base["region"]["bbox_min"][axis]
        lo, hi = shifted["region"]["bbox_min"][axis], shifted["region"]["bbox_max"][axis]
        shifted_len = (hi - lo) % 8
        assert shifted_len == base_len % 8
    assert shifted["region"]["wraps"] == [True, False, False]
    assert shifted["region"]["bbox_min"] != base["region"]["bbox_min"]
    assert shifted["finding_id"] != base["finding_id"]


def test_axis_interval_worked_examples():
    assert _axis_interval([2, 3, 4], 8) == (2, 4, False)
    assert _axis_interval([6, 7, 0, 1], 8) == (6, 1, True)
    assert _axis_interval([0, 4], 8) == (0, 4, False)   # tie -> smallest bbox_min
    assert _axis_interval([7, 0, 1], 8) == (7, 1, True)
    assert _axis_interval(list(range(8)), 8) == (0, 7, False)  # full axis
    assert _axis_interval([3], 8) == (3, 3, False)      # singleton


def test_six_face_not_diagonal_connectivity():
    states = fixtures.empty_lattice()
    states[0, 0, 0] = 1
    states[0, 1, 1] = 1  # edge-diagonal neighbour
    records = detect_structures(
        [fixtures.snapshot(states, "fx-diag", 1)],
        DetectorConfig(min_component_size=1)).records()
    assert len([r for r in records if r["kind"] == "finding"]) == 2


def test_lp_kills_delimiter_collisions():
    assert lp("ab") + lp("c") != lp("a") + lp("bc")


# ---- configuration validation ------------------------------------------------

def test_bool_config_rejected():
    header, refusal = refusal_of(fixtures.fx_single(),
                                 DetectorConfig(min_component_size=True))
    assert refusal["reason"] == "invalid_config"
    assert header["params"] is None  # frozen early-failure header shape


def test_config_subclass_rejected():
    class Sneaky(DetectorConfig):
        pass
    _, refusal = refusal_of(fixtures.fx_single(), Sneaky())
    assert refusal["reason"] == "invalid_config"


def test_unknown_config_field_is_construction_error():
    with pytest.raises(TypeError):
        DetectorConfig(surprise=1)


def test_config_bounds():
    for bad in (DetectorConfig(component_cap=0),
                DetectorConfig(component_cap=4097),
                DetectorConfig(op_budget_multiplier=1025),
                DetectorConfig(min_component_size=0)):
        _, refusal = refusal_of(fixtures.fx_single(), bad)
        assert refusal["reason"] == "invalid_config"


def test_min_size_versus_volume():
    _, refusal = refusal_of(fixtures.fx_single(),
                            DetectorConfig(min_component_size=513))
    assert refusal["reason"] == "invalid_config_for_volume"


# ---- input validation and refusal order ---------------------------------------

def test_unsafe_and_overlong_identifiers():
    for bad_id in ("Bad!", "UPPER", "x" * 65, ""):
        snap = fixtures.fx_single()[0]
        snap["provenance"]["snapshot_id"] = bad_id
        snap["provenance"]["sha256_triple"] = compute_sha256_triple(snap["states"])
        _, refusal = refusal_of([snap])
        assert refusal["reason"] == "invalid_identifier"


def test_caller_hash_mismatch():
    snap = fixtures.fx_single()[0]
    good = snap["provenance"]["sha256_triple"]["states"]
    snap["provenance"]["sha256_triple"]["states"] = \
        ("0" if good[0] != "0" else "1") + good[1:]
    _, refusal = refusal_of([snap])
    assert refusal["reason"] == "provenance_hash_mismatch"
    assert refusal["snapshot_id"] == "fx-single"


def test_first_failure_order_is_frozen():
    # identifier grammar (stage 3b) precedes states validation (stage 3d):
    snap = fixtures.fx_single()[0]
    snap["provenance"]["snapshot_id"] = "BAD"
    snap["states"] = snap["states"].astype(np.float32)  # also invalid
    _, refusal = refusal_of([snap])
    assert refusal["reason"] == "invalid_identifier"
    # with a valid identifier, the dtype defect surfaces instead:
    snap2 = fixtures.fx_single()[0]
    snap2["states"] = snap2["states"].astype(np.float32)
    _, refusal2 = refusal_of([snap2])
    assert refusal2["reason"] == "invalid_input"


def test_s2_gate_and_cross_snapshot_rules():
    snap = fixtures.fx_single()[0]
    snap["provenance"]["source"] = "snapshot"
    _, refusal = refusal_of([snap])
    assert refusal["reason"] == "s2_gated"

    dup = fixtures.fx_stable()
    dup[1]["provenance"]["snapshot_id"] = dup[0]["provenance"]["snapshot_id"]
    _, refusal = refusal_of(dup)
    assert refusal["reason"] == "duplicate_snapshot_id"

    nonmono = fixtures.fx_stable()
    nonmono[2]["provenance"]["generation"] = 1
    _, refusal = refusal_of(nonmono)
    assert refusal["reason"] == "nonmonotonic_generation"


def test_nan_optional_data_refused():
    states = fixtures.block(fixtures.empty_lattice(), 1, 1, 1, 2, 2, 2)
    memory = np.zeros((8, 8, 8, 8), dtype=np.float32)
    memory[0, 0, 0, 0] = np.nan
    snap = fixtures.snapshot(states, "fx-nan", 1, memory=memory)
    _, refusal = refusal_of([snap])
    assert refusal["reason"] == "invalid_optional_data"


# ---- truncation semantics ------------------------------------------------------

def test_budget_preflight_header_only():
    records = detect_structures(fixtures.fx_single(),
                                DetectorConfig(op_budget_multiplier=1)).records()
    assert len(records) == 1
    header = records[0]
    assert header["truncated"] is True and header["empty"] is True
    assert header["truncation"] == {"kind": "op_budget_preflight",
                                    "required_ops": 512 + 3 * 27,
                                    "op_budget": 512}
    assert header["counts"]["refusals"] == 0  # a truncation, not a refusal


# ---- artifact immutability, provenance, closure --------------------------------

def test_artifact_deep_immutability():
    artifact = detect_structures(fixtures.fx_single())
    original = bytes(artifact.jsonl)
    records = artifact.records()
    records[0]["counts"]["findings"] = 999
    records[1]["state_counts"]["1"] = 0
    assert artifact.jsonl == original
    fresh = artifact.records()
    assert fresh[0]["counts"]["findings"] == 1
    assert fresh[1]["state_counts"]["1"] == 27


def test_multi_snapshot_observation_completeness():
    finding = detect_structures(fixtures.fx_stable()).records()[1]
    assert len(finding["observations"]) == 3
    for obs in finding["observations"]:
        assert set(obs.keys()) == schema.OBSERVATION_KEYS
        assert set(obs["sha256_triple"].keys()) == schema.SHA256_TRIPLE_KEYS
        for digest in obs["sha256_triple"].values():
            assert schema.is_hex64(digest)


def test_inputs_never_mutated():
    snaps = fixtures.fx_single()
    before = snaps[0]["states"].copy()
    triple_before = compute_sha256_triple(snaps[0]["states"])
    detect_structures(snaps)
    assert np.array_equal(snaps[0]["states"], before)
    assert compute_sha256_triple(snaps[0]["states"]) == triple_before


def test_detector_performs_no_file_io(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("detector attempted file I/O")
    monkeypatch.setattr(builtins, "open", boom)
    artifact = detect_structures(fixtures.fx_single())
    assert artifact.records()[0]["counts"]["findings"] == 1


def test_forbidden_content_closure_via_public_validator():
    for snaps in (fixtures.fx_single(), fixtures.fx_stable(),
                  fixtures.fx_malformed_provenance()):
        records = list(detect_structures(snaps).records())
        assert schema.validate_records(records) == []


def test_leanctx_summary_bounds_and_determinism():
    artifact = detect_structures(fixtures.fx_checkerboard(),
                                 DetectorConfig(min_component_size=1,
                                                component_cap=300))
    payload1 = leanctx_summary(artifact, "audit-run-1")
    payload2 = leanctx_summary(artifact, "audit-run-1")
    assert payload1 == payload2
    lines = payload1.decode("utf-8").splitlines()
    assert len(lines) <= 200 and len(payload1) <= 64 * 1024
    with pytest.raises(ValueError):
        leanctx_summary(artifact, "Bad Label!")


# ---- Amendment 1 regressions: fullmatch identifiers, robust validator ----------

def test_trailing_newline_identifiers_refused():
    for field, value in (("snapshot_id", "fx-nl\n"),
                         ("channel_layout_version", "v1\n")):
        snap = fixtures.fx_single()[0]
        snap["provenance"][field] = value
        _, refusal = refusal_of([snap])
        assert refusal["reason"] == "invalid_identifier"


def test_non_string_identifier_refused():
    snap = fixtures.fx_single()[0]
    snap["provenance"]["snapshot_id"] = 123
    _, refusal = refusal_of([snap])
    assert refusal["reason"] == "invalid_identifier"


def test_trailing_newline_hex_refused():
    snap = fixtures.fx_single()[0]
    good = snap["provenance"]["sha256_triple"]["states"]
    snap["provenance"]["sha256_triple"]["states"] = good + "\n"
    _, refusal = refusal_of([snap])
    assert refusal["reason"] == "invalid_sha256_format"


def test_safe_string_helpers_are_fullmatch_and_exact_str():
    assert schema.is_safe_id("run-1") and not schema.is_safe_id("run-1\n")
    assert not schema.is_safe_id(123) and not schema.is_safe_id(None)
    hex64 = "a" * 64
    assert schema.is_hex64(hex64) and not schema.is_hex64(hex64 + "\n")
    assert not schema.is_hex64(b"a" * 64)
    hex16 = "b" * 16
    assert schema.is_hex16(hex16) and not schema.is_hex16(hex16 + "\n")


def test_leanctx_run_label_trailing_newline_rejected():
    artifact = detect_structures(fixtures.fx_single())
    with pytest.raises(ValueError):
        leanctx_summary(artifact, "run-1\n")


def test_leanctx_empty_artifact_rejected():
    with pytest.raises(ValueError, match="artifact contains no records"):
        leanctx_summary(FindingsArtifact(b""), "run-1")


def test_validator_rejects_non_object_records_without_raising():
    good = list(detect_structures(fixtures.fx_single()).records())
    header, finding = good[0], good[1]
    for bad in ([[]], ["text"], [header, []], [header, "text"],
                [header, finding, 42, "x"]):
        errors = schema.validate_records(bad)
        assert errors and isinstance(errors, list)


def test_validator_rejects_malformed_truncation_counters():
    import copy
    capped = list(detect_structures(
        fixtures.fx_checkerboard(),
        DetectorConfig(min_component_size=1, component_cap=64)).records())
    budget = list(detect_structures(
        fixtures.fx_single(), DetectorConfig(op_budget_multiplier=1)).records())
    mutations = {
        "capped": (capped, "truncation", (
            lambda t: t.__setitem__("component_cap", -1),
            lambda t: t.__setitem__("components_after_filter", True),
            lambda t: t.__setitem__("component_cap", "64"),
            lambda t: t.__setitem__("components_after_filter", 1.5),
            lambda t: t.pop("component_cap"),
            lambda t: t.__setitem__("extra", 1),
        )),
        "budget": (budget, "truncation", (
            lambda t: t.__setitem__("required_ops", -5),
            lambda t: t.__setitem__("op_budget", False),
            lambda t: t.__setitem__("required_ops", "593"),
            lambda t: t.pop("op_budget"),
        )),
    }
    for base, key, mutators in mutations.values():
        for mutate in mutators:
            records = copy.deepcopy(base)
            mutate(records[0][key])
            errors = schema.validate_records(records)
            assert errors and isinstance(errors, list)


# ---- maximum supported case (measured observations, not promises) ---------------

def test_max_lattice_64_cubed_measured():
    states = np.zeros((64, 64, 64), dtype=np.uint8)
    fixtures.block(states, 2, 2, 2, 4, 4, 4)
    fixtures.block(states, 40, 40, 40, 4, 4, 4, state=2)
    snap = fixtures.snapshot(states, "fx-max", 1)
    tracemalloc.start()
    start = time.perf_counter()
    artifact = detect_structures([snap])
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    found = [r for r in artifact.records() if r["kind"] == "finding"]
    assert len(found) == 2
    assert found[0]["state_counts"] == {"1": 64, "2": 0, "3": 0, "4": 0}
    assert found[1]["state_counts"] == {"1": 0, "2": 64, "3": 0, "4": 0}
    warnings.warn(
        f"S1-64cubed-observation: runtime={elapsed:.3f}s "
        f"tracemalloc_peak={peak / 1e6:.1f}MB (observation, not a promise)")
