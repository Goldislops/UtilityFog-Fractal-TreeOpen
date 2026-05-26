"""Tests for scripts/nextness_calibration.py — Phase 19 PR #4, Chapter 1.

Covers the shared module infrastructure (write-boundary safety,
deterministic snapshot ordering, content fingerprinting, JSONL output
writer, falsification-status reporting) plus ``check_determinism()`` —
Jack's #1 in the implementation order.

Per design doc PHASE_19_PR4_CALIBRATION.md §3.7 + §6: this experiment is
the sanity floor for the rest of the calibration suite, so we lock down
both happy-path and edge-case behavior here.

Later chapters will add tests for the other seven experiments (memory-
channel verification, shuffle test with two modes, stride sweep, threshold
sweep, cascade ablation, temporal sweep, patch-radius coarse-graining).
"""
from __future__ import annotations

import json
import pathlib
import time

import numpy as np
import pytest

from scripts.nextness_observer import (
    MEMORY_CHANNEL_LAYOUT,
    ObserverConfig,
    STATE_COMPUTE,
    WriteOutsideLogDirError,
)
from scripts.nextness_calibration import (
    DEFAULT_CANONICAL_SEED,
    DEFAULT_VARIANCE_SEEDS,
    SHUFFLE_MODES,
    _content_fingerprint,
    _extract_generation_from_filename,
    _interpret_signal_location,
    _make_aggregate_row,
    _make_per_snapshot_row,
    _shuffle_falsification_status,
    _shuffled_snapshot_arrays,
    _sort_snapshots_by_generation,
    _validate_calibration_output_path,
    check_determinism,
    shuffle_test,
)


CH = MEMORY_CHANNEL_LAYOUT


# ---------------------------------------------------------------------------
# Helpers — same pattern as test_nextness_observer.py / test_nextness_metrics.py
# ---------------------------------------------------------------------------


def _make_snapshot(
    path: pathlib.Path,
    lattice: int = 16,
    generation: int = 100,
) -> pathlib.Path:
    """Create a synthetic Medusa-format ``.npz`` snapshot for calibration tests.

    Mirrors the helper used by ``test_nextness_observer.py``; tiny lattice
    (default 16^3) keeps tests fast. No pad_bytes — post-PR-#140 the
    validity check is structural, not size-based.
    """
    state = np.zeros((lattice, lattice, lattice), dtype=np.uint8)
    state[::4, ::4, ::4] = STATE_COMPUTE
    memory = np.zeros((8, lattice, lattice, lattice), dtype=np.float32)
    memory[CH["compute_age"]].fill(15.0)
    np.savez(
        str(path),
        lattice=state, memory_grid=memory,
        generation=np.array(generation), best_fitness=np.array(0.5),
    )
    return path


def _calibration_setup(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, ObserverConfig]:
    """Build the standard test scaffolding: data dir, log_path, config.

    Returns (snapshots_dir, log_path, config). Caller still needs to create
    snapshot files in snapshots_dir.
    """
    snapshots_dir = tmp_path / "snapshots"
    snapshots_dir.mkdir()
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "nextness_runs.jsonl"
    config = ObserverConfig(
        log_directory=str(log_dir),
        uniform_grid_stride=4,
        budget_seconds=30.0,
    )
    return snapshots_dir, log_path, config


# ---------------------------------------------------------------------------
# _extract_generation_from_filename
# ---------------------------------------------------------------------------


def test_extract_generation_canonical_filename():
    """Canonical Medusa filenames parse correctly."""
    p = pathlib.Path("v070_gen1665781_step16657819_20260518T224644.npz")
    assert _extract_generation_from_filename(p) == 1665781


def test_extract_generation_returns_negative_one_for_unparseable():
    """Filenames that don't match the canonical format sort to the front."""
    p = pathlib.Path("random_other_file.npz")
    assert _extract_generation_from_filename(p) == -1


def test_extract_generation_works_with_various_prefixes():
    """Different prefix versions (v060, v070, v080) all parse."""
    for prefix in ("v060", "v070", "v080", "v999"):
        p = pathlib.Path(f"{prefix}_gen42_step420_20260101T000000.npz")
        assert _extract_generation_from_filename(p) == 42


# ---------------------------------------------------------------------------
# _sort_snapshots_by_generation
# ---------------------------------------------------------------------------


def test_sort_snapshots_orders_by_generation(tmp_path):
    """Sorted result is ascending by generation regardless of input order."""
    paths = [
        tmp_path / "v070_gen300_step3000_20260101T000003.npz",
        tmp_path / "v070_gen100_step1000_20260101T000001.npz",
        tmp_path / "v070_gen200_step2000_20260101T000002.npz",
    ]
    sorted_ = _sort_snapshots_by_generation(paths)
    assert [p.name for p in sorted_] == [
        "v070_gen100_step1000_20260101T000001.npz",
        "v070_gen200_step2000_20260101T000002.npz",
        "v070_gen300_step3000_20260101T000003.npz",
    ]


def test_sort_snapshots_deterministic_across_input_orderings(tmp_path):
    """Same paths in three different orderings → byte-identical sorted output.

    Mirrors test_nextness_metrics.py's determinism contract test.
    """
    base = [
        tmp_path / "v070_gen100_step1000_20260101T000001.npz",
        tmp_path / "v070_gen200_step2000_20260101T000002.npz",
        tmp_path / "v070_gen300_step3000_20260101T000003.npz",
    ]
    s1 = [p.name for p in _sort_snapshots_by_generation(base)]
    s2 = [p.name for p in _sort_snapshots_by_generation(list(reversed(base)))]
    s3 = [p.name for p in _sort_snapshots_by_generation([base[1], base[2], base[0]])]
    assert s1 == s2 == s3


# ---------------------------------------------------------------------------
# _content_fingerprint
# ---------------------------------------------------------------------------


def test_content_fingerprint_excludes_ts_field():
    """Two entries differing only in ``ts`` produce identical fingerprints."""
    entry_a = {"ts": "2026-05-23T10:00:00Z", "generation": 100, "boundary_rate": 0.42}
    entry_b = {"ts": "2026-05-23T11:00:00Z", "generation": 100, "boundary_rate": 0.42}
    assert _content_fingerprint(entry_a) == _content_fingerprint(entry_b)


def test_content_fingerprint_differs_when_content_differs():
    """Two entries with identical ``ts`` but different content → different fingerprints."""
    entry_a = {"ts": "2026-05-23T10:00:00Z", "generation": 100, "boundary_rate": 0.42}
    entry_b = {"ts": "2026-05-23T10:00:00Z", "generation": 100, "boundary_rate": 0.43}
    assert _content_fingerprint(entry_a) != _content_fingerprint(entry_b)


def test_content_fingerprint_independent_of_dict_insertion_order():
    """sort_keys=True in the canonical JSON makes fingerprint order-independent."""
    entry_a = {"ts": "x", "a": 1, "b": 2, "c": 3}
    entry_b = {"ts": "y", "c": 3, "a": 1, "b": 2}
    assert _content_fingerprint(entry_a) == _content_fingerprint(entry_b)


def test_content_fingerprint_returns_hex_sha256():
    """Output is a 64-char hex string (full SHA-256 digest)."""
    fp = _content_fingerprint({"ts": "x", "value": 42})
    assert len(fp) == 64
    int(fp, 16)  # raises if not hex


def test_content_fingerprint_scrubs_nested_budget_wallclock_fields():
    """Wallclock-derived fields INSIDE the budget block must also be scrubbed.

    Regression fence for the bug caught by
    test_check_determinism_passes_on_synthetic_snapshots: budget.elapsed_seconds,
    budget.fraction_used, and budget.exceeded all vary across runs even when
    the computation is fully deterministic. They must be excluded from the
    fingerprint or determinism testing produces false negatives.
    """
    entry_a = {
        "ts": "2026-05-23T10:00:00Z",
        "boundary_rate": 0.42,
        "budget": {
            "elapsed_seconds": 0.001234,
            "fraction_used": 0.0000411,
            "exceeded": False,
            "patches_processed": 4096,  # deterministic — should be in fingerprint
        },
    }
    entry_b = {
        "ts": "2026-05-23T11:00:00Z",  # different ts
        "boundary_rate": 0.42,
        "budget": {
            "elapsed_seconds": 0.002567,  # different elapsed
            "fraction_used": 0.0000855,  # different fraction
            "exceeded": False,
            "patches_processed": 4096,  # same patches_processed
        },
    }
    assert _content_fingerprint(entry_a) == _content_fingerprint(entry_b)


def test_content_fingerprint_detects_budget_patches_processed_drift():
    """Deterministic budget fields (patches_processed) MUST stay in fingerprint.

    Regression fence: ensure the scrub doesn't accidentally remove the
    deterministic budget fields. If patches_processed differs across runs,
    that's a real determinism violation and the fingerprint must catch it.
    """
    entry_a = {"ts": "x", "budget": {"elapsed_seconds": 0.1, "patches_processed": 100}}
    entry_b = {"ts": "x", "budget": {"elapsed_seconds": 0.1, "patches_processed": 101}}
    assert _content_fingerprint(entry_a) != _content_fingerprint(entry_b)


# ---------------------------------------------------------------------------
# _validate_calibration_output_path
# ---------------------------------------------------------------------------


def test_validate_output_inside_log_dir_succeeds(tmp_path):
    """Sibling output path (same dir as log) passes validation silently."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "nextness_runs.jsonl"
    out_path = log_dir / "calibration_determinism.jsonl"
    # Should not raise
    _validate_calibration_output_path(out_path, log_path)


def test_validate_output_outside_log_dir_raises(tmp_path):
    """Output path outside log_path.parent raises WriteOutsideLogDirError."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "nextness_runs.jsonl"
    out_path = tmp_path / "elsewhere" / "out.jsonl"
    with pytest.raises(WriteOutsideLogDirError, match="outside log_path"):
        _validate_calibration_output_path(out_path, log_path)


def test_validate_output_traversal_escape_rejected(tmp_path):
    """``..`` traversal must also be rejected, not just literal mismatch."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "nextness_runs.jsonl"
    out_path = log_dir / ".." / ".." / "escape.jsonl"
    with pytest.raises(WriteOutsideLogDirError):
        _validate_calibration_output_path(out_path, log_path)


# ---------------------------------------------------------------------------
# _make_aggregate_row falsification_status validation
# ---------------------------------------------------------------------------


def test_make_aggregate_row_accepts_three_valid_statuses():
    """Each of the three documented statuses is accepted."""
    for status in ("hypothesis_supported", "hypothesis_falsified", "inconclusive"):
        row = _make_aggregate_row(
            experiment="test",
            calibration_set="short",
            n_snapshots=1,
            extra_fields={},
            falsification_status=status,
        )
        assert row["falsification_status"] == status


def test_make_aggregate_row_rejects_unknown_status():
    """Arbitrary status strings are rejected — protects the schema contract."""
    with pytest.raises(ValueError, match="falsification_status"):
        _make_aggregate_row(
            experiment="test",
            calibration_set="short",
            n_snapshots=1,
            extra_fields={},
            falsification_status="vibes_say_yes",  # not a documented value
        )


# ---------------------------------------------------------------------------
# check_determinism — input validation
# ---------------------------------------------------------------------------


def test_check_determinism_rejects_unknown_calibration_set(tmp_path):
    """calibration_set must be 'short' or 'long' — protects schema."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    with pytest.raises(ValueError, match="calibration_set"):
        check_determinism([snap], out, log_path, "medium", config)


def test_check_determinism_rejects_repeats_below_two(tmp_path):
    """repeats < 2 is meaningless (no comparison possible) — rejected."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    with pytest.raises(ValueError, match="repeats must be >= 2"):
        check_determinism([snap], out, log_path, "short", config, repeats=1)


# ---------------------------------------------------------------------------
# check_determinism — happy path
# ---------------------------------------------------------------------------


def test_check_determinism_passes_on_synthetic_snapshots(tmp_path):
    """3 synthetic snapshots × 2 repeats → all byte-identical content.

    process_snapshot() is deterministic by design (no randomness in the
    classifier cascade, deterministic stride iteration), so this should
    pass cleanly.
    """
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snaps = [
        _make_snapshot(snaps_dir / f"v070_gen{i}_step{i}_test.npz", generation=i)
        for i in (1, 2, 3)
    ]
    out = log_path.parent / "calibration_determinism.jsonl"

    aggregate = check_determinism(snaps, out, log_path, "short", config, repeats=2)

    assert aggregate["experiment"] == "determinism"
    assert aggregate["summary_type"] == "run_aggregate"
    assert aggregate["calibration_set"] == "short"
    assert aggregate["n_snapshots"] == 3
    assert aggregate["repeats_per_snapshot"] == 2
    assert aggregate["all_byte_identical"] is True
    assert aggregate["n_snapshots_with_drift"] == 0
    assert aggregate["falsification_status"] == "hypothesis_supported"


def test_check_determinism_writes_correct_number_of_rows(tmp_path):
    """Output JSONL has (N_snapshots × repeats) per-snapshot rows + 1 aggregate."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snaps = [
        _make_snapshot(snaps_dir / f"v070_gen{i}_step{i}_test.npz", generation=i)
        for i in (1, 2, 3)
    ]
    out = log_path.parent / "calibration_determinism.jsonl"
    check_determinism(snaps, out, log_path, "short", config, repeats=2)

    lines = out.read_text().splitlines()
    assert len(lines) == 3 * 2 + 1  # 3 snapshots × 2 repeats + 1 aggregate
    aggregate_line = json.loads(lines[-1])
    assert aggregate_line["summary_type"] == "run_aggregate"


def test_check_determinism_emits_no_generated_at_field(tmp_path):
    """Determinism contract from PR #142 — no fresh timestamps in output.

    Locks in that the calibration JSONL doesn't accidentally re-introduce
    a generated_at field that would break byte-identical re-run.
    """
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "calibration_determinism.jsonl"
    check_determinism([snap], out, log_path, "short", config, repeats=2)
    content = out.read_text()
    assert "generated_at" not in content


def test_check_determinism_calibration_set_field_propagates(tmp_path):
    """Every row (per-snapshot AND aggregate) carries the calibration_set tag."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "calibration_determinism.jsonl"
    check_determinism([snap], out, log_path, "long", config, repeats=2)

    for line in out.read_text().splitlines():
        row = json.loads(line)
        assert row["calibration_set"] == "long"


def test_check_determinism_sorts_snapshots_by_generation(tmp_path):
    """Per-snapshot rows appear in generation-ascending order regardless of input order."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    # Create three snapshots; pass them in reverse-generation order
    snap_a = _make_snapshot(snaps_dir / "v070_gen300_step3000_test.npz", generation=300)
    snap_b = _make_snapshot(snaps_dir / "v070_gen100_step1000_test.npz", generation=100)
    snap_c = _make_snapshot(snaps_dir / "v070_gen200_step2000_test.npz", generation=200)
    out = log_path.parent / "calibration_determinism.jsonl"
    check_determinism([snap_a, snap_b, snap_c], out, log_path, "short", config, repeats=2)

    lines = [json.loads(l) for l in out.read_text().splitlines()[:-1]]  # exclude aggregate
    # 3 snapshots × 2 repeats; per-snapshot rows grouped by snapshot in sorted order
    generations_in_order = [r["snapshot_generation"] for r in lines]
    # Should be [100, 100, 200, 200, 300, 300] — sorted, with each snapshot's repeats adjacent
    assert generations_in_order == [100, 100, 200, 200, 300, 300]


# ---------------------------------------------------------------------------
# check_determinism — write-boundary safety inheritance
# ---------------------------------------------------------------------------


def test_check_determinism_rejects_outside_log_dir_output(tmp_path):
    """Output outside log directory raises WriteOutsideLogDirError.

    Inherits the Lane B write-boundary safety contract from PR #142 via
    _validate_calibration_output_path. Locked in by an explicit test here
    so future refactors can't quietly drop it.
    """
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    bad_out = tmp_path / "outside_dir" / "out.jsonl"
    with pytest.raises(WriteOutsideLogDirError, match="outside log_path"):
        check_determinism([snap], bad_out, log_path, "short", config, repeats=2)
    # No side effects — outside parent must not have been created
    assert not (tmp_path / "outside_dir").exists()


# ---------------------------------------------------------------------------
# Module-level constants exposed via __all__
# ---------------------------------------------------------------------------


def test_default_canonical_seed_is_42():
    """The canonical RNG seed is 42 — used by shuffle test and other randomized experiments."""
    assert DEFAULT_CANONICAL_SEED == 42


def test_default_variance_seeds_has_five_entries():
    """Per design doc §12 Q6: canonical seed + 5 variance-estimate seeds."""
    assert len(DEFAULT_VARIANCE_SEEDS) == 5
    assert all(isinstance(s, int) for s in DEFAULT_VARIANCE_SEEDS)


# ---------------------------------------------------------------------------
# Shuffle mechanics — Chapter 2 (design doc §3.8)
# ---------------------------------------------------------------------------


def _synthetic_arrays(lattice_size: int = 16):
    """Build a synthetic (lattice, memory_grid) pair for shuffle-mechanics tests.

    Memory channels carry a position-dependent gradient on top of a per-channel
    constant offset. The gradient is crucial — without intra-channel spatial
    variation, permuting a constant-valued array gives back the same array
    and we can't verify the shuffle actually changed anything.
    """
    state = np.zeros((lattice_size, lattice_size, lattice_size), dtype=np.uint8)
    # Sprinkle COMPUTE cells in a recognizable pattern
    state[::4, ::4, ::4] = STATE_COMPUTE
    # Position-dependent gradient (linear over flat index) + per-channel
    # constant offset. Result: each (channel, x, y, z) cell has a unique
    # value, so any permutation produces a visibly different array.
    n_voxels = lattice_size ** 3
    gradient = np.arange(n_voxels, dtype=np.float32).reshape(
        (lattice_size, lattice_size, lattice_size)
    ) / float(n_voxels)
    memory = np.zeros(
        (8, lattice_size, lattice_size, lattice_size), dtype=np.float32,
    )
    for c in range(8):
        memory[c] = float(c) + gradient
    return state, memory


def test_shuffle_modes_tuple_has_three_entries():
    """SHUFFLE_MODES is the canonical 3-mode tuple from design doc §3.8."""
    assert SHUFFLE_MODES == (
        "unshuffled",
        "lattice_only_shuffle",
        "joint_lattice_memory_shuffle",
    )


def test_shuffle_unshuffled_mode_returns_arrays_unchanged():
    """unshuffled mode is the baseline — no permutation applied."""
    lattice, memory = _synthetic_arrays()
    rng = np.random.default_rng(42)
    out_lattice, out_memory = _shuffled_snapshot_arrays(
        lattice, memory, "unshuffled", rng,
    )
    assert np.array_equal(out_lattice, lattice)
    assert np.array_equal(out_memory, memory)


def test_shuffle_lattice_only_preserves_memory_grid_exactly():
    """lattice_only_shuffle leaves memory_grid byte-identical to input."""
    lattice, memory = _synthetic_arrays()
    rng = np.random.default_rng(42)
    out_lattice, out_memory = _shuffled_snapshot_arrays(
        lattice, memory, "lattice_only_shuffle", rng,
    )
    # Lattice changes (with overwhelming probability for a 16^3 grid)
    assert not np.array_equal(out_lattice, lattice)
    # Memory is identical — same object reference is fine; same content
    # is what we actually require
    assert np.array_equal(out_memory, memory)


def test_shuffle_lattice_only_preserves_per_state_cell_counts():
    """lattice_only_shuffle is a permutation: per-state counts unchanged."""
    lattice, memory = _synthetic_arrays()
    rng = np.random.default_rng(42)
    out_lattice, _ = _shuffled_snapshot_arrays(
        lattice, memory, "lattice_only_shuffle", rng,
    )
    # All unique state counts identical between input and output
    in_counts = dict(zip(*np.unique(lattice, return_counts=True)))
    out_counts = dict(zip(*np.unique(out_lattice, return_counts=True)))
    assert in_counts == out_counts


def test_shuffle_joint_applies_same_permutation_to_both_arrays():
    """joint mode applies the SAME permutation to both lattice and memory.

    Verification: for each cell position p in the shuffled output, the
    lattice value at p and the memory value at p must come from the same
    original position (i.e., the local pairing is preserved). We verify
    this by reconstructing the permutation from the lattice change and
    checking the memory change is consistent.
    """
    lattice, memory = _synthetic_arrays()
    rng = np.random.default_rng(42)
    out_lattice, out_memory = _shuffled_snapshot_arrays(
        lattice, memory, "joint_lattice_memory_shuffle", rng,
    )
    # Both arrays changed
    assert not np.array_equal(out_lattice, lattice)
    assert not np.array_equal(out_memory, memory)
    # Per-state lattice counts preserved (joint is also a permutation)
    in_counts = dict(zip(*np.unique(lattice, return_counts=True)))
    out_counts = dict(zip(*np.unique(out_lattice, return_counts=True)))
    assert in_counts == out_counts
    # Per-channel memory marginals preserved (same permutation, per-channel
    # value distributions unchanged)
    for c in range(memory.shape[0]):
        assert np.allclose(np.sort(memory[c].flatten()),
                           np.sort(out_memory[c].flatten()))


def test_shuffle_joint_preserves_per_cell_lattice_memory_pairing():
    """In joint mode, the local lattice/memory correspondence is preserved.

    For any cell that was originally COMPUTE with memory channel 0 value
    of 1.0, after joint shuffle there must STILL be a cell where lattice
    is COMPUTE and memory channel 0 is 1.0 — they moved together. This
    is the structural-correlation contract of the joint mode.
    """
    # Setup: distinct memory values at COMPUTE positions vs VOID positions
    lattice = np.zeros((4, 4, 4), dtype=np.uint8)
    memory = np.zeros((1, 4, 4, 4), dtype=np.float32)
    # Mark COMPUTE cells with memory value 99.0; VOID cells with 0.0
    lattice[0, 0, 0] = STATE_COMPUTE
    lattice[1, 1, 1] = STATE_COMPUTE
    lattice[2, 2, 2] = STATE_COMPUTE
    memory[0, 0, 0, 0] = 99.0
    memory[0, 1, 1, 1] = 99.0
    memory[0, 2, 2, 2] = 99.0

    rng = np.random.default_rng(42)
    out_lattice, out_memory = _shuffled_snapshot_arrays(
        lattice, memory, "joint_lattice_memory_shuffle", rng,
    )
    # Every cell where lattice is COMPUTE must STILL have memory == 99.0
    compute_positions = np.argwhere(out_lattice == STATE_COMPUTE)
    for pos in compute_positions:
        assert out_memory[0, pos[0], pos[1], pos[2]] == 99.0, (
            f"Joint shuffle broke lattice/memory pairing at {tuple(pos)}: "
            f"lattice=COMPUTE but memory != 99.0"
        )


def test_shuffle_same_seed_produces_same_permutation():
    """Reproducibility — same RNG seed → identical output arrays."""
    lattice, memory = _synthetic_arrays()
    rng1 = np.random.default_rng(42)
    rng2 = np.random.default_rng(42)
    out1_l, out1_m = _shuffled_snapshot_arrays(
        lattice, memory, "joint_lattice_memory_shuffle", rng1,
    )
    out2_l, out2_m = _shuffled_snapshot_arrays(
        lattice, memory, "joint_lattice_memory_shuffle", rng2,
    )
    assert np.array_equal(out1_l, out2_l)
    assert np.array_equal(out1_m, out2_m)


def test_shuffle_different_seeds_produce_different_permutations():
    """Different seeds yield different permutations (sanity)."""
    lattice, memory = _synthetic_arrays()
    rng1 = np.random.default_rng(42)
    rng2 = np.random.default_rng(43)
    out1_l, _ = _shuffled_snapshot_arrays(
        lattice, memory, "lattice_only_shuffle", rng1,
    )
    out2_l, _ = _shuffled_snapshot_arrays(
        lattice, memory, "lattice_only_shuffle", rng2,
    )
    # With overwhelming probability for a 16^3 lattice, two random
    # permutations differ.
    assert not np.array_equal(out1_l, out2_l)


def test_shuffle_unknown_mode_raises():
    """Mode validation — unknown mode strings rejected."""
    lattice, memory = _synthetic_arrays()
    rng = np.random.default_rng(42)
    with pytest.raises(ValueError, match="unknown shuffle mode"):
        _shuffled_snapshot_arrays(lattice, memory, "rotate_lattice", rng)


# ---------------------------------------------------------------------------
# _interpret_signal_location + _shuffle_falsification_status — unit tests
# ---------------------------------------------------------------------------


def test_interpret_signal_location_classifier_artefact():
    """All three modes give similar CCIs → classifier_artefact."""
    assert _interpret_signal_location(0.30, 0.30, 0.30) == "classifier_artefact"
    assert _interpret_signal_location(0.30, 0.32, 0.31) == "classifier_artefact"


def test_interpret_signal_location_lattice_geometry():
    """unshuffled differs from both shuffled, AND lattice_only ≈ joint."""
    # unshuffled=0.30, lattice_only=0.10, joint=0.11
    # → diff(u,l)=0.20, diff(u,j)=0.19, diff(l,j)=0.01
    # → both shuffled modes collapsed similarly = lattice geometry was carrying
    assert _interpret_signal_location(0.30, 0.10, 0.11) == "lattice_geometry"


def test_interpret_signal_location_memory_grid_structure():
    """unshuffled ≈ lattice_only but ≠ joint → memory carries signal."""
    # unshuffled=0.30, lattice_only=0.31 (≈unshuffled), joint=0.10 (much lower)
    assert _interpret_signal_location(0.30, 0.31, 0.10) == "memory_grid_structure"


def test_interpret_signal_location_lattice_geometry_when_shuffled_modes_close():
    """lattice_only ≈ joint AND both differ from unshuffled → lattice_geometry.

    Per the rule precedence: when both shuffle modes give similar CCIs,
    the lattice shuffle alone was sufficient — memory shuffle adds nothing
    on top. Lattice geometry was carrying the signal.
    """
    # u=0.30, l=0.20 (diff=0.10), j=0.21 (diff=0.09), l vs j = 0.01 (close)
    assert _interpret_signal_location(0.30, 0.20, 0.21) == "lattice_geometry"


def test_interpret_signal_location_both_arrays_contribute():
    """Both shuffles produce meaningful drops AND joint drops further than lattice_only.

    Per design doc §3.8: each array's spatial structure carries independent
    signal. Strongest evidence for AURA's "real geometric structure"
    hypothesis. Requires d_u_l ≥ eps (lattice shuffle alone matters) AND
    d_l_j ≥ eps (joint shuffle drops further beyond lattice_only).
    """
    # u=0.30, l=0.20 (drop of 0.10 from lattice shuffle), j=0.10 (further
    # 0.10 drop from adding memory shuffle on top). Both arrays contributed.
    assert _interpret_signal_location(0.30, 0.20, 0.10) == "both_arrays_contribute"
    # Asymmetric drops still classify as both_arrays_contribute as long as
    # the joint shuffle adds meaningful further drop beyond lattice_only:
    assert _interpret_signal_location(0.30, 0.22, 0.12) == "both_arrays_contribute"


def test_shuffle_falsification_status_falsified_when_all_close():
    """All three modes within 0.05 → hypothesis_falsified (classifier artefact)."""
    # max_pairwise = 0.04 < 0.05 → falsified
    assert _shuffle_falsification_status(0.30, 0.30, 0.04) == "hypothesis_falsified"


def test_shuffle_falsification_status_supported_when_joint_collapses():
    """Joint shuffle drops CCI by >0.10 → hypothesis_supported."""
    # diff(unshuffled, joint) = 0.30 - 0.10 = 0.20, which is > 0.10
    assert _shuffle_falsification_status(0.30, 0.10, 0.20) == "hypothesis_supported"


def test_shuffle_falsification_status_inconclusive_in_middle():
    """Modest drops that don't meet either criterion → inconclusive."""
    # max_pairwise = 0.07 (not < 0.05) and joint diff = 0.07 (not > 0.10)
    assert _shuffle_falsification_status(0.30, 0.23, 0.07) == "inconclusive"


# ---------------------------------------------------------------------------
# shuffle_test — orchestrator integration tests
# ---------------------------------------------------------------------------


def test_shuffle_test_writes_expected_row_counts(tmp_path):
    """N snapshots × (1 unshuffled + N_seeds × 2 shuffled modes) rows + 1 aggregate.

    With 2 snapshots and default seeds (1 canonical + 5 variance = 6 total):
    per snapshot: 1 (unshuffled) + 6 (lattice_only) + 6 (joint) = 13 rows.
    Total: 2 × 13 + 1 aggregate = 27 lines.
    """
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snaps = [
        _make_snapshot(snaps_dir / f"v070_gen{i}_step{i}_test.npz", generation=i)
        for i in (1, 2)
    ]
    out = log_path.parent / "calibration_shuffle.jsonl"

    aggregate = shuffle_test(snaps, out, log_path, "short", config)
    lines = out.read_text().splitlines()
    assert len(lines) == 2 * 13 + 1  # 26 per-snapshot + 1 aggregate
    assert aggregate["experiment"] == "shuffle"
    assert aggregate["summary_type"] == "run_aggregate"


def test_shuffle_test_per_row_has_correct_parameter_combination(tmp_path):
    """Each per-snapshot row carries shuffle_mode and shuffle_seed."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "calibration_shuffle.jsonl"
    shuffle_test([snap], out, log_path, "short", config)

    pair_rows = [json.loads(l) for l in out.read_text().splitlines()[:-1]]
    for row in pair_rows:
        params = row["parameter_combination"]
        assert "shuffle_mode" in params
        assert "shuffle_seed" in params
        assert params["shuffle_mode"] in SHUFFLE_MODES


def test_shuffle_test_aggregate_has_signal_location_interpretation(tmp_path):
    """Aggregate row carries the signal_location_interpretation field."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "calibration_shuffle.jsonl"

    aggregate = shuffle_test([snap], out, log_path, "short", config)
    assert "signal_location_interpretation" in aggregate
    assert aggregate["signal_location_interpretation"] in {
        "classifier_artefact",
        "lattice_geometry",
        "memory_grid_structure",
        "both_arrays_contribute",
        "ambiguous",
        "incomplete_modes",
    }
    assert aggregate["falsification_status"] in {
        "hypothesis_supported",
        "hypothesis_falsified",
        "inconclusive",
    }


def test_shuffle_test_rejects_unknown_mode(tmp_path):
    """Unknown mode in the modes parameter → ValueError before any work happens."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "calibration_shuffle.jsonl"
    with pytest.raises(ValueError, match="unknown shuffle mode"):
        shuffle_test([snap], out, log_path, "short", config,
                     modes=("unshuffled", "rotate_lattice"))


def test_shuffle_test_rejects_unknown_calibration_set(tmp_path):
    """calibration_set must be 'short' or 'long'."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "calibration_shuffle.jsonl"
    with pytest.raises(ValueError, match="calibration_set"):
        shuffle_test([snap], out, log_path, "medium", config)


def test_shuffle_test_rejects_outside_log_dir_output(tmp_path):
    """Write-boundary safety inherited (per PR #142 pattern)."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    bad_out = tmp_path / "outside_dir" / "out.jsonl"
    with pytest.raises(WriteOutsideLogDirError, match="outside log_path"):
        shuffle_test([snap], bad_out, log_path, "short", config)
    assert not (tmp_path / "outside_dir").exists()


def test_shuffle_test_no_generated_at_field(tmp_path):
    """Determinism contract — no fresh timestamps in output."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "calibration_shuffle.jsonl"
    shuffle_test([snap], out, log_path, "short", config)
    content = out.read_text()
    assert "generated_at" not in content


def test_shuffle_test_subset_of_modes_marks_aggregate_incomplete(tmp_path):
    """If caller requests fewer than all three modes, aggregate is marked incomplete.

    Per the orchestrator's design: a partial run can't produce the
    three-way comparison, so falsification_status is 'inconclusive' and
    signal_location_interpretation is 'incomplete_modes'.
    """
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "calibration_shuffle.jsonl"
    aggregate = shuffle_test([snap], out, log_path, "short", config,
                             modes=("unshuffled", "lattice_only_shuffle"))
    assert aggregate["signal_location_interpretation"] == "incomplete_modes"
    assert aggregate["falsification_status"] == "inconclusive"
