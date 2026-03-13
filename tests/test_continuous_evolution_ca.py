import numpy as np

from scripts.continuous_evolution_ca import (
    DensityPhaseDetectorConfig,
    SelectiveMemoryDecayConfig,
    _apply_selective_memory_decay,
    init_density_phase_detector,
    init_memory_grid,
    init_telemetry_window,
    load_experimental_config,
    step_ca_lattice,
    summarize_telemetry_window,
    update_density_phase_detector,
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


def test_telemetry_window_collects_lifetimes_and_matrix() -> None:
    rule = _rule_spec_for_tests()
    rule["params"]["stochastic"]["enabled"] = False
    rule["params"]["contagion"]["enabled"] = False

    state = np.zeros((5, 5, 5), dtype=np.uint8)
    state[2, 2, 2] = 1
    inactivity = np.zeros_like(state, dtype=np.int16)
    memory = init_memory_grid(state.shape)
    telemetry = init_telemetry_window()
    rng = np.random.default_rng(123)

    state, inactivity, memory, _ = step_ca_lattice(
        state, rule, rng, inactivity, memory, 1, telemetry
    )
    state, inactivity, memory, _ = step_ca_lattice(
        state, rule, rng, inactivity, memory, 2, telemetry
    )

    summary, payload = summarize_telemetry_window(telemetry)

    assert "Telemetry Window" in summary
    assert "transition_matrix" in payload
    assert len(payload["transition_matrix"]) == 5


def test_load_experimental_config_defaults_disabled() -> None:
    cfg = load_experimental_config({"params": {}})
    assert cfg.selective_memory_decay.enabled is False
    assert cfg.density_phase_detector.enabled is False
    assert cfg.mini_lattice.default_size == 16


def test_selective_memory_decay_math_applies_high_decay_rate() -> None:
    memory = init_memory_grid((3, 3, 3))
    memory[2, :, :, :] = 1.0
    memory[1, :, :, :] = 0.0
    compute_mask = np.zeros((3, 3, 3), dtype=bool)
    compute_cluster = np.zeros((3, 3, 3), dtype=np.int16)
    compute_cluster[1, 1, 1] = 9

    cfg = SelectiveMemoryDecayConfig(
        enabled=True,
        memory_strength_threshold=2.0,
        compute_neighbor_threshold=6,
        low_decay_rate=0.01,
        high_decay_rate=0.50,
    )
    from scripts.continuous_evolution_ca import VoxelMemoryParams
    _apply_selective_memory_decay(memory, compute_mask, compute_cluster, current_gen=1, mem=VoxelMemoryParams(), cfg=cfg)

    assert memory[2, 1, 1, 1] < memory[2, 0, 0, 0]


def test_density_phase_detector_trigger_logic() -> None:
    detector = init_density_phase_detector(
        DensityPhaseDetectorConfig(
            enabled=True,
            window_size=10,
            theta_c=0.12,
            alpha_c=0.02,
            savgol_poly_order=3,
            trigger_sandboxed_memory=True,
        )
    )
    ratios = [0.90, 0.84, 0.76, 0.66, 0.54, 0.40, 0.28, 0.18, 0.10, 0.04]
    sig = {}
    triggered = False
    for ratio in ratios:
        s = np.zeros((10, 10, 10), dtype=np.uint8)
        active = int(ratio * s.size)
        s.ravel()[:active] = 1
        sig = update_density_phase_detector(detector, s)
        triggered = triggered or bool(sig["phase_triggered"])
    assert triggered
