#!/usr/bin/env python3
"""3D CA stepping utilities with state-aware contagion, stochasticity, decay, and voxel memory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

import numpy as np
import tomli

STATE_NAME_TO_ID = {
    "VOID": 0,
    "STRUCTURAL": 1,
    "COMPUTE": 2,
    "ENERGY": 3,
    "SENSOR": 4,
}


@dataclass
class DecayConfig:
    enabled: bool = True
    inactivity_neighbor_threshold: int = 1
    structural_inactive_steps_to_decay: int = 6


@dataclass
class StochasticConfig:
    enabled: bool = True
    baseline_transition_prob: float = 0.08
    structural_to_energy_prob: float = 0.08
    structural_to_sensor_prob: float = 0.08
    compute_to_energy_prob: float = 0.10
    compute_to_sensor_prob: float = 0.10
    structural_to_void_decay_prob: float = 0.04
    energy_to_void_decay_prob: float = 0.005
    sensor_to_void_decay_prob: float = 0.004


@dataclass
class ContagionConfig:
    enabled: bool = True
    energy_neighbor_threshold: int = 4
    sensor_neighbor_threshold: int = 4
    structural_energy_conversion_prob: float = 0.40
    structural_sensor_conversion_prob: float = 0.30
    compute_energy_conversion_prob: float = 0.30
    compute_sensor_conversion_prob: float = 0.25


@dataclass
class VoxelMemoryParams:
    age_young_threshold: int = 50
    age_mature_threshold: int = 200
    resistance_max: float = 0.75
    reverse_contagion_threshold: int = 5
    reverse_contagion_base_prob: float = 0.15
    reverse_contagion_boost: float = 0.08
    rag_query_radius: int = 3
    rag_memory_decay: float = 0.02
    rag_reinforcement_boost: float = 1.35
    rag_entropy_weight: float = 0.15
    energy_to_compute_prob: float = 0.12


def load_rule_spec(rule_path: str | Path) -> Dict[str, Any]:
    with Path(rule_path).open("rb") as f:
        return tomli.load(f)


def init_memory_grid(shape: Tuple[int, int, int]) -> np.ndarray:
    """Memory grid channels: [compute_age, last_active_gen, memory_strength]."""
    grid = np.zeros((3,) + shape, dtype=np.float32)
    grid[2, :, :, :] = 1.0
    return grid


def _count_neighbors_by_state(state: np.ndarray) -> np.ndarray:
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


def _compile_transition_table(rule_spec: Mapping[str, Any]) -> Dict[int, Dict[int, int]]:
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
        structural_inactive_steps_to_decay=int(decay.get("structural_inactive_steps_to_decay", 6)),
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
        structural_to_void_decay_prob=float(stoch.get("structural_to_void_decay_prob", 0.04)),
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
        compute_energy_conversion_prob=float(contagion.get("compute_energy_conversion_prob", 0.30)),
        compute_sensor_conversion_prob=float(contagion.get("compute_sensor_conversion_prob", 0.25)),
    )


def _apply_deterministic_transitions(state: np.ndarray, active_neighbors: np.ndarray, table: Mapping[int, Mapping[int, int]]) -> np.ndarray:
    next_state = np.zeros_like(state)
    for src, mapping in table.items():
        src_mask = state == src
        if not np.any(src_mask):
            continue
        for n_count, target in mapping.items():
            next_state[src_mask & (active_neighbors == n_count)] = target
    return next_state


def _reverse_contagion_probability(compute_neighbors: np.ndarray, mem: VoxelMemoryParams) -> np.ndarray:
    excess = np.maximum(0, compute_neighbors - mem.reverse_contagion_threshold)
    prob = mem.reverse_contagion_base_prob + mem.reverse_contagion_boost * excess.astype(np.float32)
    prob[compute_neighbors < mem.reverse_contagion_threshold] = 0.0
    return np.minimum(prob, 0.95)


def _apply_contagion_overrides(next_state: np.ndarray, neighbor_counts_by_state: np.ndarray, rng: np.random.Generator, contagion: ContagionConfig, memory_grid: np.ndarray, mem: VoxelMemoryParams) -> np.ndarray:
    if not contagion.enabled:
        return next_state

    out = next_state.copy()
    energy_n = neighbor_counts_by_state[STATE_NAME_TO_ID["ENERGY"]]
    sensor_n = neighbor_counts_by_state[STATE_NAME_TO_ID["SENSOR"]]
    compute_n = neighbor_counts_by_state[STATE_NAME_TO_ID["COMPUTE"]]

    structural = out == STATE_NAME_TO_ID["STRUCTURAL"]
    compute = out == STATE_NAME_TO_ID["COMPUTE"]

    out[structural & (energy_n >= contagion.energy_neighbor_threshold) & (rng.random(out.shape) < contagion.structural_energy_conversion_prob)] = STATE_NAME_TO_ID["ENERGY"]
    structural = out == STATE_NAME_TO_ID["STRUCTURAL"]
    out[structural & (sensor_n >= contagion.sensor_neighbor_threshold) & (rng.random(out.shape) < contagion.structural_sensor_conversion_prob)] = STATE_NAME_TO_ID["SENSOR"]

    out[compute & (energy_n >= contagion.energy_neighbor_threshold) & (rng.random(out.shape) < contagion.compute_energy_conversion_prob)] = STATE_NAME_TO_ID["ENERGY"]
    compute = out == STATE_NAME_TO_ID["COMPUTE"]
    out[compute & (sensor_n >= contagion.sensor_neighbor_threshold) & (rng.random(out.shape) < contagion.compute_sensor_conversion_prob)] = STATE_NAME_TO_ID["SENSOR"]

    # Reverse contagion: dense COMPUTE neighborhoods recruit nearby STRUCTURAL cells.
    structural = out == STATE_NAME_TO_ID["STRUCTURAL"]
    rc_prob = _reverse_contagion_probability(compute_n, mem)
    rc_prob = np.minimum(0.95, rc_prob * np.maximum(0.25, memory_grid[2]))
    out[structural & (rng.random(out.shape) < rc_prob)] = STATE_NAME_TO_ID["COMPUTE"]

    return out


def _apply_stochastic_overrides(next_state: np.ndarray, rng: np.random.Generator, stoch: StochasticConfig) -> np.ndarray:
    if not stoch.enabled:
        return next_state

    out = next_state.copy()
    structural = out == STATE_NAME_TO_ID["STRUCTURAL"]
    compute = out == STATE_NAME_TO_ID["COMPUTE"]
    energy = out == STATE_NAME_TO_ID["ENERGY"]
    sensor = out == STATE_NAME_TO_ID["SENSOR"]

    out[structural & (rng.random(out.shape) < stoch.structural_to_energy_prob)] = STATE_NAME_TO_ID["ENERGY"]
    structural = out == STATE_NAME_TO_ID["STRUCTURAL"]
    out[structural & (rng.random(out.shape) < stoch.structural_to_sensor_prob)] = STATE_NAME_TO_ID["SENSOR"]

    out[compute & (rng.random(out.shape) < stoch.compute_to_energy_prob)] = STATE_NAME_TO_ID["ENERGY"]
    compute = out == STATE_NAME_TO_ID["COMPUTE"]
    out[compute & (rng.random(out.shape) < stoch.compute_to_sensor_prob)] = STATE_NAME_TO_ID["SENSOR"]

    structural = out == STATE_NAME_TO_ID["STRUCTURAL"]
    out[structural & (rng.random(out.shape) < stoch.structural_to_void_decay_prob)] = STATE_NAME_TO_ID["VOID"]
    out[energy & (rng.random(out.shape) < stoch.energy_to_void_decay_prob)] = STATE_NAME_TO_ID["VOID"]
    out[sensor & (rng.random(out.shape) < stoch.sensor_to_void_decay_prob)] = STATE_NAME_TO_ID["VOID"]

    return out


def _apply_memory_reinforcement(next_state: np.ndarray, memory_grid: np.ndarray, current_gen: int, mem: VoxelMemoryParams, rng: np.random.Generator) -> np.ndarray:
    out = next_state.copy()
    compute = out == STATE_NAME_TO_ID["COMPUTE"]

    # Update compute age + active generation + strengthening.
    memory_grid[0][compute] = np.minimum(memory_grid[0][compute] + 1.0, 65535.0)
    memory_grid[1][compute] = float(current_gen)
    memory_grid[2][compute] = np.minimum(memory_grid[2][compute] * mem.rag_reinforcement_boost, 2.0)

    # Decay memory for inactive voxels.
    inactive = ~compute
    generations_inactive = np.maximum(0.0, float(current_gen) - memory_grid[1])
    memory_grid[2][inactive] *= np.power(1.0 - mem.rag_memory_decay, generations_inactive[inactive])
    memory_grid[2] = np.maximum(memory_grid[2], 0.01)

    # Memory-based decay resistance for compute cells that drifted to VOID.
    dropped_compute = (next_state == STATE_NAME_TO_ID["VOID"]) & (memory_grid[0] > 0)
    age = memory_grid[0]
    resistance = np.zeros_like(memory_grid[2])
    young = age <= mem.age_young_threshold
    mature = (age > mem.age_young_threshold) & (age <= mem.age_mature_threshold)
    old = age > mem.age_mature_threshold

    resistance[young] = (age[young] / max(1.0, float(mem.age_young_threshold))) * mem.resistance_max
    resistance[mature] = mem.resistance_max
    resistance[old] = mem.resistance_max * np.exp(-(age[old] - mem.age_mature_threshold) / 500.0)
    resistance *= np.minimum(memory_grid[2], 1.5)

    out[dropped_compute & (rng.random(out.shape) < resistance)] = STATE_NAME_TO_ID["COMPUTE"]

    # Energy->compute economy bridge.
    energy = out == STATE_NAME_TO_ID["ENERGY"]
    out[energy & (rng.random(out.shape) < mem.energy_to_compute_prob)] = STATE_NAME_TO_ID["COMPUTE"]

    # reset age if not compute after final reinforcement
    memory_grid[0][out != STATE_NAME_TO_ID["COMPUTE"]] = 0.0
    return out


def step_ca_lattice(
    state: np.ndarray,
    rule_spec: Mapping[str, Any],
    rng: np.random.Generator,
    inactivity_steps: Optional[np.ndarray] = None,
    memory_grid: Optional[np.ndarray] = None,
    current_gen: int = 0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Dict[str, float]]:
    """Single CA step with deterministic + contagion + stochastic + decay + memory dynamics."""
    if state.ndim != 3:
        raise ValueError(f"Expected a 3D lattice, got shape={state.shape}")

    if memory_grid is None:
        memory_grid = init_memory_grid(state.shape)

    table = _compile_transition_table(rule_spec)
    decay = _load_decay_config(rule_spec)
    stoch = _load_stochastic_config(rule_spec)
    contagion = _load_contagion_config(rule_spec)
    mem = VoxelMemoryParams()

    neighbor_counts = _count_neighbors_by_state(state)
    active_neighbors = np.sum(neighbor_counts[1:], axis=0)

    next_state = _apply_deterministic_transitions(state, active_neighbors, table)
    next_state = _apply_contagion_overrides(next_state, neighbor_counts, rng, contagion, memory_grid, mem)

    if inactivity_steps is None:
        inactivity_steps = np.zeros_like(state, dtype=np.int16)

    if decay.enabled:
        structural = next_state == STATE_NAME_TO_ID["STRUCTURAL"]
        low_support = active_neighbors <= decay.inactivity_neighbor_threshold
        inactivity_steps = np.where(structural & low_support, inactivity_steps + 1, 0)
        next_state[structural & (inactivity_steps >= decay.structural_inactive_steps_to_decay)] = STATE_NAME_TO_ID["VOID"]
        inactivity_steps[~structural] = 0

    next_state = _apply_stochastic_overrides(next_state, rng, stoch)
    next_state = _apply_memory_reinforcement(next_state, memory_grid, current_gen, mem, rng)

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
    return next_state.astype(np.uint8, copy=False), inactivity_steps.astype(np.int16, copy=False), memory_grid.astype(np.float32, copy=False), metrics
