# Toy #6 — Addendum 2: Analytical Closeout of the "Lock" Framing (design only, no script)

> **Status**: docs-only analytical closeout of the **"lock" framing** of Toy #6 (`TOY_06_COMPLIANT_TRAP_INCEPTION.md`). **Authorizes no script, no simulation, no implementation.** This is a **reasoned conclusion**, not a formal theorem, and it is **bounded to this target and this rule framing** — it is *not* a universal impossibility claim over all cellular automata.
>
> **NON-CANONICAL.** External canonical Conway glider only — **not native Medusa evidence, not real MOFs, not physical elasticity.**

## 0. Current model seat
Authored by **84** (`claude-opus-4-8`), desktop seat, 2026-06-22, under AURA's **Option A** ruling (analytical closeout, not script), following the chat-only U1–U7 lock memo. *(Future seats: state your seat per the model-seat hygiene protocol in `AGENT_HANDOFF.md`.)*

## 1. Core analytical finding
For the externally-canonical **Conway glider (B3/S23)** target, a **passive-local "yield-then-lock" rule with no temporal shutter is not currently ratifiable.** "Lock while preserving identity" collapses, under reasoning, into one of:
- **pass-through** (never locks),
- **latch-collapse** (locks → transforms the glider into a blob; cf. Toy #5 v0),
- **freeze / shear** (never admits → shatters at the boundary; cf. Toy #5 v1),
- **shaky near-mechanism** (yields infinitesimally, then jams; cf. Jessen),
- **active-shutter leakage** (only "works" if the lock is calibrated to *when* the glider arrives — a clock in disguise, which the U4 guard forbids).

**Root cause (the load-bearing insight): a glider's identity *is* its motion.** It has **no held-rest state** to lock-and-preserve. So **stopping it (lock)** and **keeping it a glider (preserve identity)** are **near-contradictory** for this target unless one cheats with a clock. This is the same **capture↔identity tension** Toy #5 surfaced — now reached from the *compliance* angle, independently confirming the trap arc's central result from two directions (freeze and compliance).

## 2. Why U1 (the rule family) does not close
Every candidate local rule reduces to a collapse mode:
- **Age-gated lock** (B3/S23 until a cell's local age ≥ k, then lock): a glider cell is alive only ~1–3 *consecutive* ticks (the glider never dwells). **k large → no cell reaches k → pass-through; k small → transient cells lock → latch-collapse.** No k captures with identity intact.
- **Density / occupancy lock** (a region firms when local live-density ≥ θ): a lone glider's density is low except its momentary 3×3 footprint. **θ high → pass-through; θ low → locks the footprint → latch-collapse.**
- **Hysteresis (dual-threshold admit/hold):** reduces to the age- or density-trigger → inherits their collapses.
- **Confine / reflect ("soft box"):** does **not** "lock" — it would preserve identity by *bounding the motion*, not stopping it. That is a **separate confinement hypothesis** (§4), not a resolution of the lock framing.

There is no honestly-pinnable U1 that yields, then locks, then preserves a glider's identity, without a clock.

## 3. Status: lock-as-framed is analytically closed / not script-ready
**Toy #6, in its "lock" framing for a Conway-glider target, is marked analytically closed and NOT script-ready.** Building a script would predictably re-derive the Toy #5 v1 negative; the cost is not warranted for a foreseeable null.

**Scope discipline (important):** this is a **reasoned, bounded conclusion** — confined to (a) the **Conway glider** target and (b) the **passive-local, no-clock, lock** rule framing. It is **explicitly NOT**:
- a formal mathematical impossibility theorem;
- a claim over **all** cellular automata, **all** targets, or **all** rules;
- a statement about Medusa.
A different target (one with a genuine metastable rest state), or a different framing (confinement, encode-and-release, or an active shutter), is **not** covered by this closeout and remains open (§4).

## 4. Parked future alternatives (each separate, future, gated, UNAUTHORIZED)
- **Confine-not-lock trap** — preserve identity by **bounding** a glider's motion (reflect/contain it in a "soft box") rather than stopping it. Identity is preserved *because* the motion is preserved. Fresh; requires its own inception; open question: whether a *passive rule-mask* can act as a clean reflector at all (Life reflectors are delicate *placed objects*).
- **Encode-and-release / state-transduction trap** *(from Kev's "stopped-light / glider-potential" intuition)* — the trap **transduces** the incoming glider into a stored/encoded representation (a *different* state form), then **re-emits** the original glider on a release trigger — analogous to "stopped light" (storing then re-emitting a photon's state in a medium). Distinct from "lock" (which tries to hold the glider *as* a glider): this stores it *as something else* and reconstructs it. Open questions: whether a passive-local rule can encode **and** faithfully decode without a clock, and whether it too collapses into shutter/latch. Parked as a separate hypothesis.
- **Active shutter / temporal-gating trap** — a distinct **active** (timed) primitive; out of scope here.
- **Janus + MOF coupling** — out of scope (premature until an identity-preserving trap exists).

## 5. Bellows / invariant note (carefully)
The flexible-polyhedra analogy (Ledger Entry 15) supplied the *"yield while preserving an invariant"* intuition. Stated precisely: for a **true flexible polyhedron**, the **Bellows theorem preserves the enclosed volume** as it flexes, and the flex itself **preserves metric structure** (the edge lengths are fixed). **The Medusa mapping borrows only the *idea* of a preserved invariant — and uses discrete identity invariants only** (live-cell count, bounding box, phase/orientation, period signature, post-release re-emergence, or an **encoded identity state** for the encode-and-release hypothesis): there is **no literal volume, no metric, no elasticity, no Hooke's law, no material.** And the analogy **breaks precisely at "lock":** a flexible polyhedron has a **static rest state** — it can sit at rest while preserving its metric structure — whereas **a glider has no rest state at all** (its identity *is* its motion), which is exactly why the lock framing collapses. The polyhedra gave vocabulary and a failure-mode structure, never physics.

## 6. Promotion boundary + explicit non-authorization
README §4 **six-step promotion gate** applies. **This addendum authorizes nothing further** — no script, no simulation, no Toy #6 implementation, no active-shutter experiment, **no encode-and-release implementation**, no Janus+MOF coupling, and no engine / `uft_ca` / GPU / R3 / observer / Vanguard / Lane A work. Any parked alternative (§4) requires its **own** separate inception → lock → review → gated PR.

---

*Glass box rules apply. The latch over-binds, the wall shatters, and the compliant lock turns out to ask a moving thing to be still without ceasing to move. We close the lock, honestly, and leave two new doors sketched but unopened: bound the motion, or store and re-emit it. The glider was never Medusa's to begin with.*
