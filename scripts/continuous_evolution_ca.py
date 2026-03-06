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

import argparse
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

# Outer-totalistic transitions v0.3.0 — Chaos & Decay
# Builds on v0.2.0 with:
#   - REMOVED 2-neighbour STRUCTURAL safety net (no more hiding!)
#   - Stochastic transition probability for non-deterministic differentiation
#   - Inactivity decay: STRUCTURAL cells decay to VOID after DECAY_THRESHOLD
#     steps without differentiating, forcing turnover and fresh growth
# { current_state: { active_neighbour_count: next_state } }
TRANSITIONS = {
    0: {3: 1, 4: 1, 5: 1, 6: 1},                    # VOID -> STRUCTURAL (easier nucleation)
    1: {3: 2, 4: 2, 5: 3, 6: 4, 7: 3, 8: 4},        # STRUCTURAL -> COMPUTE(3-4), ENERGY(5,7), SENSOR(6,8) — NO 2-nbr safety net!
    2: {2: 3, 3: 3, 4: 4, 5: 4},                     # COMPUTE -> ENERGY(2-3), SENSOR(4-5)
    3: {2: 3, 3: 3, 4: 3, 5: 3},                     # ENERGY (stable under moderate support)
    4: {2: 4, 3: 4, 4: 4, 5: 4},                     # SENSOR (stable under moderate support)
}

# v0.3.0 Stochastic & Decay parameters
STOCHASTIC_RATE = 0.02     # 2% chance per STRUCTURAL cell per step to randomly differentiate
DECAY_THRESHOLD = 50       # STRUCTURAL cells decay to VOID after this many steps unchanged
DECAY_ENABLED = True       # Toggle inactivity decay

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

def generate_primordial_seed_cube(cube_size: int = 3) -> np.ndarray:
    """Generate a dense primordial seed cube centred in the lattice.

    A single cell cannot bootstrap growth because VOID->STRUCTURAL
    requires 4-6 active Moore neighbours and one cell can only provide
    a neighbour count of 1 to its adjacent voxels.  A filled N^3 cube
    of STRUCTURAL cells provides the critical mass needed for the
    outer-totalistic rules to ignite cascading growth.

    Args:
        cube_size: side length of the seed cube (default 3 -> 27 cells).
                   Must be >= 2 to exceed the 4-neighbour ignition
                   threshold.

    Returns:
        64x64x64 uint8 lattice with the seed cube placed at centre.
    """
    if cube_size < 2:
        raise ValueError(
            f"cube_size must be >= 2 for ignition (got {cube_size}). "
            "A single cell cannot reach the 4-neighbour threshold."
        )

    lattice = np.zeros((LATTICE_W, LATTICE_H, LATTICE_D), dtype=np.uint8)

    cx, cy, cz = LATTICE_W // 2, LATTICE_H // 2, LATTICE_D // 2
    half = cube_size // 2

    x0, x1 = cx - half, cx - half + cube_size
    y0, y1 = cy - half, cy - half + cube_size
    z0, z1 = cz - half, cz - half + cube_size

    # Fill the cube with STRUCTURAL (state 1)
    lattice[x0:x1, y0:y1, z0:z1] = 1

    return lattice


def _init_lattice(cube_size: int = 1) -> np.ndarray:
    """Initialise the lattice with either a single cell or a primordial cube.

    Args:
        cube_size: if >= 2 use generate_primordial_seed_cube(); otherwise
                   fall back to the legacy single-cell seed.
    """
    if cube_size >= 2:
        return generate_primordial_seed_cube(cube_size)

    # Legacy single-cell seed (will collapse to VOID)
    lattice = np.zeros((LATTICE_W, LATTICE_H, LATTICE_D), dtype=np.uint8)
    cx, cy, cz = LATTICE_W // 2, LATTICE_H // 2, LATTICE_D // 2
    lattice[cx, cy, cz] = 1  # STRUCTURAL seed
    return lattice


def _count_neighbours(lattice: np.ndarray) -> np.ndarray:
    """Count active (non-VOID) Moore neighbours for each cell in the 3D lattice."""
    active = (lattice > 0).astype(np.int32)
    neighbour_count = np.zeros_like(active)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                if dx == 0 and dy == 0 and dz == 0:
                    continue
                neighbour_count += np.roll(
                    np.roll(np.roll(active, dx, axis=0), dy, axis=1), dz, axis=2
                )
    return neighbour_count


def _ca_step(lattice: np.ndarray, rng: np.random.Generator,
             inactivity: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """One CA tick with stochastic transitions and inactivity decay (v0.3.0).

    Returns (next_lattice, updated_inactivity_counter).

    New mechanics:
      - Stochastic: STRUCTURAL cells have STOCHASTIC_RATE chance per step
        to randomly differentiate into COMPUTE, ENERGY, or SENSOR.
      - Decay: STRUCTURAL cells that remain STRUCTURAL for DECAY_THRESHOLD
        consecutive steps decay to VOID, freeing space for fresh growth.
    """
    neighbour_count = _count_neighbours(lattice)

    # --- Standard deterministic transitions ---
    next_lattice = np.zeros_like(lattice)
    for state, transitions in TRANSITIONS.items():
        mask = lattice == state
        for ncount, nxt in transitions.items():
            next_lattice[mask & (neighbour_count == ncount)] = nxt

    # --- v0.3.0: Stochastic random differentiation ---
    # STRUCTURAL cells that didn't transition get a random chance to specialise
    structural_mask = (lattice == 1)
    still_structural = structural_mask & (next_lattice == 1)
    undecided = structural_mask & (next_lattice == 0)  # no rule matched
    stochastic_targets = still_structural | undecided

    if STOCHASTIC_RATE > 0 and np.any(stochastic_targets):
        n_targets = int(np.sum(stochastic_targets))
        rolls = rng.random(n_targets)
        hit = rolls < STOCHASTIC_RATE
        if np.any(hit):
            # Randomly assign COMPUTE(2), ENERGY(3), or SENSOR(4)
            new_states = rng.choice([2, 3, 4], size=int(np.sum(hit)))
            coords = np.argwhere(stochastic_targets)
            hit_coords = coords[hit]
            for idx, (x, y, z) in enumerate(hit_coords):
                next_lattice[x, y, z] = new_states[idx]

    # --- v0.3.0: Inactivity decay ---
    if inactivity is None:
        inactivity = np.zeros_like(lattice, dtype=np.int16)

    if DECAY_ENABLED:
        # Increment counter for cells that stayed STRUCTURAL
        stayed_structural = (lattice == 1) & (next_lattice == 1)
        inactivity[stayed_structural] += 1

        # Reset counter for cells that changed state
        changed = lattice != next_lattice
        inactivity[changed] = 0

        # Decay: STRUCTURAL cells past threshold -> VOID
        decay_mask = (next_lattice == 1) & (inactivity >= DECAY_THRESHOLD)
        next_lattice[decay_mask] = 0  # VOID
        inactivity[decay_mask] = 0
    else:
        inactivity = np.zeros_like(lattice, dtype=np.int16)

    return next_lattice, inactivity


# ====================================================================
# Lightweight memetic evolution (self-contained — no import deps)
# ====================================================================

def _random_genome(rng: np.random.Generator) -> np.ndarray:
    """5-gene genome: dominance, virality, stability, compatibility, threshold."""
    return rng.uniform(0.1, 0.9, size=5).astype(np.float32)


def _fitness(genome: np.ndarray, lattice_metrics: dict) -> float:
    """Fitness with Shannon entropy bonus & structural-dominance penalty.

    The fog is mathematically forced to differentiate its STRUCTURAL cells
    into a diverse mix of COMPUTE, ENERGY, and SENSOR nodes:
      - entropy bonus:  rewards heterogeneous cell-type distributions
      - struct penalty:  punishes monolithic STRUCTURAL blobs

    Final fitness = base_score + 0.25 * entropy - 0.20 * struct_dom
    """
    dominance, virality, stability, compat, thresh = genome
    branching = lattice_metrics.get("branching_ratio", 1.0)
    density = lattice_metrics.get("density", 0.0)
    entropy = lattice_metrics.get("entropy", 0.0)
    struct_dom = lattice_metrics.get("structural_dominance", 1.0)

    # Reward balance: branching near 1.5, moderate density, high stability
    target_br = 1.5
    br_score = max(0, 1.0 - abs(branching - target_br))
    density_score = min(density * 2, 1.0)
    gene_score = (0.3 * dominance + 0.2 * virality + 0.3 * stability
                  + 0.1 * compat + 0.1 * (1 - thresh))

    base_score = 0.35 * gene_score + 0.25 * br_score + 0.15 * density_score

    # --- Jack's Differentiation Physics ---
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
# Lattice metrics
# ====================================================================

def _shannon_entropy(lattice: np.ndarray, active: int) -> float:
    """Normalized Shannon entropy over non-VOID cell types.

    H = -sum(p_i * ln(p_i)) for each active state i in {STRUCTURAL,
    COMPUTE, ENERGY, SENSOR}.  Normalized to [0, 1] by dividing by
    ln(NUM_STATES - 1) so that a perfectly uniform mix scores 1.0
    and a monolithic blob scores 0.0.
    """
    if active == 0:
        return 0.0
    counts = np.bincount(lattice.ravel(), minlength=NUM_STATES)[1:]  # skip VOID
    probs = counts / active
    probs = probs[probs > 0]  # avoid log(0)
    H = -float(np.sum(probs * np.log(probs)))
    H_max = np.log(NUM_STATES - 1)  # ln(4) for 4 active states
    return H / H_max if H_max > 0 else 0.0


def _structural_dominance(lattice: np.ndarray, active: int) -> float:
    """Fraction of active cells that are STRUCTURAL (state 1).

    Returns 0.0 when no active cells exist, or a value in [0, 1].
    A value near 1.0 means the fog is a boring monolithic blob.
    """
    if active == 0:
        return 0.0
    structural_count = int(np.sum(lattice == 1))
    return structural_count / active


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

    # --- Jack's Differentiation Physics ---
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
        description="Continuous Evolution -- Infinite Long-Run Evolution Loop",
    )
    parser.add_argument(
        "--seed-cube-size",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Side-length of the primordial STRUCTURAL seed cube placed at "
            "the lattice centre. Must be >= 2 for ignition (default: 1, "
            "legacy single-cell — will collapse to VOID)."
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

    print("=" * 72)
    print("  CONTINUOUS EVOLUTION v0.3.0 — Chaos & Decay")
    print("  Lattice: {}x{}x{}  |  Population: {}".format(
        LATTICE_W, LATTICE_H, LATTICE_D, POPULATION_SIZE))
    print(f"  Seed:   {seed_desc}")
    print("  Physics: entropy bonus + struct penalty + stochastic + decay")
    print(f"  Stochastic rate: {STOCHASTIC_RATE}  |  Decay threshold: {DECAY_THRESHOLD} steps")
    print("  Status every {} s  |  Snapshot every {} s".format(
        STATUS_INTERVAL, SNAPSHOT_INTERVAL))
    print("=" * 72)

    rng = np.random.default_rng(seed=42)

    # Initialise lattice with primordial seed cube (or legacy single cell)
    lattice = _init_lattice(cube_size=cube_sz)
    prev_active = int(np.sum(lattice > 0))
    inactivity = np.zeros_like(lattice, dtype=np.int16)  # v0.3.0 decay counter

    # Initialise meme population
    population = np.array([_random_genome(rng) for _ in range(POPULATION_SIZE)], dtype=np.float32)

    generation = 0
    ca_step_count = 0
    total_decayed = 0  # cumulative cells decayed to VOID
    start_time = time.monotonic()
    last_status = start_time
    last_snapshot = start_time

    print(f"\n[{datetime.now().isoformat()}] Evolution started.\n")

    while _running:
        t_now = time.monotonic()

        # --- CA step (v0.3.0: stochastic + decay) ---
        prev_structural = int(np.sum(lattice == 1))
        lattice, inactivity = _ca_step(lattice, rng, inactivity)
        ca_step_count += 1
        new_structural = int(np.sum(lattice == 1))
        decayed_this_step = max(0, prev_structural - new_structural - int(np.sum((lattice > 1) & (lattice <= 4))))
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
            # Per-state census for differentiation tracking
            state_counts = np.bincount(lattice.ravel(), minlength=NUM_STATES)
            census_str = "  ".join(
                f"{STATE_NAMES[i]}={state_counts[i]}"
                for i in range(NUM_STATES)
            )

            print("-" * 72)
            print(f"  STATUS @ {datetime.now().isoformat()}  (uptime {elapsed})")
            print(f"  Generation: {generation}  |  CA step: {ca_step_count}")
            print(f"  Mean Energy:     {metrics['mean_energy']:.6f}")
            print(f"  |m|:             {metrics['abs_m']:.6f}")
            print(f"  Branching Ratio: {metrics['branching_ratio']:.6f}")
            print(f"  Density:         {metrics['density']:.6f}")
            print(f"  Active cells:    {metrics['active_cells']}/{metrics['total_cells']}")
            print(f"  Shannon Entropy: {metrics['entropy']:.6f}  (0=mono, 1=diverse)")
            print(f"  Struct Dominance:{metrics['structural_dominance']:.6f}  (penalty target)")
            print(f"  Cell census:     {census_str}")
            decaying_soon = int(np.sum((inactivity > DECAY_THRESHOLD * 0.7) & (lattice == 1)))
            print(f"  Decay pressure:  {decaying_soon} STRUCTURAL cells near decay threshold")
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
