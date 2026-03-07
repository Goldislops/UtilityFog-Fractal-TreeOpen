"""Tests for v0.4.0 CA stepping — Contagion & Asymmetric Stability."""
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.continuous_evolution_ca import step_ca_lattice


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
            "contagion": {
                "enabled": True,
                "energy_neighbor_threshold": 4,
                "sensor_neighbor_threshold": 4,
                "structural_energy_conversion_prob": 1.0,
                "structural_sensor_conversion_prob": 0.0,
                "compute_energy_conversion_prob": 0.0,
                "compute_sensor_conversion_prob": 0.0,
            },
            "stochastic": {
                "enabled": True,
                "baseline_transition_prob": 0.08,
                "structural_to_energy_prob": 1.0,
                "structural_to_sensor_prob": 0.0,
                "compute_to_energy_prob": 0.0,
                "compute_to_sensor_prob": 0.0,
                "structural_to_void_decay_prob": 0.0,
                "energy_to_void_decay_prob": 0.0,
                "sensor_to_void_decay_prob": 0.0,
            },
            "decay": {
                "enabled": True,
                "inactivity_neighbor_threshold": 1,
                "structural_inactive_steps_to_decay": 2,
            },
        }
    }


def test_stochastic_transition_promotes_structural_to_energy() -> None:
    """Stochastic override should convert isolated STRUCTURAL to ENERGY."""
    state = np.zeros((5, 5, 5), dtype=np.uint8)
    state[2, 2, 2] = 1  # isolated STRUCTURAL

    rule = _rule_spec_for_tests()
    rule["params"]["contagion"]["enabled"] = False

    rng = np.random.default_rng(7)
    nxt, inactivity, _ = step_ca_lattice(state, rule, rng)

    assert inactivity.shape == state.shape
    assert nxt[2, 2, 2] == 3  # ENERGY


def test_contagion_promotes_structural_with_energy_neighbors() -> None:
    """STRUCTURAL cell surrounded by ENERGY neighbours should convert via contagion."""
    state = np.zeros((5, 5, 5), dtype=np.uint8)
    state[2, 2, 2] = 1  # STRUCTURAL centre
    # 6 ENERGY neighbors around center -> exceeds threshold=4
    for p in [(1, 2, 2), (3, 2, 2), (2, 1, 2), (2, 3, 2), (2, 2, 1), (2, 2, 3)]:
        state[p] = 3  # ENERGY

    rule = _rule_spec_for_tests()
    rule["params"]["stochastic"]["enabled"] = False

    rng = np.random.default_rng(19)
    nxt, _, _ = step_ca_lattice(state, rule, rng)

    assert nxt[2, 2, 2] == 3  # ENERGY (via contagion)


def test_decay_recycles_inactive_structural_cells() -> None:
    """Isolated STRUCTURAL cells should decay to VOID after inactivity threshold."""
    rule = _rule_spec_for_tests()
    rule["params"]["stochastic"]["enabled"] = False
    rule["params"]["contagion"]["enabled"] = False

    state = np.zeros((5, 5, 5), dtype=np.uint8)
    state[2, 2, 2] = 1  # isolated STRUCTURAL

    rng = np.random.default_rng(11)
    inactivity = np.zeros_like(state, dtype=np.int16)

    nxt, inactivity, _ = step_ca_lattice(state, rule, rng, inactivity)
    assert nxt[2, 2, 2] == 1  # still STRUCTURAL after 1 step
    nxt2, inactivity2, _ = step_ca_lattice(nxt, rule, rng, inactivity)

    assert inactivity2[2, 2, 2] >= 2
    assert nxt2[2, 2, 2] == 0  # decayed to VOID


def test_asymmetric_stability_keeps_energy_cells_alive() -> None:
    """ENERGY cells should survive stochastic decay even when STRUCTURAL is obliterated."""
    rule = _rule_spec_for_tests()
    rule["params"]["contagion"]["enabled"] = False
    rule["params"]["stochastic"].update(
        {
            "enabled": True,
            "structural_to_void_decay_prob": 1.0,   # STRUCTURAL always decays
            "energy_to_void_decay_prob": 0.0,        # ENERGY never decays
            "sensor_to_void_decay_prob": 0.0,
            "structural_to_energy_prob": 0.0,
            "structural_to_sensor_prob": 0.0,
            "compute_to_energy_prob": 0.0,
            "compute_to_sensor_prob": 0.0,
        }
    )

    state = np.zeros((5, 5, 5), dtype=np.uint8)
    state[2, 2, 2] = 3  # ENERGY

    rng = np.random.default_rng(31)
    nxt, _, _ = step_ca_lattice(state, rule, rng)

    assert nxt[2, 2, 2] == 3  # ENERGY survives
