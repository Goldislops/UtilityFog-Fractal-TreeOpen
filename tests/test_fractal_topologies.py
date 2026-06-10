"""Fractal topology generators + stepping behavior for uft_ca.

CONTRACT NOTE (#180 test reconciliation, 2026-06-10): since Phase 14a,
`step()`/`step_n()` is the memory-augmented path and `step_par()`/
`step_auto()` the (memoryless) stochastic path — different algorithms by
design. seq==par equivalence is asserted on the stochastic pair
(`step_auto()` is sequential below PAR_THRESHOLD=10_000 nodes, parallel
at/above it); memory-path behavior is pinned via determinism and
mechanism-derived invariants, not via old all-states-static expectations.
See tests/test_parallel_stepping.py docstring for the full rationale.
"""

import pytest

try:
    from uft_ca import (
        MultiStateGraphLattice,
        sierpinski_node_count,
        menger_node_count,
        octahedral_node_count,
    )
except ImportError:
    pytest.skip("uft_ca not built; run `maturin develop` in crates/uft_ca", allow_module_level=True)

VOID, STRUCTURAL, COMPUTE, ENERGY, SENSOR = 0, 1, 2, 3, 4


class TestSierpinskiTetrahedron:
    def test_depth_0_node_count(self):
        lattice = MultiStateGraphLattice.sierpinski(0, VOID)
        assert lattice.node_count() == 4
        assert sierpinski_node_count(0) == 4

    def test_depth_1_node_count(self):
        lattice = MultiStateGraphLattice.sierpinski(1, ENERGY)
        assert lattice.node_count() == 16
        assert sierpinski_node_count(1) == 16

    def test_depth_2_node_count(self):
        lattice = MultiStateGraphLattice.sierpinski(2, STRUCTURAL)
        assert lattice.node_count() == 64
        assert sierpinski_node_count(2) == 64

    def test_depth_3_node_count(self):
        assert sierpinski_node_count(3) == 256

    def test_initial_state(self):
        lattice = MultiStateGraphLattice.sierpinski(1, ENERGY)
        states = lattice.get_states()
        assert all(s == ENERGY for s in states)

    def test_step_produces_valid_states(self):
        lattice = MultiStateGraphLattice.sierpinski(1, ENERGY)
        result = lattice.step()
        assert len(result) == 16
        assert all(0 <= s <= 4 for s in result)

    def test_step_auto_matches_step_par(self):
        # seq==par on the stochastic path (16 nodes < PAR_THRESHOLD,
        # so step_auto is the sequential stochastic stepper).
        a = MultiStateGraphLattice.sierpinski(1, ENERGY)
        b = MultiStateGraphLattice.sierpinski(1, ENERGY)
        assert a.step_auto() == b.step_par()

    def test_multi_step_convergence(self):
        lattice = MultiStateGraphLattice.sierpinski(1, ENERGY)
        result = lattice.step_auto_n(10)
        assert len(result) == 16


class TestMengerSponge:
    def test_depth_0_node_count(self):
        lattice = MultiStateGraphLattice.menger(0, VOID)
        assert lattice.node_count() == 1
        assert menger_node_count(0) == 1

    def test_depth_1_node_count(self):
        lattice = MultiStateGraphLattice.menger(1, STRUCTURAL)
        assert lattice.node_count() == 20
        assert menger_node_count(1) == 20

    def test_depth_2_node_count(self):
        expected = menger_node_count(2)
        lattice = MultiStateGraphLattice.menger(2, VOID)
        assert lattice.node_count() == expected
        assert expected > 20

    def test_initial_state(self):
        lattice = MultiStateGraphLattice.menger(1, STRUCTURAL)
        states = lattice.get_states()
        assert all(s == STRUCTURAL for s in states)

    def test_step_produces_valid_states(self):
        lattice = MultiStateGraphLattice.menger(1, ENERGY)
        result = lattice.step()
        assert len(result) == 20
        assert all(0 <= s <= 4 for s in result)

    def test_step_auto_matches_step_par(self):
        # seq==par on the stochastic path (20 nodes < PAR_THRESHOLD).
        a = MultiStateGraphLattice.menger(1, ENERGY)
        b = MultiStateGraphLattice.menger(1, ENERGY)
        assert a.step_auto() == b.step_par()

    def test_structural_block_evolves_deterministically(self):
        # Old contract ("all cells stay STRUCTURAL forever") died with the
        # memory path: bamboo rebirth, reverse contagion, and analogue
        # mutation legitimately convert STRUCTURAL cells (apply_with_memory).
        # The surviving contracts: node count is conserved, states stay
        # valid, and evolution is deterministic given identical state.
        a = MultiStateGraphLattice.menger(1, STRUCTURAL)
        b = MultiStateGraphLattice.menger(1, STRUCTURAL)
        for _ in range(5):
            sa = a.step()
            sb = b.step()
            assert sa == sb
            assert len(sa) == 20
            assert all(0 <= s <= 4 for s in sa)


class TestOctahedralFogLattice:
    def test_side_2_node_count(self):
        lattice = MultiStateGraphLattice.octahedral(2, VOID)
        assert lattice.node_count() == 8
        assert octahedral_node_count(2) == 8

    def test_side_3_node_count(self):
        lattice = MultiStateGraphLattice.octahedral(3, SENSOR)
        assert lattice.node_count() == 27
        assert octahedral_node_count(3) == 27

    def test_side_10_node_count(self):
        lattice = MultiStateGraphLattice.octahedral(10, VOID)
        assert lattice.node_count() == 1000
        assert octahedral_node_count(10) == 1000

    def test_initial_state(self):
        lattice = MultiStateGraphLattice.octahedral(3, SENSOR)
        states = lattice.get_states()
        assert all(s == SENSOR for s in states)

    def test_center_has_12_neighbors(self):
        lattice = MultiStateGraphLattice.octahedral(3, VOID)
        assert lattice.avg_degree() > 6.0

    def test_step_produces_valid_states(self):
        lattice = MultiStateGraphLattice.octahedral(3, ENERGY)
        result = lattice.step()
        assert len(result) == 27
        assert all(0 <= s <= 4 for s in result)

    def test_step_auto_matches_step_par(self):
        # seq==par on the stochastic path (27 nodes < PAR_THRESHOLD).
        a = MultiStateGraphLattice.octahedral(3, ENERGY)
        b = MultiStateGraphLattice.octahedral(3, ENERGY)
        assert a.step_auto() == b.step_par()

    def test_energy_lattice_evolves_into_active_states(self):
        # Mechanism-derived (apply_with_memory): from all-ENERGY, where every
        # cell has >=1 ENERGY neighbor, one memory step can only yield
        # ENERGY (base rule), COMPUTE (energy_to_compute conversion), or
        # SENSOR (analogue mutation) — never VOID or STRUCTURAL.
        lattice = MultiStateGraphLattice.octahedral(3, ENERGY)
        after_one = lattice.step()
        assert set(after_one) <= {ENERGY, COMPUTE, SENSOR}
        # Longer horizons cascade; pin determinism + validity instead of
        # the old "stays all-ENERGY forever" contract.
        a = MultiStateGraphLattice.octahedral(3, ENERGY)
        b = MultiStateGraphLattice.octahedral(3, ENERGY)
        ra = a.step_n(10)
        rb = b.step_n(10)
        assert ra == rb
        assert len(ra) == 27
        assert all(0 <= s <= 4 for s in ra)


class TestAutoThreshold:
    def test_small_graph_auto(self):
        # Below PAR_THRESHOLD, step_auto takes the sequential stochastic
        # path; it must agree exactly with the parallel stochastic path.
        lattice = MultiStateGraphLattice.sierpinski(1, ENERGY)
        assert lattice.node_count() < 10000
        a = MultiStateGraphLattice.sierpinski(1, ENERGY)
        b = MultiStateGraphLattice.sierpinski(1, ENERGY)
        assert a.step_auto() == b.step_par()

    def test_large_graph_auto(self):
        lattice = MultiStateGraphLattice.octahedral(22, ENERGY)
        assert lattice.node_count() >= 10000
        a = MultiStateGraphLattice.octahedral(22, ENERGY)
        b = MultiStateGraphLattice.octahedral(22, ENERGY)
        assert a.step_par() == b.step_auto()

    def test_step_auto_n(self):
        a = MultiStateGraphLattice.octahedral(22, ENERGY)
        b = MultiStateGraphLattice.octahedral(22, ENERGY)
        assert a.step_par_n(3) == b.step_auto_n(3)


class TestTopologyMetrics:
    def test_sierpinski_edge_count(self):
        lattice = MultiStateGraphLattice.sierpinski(0, VOID)
        assert lattice.edge_count() == 6

    def test_menger_avg_degree(self):
        lattice = MultiStateGraphLattice.menger(1, VOID)
        deg = lattice.avg_degree()
        assert 2.0 < deg < 6.0

    def test_octahedral_avg_degree(self):
        lattice = MultiStateGraphLattice.octahedral(5, VOID)
        deg = lattice.avg_degree()
        assert deg > 6.0


class TestSetStates:
    def test_set_states_and_step(self):
        lattice = MultiStateGraphLattice.sierpinski(0, VOID)
        lattice.set_states([ENERGY, ENERGY, ENERGY, COMPUTE])
        states = lattice.get_states()
        assert states == [ENERGY, ENERGY, ENERGY, COMPUTE]
        result = lattice.step()
        assert len(result) == 4

    def test_inject_energy_into_menger(self):
        lattice = MultiStateGraphLattice.menger(1, VOID)
        states = lattice.get_states()
        states[0] = ENERGY
        states[1] = ENERGY
        lattice.set_states(states)
        result = lattice.step()
        assert len(result) == 20


class TestParallelOnFractals:
    # seq==par on the stochastic path (see module docstring): step_auto is
    # sequential below PAR_THRESHOLD and parallel at/above it; either way
    # it must agree exactly with step_par.
    def test_sierpinski_par_matches_seq(self):
        a = MultiStateGraphLattice.sierpinski(2, ENERGY)
        b = MultiStateGraphLattice.sierpinski(2, ENERGY)
        assert a.step_auto() == b.step_par()

    def test_menger_par_matches_seq(self):
        a = MultiStateGraphLattice.menger(2, ENERGY)
        b = MultiStateGraphLattice.menger(2, ENERGY)
        assert a.step_auto() == b.step_par()

    def test_octahedral_par_matches_seq(self):
        a = MultiStateGraphLattice.octahedral(10, ENERGY)
        b = MultiStateGraphLattice.octahedral(10, ENERGY)
        assert a.step_auto() == b.step_par()

    def test_large_octahedral_par_multi_step(self):
        a = MultiStateGraphLattice.octahedral(22, ENERGY)
        b = MultiStateGraphLattice.octahedral(22, ENERGY)
        assert a.step_auto_n(3) == b.step_par_n(3)
