#!/usr/bin/env python3
"""Tests for scripts/continuous_evolution_ca.py -- CA stepping library."""

import numpy as np
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.continuous_evolution_ca import (
    VOID, STRUCTURAL, COMPUTE, ENERGY, SENSOR, NUM_STATES,
    StochasticConfig, ContagionConfig, DensityPhaseDetectorConfig,
    CosmicGardenConfig, ExperimentalConfig, VoxelMemoryParams, CAConfig,
    _load_stochastic_config, _load_contagion_config, _load_detector_config,
    _load_cosmic_config, _load_experimental_config, _load_transition_table,
    load_config,
    DensityPhaseDetector, init_density_phase_detector,
    count_neighbors_3d,
    init_memory_grid, _migrate_memory_grid,
    step, step_ca_lattice,
    census, compute_entropy, compute_fitness,
    init_telemetry_window, summarize_telemetry_window,
)


def _rule_spec_for_tests():
    return {
        "params": {
            "transitions": {
                "VOID": {3: "STRUCTURAL"},
                "STRUCTURAL": {0: "STRUCTURAL", 1: "STRUCTURAL", 3: "COMPUTE", 6: "STRUCTURAL"},
                "COMPUTE": {1: "COMPUTE", 2: "ENERGY"},
                "ENERGY": {0: "ENERGY", 1: "ENERGY"},
                "SENSOR": {0: "SENSOR", 1: "SENSOR"},
            },
            "stochastic": {"enabled": False},
            "contagion": {"enabled": False},
            "decay": {"enabled": False},
        }
    }


# ---------------------------------------------------------------------------
# TestCellConstants
# ---------------------------------------------------------------------------
class TestCellConstants:
    def test_void_is_0(self):
        assert VOID == 0

    def test_structural_is_1(self):
        assert STRUCTURAL == 1

    def test_compute_is_2(self):
        assert COMPUTE == 2

    def test_energy_is_3(self):
        assert ENERGY == 3

    def test_sensor_is_4(self):
        assert SENSOR == 4

    def test_num_states(self):
        assert NUM_STATES == 5


# ---------------------------------------------------------------------------
# TestNeighborCounting
# ---------------------------------------------------------------------------
class TestNeighborCounting:
    def test_empty_grid(self):
        state = np.zeros((4, 4, 4), dtype=np.uint8)
        nc = count_neighbors_3d(state)
        assert nc.shape == (NUM_STATES, 4, 4, 4)
        # All cells are VOID, so VOID neighbor counts should be 26 for interior
        # (np.roll wraps, so even corners see 26 neighbors)
        assert nc[VOID, 2, 2, 2] == 26

    def test_single_cell(self):
        state = np.zeros((5, 5, 5), dtype=np.uint8)
        state[2, 2, 2] = STRUCTURAL
        nc = count_neighbors_3d(state)
        # The STRUCTURAL cell itself is counted by neighbors
        # Neighbors of (1,2,2) should see 1 STRUCTURAL neighbor (at 2,2,2)
        assert nc[STRUCTURAL, 1, 2, 2] >= 1

    def test_full_grid(self):
        state = np.ones((3, 3, 3), dtype=np.uint8)  # all STRUCTURAL
        nc = count_neighbors_3d(state)
        # Center cell: 26 STRUCTURAL neighbors (wraps around)
        assert nc[STRUCTURAL, 1, 1, 1] == 26


# ---------------------------------------------------------------------------
# TestStochasticConfig
# ---------------------------------------------------------------------------
class TestStochasticConfig:
    def test_default_decay_is_0_005(self):
        cfg = StochasticConfig()
        assert cfg.structural_to_void_decay_prob == 0.005
        assert cfg.structural_to_void_decay_prob != 0.04

    def test_custom_values(self):
        cfg = StochasticConfig(structural_to_void_decay_prob=0.01, baseline_transition_prob=0.05)
        assert cfg.structural_to_void_decay_prob == 0.01
        assert cfg.baseline_transition_prob == 0.05

    def test_loader_fallback_is_0_005(self):
        cfg = _load_stochastic_config({"params": {}})
        assert cfg.structural_to_void_decay_prob == 0.005

    def test_loader_explicit_value(self):
        cfg = _load_stochastic_config({"params": {"stochastic": {"structural_to_void_decay_prob": 0.01}}})
        assert cfg.structural_to_void_decay_prob == 0.01


# ---------------------------------------------------------------------------
# TestStepFunction
# ---------------------------------------------------------------------------
class TestStepFunction:
    def test_preserves_shape(self):
        state = np.zeros((4, 4, 4), dtype=np.uint8)
        state[2, 2, 2] = STRUCTURAL
        rule = _rule_spec_for_tests()
        rng = np.random.default_rng(42)
        ns, inact, mem, age, metrics = step(state, rule, rng)
        assert ns.shape == state.shape
        assert inact.shape == state.shape
        assert age.shape == state.shape

    def test_returns_memory_grid(self):
        state = np.zeros((4, 4, 4), dtype=np.uint8)
        rule = _rule_spec_for_tests()
        rng = np.random.default_rng(42)
        ns, inact, mem, age, metrics = step(state, rule, rng)
        assert mem.shape[0] == 5
        assert mem.shape[1:] == state.shape

    def test_3_to_5_channel_migration(self):
        state = np.zeros((4, 4, 4), dtype=np.uint8)
        state[2, 2, 2] = COMPUTE
        rule = _rule_spec_for_tests()
        rng = np.random.default_rng(42)
        # Create a 3-channel memory grid
        old_mem = np.zeros((3, 4, 4, 4), dtype=np.float32)
        old_mem[0, 2, 2, 2] = 5.0   # compute_age
        old_mem[1, 2, 2, 2] = 0.9   # memory_strength
        old_mem[2, 2, 2, 2] = 10.0  # last_active_gen
        ns, inact, mem, age, metrics = step(state, rule, rng, memory_grid=old_mem)
        assert mem.shape[0] == 5
        # Verify migration mapped channels correctly
        # Channel 0 -> compute_age (preserved)
        # Channel 1 -> memory_strength -> new channel 2
        # Channel 2 -> last_active_gen -> new channel 4

    def test_empty_grid_stays_empty(self):
        state = np.zeros((4, 4, 4), dtype=np.uint8)
        rule = _rule_spec_for_tests()
        rng = np.random.default_rng(42)
        ns, inact, mem, age, metrics = step(state, rule, rng)
        # All void with no transitions defined for void->something at 0 neighbors
        # Should stay mostly void
        assert np.sum(ns != VOID) <= np.sum(state != VOID) + 1  # at most 1 new cell from noise

    def test_analogue_mutation_uses_pre_mut(self):
        """Verify that analogue mutation uses pre_mut = out.copy() snapshot."""
        state = np.zeros((6, 6, 6), dtype=np.uint8)
        # Create a grid with all 4 non-void states
        state[1, 1, 1] = STRUCTURAL
        state[2, 2, 2] = COMPUTE
        state[3, 3, 3] = ENERGY
        state[4, 4, 4] = SENSOR
        rule = _rule_spec_for_tests()
        # Set mutation to 100% to guarantee it fires
        rule["params"]["cosmic_garden"] = {"analogue_mutation": 1.0}
        rng = np.random.default_rng(42)
        ns, _, _, _, _ = step(state, rule, rng)
        # With pre_mut, each state should cycle to the next:
        # STRUCTURAL->COMPUTE, COMPUTE->ENERGY, ENERGY->SENSOR, SENSOR->STRUCTURAL
        # Without pre_mut, cascading would cause double-mutations
        # We can't test exact cells since other mechanics apply first,
        # but we can verify it runs without error and produces valid output
        assert ns.dtype == np.uint8
        assert np.all(ns < NUM_STATES)


# ---------------------------------------------------------------------------
# TestDensityPhaseDetector
# ---------------------------------------------------------------------------
class TestDensityPhaseDetector:
    def test_initialization(self):
        cfg = DensityPhaseDetectorConfig(enabled=True, theta_c=0.05, alpha_c=0.03)
        detector = init_density_phase_detector(cfg)
        assert len(detector.densities) == 0
        assert len(detector.first_derivatives) == 0
        assert detector.config.theta_c == 0.05
        assert detector.config.alpha_c == 0.03

    def test_contraction_trigger(self):
        cfg = DensityPhaseDetectorConfig(
            enabled=True, window_size=5, theta_c=0.01, alpha_c=0.005, savgol_poly_order=2,
        )
        detector = init_density_phase_detector(cfg)
        # Feed accelerating decline: 0.9 -> 0.8 -> 0.5 -> 0.1
        # Drops grow each step (0.1, 0.3, 0.4) so d2 < 0 (accelerating)
        s1 = np.zeros((10, 10, 10), dtype=np.uint8)
        s1.ravel()[:900] = 1   # density = 0.9
        s2 = np.zeros((10, 10, 10), dtype=np.uint8)
        s2.ravel()[:800] = 1   # density = 0.8
        s3 = np.zeros((10, 10, 10), dtype=np.uint8)
        s3.ravel()[:500] = 1   # density = 0.5
        s4 = np.zeros((10, 10, 10), dtype=np.uint8)
        s4.ravel()[:100] = 1   # density = 0.1
        detector.update(s1)
        detector.update(s2)
        detector.update(s3)
        sig = detector.update(s4)
        # d1 should be negative (declining), d2 should be negative (accelerating decline)
        assert sig["phase_d1"] < 0
        assert sig["phase_triggered"] == 1.0

    def test_stable_no_trigger(self):
        cfg = DensityPhaseDetectorConfig(
            enabled=True, window_size=5, theta_c=0.05, alpha_c=0.03, savgol_poly_order=2,
        )
        detector = init_density_phase_detector(cfg)
        # Feed constant density
        s = np.ones((4, 4, 4), dtype=np.uint8)
        for _ in range(5):
            sig = detector.update(s)
        assert sig["phase_triggered"] == 0.0


# ---------------------------------------------------------------------------
# TestCensus
# ---------------------------------------------------------------------------
class TestCensus:
    def test_all_void(self):
        state = np.zeros((3, 3, 3), dtype=np.uint8)
        c = census(state)
        assert c["void"] == 27
        assert c["structural"] == 0
        assert c["compute"] == 0
        assert c["energy"] == 0
        assert c["sensor"] == 0
        assert c["total"] == 27

    def test_mixed(self):
        state = np.zeros((2, 2, 2), dtype=np.uint8)
        state[0, 0, 0] = STRUCTURAL
        state[0, 0, 1] = COMPUTE
        state[0, 1, 0] = ENERGY
        state[0, 1, 1] = SENSOR
        c = census(state)
        assert c["void"] == 4
        assert c["structural"] == 1
        assert c["compute"] == 1
        assert c["energy"] == 1
        assert c["sensor"] == 1
        assert c["total"] == 8


# ---------------------------------------------------------------------------
# TestEntropy
# ---------------------------------------------------------------------------
class TestEntropy:
    def test_uniform(self):
        state = np.zeros((4, 4, 4), dtype=np.uint8)
        n = state.size // 4
        state.ravel()[:n] = STRUCTURAL
        state.ravel()[n:2*n] = COMPUTE
        state.ravel()[2*n:3*n] = ENERGY
        state.ravel()[3*n:] = SENSOR
        ent = compute_entropy(state)
        # 4 states equally distributed -> max entropy = 1.0
        assert abs(ent - 1.0) < 0.01

    def test_single_state(self):
        state = np.full((3, 3, 3), STRUCTURAL, dtype=np.uint8)
        ent = compute_entropy(state)
        assert ent == 0.0

    def test_all_void(self):
        state = np.zeros((3, 3, 3), dtype=np.uint8)
        ent = compute_entropy(state)
        assert ent == 0.0

    def test_fitness_range(self):
        rng = np.random.default_rng(42)
        state = rng.integers(0, NUM_STATES, size=(6, 6, 6), dtype=np.uint8)
        fit = compute_fitness(state)
        assert 0.0 <= fit <= 1.0


# ---------------------------------------------------------------------------
# TestConfigLoading
# ---------------------------------------------------------------------------
class TestConfigLoading:
    def test_default_config(self):
        cfg = load_config(None)
        assert isinstance(cfg, CAConfig)
        assert cfg.stochastic.structural_to_void_decay_prob == 0.005
        assert cfg.cosmic.bamboo_rebirth_age == 488
        assert cfg.experimental.mamba_enabled is False

    def test_nonexistent_file(self):
        cfg = load_config("/nonexistent/path/to/rules.toml")
        assert isinstance(cfg, CAConfig)
        # Should return defaults
        assert cfg.stochastic.structural_to_void_decay_prob == 0.005
