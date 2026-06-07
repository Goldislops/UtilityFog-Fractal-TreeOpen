# Medusa Theory Intake Ledger

> **What this is**: a place to *park and classify* cross-thread theory, physics, and tech inputs (mostly relayed by AURA, often originating from YouTube/papers) **before** they get lost between sessions — and **before** anyone mistakes a nice metaphor for validated engine architecture.
>
> **What this is NOT**: a physics lawbook, an engine spec, or a to-do list. Nothing here is "marching orders." Inclusion ≠ endorsement ≠ implementation.
>
> **Standing guardrails for everything below**: docs only · no engine touch · no observer-semantics changes · **Lane A PARKED** · no Swarm Hunter implementation · no tuning API · no production sweeps. An item leaves this ledger only by being promoted into a real design doc / PR through the normal review (Jack audit + AURA strategy + 84/Hermes implementation), never by sitting here long enough to look official.

**Created**: 2026-06-06 (84, desktop). **Origin**: Jack's "intake ledger, not physics lawbook" call on AURA's emergence / spatial-physics relay.

---

## Status taxonomy

Every entry carries exactly one **Status**:

| Label | Meaning | Can it touch code? |
|---|---|---|
| **canonical guardrail** | A rule the team has *ratified*; binds future design. | Constrains code; is not itself code. |
| **candidate guardrail / design principle** | Proposed rule or principle; **pending team ratification**. | No, until ratified. |
| **speculative inspiration** | Evocative; might seed future vocabulary/scaffolding. | No. |
| **strategic background** | Context for the long arc (hardware, industry, embodiment). | No. |
| **not yet actionable** | Real but blocked on a precondition (e.g. trusted observer signals). | No, until precondition met. |

Per-entry fields (Jack's required structure): **Source/thread · Claim · Status · Repo relevance · Current action · Guardrails/caveats.**

---

## Entries

### 1. Emergence / local-rule intelligence
- **Source/thread**: AURA summary of "The Strange Power of Emergence" (YouTube relay).
- **Claim**: Global order/intelligence can arise from many agents following *local* rules, with no central choreographer (flocking, ant colonies, cellular automata).
- **Status**: **candidate design principle** (+ feeds the Lane A guardrail in entry 2).
- **Repo relevance**: Directly aligned with Medusa's CA substrate and any future swarm/agent layer. Supports the existing bottom-up framing; does **not** prove the current engine is correct — it endorses the *philosophy*, not the implementation.
- **Current action**: Record only. No code.
- **Guardrails/caveats**: Emergence supporting the design philosophy is **not** evidence the engine is validated. Keep "design principle" and "proof of correctness" strictly separate. (cf. Flocking / Boids as the classic local→global example.)

### 2. Swarm Hunter semantics
- **Source/thread**: Derived from entry 1 + Jack's perimeter review.
- **Claim**: If/when a "Swarm Hunter" ever acts (Lane A), it must **observe and tune local interaction thresholds only** — it must **not** become a global controller that imposes states or moves cells as a master boss.
- **Status**: **candidate guardrail** — strong intent, **pending explicit team ratification** before it's "canonical."
- **Repo relevance**: Pre-commits a safety boundary *before* Lane A reopens, so the emergence philosophy isn't quietly violated by a central-controller shortcut.
- **Current action**: Record as the leading candidate guardrail for Lane A reopening. **No implementation.**
- **Guardrails/caveats**: Any future Lane A intervention must be (a) local-rule / threshold based and (b) gated on **trusted, calibrated observer signals** (see entry 4). Lane A stays PARKED until then.

### 3. Thurston eight geometries / spatial folding
- **Source/thread**: AURA spatial-physics relay; Jack's tungsten-diverter correction.
- **Claim (corrected)**: Thurston's geometrization (proved via Perelman) says every **closed 3-manifold** decomposes canonically into pieces, **each modeled on one of eight geometries**. It is **not** a claim that "all 3D spatial chaos reduces to eight outfits" in any direct engineering sense.
- **Status**: **speculative inspiration**.
- **Repo relevance**: Possible long-horizon muse for a *spatial-scaffold vocabulary* (how local patches might be typed/folded). Inspiration only.
- **Current action**: Record with careful wording. No implementation, no vocabulary change.
- **Guardrails/caveats**: Do **not** state or imply the eight geometries are an implementation requirement or a universal physical law. It's a topology theorem about certain manifolds, borrowed as metaphor.

### 4. Continual Harness / self-improving agents
- **Source/thread**: Prior AURA theory drops; relatedly the DeepMind AlphaProof "new way to think" video (YouTube, relayed 2026-06-06) on self-improving reasoning / extended inference.
- **Claim**: Self-improving agent loops (propose → evaluate → improve) are powerful but only safe atop trustworthy evaluation signals and calibrated boundaries.
- **Status**: **not yet actionable** (also strategic background for future Lane A).
- **Repo relevance**: Future Lane A shape. Precondition is exactly the observer-signal trustworthiness that Phase 19 has been calibrating.
- **Current action**: **No implementation. Lane A parked.** Keep as a watch-item.
- **Guardrails/caveats**: **Death-spiral risk** — a self-improving loop on ambiguous/miscalibrated observer signals optimizes the wrong target and compounds error. Trusted observers first; self-improvement second. (AlphaProof note is a *relayed summary*, not independently verified here.)

### 5. NVIDIA / Cosmos / robotics / edge agents
- **Source/thread**: Multiple AURA relays (Computex / robotics / world-model news).
- **Claim**: Industry momentum toward world models, robot foundation models, and edge/agentic compute.
- **Status**: **strategic background**.
- **Repo relevance**: Possible far-future physical-embodiment / edge-agent context for Medusa. No bearing on current direction.
- **Current action**: **No repo direction change.** Context only.
- **Guardrails/caveats**: Do not let exciting hardware news pull scope. "First floorboards, then android ballet."

### 6. Planck Star / warmth-cluster metaphor
- **Source/thread**: Earlier AURA metaphor; Workstream B empirical work.
- **Claim**: Warmth would form stable, clusterable structures (the evocative "Planck star" / cathedral-candle imagery).
- **Status**: **largely resolved** — empirically downgraded.
- **Repo relevance**: Already folded into Workstream B/C: empirical profiling found **isolated warmth sparks, not stable clusters** ("a hermit candle in a stone cathedral").
- **Current action**: None — already actioned. `metta_warmth` is **`diagnostic_only`** (PR #164); surfaced as `warmth_max` / `warm_cell_count` diagnostics.
- **Guardrails/caveats**: Kept here only as the cautionary example of a beautiful metaphor that the data did **not** support — exactly why this ledger labels confidence.

---

## How an entry graduates out of this ledger

1. Someone proposes promotion (e.g. "make entry 2 a canonical guardrail").
2. **Jack** audits the claim for overreach / hidden assumptions; **AURA** checks fit with the long arc; **84/Hermes** assess implementation cost.
3. On agreement, it moves into a real design doc (e.g. a `PHASE_*` doc, a guardrail in `AGENT_HANDOFF.md`, or `params_schema.py` metadata) via a normal PR.
4. Its row here is updated to point at where it landed.

Until then: **labelled theory, not marching orders.**
