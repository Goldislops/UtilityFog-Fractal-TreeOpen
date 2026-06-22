# Theory Sandbox — Policy + Inventory

> **Status**: policy **and live inventory**. **Six toy scripts now exist across five toys** (Toy #1 Galton/Fourier diffusion; Toy #2 stochastic-escape/annealing; Toy #3 decaying scent-trail tracking; Toy #4 Janus gradient; Toy #5 passive "MOF" trap — **v0 latch-capture + v1 Strict-Passive release-trap**) — each **non-canonical**, each landed as its own reviewed PR. Each new toy still lands only as its own small PR after its inception note is reviewed (one toy per PR; see §4 + §6).
>
> **What this is**: a **non-canonical proving ground** for toy explorations of ideas already recorded in `docs/MEDUSA_THEORY_INTAKE_LEDGER.md` or `docs/MATURIN_ARC_THEORY_PREFLIGHT.md` (Janus gradients, Galton/Fourier diffusion, stochastic escape, scent-trail tracking, MOST stored-strain, …).
>
> **What this is NOT**: engine code · observer semantics · Lane A · Swarm Hunter · CI-gated tests · evidence that any theory is true. A pretty plot in here proves nothing about Medusa.

**Created**: 2026-06-10 (84/Fab5), per AURA's "proving ground" delta and Jack's policy-first sequencing. **Inventory last corrected**: 2026-06-19 (84, Phase 2B-5H-1). **Guardrails**: Lane A parked; quarantine rules below.

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

1. **No imports from engine runtime** (`scripts/continuous_evolution_ca.py`, `medusa_api`, tuning/event-bus modules) unless explicitly reviewed and noted in the script header. Importing the *built* `uft_ca` extension read-only for toy lattices is acceptable — it's a library, not the running engine. **Read that narrowly**: `uft_ca` here is for **small, isolated toy lattices only** — not a bridge into production Medusa state/snapshots, not for sweeps, and never as evidence that an engine claim is validated.
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

## 6. Toy inventory & candidates

### 6a. Implemented toys (non-canonical; each landed as its own PR)

| Toy | File | Explores (ledger/preflight ref) | Status |
|---|---|---|---|
| **#1 Galton/Fourier diffusion** | `galton_fourier_diffusion_toy.py` | Preflight §12 | non-canonical toy (PR #200) — inspiration only, not Medusa validation |
| **#2 Stochastic escape / annealing** | `stochastic_escape_annealing_toy.py` (+ `TOY_02_STOCHASTIC_ESCAPE_ANNEALING_INCEPTION.md`) | Preflight §13 | non-canonical toy (PR #204) — algorithmic language only, not quantum physics |
| **#3 Decaying scent-trail tracking** | `scent_trail_tracking_toy.py` (+ `TOY_03_SCENT_TRAIL_TRACKING_INCEPTION.md`) | Ledger entry 14 (scent trails) | non-canonical toy (Phase 2B-5H-2) — implements the sealed inception contract; a *falsifiable* trail-vs-no-trail reacquisition test (treatment may tie/lose; no success asserted) — **not radioactive physics, not a hunt, not Medusa validation** |
| **#4 Janus gradient** | `janus_gradient_toy.py` (+ `TOY_04_JANUS_GRADIENT_INCEPTION.md`) | Ledger entry 9 / preflight §5 | non-canonical toy (inception #249 + metric erratum #250 sealed; script = this PR) — implements the **ratified pre-registration lock + Addendum 2** verbatim: a **memoryless** discrete asymmetric gradient-sampling rule vs a symmetric/gradient-blind control on 3 static fields (100 seeds × 3 geometries), separating **net displacement (drift)** from a **centered-MSD `α_var` (spreading)** exponent so raw MSD cannot masquerade as superdiffusion; treatment may tie/lose/confine, **no success asserted** — **not real Janus particles, not phoresis, not propulsion, not Medusa validation** |
| **#5 Passive "MOF" trap** | `passive_mof_trap_toy.py` (+ `TOY_05_PASSIVE_MOF_TRAP_INCEPTION.md`) | Ledger entry 14 (passive geometric traps / "MOF") | non-canonical toy (inception #252 + stats erratum #253 sealed; script = this PR) — implements the **ratified v0 lock + Addendum 1** verbatim: does a **static localized latch rule-mask** (`B3/S012345678` inside sector / `B3/S23` outside) arrest a **canonical Conway glider** vs a homogeneous baseline, keeping it recognizable? **128 deterministic conditions** (4 orientations × 4 phases × 8 offsets); v0 is **noise-free → exact category counts, no p-values/CIs/tests** (noise/inferential → v1); **capture NEVER asserted**. **Target is an externally-canonical glider, NOT native Medusa evidence; not chemistry, not a real Metal-Organic Framework, not Medusa validation.** |
| **#5 v1 Release-style / identity-preserving trap (Strict Passive)** | `release_trap_toy.py` (+ `TOY_05_V1_RELEASE_TRAP_INCEPTION.md`) | Ledger entry 14 (passive geometric traps / "MOF") | non-canonical toy (inception #255 sealed; script = this PR) — implements the **ratified Strict-Passive v1 lock + Addendum 1** verbatim: an **always-on inside-sector freeze** (`[0,t_rel)`, then `B3/S23` release) — can it **hold** a canonical glider and let it **re-emerge** on release? 384 deterministic conditions (128 trajectories × hold {8,40,200}); exact-count, no stats; **release-success NEVER asserted** (classifier tests success first). **Result (reported): 0/384 release-success** — the already-closed passive door **shears** the glider on entry (372 identity-loss, 12 clean-annihilation; control 128/128 pass-through). **External canonical glider, NOT native Medusa evidence; not chemistry, not a real Metal-Organic Framework.** |

*Toy #5 trap-arc **synthesis / capstone**: [`TOY_05_SYNTHESIS.md`](TOY_05_SYNTHESIS.md) — what v0 (capture-with-transformation) and v1 (inert-wall shear) established, the capture↔identity tension, the explicit non-claims, and the gated forward queue (compliant "yield-then-lock" trap / shutter / Janus+MOF coupling).*

### 6b. In design-inception (no script yet)

| Toy | Inception doc | Explores | Status |
|---|---|---|---|
| *(none currently — Toy #5 v1 has graduated to an implemented script; see §6a)* | | | |

### 6c. Other listed candidates (not yet inception)

| Candidate | Explores (ledger/preflight ref) | Sketch |
|---|---|---|
| MOST stored-strain metaphor toy | Ledger entry 10 / preflight §7 | latent "tension" accumulate-and-release dynamics on a toy state machine — metaphor mechanics only, no chemistry claims |
| Discrete compliant / quasi-mechanism trap | Ledger entry 15 | yielding-then-locking local rule metaphor inspired by corrected flexible-polyhedra intake; would require explicit invariants and a fresh design-inception before any script |

*(Janus gradient graduated from this list to design-inception — see §6b, `TOY_04_JANUS_GRADIENT_INCEPTION.md`.)*

Each candidate becomes real only via its own PR, with the §3 header discipline and §4 gate understood. A positive toy result still cannot touch the engine, observer vocabulary, Vanguard, Lane A or Swarm Hunter without a separate, explicitly-gated design + implementation phase.

---

*The sandbox is a glass box: look at the cathedral all you like — hands stay off the load-bearing walls.*
