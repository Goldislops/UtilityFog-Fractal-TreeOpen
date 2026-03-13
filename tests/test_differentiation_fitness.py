#!/usr/bin/env python3
"""Tests for the differentiation-aware fitness scoring in evolution engine."""

import numpy as np
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

try:
    from evolution_engine import _differentiation_score, ENTROPY_BONUS_WEIGHT
except ImportError:
    pytest.skip("evolution_engine not available", allow_module_level=True)


class TestDifferentiationScore:
    def test_uniform_distribution_high_score(self):
        grid = np.zeros((10, 10, 10), dtype=np.uint8)
        n = grid.size // 5
        grid.flat[:n] = 0
        grid.flat[n:2*n] = 1
        grid.flat[2*n:3*n] = 2
        grid.flat[3*n:4*n] = 3
        grid.flat[4*n:] = 4
        score = _differentiation_score(grid)
        assert score > 0.8, f"Uniform distribution score {score} should be > 0.8"

    def test_single_state_low_score(self):
        grid = np.zeros((10, 10, 10), dtype=np.uint8)
        score = _differentiation_score(grid)
        assert score < 0.2, f"Single state score {score} should be < 0.2"

    def test_score_between_0_and_1(self):
        rng = np.random.default_rng(42)
        grid = rng.integers(0, 5, size=(8, 8, 8), dtype=np.uint8)
        score = _differentiation_score(grid)
        assert 0.0 <= score <= 1.0

    def test_entropy_bonus_weight_positive(self):
        assert isinstance(ENTROPY_BONUS_WEIGHT, (int, float))
        assert ENTROPY_BONUS_WEIGHT > 0
