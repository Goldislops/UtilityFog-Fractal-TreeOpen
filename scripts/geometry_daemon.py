#!/usr/bin/env python3
"""Phase 16b: Geometry Export Daemon — Physical Substrate Pipeline

Watches for new Medusa snapshots and automatically exports:
  1. STL mesh (for 3D printing)
  2. Point cloud CSV (Sage positions for analysis)
  3. Voxel slices (PNG layers for volumetric printing)

The geometry is banked and ready for the moment physical hardware connects.
This is the bridge from digital simulation to physical Utility Foglets.

Usage:
  python scripts/geometry_daemon.py [--watch-interval 60] [--max-cells 50000]
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
GEO_DIR = DATA_DIR / "geometry"
GEO_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WATCH_INTERVAL = 60       # seconds between checks
MAX_CELLS_STL = 50000     # max cells for STL export (memory limit)
MAX_CELLS_CSV = 100000    # max cells for CSV point cloud
SAGE_AGE_MIN = 8.0        # minimum age for Sage point cloud
EXPORT_INTERVAL = 3600    # export geometry at most once per hour


# ---------------------------------------------------------------------------
# Exporters
# ---------------------------------------------------------------------------

def export_sage_pointcloud(state, memory_grid, gen, output_dir):
    """Export Sage positions as CSV point cloud.

    Format: x, y, z, age, energy, memory_strength, state
    Ready for visualization in CloudCompare, Blender, or Omniverse.
    """
    N = state.shape[0]
    compute_mask = state == 2
    sage_mask = compute_mask & (memory_grid[0] >= SAGE_AGE_MIN)

    coords = np.argwhere(sage_mask)
    if len(coords) == 0:
        return None

    # Limit to MAX_CELLS_CSV
    if len(coords) > MAX_CELLS_CSV:
        indices = np.random.choice(len(coords), MAX_CELLS_CSV, replace=False)
        coords = coords[indices]

    # Gather per-cell data
    rows = []
    for z, y, x in coords:
        age = float(memory_grid[0, z, y, x])
        energy = float(memory_grid[3, z, y, x])
        memory = float(memory_grid[2, z, y, x])
        s = int(state[z, y, x])
        rows.append(f"{x},{y},{z},{age:.1f},{energy:.3f},{memory:.3f},{s}")

    csv_path = output_dir / f"sages_gen{gen}.csv"
    with open(csv_path, "w") as f:
        f.write("x,y,z,age,energy,memory_strength,state\n")
        f.write("\n".join(rows))

    return csv_path


def export_stl(state, gen, output_dir):
    """Export non-void cells as STL mesh using trimesh.

    Each non-void cell becomes a small cube. Limited to MAX_CELLS_STL
    for reasonable file sizes.
    """
    try:
        import trimesh
    except ImportError:
        print("  [GEO] trimesh not installed, skipping STL export")
        return None

    non_void = np.argwhere(state > 0)
    if len(non_void) == 0:
        return None

    # Sample if too many
    if len(non_void) > MAX_CELLS_STL:
        # Prefer Sage/Compute cells
        compute_coords = np.argwhere(state == 2)
        other_coords = np.argwhere((state > 0) & (state != 2))

        n_compute = min(len(compute_coords), MAX_CELLS_STL * 3 // 4)
        n_other = min(len(other_coords), MAX_CELLS_STL - n_compute)

        if n_compute < len(compute_coords):
            compute_coords = compute_coords[
                np.random.choice(len(compute_coords), n_compute, replace=False)
            ]
        if n_other < len(other_coords):
            other_coords = other_coords[
                np.random.choice(len(other_coords), n_other, replace=False)
            ]

        non_void = np.vstack([compute_coords, other_coords])

    # Build mesh from voxel positions
    box = trimesh.primitives.Box(extents=[0.9, 0.9, 0.9])
    meshes = []
    for z, y, x in non_void:
        m = box.copy()
        m.apply_translation([float(x), float(y), float(z)])
        meshes.append(m)

    combined = trimesh.util.concatenate(meshes)
    stl_path = output_dir / f"medusa_gen{gen}.stl"
    combined.export(str(stl_path))

    return stl_path


def export_voxel_summary(state, memory_grid, gen, output_dir):
    """Export a compact JSON summary of the organism geometry.

    Includes: bounding box, centroid, state ratios, Sage clusters.
    This is the lightweight "seed" that a printer controller would read.
    """
    N = state.shape[0]
    non_void_coords = np.argwhere(state > 0)

    if len(non_void_coords) == 0:
        return None

    center = N // 2
    centroid = non_void_coords.mean(axis=0).tolist()
    bbox_min = non_void_coords.min(axis=0).tolist()
    bbox_max = non_void_coords.max(axis=0).tolist()

    # State counts
    names = ["VOID", "STRUCTURAL", "COMPUTE", "ENERGY", "SENSOR"]
    unique, counts = np.unique(state, return_counts=True)
    state_counts = {names[int(u)]: int(c) for u, c in zip(unique, counts) if u < 5}

    # Sage stats
    compute_mask = state == 2
    ages = memory_grid[0][compute_mask]
    sage_count = int((ages >= SAGE_AGE_MIN).sum()) if len(ages) > 0 else 0
    max_age = float(ages.max()) if len(ages) > 0 else 0

    summary = {
        "generation": gen,
        "lattice_size": N,
        "non_void_cells": int(len(non_void_coords)),
        "centroid": [round(c, 1) for c in centroid],
        "bounding_box": {
            "min": [int(b) for b in bbox_min],
            "max": [int(b) for b in bbox_max],
        },
        "states": state_counts,
        "sages": sage_count,
        "max_age": round(max_age, 1),
        "timestamp": datetime.now().isoformat(),
        "export_format": "voxel_summary_v1",
    }

    json_path = output_dir / f"geometry_summary_gen{gen}.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)

    return json_path


# ---------------------------------------------------------------------------
# Daemon Loop
# ---------------------------------------------------------------------------

def run_daemon():
    """Watch for new snapshots and auto-export geometry."""
    print("=" * 60)
    print("  GEOMETRY EXPORT DAEMON — Phase 16b")
    print(f"  Output: {GEO_DIR}")
    print(f"  Watch interval: {WATCH_INTERVAL}s")
    print(f"  Export interval: {EXPORT_INTERVAL}s (max 1/hour)")
    print("=" * 60)

    last_export_time = 0
    last_snapshot = None

    while True:
        try:
            # Find latest snapshot
            snapshots = sorted(
                DATA_DIR.glob("v070_gen*.npz"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )

            if not snapshots:
                time.sleep(WATCH_INTERVAL)
                continue

            latest = snapshots[0]

            # Skip if same as last time or too soon
            if latest == last_snapshot:
                time.sleep(WATCH_INTERVAL)
                continue

            if time.time() - last_export_time < EXPORT_INTERVAL:
                time.sleep(WATCH_INTERVAL)
                continue

            # Skip tiny/corrupt files
            if latest.stat().st_size < 1_000_000:
                time.sleep(WATCH_INTERVAL)
                continue

            print(f"\n  [GEO] New snapshot: {latest.name}")

            # Load snapshot
            snap = np.load(str(latest), allow_pickle=True)
            state = snap["lattice"]
            mg = snap["memory_grid"]
            gen = int(snap["generation"])

            # Export geometry
            t0 = time.time()

            # 1. Sage point cloud (CSV)
            csv_path = export_sage_pointcloud(state, mg, gen, GEO_DIR)
            if csv_path:
                print(f"  [GEO] Sage point cloud: {csv_path.name}")

            # 2. Voxel summary (JSON)
            json_path = export_voxel_summary(state, mg, gen, GEO_DIR)
            if json_path:
                print(f"  [GEO] Geometry summary: {json_path.name}")

            # 3. STL mesh (only if trimesh available)
            stl_path = export_stl(state, gen, GEO_DIR)
            if stl_path:
                size_mb = stl_path.stat().st_size / 1024 / 1024
                print(f"  [GEO] STL mesh: {stl_path.name} ({size_mb:.1f} MB)")

            elapsed = time.time() - t0
            print(f"  [GEO] Export completed in {elapsed:.1f}s")

            last_export_time = time.time()
            last_snapshot = latest

        except KeyboardInterrupt:
            print("\n  [GEO] Daemon shutting down")
            break
        except Exception as e:
            print(f"  [GEO] Error: {e}")

        time.sleep(WATCH_INTERVAL)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Geometry Export Daemon (Phase 16b)")
    parser.add_argument("--watch-interval", type=int, default=60)
    parser.add_argument("--export-interval", type=int, default=3600)
    parser.add_argument("--once", action="store_true", help="Export once and exit")
    args = parser.parse_args()

    WATCH_INTERVAL = args.watch_interval
    EXPORT_INTERVAL = args.export_interval

    if args.once:
        # Single export from latest snapshot
        snapshots = sorted(
            DATA_DIR.glob("v070_gen*.npz"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if snapshots:
            snap = np.load(str(snapshots[0]), allow_pickle=True)
            state = snap["lattice"]
            mg = snap["memory_grid"]
            gen = int(snap["generation"])

            print(f"Exporting geometry for gen {gen:,}...")

            csv = export_sage_pointcloud(state, mg, gen, GEO_DIR)
            if csv:
                print(f"  Sage CSV: {csv}")

            js = export_voxel_summary(state, mg, gen, GEO_DIR)
            if js:
                print(f"  Summary: {js}")

            stl = export_stl(state, gen, GEO_DIR)
            if stl:
                print(f"  STL: {stl} ({stl.stat().st_size / 1024 / 1024:.1f} MB)")

            print("Done!")
        else:
            print("No snapshots found!")
    else:
        run_daemon()
