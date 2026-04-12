#!/usr/bin/env python3
"""Phase 14e: The Acoustic Map — Delta Tensor & Sector Chunking

Completely decoupled from the main CA engine (ProRL: separate "doing" from "monitoring").
Reads lattice state snapshots and produces a compressed 3D friction heatmap.

The Delta Tensor tracks state-change frequency per cell ("friction").
Sector Chunking compresses this into a lightweight macro-block grid.
The Acoustic Map is the output: where is the lattice struggling, where is it stable?

Concepts:
  - High friction (rapid state toggling) = Suffering = "low-frequency noise"
  - Low friction (stable Sages) = Equanimity = "silence"
  - The Watchdog/Gardeners listen to this map, not individual cells

Usage:
    from scripts.acoustic_map import AcousticMap
    amap = AcousticMap(lattice_size=256, sector_size=16)
    amap.update(current_state, previous_state)
    heatmap = amap.get_heatmap()  # 16x16x16 friction map
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field

import numpy as np

# GPU support — try multiple import paths
GPU_AVAILABLE = False
_xp = np
try:
    from scripts.gpu_accelerator import GPU_AVAILABLE as _ga
    GPU_AVAILABLE = _ga
except ImportError:
    try:
        from gpu_accelerator import GPU_AVAILABLE as _ga
        GPU_AVAILABLE = _ga
    except ImportError:
        pass

if GPU_AVAILABLE:
    import cupy as cp
    _xp = cp
else:
    try:
        import cupy as cp
        GPU_AVAILABLE = True
        _xp = cp
    except ImportError:
        pass


def _to_numpy(arr):
    """Convert GPU array to numpy if needed."""
    if GPU_AVAILABLE and hasattr(arr, 'get'):
        return arr.get()
    return arr


@dataclass
class AcousticMapConfig:
    """Configuration for the Acoustic Map."""
    sector_size: int = 16          # Each macro-block is 16x16x16
    friction_decay: float = 0.95   # Friction decays toward 0 each step
    output_interval: int = 100     # Output heatmap every N steps
    log_dir: str = "data"          # Where to save heatmap logs
    friction_threshold: float = 0.0   # Auto-calibrated: above p75 = "stressed"
    silent_threshold: float = 0.0    # Auto-calibrated: below p25 = "silent/Sage"
    auto_calibrate: bool = True      # Phase 17a: auto-calibrate thresholds from actual data


class AcousticMap:
    """The Acoustic Map: a compressed 3D friction heatmap of the lattice.

    Instead of monitoring 16.7 million cells individually, we divide the
    256³ lattice into 16³ macro-sectors and track aggregate friction per sector.
    This is Medusa's "radar" — the Watchdog listens to this, not individual cells.
    """

    def __init__(self, lattice_size: int = 256, config: Optional[AcousticMapConfig] = None):
        self.config = config or AcousticMapConfig()
        self.lattice_size = lattice_size
        self.sector_size = self.config.sector_size
        self.sectors_per_dim = lattice_size // self.sector_size

        # Delta tensor: tracks friction per cell (rolling, decays over time)
        # This is the FULL resolution grid but updated cheaply via state comparison
        xp = _xp
        self.delta_tensor = xp.zeros((lattice_size, lattice_size, lattice_size), dtype=xp.float32)

        # Previous state for delta comparison
        self.prev_state = None

        # The acoustic heatmap: compressed sector-level friction
        self.heatmap = np.zeros(
            (self.sectors_per_dim, self.sectors_per_dim, self.sectors_per_dim),
            dtype=np.float32,
        )

        # Statistics
        self.step_count = 0
        self.total_friction = 0.0
        self.max_sector_friction = 0.0
        self.stressed_sectors = 0
        self.silent_sectors = 0

        # History for trend analysis
        self.history = []
        self.max_history = 100

    def update(self, current_state, previous_state=None):
        """Update the delta tensor by comparing current state to previous.

        Args:
            current_state: The current lattice state (256³ uint8 array)
            previous_state: Optional explicit previous state. If None, uses cached.
        """
        xp = _xp

        def _ensure_device(arr):
            """Ensure array is on GPU if GPU available."""
            if GPU_AVAILABLE and isinstance(arr, np.ndarray):
                return cp.asarray(arr)
            return arr

        current = _ensure_device(current_state)

        if previous_state is not None:
            prev = _ensure_device(previous_state)
        elif self.prev_state is not None:
            prev = self.prev_state
        else:
            # First call — no previous state to compare
            self.prev_state = current.copy()
            self.step_count += 1
            return

        # Calculate delta: where did the state change?
        # A toggling cell adds +1 to its friction score
        # Force both to same xp to avoid CuPy/numpy mismatch
        if GPU_AVAILABLE:
            if isinstance(current, np.ndarray):
                current = cp.asarray(current)
            if isinstance(prev, np.ndarray):
                prev = cp.asarray(prev)
        changed = (current != prev).astype(xp.float32)

        # Decay existing friction, add new changes
        self.delta_tensor = self.delta_tensor * self.config.friction_decay + changed

        # Cache current state for next comparison
        self.prev_state = current.copy()
        self.step_count += 1

        # Periodically compute the compressed heatmap
        if self.step_count % self.config.output_interval == 0:
            self._compute_heatmap()

    def _compute_heatmap(self):
        """Compress the delta tensor into a sector-level heatmap.

        Uses reshape + mean to efficiently average friction within each
        16x16x16 macro-block. This is the "Sector Chunking" operation.

        On GPU: ~0.1ms for 256³ → 16³ compression.
        """
        xp = _xp
        N = self.lattice_size
        S = self.sector_size
        K = self.sectors_per_dim  # N // S

        # Reshape into (K, S, K, S, K, S) then mean over the S dimensions
        # This gives us the average friction per macro-block
        reshaped = self.delta_tensor.reshape(K, S, K, S, K, S)
        sector_means = reshaped.mean(axis=(1, 3, 5))

        if GPU_AVAILABLE:
            cp.cuda.Stream.null.synchronize()

        # Convert to numpy for the heatmap output
        self.heatmap = _to_numpy(sector_means).astype(np.float32)

        # Phase 17a: Auto-calibrate thresholds from actual data distribution
        if self.config.auto_calibrate and self.heatmap.size > 0:
            flat = self.heatmap.flatten()
            self.config.friction_threshold = float(np.percentile(flat, 75))  # Top 25% = stressed
            self.config.silent_threshold = float(np.percentile(flat, 25))    # Bottom 25% = silent

        # Update statistics
        self.total_friction = float(self.heatmap.sum())
        self.max_sector_friction = float(self.heatmap.max())
        self.stressed_sectors = int((self.heatmap > self.config.friction_threshold).sum())
        self.silent_sectors = int((self.heatmap < self.config.silent_threshold).sum())

        # Record history
        self.history.append({
            "step": self.step_count,
            "total_friction": self.total_friction,
            "max_sector": self.max_sector_friction,
            "stressed": self.stressed_sectors,
            "silent": self.silent_sectors,
            "timestamp": time.time(),
        })
        if len(self.history) > self.max_history:
            self.history.pop(0)

    def get_heatmap(self) -> np.ndarray:
        """Get the current sector-level friction heatmap (16x16x16 numpy array)."""
        return self.heatmap

    def get_stressed_sectors(self) -> list:
        """Get coordinates of sectors with high friction (suffering zones)."""
        stressed = np.argwhere(self.heatmap > self.config.friction_threshold)
        return [(int(x), int(y), int(z)) for x, y, z in stressed]

    def get_silent_sectors(self) -> list:
        """Get coordinates of sectors with near-zero friction (Sage domains)."""
        silent = np.argwhere(self.heatmap < self.config.silent_threshold)
        return [(int(x), int(y), int(z)) for x, y, z in silent]

    def get_stats(self) -> Dict:
        """Get current acoustic statistics."""
        return {
            "step": self.step_count,
            "total_friction": self.total_friction,
            "max_sector_friction": self.max_sector_friction,
            "stressed_sectors": self.stressed_sectors,
            "silent_sectors": self.silent_sectors,
            "total_sectors": self.sectors_per_dim ** 3,
            "equanimity_ratio": self.silent_sectors / max(1, self.sectors_per_dim ** 3),
        }

    def get_trend(self) -> Dict:
        """Analyze friction trends over recent history."""
        if len(self.history) < 2:
            return {"trend": "insufficient_data"}

        recent = self.history[-10:]
        older = self.history[-20:-10] if len(self.history) >= 20 else self.history[:len(self.history)//2]

        if not older:
            return {"trend": "insufficient_data"}

        recent_friction = np.mean([h["total_friction"] for h in recent])
        older_friction = np.mean([h["total_friction"] for h in older])

        recent_stressed = np.mean([h["stressed"] for h in recent])
        older_stressed = np.mean([h["stressed"] for h in older])

        delta = recent_friction - older_friction
        if delta > older_friction * 0.1:
            trend = "INCREASING_FRICTION"
        elif delta < -older_friction * 0.1:
            trend = "DECREASING_FRICTION"
        else:
            trend = "STABLE"

        return {
            "trend": trend,
            "friction_delta": float(delta),
            "recent_avg_friction": float(recent_friction),
            "older_avg_friction": float(older_friction),
            "recent_avg_stressed": float(recent_stressed),
            "older_avg_stressed": float(older_stressed),
        }

    def save_heatmap(self, path: Optional[str] = None):
        """Save the current heatmap as JSON for visualization."""
        if path is None:
            path = str(Path(self.config.log_dir) / f"acoustic_map_step{self.step_count}.json")

        data = {
            "step": self.step_count,
            "lattice_size": self.lattice_size,
            "sector_size": self.sector_size,
            "sectors_per_dim": self.sectors_per_dim,
            "stats": self.get_stats(),
            "trend": self.get_trend(),
            # Flatten heatmap for JSON serialization
            "heatmap": self.heatmap.flatten().tolist(),
            "stressed_sectors": self.get_stressed_sectors()[:20],  # Top 20
            "silent_sectors_count": self.silent_sectors,
        }

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        return path

    def print_summary(self):
        """Print a human-readable summary of the acoustic state."""
        stats = self.get_stats()
        trend = self.get_trend()
        total = stats["total_sectors"]

        print(f"  ACOUSTIC MAP (step {self.step_count})")
        print(f"    Sectors: {self.sectors_per_dim}x{self.sectors_per_dim}x{self.sectors_per_dim} = {total}")
        print(f"    Total friction:  {stats['total_friction']:.2f}")
        print(f"    Max sector:      {stats['max_sector_friction']:.4f}")
        print(f"    Stressed:        {stats['stressed_sectors']} / {total} ({100*stats['stressed_sectors']/total:.1f}%)")
        print(f"    Silent (Sage):   {stats['silent_sectors']} / {total} ({100*stats['silent_sectors']/total:.1f}%)")
        print(f"    Equanimity:      {stats['equanimity_ratio']:.1%}")
        if trend["trend"] != "insufficient_data":
            print(f"    Trend:           {trend['trend']} (delta={trend['friction_delta']:.2f})")


# ---------------------------------------------------------------------------
# Standalone diagnostic: run on a snapshot
# ---------------------------------------------------------------------------
def run_acoustic_diagnostic(snapshot_path: str, num_steps: int = 200):
    """Run acoustic analysis on a snapshot by simulating N steps."""
    from scripts.continuous_evolution_ca import step_ca_lattice, load_rule_spec, init_memory_grid

    print(f"Loading snapshot: {snapshot_path}")
    snap = np.load(snapshot_path, allow_pickle=True)
    lattice = snap["lattice"]
    memory_grid = snap["memory_grid"]
    gen = int(snap["generation"])
    N = lattice.shape[0]

    if memory_grid.shape[0] < 8:
        ext = init_memory_grid(lattice.shape)
        ext[:memory_grid.shape[0]] = memory_grid
        memory_grid = ext

    rule_spec = load_rule_spec(str(Path(__file__).parent.parent / "ca" / "rules" / "example.toml"))
    rng = np.random.default_rng(42)
    inactivity = np.zeros_like(lattice, dtype=np.int16)

    # Create acoustic map
    amap = AcousticMap(lattice_size=N, config=AcousticMapConfig(output_interval=10))

    print(f"Running {num_steps} steps at {N}³ with acoustic monitoring...")
    for i in range(num_steps):
        prev = lattice.copy() if not GPU_AVAILABLE else lattice
        lattice, inactivity, memory_grid, metrics = step_ca_lattice(
            lattice, rule_spec, rng, inactivity, memory_grid, gen + i
        )
        amap.update(lattice, prev)

        if (i + 1) % 50 == 0:
            print(f"\n  Step {i+1}/{num_steps}:")
            amap.print_summary()

    print("\nFinal Acoustic Report:")
    amap.print_summary()

    # Save heatmap
    path = amap.save_heatmap()
    print(f"\nHeatmap saved: {path}")

    return amap


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        snapshot = sys.argv[1]
    else:
        # Find latest snapshot
        data_dir = Path(__file__).parent.parent / "data"
        snapshots = sorted(data_dir.glob("v070_gen*.npz"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not snapshots:
            print("No snapshots found!")
            sys.exit(1)
        snapshot = str(snapshots[0])

    steps = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    run_acoustic_diagnostic(snapshot, steps)
