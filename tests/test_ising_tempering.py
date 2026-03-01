"""Tests for agent/ising_tempering.py — Ising physics and Parallel Tempering."""

import math
import numpy as np
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.ising_tempering import (
    IsingConfig,
    IsingLattice,
    ParallelTempering,
    ReplicaState,
    SpinState,
    format_remote_polaroid,
)


class TestIsingLattice:

    def test_random_spins_shape(self):
        lattice = IsingLattice(8)
        rng = np.random.default_rng(0)
        spins = lattice.random_spins(rng)
        assert spins.shape == (8, 8)
        assert set(np.unique(spins)) <= {-1, 1}

    def test_energy_all_up(self):
        lattice = IsingLattice(4, coupling_J=1.0, external_h=0.0)
        spins = np.ones((4, 4), dtype=np.int8)
        E = lattice.energy(spins)
        expected = -1.0 * 4 * 4 * 4 / 2.0
        assert E == pytest.approx(expected)

    def test_energy_all_down(self):
        lattice = IsingLattice(4, coupling_J=1.0, external_h=0.0)
        spins = -np.ones((4, 4), dtype=np.int8)
        E = lattice.energy(spins)
        expected = -1.0 * 4 * 4 * 4 / 2.0
        assert E == pytest.approx(expected)

    def test_energy_with_field(self):
        lattice = IsingLattice(4, coupling_J=1.0, external_h=0.5)
        spins = np.ones((4, 4), dtype=np.int8)
        E = lattice.energy(spins)
        interaction = -1.0 * 4 * 4 * 4 / 2.0
        field = -0.5 * 16
        assert E == pytest.approx(interaction + field)

    def test_magnetization_all_up(self):
        lattice = IsingLattice(4)
        spins = np.ones((4, 4), dtype=np.int8)
        assert lattice.magnetization(spins) == pytest.approx(1.0)

    def test_magnetization_all_down(self):
        lattice = IsingLattice(4)
        spins = -np.ones((4, 4), dtype=np.int8)
        assert lattice.magnetization(spins) == pytest.approx(1.0)

    def test_magnetization_checkerboard(self):
        lattice = IsingLattice(4)
        spins = np.ones((4, 4), dtype=np.int8)
        spins[::2, ::2] = -1
        spins[1::2, 1::2] = -1
        assert lattice.magnetization(spins) == pytest.approx(0.0)

    def test_delta_energy_consistency(self):
        lattice = IsingLattice(8, coupling_J=1.0, external_h=0.0)
        rng = np.random.default_rng(123)
        spins = lattice.random_spins(rng)
        E_before = lattice.energy(spins)
        i, j = 3, 5
        dE = lattice.delta_energy(spins, i, j)
        spins[i, j] *= -1
        E_after = lattice.energy(spins)
        assert E_after == pytest.approx(E_before + dE, abs=1e-6)

    def test_metropolis_sweep_returns_acceptance(self):
        lattice = IsingLattice(8)
        rng = np.random.default_rng(42)
        spins = lattice.random_spins(rng)
        accepted = lattice.metropolis_sweep(spins, beta=1.0, rng=rng)
        assert 0 <= accepted <= lattice.N

    def test_metropolis_high_beta_orders(self):
        lattice = IsingLattice(8)
        rng = np.random.default_rng(99)
        spins = lattice.random_spins(rng)
        for _ in range(200):
            lattice.metropolis_sweep(spins, beta=10.0, rng=rng)
        mag = lattice.magnetization(spins)
        assert mag > 0.9


class TestParallelTempering:

    def test_replica_count(self):
        config = IsingConfig(lattice_size=8, num_replicas=4, total_exchanges=1, sweeps_per_exchange=1, seed=0)
        pt = ParallelTempering(config)
        assert len(pt.replicas) == 4

    def test_betas_ordered(self):
        config = IsingConfig(lattice_size=8, num_replicas=4, beta_min=0.1, beta_max=2.5,
                             total_exchanges=1, sweeps_per_exchange=1, seed=0)
        pt = ParallelTempering(config)
        betas = [r.beta for r in pt.replicas]
        assert betas == sorted(betas)

    def test_node_assignment(self):
        config = IsingConfig(lattice_size=8, num_replicas=4, total_exchanges=1, sweeps_per_exchange=1, seed=0)
        pt = ParallelTempering(config)
        nodes = [r.assigned_node for r in pt.replicas]
        assert nodes[0] == "mega"
        assert nodes[1] == "amdmsix870e-1"
        assert nodes[2] == "amdmsix870e-2"
        assert nodes[3] == "dell-ultracore9"

    def test_run_produces_result(self):
        config = IsingConfig(lattice_size=8, num_replicas=4, total_exchanges=5, sweeps_per_exchange=10, seed=42)
        pt = ParallelTempering(config)
        result = pt.run()
        assert result.total_sweeps == 4 * 5 * 10
        assert len(result.energy_history) == 5
        assert result.duration_secs > 0
        assert result.ground_state_energy <= 0

    def test_swap_acceptance_positive(self):
        config = IsingConfig(lattice_size=8, num_replicas=4, total_exchanges=20, sweeps_per_exchange=10, seed=7)
        pt = ParallelTempering(config)
        result = pt.run()
        assert result.total_swaps_proposed > 0
        assert result.swap_acceptance_rate > 0.0

    def test_energy_decreases_over_run(self):
        config = IsingConfig(lattice_size=16, num_replicas=4, total_exchanges=50, sweeps_per_exchange=20, seed=42)
        pt = ParallelTempering(config)
        result = pt.run()
        early = result.energy_history[0].min_energy
        late = result.energy_history[-1].min_energy
        assert late <= early

    def test_remote_polaroid_format(self):
        config = IsingConfig(lattice_size=8, num_replicas=4, total_exchanges=3, sweeps_per_exchange=5, seed=0)
        pt = ParallelTempering(config)
        result = pt.run()
        polaroid = format_remote_polaroid(result)
        assert "REMOTE POLAROID" in polaroid
        assert "Mega" in polaroid or "mega" in polaroid
        assert "192.168.86" in polaroid
        assert "Ground State" in polaroid
        assert "Grokking Run Complete" in polaroid

    def test_nodes_and_gpus_populated(self):
        config = IsingConfig(lattice_size=8, num_replicas=4, total_exchanges=2, sweeps_per_exchange=2, seed=0)
        pt = ParallelTempering(config)
        result = pt.run()
        assert len(result.nodes_used) == 4
        assert len(result.gpus_used) == 4
        assert "mega" in result.nodes_used

    def test_heat_capacity_nonnegative(self):
        config = IsingConfig(lattice_size=8, num_replicas=4, total_exchanges=10, sweeps_per_exchange=5, seed=11)
        pt = ParallelTempering(config)
        result = pt.run()
        for snap in result.energy_history:
            assert snap.heat_capacity >= 0.0


class TestWatchdogAlignment:

    def test_grokking_budget_matches_config(self):
        """Verify the PT module's node map aligns with cluster_config.yaml topology."""
        expected_ips = {"192.168.86.29", "192.168.86.16", "192.168.86.22", "192.168.86.3"}
        actual_ips = {n["ip"] for n in ParallelTempering.NODE_MAP}
        assert actual_ips == expected_ips

    def test_node_map_models(self):
        models = [n["model"] for n in ParallelTempering.NODE_MAP]
        assert models.count("RTX 5090") == 3
        assert models.count("RTX 4090") == 1

    def test_replica_gpu_affinity_matches_router(self):
        """Verify each replica targets gpu-0 on its node (matching GPU router slot IDs)."""
        for node in ParallelTempering.NODE_MAP:
            assert node["gpu"] == "gpu-0"
