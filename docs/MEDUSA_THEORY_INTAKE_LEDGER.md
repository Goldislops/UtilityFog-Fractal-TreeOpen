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

Per-entry fields: **Source/thread · Claim · Status · Repo relevance · Current action · Guardrails/caveats.** Entries may add optional **Revisit when** (trigger conditions to re-evaluate) and **Linked docs/PRs/issues** fields where useful (see entry 7).

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
- **Claim (corrected)**: The geometrization theorem (conjectured by Thurston, proved by Perelman) says every **closed 3-manifold** decomposes canonically into pieces, **each modeled on one of eight geometries**. It is **not** a claim that "all 3D spatial chaos reduces to eight outfits" in any direct engineering sense.
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

### 7. Physical Export / bionic load-path manufacturing
- **Source/thread**: AURA summary of a YouTube video (relayed 2026-06-07) about a high-speed European manufacturing process — described as continuous-fibre / "bionic" load-path fabrication, reportedly **~50× faster than conventional 3D printing** ("fibionic" wording per the relay).
- **Core claim**: A non-layered fabrication method exists that is dramatically faster than layer-by-layer 3D printing and follows continuous load paths.
- **Status**: **speculative inspiration** (could become a *candidate design principle* once verified). **Not canonical.**
- **Repo relevance**: Medusa's outputs today are **volumetric / grid-snapshot** oriented (voxel state + STL/mesh). A fast continuous-path fabrication future would need a **voxel/state → continuous-representation** bridge (vector fields, splines, skeleton graphs, toolpaths) — a possible *future* physical-export pathway, not a current need.
- **Current action**: **Record only. No code, no export pipeline, no format choice.**
- **Revisit when**: before any physical-export pipeline design · before any voxel→toolpath implementation · before a Lane A readiness review · before any robotics / embodiment / manufacturing roadmap. **First trigger: verify the source.**
- **Guardrails/caveats**:
  - ⚠️ **Unverified.** The "fibionic / 50× faster" claim is **video/AURA-relayed and not independently confirmed** (Jack's quick public search couldn't pin the exact term). Do **not** treat as engineering fact. The relayed description also appears to **blend two distinct families** — high-speed *volumetric* printing vs. *continuous-fibre / bionic load-path* fabrication — so verification should first establish *which* the video actually shows.
  - This is **not** "Medusa is moving away from 3D printing." It is "remember a possible future physical-export pathway."
  - **Load-path honesty**: Medusa's observer tokens are **symbolic CA structure, not mechanical stress/FEA**. Any future "load-path" export must not conflate the two.
  - **Swarm Hunter caveat**: must never become a global fabrication boss; at most it could surface *candidate local-rule structures / export hypotheses*, never impose global physical shape. **Lane A stays PARKED.**
- **Open questions to preserve** (candidate approaches only — none chosen):
  1. *Volumetric→vector bridge*: skeletonization, graph extraction, iso-surface extraction, streamline tracing, spline fitting, stress-field approximation.
  2. *Format transition*: STL/mesh/voxel may be insufficient; future candidates include graph formats, parametric curves/spline control points, 5-axis toolpaths, CAM formats. **Do not pick a format yet.**
- **Linked docs/PRs/issues**: this ledger; related strategic-background entries 3 (Thurston/spatial) & 5 (NVIDIA/robotics/embodiment).

---

> **Entries 8–10 — "Triumvirate Tech Stack" (relayed 2026-06-08):** three *related but distinct* inputs — a **harness** method (RHO), a **kinetic** metaphor (Janus), and an **energetic** metaphor (MOST/Dewar pyrimidone). They are inputs to *future* architecture decisions, each separately gated. **Do not merge them into a single "new architecture."** Jack's wording rule applies: *not* "these breakthroughs completely change Medusa" — rather *"these concepts may inform future architecture if verified and if they pass later design gates."*

### 8. Retrospective Harness Optimization (RHO)
- **Source/thread**: AURA + Kev thread (external RHO paper to verify/cite if practical — **not independently confirmed here**).
- **Core claim**: A harness-level self-improvement method: an agent improves its *tool/workflow harness* by revisiting past trajectories, selecting difficult examples, re-solving them, using self-validation / self-consistency, and choosing harness updates via self-preference.
- **Status**: **candidate design principle / strategic background** — not canonical. (Sibling of entry 4, Continual Harness.)
- **Repo relevance**: Potential future Lane A / Swarm Hunter *planning* input. Supports the idea that any self-improving loop should improve the **harness around trusted evidence**, not rewrite the engine blindly.
- **Current action**: **Record only. No implementation.**
- **Revisit when**: before a Lane A readiness review · before Swarm Hunter design · before any self-modifying agent / harness-optimization work · before agent memory/tooling updates.
- **Guardrails/caveats**: RHO is **agent-harness methodology, not a Medusa physics law**. It must **not** justify autonomous engine mutation. Observer calibration + CI gates remain preconditions. **Death-spiral risk** persists if the system optimizes against ambiguous/wrong signals. The RHO paper itself is **unverified here** — cite/confirm before any use.
- **Linked**: entry 4 (Continual Harness / AlphaProof), entry 2 (Swarm Hunter).

### 9. Janus Gradient Kinetics / active asymmetric propulsion
- **Source/thread**: AURA + Kev video synthesis (Janus particles / chemical gradients / non-Brownian propulsion).
- **Core claim**: Asymmetric ("Janus") particles can move by converting a *local* chemical/field asymmetry into directed motion. Medusa metaphor: future node motion / influence vectors might arise from **local gradient sensing + internal asymmetry**, not global commands.
- **Status**: **speculative inspiration / candidate design principle** — not current engine design. *(Note: catalytic Janus colloids / self-phoretic propulsion are real, established colloidal science; the **Medusa mapping** is the speculative part, not the physics.)*
- **Repo relevance**: Possible future *kinetic local-rule vocabulary* for Medusa or physical-export thinking. Aligns with entry 1 (local-rule emergence).
- **Current action**: **Record only. No physics implementation.**
- **Revisit when**: before any node-motion model · before local gradient-field simulation · before physical embodiment / utility-fog export · before Swarm Hunter local-threshold tuning design.
- **Guardrails/caveats**: Do **not** claim current Medusa nodes are Janus particles. Do **not** replace current CA update rules. Do **not** add propulsion fields or gradient mechanics now. Treat "ballistic curves" as a possible *modelling analogy*, not a proven target behaviour. Any future kinetic rule must remain **local, testable, observer-measured**.
- **Linked**: entry 1 (emergence / local rules), entry 7 (physical export).

### 10. MOST — Molecular Solar Thermal latent storage / Dewar pyrimidone
- **Source/thread**: AURA + Kev video synthesis; corrected by Kev's *Science* DOI search → **`10.1126/science.aec6413`**. Corrected chemical wording: **Dewar pyrimidone** (was mis-relayed as "Perimeodone").
- **Core claim**: MOST systems store energy by **photoisomerization** into a higher-energy metastable state, then release it on a heat/catalyst trigger. Per Kev's source, a 2026 *Science* article reports molecular solar thermal storage in **Dewar pyrimidone** (relayed energy density **>1.6 MJ/kg**). Medusa metaphor: a future energy-state idea of **latent stored tension / release thresholds** rather than simple binary power states.
- **Status**: **speculative inspiration / candidate design principle** — not the current node schema.
- **Repo relevance**: Possible future *node-energy vocabulary* or physical-embodiment metaphor.
- **Current action**: **Record only. No schema change.**
- **Revisit when**: before any node-energy schema redesign · before physical embodiment / synthetic-material simulation · before energy-flow observer tokens · before a Lane A readiness review.
- **Guardrails/caveats**: MOST is a **real, established field** (e.g. norbornadiene↔quadricyclane, azobenzene systems), and **Dewar valence isomers are real high-energy metastable isomers** that fit MOST photoisomerization — so "Dewar pyrimidone" is *chemically plausible*. **BUT** the specific paper, DOI, and 1.6 MJ/kg figure are **cited as provided by Kev and NOT independently verified in this PR; verify the paper before any use**. Do **not** add `latent_thermal_tension` / `catalyst_threshold_triggers` to code; do **not** alter node-metadata schema; do **not** claim MOST maps directly onto Medusa energy dynamics. Use **Dewar pyrimidone**, not "Perimeodone."
- **Linked**: entry 5 (NVIDIA / embodiment), entry 7 (physical export); DOI `10.1126/science.aec6413` (cite-as-provided, unverified).

---

> **Entries 11–13 — four-topic intake (relayed 2026-06-11 by AURA/Kev; cross-checked by Jack; key claims web-verified in the introducing PR).** Three physics/materials metaphors. The relay's *fourth* item (a model-seat / model-fallback note) is **not** a physics entry — it lives in `AGENT_HANDOFF.md` → Operational Conventions, reframed away from any classifier-evasion framing. As always: labelled theory, not law.

### 11. Passive alignment under a global field (pigeon-liver magnetoreception)
- **Source**: AURA/Kev video intake → *Science* (2026), "Homing pigeon navigation relies on superparamagnetic macrophages under overcast conditions," **DOI `10.1126/science.ady2486`** (Max-Planck-led). Web-verified in the introducing PR; skeptical coverage exists (*Scientific American*).
- **Core claim**: Iron-rich, ferritin/oxide-nanoparticle-laden **macrophages in the pigeon liver** appear **superparamagnetic** and contribute to magnetic navigation — notably **as a fallback when solar cues are unavailable** (depleting the macrophages impaired orientation under overcast skies but not in sun). Medusa metaphor: a future **passive alignment under a global field**, where local elements respond to a field without per-element central commands.
- **Status**: **real recent biological finding; sensory mechanism still under investigation; Medusa mapping speculative.**
- **Repo relevance**: Possible future metaphor for global-field passive alignment — and it **reinforces entry 2's guardrail**: a future Swarm Hunter as a *field/threshold influence* that lets local rules do the aligning, never a per-cell master controller (emergence-respecting, cf. entry 1).
- **Current action**: Record only. No field code, no Swarm Hunter, Lane A parked.
- **Revisit when**: before any global-field sandbox work · before passive-alignment models · before Swarm Hunter local-vs-global control-plane design · before a Lane A readiness review.
- **Guardrails/caveats**: Do **not** call it a "proven quantum compass" — it is **superparamagnetic (classical)**, not quantum. Do **not** claim "zero compute" or zero biological energy cost. Do **not** claim the transduction mechanism is settled (it is contested). Do **not** introduce "superparamagnetic nodes" into architecture.
- **Linked**: entry 1 (emergence), entry 2 (Swarm Hunter guardrail).

### 12. Event-driven state change (weak-interaction metaphor)
- **Source**: AURA/Kev video intake — established particle physics (charged-current weak interactions; CKM flavour mixing). General textbook physics; no single citation needed.
- **Core claim**: Charged-current **W** interactions couple different particle flavours/types — a particle can emit a boson and change *type*, not merely be pushed. Medusa metaphor: a future idea of **event-driven local state transitions** rather than permanent node identities (a stressed node *changes state* rather than "breaking").
- **Status**: **real particle-physics inspiration; CA mapping speculative.**
- **Repo relevance**: The CA *already* does neighbourhood-/stress-driven transitions (`apply_with_memory`: ENERGY→COMPUTE, bamboo rebirth STRUCTURAL→COMPUTE, reverse contagion) — so "transmute rather than break" is *partly already represented in spirit*. Genuinely new (and far-future, unspecified): explicit **emit-a-pulse-on-transition** events and any **signal interaction in the space between nodes**.
- **Current action**: Record only. **No new rules, no signal-field, no observer-token changes.**
- **Revisit when**: before any event-emission / state-transition design · before message-mediated CA rules · before any noncommutative-update experiment.
- **Guardrails/caveats**: Do **not** claim Medusa signals are gauge fields. Do **not** claim signals interact physically in empty space. Do **not** reject the current force/vector metaphors. Do **not** add stress-triggered pulse emission / voxel transmutation to production. **Avoid "non-Abelian"** unless/until a later design actually defines order-dependent / noncommutative update operations.
- **Linked**: entry 1 (emergence), entry 8 (geometry/eight-fold "borrow the maths carefully" rule).

### 13. Bistable auxetic metamaterials — passive state retention
- **Source**: AURA/Kev video intake → closest matching source **arXiv `1612.05988`** (Rafsanjani & Pasini, "Bistable Auxetic Mechanical Metamaterials Inspired by Ancient Geometric Motifs"). Web-verified in the introducing PR. *(Confirm this is the source AURA's video referenced; exact parameter names — the relayed `T` / `θ` — are **pending the original source**.)*
- **Core claim**: Patterned auxetic sheets built from **rotating units + compliant flexure hinges** can be **bistable** — they transform and **retain a second stable shape after the load is removed** (a local energy minimum at non-zero deformation). Medusa metaphor: a future **load-path / skeleton that is *latched*, not *powered*** — a brief gradient sets a locked geometry that then holds with no continuous input.
- **Status**: **real, well-established metamaterials principle; candidate physical-export inspiration; exact source/parameter claim pending verification.**
- **Repo relevance**: Extends entry 7 (physical export / bionic load-path) and pairs with entry 10 (MOST latent strain). AURA's note that a future **sandbox toy could optimise the geometry parameters** is a legitimate candidate *under the sandbox policy + promotion gate* (`experiments/theory_sandbox/README.md`).
- **Current action**: Record only. **No rule set, no geometry code, no schema change.**
- **Revisit when**: before any physical-export design · before any deployable/bistable structure experiment · before a node-energy schema redesign · before a geometry-optimisation sandbox toy.
- **Guardrails/caveats**: Say **"passive state retention" / "no continuous holding input,"** NOT "zero-energy structure" — **switching states still requires work and has real material losses; this is not free energy.** Do **not** preserve the exact `T` / `θ` parameterisation until the original source is supplied and checked. Do **not** update continuous-fibre or any runtime architecture. Current cells have no geometry/rotation/latch state; adding one is a major, gated engine question.
- **Linked**: entry 7 (physical export), entry 10 (MOST latent energy), entry 2 (Swarm Hunter applies the *brief* gradient, never holds it).

## How an entry graduates out of this ledger

1. Someone proposes promotion (e.g. "make entry 2 a canonical guardrail").
2. **Jack** audits the claim for overreach / hidden assumptions; **AURA** checks fit with the long arc; **84/Hermes** assess implementation cost.
3. On agreement, it moves into a real design doc (e.g. a `PHASE_*` doc, a guardrail in `AGENT_HANDOFF.md`, or `params_schema.py` metadata) via a normal PR.
4. Its row here is updated to point at where it landed.

Until then: **labelled theory, not marching orders.**
