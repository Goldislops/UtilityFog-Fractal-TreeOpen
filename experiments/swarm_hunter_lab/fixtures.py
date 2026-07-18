"""Deterministic synthetic fixtures for the ten S0 §7 rows.

Every builder returns fully valid snapshot dicts (states + verified
provenance) built with the lab's own canonical hashing — no RNG, no clock,
no I/O. STRUCTURAL (1) is the default building state.
"""

import numpy as np

from .detector import compute_sha256_triple

N = 8
STRUCTURAL = 1


def snapshot(states, snapshot_id, generation, memory=None, inactivity_steps=None):
    prov = {
        "snapshot_id": snapshot_id,
        "generation": generation,
        "lattice_size": states.shape[0],
        "num_states": 5,
        "channel_layout_version": "v1",
        "source": "synthetic",
        "sha256_triple": compute_sha256_triple(states, memory, inactivity_steps),
    }
    item = {"states": states, "provenance": prov}
    if memory is not None:
        item["memory"] = memory
    if inactivity_steps is not None:
        item["inactivity_steps"] = inactivity_steps
    return item


def empty_lattice(n=N):
    return np.zeros((n, n, n), dtype=np.uint8)


def block(states, x0, y0, z0, dx, dy, dz, state=STRUCTURAL):
    """Fill a dx*dy*dz block with periodic wrapping (array is [z][y][x])."""
    n = states.shape[0]
    for dz_i in range(dz):
        for dy_i in range(dy):
            for dx_i in range(dx):
                states[(z0 + dz_i) % n, (y0 + dy_i) % n, (x0 + dx_i) % n] = state
    return states


def fx_empty():
    return [snapshot(empty_lattice(), "fx-empty", 1)]


def fx_single():
    states = block(empty_lattice(), 2, 2, 2, 3, 3, 3)
    return [snapshot(states, "fx-single", 1)]


def fx_two_separated():
    states = block(empty_lattice(), 0, 0, 0, 2, 2, 2)
    block(states, 5, 5, 5, 2, 2, 2)
    return [snapshot(states, "fx-two", 1)]


def fx_wraparound():
    # spans the +x/-x seam: x in {6,7,0}, so wraps must be [true,false,false]
    states = block(empty_lattice(), 6, 3, 3, 3, 2, 2)
    return [snapshot(states, "fx-wrap", 1)]


def fx_transient():
    present = block(empty_lattice(), 1, 1, 1, 2, 2, 2)
    absent = empty_lattice()
    return [snapshot(present, "fx-transient-a", 1),
            snapshot(absent, "fx-transient-b", 2)]


def fx_stable():
    states = block(empty_lattice(), 1, 1, 1, 2, 2, 2)
    return [snapshot(states.copy(), f"fx-stable-{i}", i + 1) for i in range(3)]


def fx_oscillator():
    shape_a = block(empty_lattice(), 1, 1, 1, 3, 1, 1)
    shape_b = block(empty_lattice(), 1, 1, 1, 1, 3, 1)
    return [snapshot(shape_a.copy(), "fx-osc-1", 1),
            snapshot(shape_b, "fx-osc-2", 2),
            snapshot(shape_a.copy(), "fx-osc-3", 3)]


# 20 hand-fixed scattered single cells, pairwise non-adjacent under 6-face
# periodic connectivity on N=8 (deterministic "noise", no RNG).
_NOISE_CELLS = [
    (0, 0, 0), (2, 0, 0), (4, 0, 0), (6, 0, 2), (1, 2, 0),
    (3, 2, 6), (5, 2, 2), (7, 2, 4), (0, 4, 4), (2, 4, 0),
    (4, 4, 6), (6, 4, 2), (1, 6, 4), (3, 6, 0), (5, 6, 6),
    (7, 6, 0), (0, 2, 2), (4, 2, 4), (2, 6, 2), (7, 6, 6),
]


def fx_noise():
    states = empty_lattice()
    for x, y, z in _NOISE_CELLS:
        states[z, y, x] = STRUCTURAL
    return [snapshot(states, "fx-noise", 1)]


def fx_malformed_provenance():
    """Provenance missing sha256_triple — must refuse, never analyze."""
    states = block(empty_lattice(), 2, 2, 2, 2, 2, 2)
    item = snapshot(states, "fx-malformed", 1)
    del item["provenance"]["sha256_triple"]
    return [item]


def fx_checkerboard(n=16):
    """(x+y+z) even -> occupied: all components are singletons under 6-face
    connectivity, exercising the component cap with min_component_size=1."""
    zz, yy, xx = np.meshgrid(np.arange(n), np.arange(n), np.arange(n),
                             indexing="ij")
    states = (((xx + yy + zz) % 2) == 0).astype(np.uint8)
    return [snapshot(states, "fx-checker", 1)]
