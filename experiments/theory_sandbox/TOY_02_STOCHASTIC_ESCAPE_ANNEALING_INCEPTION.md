# Toy #2 Inception — Stochastic Escape / Annealing (design only, no script)

> **Status**: inception/design note only. **No script exists yet.** The toy itself lands only in a later, separate PR after Jack/AURA/Kev review this note and answer §8. Per `experiments/theory_sandbox/README.md`: one toy per PR; this PR is the *zeroth* brick of toy #2 — the thinking before the toy.

## 1. Current model seat

Authored by **Fab5** (`claude-fable-5`), desktop seat, 2026-06-10 (late Wednesday, Sydney time). No silent seat change detected at time of writing. *(Future seats editing this doc: state your seat here per the model-seat hygiene protocol.)*

## 2. Source / status

- **Reference**: `docs/MATURIN_ARC_THEORY_PREFLIGHT.md` **§13** ("Quantum tunneling / 'Hawking escape'").
- **Status**: speculative **algorithmic** metaphor / exploratory sandbox candidate. Per §13's own caveat, the preferred vocabulary is *algorithmic* — **stochastic escape, simulated annealing, local-minimum escape** — *not* quantum mechanics; there is no quantum model here and none is claimed.
- **Non-canonical. Not architecture evidence.** A trapped marble escaping a toy well proves nothing about Medusa.

## 3. Purpose

Explore, in toy algorithmic language only, the cluster of ideas around **trapped configurations**: local minima, barrier height, noise/"temperature", escape probability, and annealing-style cooling schedules. The long-horizon *interest* (not commitment) is the preflight-§13 question of how deadlocked structures might one day escape dead-end geometries — but this toy's only job is to make the *mathematics of escape* concrete, seeded, and falsifiable inside the glass box. It prepares a future tiny script PR; it does not write it.

## 4. What the future toy could show

- A simple **1D (or small 2D) toy energy landscape** with two or more basins separated by barriers of configurable height.
- **Escape probability as a function of barrier height and noise/temperature** — empirically measured over seeded trials, compared against the expected exponential suppression (Arrhenius/Kramers-flavoured ~`exp(-ΔE/T)` scaling, stated as toy expectation, not physics claim).
- **Cooling-schedule effects on final basin selection** — does slow annealing find the deeper basin more often than quenching?
- **Seeded determinism** throughout (same seed → byte-identical output).
- **Text-first output**: compact tables of (barrier, T, escape rate) and (schedule, basin-hit frequencies). No plots in v0 (per Jack's text-first posture from the #200 review).

## 5. What it cannot show

- Nothing about **Medusa engine dynamics** — no CA rules, no voxel state, no memory grid.
- Nothing about **observer semantics**, **Lane A**, or **Swarm Hunter**.
- Nothing about **real quantum tunneling** — the word "quantum" should not appear in the script except possibly in a "this is NOT" disclaimer.
- **No validation of architecture**; no promotion to production. Escape statistics in a toy well are inspiration-grade only.

## 6. Proposed future implementation shape (for the later PR — not now)

- **One Python file**, suggested path: `experiments/theory_sandbox/stochastic_escape_annealing_toy.py`.
- **stdlib + numpy only** (numpy already in the environment); **no notebooks**; **no plotting** unless Jack/AURA/Kev explicitly approve later.
- Optional CSV **only** under `experiments/theory_sandbox/out/` (already gitignored).
- **Self-checks that can fail** — candidates in §8.5, e.g.: escape rate monotonically decreases with barrier height at fixed T; deeper-basin preference under slow cooling exceeds quench baseline; determinism check.
- Must **print the non-canonical warning** every run (house style: *"NON-CANONICAL TOY: a marble escaping a toy well proves nothing about Medusa."*).
- Header must follow the README §3.6 discipline: cite preflight §13, status, can/cannot show, quarantine line.

## 7. Safety / quarantine

- Obeys `experiments/theory_sandbox/README.md` in full: **one toy per PR** · **no engine-runtime imports** · **no `uft_ca`** (not needed here; if a future variant ever wants it, that requires separate review — and is probably still unnecessary) · **no `data/` writes** · **no CI collection** (`pytest.ini` `testpaths=tests` holds) · **no promotion without the six-step gate**.
- The future **Theory Tripwire** (design v0: `docs/THEORY_TRIPWIRE_ACTION_DESIGN.md`) is expected to fire on any promotion attempt arising from this toy's results.
- Lane A remains parked regardless of how charming the escape statistics turn out to be.

## 8. Open questions for Jack / AURA / Kev (answer before the script PR)

1. **Landscape dimensionality**: 1D double-well (simplest, cleanest tables) or small 2D grid landscape (richer basins, harder to summarize)? *Fab5 lean: 1D double-well for v0; 2D only if v0 earns a sequel.*
2. **Barrier source**: fixed/parametric barriers (reproducible, interpretable) or seeded random landscapes (more general, noisier story)? *Lean: fixed parametric for v0.*
3. **Vocabulary**: simulated-annealing framing only, stochastic-escape framing only, or both side-by-side? *Lean: both — one mechanism, two lenses, clearly labelled.*
4. **Output**: table-only confirmed? *Lean: yes, text/tables only in v0.*
5. **Required self-checks**: which of —(a) escape-rate monotonicity vs barrier height; (b) escape-rate monotonicity vs temperature; (c) slow-cool > quench deep-basin preference; (d) determinism — should be hard asserts vs reported-only? *Lean: (a), (d) hard; (b), (c) reported with soft thresholds, since stochastic monotonicity can wobble at small N.*
6. **Temperature schedules in v0**: single simple geometric cooling, or compare 2–3 schedules (constant / geometric / linear)? *Lean: constant-T sweep + one geometric schedule — enough to show the effect without zoology.*

---

*Glass box rules apply. The marble may rattle; the cathedral does not.*
