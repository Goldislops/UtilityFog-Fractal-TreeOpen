# Toy #5 Inception — Passive "MOF" Trap (design only, no script)

> **Status**: inception/design note only. **No script exists yet, and this note authorizes none.** The toy itself lands only in a later, separate PR after Jack/AURA/Kev review this note. Per `experiments/theory_sandbox/README.md`: one toy per PR; this is the *zeroth* brick of Toy #5 — the thinking before the toy.
>
> **NON-CANONICAL TOY (design):** a localized rule-mask arresting a glider on a toy lattice proves nothing about Medusa. This is an **algorithmic passive-trap toy** — *not chemistry, not a Metal-Organic Framework, not molecular binding, not porosity-as-physical-truth, not a guided missile, not a hunt, not Janus/phoretic propulsion.* "MOF" is retained as a **label/analogy only**; throughout this note it means a **static localized rule-mask (spatial heterogeneity)**, never a material.

> **LOAD-BEARING DISCLAIMER (the hinge that keeps the doctrine honest):**
> **The target is an externally canonical glider, NOT a native Medusa discovery.** A read-only repo search (2026-06-21) found **no documented translating structure / glider** in Medusa or its results; rather than invent one, the team escalated and **AURA ruled Option B** — use a textbook-canonical external target. **This is an isolated sandbox proof-of-concept for trap mechanics only.** Nothing here is evidence about Medusa's own dynamics.

> **ERRATUM E1 (2026-06-21 — AURA-ratified, docs-only).** The original sealed text below claimed a "**statistically distinct rate**" for v0. **Corrected:** v0 is **deterministic and noise-free**, so each of the 128 pre-registered conditions yields one fixed outcome and the control captures **0/128 by construction** — inferential statistics (**p-values, confidence intervals, significance tests) are scientifically inappropriate for v0.** v0 compares treatment vs control by **exact category counts over the pre-registered condition table** — an *"exact descriptive rate across the 128 pre-registered deterministic conditions."* **Noise / background / inferential statistics are deferred to a separately-authorized v1.** **U1 ratified (v0 mask):** passive latch **`B3/S012345678` inside the trap sector, baseline `B3/S23` outside** (standard 8-neighborhood reads; writes only inside the sector). **This erratum authorizes no script** — a future implementation still needs separate AURA/Jack/Kev authorization.

## 0. Current model seat

Authored by **84** (`claude-opus-4-8`), desktop seat, 2026-06-21, under the AURA-ruled Option-B authorization for a Toy #5 docs-only inception (AURA ruled → Jack amended the earlier "must cite repo evidence" guard → Kev relayed). *(Future seats editing this doc: state your seat here per the model-seat hygiene protocol in `AGENT_HANDOFF.md`.)*

## 1. Source and authorization chain

- **Toy #4 Janus-alone** is characterized and parked: its memoryless asymmetric gradient rule produced **drift but not superdiffusion** (the pre-accepted negative; sealed `a4bcac2`).
- **Repo-native glider search found no documented target** (exhaustive read-only grep; `run_mini_lattice_mutation_trials` only emits aggregate `collapse/stable/growth` survival scores, `hypothesis_only:True`, with no translation/period/displacement detection). AURA's earlier "known T=4 glider from a schema sweep" had no actual repo evidence.
- **AURA selected Option B**: an externally-canonical target rather than a gated native-Medusa discovery arc.
- **Sequence intact**: Janus alone → **MOF alone** → coupling only after both stand alone. **Toy #5 is MOF-alone; no Janus coupling here.**
- **Source concept**: AURA "Physics of the Utility Fog" intake — passive geometric traps / "MOF" (`docs/MEDUSA_THEORY_INTAKE_LEDGER.md` entry 14, classified *new hypothesis; needs spatial rule heterogeneity; larger arc*). This sandbox toy explores the **trap *mechanics*** in isolation; it does **not** implement the deferred engine-level spatial-heterogeneity arc.

## 2. Source / status / language quarantine

- **Status**: speculative **discrete sandbox design only**. Non-canonical. Not architecture evidence. No engine/`uft_ca`/observer/Vanguard/Lane A import or touch; if it ever validates, wiring anything into the engine is a **separate, later, six-step-gated** arc (README §4).
- **APPROVED vocabulary**: *passive trap, localized rule-mask, spatial heterogeneity, capture, retention, collateral freezing, shatter, pass-through, still life, oscillator.*
- **VETOED vocabulary** (must not appear except in an explicit "this is NOT" disclaimer): *Metal-Organic Framework as physical claim, chemistry / molecular binding / adsorption, porosity-as-physical-truth, guided missile, hunt / hunting / prey, Janus coupling, phoresis / self-phoresis, propulsion.* "MOF" is a label only and must be reminded as such wherever it appears.

## 3. Precise falsifiable hypothesis

> Under fixed pre-registered initial conditions, a **localized passive rule-mask** (a static sector of spatial heterogeneity) can **arrest the translation** of a canonical glider at an **exact descriptive rate** — across the 128 pre-registered deterministic conditions — that **differs from the homogeneous baseline** (which captures 0/128 by construction), **while preserving the target's recognizable structure** (not dissolving it into noise).

*(Erratum E1: v0 is deterministic and noise-free, so the comparison is an **exact category-count enumeration**, not an inferential "statistically distinct rate" — no p-values / confidence intervals / significance tests. Noise + inferential testing are deferred to a separately-authorized v1.)*

The toy **must be permitted to falsify this.** The trap may fail to capture, may shatter the target, or may freeze background indiscriminately — and those outcomes must be reportable without any hard assertion to the contrary. **An honest expectation, set now** (echoing Toy #4's pre-accepted negative): for a Conway glider, "halt translation *and* keep it recognizable" may be **hard or impossible under a passive local mask** — a glider's existence and its translation may be inseparable for this rule class. If so, the **Shatter Effect** (§8) is the valid, expected negative. Designing the toy to be *allowed* to find that is the point.

## 4. Sole variable

**The sole variable is the spatial homogeneity of the ruleset.** Everything else is shared and identical.

- **Treatment** — baseline dynamics **plus** a localized trap mask inside one static sector.
- **Control** — the **homogeneous** baseline rule everywhere (no sector).
- **Shared & identical across both arms**: the same canonical glider, the same initial position(s) and trajectory/phase, the same lattice and topology, the same tick budget, the same background/noise (if any) and seed, the same measurement pipeline. **Only the presence of the localized mask differs.**

## 5. Trap definition

- A **static bounding-box sector** (a fixed rectangle of cells), declared in advance; it does **not** move, grow, steer, chase, sense gradients, read a target's position, or use any Toy #4 / Janus behaviour. It is **passive** — purely a region where the local transition rule differs.
- **Localized mask only inside the sector**: cells *outside* the sector always evolve under the unmodified baseline rule; the mask may **write** only to cells within the sector. Its **read** neighborhood is the *standard* local CA neighborhood — a cell just inside the boundary still reads its normal neighbors, some of which lie just outside the sector (necessary to compute B3/S23 correctly at the edge). There is **no write beyond the sector and no action at a distance.**
- **What the mask is ALLOWED to change** (to be pinned in the script): the cell-update rule *inside the sector only* — e.g. a modified birth/survival set, or a "freeze/latch" overlay that locks a cell to a fixed state after a declared local condition. The intent is to convert a translating structure that enters into a **stationary** structure (still life / oscillator / latched block) **while keeping it recognizable**.
- **What the mask is FORBIDDEN to change**: anything outside the sector; the global rule; the glider's identity *before* it enters; it may not relocate, it may not be retargeted, it may not depend on where the glider is. No sensing, no steering, no gradient bias, no motion, no coupling.

## 6. Target definition (externally canonical)

- **Target**: the **standard Conway Game-of-Life glider** under **B3/S23** (the canonical, most-verified translating structure in CA science — chosen because it is the *opposite* of invented; an external textbook object, not Medusa evidence). *(If a future implementer prefers a different external glider, they must justify the substitution; otherwise Conway is the default.)*
- **Baseline rule**: homogeneous **Conway Life B3/S23** (the rule the target requires) on both arms.
- **Phase / orientation / period / translation**: the Conway glider has **period 4** and translates **one cell diagonally every 4 ticks** (a (1,1) displacement per period), cycling through 4 phases/2 chiral orientations. The exact starting phase, orientation, and direction are a pre-registration lock (§9).
- **"Recognizable structure retained" (capture-without-shatter)**: a declared post-capture criterion, e.g. the captured cells form a known small Life object (a still life such as a **block**, or a low-period oscillator such as a **blinker**) that persists, rather than decaying to empty or to expanding chaos. The exact recognizability predicate is a pre-registration lock (§9), and — when a background/noise field is present — it **must attribute the captured object to the glider's arrival** (e.g. require the object to appear at the glider's intersection cell/time, and/or subtract structures present in a matched **no-glider background run**), so noise-formed or pre-existing blocks/blinkers are not miscounted as captures (this also feeds the Collateral-Freezing measurement, §7). *(Note the deep tension: a block/blinker is stationary and stable but is no longer a "glider" — so "recognizable" here means "a coherent, persistent Life object," not "still a glider." Whether any passive mask can do better than block/blinker/shatter is exactly what the toy tests.)*

## 7. Observables / metrics

**Primary**
- **Capture Rate (true positives)** — fraction of trials where a target glider that intersects the sector has its translation **halted** (centroid stops advancing) within the budget.
- **Retention Stability** — number of ticks the captured structure remains stable/recognizable post-capture (per §6 predicate).
- **Collateral Freezing (false positives)** — amount/rate of background noise frozen into persistent junk inside the sector (only meaningful when a background/noise field is present).

**Also reported (no success asserted)**
- **Shatter Rate** — translation halts but the structure dissolves into noise (not recognizable).
- **Pass-through Rate** — the glider crosses the sector unaffected (no capture).
- treatment − control deltas on the above, over identical shared inputs.

## 8. Useful negative results (must be reportable)

A negative here is **valuable**, not a failure — an early, cheap caution before any engine-level trap is contemplated:
- **Shatter Effect** — the mask halts translation but breaks the local neighborhood the structure needs, so the target dissolves. This would suggest that, **for this rule class, translation and existence are inseparable.**
- **Garbage Choke** — the mask is too loose: it freezes ambient noise into a useless permanent block, so the "trap" becomes solid junk. This would suggest **insufficient "porosity" of the mathematical mask** (label only — no physical porosity claimed).
- **No capture / indistinguishable from control** — the glider passes through; treatment ≈ control.
- **Over-broad corruption** — the mask corrupts background too broadly (a stronger Garbage Choke).

Any outcome is recorded plainly. **No hard assertion that the trap works** (§ self-checks, future script).

## 9. Pre-registration locks for the future script (declare before any run; not chosen here)

The future script PR must freeze, **before any run**, each of: exact **grid size** and topology; exact **glider phase(s)/orientation(s)**; exact **start position(s) and trajectory/trajectories** (so the glider deterministically intersects the sector); exact **trap sector geometry** (position + dimensions); exact **mask rule** (what it changes inside the sector, per §5); exact **capture / retention / collateral / shatter / pass-through definitions and thresholds**; exact **tick budget**; exact **seeds** if any background/noise is used; the exact **outcome-comparison method** — for **v0** this is a **deterministic exact-count enumeration** over the 128 pre-registered conditions (per-category counts per arm; control captures 0/128 by construction; **no p-values / confidence intervals / significance tests** — they are inappropriate for noise-free deterministic dynamics, erratum E1); any **noise/inferential** design is deferred to a separately-authorized **v1**. **Pre-registration for power, not a sweep** — a fixed declared set, no results-dependent expansion, no parameter search (same bright line as Toy #4). **Mark every still-unresolved design lock clearly** in the script PR; do not silently choose.

## 10. Hard self-checks vs scientific outcome (for the future script)

Hard self-checks may enforce only **instrument correctness** (a failure means the toy is broken, not that the hypothesis failed): determinism / byte-identical rerun; identical shared inputs across arms (same glider/start/trajectory/budget/background); the mask touches **only** sector cells (assert no out-of-sector writes); legal CA updates; correct metric computation against constructed cases (e.g. a free glider in the control arm translates exactly (1,1)/period; a **glider–block collision at a disruptive angle** scatters the target into chaotic debris → **Shatter** — note a clean *eater* **annihilates** the glider rather than shattering it, so an eater is the wrong constructed case for Shatter); trial-count conservation; ASCII-only output. **Do NOT hard-assert that the trap captures.** Capture/shatter/choke outcomes are *reported*, never asserted.

## 11. Promotion boundary + explicit non-authorization

The README §4 **six-step promotion gate** applies in full. **Even a positive result cannot alter the engine, the observer vocabulary, Vanguard, Lane A or Swarm Hunter** without a later, explicit, separately-gated design + implementation phase. **This inception authorizes no script.** A future implementation requires **separate AURA / Jack / Kev authorization after this inception is reviewed/sealed.** A working toy trap is inspiration-grade only — and on an *external* canonical glider, it is doubly so: it says something about trap mechanics in Conway Life, **nothing** about Medusa.

---

*Glass box rules apply. A static mask may catch a textbook glider; the cathedral does not move, and the glider was never Medusa's to begin with. "MOF" is a costume, not a claim.*
