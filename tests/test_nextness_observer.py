"""Tests for scripts/nextness_observer.py — Phase 19 PR #2.

Locks down each §7 safety invariant with a dedicated test, plus
classifier-token coverage, sampler/budget mechanics, and an end-to-end
process_snapshot round-trip.

Per the design doc: this is the regression-fence layer. PR #3 (metrics
pipeline) will add semantic tests on the OUTPUT of the observer; this
PR just locks down the SHAPE of it.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import os
import pathlib
import stat
import time

import numpy as np
import pytest

from scripts import nextness_observer
from scripts.nextness_observer import (
    AGE_ANCIENT,
    AGE_LEGEND,
    AGE_SAGE,
    BudgetMonitor,
    BudgetReport,
    DEFAULT_COST_PER_PATCH_SECONDS,
    DenseModeWhileLiveError,
    MEMORY_CHANNEL_LAYOUT,
    ObserverConfig,
    ObserverSafetyError,
    Patch,
    SamplingMode,
    STATE_COMPUTE,
    STATE_ENERGY,
    STATE_SENSOR,
    STATE_STRUCTURAL,
    STATE_VOID,
    THRESHOLD_COMPASSION,
    THRESHOLD_RESONANCE,
    THRESHOLD_WARMTH,
    TOKEN_BY_INDEX,
    TOKEN_INDEX,
    TOKEN_NAMES,
    WriteOutsideLogDirError,
    ZmqUseInPR2Error,
    boundary_rate,
    classify_patch,
    compute_safe_stride,
    entropy_normalized,
    find_latest_snapshot,
    is_medusa_live,
    iter_dense_patches,
    iter_importance_patches,
    iter_patches,
    iter_uniform_grid_patches,
    load_snapshot,
    process_snapshot,
    shannon_entropy_bits,
    void_compute_balance,
    write_log_entry,
)


CH = MEMORY_CHANNEL_LAYOUT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _zero_patch(state_fill: int = STATE_VOID, channels: dict[str, float] | None = None) -> Patch:
    """Build a 3x3x3 patch with the given uniform state and optional channel values."""
    s = np.full((3, 3, 3), state_fill, dtype=np.uint8)
    m = np.zeros((8, 3, 3, 3), dtype=np.float32)
    if channels:
        for name, val in channels.items():
            m[CH[name]].fill(val)
    return Patch(center=(0, 0, 0), state=s, memory=m)


def _make_snapshot(path: pathlib.Path, lattice: int = 32, generation: int = 100,
                    pad_bytes: int = 0) -> pathlib.Path:
    """Create a synthetic Medusa-format .npz snapshot, optionally padded."""
    state = np.zeros((lattice, lattice, lattice), dtype=np.uint8)
    state[::4, ::4, ::4] = STATE_COMPUTE
    memory = np.zeros((8, lattice, lattice, lattice), dtype=np.float32)
    memory[CH["compute_age"]].fill(15.0)
    extras = {}
    if pad_bytes > 0:
        extras["padding"] = np.zeros(pad_bytes // 4, dtype=np.float32)
    np.savez(
        str(path),
        lattice=state, memory_grid=memory,
        generation=np.array(generation), best_fitness=np.array(0.5),
        **extras,
    )
    return path


# ---------------------------------------------------------------------------
# Vocabulary integrity (Chunk 1)
# ---------------------------------------------------------------------------


def test_vocabulary_size_is_exactly_16():
    assert len(TOKEN_NAMES) == 16


def test_vocabulary_names_unique():
    assert len(set(TOKEN_NAMES)) == 16


def test_token_index_round_trip():
    for i, name in enumerate(TOKEN_NAMES):
        assert TOKEN_BY_INDEX[i] == name
        assert TOKEN_INDEX[name] == i


# ---------------------------------------------------------------------------
# ObserverConfig (Chunk 1)
# ---------------------------------------------------------------------------


def test_config_defaults_sensible():
    c = ObserverConfig()
    assert c.sampling_mode is SamplingMode.UNIFORM_GRID
    assert c.uniform_grid_stride == 8
    assert c.patch_spatial_radius == 1
    assert c.budget_seconds == 30.0
    assert c.use_gpu is False
    assert c.allow_dense_mode is False


def test_config_from_env_reads_budget(monkeypatch):
    monkeypatch.setenv("MEDUSA_OBSERVER_BUDGET_S", "90")
    c = ObserverConfig.from_env()
    assert c.budget_seconds == 90.0


def test_config_from_env_reads_stride(monkeypatch):
    monkeypatch.setenv("MEDUSA_OBSERVER_STRIDE", "16")
    c = ObserverConfig.from_env()
    assert c.uniform_grid_stride == 16


def test_config_budget_below_floor_raises():
    with pytest.raises(ValueError, match="below floor"):
        ObserverConfig(budget_seconds=2.0)


def test_config_dense_without_allow_raises():
    with pytest.raises(ValueError, match="DENSE"):
        ObserverConfig(sampling_mode=SamplingMode.DENSE)


def test_config_stride_zero_raises():
    with pytest.raises(ValueError, match="uniform_grid_stride"):
        ObserverConfig(uniform_grid_stride=0)


# ---------------------------------------------------------------------------
# Sampler (Chunk 2)
# ---------------------------------------------------------------------------


def test_sampler_uniform_grid_count_matches_range_math():
    state = np.zeros((16, 16, 16), dtype=np.uint8)
    memory = np.zeros((8, 16, 16, 16), dtype=np.float32)
    patches = list(iter_uniform_grid_patches(state, memory, stride=4, radius=1))
    # range(1, 15, 4) = [1, 5, 9, 13] → 4 per axis, 4^3 total
    assert len(patches) == 64


def test_sampler_returns_zero_copy_views():
    state = np.zeros((16, 16, 16), dtype=np.uint8)
    state[5, 5, 5] = STATE_COMPUTE
    memory = np.zeros((8, 16, 16, 16), dtype=np.float32)
    patches = list(iter_uniform_grid_patches(state, memory, stride=4, radius=1))
    p = next(p for p in patches if p.center == (5, 5, 5))
    # The view's centre cell should reflect the source array, and the
    # view must share the source's underlying buffer (zero-copy).
    assert p.state[1, 1, 1] == STATE_COMPUTE
    assert p.state.base is state


def test_sampler_dispatcher_routes_uniform_grid():
    state = np.zeros((16, 16, 16), dtype=np.uint8)
    memory = np.zeros((8, 16, 16, 16), dtype=np.float32)
    cfg = ObserverConfig(uniform_grid_stride=4)
    n = sum(1 for _ in iter_patches(state, memory, cfg))
    assert n == 64


def test_sampler_importance_stub_raises_naming_pr():
    state = np.zeros((16, 16, 16), dtype=np.uint8)
    memory = np.zeros((8, 16, 16, 16), dtype=np.float32)
    with pytest.raises(NotImplementedError, match="PR #3"):
        list(iter_importance_patches(state, memory))


def test_sampler_dense_stub_raises_naming_pr():
    state = np.zeros((16, 16, 16), dtype=np.uint8)
    memory = np.zeros((8, 16, 16, 16), dtype=np.float32)
    with pytest.raises(NotImplementedError, match="PR #4"):
        list(iter_dense_patches(state, memory))


def test_sampler_dispatcher_dense_refuses_when_live():
    state = np.zeros((16, 16, 16), dtype=np.uint8)
    memory = np.zeros((8, 16, 16, 16), dtype=np.float32)
    cfg = ObserverConfig(sampling_mode=SamplingMode.DENSE,
                          allow_dense_mode=True, uniform_grid_stride=4)
    with pytest.raises(DenseModeWhileLiveError):
        list(iter_patches(state, memory, cfg, medusa_is_live=True))


def test_sampler_validation_1d_state_raises():
    with pytest.raises(ValueError, match="3D"):
        list(iter_uniform_grid_patches(np.zeros((4,)), np.zeros((8, 4, 4, 4))))


def test_sampler_validation_stride_zero_raises():
    state = np.zeros((16, 16, 16), dtype=np.uint8)
    memory = np.zeros((8, 16, 16, 16), dtype=np.float32)
    with pytest.raises(ValueError, match="stride"):
        list(iter_uniform_grid_patches(state, memory, stride=0))


def test_sampler_validation_too_small_lattice_raises():
    with pytest.raises(ValueError, match="smaller than patch window"):
        list(iter_uniform_grid_patches(
            np.zeros((2, 2, 2), dtype=np.uint8),
            np.zeros((8, 2, 2, 2), dtype=np.float32),
        ))


# ---------------------------------------------------------------------------
# Classifier (Chunk 3) — one test per token, plus cascade-order regressions
# ---------------------------------------------------------------------------


def test_classifier_void_static():
    assert classify_patch(_zero_patch()) == "void_static"


def test_classifier_compute_static_when_juvenile():
    assert classify_patch(_zero_patch(STATE_COMPUTE)) == "compute_static"


def test_classifier_compute_aging_at_sage_age():
    p = _zero_patch(STATE_COMPUTE, {"compute_age": AGE_SAGE + 1.0})
    assert classify_patch(p) == "compute_aging"


def test_classifier_magnon_lighthouse_disabled_post_144_falls_through_to_compute_aging():
    """Post-issue-#144: magnon_lighthouse is disabled (status: derived_future).
    A COMPUTE-dominant patch at Legend-tier age now falls through to the
    next-priority predicate, ``compute_aging``, since AGE_LEGEND > AGE_SAGE.
    """
    p = _zero_patch(STATE_COMPUTE, {"compute_age": AGE_LEGEND + 5.0})
    result = classify_patch(p)
    assert result != "magnon_lighthouse", (
        "magnon_lighthouse should never fire post-#144 (channel is "
        "derived, not stored; disabled until observer implements the "
        "derivation)"
    )
    assert result == "compute_aging", (
        f"Expected cascade fallthrough to compute_aging; got {result!r}"
    )


def test_classifier_metta_warmth_demoted_to_diagnostic_falls_through():
    """Post-Workstream-B/C (PR #163): metta_warmth is status
    "diagnostic_only" and no longer routes classification. A patch that
    *would have* triggered the old predicate (a COMPUTE cell with warmth
    above THRESHOLD_WARMTH) must now fall through the cascade instead of
    returning metta_warmth.

    Here: 1 COMPUTE in a 26-VOID patch with warmth filled to 0.4 (> 0.3).
    metta_warmth is skipped; compute_decay needs warmth_mean < THRESHOLD
    (fails, warmth is high); the patch lands on void_birth (void-dominant
    with >1 distinct state).
    """
    s = np.zeros((3, 3, 3), dtype=np.uint8); s[1, 1, 1] = STATE_COMPUTE
    m = np.zeros((8, 3, 3, 3), dtype=np.float32)
    m[CH["warmth"]].fill(THRESHOLD_WARMTH + 0.1)
    result = classify_patch(Patch((0, 0, 0), s, m))
    assert result != "metta_warmth", (
        f"metta_warmth must not fire after diagnostic_only demotion; got {result!r}"
    )
    assert result == "void_birth", (
        f"expected fall-through to void_birth; got {result!r}"
    )


def test_classifier_mudita_resonance_disabled_post_144_falls_through_to_compute_decay():
    """Post-issue-#144: mudita_resonance is disabled (status:
    deprecated_no_engine_channel) — the engine has no resonance channel.
    A patch that *would have* triggered the old predicate now falls
    through to compute_decay (1 COMPUTE in mostly-VOID cold patch).

    Setup must not use CH["resonance"] (the key was removed); we just
    place a COMPUTE cell in a VOID-dominant patch with all-zero memory.
    """
    s = np.zeros((3, 3, 3), dtype=np.uint8); s[1, 1, 1] = STATE_COMPUTE
    m = np.zeros((8, 3, 3, 3), dtype=np.float32)
    result = classify_patch(Patch((0, 0, 0), s, m))
    assert result != "mudita_resonance", (
        "mudita_resonance should never fire post-#144"
    )
    assert result == "compute_decay", (
        f"Expected cascade fallthrough to compute_decay; got {result!r}"
    )


def test_classifier_karuna_relief_disabled_post_144_falls_through_to_compute_decay():
    """Post-issue-#144: karuna_relief is disabled (status:
    deprecated_no_engine_channel) — the engine has no compassion channel.
    A patch that *would have* triggered the old predicate now falls
    through to compute_decay.

    Setup must not use CH["compassion"] (the key was removed); we just
    place a COMPUTE cell in a VOID-dominant patch with all-zero memory.
    """
    s = np.zeros((3, 3, 3), dtype=np.uint8); s[1, 1, 1] = STATE_COMPUTE
    m = np.zeros((8, 3, 3, 3), dtype=np.float32)
    result = classify_patch(Patch((0, 0, 0), s, m))
    assert result != "karuna_relief", (
        "karuna_relief should never fire post-#144"
    )
    assert result == "compute_decay", (
        f"Expected cascade fallthrough to compute_decay; got {result!r}"
    )


def test_classifier_sensor_alert():
    s = np.zeros((3, 3, 3), dtype=np.uint8); s[1, 1, 1] = STATE_SENSOR
    m = np.zeros((8, 3, 3, 3), dtype=np.float32)
    assert classify_patch(Patch((0, 0, 0), s, m)) == "sensor_alert"


def test_classifier_energy_pulse():
    s = np.zeros((3, 3, 3), dtype=np.uint8)
    s[0, 0, 0] = STATE_ENERGY
    s[1, 1, 1] = STATE_ENERGY
    s[2, 2, 2] = STATE_ENERGY
    m = np.zeros((8, 3, 3, 3), dtype=np.float32)
    assert classify_patch(Patch((0, 0, 0), s, m)) == "energy_pulse"


def test_classifier_structural_growth_when_young():
    p = _zero_patch(STATE_STRUCTURAL, {"structural_age": 2.0})
    assert classify_patch(p) == "structural_growth"


def test_classifier_structural_decay_when_mature():
    p = _zero_patch(STATE_STRUCTURAL, {"structural_age": AGE_ANCIENT + 5.0})
    assert classify_patch(p) == "structural_decay"


def test_classifier_void_birth_when_void_dom_with_diversity():
    s = np.full((3, 3, 3), STATE_VOID, dtype=np.uint8)
    s[1, 1, 1] = STATE_STRUCTURAL  # 1 non-void → distinct=2
    m = np.zeros((8, 3, 3, 3), dtype=np.float32)
    assert classify_patch(Patch((0, 0, 0), s, m)) == "void_birth"


def test_classifier_phase_boundary_with_max_diversity():
    s = np.zeros((3, 3, 3), dtype=np.uint8)
    s[0, 0, 0] = STATE_VOID
    s[1, 0, 0] = STATE_STRUCTURAL
    s[2, 0, 0] = STATE_COMPUTE
    s[0, 1, 0] = STATE_ENERGY
    s[1, 1, 0] = STATE_SENSOR
    m = np.zeros((8, 3, 3, 3), dtype=np.float32)
    assert classify_patch(Patch((0, 0, 0), s, m)) == "phase_boundary"


def test_classifier_acoustic_stress_when_diverse_cold_no_dominance():
    # Need 3 distinct + warmth=0 + no dominant fraction to reach token 15.
    # 12 VOID + 13 STRUCTURAL (mid-age) + 2 ENERGY: void_frac=0.44,
    # structural_frac=0.48, neither ≥0.5 → falls through to acoustic_stress.
    s = np.full((3, 3, 3), STATE_VOID, dtype=np.uint8)
    s.flat[:13] = STATE_STRUCTURAL
    s.flat[13] = STATE_ENERGY
    s.flat[14] = STATE_ENERGY
    m = np.zeros((8, 3, 3, 3), dtype=np.float32)
    m[CH["structural_age"]].fill(15.0)
    result = classify_patch(Patch((0, 0, 0), s, m))
    assert result == "acoustic_stress", f"got {result!r}; cascade landed wrong"


def test_classifier_unclassified_when_nothing_else_fits():
    # 14 STRUCTURAL mid-age + 13 VOID, no signals → no rule matches → unclassified.
    s = np.full((3, 3, 3), STATE_VOID, dtype=np.uint8)
    s.flat[:14] = STATE_STRUCTURAL
    m = np.zeros((8, 3, 3, 3), dtype=np.float32)
    m[CH["structural_age"]].fill(15.0)
    assert classify_patch(Patch((0, 0, 0), s, m)) == "unclassified"


def test_classifier_compute_decay_dominates_when_cold_void_with_compute():
    # VOID-dominant with one COMPUTE cell, no warmth → compute_decay (cascade #9).
    s = np.full((3, 3, 3), STATE_VOID, dtype=np.uint8)
    s[1, 1, 1] = STATE_COMPUTE
    m = np.zeros((8, 3, 3, 3), dtype=np.float32)
    assert classify_patch(Patch((0, 0, 0), s, m)) == "compute_decay"


def test_classifier_void_birth_wins_over_acoustic_stress_when_void_dominant():
    """Cascade-order regression noted in chunk 3 sanity check.

    A patch with VOID-dominant + 2 non-void cells SHOULD return ``void_birth``
    (more semantically specific) rather than ``acoustic_stress`` (broad
    fallback). This was the case my chunk-3 sanity test labelled wrong.
    """
    s = np.full((3, 3, 3), STATE_VOID, dtype=np.uint8)
    s[0, 0, 0] = STATE_STRUCTURAL
    s[1, 1, 1] = STATE_ENERGY
    m = np.zeros((8, 3, 3, 3), dtype=np.float32)
    assert classify_patch(Patch((0, 0, 0), s, m)) == "void_birth"


def test_classifier_returns_only_valid_tokens():
    """Every classify_patch return must be in TOKEN_NAMES (totality)."""
    rng = np.random.default_rng(42)
    for _ in range(50):
        s = rng.integers(0, 5, size=(3, 3, 3), dtype=np.uint8)
        m = rng.random((8, 3, 3, 3), dtype=np.float32)
        assert classify_patch(Patch((0, 0, 0), s, m)) in TOKEN_NAMES


# ---------------------------------------------------------------------------
# Budget monitor + safe stride (Chunk 4)
# ---------------------------------------------------------------------------


def test_budget_monitor_basic_elapsed_and_tick():
    with BudgetMonitor(budget_seconds=2.0) as bm:
        time.sleep(0.02)
        assert bm.elapsed() > 0.01
        assert not bm.exceeded()
        bm.tick(); bm.tick()
    r = bm.report()
    assert r.patches_processed == 2
    assert r.exceeded is False


def test_budget_monitor_exceeds_after_overrun():
    with BudgetMonitor(budget_seconds=0.05) as bm:
        time.sleep(0.06)
        if bm.exceeded():
            bm.skip()
    r = bm.report()
    assert r.exceeded is True
    assert r.patches_skipped_due_to_budget == 1


def test_budget_monitor_zero_budget_raises():
    with pytest.raises(ValueError):
        BudgetMonitor(budget_seconds=0)


def test_budget_monitor_negative_budget_raises():
    with pytest.raises(ValueError):
        BudgetMonitor(budget_seconds=-1.0)


def test_budget_report_fraction_used():
    r = BudgetReport(
        budget_seconds=10.0, elapsed_seconds=2.5,
        patches_processed=100, patches_skipped_due_to_budget=0,
        exceeded=False,
    )
    assert r.fraction_used == 0.25


def test_safe_stride_kept_when_initial_fits():
    s = compute_safe_stride((16, 16, 16), radius=1, budget_seconds=30.0,
                              initial_stride=4)
    assert s == 4


def test_safe_stride_doubles_when_too_dense():
    # Force a tiny budget so the initial stride won't fit.
    s = compute_safe_stride((256, 256, 256), radius=1,
                              budget_seconds=0.01,
                              cost_per_patch_seconds=DEFAULT_COST_PER_PATCH_SECONDS,
                              initial_stride=8, max_stride=64)
    assert s > 8 and s <= 64


def test_safe_stride_initial_zero_raises():
    with pytest.raises(ValueError):
        compute_safe_stride((16, 16, 16), initial_stride=0)


def test_safe_stride_max_below_initial_raises():
    with pytest.raises(ValueError):
        compute_safe_stride((16, 16, 16), initial_stride=16, max_stride=8)


# ---------------------------------------------------------------------------
# I/O + safety boundaries (Chunk 5)
# ---------------------------------------------------------------------------


def test_load_snapshot_returns_correct_shapes(tmp_path):
    p = _make_snapshot(tmp_path / "v070_gen5.npz", lattice=16, generation=5)
    state, memory, gen, meta = load_snapshot(p)
    assert state.shape == (16, 16, 16)
    assert memory.shape == (8, 16, 16, 16)
    assert gen == 5


def test_load_snapshot_missing_keys_raises(tmp_path):
    bad = tmp_path / "bad.npz"
    np.savez(str(bad), wrong_key=np.zeros((4, 4, 4)))
    with pytest.raises(ValueError, match="missing keys"):
        load_snapshot(bad)


def test_load_snapshot_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_snapshot(tmp_path / "nonexistent.npz")


def test_find_latest_snapshot_picks_newest(tmp_path):
    older = _make_snapshot(tmp_path / "v070_gen10.npz", lattice=16,
                            generation=10, pad_bytes=2_000_000)
    time.sleep(0.05)
    newer = _make_snapshot(tmp_path / "v070_gen20.npz", lattice=16,
                            generation=20, pad_bytes=2_000_000)
    found = find_latest_snapshot(tmp_path)
    assert found is not None and found.name == newer.name


def test_find_latest_snapshot_empty_dir_returns_none(tmp_path):
    assert find_latest_snapshot(tmp_path) is None


def test_find_latest_snapshot_skips_npz_missing_required_keys(tmp_path):
    """Per issue #139 finding (a): validity is now structural (required
    keys present), not size-based. An .npz matching the glob but lacking
    the required Medusa keys is skipped, and if no candidate validates,
    the function returns None.
    """
    for i in range(3):
        p = tmp_path / f"v070_gen{i}_step{i}_test.npz"
        # Intentionally wrong shape: no lattice/memory_grid/generation
        np.savez(str(p), wrong_key=np.zeros((4, 4, 4), dtype=np.uint8))
    assert find_latest_snapshot(tmp_path) is None


def test_find_latest_snapshot_prefers_newest_valid_skipping_invalid(tmp_path):
    """Per issue #139 finding (a): when valid and invalid candidates
    coexist, the iteration walks newest-first by mtime and skips
    invalid candidates until it finds one with the required keys.
    """
    older_valid = _make_snapshot(tmp_path / "v070_gen10.npz", lattice=16,
                                 generation=10)
    time.sleep(0.05)
    # Newest by mtime, but invalid: missing required keys.
    invalid = tmp_path / "v070_gen20.npz"
    np.savez(str(invalid), wrong_key=np.zeros((4, 4, 4), dtype=np.uint8))
    found = find_latest_snapshot(tmp_path)
    assert found is not None
    assert found.name == older_valid.name


def test_find_latest_snapshot_skips_corrupt_npz(tmp_path):
    """Per issue #139 finding (a): files matching the glob but with
    garbage content (not valid zip archives) must not crash the
    iteration — they're skipped silently like any other invalid file.
    """
    corrupt = tmp_path / "v070_gen1_step1_test.npz"
    corrupt.write_bytes(b"this is not a valid npz file" * 100)
    assert find_latest_snapshot(tmp_path) is None


def test_find_latest_snapshot_accepts_small_but_valid_snapshot(tmp_path):
    """Per issue #139 finding (a): a synthetic snapshot with the required
    keys but well under any size heuristic must now be accepted. This
    locks in the regression that fix (a) is meant to prevent (real
    sparse-early Medusa snapshots are ~900 KB and were silently
    excluded by the old 1 MB size threshold).
    """
    p = _make_snapshot(tmp_path / "v070_gen1.npz", lattice=4, generation=1)
    # Confirm the synthetic snapshot is genuinely tiny (well below the
    # 1 MB heuristic the old code used).
    assert p.stat().st_size < 100_000
    found = find_latest_snapshot(tmp_path)
    assert found is not None
    assert found.name == p.name


def test_is_medusa_live_with_fresh_snapshot(tmp_path):
    _make_snapshot(tmp_path / "v070_gen1.npz", lattice=16,
                    pad_bytes=2_000_000)
    assert is_medusa_live(tmp_path, threshold_minutes=60) is True


def test_is_medusa_live_with_stale_snapshot(tmp_path):
    p = _make_snapshot(tmp_path / "v070_gen1.npz", lattice=16,
                        pad_bytes=2_000_000)
    # Backdate the file by 2 hours
    old = time.time() - 7200
    os.utime(str(p), (old, old))
    assert is_medusa_live(tmp_path, threshold_minutes=30) is False


def test_is_medusa_live_empty_dir_is_false(tmp_path):
    assert is_medusa_live(tmp_path) is False


def test_write_log_entry_appends_jsonl(tmp_path):
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.parent.mkdir()  # create parent (data/), not the leaf
    write_log_entry(log_dir, {"a": 1})
    write_log_entry(log_dir, {"b": 2})
    log_path = log_dir / "nextness_runs.jsonl"
    lines = log_path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["a"] == 1
    assert json.loads(lines[1])["b"] == 2


def test_write_log_entry_refuses_missing_parent_directory(tmp_path):
    """The observer creates its own leaf log dir but never the scaffolding."""
    bad_dir = tmp_path / "nonexistent_parent" / "log_dir"
    with pytest.raises(FileNotFoundError):
        write_log_entry(bad_dir, {"x": 1})


# ---------------------------------------------------------------------------
# Transactional log publication (§7 #5 — killable without partial writes)
# ---------------------------------------------------------------------------


class _HalfWriteProxy:
    """Wraps a real file handle; the first write() delivers only a prefix
    of its payload, then raises OSError. Later writes pass through."""

    def __init__(self, fh):
        self._fh = fh
        self._tripped = False

    def write(self, data):
        if not self._tripped:
            self._tripped = True
            self._fh.write(data[: len(data) // 2])
            self._fh.flush()
            raise OSError("injected fault after partial write")
        return self._fh.write(data)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._fh.close()
        return False

    def __getattr__(self, name):
        return getattr(self._fh, name)


def _install_partial_write_fault(monkeypatch):
    """Make any write-mode handle the observer opens on the canonical log or
    on a staged ``.tmp`` file deliver half of its first write, then raise.

    Patched at both seams (``pathlib.Path.open`` and ``os.fdopen``) so the
    regression bites a direct-append implementation as well as a staged
    one — this is the failing-first fence for the malformed-tail defect.
    """
    real_path_open = pathlib.Path.open
    real_fdopen = os.fdopen

    def faulty_path_open(self, mode="r", *args, **kwargs):
        fh = real_path_open(self, mode, *args, **kwargs)
        wanted = self.name == "nextness_runs.jsonl" or self.name.endswith(".tmp")
        if wanted and any(c in mode for c in "wa+"):
            return _HalfWriteProxy(fh)
        return fh

    def faulty_fdopen(fd, mode="r", *args, **kwargs):
        fh = real_fdopen(fd, mode, *args, **kwargs)
        if any(c in mode for c in "wa+"):
            return _HalfWriteProxy(fh)
        return fh

    monkeypatch.setattr(pathlib.Path, "open", faulty_path_open)
    monkeypatch.setattr(os, "fdopen", faulty_fdopen)


def test_write_log_entry_partial_write_fault_leaves_no_malformed_tail(tmp_path, monkeypatch):
    """A write fault that delivers only a prefix of the record bytes must
    leave the canonical log exactly as it was — never a truncated,
    unterminated JSON tail. (Direct append fails this: the prefix lands
    in ``nextness_runs.jsonl`` itself.)"""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.parent.mkdir()
    write_log_entry(log_dir, {"seed": 1})
    log_path = log_dir / "nextness_runs.jsonl"
    before = log_path.read_bytes()
    _install_partial_write_fault(monkeypatch)
    with pytest.raises(OSError, match="injected fault"):
        write_log_entry(log_dir, {"payload": "x" * 64})
    monkeypatch.undo()
    assert log_path.read_bytes() == before
    assert [p.name for p in log_dir.iterdir()] == ["nextness_runs.jsonl"]


def test_write_log_entry_partial_write_fault_on_absent_log_creates_nothing(tmp_path, monkeypatch):
    """The same fault on the very first record must not create a partial
    canonical log, and must clean its staging file."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.parent.mkdir()
    log_dir.mkdir()
    _install_partial_write_fault(monkeypatch)
    with pytest.raises(OSError, match="injected fault"):
        write_log_entry(log_dir, {"x": 1})
    monkeypatch.undo()
    assert list(log_dir.iterdir()) == []


class _RaisingStr:
    def __str__(self):
        raise RuntimeError("hostile __str__ during serialization")


def test_write_log_entry_serialization_failure_touches_nothing(tmp_path):
    """Pre-commit failure: ``json.dumps`` (via ``default=str``) raises
    before any file is created or modified."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.parent.mkdir()
    write_log_entry(log_dir, {"seed": 1})
    log_path = log_dir / "nextness_runs.jsonl"
    before = log_path.read_bytes()
    with pytest.raises(RuntimeError, match="hostile __str__"):
        write_log_entry(log_dir, {"bad": _RaisingStr()})
    assert log_path.read_bytes() == before
    assert [p.name for p in log_dir.iterdir()] == ["nextness_runs.jsonl"]


def test_write_log_entry_replace_failure_preserves_log_and_cleans_staging(tmp_path, monkeypatch):
    """A failure of the final atomic swap leaves the previous log intact
    and removes the staged file."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.parent.mkdir()
    write_log_entry(log_dir, {"seed": 1})
    log_path = log_dir / "nextness_runs.jsonl"
    before = log_path.read_bytes()

    def refuse_replace(src, dst):
        raise OSError("injected replace failure")

    monkeypatch.setattr(os, "replace", refuse_replace)
    with pytest.raises(OSError, match="injected replace failure"):
        write_log_entry(log_dir, {"x": 2})
    monkeypatch.undo()
    assert log_path.read_bytes() == before
    assert [p.name for p in log_dir.iterdir()] == ["nextness_runs.jsonl"]


def test_write_log_entry_fsync_failure_preserves_log_and_cleans_staging(tmp_path, monkeypatch):
    """A flush-to-disk failure before the swap leaves the previous log
    intact and removes the staged file."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.parent.mkdir()
    write_log_entry(log_dir, {"seed": 1})
    log_path = log_dir / "nextness_runs.jsonl"
    before = log_path.read_bytes()

    def refuse_fsync(fd):
        raise OSError("injected fsync failure")

    monkeypatch.setattr(os, "fsync", refuse_fsync)
    with pytest.raises(OSError, match="injected fsync failure"):
        write_log_entry(log_dir, {"x": 2})
    monkeypatch.undo()
    assert log_path.read_bytes() == before
    assert [p.name for p in log_dir.iterdir()] == ["nextness_runs.jsonl"]


class _CloseFailProxy:
    """Wraps a real file handle; ``close`` closes the underlying file, then
    raises. ``write`` optionally raises a primary failure first."""

    def __init__(self, fh, write_exc=None):
        self._fh = fh
        self._write_exc = write_exc

    def write(self, data):
        if self._write_exc is not None:
            raise self._write_exc
        return self._fh.write(data)

    def close(self):
        self._fh.close()
        raise OSError("injected close failure")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def __getattr__(self, name):
        return getattr(self._fh, name)


def test_write_log_entry_setup_close_failure_does_not_mask_primary(tmp_path, monkeypatch):
    """O1: if the staged-descriptor setup fails AND the cleanup close also
    fails, the caller must observe the primary setup failure."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.parent.mkdir()
    write_log_entry(log_dir, {"seed": 1})
    log_path = log_dir / "nextness_runs.jsonl"
    before = log_path.read_bytes()
    real_close = os.close

    def fdopen_refused(*args, **kwargs):
        raise RuntimeError("primary fdopen failure")

    def close_then_fail(fd):
        real_close(fd)
        raise OSError("secondary close failure")

    monkeypatch.setattr(os, "fdopen", fdopen_refused)
    monkeypatch.setattr(os, "close", close_then_fail)
    with pytest.raises(RuntimeError, match="primary fdopen failure"):
        write_log_entry(log_dir, {"x": 2})
    monkeypatch.undo()
    assert log_path.read_bytes() == before
    assert [p.name for p in log_dir.iterdir()] == ["nextness_runs.jsonl"]


def test_write_log_entry_body_failure_not_masked_by_close_failure(tmp_path, monkeypatch):
    """O1: a staging-write failure followed by a close failure must surface
    the write failure, clean the staging file, and leave the log intact."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.parent.mkdir()
    write_log_entry(log_dir, {"seed": 1})
    log_path = log_dir / "nextness_runs.jsonl"
    before = log_path.read_bytes()
    real_fdopen = os.fdopen
    monkeypatch.setattr(
        os, "fdopen",
        lambda *a, **k: _CloseFailProxy(
            real_fdopen(*a, **k), write_exc=RuntimeError("primary write failure")
        ),
    )
    with pytest.raises(RuntimeError, match="primary write failure"):
        write_log_entry(log_dir, {"x": 2})
    monkeypatch.undo()
    assert log_path.read_bytes() == before
    assert [p.name for p in log_dir.iterdir()] == ["nextness_runs.jsonl"]


def test_write_log_entry_close_only_failure_propagates(tmp_path, monkeypatch):
    """O1: a close failure with NO earlier failure must propagate — without
    a successful close the buffered record is not guaranteed on disk."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.parent.mkdir()
    write_log_entry(log_dir, {"seed": 1})
    log_path = log_dir / "nextness_runs.jsonl"
    before = log_path.read_bytes()
    real_fdopen = os.fdopen
    monkeypatch.setattr(
        os, "fdopen", lambda *a, **k: _CloseFailProxy(real_fdopen(*a, **k))
    )
    with pytest.raises(OSError, match="injected close failure"):
        write_log_entry(log_dir, {"x": 2})
    monkeypatch.undo()
    assert log_path.read_bytes() == before
    assert [p.name for p in log_dir.iterdir()] == ["nextness_runs.jsonl"]


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission-bit semantics")
def test_write_log_entry_preserves_existing_log_mode(tmp_path):
    """O2: an existing log's permission bits survive publication (the
    staged file's restrictive mkstemp mode must not leak through)."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.parent.mkdir()
    write_log_entry(log_dir, {"seed": 1})
    log_path = log_dir / "nextness_runs.jsonl"
    os.chmod(log_path, 0o640)
    write_log_entry(log_dir, {"x": 2})
    assert stat.S_IMODE(os.stat(log_path).st_mode) == 0o640
    lines = log_path.read_text().splitlines()
    assert [json.loads(line) for line in lines] == [{"seed": 1}, {"x": 2}]


@pytest.mark.skipif(os.name != "posix", reason="POSIX umask semantics")
def test_write_log_entry_first_publication_uses_umask_creation_mode(tmp_path):
    """O2: the first canonical log gets the ordinary creation mode under
    the active umask (0o666 & ~umask), not mkstemp's 0o600 staging mode."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.parent.mkdir()
    log_dir.mkdir()
    previous = os.umask(0o027)
    try:
        write_log_entry(log_dir, {"first": 1})
    finally:
        os.umask(previous)
    log_path = log_dir / "nextness_runs.jsonl"
    assert stat.S_IMODE(os.stat(log_path).st_mode) == 0o640  # 0o666 & ~0o027


def test_write_log_entry_mode_copy_failure_aborts_before_replace(tmp_path, monkeypatch):
    """O2: a permission-copy failure must abort publication with the prior
    canonical bytes (and mode) untouched and the staging file removed."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.parent.mkdir()
    write_log_entry(log_dir, {"seed": 1})
    log_path = log_dir / "nextness_runs.jsonl"
    before = log_path.read_bytes()
    mode_before = stat.S_IMODE(os.stat(log_path).st_mode)

    def chmod_refused(path, mode, **kwargs):
        raise OSError("injected chmod failure")

    monkeypatch.setattr(os, "chmod", chmod_refused)
    with pytest.raises(OSError, match="injected chmod failure"):
        write_log_entry(log_dir, {"x": 2})
    monkeypatch.undo()
    assert log_path.read_bytes() == before
    assert stat.S_IMODE(os.stat(log_path).st_mode) == mode_before
    assert [p.name for p in log_dir.iterdir()] == ["nextness_runs.jsonl"]


def test_write_log_entry_refuses_non_writable_existing_log(tmp_path):
    """O2: publication to a non-writable existing log is refused with
    PermissionError before any staging exists — the same write authority
    the old append path enforced; replacement must not bypass it."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.parent.mkdir()
    write_log_entry(log_dir, {"seed": 1})
    log_path = log_dir / "nextness_runs.jsonl"
    before = log_path.read_bytes()
    os.chmod(log_path, 0o444)
    try:
        with pytest.raises(PermissionError):
            write_log_entry(log_dir, {"x": 2})
        assert log_path.read_bytes() == before
        # Refusal happens before staging: nothing else in the directory.
        assert [p.name for p in log_dir.iterdir()] == ["nextness_runs.jsonl"]
    finally:
        os.chmod(log_path, 0o644)


def test_write_log_entry_payload_phase_fault_preserves_existing_log(tmp_path, monkeypatch):
    """O3: the existing bytes copy completely, then the NEW payload write
    fails after a prefix — the canonical log must stay byte-identical and
    no staging file may survive. (Complements the copy-phase fault test.)"""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.parent.mkdir()
    write_log_entry(log_dir, {"n": 0})
    write_log_entry(log_dir, {"n": 1})
    log_path = log_dir / "nextness_runs.jsonl"
    before = log_path.read_bytes()
    payload = (json.dumps({"n": 2}, sort_keys=True, default=str) + "\n").encode("utf-8")

    class PayloadPhaseFault:
        def __init__(self, fh):
            self._fh = fh

        def write(self, data):
            if bytes(data) == payload:
                self._fh.write(data[: len(data) // 2])
                self._fh.flush()
                raise OSError("injected payload-phase fault")
            return self._fh.write(data)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._fh.close()
            return False

        def __getattr__(self, name):
            return getattr(self._fh, name)

    real_fdopen = os.fdopen
    monkeypatch.setattr(os, "fdopen", lambda *a, **k: PayloadPhaseFault(real_fdopen(*a, **k)))
    with pytest.raises(OSError, match="injected payload-phase fault"):
        write_log_entry(log_dir, {"n": 2})
    monkeypatch.undo()
    assert log_path.read_bytes() == before
    assert [p.name for p in log_dir.iterdir()] == ["nextness_runs.jsonl"]


def test_write_log_entry_appends_preserve_prior_bytes_and_terminate_lines(tmp_path):
    """Acceptance: repeat writes keep the prior bytes exactly, stay ordered,
    every record is newline-terminated, and no staging files survive."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.parent.mkdir()
    write_log_entry(log_dir, {"n": 0})
    log_path = log_dir / "nextness_runs.jsonl"
    first = log_path.read_bytes()
    write_log_entry(log_dir, {"n": 1})
    second = log_path.read_bytes()
    assert second.startswith(first)
    assert second.endswith(b"\n")
    records = [json.loads(line) for line in second.decode("utf-8").splitlines()]
    assert records == [{"n": 0}, {"n": 1}]
    assert [p.name for p in log_dir.iterdir()] == ["nextness_runs.jsonl"]


# ---------------------------------------------------------------------------
# §7 SAFETY CONTRACT — one explicit test per invariant
# ---------------------------------------------------------------------------


def test_invariant_1_no_writes_outside_log_directory(tmp_path):
    """§7 #1: writes restricted to log_directory."""
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.parent.mkdir()
    log_dir.mkdir()
    outside = tmp_path / "outside.txt"
    with pytest.raises(WriteOutsideLogDirError):
        nextness_observer._validate_write_path(outside, log_dir)
    # And inside paths pass:
    nextness_observer._validate_write_path(log_dir / "ok.jsonl", log_dir)


def test_invariant_2_no_http_libraries_imported_in_module():
    """§7 #2: no HTTP POSTs. Module must not import any HTTP client lib."""
    source = inspect.getsource(nextness_observer)
    forbidden = [
        "import requests",
        "from requests",
        "import httpx",
        "from httpx",
        "import urllib.request",
        "from urllib.request",
        "import urllib3",
        "from urllib3",
    ]
    for f in forbidden:
        assert f not in source, f"§7 #2 violated: module contains {f!r}"


def test_invariant_3_no_zmq_imported_in_module():
    """§7 #3: PR #2 must not import ZMQ at all (live is strictly PR #6)."""
    source = inspect.getsource(nextness_observer)
    forbidden_imports = ["import zmq", "from zmq"]
    for f in forbidden_imports:
        assert f not in source, f"§7 #3 violated: module contains {f!r}"
    # And the guard exception class is exposed for callers/tests:
    assert issubclass(ZmqUseInPR2Error, ObserverSafetyError)


def test_invariant_3_zmq_at_import_guard_function_exists():
    """The import-time guard function exists and is callable."""
    assert callable(nextness_observer._assert_no_zmq_at_import)


def test_invariant_4_default_no_gpu():
    """§7 #4: CPU only by default; GPU opt-in via MEDUSA_OBSERVER_GPU."""
    c = ObserverConfig()
    assert c.use_gpu is False


def test_invariant_4_gpu_env_var_respected(monkeypatch):
    monkeypatch.setenv("MEDUSA_OBSERVER_GPU", "1")
    assert ObserverConfig.from_env().use_gpu is True
    monkeypatch.setenv("MEDUSA_OBSERVER_GPU", "0")
    assert ObserverConfig.from_env().use_gpu is False


def test_invariant_5_killable_no_orphan_files(tmp_path):
    """§7 #5: SIGTERM/Ctrl+C should leave a consistent log state.

    Hard to test rigorously, but we can verify that process_snapshot
    creates only the expected log file and no temp-files / lockfiles
    in the log directory (so an interrupted run leaves nothing weird).
    """
    snap = _make_snapshot(tmp_path / "v070_gen1.npz", lattice=16,
                            pad_bytes=2_000_000)
    log_dir = tmp_path / "log"
    log_dir.parent.mkdir(exist_ok=True)
    cfg = ObserverConfig(log_directory=str(log_dir),
                         uniform_grid_stride=4, budget_seconds=30.0)
    process_snapshot(snap, cfg, medusa_is_live=False)
    # Only the expected log file should exist; no temp/lock files.
    files_in_log = list(log_dir.iterdir())
    assert len(files_in_log) == 1
    assert files_in_log[0].name == "nextness_runs.jsonl"


def test_invariant_6_pause_aware_records_medusa_is_live(tmp_path):
    """§7 #6: pause-awareness — medusa_is_live recorded in every log entry.

    PR #2 doesn't itself behave differently when paused (it's already
    offline-only); but it MUST record the medusa_is_live flag so PR #6's
    live integration can react to it.
    """
    snap = _make_snapshot(tmp_path / "v070_gen1.npz", lattice=16,
                            pad_bytes=2_000_000)
    log_dir = tmp_path / "log"
    log_dir.parent.mkdir(exist_ok=True)
    cfg = ObserverConfig(log_directory=str(log_dir),
                         uniform_grid_stride=4, budget_seconds=30.0)
    summary = process_snapshot(snap, cfg, medusa_is_live=False)
    assert "medusa_is_live" in summary
    assert summary["medusa_is_live"] is False
    summary2 = process_snapshot(snap, cfg, medusa_is_live=True)
    assert summary2["medusa_is_live"] is True


def test_invariant_7_no_trust_remote_code_in_module():
    """§7 #7: no ``trust_remote_code=True`` call site in the module.

    The term legitimately appears in the module docstring where it's
    documented as a forbidden pattern. What we actually forbid is the
    dangerous *call site* — someone passing ``trust_remote_code=True`` as
    a keyword argument to a function (the Hugging Face footgun that lets
    repo-fetched code execute on import).

    AST-walk the module to look for that exact call-site pattern, ignoring
    any string literals (docstrings, comments, error messages).
    """
    import ast
    source = inspect.getsource(nextness_observer)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "trust_remote_code":
            value = node.value
            if isinstance(value, ast.Constant) and value.value is True:
                pytest.fail(
                    f"§7 #7 violated: trust_remote_code=True call site "
                    f"at line {node.lineno}"
                )


def test_invariant_8_bounded_compute_per_snapshot(tmp_path):
    """§7 #8: BudgetMonitor + compute_safe_stride enforce bounded compute."""
    # BudgetMonitor.exceeded() works as advertised
    with BudgetMonitor(budget_seconds=0.01) as bm:
        time.sleep(0.02)
        assert bm.exceeded() is True
    # compute_safe_stride backs off when budget is too tight
    s = compute_safe_stride((256, 256, 256), radius=1,
                              budget_seconds=0.001, initial_stride=8)
    assert s > 8


# ---------------------------------------------------------------------------
# Issue #144 regression fences — memory-channel layout integrity
# ---------------------------------------------------------------------------


def test_layout_matches_engine_documented_8_channel_map():
    """Observer's MEMORY_CHANNEL_LAYOUT must match the engine's documented map.

    Per issue #144: the prior layout was wrong in 6 of 8 positions. This
    test pins the corrected layout against the engine's documented channel
    map from scripts/continuous_evolution_ca.py:634-655. If the engine
    ever changes its memory_grid layout (e.g., a Phase 17b adds a 9th
    channel), this test fails loudly and the observer must be updated
    in lockstep.

    The expected map is hand-maintained here rather than parsed from
    engine source because:
        - Hand-maintained = explicit & reviewable; every layout change
          must touch both files & this test.
        - Parsed = brittle to comment-formatting changes in engine code.
    """
    from scripts.nextness_observer import MEMORY_CHANNEL_LAYOUT
    engine_documented_layout = {
        "compute_age":         0,
        "structural_age":      1,
        "memory_strength":     2,
        "energy_reserve":      3,
        "last_active_gen":     4,
        "signal_field":        5,
        "warmth":              6,
        "compassion_cooldown": 7,
    }
    assert MEMORY_CHANNEL_LAYOUT == engine_documented_layout, (
        f"MEMORY_CHANNEL_LAYOUT drift from engine documented map.\n"
        f"  Observer: {MEMORY_CHANNEL_LAYOUT}\n"
        f"  Engine:   {engine_documented_layout}\n"
        f"If the engine's layout changed, update MEMORY_CHANNEL_LAYOUT "
        f"AND update the expected layout in this test in the same PR."
    )


def test_layout_has_exactly_eight_channels():
    """Engine has MEMORY_CHANNELS = 8 — observer must mirror exactly.

    No more, no fewer. A 9th observer channel would index past the end
    of the engine's memory_grid array and read undefined memory.
    """
    from scripts.nextness_observer import MEMORY_CHANNEL_LAYOUT
    assert len(MEMORY_CHANNEL_LAYOUT) == 8
    # Indices must be exactly the contiguous range [0, 8)
    assert sorted(MEMORY_CHANNEL_LAYOUT.values()) == list(range(8))


def test_layout_does_not_contain_deprecated_channel_names():
    """The observer must not silently expose access to channels that
    don't exist in the engine.

    Per issue #144: pre-fix MEMORY_CHANNEL_LAYOUT contained keys
    "warmth"/"resonance"/"compassion"/"mindsight"/"magnon"/"ampere" that
    either didn't match the engine's actual layout or referenced
    non-stored channels. This test ensures none of those misleading
    keys come back.

    (Note: "warmth" IS a legitimate engine channel at idx 6 post-fix.
    What this test forbids is the *old wrong-index* warmth + the
    not-actually-stored channel names.)
    """
    from scripts.nextness_observer import MEMORY_CHANNEL_LAYOUT
    forbidden_names = {"resonance", "compassion", "mindsight", "magnon", "ampere"}
    overlap = forbidden_names & set(MEMORY_CHANNEL_LAYOUT.keys())
    assert overlap == set(), (
        f"MEMORY_CHANNEL_LAYOUT contains channel names that don't exist "
        f"in the engine: {sorted(overlap)}. These were the misleading "
        f"names from the pre-#144 layout. If you genuinely need to "
        f"reference these conceptually, add them to TOKEN_STATUS as "
        f"deprecated_no_engine_channel or derived_future, not as a "
        f"stored MEMORY_CHANNEL_LAYOUT entry."
    )


def test_token_status_covers_every_token_in_vocabulary():
    """TOKEN_STATUS dict must have an entry for every TOKEN_NAMES entry."""
    from scripts.nextness_observer import TOKEN_NAMES, TOKEN_STATUS
    assert set(TOKEN_STATUS.keys()) == set(TOKEN_NAMES), (
        f"TOKEN_STATUS does not match TOKEN_NAMES.\n"
        f"  In TOKEN_NAMES but not TOKEN_STATUS: {set(TOKEN_NAMES) - set(TOKEN_STATUS.keys())}\n"
        f"  In TOKEN_STATUS but not TOKEN_NAMES: {set(TOKEN_STATUS.keys()) - set(TOKEN_NAMES)}"
    )


def test_token_status_uses_only_documented_status_values():
    """Every status value must be one of the documented options."""
    from scripts.nextness_observer import TOKEN_STATUS
    valid_statuses = {
        "state_only",
        "stored",
        "diagnostic_only",  # Workstream C (PR #163): real-but-non-routing signal
        "deprecated_no_engine_channel",
        "derived_future",
    }
    for token, status in TOKEN_STATUS.items():
        assert status in valid_statuses, (
            f"Token {token!r} has invalid status {status!r}; "
            f"must be one of {sorted(valid_statuses)}"
        )


def test_deprecated_tokens_never_appear_in_classifier_output():
    """Tokens with a non-routing status must never fire.

    Per issue #144 (deprecated_no_engine_channel / derived_future) and
    Workstream B/C (PR #163, diagnostic_only for metta_warmth): even if the
    prior triggering conditions for these tokens happen to be met in a patch,
    classify_patch must skip them and the patch must fall through to another
    predicate.

    Exhaustive test: synthesize a wide range of patches and assert no
    non-routing token ever appears in the output across all of them. The
    ``warmth``-set config below specifically exercises the metta_warmth
    demotion.
    """
    from scripts.nextness_observer import TOKEN_STATUS, NON_ROUTING_STATUSES
    deprecated_tokens = {
        name for name, status in TOKEN_STATUS.items()
        if status in NON_ROUTING_STATUSES
    }
    # Sanity: there ARE non-routing tokens to check (karuna_relief,
    # mudita_resonance, magnon_lighthouse, metta_warmth) — otherwise this
    # test would silently pass.
    assert len(deprecated_tokens) >= 4, (
        "Expected at least 4 non-routing tokens (3 deprecated/derived + "
        "metta_warmth diagnostic_only)"
    )

    # Try a wide variety of patch configurations
    seed_configurations = [
        # (lattice fill, channels-to-set-with-value)
        (STATE_VOID, {}),
        (STATE_COMPUTE, {}),
        (STATE_COMPUTE, {"compute_age": AGE_SAGE}),
        (STATE_COMPUTE, {"compute_age": AGE_LEGEND + 5.0}),
        (STATE_COMPUTE, {"warmth": THRESHOLD_WARMTH + 0.1}),
        (STATE_STRUCTURAL, {"structural_age": AGE_SAGE}),
        (STATE_STRUCTURAL, {"structural_age": AGE_ANCIENT + 5.0}),
        (STATE_ENERGY, {}),
        (STATE_SENSOR, {}),
    ]
    observed_tokens = set()
    for state_fill, channels in seed_configurations:
        patch = _zero_patch(state_fill, channels)
        token = classify_patch(patch)
        observed_tokens.add(token)
        assert token not in deprecated_tokens, (
            f"Deprecated token {token!r} fired on config "
            f"(state_fill={state_fill}, channels={channels}). "
            f"Status: {TOKEN_STATUS[token]}. Classifier cascade must "
            f"skip deprecated tokens entirely."
        )


def test_patch_features_does_not_attempt_to_read_nonexistent_channels():
    """_patch_features must only request channels that exist in the layout.

    Per issue #144: pre-fix _patch_features called _safe_mean("resonance"),
    _safe_mean("compassion"), _safe_mean("magnon") — all of which were
    bogus channel names. The corrected _patch_features removed those
    calls. This test AST-walks the module to verify that any string
    literal passed to a function that does memory-channel lookup names
    a key that actually exists in MEMORY_CHANNEL_LAYOUT.
    """
    import ast
    import inspect
    from scripts.nextness_observer import MEMORY_CHANNEL_LAYOUT
    valid_channels = set(MEMORY_CHANNEL_LAYOUT.keys())
    source = inspect.getsource(nextness_observer)
    tree = ast.parse(source)
    # Find calls to _safe_mean and any MEMORY_CHANNEL_LAYOUT[<literal>]
    # subscript expressions.
    bad_references: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        # Subscript: MEMORY_CHANNEL_LAYOUT["name"]
        if isinstance(node, ast.Subscript):
            value_node = node.value
            if (isinstance(value_node, ast.Name)
                    and value_node.id == "MEMORY_CHANNEL_LAYOUT"):
                slice_node = node.slice
                if (isinstance(slice_node, ast.Constant)
                        and isinstance(slice_node.value, str)):
                    if slice_node.value not in valid_channels:
                        bad_references.append((slice_node.value, node.lineno))
        # Call: _safe_mean("name")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "_safe_mean":
                if (node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    if node.args[0].value not in valid_channels:
                        bad_references.append(
                            (node.args[0].value, node.lineno)
                        )
    assert not bad_references, (
        f"Found references to channel names not in MEMORY_CHANNEL_LAYOUT:\n"
        + "\n".join(
            f"  line {lineno}: {name!r}"
            for name, lineno in bad_references
        )
    )


# ---------------------------------------------------------------------------
# End-to-end process_snapshot
# ---------------------------------------------------------------------------


def test_end_to_end_process_snapshot_round_trip(tmp_path):
    """Full pipeline: snapshot → patches → tokens → JSONL log entry → readback."""
    snap = _make_snapshot(tmp_path / "v070_gen42.npz", lattice=32,
                            generation=42, pad_bytes=2_000_000)
    log_dir = tmp_path / "log"
    log_dir.parent.mkdir(exist_ok=True)
    cfg = ObserverConfig(log_directory=str(log_dir),
                         uniform_grid_stride=4, budget_seconds=30.0)

    summary = process_snapshot(snap, cfg, medusa_is_live=False)

    # Summary structure
    assert summary["generation"] == 42
    assert summary["lattice_shape"] == [32, 32, 32]
    assert summary["sampling_mode"] == "uniform_grid"
    assert summary["medusa_is_live"] is False
    assert "token_counts" in summary
    assert isinstance(summary["token_counts"], dict)
    assert summary["budget"]["patches_processed"] > 0

    # JSONL log file written + readable
    log_path = log_dir / "nextness_runs.jsonl"
    assert log_path.is_file()
    lines = log_path.read_text().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["generation"] == 42
    assert parsed == summary or parsed["snapshot_file"] == summary["snapshot_file"]


def test_end_to_end_token_counts_match_patches_processed(tmp_path):
    snap = _make_snapshot(tmp_path / "v070_gen5.npz", lattice=16,
                            pad_bytes=2_000_000)
    log_dir = tmp_path / "log"
    log_dir.parent.mkdir(exist_ok=True)
    cfg = ObserverConfig(log_directory=str(log_dir),
                         uniform_grid_stride=4, budget_seconds=30.0)
    summary = process_snapshot(snap, cfg, medusa_is_live=False)
    total_tokens = sum(summary["token_counts"].values())
    # In a non-budget-exhausted run, token_counts.values() should sum to
    # exactly patches_processed (every patch produces exactly one token).
    assert total_tokens == summary["budget"]["patches_processed"]


def test_end_to_end_stride_backoff_recorded(tmp_path):
    """When budget is too small to fit the initial stride, the actual
    stride used should be recorded and ``stride_backoff_fired`` set."""
    snap = _make_snapshot(tmp_path / "v070_gen99.npz", lattice=64,
                            pad_bytes=2_000_000)
    log_dir = tmp_path / "log"
    log_dir.parent.mkdir(exist_ok=True)
    # Pin cost-per-patch high enough that initial_stride=4 won't fit a 0.05s budget
    cfg = ObserverConfig(log_directory=str(log_dir),
                         uniform_grid_stride=4, budget_seconds=5.0)
    summary = process_snapshot(snap, cfg, medusa_is_live=False)
    # On a 64^3 lattice at radius=1 with stride=4 the patch count is small
    # enough that the default cost estimate fits comfortably in 5 seconds.
    # So stride_used should equal stride_initial in this case.
    assert summary["stride_used"] == summary["stride_initial"]
    assert summary["stride_backoff_fired"] is False


def test_process_snapshot_budget_block_includes_fraction_used(tmp_path):
    """Per issue #139 finding (b): ``BudgetReport.fraction_used`` is a
    ``@property``, so ``dataclasses.asdict()`` drops it. ``process_snapshot``
    must explicitly add it to the budget block in both the returned summary
    and the JSONL log entry so downstream metrics (PR #3) can consume the
    fraction without recomputing it from elapsed/budget seconds.
    """
    snap = _make_snapshot(tmp_path / "v070_gen1.npz", lattice=16, generation=1)
    log_dir = tmp_path / "log"
    log_dir.parent.mkdir(exist_ok=True)
    cfg = ObserverConfig(log_directory=str(log_dir),
                         uniform_grid_stride=4, budget_seconds=30.0)
    summary = process_snapshot(snap, cfg, medusa_is_live=False)

    # Live summary should expose fraction_used
    assert "fraction_used" in summary["budget"]
    frac = summary["budget"]["fraction_used"]
    assert isinstance(frac, float)
    # Synthetic 16^3 run finishes in milliseconds against a 30s budget
    assert 0.0 <= frac < 1.0

    # And it must round-trip through JSONL — that's the canonical
    # post-mortem record for PR #3 metrics consumption.
    jsonl = (log_dir / "nextness_runs.jsonl").read_text().splitlines()
    entry = json.loads(jsonl[-1])
    assert "fraction_used" in entry["budget"]
    assert entry["budget"]["fraction_used"] == frac


# ---------------------------------------------------------------------------
# PR #3 per-snapshot metric extensions (PHASE_19_PR3_METRICS_PIPELINE.md §3)
# ---------------------------------------------------------------------------


def test_shannon_entropy_bits_basic_cases():
    """Empty counts → 0; single-token concentration → 0; uniform over K tokens → log2(K)."""
    import math
    # Empty distribution
    assert shannon_entropy_bits({}) == 0.0
    # All-zero counts
    assert shannon_entropy_bits({"a": 0, "b": 0}) == 0.0
    # Single-token concentration: H = -1·log2(1) = 0
    assert shannon_entropy_bits({"a": 100}) == 0.0
    # Uniform over 4 tokens: H = log2(4) = 2.0 bits
    assert shannon_entropy_bits({"a": 25, "b": 25, "c": 25, "d": 25}) == pytest.approx(2.0)
    # Two-token 50/50: H = log2(2) = 1.0 bit
    assert shannon_entropy_bits({"a": 10, "b": 10}) == pytest.approx(1.0)
    # Gen-1.6M Medusa reference: karuna_relief 18941 + phase_boundary 13827
    # Manually computed in design doc §4.4: H ≈ 0.983 bits.
    medusa_h = shannon_entropy_bits({"karuna_relief": 18941, "phase_boundary": 13827})
    assert 0.97 < medusa_h < 0.99


def test_entropy_normalized_basic_cases():
    """vocabulary_size ≤ 1 → 0; H = log2(K) → 1.0; range [0, 1] otherwise."""
    import math
    # Degenerate cases
    assert entropy_normalized(1.0, 1) == 0.0
    assert entropy_normalized(1.0, 0) == 0.0
    assert entropy_normalized(0.0, 16) == 0.0
    assert entropy_normalized(-1.0, 16) == 0.0  # nonsense input → 0, not negative
    # Full saturation: H = log2(K) for K=16 → 4.0 bits → normalized 1.0
    assert entropy_normalized(math.log2(16), 16) == pytest.approx(1.0)
    # Half saturation: H = 0.5·log2(K) → normalized 0.5
    assert entropy_normalized(0.5 * math.log2(16), 16) == pytest.approx(0.5)


def test_void_compute_balance_basic_cases():
    """Equal counts → 1.0; one absent → 0; lattice with no VOID/COMPUTE → 0."""
    # Equal counts: 50% VOID + 50% COMPUTE → balance = 1.0
    state = np.zeros((4, 4, 4), dtype=np.uint8)
    state[:2] = STATE_VOID
    state[2:] = STATE_COMPUTE
    assert void_compute_balance(state) == pytest.approx(1.0)
    # All VOID, no COMPUTE → balance = 0
    state_v = np.full((4, 4, 4), STATE_VOID, dtype=np.uint8)
    assert void_compute_balance(state_v) == 0.0
    # All COMPUTE, no VOID → balance = 0
    state_c = np.full((4, 4, 4), STATE_COMPUTE, dtype=np.uint8)
    assert void_compute_balance(state_c) == 0.0
    # Neither VOID nor COMPUTE → balance = 0
    state_s = np.full((4, 4, 4), STATE_STRUCTURAL, dtype=np.uint8)
    assert void_compute_balance(state_s) == 0.0
    # Gen-1.6M reference scaled to 16³ (4096 cells): P_VOID = 0.4714,
    # P_COMPUTE = 0.4601 → balance ≈ 0.988. Synthetic counts:
    # 47.14% × 4096 ≈ 1931 VOID; 46.01% × 4096 ≈ 1884 COMPUTE; rest STRUCTURAL.
    state_m = np.full((16, 16, 16), STATE_STRUCTURAL, dtype=np.uint8)  # filler
    flat = state_m.ravel()
    flat[:1931] = STATE_VOID
    flat[1931:1931 + 1884] = STATE_COMPUTE
    # Expected: 2 * 1884 / (1931 + 1884) = 0.98765
    assert 0.985 < void_compute_balance(state_m) < 0.990


def test_boundary_rate_basic_cases():
    """phase_boundary absent → 0; present → correct fraction; empty counts → 0."""
    # Empty
    assert boundary_rate({}) == 0.0
    # phase_boundary absent
    assert boundary_rate({"karuna_relief": 100}) == 0.0
    # phase_boundary present but not exclusive
    assert boundary_rate({"phase_boundary": 25, "karuna_relief": 75}) == pytest.approx(0.25)
    # Only phase_boundary
    assert boundary_rate({"phase_boundary": 50}) == pytest.approx(1.0)
    # Gen-1.6M reference: 13827 boundary / 32768 total ≈ 0.4220
    r = boundary_rate({"karuna_relief": 18941, "phase_boundary": 13827})
    assert 0.421 < r < 0.423


def test_process_snapshot_emits_all_pr3_per_snapshot_fields(tmp_path):
    """End-to-end: process_snapshot emits all four new PR #3 fields in the
    JSONL log entry with correct types and ranges. Locks in §3 of the
    PR #3 design doc against silent regression.
    """
    snap = _make_snapshot(tmp_path / "v070_gen1.npz", lattice=16, generation=1)
    log_dir = tmp_path / "log"
    log_dir.parent.mkdir(exist_ok=True)
    cfg = ObserverConfig(log_directory=str(log_dir),
                         uniform_grid_stride=4, budget_seconds=30.0)
    summary = process_snapshot(snap, cfg, medusa_is_live=False)

    # All four PR #3 per-snapshot fields present in returned summary
    assert "shannon_entropy_bits" in summary
    assert "entropy_normalized" in summary
    assert "void_compute_balance" in summary
    assert "boundary_rate" in summary
    # vocabulary_occupancy preserved + still present (PR #138 field)
    assert "vocabulary_occupancy" in summary

    # Type + range checks
    for field in ("shannon_entropy_bits", "entropy_normalized",
                  "void_compute_balance", "boundary_rate",
                  "vocabulary_occupancy"):
        val = summary[field]
        assert isinstance(val, float), f"{field} should be float, got {type(val).__name__}"
        assert val >= 0.0, f"{field} should be non-negative, got {val}"

    # Normalized entropy bounded above by 1.0
    assert summary["entropy_normalized"] <= 1.0
    # Shannon entropy bounded above by log2(K) for K=len(TOKEN_NAMES)
    import math
    assert summary["shannon_entropy_bits"] <= math.log2(len(TOKEN_NAMES)) + 1e-9
    # Balance and boundary rate in [0, 1]
    assert 0.0 <= summary["void_compute_balance"] <= 1.0
    assert 0.0 <= summary["boundary_rate"] <= 1.0

    # All fields round-trip through JSONL identically
    jsonl = (log_dir / "nextness_runs.jsonl").read_text().splitlines()
    entry = json.loads(jsonl[-1])
    for field in ("shannon_entropy_bits", "entropy_normalized",
                  "void_compute_balance", "boundary_rate",
                  "vocabulary_occupancy"):
        assert entry[field] == summary[field], \
            f"{field} differs between summary and JSONL: {summary[field]!r} vs {entry[field]!r}"


def test_process_snapshot_emits_workstream_c_diagnostic_fields(tmp_path):
    """Workstream C (PR #163): process_snapshot emits warmth_max,
    warm_cell_count, and active_vocabulary_occupancy. metta_warmth is now
    diagnostic_only, so its warmth signal surfaces as numeric diagnostics
    instead of a classification token, and the active-occupancy metric is
    distinct from the historical vocabulary_occupancy.
    """
    from scripts.nextness_observer import ROUTING_TOKENS, TOKEN_NAMES
    snap = _make_snapshot(tmp_path / "v070_gen1.npz", lattice=16, generation=1)
    log_dir = tmp_path / "log"
    log_dir.parent.mkdir(exist_ok=True)
    cfg = ObserverConfig(log_directory=str(log_dir),
                         uniform_grid_stride=4, budget_seconds=30.0)
    summary = process_snapshot(snap, cfg, medusa_is_live=False)

    # New fields present
    assert "warmth_max" in summary
    assert "warm_cell_count" in summary
    assert "active_vocabulary_occupancy" in summary

    # Types
    assert isinstance(summary["warmth_max"], float)
    assert isinstance(summary["warm_cell_count"], int)
    assert isinstance(summary["active_vocabulary_occupancy"], float)

    # Ranges
    assert summary["warmth_max"] >= 0.0
    assert summary["warm_cell_count"] >= 0
    assert 0.0 <= summary["active_vocabulary_occupancy"] <= 1.0

    # The synthetic snapshot has an all-zero warmth channel -> no warmth.
    assert summary["warmth_max"] == 0.0
    assert summary["warm_cell_count"] == 0

    # Demotion shrank the routing-token set below the full vocabulary.
    assert len(ROUTING_TOKENS) < len(TOKEN_NAMES)
    # Same appeared-token numerator, smaller denominator -> active >= historical.
    assert summary["active_vocabulary_occupancy"] >= summary["vocabulary_occupancy"]

    # metta_warmth must never appear in token_counts (it cannot route).
    assert summary["token_counts"].get("metta_warmth", 0) == 0

    # New fields round-trip through JSONL identically.
    jsonl = (log_dir / "nextness_runs.jsonl").read_text().splitlines()
    entry = json.loads(jsonl[-1])
    for field in ("warmth_max", "warm_cell_count", "active_vocabulary_occupancy"):
        assert entry[field] == summary[field], \
            f"{field} differs between summary and JSONL: {summary[field]!r} vs {entry[field]!r}"


def test_warmth_diagnostics_read_correct_memory_axis(tmp_path):
    """Axis regression fence (Jack's PR #164 audit): warmth_max /
    warm_cell_count must read the warmth CHANNEL from the channel-first grid
    (``memory[idx]``, axis 0), NOT a spatial cross-section
    (``memory[..., idx]``, the channel-last layout Jack flagged).

    The memory grid is channel-first ``(channels, X, Y, Z)`` — enforced by
    load_snapshot's ``memory.shape[1:] == state.shape`` validation, and used
    by ``iter_uniform_grid_patches`` (``memory[:, ...]``) and ``_safe_mean``
    (``memory[idx]``). This test makes the convention executable: it injects
    warmth ONLY into the true warmth channel while a DIFFERENT channel
    (compute_age) holds a large distinctive value. A channel-first read sees
    the injected 0.5; a wrong-axis ``memory[..., 6]`` read would pick up the
    999.0 compute_age slice and fail these assertions. The prior all-zero
    test cannot catch this because both axes read zero there.
    """
    from scripts.nextness_observer import WARMTH_DIAGNOSTIC_FLOOR
    L = 16
    state = np.zeros((L, L, L), dtype=np.uint8)
    state[::4, ::4, ::4] = STATE_COMPUTE
    memory = np.zeros((8, L, L, L), dtype=np.float32)
    # A non-warmth channel holds a large distinctive value: a wrong-axis read
    # would surface this instead of warmth.
    memory[CH["compute_age"]].fill(999.0)
    # Inject warmth ONLY into the true warmth channel at 7 known cells.
    warm_value = 0.5
    warm_cells = [(0, 0, 0), (1, 2, 3), (4, 5, 6), (7, 8, 9),
                  (10, 11, 12), (13, 14, 15), (2, 9, 4)]
    for (x, y, z) in warm_cells:
        memory[CH["warmth"], x, y, z] = warm_value
    snap = tmp_path / "v070_gen1.npz"
    np.savez(str(snap), lattice=state, memory_grid=memory,
             generation=np.array(1), best_fitness=np.array(0.5))

    log_dir = tmp_path / "log"
    log_dir.parent.mkdir(exist_ok=True)
    cfg = ObserverConfig(log_directory=str(log_dir),
                         uniform_grid_stride=4, budget_seconds=30.0)
    summary = process_snapshot(snap, cfg, medusa_is_live=False)

    # warm_value (0.5) is well above WARMTH_DIAGNOSTIC_FLOOR (0.05).
    assert warm_value >= WARMTH_DIAGNOSTIC_FLOOR
    assert summary["warmth_max"] == pytest.approx(warm_value), (
        f"warmth_max={summary['warmth_max']!r}; expected {warm_value}. A value "
        f"near 999 would indicate a wrong-axis (channel-last) read of the "
        f"compute_age channel instead of the warmth channel."
    )
    assert summary["warm_cell_count"] == len(warm_cells), (
        f"warm_cell_count={summary['warm_cell_count']!r}; expected "
        f"{len(warm_cells)} warmth cells >= {WARMTH_DIAGNOSTIC_FLOOR}. A much "
        f"larger count would indicate a wrong-axis read."
    )


def test_warmth_diagnostics_empty_channel_returns_safe_zeros():
    """Post-#164 hardening: a present-but-empty warmth channel must not crash.

    ``ndarray.max()`` raises ValueError on a zero-size array ("zero-size array
    to reduction operation maximum which has no identity"). Real Medusa grids
    are never empty, but _warmth_diagnostics guards on ``.size > 0`` so a
    degenerate snapshot yields safe ``(0.0, 0)`` diagnostics instead of taking
    down the whole observation pass. (process_snapshot rejects zero-size
    lattices upstream, so the guard is exercised here at the helper boundary.)
    """
    from scripts.nextness_observer import _warmth_diagnostics
    # Warmth channel (idx 6) present but zero-size on a spatial axis.
    empty = np.zeros((8, 0, 4, 4), dtype=np.float32)
    assert _warmth_diagnostics(empty) == (0.0, 0)


def test_warmth_diagnostics_absent_channel_returns_safe_zeros():
    """Defensive: a grid with fewer channels than the warmth index returns safe
    zeros (mirrors _safe_mean's channel-count guard)."""
    from scripts.nextness_observer import _warmth_diagnostics
    too_few = np.ones((3, 4, 4, 4), dtype=np.float32)
    assert _warmth_diagnostics(too_few) == (0.0, 0)


def test_warmth_diagnostics_nonempty_channel_computes_max_and_count():
    """Sanity: a populated warmth channel returns the channel max and the count
    of cells at or above WARMTH_DIAGNOSTIC_FLOOR."""
    from scripts.nextness_observer import (
        _warmth_diagnostics,
        WARMTH_DIAGNOSTIC_FLOOR,
        MEMORY_CHANNEL_LAYOUT,
    )
    memory = np.zeros((8, 4, 4, 4), dtype=np.float32)
    widx = MEMORY_CHANNEL_LAYOUT["warmth"]
    memory[widx, 0, 0, 0] = 0.9
    memory[widx, 1, 1, 1] = WARMTH_DIAGNOSTIC_FLOOR          # exactly at floor counts
    memory[widx, 2, 2, 2] = WARMTH_DIAGNOSTIC_FLOOR / 2.0    # below floor, excluded
    warmth_max, warm_count = _warmth_diagnostics(memory)
    assert warmth_max == pytest.approx(0.9)
    assert warm_count == 2
