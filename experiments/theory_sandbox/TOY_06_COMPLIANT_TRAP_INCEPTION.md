# Toy #6 Inception — Discrete Compliant / Quasi-Mechanism Trap ("yield-then-lock") (design only, no script)

> **Status**: inception/design note only. **No script exists yet, and this note authorizes none.** The toy itself lands only in a later, separate PR after Jack/AURA/Kev review this note and ratify the unresolved locks (§7). Per `experiments/theory_sandbox/README.md`: one toy per PR; this is the *zeroth* brick of Toy #6 — the thinking before the toy.
>
> **NON-CANONICAL TOY (design):** a discrete rule yielding-then-locking around a glider on a toy lattice proves nothing about Medusa. This is an **algorithmic compliant-trap toy** — *not physical elasticity, not Hooke's law, not strain, not a real Metal-Organic Framework, not material mechanics, not a hunt.* "Compliant / quasi-mechanism / yield" are **discrete-rule analogies only**, never continuous material behaviour.

> **LOAD-BEARING DISCLAIMER (the hinge that keeps the doctrine honest):** the target is the **externally-canonical Conway Game-of-Life glider (B3/S23)**, **NOT** a native Medusa structure. This is an **isolated sandbox proof-of-concept for trap mechanics only** — *it says nothing about Medusa-native gliders, Medusa's dynamics, or real MOFs.*

## 0. Current model seat
Authored by **84** (`claude-opus-4-8`), desktop seat, 2026-06-22, under AURA's explicit authorization lifting the "no Toy #6" guardrail **for this one bounded docs-only inception** (AURA ratified 84's next-arc decision memo → explicitly blessed Toy #6 → Jack relayed). *(Future seats: state your seat per the model-seat hygiene protocol in `AGENT_HANDOFF.md`.)*

## 1. Precise falsifiable hypothesis
> A **localized discrete rule** can **yield** under entry (locally deform/absorb to *admit* the incoming structure rather than block or over-bind it), **absorb/transduce its translational momentum**, and then **lock** — **while preserving the target's identity signature** (§5) — **without using a scheduled temporal shutter** (the lock is triggered by *local state*, not by a global clock).

The toy **must be permitted to falsify this** (§7-useful-negative): the honest outcome may be that **no passive-local compliant rule exists** that doesn't collapse into one of the already-characterized poles. Identity-preservation here means the captured-then-released (or captured-and-held-recognizable) structure still carries its declared identity signature — *not* the v0 outcome (transformed into a generic blob) or the v1 outcome (sheared into debris).

## 2. Mechanism framing — the third mechanism
"**Yield-then-lock**" is the third trap mechanism, distinct from the two already sealed and from two neighbours that must NOT be conflated:
- **Toy #5 v0 latch** = **over-bind / transform** (admits, then freezes into a period-1/2 blob; identity destroyed). Toy #6 must *not* lock so eagerly that it reduces to this.
- **Toy #5 v1 strict-passive freeze** = **under-admit / shear** (inert wall; glider can't enter; shatters). Toy #6 must *yield* enough to admit, so it does not reduce to this.
- **Active shutter / temporal gating** — a *timed* transparent→hold→release primitive (a global clock/control signal). Toy #6's lock must be **state-triggered and local**, never a disguised clock; if the lock can only be made to work via a schedule, that is the **shutter**, not a compliant trap, and the toy should report that collapse.
- **Janus + MOF coupling** — a mover + a trap. Out of scope: Toy #6 is a **trap-alone** primitive (no Janus, no gradient sensing, no steering, no moving trap).

The "compliant" intuition: a rule region that is *permissive enough to let the structure in* and then *firms up to hold it* — the discrete analogue of a structure that **flexes while preserving itself, then holds a shape** (§3).

## 3. Source hygiene (analogy only — see Ledger Entry 15)
Explicitly references `docs/MEDUSA_THEORY_INTAKE_LEDGER.md` **entry 15** (`docs/FLEXIBLE_POLYHEDRA_COMPLIANT_TRAP_INTAKE.md`). The **true-flexible vs shaky** distinction is load-bearing for the analogy and for the failure modes:
- **Connelly (1977, first embedded non-self-intersecting flexible polyhedron; 18 vertices / 32 triangular faces) and Steffen (9 vertices / 21 edges / 14 triangular faces)** are **truly flexible** — they deform continuously while preserving structure (edge lengths fixed); the **Bellows theorem** (Sabitov 1995; Connelly–Sabitov–Walz 1997) says their enclosed **volume is invariant while flexing**. *This* is the analogy for "yield while preserving an identity invariant, then hold."
- **Jessen's orthogonal icosahedron** is **"shaky"** — *rigid but not infinitesimally rigid*: it has a first-order (infinitesimal) motion but does **not** truly flex. This is the **cautionary failure mode**: a discrete "compliant" rule may only yield *infinitesimally then jam* (a "shaky near-mechanism"), which is a distinct, reportable negative.

**This is an analogy only — no physical elasticity, no continuous flex, no Hooke's law, no strain, no material model.** The polyhedra supply *vocabulary and failure-mode structure*, not physics.

## 4. Target / control disclaimer
- **Target:** the externally-canonical **Conway glider (B3/S23)** — chosen because it is the *opposite* of invented (textbook, maximally verified), **NOT** native Medusa evidence.
- **Says nothing about** Medusa-native gliders (none documented), Medusa dynamics, or real MOFs.
- **References (for contrast, deterministic exact-count framing like Toy #5):** homogeneous free glider (positive control); the **v0 latch** and **v1 freeze** as the two known poles to contrast against.

## 5. Candidate identity-signature invariants (candidate locks, NOT final)
"Identity preserved" must be made precise via a declared subset of:
- **live-cell count** (a glider is 5; a transformed blob is 11–18; a shear is debris);
- **bounding box** (shape/extent);
- **phase / orientation** (which of the 4 phases / which diagonal chirality);
- **period signature** (a glider has period 4 with `(dr,dc)` translation; a still life is period 1; an oscillator is low-period stationary);
- **post-release re-emergence** (does a canonical glider of the original orientation resume translating ≥ N periods after the lock is removed/relaxed?);
- **local identity signature** (a normalized pattern-template match, e.g. the glider phase-templates).
**These are candidate invariants to be pinned in a future lock — not final.**

## 6. Mechanism intuition (design sketch, to be pinned in the lock — not chosen here)
A compliant rule plausibly needs **local state beyond binary** (e.g. a per-cell *age* or a small local counter) so that "yield" (permissive admission) and "lock" (firm-up) can be *state-triggered locally* rather than by a clock. Example *families* to evaluate (none selected): an **age-gated lock** (cells permissive until locally persistent for `k` ticks, then frozen); a **density/threshold lock** (a sector firms up once local occupancy crosses a threshold); a **hysteresis rule** (different admit vs hold thresholds). Each must be checked against the four collapse modes (§2). *This section is intuition only; the exact rule is U1.*

## 7. Unresolved locks (to be ratified in a later lock + Addendum; NOT chosen here)
- **(U1) exact rule family / mask** — the *load-bearing scientific choice*: the local compliant rule (incl. any local state such as cell age). Must be passive (no global clock, no sensing-of-glider-as-object, no steering, no motion).
- **(U2) grid + sector geometry** — lattice size, sector bounds, region/margin (candidate: reuse Toy #5's `L=96`, `SECTOR=[44,59]²`, `REGION=[41,62]²`).
- **(U3) yield criterion** — the operational definition of "yielded / admitted" (e.g. the glider's cells entered the sector intact, without shear, by some tick).
- **(U4) lock criterion** — the *local, state-triggered* condition that fires the lock. **Must provably not be a clock** (else it's the shutter).
- **(U5) identity-preservation predicate** — which §5 invariants, with what tolerances, define "identity preserved" (held-recognizable and/or re-emergent-on-release).
- **(U6) admissible failure classes** — at minimum: **latch-collapse** (over-binds → transform), **freeze-collapse** (under-admits → shear), **shaky** (yields infinitesimally then jams), **shutter-collapse** (only works via a disguised clock), plus shatter / clean-annihilation / no-capture / pass-through.
- **(U7) deterministic condition set + references** — orientations × phases × offsets (× any rule parameters), pre-registered, exact-count, no RNG; references = free glider + v0 latch + v1 freeze.

## 8. Useful negative result (must be reportable)
The inception **must allow the honest outcome that no passive-local compliant ("yield-then-lock") rule exists** — i.e. that every candidate collapses into **latch** (transform), **freeze** (shear), a **shaky near-mechanism** (infinitesimal yield then jam), or an **active shutter** (only works with a clock). Such a collapse would be a genuine, valuable finding: it would suggest that **identity-preserving capture is fundamentally incompatible with passive-local rules** and *requires* either temporal gating or active machinery. Capture / identity-preservation is **never asserted**; outcomes are reported.

## 9. Instrument-only hard self-checks (for the future script)
Enforce **only instrument correctness**: determinism / byte-identical reruns (no RNG); identical shared inputs across arms (same glider/start/trajectory/budget; only the rule differs); the rule writes only inside the sector; legal CA updates; a **positive control** (the free glider classifies as a clean translating glider — proving non-failure is reachable); canonical-glider matcher validated against a real glider and rejecting torn fragments; trial-count conservation; ASCII output. **Never hard-assert that the trap preserves identity.**

## 10. Promotion boundary + explicit non-authorization
README §4 **six-step promotion gate** applies in full. **Even a positive result cannot alter the engine, observer vocabulary, Vanguard, Lane A or Swarm Hunter** without a later, explicit, separately-gated phase. **This inception authorizes no script, no simulation, no Toy #6 implementation, no active shutter, no Janus+MOF coupling, and no engine / `uft_ca` / GPU / R3 / observer / Vanguard / Lane A work.** A future implementation requires **separate AURA / Jack / Kev authorization** after this inception is reviewed/sealed and the §7 locks are ratified.

---

*Glass box rules apply. The latch over-binds, the wall shatters; the compliant door is supposed to bend and hold — but it may only ever be shaky, or secretly a clock. We design the question; we do not yet build the answer. The glider was never Medusa's to begin with.*
