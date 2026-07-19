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
from swarm_hunter_lab.detector import MAX_SNAPSHOTS, _axis_interval


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


# ---- Amendment 2: total validator — never raises on JSON-decodable input -------

def test_validator_is_total_on_malformed_shapes():
    """schema.validate_records must return list[str] errors — never raise —
    for any JSON-decodable malformed input (Jack audit, Amendment 2)."""
    import copy
    good = list(detect_structures(fixtures.fx_stable()).records())
    refusal_art = list(detect_structures(fixtures.fx_malformed_provenance()).records())
    junk = (None, True, 7, 1.5, "text", [], ["x"], {"a": 1})

    def mutations():
        # top-level records value is not a sequence
        for top in (42, None, "x", {}, True):
            yield top
        # every expected header container replaced by each junk shape
        # (None is excluded for params/truncation — legitimately nullable)
        for key in ("detector", "run", "params", "counts", "truncation"):
            for value in junk:
                if value is None and key in ("params", "truncation"):
                    continue
                recs = copy.deepcopy(good)
                recs[0][key] = value
                yield recs
        # run sub-lists replaced by primitives/objects (Jack's examples)
        for sub, value in (("snapshot_ids", None), ("snapshot_ids", 7),
                           ("snapshot_ids", [None]), ("generations", 7),
                           ("generations", None), ("generations", ["x"])):
            recs = copy.deepcopy(good)
            recs[0]["run"][sub] = value
            yield recs
        # every expected finding container replaced by junk shapes
        for key in ("region", "state_counts", "density", "snapshot",
                    "observations", "persistence", "reasons"):
            for value in junk:
                recs = copy.deepcopy(good)
                recs[1][key] = value
                yield recs
        # region internals, mixed state_counts keys, reason shapes
        recs = copy.deepcopy(good)
        recs[1]["region"]["bbox_min"] = None
        yield recs
        recs = copy.deepcopy(good)
        recs[1]["region"]["wraps"] = [1, 2, 3]
        yield recs
        recs = copy.deepcopy(good)
        recs[1]["state_counts"] = {1: 27, "2": 0, "3": 0, "4": 0}
        yield recs
        recs = copy.deepcopy(good)
        recs[1]["observations"] = [5]
        yield recs
        recs = copy.deepcopy(good)
        recs[1]["reasons"] = [5]
        yield recs
        # refusal reason as unhashable/object values; unsafe snapshot_id
        for value in (["x"], {"r": 1}, None, 7):
            recs = copy.deepcopy(refusal_art)
            recs[1]["reason"] = value
            yield recs
        recs = copy.deepcopy(refusal_art)
        recs[1]["snapshot_id"] = 5
        yield recs
        # malformed later records mixed with valid ones
        yield [copy.deepcopy(good[0]), 42, copy.deepcopy(good[1]), "x", None]

    for case in mutations():
        errors = schema.validate_records(case)
        assert isinstance(errors, list) and errors
        assert all(isinstance(e, str) for e in errors)


def test_validator_still_accepts_all_valid_artifacts():
    for snaps, cfg in ((fixtures.fx_stable(), None),
                       (fixtures.fx_malformed_provenance(), None),
                       (fixtures.fx_checkerboard(),
                        DetectorConfig(min_component_size=1, component_cap=64)),
                       (fixtures.fx_single(),
                        DetectorConfig(op_budget_multiplier=1))):
        artifact = detect_structures(snaps, cfg) if cfg else detect_structures(snaps)
        assert schema.validate_records(list(artifact.records())) == []


# ---- LeanCTX malformed-artifact hardening (Jack audit disposition) --------------
# A JSON-decodable but non-conforming FindingsArtifact reaching leanctx_summary
# must fail as a deterministic fixed-message ValueError before any header/record
# indexing — never as a KeyError. The empty-artifact and invalid-run-label guards
# keep their existing messages and precedence; valid output stays byte-identical.

_LEANCTX_CONFORMANCE_MSG = "artifact is not a conforming findings artifact"


def _artifact_from_records(records):
    return FindingsArtifact(b"".join(schema.canonical_line(r) for r in records))


def test_leanctx_malformed_header_raises_fixed_valueerror_not_keyerror():
    # The exact minimal reproduction from the acceptance audit: JSON-decodable,
    # header present but missing "counts". Previously raised KeyError('counts').
    # pytest.raises(ValueError) also proves it is NOT a KeyError (KeyError is not
    # a ValueError subclass, so it would propagate and fail the test).
    with pytest.raises(ValueError, match=_LEANCTX_CONFORMANCE_MSG):
        leanctx_summary(FindingsArtifact(b'{"kind":"header"}\n'), "run-1")


def test_leanctx_rejects_representative_malformed_shapes():
    import copy
    good = list(detect_structures(fixtures.fx_single()).records())
    cases = [FindingsArtifact(b'{"kind":"header"}\n')]  # minimal, raw
    # first record is not a header
    recs = copy.deepcopy(good); recs[0]["kind"] = "finding"
    cases.append(_artifact_from_records(recs))
    # header carries a wrong schema id
    recs = copy.deepcopy(good); recs[0]["schema"] = "not-the-schema"
    cases.append(_artifact_from_records(recs))
    # a finding record is missing a required container
    recs = copy.deepcopy(good); del recs[1]["region"]
    cases.append(_artifact_from_records(recs))
    # header counts disagree with the actual records
    recs = copy.deepcopy(good); recs[0]["counts"]["findings"] = 999
    cases.append(_artifact_from_records(recs))
    for artifact in cases:
        with pytest.raises(ValueError, match=_LEANCTX_CONFORMANCE_MSG):
            leanctx_summary(artifact, "run-1")


def test_leanctx_empty_guard_precedes_conformance_check():
    # Requirement 3 + precedence: empty artifact keeps its exact prior message,
    # raised before the new conformance gate.
    with pytest.raises(ValueError, match="artifact contains no records"):
        leanctx_summary(FindingsArtifact(b""), "run-1")


def test_leanctx_run_label_guard_precedes_conformance_check():
    # Requirement 4 + precedence: an invalid run label wins over a malformed
    # artifact — the run-label guard still runs first with its own message.
    with pytest.raises(ValueError, match="run_label must satisfy the safe identifier grammar"):
        leanctx_summary(FindingsArtifact(b'{"kind":"header"}\n'), "Bad Label!")


def test_leanctx_accepts_all_valid_artifact_kinds():
    # Requirement 5: findings / refusal / component-cap-truncated /
    # budget-preflight-truncated artifacts all remain accepted.
    cases = (
        detect_structures(fixtures.fx_single()),
        detect_structures(fixtures.fx_malformed_provenance()),
        detect_structures(fixtures.fx_checkerboard(),
                          DetectorConfig(min_component_size=1, component_cap=64)),
        detect_structures(fixtures.fx_single(),
                          DetectorConfig(op_budget_multiplier=1)),
    )
    for artifact in cases:
        payload = leanctx_summary(artifact, "run-1")
        assert payload and b"leanctx-header" in payload


def test_leanctx_valid_output_byte_identical_after_hardening():
    # Requirement 6: repeated valid summaries stay byte-identical.
    artifact = detect_structures(fixtures.fx_stable())
    assert leanctx_summary(artifact, "run-1") == leanctx_summary(artifact, "run-1")


def test_leanctx_does_not_mutate_artifact_bytes():
    # Requirement 7: the canonical artifact bytes are never mutated (the gate
    # validates freshly decoded record copies, not the authoritative jsonl).
    artifact = detect_structures(fixtures.fx_single())
    before = bytes(artifact.jsonl)
    leanctx_summary(artifact, "run-1")
    assert artifact.jsonl == before


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


# ---------------------------------------------------------------------------
# S1 Amendment 3 — snapshot invocation ceiling (F1) + hook-free exact-container
# input boundary (F2). MAX_SNAPSHOTS=64 is public input policy: 1..64 is the
# accepted domain; >64, empty, non-list/tuple top-levels, and container
# subclasses with hostile hooks all yield the EXISTING structured invalid_input
# refusal (no new reason) BEFORE any caller-controlled len/iter/keys/get/subscript
# hook runs. Accepted-input bytes are unchanged (the fixture + determinism tests
# above still pass byte-for-byte). Hook-execution is proven zero via a counter
# whose hooks also raise if ever reached; no broad exception catching is used.
# ---------------------------------------------------------------------------


def _tiny_snap(i):
    states = fixtures.block(fixtures.empty_lattice(4), 1, 1, 1, 2, 2, 2)
    return fixtures.snapshot(states, f"amd3-s{i}", i + 1)


class _HookFlag:
    def __init__(self):
        self.n = 0


def test_amd3_exactly_64_snapshots_accepted():
    snaps = [_tiny_snap(i) for i in range(MAX_SNAPSHOTS)]  # 64
    header = detect_structures(snaps).records()[0]
    assert header["kind"] == "header"
    assert header["counts"]["refusals"] == 0
    assert header["run"]["snapshot_count"] == 64


def test_amd3_65_snapshots_refused_invalid_input_deterministically():
    snaps = [_tiny_snap(i) for i in range(MAX_SNAPSHOTS + 1)]  # 65
    _, refusal = refusal_of(snaps)
    assert refusal["reason"] == "invalid_input"
    assert detect_structures(snaps).jsonl == detect_structures(snaps).jsonl


def test_amd3_over_limit_decided_before_item_inspection():
    flag = _HookFlag()

    class _HostileFirst(dict):
        def keys(self):
            flag.n += 1
            raise AssertionError("keys() ran despite over-limit ceiling")

        def __getitem__(self, k):
            flag.n += 1
            raise AssertionError("__getitem__ ran despite over-limit ceiling")

    snaps = [_HostileFirst(_tiny_snap(0))] + [_tiny_snap(i)
                                              for i in range(1, MAX_SNAPSHOTS + 1)]
    assert len(snaps) == MAX_SNAPSHOTS + 1
    _, refusal = refusal_of(snaps)
    assert refusal["reason"] == "invalid_input"
    assert flag.n == 0  # ceiling refused before the hostile first item was touched


def test_amd3_invalid_config_wins_over_container_and_count():
    snaps = [_tiny_snap(i) for i in range(MAX_SNAPSHOTS + 1)]  # over-limit
    _, refusal = refusal_of(snaps, DetectorConfig(component_cap=0))
    assert refusal["reason"] == "invalid_config"


def test_amd3_exact_list_and_tuple_accepted():
    for ctor in (list, tuple):
        header = detect_structures(ctor([_tiny_snap(0)])).records()[0]
        assert header["kind"] == "header"


def test_amd3_list_tuple_subclass_hostile_hooks_refused_no_execution():
    flag = _HookFlag()

    class _HLenList(list):
        def __len__(self):
            flag.n += 1
            raise AssertionError("__len__ ran")

    class _HIterTuple(tuple):
        def __iter__(self):
            flag.n += 1
            raise AssertionError("__iter__ ran")

    for hostile in (_HLenList([_tiny_snap(0)]), _HIterTuple((_tiny_snap(0),))):
        _, refusal = refusal_of(hostile)
        assert refusal["reason"] == "invalid_input"
    assert flag.n == 0


def test_amd3_snapshot_dict_subclass_hostile_hooks_refused_no_execution():
    flag = _HookFlag()

    class _HKeys(dict):
        def keys(self):
            flag.n += 1
            raise AssertionError("keys() ran")

    class _HGet(dict):
        def __getitem__(self, k):
            flag.n += 1
            raise AssertionError("__getitem__ ran")

    for hostile in (_HKeys(_tiny_snap(0)), _HGet(_tiny_snap(0))):
        _, refusal = refusal_of([hostile])
        assert refusal["reason"] == "invalid_input"
    assert flag.n == 0


def test_amd3_nested_provenance_and_triple_subclass_refused_no_execution():
    flag = _HookFlag()

    class _HKeys(dict):
        def keys(self):
            flag.n += 1
            raise AssertionError("keys() ran")

    # provenance dict subclass -> invalid_provenance at its structured stage
    s = _tiny_snap(0)
    s["provenance"] = _HKeys(s["provenance"])
    _, refusal = refusal_of([s])
    assert refusal["reason"] == "invalid_provenance"
    # supplied sha256_triple dict subclass -> invalid_sha256_format at its stage
    s2 = _tiny_snap(0)
    s2["provenance"]["sha256_triple"] = _HKeys(s2["provenance"]["sha256_triple"])
    _, refusal2 = refusal_of([s2])
    assert refusal2["reason"] == "invalid_sha256_format"
    assert flag.n == 0


def test_amd3_ordinary_malformed_containers_keep_reasons_and_precedence():
    for bad in ("xx", {"a": 1}, (x for x in [1])):
        _, refusal = refusal_of(bad)
        assert refusal["reason"] == "invalid_input"
    _, refusal = refusal_of([])
    assert refusal["reason"] == "invalid_input"
    s = _tiny_snap(0)
    del s["provenance"]["sha256_triple"]
    _, refusal = refusal_of([s])
    assert refusal["reason"] == "invalid_provenance"


def test_amd3_no_input_mutation_or_io(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("file I/O attempted")
    monkeypatch.setattr(builtins, "open", boom)
    snaps = [_tiny_snap(i) for i in range(3)]
    before = [s["states"].copy() for s in snaps]
    detect_structures(snaps)
    for s, b in zip(snaps, before):
        assert np.array_equal(s["states"], b)


def test_amd3_valid_kinds_and_leanctx_still_accepted():
    cases = (
        detect_structures(fixtures.fx_single()),
        detect_structures(fixtures.fx_malformed_provenance()),
        detect_structures(fixtures.fx_checkerboard(),
                          DetectorConfig(min_component_size=1, component_cap=64)),
        detect_structures(fixtures.fx_single(), DetectorConfig(op_budget_multiplier=1)),
    )
    for art in cases:
        assert schema.validate_records(list(art.records())) == []
        assert b"leanctx-header" in leanctx_summary(art, "run-1")


# ---------------------------------------------------------------------------
# S1 Amendment 3 follow-up (Jack P2) — hostile KEYS stored inside an exact
# built-in dict, and a hostile provenance `source` scalar. The exact-container
# guards prove the container type but not the safety of keys/values inside it:
# set(dict.keys()) hashes stored keys, and `source != "synthetic"` compares the
# stored value, so an armed hostile `__hash__`/`__eq__` could fire. Every stored
# key is now proven an exact built-in str (via hash-free dict iteration) and the
# source is proven an exact str before those operations, all yielding the
# existing invalid_input refusal with the hostile hook executing ZERO times.
# ---------------------------------------------------------------------------


class _ArmedKey:
    """Hashable while disarmed (constant hash); once armed, both __hash__ and
    __eq__ raise. Inserted into a dict while benign, then armed — exactly the
    Jack-described attack. A boundary that hashes/compares it after arming
    trips the AssertionError; a correct boundary refuses via type() first."""
    armed = False

    def __hash__(self):
        if _ArmedKey.armed:
            raise AssertionError("__hash__ ran on an armed hostile key")
        return 0

    def __eq__(self, other):
        if _ArmedKey.armed:
            raise AssertionError("__eq__ ran on an armed hostile key")
        return self is other


class _ArmedEq:
    """Hashable scalar whose __eq__ raises once armed (a hostile `source`)."""
    armed = False

    def __eq__(self, other):
        if _ArmedEq.armed:
            raise AssertionError("__eq__ ran on an armed hostile source")
        return False

    def __hash__(self):
        return 0


def _amd3_tiny():
    return fixtures.snapshot(
        fixtures.block(fixtures.empty_lattice(4), 1, 1, 1, 2, 2, 2), "amd3b-s", 1)


def test_amd3_snapshot_dict_armed_hostile_key_refused_no_hash():
    key = _ArmedKey()
    item = dict(_amd3_tiny())
    item[key] = 1              # inserted while benign
    _ArmedKey.armed = True     # armed afterward
    try:
        _, refusal = refusal_of([item])
        assert refusal["reason"] == "invalid_input"
    finally:
        _ArmedKey.armed = False


def test_amd3_provenance_dict_armed_hostile_key_refused_no_hash():
    s = _amd3_tiny()
    key = _ArmedKey()
    s["provenance"] = dict(s["provenance"])
    s["provenance"][key] = 1
    _ArmedKey.armed = True
    try:
        _, refusal = refusal_of([s])
        assert refusal["reason"] == "invalid_input"
    finally:
        _ArmedKey.armed = False


def test_amd3_supplied_triple_dict_armed_hostile_key_refused_no_hash():
    s = _amd3_tiny()
    key = _ArmedKey()
    s["provenance"]["sha256_triple"] = dict(s["provenance"]["sha256_triple"])
    s["provenance"]["sha256_triple"][key] = 1
    _ArmedKey.armed = True
    try:
        _, refusal = refusal_of([s])
        assert refusal["reason"] == "invalid_input"
    finally:
        _ArmedKey.armed = False


def test_amd3_provenance_source_hostile_eq_refused_no_compare():
    s = _amd3_tiny()
    s["provenance"]["source"] = _ArmedEq()
    _ArmedEq.armed = True
    try:
        _, refusal = refusal_of([s])
        assert refusal["reason"] == "invalid_input"
    finally:
        _ArmedEq.armed = False


def test_amd3_str_subclass_key_and_source_refused():
    # adjacent audit cases: a str SUBCLASS key/source (which could carry hostile
    # __hash__/__eq__) is rejected by the exact-str type identity check.
    class _S(str):
        pass
    item = dict(_amd3_tiny())
    item[_S("extra")] = 1
    _, refusal = refusal_of([item])
    assert refusal["reason"] == "invalid_input"
    s = _amd3_tiny()
    s["provenance"]["source"] = _S("synthetic")
    _, refusal = refusal_of([s])
    assert refusal["reason"] == "invalid_input"


def test_amd3_valid_string_source_discriminator_preserved():
    # the source proof must not change the existing str-source behavior:
    # a valid non-synthetic string still yields s2_gated, synthetic still runs.
    s = _amd3_tiny()
    s["provenance"]["source"] = "snapshot"
    _, refusal = refusal_of([s])
    assert refusal["reason"] == "s2_gated"
    assert detect_structures([_amd3_tiny()]).records()[0]["kind"] == "header"
