# Toy #5 — Synthesis / Capstone (passive-trap arc)

> **Status**: synthesis/capstone of the Toy #5 line. **Non-canonical.** Records what the sealed v0 and v1 toys established, what they did **not**, and the gated forward queue. **Authorizes no script, no simulation, no engine work, no new toy.** A durable home for the trap arc's *meaning*, so it isn't scattered across PR descriptions.

> **LOAD-BEARING DISCLAIMER:** every Toy #5 toy used the **externally-canonical Conway Game-of-Life glider (B3/S23)**, **NOT** a native Medusa structure (a read-only repo search found no documented Medusa glider; AURA's Option-B ruling chose the external target). These are **isolated sandbox proofs-of-concept for trap mechanics only** — *nothing here is evidence about Medusa's own dynamics.* "MOF" is a **label/analogy only** — not chemistry, not a real Metal-Organic Framework.

## 0. Current model seat
Authored by **84** (`claude-opus-4-8`), desktop seat, 2026-06-22, under AURA's authorization for a docs-only Toy #5 synthesis/capstone (AURA ratified the read-only synthesis memo → authorized this PR → Jack relayed). *(Future seats: state your seat here per the model-seat hygiene protocol in `AGENT_HANDOFF.md`.)*

## 1. Toy #5 v0 (latch) — capture-with-transformation / absolute friction
- **Rule:** a static localized **latch** mask `B3/S012345678` inside the sector (`B3/S23` outside) — births allowed inside, deaths forbidden inside.
- **Result (sealed, `207f4a9` / PR #254):** **128/128 capture** of the canonical glider — translation arrested in every condition.
- **But identity is NOT preserved:** the glider is **transformed** into a small (11–18 cell), contained, **period-1/2** Life object (still life / oscillator). It no longer translates and is no longer a glider. This is **absolute friction** — capture purchased by destroying the structure. (Confirmed downstream: in the v1 run the v0-latch reference, when "released," gave **128/128 identity-loss** — there is no glider left to free.)

## 2. Toy #5 v1 (strict-passive freeze) — inert wall / shear
- **Rule (AURA Option A, strict passive):** an **always-on, spatially-constant, passive inside-sector FREEZE** (identity rule: inside cells never update) for `[0, t_rel)`, then **release** to homogeneous `B3/S23`. No schedule, no sensing, no steering, no shutter, no Janus, no moving trap.
- **Result (sealed, `b0f7022` / PR #256):** **0/384 release-success.** Because no births are permitted inside, the glider cannot even propagate **into** the sector — the freeze is an **inert wall**, and the glider **shears** at the boundary (372 identity-loss, 12 clean-annihilation). Control (free glider) = **128/128 pass-through** (a positive control proving the classifier *can* report success); v0-latch reference = **128/128 identity-loss**.
- **Conclusion:** **release-style identity preservation fails under an always-on passive local freeze for this rule class** — holding is inseparable from identity destruction **without temporal gating.**

## 3. The unifying finding — the two failure poles
The two *always-on* passive forms sit at opposite poles, and **neither preserves identity**:
- **v0 latch over-binds** — admits the glider, then transforms it.
- **v1 freeze under-admits** — blocks the glider, then shatters it.

For always-on passive local rule-masks, **capture and identity-preservation are in direct tension.** Clean *hold-and-release* appears to require either **temporal gating** (a timed freeze of a fully-contained glider — which leaves the strict-passive class) or a genuinely different **compliant** mechanism (§5).

## 4. What these results do NOT prove
- **Not Medusa-native evidence** — external Conway glider; says nothing about Medusa's structures or dynamics.
- **Not a claim about all traps** — only two specific rule-masks (latch, freeze), one 16×16 sector, one grid, one glider, deterministic and noise-free.
- **Not a claim about real MOFs** — "MOF" is a label; no chemistry / porosity / binding claim.
- **Not a ruling on compliant/yielding traps, temporal shutters, or Janus+MOF coupling** — those are untested. The negatives **constrain** the always-on passive class; they do **not** rule out (or authorize) a distinct primitive.
- Also untested: **collateral-freezing under noise** (deferred v1-noise variant), other sector geometries/sizes, other CA targets.

## 5. Forward queue (clearly separated; each gated; none authorized)
Recorded so the distinctions stay crisp — see [`docs/MEDUSA_THEORY_INTAKE_LEDGER.md`](../../docs/MEDUSA_THEORY_INTAKE_LEDGER.md) **entry 15** and the theory-sandbox README §6c.

- **Discrete Compliant / Quasi-Mechanism Trap ("yield-then-lock")** — *the genuine unexplored third mechanism.* A localized discrete rule that **yields under entry, preserves an identity signature** (candidate invariants: live-cell count, bounding box, phase/orientation, period signature, re-emergence), **then locks** — *without* an explicit temporal shutter. Inspired by the corrected flexible-polyhedra intake (entry 15): a flexible polyhedron deforms while preserving structure (Bellows ⇒ volume invariant) then holds. **Caution (Jessen's "shaky"):** distinguish *true* yield-then-lock from a first-order "shaky" near-miss that yields then jams. **Distinct from** v0 latch, v1 freeze, the temporal shutter, and Janus+MOF coupling. Would need its own inception → lock → script.
- **Active shutter / temporal-gating trap** — a *timed* transparent→hold→release primitive. **A distinct ACTIVE primitive**, not strict-passive (it introduces a global timing/control signal). It would likely succeed *near-tautologically* (timed pause/resume of a fully-contained glider), with the only real payoff a timing-window map. Lower priority; muddies the "passive" story.
- **Janus + MOF coupling** — couple a Toy #4-style mover with a MOF trap. **Premature until identity-preserving trapping exists:** both characterized MOF forms *destroy* the payload, so coupling a mover to a payload-shredder would be uninterpretable (can't separate "did motion work?" from "did the trap keep anything?"). Wait until a compliant trap (above) demonstrably preserves identity.

## 6. Guardrails / non-authorization
- **External Conway glider disclaimer** (above) applies throughout. **"MOF" is a label.**
- **This capstone authorizes:** no Toy #6, no script, no simulation, no shutter experiment, no Janus+MOF coupling, and no engine / `uft_ca` / GPU / R3 / observer / Vanguard / Lane A / Swarm Hunter work.
- The README §4 **six-step promotion gate** applies to anything in the forward queue: source verification · explicit design doc · tests/falsification criteria · Jack/AURA/Kev review · explicit separate PR · no Lane A activation unless separately gated. Even a positive future result is inspiration-grade until separately, explicitly gated.

## 7. Sealed-artifact references
- Toy #5 v0 inception + stats erratum: PRs #252 (`bf51f87`), #253 (`4e0cc61`); **v0 script** PR #254 (`207f4a9`).
- Toy #5 v1 inception: PR #255 (`0cd5d1e`); U1–U5 lock + Addendum 1 (chat-ratified, Option A Strict Passive); **v1 script** PR #256 (`b0f7022`).
- Flexible-polyhedra / compliant-trap intake: PR #257 (`255d294`) → [`docs/FLEXIBLE_POLYHEDRA_COMPLIANT_TRAP_INTAKE.md`](../../docs/FLEXIBLE_POLYHEDRA_COMPLIANT_TRAP_INTAKE.md) + ledger entry 15.

---

*Glass box rules apply. The latch over-binds, the wall shatters, and the compliant door is still only a sketch on the wall. The cathedral has not moved; the glider was never Medusa's to begin with.*
