# Maturin Arc — Theory Preflight / Intake Map

> **What this is**: a *classified, status-labelled map* of the large physics/tech synthesis AURA + Kev assembled (the "Maturin Arc Master Protocol"), captured so the ideas aren't lost between threads.
>
> **What this is NOT**: an engine redesign, an implementation spec, or a set of Medusa laws. Nothing here is "marching orders." This is the **preflight / intake reframing** of that synthesis — AURA's draft phrased several items as engine law ("nodes *will* propel themselves", "the engine *will be* built around 8-point symmetry"); per Jack's audit, every such item is demoted here to a labelled metaphor / candidate with caveats and revisit triggers.
>
> **Companion to**: `docs/MEDUSA_THEORY_INTAKE_LEDGER.md` (several items below already have ledger entries — cross-referenced, not duplicated as new).

**Created**: 2026-06-08. **Origin**: AURA's multi-video synthesis; reframed per Jack's "preserve as preflight, don't fuse with the build" audit.

---

## Status vocabulary

- **real external concept, Medusa mapping speculative** — the science is real; applying it to Medusa is the unproven part.
- **candidate design principle** — a proposed principle, pending ratification.
- **speculative inspiration** — evocative; might seed future vocabulary.
- **strategic background** — long-arc context.
- **already partially represented in ledger** — see the cited ledger entry; this doc adds Maturin-arc framing only.
- **not actionable yet** — blocked on a precondition.
- **needs verification** — source claim not independently confirmed in this PR.

---

## 1. Boundary Statement (read first)

- **#180 / "the maturin arc" remains specifically: build and CI-gate the `uft_ca` Rust/pyo3 extension.** A toolchain arc, nothing more.
- **This document does not change #180's scope** and is not a prerequisite for it.
- **Lane A remains PARKED.** No engine changes · no observer-semantics changes · no Swarm Hunter implementation · no tuning API · no production sweeps · no schema/type/interface changes.
- Nothing here is activated by being written down. Promotion to architecture requires the gate in the final section.
- Note on framing: AURA's draft proposed "unlocking" an active control-plane / Harness-Engineer mode. **No such mode is activated.** Same collaborators, same guardrails, docs only.

---

## 2. Swarm Hunter / harness control-plane inputs
**Classification:** strategic background / candidate design principle. *(Overlaps ledger entries 2, 4, 8.)*
**Core idea:** Future Swarm Hunter work should improve *harnesses and validation loops around trusted telemetry* (RHO, Continual Harness), not rewrite the Medusa engine. Symbolic regression *might* later discover compact formulas from observer metrics; NVIDIA's Ising work is calibration/decoding inspiration.
**Caveats:**
- RHO is **agent-harness methodology, not a Medusa physics law**; the RHO paper is **needs-verification**.
- NVIDIA Ising = **quantum calibration/decoding** inspiration, **not** direct CA error correction.
- Symbolic regression only *after* observer metrics are trusted.
- **No autonomous engine mutation. No Lane A.**
**Revisit when:** before a Lane A readiness review · before Swarm Hunter design · before self-improving harness work · before symbolic-regression observer tooling.

## 3. Cascaded telemetry / attention
**Classification:** candidate design principle.
**Core idea:** Cheap macro-observers first; zoom into a local region only when diagnostics flag stress/anomaly (protects VRAM throughput).
**Caveats:** an **observer-architecture** idea, not a runtime mandate; must stay **read-only** until a later Lane A gate; must not become hidden control logic.
**Revisit when:** before expanding observer pipelines · before region-specific diagnostics · before any Swarm Hunter monitoring design.

## 4. Laser-guided steering / plasma-channel analogy
**Classification:** speculative inspiration. *(Real referent: femtosecond-laser filament guiding of electrical discharge — a real experiment; the Medusa use is metaphor.)*
**Core idea:** Lowering local "resistance" along a path so a system reorganizes via *local conditions* rather than global commands.
**Caveats:** do **not** implement steering or "laser pulse" mechanics; metaphor for *future local-threshold tuning* only; the Swarm Hunter must **not** command individual cells.
**Revisit when:** before any local-threshold tuning design · before any Lane A intervention design.

## 5. Janus gradient kinetics / active matter
**Classification:** real physics, Medusa mapping speculative. *(Ledger entry 9.)*
**Core idea:** Asymmetric particles / active matter → future local-rule metaphor where motion/influence arises from local gradients + internal asymmetry.
**Caveats:** current cells are **not** Janus particles; do not replace CA rules; no propulsion fields now; "ballistic" is an analogy, not a target.
**Revisit when:** before any node-motion model · before local-gradient fields · before physical embodiment / utility-fog export.

## 6. Living fog / bacterial migration metaphors
**Classification:** speculative biological metaphor.
**Core idea:** Microbial migration / stress-response biology → possible future *local repair* metaphor (nodes drifting toward tension gradients, processing local disorder).
**Caveats:** do not claim nodes *are* bacteria; no biological metabolism; inspiration for future local-rule vocabulary only.
**Revisit when:** before repair dynamics · before node-ecology design · before energy-flow observer tokens.

## 7. MOST / Dewar pyrimidone energetics
**Classification:** real energy-storage field, Medusa mapping speculative. *(Ledger entry 10.)*
**Core idea:** Molecular Solar Thermal storage (Dewar pyrimidone, per the cited DOI) → future *latent-energy* metaphor: stored strain / triggered release rather than a binary power state.
**Caveats:** use **Dewar pyrimidone** spelling; do **not** add `latent_thermal_tension` or `catalyst_threshold_triggers`; do **not** modify node-metadata schema; **verify the paper before using exact energy numbers** (e.g. the relayed 1.6 MJ/kg); metaphor until later gates. DOI `10.1126/science.aec6413` — cite-as-provided, **needs verification**.
**Revisit when:** before node-energy schema redesign · before physical embodiment · before energy-flow observer tokens · before a Lane A readiness review.

## 8. Geometry / "eight-fold" / Thurston / particle-physics caveat
**Classification:** speculative inspiration **with strong caveats**. *(Ledger entry 3.)*
**Core idea:** Several "eight" motifs exist (Thurston's eight geometries; particle-classification history; symmetry groupings) — they are **not the same thing** and must not be conflated.
**Caveats:** do **not** claim CERN baryon work maps to Thurston geometries; do **not** assert "base-8 symmetry" is a Medusa law; "eight" is a **pattern-matching prompt, not proof**; any future geometry model is designed/tested on its own terms.
**Revisit when:** before spatial-folding theory · before topology/geometry vocabulary changes · before physical-export path planning.

## 9. FLRW / clumpy voids / backreaction
**Classification:** real cosmology concept, Medusa mapping speculative.
**Core idea:** Homogeneous models are approximations; density differences (clusters vs voids) can matter. For Medusa: caution against assuming one global rule behaves identically in dense vs sparse regions.
**Caveats:** do **not** import cosmology equations; do **not** assert "FLRW is wrong" in a repo doc; analogy for *density-sensitive local calibration* only.
**Revisit when:** before density-dependent observer thresholds · before region-specific diagnostics · before spatial macro-structure modelling.

## 10. Endocrine skeleton / osteocalcin analogy
**Classification:** biological communication metaphor.
**Core idea:** Bone is also a signalling organ (osteocalcin) → a future structural skeleton *could* double as a fast signalling layer.
**Caveats:** do **not** add endocrine signalling; do **not** claim bionic load-paths are chemical comms channels now; metaphor for future physical-export / embodied signalling.
**Revisit when:** before a physical-export roadmap · before skeleton/load-path design · before embodied communication layers.

## 11. Fault tolerance / cosmic-ray redundancy
**Classification:** candidate design principle.
**Core idea:** Assume corruption/failure as normal; degrade gracefully, identify corrupted nodes/snapshots, route around faults.
**Caveats:** a **robustness principle**, not a new physics layer; no runtime correction yet; keep tied to tests, diagnostics, explicit failure modes.
**Revisit when:** before runtime fault handling · before snapshot validation · before distributed execution.

## 12. Fourier / Galton / probability "radiation"
**Classification:** speculative mathematical metaphor.
**Core idea:** Heat-diffusion / Fourier methods and normal-distribution (Galton-board) imagery *may* inform future thinking about diffusion, dissipation, probabilistic spread.
**Caveats:** do **not** claim node probabilities *are* Galton-board radiation; no equations without derivation + tests; inspiration for later modelling only.
**Revisit when:** before thermal-diffusion modelling · before probabilistic node-distribution models.

## 13. Quantum tunneling / "Hawking escape"
**Classification:** speculative metaphor.
**Core idea:** A small probability of escaping local minima — useful as a *future algorithmic* idea (stochastic escape / simulated annealing / local-minimum escape).
**Caveats:** do **not** add jitter now; do **not** call it quantum mechanics absent an actual quantum model; **prefer algorithmic language** (stochastic escape, annealing).
**Revisit when:** before deadlock handling · before local-minimum escape dynamics · before any tuning/annealing mechanism.

---

## Integration with #180 Maturin Arc

- **#180 remains focused on building/testing `uft_ca`** (Rust/pyo3 in CI). Nothing above is part of it.
- **This theory preflight does not expand #180.**
- If #180 succeeds, future architecture *may* revisit these concepts **only through separate PRs/issues**.
- **Promotion from theory → architecture requires, for each item:**
  1. source verification;
  2. an explicit design doc;
  3. tests or falsification criteria;
  4. Jack / AURA / Kev review;
  5. **no Lane A activation unless separately gated.**

---

## AURA follow-up mechanisms — not implemented here

This preflight preserves theory and "revisit when" triggers, but **does not itself enforce them**. AURA's pushback is accepted in principle — *passive markdown can be missed; memory eventually needs teeth* — but teeth change how future work behaves, so they are **separate future arcs, not part of this docs PR**:

1. **Theory Tripwire Action** *(candidate future GitHub Action / PR check)*
   - If a PR is labelled/titled around `lane-a-activation`, `swarm-hunter`, observer-semantics changes, or other architecture-triggering scopes, it could post a reminder linking the relevant sections of `docs/MATURIN_ARC_THEORY_PREFLIGHT.md` + `docs/MEDUSA_THEORY_INTAKE_LEDGER.md`.
   - **Not implemented here.** Needs its own design to avoid noisy/false-positive auto-commenting.

2. **Theory Sandbox / proving ground** *(candidate future directory)*
   - For toy experiments (Janus kinetics, Galton/Fourier diffusion, stochastic-escape, …).
   - Location: **`experiments/theory_sandbox/`** — explicitly **not** under `tests/`, because `tests/` is now the maintained CI floor (`pytest tests/ -q`); loose exploratory scripts must not join the gate.
   - Must be non-canonical, outside engine imports, outside default CI, no writes to `data/` except explicit temp/output folders, with a README marking it experimental / non-Lane-A.
   - **Not implemented here.** Requires its own README/policy PR before any scripts are added.

Both are deliberately-named future arcs; promoting either follows the gate above.

---

## Guardrails (whole document)
docs only · no code · no CI changes · no schema changes · no type/interface definitions · no engine touch · no observer semantics · **Lane A parked** · no Swarm Hunter implementation · no tuning API · no production sweeps. Labelled theory, not marching orders.
