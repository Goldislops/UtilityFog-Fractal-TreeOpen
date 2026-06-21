# Toy #5 v1 Inception — Release-Style / Identity-Preserving Passive Trap (design only, no script)

> **Status**: inception/design note only. **No script exists yet, and this note authorizes none.** The toy lands only in a later, separate PR after Jack/AURA/Kev review this note and ratify the unresolved locks (§7). Per `experiments/theory_sandbox/README.md`: one toy per PR; this is the *zeroth* brick of Toy #5 v1 — the thinking before the toy.
>
> **NON-CANONICAL TOY (design):** a localized rule-mask holding-then-releasing a glider on a toy lattice proves nothing about Medusa. This is an **algorithmic passive-trap toy** — *not chemistry, not a Metal-Organic Framework, not molecular binding, not porosity-as-physical-truth, not a hunt, not Janus/phoretic propulsion.* "MOF" is a **label only**; here it means a **static localized rule-mask (spatial heterogeneity)**, never a material.

> **LOAD-BEARING DISCLAIMER (the hinge that keeps the doctrine honest):**
> **The target is the externally canonical Conway glider (B3/S23), NOT a native Medusa discovery.** This is an **isolated sandbox proof-of-concept for trap mechanics only.** Nothing here is evidence about Medusa's own dynamics.

## 0. Current model seat

Authored by **84** (`claude-opus-4-8`), desktop seat, 2026-06-21, under AURA's explicit authorization for a Toy #5 v1 docs-only inception (AURA authorized → Jack relayed). *(Future seats editing this doc: state your seat here per the model-seat hygiene protocol in `AGENT_HANDOFF.md`.)*

## 1. Source and authorization chain

- **Toy #5 v0** (MOF-alone, sealed `207f4a9`) proved **latch-capture**: the `B3/S012345678` sector arrests the canonical Conway glider **128/128** (control 0/128) — **but** transforms it into small contained period-1/2 Life objects. That is a valid v0 result: **capture-with-transformation / absolute friction** — capture at the cost of the glider's identity.
- **Toy #5 v1** asks the stricter, more interesting question: can a passive/local trap **hold** a glider and then, on **release**, let the **original glider identity re-emerge**? This is still **MOF-alone** — no Janus, no coupling.
- **Sequence intact:** Janus alone (done) → **MOF alone** (v0 done; this is the v1 deepening) → coupling only after the MOF primitive is adequately characterized, including (ideally) whether identity-preserving capture is even possible. **This inception is MOF-alone; no Janus coupling here.**
- **Source concept**: AURA "Physics of the Utility Fog" intake — passive geometric traps / "MOF" (`docs/MEDUSA_THEORY_INTAKE_LEDGER.md` entry 14). v1 explores the *reversible*-trap mechanics in isolation; it does **not** implement the deferred engine-level spatial-heterogeneity arc.

## 2. Language quarantine

- **APPROVED**: *passive trap, localized rule-mask, spatial heterogeneity, hold, release, re-emergence, identity preservation, capture, retention, shatter, debris, still life, oscillator.*
- **VETOED** (except in an explicit "this is NOT" disclaimer): *Metal-Organic Framework as physical claim, chemistry / molecular binding / adsorption, porosity-as-physical-truth, guided missile, hunt / prey, Janus coupling, phoresis, propulsion.* "MOF" stays a label and must be reminded as such wherever it appears.

## 3. Precise falsifiable hypothesis

> Under fixed pre-registered initial conditions, a **static localized passive rule-mask** can **hold** a canonical Conway glider during a capture phase and, **after the mask is released/disabled at a pre-registered moment**, allow the **original glider identity to re-emerge** and **resume canonical T=4 translation with a known/derivable phase and orientation** — i.e. capture **without** identity destruction.

The toy **must be permitted to falsify this.** **Likely useful negative (stated up front, echoing v0):** for a passive *local* rule-mask, **holding may be mathematically inseparable from identity destruction** — the v0 latch already showed capture costs the glider's structure, and a "freeze"-style hold tends to **tear** a glider that straddles the sector boundary (its outside part keeps moving while its inside part is held), so on release the pieces mismatch into debris. A result of "no clean release / identity not preserved" would be a genuine, valuable finding about this rule class.

## 4. Sole variable + two-phase protocol

**Sole variable = the release-style trap protocol** (a reversible, time-limited mask + release) **vs. an appropriate reference arm** (§7). Everything else (glider, start, trajectory, lattice, topology, budget) is shared and identical. **No Janus, no gradient sensing, no steering, no moving trap** — the mask is static, local, and passive; the *only* dynamic event is the pre-registered release.

**Two-phase protocol (treatment arm):**
1. **Capture / hold phase** — from t=0 until a pre-registered **release tick** `t_rel`, the localized mask is active inside the static sector (a *reversible* hold rule — candidates in §7; v0's permanent latch is one extreme but is identity-destroying by construction).
2. **Release phase** — at `t_rel` the mask is **disabled** (the sector reverts to homogeneous B3/S23 for the remainder), and the system evolves under pure baseline rules. Re-emergence is then classified over the post-release window.

## 5. Metrics (deterministic exact-count framing)

v0-style discipline: v1 is **deterministic and noise-free**, so outcomes are reported as **exact category counts over the pre-registered condition set** — **no p-values / confidence intervals / significance tests** (noise/inferential testing is a separately-authorized later variant). Per condition, the **post-release** outcome is classified into exactly one of:
- **release-success** — a canonical 5-cell glider of the **original orientation/chirality** re-emerges and translates `(dr,dc)` per 4 ticks for ≥ N periods (phase/orientation recorded);
- **identity-loss / debris** — something persists post-release but it is not a canonical glider (shattered/garbage);
- **wrong-phase / wrong-orientation** — a glider re-emerges but with a phase/orientation inconsistent with the pre-registered expectation;
- **pass-through** — the glider was never actually held (escaped before/around `t_rel`);
- **clean-annihilation** — nothing survives post-release;
- **choke** — the hold rule filled the sector with junk (carried from v0, if the hold candidate can grow).
Plus, for release-success, a **hold-duration** record (`t_rel`) and the re-emergent glider's recorded phase/orientation vs the reference.

## 6. Useful negative results (must be reportable)

- **Identity inseparable from destruction** — no `t_rel` yields a clean canonical re-emergence (debris/annihilation dominate). Would suggest passive *local* trapping cannot hold-and-release a glider intact for this rule class.
- **Tearing** — the hold rule severs the glider at the sector boundary, so release yields mismatched fragments.
- **Phase/orientation scrambling** — a glider re-emerges but never with a derivable phase/orientation (release is not a clean resume).
- **Trivial pass-through** — the "hold" never actually holds.
Any outcome is recorded plainly; **release-success is NEVER asserted.**

## 7. Unresolved design locks (to be pinned/ratified in a later lock + Addendum, NOT chosen here)

Marked clearly as the open, load-bearing choices (none silently chosen):
- **(U1) Exact release mask / hold rule** — the *load-bearing scientific choice*. Candidates to evaluate: a **"freeze" hold** (inside-sector cells do not update during the hold — preserve the snapshot — then release); a **bounded-lifetime latch**; or another passive local rule. Each must be *reversible* and passive; the freeze candidate's **boundary-tearing** failure mode (§3) must be confronted.
- **(U2) Release tick / hold duration(s)** — `t_rel` (single value, a small pre-registered set, or phase-locked to the glider's entry). The hold duration is itself a variable of interest.
- **(U3) Identity / re-emergence predicate** — exact post-release detector: a 5-cell glider of the original orientation translating `(dr,dc)`/4 for ≥ N periods, with the **known/derivable** phase/orientation defined relative to the free-glider reference (the reference's phase at `t_rel` gives the expected resume phase).
- **(U4) Reference / control arm** — options: homogeneous **free glider** (gold-standard canonical translation, for the re-emergence comparison); the **v0 permanent latch** (held-and-destroyed baseline); or **hold-without-release**. The sole-variable framing must keep the *only* difference the release protocol.
- **(U5) Deterministic condition set** — orientations × phases × offsets × **release ticks** (the new dimension), enumerated and frozen before any run (pre-registration for power, **not** a sweep — same bright line as v0).

## 8. Instrument-only hard self-checks (for the future script)

Enforce **only instrument correctness** (a failure means the toy is broken, not that the hypothesis failed): determinism / byte-identical reruns (no RNG); identical shared inputs across arms (same glider/start/trajectory/budget; only the release protocol differs); the mask writes **only** inside the sector during the hold phase, and after `t_rel` the grid is purely homogeneous B3/S23 (assert no post-release mask writes); legal CA updates; correct re-emergence detection verified against constructed cases (a free glider released onto empty space resumes exactly `(dr,dc)`/4; a known torn fragment does **not** classify as release-success); trial-count conservation; ASCII-only output. **Do NOT hard-assert release-success.**

## 9. Promotion boundary + explicit non-authorization

The README §4 **six-step promotion gate** applies in full: (1) source verification, (2) explicit design doc, (3) tests/falsification criteria, (4) Jack/AURA/Kev review, (5) explicit separate PR, (6) no Lane A activation unless separately gated. **Even a positive result cannot alter the engine, the observer vocabulary, Vanguard, Lane A or Swarm Hunter** without a later, explicit, separately-gated phase. **This inception authorizes no script.** A future implementation requires **separate AURA / Jack / Kev authorization** after this inception is reviewed/sealed and the §7 locks are ratified — and, since the target is an external canonical glider, any result is doubly inspiration-grade: it speaks to reversible-trap mechanics in Conway Life, **nothing** about Medusa.

---

*Glass box rules apply. A static mask may try to hold a textbook glider and let it go again; the cathedral does not move, and the glider was never Medusa's to begin with. "MOF" is a costume, not a claim.*
