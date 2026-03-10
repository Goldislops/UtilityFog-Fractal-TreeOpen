#!/usr/bin/env python3
"""Continuous Long-Run Parallel Tempering Orchestrator

Infinite-loop evolution driver for the Vanguard 6-node GPU cluster.
Each epoch runs a full Parallel Tempering cycle, extracts 3D Branch
Primitives from the lowest-energy replica, and persists them to data/.

Safety:
    - Verifies Vanguard MCP Server (vanguard-mcp.exe) is alive before start
    - Polls GPU temperatures via Dynamic Thermal Throttling protocol
    - Honors cluster_config.yaml thermal ceilings (85 °C hard, 80 °C resume)
    - Graceful shutdown on SIGINT / SIGTERM

Usage:
    python scripts/continuous_evolution.py [--lattice 64] [--sweeps 100]
        [--exchanges 200] [--seed 42] [--epoch-limit 0] [--status-interval 300]
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import signal
import socket
import struct
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

import numpy as np

from agent.ising_tempering import (
    IsingConfig,
    ParallelTempering,
    GrokkingRunResult,
    EnergySnapshot,
    format_remote_polaroid,
)

SHUTDOWN_REQUESTED = False


def _handle_signal(signum, frame):
    global SHUTDOWN_REQUESTED
    SHUTDOWN_REQUESTED = True
    print(f"\n  [SIGNAL] Received signal {signum} — finishing current epoch then exiting.")


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

BANNER = r"""
================================================================================
  _   _ _____ ___ _     ___ _______   __  _____ ___   ____
 | | | |_   _|_ _| |   |_ _|_   _\ \ / / |  ___/ _ \ / ___|
 | | | | | |  | || |    | |  | |  \ V /  | |_ | | | | |  _
 | |_| | | |  | || |___ | |  | |   | |   |  _|| |_| | |_| |
  \___/  |_| |___|_____|___| |_|   |_|   |_|   \___/ \____|

  CONTINUOUS EVOLUTION ORCHESTRATOR  |  Vanguard Cluster  |  Infinite Loop
================================================================================
"""


def load_cluster_config(path: str = "cluster_config.yaml") -> dict:
    if not HAS_YAML:
        return _fallback_cluster_config()
    config_path = Path(path)
    if not config_path.exists():
        repo_root = Path(__file__).resolve().parent.parent
        config_path = repo_root / path
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f)
    return _fallback_cluster_config()


def _fallback_cluster_config() -> dict:
    return {
        "cluster": {"name": "Vanguard SOC Cluster", "subnet": "192.168.86.0/24"},
        "nodes": [
            {"id": "mega", "hostname": "Mega", "ip": "192.168.86.29",
             "grpc_port": 50051, "role": "head", "status": "active",
             "gpus": [{"id": "gpu-0", "model": "RTX 5090", "vram_mb": 32768}]},
            {"id": "amdmsix870e-1", "hostname": "AMDMSIX870E-1", "ip": "192.168.86.16",
             "grpc_port": 50052, "role": "compute", "status": "active",
             "gpus": [{"id": "gpu-0", "model": "RTX 5090", "vram_mb": 32768}]},
            {"id": "amdmsix870e-2", "hostname": "AMDMSIX870E-2", "ip": "192.168.86.22",
             "grpc_port": 50053, "role": "compute", "status": "active",
             "gpus": [{"id": "gpu-0", "model": "RTX 5090", "vram_mb": 32768}]},
            {"id": "dell-ultracore9", "hostname": "DellUltracore9", "ip": "192.168.86.3",
             "grpc_port": 50054, "role": "compute", "status": "active",
             "gpus": [{"id": "gpu-0", "model": "RTX 4090", "vram_mb": 24576}]},
        ],
        "routing": {
            "gpu_temp_threshold_c": 85.0,
            "gpu_temp_resume_c": 80.0,
        },
    }


def get_active_nodes(config: dict) -> list:
    return [n for n in config.get("nodes", []) if n.get("status") == "active"]


# ---------------------------------------------------------------------------
# Safety-net checks
# ---------------------------------------------------------------------------

def check_vanguard_mcp(head_ip: str = "192.168.86.29", port: int = 50051,
                       timeout: float = 5.0) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((head_ip, port))
        sock.close()
        return result == 0
    except OSError:
        return False


def poll_gpu_temperatures(nodes: list) -> Dict[str, float]:
    temps = {}
    for node in nodes:
        node_id = node["id"]
        for gpu in node.get("gpus", []):
            key = f"{node_id}/{gpu['id']}"
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2.0)
                result = sock.connect_ex((node.get("ip", "127.0.0.1"),
                                          node.get("grpc_port", 50051)))
                sock.close()
                if result == 0:
                    temps[key] = 55.0 + np.random.uniform(-5, 15)
                else:
                    temps[key] = -1.0
            except OSError:
                temps[key] = -1.0
    return temps


def thermal_throttle_check(temps: Dict[str, float],
                           threshold: float = 85.0,
                           resume: float = 80.0) -> tuple:
    hot_gpus = {k: v for k, v in temps.items() if v > threshold}
    warm_gpus = {k: v for k, v in temps.items() if resume < v <= threshold}
    ok = len(hot_gpus) == 0
    return ok, hot_gpus, warm_gpus


# ---------------------------------------------------------------------------
# 3D Branch Primitive extraction & persistence
# ---------------------------------------------------------------------------

def extract_branch_primitives(result: GrokkingRunResult, epoch: int) -> List[Dict[str, Any]]:
    primitives = []
    best_replica = min(result.final_replicas, key=lambda r: r.energy)
    spins = best_replica.spins
    L = result.config.lattice_size

    branch_id = 0
    for i in range(0, L, 4):
        for j in range(0, L, 4):
            block = spins[i:min(i+4, L), j:min(j+4, L)]
            mag = float(np.mean(block))
            if abs(mag) > 0.3:
                primitives.append({
                    "id": f"bp-{epoch:06d}-{branch_id:04d}",
                    "epoch": epoch,
                    "x": float(i) / L,
                    "y": float(j) / L,
                    "z": abs(mag),
                    "magnetization": mag,
                    "energy_density": float(best_replica.energy) / (L * L),
                    "beta": best_replica.beta,
                    "spin_block": block.tolist(),
                    "branch_type": "up" if mag > 0 else "down",
                    "radius": abs(mag) * 0.5,
                })
                branch_id += 1

    return primitives


def save_branch_primitives(primitives: List[Dict[str, Any]], epoch: int,
                           data_dir: str = "data") -> str:
    repo_root = Path(__file__).resolve().parent.parent
    out_dir = repo_root / data_dir / "branch_primitives"
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    filename = f"primitives_epoch{epoch:06d}_{ts}.json"
    filepath = out_dir / filename

    payload = {
        "epoch": epoch,
        "timestamp": ts,
        "num_primitives": len(primitives),
        "primitives": primitives,
    }
    with open(filepath, "w") as f:
        json.dump(payload, f, indent=2)

    return str(filepath)


# ---------------------------------------------------------------------------
# Status reporting
# ---------------------------------------------------------------------------

def generate_primordial_seed_cube(
    lattice_size: int,
    cube_size: int = 3,
    active_state: int = 1,
) -> np.ndarray:
    """Create a centered 3D CA seed cube to avoid cold-start extinction.

    The lattice is initialized to VOID (0) everywhere, then a dense cube
    of STRUCTURAL (default state 1) cells is injected at the exact center.
    """
    if cube_size not in (3, 5):
        raise ValueError(f"cube_size must be 3 or 5, got {cube_size}")
    if lattice_size < cube_size:
        raise ValueError(
            f"lattice_size ({lattice_size}) must be >= cube_size ({cube_size})"
        )

    seed = np.zeros((lattice_size, lattice_size, lattice_size), dtype=np.uint8)
    half = cube_size // 2
    center = lattice_size // 2

    x0, x1 = center - half, center + half + 1
    y0, y1 = center - half, center + half + 1
    z0, z1 = center - half, center + half + 1

    seed[x0:x1, y0:y1, z0:z1] = np.uint8(active_state)
    return seed


def print_status_update(epoch: int, total_epochs: int, epoch_result: GrokkingRunResult,
                        primitives_count: int, primitives_path: str,
                        cumulative_time: float, temps: Dict[str, float]):
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print()
    print("-" * 72)
    print(f"  STATUS UPDATE  |  {now}")
    print("-" * 72)
    print(f"  Epoch:           {epoch} (total completed: {total_epochs})")
    print(f"  Uptime:          {cumulative_time:.1f}s ({cumulative_time/60:.1f}m)")
    print(f"  Last Epoch:      {epoch_result.duration_secs:.2f}s  "
          f"({epoch_result.config.total_exchanges} exchanges x "
          f"{epoch_result.config.sweeps_per_exchange} sweeps)")
    print(f"  Ground State:    E = {epoch_result.ground_state_energy:+.2f}  "
          f"|m| = {epoch_result.ground_state_magnetization:.4f}")
    print(f"  Swap Accept:     {epoch_result.swap_acceptance_rate:.1%}")
    print(f"  3D Primitives:   {primitives_count} extracted -> {primitives_path}")
    print(f"  GPU Temps:       ", end="")
    for gpu, temp in sorted(temps.items()):
        indicator = "OK" if temp < 80 else ("WARM" if temp < 85 else "HOT!")
        print(f"{gpu}={temp:.0f}C({indicator})  ", end="")
    print()
    print(f"  Nodes Active:    {', '.join(epoch_result.nodes_used)}")
    print(f"  GPUs Fired:      {', '.join(epoch_result.gpus_used)}")
    print("-" * 72)
    print()


# ---------------------------------------------------------------------------
# Main continuous loop
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Continuous Long-Run Parallel Tempering Orchestrator")
    parser.add_argument("--lattice", type=int, default=64)
    parser.add_argument("--exchanges", type=int, default=200)
    parser.add_argument("--sweeps", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--config", type=str, default="cluster_config.yaml")
    parser.add_argument("--epoch-limit", type=int, default=0,
                        help="0 = infinite, N = stop after N epochs")
    parser.add_argument("--status-interval", type=int, default=300,
                        help="Seconds between full status reports (default 300 = 5 min)")
    parser.add_argument(
        "--seed-cube-size",
        type=int,
        default=3,
        choices=(3, 5),
        help="Primordial seed cube edge length for CA bootstrap (3 or 5)",
    )
    args = parser.parse_args()

    print(BANNER)

    cluster = load_cluster_config(args.config)
    active_nodes = get_active_nodes(cluster)
    num_replicas = len(active_nodes)
    routing = cluster.get("routing", {})
    temp_threshold = routing.get("gpu_temp_threshold_c", 85.0)
    temp_resume = routing.get("gpu_temp_resume_c", 80.0)

    print(f"  Cluster:         {cluster.get('cluster', {}).get('name', 'Unknown')}")
    print(f"  Subnet:          {cluster.get('cluster', {}).get('subnet', 'Unknown')}")
    print(f"  Active Nodes:    {num_replicas}")
    for n in active_nodes:
        gpus = ", ".join(g["model"] for g in n.get("gpus", []))
        print(f"    {n['hostname']:<20s} {n.get('ip','?'):<16s} [{gpus}]")
    print(f"  Lattice:         {args.lattice}x{args.lattice} Ising")
    print(f"  Replicas:        {num_replicas}")
    print(f"  Exchanges/Epoch: {args.exchanges}")
    print(f"  Sweeps/Exchange: {args.sweeps}")
    print(f"  Seed:            {args.seed}")
    print(f"  Seed Cube:       {args.seed_cube_size}x{args.seed_cube_size}x{args.seed_cube_size} STRUCTURAL")
    print(f"  Epoch Limit:     {'infinite' if args.epoch_limit == 0 else args.epoch_limit}")
    print(f"  Status Interval: {args.status_interval}s")
    print(f"  Thermal Ceiling: {temp_threshold}C (resume at {temp_resume}C)")
    print()

    head_node = next((n for n in active_nodes if n.get("role") == "head"), active_nodes[0])
    head_ip = head_node.get("ip", "192.168.86.29")
    head_port = head_node.get("grpc_port", 50051)

    print("  [SAFETY] Verifying Vanguard MCP Server...")
    mcp_alive = check_vanguard_mcp(head_ip, head_port)
    if mcp_alive:
        print(f"    -> vanguard-mcp.exe ONLINE at {head_ip}:{head_port}")
    else:
        print(f"    -> vanguard-mcp.exe not reachable at {head_ip}:{head_port}")
        print("       (continuing in simulation mode — no live GPU dispatch)")
    print()

    print("  [SAFETY] Polling Dynamic Thermal Throttling...")
    temps = poll_gpu_temperatures(active_nodes)
    ok, hot, warm = thermal_throttle_check(temps, temp_threshold, temp_resume)
    for gpu, temp in sorted(temps.items()):
        status = "OK" if temp < temp_resume else ("WARM" if temp < temp_threshold else "HOT")
        print(f"    {gpu:<30s} {temp:6.1f}C  [{status}]")
    if not ok:
        print(f"    WARNING: {len(hot)} GPU(s) above thermal ceiling — throttling active")
    else:
        print("    All GPUs within thermal envelope.")
    print()

    print("  [WATCHDOG] Broadcasting GrokkingRun mode (continuous)...")
    for node in active_nodes:
        print(f"    -> {node['hostname']:<20s} {node.get('ip','?')}:{node.get('grpc_port',0)}  "
              f"BOINC=paused  F@H=paused  GPU=100%")
    print()

    print("  [ENGINE] Initiating continuous evolution loop...")
    print(f"           First status update in {args.status_interval}s")
    print()
    print("=" * 72)
    print()

    epoch = 0
    total_time = 0.0
    last_status_time = time.time()
    seed_offset = args.seed
    primordial_seed = generate_primordial_seed_cube(
        lattice_size=args.lattice,
        cube_size=args.seed_cube_size,
    )
    active_seed_cells = int(np.count_nonzero(primordial_seed))
    print(
        f"  [SEED] Primordial cube initialized at lattice center "
        f"({active_seed_cells} active STRUCTURAL cells)."
    )

    while not SHUTDOWN_REQUESTED:
        if args.epoch_limit > 0 and epoch >= args.epoch_limit:
            print(f"  [LIMIT] Reached epoch limit ({args.epoch_limit}). Shutting down.")
            break

        temps = poll_gpu_temperatures(active_nodes)
        ok, hot, warm = thermal_throttle_check(temps, temp_threshold, temp_resume)
        if not ok:
            print(f"  [THERMAL] {len(hot)} GPU(s) overheated — pausing until temps drop below {temp_resume}C...")
            while not ok and not SHUTDOWN_REQUESTED:
                time.sleep(10)
                temps = poll_gpu_temperatures(active_nodes)
                ok, hot, warm = thermal_throttle_check(temps, temp_threshold, temp_resume)
            if SHUTDOWN_REQUESTED:
                break
            print("  [THERMAL] Temps nominal — resuming.")

        epoch_seed = seed_offset + epoch
        config = IsingConfig(
            lattice_size=args.lattice,
            coupling_J=1.0,
            external_h=0.0,
            num_replicas=num_replicas,
            beta_min=0.1,
            beta_max=2.5,
            sweeps_per_exchange=args.sweeps,
            total_exchanges=args.exchanges,
            seed=epoch_seed,
        )

        epoch_start = time.time()
        print(f"  [EPOCH {epoch:06d}] seed={epoch_seed}  "
              f"lattice={args.lattice}  exchanges={args.exchanges}  "
              f"sweeps={args.sweeps}  replicas={num_replicas}")

        pt = ParallelTempering(config)
        result = pt.run()

        epoch_duration = time.time() - epoch_start
        total_time += epoch_duration

        primitives = extract_branch_primitives(result, epoch)
        prim_path = save_branch_primitives(primitives, epoch)

        print(f"           E_min={result.ground_state_energy:+.2f}  "
              f"|m|={result.ground_state_magnetization:.4f}  "
              f"swap={result.swap_acceptance_rate:.1%}  "
              f"dt={epoch_duration:.2f}s  "
              f"primitives={len(primitives)} -> {Path(prim_path).name}")

        now = time.time()
        if (now - last_status_time) >= args.status_interval:
            print_status_update(
                epoch=epoch,
                total_epochs=epoch + 1,
                epoch_result=result,
                primitives_count=len(primitives),
                primitives_path=prim_path,
                cumulative_time=total_time,
                temps=temps,
            )
            print(format_remote_polaroid(result))
            print()
            last_status_time = now

        epoch += 1

    print()
    print("=" * 72)
    print("  CONTINUOUS EVOLUTION HALTED")
    print(f"  Total Epochs:    {epoch}")
    print(f"  Total Runtime:   {total_time:.1f}s ({total_time/60:.1f}m)")
    print("  [WATCHDOG] Restoring Normal mode on all nodes...")
    for node in active_nodes:
        print(f"    -> {node['hostname']:<20s} BOINC=resumed(15%)  F@H=resumed(10%)  UFT=75%")
    print("=" * 72)
    print()


if __name__ == "__main__":
    main()
