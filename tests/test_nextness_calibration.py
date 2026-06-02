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
    DEFAULT_ABLATION_DISABLED_TOKENS,
    DEFAULT_CANONICAL_SEED,
    DEFAULT_GAP_SPECS_LONG,
    DEFAULT_GAP_SPECS_SHORT,
    DEFAULT_PATCH_RADII,
    DEFAULT_STRIDES,
    DEFAULT_THRESHOLD_MULTIPLIERS,
    DEFAULT_THRESHOLD_NAME,
    DEFAULT_VARIANCE_SEEDS,
    EXPECTED_MEMORY_CHANNELS,
    EXPECTED_MEMORY_DTYPE,
    PATCH_RADIUS_BASELINE,
    SHUFFLE_MODES,
    SPARSITY_EPSILON,
    _ACTIVE_CASCADE_ORDER,
    _ablation_modes_for_run,
    _classify_patch_ablation,
    _clone_config_with_radius,
    _clone_config_with_stride,
    _content_fingerprint,
    _emerging_tokens_vs_baseline,
    _extract_generation_from_filename,
    _interpret_signal_location,
    _make_aggregate_row,
    _make_per_snapshot_row,
    _patch_cell_count,
    _per_channel_signature,
    _rescale_count_threshold_for_radius,
    _shuffle_falsification_status,
    _shuffled_snapshot_arrays,
    _sort_snapshots_by_generation,
    _temporal_pair_stats,
    _validate_calibration_output_path,
    _validate_config_log_directory,
    _verify_snapshot_memory_grid,
    ablate_cascade,
    check_determinism,
    shuffle_test,
    sweep_patch_radius,
    sweep_stride,
    sweep_temporal,
    sweep_threshold,
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
# _validate_config_log_directory (Jack PR #149 safety-contract guard)
# ---------------------------------------------------------------------------


def test_validate_config_log_dir_matches_log_path_parent_succeeds(tmp_path):
    """config.log_directory == log_path.parent passes silently."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "nextness_runs.jsonl"
    config = ObserverConfig(log_directory=str(log_dir))
    # Should not raise.
    _validate_config_log_directory(config, log_path)


def test_validate_config_log_dir_mismatch_raises(tmp_path):
    """Mismatched config.log_directory raises WriteOutsideLogDirError."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    log_path = log_dir / "nextness_runs.jsonl"
    config = ObserverConfig(log_directory=str(elsewhere))
    with pytest.raises(
        WriteOutsideLogDirError,
        match="config.log_directory diverging from log_path.parent",
    ):
        _validate_config_log_directory(config, log_path)


def test_validate_config_log_dir_traversal_escape_rejected(tmp_path):
    """``..`` traversal in config.log_directory is rejected via resolve()."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "nextness_runs.jsonl"
    # log_dir / ".." resolves to tmp_path / "data" — not the same as log_dir
    config = ObserverConfig(log_directory=str(log_dir / ".."))
    with pytest.raises(WriteOutsideLogDirError):
        _validate_config_log_directory(config, log_path)


def test_validate_config_log_dir_mismatch_creates_no_side_effect_directory(tmp_path):
    """When the guard rejects a mismatched config, no stray log directory
    must be created. Locks in the property that the guard fires BEFORE any
    process_snapshot() call (which would trigger _ensure_log_dir on the
    misconfigured path)."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "nextness_runs.jsonl"
    bogus_dir = tmp_path / "bogus_log_dir_should_never_be_created"
    assert not bogus_dir.exists()
    config = ObserverConfig(log_directory=str(bogus_dir))
    with pytest.raises(WriteOutsideLogDirError):
        _validate_config_log_directory(config, log_path)
    # The bogus directory must NOT have been created as a side effect.
    assert not bogus_dir.exists()


def test_check_determinism_rejects_mismatched_config_log_directory(tmp_path):
    """Integration: check_determinism must fire the config-log-dir guard
    before any process_snapshot() call. Proves the helper is wired in."""
    snaps_dir, log_path, _ = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    bogus_dir = tmp_path / "bogus_for_check_determinism"
    bad_config = ObserverConfig(
        log_directory=str(bogus_dir),
        uniform_grid_stride=4,
        budget_seconds=30.0,
    )
    with pytest.raises(
        WriteOutsideLogDirError,
        match="config.log_directory diverging",
    ):
        check_determinism(
            snapshots=[snap],
            out_path=out,
            log_path=log_path,
            calibration_set="short",
            config=bad_config,
            repeats=2,
        )
    # Neither the bogus log dir nor the output file may have been created.
    assert not bogus_dir.exists()
    assert not out.exists()


def test_shuffle_test_rejects_mismatched_config_log_directory(tmp_path):
    """Integration: shuffle_test must fire the config-log-dir guard
    before any process_snapshot() call."""
    snaps_dir, log_path, _ = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    bogus_dir = tmp_path / "bogus_for_shuffle_test"
    bad_config = ObserverConfig(
        log_directory=str(bogus_dir),
        uniform_grid_stride=4,
        budget_seconds=30.0,
    )
    with pytest.raises(
        WriteOutsideLogDirError,
        match="config.log_directory diverging",
    ):
        shuffle_test(
            snapshots=[snap],
            out_path=out,
            log_path=log_path,
            calibration_set="short",
            config=bad_config,
        )
    assert not bogus_dir.exists()
    assert not out.exists()


def test_sweep_stride_rejects_mismatched_config_log_directory(tmp_path):
    """Integration: sweep_stride must fire the config-log-dir guard
    before any process_snapshot() call."""
    snaps_dir, log_path, _ = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    bogus_dir = tmp_path / "bogus_for_sweep_stride"
    bad_config = ObserverConfig(
        log_directory=str(bogus_dir),
        uniform_grid_stride=4,
        budget_seconds=30.0,
    )
    with pytest.raises(
        WriteOutsideLogDirError,
        match="config.log_directory diverging",
    ):
        sweep_stride(
            snapshots=[snap],
            out_path=out,
            log_path=log_path,
            calibration_set="short",
            config=bad_config,
        )
    assert not bogus_dir.exists()
    assert not out.exists()


def test_sweep_threshold_rejects_mismatched_config_log_directory(tmp_path):
    """Integration: sweep_threshold must fire the config-log-dir guard
    before any process_snapshot() call AND before any threshold monkeypatch."""
    snaps_dir, log_path, _ = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    bogus_dir = tmp_path / "bogus_for_sweep_threshold"
    bad_config = ObserverConfig(
        log_directory=str(bogus_dir),
        uniform_grid_stride=4,
        budget_seconds=30.0,
    )
    # Snapshot the threshold so we can also confirm the guard fired before
    # any monkeypatch happened (no threshold mutation if the guard rejects).
    from scripts import nextness_observer as _observer_module
    original_threshold = getattr(_observer_module, "THRESHOLD_WARMTH")
    with pytest.raises(
        WriteOutsideLogDirError,
        match="config.log_directory diverging",
    ):
        sweep_threshold(
            snapshots=[snap],
            out_path=out,
            log_path=log_path,
            calibration_set="short",
            config=bad_config,
            threshold_dependent_token="compute_decay",
        )
    assert not bogus_dir.exists()
    assert not out.exists()
    assert getattr(_observer_module, "THRESHOLD_WARMTH") == original_threshold


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


# ---------------------------------------------------------------------------
# Chapter 5 — sweep_threshold (threshold sensitivity sweep, design doc §3.4)
# ---------------------------------------------------------------------------


def test_default_threshold_multipliers_symmetric_around_one():
    """Per design doc §12 Q3: ±10%, ±25%, ±50% + baseline."""
    assert DEFAULT_THRESHOLD_MULTIPLIERS == (0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5)
    # Baseline included
    assert 1.0 in DEFAULT_THRESHOLD_MULTIPLIERS


def test_default_threshold_name_is_warmth():
    """Post-#144, THRESHOLD_WARMTH is the only active classifier threshold."""
    assert DEFAULT_THRESHOLD_NAME == "THRESHOLD_WARMTH"


def test_sweep_threshold_rejects_unknown_calibration_set(tmp_path):
    """calibration_set validation."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "calibration_threshold.jsonl"
    with pytest.raises(ValueError, match="calibration_set"):
        sweep_threshold([snap], out, log_path, "medium", config)


def test_sweep_threshold_rejects_missing_threshold_attribute(tmp_path):
    """threshold_name must exist on the observer module."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "calibration_threshold.jsonl"
    with pytest.raises(ValueError, match="not found on"):
        sweep_threshold([snap], out, log_path, "short", config,
                        threshold_name="THRESHOLD_NONEXISTENT")


def test_sweep_threshold_rejects_empty_multipliers(tmp_path):
    """At least one multiplier required."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    out = log_path.parent / "calibration_threshold.jsonl"
    with pytest.raises(ValueError, match="multipliers must be non-empty"):
        sweep_threshold([], out, log_path, "short", config, multipliers=())


def test_sweep_threshold_rejects_non_positive_multiplier(tmp_path):
    """Multipliers must be positive."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    out = log_path.parent / "calibration_threshold.jsonl"
    with pytest.raises(ValueError, match="positive number"):
        sweep_threshold([], out, log_path, "short", config, multipliers=(0.0,))
    with pytest.raises(ValueError, match="positive number"):
        sweep_threshold([], out, log_path, "short", config, multipliers=(-0.5,))


def test_sweep_threshold_rejects_outside_log_dir_output(tmp_path):
    """Write-boundary inheritance."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    bad_out = tmp_path / "outside_dir" / "out.jsonl"
    with pytest.raises(WriteOutsideLogDirError, match="outside log_path"):
        sweep_threshold([snap], bad_out, log_path, "short", config,
                        threshold_dependent_token="compute_decay")
    assert not (tmp_path / "outside_dir").exists()


def test_sweep_threshold_restores_threshold_after_run(tmp_path):
    """The monkeypatch must restore the original threshold value after the sweep.

    Locks in the try/finally contract: even if the sweep succeeds normally,
    the observer module's THRESHOLD_WARMTH constant must be exactly what
    it was before the sweep started.
    """
    from scripts import nextness_observer as obs
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz",
                          generation=1, lattice=16)
    out = log_path.parent / "calibration_threshold.jsonl"

    original = obs.THRESHOLD_WARMTH
    sweep_threshold([snap], out, log_path, "short", config,
                    threshold_dependent_token="compute_decay")
    assert obs.THRESHOLD_WARMTH == original


def test_sweep_threshold_restores_threshold_even_if_process_snapshot_fails(tmp_path, monkeypatch):
    """If process_snapshot raises mid-sweep, the threshold must STILL be restored.

    The whole point of the try/finally contract — observer state must not
    leak from the calibration scope even under exception.
    """
    from scripts import nextness_observer as obs
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz",
                          generation=1, lattice=16)
    out = log_path.parent / "calibration_threshold.jsonl"

    original = obs.THRESHOLD_WARMTH

    # Monkeypatch process_snapshot to raise mid-iteration
    def broken_process(*args, **kwargs):
        raise RuntimeError("simulated mid-sweep failure")

    monkeypatch.setattr(
        "scripts.nextness_calibration.process_snapshot",
        broken_process,
    )
    with pytest.raises(RuntimeError, match="simulated mid-sweep failure"):
        sweep_threshold([snap], out, log_path, "short", config,
                        threshold_dependent_token="compute_decay")
    # Threshold must be restored despite the exception
    assert obs.THRESHOLD_WARMTH == original


def test_sweep_threshold_writes_expected_row_count(tmp_path):
    """N snapshots × M multipliers = N*M per-snapshot rows + 1 aggregate."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snaps = [
        _make_snapshot(snaps_dir / f"v070_gen{i}_step{i}_test.npz",
                       generation=i, lattice=16)
        for i in (1, 2)
    ]
    out = log_path.parent / "calibration_threshold.jsonl"
    # Use a small multiplier set for test speed
    sweep_threshold(snaps, out, log_path, "short", config,
                    multipliers=(0.5, 1.0, 1.5),
                    threshold_dependent_token="compute_decay")

    lines = out.read_text().splitlines()
    # 2 snapshots × 3 multipliers + 1 aggregate = 7
    assert len(lines) == 2 * 3 + 1


def test_sweep_threshold_per_row_has_effective_value(tmp_path):
    """Each per-snapshot row carries the effective threshold value."""
    from scripts import nextness_observer as obs
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz",
                          generation=1, lattice=16)
    out = log_path.parent / "calibration_threshold.jsonl"
    base = obs.THRESHOLD_WARMTH
    sweep_threshold([snap], out, log_path, "short", config,
                    multipliers=(0.5, 1.0, 2.0),
                    threshold_dependent_token="compute_decay")

    pair_rows = [json.loads(l) for l in out.read_text().splitlines()[:-1]]
    eff_values = sorted(r["parameter_combination"]["threshold_effective_value"]
                        for r in pair_rows)
    expected = sorted([0.5 * base, 1.0 * base, 2.0 * base])
    for a, b in zip(eff_values, expected):
        assert a == pytest.approx(b)


def test_sweep_threshold_aggregate_has_knife_edge_evidence(tmp_path):
    """Aggregate carries knife_edge_evidence dict + per_multiplier_summary."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz",
                          generation=1, lattice=16)
    out = log_path.parent / "calibration_threshold.jsonl"
    aggregate = sweep_threshold([snap], out, log_path, "short", config,
                                threshold_dependent_token="compute_decay")

    assert aggregate["experiment"] == "threshold_sweep"
    assert "threshold_base_value" in aggregate
    assert "per_multiplier_summary" in aggregate
    assert "knife_edge_evidence" in aggregate
    assert "1.0" in aggregate["per_multiplier_summary"]


def test_sweep_threshold_inconclusive_when_token_never_fires(tmp_path):
    """If the threshold_dependent_token never fires on any (snapshot, mult)
    combo, the knife-edge criterion has no denominator → inconclusive."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz",
                          generation=1, lattice=16)
    out = log_path.parent / "calibration_threshold.jsonl"
    # Use a real routing token that does not fire on this synthetic snapshot:
    # the only token that classifies here is compute_decay (all cells are
    # compute with compute_age=15 and zero warmth), so acoustic_stress has a
    # firing count of 0 across every multiplier. Status should be inconclusive,
    # not falsified. (Post-#164 the sweep refuses the old metta_warmth default
    # outright, so the never-fires path must be exercised via a routing token.)
    aggregate = sweep_threshold([snap], out, log_path, "short", config,
                                multipliers=(0.5, 1.0, 1.5),
                                threshold_dependent_token="acoustic_stress")
    assert aggregate["falsification_status"] == "inconclusive"
    assert "never fires" in aggregate["knife_edge_evidence"].get("reason", "")


def test_sweep_threshold_no_generated_at_field(tmp_path):
    """Determinism contract — no fresh timestamps."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz",
                          generation=1, lattice=16)
    out = log_path.parent / "calibration_threshold.jsonl"
    sweep_threshold([snap], out, log_path, "short", config,
                    multipliers=(0.5, 1.0, 1.5),
                    threshold_dependent_token="compute_decay")
    assert "generated_at" not in out.read_text()


def test_sweep_threshold_byte_identical_on_rerun(tmp_path):
    """Determinism contract — byte-identical re-run on same input."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz",
                          generation=1, lattice=16)
    out_a = log_path.parent / "calibration_threshold_a.jsonl"
    out_b = log_path.parent / "calibration_threshold_b.jsonl"
    sweep_threshold([snap], out_a, log_path, "short", config,
                    multipliers=(0.5, 1.0, 1.5),
                    threshold_dependent_token="compute_decay")
    sweep_threshold([snap], out_b, log_path, "short", config,
                    multipliers=(0.5, 1.0, 1.5),
                    threshold_dependent_token="compute_decay")
    assert out_a.read_bytes() == out_b.read_bytes()


def test_sweep_threshold_sorts_input_by_generation(tmp_path):
    """Per-snapshot rows in generation-ascending order regardless of input."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    s3 = _make_snapshot(snaps_dir / "v070_gen300_step3000_test.npz",
                        generation=300, lattice=16)
    s1 = _make_snapshot(snaps_dir / "v070_gen100_step1000_test.npz",
                        generation=100, lattice=16)
    s2 = _make_snapshot(snaps_dir / "v070_gen200_step2000_test.npz",
                        generation=200, lattice=16)
    out = log_path.parent / "calibration_threshold.jsonl"
    sweep_threshold([s3, s1, s2], out, log_path, "short", config,
                    multipliers=(1.0,),  # single multiplier for predictable ordering
                    threshold_dependent_token="compute_decay")

    rows = [json.loads(l) for l in out.read_text().splitlines()[:-1]]
    generations = [r["snapshot_generation"] for r in rows]
    assert generations == [100, 200, 300]


def test_sweep_threshold_rejects_missing_token(tmp_path):
    """Explicit-only (post-#164 hardening): there is no threshold_dependent_token
    default. Omitting it must raise a clear ValueError rather than silently
    sweeping the demoted metta_warmth token (inconclusive by construction)."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "calibration_threshold.jsonl"
    with pytest.raises(ValueError, match="must be passed explicitly"):
        sweep_threshold([snap], out, log_path, "short", config)


def test_sweep_threshold_rejects_non_routing_token(tmp_path):
    """A non-routing token (e.g. the demoted metta_warmth, status
    diagnostic_only) never fires in the active cascade, so a sweep against it is
    inconclusive by construction. It must be rejected with a clear message
    rather than silently manufacturing useless calibration evidence."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "calibration_threshold.jsonl"
    with pytest.raises(ValueError, match="non-routing status"):
        sweep_threshold([snap], out, log_path, "short", config,
                        threshold_dependent_token="metta_warmth")


def test_sweep_threshold_rejects_unknown_token(tmp_path):
    """An unknown token name is rejected clearly (not silently treated as
    never-firing)."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "calibration_threshold.jsonl"
    with pytest.raises(ValueError, match="not a known token"):
        sweep_threshold([snap], out, log_path, "short", config,
                        threshold_dependent_token="not_a_real_token")


def test_sweep_threshold_explicit_routing_token_is_recorded(tmp_path):
    """Explicit routing-token selection still works and the chosen token name is
    threaded into the aggregate + per-snapshot rows."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz",
                          generation=1, lattice=16)
    out = log_path.parent / "calibration_threshold.jsonl"
    aggregate = sweep_threshold([snap], out, log_path, "short", config,
                                multipliers=(1.0,),
                                threshold_dependent_token="compute_decay")
    assert aggregate["threshold_dependent_token"] == "compute_decay"
    pair_rows = [json.loads(l) for l in out.read_text().splitlines()[:-1]]
    assert pair_rows  # sanity: at least one per-snapshot row
    assert all(
        r["parameter_combination"]["threshold_dependent_token"] == "compute_decay"
        for r in pair_rows
    )
    assert all(
        r["metrics"]["threshold_dependent_token_name"] == "compute_decay"
        for r in pair_rows
    )


# ===========================================================================
# Chapter 6 — ablate_cascade (design doc §3.5)
# ===========================================================================


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


def test_default_ablation_disabled_tokens_are_active_cascade_tokens():
    """Every DEFAULT_ABLATION_DISABLED_TOKENS entry must be in the active
    cascade — guards against typos and against accidentally trying to
    ablate a deprecated token."""
    for token in DEFAULT_ABLATION_DISABLED_TOKENS:
        assert token in _ACTIVE_CASCADE_ORDER, (
            f"default ablation token {token!r} not in active cascade"
        )


def test_active_cascade_order_excludes_non_routing_tokens():
    """_ACTIVE_CASCADE_ORDER must NOT contain any non-routing token:
    the #144 deprecated tokens (karuna_relief, mudita_resonance,
    magnon_lighthouse) and the Workstream B/C diagnostic_only token
    (metta_warmth, PR #163). Locks the cascade composition against drift."""
    non_routing = {
        "karuna_relief", "mudita_resonance", "magnon_lighthouse",
        "metta_warmth",
    }
    overlap = set(_ACTIVE_CASCADE_ORDER) & non_routing
    assert not overlap, f"non-routing tokens in active cascade: {overlap}"


# ---------------------------------------------------------------------------
# _classify_patch_ablation — parity regression-fence + ablation correctness
# ---------------------------------------------------------------------------


def _make_synthetic_patch_for_branch(branch: str):
    """Synthetic Patch built to trigger a specific cascade branch.

    Returns a minimal Patch object with hand-built state + memory arrays.
    Mirrors the lazy-import pattern used by the observer's _patch_features.
    """
    from scripts.nextness_observer import (
        AGE_ANCIENT,
        AGE_SAGE,
        ENERGY_PULSE_MIN_COUNT,
        Patch,
        STATE_COMPUTE,
        STATE_ENERGY,
        STATE_SENSOR,
        STATE_STRUCTURAL,
        STATE_VOID,
    )
    # 3x3x3 patches everywhere; deterministic content.
    R = 1  # patch_spatial_radius -> 3x3x3 = 27 cells
    state = np.full((3, 3, 3), STATE_VOID, dtype=np.uint8)
    memory = np.zeros((8, 3, 3, 3), dtype=np.float32)
    if branch == "phase_boundary":
        # distinct_states >= DIVERSITY_BOUNDARY (>=4 by default).
        state[0, 0, 0] = STATE_COMPUTE
        state[0, 0, 1] = STATE_STRUCTURAL
        state[0, 0, 2] = STATE_ENERGY
        state[0, 1, 0] = STATE_SENSOR
    elif branch == "compute_aging":
        state[:, :, :] = STATE_COMPUTE  # compute_frac = 1.0
        memory[CH["compute_age"], :, :, :] = float(AGE_SAGE + 5)
    # (metta_warmth branch removed: demoted to diagnostic_only per PR #163,
    #  no longer in _ACTIVE_CASCADE_ORDER, so the parity battery never builds
    #  a patch for it.)
    elif branch == "sensor_alert":
        # sensor_count>=1, no compute/energy dominance, distinct_states<4
        state[0, 0, 0] = STATE_SENSOR
    elif branch == "energy_pulse":
        # energy_count >= ENERGY_PULSE_MIN_COUNT, no compute, no sensors,
        # not dominant in any single category.
        for i in range(ENERGY_PULSE_MIN_COUNT):
            state.flat[i] = STATE_ENERGY
    elif branch == "compute_decay":
        # compute_count>=1, void_frac dominant, warmth_mean < THRESHOLD_WARMTH
        state[0, 0, 0] = STATE_COMPUTE
        # rest stays VOID -> void_frac high
        memory[CH["warmth"], :, :, :] = 0.0
    elif branch == "compute_static":
        # compute_frac >= FRACTION_DOMINANT, compute_age below SAGE,
        # warmth below threshold (so metta_warmth/decay don't catch first).
        state[:, :, :] = STATE_COMPUTE
        memory[CH["compute_age"], :, :, :] = float(AGE_SAGE - 1)
        memory[CH["warmth"], :, :, :] = 0.0
    elif branch == "structural_growth":
        state[:, :, :] = STATE_STRUCTURAL
        memory[CH["structural_age"], :, :, :] = float(AGE_SAGE - 1)
    elif branch == "structural_decay":
        state[:, :, :] = STATE_STRUCTURAL
        memory[CH["structural_age"], :, :, :] = float(AGE_ANCIENT + 1)
    elif branch == "void_birth":
        # void_frac dominant but distinct_states>=2 (and <4 so phase_boundary
        # doesn't catch).
        state[0, 0, 0] = STATE_STRUCTURAL
        state[0, 0, 1] = STATE_STRUCTURAL
    elif branch == "void_static":
        # All void -> distinct_states=1, void_frac=1.0
        pass  # state already all-VOID
    elif branch == "acoustic_stress":
        # distinct_states>=3, distinct<4 (else phase_boundary), warmth low,
        # no compute/energy dominant, no sensors.
        state[0, 0, 0] = STATE_STRUCTURAL
        state[0, 0, 1] = STATE_ENERGY
        # void + structural + energy = 3 distinct states; default
        # DIVERSITY_BOUNDARY is 4 so phase_boundary won't catch.
    elif branch == "unclassified":
        # We want NO predicate to fire. Hardest to construct. A patch
        # with: void_frac < FRACTION_MAJORITY, no dominance anywhere,
        # distinct_states < 3, no sensors, energy_count < min.
        # Try: half void, half structural with mature age (>= ANCIENT).
        # If FRACTION_MAJORITY is 0.5 (typical), set void_frac < 0.5 too.
        state[0, 0, 0] = STATE_STRUCTURAL
        state[0, 0, 1] = STATE_STRUCTURAL
        state[0, 0, 2] = STATE_STRUCTURAL
        state[0, 1, 0] = STATE_STRUCTURAL
        state[0, 1, 1] = STATE_STRUCTURAL
        state[0, 1, 2] = STATE_STRUCTURAL
        state[0, 2, 0] = STATE_STRUCTURAL
        state[0, 2, 1] = STATE_STRUCTURAL
        state[0, 2, 2] = STATE_STRUCTURAL
        state[1, 0, 0] = STATE_STRUCTURAL
        state[1, 0, 1] = STATE_STRUCTURAL
        state[1, 0, 2] = STATE_STRUCTURAL
        state[1, 1, 0] = STATE_STRUCTURAL
        # 13 structural / 27 = 0.48 < FRACTION_MAJORITY (0.5) but high
        # enough that void_frac is also < 0.5 -> nothing dominant.
        memory[CH["structural_age"], :, :, :] = float(AGE_SAGE)
        # structural_age_mean is SAGE (not < SAGE for growth, not >= ANCIENT
        # for decay), structural_frac < DOMINANT so neither growth nor decay
        # fire. distinct=2 not >=3. No sensors. compute=0, energy=0. The
        # only risk is acoustic_stress (distinct>=3) - here distinct=2.
    else:
        raise ValueError(f"unknown branch {branch}")
    return Patch(
        center=(R, R, R),
        state=state,
        memory=memory,
    )


def test_classify_patch_ablation_parity_with_observer_on_synthetic_battery():
    """Regression fence: non-ablated, non-reversed _classify_patch_ablation
    must agree with observer.classify_patch bit-for-bit on synthetic
    patches built to hit each ACTIVE cascade branch. Locks out silent
    drift between the calibration cascade mirror and the observer's
    source-of-truth cascade."""
    from scripts.nextness_observer import classify_patch as observer_classify
    branches = list(_ACTIVE_CASCADE_ORDER) + ["unclassified"]
    for branch in branches:
        patch = _make_synthetic_patch_for_branch(branch)
        observer_result = observer_classify(patch)
        calibration_result = _classify_patch_ablation(patch)
        assert observer_result == calibration_result, (
            f"parity drift on branch {branch!r}: "
            f"observer={observer_result!r} vs calibration={calibration_result!r}"
        )


def test_classify_patch_ablation_skips_disabled_token():
    """When a token's predicate would fire, disabling it must yield a
    different result — proves the ablation knob actually skips."""
    patch = _make_synthetic_patch_for_branch("phase_boundary")
    # Baseline: fires phase_boundary
    assert _classify_patch_ablation(patch) == "phase_boundary"
    # Ablation: must NOT return phase_boundary
    result = _classify_patch_ablation(
        patch, disabled_tokens=frozenset({"phase_boundary"})
    )
    assert result != "phase_boundary", (
        f"ablation did not skip phase_boundary; got {result!r}"
    )


def test_classify_patch_ablation_unclassified_when_all_active_disabled():
    """If every active cascade token is disabled, the patch must fall
    through to ``unclassified`` (the catch-all bucket)."""
    patch = _make_synthetic_patch_for_branch("phase_boundary")
    result = _classify_patch_ablation(
        patch, disabled_tokens=frozenset(_ACTIVE_CASCADE_ORDER)
    )
    assert result == "unclassified"


def test_classify_patch_ablation_reverse_order_differs_when_appropriate():
    """Reverse order must produce a different result for at least one
    patch where multiple predicates could fire (forward picks the
    most-specific; reversed picks the least-specific). Otherwise the
    reverse_order knob is a no-op and the chapter has nothing to probe."""
    # A patch that triggers both phase_boundary (specific) and void_birth
    # / void_static (less specific). Use the phase_boundary patch which
    # has multiple distinct states.
    patch = _make_synthetic_patch_for_branch("phase_boundary")
    forward = _classify_patch_ablation(patch, reverse_order=False)
    reversed_ = _classify_patch_ablation(patch, reverse_order=True)
    # forward should pick phase_boundary; reversed should pick something
    # later in the original cascade order (acoustic_stress / void_static).
    assert forward != reversed_, (
        f"reverse_order produced same result as forward: {forward!r}"
    )


# ---------------------------------------------------------------------------
# _ablation_modes_for_run
# ---------------------------------------------------------------------------


def test_ablation_modes_for_run_includes_baseline_first():
    """Baseline mode (when requested) must come first; downstream code
    relies on it being the reference for emerging-token comparison."""
    modes = _ablation_modes_for_run(
        disabled_tokens=("phase_boundary",),
        include_baseline=True,
        include_reverse=True,
    )
    assert modes[0]["label"] == "baseline"
    assert modes[0]["disabled_tokens"] == frozenset()
    assert modes[0]["reverse_order"] is False


def test_ablation_modes_for_run_skips_baseline_when_disabled():
    """include_baseline=False must omit the baseline mode entirely."""
    modes = _ablation_modes_for_run(
        disabled_tokens=("phase_boundary",),
        include_baseline=False,
        include_reverse=False,
    )
    labels = [m["label"] for m in modes]
    assert "baseline" not in labels


def test_ablation_modes_for_run_disable_modes_in_order():
    """disable_<token> modes must appear in disabled_tokens input order
    so the parameter_combination output is deterministic."""
    modes = _ablation_modes_for_run(
        disabled_tokens=("compute_static", "phase_boundary", "void_static"),
        include_baseline=False,
        include_reverse=False,
    )
    labels = [m["label"] for m in modes]
    assert labels == [
        "disable_compute_static",
        "disable_phase_boundary",
        "disable_void_static",
    ]


# ---------------------------------------------------------------------------
# _emerging_tokens_vs_baseline
# ---------------------------------------------------------------------------


def test_emerging_tokens_identifies_threshold_crossers():
    """A token below rate_threshold in baseline and above it in mode is
    emerging. Tokens that stay below or stay above don't count."""
    baseline = {"phase_boundary": 100, "void_static": 5, "metta_warmth": 0}
    # 100 total in baseline; phase_boundary=1.0, void_static=0.05, metta_warmth=0
    mode = {"compute_static": 20, "void_static": 60, "metta_warmth": 20}
    # 100 total in mode; compute_static=0.2 (emerging), void_static=0.6
    # (already > 5% in baseline at exactly 5%, but baseline is <= 5%, mode > 5%
    # -> qualifies), metta_warmth=0.2 (was 0, now 0.2 -> emerging)
    result = _emerging_tokens_vs_baseline(
        baseline_counts=baseline,
        mode_counts=mode,
        rate_threshold=0.05,
    )
    assert "compute_static" in result["emerging_tokens"]
    assert "metta_warmth" in result["emerging_tokens"]
    assert "phase_boundary" not in result["emerging_tokens"]  # was > 5%
    assert result["emerging_token_count"] == len(result["emerging_tokens"])


def test_emerging_tokens_handles_empty_baseline():
    """Empty baseline counts produce baseline_rate of 0 for everything,
    so any token above threshold in mode counts as emerging."""
    result = _emerging_tokens_vs_baseline(
        baseline_counts={},
        mode_counts={"a": 50, "b": 50},
        rate_threshold=0.05,
    )
    assert set(result["emerging_tokens"]) == {"a", "b"}


# ---------------------------------------------------------------------------
# ablate_cascade — input validation
# ---------------------------------------------------------------------------


def test_ablate_cascade_rejects_unknown_calibration_set(tmp_path):
    """calibration_set must be 'short' or 'long'."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    with pytest.raises(ValueError, match="calibration_set"):
        ablate_cascade([snap], out, log_path, "weekend", config)


def test_ablate_cascade_rejects_unknown_disabled_token(tmp_path):
    """Disabling a token name that isn't in the active cascade raises."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    with pytest.raises(ValueError, match="not an active cascade token"):
        ablate_cascade([snap], out, log_path, "short", config,
                       disabled_tokens=("not_a_real_token",))


def test_ablate_cascade_rejects_no_modes(tmp_path):
    """Empty disabled_tokens + include_baseline=False + include_reverse=False
    leaves no modes to run."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    with pytest.raises(ValueError, match="no modes selected"):
        ablate_cascade(
            [snap], out, log_path, "short", config,
            disabled_tokens=(),
            include_baseline=False,
            include_reverse=False,
        )


def test_ablate_cascade_rejects_outside_log_dir_output(tmp_path):
    """Inherits the write-boundary contract via
    _validate_calibration_output_path."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = tmp_path / "elsewhere" / "out.jsonl"
    with pytest.raises(WriteOutsideLogDirError, match="outside log_path"):
        ablate_cascade([snap], out, log_path, "short", config)


def test_ablate_cascade_rejects_mismatched_config_log_directory(tmp_path):
    """Inherits the config-log-directory guard from PR #149."""
    snaps_dir, log_path, _ = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    bad_config = ObserverConfig(
        log_directory=str(tmp_path / "bogus_for_ablate"),
        uniform_grid_stride=4,
        budget_seconds=30.0,
    )
    with pytest.raises(WriteOutsideLogDirError, match="config.log_directory"):
        ablate_cascade([snap], out, log_path, "short", bad_config)


# ---------------------------------------------------------------------------
# ablate_cascade — restore contract regression fences
# ---------------------------------------------------------------------------


def test_ablate_cascade_restores_classify_patch_after_run(tmp_path):
    """After normal exit, observer.classify_patch must be the original
    callable, not the monkey-patched ablating version."""
    from scripts import nextness_observer as _observer_module
    original_classifier = _observer_module.classify_patch
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    ablate_cascade(
        [snap], out, log_path, "short", config,
        disabled_tokens=("phase_boundary",),
        include_reverse=False,
    )
    assert _observer_module.classify_patch is original_classifier


def test_ablate_cascade_restores_classify_patch_even_if_process_snapshot_fails(
    tmp_path, monkeypatch
):
    """Mid-loop exception still triggers the try/finally restore. Locks
    the contract that no observer-state leak survives an exception."""
    from scripts import nextness_observer as _observer_module
    original_classifier = _observer_module.classify_patch
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"

    # Force process_snapshot to raise after one call to simulate mid-loop
    # failure. Patch it on the calibration module (where it was imported).
    call_count = {"n": 0}
    def _exploding_process_snapshot(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise RuntimeError("simulated mid-sweep failure")
        # First call - delegate to a minimal fake entry so the row builder works
        return {
            "snapshot_file": str(args[0].name) if args else "x.npz",
            "generation": 1,
            "token_counts": {"phase_boundary": 1},
            "vocabulary_occupancy": 0.5,
            "shannon_entropy_bits": 0.0,
            "entropy_normalized": 0.0,
            "void_compute_balance": 0.0,
            "boundary_rate": 0.0,
            "budget": {"patches_processed": 1},
        }
    monkeypatch.setattr(
        "scripts.nextness_calibration.process_snapshot",
        _exploding_process_snapshot,
    )

    with pytest.raises(RuntimeError, match="simulated mid-sweep failure"):
        ablate_cascade(
            [snap], out, log_path, "short", config,
            disabled_tokens=("phase_boundary",),
            include_reverse=False,
        )
    # Even with mid-loop exception, classify_patch must be restored.
    assert _observer_module.classify_patch is original_classifier


# ---------------------------------------------------------------------------
# ablate_cascade — output structure
# ---------------------------------------------------------------------------


def test_ablate_cascade_row_count_matches_snapshots_times_modes(tmp_path):
    """One per-snapshot row per (snapshot * mode), plus one aggregate row."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    s1 = _make_snapshot(snaps_dir / "v070_gen1_step1_a.npz", generation=1)
    s2 = _make_snapshot(snaps_dir / "v070_gen2_step2_b.npz", generation=2)
    out = log_path.parent / "out.jsonl"
    ablate_cascade(
        [s1, s2], out, log_path, "short", config,
        disabled_tokens=("phase_boundary", "compute_static"),  # 2 disable modes
        include_baseline=True,   # +1
        include_reverse=True,    # +1
    )
    # 4 modes per snapshot * 2 snapshots = 8 per-snapshot rows + 1 aggregate
    lines = out.read_text().splitlines()
    assert len(lines) == 9
    rows = [json.loads(l) for l in lines[:-1]]
    aggregate = json.loads(lines[-1])
    assert all(r.get("experiment") == "cascade_ablation" for r in rows)
    assert aggregate.get("experiment") == "cascade_ablation"


def test_ablate_cascade_per_row_carries_mode_in_parameter_combination(tmp_path):
    """parameter_combination per row carries mode + disabled_tokens + reverse_order."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    ablate_cascade(
        [snap], out, log_path, "short", config,
        disabled_tokens=("phase_boundary",),
        include_baseline=True,
        include_reverse=True,
    )
    rows = [json.loads(l) for l in out.read_text().splitlines()[:-1]]
    modes = [r["parameter_combination"]["mode"] for r in rows]
    assert modes == ["baseline", "disable_phase_boundary", "reverse_order"]
    # Disabled tokens echo back as sorted list
    for r in rows:
        if r["parameter_combination"]["mode"] == "disable_phase_boundary":
            assert r["parameter_combination"]["disabled_tokens"] == ["phase_boundary"]
            assert r["parameter_combination"]["reverse_order"] is False
        elif r["parameter_combination"]["mode"] == "reverse_order":
            assert r["parameter_combination"]["reverse_order"] is True


def test_ablate_cascade_aggregate_has_emerging_token_evidence(tmp_path):
    """Aggregate must expose per_mode_summary + emerging_token_evidence."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    aggregate = ablate_cascade(
        [snap], out, log_path, "short", config,
        disabled_tokens=("phase_boundary",),
        include_baseline=True,
        include_reverse=False,
    )
    assert "per_mode_summary" in aggregate
    assert "emerging_token_evidence" in aggregate
    assert "modes_run" in aggregate
    assert aggregate["modes_run"] == ["baseline", "disable_phase_boundary"]


# ---------------------------------------------------------------------------
# ablate_cascade — falsification logic
# ---------------------------------------------------------------------------


def test_ablate_cascade_inconclusive_when_baseline_omitted(tmp_path):
    """Without a baseline, the emerging-token criterion has no denominator
    -> inconclusive (even if other modes run)."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    aggregate = ablate_cascade(
        [snap], out, log_path, "short", config,
        disabled_tokens=("phase_boundary",),
        include_baseline=False,
        include_reverse=False,
    )
    assert aggregate["falsification_status"] == "inconclusive"


def test_ablate_cascade_inconclusive_when_only_baseline_requested(tmp_path):
    """Only baseline, no non-baseline modes -> no ablation to compare,
    falsification_status is inconclusive."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    aggregate = ablate_cascade(
        [snap], out, log_path, "short", config,
        disabled_tokens=(),
        include_baseline=True,
        include_reverse=False,
    )
    assert aggregate["falsification_status"] == "inconclusive"


# ---------------------------------------------------------------------------
# ablate_cascade — determinism contract
# ---------------------------------------------------------------------------


def test_ablate_cascade_no_fresh_generated_at_field(tmp_path):
    """No fresh wallclock-derived generated_at field in any row."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    ablate_cascade(
        [snap], out, log_path, "short", config,
        disabled_tokens=("phase_boundary",),
        include_reverse=False,
    )
    for line in out.read_text().splitlines():
        row = json.loads(line)
        assert "generated_at" not in row


def test_ablate_cascade_byte_identical_on_rerun(tmp_path):
    """Two back-to-back runs on the same input produce byte-identical
    output. Locks the determinism contract for this chapter."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz",
                          generation=1, lattice=16)
    out_a = log_path.parent / "calibration_ablate_a.jsonl"
    out_b = log_path.parent / "calibration_ablate_b.jsonl"
    ablate_cascade(
        [snap], out_a, log_path, "short", config,
        disabled_tokens=("phase_boundary",),
        include_reverse=True,
    )
    ablate_cascade(
        [snap], out_b, log_path, "short", config,
        disabled_tokens=("phase_boundary",),
        include_reverse=True,
    )
    assert out_a.read_bytes() == out_b.read_bytes()


def test_ablate_cascade_sorts_input_by_generation(tmp_path):
    """Per-snapshot rows in generation-ascending order regardless of input."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    s3 = _make_snapshot(snaps_dir / "v070_gen300_step3000_test.npz",
                        generation=300, lattice=16)
    s1 = _make_snapshot(snaps_dir / "v070_gen100_step1000_test.npz",
                        generation=100, lattice=16)
    s2 = _make_snapshot(snaps_dir / "v070_gen200_step2000_test.npz",
                        generation=200, lattice=16)
    out = log_path.parent / "out.jsonl"
    ablate_cascade(
        [s3, s1, s2], out, log_path, "short", config,
        disabled_tokens=(),
        include_baseline=True,
        include_reverse=False,
    )
    rows = [json.loads(l) for l in out.read_text().splitlines()[:-1]]
    generations = [r["snapshot_generation"] for r in rows]
    assert generations == [100, 200, 300]


# ===========================================================================
# Chapter 7 — sweep_temporal (design doc §3.2)
# ===========================================================================


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


def test_default_gap_specs_short_has_valid_entries():
    """Every DEFAULT_GAP_SPECS_SHORT entry is (str, positive int)."""
    assert DEFAULT_GAP_SPECS_SHORT  # non-empty
    for label, stride in DEFAULT_GAP_SPECS_SHORT:
        assert isinstance(label, str) and label
        assert isinstance(stride, int) and stride >= 1


def test_default_gap_specs_long_has_valid_entries():
    """Every DEFAULT_GAP_SPECS_LONG entry is (str, positive int)."""
    assert DEFAULT_GAP_SPECS_LONG  # non-empty
    for label, stride in DEFAULT_GAP_SPECS_LONG:
        assert isinstance(label, str) and label
        assert isinstance(stride, int) and stride >= 1


def test_default_gap_specs_ordered_ascending_for_falsification_semantics():
    """Last entry in gap_specs must be the LARGEST gap — the falsification
    check picks the last entry as the 'largest' by convention. Ordering
    short ascending: 1 < 6. Long ascending: 1 < 3 < 11."""
    short_strides = [s for _, s in DEFAULT_GAP_SPECS_SHORT]
    assert short_strides == sorted(short_strides)
    long_strides = [s for _, s in DEFAULT_GAP_SPECS_LONG]
    assert long_strides == sorted(long_strides)


# ---------------------------------------------------------------------------
# _temporal_pair_stats helper
# ---------------------------------------------------------------------------


def test_temporal_pair_stats_empty_list_returns_zeros():
    """Empty input returns all zeros — no values to compute over."""
    assert _temporal_pair_stats([]) == {"mean": 0.0, "std": 0.0, "max": 0.0}


def test_temporal_pair_stats_single_value_has_zero_std():
    """Sample std with n=1 has no denominator (n-1=0); helper returns 0.0
    rather than NaN/error to keep aggregate JSON serializable."""
    stats = _temporal_pair_stats([0.5])
    assert stats["mean"] == 0.5
    assert stats["std"] == 0.0
    assert stats["max"] == 0.5


def test_temporal_pair_stats_multiple_values_correct():
    """Sample std (n-1 denominator) on a known input."""
    # mean = 0.3, variance = ((0.1-0.3)^2 + (0.3-0.3)^2 + (0.5-0.3)^2) / 2
    #      = (0.04 + 0 + 0.04) / 2 = 0.04, std = 0.2
    stats = _temporal_pair_stats([0.1, 0.3, 0.5])
    assert abs(stats["mean"] - 0.3) < 1e-9
    assert abs(stats["std"] - 0.2) < 1e-9
    assert stats["max"] == 0.5


# ---------------------------------------------------------------------------
# sweep_temporal — input validation
# ---------------------------------------------------------------------------


def test_sweep_temporal_rejects_unknown_calibration_set(tmp_path):
    """calibration_set must be 'short' or 'long'."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    with pytest.raises(ValueError, match="calibration_set"):
        sweep_temporal([snap], out, log_path, "weekend", config)


def test_sweep_temporal_rejects_empty_gap_specs_when_explicit(tmp_path):
    """Empty gap_specs (when provided explicitly) is an error."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    with pytest.raises(ValueError, match="gap_specs"):
        sweep_temporal([snap], out, log_path, "short", config,
                       gap_specs=())


def test_sweep_temporal_rejects_non_positive_gap_stride(tmp_path):
    """Index stride must be a positive int."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    with pytest.raises(ValueError, match="index_stride"):
        sweep_temporal([snap], out, log_path, "short", config,
                       gap_specs=(("zero", 0),))


def test_sweep_temporal_rejects_empty_gap_label(tmp_path):
    """Each gap label must be a non-empty string."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    with pytest.raises(ValueError, match="label"):
        sweep_temporal([snap], out, log_path, "short", config,
                       gap_specs=(("", 1),))


def test_sweep_temporal_rejects_outside_log_dir_output(tmp_path):
    """Inherits the write-boundary contract."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = tmp_path / "elsewhere" / "out.jsonl"
    with pytest.raises(WriteOutsideLogDirError, match="outside log_path"):
        sweep_temporal([snap], out, log_path, "short", config)


def test_sweep_temporal_rejects_mismatched_config_log_directory(tmp_path):
    """Inherits the PR #149 config-log-directory guard."""
    snaps_dir, log_path, _ = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    bad_config = ObserverConfig(
        log_directory=str(tmp_path / "bogus_for_temporal"),
        uniform_grid_stride=4,
        budget_seconds=30.0,
    )
    with pytest.raises(WriteOutsideLogDirError, match="config.log_directory"):
        sweep_temporal([snap], out, log_path, "short", bad_config)


# ---------------------------------------------------------------------------
# sweep_temporal — defaults selection
# ---------------------------------------------------------------------------


def test_sweep_temporal_short_calibration_uses_short_default_gap_specs(tmp_path):
    """When gap_specs is omitted, 'short' uses DEFAULT_GAP_SPECS_SHORT."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snaps = [
        _make_snapshot(snaps_dir / f"v070_gen{i}_step{i*10}_test.npz",
                       generation=i, lattice=8)
        for i in range(1, 13)  # 12 snapshots so all default gaps produce >= 1 pair
    ]
    out = log_path.parent / "out.jsonl"
    aggregate = sweep_temporal(snaps, out, log_path, "short", config)
    expected = [list(g) for g in DEFAULT_GAP_SPECS_SHORT]
    assert aggregate["gap_specs"] == expected


def test_sweep_temporal_long_calibration_uses_long_default_gap_specs(tmp_path):
    """When gap_specs is omitted, 'long' uses DEFAULT_GAP_SPECS_LONG."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snaps = [
        _make_snapshot(snaps_dir / f"v070_gen{i}_step{i*10}_test.npz",
                       generation=i, lattice=8)
        for i in range(1, 13)
    ]
    out = log_path.parent / "out.jsonl"
    aggregate = sweep_temporal(snaps, out, log_path, "long", config)
    expected = [list(g) for g in DEFAULT_GAP_SPECS_LONG]
    assert aggregate["gap_specs"] == expected


# ---------------------------------------------------------------------------
# sweep_temporal — pair counting
# ---------------------------------------------------------------------------


def test_sweep_temporal_pair_count_for_stride_one(tmp_path):
    """N snapshots, gap stride 1 -> N-1 pairs."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snaps = [
        _make_snapshot(snaps_dir / f"v070_gen{i}_step{i*10}_test.npz",
                       generation=i, lattice=8)
        for i in range(1, 4)
    ]
    out = log_path.parent / "out.jsonl"
    aggregate = sweep_temporal(
        snaps, out, log_path, "short", config,
        gap_specs=(("adjacent", 1),),
    )
    # 3 - 1 = 2 pairs
    assert aggregate["per_gap_summary"]["adjacent"]["n_pairs"] == 2


def test_sweep_temporal_pair_count_for_larger_stride(tmp_path):
    """N snapshots, gap stride 2 -> N-2 pairs."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snaps = [
        _make_snapshot(snaps_dir / f"v070_gen{i}_step{i*10}_test.npz",
                       generation=i, lattice=8)
        for i in range(1, 4)
    ]
    out = log_path.parent / "out.jsonl"
    aggregate = sweep_temporal(
        snaps, out, log_path, "short", config,
        gap_specs=(("gap2", 2),),
    )
    assert aggregate["per_gap_summary"]["gap2"]["n_pairs"] == 1


def test_sweep_temporal_zero_pairs_when_stride_exceeds_snapshot_count(tmp_path):
    """Stride >= N -> 0 pairs for that gap. Falsification status must
    fall back to inconclusive with an explicit reason if the LARGEST
    gap has 0 pairs."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snaps = [
        _make_snapshot(snaps_dir / f"v070_gen{i}_step{i*10}_test.npz",
                       generation=i, lattice=8)
        for i in range(1, 3)  # only 2 snapshots
    ]
    out = log_path.parent / "out.jsonl"
    aggregate = sweep_temporal(
        snaps, out, log_path, "short", config,
        gap_specs=(("too_big", 5),),
    )
    assert aggregate["per_gap_summary"]["too_big"]["n_pairs"] == 0
    assert aggregate["falsification_status"] == "inconclusive"
    assert "0 pairs" in aggregate["falsification_evidence"]["reason"]


# ---------------------------------------------------------------------------
# sweep_temporal — falsification logic
# ---------------------------------------------------------------------------


def test_sweep_temporal_identical_snapshots_supports_hypothesis(tmp_path):
    """Identical snapshots produce JS=0 -> hypothesis_supported."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    # Make two snapshots with identical content but different generation
    # (engine-state-wise, identical token distributions are the canonical
    # "attractor confirmed" case).
    s1 = _make_snapshot(snaps_dir / "v070_gen1_step10_a.npz",
                        generation=1, lattice=8)
    s2 = _make_snapshot(snaps_dir / "v070_gen2_step20_b.npz",
                        generation=2, lattice=8)
    out = log_path.parent / "out.jsonl"
    aggregate = sweep_temporal(
        [s1, s2], out, log_path, "short", config,
        gap_specs=(("adjacent", 1),),
    )
    # Identical content -> JS_divergence = 0.0 -> well below attractor
    # threshold of 0.01 bits.
    assert aggregate["per_gap_summary"]["adjacent"]["mean_js_divergence_bits"] == 0.0
    assert aggregate["falsification_status"] == "hypothesis_supported"


def test_sweep_temporal_falsified_when_largest_gap_js_above_threshold(
    tmp_path, monkeypatch
):
    """Integration test for the hypothesis_falsified branch.

    Monkey-patches ``scripts.nextness_calibration._js_divergence`` to
    return a constant 0.2 bits (above the falsification threshold of
    0.1), then runs sweep_temporal end-to-end and asserts:

      1. falsification_status == "hypothesis_falsified"
      2. The largest gap's recorded mean_js_divergence_bits == 0.2
      3. The falsification_evidence carries the correct largest_gap_label
         and largest_gap_mean_js values

    This exercises the actual sweep_temporal code path through the
    falsification branch, not just the threshold constants — closing
    the gap Jack flagged in PR #153 review.
    """
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    # Three snapshots so the "two" gap has at least one pair.
    snaps = [
        _make_snapshot(snaps_dir / f"v070_gen{i}_step{i*10}_test.npz",
                       generation=i, lattice=8)
        for i in range(1, 4)
    ]
    out = log_path.parent / "out.jsonl"

    monkeypatch.setattr(
        "scripts.nextness_calibration._js_divergence",
        lambda a, b: 0.2,
    )

    aggregate = sweep_temporal(
        snaps, out, log_path, "short", config,
        gap_specs=(("adjacent", 1), ("two", 2)),
    )

    assert aggregate["falsification_status"] == "hypothesis_falsified"
    # Largest gap is "two" (last entry in gap_specs by convention).
    assert aggregate["per_gap_summary"]["two"]["mean_js_divergence_bits"] == 0.2
    evidence = aggregate["falsification_evidence"]
    assert evidence["largest_gap_label"] == "two"
    assert evidence["largest_gap_mean_js"] == 0.2


def test_sweep_temporal_inconclusive_when_largest_gap_js_in_middle_band(
    tmp_path, monkeypatch
):
    """Integration test for the inconclusive-band branch of the
    falsification logic. Mid-band JS (between 0.01 attractor threshold
    and 0.1 falsification threshold) should yield inconclusive with an
    explicit reason — not falsified, not supported."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snaps = [
        _make_snapshot(snaps_dir / f"v070_gen{i}_step{i*10}_test.npz",
                       generation=i, lattice=8)
        for i in range(1, 4)
    ]
    out = log_path.parent / "out.jsonl"

    monkeypatch.setattr(
        "scripts.nextness_calibration._js_divergence",
        lambda a, b: 0.05,  # in the (0.01, 0.1) inconclusive band
    )

    aggregate = sweep_temporal(
        snaps, out, log_path, "short", config,
        gap_specs=(("adjacent", 1),),
    )

    assert aggregate["falsification_status"] == "inconclusive"
    assert aggregate["per_gap_summary"]["adjacent"]["mean_js_divergence_bits"] == 0.05
    evidence = aggregate["falsification_evidence"]
    assert "between the attractor threshold" in evidence["reason"]


# ---------------------------------------------------------------------------
# sweep_temporal — output structure
# ---------------------------------------------------------------------------


def test_sweep_temporal_row_count_matches_sum_of_pairs_plus_aggregate(tmp_path):
    """Per-snapshot rows = sum over gap_specs of max(0, N - stride)."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snaps = [
        _make_snapshot(snaps_dir / f"v070_gen{i}_step{i*10}_test.npz",
                       generation=i, lattice=8)
        for i in range(1, 5)  # N=4
    ]
    out = log_path.parent / "out.jsonl"
    sweep_temporal(
        snaps, out, log_path, "short", config,
        gap_specs=(("adjacent", 1), ("two", 2)),  # 3 + 2 = 5 pairs total
    )
    lines = out.read_text().splitlines()
    # 5 per-snapshot rows + 1 aggregate
    assert len(lines) == 6


def test_sweep_temporal_per_row_carries_gap_label_and_snapshot_b(tmp_path):
    """Each per-snapshot row's parameter_combination carries gap_label,
    gap_index_stride, snapshot_b, generation_b, generation_diff."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    s1 = _make_snapshot(snaps_dir / "v070_gen1_step10_test.npz",
                        generation=1, lattice=8)
    s2 = _make_snapshot(snaps_dir / "v070_gen2_step20_test.npz",
                        generation=2, lattice=8)
    out = log_path.parent / "out.jsonl"
    sweep_temporal(
        [s1, s2], out, log_path, "short", config,
        gap_specs=(("adjacent", 1),),
    )
    rows = [json.loads(l) for l in out.read_text().splitlines()[:-1]]
    assert len(rows) == 1
    row = rows[0]
    pc = row["parameter_combination"]
    assert pc["gap_label"] == "adjacent"
    assert pc["gap_index_stride"] == 1
    assert pc["snapshot_b"] == s2.name
    assert pc["generation_b"] == 2
    assert pc["generation_diff"] == 1
    # metrics block carries js_divergence_bits + cci_drift
    assert "js_divergence_bits" in row["metrics"]
    assert "cci_drift" in row["metrics"]


def test_sweep_temporal_aggregate_has_per_gap_summary_and_evidence(tmp_path):
    """Aggregate must expose gap_specs, per_gap_summary, falsification_evidence."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    s1 = _make_snapshot(snaps_dir / "v070_gen1_step10_test.npz", generation=1)
    s2 = _make_snapshot(snaps_dir / "v070_gen2_step20_test.npz", generation=2)
    out = log_path.parent / "out.jsonl"
    aggregate = sweep_temporal(
        [s1, s2], out, log_path, "short", config,
        gap_specs=(("adjacent", 1),),
    )
    assert "gap_specs" in aggregate
    assert "per_gap_summary" in aggregate
    assert "falsification_evidence" in aggregate
    # Evidence carries the threshold constants
    evidence = aggregate["falsification_evidence"]
    assert evidence["js_falsification_threshold_bits"] == 0.1
    assert evidence["js_attractor_threshold_bits"] == 0.01


# ---------------------------------------------------------------------------
# sweep_temporal — process_snapshot caching (cost-control invariant)
# ---------------------------------------------------------------------------


def test_sweep_temporal_caches_process_snapshot_per_snapshot(tmp_path, monkeypatch):
    """Each unique snapshot must be processed at most once even when it
    appears in multiple gap-pair lists (e.g., snapshot[2] participates in
    both the 'adjacent' pair (2,3) and the 'gap-2' pair (0,2))."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snaps = [
        _make_snapshot(snaps_dir / f"v070_gen{i}_step{i*10}_test.npz",
                       generation=i, lattice=8)
        for i in range(1, 5)  # 4 snapshots
    ]
    out = log_path.parent / "out.jsonl"

    call_count = {"n": 0, "paths_seen": []}
    original = __import__("scripts.nextness_calibration",
                          fromlist=["process_snapshot"]).process_snapshot

    def _counting_process_snapshot(*args, **kwargs):
        call_count["n"] += 1
        call_count["paths_seen"].append(str(args[0]))
        return original(*args, **kwargs)

    monkeypatch.setattr(
        "scripts.nextness_calibration.process_snapshot",
        _counting_process_snapshot,
    )

    sweep_temporal(
        snaps, out, log_path, "short", config,
        gap_specs=(("adjacent", 1), ("two", 2)),  # both share endpoints
    )
    # Without cache: gap1 needs 4 entries (snap0..3 via pairs), gap2 needs
    # 4 entries again. With cache: 4 unique snapshots -> 4 process_snapshot
    # calls total.
    assert call_count["n"] == 4
    # Each snapshot path appears exactly once in the call list.
    assert len(set(call_count["paths_seen"])) == 4


# ---------------------------------------------------------------------------
# sweep_temporal — determinism contract
# ---------------------------------------------------------------------------


def test_sweep_temporal_no_fresh_generated_at_field(tmp_path):
    """No fresh wallclock-derived generated_at field in any row."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    s1 = _make_snapshot(snaps_dir / "v070_gen1_step10_test.npz", generation=1)
    s2 = _make_snapshot(snaps_dir / "v070_gen2_step20_test.npz", generation=2)
    out = log_path.parent / "out.jsonl"
    sweep_temporal(
        [s1, s2], out, log_path, "short", config,
        gap_specs=(("adjacent", 1),),
    )
    for line in out.read_text().splitlines():
        assert "generated_at" not in json.loads(line)


def test_sweep_temporal_byte_identical_on_rerun(tmp_path):
    """Two back-to-back runs on the same input produce byte-identical output."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    s1 = _make_snapshot(snaps_dir / "v070_gen1_step10_test.npz",
                        generation=1, lattice=16)
    s2 = _make_snapshot(snaps_dir / "v070_gen2_step20_test.npz",
                        generation=2, lattice=16)
    out_a = log_path.parent / "calibration_temporal_a.jsonl"
    out_b = log_path.parent / "calibration_temporal_b.jsonl"
    sweep_temporal([s1, s2], out_a, log_path, "short", config,
                   gap_specs=(("adjacent", 1),))
    sweep_temporal([s1, s2], out_b, log_path, "short", config,
                   gap_specs=(("adjacent", 1),))
    assert out_a.read_bytes() == out_b.read_bytes()


def test_sweep_temporal_sorts_input_by_generation(tmp_path):
    """Per-snapshot rows in generation-ascending order regardless of input."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    s3 = _make_snapshot(snaps_dir / "v070_gen300_step3000_c.npz",
                        generation=300, lattice=8)
    s1 = _make_snapshot(snaps_dir / "v070_gen100_step1000_a.npz",
                        generation=100, lattice=8)
    s2 = _make_snapshot(snaps_dir / "v070_gen200_step2000_b.npz",
                        generation=200, lattice=8)
    out = log_path.parent / "out.jsonl"
    sweep_temporal(
        [s3, s1, s2], out, log_path, "short", config,
        gap_specs=(("adjacent", 1),),
    )
    rows = [json.loads(l) for l in out.read_text().splitlines()[:-1]]
    # Anchor snapshot in each row is the earlier one; gens 100, 200
    generations = [r["snapshot_generation"] for r in rows]
    assert generations == [100, 200]


# ===========================================================================
# Chapter 8 — sweep_patch_radius (design doc §3.3)
# ===========================================================================


# ---------------------------------------------------------------------------
# Module constants + helpers
# ---------------------------------------------------------------------------


def test_default_patch_radii_includes_baseline():
    """DEFAULT_PATCH_RADII must include PATCH_RADIUS_BASELINE for the
    §3.3 falsification criterion to have a denominator."""
    assert PATCH_RADIUS_BASELINE in DEFAULT_PATCH_RADII


def test_default_patch_radii_has_at_least_two_radii():
    """A radius sweep needs at least 2 radii to compare anything."""
    assert len(DEFAULT_PATCH_RADII) >= 2


def test_patch_cell_count_correct_at_known_radii():
    """(2r+1)^3 cells per Moore-neighbourhood patch."""
    assert _patch_cell_count(1) == 27   # 3x3x3
    assert _patch_cell_count(2) == 125  # 5x5x5
    assert _patch_cell_count(3) == 343  # 7x7x7


def test_rescale_count_threshold_for_baseline_radius_unchanged():
    """A rescale from a radius to itself returns the same value."""
    assert _rescale_count_threshold_for_radius(3, 1, 1) == 3
    assert _rescale_count_threshold_for_radius(14, 2, 2) == 14


def test_rescale_count_threshold_proportional_to_volume_ratio():
    """ENERGY_PULSE_MIN_COUNT=3 at r=1 (27 cells, fraction 3/27 = 0.111)
    rescales at r=2 (125 cells) to round(3 * 125/27) = 14
    (fraction 14/125 = 0.112, matching baseline within rounding)."""
    assert _rescale_count_threshold_for_radius(3, 1, 2) == 14


def test_rescale_count_threshold_clamps_to_one_minimum():
    """A rescaled threshold cannot drop below 1 (a count of 0 would be
    a no-op trigger; clamp prevents that pathology)."""
    # baseline=1 at r=2 rescales DOWN to r=1 → round(1 * 27/125) = round(0.216) = 0
    # → clamped to 1.
    assert _rescale_count_threshold_for_radius(1, 2, 1) == 1


def test_clone_config_with_radius_preserves_other_fields(tmp_path):
    """_clone_config_with_radius must change only patch_spatial_radius,
    leaving stride/budget/log_directory etc. untouched."""
    base = ObserverConfig(
        log_directory="/tmp/test_log",
        uniform_grid_stride=8,
        budget_seconds=42.0,
        patch_spatial_radius=1,
    )
    clone = _clone_config_with_radius(base, 2)
    assert clone.patch_spatial_radius == 2
    assert clone.log_directory == base.log_directory
    assert clone.uniform_grid_stride == base.uniform_grid_stride
    assert clone.budget_seconds == base.budget_seconds
    # Original unchanged (frozen dataclass)
    assert base.patch_spatial_radius == 1


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_sweep_patch_radius_rejects_unknown_calibration_set(tmp_path):
    """calibration_set must be 'short' or 'long'."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    with pytest.raises(ValueError, match="calibration_set"):
        sweep_patch_radius([snap], out, log_path, "weekend", config)


def test_sweep_patch_radius_rejects_empty_radii(tmp_path):
    """Empty radii tuple is an error."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    with pytest.raises(ValueError, match="radii"):
        sweep_patch_radius([snap], out, log_path, "short", config, radii=())


def test_sweep_patch_radius_rejects_non_positive_radius(tmp_path):
    """Radius must be a positive int."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    with pytest.raises(ValueError, match="radius"):
        sweep_patch_radius([snap], out, log_path, "short", config,
                           radii=(0,))


def test_sweep_patch_radius_rejects_outside_log_dir_output(tmp_path):
    """Inherits the write-boundary contract."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = tmp_path / "elsewhere" / "out.jsonl"
    with pytest.raises(WriteOutsideLogDirError, match="outside log_path"):
        sweep_patch_radius([snap], out, log_path, "short", config)


def test_sweep_patch_radius_rejects_mismatched_config_log_directory(tmp_path):
    """Inherits the PR #149 config-log-directory guard."""
    snaps_dir, log_path, _ = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    bad_config = ObserverConfig(
        log_directory=str(tmp_path / "bogus_for_radius"),
        uniform_grid_stride=4,
        budget_seconds=30.0,
    )
    with pytest.raises(WriteOutsideLogDirError, match="config.log_directory"):
        sweep_patch_radius([snap], out, log_path, "short", bad_config)


# ---------------------------------------------------------------------------
# Restore contract regression fences
# ---------------------------------------------------------------------------


def test_sweep_patch_radius_restores_count_thresholds_after_run(tmp_path):
    """After normal exit, observer count thresholds must be the original
    values, not the rescaled per-radius values."""
    from scripts import nextness_observer as _observer_module
    original_pulse = _observer_module.ENERGY_PULSE_MIN_COUNT

    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    sweep_patch_radius([snap], out, log_path, "short", config, radii=(1, 2))
    assert _observer_module.ENERGY_PULSE_MIN_COUNT == original_pulse


def test_sweep_patch_radius_restores_count_thresholds_even_if_process_snapshot_fails(
    tmp_path, monkeypatch
):
    """Mid-loop exception still triggers the try/finally restore. Locks
    the contract that no observer-state leak survives an exception."""
    from scripts import nextness_observer as _observer_module
    original_pulse = _observer_module.ENERGY_PULSE_MIN_COUNT

    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"

    def _exploding_process_snapshot(*args, **kwargs):
        raise RuntimeError("simulated mid-sweep failure")

    monkeypatch.setattr(
        "scripts.nextness_calibration.process_snapshot",
        _exploding_process_snapshot,
    )

    with pytest.raises(RuntimeError, match="simulated"):
        sweep_patch_radius([snap], out, log_path, "short", config, radii=(1, 2))

    # ENERGY_PULSE_MIN_COUNT restored even though we crashed mid-loop.
    assert _observer_module.ENERGY_PULSE_MIN_COUNT == original_pulse


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------


def test_sweep_patch_radius_row_count_matches_snapshots_times_radii(tmp_path):
    """One per-snapshot row per (snapshot * radius), plus one aggregate row."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    s1 = _make_snapshot(snaps_dir / "v070_gen1_step1_a.npz", generation=1)
    s2 = _make_snapshot(snaps_dir / "v070_gen2_step2_b.npz", generation=2)
    out = log_path.parent / "out.jsonl"
    sweep_patch_radius([s1, s2], out, log_path, "short", config, radii=(1, 2))
    lines = out.read_text().splitlines()
    # 2 radii * 2 snapshots = 4 per-snapshot rows + 1 aggregate
    assert len(lines) == 5


def test_sweep_patch_radius_per_row_carries_radius_and_rescaled_thresholds(tmp_path):
    """parameter_combination per row carries patch_spatial_radius,
    patch_cell_count, and rescaled_count_thresholds."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    sweep_patch_radius([snap], out, log_path, "short", config, radii=(1, 2))
    rows = [json.loads(l) for l in out.read_text().splitlines()[:-1]]
    assert len(rows) == 2
    # Row 0: radius 1
    pc0 = rows[0]["parameter_combination"]
    assert pc0["patch_spatial_radius"] == 1
    assert pc0["patch_cell_count"] == 27
    assert pc0["rescaled_count_thresholds"]["ENERGY_PULSE_MIN_COUNT"] == 3
    # Row 1: radius 2
    pc1 = rows[1]["parameter_combination"]
    assert pc1["patch_spatial_radius"] == 2
    assert pc1["patch_cell_count"] == 125
    assert pc1["rescaled_count_thresholds"]["ENERGY_PULSE_MIN_COUNT"] == 14


def test_sweep_patch_radius_aggregate_has_per_radius_summary_and_evidence(tmp_path):
    """Aggregate must expose per_radius_summary, cross_radius_diffs,
    falsification_evidence (with baseline_radius + threshold embedded)."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    aggregate = sweep_patch_radius(
        [snap], out, log_path, "short", config, radii=(1, 2),
    )
    assert "per_radius_summary" in aggregate
    assert "cross_radius_diffs" in aggregate
    assert "falsification_evidence" in aggregate
    assert aggregate["baseline_radius"] == 1
    assert "ENERGY_PULSE_MIN_COUNT" in aggregate["rescaled_threshold_names"]
    evidence = aggregate["falsification_evidence"]
    assert evidence["baseline_radius"] == 1
    assert evidence["cci_falsification_threshold"] == 0.10


# ---------------------------------------------------------------------------
# Falsification logic
# ---------------------------------------------------------------------------


def test_sweep_patch_radius_inconclusive_when_baseline_not_in_radii(tmp_path):
    """Without baseline radius in the sweep, no reference to diff against
    -> inconclusive with explicit reason."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    aggregate = sweep_patch_radius(
        [snap], out, log_path, "short", config, radii=(2,),
    )
    assert aggregate["falsification_status"] == "inconclusive"
    assert "baseline radius" in aggregate["falsification_evidence"]["reason"]


def test_sweep_patch_radius_inconclusive_when_only_baseline_requested(tmp_path):
    """Only baseline radius, no comparison radius -> inconclusive."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    aggregate = sweep_patch_radius(
        [snap], out, log_path, "short", config, radii=(1,),
    )
    assert aggregate["falsification_status"] == "inconclusive"
    assert "comparison radius" in aggregate["falsification_evidence"]["reason"]


def test_sweep_patch_radius_falsified_when_cci_diff_exceeds_threshold(
    tmp_path, monkeypatch
):
    """Integration test for the hypothesis_falsified branch.

    Monkey-patches process_snapshot to return entries with hand-crafted
    token_counts and per-snapshot fields that produce a CCI difference
    larger than the 0.10 falsification threshold between radius 1 and
    radius 2. Asserts:

      1. falsification_status == "hypothesis_falsified"
      2. max_abs_cci_diff > 0.10
      3. The triggering radius is recorded

    This exercises the actual sweep_patch_radius code path through the
    falsification branch (closing the same class of gap Jack flagged
    on PR #153)."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"

    call_count = {"n": 0}
    # CCI = balance * boundary * (1 - entropy_norm). Engineer two entries
    # such that the CCI difference exceeds the 0.10 falsification threshold.
    #   r=1: balance=0.8, boundary=0.5, entropy_norm=0.0 -> CCI = 0.4
    #   r=2: balance=0.0, boundary=0.0, entropy_norm=1.0 -> CCI = 0.0
    #   |diff| = 0.4 > 0.10 -> hypothesis_falsified
    fake_entries = [
        {  # radius 1 invocation: high CCI
            "snapshot_file": snap.name,
            "generation": 1,
            "token_counts": {"a": 60, "b": 40},
            "vocabulary_occupancy": 0.4,
            "shannon_entropy_bits": 0.97,
            "entropy_normalized": 0.0,
            "void_compute_balance": 0.8,
            "boundary_rate": 0.5,
            "budget": {"patches_processed": 100},
        },
        {  # radius 2 invocation: low CCI
            "snapshot_file": snap.name,
            "generation": 1,
            "token_counts": {"a": 100},
            "vocabulary_occupancy": 0.1,
            "shannon_entropy_bits": 0.0,
            "entropy_normalized": 1.0,
            "void_compute_balance": 0.0,
            "boundary_rate": 0.0,
            "budget": {"patches_processed": 100},
        },
    ]

    def _fake_process_snapshot(*args, **kwargs):
        entry = fake_entries[call_count["n"]]
        call_count["n"] += 1
        return entry

    monkeypatch.setattr(
        "scripts.nextness_calibration.process_snapshot",
        _fake_process_snapshot,
    )

    aggregate = sweep_patch_radius(
        [snap], out, log_path, "short", config, radii=(1, 2),
    )

    assert aggregate["falsification_status"] == "hypothesis_falsified"
    evidence = aggregate["falsification_evidence"]
    assert evidence["max_abs_cci_diff"] > 0.10
    assert evidence["max_abs_diff_radius"] == 2


def test_sweep_patch_radius_supported_when_cci_diff_within_threshold(
    tmp_path, monkeypatch
):
    """Integration test for the hypothesis_supported branch.

    Engineer two entries where r=1 and r=2 produce nearly-identical CCI
    (within 0.10 absolute). Assert falsification_status =
    hypothesis_supported and max_abs_cci_diff is recorded below threshold."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"

    call_count = {"n": 0}
    # Both radii: identical metrics -> CCI diff = 0
    fake_entry = {
        "snapshot_file": snap.name,
        "generation": 1,
        "token_counts": {"a": 60, "b": 40},
        "vocabulary_occupancy": 0.3,
        "shannon_entropy_bits": 0.9,
        "entropy_normalized": 0.9,
        "void_compute_balance": 0.1,
        "boundary_rate": 0.4,
        "budget": {"patches_processed": 100},
    }

    def _fake_process_snapshot(*args, **kwargs):
        call_count["n"] += 1
        return dict(fake_entry)

    monkeypatch.setattr(
        "scripts.nextness_calibration.process_snapshot",
        _fake_process_snapshot,
    )

    aggregate = sweep_patch_radius(
        [snap], out, log_path, "short", config, radii=(1, 2),
    )

    assert aggregate["falsification_status"] == "hypothesis_supported"
    evidence = aggregate["falsification_evidence"]
    assert evidence["max_abs_cci_diff"] <= 0.10


# ---------------------------------------------------------------------------
# Determinism contract
# ---------------------------------------------------------------------------


def test_sweep_patch_radius_no_fresh_generated_at_field(tmp_path):
    """No fresh wallclock-derived generated_at field in any row."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz", generation=1)
    out = log_path.parent / "out.jsonl"
    sweep_patch_radius([snap], out, log_path, "short", config, radii=(1, 2))
    for line in out.read_text().splitlines():
        assert "generated_at" not in json.loads(line)


def test_sweep_patch_radius_byte_identical_on_rerun(tmp_path):
    """Two back-to-back runs on the same input produce byte-identical output."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    snap = _make_snapshot(snaps_dir / "v070_gen1_step1_test.npz",
                          generation=1, lattice=16)
    out_a = log_path.parent / "calibration_radius_a.jsonl"
    out_b = log_path.parent / "calibration_radius_b.jsonl"
    sweep_patch_radius([snap], out_a, log_path, "short", config, radii=(1, 2))
    sweep_patch_radius([snap], out_b, log_path, "short", config, radii=(1, 2))
    assert out_a.read_bytes() == out_b.read_bytes()


def test_sweep_patch_radius_sorts_input_by_generation(tmp_path):
    """Per-snapshot rows in generation-ascending order regardless of input."""
    snaps_dir, log_path, config = _calibration_setup(tmp_path)
    s3 = _make_snapshot(snaps_dir / "v070_gen300_step3000_c.npz",
                        generation=300, lattice=8)
    s1 = _make_snapshot(snaps_dir / "v070_gen100_step1000_a.npz",
                        generation=100, lattice=8)
    s2 = _make_snapshot(snaps_dir / "v070_gen200_step2000_b.npz",
                        generation=200, lattice=8)
    out = log_path.parent / "out.jsonl"
    sweep_patch_radius(
        [s3, s1, s2], out, log_path, "short", config, radii=(1,),
    )
    rows = [json.loads(l) for l in out.read_text().splitlines()[:-1]]
    generations = [r["snapshot_generation"] for r in rows]
    assert generations == [100, 200, 300]
