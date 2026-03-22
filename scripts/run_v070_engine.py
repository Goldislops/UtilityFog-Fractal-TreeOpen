#!/usr/bin/env python3
"""
v0.7.0 Continuous Evolution Engine — The OpenClaw Memory Update

Wraps the step_ca_lattice() stepping library with the memetic evolution
engine to grow fractal branch structures indefinitely.

New in v0.7.0:
  - Voxel Memory (Spatial RAG): COMPUTE cells gain decay resistance
  - Machine Economy (Reverse Contagion): ENERGY -> COMPUTE conversion
  - Differentiation-aware fitness scoring

Emits a status summary every 5 minutes.
Periodically saves 3D Branch Primitives (.npz snapshots).
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.continuous_evolution_ca import (
    STATE_NAME_TO_ID,
    init_memory_grid,
    init_telemetry_window,
    load_rule_spec,
    reset_telemetry_window,
    step_ca_lattice,
    summarize_telemetry_window,
    write_telemetry_artifact,
)

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LATTICE_W, LATTICE_H, LATTICE_D = 64, 64, 64
NUM_CELLS = LATTICE_W * LATTICE_H * LATTICE_D
STATE_NAMES = ["VOID", "STRUCTURAL", "COMPUTE", "ENERGY", "SENSOR"]
NUM_STATES = len(STATE_NAMES)

POPULATION_SIZE = 120
MUTATION_RATE = 0.10
CROSSOVER_RATE = 0.80
ELITISM_RATE = 0.10
TOURNAMENT_K = 3

STATUS_INTERVAL = 300   # seconds (5 minutes)
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


# ---------------------------------------------------------------------------
# Primordial seed
# ---------------------------------------------------------------------------

def generate_primordial_seed_cube(cube_size: int = 3) -> np.ndarray:
    lattice = np.zeros((LATTICE_W, LATTICE_H, LATTICE_D), dtype=np.uint8)
    if cube_size < 2:
        cx, cy, cz = LATTICE_W // 2, LATTICE_H // 2, LATTICE_D // 2
        lattice[cx, cy, cz] = 1
        return lattice

    cx, cy, cz = LATTICE_W // 2, LATTICE_H // 2, LATTICE_D // 2
    half = cube_size // 2
    x0, x1 = cx - half, cx - half + cube_size
    y0, y1 = cy - half, cy - half + cube_size
    z0, z1 = cz - half, cz - half + cube_size
    lattice[x0:x1, y0:y1, z0:z1] = 1  # STRUCTURAL
    return lattice


# ---------------------------------------------------------------------------
# Lightweight memetic evolution (self-contained)
# ---------------------------------------------------------------------------

def _random_genome(rng: np.random.Generator) -> np.ndarray:
    return rng.uniform(0.1, 0.9, size=5).astype(np.float32)


# Phase 5: Target median age for longevity bonus (AURA directive)
TARGET_MEDIAN_AGE = 10.0

def _fitness(genome: np.ndarray, metrics: dict) -> float:
    dominance, virality, stability, compat, thresh = genome
    density = metrics.get("density", 0.0)
    entropy = metrics.get("entropy", 0.0)
    compute_ratio = metrics.get("compute_ratio", 0.0)
    compute_median_age = metrics.get("compute_median_age", 0.0)

    # Phase 5 fitness: AURA formula with longevity pressure
    # base_fitness + propagation_bonus + differentiation*0.4 + longevity*0.6
    #
    # base_fitness: genome contribution + density maintenance
    gene_score = 0.3 * dominance + 0.2 * virality + 0.3 * stability + 0.1 * compat + 0.1 * (1 - thresh)
    density_score = min(density * 2.5, 1.0)
    base_fitness = 0.15 * gene_score + 0.10 * density_score

    # propagation_bonus: compute ratio drives propagation
    propagation_bonus = min(0.15, compute_ratio * 0.75)

    # differentiation_term: entropy rewards state diversity
    entropy_score = min(entropy, 1.0)
    compute_score = min(compute_ratio * 5.0, 1.0)
    differentiation_term = 0.5 * entropy_score + 0.5 * compute_score

    # longevity_score: AURA's key innovation -- reward persistent COMPUTE
    longevity_score = min(1.0, compute_median_age / TARGET_MEDIAN_AGE)

    # AURA Phase 5 formula:
    total = base_fitness + propagation_bonus + (differentiation_term * 0.4) + (longevity_score * 0.6)
    return max(0.0, min(1.0, total))


def _tournament_select(pop, fits, k, rng):
    indices = rng.choice(len(pop), size=k, replace=False)
    return int(indices[np.argmax(fits[indices])])


def _crossover(p1, p2, rng):
    mask = rng.random(len(p1)) < 0.5
    c1, c2 = p1.copy(), p2.copy()
    c1[mask], c2[mask] = p2[mask], p1[mask]
    return c1, c2


def _mutate(genome, rate, rng):
    g = genome.copy()
    for i in range(len(g)):
        if rng.random() < rate:
            g[i] = np.clip(g[i] + rng.normal(0, 0.08), 0.0, 1.0)
    return g


def _evolve_population(pop, metrics, rng):
    n = len(pop)
    fits = np.array([_fitness(g, metrics) for g in pop], dtype=np.float32)
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
    new_fits = np.array([_fitness(g, metrics) for g in new_pop], dtype=np.float32)
    return new_pop, new_fits


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

def _save_snapshot(lattice, memory_grid, generation, ca_step, best_fitness):
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    fname = f"v070_gen{generation:06d}_step{ca_step:06d}_{ts}.npz"
    path = DATA_DIR / fname
    np.savez_compressed(
        path,
        lattice=lattice,
        memory_grid=memory_grid,
        generation=generation,
        ca_step=ca_step,
        best_fitness=best_fitness,
    )
    return path


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    global _running

    parser = argparse.ArgumentParser(description="v0.7.0 OpenClaw Engine")
    parser.add_argument("--seed-cube-size", type=int, default=3)
    parser.add_argument("--rule-file", type=str, default=str(PROJECT_ROOT / "ca" / "rules" / "example.toml"))
    parser.add_argument("--resume", type=str, default=None,
                        help="Path to .npz snapshot to resume from")
    args = parser.parse_args()

    rule_spec = load_rule_spec(args.rule_file)

    print("=" * 72)
    print("  v0.7.0 OPENCLAW ENGINE — The Machine Economy")
    print("  Lattice: {}x{}x{}  |  Population: {}".format(
        LATTICE_W, LATTICE_H, LATTICE_D, POPULATION_SIZE))
    print("  Voxel Memory: ENABLED  |  Reverse Contagion: ENABLED")
    print("  Rule file: {}".format(args.rule_file))
    print("  Status every {}s  |  Snapshot every {}s".format(
        STATUS_INTERVAL, SNAPSHOT_INTERVAL))
    print("=" * 72)

    rng = np.random.default_rng(seed=42)

    if args.resume:
        snap = np.load(args.resume, allow_pickle=True)
        lattice = snap["lattice"]
        memory_grid = snap["memory_grid"]
        generation = int(snap["generation"])
        ca_step_count = int(snap["ca_step"])
        best_fitness_ever = float(snap["best_fitness"])
        best_fitness_gen = 0
        # v0.7.5 migration: extend 3-channel memory grid to 5 channels
        old_channels = memory_grid.shape[0]
        if old_channels < 5:
            shape_3d = memory_grid.shape[1:]
            extended = init_memory_grid(shape_3d)
            extended[:old_channels] = memory_grid
            memory_grid = extended
            print(f"  [MIGRATE] Extended memory grid from {old_channels} to 5 channels (v0.7.5)")
        print(f"  [RESUME] Loaded gen={generation}, step={ca_step_count}, best_fitness={best_fitness_ever:.4f}")
    else:
        lattice = generate_primordial_seed_cube(args.seed_cube_size)
        memory_grid = init_memory_grid(lattice.shape)
        generation = 0
        ca_step_count = 0
        best_fitness_ever = 0.0
        best_fitness_gen = 0

    inactivity_steps = np.zeros_like(lattice, dtype=np.int16)
    population = np.array([_random_genome(rng) for _ in range(POPULATION_SIZE)], dtype=np.float32)

    start_time = time.monotonic()
    last_status = start_time
    last_snapshot = start_time
    prev_compute_ratio = 0.0
    telemetry = init_telemetry_window()

    # Phase 10.8: Great Oscillation tracking
    initial_non_void = int(np.sum(lattice > 0))
    drought_start_gen = ca_step_count  # drought cycle starts from current gen
    drought_hibernation_triggered = False

    print(f"\n[{datetime.now().isoformat()}] Engine started (PID {os.getpid()}).\n")

    while _running:
        t_now = time.monotonic()

        # --- CA step (v0.7.0 with voxel memory + reverse contagion) ---
        lattice, inactivity_steps, memory_grid, metrics = step_ca_lattice(
            lattice, rule_spec, rng,
            inactivity_steps=inactivity_steps,
            memory_grid=memory_grid,
            current_gen=ca_step_count,
            telemetry=telemetry,
        )
        ca_step_count += 1

        # Compute density for GA
        active = int(np.sum(lattice > 0))
        density = active / NUM_CELLS
        metrics["density"] = density
        metrics["active_cells"] = active

        # Phase 10.8: Safety valve -- emergency hibernation if population drops >40%
        if initial_non_void > 0 and not drought_hibernation_triggered:
            pop_ratio = active / initial_non_void
            if pop_ratio < 0.60:  # 40% drop threshold
                print(f"\n  [SAFETY VALVE] Population dropped to {pop_ratio:.1%} of initial!")
                print(f"  [SAFETY VALVE] Triggering emergency hibernation snapshot...")
                path = _save_snapshot(lattice, memory_grid, generation, ca_step_count, best_fitness_ever)
                print(f"  [SAFETY VALVE] Emergency snapshot saved -> {path}")
                drought_hibernation_triggered = True
                # Don't stop -- let it recover if it can!
                print(f"  [SAFETY VALVE] Engine continues. Will not trigger again.")
                sys.stdout.flush()

        # --- Evolution step (every 10 CA steps) ---
        if ca_step_count % 10 == 0:
            population, fits = _evolve_population(population, metrics, rng)
            generation += 1
            if fits.max() > best_fitness_ever:
                best_fitness_ever = float(fits.max())
                best_fitness_gen = generation

        # --- 5-minute status report ---
        if t_now - last_status >= STATUS_INTERVAL:
            elapsed = timedelta(seconds=int(t_now - start_time))
            fits_now = np.array([_fitness(g, metrics) for g in population], dtype=np.float32)

            # State census
            counts = np.bincount(lattice.ravel(), minlength=5)
            non_void = int(np.sum(counts[1:]))

            # Compute delta from previous report
            compute_delta = metrics["compute_ratio"] - prev_compute_ratio
            prev_compute_ratio = metrics["compute_ratio"]

            # Memory stats (Phase 5: median age + longevity score)
            compute_mask = lattice == STATE_NAME_TO_ID["COMPUTE"]
            avg_age = float(np.mean(memory_grid[0][compute_mask])) if np.any(compute_mask) else 0.0
            med_age = float(np.median(memory_grid[0][compute_mask])) if np.any(compute_mask) else 0.0
            max_age = float(np.max(memory_grid[0][compute_mask])) if np.any(compute_mask) else 0.0
            longevity = min(1.0, med_age / TARGET_MEDIAN_AGE)

            print("-" * 72)
            print(f"  STATUS @ {datetime.now().isoformat()}  (uptime {elapsed})")
            print(f"  Generation: {generation}  |  CA step: {ca_step_count}")
            print(f"  Active cells:    {active}/{NUM_CELLS} (density {density:.4f})")
            print(f"  STRUCT: {counts[1]:>6}  COMPUTE: {counts[2]:>6}  ENERGY: {counts[3]:>6}  SENSOR: {counts[4]:>6}")
            if non_void > 0:
                print(f"  Ecosystem: STRUCT {counts[1]/non_void:.1%}  COMPUTE {counts[2]/non_void:.1%}  ENERGY {counts[3]/non_void:.1%}  SENSOR {counts[4]/non_void:.1%}")
            print(f"  COMPUTE density: {metrics['compute_ratio']:.4f} (delta {compute_delta:+.4f})")
            print(f"  Shannon entropy: {metrics['entropy']:.4f}")
            print(f"  Memory: avg_age={avg_age:.1f}  med_age={med_age:.1f}  max_age={max_age:.0f}  longevity_score={longevity:.3f}")
            print(f"  Fitness: best={fits_now.max():.4f}  mean={fits_now.mean():.4f}  (ATH={best_fitness_ever:.4f} @ gen {best_fitness_gen})")
            # Phase 10.8 drought status
            import math
            cycle_len = 10000
            cycle_pos = ca_step_count % cycle_len
            drought_mult = 0.70 + 0.30 * math.cos(2 * math.pi * cycle_pos / cycle_len)
            season = 'SUMMER' if drought_mult > 0.85 else ('AUTUMN' if drought_mult > 0.55 else 'WINTER')
            print(f"  Drought: {season} (energy={drought_mult:.1%} of nominal, cycle={cycle_pos}/{cycle_len})")
            if initial_non_void > 0:
                pop_pct = active / initial_non_void * 100
                print(f"  Population: {pop_pct:.1f}% of initial ({initial_non_void:,})")
            # Telemetry window summary
            telem_summary, telem_payload = summarize_telemetry_window(telemetry)
            print(f"  {telem_summary}")
            if telem_payload:
                ts = datetime.now().strftime("%Y%m%dT%H%M%S")
                write_telemetry_artifact(DATA_DIR / f"telemetry_{ts}.json", telem_payload)
            reset_telemetry_window(telemetry)
            print("-" * 72)
            sys.stdout.flush()
            last_status = t_now

        # --- Periodic snapshot ---
        if t_now - last_snapshot >= SNAPSHOT_INTERVAL:
            path = _save_snapshot(lattice, memory_grid, generation, ca_step_count, best_fitness_ever)
            print(f"  [SNAPSHOT] Saved -> {path}")
            sys.stdout.flush()
            last_snapshot = t_now

        # Yield to avoid busy-spin
        if ca_step_count % 500 == 0:
            time.sleep(0.001)

    # --- Graceful shutdown ---
    print(f"\n[{datetime.now().isoformat()}] Shutting down after {generation} generations, {ca_step_count} CA steps.")
    path = _save_snapshot(lattice, memory_grid, generation, ca_step_count, best_fitness_ever)
    print(f"  Final snapshot saved -> {path}")
    print("Done.")


if __name__ == "__main__":
    main()
