"""Tests for the differentiation fitness mechanics (v0.3.0).

Validates that the GA fitness landscape correctly incentivises
cell-type diversity and penalises monolithic STRUCTURAL blobs.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.continuous_evolution_ca import (
    _fitness,
    _shannon_entropy,
    _structural_dominance,
    _compute_metrics,
    _random_genome,
    NUM_STATES,
)


class TestEntropyBonus:
    """Shannon entropy bonus drives differentiation."""

    def test_perfect_diversity_max_bonus(self):
        """Equal 4-way split should give entropy=1.0 -> max bonus."""
        genome = np.array([0.5] * 5, dtype=np.float32)
        metrics = {"branching_ratio": 1.5, "density": 0.3,
                   "entropy": 1.0, "structural_dominance": 0.25}
        f = _fitness(genome, metrics)
        # entropy_bonus = 0.25 * 1.0 = 0.25
        assert f > 0.4  # significant contribution

    def test_zero_diversity_no_bonus(self):
        """Monolithic state should give entropy=0 -> no bonus, but base score remains."""
        genome = np.array([0.5] * 5, dtype=np.float32)
        metrics_mono = {"branching_ratio": 1.5, "density": 0.3,
                        "entropy": 0.0, "structural_dominance": 1.0}
        metrics_diverse = {"branching_ratio": 1.5, "density": 0.3,
                           "entropy": 0.8, "structural_dominance": 1.0}
        f_mono = _fitness(genome, metrics_mono)
        f_diverse = _fitness(genome, metrics_diverse)
        # No entropy bonus means strictly lower fitness
        assert f_mono < f_diverse

    def test_entropy_gradient_monotonic(self):
        """Fitness should strictly increase as entropy increases (dom fixed)."""
        genome = np.array([0.5] * 5, dtype=np.float32)
        fitnesses = []
        for e in np.linspace(0, 1, 10):
            m = {"branching_ratio": 1.5, "density": 0.3,
                 "entropy": float(e), "structural_dominance": 0.5}
            fitnesses.append(_fitness(genome, m))
        for i in range(1, len(fitnesses)):
            assert fitnesses[i] >= fitnesses[i - 1]


class TestStructuralDominancePenalty:
    """Structural dominance penalty punishes monolithic blobs."""

    def test_full_dominance_max_penalty(self):
        """100% STRUCTURAL should incur max penalty (-0.20)."""
        genome = np.array([0.5] * 5, dtype=np.float32)
        no_penalty = {"branching_ratio": 1.5, "density": 0.3,
                      "entropy": 0.5, "structural_dominance": 0.0}
        max_penalty = {"branching_ratio": 1.5, "density": 0.3,
                       "entropy": 0.5, "structural_dominance": 1.0}
        f_none = _fitness(genome, no_penalty)
        f_max = _fitness(genome, max_penalty)
        assert f_none - f_max == pytest.approx(0.20, abs=0.001)

    def test_penalty_gradient_monotonic(self):
        """Fitness should decrease as structural dominance increases (entropy fixed)."""
        genome = np.array([0.5] * 5, dtype=np.float32)
        fitnesses = []
        for d in np.linspace(0, 1, 10):
            m = {"branching_ratio": 1.5, "density": 0.3,
                 "entropy": 0.5, "structural_dominance": float(d)}
            fitnesses.append(_fitness(genome, m))
        for i in range(1, len(fitnesses)):
            assert fitnesses[i] <= fitnesses[i - 1]


class TestCombinedFitnessLandscape:
    """Test the combined effect of entropy bonus + dominance penalty."""

    def test_diverse_fog_beats_monolithic(self):
        """A diverse fog should always beat a monolithic one."""
        genome = np.array([0.5] * 5, dtype=np.float32)
        diverse = {"branching_ratio": 1.5, "density": 0.3,
                   "entropy": 0.8, "structural_dominance": 0.3}
        monolithic = {"branching_ratio": 1.5, "density": 0.3,
                      "entropy": 0.1, "structural_dominance": 0.9}
        assert _fitness(genome, diverse) > _fitness(genome, monolithic)

    def test_ideal_fog_high_fitness(self):
        """Perfect diversity + low dominance should yield high fitness."""
        genome = np.array([0.9, 0.9, 0.9, 0.9, 0.1], dtype=np.float32)
        ideal = {"branching_ratio": 1.5, "density": 0.5,
                 "entropy": 1.0, "structural_dominance": 0.25}
        f = _fitness(genome, ideal)
        assert f > 0.5

    def test_worst_fog_low_fitness(self):
        """Zero entropy + full dominance should yield low fitness."""
        genome = np.array([0.1, 0.1, 0.1, 0.1, 0.9], dtype=np.float32)
        worst = {"branching_ratio": 0.0, "density": 0.0,
                 "entropy": 0.0, "structural_dominance": 1.0}
        f = _fitness(genome, worst)
        assert f < 0.1


class TestEntropyCalculation:
    """Validate Shannon entropy math."""

    def test_uniform_4_states(self):
        """4 equal states: H = ln(4)/ln(4) = 1.0."""
        lattice = np.array([1, 2, 3, 4] * 16, dtype=np.uint8).reshape(4, 4, 4)
        assert abs(_shannon_entropy(lattice, 64) - 1.0) < 0.01

    def test_single_state(self):
        """1 state: H = 0."""
        lattice = np.full((4, 4, 4), 2, dtype=np.uint8)
        assert _shannon_entropy(lattice, 64) == 0.0

    def test_two_equal_states(self):
        """2 equal states: H = ln(2)/ln(4) = 0.5."""
        lattice = np.zeros((4, 4, 4), dtype=np.uint8)
        lattice[:2, :, :] = 1
        lattice[2:, :, :] = 3
        expected = np.log(2) / np.log(4)
        assert abs(_shannon_entropy(lattice, 64) - expected) < 0.01

    def test_empty_lattice(self):
        lattice = np.zeros((4, 4, 4), dtype=np.uint8)
        assert _shannon_entropy(lattice, 0) == 0.0
