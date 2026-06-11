#!/usr/bin/env python3
"""Stochastic escape / annealing toy — theory sandbox, NON-CANONICAL.

Explores : docs/MATURIN_ARC_THEORY_PREFLIGHT.md §13 (algorithmic framing
           only: stochastic escape, local-minimum escape, simulated
           annealing — trapped configurations and how noise frees them).
Inception: experiments/theory_sandbox/TOY_02_STOCHASTIC_ESCAPE_ANNEALING_INCEPTION.md
           — the §9 review decisions (Jack, 2026-06-11) are binding here.
Status   : speculative algorithmic metaphor / exploratory toy.
           Non-canonical. NOT architecture evidence.

Disclaimer
----------
This is NOT quantum tunnelling. The mechanism is a classical, seeded,
discrete Metropolis-style random walk in dimensionless toy units; no
quantum model is implemented, used, or implied. The word appears in this
file only inside this disclaimer and the matching disclaimer printed in
the report.

What this toy CAN show
----------------------
* Experiment A — fixed-temperature stochastic escape: how often a walker
  started in the shallow basin of a fixed parametric 1D double-well first
  reaches the deep basin within a step budget, over a small fixed table of
  barrier scales and temperatures. Barrier height (an energy difference on
  the landscape) and temperature (the walker's noise scale) are distinct
  knobs and are varied independently.
* Experiment B — geometric simulated annealing: whether one geometric
  cooling schedule ends in the deeper basin more often than an abrupt
  low-temperature quench, given the same landscape, walker and step
  budget. Reported separately from Experiment A.
* Hard self-checks that can fail the run: byte-identical determinism for
  the same seed/config; all probabilities/frequencies within [0, 1];
  trial-count conservation; theoretical Metropolis uphill acceptance
  falling as dE rises at fixed T and rising as T rises at fixed dE; no
  NaN/inf anywhere. Soft diagnostics (reported, never fatal): sampled
  escape trends vs barrier and temperature, cooling-vs-quench basin
  preference, Monte Carlo vs theoretical acceptance. Strict empirical
  monotonicity is deliberately NOT hard-asserted from finite samples.

What this toy CANNOT show
-------------------------
* Anything about Medusa. It imports no engine code, no uft_ca, touches no
  observer semantics, no CA rules, and no production data. A marble
  escaping a toy well is NOT evidence that any Medusa structure escapes,
  anneals, or tunnels anything. Promotion of any idea built on this
  requires the full 6-step gate in experiments/theory_sandbox/README.md.

Quarantine compliance (experiments/theory_sandbox/README.md §3): pure
standard library (no numpy needed); seeded/deterministic; no engine-
runtime imports; no uft_ca; no reads of production state; no file writes
at all (text output only, no CSV in v0); not collected by pytest
(pytest.ini scopes collection to tests/).
"""

from __future__ import annotations

import argparse
import math
import random

# --- fixed toy configuration (binding: small fixed tables, no zoology) -----
GRID_POINTS = 61                  # odd -> one site exactly at x = 0
X_MIN, X_MAX = -1.5, 1.5
TILT = -0.2                       # linear tilt; makes the right basin deeper

BARRIER_SCALES = (0.5, 1.0, 2.0)  # h in E(x) = h*(x^2 - 1)^2 + TILT*x
TEMPERATURES = (0.2, 0.4, 0.8)    # fixed-temperature table for Experiment A
TRIALS_A = 150
MAX_STEPS_A = 5000

ANNEAL_BARRIER_SCALE = 1.0        # Experiment B: same landscape family
T_START, T_END = 1.5, 0.05
STEPS_B = 8000
TRIALS_B = 200                    # per arm (geometric cooling vs quench)

FOOTER = ("NON-CANONICAL TOY: a marble escaping a toy well proves nothing "
          "about Medusa.")


class SelfCheckFailure(Exception):
    """A hard self-check failed; this run's numbers must not be trusted."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SelfCheckFailure(f"HARD SELF-CHECK FAILED: {message}")


def checked_fraction(numerator: int, denominator: int,
                     tracked: list[float]) -> float:
    require(denominator > 0, "fraction denominator must be positive")
    fraction = numerator / denominator
    require(0.0 <= fraction <= 1.0,
            f"frequency {fraction!r} escaped the interval [0, 1]")
    tracked.append(fraction)
    return fraction


# --- landscape --------------------------------------------------------------

def make_landscape(barrier_scale: float) -> tuple[list[float], list[float]]:
    """Fixed parametric double-well on a discrete grid (dimensionless)."""
    step = (X_MAX - X_MIN) / (GRID_POINTS - 1)
    xs = [X_MIN + i * step for i in range(GRID_POINTS)]
    energies = [barrier_scale * (x * x - 1.0) ** 2 + TILT * x for x in xs]
    return xs, energies


def landscape_features(energies: list[float]) -> tuple[int, int, int]:
    """Grid indices of (shallow minimum, barrier top, deep minimum)."""
    size = len(energies)
    mid = size // 2
    left_min = min(range(mid), key=energies.__getitem__)
    right_min = min(range(mid, size), key=energies.__getitem__)
    barrier = max(range(left_min, right_min + 1), key=energies.__getitem__)
    if energies[left_min] >= energies[right_min]:
        shallow, deep = left_min, right_min
    else:
        shallow, deep = right_min, left_min
    return shallow, barrier, deep


# --- walker ------------------------------------------------------------------

def theoretical_uphill_acceptance(d_e: float, temperature: float) -> float:
    """Metropolis acceptance probability for an uphill move (d_e > 0)."""
    return math.exp(-d_e / temperature)


def escape_trial(energies: list[float], start: int, target: int,
                 temperature: float, max_steps: int, rng: random.Random,
                 uphill: list) -> bool:
    """One constant-temperature Metropolis walk from `start`.

    Returns True on first arrival at `target` within `max_steps`. `uphill`
    accumulates [proposal count, acceptance count, sum of theoretical
    acceptance probabilities] for the Monte-Carlo-vs-theory diagnostic.
    """
    pos = start
    last = len(energies) - 1
    rand = rng.random
    exp = math.exp
    proposals = accepted = 0
    theory_sum = 0.0
    escaped = False
    for _ in range(max_steps):
        nxt = pos + 1 if rand() < 0.5 else pos - 1
        if nxt < 0 or nxt > last:
            continue                      # off-grid proposal rejected
        d_e = energies[nxt] - energies[pos]
        if d_e <= 0.0:
            pos = nxt
        else:
            acceptance = exp(-d_e / temperature)
            proposals += 1
            theory_sum += acceptance
            if rand() < acceptance:
                accepted += 1
                pos = nxt
        if pos == target:
            escaped = True
            break
    uphill[0] += proposals
    uphill[1] += accepted
    uphill[2] += theory_sum
    return escaped


def schedule_trial(energies: list[float], start: int,
                   temperatures: list[float], rng: random.Random) -> int:
    """One Metropolis walk under a per-step temperature schedule."""
    pos = start
    last = len(energies) - 1
    rand = rng.random
    exp = math.exp
    for temperature in temperatures:
        nxt = pos + 1 if rand() < 0.5 else pos - 1
        if nxt < 0 or nxt > last:
            continue
        d_e = energies[nxt] - energies[pos]
        if d_e <= 0.0 or rand() < exp(-d_e / temperature):
            pos = nxt
    return pos


# --- Experiment A: fixed-temperature stochastic escape ----------------------

def experiment_a(rng: random.Random, tracked: list[float],
                 lines: list[str]) -> tuple[list, list]:
    lines.append("--- Experiment A: fixed-temperature stochastic escape "
                 "-------------------")
    lines.append("Barrier height is an energy difference on the landscape; "
                 "temperature is")
    lines.append("the walker's noise scale. Distinct knobs, varied "
                 "independently below.")
    lines.append("Start: shallow-well minimum. Escape = first arrival at "
                 "the deep-well")
    lines.append(f"minimum within {MAX_STEPS_A} steps. "
                 f"Trials per cell: {TRIALS_A}.")
    lines.append("")
    barrier_notes = []
    freq_rows = []
    acc_rows = []
    for scale in BARRIER_SCALES:
        xs, energies = make_landscape(scale)
        tracked.extend(energies)
        shallow, barrier, deep = landscape_features(energies)
        barrier_height = energies[barrier] - energies[shallow]
        tracked.append(barrier_height)
        barrier_notes.append(
            f"  h={scale:.2f}: measured barrier height from start well "
            f"= {barrier_height:.3f}  (top at x={xs[barrier]:+.2f})")
        freq_row = []
        acc_row = []
        for temperature in TEMPERATURES:
            uphill = [0, 0, 0.0]
            escaped = stayed = ran = 0
            for _ in range(TRIALS_A):
                ran += 1
                if escape_trial(energies, shallow, deep, temperature,
                                MAX_STEPS_A, rng, uphill):
                    escaped += 1
                else:
                    stayed += 1
            require(escaped + stayed == ran == TRIALS_A,
                    "trial counts must be conserved (Experiment A cell)")
            frequency = checked_fraction(escaped, TRIALS_A, tracked)
            freq_row.append((frequency, escaped))
            if uphill[0] > 0:
                measured = checked_fraction(uphill[1], uphill[0], tracked)
                theory_mean = uphill[2] / uphill[0]
                require(0.0 <= theory_mean <= 1.0,
                        "theoretical mean acceptance escaped [0, 1]")
                tracked.append(theory_mean)
                acc_row.append((measured, theory_mean))
            else:
                acc_row.append(None)
        freq_rows.append(freq_row)
        acc_rows.append(acc_row)

    cell_w = 14
    header = ("      h \\ T  |"
              + "".join(f"  T={t:.2f}".ljust(cell_w) for t in TEMPERATURES))
    lines.extend(barrier_notes)
    lines.append("")
    lines.append(f"  Escape frequency (escaped trials of {TRIALS_A} in "
                 f"parentheses):")
    lines.append(header)
    for scale, row in zip(BARRIER_SCALES, freq_rows):
        cells = "".join(f"  {f:.3f} ({n:3d})".ljust(cell_w) for f, n in row)
        lines.append(f"      h={scale:4.2f} |" + cells)
    lines.append("")
    lines.append("  Uphill acceptance during those walks, "
                 "measured/theoretical mean:")
    lines.append(header)
    for scale, row in zip(BARRIER_SCALES, acc_rows):
        cells = ""
        for entry in row:
            text = ("  n/a" if entry is None
                    else f"  {entry[0]:.3f}/{entry[1]:.3f}")
            cells += text.ljust(cell_w)
        lines.append(f"      h={scale:4.2f} |" + cells)
    return freq_rows, acc_rows


# --- Experiment B: geometric simulated annealing ----------------------------

def experiment_b(rng: random.Random, tracked: list[float],
                 lines: list[str]) -> dict:
    lines.append("--- Experiment B: geometric simulated annealing "
                 "-------------------------")
    xs, energies = make_landscape(ANNEAL_BARRIER_SCALE)
    tracked.extend(energies)
    shallow, barrier, deep = landscape_features(energies)
    barrier_height = energies[barrier] - energies[shallow]
    basin_gap = energies[shallow] - energies[deep]
    tracked.extend([barrier_height, basin_gap])
    alpha = (T_END / T_START) ** (1.0 / (STEPS_B - 1))
    tracked.append(alpha)
    cooling = [T_START * alpha ** k for k in range(STEPS_B)]
    quench = [T_END] * STEPS_B
    lines.append(f"Same landscape family and walker as Experiment A, "
                 f"h={ANNEAL_BARRIER_SCALE:.2f}.")
    lines.append(f"Start: shallow-well minimum. Barrier height "
                 f"{barrier_height:.3f}; the deep basin")
    lines.append(f"floor lies {basin_gap:.3f} below the start basin floor.")
    lines.append(f"Cooling arm : geometric schedule, T {T_START:.2f} -> "
                 f"{T_END:.2f} over {STEPS_B} steps")
    lines.append(f"              (per-step factor alpha = {alpha:.6f}).")
    lines.append(f"Quench arm  : abrupt jump to T={T_END:.2f}, held for the "
                 f"same {STEPS_B} steps.")
    lines.append(f"Trials per arm: {TRIALS_B}. Final basin read from the "
                 f"walker's last position.")
    lines.append("")
    results = {}
    for arm_name, temps in (("geometric cooling", cooling),
                            ("abrupt quench", quench)):
        n_shallow = n_deep = n_top = ran = 0
        for _ in range(TRIALS_B):
            ran += 1
            final = schedule_trial(energies, shallow, temps, rng)
            if final == barrier:
                n_top += 1
            elif (final < barrier) == (shallow < barrier):
                n_shallow += 1
            else:
                n_deep += 1
        require(n_shallow + n_deep + n_top == ran == TRIALS_B,
                "trial counts must be conserved (Experiment B arm)")
        fractions = tuple(checked_fraction(count, TRIALS_B, tracked)
                          for count in (n_shallow, n_deep, n_top))
        results[arm_name] = (fractions, (n_shallow, n_deep, n_top))

    lines.append("  Final-basin proportions (trial counts in parentheses):")
    lines.append("      arm                   shallow basin   deep basin"
                 "      barrier top")
    for arm_name in ("geometric cooling", "abrupt quench"):
        fractions, counts = results[arm_name]
        cells = "".join(f"  {f:.3f} ({c:3d})  "
                        for f, c in zip(fractions, counts))
        lines.append(f"      {arm_name:<20}" + cells)
    return results


# --- hard theory checks ------------------------------------------------------

def hard_theory_checks(tracked: list[float]) -> None:
    fixed_t = 0.5
    rising_d_e = (0.1, 0.25, 0.5, 1.0, 2.0, 4.0)
    accs = [theoretical_uphill_acceptance(d, fixed_t) for d in rising_d_e]
    for acc in accs:
        require(0.0 <= acc <= 1.0,
                "theoretical acceptance escaped [0, 1] (dE sweep)")
    tracked.extend(accs)
    require(all(a > b for a, b in zip(accs, accs[1:])),
            "theoretical uphill acceptance must fall as dE rises at fixed T")

    fixed_d_e = 1.0
    rising_t = (0.1, 0.2, 0.5, 1.0, 2.0)
    accs_t = [theoretical_uphill_acceptance(fixed_d_e, t) for t in rising_t]
    for acc in accs_t:
        require(0.0 <= acc <= 1.0,
                "theoretical acceptance escaped [0, 1] (T sweep)")
    tracked.extend(accs_t)
    require(all(a < b for a, b in zip(accs_t, accs_t[1:])),
            "theoretical uphill acceptance must rise as T rises at fixed dE")


# --- soft diagnostics --------------------------------------------------------

def soft_section(freq_rows: list, acc_rows: list, anneal: dict,
                 lines: list[str]) -> None:
    lines.append("--- Soft diagnostics (reported only; finite-sample noise "
                 "is NOT a failure) ---")

    barrier_pairs = barrier_against = barrier_ties = 0
    for col in range(len(TEMPERATURES)):
        for row in range(len(BARRIER_SCALES) - 1):
            barrier_pairs += 1
            step = freq_rows[row + 1][col][0] - freq_rows[row][col][0]
            if step > 0:
                barrier_against += 1
            elif step == 0:
                barrier_ties += 1
    tag = ("as expected" if barrier_against == 0
           else "wobble (finite-sample noise, not a failure)")
    lines.append(f"  [soft] escape falls as barrier rises ....... "
                 f"{barrier_against}/{barrier_pairs} adjacent pairs against "
                 f"trend, {barrier_ties} ties -> {tag}")

    temp_pairs = temp_against = temp_ties = 0
    for row in range(len(BARRIER_SCALES)):
        for col in range(len(TEMPERATURES) - 1):
            temp_pairs += 1
            step = freq_rows[row][col + 1][0] - freq_rows[row][col][0]
            if step < 0:
                temp_against += 1
            elif step == 0:
                temp_ties += 1
    tag = ("as expected" if temp_against == 0
           else "wobble (finite-sample noise, not a failure)")
    lines.append(f"  [soft] escape rises as temperature rises ... "
                 f"{temp_against}/{temp_pairs} adjacent pairs against "
                 f"trend, {temp_ties} ties -> {tag}")

    deep_cooling = anneal["geometric cooling"][0][1]
    deep_quench = anneal["abrupt quench"][0][1]
    tag = ("as expected" if deep_cooling > deep_quench
           else "wobble (finite-sample noise, not a failure)")
    lines.append(f"  [soft] cooling beats quench on deep basin .. "
                 f"{deep_cooling:.3f} vs {deep_quench:.3f} -> {tag}")

    diffs = []
    for row in acc_rows:
        for entry in row:
            if entry is not None:
                diffs.append(abs(entry[0] - entry[1]))
    max_diff = max(diffs) if diffs else 0.0
    tag = ("close" if max_diff < 0.02
           else "loose (finite-sample noise, not a failure)")
    lines.append(f"  [soft] Monte Carlo vs theory acceptance .... "
                 f"max |measured - theoretical| = {max_diff:.4f} "
                 f"(tol 0.02) -> {tag}")


# --- report ------------------------------------------------------------------

def build_report(seed: int) -> str:
    rng = random.Random(seed)
    tracked: list[float] = []
    lines: list[str] = []
    lines.append("=" * 74)
    lines.append("Stochastic escape / annealing toy -- NON-CANONICAL theory "
                 "sandbox")
    lines.append("=" * 74)
    lines.append("Mechanism : discrete Metropolis-style walker on a fixed "
                 "parametric 1D")
    lines.append("            double-well energy landscape; dimensionless "
                 "toy units.")
    lines.append(f"Landscape : E(x) = h*(x^2 - 1)^2 + ({TILT})*x on "
                 f"{GRID_POINTS} sites over [{X_MIN}, {X_MAX}].")
    lines.append(f"Seed      : {seed} (one seeded generator; fully "
                 f"deterministic run)")
    lines.append("Disclaimer: this is NOT quantum tunnelling -- a classical "
                 "Metropolis random")
    lines.append("            walk only; no quantum model is implemented or "
                 "implied.")
    lines.append("")
    freq_rows, acc_rows = experiment_a(rng, tracked, lines)
    lines.append("")
    anneal = experiment_b(rng, tracked, lines)
    lines.append("")
    hard_theory_checks(tracked)
    require(all(math.isfinite(value) for value in tracked),
            "no NaN or infinite value may appear in tracked quantities")
    lines.append("--- Hard self-checks (any failure aborts the run) "
                 "----------------------")
    lines.append("  [hard] probabilities/frequencies within [0, 1] "
                 "............. OK")
    lines.append("  [hard] trial counts conserved (every cell, every arm) "
                 "...... OK")
    lines.append("  [hard] theoretical acceptance falls as dE rises at "
                 "fixed T .. OK")
    lines.append("  [hard] theoretical acceptance rises as T rises at "
                 "fixed dE .. OK")
    lines.append(f"  [hard] no NaN or infinite value "
                 f"({len(tracked)} tracked quantities) ... OK")
    lines.append("")
    soft_section(freq_rows, acc_rows, anneal, lines)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=("Stochastic escape / annealing toy (NON-CANONICAL "
                     "theory sandbox; text output only)."))
    parser.add_argument("--seed", type=int, default=42,
                        help="seed for the deterministic run (default: 42)")
    args = parser.parse_args()
    try:
        report = build_report(args.seed)
        rebuilt = build_report(args.seed)
        require(rebuilt == report,
                "identical seed/config must reproduce a byte-identical "
                "report")
        print(report)
        print()
        print("--- Run-level hard self-check ------------------------------"
              "------------")
        print("  [hard] identical seed/config reproduces byte-identical "
              "report . OK")
    except SelfCheckFailure as failure:
        print(failure)
        print()
        print(FOOTER)
        raise SystemExit(1)
    print()
    print(FOOTER)


if __name__ == "__main__":
    main()
