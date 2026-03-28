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

# Phase 13: GPU Acceleration via CuPy
try:
    from scripts.gpu_accelerator import gpu, to_gpu, to_cpu, sync, is_gpu_available, GPU_AVAILABLE
    if GPU_AVAILABLE:
        import cupy as cp
        _xp = cp  # Use CuPy for array operations
    else:
        _xp = np
except ImportError:
    GPU_AVAILABLE = False
    _xp = np

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
    # Phase 10.5: Lowered from 3.0 to 1.0 (AURA: "Anti-Star early shield onset")
    equanimity_age_min: float = 1.0
    equanimity_p_max: float = 0.85
    equanimity_tau: float = 2.0  # Phase 10.6: was 5.0, accelerated for Ice Battery
    equanimity_gamma: float = 0.5
    # Phase 10.5: Anti-Star Density Collapse (AURA Deep Think 5.0)
    # VOID cells near COMPUTE rapidly nucleate to STRUCTURAL, forming a protective shell
    antistar_enabled: bool = True
    antistar_prob: float = 0.30  # P(VOID->STRUCTURAL | COMPUTE neighbor)
    # Phase 10.5: MOF Battery (AURA Deep Think 5.0)
    # ENERGY cells near COMPUTE funnel energy_reserve to boost elder survival
    mof_battery_enabled: bool = True
    mof_energy_boost: float = 0.15  # energy_reserve boost per ENERGY neighbor
    mof_drain_rate: float = 0.02    # energy drained from donor ENERGY cell
    # Phase 6a: Loving-Kindness (metta) -- ENERGY warms STRUCTURAL cells
    metta_beta: float = 0.25          # max survival floor boost (25%)
    metta_warmth_rate: float = 0.02   # warmth accumulation rate per ENERGY neighbor
    metta_warmth_decay: float = 0.95  # warmth decays when no ENERGY neighbors
    # Phase 6b: Sympathetic Joy (mudita) -- resonance from mature neighbors
    joy_beta: float = 0.35           # max resonance multiplier (35%)
    joy_age_scale: float = 15.0      # age excess scaling factor
    # Phase 6c: Mindsight + Mycelial Network + Compassion
    mindsight_s_max: float = 1.0     # max signal magnitude
    mindsight_sigma_opp: float = 0.15  # opportunity gradient scale
    mindsight_sigma_dis: float = 0.10  # distress gradient scale
    mindsight_threshold: float = 0.3   # |S| threshold for action
    mindsight_radius: int = 12         # regional density filter radius
    mycelial_k_iter: int = 3           # diffusion iterations (3 = ~3-voxel range per interval)
    mycelial_lambda_distress: float = 12.0   # distress decay length
    mycelial_lambda_opportunity: float = 8.0 # opportunity decay length
    compassion_beta: float = 0.50      # remote resistance buff (+50%)
    compassion_gamma: float = 0.20     # local cost (20% energy/memory drain)
    compassion_distance_scale: float = 15.0  # exp(-d/15) distance decay
    compassion_age_scale_min: float = 30.0   # min adaptive age scale
    compassion_age_scale_factor: float = 1.5 # a_scale = max(min, max_age * factor)
    # Phase 10.6: Ice Battery (Nemo's thermodynamic overhaul)
    ice_battery_k: float = 2.5         # boost coefficient
    ice_battery_alpha: float = 0.7     # energy scaling exponent (sublinear)
    ice_battery_age_peak: float = 4.0  # optimal burn window center
    ice_battery_sigma: float = 1.0     # Gaussian window width
    ice_battery_threshold: float = 0.5 # min energy_reserve to activate
    ice_battery_burn_rate: float = 0.20 # 20% E consumed per step when active
    ice_battery_p_max: float = 0.95    # hard cap on total P_resist
    # Phase 10.6: Trash Battery (entropy harvest from void)
    trash_harvest_eff: float = 0.15    # base harvest rate
    trash_entropic_flux: float = 0.05  # energy per void neighbor
    trash_max_reclaim: float = 0.05    # cap per step
    # Phase 10.7: Expansive Compassion Continuum (Nemo's circulatory model)
    elder_age_threshold: float = 8.0        # tau_elder: age for Elder status
    elder_baseline_fraction: float = 0.15   # beta_base: continuous circulation fraction
    elder_membrane_decay: float = 0.05      # lambda_mem: permeability decay with age
    elder_circulation_radius: int = 2       # r_max: distribution neighborhood
    elder_sustenance_threshold: float = 1.0 # E_sustain: minimum energy to maintain
    equanimity_zero_waste: bool = True      # Zero waste heat for equanimous cells
    equanimity_stability_window: int = 3    # w_eq: steps for stability check
    equanimity_stability_sigma: float = 0.05 # sigma_stable: max variance for stability
    base_dissipation: float = 0.02          # standard heat loss for non-equanimous
    parasite_max_ticks: int = 100           # anti-subsidy: max consecutive receiving
    parasite_penalty_rate: float = 0.01     # extra energy stress per tick over limit
    # Phase 6 signal interval (expensive ops every K steps)
    signal_interval: int = 10

    # Phase 10.8: Great Oscillation (Sinusoidal Energy Drought)
    drought_enabled: bool = True
    drought_cycle_length: int = 10000        # T: full sinusoidal cycle in generations
    drought_amplitude: float = 0.30          # A: amplitude of oscillation
    drought_baseline: float = 0.70           # B: baseline fraction (min = B-A = 0.40)
    drought_start_gen: int = 0               # gen offset for drought cycle


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
    """Count neighbors by state using np.roll for 3D Moore neighborhood (26 neighbors).
    GPU-accelerated via CuPy when available (44x speedup at 128^3)."""
    if state.ndim != 3:
        raise ValueError(f"Expected a 3D lattice, got shape={state.shape}")
    xp = _xp
    s = to_gpu(state) if GPU_AVAILABLE else state
    out = xp.zeros((NUM_STATES,) + state.shape, dtype=xp.int16)
    for state_id in range(NUM_STATES):
        indicator = (s == state_id).astype(xp.int16)
        counts = xp.zeros_like(indicator, dtype=xp.int16)
        for dz in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dz == 0 and dy == 0 and dx == 0:
                        continue
                    shifted = xp.roll(xp.roll(xp.roll(indicator, -dz, axis=0), -dy, axis=1), -dx, axis=2)
                    counts += shifted
        out[state_id] = counts
    if GPU_AVAILABLE:
        sync()
        out = to_cpu(out)
    return out


_count_neighbors_by_state = count_neighbors_3d


def _max_neighbor_value(field: np.ndarray) -> np.ndarray:
    """Find the maximum value among Moore neighbors for a 3D scalar field.
    Used for Sympathetic Joy: find the oldest COMPUTE neighbor.
    Optimized: pad once + slice (avoids 26 np.roll copies)."""
    padded = np.pad(field, 1, mode="constant", constant_values=0.0)
    nz, ny, nx = field.shape
    result = np.zeros_like(field)
    for dz in range(3):
        for dy in range(3):
            for dx in range(3):
                if dz == 1 and dy == 1 and dx == 1:
                    continue
                np.maximum(result, padded[dz:dz+nz, dy:dy+ny, dx:dx+nx], out=result)
    return result


# Cache for box filter normalization grids (shape -> count_grid)
_box_filter_count_cache: Dict[Tuple[int, ...], np.ndarray] = {}

def _box_cumsum_1d(arr: np.ndarray, axis: int, r: int, n: int) -> np.ndarray:
    """Apply 1D box-sum along one axis using prefix sums."""
    w = 2 * r + 1
    pad_widths = [(0, 0)] * 3
    pad_widths[axis] = (r, r)
    padded = np.pad(arr, pad_widths, mode='constant', constant_values=0.0)
    zs = list(padded.shape); zs[axis] = 1
    padded = np.concatenate([np.zeros(zs, dtype=np.float64), padded], axis=axis)
    cs = np.cumsum(padded, axis=axis)
    slices_hi = [slice(None)] * 3
    slices_lo = [slice(None)] * 3
    slices_hi[axis] = slice(w, w + n)
    slices_lo[axis] = slice(0, n)
    return cs[tuple(slices_hi)] - cs[tuple(slices_lo)]

def _separable_box_filter_3d(field: np.ndarray, radius: int) -> np.ndarray:
    """Fast R-radius 3D box filter via separable 1D cumsum trick.
    O(N^3) regardless of R. Caches normalization count for repeated calls."""
    r = radius
    cache_key = (field.shape, r)
    # Compute count normalization grid (cached per shape+radius)
    if cache_key not in _box_filter_count_cache:
        count = np.ones(field.shape, dtype=np.float64)
        for axis in range(3):
            count = _box_cumsum_1d(count, axis, r, field.shape[axis])
        _box_filter_count_cache[cache_key] = np.maximum(count, 1.0).astype(np.float64)
    count = _box_filter_count_cache[cache_key]
    # Compute box sum of actual field
    result = field.astype(np.float64)
    for axis in range(3):
        result = _box_cumsum_1d(result, axis, r, field.shape[axis])
    result /= count
    return result.astype(np.float32)


def _mycelial_diffuse(signal: np.ndarray, energy_mask: np.ndarray,
                      k_iter: int, decay_per_iter: float) -> np.ndarray:
    """Iterative 3x3x3 diffusion of signal through ENERGY cells.
    Each iteration: average neighbors (masked to ENERGY), then decay.
    Optimized: pre-compute padded energy mask (constant across iterations)."""
    field = signal.copy()
    nz, ny, nx = field.shape
    energy_f = energy_mask.astype(np.float32)
    # Pre-pad the energy mask once (it does not change across iterations)
    padded_mask = np.pad(energy_f, 1, mode='constant', constant_values=0.0)
    # Pre-compute 26 mask slices (constant across iterations)
    mask_slices = []
    offsets = []
    for dz in range(3):
        for dy in range(3):
            for dx in range(3):
                if dz == 1 and dy == 1 and dx == 1:
                    continue
                mask_slices.append(padded_mask[dz:dz+nz, dy:dy+ny, dx:dx+nx])
                offsets.append((dz, dy, dx))
    # Pre-compute neighbor count from energy mask (constant)
    neighbor_count = np.zeros_like(field)
    for ms in mask_slices:
        neighbor_count += ms
    safe_count = np.maximum(neighbor_count, 1.0)
    inv_decay = 1.0 - decay_per_iter
    for _ in range(k_iter):
        padded = np.pad(field, 1, mode='constant', constant_values=0.0)
        neighbor_sum = np.zeros_like(field)
        for i, (dz, dy, dx) in enumerate(offsets):
            neighbor_sum += padded[dz:dz+nz, dy:dy+ny, dx:dx+nx] * mask_slices[i]
        avg = neighbor_sum / safe_count
        field = np.where(energy_mask, field * decay_per_iter + avg * inv_decay, 0.0)
    return field.astype(np.float32)


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
# Memory grid (8 channels -- Phase 6 expansion)
# Channel map:
#   0: compute_age        (Phase 1+)
#   1: structural_age     (Phase 1+)
#   2: memory_strength    (Phase 1+)
#   3: energy_reserve     (Phase 1+, repurposed Phase 6c for compassion cost)
#   4: last_active_gen    (Phase 1+)
#   5: signal_field       (Phase 6c: mycelial signal amplitude)
#   6: warmth             (Phase 6a: metta/loving-kindness accumulation)
#   7: compassion_cooldown (Phase 6c: prevents echo/spam)
# ---------------------------------------------------------------------------
MEMORY_CHANNELS = 8

def init_memory_grid(shape: Tuple[int, int, int]) -> np.ndarray:
    """8 channels: compute_age, structural_age, memory_strength, energy_reserve,
    last_active_gen, signal_field, warmth, compassion_cooldown."""
    grid = np.zeros((MEMORY_CHANNELS,) + shape, dtype=np.float32)
    grid[2, :, :, :] = 1.0   # memory_strength default
    grid[3, :, :, :] = 1.0   # energy_reserve default
    return grid


def _migrate_memory_grid(memory_grid: np.ndarray, shape: Tuple[int, int, int]) -> np.ndarray:
    """Auto-migrate older memory grids to 8-channel format."""
    if memory_grid.shape[0] == MEMORY_CHANNELS:
        return memory_grid
    if memory_grid.shape[0] == 5:
        # Phase 5 -> Phase 6: add 3 new channels (signal, warmth, cooldown)
        new_grid = np.zeros((MEMORY_CHANNELS,) + shape, dtype=np.float32)
        new_grid[:5] = memory_grid
        return new_grid
    if memory_grid.shape[0] == 3:
        new_grid = np.zeros((MEMORY_CHANNELS,) + shape, dtype=np.float32)
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
    elif memory_grid.shape[0] != MEMORY_CHANNELS:
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
    # Phase 10.8: Great Oscillation -- Sinusoidal Energy Drought (computed EARLY, used by all energy systems)
    drought_multiplier = 1.0
    if mem.drought_enabled and current_gen > 0:
        cycle_pos = (current_gen - mem.drought_start_gen) % mem.drought_cycle_length
        drought_multiplier = mem.drought_baseline + mem.drought_amplitude * np.cos(
            2.0 * np.pi * cycle_pos / mem.drought_cycle_length
        )
    # Phase 10.5: Anti-Star Density Collapse (AURA Deep Think 5.0)
    # VOID cells adjacent to COMPUTE rapidly nucleate to STRUCTURAL, forming a protective shell
    if mem.antistar_enabled:
        compute_neighbor_count = neighbor_counts[COMPUTE]
        void_near_compute = (out == VOID) & (compute_neighbor_count > 0)
        antistar_roll = rng.random(shape) < mem.antistar_prob
        out[void_near_compute & antistar_roll] = STRUCTURAL
    # Phase 10.5: MOF Battery (AURA Deep Think 5.0)
    # ENERGY cells near COMPUTE funnel energy_reserve to boost elder survival
    if mem.mof_battery_enabled:
        compute_now = out == COMPUTE
        energy_now = out == ENERGY
        # COMPUTE cells receive energy boost from nearby ENERGY cells
        energy_neighbor_count_for_compute = neighbor_counts[ENERGY].astype(np.float32)
        boost = mem.mof_energy_boost * energy_neighbor_count_for_compute
        boost *= drought_multiplier  # Phase 10.8 drought modulation
        memory_grid[3][compute_now] = np.minimum(2.0, memory_grid[3][compute_now] + boost[compute_now])
        # ENERGY cells near COMPUTE slowly drain (sacrifice for the elders)
        compute_neighbor_count_e = neighbor_counts[COMPUTE]
        draining = energy_now & (compute_neighbor_count_e > 0)
        memory_grid[3][draining] = np.maximum(0.05, memory_grid[3][draining] - mem.mof_drain_rate)
    # Phase 10.6: Trash Battery -- STRUCTURAL cells harvest entropy from void neighbors
    # E_reclaim = min(harvest_eff * N_void * entropic_flux, max_reclaim)
    structural_now = state == STRUCTURAL
    n_void_neighbors = neighbor_counts[VOID]
    trash_harvestable = structural_now & (n_void_neighbors > 0)
    if np.any(trash_harvestable):
        e_reclaimed = np.minimum(
            mem.trash_harvest_eff * n_void_neighbors * mem.trash_entropic_flux,
            mem.trash_max_reclaim
        )
        e_reclaimed *= drought_multiplier  # Phase 10.8 drought modulation
        # Route harvested energy to the memory grid energy_reserve channel
        # STRUCTURAL stores it, then MOF battery delivers it to nearby COMPUTE
        memory_grid[3][trash_harvestable] = np.minimum(
            5.0, memory_grid[3][trash_harvestable] + e_reclaimed[trash_harvestable]
        )
    # Phase 10.7: Elder Circulation -- continuous fountain-model energy flow
    # Elders (age >= threshold, energy > mean) circulate excess to needy neighbors
    # This is PROACTIVE compassion: no distress trigger needed
    compute_now_circ = out == COMPUTE
    if np.any(compute_now_circ):
        compute_ages = memory_grid[0][compute_now_circ]
        compute_energies = memory_grid[3][compute_now_circ]
        energy_mean = compute_energies.mean() if compute_energies.size > 0 else 0.0
        elder_mask = compute_now_circ & (memory_grid[0] >= mem.elder_age_threshold) & (memory_grid[3] > energy_mean)
        if np.any(elder_mask):
            # Calculate circulation amount per elder
            excess = np.maximum(0.0, memory_grid[3] - mem.elder_sustenance_threshold)
            age_factor = np.exp(-mem.elder_membrane_decay * np.maximum(0.0, memory_grid[0] - mem.elder_age_threshold))
            e_circulate = excess * mem.elder_baseline_fraction * age_factor
            e_circulate *= drought_multiplier  # Phase 10.8 drought modulation
            # Distribute to all non-void cells in neighborhood (pull-agnostic)
            # Use the smoothed density field as a proxy for neighborhood need
            non_void_mask = out != VOID
            deficit = np.maximum(0.0, mem.elder_sustenance_threshold - memory_grid[3])
            # Simple distribution: elder energy spread to nearby cells via box filter
            elder_donation_field = np.where(elder_mask, e_circulate, 0.0).astype(np.float32)
            if np.any(elder_donation_field > 0):
                # Use R=2 box filter to diffuse donations to neighborhood
                smoothed_donation = _separable_box_filter_3d(elder_donation_field, radius=mem.elder_circulation_radius)
                # Apply only to non-void cells with deficit
                receiving = non_void_mask & (deficit > 0)
                memory_grid[3][receiving] = np.minimum(
                    5.0, memory_grid[3][receiving] + smoothed_donation[receiving]
                )
                # Deduct from elders
                memory_grid[3][elder_mask] -= e_circulate[elder_mask]
                memory_grid[3] = np.maximum(0.0, memory_grid[3])
    # Phase 10.7: Thermodynamic Equanimity -- zero waste heat for stable cells
    # Equanimous cells are superconductors: processing sensation without friction
    if mem.equanimity_zero_waste:
        compute_for_heat = out == COMPUTE
        if np.any(compute_for_heat):
            # Simple stability check: cells with age > stability_window and low energy variance
            stable_cells = compute_for_heat & (memory_grid[0] > mem.equanimity_stability_window)
            # Non-equanimous cells lose energy to waste heat
            reactive_cells = compute_for_heat & ~stable_cells
            if np.any(reactive_cells):
                heat_loss = mem.base_dissipation * memory_grid[3][reactive_cells]
                memory_grid[3][reactive_cells] = np.maximum(0.0, memory_grid[3][reactive_cells] - heat_loss)
            # Equanimous cells: ZERO waste heat (superconductor state!)
            # They keep all their energy -- this is thermodynamic enlightenment
    # Phase 4: Equanimity Shield -- compute shield mask ONCE before all kills
    # P_resist(a, M) = P_max * (1 - exp(-(a - a_m) / tau)) * tanh(gamma * M)
    # Nemo's sigmoid: cells that have endured gain composure under pressure
    was_compute = state == COMPUTE
    equanimity_mask = np.zeros(shape, dtype=bool)
    mature_compute = was_compute & (memory_grid[0] > mem.equanimity_age_min)
    if np.any(mature_compute):
        age_excess = np.maximum(0.0, memory_grid[0] - mem.equanimity_age_min)
        # Phase 10.6: Base Equanimity (with accelerated tau=2.0)
        p_base = mem.equanimity_p_max * (
            1.0 - np.exp(-age_excess / mem.equanimity_tau)
        ) * np.tanh(mem.equanimity_gamma * memory_grid[2])
        # Phase 10.6: Ice Battery boost -- COMPUTE elders burn stored energy for resistance spike
        # P_ice = k * E^alpha * exp(-((age - peak)^2) / (2*sigma^2))
        e_reserve = memory_grid[3]  # energy_reserve channel
        ice_active = mature_compute & (e_reserve > mem.ice_battery_threshold)
        p_ice = np.zeros(shape, dtype=np.float32)
        if np.any(ice_active):
            age_field = memory_grid[0]
            p_ice[ice_active] = (
                mem.ice_battery_k
                * np.power(e_reserve[ice_active], mem.ice_battery_alpha)
                * np.exp(-((age_field[ice_active] - mem.ice_battery_age_peak) ** 2)
                         / (2.0 * mem.ice_battery_sigma ** 2))
            )
            # Burn energy: 20% consumed per step when boost is active
            memory_grid[3][ice_active] *= (1.0 - mem.ice_battery_burn_rate)
        # Combined resistance: base + ice, hard-capped
        p_resist = np.minimum(p_base + p_ice, mem.ice_battery_p_max)
        equanimity_mask = mature_compute & (rng.random(shape) < p_resist)
    # Phase 6b: Sympathetic Joy (mudita) -- resonance from mature neighbors
    # Nemo's formula: R_joy = 1 + beta_joy * tanh((a_max_neighbor - a_m) / joy_age_scale)
    # A cell benefits from the maturity of its neighbors without consuming them
    compute_age_field = np.where(state == COMPUTE, memory_grid[0], 0.0).astype(np.float32)
    max_neighbor_age = _max_neighbor_value(compute_age_field)
    # Only apply to cells that have a mature COMPUTE neighbor (age > equanimity_age_min)
    has_mature_neighbor = max_neighbor_age > mem.equanimity_age_min
    if np.any(has_mature_neighbor):
        age_excess_neighbor = np.maximum(0.0, max_neighbor_age - mem.equanimity_age_min)
        r_joy = 1.0 + mem.joy_beta * np.tanh(age_excess_neighbor / mem.joy_age_scale)
        # Boost memory_strength (channel 2) for ALL cells near mature COMPUTE
        # This is positive-sum: the neighbor thrives because the elder thrives
        memory_grid[2][has_mature_neighbor] = np.minimum(
            2.0, memory_grid[2][has_mature_neighbor] * r_joy[has_mature_neighbor])
    # Phase 6c: Mindsight + Mycelial Network + Compassion (nervous system)
    # Runs every signal_interval steps to save CPU (~3s per call at R=12)
    if current_gen % mem.signal_interval == 0:
        # --- 6c.1: Mindsight (Stimulus) ---
        # Compute regional SENSOR density using R=12 separable box filter
        sensor_field = (state == SENSOR).astype(np.float32)
        rho_regional = _separable_box_filter_3d(sensor_field, mem.mindsight_radius)
        # Local SENSOR density (immediate Moore neighborhood, already computed)
        sensor_local = neighbor_counts[SENSOR].astype(np.float32) / 26.0
        # Gradient: positive = opportunity (more SENSOR locally), negative = distress
        grad_rho = sensor_local - rho_regional
        # Compute initial signal: S_0 = S_max * tanh(grad / sigma)
        # Use asymmetric sigma: sigma_opp for positive, sigma_dis for negative
        sigma = np.where(grad_rho >= 0, mem.mindsight_sigma_opp, mem.mindsight_sigma_dis)
        s_initial = mem.mindsight_s_max * np.tanh(grad_rho / np.maximum(sigma, 1e-8))
        # Only seed signals where |S| > threshold AND cell is SENSOR
        sensor_mask = state == SENSOR
        s_initial[~sensor_mask] = 0.0
        s_initial[np.abs(s_initial) < mem.mindsight_threshold] = 0.0
        # Seed initial signals on SENSOR cells, then deliver to ENERGY neighbors
        # SENSOR cells generate, ENERGY cells transmit
        memory_grid[5] = s_initial
        # --- 6c.2: Mycelial Diffusion (Transmission) ---
        # First: deliver SENSOR signals to adjacent ENERGY cells (handoff)
        energy_mask = out == ENERGY
        if np.any(s_initial != 0) and np.any(energy_mask):
            # Spread signals from SENSOR to immediate neighbors (including ENERGY)
            abs_neg = np.abs(np.minimum(s_initial, 0.0))
            pos = np.maximum(s_initial, 0.0)
            handoff_distress = _max_neighbor_value(abs_neg)
            handoff_opportunity = _max_neighbor_value(pos)
            # Only keep handoff on ENERGY cells (they receive from adjacent SENSOR)
            energy_seed = np.where(energy_mask, -handoff_distress + handoff_opportunity, 0.0)
            # Add original SENSOR signals (SENSOR cells also seed the field)
            s_initial = s_initial + energy_seed
            # Separate distress and opportunity signals for asymmetric decay
            distress_signal = np.minimum(s_initial, 0.0)  # negative values
            opportunity_signal = np.maximum(s_initial, 0.0)  # positive values
            # Diffuse each with its own decay length
            decay_distress = np.exp(-1.0 / mem.mycelial_lambda_distress)
            decay_opportunity = np.exp(-1.0 / mem.mycelial_lambda_opportunity)
            diffused_distress = _mycelial_diffuse(
                distress_signal, energy_mask, mem.mycelial_k_iter, decay_distress)
            diffused_opportunity = _mycelial_diffuse(
                opportunity_signal, energy_mask, mem.mycelial_k_iter, decay_opportunity)
            # Combine diffused signals
            diffused = diffused_distress + diffused_opportunity
            # Deliver signals to ALL neighbors of ENERGY cells (not just ENERGY)
            # This lets COMPUTE cells adjacent to the ENERGY network receive signals
            # Use max absolute signal from neighbors as the delivery mechanism
            abs_distress = np.abs(diffused_distress)
            delivered_distress_mag = _max_neighbor_value(abs_distress)
            delivered_opportunity_mag = _max_neighbor_value(diffused_opportunity)
            # Reconstruct signed signals: distress is negative, opportunity is positive
            memory_grid[5] = -delivered_distress_mag + delivered_opportunity_mag
            # Preserve stronger signals on ENERGY cells themselves
            stronger = np.abs(diffused) > np.abs(memory_grid[5])
            memory_grid[5][stronger] = diffused[stronger]
        # --- 6c.3: Compassion (Response) ---
        # Mature COMPUTE cells receiving distress donate energy for remote resistance
        compute_now = out == COMPUTE
        distress_received = memory_grid[5] < -mem.mindsight_threshold
        # Adaptive compassion scale: a_scale = max(30, max_age * 1.5)
        compute_ages = memory_grid[0][compute_now]
        current_max_age = float(np.max(compute_ages)) if np.any(compute_now) else 0.0
        a_compassion_scale = max(mem.compassion_age_scale_min,
                                 current_max_age * mem.compassion_age_scale_factor)
        # Compassion donors: mature COMPUTE cells receiving distress
        compassion_donors = compute_now & distress_received & (memory_grid[0] > mem.equanimity_age_min)
        if np.any(compassion_donors):
            # Phi_compassion = |S| * (a_self / a_scale)
            donor_signal_strength = np.abs(memory_grid[5][compassion_donors])
            donor_age_ratio = memory_grid[0][compassion_donors] / a_compassion_scale
            phi_compassion = donor_signal_strength * np.minimum(1.0, donor_age_ratio)
            # Local cost: donors pay gamma_compassion of their memory + energy
            cost_factor = 1.0 - mem.compassion_gamma * phi_compassion
            cost_factor = np.maximum(0.3, cost_factor)  # never drain below 30%
            memory_grid[2][compassion_donors] *= cost_factor
            memory_grid[3][compassion_donors] *= cost_factor
            # Remote buff: boost resistance for cells in distress region
            # Apply buff to ALL cells in distress zones (not just donors)
            distress_zone = distress_received & (~compassion_donors)
            if np.any(distress_zone):
                # Resistance buff proportional to nearby compassion strength
                # Use the diffused signal magnitude as proxy for compassion reach
                buff_strength = mem.compassion_beta * np.minimum(
                    1.0, np.abs(memory_grid[5][distress_zone]))
                # Boost memory_strength (which feeds into decay resistance)
                memory_grid[2][distress_zone] = np.minimum(
                    2.0, memory_grid[2][distress_zone] + buff_strength)
            # Track compassion activity with cooldown (channel 7)
            memory_grid[7][compassion_donors] = 5.0  # 5-step cooldown
        # Decay compassion cooldown
        memory_grid[7] = np.maximum(0.0, memory_grid[7] - 1.0)
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
    # Phase 6a: Loving-Kindness (metta) -- ENERGY warms STRUCTURAL cells
    # Nemo's formula: delta_r_metta = beta_metta * (1 - exp(-n_E / 3))
    # Warmth accumulates in channel 6, decays when no ENERGY neighbors
    energy_neighbor_count = neighbor_counts[ENERGY].astype(np.float32)
    structural_now = out == STRUCTURAL
    # Accumulate warmth for STRUCTURAL cells touching ENERGY
    has_energy_neighbors = structural_now & (energy_neighbor_count > 0)
    warmth_boost = mem.metta_warmth_rate * energy_neighbor_count
    memory_grid[6][has_energy_neighbors] = np.minimum(
        1.0, memory_grid[6][has_energy_neighbors] + warmth_boost[has_energy_neighbors])
    # Decay warmth for STRUCTURAL cells with no ENERGY neighbors
    no_energy = structural_now & (energy_neighbor_count == 0)
    memory_grid[6][no_energy] *= mem.metta_warmth_decay
    # Clear warmth for non-STRUCTURAL cells
    memory_grid[6][~structural_now] = 0.0
    # Stochastic decay (0.005 -- CRITICAL)
    # Phase 6a: warmth reduces STRUCTURAL decay probability
    # survival_floor = beta_metta * (1 - exp(-n_E / 3)) -- Nemo's formula
    if stoch.enabled:
        structural = out == STRUCTURAL; energy = out == ENERGY; sensor = out == SENSOR
        # Loving-Kindness: warmth-modulated STRUCTURAL decay
        metta_survival_floor = mem.metta_beta * (1.0 - np.exp(-energy_neighbor_count / 3.0))
        structural_decay_prob = np.maximum(
            0.0, stoch.structural_to_void_decay_prob - metta_survival_floor)
        out[structural & (rng.random(shape) < structural_decay_prob)] = VOID
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
    # Phase 6c telemetry: signal activity and compassion stats
    signal_active = int(np.sum(np.abs(memory_grid[5]) > 0.01))
    compassion_active = int(np.sum(memory_grid[7] > 0))
    metrics = {"entropy": normalized_entropy, "structural_ratio": float(counts[STRUCTURAL] / max(1, non_void_total)), "void_ratio": float(counts[VOID] / total_cells), "compute_ratio": float(counts[COMPUTE] / total_cells), "energy_ratio": float(counts[ENERGY] / total_cells), "sensor_ratio": float(counts[SENSOR] / total_cells), "compute_median_age": compute_median_age, "compute_max_age": compute_max_age, "compute_mean_age": compute_mean_age, "signal_active": signal_active, "compassion_active": compassion_active}
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
