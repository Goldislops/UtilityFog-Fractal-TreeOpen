"""Sequential-vs-parallel stepping equivalence for uft_ca.

CONTRACT NOTE (#180 test reconciliation, 2026-06-10):
Since Phase 14a (`56e0b72`), `MultiStateGraphLattice.step()` is the
*memory-augmented* path (`step_multi_with_memory`: voxel memory, decay
resistance, energy->compute conversion, analogue mutation), while
`step_par()` is the *memoryless stochastic* path
(`step_multi_par_stochastic`). They are different algorithms by design,
so `step() == step_par()` is no longer a valid contract.

The seq==par equivalence property is real on the *stochastic* path:
`step_multi_stochastic` (sequential) and `step_multi_par_stochastic`
(parallel) apply the identical `apply_stochastic(state, counts, node_id)`
with identical per-node hash seeds, so they must agree exactly regardless
of execution order. From Python: `step_auto()` dispatches to the
sequential stochastic stepper for graphs < 10_000 nodes (PAR_THRESHOLD),
so `step_auto() == step_par()` on small graphs is precisely seq==par on
the same algorithm. All graphs in this file are < 10_000 nodes.

The memory path's own contract — determinism given identical initial
state — is covered by TestMemoryPathDeterminism below; its semantics are
fenced by the Rust suite (`cargo test`, 86 tests).
"""

import pytest
import random

try:
    from uft_ca import MultiStateGraphLattice
except ImportError:
    pytest.skip("uft_ca not built; run `maturin develop` in crates/uft_ca", allow_module_level=True)

VOID, STRUCTURAL, COMPUTE, ENERGY, SENSOR = 0, 1, 2, 3, 4


def triangle(states):
    adj = [[1, 2], [0, 2], [0, 1]]
    return states, adj


def ring(n, state_fn):
    states = [state_fn(i) for i in range(n)]
    adj = [[(i - 1) % n, (i + 1) % n] for i in range(n)]
    return states, adj


def complete_graph(n, state_fn):
    states = [state_fn(i) for i in range(n)]
    adj = [[j for j in range(n) if j != i] for i in range(n)]
    return states, adj


def grid_2d(width, height, state_fn):
    n = width * height
    states = [state_fn(i) for i in range(n)]
    adj = [[] for _ in range(n)]
    for y in range(height):
        for x in range(width):
            idx = y * width + x
            if x > 0:
                adj[idx].append(idx - 1)
            if x < width - 1:
                adj[idx].append(idx + 1)
            if y > 0:
                adj[idx].append(idx - width)
            if y < height - 1:
                adj[idx].append(idx + width)
    return states, adj


class TestParallelMatchesSequential:
    """seq==par on the stochastic path: step_auto() (sequential for <10K
    nodes) must agree exactly with step_par() (parallel)."""

    def test_triangle_energy_compute(self):
        states, adj = triangle([ENERGY, COMPUTE, VOID])
        seq = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        par = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        seq_result = seq.step_auto()
        par_result = par.step_par()
        assert seq_result == par_result

    def test_triangle_energy_chain(self):
        states, adj = triangle([ENERGY, ENERGY, VOID])
        seq = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        par = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        assert seq.step_auto() == par.step_par()

    def test_structural_crystallization(self):
        states = [VOID, STRUCTURAL, STRUCTURAL, STRUCTURAL]
        adj = [[1, 2, 3], [0, 2, 3], [0, 1, 3], [0, 1, 2]]
        seq = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        par = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        assert seq.step_auto() == par.step_par()

    def test_sensor_fires(self):
        states, adj = triangle([SENSOR, COMPUTE, COMPUTE])
        seq = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        par = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        assert seq.step_auto() == par.step_par()

    def test_all_five_states(self):
        states = [VOID, STRUCTURAL, COMPUTE, ENERGY, SENSOR]
        adj = [[1,2,3,4], [0,2,3,4], [0,1,3,4], [0,1,2,4], [0,1,2,3]]
        seq = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        par = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        assert seq.step_auto() == par.step_par()


class TestParallelMultiStep:
    def test_step_n_matches(self):
        states, adj = triangle([ENERGY, ENERGY, VOID])
        seq = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        par = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        assert seq.step_auto_n(10) == par.step_par_n(10)

    def test_convergence_over_steps(self):
        states, adj = ring(6, lambda i: ENERGY if i % 2 == 0 else VOID)
        seq = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        par = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        for _ in range(20):
            s = seq.step_auto()
            p = par.step_par()
            assert s == p


class TestParallelLargeGraphs:
    def test_ring_1000(self):
        states, adj = ring(1000, lambda i: i % 5)
        seq = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        par = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        assert seq.step_auto() == par.step_par()

    def test_grid_50x50(self):
        states, adj = grid_2d(50, 50, lambda i: i % 5)
        seq = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        par = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        assert seq.step_auto() == par.step_par()

    def test_grid_50x50_multi_step(self):
        states, adj = grid_2d(50, 50, lambda i: i % 5)
        seq = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        par = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        assert seq.step_auto_n(5) == par.step_par_n(5)

    def test_complete_graph_100(self):
        states, adj = complete_graph(100, lambda i: i % 5)
        seq = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        par = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        assert seq.step_auto() == par.step_par()

    def test_large_ring_multi_step(self):
        states, adj = ring(5000, lambda i: i % 5)
        seq = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        par = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        assert seq.step_auto_n(3) == par.step_par_n(3)


class TestParallelRandomized:
    def test_random_graph_1000(self):
        random.seed(42)
        n = 1000
        states = [random.randint(0, 4) for _ in range(n)]
        adj = [sorted(random.sample(range(n), min(random.randint(1, 6), n))) for _ in range(n)]
        for i in range(n):
            adj[i] = [x for x in adj[i] if x != i]
        seq = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        par = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        assert seq.step_auto() == par.step_par()

    def test_random_graph_5_steps(self):
        random.seed(99)
        n = 500
        states = [random.randint(0, 4) for _ in range(n)]
        adj = [sorted(random.sample(range(n), min(random.randint(1, 8), n))) for _ in range(n)]
        for i in range(n):
            adj[i] = [x for x in adj[i] if x != i]
        seq = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        par = MultiStateGraphLattice.with_fog_rules(list(states), [list(a) for a in adj])
        assert seq.step_auto_n(5) == par.step_par_n(5)


class TestMemoryPathDeterminism:
    """The memory-augmented step() is hash-seeded per (node, counts,
    memory-state) — no global RNG — so identical lattices must evolve
    identically. This pins the memory path's reproducibility contract
    without asserting cross-algorithm equality."""

    def test_step_reproducible(self):
        states, adj = ring(100, lambda i: i % 5)
        a = MultiStateGraphLattice.with_fog_rules(list(states), [list(r) for r in adj])
        b = MultiStateGraphLattice.with_fog_rules(list(states), [list(r) for r in adj])
        assert a.step() == b.step()

    def test_step_n_reproducible(self):
        states, adj = grid_2d(20, 20, lambda i: i % 5)
        a = MultiStateGraphLattice.with_fog_rules(list(states), [list(r) for r in adj])
        b = MultiStateGraphLattice.with_fog_rules(list(states), [list(r) for r in adj])
        assert a.step_n(10) == b.step_n(10)

    def test_memory_path_differs_from_stochastic_path(self):
        """Documents the Phase 14a split: step() (memory) and step_par()
        (stochastic) are different algorithms. If this ever starts
        passing-as-equal on this seed, the split has changed — revisit
        the module docstring and the #180 reconciliation notes."""
        states, adj = ring(1000, lambda i: i % 5)
        mem = MultiStateGraphLattice.with_fog_rules(list(states), [list(r) for r in adj])
        sto = MultiStateGraphLattice.with_fog_rules(list(states), [list(r) for r in adj])
        assert mem.step_n(5) != sto.step_par_n(5)
