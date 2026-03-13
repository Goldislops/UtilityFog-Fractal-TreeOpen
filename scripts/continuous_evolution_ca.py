#!/usr/bin/env python3
"""3D CA stepping utilities with state-aware contagion, stochasticity, decay, and voxel memory.

v0.7.5 Cosmic Garden -- 5 mechanisms: Cluster Coherence, Halbach Recuperation,
Bamboo Protocol (G3=488), Super-Pod Leeching, Analogue Mutation.

CRITICAL: structural_to_void_decay_prob = 0.005 everywhere (not 0.04 or 0.025).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from collections import deque
from typing import Any, Deque, Dict, List, Mapping, Optional, Tuple

import numpy as np

try:
    import tomli
except ImportError:
    try:
        import tomllib as tomli  # type: ignore[no-redef]
    except ImportError:
        tomli = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Cell state constants
# ---------------------------------------------------------------------------
VOID = 0
STRUCTURAL = 1
COMPUTE = 2
ENERGY = 3
SENSOR = 4

STATE_NAME_TO_ID: Dict[str, int] = {
    "VOID": VOID,
    "STRUCTURAL": STRUCTURAL,
    "COMPUTE": COMPUTE,
    "ENERGY": ENERGY,
    "SENSOR": SENSOR,
}

NUM_STATES = 5


# ---------------------------------------------------------------------------
# Dataclass configs
# ---------------------------------------------------------------------------
@dataclass
class StochasticConfig:
    enabled: bool = True
    baseline_transition_prob: float = 0.08
    structural_to_energy_prob: float = 0.08
    structural_to_sensor_prob: float = 0.08
    compute_to_energy_prob: float = 0.10
    compute_to_sensor_prob: float = 0.10
    # CRITICAL: 0.005, NOT 0.04
    structural_to_void_decay_prob: float = 0.005
    energy_to_void_decay_prob: float = 0.005
    sensor_to_void_decay_prob: float = 0.004


@dataclass
class ContagionConfig:
    enabled: bool = True
    energy_neighbor_threshold: int = 4
    sensor_neighbor_threshold: int = 4
    structural_energy_conversion_prob: float = 0.40
    structural_sensor_conversion_prob: float = 0.30
    compute_energy_conversion_prob: float = 0.15
    compute_sensor_conversion_prob: float = 0.25


@dataclass
class DensityPhaseDetectorConfig:
    enabled: bool = False
    window_size: int = 8
    theta_c: float = 0.03
    alpha_c: float = 0.02
    savgol_poly_order: int = 2
    density_low_threshold: float = 0.10
    density_high_threshold: float = 0.65
    contraction_density_threshold: float = 0.22
    trigger_sandboxed_memory: bool = False


@dataclass
class CosmicGardenConfig:
    cluster_coherence_threshold: int = 3
    shield_strength: float = 0.85
    cluster_shield_bonus: float = 0.15
    halbach_recuperation_rate: float = 0.40
    temporal_dilation: float = 0.15
    bamboo_initial_growth: int = 100
    bamboo_max_length: int = 500
    bamboo_rebirth_age: int = 488
    biofilm_leech_rate: float = 0.10
    super_pod_threshold: int = 8
    analogue_mutation: float = 0.03
    otolith_vector: float = 0.05
    damping_radius: int = 2


@dataclass
class ExperimentalConfig:
    mamba_d_model: int = 64
    mamba_d_state: int = 16
    mamba_enabled: bool = False
    void_sanctuary_enabled: bool = False
    void_sanctuary_radius: int = 2
    epsilon: float = 1e-8
    selective_memory_decay_enabled: bool = False
    selective_memory_decay_threshold: float = 0.75
    selective_compute_neighbor_threshold: int = 6
    selective_low_decay_rate: float = 0.015
    selective_high_decay_rate: float = 0.045


@dataclass
class VoxelMemoryParams:
    age_young_threshold: int = 8
    age_mature_threshold: int = 40
    resistance_max: float = 0.82
    reverse_contagion_threshold: int = 4
    reverse_contagion_base_prob: float = 0.20
    reverse_contagion_boost: float = 0.06
    energy_to_compute_prob: float = 0.20
    forward_contagion_threshold: int = 5
    forward_contagion_penalty: float = 0.18
    forward_contagion_floor: float = 0.40
    rag_query_radius: int = 3
    rag_memory_decay: float = 0.015
    rag_reinforcement_boost: float = 1.50
    rag_entropy_weight: float = 0.18
    # Phase 3: Mamba-Viking memory dynamics
    mamba_delta_threshold: float = 0.12
    mamba_tau_base: float = 5.0
    mamba_tau_scale: float = 12.0
    mamba_boost_base: float = 0.015
    mamba_boost_gain: float = 0.045
    mamba_age_stability_gain: float = 0.03
    mamba_high_delta_floor: float = 1.15
    # Phase 3: Void Sanctuary Shield
    void_sanctuary_multiplier: float = 50.0
    # Phase 3: Epsilon Buffer (Dimensional Regularization)
    epsilon_p_max: float = 0.943
    epsilon_buffer: float = 0.08
    epsilon_n_c: int = 20
    epsilon_tau: float = 3.0
    # Phase 4: Equanimity Shield (Nemo's sigmoid resistance for mature cells)
    # equanimity_age_min: bootstrap threshold (much lower than age_mature_threshold)
    # Without this, cells never reach age 40 to activate the shield (chicken-and-egg)
    equanimity_age_min: float = 3.0
    equanimity_p_max: float = 0.85
    equanimity_tau: float = 5.0
    equanimity_gamma: float = 0.5


@dataclass
class DecayConfig:
    enabled: bool = True
    inactivity_neighbor_threshold: int = 1
    structural_inactive_steps_to_decay: int = 6


@dataclass
class CAConfig:
    """Top-level configuration aggregating all sub-configs."""
    stochastic: StochasticConfig = field(default_factory=StochasticConfig)
    contagion: ContagionConfig = field(default_factory=ContagionConfig)
    decay: DecayConfig = field(default_factory=DecayConfig)
    detector: DensityPhaseDetectorConfig = field(default_factory=DensityPhaseDetectorConfig)
    cosmic: CosmicGardenConfig = field(default_factory=CosmicGardenConfig)
    experimental: ExperimentalConfig = field(default_factory=ExperimentalConfig)
    voxel_memory: VoxelMemoryParams = field(default_factory=VoxelMemoryParams)
    transition_table: Dict[int, Dict[int, int]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# TOML loading functions
# ---------------------------------------------------------------------------
def _load_stochastic_config(rule_spec: Mapping[str, Any]) -> StochasticConfig:
    stoch = rule_spec.get("params", {}).get("stochastic", {})
    baseline = float(stoch.get("baseline_transition_prob", 0.08))
    return StochasticConfig(
        enabled=bool(stoch.get("enabled", True)),
        baseline_transition_prob=baseline,
        structural_to_energy_prob=float(stoch.get("structural_to_energy_prob", baseline)),
        structural_to_sensor_prob=float(stoch.get("structural_to_sensor_prob", baseline)),
        compute_to_energy_prob=float(stoch.get("compute_to_energy_prob", baseline + 0.02)),
        compute_to_sensor_prob=float(stoch.get("compute_to_sensor_prob", baseline + 0.02)),
        # CRITICAL fallback: 0.005, NOT 0.04
        structural_to_void_decay_prob=float(stoch.get("structural_to_void_decay_prob", 0.005)),
        energy_to_void_decay_prob=float(stoch.get("energy_to_void_decay_prob", 0.005)),
        sensor_to_void_decay_prob=float(stoch.get("sensor_to_void_decay_prob", 0.004)),
    )


def _load_contagion_config(rule_spec: Mapping[str, Any]) -> ContagionConfig:
    contagion = rule_spec.get("params", {}).get("contagion", {})
    return ContagionConfig(
        enabled=bool(contagion.get("enabled", True)),
        energy_neighbor_threshold=int(contagion.get("energy_neighbor_threshold", 4)),
        sensor_neighbor_threshold=int(contagion.get("sensor_neighbor_threshold", 4)),
        structural_energy_conversion_prob=float(contagion.get("structural_energy_conversion_prob", 0.40)),
        structural_sensor_conversion_prob=float(contagion.get("structural_sensor_conversion_prob", 0.30)),
        compute_energy_conversion_prob=float(contagion.get("compute_energy_conversion_prob", 0.15)),
        compute_sensor_conversion_prob=float(contagion.get("compute_sensor_conversion_prob", 0.25)),
    )


def _load_detector_config(rule_spec: Mapping[str, Any]) -> DensityPhaseDetectorConfig:
    det = rule_spec.get("params", {}).get("density_phase_detector", {})
    return DensityPhaseDetectorConfig(
        enabled=bool(det.get("enabled", False)),
        window_size=max(3, int(det.get("window_size", 8))),
        theta_c=float(det.get("theta_c", det.get("first_derivative_threshold", 0.03))),
        alpha_c=float(det.get("alpha_c", det.get("second_derivative_threshold", 0.02))),
        savgol_poly_order=int(det.get("savgol_poly_order", 2)),
        density_low_threshold=float(det.get("density_low_threshold", 0.10)),
        density_high_threshold=float(det.get("density_high_threshold", 0.65)),
        contraction_density_threshold=float(det.get("contraction_density_threshold", 0.22)),
        trigger_sandboxed_memory=bool(det.get("trigger_sandboxed_memory", False)),
    )


def _load_cosmic_config(rule_spec: Mapping[str, Any]) -> CosmicGardenConfig:
    cosmic = rule_spec.get("params", {}).get("cosmic_garden", {})
    return CosmicGardenConfig(
        cluster_coherence_threshold=int(cosmic.get("cluster_coherence_threshold", 3)),
        shield_strength=float(cosmic.get("shield_strength", 0.85)),
        cluster_shield_bonus=float(cosmic.get("cluster_shield_bonus", 0.15)),
        halbach_recuperation_rate=float(cosmic.get("halbach_recuperation_rate", 0.40)),
        temporal_dilation=float(cosmic.get("temporal_dilation", 0.15)),
        bamboo_initial_growth=int(cosmic.get("bamboo_initial_growth", 100)),
        bamboo_max_length=int(cosmic.get("bamboo_max_length", 500)),
        bamboo_rebirth_age=int(cosmic.get("bamboo_rebirth_age", 488)),
        biofilm_leech_rate=float(cosmic.get("biofilm_leech_rate", 0.10)),
        super_pod_threshold=int(cosmic.get("super_pod_threshold", 8)),
        analogue_mutation=float(cosmic.get("analogue_mutation", 0.03)),
        otolith_vector=float(cosmic.get("otolith_vector", 0.05)),
        damping_radius=int(cosmic.get("damping_radius", 2)),
    )


def _load_experimental_config(rule_spec: Mapping[str, Any]) -> ExperimentalConfig:
    exp = rule_spec.get("params", {}).get("experimental", {})
    return ExperimentalConfig(
        mamba_d_model=int(exp.get("mamba_d_model", 64)),
        mamba_d_state=int(exp.get("mamba_d_state", 16)),
        mamba_enabled=bool(exp.get("mamba_enabled", False)),
        void_sanctuary_enabled=bool(exp.get("void_sanctuary_enabled", False)),
        void_sanctuary_radius=int(exp.get("void_sanctuary_radius", 2)),
        epsilon=float(exp.get("epsilon", 1e-8)),
        selective_memory_decay_enabled=bool(exp.get("selective_memory_decay_enabled", False)),
        selective_memory_decay_threshold=float(exp.get("selective_memory_decay_threshold", 0.75)),
        selective_compute_neighbor_threshold=int(exp.get("selective_compute_neighbor_threshold", 6)),
        selective_low_decay_rate=float(exp.get("selective_low_decay_rate", 0.015)),
        selective_high_decay_rate=float(exp.get("selective_high_decay_rate", 0.045)),
    )


def _load_transition_table(rule_spec: Mapping[str, Any]) -> Dict[int, Dict[int, int]]:
    transitions = rule_spec.get("params", {}).get("transitions", {})
    table: Dict[int, Dict[int, int]] = {}
    for state_name, mapping in transitions.items():
        src = STATE_NAME_TO_ID[state_name.upper()]
        table[src] = {}
        for neighbor_count, target_name in mapping.items():
            table[src][int(neighbor_count)] = STATE_NAME_TO_ID[str(target_name).upper()]
    return table


def _load_decay_config(rule_spec: Mapping[str, Any]) -> DecayConfig:
    decay = rule_spec.get("params", {}).get("decay", {})
    return DecayConfig(
        enabled=bool(decay.get("enabled", True)),
        inactivity_neighbor_threshold=int(decay.get("inactivity_neighbor_threshold", 1)),
        structural_inactive_steps_to_decay=int(decay.get("structural_inactive_steps_to_decay", 6)),
    )


def load_config(rule_path: Optional[str | Path] = None) -> CAConfig:
    """Load a complete CAConfig from a TOML file, or return defaults."""
    if rule_path is not None and tomli is not None:
        p = Path(rule_path)
        if p.exists():
            with p.open("rb") as f:
                rule_spec = tomli.load(f)
            return CAConfig(stochastic=_load_stochastic_config(rule_spec), contagion=_load_contagion_config(rule_spec), decay=_load_decay_config(rule_spec), detector=_load_detector_config(rule_spec), cosmic=_load_cosmic_config(rule_spec), experimental=_load_experimental_config(rule_spec), voxel_memory=VoxelMemoryParams(), transition_table=_load_transition_table(rule_spec))
    return CAConfig()


def load_rule_spec(rule_path: str | Path) -> Dict[str, Any]:
    with Path(rule_path).open("rb") as f:
        return tomli.load(f)


def load_experimental_config(rule_spec: Mapping[str, Any]) -> ExperimentalConfig:
    return _load_experimental_config(rule_spec)


# ---------------------------------------------------------------------------
# DensityPhaseDetector
# ---------------------------------------------------------------------------
@dataclass
class DensityPhaseDetector:
    """Trigger: d1 < -theta_c/2 AND d2 < -alpha_c. Uses np.polyfit/polyder."""
    config: DensityPhaseDetectorConfig
    densities: Deque[float] = field(default_factory=deque)
    first_derivatives: Deque[float] = field(default_factory=deque)

    def _savgol_latest_derivatives(self) -> Tuple[float, float]:
        n = len(self.densities)
        if n < 3:
            d1 = self.densities[-1] - self.densities[-2] if n >= 2 else 0.0
            return d1, 0.0
        order = min(self.config.savgol_poly_order, n - 1)
        x = np.arange(n, dtype=np.float64)
        y = np.array(list(self.densities), dtype=np.float64)
        coeffs = np.polyfit(x, y, deg=order)
        poly = np.poly1d(coeffs)
        d1_poly = np.polyder(poly, m=1)
        d2_poly = np.polyder(poly, m=2)
        t = float(n - 1)
        return float(d1_poly(t)), float(d2_poly(t))

    def update(self, state: np.ndarray) -> Dict[str, float]:
        density = float(np.count_nonzero(state) / max(1, state.size))
        self.densities.append(density)
        if len(self.densities) > self.config.window_size:
            self.densities.popleft()
        d1, d2 = self._savgol_latest_derivatives()
        self.first_derivatives.append(d1)
        if len(self.first_derivatives) > self.config.window_size:
            self.first_derivatives.popleft()
        triggered = 0.0
        if self.config.enabled and len(self.densities) >= 3:
            if d1 < -self.config.theta_c / 2.0 and d2 < -self.config.alpha_c:
                triggered = 1.0
        return {"phase_density": density, "phase_d1": d1, "phase_d2": d2, "phase_triggered": triggered}


def init_density_phase_detector(config: DensityPhaseDetectorConfig) -> DensityPhaseDetector:
    return DensityPhaseDetector(config=config)


def update_density_phase_detector(detector: Optional[DensityPhaseDetector], state: np.ndarray) -> Dict[str, float]:
    if detector is None:
        return {}
    return detector.update(state)


# ---------------------------------------------------------------------------
# Transition functions
# ---------------------------------------------------------------------------
def _apply_transition_table(state: np.ndarray, active_neighbors: np.ndarray, table: Mapping[int, Mapping[int, int]]) -> np.ndarray:
    next_state = np.zeros_like(state)
    for src, mapping in table.items():
        src_mask = state == src
        if not np.any(src_mask):
            continue
        for n_count, target in mapping.items():
            next_state[src_mask & (active_neighbors == n_count)] = target
    return next_state


def _default_transition(state: np.ndarray, active_neighbors: np.ndarray) -> np.ndarray:
    """v0.6.0 default rules."""
    out = np.zeros_like(state)
    out[(state == VOID) & (active_neighbors == 3)] = STRUCTURAL
    for n in range(3):
        out[(state == STRUCTURAL) & (active_neighbors == n)] = STRUCTURAL
    out[(state == STRUCTURAL) & (active_neighbors >= 3)] = COMPUTE
    out[(state == COMPUTE) & (active_neighbors == 1)] = COMPUTE
    out[(state == COMPUTE) & (active_neighbors == 2)] = ENERGY
    out[(state == ENERGY) & (active_neighbors <= 1)] = ENERGY
    out[(state == SENSOR) & (active_neighbors <= 1)] = SENSOR
    return out


# ---------------------------------------------------------------------------
# count_neighbors_3d
# ---------------------------------------------------------------------------
def count_neighbors_3d(state: np.ndarray) -> np.ndarray:
    """Count neighbors by state using np.roll for 3D Moore neighborhood (26 neighbors)."""
    if state.ndim != 3:
        raise ValueError(f"Expected a 3D lattice, got shape={state.shape}")
    out = np.zeros((NUM_STATES,) + state.shape, dtype=np.int16)
    for state_id in range(NUM_STATES):
        indicator = (state == state_id).astype(np.int16)
        counts = np.zeros_like(indicator, dtype=np.int16)
        for dz in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dz == 0 and dy == 0 and dx == 0:
                        continue
                    shifted = np.roll(np.roll(np.roll(indicator, -dz, axis=0), -dy, axis=1), -dx, axis=2)
                    counts += shifted
        out[state_id] = counts
    return out


_count_neighbors_by_state = count_neighbors_3d


def _compute_neighbor_count(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask.astype(np.int16), 1, mode="constant", constant_values=0)
    cluster = np.zeros_like(mask, dtype=np.int16)
    for dz in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0 and dz == 0:
                    continue
                cluster += padded[1+dz:1+dz+mask.shape[0], 1+dy:1+dy+mask.shape[1], 1+dx:1+dx+mask.shape[2]]
    return cluster


# ---------------------------------------------------------------------------
# Memory grid (5 channels)
# ---------------------------------------------------------------------------
def init_memory_grid(shape: Tuple[int, int, int]) -> np.ndarray:
    """5 channels: compute_age, structural_age, memory_strength, energy_reserve, last_active_gen."""
    grid = np.zeros((5,) + shape, dtype=np.float32)
    grid[2, :, :, :] = 1.0
    grid[3, :, :, :] = 1.0
    return grid


def _migrate_memory_grid(memory_grid: np.ndarray, shape: Tuple[int, int, int]) -> np.ndarray:
    """Auto-migrate 3-channel memory grid to 5-channel format."""
    if memory_grid.shape[0] == 5:
        return memory_grid
    if memory_grid.shape[0] == 3:
        new_grid = np.zeros((5,) + shape, dtype=np.float32)
        new_grid[0] = memory_grid[0]
        new_grid[2] = memory_grid[1]
        new_grid[4] = memory_grid[2]
        new_grid[1, :, :, :] = 0.0
        new_grid[3, :, :, :] = 1.0
        return new_grid
    raise ValueError(f"Cannot migrate memory grid with {memory_grid.shape[0]} channels")


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------
@dataclass
class TelemetryWindow:
    transition_matrix: np.ndarray = field(default_factory=lambda: np.zeros((5, 5), dtype=np.int64))
    structural_lifetimes: List[float] = field(default_factory=list)
    compute_lifetimes: List[float] = field(default_factory=list)


def init_telemetry_window() -> TelemetryWindow:
    return TelemetryWindow()


def update_telemetry_window(telemetry: Optional[TelemetryWindow], prev_state: np.ndarray, next_state: np.ndarray, compute_age_snapshot: np.ndarray, structural_age_snapshot: np.ndarray) -> None:
    if telemetry is None:
        return
    flat_prev = prev_state.ravel().astype(np.int64)
    flat_next = next_state.ravel().astype(np.int64)
    for src in range(NUM_STATES):
        src_mask = flat_prev == src
        if not np.any(src_mask):
            continue
        dst_vals = flat_next[src_mask]
        cnts = np.bincount(dst_vals, minlength=NUM_STATES)
        telemetry.transition_matrix[src, :] += cnts[:NUM_STATES]
    structural_left = (prev_state == STRUCTURAL) & (next_state != STRUCTURAL)
    compute_left = (prev_state == COMPUTE) & (next_state != COMPUTE)
    if np.any(structural_left):
        telemetry.structural_lifetimes.extend(structural_age_snapshot[structural_left].astype(float).tolist())
    if np.any(compute_left):
        telemetry.compute_lifetimes.extend(compute_age_snapshot[compute_left].astype(float).tolist())


def summarize_telemetry_window(telemetry: Optional[TelemetryWindow]) -> Tuple[str, Dict[str, Any]]:
    if telemetry is None:
        return "(telemetry disabled)", {}
    matrix = telemetry.transition_matrix
    transitions = sorted([(int(matrix[s,d]),s,d) for s in range(NUM_STATES) for d in range(NUM_STATES) if matrix[s,d]>0], reverse=True)
    top_pairs = [{"from": int(s), "to": int(d), "count": int(c)} for c,s,d in transitions[:10]]
    def _pctl(vals, q):
        return float(np.percentile(np.asarray(vals, dtype=np.float32), q)) if vals else 0.0
    def _hist(vals, bins=10):
        if not vals:
            return {"bins": [], "counts": []}
        c2, e = np.histogram(np.asarray(vals, dtype=np.float32), bins=bins)
        return {"bins": e.tolist(), "counts": c2.tolist()}
    s_med, s_p95 = _pctl(telemetry.structural_lifetimes, 50), _pctl(telemetry.structural_lifetimes, 95)
    c_med, c_p95 = _pctl(telemetry.compute_lifetimes, 50), _pctl(telemetry.compute_lifetimes, 95)
    payload = {"structural": {"median": s_med, "p95": s_p95, "histogram": _hist(telemetry.structural_lifetimes)}, "compute": {"median": c_med, "p95": c_p95, "histogram": _hist(telemetry.compute_lifetimes)}, "transition_matrix": matrix.astype(int).tolist(), "top_transition_pairs": top_pairs}
    summary = f"Telemetry Window | STRUCTURAL median={s_med:.2f} p95={s_p95:.2f} | COMPUTE median={c_med:.2f} p95={c_p95:.2f} | Top transitions={top_pairs[:3]}"
    return summary, payload


def reset_telemetry_window(telemetry: Optional[TelemetryWindow]) -> None:
    if telemetry is None:
        return
    telemetry.transition_matrix.fill(0)
    telemetry.structural_lifetimes.clear()
    telemetry.compute_lifetimes.clear()


def write_telemetry_artifact(path: str | Path, payload: Dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    import json
    with Path(path).open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def apply_with_memory_sandboxed(next_state: np.ndarray, memory_grid: np.ndarray, mem: VoxelMemoryParams, cosmic: CosmicGardenConfig, contraction_phase: bool) -> np.ndarray:
    if not contraction_phase:
        return next_state
    out = next_state.copy()
    mature_compute = memory_grid[0] >= float(mem.age_mature_threshold)
    dense_compute = _compute_neighbor_count(out == COMPUTE) >= (cosmic.damping_radius + 3)
    out[(out == VOID) & mature_compute & dense_compute] = COMPUTE
    return out


def _reverse_contagion_probability(compute_neighbors: np.ndarray, mem: VoxelMemoryParams) -> np.ndarray:
    excess = np.maximum(0, compute_neighbors - mem.reverse_contagion_threshold)
    prob = mem.reverse_contagion_base_prob + mem.reverse_contagion_boost * excess.astype(np.float32)
    prob[compute_neighbors < mem.reverse_contagion_threshold] = 0.0
    return np.minimum(prob, 0.95)


# ---------------------------------------------------------------------------
# step function
# ---------------------------------------------------------------------------
def step(state: np.ndarray, rule_spec: Mapping[str, Any], rng: np.random.Generator, inactivity_steps: Optional[np.ndarray] = None, memory_grid: Optional[np.ndarray] = None, age_grid: Optional[np.ndarray] = None, current_gen: int = 0, telemetry: Optional[TelemetryWindow] = None, phase_detector: Optional[DensityPhaseDetector] = None) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, Dict[str, float]]:
    """Single CA step. Returns (next_state, inactivity_steps, memory_grid, age_grid, metrics).
    Memory grid 5 channels: compute_age, structural_age, memory_strength, energy_reserve, last_active_gen.
    Supports 3->5 channel auto-migration.
    """
    if state.ndim != 3:
        raise ValueError(f"Expected a 3D lattice, got shape={state.shape}")
    shape = state.shape
    if memory_grid is None:
        memory_grid = init_memory_grid(shape)
    elif memory_grid.shape[0] != 5:
        memory_grid = _migrate_memory_grid(memory_grid, shape)
    if age_grid is None:
        age_grid = np.zeros(shape, dtype=np.float32)
    if inactivity_steps is None:
        inactivity_steps = np.zeros(shape, dtype=np.int16)
    compute_age_snapshot = memory_grid[0].copy()
    structural_age_snapshot = memory_grid[1].copy()
    table = _load_transition_table(rule_spec)
    decay_cfg = _load_decay_config(rule_spec)
    stoch = _load_stochastic_config(rule_spec)
    contagion = _load_contagion_config(rule_spec)
    cosmic = _load_cosmic_config(rule_spec)
    mem = VoxelMemoryParams()
    exp = _load_experimental_config(rule_spec)
    neighbor_counts = count_neighbors_3d(state)
    active_neighbors = np.sum(neighbor_counts[1:], axis=0)
    # Deterministic transitions
    out = _apply_transition_table(state, active_neighbors, table) if table else _default_transition(state, active_neighbors)
    # Phase 4: Equanimity Shield -- compute shield mask ONCE before all kills
    # P_resist(a, M) = P_max * (1 - exp(-(a - a_m) / tau)) * tanh(gamma * M)
    # Nemo's sigmoid: cells that have endured gain composure under pressure
    was_compute = state == COMPUTE
    equanimity_mask = np.zeros(shape, dtype=bool)
    mature_compute = was_compute & (memory_grid[0] > mem.equanimity_age_min)
    if np.any(mature_compute):
        age_excess = np.maximum(0.0, memory_grid[0] - mem.equanimity_age_min)
        p_resist = mem.equanimity_p_max * (
            1.0 - np.exp(-age_excess / mem.equanimity_tau)
        ) * np.tanh(mem.equanimity_gamma * memory_grid[2])
        equanimity_mask = mature_compute & (rng.random(shape) < p_resist)
    # Stochastic transitions
    if stoch.enabled:
        structural = out == STRUCTURAL; compute = out == COMPUTE
        out[structural & (rng.random(shape) < stoch.structural_to_energy_prob)] = ENERGY
        structural = out == STRUCTURAL
        out[structural & (rng.random(shape) < stoch.structural_to_sensor_prob)] = SENSOR
        out[compute & (rng.random(shape) < stoch.compute_to_energy_prob)] = ENERGY
        compute = out == COMPUTE
        out[compute & (rng.random(shape) < stoch.compute_to_sensor_prob)] = SENSOR
    # Forward contagion
    if contagion.enabled:
        energy_n = neighbor_counts[ENERGY]; sensor_n = neighbor_counts[SENSOR]
        structural = out == STRUCTURAL; compute = out == COMPUTE
        out[structural & (energy_n >= contagion.energy_neighbor_threshold) & (rng.random(shape) < contagion.structural_energy_conversion_prob)] = ENERGY
        structural = out == STRUCTURAL
        out[structural & (sensor_n >= contagion.sensor_neighbor_threshold) & (rng.random(shape) < contagion.structural_sensor_conversion_prob)] = SENSOR
        out[compute & (energy_n >= contagion.energy_neighbor_threshold) & (rng.random(shape) < contagion.compute_energy_conversion_prob)] = ENERGY
        compute = out == COMPUTE
        out[compute & (sensor_n >= contagion.sensor_neighbor_threshold) & (rng.random(shape) < contagion.compute_sensor_conversion_prob)] = SENSOR
    # Reverse contagion
    if contagion.enabled:
        structural = out == STRUCTURAL; compute_n = neighbor_counts[COMPUTE]
        rc_prob = _reverse_contagion_probability(compute_n, mem)
        rc_prob = np.minimum(0.95, rc_prob * np.maximum(0.25, memory_grid[2]))
        out[structural & (rng.random(shape) < rc_prob)] = COMPUTE
    # Stochastic decay (0.005 -- CRITICAL)
    if stoch.enabled:
        structural = out == STRUCTURAL; energy = out == ENERGY; sensor = out == SENSOR
        out[structural & (rng.random(shape) < stoch.structural_to_void_decay_prob)] = VOID
        out[energy & (rng.random(shape) < stoch.energy_to_void_decay_prob)] = VOID
        out[sensor & (rng.random(shape) < stoch.sensor_to_void_decay_prob)] = VOID
    # Inactivity decay
    if decay_cfg.enabled:
        structural = out == STRUCTURAL
        low_support = active_neighbors <= decay_cfg.inactivity_neighbor_threshold
        inactivity_steps = np.where(structural & low_support, inactivity_steps + 1, 0).astype(np.int16)
        out[structural & (inactivity_steps >= decay_cfg.structural_inactive_steps_to_decay)] = VOID
        inactivity_steps[~(out == STRUCTURAL)] = 0
    # Energy conversion
    energy = out == ENERGY
    compute_cluster = _compute_neighbor_count(out == COMPUTE)
    scluster = _compute_neighbor_count(out == STRUCTURAL)
    e2c_prob = np.full(shape, mem.energy_to_compute_prob, dtype=np.float32)
    mitigated = np.maximum(mem.forward_contagion_floor * mem.energy_to_compute_prob, mem.energy_to_compute_prob - mem.forward_contagion_penalty)
    e2c_prob[scluster >= mem.forward_contagion_threshold] = mitigated
    superpod = compute_cluster >= cosmic.super_pod_threshold
    e2c_prob[superpod] = np.minimum(0.95, e2c_prob[superpod] + cosmic.biofilm_leech_rate * 0.5)
    memory_grid[3][superpod] = np.maximum(0.05, memory_grid[3][superpod] * (1.0 - cosmic.biofilm_leech_rate))
    out[energy & (rng.random(shape) < e2c_prob)] = COMPUTE
    # Memory reinforcement (Phase 3: half-rate aging for isolated COMPUTE)
    compute = out == COMPUTE
    isolated_compute = compute & (active_neighbors == 0)
    connected_compute = compute & (active_neighbors > 0)
    memory_grid[0][connected_compute] = np.minimum(memory_grid[0][connected_compute] + 1.0, 65535.0)
    memory_grid[0][isolated_compute] = np.minimum(memory_grid[0][isolated_compute] + 0.5, 65535.0)
    memory_grid[4][compute] = float(current_gen)
    memory_grid[2][compute] = np.minimum(memory_grid[2][compute] * mem.rag_reinforcement_boost, 2.0)
    # Bamboo protocol
    structural = out == STRUCTURAL
    memory_grid[1][structural] = np.minimum(memory_grid[1][structural] + 1.0, float(cosmic.bamboo_max_length))
    memory_grid[2][structural] = np.minimum(memory_grid[2][structural] + cosmic.otolith_vector, 2.0)
    rebirth = structural & (memory_grid[1] >= float(cosmic.bamboo_rebirth_age))
    out[rebirth] = COMPUTE
    memory_grid[1][~(out == STRUCTURAL)] = 0.0
    # Decay resistance
    dropped_compute = (out == VOID) & (memory_grid[0] > 0)
    age_arr = memory_grid[0]
    resistance = np.zeros_like(memory_grid[2])
    young = age_arr <= mem.age_young_threshold
    mature = (age_arr > mem.age_young_threshold) & (age_arr <= mem.age_mature_threshold)
    old = age_arr > mem.age_mature_threshold
    resistance[young] = (age_arr[young] / max(1.0, float(mem.age_young_threshold))) * mem.resistance_max
    resistance[mature] = mem.resistance_max
    resistance[old] = mem.resistance_max * np.exp(-(age_arr[old] - mem.age_mature_threshold) / 500.0)
    resistance *= np.minimum(memory_grid[2], 1.5)
    compute_cluster2 = _compute_neighbor_count(out == COMPUTE)
    resistance = np.minimum(0.98, resistance + (compute_cluster2 >= cosmic.cluster_coherence_threshold).astype(np.float32) * (cosmic.cluster_shield_bonus + cosmic.shield_strength * 0.15))
    # Phase 3: Void Sanctuary Shield -- isolated COMPUTE gets 50x resistance
    void_sanctuary_mask = dropped_compute & (active_neighbors == 0)
    resistance[void_sanctuary_mask] = np.minimum(0.98, resistance[void_sanctuary_mask] * mem.void_sanctuary_multiplier)
    # Phase 3: Epsilon Buffer -- packed cells get survival floor (>5.7%)
    packed_mask = dropped_compute & (active_neighbors >= mem.epsilon_n_c)
    if np.any(packed_mask):
        excess = (active_neighbors[packed_mask].astype(np.float32) - float(mem.epsilon_n_c))
        p_reg = mem.epsilon_p_max - mem.epsilon_buffer * np.exp(-excess / mem.epsilon_tau)
        survival_floor = np.maximum(1.0 - p_reg, 0.057)
        resistance[packed_mask] = np.maximum(resistance[packed_mask], survival_floor)
    out[dropped_compute & (rng.random(shape) < resistance)] = COMPUTE
    # Phase 3: Mamba-Viking memory dynamics (state-space update)
    # M(t+1) = M(t) * exp(-1/tau(d)) + B(d)*d + S*Phi(age)
    # where d = local non-void density, tau adapts to activity
    inactive = ~(out == COMPUTE)
    local_density = active_neighbors.astype(np.float32) / 26.0
    # Adaptive tau: higher in active regions (slow decay), lower in dead regions
    tau = mem.mamba_tau_base + mem.mamba_tau_scale * np.tanh(
        local_density / max(mem.mamba_delta_threshold, 1e-6))
    decay_factor = np.exp(-1.0 / np.maximum(tau, 0.1))
    # Boost proportional to local activity
    boost = (mem.mamba_boost_base + mem.mamba_boost_gain * local_density) * local_density
    # Age stability: older cells get memory bonus
    age_stability = mem.mamba_age_stability_gain * np.tanh(
        memory_grid[0] / max(float(mem.age_mature_threshold), 1.0))
    # Apply state-space update
    memory_grid[2][inactive] *= decay_factor[inactive]
    memory_grid[2] += boost
    memory_grid[2] += age_stability
    # High-delta floor: active regions keep memory above floor
    high_delta = local_density > mem.mamba_delta_threshold
    memory_grid[2][high_delta] = np.maximum(
        memory_grid[2][high_delta], mem.mamba_high_delta_floor)
    # Global floor and ceiling
    memory_grid[2] = np.clip(memory_grid[2], 0.01, 2.0)
    # Phase 4: Equanimity Shield restoration -- restore shielded cells after ALL kills
    if np.any(equanimity_mask):
        out[equanimity_mask & (out != COMPUTE)] = COMPUTE
    # Analogue mutation (MUST have pre_mut = out.copy() before mutation)
    pre_mut = out.copy()
    mut_mask = rng.random(shape) < cosmic.analogue_mutation
    out[mut_mask & (pre_mut == STRUCTURAL)] = COMPUTE
    out[mut_mask & (pre_mut == COMPUTE)] = ENERGY
    out[mut_mask & (pre_mut == ENERGY)] = SENSOR
    out[mut_mask & (pre_mut == SENSOR)] = STRUCTURAL
    memory_grid[0][out != COMPUTE] = 0.0
    # Memory grid update (5 channels: compute_age, structural_age, memory_strength, energy_reserve, last_active_gen)
    # Age grid update
    age_grid = np.where(out != VOID, age_grid + 1.0, 0.0).astype(np.float32)
    phase_signals = update_density_phase_detector(phase_detector, out)
    if phase_detector is not None and phase_detector.config.trigger_sandboxed_memory and phase_signals.get("phase_triggered", 0.0) > 0:
        out = apply_with_memory_sandboxed(out, memory_grid, mem, cosmic, contraction_phase=True)
    update_telemetry_window(telemetry, state, out, compute_age_snapshot, structural_age_snapshot)
    counts = np.bincount(out.ravel(), minlength=NUM_STATES)
    total_cells = max(1, int(np.prod(shape)))
    non_void_total = int(np.sum(counts[1:]))
    probs = counts[1:] / max(1, non_void_total)
    non_zero_probs = probs[probs > 0]
    entropy = float(-np.sum(non_zero_probs * np.log(non_zero_probs))) if non_zero_probs.size else 0.0
    normalized_entropy = float(entropy / np.log(4.0)) if non_zero_probs.size > 1 else 0.0
    # Phase 5: add compute age metrics for longevity-aware fitness
    compute_mask_final = out == COMPUTE
    compute_median_age = float(np.median(memory_grid[0][compute_mask_final])) if np.any(compute_mask_final) else 0.0
    compute_max_age = float(np.max(memory_grid[0][compute_mask_final])) if np.any(compute_mask_final) else 0.0
    compute_mean_age = float(np.mean(memory_grid[0][compute_mask_final])) if np.any(compute_mask_final) else 0.0
    metrics = {"entropy": normalized_entropy, "structural_ratio": float(counts[STRUCTURAL] / max(1, non_void_total)), "void_ratio": float(counts[VOID] / total_cells), "compute_ratio": float(counts[COMPUTE] / total_cells), "energy_ratio": float(counts[ENERGY] / total_cells), "sensor_ratio": float(counts[SENSOR] / total_cells), "compute_median_age": compute_median_age, "compute_max_age": compute_max_age, "compute_mean_age": compute_mean_age}
    metrics.update(phase_signals)
    return (out.astype(np.uint8, copy=False), inactivity_steps.astype(np.int16, copy=False), memory_grid.astype(np.float32, copy=False), age_grid.astype(np.float32, copy=False), metrics)


def step_ca_lattice(state: np.ndarray, rule_spec: Mapping[str, Any], rng: np.random.Generator, inactivity_steps: Optional[np.ndarray] = None, memory_grid: Optional[np.ndarray] = None, current_gen: int = 0, telemetry: Optional[TelemetryWindow] = None, phase_detector: Optional[DensityPhaseDetector] = None) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Dict[str, float]]:
    """Legacy step function returning 4-tuple (state, inactivity, memory, metrics)."""
    ns, inact, mem_grid, _age, metrics = step(state, rule_spec, rng, inactivity_steps, memory_grid, None, current_gen, telemetry, phase_detector)
    return ns, inact, mem_grid, metrics


# ---------------------------------------------------------------------------
# census, compute_entropy, compute_fitness
# ---------------------------------------------------------------------------
def census(state: np.ndarray) -> Dict[str, int]:
    counts = np.bincount(state.ravel(), minlength=NUM_STATES)
    return {"void": int(counts[VOID]), "structural": int(counts[STRUCTURAL]), "compute": int(counts[COMPUTE]), "energy": int(counts[ENERGY]), "sensor": int(counts[SENSOR]), "total": int(state.size)}


def compute_entropy(state: np.ndarray) -> float:
    counts = np.bincount(state.ravel(), minlength=NUM_STATES)
    non_void = counts[1:]
    total = int(np.sum(non_void))
    if total == 0:
        return 0.0
    probs = non_void / total
    non_zero = probs[probs > 0]
    if non_zero.size <= 1:
        return 0.0
    ent = float(-np.sum(non_zero * np.log(non_zero)))
    return float(ent / np.log(4.0))


def compute_fitness(state: np.ndarray) -> float:
    total = max(1, state.size)
    counts = np.bincount(state.ravel(), minlength=NUM_STATES)
    void_ratio = float(counts[VOID]) / total
    compute_ratio = float(counts[COMPUTE]) / total
    ent = compute_entropy(state)
    compute_bonus = min(1.0, compute_ratio * 10.0 + 0.5) if compute_ratio > 0 else 0.3
    fitness = ent * (1.0 - void_ratio) * compute_bonus
    return float(np.clip(fitness, 0.0, 1.0))


def run_mini_lattice_mutation_trials(base_rule_spec: Mapping[str, Any], mutation_specs: List[Mapping[str, Any]], trials_per_mutation: int = 3, lattice_size: int = 16, steps: int = 6, seed: int = 0) -> List[Dict[str, Any]]:
    rng = np.random.default_rng(seed)
    results: List[Dict[str, Any]] = []
    for mutation_id, mutation in enumerate(mutation_specs):
        trial_scores: List[float] = []
        for trial in range(trials_per_mutation):
            state = np.zeros((lattice_size,) * 3, dtype=np.uint8)
            c = lattice_size // 2
            state[c, c, c] = STRUCTURAL
            memory = init_memory_grid(state.shape)
            inactivity = np.zeros_like(state, dtype=np.int16)
            rule = dict(base_rule_spec)
            rule_params = dict(rule.get("params", {}))
            trial_mut = dict(mutation)
            if "transitions" in trial_mut and "transitions" in rule_params:
                td = dict(rule_params["transitions"]); td.update(trial_mut.pop("transitions")); rule_params["transitions"] = td
            rule_params.update(trial_mut); rule["params"] = rule_params
            for gen in range(steps):
                state, inactivity, memory, metrics = step_ca_lattice(state, rule, rng, inactivity, memory, gen + 1)
            trial_scores.append(float(metrics.get("compute_ratio", 0.0) + metrics.get("structural_ratio", 0.0)))
        avg = float(np.mean(np.asarray(trial_scores, dtype=np.float32))) if trial_scores else 0.0
        label = "collapse" if avg < 0.05 else "stable" if avg < 0.35 else "growth"
        results.append({"mutation_id": mutation_id, "mean_survival_score": avg, "classification": label, "hypothesis_only": True, "lattice_size": lattice_size})
    return results
