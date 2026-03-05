#!/usr/bin/env python3
"""
Continuous Evolution — Infinite Long-Run Evolution Loop

Combines the 3D Cellular Automata lattice with the memetic evolution engine
to grow fractal branch structures indefinitely.  Emits a status summary
every 5 minutes with:
    - Mean Energy
    - |m| (magnetisation / order parameter)
    - Branching Ratio

Periodically saves 3D Branch Primitives (.npy snapshots) to data/.

Thermal safety is handled at the OS level by vanguard-mcp.exe (hard-
throttle 85 °C, pause 88 °C).  This script does NOT duplicate that logic.
"""

from __future__ import annotations

import os
import sys
import json
import signal
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# CA lattice configuration (from ca/experiments/branching-3.yaml)
# ---------------------------------------------------------------------------
LATTICE_W, LATTICE_H, LATTICE_D = 64, 64, 64
NUM_CELLS = LATTICE_W * LATTICE_H * LATTICE_D

# States: 0=VOID, 1=STRUCTURAL, 2=COMPUTE, 3=ENERGY, 4=SENSOR
STATE_NAMES = ["VOID", "STRUCTURAL", "COMPUTE", "ENERGY", "SENSOR"]
NUM_STATES = len(STATE_NAMES)

# Outer-totalistic transitions (from ca/rules/example.toml)
# { current_state: { active_neighbour_count: next_state } }
TRANSITIONS = {
    0: {4: 1, 5: 1, 6: 1},          # VOID -> STRUCTURAL
    1: {2: 1, 3: 1, 4: 2, 5: 2},    # STRUCTURAL -> COMPUTE
    2: {2: 2, 3: 3, 4: 4},          # COMPUTE -> ENERGY / SENSOR
    3: {2: 3, 3: 3, 4: 3},          # ENERGY (stable)
    4: {2: 4, 3: 4, 4: 4},          # SENSOR (stable)
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
# 3-D Moore neighbourhood CA step (pure-numpy, no Rust kernel needed)
# ====================================================================

def _init_lattice() -> np.ndarray:
    """Seed: single STRUCTURAL cell at centre of 64^3 lattice."""
    lattice = np.zeros((LATTICE_W, LATTICE_H, LATTICE_D), dtype=np.uint8)
    cx, cy, cz = LATTICE_W // 2, LATTICE_H // 2, LATTICE_D // 2
    lattice[cx, cy, cz] = 1  # STRUCTURAL seed
    return lattice


def _ca_step(lattice: np.ndarray) -> np.ndarray:
    """One outer-totalistic CA tick using 3-D Moore neighbourhood (26 nbrs).

    Active neighbour = any cell with state > 0 (non-VOID).
    """
    active = (lattice > 0).astype(np.int32)

    # Sum over 26 Moore neighbours via shifted additions (periodic boundary)
    neighbour_count = np.zeros_like(active)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                if dx == 0 and dy == 0 and dz == 0:
                    continue
                neighbour_count += np.roll(
                    np.roll(np.roll(active, dx, axis=0), dy, axis=1), dz, axis=2
                )

    next_lattice = np.zeros_like(lattice)
    for state, transitions in TRANSITIONS.items():
        mask = lattice == state
        for ncount, nxt in transitions.items():
            next_lattice[mask & (neighbour_count == ncount)] = nxt

    return next_lattice


# ====================================================================
# Lightweight memetic evolution (self-contained — no import deps)
# ====================================================================

def _random_genome(rng: np.random.Generator) -> np.ndarray:
    """5-gene genome: dominance, virality, stability, compatibility, threshold."""
    return rng.uniform(0.1, 0.9, size=5).astype(np.float32)


def _fitness(genome: np.ndarray, lattice_metrics: dict) -> float:
    """Fitness = blend of genome traits weighted by lattice health."""
    dominance, virality, stability, compat, thresh = genome
    branching = lattice_metrics.get("branching_ratio", 1.0)
    density = lattice_metrics.get("density", 0.0)
    # Reward balance: branching near 1.5, moderate density, high stability
    target_br = 1.5
    br_score = max(0, 1.0 - abs(branching - target_br))
    density_score = min(density * 2, 1.0)
    gene_score = 0.3 * dominance + 0.2 * virality + 0.3 * stability + 0.1 * compat + 0.1 * (1 - thresh)
    return 0.4 * gene_score + 0.35 * br_score + 0.25 * density_score


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
# Lattice metrics
# ====================================================================

def _compute_metrics(lattice: np.ndarray, prev_active: int) -> dict:
    active = int(np.sum(lattice > 0))
    total = int(lattice.size)
    density = active / total if total else 0.0
    branching_ratio = active / max(prev_active, 1)

    # Mean energy: treat state value as energy level (0-4 scale, normalised)
    mean_energy = float(np.mean(lattice)) / (NUM_STATES - 1)

    # Order parameter |m|: fraction of dominant non-void state
    if active > 0:
        counts = np.bincount(lattice.ravel(), minlength=NUM_STATES)[1:]  # skip VOID
        m = float(np.max(counts)) / active
    else:
        m = 0.0

    return {
        "active_cells": active,
        "total_cells": total,
        "density": density,
        "branching_ratio": branching_ratio,
        "mean_energy": mean_energy,
        "abs_m": m,
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

def main():
    global _running
    print("=" * 72)
    print("  CONTINUOUS EVOLUTION — Infinite Long-Run")
    print("  Lattice: {}x{}x{}  |  Population: {}".format(
        LATTICE_W, LATTICE_H, LATTICE_D, POPULATION_SIZE))
    print("  Status every {} s  |  Snapshot every {} s".format(
        STATUS_INTERVAL, SNAPSHOT_INTERVAL))
    print("=" * 72)

    rng = np.random.default_rng(seed=42)

    # Initialise lattice
    lattice = _init_lattice()
    prev_active = int(np.sum(lattice > 0))

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

        # --- CA step ---
        lattice = _ca_step(lattice)
        ca_step_count += 1
        metrics = _compute_metrics(lattice, prev_active)
        prev_active = metrics["active_cells"]

        # --- Evolution step (every 10 CA steps) ---
        if ca_step_count % 10 == 0:
            population, fits = _evolve_population(population, metrics, rng)
            generation += 1

        # --- 5-minute status report ---
        if t_now - last_status >= STATUS_INTERVAL:
            elapsed = timedelta(seconds=int(t_now - start_time))
            fits_now = np.array([_fitness(g, metrics) for g in population], dtype=np.float32)
            print("-" * 72)
            print(f"  STATUS @ {datetime.now().isoformat()}  (uptime {elapsed})")
            print(f"  Generation: {generation}  |  CA step: {ca_step_count}")
            print(f"  Mean Energy:     {metrics['mean_energy']:.6f}")
            print(f"  |m|:             {metrics['abs_m']:.6f}")
            print(f"  Branching Ratio: {metrics['branching_ratio']:.6f}")
            print(f"  Density:         {metrics['density']:.6f}")
            print(f"  Active cells:    {metrics['active_cells']}/{metrics['total_cells']}")
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

        # Brief yield to avoid busy-spin when lattice becomes static
        if ca_step_count % 500 == 0:
            time.sleep(0.001)

    # ----- Graceful shutdown -----
    print(f"\n[{datetime.now().isoformat()}] Shutting down after {generation} generations, {ca_step_count} CA steps.")
    path = _save_branch_primitive(lattice, generation, ca_step_count)
    print(f"  Final snapshot saved -> {path}")
    print("Done.")


if __name__ == "__main__":
    main()
