"""Tests for scripts/shard_transport_zmq.py — ZMQ backend for the shard protocol.

Two scopes:
  1. Single-process sanity: one ZMQHaloExchange wired to itself, prove the
     send/recv plumbing works (exercises self-loop short-circuit).
  2. Two-process integration: spawn two subprocesses, each owning one shard of
     a (2,1,1) partition. Run the sharded protocol over real ZMQ sockets and
     assert the assembled result is bitwise-identical to a monolithic run.
     This is the correctness proof that the ZMQ transport delivers halos
     correctly across a real process boundary.
"""

from __future__ import annotations

import itertools
import pickle
import subprocess
import sys
import textwrap
import threading
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pytest

try:
    import zmq  # noqa: F401
except ImportError:
    pytest.skip("pyzmq not installed", allow_module_level=True)

import scripts.shard_transport_zmq as shard_transport_zmq
from scripts.shard_protocol import (
    HaloPacket,
    StepCoordinator,
    assemble_lattice,
    run_sharded_step,
    split_lattice,
)
from scripts.shard_transport_zmq import PACKETS_PER_SHARD_PER_STEP, ZMQHaloExchange


REPO_ROOT = Path(__file__).resolve().parent.parent


def _neighbor_count_step(state, memory, generation):
    """Same step_fn used by test_shard_protocol's correctness proof."""
    mask = (state == 1).astype(np.float32)
    total = np.zeros_like(mask)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                total += np.roll(np.roll(np.roll(mask, dx, 0), dy, 1), dz, 2)
    new_memory = memory.copy()
    new_memory[0] = total
    return state.copy(), new_memory


# -- single-process sanity ---------------------------------------------------


def test_single_process_self_owned_coords_equals_monolithic():
    """One process owns *all* coords → every send is a self-loop → protocol
    must still produce the correct result. Exercises the self-loop inbox.
    """
    rng = np.random.default_rng(77)
    state = rng.integers(0, 5, size=(8, 8, 8), dtype=np.uint8)
    memory = rng.random(size=(8, 8, 8, 8), dtype=np.float32)

    # Monolithic baseline.
    mono_state, mono_memory = state.copy(), memory.copy()
    for _ in range(3):
        mono_state, mono_memory = _neighbor_count_step(mono_state, mono_memory, 0)

    # Sharded via ZMQ, but all coords owned by this one process → no wire traffic.
    layout, shards = split_lattice(state, memory, shard_grid=(2, 2, 2), halo_width=1)
    endpoints = {
        coord: f"inproc://self-test-{coord[0]}-{coord[1]}-{coord[2]}"
        for coord in layout.all_coords()
    }
    with ZMQHaloExchange(own_coords=layout.all_coords(), endpoints=endpoints) as exchange:
        coords_in_order = layout.all_coords()
        coordinators = [
            StepCoordinator(shards[c], exchange, _neighbor_count_step) for c in coords_in_order
        ]
        for _ in range(3):
            run_sharded_step(coordinators, exchange)

        assembled_state, assembled_memory = assemble_lattice(
            layout, {c.shard.coord: c.shard for c in coordinators}
        )

    np.testing.assert_array_equal(assembled_state, mono_state)
    np.testing.assert_array_equal(assembled_memory, mono_memory)


def test_zmq_exchange_rejects_unknown_own_coord():
    with pytest.raises(ValueError, match="not in endpoints map"):
        ZMQHaloExchange(
            own_coords={(9, 9, 9)},
            endpoints={(0, 0, 0): "inproc://nope"},
        )


def test_zmq_exchange_rejects_recv_for_non_owned():
    with ZMQHaloExchange(
        own_coords={(0, 0, 0)},
        endpoints={(0, 0, 0): "inproc://own"},
    ) as exchange:
        with pytest.raises(ValueError, match="non-owned"):
            exchange.recv_all((1, 0, 0))


# -- two-process integration -------------------------------------------------

# Worker script. Each spawned process imports the protocol, deterministically
# rebuilds the initial lattice from a known seed, runs N sharded steps over
# ZMQ, and pickles its interior arrays to a shared temp file.
_WORKER_SOURCE = textwrap.dedent("""
    import pickle
    import sys
    from pathlib import Path

    repo_root = sys.argv[1]
    sys.path.insert(0, repo_root)

    import numpy as np
    from scripts.shard_protocol import StepCoordinator, split_lattice
    from scripts.shard_transport_zmq import ZMQHaloExchange

    own_coord = tuple(int(x) for x in sys.argv[2].split(","))
    endpoints = pickle.loads(bytes.fromhex(sys.argv[3]))
    n_steps = int(sys.argv[4])
    out_path = Path(sys.argv[5])
    seed = int(sys.argv[6])

    rng = np.random.default_rng(seed)
    state = rng.integers(0, 5, size=(8, 4, 4), dtype=np.uint8)
    memory = rng.random(size=(8, 8, 4, 4), dtype=np.float32)

    layout, shards = split_lattice(state, memory, shard_grid=(2, 1, 1), halo_width=1)
    shard = shards[own_coord]

    def step_fn(st, mem, gen):
        mask = (st == 1).astype(np.float32)
        total = np.zeros_like(mask)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    total += np.roll(np.roll(np.roll(mask, dx, 0), dy, 1), dz, 2)
        new_memory = mem.copy()
        new_memory[0] = total
        return st.copy(), new_memory

    with ZMQHaloExchange(own_coords={own_coord}, endpoints=endpoints) as exchange:
        coord = StepCoordinator(shard, exchange, step_fn)
        for _ in range(n_steps):
            coord.send_halos()
            coord.apply_halos()
            coord.step_local()
        interior_state = shard.interior_state().copy()
        interior_memory = shard.interior_memory().copy()

    with open(out_path, "wb") as f:
        pickle.dump(
            {"coord": own_coord, "state": interior_state, "memory": interior_memory}, f
        )
""")


def _pick_free_ports(n):
    """Grab N free local TCP ports by binding+immediately closing."""
    import socket

    ports = []
    socks = []
    try:
        for _ in range(n):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("127.0.0.1", 0))
            ports.append(s.getsockname()[1])
            socks.append(s)
    finally:
        for s in socks:
            s.close()
    return ports


def test_zmq_two_process_halo_exchange_equals_monolithic(tmp_path):
    """The key correctness proof for the ZMQ transport: two processes,
    each owning one shard of a (2,1,1) partition, step 3 generations over
    real ZMQ sockets, and produce a combined result that matches a monolithic
    run bitwise."""
    seed = 2024
    n_steps = 3

    # Allocate two ports that the OS just told us were free.
    ports = _pick_free_ports(2)
    endpoints = {
        (0, 0, 0): f"tcp://127.0.0.1:{ports[0]}",
        (1, 0, 0): f"tcp://127.0.0.1:{ports[1]}",
    }
    endpoints_hex = pickle.dumps(endpoints).hex()

    # Write worker script into tmp_path so subprocesses can import it via path.
    worker_script = tmp_path / "zmq_worker.py"
    worker_script.write_text(_WORKER_SOURCE)

    out_a = tmp_path / "shard_000.pkl"
    out_b = tmp_path / "shard_100.pkl"

    procs = []
    for coord_str, out in [("0,0,0", out_a), ("1,0,0", out_b)]:
        p = subprocess.Popen(
            [
                sys.executable,
                str(worker_script),
                str(REPO_ROOT),
                coord_str,
                endpoints_hex,
                str(n_steps),
                str(out),
                str(seed),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        procs.append(p)

    deadline = time.monotonic() + 60.0
    for i, p in enumerate(procs):
        timeout = max(1.0, deadline - time.monotonic())
        try:
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            stderr = p.stderr.read().decode(errors="replace")
            pytest.fail(f"worker {i} timed out after {timeout:.1f}s\nstderr:\n{stderr}")
        if rc != 0:
            stderr = p.stderr.read().decode(errors="replace")
            stdout = p.stdout.read().decode(errors="replace")
            pytest.fail(
                f"worker {i} failed with rc={rc}\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )

    with open(out_a, "rb") as f:
        result_a = pickle.load(f)
    with open(out_b, "rb") as f:
        result_b = pickle.load(f)
    assert result_a["coord"] == (0, 0, 0)
    assert result_b["coord"] == (1, 0, 0)

    # Assemble along x (axis 0 for state, axis 1 for 8-channel memory).
    zmq_state = np.concatenate([result_a["state"], result_b["state"]], axis=0)
    zmq_memory = np.concatenate([result_a["memory"], result_b["memory"]], axis=1)

    # Monolithic baseline, same seed.
    rng = np.random.default_rng(seed)
    mono_state = rng.integers(0, 5, size=(8, 4, 4), dtype=np.uint8)
    mono_memory = rng.random(size=(8, 8, 4, 4), dtype=np.float32)
    for _ in range(n_steps):
        mono_state, mono_memory = _neighbor_count_step(mono_state, mono_memory, 0)

    np.testing.assert_array_equal(zmq_state, mono_state)
    np.testing.assert_array_equal(zmq_memory, mono_memory)


# -- recv_all failure atomicity ----------------------------------------------
#
# `recv_all` extracts the local inbox and clears it before the barrier count is
# reached, so an exceptional exit past that point used to drop every packet held
# in hand. PUSH/PULL delivers each frame exactly once, so those packets are never
# re-sent. These tests drive the GENUINE `recv_all` implementation; only the
# socket and the clock are faked — no real TCP port, subprocess, sleep, network,
# engine, GPU work or repository data is involved.

_OWN = (0, 0, 0)
_INPROC_SEQ = itertools.count()


class _FakePull:
    """Stands in for the bound PULL socket.

    `script` is replayed one entry per `recv()`: `bytes` are returned as a wire
    frame, a `BaseException` instance is raised. Once exhausted, `recv()` raises
    `zmq.Again` — the same signal a real socket gives when `RCVTIMEO` expires.
    """

    def __init__(self, script=(), on_exhausted=None, observe=None):
        self.script = list(script)
        self.on_exhausted = on_exhausted
        self.observe = observe
        self.opts = {}
        self.recv_calls = 0

    def setsockopt(self, opt, value):
        self.opts[opt] = value

    def recv(self):
        self.recv_calls += 1
        if self.observe is not None:
            self.observe()
        if not self.script:
            if self.on_exhausted is not None:
                self.on_exhausted()
            raise zmq.Again()
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self, linger=None):
        pass


class _FakeClock:
    """Deterministic stand-in for the module's `time`; never sleeps."""

    def __init__(self, start=1_000.0):
        self.t = start

    def monotonic(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def _packet(generation, target=_OWN):
    """A real `HaloPacket`, tagged by `generation` so it stays identifiable."""
    return HaloPacket(
        source_coord=(9, 9, 9),
        target_coord=target,
        direction=(1, 0, 0),
        generation=generation,
        state_slab=np.full((1, 1, 1), generation % 256, dtype=np.uint8),
        memory_slab=np.full((1, 1, 1, 1), float(generation), dtype=np.float32),
    )


def _gens(packets):
    return [p.generation for p in packets]


def _wired_exchange(monkeypatch, script=(), timeout_ms=10_000):
    """A real `ZMQHaloExchange` whose PULL socket and clock are faked."""
    endpoint = f"inproc://recv-atomicity-{next(_INPROC_SEQ)}"
    exchange = ZMQHaloExchange(
        own_coords={_OWN},
        endpoints={_OWN: endpoint},
        recv_timeout_ms=timeout_ms,
    )
    exchange._pulls[_OWN].close(linger=0)  # release the genuinely bound socket
    pull = _FakePull(script)
    exchange._pulls[_OWN] = pull
    clock = _FakeClock()
    monkeypatch.setattr(shard_transport_zmq, "time", clock)
    return exchange, pull, clock


class _SentinelError(Exception):
    """Distinct type so the propagated object can be identity-checked."""


class _ExplodingClock:
    """Clock boundary that fails on the very first `monotonic()` call, i.e.
    while the initial deadline is being constructed."""

    def __init__(self, error):
        self.error = error

    def monotonic(self):
        raise self.error


class _RaisingPulls(dict):
    """PULL-registry boundary whose lookup fails.

    Subclasses `dict` so `close()` still finds working `values()`/`clear()`.
    """

    def __init__(self, error):
        super().__init__()
        self.error = error

    def __getitem__(self, key):
        raise self.error


def test_recv_all_restores_packets_when_deadline_construction_fails(monkeypatch):
    """The protected interval starts at the inbox clear, not at the loop: a
    failure while building the initial deadline must still restore packets."""
    exchange, pull, clock = _wired_exchange(monkeypatch)
    for gen in (0, 1, 2):
        exchange.send(_packet(gen))
    sentinel = _SentinelError("clock unavailable")
    monkeypatch.setattr(shard_transport_zmq, "time", _ExplodingClock(sentinel))

    with pytest.raises(_SentinelError) as excinfo:
        exchange.recv_all(_OWN)

    assert excinfo.value is sentinel  # identical object, unwrapped
    assert _gens(exchange._local_inbox[_OWN]) == [0, 1, 2]
    exchange.close()


def test_recv_all_restores_packets_when_pull_lookup_fails(monkeypatch):
    """A `_pulls[target]` lookup failure occurs after extraction but before the
    loop; the packets must still come back in order."""
    exchange, pull, clock = _wired_exchange(monkeypatch)
    for gen in (0, 1, 2):
        exchange.send(_packet(gen))
    sentinel = _SentinelError("pull socket missing")
    exchange._pulls = _RaisingPulls(sentinel)

    with pytest.raises(_SentinelError) as excinfo:
        exchange.recv_all(_OWN)

    assert excinfo.value is sentinel  # identical object, unwrapped
    assert _gens(exchange._local_inbox[_OWN]) == [0, 1, 2]
    exchange.close()


def test_recv_all_restores_local_and_decoded_packets_on_timeout(monkeypatch):
    """Regression: a timeout must hand back the local packets AND every wire
    packet already decoded during the same call."""
    wire = [_packet(100).to_bytes(), _packet(101).to_bytes()]
    exchange, pull, clock = _wired_exchange(monkeypatch, wire, timeout_ms=1_000)
    pull.on_exhausted = lambda: clock.advance(2.0)  # blow past the deadline
    for gen in (0, 1, 2):
        exchange.send(_packet(gen))

    with pytest.raises(TimeoutError, match="5/26 packets received"):
        exchange.recv_all(_OWN)

    assert _gens(exchange._local_inbox[_OWN]) == [0, 1, 2, 100, 101]
    exchange.close()


def test_recv_all_timeout_then_retry_completes_the_barrier(monkeypatch):
    """Regression: after a timeout, a retry supplied with only the genuine
    remaining packets can still satisfy the per-step barrier."""
    exchange, pull, clock = _wired_exchange(
        monkeypatch, [_packet(100).to_bytes(), _packet(101).to_bytes()], timeout_ms=1_000
    )
    pull.on_exhausted = lambda: clock.advance(2.0)
    for gen in (0, 1, 2):
        exchange.send(_packet(gen))

    with pytest.raises(TimeoutError):
        exchange.recv_all(_OWN)

    # The peer now delivers only what it still owed — nothing is re-sent.
    remaining = PACKETS_PER_SHARD_PER_STEP - 5
    pull.script = [_packet(200 + i).to_bytes() for i in range(remaining)]
    pull.on_exhausted = None
    clock.t = 1_000.0

    out = exchange.recv_all(_OWN)

    assert len(out) == PACKETS_PER_SHARD_PER_STEP
    assert _gens(out) == [0, 1, 2, 100, 101] + [200 + i for i in range(remaining)]
    assert exchange._local_inbox[_OWN] == []
    exchange.close()


def test_recv_all_retry_returns_each_packet_exactly_once(monkeypatch):
    """No retained or newly received packet may be duplicated by the retry."""
    exchange, pull, clock = _wired_exchange(
        monkeypatch, [_packet(100).to_bytes()], timeout_ms=1_000
    )
    pull.on_exhausted = lambda: clock.advance(2.0)
    for gen in (0, 1, 2):
        exchange.send(_packet(gen))

    with pytest.raises(TimeoutError):
        exchange.recv_all(_OWN)

    remaining = PACKETS_PER_SHARD_PER_STEP - 4
    pull.script = [_packet(200 + i).to_bytes() for i in range(remaining)]
    pull.on_exhausted = None
    clock.t = 1_000.0

    out = exchange.recv_all(_OWN)

    seen = _gens(out)
    assert len(seen) == len(set(seen)) == PACKETS_PER_SHARD_PER_STEP
    assert exchange._local_inbox[_OWN] == []
    exchange.close()


def test_recv_all_malformed_frame_restores_valid_packets_only(monkeypatch):
    """A `HaloPacket.from_bytes()` refusal propagates unchanged, prior valid
    packets come back, and the malformed raw frame is NOT restored."""
    bad_frame = b"nope"  # shorter than the fixed header
    exchange, pull, clock = _wired_exchange(
        monkeypatch, [_packet(100).to_bytes(), bad_frame, _packet(101).to_bytes()]
    )
    for gen in (0, 1, 2):
        exchange.send(_packet(gen))

    with pytest.raises(ValueError, match="frame shorter than the fixed header"):
        exchange.recv_all(_OWN)

    retained = exchange._local_inbox[_OWN]
    assert _gens(retained) == [0, 1, 2, 100]
    assert all(isinstance(p, HaloPacket) for p in retained)
    assert bad_frame not in retained  # the refused frame is discarded, not replayed
    exchange.close()


def test_recv_all_socket_failure_restores_valid_packets(monkeypatch):
    """A non-`zmq.Again` ZMQ error propagates unchanged and prior valid packets
    are restored."""
    failure = zmq.ZMQError(zmq.ETERM)
    assert not isinstance(failure, zmq.Again)
    exchange, pull, clock = _wired_exchange(
        monkeypatch, [_packet(100).to_bytes(), failure]
    )
    for gen in (0, 1, 2):
        exchange.send(_packet(gen))

    with pytest.raises(zmq.ZMQError) as excinfo:
        exchange.recv_all(_OWN)

    assert excinfo.value is failure  # class, message and traceback untouched
    assert _gens(exchange._local_inbox[_OWN]) == [0, 1, 2, 100]
    exchange.close()


# -- genuine concurrency: self-loop send vs. inbox handover -------------------
#
# Both local-inbox handovers replace the stored list wholesale:
#
#     packets = list(self._local_inbox[target]); self._local_inbox[target] = []
#     self._local_inbox[target] = packets + self._local_inbox[target]
#
# An unsynchronized `send()` append landing between the read and the store is
# discarded by the store. The two tests below drive that window from a real
# thread. They substitute only the inbox mapping — an existing dependency
# boundary — so the production `recv_all` under test is the genuine one.

# Bounded wait used at the assign point. An UNBOUNDED wait would deadlock by
# construction once the handover is serialized, because the concurrent `send()`
# is blocked on the very lock the handover holds. Expiry is therefore the
# expected, correct outcome; prompt return means the append was NOT serialized.
_ASSIGN_WINDOW_S = 0.25
_JOIN_S = 10.0


class _CoordinatedInbox(defaultdict):
    """`_local_inbox` view that exposes the read-then-store window.

    `on_assign` fires immediately before a replacement list is stored — exactly
    the instant at which a racing `send()` append would be lost. Only `recv_all`
    ever stores; `send()` appends in place, so the hook never fires on the
    worker thread.
    """

    def __init__(self, source):
        super().__init__(list, source)
        self.on_assign = None

    def __setitem__(self, key, value):
        if self.on_assign is not None:
            self.on_assign(key)
        super().__setitem__(key, value)


def _start_self_loop_sender(exchange, packet, release, done):
    """Thread that performs one self-loop `send()` once `release` is set."""

    def _worker():
        release.wait(_JOIN_S)
        exchange.send(packet)
        done.set()

    thread = threading.Thread(target=_worker, name="self-loop-sender", daemon=True)
    thread.start()
    return thread


def test_concurrent_self_loop_send_survives_inbox_extraction(monkeypatch):
    """Window 1 — a self-loop `send()` racing the extraction/clear at the start
    of `recv_all()` must not be lost."""
    wire = [_packet(100 + i).to_bytes() for i in range(PACKETS_PER_SHARD_PER_STEP - 3)]
    exchange, pull, clock = _wired_exchange(monkeypatch, wire)
    for gen in (0, 1, 2):
        exchange.send(_packet(gen))
    exchange._local_inbox = _CoordinatedInbox(exchange._local_inbox)

    release, done = threading.Event(), threading.Event()
    worker = _start_self_loop_sender(exchange, _packet(300), release, done)

    def _on_assign(key):
        # The extraction clear is the first (and here only) store.
        if not release.is_set():
            release.set()
            done.wait(_ASSIGN_WINDOW_S)

    exchange._local_inbox.on_assign = _on_assign

    out = exchange.recv_all(_OWN)
    worker.join(_JOIN_S)
    assert not worker.is_alive()

    # The barrier set is unaffected; the racing packet is retained for next step.
    assert _gens(out) == [0, 1, 2] + [
        100 + i for i in range(PACKETS_PER_SHARD_PER_STEP - 3)
    ]
    assert _gens(exchange._local_inbox[_OWN]) == [300]
    exchange.close()


def test_concurrent_self_loop_send_survives_exceptional_restoration(monkeypatch):
    """Window 2 — a self-loop `send()` racing the exceptional restoration must
    not be overwritten, and restored packets still precede it."""
    exchange, pull, clock = _wired_exchange(
        monkeypatch, [_packet(100).to_bytes()], timeout_ms=1_000
    )
    for gen in (0, 1, 2):
        exchange.send(_packet(gen))
    exchange._local_inbox = _CoordinatedInbox(exchange._local_inbox)

    armed = threading.Event()

    def _expire():
        clock.advance(2.0)  # force the deadline past, triggering TimeoutError
        armed.set()

    pull.on_exhausted = _expire

    release, done = threading.Event(), threading.Event()
    worker = _start_self_loop_sender(exchange, _packet(300), release, done)

    def _on_assign(key):
        # Ignore the extraction store; coordinate only on the restoration store.
        if armed.is_set() and not release.is_set():
            release.set()
            done.wait(_ASSIGN_WINDOW_S)

    exchange._local_inbox.on_assign = _on_assign

    with pytest.raises(TimeoutError):
        exchange.recv_all(_OWN)

    worker.join(_JOIN_S)
    assert not worker.is_alive()

    # Restored local packets, then the restored wire packet, then the racing
    # self-loop arrival — none lost, none duplicated.
    assert _gens(exchange._local_inbox[_OWN]) == [0, 1, 2, 100, 300]
    exchange.close()


def test_recv_all_again_continues_without_premature_restoration(monkeypatch):
    """`zmq.Again` stays an internal retry: the loop continues and nothing is
    handed back to the inbox while it is still running."""
    wire = [zmq.Again(), zmq.Again()] + [
        _packet(100 + i).to_bytes() for i in range(PACKETS_PER_SHARD_PER_STEP - 3)
    ]
    exchange, pull, clock = _wired_exchange(monkeypatch, wire)
    for gen in (0, 1, 2):
        exchange.send(_packet(gen))

    sizes = []
    pull.observe = lambda: sizes.append(len(exchange._local_inbox[_OWN]))

    out = exchange.recv_all(_OWN)

    assert len(out) == PACKETS_PER_SHARD_PER_STEP
    assert sizes and all(size == 0 for size in sizes)  # never restored mid-loop
    assert exchange._local_inbox[_OWN] == []
    exchange.close()


def test_recv_all_success_preserves_order_and_drains_inbox(monkeypatch):
    """The established success path is unchanged: local packets first, then wire
    packets in arrival order, and the inbox is left drained."""
    wire = [_packet(100 + i).to_bytes() for i in range(PACKETS_PER_SHARD_PER_STEP - 3)]
    exchange, pull, clock = _wired_exchange(monkeypatch, wire)
    for gen in (0, 1, 2):
        exchange.send(_packet(gen))

    out = exchange.recv_all(_OWN)

    assert len(out) == PACKETS_PER_SHARD_PER_STEP
    assert _gens(out) == [0, 1, 2] + [
        100 + i for i in range(PACKETS_PER_SHARD_PER_STEP - 3)
    ]
    assert exchange._local_inbox[_OWN] == []
    exchange.close()


def test_recv_all_closed_exchange_leaves_inbox_untouched(monkeypatch):
    """The closed-exchange guard fires before extraction, so nothing moves."""
    exchange, pull, clock = _wired_exchange(monkeypatch)
    for gen in (0, 1, 2):
        exchange.send(_packet(gen))
    exchange.close()

    with pytest.raises(RuntimeError, match="is closed"):
        exchange.recv_all(_OWN)

    assert _gens(exchange._local_inbox[_OWN]) == [0, 1, 2]


def test_recv_all_non_owned_target_leaves_inbox_untouched(monkeypatch):
    """The non-owned guard fires before extraction, so nothing moves."""
    exchange, pull, clock = _wired_exchange(monkeypatch)
    for gen in (0, 1, 2):
        exchange.send(_packet(gen))

    with pytest.raises(ValueError, match="non-owned"):
        exchange.recv_all((1, 0, 0))

    assert _gens(exchange._local_inbox[_OWN]) == [0, 1, 2]
    exchange.close()
