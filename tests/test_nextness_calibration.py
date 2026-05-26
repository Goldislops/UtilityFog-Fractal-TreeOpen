"""Tests for scripts/nextness_calibration.py — Phase 19 PR #4 calibration suite.

Currently covers Chapters 1, 2, and 3 of the eight-chapter PR #4
implementation:

  - Chapter 1: Shared module infrastructure (write-boundary safety,
    deterministic snapshot ordering, content fingerprinting, JSONL
    output writer, falsification-status reporting) plus
    ``check_determinism()`` (Jack's #1 in the implementation order —
    the sanity floor for the rest of the calibration suite).

  - Chapter 2: ``shuffle_test()`` (Jack's #3) with **three modes** —
    ``unshuffled``, ``lattice_only_shuffle``, and
    ``joint_lattice_memory_shuffle`` — for the null-model
    discriminating test (signal_location_interpretation +
    falsification_status).

  - Chapter 3: ``verify_memory_channels()`` (Jack's #2) — runtime
    per-snapshot regression-fence complementing PR #145's static
    layout check. Verifies channel count, dtype, finiteness, and
    emits per-channel statistical signatures as diagnostic readout.

Later chapters will add tests for the remaining four experiments
(stride sweep, threshold sweep, cascade ablation, temporal sweep,
patch-radius coarse-graining).
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
    CANONICAL_STRIDE,
    DEFAULT_CANONICAL_SEED,
    DEFAULT_STRIDES,
    DEFAULT_VARIANCE_SEEDS,
    EXPECTED_MEMORY_CHANNELS,
    EXPECTED_MEMORY_DTYPE,
    SHUFFLE_MODES,
    SPARSITY_EPSILON,
    _clone_config_with_stride,
    _content_fingerprint,
    _extract_generation_from_filename,
    _interpret_signal_location,
    _make_aggregate_row,
    _make_per_snapshot_row,
    _per_channel_signature,
    _shuffle_falsification_status,
    _shuffled_snapshot_arrays,
    _sort_snapshots_by_generation,
    _validate_calibration_output_path,
    _verify_snapshot_memory_grid,
    check_determinism,
    shuffle_test,
    sweep_stride,
    verify_memory_channels,
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


# ---------------------------------------------------------------------------
# Chapter 3 — verify_memory_channels runtime regression-fence
# ---------------------------------------------------------------------------


def _make_snapshot_with_options(
    path: pathlib.Path,
    *,
    n_channels: int = 8,
    dtype: type = np.float32,
    inject_nan_at: tuple[int, int, int, int] | None = None,
    inject_inf_at: tuple[int, int, int, int] | None = None,
    lattice: int = 4,
    generation: int = 1,
) -> pathlib.Path:
    """Make a synthetic snapshot with explicit control over structural
    properties. Used to test verify_memory_channels under various drift
    scenarios.
    """
    state = np.zeros((lattice, lattice, lattice), dtype=np.uint8)
    state[::4, ::4, ::4] = STATE_COMPUTE
    memory = np.zeros((n_channels, lattice, lattice, lattice), dtype=dtype)
    memory[0, 0, 0, 0] = 1.0  # at least one non-zero
    if inject_nan_at is not None:
        memory[inject_nan_at] = np.nan
    if inject_inf_at is not None:
        memory[inject_inf_at] = np.inf
    np.savez(
        str(path),
        lattice=state, memory_grid=memory,
        generation=np.array(generation), best_fitness=np.array(0.5),
    )
    return path


# --- _per_channel_signature unit tests ---


def test_per_channel_signature_clean_channel_returns_complete_stats():
    """All-finite channel returns min/max/mean/std/sparsity + finite=True."""
    arr = np.array([[[0.0, 1.0], [2.0, 3.0]],
                    [[4.0, 5.0], [6.0, 7.0]]], dtype=np.float32)
    sig = _per_channel_signature(arr)
    assert sig["min"] == 0.0
    assert sig["max"] == 7.0
    assert sig["mean"] == pytest.approx(3.5)
    assert sig["finite"] is True
    assert sig["n_non_finite"] == 0
    assert sig["n_voxels"] == 8


def test_per_channel_signature_with_nan_flags_non_finite():
    """A NaN in the channel yields finite=False + non-zero n_non_finite."""
    arr = np.array([1.0, 2.0, np.nan, 4.0], dtype=np.float32)
    sig = _per_channel_signature(arr)
    assert sig["finite"] is False
    assert sig["n_non_finite"] == 1


def test_per_channel_signature_with_inf_flags_non_finite():
    """An Inf in the channel yields finite=False."""
    arr = np.array([1.0, np.inf, 3.0], dtype=np.float32)
    sig = _per_channel_signature(arr)
    assert sig["finite"] is False
    assert sig["n_non_finite"] == 1


def test_per_channel_signature_all_nan_returns_null_stats():
    """If every value is non-finite, min/max/mean/std are null but n_voxels
    and n_non_finite are still reported."""
    arr = np.array([np.nan, np.nan, np.nan], dtype=np.float32)
    sig = _per_channel_signature(arr)
    assert sig["min"] is None
    assert sig["max"] is None
    assert sig["mean"] is None
    assert sig["finite"] is False
    assert sig["n_non_finite"] == 3


def test_per_channel_signature_sparsity_counts_near_zero():
    """Sparsity = fraction of voxels with |value| <= SPARSITY_EPSILON."""
    # 6/8 voxels are zero
    arr = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 2.0], dtype=np.float32)
    sig = _per_channel_signature(arr)
    assert sig["sparsity"] == pytest.approx(6.0 / 8.0)


# --- _verify_snapshot_memory_grid unit tests ---


def test_verify_snapshot_clean_returns_no_drift(tmp_path):
    """Standard 8-channel float32 snapshot verifies cleanly."""
    snap = _make_snapshot_with_options(
        tmp_path / "v070_gen1_step1_test.npz",
        n_channels=8, dtype=np.float32,
    )
    signatures, drift_reasons = _verify_snapshot_memory_grid(snap)
    assert drift_reasons == []
    assert len(signatures) == 8


def test_verify_snapshot_wrong_channel_count_flags_drift(tmp_path):
    """7-channel grid flags shape drift."""
    snap = _make_snapshot_with_options(
        tmp_path / "v070_gen1_step1_test.npz",
        n_channels=7, dtype=np.float32,
    )
    _, drift_reasons = _verify_snapshot_memory_grid(snap)
    assert any("7 channels" in r for r in drift_reasons)
    assert any("expected 8" in r for r in drift_reasons)


def test_verify_snapshot_extra_channels_flag_drift(tmp_path):
    """9-channel grid flags shape drift (engine added a channel)."""
    snap = _make_snapshot_with_options(
        tmp_path / "v070_gen1_step1_test.npz",
        n_channels=9, dtype=np.float32,
    )
    _, drift_reasons = _verify_snapshot_memory_grid(snap)
    assert any("9 channels" in r for r in drift_reasons)


def test_verify_snapshot_wrong_dtype_flags_drift(tmp_path):
    """float64 instead of float32 flags dtype drift."""
    snap = _make_snapshot_with_options(
        tmp_path / "v070_gen1_step1_test.npz",
        n_channels=8, dtype=np.float64,
    )
    _, drift_reasons = _verify_snapshot_memory_grid(snap)
    assert any("dtype" in r.lower() for r in drift_reasons)
    assert any("float64" in r for r in drift_reasons)


def test_verify_snapshot_nan_in_channel_flags_drift(tmp_path):
    """A single NaN voxel in the memory_grid is flagged in drift reasons."""
    snap = _make_snapshot_with_options(
        tmp_path / "v070_gen1_step1_test.npz",
        inject_nan_at=(3, 1, 1, 1),  # channel 3, voxel (1,1,1)
    )
    signatures, drift_reasons = _verify_snapshot_memory_grid(snap)
    assert any("non-finite" in r for r in drift_reasons)
    assert any("channel 3" in r for r in drift_reasons)
    # The named channel for index 3 in post-#145 layout is "energy_reserve"
    assert "energy_reserve" in signatures
    assert signatures["energy_reserve"]["finite"] is False


def test_verify_snapshot_inf_in_channel_flags_drift(tmp_path):
    """A single Inf voxel is flagged the same way as NaN."""
    snap = _make_snapshot_with_options(
        tmp_path / "v070_gen1_step1_test.npz",
        inject_inf_at=(0, 0, 0, 0),  # channel 0
    )
    signatures, drift_reasons = _verify_snapshot_memory_grid(snap)
    assert any("non-finite" in r for r in drift_reasons)
    assert signatures["compute_age"]["finite"] is False


def test_verify_snapshot_missing_memory_grid_key_flags_drift(tmp_path):
    """An .npz file that lacks the memory_grid key is flagged."""
    bad = tmp_path / "v070_gen1_step1_test.npz"
    np.savez(
        str(bad),
        lattice=np.zeros((4, 4, 4), dtype=np.uint8),
        generation=np.array(1),
        # NO memory_grid key
    )
    signatures, drift_reasons = _verify_snapshot_memory_grid(bad)
    assert signatures == {}
    assert any("memory_grid" in r for r in drift_reasons)


# --- verify_memory_channels orchestrator integration tests ---


def test_verify_memory_channels_happy_path_all_snapshots_clean(tmp_path):
    """3 clean synthetic snapshots → hypothesis_supported, 0 drift."""
    snaps_dir = tmp_path / "snapshots"
    snaps_dir.mkdir()
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "nextness_runs.jsonl"

    snaps = [
        _make_snapshot_with_options(
            snaps_dir / f"v070_gen{i}_step{i}_test.npz", generation=i
        ) for i in (1, 2, 3)
    ]
    out = log_path.parent / "calibration_verify.jsonl"
    aggregate = verify_memory_channels(snaps, out, log_path, "short")

    assert aggregate["experiment"] == "verify_memory_channels"
    assert aggregate["summary_type"] == "run_aggregate"
    assert aggregate["n_snapshots"] == 3
    assert aggregate["n_snapshots_verified"] == 3
    assert aggregate["n_snapshots_with_drift"] == 0
    assert aggregate["falsification_status"] == "hypothesis_supported"
    assert aggregate["expected_channels"] == EXPECTED_MEMORY_CHANNELS
    assert aggregate["expected_dtype"] == EXPECTED_MEMORY_DTYPE
    assert aggregate["first_drift_reasons"] == []


def test_verify_memory_channels_mixed_set_flags_hypothesis_falsified(tmp_path):
    """Mix of clean + drifted snapshots → hypothesis_falsified, drift counted."""
    snaps_dir = tmp_path / "snapshots"
    snaps_dir.mkdir()
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "nextness_runs.jsonl"

    clean = _make_snapshot_with_options(
        snaps_dir / "v070_gen1_step1_test.npz", generation=1,
    )
    bad_channels = _make_snapshot_with_options(
        snaps_dir / "v070_gen2_step2_test.npz", generation=2, n_channels=9,
    )
    bad_dtype = _make_snapshot_with_options(
        snaps_dir / "v070_gen3_step3_test.npz", generation=3, dtype=np.float64,
    )
    out = log_path.parent / "calibration_verify.jsonl"
    aggregate = verify_memory_channels(
        [clean, bad_channels, bad_dtype], out, log_path, "short",
    )

    assert aggregate["n_snapshots_verified"] == 1
    assert aggregate["n_snapshots_with_drift"] == 2
    assert aggregate["falsification_status"] == "hypothesis_falsified"
    assert len(aggregate["first_drift_reasons"]) >= 2


def test_verify_memory_channels_empty_set_returns_inconclusive(tmp_path):
    """Empty snapshot list → inconclusive (nothing to verify)."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "nextness_runs.jsonl"
    out = log_path.parent / "calibration_verify.jsonl"

    aggregate = verify_memory_channels([], out, log_path, "short")
    assert aggregate["falsification_status"] == "inconclusive"
    assert aggregate["n_snapshots"] == 0


def test_verify_memory_channels_per_row_has_channel_signatures(tmp_path):
    """Per-snapshot rows expose channel_signatures dict keyed by channel name."""
    snaps_dir = tmp_path / "snapshots"
    snaps_dir.mkdir()
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "nextness_runs.jsonl"
    snap = _make_snapshot_with_options(
        snaps_dir / "v070_gen1_step1_test.npz", generation=1,
    )
    out = log_path.parent / "calibration_verify.jsonl"
    verify_memory_channels([snap], out, log_path, "short")

    rows = [json.loads(l) for l in out.read_text().splitlines()[:-1]]
    assert len(rows) == 1
    sigs = rows[0]["metrics"]["channel_signatures"]
    # Post-#145 layout — all 8 named channels present
    expected_names = {
        "compute_age", "structural_age", "memory_strength",
        "energy_reserve", "last_active_gen", "signal_field",
        "warmth", "compassion_cooldown",
    }
    assert set(sigs.keys()) == expected_names


def test_verify_memory_channels_rejects_unknown_calibration_set(tmp_path):
    """calibration_set validation — must be 'short' or 'long'."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "nextness_runs.jsonl"
    out = log_path.parent / "calibration_verify.jsonl"
    with pytest.raises(ValueError, match="calibration_set"):
        verify_memory_channels([], out, log_path, "medium")


def test_verify_memory_channels_rejects_outside_log_dir_output(tmp_path):
    """Write-boundary inheritance — output outside log dir raises."""
    snaps_dir = tmp_path / "snapshots"
    snaps_dir.mkdir()
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "nextness_runs.jsonl"
    snap = _make_snapshot_with_options(
        snaps_dir / "v070_gen1_step1_test.npz", generation=1,
    )
    bad_out = tmp_path / "outside_dir" / "out.jsonl"
    with pytest.raises(WriteOutsideLogDirError, match="outside log_path"):
        verify_memory_channels([snap], bad_out, log_path, "short")
    assert not (tmp_path / "outside_dir").exists()


def test_verify_memory_channels_no_generated_at_field(tmp_path):
    """Output JSONL must not include a fresh generated_at field."""
    snaps_dir = tmp_path / "snapshots"
    snaps_dir.mkdir()
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "nextness_runs.jsonl"
    snap = _make_snapshot_with_options(
        snaps_dir / "v070_gen1_step1_test.npz", generation=1,
    )
    out = log_path.parent / "calibration_verify.jsonl"
    verify_memory_channels([snap], out, log_path, "short")
    assert "generated_at" not in out.read_text()


def test_verify_memory_channels_deterministic_output(tmp_path):
    """Re-running on the same input produces byte-identical output.

    Same determinism contract as the other calibration functions — no
    fresh timestamps, sorted snapshot ordering, sort_keys=True in JSON.
    """
    snaps_dir = tmp_path / "snapshots"
    snaps_dir.mkdir()
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "nextness_runs.jsonl"
    snaps = [
        _make_snapshot_with_options(
            snaps_dir / f"v070_gen{i}_step{i}_test.npz", generation=i
        ) for i in (1, 2, 3)
    ]
    out_a = log_path.parent / "calibration_verify_a.jsonl"
    out_b = log_path.parent / "calibration_verify_b.jsonl"
    verify_memory_channels(snaps, out_a, log_path, "short")
    verify_memory_channels(snaps, out_b, log_path, "short")
    assert out_a.read_bytes() == out_b.read_bytes()


def test_verify_memory_channels_sorts_input_by_generation(tmp_path):
    """Per-snapshot rows in output appear in generation-ascending order."""
    snaps_dir = tmp_path / "snapshots"
    snaps_dir.mkdir()
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "nextness_runs.jsonl"
    # Create out of order
    s3 = _make_snapshot_with_options(
        snaps_dir / "v070_gen300_step3000_test.npz", generation=300,
    )
    s1 = _make_snapshot_with_options(
        snaps_dir / "v070_gen100_step1000_test.npz", generation=100,
    )
    s2 = _make_snapshot_with_options(
        snaps_dir / "v070_gen200_step2000_test.npz", generation=200,
    )
    out = log_path.parent / "calibration_verify.jsonl"
    verify_memory_channels([s3, s1, s2], out, log_path, "short")

    rows = [json.loads(l) for l in out.read_text().splitlines()[:-1]]
    generations = [r["snapshot_generation"] for r in rows]
    assert generations == [100, 200, 300]


# ---------------------------------------------------------------------------
# Chapter 4 — sweep_stride (spatial stride sweep, design doc §3.1)
# ---------------------------------------------------------------------------


def test_default_strides_is_canonical_triple():
    """Default strides per design doc §3.1: (4, 8, 16)."""
    assert DEFAULT_STRIDES == (4, 8, 16)
    assert CANONICAL_STRIDE == 8
    assert CANONICAL_STRIDE in DEFAULT_STRIDES


def test_clone_config_with_stride_preserves_other_fields():
    """The clone overrides only uniform_grid_stride; other fields are kept."""
    base = ObserverConfig(
        log_directory="/tmp/test_log",
        uniform_grid_stride=8,
        budget_seconds=30.0,
    )
    clone = _clone_config_with_stride(base, 4)
    assert clone.uniform_grid_stride == 4
    assert clone.budget_seconds == base.budget_seconds
    assert clone.log_directory == base.log_directory
    # Original is unchanged (frozen dataclass)
    assert base.uniform_grid_stride == 8


def test_sweep_stride_rejects_unknown_calibration_set(tmp_path):
    """calibration_set validation."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "calibration_stride.jsonl"
    with pytest.raises(ValueError, match="calibration_set"):
        sweep_stride([snap], out, log_path, "medium", config)


def test_sweep_stride_rejects_empty_strides(tmp_path):
    """At least one stride required."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    out = log_path.parent / "calibration_stride.jsonl"
    with pytest.raises(ValueError, match="strides must be non-empty"):
        sweep_stride([], out, log_path, "short", config, strides=())


def test_sweep_stride_rejects_non_positive_stride(tmp_path):
    """Stride values must be positive integers."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    out = log_path.parent / "calibration_stride.jsonl"
    with pytest.raises(ValueError, match="positive int"):
        sweep_stride([], out, log_path, "short", config, strides=(0,))
    with pytest.raises(ValueError, match="positive int"):
        sweep_stride([], out, log_path, "short", config, strides=(-1,))


def test_sweep_stride_rejects_outside_log_dir_output(tmp_path):
    """Write-boundary inheritance."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    bad_out = tmp_path / "outside_dir" / "out.jsonl"
    with pytest.raises(WriteOutsideLogDirError, match="outside log_path"):
        sweep_stride([snap], bad_out, log_path, "short", config)
    assert not (tmp_path / "outside_dir").exists()


def test_sweep_stride_writes_expected_row_count(tmp_path):
    """N snapshots × M strides = N*M per-snapshot rows + 1 aggregate."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snaps = [
        _make_snapshot(snaps_dir / f"v070_gen{i}_step{i}_test.npz",
                       generation=i, lattice=16)
        for i in (1, 2)
    ]
    out = log_path.parent / "calibration_stride.jsonl"
    sweep_stride(snaps, out, log_path, "short", config)

    lines = out.read_text().splitlines()
    # 2 snapshots × 3 default strides + 1 aggregate = 7
    assert len(lines) == 2 * 3 + 1


def test_sweep_stride_per_row_has_stride_parameter(tmp_path):
    """Each per-snapshot row carries its stride in parameter_combination."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz",
                          generation=1, lattice=16)
    out = log_path.parent / "calibration_stride.jsonl"
    sweep_stride([snap], out, log_path, "short", config)

    pair_rows = [json.loads(l) for l in out.read_text().splitlines()[:-1]]
    observed_strides = sorted(r["parameter_combination"]["stride"]
                              for r in pair_rows)
    assert observed_strides == [4, 8, 16]


def test_sweep_stride_aggregate_has_per_stride_summary(tmp_path):
    """Aggregate row carries per-stride summary stats + cross-stride diffs."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz",
                          generation=1, lattice=16)
    out = log_path.parent / "calibration_stride.jsonl"
    aggregate = sweep_stride([snap], out, log_path, "short", config)

    assert aggregate["experiment"] == "stride_sweep"
    assert aggregate["strides_swept"] == [4, 8, 16]
    assert aggregate["canonical_stride"] == 8
    per_stride = aggregate["per_stride_summary"]
    assert set(per_stride.keys()) == {"4", "8", "16"}
    for stride_key in ("4", "8", "16"):
        assert "mean_vocabulary_occupancy" in per_stride[stride_key]
        assert "mean_cci" in per_stride[stride_key]
    # Cross-stride diffs (only for non-canonical strides)
    diffs = aggregate["cross_stride_diffs"]
    assert "voc_occ_diff_4_vs_8" in diffs
    assert "voc_occ_diff_16_vs_8" in diffs
    # JS divergence across pairs
    js = aggregate["cross_stride_js_divergence"]
    assert any("4_vs_8" in k for k in js.keys())
    assert any("4_vs_16" in k for k in js.keys())
    assert any("8_vs_16" in k for k in js.keys())


def test_sweep_stride_falsification_status_supported_on_synthetic_stable(tmp_path):
    """Synthetic snapshots produce stable metrics across strides → supported.

    Our synthetic _make_snapshot has a sparse uniform pattern; classify_patch
    output is dominated by predictable tokens. We expect all three strides to
    give similar voc_occ on this artificial fixture.
    """
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snaps = [
        _make_snapshot(snaps_dir / f"v070_gen{i}_step{i}_test.npz",
                       generation=i, lattice=16)
        for i in (1, 2)
    ]
    out = log_path.parent / "calibration_stride.jsonl"
    aggregate = sweep_stride(snaps, out, log_path, "short", config)

    # On synthetic data the result is expected to be either supported or
    # inconclusive — both are non-falsifying. The key thing this test
    # asserts is that the falsification machinery doesn't spuriously
    # report 'falsified' on stable input.
    assert aggregate["falsification_status"] in {
        "hypothesis_supported",
        "inconclusive",
    }


def test_sweep_stride_falsification_inconclusive_without_canonical_stride(tmp_path):
    """If strides tuple doesn't include CANONICAL_STRIDE (=8), can't apply
    the §3.1 criterion → inconclusive."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz",
                          generation=1, lattice=16)
    out = log_path.parent / "calibration_stride.jsonl"
    aggregate = sweep_stride([snap], out, log_path, "short", config,
                             strides=(2, 4, 16))  # no 8
    assert aggregate["falsification_status"] == "inconclusive"


def test_sweep_stride_no_generated_at_field(tmp_path):
    """Determinism contract — no fresh timestamps in output."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz",
                          generation=1, lattice=16)
    out = log_path.parent / "calibration_stride.jsonl"
    sweep_stride([snap], out, log_path, "short", config)
    assert "generated_at" not in out.read_text()


def test_sweep_stride_byte_identical_on_rerun(tmp_path):
    """Determinism — re-running on the same input produces byte-identical output."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snaps = [
        _make_snapshot(snaps_dir / f"v070_gen{i}_step{i}_test.npz",
                       generation=i, lattice=16)
        for i in (1, 2)
    ]
    out_a = log_path.parent / "calibration_stride_a.jsonl"
    out_b = log_path.parent / "calibration_stride_b.jsonl"
    sweep_stride(snaps, out_a, log_path, "short", config)
    sweep_stride(snaps, out_b, log_path, "short", config)
    assert out_a.read_bytes() == out_b.read_bytes()


def test_sweep_stride_sorts_input_by_generation(tmp_path):
    """Per-snapshot rows appear in (generation-ascending, stride-iteration) order."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    s3 = _make_snapshot(snaps_dir / "v070_gen300_step3000_test.npz",
                        generation=300, lattice=16)
    s1 = _make_snapshot(snaps_dir / "v070_gen100_step1000_test.npz",
                        generation=100, lattice=16)
    s2 = _make_snapshot(snaps_dir / "v070_gen200_step2000_test.npz",
                        generation=200, lattice=16)
    out = log_path.parent / "calibration_stride.jsonl"
    sweep_stride([s3, s1, s2], out, log_path, "short", config)

    rows = [json.loads(l) for l in out.read_text().splitlines()[:-1]]
    # First 3 rows should be gen 100 (each stride); next 3 gen 200; next 3 gen 300
    assert rows[0]["snapshot_generation"] == 100
    assert rows[1]["snapshot_generation"] == 100
    assert rows[2]["snapshot_generation"] == 100
    assert rows[3]["snapshot_generation"] == 200
    assert rows[6]["snapshot_generation"] == 300


def test_sweep_stride_custom_strides_honored(tmp_path):
    """Custom strides tuple changes the sweep."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz",
                          generation=1, lattice=16)
    out = log_path.parent / "calibration_stride.jsonl"
    aggregate = sweep_stride([snap], out, log_path, "short", config,
                             strides=(2, 4, 8))
    assert aggregate["strides_swept"] == [2, 4, 8]
    assert set(aggregate["per_stride_summary"].keys()) == {"2", "4", "8"}
