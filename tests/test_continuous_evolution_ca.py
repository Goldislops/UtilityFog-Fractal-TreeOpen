import numpy as np

from scripts.continuous_evolution_ca import init_memory_grid, step_ca_lattice


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
    state = np.zeros((5, 5, 5), dtype=np.uint8)
    state[2, 2, 2] = 1

    rule = _rule_spec_for_tests()
    rule["params"]["contagion"]["enabled"] = False

    rng = np.random.default_rng(7)
    nxt, inactivity, memory, _ = step_ca_lattice(state, rule, rng, memory_grid=init_memory_grid(state.shape), current_gen=1)

    assert inactivity.shape == state.shape
    assert memory.shape[0] == 5
    assert nxt[2, 2, 2] == 3


def test_contagion_promotes_structural_with_energy_neighbors() -> None:
    state = np.zeros((5, 5, 5), dtype=np.uint8)
    state[2, 2, 2] = 1
    # 6 ENERGY neighbors around center -> exceeds threshold=4
    for p in [(1, 2, 2), (3, 2, 2), (2, 1, 2), (2, 3, 2), (2, 2, 1), (2, 2, 3)]:
        state[p] = 3

    rule = _rule_spec_for_tests()
    rule["params"]["stochastic"]["enabled"] = False

    rng = np.random.default_rng(19)
    nxt, _, _, _ = step_ca_lattice(state, rule, rng, memory_grid=init_memory_grid(state.shape), current_gen=1)

    assert nxt[2, 2, 2] == 3


def test_decay_recycles_inactive_structural_cells() -> None:
    rule = _rule_spec_for_tests()
    rule["params"]["stochastic"]["enabled"] = False
    rule["params"]["contagion"]["enabled"] = False

    state = np.zeros((5, 5, 5), dtype=np.uint8)
    state[2, 2, 2] = 1

    rng = np.random.default_rng(11)
    inactivity = np.zeros_like(state, dtype=np.int16)

    nxt, inactivity, memory, _ = step_ca_lattice(state, rule, rng, inactivity, init_memory_grid(state.shape), 1)
    assert nxt[2, 2, 2] == 1
    nxt2, inactivity2, memory2, _ = step_ca_lattice(nxt, rule, rng, inactivity, memory, 2)

    assert inactivity2[2, 2, 2] >= 2
    assert nxt2[2, 2, 2] == 0


def test_asymmetric_stability_keeps_energy_cells_alive() -> None:
    rule = _rule_spec_for_tests()
    rule["params"]["contagion"]["enabled"] = False
    rule["params"]["stochastic"].update(
        {
            "enabled": True,
            "structural_to_void_decay_prob": 1.0,
            "energy_to_void_decay_prob": 0.0,
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
    nxt, _, _, _ = step_ca_lattice(state, rule, rng, memory_grid=init_memory_grid(state.shape), current_gen=1)

    assert nxt[2, 2, 2] == 3
