"""Tests for scripts/shard_protocol.py (Phase 17b Track B).

Primary test is `test_sharded_step_equals_monolithic`: proves that stepping a
2×2×2 shard partition through N generations via the in-process halo exchange
yields bitwise-identical results to running the same step_fn on the monolithic
lattice with periodic boundaries. This is the correctness proof for the
protocol — if it passes, any transport backend that moves the same bytes
around will produce the same results.
"""

import struct

import numpy as np
import pytest

from scripts.shard_protocol import (
    HaloPacket,
    InProcessHaloExchange,
    NEIGHBOR_DIRECTIONS,
    ShardLayout,
    StepCoordinator,
    _HEADER_FMT,
    _HEADER_SIZE,
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


# -- from_bytes structural refusal totality ----------------------------------
#
# `from_bytes` decodes frames straight off a transport — scripts/
# shard_transport_zmq.py calls it bare on socket bytes inside its recv loop —
# so every structurally invalid frame must become a FIXED, value-free
# ValueError instead of a struct.error, a silently misread halo face, or a
# numpy message carrying wire-supplied values.
#
# Failing-before, against the pre-fix decoder:
#   - empty / 1-byte / (_HEADER_SIZE - 1) frames raised `struct.error` — which
#     is NOT a ValueError — straight out of `struct.unpack`;
#   - out-of-range direction components and the non-neighbor (0, 0, 0) decoded
#     silently, and `_slab_slice` maps every component other than -1/0 onto the
#     +1 face, so a corrupt direction wrote a halo into the WRONG face;
#   - a short payload surfaced numpy's own "buffer is smaller than requested
#     size" ValueError, and trailing bytes were accepted outright;
#   - the magic and dtype-code refusals embedded the supplied values.
#
# Every case below pins the EXACT fixed message, so none of them can pass
# vacuously against the pre-fix decoder. Scope is structural refusal only:
# source/target coordinates, generation, and directly-constructed HaloPackets
# are deliberately not covered.

_VALID_STATE_SHAPE = (1, 2, 2)
_VALID_MEMORY_SHAPE = (8, 1, 2, 2)


def _element_count(shape):
    n = 1
    for dim in shape:
        n *= dim
    return n


def _halo_header(
    *,
    magic=b"SHD1",
    source=(0, 0, 0),
    target=(1, 0, 0),
    direction=(1, 0, 0),
    generation=7,
    state_code=0,
    memory_code=0,
    state_shape=_VALID_STATE_SHAPE,
    memory_shape=_VALID_MEMORY_SHAPE,
):
    """Pack a header field-by-field so exactly one field can be made invalid."""
    return struct.pack(
        _HEADER_FMT,
        magic,
        *source,
        *target,
        *direction,
        generation,
        state_code,
        memory_code,
        *state_shape,
        *memory_shape,
    )


def _halo_payload(state_shape=_VALID_STATE_SHAPE, memory_shape=_VALID_MEMORY_SHAPE):
    """Zero payload of exactly the size the declared shapes require."""
    return bytes(_element_count(state_shape)) + bytes(4 * _element_count(memory_shape))


def _valid_frame(**header_kwargs):
    return _halo_header(**header_kwargs) + _halo_payload()


def _refusal_message(frame):
    """Decode `frame`, requiring an exact ValueError; return its message."""
    with pytest.raises(ValueError) as exc:
        HaloPacket.from_bytes(frame)
    # Exactly ValueError: not struct.error (which is not a ValueError at all),
    # and not some subclass carrying extra state.
    assert type(exc.value) is ValueError
    return str(exc.value)


def test_handcrafted_valid_frame_decodes():
    """Guards every refusal case below: the hand-packed frame really is valid,
    so a later refusal is caused by the mutated field alone, not the helper."""
    packet = HaloPacket.from_bytes(_valid_frame())
    assert packet.source_coord == (0, 0, 0)
    assert packet.target_coord == (1, 0, 0)
    assert packet.direction == (1, 0, 0)
    assert packet.generation == 7
    assert packet.state_slab.shape == _VALID_STATE_SHAPE
    assert packet.memory_slab.shape == _VALID_MEMORY_SHAPE
    assert packet.state_slab.dtype == np.uint8
    assert packet.memory_slab.dtype == np.float32


@pytest.mark.parametrize(
    "frame",
    [
        b"",
        b"\x00",
        b"S",
        b"SHD1",
        bytes(_HEADER_SIZE - 1),
        b"SHD1" + bytes(_HEADER_SIZE - 5),
    ],
    ids=[
        "empty",
        "one_zero_byte",
        "one_letter",
        "magic_only",
        "header_size_minus_one",
        "valid_magic_short_header",
    ],
)
def test_from_bytes_refuses_frame_shorter_than_header(frame):
    # Pre-fix these raised struct.error out of struct.unpack.
    assert len(frame) < _HEADER_SIZE
    assert _refusal_message(frame) == (
        "bad halo packet: frame shorter than the fixed header"
    )


@pytest.mark.parametrize(
    "direction",
    [
        (2, 0, 0),
        (0, 3, 0),
        (0, 0, 127),
        (-2, 0, 0),
        (0, -7, 0),
        (0, 0, -128),
        (42, -7, 99),
        (1, 1, 2),
        (-1, -1, -2),
    ],
    ids=[
        "pos_x_two",
        "pos_y_three",
        "pos_z_max",
        "neg_x_two",
        "neg_y_seven",
        "neg_z_min",
        "all_out_of_range",
        "one_component_out_of_range",
        "one_negative_out_of_range",
    ],
)
def test_from_bytes_refuses_out_of_range_direction(direction):
    assert direction not in NEIGHBOR_DIRECTIONS
    assert _refusal_message(_valid_frame(direction=direction)) == (
        "bad halo packet: direction is not a neighbor direction"
    )


def test_from_bytes_refuses_zero_direction():
    """(0, 0, 0) packs as a legal signed-byte triple but is NOT a neighbor
    direction — NEIGHBOR_DIRECTIONS deliberately excludes it, so a frame
    claiming it must be refused rather than applied to some halo face."""
    assert (0, 0, 0) not in NEIGHBOR_DIRECTIONS
    assert _refusal_message(_valid_frame(direction=(0, 0, 0))) == (
        "bad halo packet: direction is not a neighbor direction"
    )


def test_from_bytes_accepts_every_neighbor_direction():
    """No over-refusal: all 26 real directions a coordinator emits still decode."""
    assert len(NEIGHBOR_DIRECTIONS) == 26
    for direction in NEIGHBOR_DIRECTIONS:
        packet = HaloPacket.from_bytes(_valid_frame(direction=direction))
        assert packet.direction == direction


@pytest.mark.parametrize(
    "frame_builder",
    [
        lambda: _halo_header(),
        lambda: _halo_header() + bytes(_element_count(_VALID_STATE_SHAPE)),
        lambda: _valid_frame()[:-1],
        lambda: _valid_frame()[: _HEADER_SIZE + 1],
    ],
    ids=[
        "header_only",
        "state_but_no_memory",
        "one_byte_short",
        "one_payload_byte_only",
    ],
)
def test_from_bytes_refuses_payload_shorter_than_declared(frame_builder):
    assert _refusal_message(frame_builder()) == (
        "bad halo packet: length does not match the declared shapes"
    )


@pytest.mark.parametrize(
    "trailer",
    [b"\x00", b"\x00" * 4, b"trailing junk"],
    ids=["one_zero_byte", "four_zero_bytes", "junk"],
)
def test_from_bytes_refuses_trailing_bytes(trailer):
    """A frame whose payload is complete but is followed by extra bytes was
    previously decoded, silently ignoring the trailer."""
    assert _refusal_message(_valid_frame() + trailer) == (
        "bad halo packet: length does not match the declared shapes"
    )


@pytest.mark.parametrize(
    "header_kwargs",
    [
        {"state_shape": (4096, 4096, 4096)},
        {"memory_shape": (8, 4096, 4096, 4096)},
        {"state_shape": (65535, 65535, 65535)},
    ],
    ids=["huge_state", "huge_memory", "enormous_state"],
)
def test_from_bytes_refuses_over_declared_shape_before_allocating(header_kwargs):
    """An over-declared shape is refused on declared length alone, so neither
    np.frombuffer call is reached and no allocation is attempted."""
    assert _refusal_message(_halo_header(**header_kwargs) + _halo_payload()) == (
        "bad halo packet: length does not match the declared shapes"
    )


@pytest.mark.parametrize(
    "state_code,memory_code",
    [(1, 0), (0, 1), (1, 1), (255, 0), (0, 255), (7, 9)],
    ids=["state_one", "memory_one", "both_one", "state_max", "memory_max", "both_unknown"],
)
def test_from_bytes_refuses_unsupported_dtype_codes(state_code, memory_code):
    assert _refusal_message(
        _valid_frame(state_code=state_code, memory_code=memory_code)
    ) == "unsupported dtype codes in halo packet header"


def test_from_bytes_bad_magic_message_is_fixed():
    """The established `bad magic` contract is kept, without the value."""
    message = _refusal_message(_valid_frame(magic=b"XXXX"))
    assert message == "bad magic in halo packet header"
    assert "bad magic" in message  # the pre-existing test's contract


def test_from_bytes_refusals_are_fixed_and_value_free():
    """No refusal may echo a supplied byte sequence or numeric field. Every
    fixed message is digit-free, so no wire number can leak through one."""
    cases = [
        (_valid_frame(magic=b"LEAK"), ["LEAK"]),
        (_valid_frame(direction=(42, -7, 99)), ["42", "-7", "99"]),
        (_valid_frame(state_code=77, memory_code=88), ["77", "88"]),
        (_valid_frame() + b"LEAKINGTRAILER", ["LEAKINGTRAILER"]),
        (_halo_header(state_shape=(3, 5, 7)), ["3", "5", "7"]),
        (bytes(_HEADER_SIZE - 1), []),
    ]
    for frame, forbidden_tokens in cases:
        message = _refusal_message(frame)
        assert message == message.strip()
        assert not any(character.isdigit() for character in message)
        for token in forbidden_tokens:
            assert token not in message


def test_valid_round_trip_unchanged_by_refusal_hardening():
    """Valid-packet byte interpretation is untouched: the decoded packet
    matches the source arrays and re-encodes to the identical frame."""
    rng = np.random.default_rng(17)
    state_slab = rng.integers(0, 5, size=(2, 3, 4), dtype=np.uint8)
    memory_slab = rng.random(size=(8, 2, 3, 4), dtype=np.float32)
    packet = HaloPacket(
        source_coord=(1, 2, 3),
        target_coord=(0, 2, 3),
        direction=(-1, 0, 0),
        generation=99,
        state_slab=state_slab,
        memory_slab=memory_slab,
    )
    frame = packet.to_bytes()
    restored = HaloPacket.from_bytes(frame)
    assert restored.source_coord == (1, 2, 3)
    assert restored.target_coord == (0, 2, 3)
    assert restored.direction == (-1, 0, 0)
    assert restored.generation == 99
    np.testing.assert_array_equal(restored.state_slab, state_slab)
    np.testing.assert_array_equal(restored.memory_slab, memory_slab)
    assert restored.to_bytes() == frame


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
