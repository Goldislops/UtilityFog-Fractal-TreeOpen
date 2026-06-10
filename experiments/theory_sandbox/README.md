# Theory Sandbox — Policy (no scripts yet)

> **Status**: policy README only. **This directory contains no experiments yet.** The first toy script lands only after this policy is merged and a specific toy is approved as its own small PR.
>
> **What this is**: a **non-canonical proving ground** for toy explorations of ideas already recorded in `docs/MEDUSA_THEORY_INTAKE_LEDGER.md` or `docs/MATURIN_ARC_THEORY_PREFLIGHT.md` (Janus gradients, Galton/Fourier diffusion, stochastic escape, MOST stored-strain, …).
>
> **What this is NOT**: engine code · observer semantics · Lane A · Swarm Hunter · CI-gated tests · evidence that any theory is true. A pretty plot in here proves nothing about Medusa.

**Created**: 2026-06-10 (84/Fab5), per AURA's "proving ground" delta and Jack's policy-first sequencing. **Guardrails**: Lane A parked; quarantine rules below.

---

## 1. Purpose

- Give theory-ledger / preflight ideas a place to be **played with** — small, cheap, clearly-caveated toy scripts — *without* touching maintained tests, production code, or the engine.
- Convert "interesting metaphor" into "explored metaphor with a falsifiable sketch" **before** anyone argues for promotion.
- Keep exploratory chaos out of the cathedral: the maintained floor (`tests/`, CI) stays exactly as honest as the #165/#180 arcs made it.

## 2. Non-goals

- **Not engine code** — nothing here ships into `scripts/continuous_evolution_ca.py`, `crates/uft_ca`, or any runtime path.
- **Not observer semantics** — no token/vocabulary/status-model changes originate here.
- **Not Lane A, not Swarm Hunter** — no acting on observer signals, no controller prototypes.
- **Not CI-gated** — nothing in this directory runs in `verify-python` (see §5).
- **Not proof** — sandbox output is *inspiration / evidence-candidate*, never validation. The ledger's status labels still govern.

## 3. Directory rules (the quarantine)

1. **No imports from engine runtime** (`scripts/continuous_evolution_ca.py`, `medusa_api`, tuning/event-bus modules) unless explicitly reviewed and noted in the script header. Importing the *built* `uft_ca` extension read-only for toy lattices is acceptable — it's a library, not the running engine.
2. **No writes to `data/`** — ever. Toy outputs go to a git-ignored `experiments/theory_sandbox/out/` (or tempfiles).
3. **No production sweeps**, no long-running jobs, no GPU grabs without coordinating with Kevin (BOINC/F@H/Medusa share the box).
4. **No heavy new dependencies** (and no notebooks) without review — the lean-install discipline applies here too.
5. **Small, deterministic where possible, clearly caveated** — seed your randomness; print your assumptions.
6. **Every script header must state**: which ledger/preflight entry it explores · status of that entry · what the toy can and cannot show.
7. One toy per PR; each toy is its own reviewed brick.

## 4. Promotion gate (sandbox → architecture)

A sandbox result **cannot** become design or code without **all** of:

1. **source verification** of the underlying claim;
2. an **explicit design doc**;
3. **tests or falsification criteria**;
4. **Jack / AURA / Kev review**;
5. an **explicit separate PR** (never "while we're here");
6. **no Lane A activation unless separately gated** — a sandbox plot is not a gate pass.

This mirrors the graduation path in the Theory Intake Ledger and the promotion gate in the Maturin preflight; the future Theory Tripwire (design: `docs/THEORY_TRIPWIRE_ACTION_DESIGN.md`) is expected to fire on any such promotion attempt.

## 5. CI policy

- `pytest.ini` scopes collection to `tests/`, so nothing here is collected by `pytest` or by the `verify-python` gate — **keep it that way**.
- Sandbox scripts must not be added to CI by default. If a specific check is ever wanted (e.g. "toy still runs"), it must be **opt-in, separate from the gate, and its own reviewed PR**.
- A sandbox failure must never be able to redden the maintained floor.

## 6. First candidate toys (listed only — NOT implemented here)

| Candidate | Explores (ledger/preflight ref) | Sketch |
|---|---|---|
| Janus gradient toy | Ledger entry 9 / preflight §5 | asymmetric agents on a 2D field; does local-gradient sensing yield ballistic-ish curves? |
| Galton/Fourier diffusion toy | Preflight §12 | compare discrete random walks vs heat-equation smoothing on a small lattice |
| Stochastic escape / annealing toy | Preflight §13 | escape probability vs barrier height for trapped configurations (algorithmic language only) |
| MOST stored-strain metaphor toy | Ledger entry 10 / preflight §7 | latent "tension" accumulate-and-release dynamics on a toy state machine — metaphor mechanics only, no chemistry claims |

Each becomes real only via its own PR, after this policy merges, with the §3 header discipline and §4 gate understood.

---

*The sandbox is a glass box: look at the cathedral all you like — hands stay off the load-bearing walls.*
