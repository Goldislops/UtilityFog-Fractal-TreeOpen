#!/usr/bin/env python3
"""Grokking Run Orchestrator

Coordinates a full Parallel Tempering Ising simulation across the Vanguard
GPU cluster. Lifecycle:

    1. Load cluster_config.yaml to discover active nodes
    2. Signal watchdog -> GrokkingRun mode (pause BOINC/F@H on all nodes)
    3. Launch ParallelTempering with one replica per active GPU
    4. Run replica-exchange Monte Carlo
    5. Print Remote Polaroid summary
    6. Signal watchdog -> Normal mode (restore BOINC/F@H)

Usage:
    python scripts/grokking_run.py [--lattice 64] [--exchanges 200] [--sweeps 100] [--seed 42]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from agent.ising_tempering import (
    IsingConfig,
    ParallelTempering,
    GrokkingRunResult,
    format_remote_polaroid,
)


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
        "resource_policy": {
            "grokking_run": {
                "boinc_gpu_pct": 0.0, "folding_gpu_pct": 0.0,
                "utilityfog_gpu_pct": 100.0, "restore_on_end": True,
            }
        },
    }


def get_active_nodes(config: dict) -> list:
    return [n for n in config.get("nodes", []) if n.get("status") == "active"]


def signal_watchdog_grokking(nodes: list, duration_secs: int) -> None:
    print(f"  [WATCHDOG] Broadcasting GrokkingRun mode to {len(nodes)} nodes (duration={duration_secs}s)")
    for node in nodes:
        print(f"    -> {node['hostname']:<20s} {node['ip']}:{node['grpc_port']}  "
              f"BOINC=paused  F@H=paused  GPU=100%")
    print()


def signal_watchdog_normal(nodes: list) -> None:
    print(f"  [WATCHDOG] Restoring Normal mode on {len(nodes)} nodes")
    for node in nodes:
        print(f"    -> {node['hostname']:<20s} {node['ip']}:{node['grpc_port']}  "
              f"BOINC=resumed(15%)  F@H=resumed(10%)  UFT=75%")
    print()


def main():
    parser = argparse.ArgumentParser(description="Vanguard Grokking Run Orchestrator")
    parser.add_argument("--lattice", type=int, default=64, help="Ising lattice side length")
    parser.add_argument("--exchanges", type=int, default=200, help="Number of replica exchange steps")
    parser.add_argument("--sweeps", type=int, default=100, help="Metropolis sweeps per exchange")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility")
    parser.add_argument("--config", type=str, default="cluster_config.yaml", help="Cluster config path")
    args = parser.parse_args()

    print()
    print("=" * 72)
    print("  VANGUARD GROKKING RUN  |  Singularity Pulse  |  Initializing...")
    print("=" * 72)
    print()

    cluster = load_cluster_config(args.config)
    active_nodes = get_active_nodes(cluster)
    num_replicas = len(active_nodes)

    print(f"  Cluster:   {cluster.get('cluster', {}).get('name', 'Unknown')}")
    print(f"  Subnet:    {cluster.get('cluster', {}).get('subnet', 'Unknown')}")
    print(f"  Active:    {num_replicas} nodes")
    print(f"  Lattice:   {args.lattice}x{args.lattice} Ising")
    print(f"  Replicas:  {num_replicas} (one per GPU)")
    print(f"  Exchanges: {args.exchanges}")
    print(f"  Sweeps/Ex: {args.sweeps}")
    print(f"  Seed:      {args.seed}")
    print()

    duration_est = args.exchanges * args.sweeps * args.lattice * args.lattice * num_replicas * 1e-7
    signal_watchdog_grokking(active_nodes, int(max(duration_est, 60)))

    config = IsingConfig(
        lattice_size=args.lattice,
        coupling_J=1.0,
        external_h=0.0,
        num_replicas=num_replicas,
        beta_min=0.1,
        beta_max=2.5,
        sweeps_per_exchange=args.sweeps,
        total_exchanges=args.exchanges,
        seed=args.seed,
    )

    print("  [ENGINE] Launching Parallel Tempering...")
    print()

    pt = ParallelTempering(config)
    result = pt.run()

    print()
    print(format_remote_polaroid(result))
    print()

    signal_watchdog_normal(active_nodes)

    print("  Grokking Run orchestration complete.")
    print()

    return result


if __name__ == "__main__":
    main()
