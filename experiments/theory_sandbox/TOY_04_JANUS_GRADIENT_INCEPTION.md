# Toy #4 Inception — Janus Gradient Kinetics (design only, no script)

> **Status**: inception/design note only. **No script exists yet, and this note authorizes none.** The toy itself lands only in a later, separate PR after Jack/AURA/Kev review this note. Per `experiments/theory_sandbox/README.md`: one toy per PR; this is the *zeroth* brick of Toy #4 — the thinking before the toy.
>
> **NON-CANONICAL TOY (design):** a discrete asymmetric sampling rule that drifts across a toy lattice proves nothing about Medusa. This is an **algorithmic lattice-displacement toy** — *not real Janus particles, not phoresis, not propulsion, not active-matter physics, and not engine validation.* The word "Janus" is retained as a **label only**; throughout this note it means **discrete asymmetric gradient sampling**, never a colloidal particle. The poetry is allowed to ride along; it is not allowed to drive the bus.

**Explores:** `docs/MEDUSA_THEORY_INTAKE_LEDGER.md` entry 9 (Janus Gradient Kinetics / active asymmetric propulsion) / `docs/MATURIN_ARC_THEORY_PREFLIGHT.md` §5 (Janus gradient kinetics / active matter).
**Status of that entry:** *speculative inspiration / candidate design principle — not current engine design* (the colloidal science is real; the Medusa mapping is the speculative part).

## 0. Current model seat

Authored by **84** (`claude-opus-4-8`), desktop seat, 2026-06-20, under the Toy #4 docs-only inception authorization (AURA blessed → Jack accepts → Kev relayed). *(Future seats editing this doc: state your seat here per the model-seat hygiene protocol in `AGENT_HANDOFF.md`.)*

## 1. Source and status

- **Source**: AURA's explicit ruling blessing Toy #4 = Janus gradient (relayed via Jack/Kev, 2026-06-20), grounded in `docs/MEDUSA_THEORY_INTAKE_LEDGER.md` **entry 9** (Janus Gradient Kinetics / active asymmetric propulsion) and `docs/MATURIN_ARC_THEORY_PREFLIGHT.md` **§5** (Janus gradient kinetics / active matter).
- **Status**: speculative **discrete sandbox design only**. Ledger entry 9 is classified *speculative inspiration / candidate design principle — not current engine design*; the **established colloidal science is real, but the Medusa mapping is the speculative part** (entry 9's own caveat). This toy explores only the *algorithmic* question of whether a discrete asymmetric local-sampling rule produces directed lattice displacement.
- **Non-canonical. Not architecture evidence.** This toy deliberately does **not** import or touch any engine primitive (CA rules, memory grid, `signal_field`, `uft_ca`). If it ever validates, wiring any idea into the engine is a **separate, later, six-step-gated** arc (README §4).

## 2. Precise falsifiable hypothesis (AURA/Jack-pinned)

> Under **exactly pre-registered seeds and geometries**, a discrete asymmetric "Janus" gradient-sampling rule over a **static scalar field** exhibits **directed superdiffusive lattice displacement** that is **statistically distinct** from a symmetric / gradient-blind baseline on the **same field**.

The toy **must be permitted to falsify this.** The asymmetric rule may tie, fail to separate from baseline, or destabilise — and that outcome must be reportable without any hard assertion to the contrary (§6). "Statistically distinct" means a declared, pre-registered test over the fixed seed/geometry set — *not* a search for a setting that happens to separate.

## 3. Mechanism (design intent — pin fully in the later script PR, review first)

### 3.1 The single experimental variable
**The sole variable under test is the *symmetry* of the rule's local gradient sampling.** Everything else is shared and identical between the two arms.

- **Treatment** — discrete **asymmetric** sampling: an **integer gradient bias** derived from the local field neighbourhood steers the next lattice move (an asymmetric read of the neighbourhood, resolved to a single legal cardinal step).
- **Control** — **gradient-blind or perfectly symmetric** sampling: the same walker on the same field, but its local read carries **no net directional bias** (either it ignores the field entirely, or it samples it symmetrically so no preferred direction emerges).

### 3.2 Shared, identical across both arms
- the same **static scalar field**;
- the same **PRNG seed** per trial;
- the same **start cell**;
- the same **step budget** `T_max`;
- the same **tie-break rules** and **lattice topology**;
- the same **measurement pipeline** (displacement + MSD computation).

**Field symmetry of the local sampling rule is the only thing that differs.** This mirrors Toy #3's discipline (trail-visibility was Toy #3's sole variable; gradient-sampling symmetry is Toy #4's).

### 3.3 Static field (no dynamics)
The scalar field is **static** — it is generated once per geometry and never updated during a run. There is no field diffusion, no deposition, no feedback from the walker onto the field. This keeps the toy minimal and the variable clean.

### 3.4 Two distinct effects — drift vs spreading (metric erratum; post-seal Codex P2 on #249)
"Bias your steps toward the gradient and you will, trivially, move up the gradient" is not interesting — and **raw mean-squared displacement measured from the start cell does not separate the interesting part from the trivial part.** A biased walk grows its raw MSD as `⟨r²⟩ ≈ v²·t² + D·t`: the `v²·t²` term is pure **directed drift**, so a *raw*-MSD exponent can read "ballistic" (toward 2) even when the only effect is ordinary drift and the genuine *spreading* is plainly diffusive. Net displacement already measures the drift (§4), so raw MSD must **not** double as the diffusion/superdiffusion evidence.

The toy therefore measures **two separated quantities**:
- **directed drift** — the net displacement vector / distance (§4);
- **spreading** — a **centered-MSD / ensemble-variance** exponent `α_var`: subtract each arm's **per-time ensemble-mean trajectory** before fitting, so the `v²·t²` drift term is removed and the exponent reflects genuine dispersion *around the mean path*.

The **non-trivial, falsifiable** question is whether asymmetric local sampling produces directed drift **and/or** genuine superdiffusive *spreading* (`α_var` meaningfully > 1) that the symmetric/blind control does not — **not** whether a drift-contaminated raw exponent looks ballistic. A centered exponent is an *emergent* dispersion statistic of the ensemble, not something you can write into one step. A treatment that merely drifts while its centered spreading stays diffusive (`α_var ≈ 1`) is a genuine — and useful — negative result for the *superdiffusion* claim (§5), **even if its net displacement is large**.

## 4. Observables / metrics (Jack-pinned)

**Primary**
- **net displacement (directed-drift observable)** — vector and scalar distance from start at `T_max`, per arm, across the fixed seed ensemble;
- **centered-MSD / ensemble-variance spreading exponent `α_var`** — subtract each arm's **per-time ensemble-mean trajectory**, then fit the centered mean-squared displacement vs step count (superdiffusive spreading `α_var > 1`, diffusive `α_var ≈ 1`, sub-diffusive `α_var < 1`). **This — not raw MSD — is the diffusion/superdiffusion evidence** (the `v²·t²` drift term is removed, §3.4);
- **treatment − control deltas** on the **net displacement** *and* the **centered-MSD spreading exponent**, reported **separately** (treatment success must not rest on one combined exponent), over the identical shared inputs;
- **shared, pre-registered fit** — the same fitting window, fit form, and ensemble-centering method are applied **identically to treatment and control** and declared **before any script** (alongside the seeds/geometries).

**Reported (no success asserted)**
- **raw / uncentered displacement-growth exponent `α_raw`** *(optional)* — if reported at all, label it explicitly as a **"raw displacement-growth exponent," NOT proof of superdiffusion around drift** (it contains the `v²·t²` drift term, §3.4); treatment success must **never** rest on `α_raw` alone;
- per-geometry breakdown (the three geometries in §4.1 need not behave alike, and that is informative, not a failure);
- trajectory stability indicators (did the asymmetric arm stall, oscillate, or wander off-field?).

### 4.1 Power floor — pre-registration, NOT a sweep (the bright line)
- **Exactly 100 pre-registered PRNG seeds.**
- **Exactly 3 pre-defined static field geometries**: **Linear Slope**, **Radial Well**, **Noisy Step-Function**.

This is **pre-registration for statistical power** — the fixed sample (100 × 3) is declared **in the script before any run**, and the verdict is computed over **exactly that frozen set**. Power is decided *before* results are seen.

It is explicitly **NOT** exploratory sweep / search: there is **no** scanning of seed/geometry/parameter ranges to find a favourable setting, and **no** results-dependent expansion of the run set (no "add seeds until it separates"). One sentence to keep the distinction sharp:

> *Pre-registration enlarges a **fixed** sample to make the verdict decidable; a sweep searches the space **for** a verdict. The first is allowed; the second stays parked behind the six-step gate (README §4), at the same bar as the parked CA-search/sweep machinery.*

This is the direct lesson banked from Toy #3, whose single-geometry / 12-seed run left its verdict undecided. Toy #4 is powered up front so its verdict is decidable rather than thin.

## 5. Useful negative results (must be reportable)
A negative result here is **valuable**, not a failure of the toy — it is an early, cheap caution against entry-9's central design principle (node motion from local gradient + internal asymmetry) **before** anyone proposes building it. Two honest negatives the toy must be able to report:
- **No separation**: treatment's **net-displacement delta ≈ 0** *and* its **centered-MSD spreading exponent `α_var` ≈ control's `α_var` ≈ 1** — asymmetric local sampling buys neither directed drift nor genuine superdiffusive *spreading* over the symmetric/blind baseline on the fixed set. (A large net displacement with `α_var ≈ 1` is **drift without superdiffusion** — still a negative for the superdiffusion claim, per §3.4.) **or**
- **Instability**: the asymmetric rule **fails stability** / the trajectory structure "shatters" (stalls, traps, or degenerates) under the specified rule subset.

Either outcome is recorded plainly. No hard assertion that treatment wins (§6).

## 6. Hard self-checks vs scientific outcome
**Hard self-checks may enforce only instrument correctness** (a failure means the toy is broken, not that the hypothesis failed):
- **determinism** — same seed → byte-identical textual metrics; same-seed rerun is byte-identical;
- **identical shared inputs across arms** — assert equality of field, seed, start, budget, tie-breaks, topology, and the measurement pipeline inputs between treatment and control;
- **legal moves** — the walker stays in-bounds; exactly one legal lattice move per tick (cardinal, per the pinned topology);
- **correct MSD calculation (centered vs raw, shared fit)** — the displacement, centering, and exponent fits are verified against constructed synthetic trajectories: (a) a **pure-drift** trajectory (constant velocity, no noise) must yield **`α_raw ≈ 2` but `α_var ≈ 0`** (flat centered variance — the check that centering actually removes drift, §3.4); (b) a **pure-diffusion** trajectory (zero mean drift) must yield **`α_var ≈ 1`**; (c) a **drift + diffusion** trajectory must recover **`α_var ≈ 1`** despite a near-ballistic `α_raw`. The same fitting window/method is applied to both arms (assert identical fit configuration).

**Do NOT hard-assert that treatment beats control.** That is the hypothesis and must be allowed to fail; treatment-vs-control outcomes are *reported*, never asserted.

## 7. Language quarantine (Jack-pinned)
To keep the metaphor from smuggling in physics claims the toy does not make:

- **VETOED vocabulary** (must not appear except in an explicit "this is NOT" disclaimer): *phoresis, self-phoresis, continuous thermodynamics, propulsion force, floating-point vectors, Navier–Stokes, physical mass.*
- **APPROVED vocabulary**: *discrete asymmetric sampling, integer gradient bias, superdiffusive state translation, lattice displacement.*

"Janus" is kept as the **label**; every section that uses it must keep reminding the reader it denotes **discrete asymmetric sampling**, not a real Janus particle.

## 8. Output and quarantine
- **Text / table output first**; compact tables of (geometry, arm, α, net displacement) + aggregate means over the 100-seed set + treatment−control deltas + the §4 reported diagnostics.
- Optional CSV **only** under the git-ignored `experiments/theory_sandbox/out/`.
- **stdlib + NumPy only**; **no plots in v0**.
- **No engine-runtime imports**; **no `uft_ca`**; **no production data**; **no `data/` writes**; **no CI collection** (`pytest.ini` `testpaths=tests` holds); **no GPU**; **no R3**; **no sweep / search / mutation modes**.
- Must print the non-canonical warning every run, house style: *"NON-CANONICAL TOY: an asymmetric sampling rule drifting across a toy lattice proves nothing about Medusa; not real Janus particles, not phoresis, not propulsion."*
- Header must follow README §3.6: cite ledger entry 9 / preflight §5, status, can/cannot show, quarantine line.

## 9. Promotion boundary
The README §4 **six-step promotion gate** applies in full: (1) source verification, (2) explicit design doc, (3) tests/falsification criteria, (4) Jack/AURA/Kev review, (5) explicit separate PR, (6) no Lane A activation unless separately gated. **Even a positive result cannot alter the engine, the observer vocabulary, Vanguard, Lane A or Swarm Hunter** without a later, explicit, separately-gated design + implementation phase. A pretty superdiffusive α is inspiration-grade only.

## 10. Resolved decisions and remaining questions

**Pinned by AURA/Jack (binding for the future script PR):**
- hypothesis as stated in §2 (pre-registered seeds/geometries; static scalar field; superdiffusive lattice displacement vs symmetric/blind baseline; statistically distinct on the same field);
- sole variable = symmetry of the rule's local gradient sampling (treatment asymmetric / control symmetric-or-blind);
- shared field/seed/start/budget/tie-breaks/topology/measurement pipeline;
- observables = **net displacement** (vector + scalar, directed-drift) at `T_max` **and** a **centered-MSD / ensemble-variance spreading exponent `α_var`** (drift removed, §3.4), reported as **separate** treatment−control deltas; raw/uncentered `α_raw` is optional and explicitly **not** superdiffusion proof; the same fitting window/method is pre-registered and identical across arms;
- power floor = **exactly 100 pre-registered seeds × exactly 3 static geometries** (Linear Slope, Radial Well, Noisy Step-Function); pre-registration for power, **not** a sweep;
- negatives are reportable (no-separation **or** instability);
- language quarantine (§7);
- hard self-checks limited to instrument correctness; no treatment-win assertion;
- **no implementation authorized by this note.**

**Genuinely open (implementer's choice, declared/pinned in the eventual script before any run; not blocking):**
- the literal 100 seed integers and the exact parameterisation of each of the three geometries (must be fixed/declared in the script — pre-registered, not searched);
- lattice size and `T_max` step budget (declared constants; chosen so the three geometries are boundary-safe and α is fittable);
- the exact form of the asymmetric integer-gradient-bias rule and the symmetric/blind control rule (must satisfy §3.1–§3.2 and the §6 self-checks);
- the declared statistical test used for "statistically distinct," and its tolerance;
- the centered-MSD `α_var` fit method (e.g. log–log slope of **centered** MSD vs step), the chosen fit window, and the §6 synthetic self-check cases (pure-drift, pure-diffusion, drift+diffusion) — all declared/pre-registered before any run.

**Nothing else material remains open** — the variable, the shared inputs, the observables, the power floor, the negatives, the language, and the quarantine are all pinned above.

---

*Glass box rules apply. An asymmetric rule may drift across the lattice; the cathedral does not move. "Janus" is a costume, not a claim.*
