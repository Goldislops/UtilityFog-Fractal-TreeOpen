# Workstream C — Vocabulary & Status Model Review

**Status**: Design review. No code. No token renames. Awaiting AURA + Jack review.
**Inputs**: PHASE_19_SECOND_PASS_CALIBRATION_PLAN.md §5 (Workstream C definition), PR #162 (Workstream B candidate selection, which defers to this doc for naming/status model).
**Author**: 84, 2026-06-01 Sydney morning.
**Guardrails**: Docs-only. No observer changes. No token renames in code. No engine touch. No Lane A. No tuning API. No Swarm Hunter.

> Define the language first. Then build the logic.
> — Jack's constraint on implementation sequencing (PR #162 §5.3)

---

## 1. Purpose

This document answers eight questions Jack posed for Workstream C, establishing the vocabulary/status model that implementation PRs must follow. It also completes the forward-pointer audit for pre-#145 vocabulary references in interpretive docs.

Until this document is reviewed and merged, no implementation PR should modify `TOKEN_STATUS`, add new JSONL fields, or change the classification cascade.

---

## 2. The eight questions, answered

### Q1: What does `diagnostic_only` mean?

**Proposed definition**: A token whose underlying signal is physically real and measured, but whose classification-cascade predicate is not discriminating enough to route patch classification in current Medusa state.

A `diagnostic_only` token:
- **Remains in `TOKEN_NAMES`** (preserves vocabulary size, historical continuity, and the assertion `set(TOKEN_STATUS.keys()) == set(TOKEN_NAMES)`).
- **Is listed in `TOKEN_STATUS`** with value `"diagnostic_only"`.
- **Is skipped by `classify_patch()`** — the cascade does not check its predicate. (Same mechanical behavior as `deprecated_no_engine_channel`, but with a different semantic reason.)
- **Has its underlying measurement reported as a numeric field** in the JSONL output (e.g., `warmth_max`, `warm_cell_count`), separate from `token_counts`.
- **Can be rehabilitated** to an active cascade predicate if future Medusa states produce a stronger signal. Rehabilitation requires new profiling evidence and a review gate, not just a threshold tweak.

**Distinction from existing statuses:**

| Status | Meaning | Can fire in cascade? | Example |
|---|---|---|---|
| `state_only` | Predicate uses cell state, no memory channels | Yes | `void_static` |
| `stored` | Predicate reads a stored memory channel | Yes | `compute_aging` |
| `deprecated_no_engine_channel` | Predicate references a channel that doesn't exist | No | `karuna_relief` |
| `derived_future` | Predicate references a derived quantity not yet implemented | No | `magnon_lighthouse` |
| **`diagnostic_only`** (new) | **Predicate's signal is real but not discriminating** | **No** | **`metta_warmth`** |

The key difference between `diagnostic_only` and `deprecated_no_engine_channel`: the former has a real signal that's too sparse to classify with; the latter has no signal at all (wrong channel or missing channel).

### Q2: Is `diagnostic_only` a token status, an output-channel status, or both?

**Token status only.** It is a value in the `TOKEN_STATUS` dictionary, applied per-token.

It is NOT an output-channel status. The diagnostic measurements (warmth_max, warm_cell_count) are added to the JSONL output as **top-level numeric fields**, not as a new output channel or a separate diagnostic dictionary. They sit alongside existing fields like `boundary_rate` and `void_compute_balance` — per-snapshot scalar metrics computed from data already in memory.

**Room to grow**: top-level fields are the right call for the initial two diagnostics (keeps parsing trivial and consistent with the existing flat schema). If the JSONL entry later accumulates several diagnostics and the top level gets crowded, the implementation may migrate them into a nested `diagnostics` object at that point. Flagged here so the future option is explicit rather than a surprise refactor; the initial implementation stays flat.

### Q3: Should `metta_warmth` remain a named token?

**Yes.** `metta_warmth` stays in `TOKEN_NAMES` with status `diagnostic_only`. Reasons:

- **Historical continuity**: PR #142-era docs, calibration summary §4.2, and issue #150 all reference it by name. Removing it from the vocabulary would break cross-references.
- **Future rehabilitation**: If Medusa's warmth channel becomes less sparse (e.g., under different initial conditions or engine evolution), the token can be re-promoted to `stored` status with a new profiling pass. Easier to re-promote than to re-invent.
- **The assertion holds**: `set(TOKEN_STATUS.keys()) == set(TOKEN_NAMES)` continues to pass because the token is still in both sets.
- **Occupancy semantics must be explicit**: because `diagnostic_only` tokens remain in `TOKEN_NAMES` but do not route classification, future implementation should either document `vocabulary_occupancy` as full historical-vocabulary occupancy, or add a separate `active_vocabulary_occupancy` metric that excludes non-routing statuses. Jack's preference is to add/define an active occupancy metric in the implementation PR so Lane A does not mistake diagnostic vocabulary for active routing vocabulary.

### Q4: Should `metta_warmth` be renamed?

**Not in Workstream C. Not in the implementation PR. Not yet.**

The name `metta_warmth` accurately describes what the predicate *measures* (warmth in the metta/loving-kindness accumulation channel, memory index 6). The name is correct; the signal is just too sparse to classify with. Renaming it (e.g., to `warmth_diagnostic`) would change the vocabulary without changing the underlying reality, and would break references in 5+ documents.

If a rename is ever desired, it belongs in a **separate, future PR** with corresponding test updates, doc updates, and a review gate. It is explicitly out of scope for Workstream B and C.

### Q5: How should `phase_boundary` be documented as radius/lens-specific?

**Three documentation changes (all docs-only, no code):**

1. **JSONL schema note**: Add a comment block in `process_snapshot()` (near the `entry` dict construction) documenting that `boundary_rate` and `token_counts["phase_boundary"]` are radius-specific: their firing rates change with `patch_radius`. The `patch_radius` field already exists in the JSONL entry; the note ensures future readers know to interpret `phase_boundary` in that context.

2. **Interpretive doc note**: Add a forward-pointer in the Workstream B conclusion doc (already merged as PR #162 §3.2) that links to this document's radius-specific guidance.

3. **Calibration doc note**: In PHASE_19_PR4_CALIBRATION.md (the design doc), the existing Ch8 description of `sweep_patch_radius` already documents the scale-sensitivity finding. A brief forward-pointer note should reference PR #162's conclusion.

**No code changes.** The cascade logic for `phase_boundary` stays as-is (`distinct_states >= DIVERSITY_BOUNDARY`). The fix is interpretive, not mechanical.

### Q6: What fields must appear in JSONL reports?

**New diagnostic fields (to be added by the implementation PR, not this doc):**

| Field | Type | Description | Alongside |
|---|---|---|---|
| `warmth_max` | float | Max warmth-channel value across all patches in this snapshot | `boundary_rate` |
| `warm_cell_count` | int | Total cells with warmth >= 0.05 across all patches | `warmth_max` |
| `active_vocabulary_occupancy` | float | Fraction of *routing* tokens (statuses that can fire) that appeared, excluding `diagnostic_only` / `deprecated_no_engine_channel` / `derived_future` | `vocabulary_occupancy` |

The existing `vocabulary_occupancy` field is **retained and re-documented** as full historical-vocabulary occupancy (fraction of all 16 `TOKEN_NAMES` that appeared). The new `active_vocabulary_occupancy` gives the routing-only view. Keeping both means historical JSONL stays comparable while Lane A gets the disambiguated metric.

These fields are:
- **Top-level in the JSONL entry**, not nested inside `token_counts`.
- **Numeric**, not classification outputs.
- **Clearly distinguishable** from `token_counts` by type (float/int vs. dict) and by position (top-level vs. nested).

A future Lane A agent should be able to see: "`token_counts` is what the cascade classified; `warmth_max` and `warm_cell_count` are diagnostic measurements that the cascade does not consume."

**No schema version bump needed.** Adding new top-level fields to a JSONL entry is non-breaking — existing parsers ignore unknown keys. If a version field is desired later, it can be added in a future infra PR.

### Q7: Which docs need updating?

**Forward-pointer audit results (main-branch Phase 19 docs):**

| Document | Current state | Action needed |
|---|---|---|
| PHASE_19_PR4_CALIBRATION_SUMMARY.md | ✅ Already has §3 post-#145 correction | None |
| PHASE_19_SECOND_PASS_CALIBRATION_PLAN.md | ✅ Already scopes Workstream C | None |
| PHASE_19_PR3_METRICS_PIPELINE.md | ⚠️ References "Karuna/Boundary equilibrium" as current hypothesis; no post-#145 context | Add preamble note |
| PHASE_19_PR4_CALIBRATION.md | ⚠️ Multiple references to Karuna/Boundary framing as experiment target; no post-#145 pointer | Add preamble note |
| PHASE_19_NEXTNESS_OBSERVER.md | ✅ Single token-table reference; low-priority | Minor — update after implementation PR |
| AGENT_HANDOFF.md | ✅ No pre-#145 vocabulary found | None |
| docs/ folder | ✅ Clean | None |

**Two documents need forward-pointer notes:**

1. **PHASE_19_PR3_METRICS_PIPELINE.md** — Add a note at the top: "The Karuna/Boundary equilibrium hypothesis referenced in this document was formulated before PR #145 corrected the memory-channel layout. The post-#145 dominant token is `phase_boundary` (66.5%), not `karuna_relief`. See PHASE_19_PR4_CALIBRATION_SUMMARY.md §3 for the corrected distribution."

2. **PHASE_19_PR4_CALIBRATION.md** — Add a preamble note: "This design doc targets the Karuna/Boundary equilibrium hypothesis. PR #145 (memory-channel layout fix) invalidated the pre-fix interpretation: `karuna_relief` was reading `last_active_gen`, not the compassion field. The experiments in this doc remain valid but results must be read against the post-#145 channel layout. See PHASE_19_PR4_CALIBRATION_SUMMARY.md §3."

These are **forward-pointer notes only** — they do not rewrite the historical text. Per the second-pass plan §5 and §9 Q5: historicize rather than retire.

### Q8: What implementation PRs become allowable after Workstream C?

**After this document is reviewed and merged:**

1. **`metta_warmth` diagnostic-demotion PR** — May:
   - Add `"diagnostic_only"` to `TOKEN_STATUS` for `metta_warmth`.
   - Skip the `metta_warmth` predicate in `classify_patch()` (same pattern as `deprecated_no_engine_channel` tokens).
   - Add `warmth_max` and `warm_cell_count` to the JSONL entry.
   - Add/define an `active_vocabulary_occupancy` metric (per Q3's occupancy-semantics requirement) that excludes non-routing statuses, so Lane A does not mistake diagnostic vocabulary for active routing vocabulary. The existing `vocabulary_occupancy` field is retained and documented as full historical-vocabulary occupancy.
   - Update issue #150 with the decision record.
   - Update calibration tests.

2. **Forward-pointer docs PR** — May:
   - Add the two preamble notes to PHASE_19_PR3_METRICS_PIPELINE.md and PHASE_19_PR4_CALIBRATION.md.
   - **Recommended to keep this as a separate PR from the demotion implementation** (Jack's lean), so the code-change PR stays tightly scoped to observer logic and the docs PR stays purely textual. Combine only if both stay genuinely small.

3. **Optional `phase_boundary` labelling PR** — May:
   - Add JSONL schema comments documenting radius-specificity.
   - Only if not covered by the docs PR above.

4. **Full production sweeps** — Only after the demotion and any approved observer changes land, so canonical JSONL doesn't carry dead-predicate rows.

**Not allowable until after Workstream C:**
- Token renames (not proposed).
- New cascade predicates (not proposed).
- Lane A anything.
- Engine interaction.

---

## 3. Vocabulary snapshot — current vs. proposed

| Token | Current status | Proposed status | Cascade? | Notes |
|---|---|---|---|---|
| `void_static` | `state_only` | unchanged | Yes | — |
| `compute_static` | `state_only` | unchanged | Yes | — |
| `void_birth` | `state_only` | unchanged | Yes | — |
| `compute_aging` | `stored` | unchanged | Yes | — |
| `compute_decay` | `stored` | unchanged | Yes | Correctly uses warmth_mean for ambient coldness |
| `structural_growth` | `stored` | unchanged | Yes | — |
| `structural_decay` | `stored` | unchanged | Yes | — |
| `energy_pulse` | `state_only` | unchanged | Yes | — |
| `sensor_alert` | `state_only` | unchanged | Yes | — |
| **`metta_warmth`** | **`stored`** | **`diagnostic_only`** | **No → diagnostic** | Underlying signal real but too sparse |
| `karuna_relief` | `deprecated_no_engine_channel` | unchanged | No | No compassion channel in engine |
| `mudita_resonance` | `deprecated_no_engine_channel` | unchanged | No | No resonance channel in engine |
| `magnon_lighthouse` | `derived_future` | unchanged | No | Derived magnon not yet implemented |
| `acoustic_stress` | `state_only` | unchanged | Yes | — |
| `phase_boundary` | `state_only` | unchanged (+ docs) | Yes | Add radius-specific documentation |
| `unclassified` | `state_only` | unchanged | Yes | Catch-all |

**Only one token changes status.** The vocabulary size (16 tokens) does not change. The `TOKEN_NAMES` tuple does not change. The assertion `set(TOKEN_STATUS.keys()) == set(TOKEN_NAMES)` continues to hold.

---

## 4. What this document is not

- **Not implementation.** No code changes. The `TOKEN_STATUS` dictionary is not modified by this document.
- **Not a token rename.** `metta_warmth` keeps its name.
- **Not a Lane A decision.** Lane A remains parked.
- **Not a vocabulary redesign.** The 16-token vocabulary stays as-is. One token changes status; the rest are untouched.
- **Not a new interpretive framing.** The "hermit candle in a stone cathedral" metaphor (Kevin/Jack) is recorded as architectural observation, not baked into the vocabulary definition. Future framings are for AURA to propose, not for this doc to pre-decide.

---

**Approval requested from**: AURA — does the `diagnostic_only` status definition preserve the spark-detector intent? Is the forward-pointer (historicize, not retire) approach acceptable for the Karuna/Boundary framing? Jack — is the STATUS distinction between `diagnostic_only` and `deprecated_no_engine_channel` clean enough? Are the JSONL field additions in Q6 the right shape? Kevin — operator gate.

*— 84, 2026-06-01 Sydney morning, first day of winter, frost on the ground, warmth in the treehouse.*
