"""Transport-agnostic shard protocol for distributed CA stepping (Phase 17b Track B).

Foundation for eventually running a 512³ lattice split across multiple processes
or nodes, independent of whether the transport is Ray, MPI, ZMQ, or raw TCP.

Design principles:
  1. No transport dependencies in the core. `HaloExchange` is an abstract interface;
     concrete backends (in-process, Ray, MPI, ZMQ) plug in via subclassing.
  2. Bitwise reproducibility. A sharded N-step run must produce the same final
     lattice as a monolithic N-step run on the same initial state, given the
     same step function and periodic boundary conditions.
  3. Numpy-only in the core. Stays transport-agnostic AND compute-agnostic; a
     CuPy-backed step_fn can feed in GPU arrays via `.get()` at the halo
     boundary, or we add a `xp` parameter later.

Halo width == max radius of any kernel that operates on the lattice. For
Phase 17a magnon at 512³ (R=32), halo_width=32. For cheap per-step CA
transitions (R=1), a 1-voxel halo suffices. Multi-radius halos at different
exchange cadences are a future optimization; this module ships a single
uniform halo width.
"""

from __future__ import annotations

import struct
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

ShardCoord = tuple[int, int, int]
Direction = tuple[int, int, int]  # each component in {-1, 0, 1}; (0,0,0) excluded for neighbors

NEIGHBOR_DIRECTIONS: list[Direction] = [
    (dx, dy, dz)
    for dx in (-1, 0, 1)
    for dy in (-1, 0, 1)
    for dz in (-1, 0, 1)
    if (dx, dy, dz) != (0, 0, 0)
]
assert len(NEIGHBOR_DIRECTIONS) == 26


@dataclass(frozen=True)
class ShardLayout:
    """Immutable description of how the global lattice is partitioned."""

    global_shape: tuple[int, int, int]
    shard_grid: tuple[int, int, int]
    halo_width: int
    memory_channels: int = 8

    def __post_init__(self):
        for axis, (g, s) in enumerate(zip(self.global_shape, self.shard_grid)):
            if g % s != 0:
                raise ValueError(
                    f"global_shape[{axis}]={g} not divisible by shard_grid[{axis}]={s}"
                )
            if g // s < self.halo_width:
                raise ValueError(
                    f"interior axis {axis} ({g // s}) smaller than halo_width "
                    f"({self.halo_width}); halo would wrap across neighbors"
                )

    @property
    def interior_shape(self) -> tuple[int, int, int]:
        return tuple(g // s for g, s in zip(self.global_shape, self.shard_grid))  # type: ignore[return-value]

    @property
    def total_shape(self) -> tuple[int, int, int]:
        h = self.halo_width
        return tuple(i + 2 * h for i in self.interior_shape)  # type: ignore[return-value]

    def all_coords(self) -> list[ShardCoord]:
        Sx, Sy, Sz = self.shard_grid
        return [(x, y, z) for x in range(Sx) for y in range(Sy) for z in range(Sz)]

    def neighbor_coord(self, coord: ShardCoord, direction: Direction) -> ShardCoord:
        """Periodic neighbor lookup. Non-periodic BCs can be added via a flag later."""
        return tuple(
            (c + d) % s for c, d, s in zip(coord, direction, self.shard_grid)
        )  # type: ignore[return-value]


def _slab_slice(
    direction_component: int, interior_len: int, halo: int, *, region: str
) -> slice:
    """Return the 1D slice for one axis of a halo or interior-boundary slab.

    region='interior_boundary' → the first/last `halo` voxels of interior (sent to neighbor).
    region='halo'              → the halo region on the -1 / +1 side of the array.
    For direction_component == 0: the full interior range (orthogonal to send direction).
    """
    if direction_component == 0:
        return slice(halo, halo + interior_len)
    if region == "interior_boundary":
        if direction_component == -1:
            return slice(halo, halo + halo)
        return slice(halo + interior_len - halo, halo + interior_len)
    if region == "halo":
        if direction_component == -1:
            return slice(0, halo)
        return slice(halo + interior_len, halo + interior_len + halo)
    raise ValueError(f"unknown region: {region}")


def interior_boundary_slab(layout: ShardLayout, direction: Direction) -> tuple[slice, slice, slice]:
    """Slice of this shard's interior that will be SENT to the neighbor in `direction`."""
    h = self_halo = layout.halo_width
    Lx, Ly, Lz = layout.interior_shape
    return (
        _slab_slice(direction[0], Lx, h, region="interior_boundary"),
        _slab_slice(direction[1], Ly, h, region="interior_boundary"),
        _slab_slice(direction[2], Lz, h, region="interior_boundary"),
    )


def halo_slab(layout: ShardLayout, direction: Direction) -> tuple[slice, slice, slice]:
    """Slice of this shard's halo region on the side facing the neighbor in `direction`."""
    h = layout.halo_width
    Lx, Ly, Lz = layout.interior_shape
    return (
        _slab_slice(direction[0], Lx, h, region="halo"),
        _slab_slice(direction[1], Ly, h, region="halo"),
        _slab_slice(direction[2], Lz, h, region="halo"),
    )


@dataclass
class ShardState:
    """One shard's local arrays, including halo regions."""

    coord: ShardCoord
    layout: ShardLayout
    state: np.ndarray       # uint8, shape = layout.total_shape
    memory_grid: np.ndarray # float32, shape = (memory_channels, *layout.total_shape)
    generation: int = 0

    def __post_init__(self):
        expected = self.layout.total_shape
        if self.state.shape != expected:
            raise ValueError(f"state shape {self.state.shape} != expected {expected}")
        mem_expected = (self.layout.memory_channels, *expected)
        if self.memory_grid.shape != mem_expected:
            raise ValueError(
                f"memory_grid shape {self.memory_grid.shape} != expected {mem_expected}"
            )

    def interior_slice(self) -> tuple[slice, slice, slice]:
        h = self.layout.halo_width
        Lx, Ly, Lz = self.layout.interior_shape
        return (slice(h, h + Lx), slice(h, h + Ly), slice(h, h + Lz))

    def interior_state(self) -> np.ndarray:
        return self.state[self.interior_slice()]

    def interior_memory(self) -> np.ndarray:
        return self.memory_grid[(slice(None),) + self.interior_slice()]


# -- wire format ---------------------------------------------------------------

# Packet binary layout:
#   header:
#     magic              (4s, b"SHD1")
#     source_coord       (3i)
#     target_coord       (3i)
#     direction          (3b)
#     generation         (q)
#     state_dtype_code   (B, 0=uint8)
#     memory_dtype_code  (B, 0=float32)
#     state_shape        (3I)
#     memory_shape       (4I, channels + 3 spatial dims)
#   payload:
#     state bytes (state_shape product * 1)
#     memory bytes (memory_shape product * 4)

_HEADER_FMT = ">4s 3i 3i 3b q B B 3I 4I"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)


@dataclass
class HaloPacket:
    source_coord: ShardCoord
    target_coord: ShardCoord
    direction: Direction
    generation: int
    state_slab: np.ndarray        # dtype uint8, contiguous
    memory_slab: np.ndarray       # dtype float32, contiguous

    def to_bytes(self) -> bytes:
        if self.state_slab.dtype != np.uint8:
            raise TypeError(f"state_slab must be uint8, got {self.state_slab.dtype}")
        if self.memory_slab.dtype != np.float32:
            raise TypeError(f"memory_slab must be float32, got {self.memory_slab.dtype}")
        state = np.ascontiguousarray(self.state_slab)
        memory = np.ascontiguousarray(self.memory_slab)
        if state.ndim != 3:
            raise ValueError(f"state_slab must be 3D, got {state.ndim}D")
        if memory.ndim != 4:
            raise ValueError(f"memory_slab must be 4D (channel + 3 spatial), got {memory.ndim}D")
        header = struct.pack(
            _HEADER_FMT,
            b"SHD1",
            *self.source_coord,
            *self.target_coord,
            *self.direction,
            self.generation,
            0,  # state dtype code: uint8
            0,  # memory dtype code: float32
            *state.shape,
            *memory.shape,
        )
        return header + state.tobytes() + memory.tobytes()

    @classmethod
    def from_bytes(cls, buf: bytes) -> "HaloPacket":
        (
            magic,
            sx, sy, sz,
            tx, ty, tz,
            dx, dy, dz,
            generation,
            state_code,
            memory_code,
            ssx, ssy, ssz,
            msc, msx, msy, msz,
        ) = struct.unpack(_HEADER_FMT, buf[:_HEADER_SIZE])
        if magic != b"SHD1":
            raise ValueError(f"bad magic {magic!r}; expected b'SHD1'")
        if state_code != 0 or memory_code != 0:
            raise ValueError(f"unsupported dtype codes state={state_code} memory={memory_code}")
        offset = _HEADER_SIZE
        state_size = ssx * ssy * ssz
        state = np.frombuffer(buf, dtype=np.uint8, count=state_size, offset=offset).reshape(
            (ssx, ssy, ssz)
        ).copy()
        offset += state_size
        memory_count = msc * msx * msy * msz
        memory = np.frombuffer(buf, dtype=np.float32, count=memory_count, offset=offset).reshape(
            (msc, msx, msy, msz)
        ).copy()
        return cls(
            source_coord=(sx, sy, sz),
            target_coord=(tx, ty, tz),
            direction=(dx, dy, dz),
            generation=generation,
            state_slab=state,
            memory_slab=memory,
        )


# -- transport interface -------------------------------------------------------


class HaloExchange(ABC):
    """Abstract transport for halo packets. Subclass with a concrete backend."""

    @abstractmethod
    def send(self, packet: HaloPacket) -> None: ...

    @abstractmethod
    def recv_all(self, target: ShardCoord) -> list[HaloPacket]: ...

    @abstractmethod
    def barrier(self) -> None: ...


class InProcessHaloExchange(HaloExchange):
    """Reference backend: all shards in one process, queues for send/recv.

    Used for protocol validation and as a baseline for the distributed-step
    == monolithic-step test. Not intended for production.
    """

    def __init__(self) -> None:
        self._inbox: dict[ShardCoord, list[HaloPacket]] = defaultdict(list)

    def register(self, coord: ShardCoord) -> None:
        self._inbox.setdefault(coord, [])

    def send(self, packet: HaloPacket) -> None:
        self._inbox[packet.target_coord].append(packet)

    def recv_all(self, target: ShardCoord) -> list[HaloPacket]:
        packets = self._inbox[target]
        self._inbox[target] = []
        return packets

    def barrier(self) -> None:
        # Synchronous in-process; sends are already complete by the time send() returns.
        pass


# -- coordinator ---------------------------------------------------------------


StepFn = Callable[[np.ndarray, np.ndarray, int], tuple[np.ndarray, np.ndarray]]
"""step_fn(state, memory_grid, generation) -> (new_state, new_memory_grid).

Operates on arrays that INCLUDE halo regions; the coordinator keeps only the
interior of the output and refreshes halo on the next step.
"""


class StepCoordinator:
    """Orchestrates one step of one shard: send halos → apply halos → step locally."""

    def __init__(self, shard: ShardState, exchange: HaloExchange, step_fn: StepFn):
        self.shard = shard
        self.exchange = exchange
        self.step_fn = step_fn

    def send_halos(self) -> None:
        for direction in NEIGHBOR_DIRECTIONS:
            target = self.shard.layout.neighbor_coord(self.shard.coord, direction)
            sl = interior_boundary_slab(self.shard.layout, direction)
            state_slab = self.shard.state[sl].copy()
            memory_slab = self.shard.memory_grid[(slice(None),) + sl].copy()
            self.exchange.send(
                HaloPacket(
                    source_coord=self.shard.coord,
                    target_coord=target,
                    direction=direction,
                    generation=self.shard.generation,
                    state_slab=state_slab,
                    memory_slab=memory_slab,
                )
            )

    def apply_halos(self) -> None:
        for packet in self.exchange.recv_all(self.shard.coord):
            # packet.direction is source→target. The receiving halo is on the side
            # facing the source, which is the NEGATION of packet.direction.
            incoming_side = tuple(-d for d in packet.direction)  # type: ignore[assignment]
            sl = halo_slab(self.shard.layout, incoming_side)
            self.shard.state[sl] = packet.state_slab
            self.shard.memory_grid[(slice(None),) + sl] = packet.memory_slab

    def step_local(self) -> None:
        new_state, new_memory = self.step_fn(
            self.shard.state, self.shard.memory_grid, self.shard.generation
        )
        if new_state.shape != self.shard.state.shape:
            raise ValueError(
                f"step_fn changed state shape {self.shard.state.shape} → {new_state.shape}"
            )
        if new_memory.shape != self.shard.memory_grid.shape:
            raise ValueError(
                f"step_fn changed memory shape {self.shard.memory_grid.shape} → {new_memory.shape}"
            )
        self.shard.state = new_state
        self.shard.memory_grid = new_memory
        self.shard.generation += 1


def run_sharded_step(
    coordinators: list[StepCoordinator], exchange: HaloExchange
) -> None:
    """Advance every shard by one generation. Two-phase to avoid race conditions."""
    for c in coordinators:
        c.send_halos()
    exchange.barrier()
    for c in coordinators:
        c.apply_halos()
    for c in coordinators:
        c.step_local()


# -- split / assemble ----------------------------------------------------------


def split_lattice(
    global_state: np.ndarray,
    global_memory: np.ndarray,
    shard_grid: tuple[int, int, int],
    halo_width: int,
) -> tuple[ShardLayout, dict[ShardCoord, ShardState]]:
    """Partition a global lattice into shards with halos populated from neighbors (periodic)."""
    if global_state.dtype != np.uint8:
        raise TypeError(f"global_state must be uint8, got {global_state.dtype}")
    if global_memory.dtype != np.float32:
        raise TypeError(f"global_memory must be float32, got {global_memory.dtype}")
    if global_state.ndim != 3:
        raise ValueError(f"global_state must be 3D, got {global_state.ndim}D")
    if global_memory.ndim != 4 or global_memory.shape[1:] != global_state.shape:
        raise ValueError(
            f"global_memory shape {global_memory.shape} inconsistent with state shape {global_state.shape}"
        )

    layout = ShardLayout(
        global_shape=global_state.shape,  # type: ignore[arg-type]
        shard_grid=shard_grid,
        halo_width=halo_width,
        memory_channels=global_memory.shape[0],
    )
    Lx, Ly, Lz = layout.interior_shape
    h = layout.halo_width
    shards: dict[ShardCoord, ShardState] = {}

    # Periodic padding makes halo extraction a simple slice.
    padded_state = np.pad(global_state, h, mode="wrap")
    padded_memory = np.pad(global_memory, ((0, 0), (h, h), (h, h), (h, h)), mode="wrap")

    for coord in layout.all_coords():
        x0 = coord[0] * Lx
        y0 = coord[1] * Ly
        z0 = coord[2] * Lz
        state = padded_state[x0 : x0 + Lx + 2 * h, y0 : y0 + Ly + 2 * h, z0 : z0 + Lz + 2 * h].copy()
        memory = padded_memory[
            :, x0 : x0 + Lx + 2 * h, y0 : y0 + Ly + 2 * h, z0 : z0 + Lz + 2 * h
        ].copy()
        shards[coord] = ShardState(
            coord=coord,
            layout=layout,
            state=state,
            memory_grid=memory,
        )
    return layout, shards


def assemble_lattice(
    layout: ShardLayout, shards: dict[ShardCoord, ShardState]
) -> tuple[np.ndarray, np.ndarray]:
    """Collect all shard interiors into a single global lattice."""
    global_state = np.empty(layout.global_shape, dtype=np.uint8)
    global_memory = np.empty(
        (layout.memory_channels,) + layout.global_shape, dtype=np.float32
    )
    Lx, Ly, Lz = layout.interior_shape
    for coord, shard in shards.items():
        x0, y0, z0 = coord[0] * Lx, coord[1] * Ly, coord[2] * Lz
        global_state[x0 : x0 + Lx, y0 : y0 + Ly, z0 : z0 + Lz] = shard.interior_state()
        global_memory[:, x0 : x0 + Lx, y0 : y0 + Ly, z0 : z0 + Lz] = shard.interior_memory()
    return global_state, global_memory


__all__ = [
    "ShardCoord",
    "Direction",
    "NEIGHBOR_DIRECTIONS",
    "ShardLayout",
    "ShardState",
    "HaloPacket",
    "HaloExchange",
    "InProcessHaloExchange",
    "StepCoordinator",
    "StepFn",
    "run_sharded_step",
    "split_lattice",
    "assemble_lattice",
    "interior_boundary_slab",
    "halo_slab",
]
