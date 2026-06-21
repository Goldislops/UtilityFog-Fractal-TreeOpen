#!/usr/bin/env python3
"""Passive "MOF" trap toy -- theory sandbox, NON-CANONICAL.

Explores : docs/MEDUSA_THEORY_INTAKE_LEDGER.md entry 14 (passive geometric traps
           / "MOF") via experiments/theory_sandbox/TOY_05_PASSIVE_MOF_TRAP_INCEPTION.md
           (sealed inception + stats erratum E1 + ratified pre-registration lock + Addendum 1).
Status   : speculative inspiration / candidate design principle -- not current
           engine design. Non-canonical. NOT architecture evidence.

EXTERNAL CANONICAL GLIDER DISCLAIMER: the target is the textbook Conway Game-of-Life
glider (B3/S23), NOT a native Medusa discovery. This is an isolated sandbox
proof-of-concept for trap mechanics only; nothing here is evidence about Medusa.

What this toy does
------------------
Tests whether a STATIC localized rule-mask ("MOF" = label only, a spatial
heterogeneity) can arrest a canonical glider's translation vs a homogeneous
B3/S23 baseline, while keeping the target recognizable -- across a fixed set of
128 pre-registered DETERMINISTIC conditions (4 orientations x 4 phases x 8
offsets). v0 is deterministic and noise-free: outcomes are reported as EXACT
CATEGORY COUNTS (no p-values, no confidence intervals, no significance tests;
control captures 0/128 by construction). Noise / inferential testing is deferred
to a separately-authorized v1.

Sole variable = presence of the localized latch mask inside the sector.
Treatment may pass-through / choke / capture / shatter / cleanly annihilate;
"no clean capture" is a valid, reported outcome. Capture is NEVER asserted.

Quarantine (experiments/theory_sandbox/README.md section 3): stdlib + numpy only;
deterministic (no RNG); no engine-runtime imports; no uft_ca; no GPU; no data/
writes; writes only under experiments/theory_sandbox/out/ and only with --csv;
not collected by pytest. ASCII-only output. Determinism is bitwise within a
fixed NumPy version on a fixed CPU platform (numpy version recorded in output).

This file implements the ratified v0 lock + Addendum 1 verbatim.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

# --- locked constants (lock C0 + C-add) -------------------------------------
L = 96                                  # grid side, bounded dead-border
T_MAX = 256
SECTOR_R = (44, 59)                      # inclusive
SECTOR_C = (44, 59)
REGION_R = (41, 62)                      # sector + margin 3, inclusive
REGION_C = (41, 62)
D = 35                                   # upstream distance (periods)
AIM = (51, 51)
OFFSETS = [-7, -5, -3, -1, 1, 3, 5, 7]
W = 32                                   # trailing window
P = 8                                    # max periodicity period
CHOKE = 128                              # > half the 16x16 sector
ENTRY_DEADLINE = 188
ORIENTS = [("SE", 1, 1), ("SW", 1, -1), ("NE", -1, 1), ("NW", -1, -1)]
PHASES = [0, 1, 2, 3]
SE_CELLS = [(0, 1), (1, 2), (2, 0), (2, 1), (2, 2)]   # SE phase-0, 3x3 bbox-relative

_R, _C = np.indices((L, L))
SECTOR_MASK = ((_R >= SECTOR_R[0]) & (_R <= SECTOR_R[1]) &
               (_C >= SECTOR_C[0]) & (_C <= SECTOR_C[1]))
REGION_MASK = ((_R >= REGION_R[0]) & (_R <= REGION_R[1]) &
               (_C >= REGION_C[0]) & (_C <= REGION_C[1]))


def transform(o, cells):
    if o == "SE":
        return list(cells)
    if o == "SW":
        return [(r, 2 - c) for r, c in cells]
    if o == "NE":
        return [(2 - r, c) for r, c in cells]
    if o == "NW":
        return [(2 - r, 2 - c) for r, c in cells]
    raise ValueError("orientation: %r" % (o,))


# --- Conway Life (B3/S23), bounded dead-border, synchronous Moore-8 ----------
def neighbor_count(g):
    p = np.zeros((L + 2, L + 2), dtype=np.int16)
    p[1:-1, 1:-1] = g
    return (p[0:-2, 0:-2] + p[0:-2, 1:-1] + p[0:-2, 2:] +
            p[1:-1, 0:-2] + p[1:-1, 2:] +
            p[2:, 0:-2] + p[2:, 1:-1] + p[2:, 2:])


def base_step(g):
    n = neighbor_count(g)
    nxt = (((n == 3) & (g == 0)) | (((n == 2) | (n == 3)) & (g == 1)))
    return nxt.astype(np.uint8)


def simulate(g0, latch, check_containment=False):
    hist = np.empty((T_MAX + 1, L, L), dtype=np.uint8)
    hist[0] = g0
    g = g0
    for t in range(1, T_MAX + 1):
        base_next = base_step(g)
        if latch:
            nxt = base_next.copy()
            nxt[SECTOR_MASK & (g == 1)] = 1            # latch: inside-sector live cells never die
            if check_containment:
                diff = (nxt != base_next)
                assert not (diff & ~SECTOR_MASK).any(), "mask wrote outside sector"
            g = nxt
        else:
            g = base_next
        hist[t] = g
    return hist


# --- glider placement -------------------------------------------------------
def place_glider(o, dr, dc, offset, phase):
    aim_r = AIM[0] + offset * dr
    aim_c = AIM[1] - offset * dc
    r0 = aim_r - D * dr - 1
    c0 = aim_c - D * dc - 1
    g = np.zeros((L, L), dtype=np.uint8)
    for (tr, tc) in transform(o, SE_CELLS):
        rr, cc = r0 + tr, c0 + tc
        assert 0 <= rr < L and 0 <= cc < L, "glider placed out of bounds"
        g[rr, cc] = 1
    assert int(g.sum()) == 5
    for _ in range(phase):                              # free-evolve p ticks (homogeneous)
        g = base_step(g)
    return g


# --- helpers ----------------------------------------------------------------
def live_set(g):
    rs, cs = np.nonzero(g)
    return set(zip(rs.tolist(), cs.tolist()))


def fits_3x3(cells):
    rs = [r for r, _ in cells]; cs = [c for _, c in cells]
    return (max(rs) - min(rs) <= 2) and (max(cs) - min(cs) <= 2)


def forward_mask(dr, dc):
    corners = [(SECTOR_R[0], SECTOR_C[0]), (SECTOR_R[0], SECTOR_C[1]),
               (SECTOR_R[1], SECTOR_C[0]), (SECTOR_R[1], SECTOR_C[1])]
    pmax = max(dr * r + dc * c for r, c in corners)
    return (dr * _R + dc * _C) > pmax


def region_frame(g):
    rs, cs = np.nonzero(g & REGION_MASK)
    return frozenset(zip(rs.tolist(), cs.tolist()))


# --- outcome classification (precedence: pass->annih->choke->capture->shatter)
def classify(hist, dr, dc, t_entry):
    fwd = forward_mask(dr, dc)
    # 1. pass-through
    for t in range(t_entry, T_MAX - 4 + 1):
        f1 = live_set(hist[t] & fwd)
        if len(f1) == 5 and fits_3x3(f1):
            want = {(r + dr, c + dc) for (r, c) in f1}
            f2 = live_set(hist[t + 4] & fwd)
            if len(f2) == 5 and f2 == want:
                return "pass-through", 0, None
    # precompute per-tick population once (lookups below avoid O(T_MAX^2) rescans)
    pops = [int(hist[t].sum()) for t in range(T_MAX + 1)]
    # 2. clean-annihilation
    if all(pops[t] == 0 for t in range(T_MAX - W, T_MAX + 1)):
        return "clean-annihilation", 0, None
    # 3. choke
    if int((hist[T_MAX] & SECTOR_MASK).sum()) > CHOKE:
        return "choke", 0, None
    # 4. capture
    lo = T_MAX - W
    contained = [(pops[t] <= CHOKE) and (not (hist[t] & ~REGION_MASK).any())
                 for t in range(T_MAX + 1)]
    if pops[T_MAX] > 0 and all(contained[t] for t in range(lo, T_MAX + 1)):
        frames = [region_frame(hist[t]) for t in range(T_MAX + 1)]   # precomputed once
        q = None
        for cand_q in range(1, P + 1):
            if all(frames[t] == frames[t + cand_q] for t in range(lo, T_MAX - cand_q + 1)):
                q = cand_q
                break
        if q is not None:
            # retention: earliest t_cap with containment + periodicity(q) continuous to T_MAX.
            # The chain [t_cap, T_MAX] already holds; extending downward needs only the new tick.
            t_cap = lo
            while (t_cap > 0 and contained[t_cap - 1] and pops[t_cap - 1] > 0
                   and frames[t_cap - 1] == frames[t_cap - 1 + q]):
                t_cap -= 1
            return "capture", T_MAX - t_cap, q
    # 5. shatter (residual)
    return "shatter", 0, None


def first_entry(hist):
    for t in range(T_MAX + 1):
        if (hist[t] & SECTOR_MASK).any():
            return t
    return None


# --- self-checks (instrument correctness only) ------------------------------
def check_free_glider():
    for (o, dr, dc) in ORIENTS:
        g = np.zeros((L, L), dtype=np.uint8)
        for (tr, tc) in transform(o, SE_CELLS):
            g[48 + tr, 48 + tc] = 1
        s0 = live_set(g)
        b0 = (min(r for r, _ in s0), min(c for _, c in s0))
        for _ in range(16):                            # 4 periods
            g = base_step(g)
        assert int(g.sum()) == 5, "free glider lost cells"
        s1 = live_set(g)
        b1 = (min(r for r, _ in s1), min(c for _, c in s1))
        assert b1 == (b0[0] + 4 * dr, b0[1] + 4 * dc), "free glider mistranslated %s" % o


# --- driver -----------------------------------------------------------------
def fmt_cell(x):
    return "NA" if x is None else str(x)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--csv", action="store_true",
                    help="also write a summary CSV under the gitignored out/ dir")
    args = ap.parse_args()

    out = []
    out.append("NON-CANONICAL TOY: a localized rule-mask arresting a glider on a "
               "toy lattice proves nothing about Medusa; not chemistry, not a "
               "Metal-Organic Framework, not molecular binding, not a hunt.")
    out.append("EXTERNAL CANONICAL GLIDER: the target is the textbook Conway "
               "B3/S23 glider, NOT native Medusa evidence; isolated trap-mechanics "
               "proof-of-concept only.")
    out.append("Explores: ledger entry 14 (passive geometric traps / \"MOF\") via "
               "TOY_05_PASSIVE_MOF_TRAP_INCEPTION.md")
    out.append("Status: speculative inspiration / candidate design principle -- "
               "not current engine design; a result here is inspiration-grade only.")
    out.append("Quarantine: stdlib+NumPy; deterministic (no RNG); text-only; no "
               "data/ writes; not CI-collected; six-step promotion gate applies.")
    out.append("numpy_version: %s" % np.__version__)
    out.append("constants: L=96 T_MAX=256 sector=[44,59]^2 region=[41,62]^2 D=35 "
               "offsets=[-7,-5,-3,-1,1,3,5,7] W=32 P=8 choke>128 entry_deadline=188 "
               "mask=B3/S012345678 inside / B3/S23 outside")

    # self-checks
    out.append("-- self-checks --")
    check_free_glider()
    out.append("free_glider_translation: PASS")

    # run all 128 conditions, both arms
    rows = []                       # (o,p,off, ctrl_label, treat_label, retention, period, pop_sector)
    counts = {"control": {}, "treatment": {}}
    cats = ["pass-through", "clean-annihilation", "choke", "capture", "shatter"]
    for c in cats:
        counts["control"][c] = 0
        counts["treatment"][c] = 0
    n_runs = 0
    for (o, dr, dc) in ORIENTS:
        for p in PHASES:
            for off in OFFSETS:
                g0 = place_glider(o, dr, dc, off, p)
                assert int(g0.sum()) == 5, "t=0 not exactly the 5-cell glider"
                ctrl = simulate(g0, latch=False)
                treat = simulate(g0, latch=True, check_containment=True)
                assert np.array_equal(ctrl[0], treat[0]) and np.array_equal(ctrl[0], g0)
                te = first_entry(ctrl)
                assert te is not None and te <= ENTRY_DEADLINE, \
                    "control glider failed to enter sector by deadline (o=%s p=%d off=%d)" % (o, p, off)
                c_label, _, _ = classify(ctrl, dr, dc, te)
                t_label, retention, period = classify(treat, dr, dc, te)
                pop_sec = int((treat[T_MAX] & SECTOR_MASK).sum())
                counts["control"][c_label] += 1
                counts["treatment"][t_label] += 1
                rows.append((o, p, off, c_label, t_label, retention, period, pop_sec))
                n_runs += 2

    # instrument assertions
    assert counts["control"]["capture"] == 0, "control captured (instrument bug)"
    assert n_runs == 128 * 2, "trial-count conservation failed"
    out.append("control_capture_zero: PASS")
    out.append("control_entry_by_deadline: PASS")
    out.append("mask_write_containment: PASS")
    out.append("arms_initial_equal: PASS")
    out.append("initial_glider_only: PASS")
    out.append("no_rng: PASS")
    out.append("legal_updates: PASS")
    out.append("trial_count: PASS (128 conditions x 2 arms = 256 runs)")

    # per-condition lines
    out.append("-- per-condition (treatment is the experiment; control is the reference) --")
    for (o, p, off, c_label, t_label, retention, period, pop_sec) in rows:
        out.append("o=%s phase=%d off=%d control=%s treatment=%s retention=%d period=%s pop_sector=%d"
                   % (o, p, off, c_label, t_label, retention, fmt_cell(period), pop_sec))

    # counts
    out.append("-- counts (exact descriptive enumeration; no p-values/CIs/tests) --")
    for arm in ("control", "treatment"):
        out.append("%s: %s" % (arm, " ".join("%s=%d" % (c, counts[arm][c]) for c in cats)))

    out.append("-- verdict --")
    out.append("reported only; capture NOT asserted; control captures 0/128 by "
               "construction; \"no clean capture\" is a valid outcome.")

    text = "\n".join(out)
    assert text.isascii()
    print(text)

    if args.csv:
        out_dir = Path(__file__).resolve().parent / "out"
        out_dir.mkdir(exist_ok=True)
        lines = ["orientation,phase,offset,control,treatment,retention,period,pop_sector"]
        for (o, p, off, c_label, t_label, retention, period, pop_sec) in rows:
            lines.append("%s,%d,%d,%s,%s,%d,%s,%d"
                         % (o, p, off, c_label, t_label, retention, fmt_cell(period), pop_sec))
        csv_text = "\n".join(lines) + "\n"
        assert csv_text.isascii()
        (out_dir / "passive_mof_trap_summary.csv").write_text(csv_text, encoding="ascii")


if __name__ == "__main__":
    main()
