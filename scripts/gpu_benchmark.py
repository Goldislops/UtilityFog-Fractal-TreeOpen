#!/usr/bin/env python3
"""Phase 14a: GPU Benchmark — Before/After comparison for CA stepping pipeline.

Usage:
    python -m scripts.gpu_benchmark [--snapshot path/to/snapshot.npz] [--steps 10]

Measures per-step timing for:
  - Full step (CPU-only baseline)
  - Full step (GPU-resident, after migration)
  - Individual hotspots: count_neighbors_3d, box_filter, mycelial_diffuse
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Dict, List

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# GPU setup
# ---------------------------------------------------------------------------
try:
    from scripts.gpu_accelerator import GPU_AVAILABLE, GPU_NAME, GPU_VRAM
except ImportError:
    GPU_AVAILABLE = False
    GPU_NAME = "N/A"
    GPU_VRAM = 0.0

if GPU_AVAILABLE:
    import cupy as cp

from scripts.continuous_evolution_ca import (
    step_ca_lattice,
    count_neighbors_3d,
    load_rule_spec,
    init_memory_grid,
    _separable_box_filter_3d,
    _max_neighbor_value,
)


def _timer():
    """High-resolution timer context manager."""
    class Timer:
        def __init__(self):
            self.elapsed = 0.0
        def __enter__(self):
            self.start = time.perf_counter()
            return self
        def __exit__(self, *_):
            self.elapsed = time.perf_counter() - self.start
    return Timer()


def benchmark_component(name: str, fn, warmup: int = 2, iterations: int = 10) -> float:
    """Benchmark a single function, return median time in ms."""
    # Warmup
    for _ in range(warmup):
        fn()

    times = []
    for _ in range(iterations):
        t = _timer()
        with t:
            fn()
        times.append(t.elapsed * 1000)  # ms

    times.sort()
    median = times[len(times) // 2]
    return median


def _load_snapshot(snapshot_path):
    """Return (lattice, memory_grid, generation) with the archive already closed.

    `run_benchmarks` previously did `snap = np.load(...)` inline and kept the
    returned `NpzFile` referenced for the whole suite: the shape and cell-count
    calculations, `load_rule_spec`, legacy memory-grid expansion, RNG and
    inactivity construction, the temporary CPU/GPU global switch, every CPU and
    optional GPU component benchmark with all its warmups and iterations, every
    full `step_ca_lattice` step, the timing aggregation and the printed summary.
    A benchmark run therefore held the input handle across an operator-selected
    number of steps, released only by eventual object destruction. On Windows a
    retained snapshot handle can interfere with deleting, rotating or replacing
    that file.

    The `with` block bounds the archive to extraction: the three values are
    materialised while it is open and it is closed before this helper returns,
    so no benchmark work holds the input handle. Closure is explicit, not left
    to garbage collection.

    Extraction is not guarded: a missing key or a failing `int()` conversion
    propagates exactly as before, and the `with` block still closes the archive
    on the way out. The supplied `snapshot_path` object is passed to `np.load`
    unchanged (no path conversion introduced).

    `allow_pickle=False` — an object-dtype member is stored as a pickle, so
    loading one with pickle enabled is arbitrary code execution. `--snapshot`
    is forwarded here straight from argparse, so NumPy now refuses such a
    member with a `ValueError` rather than unpickling it. Passed explicitly
    although it is already NumPy's default, because relying on a default makes
    the property invisible at the call site and silently reversible upstream.
    There is deliberately no fallback retry and no override.

    That refusal is an OBJECT-MEMBER REFUSAL, not whole-archive validation:
    nothing here resists decompression amplification, absurd declared shapes,
    hostile member names or defects in NumPy's own header parsing.

    The claim is archive resource lifetime relative to extraction — not an
    indefinitely accumulating descriptor leak, not snapshot validation, and
    nothing about the benchmark mathematics or timing methodology.
    """
    with np.load(snapshot_path, allow_pickle=False) as snap:
        lattice = snap["lattice"]
        memory_grid = snap["memory_grid"]
        generation = int(snap["generation"])
    return lattice, memory_grid, generation


def run_benchmarks(snapshot_path: str, num_steps: int = 10):
    """Run the full benchmark suite."""
    # Refuse a nonpositive step count HERE, before anything observable happens.
    # Previously the run proceeded through the banner, snapshot loading, rule
    # loading, RNG construction, the temporary backend switch and every
    # component benchmark, and only then failed in the timing aggregation --
    # `np.min([])` on an empty list, or an unbound `first_metrics` because the
    # step loop never ran. That is a long way to travel, and a lot of state to
    # touch, to report an argument that was wrong before the function started.
    if num_steps <= 0:
        raise ValueError(f"num_steps must be positive, got {num_steps}")

    print("=" * 72)
    print("  Phase 14a GPU Benchmark — Medusa Stepping Pipeline")
    print("=" * 72)
    print()

    # Hardware info
    print(f"  GPU: {GPU_NAME if GPU_AVAILABLE else 'Not available'}")
    if GPU_AVAILABLE:
        print(f"  VRAM: {GPU_VRAM:.1f} GB")
        free = cp.cuda.runtime.memGetInfo()[0] / 1024**3
        print(f"  Free VRAM: {free:.1f} GB")
    print()

    # Load snapshot
    print(f"  Loading snapshot: {snapshot_path}")
    lattice, memory_grid, generation = _load_snapshot(snapshot_path)
    shape = lattice.shape
    N = shape[0]
    total_cells = lattice.size
    print(f"  Lattice: {N}x{N}x{N} ({total_cells:,} cells)")
    print(f"  Generation: {generation:,}")
    print()

    # Load rule spec
    rule_file = PROJECT_ROOT / "ca" / "rules" / "example.toml"
    rule_spec = load_rule_spec(str(rule_file))
    rng = np.random.default_rng(seed=42)

    # Extend memory grid if needed
    if memory_grid.shape[0] < 8:
        old_ch = memory_grid.shape[0]
        extended = init_memory_grid(shape)
        extended[:old_ch] = memory_grid
        memory_grid = extended

    inactivity = np.zeros_like(lattice, dtype=np.int16)

    # ── Component Benchmarks ──────────────────────────────────────────
    print("-" * 72)
    print("  COMPONENT BENCHMARKS (CPU)")
    print("-" * 72)

    # 1. count_neighbors_3d (CPU)
    # Force CPU mode temporarily
    import scripts.continuous_evolution_ca as ca_module
    # BOTH originals are read before EITHER is written. Reading `_xp` after
    # forcing `GPU_AVAILABLE = False` meant an engine without an `_xp`
    # attribute left the backend pinned to CPU on the way out of the
    # `AttributeError`.
    old_gpu = getattr(ca_module, 'GPU_AVAILABLE', False)
    old_xp = ca_module._xp
    ca_module.GPU_AVAILABLE = False
    ca_module._xp = np

    # Everything that runs under the forced-CPU backend lives inside this
    # `try`. The restore used to sit after the third benchmark on the success
    # path only, so any failure in a component, or in the CPU preparation
    # between them, left `scripts.continuous_evolution_ca` pinned to CPU for
    # the rest of the process -- module globals, so every later user of the
    # engine inherited it, including the GPU section immediately below.
    try:
        median_cpu_neighbors = benchmark_component(
            "count_neighbors_3d (CPU)",
            lambda: count_neighbors_3d(lattice),
            warmup=1, iterations=5
        )
        print(f"  count_neighbors_3d (CPU):     {median_cpu_neighbors:8.1f} ms")

        # 2. _separable_box_filter_3d
        test_field = np.random.rand(*shape).astype(np.float32)
        median_box_cpu = benchmark_component(
            "box_filter_3d R=12 (CPU)",
            lambda: _separable_box_filter_3d(test_field, radius=12),
            warmup=1, iterations=5
        )
        print(f"  box_filter_3d R=12 (CPU):     {median_box_cpu:8.1f} ms")

        # 3. _max_neighbor_value
        test_ages = memory_grid[0].copy()
        median_maxn_cpu = benchmark_component(
            "max_neighbor_value (CPU)",
            lambda: _max_neighbor_value(test_ages),
            warmup=1, iterations=5
        )
        print(f"  max_neighbor_value (CPU):     {median_maxn_cpu:8.1f} ms")
    finally:
        # Restore GPU state -- on every exit, not just the successful one. The
        # original exception is untouched: this clause neither swallows nor
        # replaces it.
        ca_module.GPU_AVAILABLE = old_gpu
        ca_module._xp = old_xp

    # 4. GPU versions of same components (if available)
    if GPU_AVAILABLE:
        print()
        print("-" * 72)
        print("  COMPONENT BENCHMARKS (GPU)")
        print("-" * 72)

        # count_neighbors_3d GPU
        median_gpu_neighbors = benchmark_component(
            "count_neighbors_3d (GPU)",
            lambda: count_neighbors_3d(lattice),
            warmup=2, iterations=5
        )
        speedup_n = median_cpu_neighbors / max(0.01, median_gpu_neighbors)
        print(f"  count_neighbors_3d (GPU):     {median_gpu_neighbors:8.1f} ms  ({speedup_n:.1f}x speedup)")

        # box_filter on GPU (pass GPU array directly)
        test_field_gpu = cp.asarray(test_field)
        median_box_gpu = benchmark_component(
            "box_filter_3d R=12 (GPU)",
            lambda: _separable_box_filter_3d(test_field_gpu, radius=12),
            warmup=1, iterations=3
        )
        speedup_b = median_box_cpu / max(0.01, median_box_gpu)
        print(f"  box_filter_3d R=12 (GPU):     {median_box_gpu:8.1f} ms  ({speedup_b:.1f}x speedup)")

    # ── Full Step Benchmark ───────────────────────────────────────────
    print()
    print("-" * 72)
    print(f"  FULL STEP BENCHMARK ({num_steps} steps)")
    print("-" * 72)

    # Make copies for benchmarking
    lat = lattice.copy()
    mem = memory_grid.copy()
    inact = inactivity.copy()

    step_times = []
    for i in range(num_steps):
        t = _timer()
        with t:
            lat, inact, mem, metrics = step_ca_lattice(
                lat, rule_spec, rng, inact, mem,
                current_gen=generation + i
            )
        step_times.append(t.elapsed * 1000)
        if i == 0:
            first_metrics = metrics

    step_times_arr = np.array(step_times)
    median_step = float(np.median(step_times_arr))
    mean_step = float(np.mean(step_times_arr))
    min_step = float(np.min(step_times_arr))
    max_step = float(np.max(step_times_arr))
    steps_per_sec = 1000.0 / median_step

    print(f"  Median step time:  {median_step:8.1f} ms")
    print(f"  Mean step time:    {mean_step:8.1f} ms")
    print(f"  Min step time:     {min_step:8.1f} ms")
    print(f"  Max step time:     {max_step:8.1f} ms")
    print(f"  Steps/second:      {steps_per_sec:8.2f}")
    print()
    print(f"  After {num_steps} steps:")
    print(f"    Entropy:         {first_metrics.get('entropy', 0):.4f}")
    print(f"    COMPUTE ratio:   {first_metrics.get('compute_ratio', 0):.4f}")
    print(f"    Max age:         {first_metrics.get('compute_max_age', 0):.1f}")
    print(f"    Signal active:   {first_metrics.get('signal_active', 0)}")

    # ── Summary ───────────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("  SUMMARY")
    print("=" * 72)
    print(f"  Lattice:           {N}³ = {total_cells:,} cells")
    print(f"  GPU:               {'ONLINE' if GPU_AVAILABLE else 'OFF'}")
    print(f"  Steps/second:      {steps_per_sec:.2f}")
    print(f"  Time per step:     {median_step:.0f} ms")
    print()
    component_total = median_cpu_neighbors + median_box_cpu + median_maxn_cpu
    print(f"  Component overhead (CPU):")
    print(f"    count_neighbors: {median_cpu_neighbors:6.0f} ms ({100*median_cpu_neighbors/median_step:.0f}%)")
    print(f"    box_filter R=12: {median_box_cpu:6.0f} ms ({100*median_box_cpu/median_step:.0f}%)")
    print(f"    max_neighbor:    {median_maxn_cpu:6.0f} ms ({100*median_maxn_cpu/median_step:.0f}%)")
    print(f"    other (masks, rng, memory): {median_step - component_total:.0f} ms ({100*(median_step - component_total)/median_step:.0f}%)")
    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(description="Phase 14a GPU Benchmark")
    parser.add_argument("--snapshot", type=str, default=None,
                        help="Path to .npz snapshot (default: latest in data/)")
    parser.add_argument("--steps", type=int, default=10,
                        help="Number of steps to benchmark (default: 10)")
    args = parser.parse_args()

    # Find snapshot
    if args.snapshot:
        snapshot_path = args.snapshot
    else:
        data_dir = PROJECT_ROOT / "data"
        snapshots = sorted(data_dir.glob("v070_gen*.npz"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not snapshots:
            print("ERROR: No snapshots found in data/")
            sys.exit(1)
        snapshot_path = str(snapshots[0])

    run_benchmarks(snapshot_path, args.steps)


if __name__ == "__main__":
    main()
