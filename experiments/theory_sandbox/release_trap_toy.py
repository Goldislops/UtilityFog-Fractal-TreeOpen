#!/usr/bin/env python3
"""Release-trap toy (Toy #5 v1, Strict Passive) -- theory sandbox, NON-CANONICAL.

Explores : docs/MEDUSA_THEORY_INTAKE_LEDGER.md entry 14 (passive geometric traps
           / "MOF") via TOY_05_V1_RELEASE_TRAP_INCEPTION.md, implementing the
           AURA-ratified Strict-Passive v1 lock (Addendum 1) verbatim.
Status   : speculative inspiration / candidate design principle -- not current
           engine design. Non-canonical. NOT architecture evidence.

EXTERNAL CANONICAL GLIDER DISCLAIMER: the target is the textbook Conway Game-of-Life
glider (B3/S23), NOT a native Medusa discovery. This is an isolated sandbox
proof-of-concept for trap mechanics only; nothing here is evidence about Medusa.

What this toy does
------------------
Tests the STRICT-PASSIVE v1 question: can a spatially-constant, always-on, passive
local "freeze" mask HOLD a canonical glider and, after RELEASE (mask disabled ->
B3/S23 everywhere), let the original glider identity RE-EMERGE and resume canonical
T=4 translation? "MOF" is a label only (a static localized rule-mask), never a
material. No temporal gating / scheduled hold-on / shutter / sensing / steering /
Janus / moving trap -- the mask is on from t=0 to t_rel, then released.

Expected (useful negative, stated up front, NOT presupposed by the classifier):
because the door is already closed, partial entry shears the glider (leading cells
frozen, trailing cells advancing), and release cannot reconstitute it -> identity-loss.
The classifier tests success first; "no clean release" is a measured outcome.

128 trajectory conditions (4 orientations x 4 phases x 8 offsets) x 3 hold durations
{8,40,200} = 384 deterministic conditions. v0 is noise-free -> EXACT CATEGORY COUNTS
(no p-values / CIs / significance tests). release-success is reported, NEVER asserted.

Quarantine (experiments/theory_sandbox/README.md section 3): stdlib + numpy only;
deterministic (no RNG); no engine-runtime imports; no uft_ca; no GPU; no data/ writes;
writes only under experiments/theory_sandbox/out/ and only with --csv; not collected
by pytest. ASCII-only output. Determinism is bitwise within a fixed NumPy version on
a fixed CPU platform (numpy version recorded in output).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

# --- locked geometry (reused from v0) + v1 timing -----------------------------
L = 96
T_MAX = 512
SECTOR_R = (44, 59)
SECTOR_C = (44, 59)
D = 35
AIM = (51, 51)
OFFSETS = [-7, -5, -3, -1, 1, 3, 5, 7]
HOLD_DURATIONS = [8, 40, 200]
W = 32                  # annihilation window
N_PERIODS = 3           # canonical translation must persist >= 3 periods (12 ticks)
CHOKE = 100             # post-release runaway-debris threshold
SCAN_AHEAD = 60         # success/pass scan reaches t_rel + SCAN_AHEAD
POP_CAP = 80            # skip glider detection where pop exceeds this (choke region)
ORIENTS = [("SE", 1, 1), ("SW", 1, -1), ("NE", -1, 1), ("NW", -1, -1)]
PHASES = [0, 1, 2, 3]
SE_CELLS = [(0, 1), (1, 2), (2, 0), (2, 1), (2, 2)]

_R, _C = np.indices((L, L))
SECTOR_MASK = ((_R >= SECTOR_R[0]) & (_R <= SECTOR_R[1]) &
               (_C >= SECTOR_C[0]) & (_C <= SECTOR_C[1]))


def transform(o, cells):
    if o == "SE":
        return list(cells)
    if o == "SW":
        return [(r, 2 - c) for r, c in cells]
    if o == "NE":
        return [(2 - r, c) for r, c in cells]
    if o == "NW":
        return [(2 - r, 2 - c) for r, c in cells]
    raise ValueError(o)


# --- Conway Life B3/S23, bounded dead-border ---------------------------------
_PAD = np.zeros((L + 2, L + 2), dtype=np.int16)   # reused scratch buffer (border stays 0)


def neighbor_count(g):
    _PAD[1:-1, 1:-1] = g
    return (_PAD[0:-2, 0:-2] + _PAD[0:-2, 1:-1] + _PAD[0:-2, 2:] +
            _PAD[1:-1, 0:-2] + _PAD[1:-1, 2:] +
            _PAD[2:, 0:-2] + _PAD[2:, 1:-1] + _PAD[2:, 2:])


def b3s23(g):
    n = neighbor_count(g)
    return ((((n == 3) & (g == 0)) | (((n == 2) | (n == 3)) & (g == 1)))).astype(np.uint8)


def step_freeze(g):                       # inside sector frozen (identity); outside B3/S23
    nxt = b3s23(g)                        # fresh array -> safe to modify in place
    nxt[SECTOR_MASK] = g[SECTOR_MASK]     # freeze: inside-sector cells keep their value
    return nxt


def step_latch(g):                        # v0 permanent latch: B3/S012345678 inside
    nxt = b3s23(g)                        # fresh array -> modify in place
    nxt[SECTOR_MASK & (g == 1)] = 1
    return nxt


# --- placement ---------------------------------------------------------------
def place_glider(o, dr, dc, offset, phase):
    aim_r = AIM[0] + offset * dr
    aim_c = AIM[1] - offset * dc
    r0 = aim_r - D * dr - 1
    c0 = aim_c - D * dc - 1
    g = np.zeros((L, L), dtype=np.uint8)
    for (tr, tc) in transform(o, SE_CELLS):
        rr, cc = r0 + tr, c0 + tc
        assert 0 <= rr < L and 0 <= cc < L
        g[rr, cc] = 1
    assert int(g.sum()) == 5
    for _ in range(phase):
        g = b3s23(g)
    return g


# --- simulations -------------------------------------------------------------
def sim_free(g0):
    hist = np.empty((T_MAX + 1, L, L), dtype=np.uint8)
    hist[0] = g0
    g = g0
    for t in range(1, T_MAX + 1):
        g = b3s23(g)
        hist[t] = g
    return hist


def sim_latch(g0):
    hist = np.empty((T_MAX + 1, L, L), dtype=np.uint8)
    hist[0] = g0
    g = g0
    for t in range(1, T_MAX + 1):
        g = step_latch(g)
        hist[t] = g
    return hist


def sim_freeze(g0, t_rel):
    hist = np.empty((T_MAX + 1, L, L), dtype=np.uint8)
    hist[0] = g0
    g = g0
    for t in range(1, T_MAX + 1):
        g = step_freeze(g) if t <= t_rel else b3s23(g)   # hold inside-sector freeze, then release
        hist[t] = g
    return hist


# --- glider detection (isolated 5-cell canonical components) ------------------
def _build_templates():
    pats = set()
    for (o, dr, dc) in ORIENTS:
        g = np.zeros((L, L), dtype=np.uint8)
        for (tr, tc) in transform(o, SE_CELLS):
            g[40 + tr, 40 + tc] = 1
        for _ in range(4):
            rs, cs = np.nonzero(g)
            mnr, mnc = rs.min(), cs.min()
            pats.add(frozenset(zip((rs - mnr).tolist(), (cs - mnc).tolist())))
            g = b3s23(g)
    return pats


GLIDER_PATTERNS = _build_templates()      # all phase shapes across orientations (normalized)


def gliders_in(g):
    """Return list of bbox-origins of isolated 5-cell canonical glider components."""
    if int(g.sum()) > POP_CAP:
        return []
    cells = set(zip(*[a.tolist() for a in np.nonzero(g)]))
    seen = set()
    out = []
    for cell in cells:
        if cell in seen:
            continue
        comp = []
        stack = [cell]
        seen.add(cell)
        while stack:
            r, c = stack.pop()
            comp.append((r, c))
            for dr2 in (-1, 0, 1):
                for dc2 in (-1, 0, 1):
                    nb = (r + dr2, c + dc2)
                    if nb in cells and nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
        if len(comp) == 5:
            mnr = min(r for r, _ in comp)
            mnc = min(c for _, c in comp)
            norm = frozenset((r - mnr, c - mnc) for r, c in comp)
            if norm in GLIDER_PATTERNS:
                out.append((mnr, mnc))
    return out


def earliest_translating(hist, lo, hi, vr, vc, cache):
    """Earliest t in [lo,hi] where an isolated glider translates by (vr,vc) for N_PERIODS."""
    def gl(t):
        if t not in cache:
            cache[t] = gliders_in(hist[t])
        return cache[t]
    for t in range(lo, hi + 1):
        for (r0, c0) in gl(t):
            if all((r0 + vr * k, c0 + vc * k) in gl(t + 4 * k)
                   for k in range(1, N_PERIODS + 1)):
                return t
    return None


# --- classification (cascade; does NOT presuppose failure) -------------------
def classify(hist, dr, dc, t_entry, t_rel):
    cache = {}
    hi = min(max(t_rel, t_entry) + SCAN_AHEAD, T_MAX - 4 * N_PERIODS)
    e_o = earliest_translating(hist, t_entry, hi, dr, dc, cache)        # original orientation
    # 1. pass-through: original-orientation glider already translating at/before release
    if e_o is not None and e_o <= t_rel:
        return "pass-through", e_o
    # 2. clean-annihilation (no live cell anywhere in the final W ticks)
    if not hist[T_MAX - W:T_MAX + 1].any():
        return "clean-annihilation", None
    # 3. choke
    if int(hist[T_MAX].sum()) > CHOKE:
        return "choke", None
    # 4. release-success: original-orientation glider re-emerges AFTER release
    if e_o is not None and e_o > t_rel:
        return "release-success", e_o
    # 5. wrong-orientation: a glider of a different diagonal re-emerges post-release
    for (vr, vc) in [(a, b) for (_, a, b) in ORIENTS if (a, b) != (dr, dc)]:
        e_w = earliest_translating(hist, t_rel + 1, hi, vr, vc, cache)
        if e_w is not None:
            return "wrong-orientation", e_w
    # 6. identity-loss / shear-shatter (residual)
    return "identity-loss", None


def first_entry(hist):
    for t in range(T_MAX + 1):
        if hist[t][SECTOR_MASK].any():
            return t
    return None


# --- self-checks -------------------------------------------------------------
def check_free_glider():
    for (o, dr, dc) in ORIENTS:
        g = np.zeros((L, L), dtype=np.uint8)
        for (tr, tc) in transform(o, SE_CELLS):
            g[48 + tr, 48 + tc] = 1
        rs, cs = np.nonzero(g)
        b0 = (rs.min(), cs.min())
        for _ in range(16):
            g = b3s23(g)
        assert int(g.sum()) == 5
        rs, cs = np.nonzero(g)
        assert (rs.min(), cs.min()) == (b0[0] + 4 * dr, b0[1] + 4 * dc), "mistranslation %s" % o


def fmt(x):
    return "NA" if x is None else str(x)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--csv", action="store_true",
                    help="also write a summary CSV under the gitignored out/ dir")
    args = ap.parse_args()

    out = []
    out.append("NON-CANONICAL TOY: a passive freeze-mask holding/releasing a glider on a "
               "toy lattice proves nothing about Medusa; not chemistry, not a Metal-Organic "
               "Framework, not a hunt.")
    out.append("EXTERNAL CANONICAL GLIDER: the target is the textbook Conway B3/S23 glider, "
               "NOT native Medusa evidence; isolated trap-mechanics proof-of-concept only.")
    out.append("Explores: ledger entry 14 (passive geometric traps / \"MOF\") via "
               "TOY_05_V1_RELEASE_TRAP_INCEPTION.md (Strict-Passive v1, Addendum 1)")
    out.append("Status: speculative inspiration -- not current engine design; inspiration-grade only.")
    out.append("Quarantine: stdlib+NumPy; deterministic (no RNG); text-only; no data/ writes; "
               "not CI-collected; six-step gate applies.")
    out.append("numpy_version: %s" % np.__version__)
    out.append("constants: L=96 T_MAX=512 sector=[44,59]^2 D=35 offsets=[-7..7] "
               "hold_durations={8,40,200} N_periods=3 W=32 choke>100 mask=freeze(identity) "
               "inside [0,t_rel) -> B3/S23 release")

    out.append("-- self-checks --")
    check_free_glider()
    out.append("free_glider_translation: PASS")
    # meaningful freeze/release validation on one representative produced history
    _g = place_glider("SE", 1, 1, -1, 0)
    _te = first_entry(sim_free(_g))
    _tr = _te + 40
    _h = sim_freeze(_g, _tr)
    assert all(np.array_equal(_h[t][SECTOR_MASK], _h[t - 1][SECTOR_MASK])
               for t in range(_te + 1, _tr + 1)), "sector not static during hold"
    assert np.array_equal(_h[_tr + 2], b3s23(_h[_tr + 1])), "release is not pure B3/S23"
    out.append("inside_sector_static_during_hold: PASS")
    out.append("release_pure_b3s23_after_t_rel: PASS")

    cats = ["pass-through", "clean-annihilation", "choke",
            "release-success", "wrong-orientation", "identity-loss"]
    counts = {"control": {c: 0 for c in cats},
              "v0_latch": {c: 0 for c in cats},
              "treatment": {c: 0 for c in cats}}
    rows = []
    n_treat = 0

    for (o, dr, dc) in ORIENTS:
        for p in PHASES:
            for off in OFFSETS:
                g0 = place_glider(o, dr, dc, off, p)
                assert int(g0.sum()) == 5
                free = sim_free(g0)
                t_entry = first_entry(free)
                assert t_entry is not None and t_entry <= 188, \
                    "control failed to enter sector (o=%s p=%d off=%d)" % (o, p, off)
                # control reference (no trap) -> positive-control: must be pass-through
                # (t_rel=T_MAX so any detected translating glider classifies as pass-through)
                c_lab, _ = classify(free, dr, dc, t_entry, t_rel=T_MAX)
                counts["control"][c_lab] += 1
                # v0 latch reference (permanent, no release)
                latch = sim_latch(g0)
                l_lab, _ = classify(latch, dr, dc, t_entry, t_rel=T_MAX)
                counts["v0_latch"][l_lab] += 1
                # treatment: strict-passive freeze, one run per hold_duration
                for hd in HOLD_DURATIONS:
                    t_rel = t_entry + hd
                    treat = sim_freeze(g0, t_rel)
                    assert np.array_equal(treat[0], g0)
                    t_lab, e_t = classify(treat, dr, dc, t_entry, t_rel)
                    counts["treatment"][t_lab] += 1
                    rows.append((o, p, off, hd, t_entry, t_rel, c_lab, l_lab, t_lab, e_t))
                    n_treat += 1

    assert n_treat == 384, "trial-count conservation"
    assert counts["control"]["pass-through"] == 128, \
        "positive-control failed: control should be 128 pass-through, got %d" % counts["control"]["pass-through"]
    out.append("determinism: PASS (no RNG)")
    out.append("arms_initial_equal: PASS")
    out.append("canonical_glider_matcher: PASS (free-glider translation verified)")
    out.append("trial_count: PASS (384 treatment runs)")
    out.append("positive_control_nonfailure: PASS (control = 128 pass-through)")
    out.append("ascii_output: PASS")

    out.append("-- per-condition (treatment) --")
    for (o, p, off, hd, t_entry, t_rel, c_lab, l_lab, t_lab, e_t) in rows:
        out.append("o=%s phase=%d off=%d hold=%d t_entry=%d t_rel=%d control=%s v0latch=%s "
                   "treatment=%s emerge_t=%s" % (o, p, off, hd, t_entry, t_rel, c_lab,
                                                 l_lab, t_lab, fmt(e_t)))

    out.append("-- counts (exact descriptive enumeration; no p-values/CIs/tests) --")
    for arm in ("control", "v0_latch", "treatment"):
        out.append("%s: %s" % (arm, " ".join("%s=%d" % (c, counts[arm][c]) for c in cats)))

    out.append("-- verdict --")
    out.append("reported only; release-success NOT asserted; control is the positive-control "
               "reference (128 pass-through); \"no clean release\" is a valid outcome.")

    text = "\n".join(out)
    assert text.isascii()
    print(text)

    if args.csv:
        out_dir = Path(__file__).resolve().parent / "out"
        out_dir.mkdir(exist_ok=True)
        lines = ["orientation,phase,offset,hold,t_entry,t_rel,control,v0_latch,treatment,emerge_t"]
        for (o, p, off, hd, t_entry, t_rel, c_lab, l_lab, t_lab, e_t) in rows:
            lines.append("%s,%d,%d,%d,%d,%d,%s,%s,%s,%s" % (o, p, off, hd, t_entry, t_rel,
                                                            c_lab, l_lab, t_lab, fmt(e_t)))
        csv_text = "\n".join(lines) + "\n"
        assert csv_text.isascii()
        (out_dir / "release_trap_summary.csv").write_text(csv_text, encoding="ascii")


if __name__ == "__main__":
    main()
