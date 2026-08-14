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

# This module is documented as `python scripts/geometry_daemon.py`, which
# leaves the repository root off sys.path. The shared snapshot guard lives in
# the `scripts` package, so the root is put on the path before importing it --
# one canonical module name either way, which matters because the guard's
# exception type is caught by identity below.
if str(PROJECT_ROOT) not in sys.path:
    # Appended, not prepended: this must not be able to shadow a standard
    # library module with a repository file of the same name.
    sys.path.append(str(PROJECT_ROOT))

from scripts.snapshot_archive_guard import (  # noqa: E402
    PRODUCTION_POLICY as SNAPSHOT_POLICY,
)
from scripts.snapshot_archive_guard import (  # noqa: E402
    SnapshotArchiveRejected,
    admit_snapshot,
    entry_fingerprint,
    newest_first,
)

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
# Snapshot loading
# ---------------------------------------------------------------------------

def _load_snapshot(path):
    """Return (state, memory_grid, generation) with the archive already closed.

    Both load sites previously did `snap = np.load(...)` and then kept the
    returned `NpzFile` referenced in the calling frame — through the whole
    export stage in the daemon, and until process teardown in `--once`. The
    archive's underlying file handle therefore stayed open far longer than the
    extraction needed, which on Windows can block cleanup, rotation or
    replacement of that snapshot.

    The `with` block bounds the archive's lifetime to the extraction itself:
    the three values are materialised as real in-memory objects while the
    archive is open, and it is closed before this function returns — so the
    potentially long-running exporters never hold the input handle. Closure is
    explicit, not left to garbage collection or interpreter shutdown.

    Extraction failures are NOT caught, translated or suppressed: a missing key
    or a failing `int()` conversion propagates exactly as before, and the `with`
    block still closes the archive on the way out.

    The `str(path)` conversion is NOT preserved: it was deliberately replaced
    by same-descriptor loading, described below.

    `allow_pickle=False` — an object-dtype member is stored as a pickle, so
    loading one with pickle enabled is arbitrary code execution. This daemon
    loads unattended from a watched directory, so a file dropped into `data/`
    would be unpickled with nobody present; NumPy now refuses such a member
    with a `ValueError` instead. Passed explicitly although it is already
    NumPy's default, because relying on a default makes the property invisible
    at the call site and silently reversible upstream. There is deliberately
    no fallback retry and no override.

    The claim here is an OBJECT-MEMBER REFUSAL plus archive resource lifetime
    — not deterministic export or atomic output.

    Structural admission
    --------------------
    `admit_snapshot` now runs first and raises `SnapshotArchiveRejected`
    before `np.load`, its decompressor or its allocator is reached, for an
    archive that is out of the data directory, not a ZIP, wrong in its
    membership, hostile in its member names, oversized in its declared or
    physical size, or wrong in any member's NPY header. Both call sites — the
    daemon loop and `--once` — catch that type and stop before any exporter
    runs.

    The guard opens the file once and hands this helper the very descriptor it
    preflighted, so the bytes inspected are the bytes NumPy reads. `str(path)`
    is therefore gone: there is no second open to convert a path for. The
    inner `with` closes the archive, the guard closes the descriptor, on
    success and on every exceptional exit.

    Extraction failures are still NOT caught, translated or suppressed: a
    missing key or a failing `int()` conversion propagates exactly as before.

    `allow_pickle=False` stays at this call site even though an object-dtype
    member can no longer survive admission. It is the second line of defence
    and the property the repository-wide static gate reads.
    """
    with admit_snapshot(path, data_dir=DATA_DIR, policy=SNAPSHOT_POLICY) as descriptor:
        with np.load(descriptor, allow_pickle=False) as snap:
            state = snap["lattice"]
            memory_grid = snap["memory_grid"]
            generation = int(snap["generation"])
    return state, memory_grid, generation


def _snapshot_fingerprint(path):
    """Identify a snapshot by the attributes that change when it changes.

    A rejected archive is remembered by this triple so the daemon neither logs
    nor retries it on every poll, while a genuinely new file at the same path
    — a replaced or rotated snapshot — differs in size or modification time
    and is admitted for a fresh attempt.

    Non-following: `stat` described a symlink's TARGET, so a rejected link kept
    changing fingerprint whenever anything touched the target, and the daemon
    re-preflighted and re-logged the same unchanged poison on every poll — the
    exact churn the memory exists to stop.
    """
    return entry_fingerprint(path)


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
    last_rejected = None

    while True:
        try:
            # Find latest snapshot. Non-following ordering that also drops
            # entries vanishing mid-enumeration: `p.stat()` followed symlinks,
            # so a link could borrow its target's mtime to become "newest"
            # before admission had any say, and it raised OSError into the
            # broad handler below, whose message carries the path.
            snapshots = newest_first(DATA_DIR.glob("v070_gen*.npz"))

            if not snapshots:
                time.sleep(WATCH_INTERVAL)
                continue

            latest = snapshots[0]

            # Skip if same as last time or too soon
            if latest == last_snapshot:
                time.sleep(WATCH_INTERVAL)
                continue

            # An unchanged archive that was already refused is skipped in
            # silence: no repeated reason-code log, no repeated preflight, no
            # export attempt. A file that CHANGES at the same path has a
            # different fingerprint and gets a fresh attempt.
            try:
                fingerprint = _snapshot_fingerprint(latest)
            except OSError:
                # The file was rotated or deleted between the glob above and
                # this stat. Letting that escape would reach the broad handler
                # at the bottom of the loop, which prints the exception — and
                # OSError's message carries the full path, which is a name the
                # attacker chose. Nothing to do but look again next poll.
                time.sleep(WATCH_INTERVAL)
                continue

            if fingerprint == last_rejected:
                time.sleep(WATCH_INTERVAL)
                continue

            if time.time() - last_export_time < EXPORT_INTERVAL:
                time.sleep(WATCH_INTERVAL)
                continue

            # The former one-megabyte minimum is gone. It was a guess at
            # "tiny/corrupt" and it was wrong in both directions: a sparse but
            # structurally valid snapshot compresses to far less and was
            # skipped, while a hostile archive only had to be padded past the
            # threshold to be processed. Admission decides usability instead.

            # Load snapshot. The archive is closed inside the helper, so it is
            # already released before any exporter below runs.
            try:
                state, mg, gen = _load_snapshot(latest)
            except SnapshotArchiveRejected as refusal:
                # One bounded reason code. Nothing about the archive's path,
                # name, members or headers is logged, because this daemon runs
                # unattended over a directory anyone able to write there can
                # fill.
                print(f"  [GEO] Snapshot rejected: {refusal.reason}")
                last_rejected = fingerprint
                time.sleep(WATCH_INTERVAL)
                continue

            # Logged only once the archive has been admitted, so a refused
            # file's chosen name never reaches the log at all.
            print(f"\n  [GEO] New snapshot: {latest.name}")

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


def run_once():
    """Single export from the latest snapshot — the `--once` production path.

    Split out of the `__main__` block, which pytest never executes, so the
    refusal contract is reachable by a test rather than restated by one: a
    rejected archive prints exactly one bounded reason on stderr and exits
    nonzero, with no exporter having run. The body is otherwise the block that
    was here before, unchanged.
    """
    snapshots = newest_first(DATA_DIR.glob("v070_gen*.npz"))
    if not snapshots:
        print("No snapshots found!")
        return

    try:
        state, mg, gen = _load_snapshot(snapshots[0])
    except SnapshotArchiveRejected as refusal:
        # Exactly one bounded reason on stderr, then a nonzero exit. Only the
        # typed refusal is caught here: a MemoryError, a KeyboardInterrupt or
        # a programmer error must not be turned into "the snapshot was bad".
        print(f"Snapshot rejected: {refusal.reason}", file=sys.stderr)
        sys.exit(1)

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
        run_once()
    else:
        run_daemon()
