"""Tests for scripts/shard_protocol.py (Phase 17b Track B).

Primary test is `test_sharded_step_equals_monolithic`: proves that stepping a
2×2×2 shard partition through N generations via the in-process halo exchange
yields bitwise-identical results to running the same step_fn on the monolithic
lattice with periodic boundaries. This is the correctness proof for the
protocol — if it passes, any transport backend that moves the same bytes
around will produce the same results.
"""

import numpy as np
import pytest

from scripts.shard_protocol import (
    HaloPacket,
    InProcessHaloExchange,
    NEIGHBOR_DIRECTIONS,
    ShardLayout,
    StepCoordinator,
    assemble_lattice,
    halo_slab,
    interior_boundary_slab,
    run_sharded_step,
    split_lattice,
)


def _random_lattice(shape=(8, 8, 8), channels=8, seed=0):
    rng = np.random.default_rng(seed)
    state = rng.integers(0, 5, size=shape, dtype=np.uint8)
    memory = rng.random(size=(channels,) + shape, dtype=np.float32)
    return state, memory


def _neighbor_count_step(state, memory, generation):
    """Step function used in correctness tests. Computes the 27-cell neighbourhood
    sum of `state == 1` cells into memory channel 0. `np.roll` gives periodic
    behaviour, which is what we want in the monolithic path. On a sharded array
    with a halo of radius >= 1, the roll wraps across the halo boundary, but the
    interior of the output is still correct — which is all the coordinator keeps.
    """
    mask = (state == 1).astype(np.float32)
    total = np.zeros_like(mask)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                total += np.roll(np.roll(np.roll(mask, dx, 0), dy, 1), dz, 2)
    new_memory = memory.copy()
    new_memory[0] = total
    return state.copy(), new_memory


# -- layout math --------------------------------------------------------------


def test_layout_basic_shapes():
    layout = ShardLayout(global_shape=(8, 8, 8), shard_grid=(2, 2, 2), halo_width=1)
    assert layout.interior_shape == (4, 4, 4)
    assert layout.total_shape == (6, 6, 6)
    assert len(layout.all_coords()) == 8


def test_layout_rejects_indivisible_shape():
    with pytest.raises(ValueError, match="not divisible"):
        ShardLayout(global_shape=(7, 8, 8), shard_grid=(2, 2, 2), halo_width=1)


def test_layout_rejects_halo_larger_than_interior():
    with pytest.raises(ValueError, match="smaller than halo_width"):
        ShardLayout(global_shape=(4, 4, 4), shard_grid=(2, 2, 2), halo_width=4)


def test_neighbor_coord_wraps_periodically():
    layout = ShardLayout(global_shape=(8, 8, 8), shard_grid=(2, 2, 2), halo_width=1)
    assert layout.neighbor_coord((0, 0, 0), (-1, 0, 0)) == (1, 0, 0)
    assert layout.neighbor_coord((1, 1, 1), (1, 1, 1)) == (0, 0, 0)


# -- slab geometry ------------------------------------------------------------


def test_interior_boundary_slab_sizes():
    layout = ShardLayout(global_shape=(8, 8, 8), shard_grid=(2, 2, 2), halo_width=1)
    # Axis-aligned face: H × L × L
    sl = interior_boundary_slab(layout, (1, 0, 0))
    assert sl == (slice(4, 5), slice(1, 5), slice(1, 5))
    # Edge: H × H × L
    sl = interior_boundary_slab(layout, (1, 1, 0))
    assert sl == (slice(4, 5), slice(4, 5), slice(1, 5))
    # Corner: H × H × H
    sl = interior_boundary_slab(layout, (1, 1, 1))
    assert sl == (slice(4, 5), slice(4, 5), slice(4, 5))


def test_halo_slab_matches_opposite_side():
    layout = ShardLayout(global_shape=(8, 8, 8), shard_grid=(2, 2, 2), halo_width=1)
    # Halo on +x side is where the +x neighbor's interior-boundary lands
    assert halo_slab(layout, (1, 0, 0)) == (slice(5, 6), slice(1, 5), slice(1, 5))
    assert halo_slab(layout, (-1, 0, 0)) == (slice(0, 1), slice(1, 5), slice(1, 5))


def test_all_26_directions_have_distinct_slabs():
    layout = ShardLayout(global_shape=(8, 8, 8), shard_grid=(2, 2, 2), halo_width=1)
    seen = set()
    for d in NEIGHBOR_DIRECTIONS:
        sl = interior_boundary_slab(layout, d)
        # Represent slice as tuple of (start, stop) for hashing
        key = tuple((s.start, s.stop) for s in sl)
        assert key not in seen, f"direction {d} collides with another direction"
        seen.add(key)
    assert len(seen) == 26


# -- split / assemble --------------------------------------------------------


def test_split_assemble_roundtrip():
    state, memory = _random_lattice(shape=(8, 8, 8), seed=42)
    layout, shards = split_lattice(state, memory, shard_grid=(2, 2, 2), halo_width=1)
    assert len(shards) == 8
    state_back, memory_back = assemble_lattice(layout, shards)
    np.testing.assert_array_equal(state_back, state)
    np.testing.assert_array_equal(memory_back, memory)


def test_split_populates_halos_from_periodic_neighbors():
    """A shard at coord (0,0,0) should have its -x halo populated from the (1,0,0) shard's
    +x interior boundary (periodic wrap)."""
    state, memory = _random_lattice(shape=(8, 8, 8), seed=7)
    layout, shards = split_lattice(state, memory, shard_grid=(2, 2, 2), halo_width=1)
    shard_000 = shards[(0, 0, 0)]
    # -x halo of (0,0,0) should equal +x interior boundary of (1,0,0), which under
    # periodic wrap is the rightmost interior column (global index 7) of the original lattice.
    neg_x_halo = shard_000.state[halo_slab(layout, (-1, 0, 0))]
    expected = state[7:8, 0:4, 0:4]
    np.testing.assert_array_equal(neg_x_halo, expected)


# -- packet serialization ----------------------------------------------------


def test_halo_packet_roundtrip():
    rng = np.random.default_rng(1)
    state_slab = rng.integers(0, 5, size=(1, 4, 4), dtype=np.uint8)
    memory_slab = rng.random(size=(8, 1, 4, 4), dtype=np.float32)
    packet = HaloPacket(
        source_coord=(0, 1, 1),
        target_coord=(1, 1, 1),
        direction=(1, 0, 0),
        generation=42,
        state_slab=state_slab,
        memory_slab=memory_slab,
    )
    buf = packet.to_bytes()
    restored = HaloPacket.from_bytes(buf)
    assert restored.source_coord == (0, 1, 1)
    assert restored.target_coord == (1, 1, 1)
    assert restored.direction == (1, 0, 0)
    assert restored.generation == 42
    np.testing.assert_array_equal(restored.state_slab, state_slab)
    np.testing.assert_array_equal(restored.memory_slab, memory_slab)


def test_halo_packet_rejects_wrong_dtype():
    with pytest.raises(TypeError, match="uint8"):
        HaloPacket(
            source_coord=(0, 0, 0),
            target_coord=(1, 0, 0),
            direction=(1, 0, 0),
            generation=0,
            state_slab=np.zeros((1, 4, 4), dtype=np.int32),  # wrong
            memory_slab=np.zeros((8, 1, 4, 4), dtype=np.float32),
        ).to_bytes()


def test_halo_packet_bad_magic():
    with pytest.raises(ValueError, match="bad magic"):
        HaloPacket.from_bytes(b"XXXX" + b"\x00" * 200)


# -- end-to-end correctness --------------------------------------------------


def _run_monolithic(state, memory, n_steps):
    for _ in range(n_steps):
        state, memory = _neighbor_count_step(state, memory, 0)
    return state, memory


def _run_sharded(state, memory, shard_grid, halo_width, n_steps):
    layout, shards = split_lattice(state, memory, shard_grid=shard_grid, halo_width=halo_width)
    exchange = InProcessHaloExchange()
    for coord in layout.all_coords():
        exchange.register(coord)
    coordinators = [
        StepCoordinator(shards[coord], exchange, _neighbor_count_step)
        for coord in layout.all_coords()
    ]
    for _ in range(n_steps):
        run_sharded_step(coordinators, exchange)
    return assemble_lattice(layout, {c.shard.coord: c.shard for c in coordinators})


def test_sharded_single_step_equals_monolithic():
    state, memory = _random_lattice(shape=(8, 8, 8), seed=123)
    mono_state, mono_memory = _run_monolithic(state.copy(), memory.copy(), n_steps=1)
    shard_state, shard_memory = _run_sharded(
        state.copy(), memory.copy(), shard_grid=(2, 2, 2), halo_width=1, n_steps=1
    )
    np.testing.assert_array_equal(shard_state, mono_state)
    np.testing.assert_array_equal(shard_memory, mono_memory)


def test_sharded_multi_step_equals_monolithic():
    state, memory = _random_lattice(shape=(8, 8, 8), seed=999)
    mono_state, mono_memory = _run_monolithic(state.copy(), memory.copy(), n_steps=5)
    shard_state, shard_memory = _run_sharded(
        state.copy(), memory.copy(), shard_grid=(2, 2, 2), halo_width=1, n_steps=5
    )
    np.testing.assert_array_equal(shard_state, mono_state)
    np.testing.assert_array_equal(shard_memory, mono_memory)


def test_sharded_1x2x2_grid_still_matches():
    """Sanity check: non-cubic shard grid also works."""
    state, memory = _random_lattice(shape=(4, 8, 8), seed=55)
    mono_state, mono_memory = _run_monolithic(state.copy(), memory.copy(), n_steps=3)
    shard_state, shard_memory = _run_sharded(
        state.copy(), memory.copy(), shard_grid=(1, 2, 2), halo_width=1, n_steps=3
    )
    np.testing.assert_array_equal(shard_state, mono_state)
    np.testing.assert_array_equal(shard_memory, mono_memory)
