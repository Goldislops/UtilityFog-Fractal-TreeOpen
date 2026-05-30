# Workstream B — Predicate Aggregator Review

**Status**: Design analysis. No code in this document. Awaiting AURA + Jack review.
**Origin**: PHASE_19_SECOND_PASS_CALIBRATION_PLAN.md §4 (Workstream B).
**Companion to**: Issue #150 (predicate aggregator redesign question).
**Author**: 84, 2026-05-29 Sydney evening.
**Guardrails**: Lane B only. No engine touch. No Lane A. No Swarm Hunter. No tuning API.

> The calibration found two predicates non-discriminating under the current Medusa state. This document diagnoses *why* each fails to discriminate, evaluates candidate fixes, and presents a decision framework per-predicate. The final candidate selection is for AURA + Jack + Kevin to approve after the empirical profiling lands, not a unilateral call.

---

## 1. Executive summary

Two predicates in the observer's classification cascade are non-discriminating in current Medusa state:

| Predicate | Failure mode | Root cause | Candidate direction |
|---|---|---|---|
| `metta_warmth` | Never fires | **Aggregator shape**: patch-mean washes out sparse signal | Max-pooling or cluster density (empirical comparison pending) |
| `DIVERSITY_BOUNDARY` | Fires too easily at r=2 | **Scale sensitivity**: absolute count threshold ignores patch volume | Normalized Shannon entropy (radius validation pending) |

These are **different problems** requiring **different fixes**. Treating them as "both broken, demote both" would lose the diagnostic value of warmth detection entirely and leave diversity measurement ungrounded.

**This document presents a decision framework.** Final candidate selection happens after the empirical profiling in §6 lands. Implementation follows only after AURA + Jack review.

---

## 2. Predicate 1: `metta_warmth` — the dead predicate

### 2.1 Current implementation

```
# nextness_observer.py line 770
if (f.compute_count >= 1 or f.energy_count >= 1) and f.warmth_mean >= THRESHOLD_WARMTH:
    return "metta_warmth"
```

Where `warmth_mean` = arithmetic mean of the warmth channel (memory index 6) across all cells in the patch, and `THRESHOLD_WARMTH = 0.3`.

### 2.2 Why it never fires — the arithmetic

The warmth channel has sparsity 0.990 and max value 0.185 across calibration snapshots. For a 3x3x3 patch (27 cells):

- Expected non-zero cells per patch: 27 * 0.01 = **0.27**
- Best-case patch mean (one cell at 0.185, 26 at zero): 0.185 / 27 = **0.0069**
- Threshold required: **0.3**

The patch mean is ~43x below threshold in the best observed case. This is not a "tune the threshold" problem — `warmth_mean` cannot reach 0.3 without approximately 44 of 27 cells being at maximum warmth. The predicate is dead by arithmetic, not by tuning.

Even at the sweep's lowest multiplier (0.5x, effective threshold 0.15), the best-case patch mean of 0.0069 is still 22x below. **No threshold within the sweep's range can activate this predicate.**

### 2.3 The real diagnosis (AURA's framing)

The problem is the **aggregator shape**, not the threshold value. A spatial mean is a low-pass filter. It answers "is the average temperature of the room high?" When the phenomenon of interest is a sparse, localized spark — one or two warm voxels in a cold lattice — the mean returns noise. The spark exists; the aggregator can't see it.

AURA's framing: *the vocabulary refresh defines the literal language the Swarm Hunter will later use to see Medusa. If the warmth predicate can't see warmth, the Swarm Hunter is blind in that channel.*

### 2.4 Candidate aggregator designs

**Option A: Max-pooling** — replace `warmth_mean` with `warmth_max`

```
# Concept (not proposed code — design analysis only)
warmth_max = float(memory[warmth_idx].max())
fires when: warmth_max >= threshold
```

- **Strengths**: Simple. Directly detects "does this patch contain at least one warm cell?" Matches the physical question: is there a spark here?
- **Weaknesses**: Loses information about *how much* warmth is present. A single voxel at 0.185 would fire the predicate identically to ten voxels at 0.185. Also sensitive to noise — a single spurious voxel could trigger.
- **Threshold grounding**: With `warmth.max = 0.185` in current Medusa, a threshold around 0.10–0.15 would fire on patches containing at least one warm cell. But this needs empirical grounding: what fraction of patches would fire? If 1% of cells are warm and patches contain 27 cells, roughly 24% of patches would contain at least one warm cell. Is that a reasonable firing rate for a "warmth-notable" predicate?

**Option B: Density cluster count** (AURA's suggestion) — count warm-cell clusters

```
# Concept
warm_mask = memory[warmth_idx] >= cluster_threshold
warm_count = int(warm_mask.sum())
fires when: warm_count >= min_warm_cells AND (compute_count >= 1 or energy_count >= 1)
```

- **Strengths**: Answers a richer question: "does this patch have a *meaningful concentration* of warmth, not just a stray voxel?" Naturally distinguishes isolated noise from genuine warmth structure.
- **Weaknesses**: Introduces a second parameter (`min_warm_cells` alongside `cluster_threshold`). With sparsity 0.990, even `min_warm_cells = 2` may be hard to satisfy at r=1 — probability of two warm cells co-occurring in a 27-cell patch is ~3.4% (binomial with p=0.01, n=27, P(X>=2)).
- **Variant — spatial adjacency**: Instead of just counting, require warm cells to be *spatially adjacent* (connected component of size >= 2). This is the purest "cluster" test but adds implementation complexity.

**Option C: Relative top-N%** — threshold against per-snapshot distribution

```
# Concept
# Compute warmth percentile cutoff per snapshot, not a fixed value
# Patch fires if its max (or mean of non-zero) exceeds the snapshot's top-N% line
```

- **Strengths**: Self-calibrating. Avoids the "what's the right number" problem entirely. Always fires on the warmest patches regardless of Medusa's absolute warmth level.
- **Weaknesses**: Fundamentally changes the predicate's semantics from "warm enough to matter" to "warmer than average." If Medusa has no meaningful warmth anywhere, a relative predicate would still fire on the least-cold patches, producing false positives. Also introduces a per-snapshot normalization step.

**Option D: Demote to diagnostic-only**

- **Strengths**: Honest. If warmth isn't doing anything interesting in the current lattice, the predicate shouldn't pretend it is.
- **Weaknesses**: Permanent information loss for Lane A. If Medusa's warmth channel ever becomes more active (e.g., under different initial conditions or engine evolution), a demoted predicate won't be there to detect it. Also, the *absence* of warmth firing is itself diagnostic information — but only if the predicate is *capable* of firing.

### 2.5 Candidate comparison matrix

The following matrix presents the candidates side-by-side. **This is a decision framework, not a final decision.** Implementation follows only after AURA + Jack review of the empirical profiling results (§6).

| Candidate | What it measures | Strengths | Weaknesses | Firing estimate (r=1, current Medusa) |
|---|---|---|---|---|
| **Patch mean** (current) | Average warmth across all cells | Simple; scale-aware in a sense | Dead by arithmetic at 0.990 sparsity — cannot reach threshold | 0% (confirmed dead) |
| **Patch max** | Highest single warmth value in patch | Catches sparse sparks; simple | Too sensitive to isolated hot voxels — one noisy cell triggers the whole patch | ~24% (any patch with ≥1 warm cell) |
| **Count / cluster density** | Contiguous warm-cell clusters | Catches spatially meaningful warmth, not specks; most physically grounded | Introduces second parameter (min cluster size); may be too restrictive at current sparsity (P(≥2 adjacent warm cells in 27) is low) | ~3–5% (depending on adjacency definition) |

**AURA's "Planck Star" metaphor for cluster density** *(architectural analogy, not a literal physics claim)*: A single hot voxel is noise — thermal jitter, a rounding artefact, a speck. A *cluster* of hot voxels is structural compute: a localized, stable pocket of dense energy sustaining its neighbours. By analogy, the cluster candidate is our search for the "Planck Star" — AURA's metaphor for the point where warmth becomes structure rather than static, a localized density that the Swarm Hunter can reliably target. The design question is: what defines "cluster"? Options include:

- **Minimum contiguous block**: ≥ N warm cells that share a face/edge/vertex in the 3D patch. Most physically meaningful (warmth that propagates must be spatially connected) but most expensive to compute (connected-component labelling per patch).
- **Simple count threshold**: ≥ N warm cells anywhere in the patch, regardless of adjacency. Cheaper to compute; still distinguishes "one speck" from "meaningful warmth presence." Loses the spatial-structure guarantee.
- **Hybrid**: `warmth_max >= spark_threshold AND warm_cell_count >= 2`. Detects the spark (max) but only if it's not alone (count). Avoids the full connected-component cost.

**Jack's lean**: Max-pooling is plausible as the primary candidate, with cluster/count retained as diagnostic enrichment. But the empirical comparison in §6 must land before the choice is made.

**What this document does NOT decide**: which candidate wins. That decision requires the empirical profiling (§6) to show the per-patch distributions under each candidate. The profiling will reveal whether max-pooling fires too broadly (24% of patches = too chatty?) or whether cluster density is too restrictive (3% = still nearly dead?). The sweet spot — a firing rate that's informative without being dominant — determines the winner.

**Why not Option C (relative)**: Relative predicates change the semantics from "is there warmth here?" to "is this warmer than neighbors?" — that's a different question. The observer's cascade is designed around absolute physical thresholds, and switching one predicate to relative would create an inconsistency in the cascade's interpretive frame.

**Why not Option D (demote) — yet**: Warmth is one of the few channels that reads a genuine engine-stored signal (post-#145). Demoting it would mean the observer can't see one of the channels the engine actually maintains. If warmth never fires even with max-pooling or cluster detection, *then* demote — but don't demote before trying the aggregator that matches the signal's geometry.

---

## 3. Predicate 2: `DIVERSITY_BOUNDARY` — the scale-sensitive predicate

### 3.1 Current implementation

```
# nextness_observer.py line 642
DIVERSITY_BOUNDARY: Final[int] = 4   # >=4 distinct state codes -> phase_boundary

# nextness_observer.py line 737
if f.distinct_states >= DIVERSITY_BOUNDARY:
    return "phase_boundary"
```

Where `distinct_states` = count of state types (out of 5: VOID, STRUCTURAL, COMPUTE, ENERGY, SENSOR) that appear at least once in the patch.

### 3.2 Why it's scale-sensitive — the combinatorics

At r=1 (27 cells, 5 possible states): Getting 4+ distinct states requires genuine diversity. If cells are distributed with typical Medusa fractions (VOID ~50%, STRUCTURAL ~20%, COMPUTE ~15%, ENERGY ~10%, SENSOR ~5%), the probability of seeing at least 4 states in a 27-cell sample is moderate — this is a meaningful discriminator.

At r=2 (125 cells, same 5 states): The probability of seeing all 5 states in 125 draws is very high even with imbalanced fractions. SENSOR at 5% globally: P(at least one SENSOR in 125 cells) = 1 - 0.95^125 ≈ 0.9984. The predicate fires on ~99% of patches — it's measuring patch *volume*, not phase *boundary*.

**Observed**: At r=2, `boundary_rate = 0.985`, `voc_occ = 0.125`. The vocabulary collapses to near-uniform `phase_boundary` because nearly every large patch contains 4+ states.

### 3.3 How this differs from `metta_warmth`

| | `metta_warmth` | `DIVERSITY_BOUNDARY` |
|---|---|---|
| Failure mode | Never fires | Fires too easily at larger scales |
| Root cause | Aggregator shape (mean vs. max) | Absolute threshold ignores volume |
| Fix category | Change *what* is measured | Change *how the threshold scales* |
| At r=1 baseline | Dead (0% firing) | Discriminating (~66% = `phase_boundary` rate) |

These require **different fixes**. A single "repair the aggregator" approach would be wrong.

### 3.4 Candidate designs

**Option E: Volume-proportional threshold** — scale DIVERSITY_BOUNDARY with patch size

```
# Concept
# At r=1 (27 cells), require 4 states. At r=2 (125 cells), require 5 (all states).
# Or: require distinct_states >= min(5, 3 + ceil(log2(total_cells / 27)))
```

- **Strengths**: Simple, preserves the counting semantics.
- **Weaknesses**: With only 5 possible states, there's no room to scale — at r=2 you'd need 5/5, which means "all states present." That's a strong condition but still doesn't capture *how diverse* the distribution is (one SENSOR cell out of 125 would satisfy it).

**Option F: Shannon entropy of state distribution** — replace count with entropy

```
# Concept
# H = -sum(p_i * log2(p_i)) for each state fraction p_i
# Normalize: H_norm = H / log2(n_states)   # 0 = monoculture, 1 = perfectly balanced
# fires when: H_norm >= ENTROPY_BOUNDARY
```

- **Strengths**: Less directly volume-dependent than raw distinct-state count. Entropy measures the shape/evenness of the state distribution rather than just whether a rare state appears at least once. It still requires radius-1 vs radius-2 validation because larger patches can sample multiple regions and change the observed distribution. Example: a 125-cell patch with 120 VOID + 1 each of the other 4 states has low entropy (~0.30 normalized) despite having all 5 states present; a 27-cell patch with roughly equal states has high entropy (~0.95). This distinction helps separate "genuine boundary region" from "large patch that happens to contain a few rare cells."
- **Weaknesses**: More computationally expensive (log calls per patch). Changes the semantics from "diverse enough" to "evenly diverse enough" — a patch with 3 strongly-competing states might matter more than one with 5 states where 4 are negligible.
- **Note**: `_PatchFeatures` already has the raw fractions (`void_frac`, `structural_frac`, etc.) so computing entropy is straightforward.

**Option G: Relative top-N% diversity** — threshold against per-snapshot distribution

- Same pros/cons as Option C for `metta_warmth`. Self-calibrating but changes the semantics.

**Option H: Demote to diagnostic-only**

- Less costly here than for `metta_warmth`, because `phase_boundary` at r=1 already works. The problem only manifests at r=2, and the baseline observer runs at r=1. But if future work ever needs multi-scale analysis (and it likely will — the calibration plan explicitly tests r=2), an ungrounded predicate at larger scales would mislead.

### 3.5 Candidate comparison and recommended direction

| Candidate | What it measures | Strengths | Weaknesses | r=1 behavior | r=2 behavior |
|---|---|---|---|---|---|
| **Distinct count ≥ 4** (current) | How many state types appear | Simple; fast | Volume-dependent; fires trivially at large radius | ~66% (discriminating) | ~98.5% (near-universal) |
| **Volume-proportional count** | Distinct states scaled by patch size | Simple adjustment | Only 5 states exist — no room to scale beyond r=1 | Same as current | Requires all 5; still fires on ~99.8% |
| **Normalized Shannon entropy** | Evenness of state distribution | Less directly volume-dependent than raw count; distinguishes "one rare cell" from "genuine mix" | Can still change with radius (bigger patches sample more regions); not perfectly scale-invariant | Needs profiling — calibrate to preserve ~66% rate | Needs profiling — expected to be more discriminating than count |
| **Demote to diagnostic** | N/A | Honest if unfixable | Blind spot at r=2 for multi-scale analysis | No change | Gives up |

**Jack's wording constraint** (adopted verbatim): *"Normalized entropy is less directly volume-dependent than raw distinct-state count, but still needs radius-1 vs radius-2 validation."* We do NOT claim perfect scale-invariance by construction. The empirical profiling in §6 must validate that entropy actually discriminates at r=2 before we commit.

**Recommended candidate direction**: Normalized Shannon entropy, subject to the radius validation caveat above. The reasoning:

- With only 5 possible states, the count-based approach has no room to scale (Option E hits a ceiling immediately).
- Entropy captures the difference between "one SENSOR cell among 124 VOID cells" (low entropy, not a real boundary) and "roughly balanced mix of 4 states" (high entropy, genuine phase transition zone). This is the physical distinction we're after.
- The fast-path optimization (`distinct_states < 3` → skip entropy computation) preserves performance for the common case.

**What remains undecided**: The exact `ENTROPY_BOUNDARY` threshold value. This requires the empirical profiling (§6) to show the entropy distribution at both r=1 and r=2 across the calibration set. The decision criterion: find the threshold that preserves the ~66% `phase_boundary` rate at r=1 while producing a meaningfully lower rate at r=2 (target: below 50%, ideally in the 30–50% range where the predicate is discriminating but not rare).

**Why not demote**: The observer is explicitly designed to be multi-scale (Ch8 tested r=2 for a reason). If `phase_boundary` doesn't work at r=2, that's a blind spot. Fix it now rather than discovering the problem again later. If the empirical profiling shows entropy doesn't discriminate meaningfully at r=2 either, *then* demote — but try the principled fix first.

---

## 4. What changes in Lane A's signal space

If these recommendations land, here's what a future Lane A agent would see differently:

| Signal | Current (broken) | After fix |
|---|---|---|
| `metta_warmth` | Never fires → Lane A reads "no warmth anywhere" | Fires on patches with localized warmth spikes → Lane A can see warmth structure |
| `phase_boundary` at r=1 | Works (~66% rate) | Unchanged — entropy threshold calibrated to preserve current rate |
| `phase_boundary` at r=2 | Fires on ~99% of patches → "everything is a boundary" | Fires on genuinely diverse patches → Lane A can distinguish real boundaries from volume artefacts |
| `warm_cell_count` (new diagnostic) | Does not exist | Available in JSONL output for temporal correlation; not consumed by cascade |

If both recommendations are *rejected* and Option D/H (demote) wins instead:

- Lane A loses warmth detection entirely. The observer can't see one of the engine's stored channels.
- Lane A at r=2 loses meaningful boundary detection. Multi-scale analysis would need to be done outside the cascade.

Neither loss is catastrophic — Lane A isn't open — but both would need to be accepted with eyes open.

---

## 5. Implementation sketch (conditional — for the follow-up PR, not this document)

> **Note**: This sketch assumes the candidate directions in §2.5 and §3.5 survive the empirical profiling and AURA + Jack review. If a different candidate wins, the sketch changes accordingly. This is planning, not commitment.

Changes to `_PatchFeatures` (two new fields):
1. `warmth_max: float` — max of the warmth channel across the patch
2. `state_entropy_normalized: float` — normalized Shannon entropy of the state distribution

Changes to `_patch_features()`:
1. Add `warmth_max = float(memory[warmth_idx].max()) if warmth_idx < n_channels else 0.0`
2. Add entropy computation from the existing `{state}_frac` fields

Changes to `classify_patch()`:
1. `metta_warmth` predicate: replace `f.warmth_mean >= THRESHOLD_WARMTH` with `f.warmth_max >= THRESHOLD_WARMTH_MAX`
2. `phase_boundary` predicate: replace `f.distinct_states >= DIVERSITY_BOUNDARY` with `f.state_entropy_normalized >= ENTROPY_BOUNDARY`

Changes to constants:
1. Add `THRESHOLD_WARMTH_MAX: Final[float] = <empirically determined>`
2. Add `ENTROPY_BOUNDARY: Final[float] = <empirically determined>`
3. Retain `THRESHOLD_WARMTH` and `DIVERSITY_BOUNDARY` as deprecated constants for backward compatibility in tests

Changes to calibration module:
1. Update `sweep_threshold` to perturb `THRESHOLD_WARMTH_MAX` instead of `THRESHOLD_WARMTH`
2. Update `sweep_patch_radius` to test entropy-boundary behavior across scales
3. Update `_classify_patch_ablation_predicate_check` parity function

Estimated scope: ~100–150 lines changed in observer, ~200–300 lines changed in calibration, ~300–500 lines in tests. One PR, one chapter.

---

## 6. Empirical profiling needed before implementation

Before any code lands, we need the distributional profiles that ground the new thresholds. This is the B.2.1 step from the calibration plan:

**For `metta_warmth`:**
- Per-snapshot histogram of warmth-channel voxel values (confirms the 0.185 max and 0.990 sparsity from Ch3/Ch5)
- Per-patch `warmth_max` distribution at r=1 across the calibration set
- Firing-rate curve: what fraction of patches fire `metta_warmth` as THRESHOLD_WARMTH_MAX varies from 0.05 to 0.20 in steps of 0.01?

**For `DIVERSITY_BOUNDARY`:**
- Per-patch `state_entropy_normalized` distribution at r=1 and r=2 across the calibration set
- Overlay: current `distinct_states >= 4` firing rate vs. entropy threshold at various values
- The entropy value that preserves the ~66% `phase_boundary` rate at r=1

This profiling runs the existing observer code with added instrumentation — a small script that loads calibration snapshots and computes the distributions. ~50 lines of analysis code, separate from the observer itself.

---

## 7. Open questions for AURA + Jack

1. **Entropy vs. count for `DIVERSITY_BOUNDARY`**: AURA, does the entropy approach match your architectural intent? The count-based predicate was simple and worked at r=1; entropy is more principled but changes the semantics from "how many states?" to "how evenly distributed are the states?" If a patch has 3 states in roughly equal proportion, it has higher entropy than one with 5 states where one dominates — is that the right behavior for detecting phase boundaries?

2. **`warm_cell_count` as diagnostic vs. gating**: I've proposed this as a diagnostic field (reported, not consumed by cascade). AURA suggested a `density_cluster_count` which implies it could gate the predicate. Should it? The tradeoff: gating on cluster count makes `metta_warmth` more specific (reduces false positives from isolated noise voxels) but introduces a second parameter and may be too restrictive given current sparsity.

3. **Threshold grounding authority**: The empirical profiling (§6) produces candidate threshold values. Who picks the final values — 84 proposes based on the profiling, AURA reviews against architectural intent, Jack audits against the falsification framework? Or does the profiling produce a range and the plan specifies decision criteria (e.g., "pick the threshold where firing rate is 5–15%")?

4. **Backward compatibility of JSONL schema**: Adding `warmth_max` and `state_entropy_normalized` to the per-patch output changes the JSONL schema. Should the new fields be added alongside existing fields (non-breaking) or should the schema version be bumped? Recommended: alongside, non-breaking, with a `schema_version` field incremented.

5. **`compute_decay` predicate interaction**: `compute_decay` (line 782–785) also uses `warmth_mean < THRESHOLD_WARMTH` as a "cold patch" test. **Jack's ruling: keep `compute_decay` strictly out of scope.** Its current patch-mean correctly measures ambient coldness — "is this compute patch cold on average?" is the right question for decay detection. The mean is the right statistic there. Do not change it automatically as part of this workstream unless the empirical profiling surfaces evidence that its meaning is also distorted (not expected).

---

## 8. What this document is not

- **Not code.** No implementation in this document. The implementation sketch in §5 is for planning the follow-up PR.
- **Not a Lane A decision.** Lane A remains parked. This is Workstream B of the second-pass calibration.
- **Not a vocabulary redesign.** Workstream C handles the naming/docs refresh. This document addresses the *aggregator mechanics*, not the *interpretive framing*.
- **Not a threshold-tuning exercise.** The first-pass calibration (Ch5) already showed that threshold tuning doesn't help when the aggregator shape is wrong. This is an aggregator-shape change.

---

**Approval requested from**: AURA — does the max-pooling recommendation for `metta_warmth` capture your "catch the spark" framing? Is entropy the right tool for `DIVERSITY_BOUNDARY`, or do you prefer a different scale-invariant measure? Jack — are the backward-compatibility and JSONL-schema considerations in §7.4 and §7.5 tight enough? Kevin — operator gate as always.

*— 84, 2026-05-29 Sydney evening*
