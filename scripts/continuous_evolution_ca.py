#!/usr/bin/env python3
"""
Continuous Evolution v0.4.0 — State-Aware Contagion & Asymmetric Stability

Combines the 3D Cellular Automata lattice with the memetic evolution engine
to grow fractal branch structures indefinitely.  Emits a status summary
every 5 minutes.

v0.4.0 physics (Jack / AURA):
  - State-aware neighbour counting (per-state, not just active/inactive)
  - Contagion mechanics: STRUCTURAL/COMPUTE near ENERGY/SENSOR clusters convert
  - Asymmetric stability: ENERGY stable 0-5, SENSOR stable 0-8 (nearly indestructible)
  - 8% stochastic chaos rate (up from 2%)
  - Aggressive decay: 4-step inactivity threshold (down from 50)
  - STRUCTURAL transitions at ALL neighbour counts (always differentiates)

Periodically saves 3D Branch Primitives (.npz snapshots) to data/.

Thermal safety is handled at the OS level by vanguard-mcp.exe (hard-
throttle 85 C, pause 88 C).  This script does NOT duplicate that logic.
"""

from __future__ import annotations

import argparse
import os
import sys
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

import numpy as np

# Python 3.11+ has tomllib in stdlib; older versions need tomli
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

RULES_PATH = PROJECT_ROOT / "ca" / "rules" / "example.toml"

# ---------------------------------------------------------------------------
# CA lattice configuration
# ---------------------------------------------------------------------------
LATTICE_W, LATTICE_H, LATTICE_D = 64, 64, 64
NUM_CELLS = LATTICE_W * LATTICE_H * LATTICE_D

# States: 0=VOID, 1=STRUCTURAL, 2=COMPUTE, 3=ENERGY, 4=SENSOR
STATE_NAMES = ["VOID", "STRUCTURAL", "COMPUTE", "ENERGY", "SENSOR"]
NUM_STATES = len(STATE_NAMES)

STATE_NAME_TO_ID = {
    "VOID": 0,
    "STRUCTURAL": 1,
    "COMPUTE": 2,
    "ENERGY": 3,
    "SENSOR": 4,
}

# ---------------------------------------------------------------------------
# Evolution engine parameters
# ---------------------------------------------------------------------------
POPULATION_SIZE = 120
MUTATION_RATE = 0.10
CROSSOVER_RATE = 0.80
ELITISM_RATE = 0.10
TOURNAMENT_K = 3

# Reporting cadence
STATUS_INTERVAL = 300  # seconds (5 minutes)
SNAPSHOT_INTERVAL = 600  # seconds (10 minutes)

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
_running = True


def _handle_signal(sig, frame):
    global _running
    print(f"\n[SIGNAL] Received {signal.Signals(sig).name}, shutting down gracefully...")
    _running = False


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ====================================================================
# v0.4.0 Config dataclasses (Jack / AURA)
# ====================================================================

@dataclass
class DecayConfig:
    enabled: bool = True
    inactivity_neighbor_threshold: int = 1
    structural_inactive_steps_to_decay: int = 4


@dataclass
class StochasticConfig:
    enabled: bool = True
    baseline_transition_prob: float = 0.08
    structural_to_energy_prob: float = 0.08
    structural_to_sensor_prob: float = 0.08
    compute_to_energy_prob: float = 0.10
    compute_to_sensor_prob: float = 0.10
    structural_to_void_decay_prob: float = 0.045
    energy_to_void_decay_prob: float = 0.004
    sensor_to_void_decay_prob: float = 0.003


@dataclass
class ContagionConfig:
    enabled: bool = True
    energy_neighbor_threshold: int = 4
    sensor_neighbor_threshold: int = 4
    structural_energy_conversion_prob: float = 0.42
    structural_sensor_conversion_prob: float = 0.34
    compute_energy_conversion_prob: float = 0.36
    compute_sensor_conversion_prob: float = 0.30


@dataclass
class DensityTargetingConfig:
    """v0.6.0 Nemo's density-targeting probability curve.

    When COMPUTE fraction is below target, STRUCTURAL→COMPUTE transitions
    are boosted to `boost_probability`. When at or above target, they are
    suppressed to `suppress_probability`. This creates a self-regulating
    feedback loop that drives COMPUTE toward the target density.
    """
    enabled: bool = True
    compute_target_fraction: float = 0.25
    boost_probability: float = 0.85
    suppress_probability: float = 0.35


# ====================================================================
# Rule spec loading (TOML)
# ====================================================================

def load_rule_spec(rule_path: str | Path) -> Dict[str, Any]:
    """Load CA rule specification from a TOML file."""
    with Path(rule_path).open("rb") as f:
        return tomllib.load(f)


def _compile_transition_table(rule_spec: Mapping[str, Any]) -> Dict[int, Dict[int, int]]:
    """Build {src_state: {neighbour_count: target_state}} from TOML spec."""
    transitions = rule_spec["params"]["transitions"]
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
        structural_inactive_steps_to_decay=int(decay.get("structural_inactive_steps_to_decay", 4)),
    )


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
        structural_to_void_decay_prob=float(stoch.get("structural_to_void_decay_prob", 0.045)),
        energy_to_void_decay_prob=float(stoch.get("energy_to_void_decay_prob", 0.004)),
        sensor_to_void_decay_prob=float(stoch.get("sensor_to_void_decay_prob", 0.003)),
    )


def _load_contagion_config(rule_spec: Mapping[str, Any]) -> ContagionConfig:
    contagion = rule_spec.get("params", {}).get("contagion", {})
    return ContagionConfig(
        enabled=bool(contagion.get("enabled", True)),
        energy_neighbor_threshold=int(contagion.get("energy_neighbor_threshold", 4)),
        sensor_neighbor_threshold=int(contagion.get("sensor_neighbor_threshold", 4)),
        structural_energy_conversion_prob=float(contagion.get("structural_energy_conversion_prob", 0.42)),
        structural_sensor_conversion_prob=float(contagion.get("structural_sensor_conversion_prob", 0.34)),
        compute_energy_conversion_prob=float(contagion.get("compute_energy_conversion_prob", 0.36)),
        compute_sensor_conversion_prob=float(contagion.get("compute_sensor_conversion_prob", 0.30)),
    )


def _load_density_targeting_config(rule_spec: Mapping[str, Any]) -> DensityTargetingConfig:
    dt = rule_spec.get("params", {}).get("density_targeting", {})
    return DensityTargetingConfig(
        enabled=bool(dt.get("enabled", False)),
        compute_target_fraction=float(dt.get("compute_target_fraction", 0.25)),
        boost_probability=float(dt.get("boost_probability", 0.85)),
        suppress_probability=float(dt.get("suppress_probability", 0.35)),
    )


# ====================================================================
# v0.4.0 State-aware neighbour counting
# ====================================================================

def _count_neighbors_by_state(state: np.ndarray) -> np.ndarray:
    """Return per-state Moore-3D neighbor counts with fixed VOID boundary.

    Output shape: [num_states, *state.shape], where axis 0 indexes state IDs.
    """
    if state.ndim != 3:
        raise ValueError(f"Expected a 3D lattice, got shape={state.shape}")

    out = np.zeros((len(STATE_NAME_TO_ID),) + state.shape, dtype=np.int16)
    for state_id in range(len(STATE_NAME_TO_ID)):
        indicator = (state == state_id).astype(np.int16)
        padded = np.pad(indicator, 1, mode="constant", constant_values=0)
        counts = np.zeros_like(indicator, dtype=np.int16)
        for dz in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0 and dz == 0:
                        continue
                    counts += padded[
                        1 + dz:1 + dz + state.shape[0],
                        1 + dy:1 + dy + state.shape[1],
                        1 + dx:1 + dx + state.shape[2],
                    ]
        out[state_id] = counts
    return out


# ====================================================================
# v0.4.0 CA stepping phases
# ====================================================================

def _apply_deterministic_transitions(
    state: np.ndarray,
    active_neighbors: np.ndarray,
    table: Mapping[int, Mapping[int, int]],
) -> np.ndarray:
    """Phase 1: Apply outer-totalistic rules based on active neighbour count."""
    next_state = np.zeros_like(state)
    for src, mapping in table.items():
        src_mask = state == src
        if not np.any(src_mask):
            continue
        for n_count, target in mapping.items():
            mask = src_mask & (active_neighbors == n_count)
            next_state[mask] = target
    return next_state


def _apply_contagion_overrides(
    next_state: np.ndarray,
    neighbor_counts_by_state: np.ndarray,
    rng: np.random.Generator,
    contagion: ContagionConfig,
) -> np.ndarray:
    """Phase 2: State-aware contagion — nearby ENERGY/SENSOR clusters convert neighbours."""
    if not contagion.enabled:
        return next_state

    out = next_state.copy()
    energy_n = neighbor_counts_by_state[STATE_NAME_TO_ID["ENERGY"]]
    sensor_n = neighbor_counts_by_state[STATE_NAME_TO_ID["SENSOR"]]

    # STRUCTURAL near ENERGY clusters -> ENERGY
    structural = out == STATE_NAME_TO_ID["STRUCTURAL"]
    se_mask = structural & (energy_n >= contagion.energy_neighbor_threshold)
    out[se_mask & (rng.random(out.shape) < contagion.structural_energy_conversion_prob)] = STATE_NAME_TO_ID["ENERGY"]

    # STRUCTURAL near SENSOR clusters -> SENSOR
    structural = out == STATE_NAME_TO_ID["STRUCTURAL"]
    ss_mask = structural & (sensor_n >= contagion.sensor_neighbor_threshold)
    out[ss_mask & (rng.random(out.shape) < contagion.structural_sensor_conversion_prob)] = STATE_NAME_TO_ID["SENSOR"]

    # COMPUTE near ENERGY clusters -> ENERGY
    compute = out == STATE_NAME_TO_ID["COMPUTE"]
    ce_mask = compute & (energy_n >= contagion.energy_neighbor_threshold)
    out[ce_mask & (rng.random(out.shape) < contagion.compute_energy_conversion_prob)] = STATE_NAME_TO_ID["ENERGY"]

    # COMPUTE near SENSOR clusters -> SENSOR
    compute = out == STATE_NAME_TO_ID["COMPUTE"]
    cs_mask = compute & (sensor_n >= contagion.sensor_neighbor_threshold)
    out[cs_mask & (rng.random(out.shape) < contagion.compute_sensor_conversion_prob)] = STATE_NAME_TO_ID["SENSOR"]

    return out


def _apply_stochastic_overrides(
    next_state: np.ndarray,
    rng: np.random.Generator,
    stoch: StochasticConfig,
) -> np.ndarray:
    """Phase 3: Stochastic transitions — random differentiation and asymmetric decay."""
    if not stoch.enabled:
        return next_state

    out = next_state.copy()

    structural = out == STATE_NAME_TO_ID["STRUCTURAL"]
    compute = out == STATE_NAME_TO_ID["COMPUTE"]
    energy = out == STATE_NAME_TO_ID["ENERGY"]
    sensor = out == STATE_NAME_TO_ID["SENSOR"]

    # Stochastic specialization: STRUCTURAL -> ENERGY/SENSOR
    out[structural & (rng.random(out.shape) < stoch.structural_to_energy_prob)] = STATE_NAME_TO_ID["ENERGY"]
    structural = out == STATE_NAME_TO_ID["STRUCTURAL"]
    out[structural & (rng.random(out.shape) < stoch.structural_to_sensor_prob)] = STATE_NAME_TO_ID["SENSOR"]

    # Stochastic specialization: COMPUTE -> ENERGY/SENSOR
    out[compute & (rng.random(out.shape) < stoch.compute_to_energy_prob)] = STATE_NAME_TO_ID["ENERGY"]
    compute = out == STATE_NAME_TO_ID["COMPUTE"]
    out[compute & (rng.random(out.shape) < stoch.compute_to_sensor_prob)] = STATE_NAME_TO_ID["SENSOR"]

    # Asymmetric stochastic decay: STRUCTURAL fragile, ENERGY/SENSOR resilient
    structural = out == STATE_NAME_TO_ID["STRUCTURAL"]
    out[structural & (rng.random(out.shape) < stoch.structural_to_void_decay_prob)] = STATE_NAME_TO_ID["VOID"]
    out[energy & (rng.random(out.shape) < stoch.energy_to_void_decay_prob)] = STATE_NAME_TO_ID["VOID"]
    out[sensor & (rng.random(out.shape) < stoch.sensor_to_void_decay_prob)] = STATE_NAME_TO_ID["VOID"]

    return out


def _apply_density_targeting(
    next_state: np.ndarray,
    prev_state: np.ndarray,
    rng: np.random.Generator,
    dt: DensityTargetingConfig,
) -> np.ndarray:
    """Phase 5 (v0.6.0): Nemo's density-targeting probability curve.

    Adaptively modulates STRUCTURAL→COMPUTE transition probability based on
    current COMPUTE density. When COMPUTE is below target (25%), transitions
    are boosted to 85%. When at or above target, they're suppressed to 35%.
    This creates a self-regulating feedback loop.
    """
    if not dt.enabled:
        return next_state

    out = next_state.copy()

    # Measure current COMPUTE density among active cells
    active_total = int(np.sum(out > 0))
    if active_total == 0:
        return out
    compute_count = int(np.sum(out == STATE_NAME_TO_ID["COMPUTE"]))
    compute_fraction = compute_count / active_total

    # Find cells that just transitioned from STRUCTURAL to COMPUTE
    was_structural = prev_state == STATE_NAME_TO_ID["STRUCTURAL"]
    now_compute = out == STATE_NAME_TO_ID["COMPUTE"]
    newly_compute = was_structural & now_compute

    if not np.any(newly_compute):
        return out

    # Apply density-dependent gate
    if compute_fraction < dt.compute_target_fraction:
        # Below target: boost — keep most transitions (85% survive)
        revert_prob = 1.0 - dt.boost_probability
    else:
        # At/above target: suppress — revert most transitions (only 35% survive)
        revert_prob = 1.0 - dt.suppress_probability

    # Stochastically revert some COMPUTE→STRUCTURAL transitions
    revert_mask = newly_compute & (rng.random(out.shape) < revert_prob)
    out[revert_mask] = STATE_NAME_TO_ID["STRUCTURAL"]

    return out


def step_ca_lattice(
    state: np.ndarray,
    rule_spec: Mapping[str, Any],
    rng: np.random.Generator,
    inactivity_steps: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, float]]:
    """Single CA step with deterministic + contagion + stochastic + decay + density-targeting.

    Returns (next_state, inactivity_steps, metrics_dict).

    v0.6.0 adds Phase 5: Nemo's density-targeting probability curve.
    """
    if state.ndim != 3:
        raise ValueError(f"Expected a 3D lattice, got shape={state.shape}")

    table = _compile_transition_table(rule_spec)
    decay = _load_decay_config(rule_spec)
    stoch = _load_stochastic_config(rule_spec)
    contagion = _load_contagion_config(rule_spec)
    density_targeting = _load_density_targeting_config(rule_spec)

    # Per-state neighbour counting (the v0.4.0 core innovation)
    neighbor_counts = _count_neighbors_by_state(state)
    active_neighbors = np.sum(neighbor_counts[1:], axis=0)  # sum non-VOID

    # Phase 1: Deterministic transitions
    next_state = _apply_deterministic_transitions(state, active_neighbors, table)

    # Phase 2: Contagion overrides
    next_state = _apply_contagion_overrides(next_state, neighbor_counts, rng, contagion)

    # Phase 3: Inactivity decay
    if inactivity_steps is None:
        inactivity_steps = np.zeros_like(state, dtype=np.int16)

    if decay.enabled:
        structural = next_state == STATE_NAME_TO_ID["STRUCTURAL"]
        low_support = active_neighbors <= decay.inactivity_neighbor_threshold
        inactivity_steps = np.where(structural & low_support, inactivity_steps + 1, 0)
        decay_mask = structural & (inactivity_steps >= decay.structural_inactive_steps_to_decay)
        next_state[decay_mask] = STATE_NAME_TO_ID["VOID"]
        inactivity_steps[~structural] = 0

    # Phase 4: Stochastic overrides
    next_state = _apply_stochastic_overrides(next_state, rng, stoch)

    # Phase 5 (v0.6.0): Density-targeting — Nemo's adaptive COMPUTE regulation
    next_state = _apply_density_targeting(next_state, state, rng, density_targeting)

    # Compute metrics
    counts = np.bincount(next_state.ravel(), minlength=5)
    non_void_total = int(np.sum(counts[1:]))
    probs = counts[1:] / max(1, non_void_total)
    non_zero_probs = probs[probs > 0]
    entropy = float(-np.sum(non_zero_probs * np.log(non_zero_probs))) if non_zero_probs.size else 0.0
    normalized_entropy = float(entropy / np.log(4.0)) if non_zero_probs.size > 1 else 0.0

    metrics = {
        "entropy": normalized_entropy,
        "structural_ratio": float(counts[1] / max(1, non_void_total)),
        "void_ratio": float(counts[0] / max(1, np.prod(next_state.shape))),
        "compute_ratio": float(counts[2] / max(1, np.prod(next_state.shape))),
        "energy_ratio": float(counts[3] / max(1, np.prod(next_state.shape))),
        "sensor_ratio": float(counts[4] / max(1, np.prod(next_state.shape))),
    }
    return next_state.astype(np.uint8, copy=False), inactivity_steps.astype(np.int16, copy=False), metrics


# ====================================================================
# Primordial seed cube
# ====================================================================

def generate_primordial_seed_cube(cube_size: int = 3) -> np.ndarray:
    """Generate a dense primordial seed cube centred in the lattice.

    A single cell cannot bootstrap growth because VOID->STRUCTURAL
    requires 4-6 active Moore neighbours.  A filled N^3 cube of
    STRUCTURAL cells provides the critical mass for ignition.

    Args:
        cube_size: side length of the seed cube (default 3 -> 27 cells).
                   Must be >= 2.

    Returns:
        64x64x64 uint8 lattice with the seed cube placed at centre.
    """
    if cube_size < 2:
        raise ValueError(
            f"cube_size must be >= 2 for ignition (got {cube_size}). "
            "A single cell cannot reach the neighbour threshold."
        )

    lattice = np.zeros((LATTICE_W, LATTICE_H, LATTICE_D), dtype=np.uint8)

    cx, cy, cz = LATTICE_W // 2, LATTICE_H // 2, LATTICE_D // 2
    half = cube_size // 2

    x0, x1 = cx - half, cx - half + cube_size
    y0, y1 = cy - half, cy - half + cube_size
    z0, z1 = cz - half, cz - half + cube_size

    lattice[x0:x1, y0:y1, z0:z1] = 1  # STRUCTURAL
    return lattice


def _init_lattice(cube_size: int = 1) -> np.ndarray:
    """Initialise the lattice with either a single cell or a primordial cube."""
    if cube_size >= 2:
        return generate_primordial_seed_cube(cube_size)
    lattice = np.zeros((LATTICE_W, LATTICE_H, LATTICE_D), dtype=np.uint8)
    cx, cy, cz = LATTICE_W // 2, LATTICE_H // 2, LATTICE_D // 2
    lattice[cx, cy, cz] = 1  # STRUCTURAL seed
    return lattice


# ====================================================================
# Lightweight memetic evolution (self-contained)
# ====================================================================

def _random_genome(rng: np.random.Generator) -> np.ndarray:
    """5-gene genome: dominance, virality, stability, compatibility, threshold."""
    return rng.uniform(0.1, 0.9, size=5).astype(np.float32)


def _fitness(genome: np.ndarray, lattice_metrics: dict) -> float:
    """Fitness with Shannon entropy bonus & structural-dominance penalty.

    v0.4.0: adapted to work with step_ca_lattice metrics.
    """
    dominance, virality, stability, compat, thresh = genome
    branching = lattice_metrics.get("branching_ratio", 1.0)
    density = lattice_metrics.get("density", 0.0)
    entropy = lattice_metrics.get("entropy", 0.0)
    struct_dom = lattice_metrics.get("structural_dominance", lattice_metrics.get("structural_ratio", 1.0))

    # Reward balance: branching near 1.5, moderate density, high stability
    target_br = 1.5
    br_score = max(0, 1.0 - abs(branching - target_br))
    density_score = min(density * 2, 1.0)
    gene_score = (0.3 * dominance + 0.2 * virality + 0.3 * stability
                  + 0.1 * compat + 0.1 * (1 - thresh))

    base_score = 0.35 * gene_score + 0.25 * br_score + 0.15 * density_score

    # --- Differentiation Physics ---
    entropy_bonus = 0.25 * entropy            # max +0.25 for perfect diversity
    dominance_penalty = 0.20 * struct_dom     # max -0.20 for pure STRUCTURAL

    return max(0.0, base_score + entropy_bonus - dominance_penalty)


def _tournament_select(pop: np.ndarray, fits: np.ndarray, k: int, rng: np.random.Generator) -> int:
    indices = rng.choice(len(pop), size=k, replace=False)
    return int(indices[np.argmax(fits[indices])])


def _crossover(p1: np.ndarray, p2: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    mask = rng.random(len(p1)) < 0.5
    c1, c2 = p1.copy(), p2.copy()
    c1[mask], c2[mask] = p2[mask], p1[mask]
    return c1, c2


def _mutate(genome: np.ndarray, rate: float, rng: np.random.Generator) -> np.ndarray:
    g = genome.copy()
    for i in range(len(g)):
        if rng.random() < rate:
            g[i] = np.clip(g[i] + rng.normal(0, 0.08), 0.0, 1.0)
    return g


def _evolve_population(pop: np.ndarray, lattice_metrics: dict, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """One generational step.  Returns (new_population, fitness_array)."""
    n = len(pop)
    fits = np.array([_fitness(g, lattice_metrics) for g in pop], dtype=np.float32)

    # Elitism
    num_elites = max(1, int(ELITISM_RATE * n))
    elite_idx = np.argsort(fits)[-num_elites:]
    new_pop = [pop[i].copy() for i in elite_idx]

    while len(new_pop) < n:
        i1 = _tournament_select(pop, fits, TOURNAMENT_K, rng)
        i2 = _tournament_select(pop, fits, TOURNAMENT_K, rng)
        if rng.random() < CROSSOVER_RATE:
            c1, c2 = _crossover(pop[i1], pop[i2], rng)
        else:
            c1, c2 = pop[i1].copy(), pop[i2].copy()
        new_pop.append(_mutate(c1, MUTATION_RATE, rng))
        if len(new_pop) < n:
            new_pop.append(_mutate(c2, MUTATION_RATE, rng))

    new_pop = np.array(new_pop[:n], dtype=np.float32)
    new_fits = np.array([_fitness(g, lattice_metrics) for g in new_pop], dtype=np.float32)
    return new_pop, new_fits


# ====================================================================
# Lattice metrics (extended for backward compat + v0.4.0)
# ====================================================================

def _shannon_entropy(lattice: np.ndarray, active: int) -> float:
    """Normalized Shannon entropy over non-VOID cell types."""
    if active == 0:
        return 0.0
    counts = np.bincount(lattice.ravel(), minlength=NUM_STATES)[1:]  # skip VOID
    probs = counts / active
    probs = probs[probs > 0]
    H = -float(np.sum(probs * np.log(probs)))
    H_max = np.log(NUM_STATES - 1)  # ln(4)
    return H / H_max if H_max > 0 else 0.0


def _structural_dominance(lattice: np.ndarray, active: int) -> float:
    """Fraction of active cells that are STRUCTURAL."""
    if active == 0:
        return 0.0
    return int(np.sum(lattice == 1)) / active


def _compute_metrics(lattice: np.ndarray, prev_active: int) -> dict:
    """Full metrics dict for the GA fitness evaluator."""
    active = int(np.sum(lattice > 0))
    total = int(lattice.size)
    density = active / total if total else 0.0
    branching_ratio = active / max(prev_active, 1)

    mean_energy = float(np.mean(lattice)) / (NUM_STATES - 1)

    if active > 0:
        counts = np.bincount(lattice.ravel(), minlength=NUM_STATES)[1:]
        m = float(np.max(counts)) / active
    else:
        m = 0.0

    entropy = _shannon_entropy(lattice, active)
    struct_dom = _structural_dominance(lattice, active)

    return {
        "active_cells": active,
        "total_cells": total,
        "density": density,
        "branching_ratio": branching_ratio,
        "mean_energy": mean_energy,
        "abs_m": m,
        "entropy": entropy,
        "structural_dominance": struct_dom,
    }


# ====================================================================
# 3-D branch primitive snapshot
# ====================================================================

def _save_branch_primitive(lattice: np.ndarray, generation: int, step: int) -> Path:
    """Save current lattice as a compressed .npz file in data/."""
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    fname = f"branch3d_gen{generation:06d}_step{step:06d}_{ts}.npz"
    path = DATA_DIR / fname
    np.savez_compressed(path, lattice=lattice, generation=generation, step=step)
    return path


# ====================================================================
# Main infinite loop
# ====================================================================

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Continuous Evolution v0.4.0 — Contagion & Asymmetric Stability",
    )
    parser.add_argument(
        "--seed-cube-size",
        type=int,
        default=3,
        metavar="N",
        help=(
            "Side-length of the primordial STRUCTURAL seed cube placed at "
            "the lattice centre. Must be >= 2 for ignition (default: 3)."
        ),
    )
    return parser.parse_args()


def main():
    global _running

    args = _parse_args()
    cube_sz = args.seed_cube_size

    seed_desc = (
        f"Primordial {cube_sz}^3 cube ({cube_sz**3} cells)"
        if cube_sz >= 2
        else "Single cell (legacy — will collapse)"
    )

    # Load v0.4.0 rule spec from TOML
    rule_spec = load_rule_spec(RULES_PATH)
    rule_version = rule_spec.get("params", {}).get("meta", {}).get("version", "0.4.0")
    rule_desc = rule_spec.get("params", {}).get("meta", {}).get("description", "v0.4.0")

    # Extract config for display
    decay_cfg = _load_decay_config(rule_spec)
    stoch_cfg = _load_stochastic_config(rule_spec)
    contagion_cfg = _load_contagion_config(rule_spec)

    print("=" * 72)
    print("  CONTINUOUS EVOLUTION v0.4.0 — Contagion & Asymmetric Stability")
    print("  Lattice: {}x{}x{}  |  Population: {}".format(
        LATTICE_W, LATTICE_H, LATTICE_D, POPULATION_SIZE))
    print(f"  Seed:   {seed_desc}")
    print(f"  Rule:   {rule_desc} (v{rule_version})")
    print(f"  Physics: state-aware contagion + asymmetric stability + 8% chaos")
    print(f"  Stochastic baseline: {stoch_cfg.baseline_transition_prob}")
    print(f"  Contagion: STRUCT->ENERGY={contagion_cfg.structural_energy_conversion_prob}  "
          f"STRUCT->SENSOR={contagion_cfg.structural_sensor_conversion_prob}")
    print(f"  Decay: {decay_cfg.structural_inactive_steps_to_decay}-step threshold  "
          f"(neighbour threshold={decay_cfg.inactivity_neighbor_threshold})")
    print("  Status every {} s  |  Snapshot every {} s".format(
        STATUS_INTERVAL, SNAPSHOT_INTERVAL))
    print("=" * 72)

    rng = np.random.default_rng(seed=42)

    # Initialise lattice with primordial seed cube
    lattice = _init_lattice(cube_size=cube_sz)
    prev_active = int(np.sum(lattice > 0))
    inactivity = np.zeros_like(lattice, dtype=np.int16)

    # Initialise meme population
    population = np.array([_random_genome(rng) for _ in range(POPULATION_SIZE)], dtype=np.float32)

    generation = 0
    ca_step_count = 0
    start_time = time.monotonic()
    last_status = start_time
    last_snapshot = start_time

    print(f"\n[{datetime.now().isoformat()}] Evolution started.\n")

    while _running:
        t_now = time.monotonic()

        # --- CA step (v0.4.0: state-aware contagion + asymmetric stability) ---
        lattice, inactivity, step_metrics = step_ca_lattice(
            lattice, rule_spec, rng, inactivity
        )
        ca_step_count += 1

        # Build full metrics for GA (merge step_metrics with computed metrics)
        full_metrics = _compute_metrics(lattice, prev_active)
        # Override entropy with the step_ca_lattice's own calculation
        full_metrics["entropy"] = step_metrics["entropy"]
        full_metrics["structural_ratio"] = step_metrics["structural_ratio"]
        prev_active = full_metrics["active_cells"]

        # --- Evolution step (every 10 CA steps) ---
        if ca_step_count % 10 == 0:
            population, fits = _evolve_population(population, full_metrics, rng)
            generation += 1

        # --- 5-minute status report ---
        if t_now - last_status >= STATUS_INTERVAL:
            elapsed = timedelta(seconds=int(t_now - start_time))
            fits_now = np.array([_fitness(g, full_metrics) for g in population], dtype=np.float32)
            # Per-state census
            state_counts = np.bincount(lattice.ravel(), minlength=NUM_STATES)
            census_str = "  ".join(
                f"{STATE_NAMES[i]}={state_counts[i]}"
                for i in range(NUM_STATES)
            )

            print("-" * 72)
            print(f"  STATUS @ {datetime.now().isoformat()}  (uptime {elapsed})")
            print(f"  Generation: {generation}  |  CA step: {ca_step_count}")
            print(f"  Mean Energy:     {full_metrics['mean_energy']:.6f}")
            print(f"  |m|:             {full_metrics['abs_m']:.6f}")
            print(f"  Branching Ratio: {full_metrics['branching_ratio']:.6f}")
            print(f"  Density:         {full_metrics['density']:.6f}")
            print(f"  Active cells:    {full_metrics['active_cells']}/{full_metrics['total_cells']}")
            print(f"  Shannon Entropy: {step_metrics['entropy']:.6f}  (0=mono, 1=diverse)")
            print(f"  Struct Ratio:    {step_metrics['structural_ratio']:.6f}  (penalty target)")
            print(f"  Cell census:     {census_str}")
            print(f"  Contagion:       energy_conv={contagion_cfg.structural_energy_conversion_prob}  "
                  f"sensor_conv={contagion_cfg.structural_sensor_conversion_prob}")
            print(f"  Stochastic:      baseline={stoch_cfg.baseline_transition_prob}  "
                  f"struct_decay={stoch_cfg.structural_to_void_decay_prob}")
            print(f"  Pop fitness:     best={fits_now.max():.4f}  mean={fits_now.mean():.4f}  std={fits_now.std():.4f}")
            print("-" * 72)
            sys.stdout.flush()
            last_status = t_now

        # --- Periodic snapshot ---
        if t_now - last_snapshot >= SNAPSHOT_INTERVAL:
            path = _save_branch_primitive(lattice, generation, ca_step_count)
            print(f"  [SNAPSHOT] Saved branch primitive -> {path}")
            sys.stdout.flush()
            last_snapshot = t_now

        # Brief yield to avoid busy-spin
        if ca_step_count % 500 == 0:
            time.sleep(0.001)

    # ----- Graceful shutdown -----
    print(f"\n[{datetime.now().isoformat()}] Shutting down after {generation} generations, {ca_step_count} CA steps.")
    path = _save_branch_primitive(lattice, generation, ca_step_count)
    print(f"  Final snapshot saved -> {path}")
    print("Done.")


if __name__ == "__main__":
    main()
