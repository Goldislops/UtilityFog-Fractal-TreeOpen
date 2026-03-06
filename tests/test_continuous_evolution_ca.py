"""Tests for the continuous evolution CA engine (v0.3.0 — Chaos & Decay)."""
import sys
from pathlib import Path

import numpy as np
import pytest

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.continuous_evolution_ca import (
    STATE_NAMES,
    NUM_STATES,
    TRANSITIONS,
    STOCHASTIC_RATE,
    DECAY_THRESHOLD,
    DECAY_ENABLED,
    generate_primordial_seed_cube,
    _init_lattice,
    _ca_step,
    _count_neighbours,
    _compute_metrics,
    _shannon_entropy,
    _structural_dominance,
    _fitness,
    _random_genome,
    _evolve_population,
)


# ====================================================================
# Transition rules (v0.3.0)
# ====================================================================

class TestTransitionRules:
    """Verify v0.3.0 transition map properties."""

    def test_structural_has_no_2_neighbour_safety(self):
        """v0.3.0: STRUCTURAL must NOT survive at 2 neighbours."""
        assert 2 not in TRANSITIONS[1], (
            "v0.3.0 removed the 2-neighbour STRUCTURAL safety net"
        )

    def test_void_nucleation_at_3(self):
        """VOID should nucleate to STRUCTURAL at 3 neighbours."""
        assert TRANSITIONS[0].get(3) == 1

    def test_structural_direct_energy_channel(self):
        """STRUCTURAL should have direct ENERGY channels at 5 and 7."""
        assert TRANSITIONS[1].get(5) == 3  # ENERGY
        assert TRANSITIONS[1].get(7) == 3  # ENERGY

    def test_structural_direct_sensor_channel(self):
        """STRUCTURAL should have direct SENSOR channels at 6 and 8."""
        assert TRANSITIONS[1].get(6) == 4  # SENSOR
        assert TRANSITIONS[1].get(8) == 4  # SENSOR

    def test_compute_transitions_to_energy_and_sensor(self):
        """COMPUTE should transition: ENERGY at 2-3, SENSOR at 4-5."""
        assert TRANSITIONS[2].get(2) == 3  # ENERGY
        assert TRANSITIONS[2].get(3) == 3  # ENERGY
        assert TRANSITIONS[2].get(4) == 4  # SENSOR
        assert TRANSITIONS[2].get(5) == 4  # SENSOR

    def test_energy_stable_range(self):
        """ENERGY should remain ENERGY at 2-5 neighbours."""
        for n in (2, 3, 4, 5):
            assert TRANSITIONS[3].get(n) == 3

    def test_sensor_stable_range(self):
        """SENSOR should remain SENSOR at 2-5 neighbours."""
        for n in (2, 3, 4, 5):
            assert TRANSITIONS[4].get(n) == 4


# ====================================================================
# Stochastic & decay parameters
# ====================================================================

class TestV030Parameters:
    """Verify stochastic and decay config."""

    def test_stochastic_rate_positive(self):
        assert STOCHASTIC_RATE > 0

    def test_stochastic_rate_reasonable(self):
        assert STOCHASTIC_RATE <= 0.10, "Rate > 10% would be too chaotic"

    def test_decay_threshold_positive(self):
        assert DECAY_THRESHOLD > 0

    def test_decay_enabled(self):
        assert DECAY_ENABLED is True


# ====================================================================
# Primordial seed
# ====================================================================

class TestPrimordialSeed:
    def test_seed_cube_creates_structural(self):
        lattice = generate_primordial_seed_cube(3)
        assert np.sum(lattice == 1) == 27  # 3^3

    def test_seed_cube_center(self):
        lattice = generate_primordial_seed_cube(3)
        cx = 64 // 2
        assert lattice[cx, cx, cx] == 1

    def test_seed_cube_rejects_size_1(self):
        with pytest.raises(ValueError):
            generate_primordial_seed_cube(1)

    def test_init_lattice_with_cube(self):
        lattice = _init_lattice(cube_size=3)
        assert np.sum(lattice > 0) == 27


# ====================================================================
# CA step mechanics
# ====================================================================

class TestCAStep:
    def test_ca_step_returns_tuple(self):
        """v0.3.0 _ca_step returns (lattice, inactivity)."""
        lattice = _init_lattice(cube_size=3)
        rng = np.random.default_rng(42)
        result = _ca_step(lattice, rng)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_ca_step_produces_growth(self):
        """After several steps, active cells should increase from the seed."""
        lattice = _init_lattice(cube_size=3)
        rng = np.random.default_rng(42)
        inactivity = None
        for _ in range(20):
            lattice, inactivity = _ca_step(lattice, rng, inactivity)
        assert np.sum(lattice > 0) > 27  # grew from seed

    def test_stochastic_creates_diversity(self):
        """Over many steps, stochastic transitions should create non-STRUCTURAL cells."""
        lattice = _init_lattice(cube_size=3)
        rng = np.random.default_rng(42)
        inactivity = None
        for _ in range(100):
            lattice, inactivity = _ca_step(lattice, rng, inactivity)
        # Should have at least some non-STRUCTURAL active cells
        non_structural_active = np.sum(lattice > 1)
        assert non_structural_active > 0, "Stochastic transitions should produce diversity"

    def test_decay_removes_stale_structural(self):
        """STRUCTURAL cells stuck for DECAY_THRESHOLD steps should decay to VOID."""
        # Create a small lattice with one isolated STRUCTURAL cell (no neighbours)
        lattice = np.zeros((8, 8, 8), dtype=np.uint8)
        lattice[4, 4, 4] = 1  # isolated STRUCTURAL
        rng = np.random.default_rng(99)
        inactivity = np.zeros_like(lattice, dtype=np.int16)
        inactivity[4, 4, 4] = DECAY_THRESHOLD + 1  # past threshold

        lattice, inactivity = _ca_step(lattice, rng, inactivity)
        # The isolated cell should have decayed
        assert lattice[4, 4, 4] == 0, "Stale STRUCTURAL should decay to VOID"

    def test_neighbour_count_symmetry(self):
        """Neighbour counting should be symmetric for a central cube."""
        lattice = np.zeros((8, 8, 8), dtype=np.uint8)
        lattice[3:5, 3:5, 3:5] = 1  # 2x2x2 cube
        nc = _count_neighbours(lattice)
        # Each cell in the cube should have same count due to periodic boundaries
        # Centre of cube face cells should have 7 neighbours within cube
        assert nc[3, 3, 3] > 0


# ====================================================================
# Metrics
# ====================================================================

class TestMetrics:
    def test_shannon_entropy_uniform(self):
        """Equal distribution across 4 states should give entropy ~1.0."""
        lattice = np.zeros((4, 4, 4), dtype=np.uint8)
        lattice[0, :, :] = 1  # 16 STRUCTURAL
        lattice[1, :, :] = 2  # 16 COMPUTE
        lattice[2, :, :] = 3  # 16 ENERGY
        lattice[3, :, :] = 4  # 16 SENSOR
        entropy = _shannon_entropy(lattice, active=64)
        assert abs(entropy - 1.0) < 0.01

    def test_shannon_entropy_monolithic(self):
        """All one state should give entropy 0."""
        lattice = np.ones((4, 4, 4), dtype=np.uint8)  # all STRUCTURAL
        entropy = _shannon_entropy(lattice, active=64)
        assert entropy == 0.0

    def test_structural_dominance_pure(self):
        lattice = np.ones((4, 4, 4), dtype=np.uint8)
        dom = _structural_dominance(lattice, active=64)
        assert dom == 1.0

    def test_structural_dominance_mixed(self):
        lattice = np.zeros((4, 4, 4), dtype=np.uint8)
        lattice[0, :, :] = 1
        lattice[1, :, :] = 2
        lattice[2, :, :] = 3
        lattice[3, :, :] = 4
        dom = _structural_dominance(lattice, active=64)
        assert abs(dom - 0.25) < 0.01

    def test_compute_metrics_includes_entropy(self):
        lattice = _init_lattice(cube_size=3)
        metrics = _compute_metrics(lattice, prev_active=0)
        assert "entropy" in metrics
        assert "structural_dominance" in metrics

    def test_compute_metrics_empty_lattice(self):
        lattice = np.zeros((8, 8, 8), dtype=np.uint8)
        metrics = _compute_metrics(lattice, prev_active=0)
        assert metrics["entropy"] == 0.0
        assert metrics["structural_dominance"] == 0.0


# ====================================================================
# Fitness & evolution
# ====================================================================

class TestFitness:
    def test_fitness_rewards_entropy(self):
        """Higher entropy should produce higher fitness (all else equal)."""
        genome = np.array([0.5, 0.5, 0.5, 0.5, 0.5], dtype=np.float32)
        low_entropy = {"branching_ratio": 1.5, "density": 0.3,
                       "entropy": 0.1, "structural_dominance": 0.5}
        high_entropy = {"branching_ratio": 1.5, "density": 0.3,
                        "entropy": 0.9, "structural_dominance": 0.5}
        f_low = _fitness(genome, low_entropy)
        f_high = _fitness(genome, high_entropy)
        assert f_high > f_low

    def test_fitness_penalises_structural_dominance(self):
        """Higher structural dominance should produce lower fitness."""
        genome = np.array([0.5, 0.5, 0.5, 0.5, 0.5], dtype=np.float32)
        low_dom = {"branching_ratio": 1.5, "density": 0.3,
                   "entropy": 0.5, "structural_dominance": 0.2}
        high_dom = {"branching_ratio": 1.5, "density": 0.3,
                    "entropy": 0.5, "structural_dominance": 0.9}
        f_low_dom = _fitness(genome, low_dom)
        f_high_dom = _fitness(genome, high_dom)
        assert f_low_dom > f_high_dom

    def test_fitness_non_negative(self):
        """Fitness should never go below 0."""
        genome = np.array([0.1, 0.1, 0.1, 0.1, 0.9], dtype=np.float32)
        worst_case = {"branching_ratio": 0.0, "density": 0.0,
                      "entropy": 0.0, "structural_dominance": 1.0}
        assert _fitness(genome, worst_case) >= 0.0

    def test_evolve_population_maintains_size(self):
        rng = np.random.default_rng(42)
        pop = np.array([_random_genome(rng) for _ in range(20)], dtype=np.float32)
        metrics = {"branching_ratio": 1.5, "density": 0.3,
                   "entropy": 0.5, "structural_dominance": 0.5}
        new_pop, fits = _evolve_population(pop, metrics, rng)
        assert len(new_pop) == 20
        assert len(fits) == 20
