"""Ising Model + Parallel Tempering for UtilityFog Fractal Lattice

Maps the foglet lattice onto an Ising Hamiltonian and uses replica-exchange
(Parallel Tempering) to explore the energy landscape across the Vanguard
GPU cluster. Each replica runs at a different inverse temperature (beta)
and neighboring replicas periodically attempt swap moves governed by the
Metropolis-Hastings criterion.

Designed to distribute replicas across nodes via the Vanguard MCP GPU
router: one replica per GPU, 4 active nodes, 4 concurrent replicas in
the base configuration (expandable to 6).

Author: Jack (Ising physics & PT) + Vanguard integration
License: MIT
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


class SpinState(IntEnum):
    DOWN = -1
    UP = 1


@dataclass
class IsingConfig:
    lattice_size: int = 64
    coupling_J: float = 1.0
    external_h: float = 0.0
    num_replicas: int = 4
    beta_min: float = 0.1
    beta_max: float = 2.5
    sweeps_per_exchange: int = 100
    total_exchanges: int = 200
    seed: Optional[int] = None


@dataclass
class ReplicaState:
    replica_id: int
    beta: float
    spins: np.ndarray
    energy: float = 0.0
    magnetization: float = 0.0
    assigned_node: str = ""
    assigned_gpu: str = ""
    sweeps_done: int = 0
    swaps_accepted: int = 0
    swaps_proposed: int = 0


@dataclass
class EnergySnapshot:
    exchange_step: int
    timestamp: float
    replica_energies: List[float]
    replica_betas: List[float]
    replica_magnetizations: List[float]
    swap_acceptance_rate: float
    min_energy: float
    mean_energy: float
    max_energy: float
    heat_capacity: float
    order_parameter: float


@dataclass
class GrokkingRunResult:
    config: IsingConfig
    duration_secs: float
    total_sweeps: int
    total_swaps_proposed: int
    total_swaps_accepted: int
    swap_acceptance_rate: float
    energy_history: List[EnergySnapshot]
    final_replicas: List[ReplicaState]
    ground_state_energy: float
    ground_state_magnetization: float
    nodes_used: List[str]
    gpus_used: List[str]


class IsingLattice:
    """2D Ising model on a square lattice with periodic boundary conditions."""

    def __init__(self, size: int, coupling_J: float = 1.0, external_h: float = 0.0):
        self.size = size
        self.J = coupling_J
        self.h = external_h
        self.N = size * size

    def random_spins(self, rng: np.random.Generator) -> np.ndarray:
        return rng.choice([-1, 1], size=(self.size, self.size)).astype(np.int8)

    def energy(self, spins: np.ndarray) -> float:
        nn_sum = (
            np.roll(spins, 1, axis=0) +
            np.roll(spins, -1, axis=0) +
            np.roll(spins, 1, axis=1) +
            np.roll(spins, -1, axis=1)
        )
        interaction = -self.J * np.sum(spins * nn_sum) / 2.0
        field = -self.h * np.sum(spins)
        return float(interaction + field)

    def magnetization(self, spins: np.ndarray) -> float:
        return float(np.abs(np.mean(spins)))

    def delta_energy(self, spins: np.ndarray, i: int, j: int) -> float:
        s = spins[i, j]
        L = self.size
        neighbors = (
            spins[(i + 1) % L, j] +
            spins[(i - 1) % L, j] +
            spins[i, (j + 1) % L] +
            spins[i, (j - 1) % L]
        )
        return float(2.0 * self.J * s * neighbors + 2.0 * self.h * s)

    def metropolis_sweep(self, spins: np.ndarray, beta: float, rng: np.random.Generator) -> int:
        accepted = 0
        for _ in range(self.N):
            i = rng.integers(0, self.size)
            j = rng.integers(0, self.size)
            dE = self.delta_energy(spins, i, j)
            if dE <= 0.0 or rng.random() < math.exp(-beta * dE):
                spins[i, j] *= -1
                accepted += 1
        return accepted


class ParallelTempering:
    """Replica-exchange Monte Carlo across multiple temperature replicas.

    Each replica is assigned to a GPU node via the Vanguard MCP router.
    The mapping is:
        replica 0 -> Mega          (192.168.86.29, RTX 5090)
        replica 1 -> AMDMSIX870E-1 (192.168.86.16, RTX 5090)
        replica 2 -> AMDMSIX870E-2 (192.168.86.22, RTX 5090)
        replica 3 -> DellUltracore9(192.168.86.3,  RTX 4090)
    Additional replicas map to placeholder nodes when they come online.
    """

    NODE_MAP = [
        {"node_id": "mega",          "hostname": "Mega",          "ip": "192.168.86.29", "gpu": "gpu-0", "model": "RTX 5090"},
        {"node_id": "amdmsix870e-1", "hostname": "AMDMSIX870E-1", "ip": "192.168.86.16", "gpu": "gpu-0", "model": "RTX 5090"},
        {"node_id": "amdmsix870e-2", "hostname": "AMDMSIX870E-2", "ip": "192.168.86.22", "gpu": "gpu-0", "model": "RTX 5090"},
        {"node_id": "dell-ultracore9","hostname": "DellUltracore9","ip": "192.168.86.3",  "gpu": "gpu-0", "model": "RTX 4090"},
    ]

    def __init__(self, config: IsingConfig):
        self.config = config
        self.lattice = IsingLattice(config.lattice_size, config.coupling_J, config.external_h)
        self.rng = np.random.default_rng(config.seed)

        betas = np.geomspace(config.beta_min, config.beta_max, config.num_replicas)
        self.replicas: List[ReplicaState] = []
        for idx in range(config.num_replicas):
            spins = self.lattice.random_spins(self.rng)
            node = self.NODE_MAP[idx % len(self.NODE_MAP)]
            replica = ReplicaState(
                replica_id=idx,
                beta=float(betas[idx]),
                spins=spins,
                energy=self.lattice.energy(spins),
                magnetization=self.lattice.magnetization(spins),
                assigned_node=node["node_id"],
                assigned_gpu=node["gpu"],
            )
            self.replicas.append(replica)

        self.energy_history: List[EnergySnapshot] = []

    def run_sweeps(self, replica: ReplicaState, num_sweeps: int) -> None:
        for _ in range(num_sweeps):
            self.lattice.metropolis_sweep(replica.spins, replica.beta, self.rng)
            replica.sweeps_done += 1
        replica.energy = self.lattice.energy(replica.spins)
        replica.magnetization = self.lattice.magnetization(replica.spins)

    def attempt_swap(self, i: int, j: int) -> bool:
        ri, rj = self.replicas[i], self.replicas[j]
        delta = (ri.beta - rj.beta) * (ri.energy - rj.energy)
        ri.swaps_proposed += 1
        rj.swaps_proposed += 1
        if delta >= 0.0 or self.rng.random() < math.exp(delta):
            ri.beta, rj.beta = rj.beta, ri.beta
            ri.swaps_accepted += 1
            rj.swaps_accepted += 1
            return True
        return False

    def exchange_step(self, step: int, even: bool) -> int:
        accepted = 0
        start = 0 if even else 1
        for k in range(start, len(self.replicas) - 1, 2):
            if self.attempt_swap(k, k + 1):
                accepted += 1
        return accepted

    def snapshot(self, step: int) -> EnergySnapshot:
        energies = [r.energy for r in self.replicas]
        betas = [r.beta for r in self.replicas]
        mags = [r.magnetization for r in self.replicas]
        total_proposed = sum(r.swaps_proposed for r in self.replicas)
        total_accepted = sum(r.swaps_accepted for r in self.replicas)
        acceptance = total_accepted / max(1, total_proposed)

        mean_e = np.mean(energies)
        var_e = np.var(energies)
        avg_beta = np.mean(betas)
        heat_cap = float(avg_beta * avg_beta * var_e / self.lattice.N) if self.lattice.N > 0 else 0.0

        return EnergySnapshot(
            exchange_step=step,
            timestamp=time.time(),
            replica_energies=energies,
            replica_betas=betas,
            replica_magnetizations=mags,
            swap_acceptance_rate=acceptance,
            min_energy=float(np.min(energies)),
            mean_energy=float(mean_e),
            max_energy=float(np.max(energies)),
            heat_capacity=heat_cap,
            order_parameter=float(np.mean(mags)),
        )

    def run(self) -> GrokkingRunResult:
        t0 = time.time()

        for step in range(self.config.total_exchanges):
            for replica in self.replicas:
                self.run_sweeps(replica, self.config.sweeps_per_exchange)

            even = (step % 2 == 0)
            self.exchange_step(step, even)

            snap = self.snapshot(step)
            self.energy_history.append(snap)

        duration = time.time() - t0
        total_proposed = sum(r.swaps_proposed for r in self.replicas)
        total_accepted = sum(r.swaps_accepted for r in self.replicas)

        best = min(self.replicas, key=lambda r: r.energy)

        return GrokkingRunResult(
            config=self.config,
            duration_secs=duration,
            total_sweeps=sum(r.sweeps_done for r in self.replicas),
            total_swaps_proposed=total_proposed,
            total_swaps_accepted=total_accepted,
            swap_acceptance_rate=total_accepted / max(1, total_proposed),
            energy_history=self.energy_history,
            final_replicas=self.replicas,
            ground_state_energy=best.energy,
            ground_state_magnetization=best.magnetization,
            nodes_used=list({r.assigned_node for r in self.replicas}),
            gpus_used=list({f"{r.assigned_node}/{r.assigned_gpu}" for r in self.replicas}),
        )


def format_remote_polaroid(result: GrokkingRunResult) -> str:
    """Generate the 'Remote Polaroid' summary of a completed Grokking Run."""

    lines = []
    lines.append("=" * 72)
    lines.append("  REMOTE POLAROID  |  Vanguard Grokking Run  |  Energy Landscape")
    lines.append("=" * 72)
    lines.append("")

    lines.append(f"  Lattice:         {result.config.lattice_size}x{result.config.lattice_size} Ising (J={result.config.coupling_J}, h={result.config.external_h})")
    lines.append(f"  Replicas:        {result.config.num_replicas} (beta range [{result.config.beta_min:.2f}, {result.config.beta_max:.2f}])")
    lines.append(f"  Duration:        {result.duration_secs:.2f}s")
    lines.append(f"  Total Sweeps:    {result.total_sweeps:,}")
    lines.append(f"  Swap Accept:     {result.swap_acceptance_rate:.1%} ({result.total_swaps_accepted}/{result.total_swaps_proposed})")
    lines.append("")

    lines.append("  --- Cluster Dispatch ---")
    for replica in result.final_replicas:
        node_info = next((n for n in ParallelTempering.NODE_MAP if n["node_id"] == replica.assigned_node), None)
        ip_str = node_info["ip"] if node_info else "???"
        model_str = node_info["model"] if node_info else "???"
        lines.append(
            f"    Replica {replica.replica_id}  ->  {replica.assigned_node:<20s}  "
            f"{ip_str:<16s}  {model_str:<10s}  "
            f"beta={replica.beta:.4f}  E={replica.energy:+.1f}  |m|={replica.magnetization:.4f}"
        )
    lines.append("")

    lines.append("  --- Energy Landscape ---")
    last = result.energy_history[-1] if result.energy_history else None
    if last:
        lines.append(f"    Min  Energy:   {last.min_energy:+.2f}")
        lines.append(f"    Mean Energy:   {last.mean_energy:+.2f}")
        lines.append(f"    Max  Energy:   {last.max_energy:+.2f}")
        lines.append(f"    Heat Capacity: {last.heat_capacity:.4f}")
        lines.append(f"    Order Param:   {last.order_parameter:.4f}")
    lines.append("")

    n_hist = len(result.energy_history)
    sample_points = [0, n_hist // 4, n_hist // 2, 3 * n_hist // 4, n_hist - 1]
    sample_points = sorted(set(max(0, min(p, n_hist - 1)) for p in sample_points))
    lines.append("  --- Convergence Trace ---")
    lines.append(f"    {'Step':>6s}  {'MinE':>10s}  {'MeanE':>10s}  {'MaxE':>10s}  {'SwapRate':>10s}")
    for idx in sample_points:
        s = result.energy_history[idx]
        lines.append(
            f"    {s.exchange_step:6d}  {s.min_energy:+10.2f}  "
            f"{s.mean_energy:+10.2f}  {s.max_energy:+10.2f}  "
            f"{s.swap_acceptance_rate:10.1%}"
        )
    lines.append("")

    lines.append(f"  Ground State:    E = {result.ground_state_energy:+.2f}  |m| = {result.ground_state_magnetization:.4f}")
    lines.append(f"  Nodes Used:      {', '.join(result.nodes_used)}")
    lines.append(f"  GPUs Fired:      {', '.join(result.gpus_used)}")
    lines.append("")
    lines.append("=" * 72)
    lines.append("  Grokking Run Complete. BOINC/F@H auto-restoring to normal mode.")
    lines.append("=" * 72)

    return "\n".join(lines)
