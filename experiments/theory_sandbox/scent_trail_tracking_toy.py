#!/usr/bin/env python3
"""Toy #3 — Decaying Scent-Trail Tracking (NON-CANONICAL sandbox toy).

Explores: `docs/MEDUSA_THEORY_INTAKE_LEDGER.md` entry 14 (decaying trails) — status
APPROVED FOR DESIGN-INCEPTION; this script implements the sealed design contract in
`experiments/theory_sandbox/TOY_03_SCENT_TRAIL_TRACKING_INCEPTION.md` (Phase 2B-5H).

What it CAN show: whether, on an identical seeded geometry, a tracker that can read a
decaying integer trail reacquires a now-stationary hidden endpoint in fewer steps / more
often-within-budget than an otherwise-identical trail-blind control.

What it CANNOT show: anything about Medusa engine dynamics, observer semantics, Lane A,
Swarm Hunter, real physics, or architecture validity. A wayfinder reaching a faded
endpoint on a toy grid proves nothing about Medusa. It is an algorithmic trail-following
toy — not radioactive physics, not a hunt.

Quarantine: stdlib + NumPy only; no engine/runtime imports; no `uft_ca`; no GPU/CuPy; no
`data/` writes; no CI collection; text-only output. (README §3.)

The treatment arm is allowed to tie or lose; this script never asserts that it wins.
"""
from __future__ import annotations

import sys

import numpy as np

# ----------------------------------------------------------------------------- #
# Pinned v0 constants (sealed contract — do not widen here)
# ----------------------------------------------------------------------------- #
GRID = 32                       # bounded 32x32 (non-toroidal)
START = (16, 16)               # declared shared last-seen cell (tracker + target)
JUMP_CHEB = (3, 5)             # jump destination Chebyshev distance from START (inclusive)
PATH_MOVES = 12                # seeded self-avoiding cardinal hidden path: up to 12 moves
BUDGET = 192                   # max tracker moves during reacquisition
A = np.int16(64)              # deposit amplitude
D = np.int16(1)               # per-step decrement
REACQUIRE_RADIUS = 0          # exact-cell reacquisition (r = 0)
SEEDS = [11, 22, 33, 44, 55, 66, 77, 88, 99, 111, 123, 222]   # 12 declared seeds

WARNING = ("NON-CANONICAL TOY: a wayfinder reaching a faded endpoint on a toy grid proves "
           "nothing about Medusa; not radioactive physics, not a hunt.")

_CARDINAL = ((-1, 0), (1, 0), (0, -1), (0, 1))   # deterministic order: N, S, W, E


# ----------------------------------------------------------------------------- #
# Geometry (seeded, shared identically by both arms)
# ----------------------------------------------------------------------------- #
def _in_bounds(rc):
    r, c = rc
    return 0 <= r < GRID and 0 <= c < GRID


def _cardinal_neighbours(rc):
    r, c = rc
    return [(r + dr, c + dc) for dr, dc in _CARDINAL if _in_bounds((r + dr, c + dc))]


def build_waypoints(start):
    """All in-bounds cells ordered by increasing Chebyshev distance from `start`,
    tie-broken lexicographically by (row, col). waypoints[0] == start (distance 0)."""
    cells = [(r, c) for r in range(GRID) for c in range(GRID)]
    cells.sort(key=lambda rc: (max(abs(rc[0] - start[0]), abs(rc[1] - start[1])), rc[0], rc[1]))
    return cells


def gen_jump_and_path(rng):
    """Return (jump_dest, path, endpoint). `path` = [jump_dest, c1, ...] of up to
    PATH_MOVES additional cells; a seeded self-avoiding cardinal walk that ends early if
    it traps itself. Identical for both arms (generated once per seed)."""
    lo, hi = JUMP_CHEB
    ring = [(r, c) for r in range(GRID) for c in range(GRID)
            if lo <= max(abs(r - START[0]), abs(c - START[1])) <= hi]
    ring.sort()                                   # deterministic ordering before choice
    jump_dest = tuple(ring[int(rng.integers(len(ring)))])

    path = [jump_dest]
    visited = {jump_dest}
    pos = jump_dest
    for _ in range(PATH_MOVES):
        legal = [n for n in _cardinal_neighbours(pos) if n not in visited]
        if not legal:
            break                                 # trapped -> realised path ends early
        legal.sort()                              # deterministic ordering before choice
        pos = tuple(legal[int(rng.integers(len(legal)))])
        path.append(pos)
        visited.add(pos)
    return jump_dest, path, path[-1]


def lay_trail(jump_dest, path):
    """Build the int16 trail as it exists at the END of the laying phase, per the sealed
    update order: deposit A at the jump destination, then for each subsequent path cell
    (decay -> move -> deposit). Tracker is stationary throughout."""
    trail = np.zeros((GRID, GRID), dtype=np.int16)
    trail[jump_dest] = A                          # initial-jump deposit
    for cell in path[1:]:
        _apply_decay(trail)                        # signed saturating decay + exact §6 check
        trail[cell] = A                           # deposit/overwrite at target's new cell
        _assert_trail_invariants(trail)
    return trail


# ----------------------------------------------------------------------------- #
# Instrument self-checks (correctness only — never about who wins)
# ----------------------------------------------------------------------------- #
def _assert_trail_invariants(trail):
    assert trail.dtype == np.int16, "trail dtype must be int16"
    assert int(trail.min()) >= 0, "trail must never be negative"
    assert int(trail.max()) <= int(A), "trail must never exceed A"


def _apply_decay(trail):
    """Apply signed saturating decay IN PLACE and hard-verify the exact per-cell §6
    contract: every cell becomes ``max(prev - D, 0)`` — i.e. it drops by exactly ``D``,
    or saturates to 0 only if it was already ``<= D``. Verified via (prev, post)
    relations rather than by re-running the formula, so a wrong future decay rule (e.g.
    a different step, multiplicative decay, or a missing clamp) is caught.

    Called on the pure decayed array **before** any deposit, so every cell is
    "non-deposited" at check time; the deposit overwrite during trail-laying is a
    separate, later step and is therefore never mistaken for a decay result.
    """
    prev = trail.copy()
    trail[:] = np.maximum(prev - D, 0)
    delta = prev - trail
    assert np.all((delta == D) | (trail == 0)), \
        "decay: each cell must drop by exactly D or saturate to 0"
    assert np.all((trail != 0) | (prev <= D)), \
        "decay: a cell reached 0 only if it was already <= D"
    assert np.all(trail >= 0) and np.all(trail <= prev), \
        "decay must be non-negative and non-increasing"
    _assert_trail_invariants(trail)


# ----------------------------------------------------------------------------- #
# Movement rules
# ----------------------------------------------------------------------------- #
def _strict_ascent_step(pos, trail):
    """Treatment: move to the cardinal neighbour whose trail value is STRICTLY greater
    than the current cell's value; ties broken by lowest (row, col). Returns the new
    cell or None if no strictly-greater neighbour exists."""
    cur = int(trail[pos])
    candidates = [(int(trail[n]), n[0], n[1]) for n in _cardinal_neighbours(pos)
                  if int(trail[n]) > cur]
    if not candidates:
        return None
    candidates.sort(key=lambda t: (-t[0], t[1], t[2]))   # highest value, then lowest (row,col)
    best = candidates[0]
    return (best[1], best[2])


def _fallback_step(pos, idx, waypoints, reached):
    """Shared deterministic expanding-ring sweep (sealed §3.6). Pre-advances past any
    waypoint this arm has **already reached** (not merely the current cell) before moving;
    bounded; fail-closed if exhausted.

    A single cardinal step toward a (possibly diagonal) waypoint can *transit* a later
    waypoint cell before it becomes the current target, so skipping only `pos == waypoints[idx]`
    would let the sweep walk back to an already-visited cell. Skipping any `waypoints[idx] in
    reached` keeps it a true next-**unvisited** sweep (Codex thread r3441... / #247 r…aad).
    """
    n = len(waypoints)
    while idx < n and waypoints[idx] in reached:
        idx += 1
    if idx >= n:
        raise RuntimeError(
            "fallback waypoint list exhausted (idx == len(waypoints)) -- instrument-contract "
            "failure; unreachable under pinned v0 (1024 waypoints vs 192-move budget)"
        )
    target = waypoints[idx]
    assert target not in reached, "fallback must never target an already-reached waypoint"
    dr = target[0] - pos[0]
    dc = target[1] - pos[1]
    if abs(dr) >= abs(dc):                         # fixed axis rule: row first on ties
        step = (pos[0] + (1 if dr > 0 else -1), pos[1])
    else:
        step = (pos[0], pos[1] + (1 if dc > 0 else -1))
    return step, idx


# ----------------------------------------------------------------------------- #
# One reacquisition arm
# ----------------------------------------------------------------------------- #
def run_arm(laid_trail, endpoint, waypoints, *, read_trail):
    """Simulate one arm from START toward the stationary `endpoint`. Returns a dict of
    metrics + diagnostics. `read_trail=True` is the treatment arm; False is the control."""
    trail = laid_trail.copy()
    pos = START
    idx = 0
    reached = {START}                               # all cells this arm has stood on (incl. ascent)
    moves = 0
    ascent_moves = 0
    fallback_moves = 0
    first_trail_acq = None                         # tick the tracker first stands on trail>0
    fully_decayed_tick = None                      # tick the trail first becomes all-zero
    reacquired = False
    steps = None

    if read_trail and int(trail[pos]) > 0:
        first_trail_acq = 0

    while moves < BUDGET:
        # (1) check before moving
        if pos == endpoint:
            reacquired = True
            steps = moves
            break
        # (2) decay (no deposit during reacquisition -> exact §6 check applies to all cells)
        _apply_decay(trail)
        if fully_decayed_tick is None and int(trail.max()) == 0:
            fully_decayed_tick = moves
        # (4) one tracker move (treatment: strict ascent else fallback; control: fallback)
        nxt = _strict_ascent_step(pos, trail) if read_trail else None
        if nxt is not None:
            ascent_moves += 1
        else:
            nxt, idx = _fallback_step(pos, idx, waypoints, reached)
            fallback_moves += 1
        # instrument checks: exactly one non-zero, legal cardinal move
        assert nxt != pos, "tracker made a zero-length (stall) move"
        assert _in_bounds(nxt), "tracker left the grid"
        assert abs(nxt[0] - pos[0]) + abs(nxt[1] - pos[1]) == 1, "move was not one cardinal step"
        pos = nxt
        reached.add(pos)                            # record every visited cell (ascent + fallback)
        moves += 1
        if read_trail and first_trail_acq is None and int(trail[pos]) > 0:
            first_trail_acq = moves
        # (5) check immediately after the move
        if pos == endpoint:
            reacquired = True
            steps = moves
            break

    return {
        "reacquired": reacquired,
        "steps": steps,                            # None if budget exhausted
        "ascent_moves": ascent_moves,
        "fallback_moves": fallback_moves,
        "first_trail_acq": first_trail_acq,
        "fully_decayed_tick": fully_decayed_tick,
        "trail_fully_decayed_before_reacq": (
            reacquired and fully_decayed_tick is not None and fully_decayed_tick <= steps
        ),
    }


# ----------------------------------------------------------------------------- #
# One seed -> both arms (identical geometry; trail visibility the sole variable)
# ----------------------------------------------------------------------------- #
def run_seed(seed, waypoints):
    rng = np.random.default_rng(seed)
    jump_dest, path, endpoint = gen_jump_and_path(rng)
    laid = lay_trail(jump_dest, path)
    treatment = run_arm(laid, endpoint, waypoints, read_trail=True)
    control = run_arm(laid, endpoint, waypoints, read_trail=False)
    return {
        "seed": seed,
        "jump_dest": jump_dest,
        "endpoint": endpoint,
        "path_len_moves": len(path) - 1,           # realised hidden-path length (moves)
        "treatment": treatment,
        "control": control,
    }


# ----------------------------------------------------------------------------- #
# Reporting
# ----------------------------------------------------------------------------- #
def _steps_str(arm):
    return str(arm["steps"]) if arm["reacquired"] else ">budget"


def _winner(res):
    t, c = res["treatment"], res["control"]
    # Rank: reacquired-in-fewer-steps beats not; a successful arm beats a failed one.
    tk = (0 if t["reacquired"] else 1, t["steps"] if t["reacquired"] else BUDGET + 1)
    ck = (0 if c["reacquired"] else 1, c["steps"] if c["reacquired"] else BUDGET + 1)
    if tk < ck:
        return "treatment"
    if ck < tk:
        return "control"
    return "tie"


def main(argv=None):
    print(WARNING)
    print(f"Toy #3 scent-trail tracking -- grid {GRID}x{GRID}, seeds={len(SEEDS)}, "
          f"budget={BUDGET}, A={int(A)}, D={int(D)}, r={REACQUIRE_RADIUS}, no diffusion")
    print("(NON-CANONICAL; treatment is permitted to tie or lose. No success is asserted.)\n")

    waypoints = build_waypoints(START)
    assert waypoints[0] == START, "waypoints[0] must be the distance-0 start cell"

    results = [run_seed(s, waypoints) for s in SEEDS]

    # --- §6 instrument self-checks (correctness only) ---
    # same-seed rerun is byte-identical (determinism)
    assert run_seed(SEEDS[0], waypoints) == results[0], "non-deterministic: same-seed rerun differs"
    # trial-count conservation: every seed ran both arms
    assert len(results) == len(SEEDS)
    for r in results:
        assert "treatment" in r and "control" in r

    # --- primary table ---
    print("per-seed results:")
    print(f"{'seed':>5} | {'treat':>7} | {'ctrl':>7} | {'winner':>9} | "
          f"{'jump':>9} | {'endpoint':>9} | {'pathmv':>6}")
    print("-" * 76)
    t_succ = c_succ = 0
    t_steps_sum = c_steps_sum = 0
    t_succ_n = c_succ_n = 0
    for r in results:
        t, c = r["treatment"], r["control"]
        t_succ += int(t["reacquired"])
        c_succ += int(c["reacquired"])
        if t["reacquired"]:
            t_steps_sum += t["steps"]
            t_succ_n += 1
        if c["reacquired"]:
            c_steps_sum += c["steps"]
            c_succ_n += 1
        print(f"{r['seed']:>5} | {_steps_str(t):>7} | {_steps_str(c):>7} | {_winner(r):>9} | "
              f"{str(r['jump_dest']):>9} | {str(r['endpoint']):>9} | {r['path_len_moves']:>6}")

    n = len(results)
    censored = BUDGET + 1                           # unreacquired arms counted as BUDGET+1
    t_cens = sum((r["treatment"]["steps"] if r["treatment"]["reacquired"] else censored)
                 for r in results) / n
    c_cens = sum((r["control"]["steps"] if r["control"]["reacquired"] else censored)
                 for r in results) / n
    t_mean = f"{t_steps_sum / t_succ_n:.1f}" if t_succ_n else "n/a"
    c_mean = f"{c_steps_sum / c_succ_n:.1f}" if c_succ_n else "n/a"
    print("\nsummary (descriptive only -- NOT a success claim; a lower mean is not 'better' "
          "unless the success rates are equal):")
    print(f"  PRIMARY (sealed v0 section 4) -- all-{n}-seed mean steps-to-reacquisition, "
          f"budget-censored (unreacquired counted as BUDGET+1={censored}):")
    print(f"      treatment: {t_cens:.1f}    control: {c_cens:.1f}")
    print(f"  success-in-budget: treatment {t_succ}/{n}, control {c_succ}/{n}")
    print(f"  secondary -- mean steps over successful seeds only: "
          f"treatment {t_mean}, control {c_mean}")
    wins = {"treatment": 0, "control": 0, "tie": 0}
    for r in results:
        wins[_winner(r)] += 1
    print(f"  per-seed winners: treatment={wins['treatment']}, control={wins['control']}, tie={wins['tie']}")

    # --- §4 diagnostics ---
    print("\ndiagnostics (treatment arm; diagnostic only):")
    print(f"{'seed':>5} | {'1st_acq':>7} | {'ascent':>6} | {'fallbk':>6} | "
          f"{'decayed_before_reacq':>20}")
    print("-" * 60)
    for r in results:
        t = r["treatment"]
        acq = "none" if t["first_trail_acq"] is None else str(t["first_trail_acq"])
        print(f"{r['seed']:>5} | {acq:>7} | {t['ascent_moves']:>6} | {t['fallback_moves']:>6} | "
              f"{str(t['trail_fully_decayed_before_reacq']):>20}")

    print("\nself-checks passed (instrument correctness only). "
          "Outcome is reported, never asserted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
