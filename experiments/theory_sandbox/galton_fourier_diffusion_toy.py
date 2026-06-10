#!/usr/bin/env python3
"""Galton/Fourier diffusion toy — theory sandbox, NON-CANONICAL.

Explores : docs/MATURIN_ARC_THEORY_PREFLIGHT.md §12 ("Fourier / Galton /
           probability 'radiation'").
Status   : speculative mathematical metaphor / exploratory toy.
           Non-canonical. NOT architecture evidence.

What this toy CAN show
----------------------
* A seeded discrete random walk (Galton board: R left/right peg choices)
  empirically converges to the Binomial(R, 1/2) distribution.
* That same distribution is EXACTLY what repeated [1/2, 1/2] diffusion
  smoothing of a point mass produces — i.e. local chaos and deterministic
  smoothing share one macro profile (the heat-kernel/normal limit).
* The Fourier view of why: each smoothing step multiplies spatial mode
  omega by cos(omega/2), so high-frequency structure decays geometrically;
  after R steps mode omega is damped by cos(omega/2)**R.

What this toy CANNOT show
-------------------------
* Anything about Medusa. It imports no engine code, no uft_ca, touches no
  observer semantics, no CA rules, and no production data. A tidy bell
  curve here is NOT evidence that any Medusa behaviour is diffusive,
  Gaussian, or otherwise validated. Promotion of any idea built on this
  requires the full 6-step gate in experiments/theory_sandbox/README.md.

Quarantine compliance (experiments/theory_sandbox/README.md §3): stdlib +
numpy only; seeded/deterministic; no engine-runtime imports; writes only
under experiments/theory_sandbox/out/ and only with --csv; not collected
by pytest (pytest.ini scopes collection to tests/).
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np

OUT_DIR = Path(__file__).resolve().parent / "out"


def galton_counts(n_balls: int, rows: int, rng: np.random.Generator) -> np.ndarray:
    """Simulate the walk honestly: each ball makes `rows` independent
    left/right choices; bin = number of rights. Returns counts per bin."""
    rights = rng.integers(0, 2, size=(n_balls, rows)).sum(axis=1)
    return np.bincount(rights, minlength=rows + 1)


def diffusion_profile(rows: int) -> np.ndarray:
    """Point mass repeatedly smoothed with the [1/2, 1/2] kernel — the
    deterministic twin of one peg row. R steps -> Binomial(R, 1/2) pmf."""
    profile = np.array([1.0])
    for _ in range(rows):
        profile = np.convolve(profile, [0.5, 0.5])
    return profile


def binomial_pmf(rows: int) -> np.ndarray:
    return np.array(
        [math.comb(rows, k) / 2.0**rows for k in range(rows + 1)]
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--balls", type=int, default=100_000)
    ap.add_argument("--rows", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--csv", action="store_true",
                    help="also write a small CSV under experiments/theory_sandbox/out/")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    counts = galton_counts(args.balls, args.rows, rng)
    empirical = counts / counts.sum()
    diffusion = diffusion_profile(args.rows)
    binomial = binomial_pmf(args.rows)

    # --- metrics -----------------------------------------------------------
    tv_emp_vs_binom = 0.5 * np.abs(empirical - binomial).sum()
    max_diff_diffusion_vs_binom = np.abs(diffusion - binomial).max()
    mean_emp = float((np.arange(args.rows + 1) * empirical).sum())
    var_emp = float(((np.arange(args.rows + 1) - mean_emp) ** 2 * empirical).sum())
    mean_theory, var_theory = args.rows / 2.0, args.rows / 4.0

    print(f"Galton/Fourier diffusion toy  (balls={args.balls}, rows={args.rows}, seed={args.seed})")
    print("-" * 72)
    print(f"empirical mean / theory : {mean_emp:.4f} / {mean_theory:.1f}")
    print(f"empirical var  / theory : {var_emp:.4f} / {var_theory:.1f}")
    print(f"TV(empirical, binomial) : {tv_emp_vs_binom:.5f}   (local chaos -> macro bell curve)")
    print(f"max|diffusion - binomial|: {max_diff_diffusion_vs_binom:.2e}   (smoothing IS the binomial)")
    print("Fourier view — damping of mode omega after R steps = cos(omega/2)**R:")
    for omega_name, omega in (("pi/8", math.pi / 8), ("pi/4", math.pi / 4), ("pi/2", math.pi / 2), ("pi", math.pi)):
        print(f"  omega = {omega_name:>4} : {math.cos(omega / 2) ** args.rows:.3e}")

    # --- self-checks (honest toy: it should be able to fail) ----------------
    assert abs(mean_emp - mean_theory) < 0.05, "empirical mean drifted from R/2"
    assert max_diff_diffusion_vs_binom < 1e-12, "convolution != binomial?!"
    assert tv_emp_vs_binom < 0.02, "empirical distribution far from binomial"
    print("self-checks: OK")

    if args.csv:
        OUT_DIR.mkdir(exist_ok=True)
        out = OUT_DIR / f"galton_R{args.rows}_N{args.balls}_seed{args.seed}.csv"
        with out.open("w") as f:
            f.write("bin,count,empirical,binomial,diffusion\n")
            for k in range(args.rows + 1):
                f.write(f"{k},{counts[k]},{empirical[k]:.8f},{binomial[k]:.8f},{diffusion[k]:.8f}\n")
        print(f"csv written: {out}")

    print("\nNON-CANONICAL TOY: a bell curve here proves nothing about Medusa.")


if __name__ == "__main__":
    main()
