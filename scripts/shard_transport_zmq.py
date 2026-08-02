"""ZeroMQ transport backend for the shard protocol (Phase 17b, follow-up to PR #117).

Subclasses `HaloExchange` with a PUSH/PULL-backed implementation that lets shard
processes exchange halos across a real process boundary. Self-addressed halos
short-circuit through an in-memory inbox to avoid a needless loopback hop.

The core `scripts/shard_protocol` module has no zmq dependency; importing
this module is the only place pyzmq is required. A future Ray / MPI / raw-TCP
backend drops in as another sibling module — same pattern, no protocol change.

Requires: pyzmq >= 27.0.0
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Iterable, Mapping

import zmq

from scripts.shard_protocol import HaloExchange, HaloPacket, ShardCoord


# Each shard receives exactly one halo packet per neighbor direction per step.
# In periodic topologies where the shard grid is small along an axis (e.g. size 2
# gives both (-1) and (+1) the same target), multiple directions can share a
# source/target pair — but the coordinator still emits 26 packets per shard per
# step, and each shard still *receives* 26 total.
PACKETS_PER_SHARD_PER_STEP = 26

_DEFAULT_RECV_TIMEOUT_MS = 10_000
_DEFAULT_LINGER_MS = 500
_DEFAULT_HWM = 10_000


class ZMQHaloExchange(HaloExchange):
    """PUSH/PULL-backed halo exchange over ZeroMQ.

    Each participating process constructs one `ZMQHaloExchange` declaring:
      - `own_coords`: the shard coordinate(s) this process owns
      - `endpoints`: full map from every shard coord in the global topology
                     to a ZMQ endpoint string (e.g. "tcp://127.0.0.1:5550")

    For each owned coord the instance binds a PULL socket at its endpoint.
    For each non-owned coord it connects a PUSH socket. Halos addressed to
    an owned coord never hit the wire — they're routed through a local inbox.

    Use as a context manager (`with ZMQHaloExchange(...) as exchange:`) or
    call `close()` explicitly to release socket resources.
    """

    def __init__(
        self,
        own_coords: Iterable[ShardCoord],
        endpoints: Mapping[ShardCoord, str],
        *,
        recv_timeout_ms: int = _DEFAULT_RECV_TIMEOUT_MS,
        linger_ms: int = _DEFAULT_LINGER_MS,
        hwm: int = _DEFAULT_HWM,
        context: zmq.Context | None = None,
    ) -> None:
        self.own_coords: set[ShardCoord] = set(own_coords)
        self.endpoints: dict[ShardCoord, str] = dict(endpoints)
        missing = self.own_coords - set(self.endpoints)
        if missing:
            raise ValueError(f"own coord(s) {sorted(missing)} not in endpoints map")
        self.recv_timeout_ms = int(recv_timeout_ms)
        self._owns_context = context is None
        self.ctx: zmq.Context = context if context is not None else zmq.Context.instance()

        self._pulls: dict[ShardCoord, zmq.Socket] = {}
        self._pushes: dict[ShardCoord, zmq.Socket] = {}
        self._local_inbox: dict[ShardCoord, list[HaloPacket]] = defaultdict(list)
        # Serializes every local-inbox transition against a concurrent
        # self-loop `send()`. Held only for the O(1)/O(n) list handovers below —
        # never across a ZMQ call, a frame decode or the receive deadline.
        # Scope is the local inbox alone; see `recv_all` for what is NOT claimed.
        self._inbox_lock = threading.Lock()
        self._closed = False

        # Bind one PULL socket per owned coord.
        for coord in sorted(self.own_coords):
            sock = self.ctx.socket(zmq.PULL)
            sock.setsockopt(zmq.LINGER, linger_ms)
            sock.setsockopt(zmq.RCVHWM, hwm)
            sock.bind(self.endpoints[coord])
            self._pulls[coord] = sock

        # Connect one PUSH socket per non-own coord.
        for coord, addr in self.endpoints.items():
            if coord in self.own_coords:
                continue
            sock = self.ctx.socket(zmq.PUSH)
            sock.setsockopt(zmq.LINGER, linger_ms)
            sock.setsockopt(zmq.SNDHWM, hwm)
            sock.connect(addr)
            self._pushes[coord] = sock

    # ---- HaloExchange interface -------------------------------------------

    def send(self, packet: HaloPacket) -> None:
        if self._closed:
            raise RuntimeError("ZMQHaloExchange is closed")
        target = packet.target_coord
        if target in self.own_coords:
            # Self-loop: skip ZMQ entirely. Serialized against `recv_all`'s
            # extraction and restoration so an append can never be discarded by
            # a concurrent replacement of the inbox list.
            with self._inbox_lock:
                self._local_inbox[target].append(packet)
            return
        sock = self._pushes.get(target)
        if sock is None:
            raise ValueError(
                f"no PUSH socket for target {target}; endpoints: {sorted(self.endpoints)}"
            )
        sock.send(packet.to_bytes())

    def recv_all(self, target: ShardCoord) -> list[HaloPacket]:
        """Block until `PACKETS_PER_SHARD_PER_STEP` halos are gathered for `target`.

        Combines self-loop packets already in the local inbox with ZMQ-delivered
        packets. Raises `TimeoutError` if the full count isn't received within
        `recv_timeout_ms`. This is the implicit per-step barrier.

        Extracting the local inbox transfers packet ownership to this call, so
        an exceptional exit past that point would otherwise drop every packet
        held in hand — the local ones AND any already decoded off the wire.
        PUSH/PULL delivers each frame exactly once, so a dropped wire packet is
        never re-sent and the barrier can never be satisfied afterwards.

        The protected ownership interval therefore begins IMMEDIATELY after the
        stored inbox is cleared and covers everything up to the return: the
        `_pulls[target]` lookup, the initial deadline construction, timeout
        handling, socket operations and packet decoding. A cleanup-only handler
        hands the in-hand packets back to `_local_inbox[target]` before
        re-raising.

        Retention is bounded to packets this call had already accepted:

          - Restored packets are PREPENDED, so they precede any self-loop
            packet `send()` placed into the replacement inbox while the receive
            was in progress, and their relative order is preserved.
          - Packets are moved, never copied, so no later call can return a
            duplicate.
          - The exception is re-raised bare: class, message and traceback are
            untouched, and nothing is swallowed. `zmq.Again` stays an internal
            retry and never triggers restoration.
          - A frame `HaloPacket.from_bytes()` refuses is NOT restored or
            replayed — only previously valid packets are handed back. Malformed
            frames remain discarded, exactly as before.

        Both local-inbox handovers — the extraction/clear above and the
        restoration below — run under `_inbox_lock`, the same lock a self-loop
        `send()` takes around its append. Each handover replaces the stored list
        wholesale, so without that mutual exclusion an append landing between
        the read and the store would be silently dropped. The lock is released
        before the gather loop and is NEVER held across a ZMQ call, a frame
        decode or the receive deadline.

        The claim is bounded to retention across an exceptional receive exit and
        to serializing local-inbox transitions against self-loop `send()`.
        Cleanup is not claimed to be total under a SECOND failure (e.g. an
        allocation failure during restoration itself), and this changes no
        caller retry policy, generation validation, or over-delivery behaviour.
        Broader thread-safety is explicitly NOT claimed: the PULL/PUSH sockets,
        `close()` and the rest of the object lifecycle remain unsynchronized,
        and concurrent `recv_all()` calls for the same target are unsupported.
        """
        if self._closed:
            raise RuntimeError("ZMQHaloExchange is closed")
        if target not in self.own_coords:
            raise ValueError(f"cannot recv for non-owned coord {target}")
        with self._inbox_lock:
            packets = list(self._local_inbox[target])
            self._local_inbox[target] = []
        try:
            pull = self._pulls[target]
            deadline = time.monotonic() + self.recv_timeout_ms / 1000.0
            while len(packets) < PACKETS_PER_SHARD_PER_STEP:
                remaining_ms = int((deadline - time.monotonic()) * 1000)
                if remaining_ms <= 0:
                    raise TimeoutError(
                        f"ZMQHaloExchange.recv_all timed out for {target} "
                        f"({len(packets)}/{PACKETS_PER_SHARD_PER_STEP} packets received)"
                    )
                pull.setsockopt(zmq.RCVTIMEO, remaining_ms)
                try:
                    buf = pull.recv()
                except zmq.Again:
                    continue
                packets.append(HaloPacket.from_bytes(buf))
        except BaseException:
            # Cleanup only — give back what this call took, then propagate.
            # The read/concatenate/store is one critical section, so a self-loop
            # append racing this handover is never overwritten: it either lands
            # before the read (and is preserved after the restored packets) or
            # after the store (and is appended to the restored list).
            with self._inbox_lock:
                self._local_inbox[target] = packets + self._local_inbox[target]
            raise
        return packets

    def barrier(self) -> None:
        # No explicit barrier needed — recv_all blocks until the per-shard
        # expected count is reached, which serves as the per-step rendezvous.
        pass

    # ---- lifecycle --------------------------------------------------------

    def close(self) -> None:
        if self._closed:
            return
        for sock in list(self._pulls.values()) + list(self._pushes.values()):
            try:
                sock.close(linger=_DEFAULT_LINGER_MS)
            except Exception:
                pass
        self._pulls.clear()
        self._pushes.clear()
        if self._owns_context:
            # `zmq.Context.instance()` returns a shared context; don't terminate it.
            pass
        self._closed = True

    def __enter__(self) -> "ZMQHaloExchange":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


__all__ = ["ZMQHaloExchange", "PACKETS_PER_SHARD_PER_STEP"]
