import pytest

try:
    from uft_ca import GraphLattice
    HAS_UFT_CA = True
except ImportError:
    HAS_UFT_CA = False

pytestmark = pytest.mark.skipif(not HAS_UFT_CA, reason="uft_ca not built; run `maturin develop` in crates/uft_ca first")


def test_triangle_birth():
    """Triangle graph: nodes 0,1 alive, node 2 dead. Birth rule on 2 neighbors."""
    states = [1, 1, 0]
    adjacency = [
        [1, 2],
        [0, 2],
        [0, 1],
    ]
    lattice = GraphLattice(states, adjacency)
    rule = {"birth": [2], "survival": [1, 2]}
    result = lattice.step(rule)
    assert result[0] == 1, "Node 0 should survive (1 live neighbor, survival includes 1)"
    assert result[1] == 1, "Node 1 should survive (1 live neighbor, survival includes 1)"
    assert result[2] == 1, "Node 2 should be born (2 live neighbors, birth includes 2)"


def test_line_death():
    """Line graph: 0-1-2, only node 0 alive. No birth or survival conditions met."""
    states = [1, 0, 0]
    adjacency = [
        [1],
        [0, 2],
        [1],
    ]
    lattice = GraphLattice(states, adjacency)
    rule = {"birth": [2], "survival": [2, 3]}
    result = lattice.step(rule)
    assert result[0] == 0, "Node 0 should die (0 live neighbors, survival needs 2 or 3)"
    assert result[1] == 0, "Node 1 should stay dead (1 live neighbor, birth needs 2)"
    assert result[2] == 0, "Node 2 should stay dead (0 live neighbors)"


def test_square_majority():
    """Square graph (4 nodes in a cycle), 3 alive, 1 dead."""
    states = [1, 1, 1, 0]
    adjacency = [
        [1, 3],
        [0, 2],
        [1, 3],
        [2, 0],
    ]
    lattice = GraphLattice(states, adjacency)
    rule = {"birth": [1, 2], "survival": [1, 2]}
    result = lattice.step(rule)
    assert result[0] == 1, "Node 0 survives (1 live neighbor)"
    assert result[1] == 1, "Node 1 survives (2 live neighbors)"
    assert result[2] == 1, "Node 2 survives (1 live neighbor)"
    assert result[3] == 1, "Node 3 born (1 live neighbor, birth includes 1)"


def test_all_dead_no_birth():
    """All nodes dead, rule requires neighbors for birth -> stays dead."""
    states = [0, 0, 0]
    adjacency = [
        [1, 2],
        [0, 2],
        [0, 1],
    ]
    lattice = GraphLattice(states, adjacency)
    rule = {"birth": [2], "survival": [2]}
    result = lattice.step(rule)
    assert result == [0, 0, 0], "All nodes should remain dead"


def test_conway_life_rule_on_triangle():
    """Standard Conway B3/S23 on a triangle -- too few neighbors for anything."""
    states = [1, 1, 0]
    adjacency = [
        [1, 2],
        [0, 2],
        [0, 1],
    ]
    lattice = GraphLattice(states, adjacency)
    rule = {"birth": [3], "survival": [2, 3]}
    result = lattice.step(rule)
    assert result[0] == 0, "Node 0 dies (only 1 live neighbor, needs 2-3 for survival)"
    assert result[1] == 0, "Node 1 dies (only 1 live neighbor)"
    assert result[2] == 0, "Node 2 stays dead (2 live neighbors, but birth needs 3)"
