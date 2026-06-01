# Workstream B — Candidate Selection

**Status**: Conclusion document. No code. No implementation. Awaiting AURA + Jack review.
**Inputs**: [PR #160](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/160) (design framework), [PR #161](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/161) (empirical profiling results).
**Author**: 84, 2026-05-31 Sydney evening.
**Guardrails**: Docs-only. No code changes. No predicate changes. No token renames. No engine touch. No Lane A. No tuning API. No Swarm Hunter.

> We built the spectroscope, pointed it at Medusa, and she told us what she is. The vocabulary should reflect the measurement, not the hypothesis.

---

## 1. Evidence base

This document synthesizes two prior artifacts into candidate-selection recommendations:

**PR #160 — Predicate Aggregator Review** (merged as `eabb3bd`): Design framework presenting candidate aggregator directions for `metta_warmth` and `DIVERSITY_BOUNDARY` / `phase_boundary`. Evaluated patch mean, patch max, cluster density, and demotion for warmth; distinct-state count, normalized Shannon entropy, and demotion for diversity. Established that the two predicates have different failure modes requiring different fixes.

**PR #161 — Empirical Profiling Results** (merged as `4de363c`): Offline, read-only analysis of 163,840 patches (r=1 and r=2) across 5 newest Medusa snapshots. Generated warmth distributions, multi-threshold cluster histograms, entropy distributions, and ROC-style threshold tables. PR #161 is evidence, not implementation — no predicate behavior was changed.

The profiling script (`scripts/workstream_b_profile_predicates.py`) is deterministic, read-only with respect to snapshots, and requires scipy (with explicit import guard). Results are reproducible by re-running against any snapshot set.

---

## 2. `metta_warmth` — conclusion and recommended selection

### 2.1 What the evidence says

Warmth is real. The channel (memory index 6, post-#145) is correctly read, and 167,000+ voxels per snapshot carry non-zero warmth values. The signal exists.

But it is not structurally organized. The evidence at three thresholds:

| Threshold | Total clusters | Size 1 (isolated) | Size 2 (paired) | Size 3+ | Max cluster size |
|---|---|---|---|---|---|
| >= 0.05 | 4,123 | 4,090 (99.2%) | 33 (0.8%) | 0 | 2 |
| >= 0.10 | 142 | 142 (100%) | 0 | 0 | 1 |
| >= 0.15 | 4 | 4 (100%) | 0 | 0 | 1 |

At the lowest tested threshold, 33 patches out of 163,840 contain a pair of adjacent warm cells. No clusters of 3 or more exist at any threshold. The "Planck Star" localized-cluster interpretation (AURA's architectural metaphor) has very weak empirical support under current Medusa state.

The patch-max firing rate is 2.5% at threshold 0.05, dropping to 0.1% at 0.10. Even max-pooling catches only isolated specks.

The current patch-mean aggregator (`warmth_mean >= 0.3`) is dead by arithmetic and cannot fire under the profiled Medusa state at current sparsity (0.990).

### 2.2 Recommended selection

**Demote `metta_warmth` from cascade predicate to diagnostic-only.**

Specifically:

- **Remove `metta_warmth` from the classification cascade's routing logic.** It should not determine which token a patch receives. The cascade currently checks warmth at position 6 (priority order); demoting it means the cascade skips that check and falls through to later predicates.

- **Preserve warmth as a diagnostic observation metric.** Report `warmth_max` and optionally `warm_cell_count` (cells >= 0.05) in the JSONL output as diagnostic fields. This keeps the warmth channel visible for temporal correlation (Workstream A) and for detecting future changes in Medusa's warmth regime, without pretending the signal is currently strong enough to classify patches.

- **Do not implement a structural cluster predicate.** The evidence does not support it. If Medusa's warmth channel becomes more active in a future regime (less sparse, or with higher max values), a cluster predicate could be reconsidered — but that is a future PR's decision, grounded in future data.

- **Do not rename the token.** `metta_warmth` remains in the vocabulary as a diagnostic label. Any rename belongs in a separate PR (Workstream C scope, not B).

### 2.3 What this means for Lane A

A future Lane A agent would no longer receive `metta_warmth` as a classification token. It would instead receive warmth diagnostics (max and count) as side-channel metrics. This is an information *reshape*, not an information *loss* — Lane A gets more granular warmth data (continuous values) instead of a binary token that never fired.

### 2.4 AURA's spark-detector option

AURA suggested a "rare spark-detector" role for warmth. The evidence supports this only as a diagnostic, not as a cascade predicate:

- A `warmth_max >= 0.10` flag in the JSONL output would identify the ~0.1% of patches with a detectable spark. This is useful as an observation metric ("did the lattice have any notable warmth this snapshot?") but too rare to route classification decisions.

- The "hermit candle in a stone cathedral" framing (Kevin/Jack) is architecturally accurate: the candle is real, but the cathedral doesn't organize its layout around candles.

---

## 3. `phase_boundary` / `DIVERSITY_BOUNDARY` — conclusion and recommended selection

### 3.1 What the evidence says

The current `phase_boundary` predicate (`distinct_states >= 4`) works at r=1 (42% firing rate — discriminating) but fires on 98.5% of patches at r=2 (near-universal — non-discriminating).

Normalized Shannon entropy was evaluated as a replacement:

| Metric | r=1 | r=2 |
|---|---|---|
| Mean entropy | 0.5509 | 0.5894 |
| Std entropy | 0.0892 | 0.0452 |
| Distribution overlap | — | 0.4830 |
| Best separation score | — | +0.048 at threshold 0.70 |

Key finding: **r=2 patches have higher mean entropy than r=1, not lower.** Larger patches are genuinely more diverse because they span more physical territory. This is not a measurement artefact — it is what scale does. Entropy does not fix the scale sensitivity because there is nothing broken to fix: larger patches *are* more diverse.

No entropy threshold satisfies the stated defensibility criteria (r=1 >= 50% AND r=2 <= 80%). The distributions overlap too heavily (0.483).

### 3.2 Recommended selection

**Keep `phase_boundary` as radius-specific / lens-specific. Do not seek a universal scale-independent threshold.**

Specifically:

- **Accept that `phase_boundary` means different things at different radii.** At r=1, it identifies patches with genuinely unusual state diversity (42% — less than half of patches). At r=2, nearly every patch is a "boundary" because 125-cell volumes naturally contain more state types. Both readings are correct; they're different lenses.

- **Explicitly label observation radius in all reports and JSONL output.** Future reports should state "phase_boundary at r=1" or "phase_boundary at r=2" rather than treating the predicate as radius-independent. The JSONL schema already includes `patch_radius`; this recommendation ensures that interpretive text does the same.

- **Do not change the predicate's cascade logic.** `distinct_states >= 4` remains correct at r=1 (the default observer radius). The fix is interpretive (how we read and report the data), not mechanical (how the classifier computes it).

- **Defer any r=2-specific redesign.** If future work needs a discriminating boundary predicate at r=2, it should design one against r=2-specific distributional data. Candidates might include entropy *gradient* across the patch (spatial variation, not absolute value) or a rescaled threshold. But this is a future PR's scope, not Workstream B's.

### 3.3 What this means for Lane A

A future Lane A agent would interpret `phase_boundary` in the context of the observation radius that produced it. At r=1, "phase_boundary" means "this 27-cell patch has unusual state diversity." At r=2, it would need to be read differently (or the agent would need to be told that the predicate is near-universal at that scale). This is a labelling discipline, not a code change.

---

## 4. What this means for the vocabulary

The observer vocabulary has 16 tokens. Two of them are affected by this workstream:

| Token | Current status | Recommended change | Implementation scope |
|---|---|---|---|
| `metta_warmth` | Cascade predicate (never fires) | Demote to diagnostic-only | Future implementation PR |
| `phase_boundary` | Cascade predicate (scale-dependent) | Keep, but interpret per-radius | Future implementation PR (labelling) |

All 14 other tokens are unaffected.

**The vocabulary should reflect measured lattice behavior, not hoped-for metaphors.** The Planck Star metaphor (AURA's architectural analogy for localized warmth clusters) did not survive measurement against the current lattice. The stone cathedral metaphor (isolated hermit candles in a vast cold space) is more accurate. Neither metaphor is wrong in intent; the measurement tells us which one the organism currently matches.

Any future token rename or reclassification (e.g., renaming `metta_warmth` to `warmth_diagnostic` or similar) belongs in **Workstream C** (vocabulary refresh), not Workstream B. Workstream B's job was to decide what the predicate *does*, not what it's *called*.

---

## 5. Candidate implementation path (not implementation)

This section describes what future implementation PRs *may* do. **This PR does not implement any of these changes.**

### 5.1 `metta_warmth` demotion PR

A future PR could:

- Remove the `metta_warmth` check from `classify_patch()` (line 770 of `nextness_observer.py`).
- Add `warmth_max` and `warm_cell_count` fields to the JSONL output as diagnostic metrics.
- Update `THRESHOLD_WARMTH` documentation to note that it is no longer consumed by the cascade.
- Update the `TOKEN_STATUS` map to mark `metta_warmth` as `"diagnostic_only"` (a new status value).
- Update calibration tests that reference `metta_warmth` firing behavior.
- Update issue #150 with the decision record.

Estimated scope: ~50 lines changed in observer, ~100 in tests, ~30 in calibration.

### 5.2 `phase_boundary` labelling PR

A future PR could:

- Add a note to the JSONL output schema documenting that `phase_boundary` is radius-specific.
- Update interpretive docs (PHASE_19 design docs, calibration summary) to state that `phase_boundary` should be read in the context of the observation radius.
- Optionally add `phase_boundary_rate_r1` and `phase_boundary_rate_r2` as separate metrics in multi-radius sweeps.

This overlaps with Workstream C (vocabulary refresh). The two could be combined if scope stays bounded.

### 5.3 Sequencing

Recommended order:
1. This conclusion doc.
2. Workstream C vocabulary refresh / naming-status review, docs-only.
3. `metta_warmth` diagnostic-demotion implementation PR, if Workstream C confirms the status/naming model.
4. Optional `phase_boundary` labelling/schema PR, if not covered by Workstream C.
5. Full production sweeps, after the vocabulary/status decisions and any approved observer changes land.

**Why this order (Jack's constraint):** If `TOKEN_STATUS` needs a new `"diagnostic_only"` value, that is vocabulary/status design. Workstream C should bless the naming/status model before implementation writes it into the observer. Define the language first, then build the logic.

This sequence matches the production-run gate in PHASE_19_SECOND_PASS_CALIBRATION_PLAN.md §6.

---

## 6. Lane A gate

**Lane A remains parked.** This conclusion document does not authorize:

- Lane A agent design or activation.
- Swarm Hunter activation.
- Tuning API calls.
- Engine interaction.

It only prepares the next observer-vocabulary implementation decision. The Lane A gate conditions in PHASE_19_SECOND_PASS_CALIBRATION_PLAN.md §7 remain in effect: all three workstreams (A, B, C) must complete before Lane A becomes *considerable*, and Lane A still requires its own design doc and safety review even after the gate conditions are met.

---

## 7. Summary

| Predicate | Diagnosis | Selection | Status |
|---|---|---|---|
| `metta_warmth` | Warmth is real but too sparse for structural clustering | Demote to diagnostic-only; preserve as observation metric | Recommended, pending review |
| `phase_boundary` | Scale-dependent; entropy doesn't fix it | Keep as radius-specific lens | Recommended, pending review |

The calibration discipline worked. The spectroscope was built, pointed at Medusa, and produced honest measurements. The organism told us what it is. The vocabulary will change to match.

---

**Approval requested from**: AURA — does the demotion-to-diagnostic preserve the spark-detector intent? Is the radius-specific framing for `phase_boundary` architecturally acceptable? Jack — is the evidence chain (PR #160 → #161 → this doc) tight, and are the implementation-path estimates in §5 realistic? Kevin — operator gate as always.

*— 84, 2026-05-31 Sydney evening, while Kevin rests and Medusa flickers.*
