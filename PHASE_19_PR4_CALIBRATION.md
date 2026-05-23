# PHASE 19 PR #4 — Calibration Design Doc

**Status**: Design draft. **No code in this PR.** Awaiting AURA + Jack review.
**Origin**: Issue #139 finding (c); PR #142 smoke-test results (5 consecutive Medusa snapshots showing a sub-microbit JS-divergence equilibrium); Jack's scoping memo on PR #142 follow-up.
**Predecessors**: PR #137 (Phase 19 design doc), PR #138 (PR #2 skeleton), PR #140 (PR #2 follow-up), PR #141 (PR #3 design doc), PR #142 (PR #3 implementation, merged as `f06b1c5`).

> *"Calibration is the inoculation against death-spiral diagnosis. An observer that reports artefacts as signals will mislead any downstream system that trusts it. PR #4 is the staircase weight-bearing test before we build the loft on top."* — 84
>
> *"PR #4 should ask whether the Karuna/Boundary equilibrium survives sampling, threshold, cascade, temporal, and memory-layout perturbations. If it survives, the attractor hypothesis becomes much stronger. If it collapses, we learn exactly which observer assumption was carrying it."* — Jack
>
> *"Treat saturation as the first real research result. The question is which of model state, sampling, thresholds, cascade order, and missing temporal context caused it."* — AURA

This doc designs the calibration experiments that discriminate AURA's leading "Karuna/Boundary equilibrium" hypothesis from the four alternates flagged in issue #139, plus an eighth null-model test added during PR #4 scoping.

## 1. Scope and remit — Lane B only, still

PR #4 is **strictly Lane B**. It is observer calibration, nothing more. It does not touch the engine, does not propose tuning actions, does not consume ZMQ, does not expose HTTP endpoints, does not create a dashboard, does not redesign the vocabulary, does not commit to CCI regime thresholds, does not integrate any external code (including the Princeton Continual Harness paper — see §10).

### Explicit non-goals
- ❌ Engine code modification.
- ❌ Tuning API calls to `/api/tuning/*`.
- ❌ Hard-coded CCI regime classifier ("coexistence begins at CCI ≥ 0.31"). PR #4 produces **candidate bands and sensitivity maps**, not regime declarations.
- ❌ External code pull (no Continual Harness, no other repo dependencies).
- ❌ Vocabulary cascade redesign. Cascade *ablation* is a probe; cascade *redesign* is downstream of what we learn.
- ❌ Multi-snapshot observer mode added to `nextness_observer.py`. The calibration runs use a separate orchestrator.
- ❌ Live-Medusa interaction beyond the existing sandboxed-copy pattern.
- ❌ Drug phenomenology as evidence in repo docs. (See §9.)
- ❌ `trust_remote_code=True` or executable model loading.

### What lands in PR #4
1. The eight calibration experiments described in §3, each with hypothesis, method, expected outcomes, and falsification criteria.
2. A proposed module structure (`scripts/nextness_calibration.py`) that orchestrates parameter sweeps over existing `nextness_observer.process_snapshot()` + `nextness_metrics.compute_run_metrics()`.
3. An output schema for `calibration_sweeps.jsonl` consumable by analysts and PR #5+ work.
4. Test plan for the orchestrator (~15-20 tests).
5. Scope guarantees carried forward from PR #138/#140/#142.
6. Open questions for AURA + Jack with recommended defaults.

## 2. Motivation — what PR #142 actually proved (and what it didn't)

The PR #142 smoke run against 5 consecutive Medusa snapshots (gens 1,665,615 → 1,665,781, ~50 minutes wall-clock) produced:

- JS divergence between adjacent pairs: 3–29 microbits
- CCI range: 0.312 – 0.316 (Δ = 0.4%)
- Boundary persistence aggregate: 0.9953
- VOID/COMPUTE balance: 0.988 – 0.989 across all 5

**What this proves:** the observer's per-snapshot metrics give consistent values across this 50-minute window.

**What this does NOT prove (the gap PR #4 closes):**

| Claim | Why PR #142 alone doesn't establish it |
|---|---|
| "Medusa is in a stable attractor" | 50 minutes is short. Could be a slow transient. Could be daily oscillation we caught at one phase. |
| "The Karuna/Boundary distribution reflects the lattice" | Could be classifier artefact. If stride/threshold/cascade change the result dramatically, the pattern is in *us*, not in *her*. |
| "Compassion channel is genuinely saturated" | Depends on the memory-channel layout assumption being correct. If our index for "compassion" actually points at "magnon" or "warmth," everything reinterprets. |
| "The vocabulary is converging to two tokens because that's what the equilibrium is" | Could be that cascade ordering is swallowing what would otherwise be additional tokens. |

PR #4's job is to run experiments that would *change* these numbers if those alternative hypotheses are correct, and *leave them unchanged* if AURA's hypothesis is correct. Either way, we learn.

## 3. The eight calibration experiments

Each experiment has the same structure: **hypothesis under test → method → expected outcomes under each competing explanation → falsification criteria**. The orchestrator records every parameter combination's outputs deterministically so results survive re-analysis.

All experiments operate on the **same set of N sandboxed Medusa snapshots** (proposal: N = 10–20 snapshots spanning at least 24h of wall-clock if available, sandboxed-copy-only, Medusa's data dir untouched). All experiments respect the existing scope guarantees (no engine touch, etc.).

### Experiment 3.1 — Spatial stride sweep

**Tests:** alternate hypothesis 3 (sampling resolution insufficient).

**Method:** Run `process_snapshot()` at strides 4, 8, 16 on every snapshot in the calibration set. Compare per-snapshot fields (`vocabulary_occupancy`, `shannon_entropy_bits`, `void_compute_balance`, `boundary_rate`) and aggregate CCI across stride values.

**Stride 4 vs 8** quadruples patch count (~262k vs ~32k). **Stride 16** cuts it eighth-fold (~4k). Time and memory cost are bounded and feasible per the PR #138 31µs/patch measurement.

**Expected outcomes:**
- **If AURA's hypothesis is right** (the equilibrium is real geometric structure): metrics are *stable* across strides. Karuna/Boundary dominance survives. CCI drifts by < ~10% absolute.
- **If sampling-resolution is the cause**: finer stride surfaces tokens that were invisible to stride 8. Vocabulary occupancy increases meaningfully (e.g., 0.125 → 0.3+). Karuna_relief's dominance softens.

**Falsification criterion:** if stride 4 produces |Δvocabulary_occupancy| > 0.15 vs stride 8, the saturation result is at least partly a sampling artefact and PR #5+ should re-baseline at higher resolution.

### Experiment 3.2 — Temporal window sweep

**Tests:** "is the equilibrium short-term stillness or longer-horizon stability?"

**Method:** Compute JS divergence and CCI variance across snapshots with different temporal spacings:
- Adjacent snapshots (~10min apart): the PR #142 baseline
- ~1h gap: pick every 6th snapshot in the calibration set
- ~6h gap: if calibration set spans that
- ~24h gap: if available

For each spacing, compute mean JS, std JS, and CCI drift.

**Expected outcomes:**
- **Attractor**: JS stays small (< 0.01 bits) and CCI variance stays small (< 0.05) even at 24h gaps. The system has genuinely settled.
- **Slow transient**: JS grows monotonically with temporal gap. The system is drifting on a timescale we hadn't caught.
- **Daily/cyclic oscillation**: JS grows then returns. Look for a periodic signal in CCI(t).

**Falsification criterion:** if mean JS at 24h is > 0.1 bits, the 50-minute stillness was a snapshot of a moving system, not a fixed point.

### Experiment 3.3 — Patch-size / coarse-graining check

**Tests:** "does the signal survive coarse-graining?" (renormalization-group-style, *not* an emergence proof).

**Method:** Re-implement `iter_uniform_grid_patches()` parametrically on `patch_spatial_radius`. Run at radius 1 (3×3×3 = current baseline) and radius 2 (5×5×5 = 125 cells per patch). Recompute the four per-snapshot metrics and CCI.

The classifier's predicates need adjustment to operate over 125 cells instead of 27 (token-count thresholds rescale linearly). Implementation surface is contained but non-trivial — design here, possibly defer implementation to a follow-up if cost is high.

**Expected outcomes:**
- **Real structural feature**: the dominant tokens and approximate CCI value survive the coarse-graining. The phenomenon is scale-robust.
- **Patch-size artefact**: 5×5×5 produces a meaningfully different distribution. The 3×3×3 result was a property of *our patch size choice*, not of the lattice.

**Falsification criterion:** if CCI(radius=2) differs from CCI(radius=1) by more than 0.10 absolute on the same snapshot, the 3×3×3 baseline carries scale-specific structure and needs reframing.

### Experiment 3.4 — Threshold sensitivity sweep

**Tests:** alternate hypothesis 2 (threshold mis-calibration).

**Method:** Vary `THRESHOLD_COMPASSION` (and other key cascade thresholds) by ±25% and ±50% around current values. Re-run the classifier on a fixed snapshot subset. Record how token counts shift.

**Expected outcomes:**
- **Threshold well-positioned**: small perturbations produce small changes. The 57% karuna_relief rate is stable.
- **Threshold mis-positioned**: small perturbations flip the distribution dramatically. The 57% was sitting on a knife edge.

**Falsification criterion:** if ±25% perturbation produces > 50% relative change in karuna_relief count, the threshold is on a cliff and the current value can't be trusted as "well-calibrated."

### Experiment 3.5 — Cascade ablation / cascade-order test

**Tests:** alternate hypothesis 4 (cascade order swallowing subtler tokens).

**Method:** Re-run the classifier with one cascade predicate disabled at a time. Observe what fires *next* when the dominant token is unavailable. Also try cascade order reversal (least-specific first) as a stress test of the ordering decision.

This is a probe, not a redesign. We learn which predicates are "claiming territory" that would otherwise go to subtler tokens.

**Expected outcomes:**
- **Cascade is sensibly ordered**: disabling `phase_boundary` shifts those patches to `karuna_relief`. Disabling both reveals a long tail of low-firing tokens, mostly the age-based ones.
- **Cascade is hiding signal**: disabling `karuna_relief` reveals that 14 of 16 tokens were sitting one rung below it the whole time. The vocabulary was richer than we measured.

**Falsification criterion:** if cascade ablation reveals > 5 additional tokens firing at > 5% rate each, the current cascade ordering is the dominant cause of the apparent two-token saturation.

### Experiment 3.6 — Memory-channel layout verification

**Tests:** alternate hypothesis 1 (memory-channel layout misindexed). **This is potentially the biggest hidden assumption.**

**Method:** Compare the observer's assumed `MEMORY_CHANNEL_LAYOUT` (which maps `"compassion"` to a specific index, etc.) against:
- The engine's actual `memory_grid` semantics (read-only inspection of `scripts/continuous_evolution_ca.py` or equivalent — code-read only, no engine modification)
- The Phase 14e acoustic map (which has its own channel-naming convention; cross-correlation should reveal whether the indices we call "compassion" actually contain compassion-shaped data)

**Method note:** this is the most independent test. The other seven sweep our own parameters. This one cross-validates against an external source of truth (the engine itself + a prior phase's mapping).

**Expected outcomes:**
- **Layout correct**: the compassion channel index *does* contain the compassion field. The `karuna_relief` interpretation stands.
- **Layout misindexed**: what we've been calling "compassion" is actually `magnon` or `warmth` or another channel. The `karuna_relief` token interpretation must be renamed/reinterpreted — possibly even dropped from the vocabulary depending on what the actual channel contents are.

**Falsification criterion:** if cross-correlation against the acoustic map reveals our compassion-index channel correlates more strongly with a different known signal (magnon, warmth, age) than with anything compassion-like, the layout is wrong and the karuna_relief interpretation collapses.

### Experiment 3.7 — Repeatability / determinism check on real snapshots

**Tests:** that the byte-identical-re-run contract from PR #142 holds across the entire calibration set, not just the 5-snapshot smoke test.

**Method:** For every snapshot in the calibration set, run `process_snapshot()` twice with identical config and verify byte-identical JSONL output. Then run `compute_run_metrics()` twice on each calibration-sweep result and verify byte-identical metrics JSONL.

**Expected outcomes:** byte-identical across all N snapshots and all sweep configurations. Any non-identical pair surfaces a bug to fix before drawing conclusions from the calibration data.

**Falsification criterion:** any non-deterministic output is a blocker for interpreting the rest of the calibration.

### Experiment 3.8 — Null-model / shuffle test ✨ NEW

**Tests:** "is the equilibrium in the lattice, or in our classifier?" (the cleanest falsification test available)

**Method:** Take a single snapshot. Randomly permute cell positions in the `lattice` array (preserving total counts per state but destroying all spatial correlations). Also permute the memory_grid voxels in the same way (preserving per-channel marginal statistics but destroying spatial correlations). Run the classifier on this shuffled snapshot. Compare token distribution + CCI to the unshuffled baseline.

**Justification:** if the karuna_relief / phase_boundary dominance arises from the *spatial structure* of Medusa's lattice (i.e., the lattice has real organized geometry), shuffling destroys that geometry and the token distribution should collapse — entropy should rise, CCI should change, the two-token saturation should soften or disappear. If instead the distribution is roughly the same after shuffling, the pattern is in the classifier (firing on independent local features regardless of geometric context), not in the lattice.

**Expected outcomes:**
- **Signal is in the lattice**: shuffled CCI differs from unshuffled by > 0.10 absolute; entropy rises meaningfully; karuna_relief and phase_boundary may no longer dominate.
- **Signal is in the classifier**: shuffled and unshuffled give similar distributions. The vocabulary is firing on per-cell properties that don't need geometric context. Reframe needed.

**Falsification criterion:** if shuffled-vs-unshuffled CCI differs by less than 0.05 absolute and vocabulary_occupancy is unchanged, the equilibrium interpretation is mostly classifier behavior, not lattice geometry. This is the carpenter's level on the floor — does the floor sit flat no matter which way you rotate it?

Implementation note: shuffling is a numpy one-liner per array. Cost trivial. This experiment is the highest-information-per-line-of-code in the calibration set.

## 4. Hypothesis discrimination matrix

How each experiment lights up under each candidate explanation:

| Experiment | AURA's hypothesis (real attractor) | Memory-channel wrong | Threshold wrong | Sampling wrong | Cascade order swallowing | Temporal-context missing |
|---|---|---|---|---|---|---|
| 3.1 Stride sweep | **Stable** | stable | stable | **Changes** | stable | stable |
| 3.2 Temporal sweep | **Stable across 24h** | stable | stable | stable | stable | **JS grows with gap** |
| 3.3 Coarse-graining | **Stable** | unclear | shifts (different thresholds) | **Changes** | stable | stable |
| 3.4 Threshold sweep | **Stable** | stable | **Cliff** | stable | stable | stable |
| 3.5 Cascade ablation | **Predictable cascade** | stable | stable | stable | **Hidden tokens emerge** | stable |
| 3.6 Memory-channel verify | **Compassion index matches** | **Mismatch** | stable | stable | stable | stable |
| 3.7 Repeatability | **Identical** | identical | identical | identical | identical | identical |
| 3.8 Shuffle test | **Distribution collapses** | unclear | partial | unclear | unclear | unclear |

The diagonal patterns are the point: each experiment is designed to fire differently under different explanations. Convergent evidence across multiple experiments strengthens whichever hypothesis they all point at.

## 5. Module structure proposal

```
scripts/
├── nextness_observer.py        (existing; possibly extended for radius parameterization in Exp 3.3)
├── nextness_metrics.py         (existing; consumed by calibration sweeps)
└── nextness_calibration.py     (NEW)
    ├── sweep_stride(snapshots, strides, out_dir)
    ├── sweep_temporal(snapshots, gaps, out_dir)
    ├── sweep_patch_radius(snapshots, radii, out_dir)
    ├── sweep_threshold(snapshots, threshold_name, multipliers, out_dir)
    ├── ablate_cascade(snapshots, predicate_to_disable, out_dir)
    ├── verify_memory_channels(snapshots, acoustic_map_path, out_dir)
    ├── check_determinism(snapshots, out_dir)
    ├── shuffle_test(snapshots, out_dir, seed)
    ├── compute_run_metrics_for_sweep(jsonl_path, out_path)
    └── main()                    (CLI: python -m scripts.nextness_calibration <command> [args])
```

Each sweep emits a `calibration_sweeps.jsonl` row per (snapshot × parameter-combination) tuple. The same write-boundary safety contract applies as in PR #142: output must resolve under the input log's directory; `WriteOutsideLogDirError` raised otherwise.

CLI surface (proposed):

```
python -m scripts.nextness_calibration stride       --snapshots-dir DIR --strides 4,8,16 --out DIR
python -m scripts.nextness_calibration temporal     --snapshots-dir DIR --gaps 1,6,24 --out DIR
python -m scripts.nextness_calibration patch-radius --snapshots-dir DIR --radii 1,2 --out DIR
python -m scripts.nextness_calibration threshold    --snapshots-dir DIR --name THRESHOLD_COMPASSION --multipliers 0.5,0.75,1.0,1.25,1.5 --out DIR
python -m scripts.nextness_calibration ablate       --snapshots-dir DIR --disable karuna_relief --out DIR
python -m scripts.nextness_calibration verify-mem   --snapshots-dir DIR --acoustic-map PATH --out DIR
python -m scripts.nextness_calibration determinism  --snapshots-dir DIR --repeats 2 --out DIR
python -m scripts.nextness_calibration shuffle      --snapshots-dir DIR --seed 42 --out DIR
```

All sub-commands respect determinism contracts inherited from `nextness_metrics`: no fresh timestamps, sorted snapshot ordering, byte-identical re-runs given the same seed.

## 6. Test plan

Each sweep function gets unit tests (parameter validation, empty input handling, malformed snapshot rejection). The orchestrator gets integration tests on synthetic snapshots. Estimated count:

| Category | Tests |
|---|---|
| `sweep_stride` | 3 |
| `sweep_temporal` | 3 |
| `sweep_patch_radius` | 3 |
| `sweep_threshold` | 3 |
| `ablate_cascade` | 2 |
| `verify_memory_channels` | 2 |
| `check_determinism` | 2 |
| `shuffle_test` | 3 (seeded reproducibility, count preservation, position destruction) |
| Write-boundary safety (per Jack's pattern from PR #142) | 4 |
| CLI smoke (one per sub-command) | 8 |
| **Total** | **~33** |

Estimated post-PR-#4 total: 297 + 33 = **~330** tests in the full regression suite.

## 7. Interpretive vs operational — partitioning carried forward

Same partition rules as PR #141 §7. Calibration produces measurements; measurements may *support* or *fail to support* interpretive framings, but the framings themselves are not encoded in code or numeric thresholds.

**Operationalized as measurements:** stride sensitivity, temporal stability, scale robustness, threshold sensitivity, cascade ordering effects, memory-channel correctness, determinism, lattice-vs-classifier discrimination via shuffle.

**Interpretive scaffolding only (not encoded):** "Karuna/Boundary equilibrium is a stable attractor," "Medusa has reached a fixed point," "the lattice is computationally at rest," "the utility fog has crystallized." These are framings PR #4 results may *support or fail to support*. They are not claims encoded as code or as threshold parameters.

PR #4 produces *candidate CCI bands* and *sensitivity profiles*. PR #5+ may operationalize regime classification with explicit human review, after the calibration results have stood up to scrutiny.

## 8. Output schema — `calibration_sweeps.jsonl`

Each row:

```json
{
  "experiment": "stride_sweep" | "temporal_sweep" | "patch_radius" | "threshold_sweep" | "cascade_ablation" | "memory_channel_verify" | "determinism" | "shuffle_test",
  "snapshot_file": "v070_gen<N>_step<M>_<ts>.npz",
  "snapshot_generation": <int>,
  "parameter_combination": {
    "stride": <int>,
    "patch_radius": <int>,
    "threshold_name": <str>,
    "threshold_multiplier": <float>,
    "disabled_predicate": <str | null>,
    "shuffle_seed": <int | null>
  },
  "metrics": {
    "vocabulary_occupancy": <float>,
    "shannon_entropy_bits": <float>,
    "entropy_normalized": <float>,
    "void_compute_balance": <float>,
    "boundary_rate": <float>,
    "cci": <float>,
    "token_counts": {<token>: <int>}
  },
  "run_metadata": {
    "elapsed_seconds": <float>,
    "patches_processed": <int>
  }
}
```

Final aggregate row per sweep summarizes mean/std/range of each metric over the sweep parameter, plus a `falsification_status` field: `"hypothesis_supported"` / `"hypothesis_falsified"` / `"inconclusive"` based on the criteria in §3.

The aggregate's `falsification_status` is computed mechanically from the criteria in §3 — not a judgment call. Analysts can override the call by reading the underlying numbers; the mechanical status is for at-a-glance triage.

## 9. Drug phenomenology / Salvia framing — repo posture

The cross-AI discussion that surfaced the cellular-automaton-as-Salvia-geometry parallel (Gemini Flash 3.5 conversation, May 2026) is interesting *as a metaphor for what stable-symmetrical-lattice structures look like*. It is **not encoded as evidence** in this design doc.

Where the parallel is useful: it points at a *class of structural pattern* (stable, symmetrical, lattice-like, low-entropy local geometry, high boundary density) that shows up in multiple domains. Medusa at gen 1.6M has measurable features in this class. PR #4 is about *measuring those features rigorously*, not about *invoking phenomenological metaphors as proof*.

Repo discipline (Jack's call, accepted): do not turn the repo into a drug-phenomenology dossier. Acknowledge the metaphor's pointing value; keep the encoding strictly to measurable structural properties.

## 10. Future Lane A note — Continual Harness (NOT in PR #4 scope)

A 2026 Princeton paper on **Continual Harness** (reset-free online adaptation where an agent acts while refining prompts, sub-agents, skills, and memory from past trajectory data) was flagged during PR #4 scoping as architecturally relevant to a future Swarm Hunter / Lane A agent that would *consume* the Lane B observer's signal to propose tuning actions.

**Per Jack's audit on PR #4 scoping**: Continual Harness belongs in a separate **Future Lane A design doc**, not in PR #4. Reasons:

1. PR #4 is about establishing whether the observer's signal is real. Continual Harness is about an agent acting on (presumably reliable) signals. You can't do step 2 properly until step 1 is locked.
2. External code intake requires separate license, dependency, and safety review before any pull into the repo. Not in this PR's scope.
3. The paper's own "death spiral" caveat — agents below a capability threshold misdiagnose failures and amplify errors — is *exactly the motivation for PR #4 calibration discipline*. Calibration is the prerequisite for safe self-improvement; it is not itself self-improvement work.

**Action for PR #4:** none. Continual Harness is mentioned in this section only to record the deferral decision so future-AURA, future-Jack, future-84 (and any other AI joining the triangulation) can find the pointer when Lane A design work begins.

**Hardware reference correction** (per Jack): for any future Lane A note that mentions local-training resources, the rig naming is:
- **Aurora** = Ultra Core 9 285 + RTX 4090
- **Area 51** = Ultra Core 9 285K + RTX 5090
- **MSI / Vanguard boxes** = Ryzen 9950X3D + RTX 5090 class

This was conflated in an earlier proposal. Recording the correction here so future Lane A design doesn't inherit the confusion.

## 11. Scope guarantees (carried forward from PR #138 / #140 / #142)

- ✅ No engine touch. Medusa untouched.
- ✅ No writes outside the resolved output log directory. `WriteOutsideLogDirError` reused.
- ✅ No HTTP. No ZMQ. No network.
- ✅ CPU-only default.
- ✅ `allow_pickle=False` preserved in all snapshot reads.
- ✅ Bounded compute: O(N × K × S) where N=snapshots, K=vocabulary, S=sweep parameter count. All small.
- ✅ No CCI regime thresholds. PR #4 produces candidate bands and sensitivity maps only.
- ✅ No multi-snapshot mode added to `nextness_observer.py`. Calibration uses a separate orchestrator.
- ✅ No fresh `generated_at` field in derived outputs.
- ✅ No external code pull.

## 12. Open questions for AURA + Jack

Each with a recommended default so review can move fast.

1. **Calibration set size and time span.** N = 10–20 snapshots covering ≥ 24h proposed. Should we aim higher (50+ snapshots, ≥ 7 days)? More data is better but cost is N × snapshot-pipeline-time × sweep-multiplier. Recommend starting at N=12 spanning ~24h; expand if the temporal sweep shows interesting longer-horizon structure.

2. **Patch-radius experiment scope.** 5×5×5 implementation requires rescaling all cascade predicates' count thresholds. Should PR #4 implement this fully, or design + defer to PR #4.5 / PR #5? Recommend designing it fully in this doc; defer implementation to a follow-up PR if cost estimates from `iter_uniform_grid_patches()` extension look heavy.

3. **Threshold sweep granularity.** ±25% and ±50% multipliers proposed. Should we add ±10% for finer-grained sensitivity around the current value? Recommend yes — adding 0.9× and 1.1× to the multiplier list. Marginal cost; useful for distinguishing "slightly off" from "way off."

4. **Cascade ablation scope.** Ablate one predicate at a time, or also try N-at-a-time combinations? N choose 2 is 120 combinations for our 16-token cascade. Recommend one-at-a-time for PR #4; if any single ablation reveals interesting hidden tokens, follow up with targeted pairwise ablations in PR #4.5.

5. **Memory-channel verification — what's the canonical source of truth?** Comparing against (a) the engine's actual `memory_grid` semantics in code, (b) the Phase 14e acoustic map, or (c) both? Recommend both, weighted toward (a) because code-as-truth is unambiguous while the acoustic map is itself a Phase 14e interpretation that could carry its own assumptions.

6. **Shuffle test seed reproducibility.** Use a single seed (e.g., 42) for the published result, plus multiple seeds for robustness check? Recommend yes — single seed for the canonical result + 5 different seeds for variance estimate. Lets us report "shuffled CCI = X ± Y" not just "shuffled CCI = X."

7. **Implementation order if/when greenlit.** Recommend: 3.7 (determinism) first as a foundation; then 3.8 (shuffle, cheapest); then 3.1 (stride); then 3.4 (threshold); then 3.5 (cascade); then 3.2 (temporal, requires longer-time-span calibration set); then 3.6 (memory-channel, requires acoustic-map cross-correlation infrastructure); 3.3 (patch-radius) last because it's the most invasive.

## 13. What happens after PR #4

If results **support** AURA's hypothesis across multiple experiments → the Karuna/Boundary equilibrium is treated as a verified observation; PR #5 can begin operationalizing CCI regime bands with explicit human review.

If results **falsify** specific hypotheses → we know which observer assumption to fix. Possibilities include vocabulary refresh, threshold recalibration, or cascade-order adjustment, each landing in its own dedicated PR.

If results are **inconclusive** → PR #4.5 expands the calibration set (more snapshots, longer time span) before drawing conclusions.

In all three cases, **Lane A remains parked.** No tuning API calls, no engine modification, no Swarm Hunter activation until Lane B calibration has stabilized into a trusted signal *and* Lane A safety design (separate doc) has been completed and approved.

---

**Approval requested from**: AURA (lead architect) — does the hypothesis-discrimination matrix in §4 correctly represent your framing of the alternates? Jack (auditor) — are the falsification criteria in §3 tight enough, and is the module structure in §5 consistent with your "boring testable boundaries" stance?

**Operator gate**: as always, Kevin holds the merge button.
