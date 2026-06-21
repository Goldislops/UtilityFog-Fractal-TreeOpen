#!/usr/bin/env python3
"""Janus gradient toy -- theory sandbox, NON-CANONICAL.

Explores : docs/MEDUSA_THEORY_INTAKE_LEDGER.md entry 9 (Janus Gradient
           Kinetics) / docs/MATURIN_ARC_THEORY_PREFLIGHT.md section 5.
Status   : speculative inspiration / candidate design principle -- not current
           engine design. The colloidal science is real; the Medusa mapping is
           the speculative part. Non-canonical. NOT architecture evidence.

What this toy CAN show
----------------------
* Whether a discrete, MEMORYLESS asymmetric gradient-sampling rule ("Janus")
  produces directed drift (net displacement) AND/OR genuine superdiffusive
  spreading (centered-MSD exponent alpha_var > 1) vs an otherwise-identical
  symmetric / gradient-blind control, on a fixed static integer field.
* It separates the two effects on purpose: net displacement measures DRIFT;
  the centered-MSD / ensemble-variance exponent alpha_var measures SPREADING
  (the per-time ensemble-mean trajectory is subtracted before fitting, so the
  v^2 t^2 drift term cannot masquerade as superdiffusion). A raw exponent
  alpha_raw is reported only as a "raw displacement-growth exponent", never as
  proof of superdiffusion.

What this toy CANNOT show
-------------------------
* Anything about Medusa. It imports no engine code, no uft_ca, touches no
  observer semantics, no CA rules, and no production data. "drift without
  superdiffusion" (large net displacement with alpha_var ~ 1) is a VALID,
  expected outcome -- not a failure. Treatment may tie/lose/confine; no
  treatment-superiority is ever asserted. Promotion of any idea built on this
  requires the full 6-step gate in experiments/theory_sandbox/README.md.

Quarantine compliance (experiments/theory_sandbox/README.md section 3): stdlib
+ numpy only; seeded/deterministic; no engine-runtime imports; no GPU; writes
only under experiments/theory_sandbox/out/ and only with --csv; not collected
by pytest (pytest.ini scopes collection to tests/). All runtime output is
ASCII. Determinism is bitwise only within a fixed NumPy version on a fixed CPU
platform (numpy version is recorded in the output).

This file implements verbatim the ratified pre-registration lock + Addendum +
Addendum 2 for Toy #4 (TOY_04_JANUS_GRADIENT_INCEPTION.md).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

# --- C0: master constants block (the only magic numbers that exist) ---------
L = 1027                                # grid side
CENTER = (513, 513)                     # start S = (r, c)
T_MAX = 512                             # steps per trajectory
B = 4                                   # treatment bias constant
SEEDS = list(range(1000, 1100))         # 100 seeds, inclusive 1000..1099
GLOBAL_SALT = 4                         # walk-RNG salt
GEOM_ID = {"linear": 0, "radial": 1, "noisy": 2}
NOISE_SEED = 424242                     # Noisy-Step field noise generator
STEP = 8                               # Noisy-Step height
NOISE_LOW, NOISE_HIGH = -1, 2           # integers(low, high) -> {-1, 0, 1}
FIT_LO, FIT_HI = 32, 512               # alpha fit window, inclusive both ends
EPS = 1e-9                              # zero-variance threshold
N_PERM = 10000
PERM_SEED = 1234567
B_BOOT = 2000
BOOT_SEED = 7654321
ALPHA = 0.05
N_TESTS = 6
ALPHA_PRIME = 0.05 / 6                  # = 0.008333...
SYN_DIFF_GEOM_ID = 90                   # synthetic-check stream, disjoint from {0,1,2}
FLOAT_FMT = "%.6f"

# --- C1: neighbour conventions ----------------------------------------------
# fixed cardinal order: 0=N, 1=E, 2=S, 3=W
DELTAS = [(-1, 0), (0, 1), (1, 0), (0, -1)]

GEOM_ORDER = ["linear", "radial", "noisy"]
ARM_ORDER = ["treatment", "control"]


# --- C2: field construction (deterministic, one way only) -------------------
def build_field(kind: str) -> np.ndarray:
    rows = np.arange(L, dtype=np.int64)[:, None]
    cols = np.arange(L, dtype=np.int64)[None, :]
    if kind == "linear":
        return np.broadcast_to(cols - 513, (L, L)).astype(np.int64).copy()
    if kind == "radial":
        return (-((rows - 513) ** 2 + (cols - 513) ** 2)).astype(np.int64)
    if kind == "noisy":
        base = np.where(cols >= 513, np.int64(STEP), np.int64(0))
        base = np.broadcast_to(base, (L, L))
        noise = np.random.default_rng(NOISE_SEED).integers(
            NOISE_LOW, NOISE_HIGH, size=(L, L), dtype=np.int64
        )
        return (base + noise).astype(np.int64)
    if kind == "flat":
        return np.zeros((L, L), dtype=np.int64)
    raise ValueError("unknown field kind: %r" % (kind,))


# --- C3: walk RNG + step selection ------------------------------------------
def make_rng(geom_id: int, seed: int) -> np.random.Generator:
    return np.random.default_rng([GLOBAL_SALT, geom_id, seed])  # list, not tuple


def weights(F: np.ndarray, r: int, c: int, arm: str) -> list:
    cur = int(F[r, c])
    out = []
    for dr, dc in DELTAS:
        if arm == "treatment":
            out.append(1 + B * max(0, int(F[r + dr, c + dc]) - cur))
        else:
            out.append(1)
    return out


def choose(w: list, rng: np.random.Generator) -> int:
    total = w[0] + w[1] + w[2] + w[3]
    thr = rng.random() * total            # one float draw in [0, total)
    acc = 0
    for i in range(4):                     # fixed N, E, S, W order
        acc += w[i]
        if acc > thr:                      # strictly greater
            return i
    return 3                               # unreachable (thr < total); defensive


# --- C4: one trajectory ------------------------------------------------------
def run_walk(F: np.ndarray, geom_id: int, seed: int, arm: str) -> np.ndarray:
    rng = make_rng(geom_id, seed)
    pos = np.empty((T_MAX + 1, 2), dtype=np.int64)
    r, c = CENTER
    pos[0] = (r, c)
    for t in range(T_MAX):
        i = choose(weights(F, r, c, arm), rng)
        r += DELTAS[i][0]
        c += DELTAS[i][1]
        assert 0 <= r <= 1026 and 0 <= c <= 1026   # fail-closed (provably never trips)
        pos[t + 1] = (r, c)
    return pos


def run_ensemble(F: np.ndarray, geom_id: int, arm: str) -> np.ndarray:
    return np.stack([run_walk(F, geom_id, s, arm) for s in SEEDS])  # (100, T+1, 2) int64


# --- C5: net displacement ----------------------------------------------------
def net_dist_array(P: np.ndarray) -> np.ndarray:
    d = (P[:, T_MAX, :] - P[:, 0, :]).astype(np.float64)
    return np.hypot(d[:, 0], d[:, 1])


def mean_dvec(P: np.ndarray) -> np.ndarray:
    return (P[:, T_MAX, :] - P[:, 0, :]).astype(np.float64).mean(axis=0)  # (dr, dc)


# --- C6: centered-MSD alpha_var + alpha_raw, with zero-variance guard --------
def alpha_from_msd(msd: np.ndarray):
    ts = np.arange(FIT_LO, FIT_HI + 1)            # 32..512 inclusive
    seg = msd[FIT_LO:FIT_HI + 1]
    if seg.max() <= EPS:
        return None                               # zero-variance: bypass fit
    keep = seg > EPS
    return float(np.polyfit(np.log(ts[keep].astype(np.float64)),
                            np.log(seg[keep]), 1)[0])  # slope = coeff[0], natural log


def centered_msd(P: np.ndarray) -> np.ndarray:
    Pf = P.astype(np.float64)
    mean_path = Pf.mean(axis=0)                    # (T+1, 2)
    cen = Pf - mean_path
    return (cen ** 2).sum(axis=2).mean(axis=0)     # (T+1,)


def raw_msd(P: np.ndarray) -> np.ndarray:
    Pf = P.astype(np.float64)
    d = Pf - Pf[:, 0:1, :]
    return (d ** 2).sum(axis=2).mean(axis=0)


# --- C7: net-displacement test (sign-flip permutation) ----------------------
def perm_test_net(net_t: np.ndarray, net_c: np.ndarray) -> float:
    d = net_t - net_c                             # (100,) paired by seed index
    stat_obs = float(d.mean())
    S = np.random.default_rng(PERM_SEED).integers(
        0, 2, size=(N_PERM, 100), dtype=np.int64) * 2 - 1
    stats = (S * d).mean(axis=1)
    return (1 + int(np.count_nonzero(np.abs(stats) >= abs(stat_obs)))) / (N_PERM + 1)


# --- C8 + A2.3: alpha_var test (seeded paired bootstrap) --------------------
def bootstrap_alpha(P_t: np.ndarray, P_c: np.ndarray, a_full_t, a_full_c) -> dict:
    if a_full_t is None or a_full_c is None:
        return {
            "degenerate": True, "dalpha": "NA", "p_alpha": "NA",
            "ci": ("NA", "NA"), "excluded": 0, "distinct": "N",
        }
    delta_obs = a_full_t - a_full_c
    idx = np.random.default_rng(BOOT_SEED).integers(
        0, 100, size=(B_BOOT, 100), dtype=np.int64)
    deltas = []
    excluded = 0
    for b in range(B_BOOT):
        sel = idx[b]
        a_t = alpha_from_msd(centered_msd(P_t[sel]))
        a_c = alpha_from_msd(centered_msd(P_c[sel]))
        if a_t is None or a_c is None:
            excluded += 1
            continue
        deltas.append(a_t - a_c)
    deltas = np.array(deltas, dtype=np.float64)
    n = len(deltas)
    count_le = int((deltas <= 0).sum())
    count_ge = int((deltas >= 0).sum())
    p_alpha = min(1.0, 2.0 * min((1 + count_le) / (n + 1), (1 + count_ge) / (n + 1)))
    ci = (float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5)))
    return {
        "degenerate": False, "dalpha": delta_obs, "p_alpha": p_alpha,
        "ci": ci, "excluded": excluded,
        "distinct": "Y" if p_alpha < ALPHA_PRIME else "N",
    }


# --- C10: synthetic self-checks ---------------------------------------------
def synthetic_self_checks() -> None:
    # (a) pure drift: all 100 trajectories identical, +1 column each step
    drift_one = np.stack([np.array([513, 513 + t], dtype=np.int64)
                          for t in range(T_MAX + 1)])
    P_drift = np.stack([drift_one for _ in range(100)])
    assert centered_msd(P_drift)[FIT_LO:FIT_HI + 1].max() <= EPS
    assert alpha_from_msd(centered_msd(P_drift)) is None
    a_drift_raw = alpha_from_msd(raw_msd(P_drift))
    assert 1.8 <= a_drift_raw <= 2.2

    # (b) pure diffusion: control rule on a flat field, disjoint stream
    F_flat = build_field("flat")
    P_diff = run_ensemble(F_flat, SYN_DIFF_GEOM_ID, "control")
    a_diff = alpha_from_msd(centered_msd(P_diff))
    assert 0.85 <= a_diff <= 1.15

    # (c) drift + diffusion: add identical deterministic +1 col/step
    shift = np.stack([np.array([0, t], dtype=np.int64) for t in range(T_MAX + 1)])
    P_dd = P_diff + shift[None, :, :]
    a_dd = alpha_from_msd(centered_msd(P_dd))
    assert 0.85 <= a_dd <= 1.15 and abs(a_dd - a_diff) <= 0.01
    assert alpha_from_msd(raw_msd(P_dd)) >= 1.8


def instrument_self_checks(fields: dict, ensembles: dict) -> None:
    # determinism: a single (geom, seed, arm) reruns identical
    a = run_walk(fields["linear"], GEOM_ID["linear"], SEEDS[0], "treatment")
    b = run_walk(fields["linear"], GEOM_ID["linear"], SEEDS[0], "treatment")
    assert np.array_equal(a, b)

    # RNG parity: on a flat field, treatment weights == control weights, so the
    # same seed yields byte-identical trajectories (identical RNG consumption).
    F_flat = build_field("flat")
    pt = run_walk(F_flat, SYN_DIFF_GEOM_ID, SEEDS[0], "treatment")
    pc = run_walk(F_flat, SYN_DIFF_GEOM_ID, SEEDS[0], "control")
    assert np.array_equal(pt, pc)

    # shared inputs: fields rebuild deterministically; start is always CENTER
    assert np.array_equal(fields["noisy"], build_field("noisy"))
    for arm in ARM_ORDER:
        for g in GEOM_ORDER:
            assert tuple(ensembles[(g, arm)][0, 0]) == CENTER

    # legal moves + boundary invariant over every trajectory
    for g in GEOM_ORDER:
        for arm in ARM_ORDER:
            P = ensembles[(g, arm)]
            steps = np.abs(np.diff(P, axis=1)).sum(axis=2)   # |dr|+|dc| per step
            assert (steps == 1).all()                        # exactly one cardinal cell
            man = np.abs(P - np.array(CENTER)).sum(axis=2)    # |r-513|+|c-513|
            assert man.max() <= T_MAX
            assert P.min() >= 1 and P.max() <= 1025

    # trial-count conservation
    assert len(ensembles) == len(GEOM_ORDER) * len(ARM_ORDER)
    for P in ensembles.values():
        assert P.shape == (100, T_MAX + 1, 2) and P.dtype == np.int64

    # statistical determinism: permutation draw reproduces
    s1 = np.random.default_rng(PERM_SEED).integers(0, 2, size=(8, 100), dtype=np.int64)
    s2 = np.random.default_rng(PERM_SEED).integers(0, 2, size=(8, 100), dtype=np.int64)
    assert np.array_equal(s1, s2)

    # dtype checks
    for g in GEOM_ORDER:
        assert fields[g].dtype == np.int64


# --- driver ------------------------------------------------------------------
def fnum(x) -> str:
    return x if isinstance(x, str) else (FLOAT_FMT % x)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--csv", action="store_true",
                    help="also write a summary CSV under the gitignored out/ dir")
    args = ap.parse_args()

    out = []
    out.append("NON-CANONICAL TOY: an asymmetric sampling rule drifting across a "
               "toy lattice proves nothing about Medusa; not real Janus "
               "particles, not phoresis, not propulsion.")
    out.append("Explores: ledger entry 9 (Janus Gradient Kinetics) / preflight section 5")
    out.append("Status: speculative inspiration / candidate design principle -- "
               "not current engine design")
    out.append("Can show: whether a discrete asymmetric gradient-sampling rule "
               "yields directed drift and/or superdiffusive spreading vs a "
               "symmetric/gradient-blind control on a fixed static field.")
    out.append("Cannot show: anything about Medusa; no engine/uft_ca/GPU; a "
               "result here is inspiration-grade only.")
    out.append("Quarantine: stdlib+NumPy; text-only; no data/ writes; not "
               "CI-collected; six-step promotion gate applies.")
    out.append("numpy_version: %s" % np.__version__)
    out.append("constants: L=1027 T_MAX=512 B=4 seeds=1000..1099 fit=[32,512] "
               "EPS=1e-09 N_PERM=10000 PERM_SEED=1234567 B_BOOT=2000 "
               "BOOT_SEED=7654321 alpha_prime=%.6f" % ALPHA_PRIME)

    # build fields once
    fields = {g: build_field(g) for g in GEOM_ORDER}

    # synthetic checks first (fail-closed)
    out.append("-- self-checks --")
    synthetic_self_checks()
    out.append("synthetic_msd: PASS")

    # run the experiment
    ensembles = {}
    for g in GEOM_ORDER:
        for arm in ARM_ORDER:
            ensembles[(g, arm)] = run_ensemble(fields[g], GEOM_ID[g], arm)

    instrument_self_checks(fields, ensembles)
    out.append("determinism: PASS")
    out.append("rng_parity: PASS")
    out.append("shared_inputs: PASS")
    out.append("legal_moves: PASS")
    out.append("boundary_invariant: PASS")
    out.append("trial_count: PASS")
    out.append("statistical_determinism: PASS")
    out.append("dtype: PASS")

    # per-arm metrics + per-geometry tests
    out.append("-- results --")
    rows = {}
    for g in GEOM_ORDER:
        for arm in ARM_ORDER:
            P = ensembles[(g, arm)]
            nd = net_dist_array(P)
            mv = mean_dvec(P)
            a_var = alpha_from_msd(centered_msd(P))
            a_raw = alpha_from_msd(raw_msd(P))
            rows[(g, arm)] = {
                "P": P, "nd": nd, "a_var": a_var,
                "net_mean": float(nd.mean()), "net_std": float(nd.std(ddof=0)),
                "mv": mv, "a_raw": a_raw,
            }
            avar_s = "zero_variance" if a_var is None else (FLOAT_FMT % a_var)
            araw_s = "zero_variance" if a_raw is None else (FLOAT_FMT % a_raw)
            out.append(
                "geom=%s arm=%s net_mean=%s net_std=%s mean_dvec=(%s,%s) "
                "alpha_var=%s alpha_raw=%s [raw displacement-growth exponent -- "
                "NOT superdiffusion proof]" % (
                    g, arm, FLOAT_FMT % rows[(g, arm)]["net_mean"],
                    FLOAT_FMT % rows[(g, arm)]["net_std"],
                    FLOAT_FMT % mv[0], FLOAT_FMT % mv[1], avar_s, araw_s))

    for g in GEOM_ORDER:
        rt, rc = rows[(g, "treatment")], rows[(g, "control")]
        p_net = perm_test_net(rt["nd"], rc["nd"])
        dnet = rt["net_mean"] - rc["net_mean"]
        distinct_net = "Y" if p_net < ALPHA_PRIME else "N"
        bs = bootstrap_alpha(rt["P"], rc["P"], rt["a_var"], rc["a_var"])
        out.append(
            "geom=%s dnet=%s p_net=%s distinct_net=%s dalpha=%s p_alpha=%s "
            "ci=[%s,%s] boot_excluded=%d alpha_degenerate=%s distinct_alpha=%s" % (
                g, FLOAT_FMT % dnet, FLOAT_FMT % p_net, distinct_net,
                fnum(bs["dalpha"]), fnum(bs["p_alpha"]),
                fnum(bs["ci"][0]), fnum(bs["ci"][1]), bs["excluded"],
                "Y" if bs["degenerate"] else "N", bs["distinct"]))

    out.append("-- verdict --")
    out.append("reported only; treatment-superiority NOT asserted; "
               "\"drift without superdiffusion\" is a valid outcome.")

    text = "\n".join(out)
    assert text.isascii()   # ASCII-only runtime output (A2.2)
    print(text)

    if args.csv:
        out_dir = Path(__file__).resolve().parent / "out"
        out_dir.mkdir(exist_ok=True)
        lines = ["geom,arm,net_mean,net_std,mean_dr,mean_dc,alpha_var,alpha_raw"]
        for g in GEOM_ORDER:
            for arm in ARM_ORDER:
                r = rows[(g, arm)]
                av = "" if r["a_var"] is None else (FLOAT_FMT % r["a_var"])
                ar = "" if r["a_raw"] is None else (FLOAT_FMT % r["a_raw"])
                lines.append("%s,%s,%s,%s,%s,%s,%s,%s" % (
                    g, arm, FLOAT_FMT % r["net_mean"], FLOAT_FMT % r["net_std"],
                    FLOAT_FMT % r["mv"][0], FLOAT_FMT % r["mv"][1], av, ar))
        csv_text = "\n".join(lines) + "\n"
        assert csv_text.isascii()
        (out_dir / "janus_gradient_summary.csv").write_text(csv_text, encoding="ascii")


if __name__ == "__main__":
    main()
