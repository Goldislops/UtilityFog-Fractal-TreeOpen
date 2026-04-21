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

import pickle
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import numpy as np
import pytest

try:
    import zmq  # noqa: F401
except ImportError:
    pytest.skip("pyzmq not installed", allow_module_level=True)

from scripts.shard_protocol import (
    StepCoordinator,
    assemble_lattice,
    run_sharded_step,
    split_lattice,
)
from scripts.shard_transport_zmq import ZMQHaloExchange


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
