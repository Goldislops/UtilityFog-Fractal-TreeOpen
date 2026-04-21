#!/usr/bin/env python3
"""Phase 16a: Medusa REST API — Frictionless Gravity Well

A lightweight Flask server that exposes Medusa's live telemetry,
snapshots, acoustic heatmap, and magnon field stats via REST endpoints.

Runs alongside the engine and watchdog without port conflicts.
Future cluster nodes can connect to donate compute.

Endpoints:
  GET /api/status          — Current engine status (gen, uptime, GPU)
  GET /api/telemetry       — Latest telemetry metrics
  GET /api/census          — Cell state census from latest snapshot
  GET /api/equanimity      — Equanimity/Sage census
  GET /api/acoustic        — Acoustic heatmap (16³ sector friction)
  GET /api/snapshot/latest — Download latest .npz snapshot
  GET /api/geometry/stl    — Export latest organism as STL
  GET /api/health          — Simple health check

Usage:
  python scripts/medusa_api.py [--port 8080]
"""

from __future__ import annotations

import glob
import json
import os
import sys
import time
from pathlib import Path
from threading import Thread

import numpy as np
from flask import Flask, jsonify, send_file, Response

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
API_PORT = 8080
API_HOST = "0.0.0.0"  # Listen on all interfaces for cluster access

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_latest_snapshot():
    """Find the most recent .npz snapshot."""
    snapshots = sorted(
        DATA_DIR.glob("v070_gen*.npz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    # Skip tiny/corrupt files (< 10 MB for 256³)
    for s in snapshots:
        if s.stat().st_size > 1_000_000:
            return s
    return snapshots[0] if snapshots else None


def _load_snapshot(path):
    """Load a snapshot and return (state, memory_grid, gen, fitness)."""
    snap = np.load(str(path), allow_pickle=True)
    return (
        snap["lattice"],
        snap["memory_grid"],
        int(snap["generation"]),
        float(snap["best_fitness"]),
    )


def _read_engine_log():
    """Read the latest status from the engine stdout log."""
    log_path = DATA_DIR / "v070_gpu_stdout.log"
    if not log_path.exists():
        return None
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        # Find the last STATUS block
        for i in range(len(lines) - 1, -1, -1):
            if "STATUS @" in lines[i]:
                return "".join(lines[i:min(i + 20, len(lines))])
        return lines[-5:] if lines else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/health")
def health():
    """Simple health check."""
    return jsonify({"status": "ok", "service": "medusa-api", "timestamp": time.time()})


@app.route("/api/status")
def status():
    """Current engine status."""
    snap_path = _find_latest_snapshot()
    if not snap_path:
        return jsonify({"error": "No snapshots found"}), 404

    snap_age = time.time() - snap_path.stat().st_mtime
    snap_size = snap_path.stat().st_size

    # Count total snapshots
    all_snaps = list(DATA_DIR.glob("v070_gen*.npz"))

    return jsonify({
        "latest_snapshot": snap_path.name,
        "snapshot_age_seconds": round(snap_age, 1),
        "snapshot_size_mb": round(snap_size / 1024 / 1024, 1),
        "total_snapshots": len(all_snaps),
        "engine_alive": snap_age < 900,  # 15 min threshold
        "api_port": API_PORT,
    })


@app.route("/api/telemetry")
def telemetry():
    """Latest telemetry from the engine log."""
    # Find latest telemetry JSON
    telem_files = sorted(
        DATA_DIR.glob("telemetry_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not telem_files:
        return jsonify({"error": "No telemetry files found"}), 404

    with open(telem_files[0]) as f:
        data = json.load(f)

    data["_source"] = telem_files[0].name
    return jsonify(data)


@app.route("/api/census")
def census():
    """Cell state census from latest snapshot."""
    snap_path = _find_latest_snapshot()
    if not snap_path:
        return jsonify({"error": "No snapshots found"}), 404

    state, mg, gen, fitness = _load_snapshot(snap_path)
    N = state.shape[0]
    total = state.size

    names = ["VOID", "STRUCTURAL", "COMPUTE", "ENERGY", "SENSOR"]
    unique, counts = np.unique(state, return_counts=True)
    count_dict = {names[int(u)]: int(c) for u, c in zip(unique, counts) if u < 5}
    non_void = total - count_dict.get("VOID", 0)

    # Entropy
    nv = state[state > 0]
    if len(nv) > 0:
        nv_u, nv_c = np.unique(nv, return_counts=True)
        probs = nv_c / nv_c.sum()
        entropy = float(-np.sum(probs * np.log(probs)) / np.log(4))
    else:
        entropy = 0.0

    return jsonify({
        "generation": gen,
        "lattice_size": N,
        "total_cells": total,
        "non_void": non_void,
        "non_void_pct": round(100 * non_void / total, 1),
        "states": count_dict,
        "entropy": round(entropy, 4),
        "fitness": round(fitness, 4),
        "snapshot": snap_path.name,
    })


@app.route("/api/equanimity")
def equanimity():
    """Equanimity/Sage census from latest snapshot."""
    snap_path = _find_latest_snapshot()
    if not snap_path:
        return jsonify({"error": "No snapshots found"}), 404

    state, mg, gen, fitness = _load_snapshot(snap_path)

    compute_mask = state == 2
    ages = mg[0][compute_mask]

    if len(ages) == 0:
        return jsonify({"generation": gen, "error": "No COMPUTE cells"})

    # Find top 5 elders with coordinates
    N = state.shape[0]
    flat_compute = np.where(compute_mask.flatten())[0]
    flat_ages = mg[0].flatten()[flat_compute]
    top5_idx = np.argsort(flat_ages)[-5:][::-1]

    top_elders = []
    for ti in top5_idx:
        fi = flat_compute[ti]
        x, y, z = fi % N, (fi // N) % N, fi // (N * N)
        top_elders.append({
            "age": float(flat_ages[ti]),
            "coords": [int(x), int(y), int(z)],
            "energy": float(mg[3].flatten()[fi]),
            "memory": float(mg[2].flatten()[fi]),
        })

    return jsonify({
        "generation": gen,
        "total_compute": int(compute_mask.sum()),
        "shielded_age3": int((ages > 3).sum()),
        "veterans_age5": int((ages > 5).sum()),
        "sages_age8": int((ages >= 8).sum()),
        "ancients_age20": int((ages >= 20).sum()),
        "legends_age50": int((ages >= 50).sum()),
        "centennial_age100": int((ages >= 100).sum()),
        "max_age": float(ages.max()),
        "median_age": float(np.median(ages)),
        "mean_age": round(float(ages.mean()), 1),
        "p95_age": float(np.percentile(ages, 95)),
        "p99_age": float(np.percentile(ages, 99)),
        "top_elders": top_elders,
    })


@app.route("/api/acoustic")
def acoustic():
    """Acoustic heatmap — 16³ sector friction map."""
    # Check if we have a saved acoustic map
    acoustic_files = sorted(
        DATA_DIR.glob("acoustic_map_step*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if acoustic_files:
        with open(acoustic_files[0]) as f:
            return jsonify(json.load(f))

    # Generate from latest snapshot (sector comparison)
    snap_path = _find_latest_snapshot()
    if not snap_path:
        return jsonify({"error": "No data available"}), 404

    state, mg, gen, _ = _load_snapshot(snap_path)
    N = state.shape[0]
    S = 16
    K = N // S

    # Simple: compute per-sector state diversity as friction proxy
    reshaped = state.reshape(K, S, K, S, K, S)
    sector_diversity = np.zeros((K, K, K), dtype=np.float32)
    for sz in range(K):
        for sy in range(K):
            for sx in range(K):
                block = reshaped[sz, :, sy, :, sx, :]
                unique_states = len(np.unique(block))
                sector_diversity[sz, sy, sx] = unique_states / 5.0

    return jsonify({
        "generation": gen,
        "sectors_per_dim": K,
        "total_sectors": K ** 3,
        "heatmap": sector_diversity.flatten().tolist(),
        "mean_diversity": round(float(sector_diversity.mean()), 4),
        "max_diversity": round(float(sector_diversity.max()), 4),
    })


@app.route("/api/snapshot/latest")
def snapshot_latest():
    """Download the latest .npz snapshot."""
    snap_path = _find_latest_snapshot()
    if not snap_path:
        return jsonify({"error": "No snapshots found"}), 404
    return send_file(str(snap_path), as_attachment=True)


@app.route("/api/geometry/stl")
def geometry_stl():
    """Export latest organism geometry as STL (non-void cells as cubes)."""
    try:
        import trimesh
    except ImportError:
        return jsonify({"error": "trimesh not installed"}), 500

    snap_path = _find_latest_snapshot()
    if not snap_path:
        return jsonify({"error": "No snapshots found"}), 404

    state, mg, gen, _ = _load_snapshot(snap_path)

    # Sample non-void cells (limit to 50K for reasonable STL size)
    non_void_coords = np.argwhere(state > 0)
    if len(non_void_coords) > 50000:
        indices = np.random.choice(len(non_void_coords), 50000, replace=False)
        non_void_coords = non_void_coords[indices]

    if len(non_void_coords) == 0:
        return jsonify({"error": "No non-void cells"}), 404

    # Create a mesh from voxel positions
    meshes = []
    box = trimesh.primitives.Box(extents=[0.9, 0.9, 0.9])
    for z, y, x in non_void_coords:
        m = box.copy()
        m.apply_translation([float(x), float(y), float(z)])
        meshes.append(m)

    combined = trimesh.util.concatenate(meshes)

    # Export to temp file
    stl_path = DATA_DIR / f"medusa_gen{gen}_geometry.stl"
    combined.export(str(stl_path))

    return send_file(str(stl_path), as_attachment=True)


# ---------------------------------------------------------------------------
# Phase 18 PR 2 + PR 3: Tuning API Blueprint + Event Bus
# ---------------------------------------------------------------------------
# PR 2 adds the write-side tuning endpoints (propose/commit/rollback).
# PR 3 adds a ZMQ PUB event stream on :8081 and a StateWatcher that
# broadcasts telemetry.5min events when new telemetry files appear.
# See scripts/tuning_api.py, scripts/event_bus.py, and PHASE_18.md.

import os as _os
import re as _re

from scripts.tuning_api import TuningState as _TuningState
from scripts.tuning_api import create_blueprint as _create_tuning_blueprint
from scripts.event_bus import EventPublisher as _EventPublisher
from scripts.event_bus import StateWatcher as _StateWatcher


def _infer_current_gen_from_snapshot() -> int:
    """Extract generation number from the latest snapshot's filename.
    Returns 0 if no snapshot is found or the filename is unparseable."""
    snap = _find_latest_snapshot()
    if snap is None:
        return 0
    m = _re.search(r"gen(\d+)", snap.name)
    return int(m.group(1)) if m else 0


# Event bus — PUB socket + telemetry file watcher. Disabled when running
# under pytest (MEDUSA_EVENT_BUS_DISABLED=1) to avoid port conflicts in CI.
_event_publisher = None
_state_watcher = None
if _os.environ.get("MEDUSA_EVENT_BUS_DISABLED") != "1":
    try:
        _event_publisher = _EventPublisher("tcp://*:8081")
        _state_watcher = _StateWatcher(_event_publisher, DATA_DIR, poll_interval_s=15.0)
        _state_watcher.start()
    except Exception as _e:
        # Non-fatal: REST API still works even if the event bus is down.
        print(f"[event_bus] disabled ({_e}); REST endpoints remain available")
        _event_publisher = None
        _state_watcher = None


_tuning_state = _TuningState(
    data_dir=DATA_DIR,
    gen_getter=_infer_current_gen_from_snapshot,
    event_publisher=_event_publisher,
)
app.register_blueprint(_create_tuning_blueprint(_tuning_state))


@app.route("/")
def index():
    """API documentation."""
    return jsonify({
        "service": "Medusa REST API (Phase 16a + Phase 18 PRs 2+3)",
        "version": "1.2.0",
        "endpoints": {
            "/api/health": "Health check",
            "/api/status": "Engine status",
            "/api/telemetry": "Latest telemetry",
            "/api/census": "Cell state census",
            "/api/equanimity": "Sage/Elder census",
            "/api/acoustic": "Acoustic heatmap (16³)",
            "/api/snapshot/latest": "Download latest .npz",
            "/api/geometry/stl": "Export STL geometry",
            "/api/params": "GET — current effective tunable parameters",
            "/api/params/schema": "GET — tunable parameter schema (types, bounds, categories)",
            "/api/tuning/propose": "POST — propose a tuning (dry-run by default)",
            "/api/tuning/commit": "POST — commit a proposal (gated by approver policy + rate limit)",
            "/api/tuning/rollback": "POST — revert to a prior committed proposal",
        },
        "event_bus": {
            "zmq_pub_endpoint": "tcp://<host>:8081" if _event_publisher else None,
            "topics": [
                "tuning.committed", "tuning.rejected", "tuning.rolled_back",
                "telemetry.5min",
            ],
            "state_watcher": bool(_state_watcher),
        },
        "cluster_subnet": "192.168.86.0/24",
        "note": "Future cluster nodes can connect to donate compute",
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Medusa REST API (Phase 16a)")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()

    print("=" * 60)
    print("  MEDUSA REST API — Phase 16a")
    print(f"  http://{args.host}:{args.port}/")
    print(f"  Cluster access: http://192.168.86.29:{args.port}/")
    print("=" * 60)

    app.run(host=args.host, port=args.port, debug=False, threaded=True)
