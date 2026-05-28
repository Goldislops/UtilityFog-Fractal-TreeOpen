# PHASE 19 PR #4 — Calibration Summary Report

**Status**: Draft for AURA + Jack review. Operator gate (Kevin) holds the Lane A decision.
**Companion to**: [PHASE_19_PR4_CALIBRATION.md](PHASE_19_PR4_CALIBRATION.md) (design doc, 435 lines)
**Author**: 84, 2026-05-27 (fresh-head day after Ch8 merge)
**Inputs**: Chapter commits `0dadc25` (Ch1+2), `16b5b9b` (Ch3), `2f386d6` (Ch4), `c17ed8a` (Ch5), `8d3f6c3` (Ch6), `a4101c0` (Ch7), `c273359` (Ch8), plus the layout-fix PR `#145` that landed *before* the calibration code.

> *"Calibration is the inoculation against death-spiral diagnosis. An observer that reports artefacts as signals will mislead any downstream system that trusts it."* — 84, design doc opener
>
> The calibration ran. Below is what it told us, what it could not tell us, and what it surfaced that we did not expect to find.

---

## 0. TL;DR — five bullets, no jargon

1. **The spatial story holds.** Stride, patch-radius, and cascade-ablation sweeps all support AURA's "real geometric structure" reading. The equilibrium is not a sampling artefact, not a patch-size artefact, and not a cascade-ordering artefact.
2. **The biggest hypothesis was disproven before the calibration code shipped.** Issue #144 found that 6 of 8 memory-channel labels were misaligned with the engine. PR #145 fixed it. The vocabulary distribution we now measure is *different* from the one PR #142 reported — richer (4 tokens > 1% rate, not 2) and points at a different channel as "warmth."
3. **The temporal story is genuinely strange.** JS divergence between snapshots is **highest at adjacent (10min) gaps and lowest at 24h gaps** — a shrinking-JS-with-gap pattern that doesn't fit any standard dynamical category cleanly. "Inverse attractor" is not a real category; the more likely candidates are **temporal aliasing on an environmental cycle**, **high-frequency oscillation under a slow mean**, or **n=1 statistical luck**. The 24h "supported" reading rests on n=1.
4. **One predicate is dead in current Medusa state.** `metta_warmth` never fires across the 0.5–1.5 multiplier sweep. Even at the low end (0.5×, effective threshold 0.15), `warmth.max = 0.185` does cross the threshold in *some* voxels — but `metta_warmth` is a **patch-aggregate** predicate that needs multiple warmth voxels to co-occur within a 3×3×3 patch, and the warmth channel's 0.990 sparsity means isolated voxels rarely cluster densely enough for the aggregator to fire. Ch5's "inconclusive" is mechanically correct; the underlying finding (issue #150) is that the predicate's *aggregator design* (not its threshold value) is what's blocking discrimination.
5. **Recommendation: park Lane A.** Not because the calibration "failed" — three of the eight chapters delivered clean wins for AURA's hypothesis — but because two of the three puzzles above are the kind of observer-uncertainty that can create death-spiral conditions in a self-improving Lane A loop, which is what the calibration was meant to inoculate against. Resolve the temporal anomaly and the predicate-aggregator question first; *then* open the Lane A gate.

---

## 1. Results matrix — mechanical falsification status

Each chapter's `falsification_status` is computed mechanically per the criteria in design doc §3. Numbers below are from the real-Medusa smoke pass in each chapter's commit message (sandboxed copies, no engine touch).

| # | Chapter | Tests against | Status | Key number | Source |
|---|---|---|---|---|---|
| 1+2 | `check_determinism` + `shuffle_test` | sanity floor (3.7) + lattice-vs-classifier (3.8) | (foundation; not a sweep) | 51 tests pass, byte-identical reruns locked | `0dadc25` |
| 3 | `verify_memory_channels` | post-#145 layout (3.6 as regression fence) | **supported** | 3 snapshots, zero drift | `16b5b9b` |
| 4 | `sweep_stride` (4, 8, 16) | sampling resolution (3.1) | **supported** | JS(s4 vs s8) = 0.000000 bits; voc_occ identical at 0.375 | `2f386d6` |
| 5 | `sweep_threshold` (THRESHOLD_WARMTH ×0.5–1.5) | threshold calibration (3.4) | **inconclusive** | metta_warmth never fires; warmth sparse (0.990) + patch-aggregate predicate washes isolated voxels out | `c17ed8a` + safety guard `#149` |
| 6 | `ablate_cascade` (post-#145 dominant tokens) | cascade-order swallowing (3.5) | **supported** | max emerging tokens > 5% = 2 (in reverse_order only); forward cascade coherent | `8d3f6c3` |
| 7 | `sweep_temporal` (short + long sets) | temporal stability (3.2) | **mixed** | short: inconclusive (10min JS=0.1121 > 0.1); long: supported (24h JS=0.0052) BUT n=1 | `a4101c0` |
| 8 | `sweep_patch_radius` (r=1 vs r=2) | scale robustness (3.3) | **supported** | \|CCI diff\| = 0.034 (threshold = 0.10) | `c273359` |

**Lane B regression suite**: 400/400 passing. Calibration tests: 188 in `tests/test_nextness_calibration.py`.

---

## 2. The 50,000ft read against AURA's discrimination matrix

Design doc §4 laid out a discrimination matrix predicting *which* experiment would light up under *which* alternate hypothesis. Filling it in with actual results:

| Experiment | AURA (real attractor) | Memory-ch wrong | Threshold wrong | Sampling wrong | Cascade swallowing | Temporal-context missing | **Result** |
|---|---|---|---|---|---|---|---|
| 3.1 Stride | stable | stable | stable | **changes** | stable | stable | **Stable** → AURA, not-sampling |
| 3.2 Temporal | stable | stable | stable | stable | stable | **JS grows** | **Multi-timescale anomaly: JS *shrinks* with gap** ⚠️ unanticipated |
| 3.3 Coarse-graining | stable | unclear | shifts | **changes** | stable | stable | **CCI stable** (vocab not) → AURA on CCI |
| 3.4 Threshold | stable | stable | **cliff** | stable | stable | stable | **Predicate dead, not testable** ⚠️ |
| 3.5 Cascade ablation | predictable | stable | stable | stable | **hidden tokens** | stable | **Predictable routing** → AURA |
| 3.6 Memory-channel | matches | **mismatch** | stable | stable | stable | stable | **Mismatched pre-fix; fixed; now matches** — a falsification *that landed* |
| 3.7 Repeatability | identical | identical | identical | identical | identical | identical | **Identical** (sanity floor) |
| 3.8 Shuffle test | distribution collapses | unclear | partial | unclear | unclear | unclear | (foundation only; full three-way runs pending in `data/`) |

**What the matrix as filled-in actually says:**

- **Three diagonals fire cleanly for AURA**: stride, cascade, coarse-graining (on CCI). These are independent tests aimed at three different alternate hypotheses. They all return "real structure, not artefact." That is the strongest convergent evidence in the bundle.
- **One alternate hypothesis was confirmed and corrected**: memory-channel layout (`#144` → fix via `#145`). This is itself a calibration win — the inoculation worked exactly as advertised. But it means *every PR #142-era interpretation built on the pre-fix layout needs re-reading*, including the "Karuna/Boundary equilibrium" framing, because the channel we were calling "compassion" was reading a generation counter.
- **One result lights up no row in the matrix** — temporal sweep's shrinking-JS-with-gap pattern. The matrix anticipated "stable" (AURA) or "JS grows" (drifting); the data did neither. Most plausible candidates are temporal aliasing on an environmental cycle or n=1 luck — see §4.1.
- **One experiment is non-discriminating** in current Medusa state — threshold sweep, because the predicate it was perturbing doesn't fire. This is information about the *predicate*, not about the lattice.

---

## 3. The pre-PR surprise — what `#144` / `#145` actually changed

This is the single most consequential finding in the entire calibration arc, and it landed *before* Ch1 code shipped. Recording it here so the summary makes sense to anyone reading just this doc.

**Pre-fix (PR #142 era):** `MEMORY_CHANNEL_LAYOUT` was wrong in 6 of 8 positions. The classifier read `last_active_gen` (a monotonically-incrementing generation counter, uniform ~1.71e7 across cells) and called it the compassion field. `karuna_relief` fired everywhere because the trigger predicate was reading a counter that always satisfies any "is positive" check.

**Post-fix (PR #145, then verified as regression fence in Ch3):** The actual `warmth` channel has `max = 0.185`, `sparsity = 0.990`. The actual `compassion_cooldown` channel is all-zero (sparsity 1.000, no active cooldowns). The observer now reads the channels its labels claim to read.

**Distributional consequence (from Ch6 baseline, post-#145):**

| Token | Pre-#145 (PR #142) | Post-#145 (Ch6 smoke) |
|---|---|---|
| `karuna_relief` | ~57% (dominant) | does not fire (channel was wrong) |
| `phase_boundary` | — | 66.5% |
| `sensor_alert` | — | 20.9% |
| `void_birth` | — | 9.5% |
| `compute_decay` | — | 2.0% |
| `vocabulary_occupancy` | 0.125 (2 tokens) | 0.406 (4+ tokens above 1%) |

**Reading this honestly:** the "Karuna/Boundary equilibrium" framing from PR #142 was constructed on a misaligned classifier. The *post-fix* distribution is richer and structured around a different dominant token (`phase_boundary`). The equilibrium-like *behavior* survives (low CCI, boundary-dominated, settled across stride/radius/cascade perturbations), but the *naming* and the *specific Karuna/Boundary story* need re-grounding. The phenomenon is real; the interpretive vocabulary needs a refresh.

This is exactly what calibration is supposed to surface, and exactly what AURA and Jack designed the experiment matrix to catch. The discipline worked.

---

## 4. Three puzzles to resolve before Lane A

These are not "the calibration failed." They are "the calibration surfaced three things that need a human-in-the-loop decision before any downstream agent acts on the signal." Each carries a recommended next step.

### 4.1 The temporal-sweep multi-timescale anomaly (shrinking JS with gap)

**The data:**

| Gap | JS divergence (bits) | Source set |
|---|---|---|
| Adjacent (~10 min) | **0.1121** ⚠️ above falsification threshold | short |
| ~1 h | 0.0971 (just below) | short |
| ~2 h | 0.0782 (inconclusive band) | long |
| ~6 h | 0.0525 (inconclusive band) | long |
| ~24 h | **0.0052** (well below attractor threshold) | long, n=1 |

**Why it matters:** an attractor should produce low JS at *every* gap. A drifting transient should produce JS that *grows* with gap. This data shows neither — JS *shrinks* monotonically with gap. "Inverse attractor" is not a real dynamical category; the pattern is more likely **temporal aliasing on an environmental cycle**, **high-frequency oscillation under a slow mean**, or **n=1 statistical luck**. The three hypotheses below are physically plausible and testable, *not* confirmed.

**Three testable hypotheses** (none yet tested; pick the language carefully — these are candidates, not findings):

1. **24h environmental / hardware-cycle aliasing.** Medusa runs on the **Area 51 head node** (Ultra Core 9 285K + RTX 5090), with **Folding@home using the RTX 5090 and one CPU core**, and **BOINC restricted to CPU-only** (BOINC GPU access was blocked because its prime-number workload was hammering the 5090). Any of: F@H work-unit scheduling, BOINC CPU pressure, GPU thermal/fan-curve cycles, machine-room power or HVAC rhythms, or daily user-presence patterns could impose a ~24h envelope on Medusa's effective stepping environment. Under aliasing, the 24h-apart pair lands at the *same phase* of that cycle and looks unusually similar; adjacent-gap pairs land at *different phases* of intra-cycle variation and look divergent. This is the most concrete testable candidate.
2. **High-frequency oscillation around a slow mean.** Medusa may genuinely vary at 10-minute scale while remaining broadly similar over longer windows — meaning the short-scale noise is *real lattice dynamics* and the long-scale similarity is *real settling at long timescales*. Both readings can be simultaneously true; we just haven't disentangled them.
3. **n=1 statistical luck.** With only one pair informing the 24h cell, "supported" carries large uncertainty. The single 24h pair may simply be unusually low; the real 24h-pair distribution could span the full 0–0.1 bit range.

**Recommended next step — a temporal-sweep deepening pass with discriminator before Lane A.**

The cleanest discriminator between hypothesis 1 (cycle aliasing) and hypotheses 2/3 (real dynamics or noise): **test 23h, 24h, and 25h pairs.** If 24h is uniquely low while 23h and 25h spike, that **supports** the 24h environmental-aliasing reading. If all three are similar (noisy or similar-low), the n=1 or high-frequency-oscillation reading **strengthens**. This is a one-day pass; it runs existing PR #4 code with different gap anchors.

**For hypothesis 1, gather hardware telemetry concurrently** to cross-correlate environmental phase with lattice divergence dips. Metadata targets, where available:

- snapshot timestamps (already in JSONL)
- Medusa step rate (per-snapshot generation deltas)
- GPU temperature and power draw (RTX 5090 telemetry)
- CPU load (Ultra Core 9 285K)
- Folding@home status (active / between-WU / idle)
- BOINC status (active / between-tasks)
- confirmed Medusa host machine (Area 51 head node)

**Goal of the metadata pass:** cross-correlate hardware telemetry phase with lattice divergence dips. If 24h-aligned hardware cycles (F@H WU boundaries, GPU thermal cycles, etc.) phase-lock with the low-JS pair, that is **discriminating evidence** for environmental aliasing — *not* a smoking gun. Reserve stronger language for after the data lands.

This is *not* PR #4.5 scope creep — it's running PR #4's existing code with different anchors plus telemetry capture. Should be a one-to-two-day pass.

### 4.2 The `metta_warmth` dead-predicate finding (Ch5 + issue #150)

**The data:** `warmth.max = 0.185` across all 3 newest snapshots in the Ch3 smoke pass; warmth-channel sparsity is 0.990. `THRESHOLD_WARMTH = 0.3` at baseline; the ×0.5–1.5 sweep covers effective thresholds 0.15–0.45. At the low end (0.15), `warmth.max = 0.185` *does* cross the threshold in some voxels — so the predicate is not simply blocked by max-below-threshold. The actual block is that `metta_warmth` is a **patch-aggregate** predicate: it needs multiple warmth voxels to co-occur within a 3×3×3 patch, and the 0.990 sparsity means isolated voxels rarely cluster densely enough for the aggregator to fire. The predicate is dead in current Medusa state because of the *aggregator design*, not because of a mis-set threshold value.

**Why "inconclusive" was the right mechanical answer but doesn't tell the full story:** the threshold sweep's job is to ask "is the classifier sitting on a cliff?" The answer here is "the classifier is sitting nowhere — the predicate it gates never fires." That is information *about predicate design*, not about threshold calibration. Issue #150 (predicate aggregator redesign) is the right place to land this; deferred from PR #4 per Jack's scope discipline.

**Recommended next step:** **a PR #4.5 or PR #5 predicate-aggregator pass that takes #150 seriously**. Options to consider (not to decide here):
- Lower `THRESHOLD_WARMTH` to something the current distribution can actually trigger (e.g., 0.15 → fires on the top ~1% of cells). Empirically motivated, but arbitrary.
- Reformulate `metta_warmth` as a *relative* predicate (top-N% of warmth values per snapshot) instead of an absolute threshold. Avoids the "what's the right number" problem but introduces its own framing question.
- Accept that warmth is currently a low-signal channel in late-game Medusa and demote `metta_warmth` from the active cascade, surface as a diagnostic-only metric.

None of these is Lane A's call to make; all three are legitimate calibration-second-pass questions.

### 4.3 The `DIVERSITY_BOUNDARY` combinatorial-rescaling question (Ch8 finding 3)

**The data:** At `patch_spatial_radius = 1` (27 cells/patch), `voc_occ = 0.406`. At `r = 2` (125 cells/patch), `voc_occ = 0.125` and `boundary_rate = 0.985`. The `DIVERSITY_BOUNDARY` predicate (which requires > 3 distinct cell states in a patch) is *combinatorially* easier to satisfy with 125 cells than with 27, even when nothing else changes.

**Why this is a calibration finding, not a Ch8 bug:** Ch8 deliberately did not rescale `DIVERSITY_BOUNDARY` because the threshold is bounded by the 5-state alphabet, not by patch volume. The decision is correct under design-doc §3.3 ("rescale ONLY count thresholds that truly need rescaling"). But the *consequence* — that the vocabulary composition is patch-size-dependent even when CCI is not — is a real second-order finding worth recording for the predicate-design pass in #4.2 above.

**Recommended next step:** roll this into the same predicate-aggregator pass as `metta_warmth`. The two findings together (one absolute-threshold predicate that never fires, one combinatorial-threshold predicate that fires too easily at larger patch sizes) are *the same shape of problem* — predicate calibration that wasn't grounded in actual distributional statistics from current Medusa.

---

## 5. What this calibration is *not*

Maintaining the interpretive/operational partition (design doc §7) — these reframings are tempting but the data does not support them and the encoding discipline forbids them.

- **Not "Medusa is in a stable attractor."** Three independent spatial discriminating tests support real geometric structure. The temporal evidence is mixed-to-anomalous. The combination supports "spatially settled," not "globally settled."
- **Not "the Karuna/Boundary equilibrium is verified."** The post-#145 dominant token is `phase_boundary`, not `karuna_relief`. The post-fix story needs a refreshed name — perhaps "Boundary-dominant low-CCI equilibrium" — and explicit acknowledgement that the PR #142 framing was constructed on a layout error.
- **Not "the lattice is computationally at rest."** Adjacent-snapshot JS of 0.1121 bits is not "at rest" by any reasonable reading. The current evidence supports low 24h-scale drift, with an n=1 caveat (per Jack, PR #4 review); the short-timescale dynamics are unresolved.
- **Not "calibration done, ship Lane A."** See §6.

---

## 6. Recommendation for the Lane A decision gate

**Recommendation: park Lane A. Run a calibration-second-pass first.**

The case *for* opening Lane A:
- Spatial-structure evidence is convergent and strong (3 chapters, 3 different alternate-hypothesis tests, all support AURA).
- Determinism + regression-fence + memory-channel structural checks all green.
- The test discipline (400/400 Lane B suite) is mature enough to catch regressions.

The case *against*, which I judge stronger right now:
- The temporal anomaly (§4.1) is the kind of observer-uncertainty that can create death-spiral conditions in a self-improving Lane A loop — the "stable-looking signal that isn't actually stable" pattern the Continual Harness paper flagged. A Lane A agent acting on a metric that says "settled" while the underlying lattice has 0.11 bits of adjacent-snapshot variance would be misled by the observer in the way the calibration was designed to prevent.
- The dead-predicate finding (§4.2) means part of the vocabulary the agent would consume is currently non-discriminating. Acting on "the lattice is not in a `metta_warmth` state" when it *cannot be* in a `metta_warmth` state is also misleading-by-construction.
- The pre-#145 framing error (§3) was already a real shot across the bow. The interpretation we have today is *better* than PR #142's, but the Karuna/Boundary vocabulary has not been refreshed in design docs to match what the post-fix classifier actually measures. Lane A reading "Karuna saturation" would mean different things to different readers.

**Concrete proposed next step (not for Lane A; for *this* lane):**

1. **One-day pass: temporal-sweep deepening** — multiple 24h pairs, sub-cadence gaps, JS variance bars, plus the 23h/24h/25h discriminator. Either resolves the temporal multi-timescale anomaly into one of the §4.1 hypotheses or sharpens the question.
2. **One-day pass: predicate-aggregator review** — `metta_warmth` and `DIVERSITY_BOUNDARY` together, per #150. Either refit thresholds against actual distributional data or demote the predicates with reasons recorded.
3. **One-day pass: vocabulary refresh** — update interpretive docs (and only docs; no code) to match the post-#145 distribution. Drop the Karuna/Boundary headline framing; replace with whatever language the post-fix data actually supports.
4. **Then re-open the Lane A decision gate** with §1–3 in hand. The gate is its own gate; this report does not pre-decide it.

**Operator override:** Kevin holds the merge button on all of this, as always. If the judgment is that the spatial-structure evidence is strong enough to greenlight Lane A *with* the §4 puzzles annotated as known unknowns in the Lane A safety design, that's a legitimate call. I do not make it. I flag the trade-off.

---

## 7. Issue / PR references

- Issue **#139** — finding (c) parent hub; alternate hypotheses 1–4 + null. **Stays open** pending Lane A decision; do not auto-close on this report.
- Issue **#144** — memory-channel layout misalignment; **fixed** by `#145` before PR #4 code.
- Issue **#150** — predicate aggregator redesign question; **stays open**; this report is the first time it's framed against the combined Ch5 + Ch8 evidence.
- Issue **#151** — Chapters 1+2 wallclock metadata cleanup / byte-identical rerun coverage. Not directly touched by this summary, but the determinism contract it tightens is the foundation Ch3–Ch8 all rely on.
- PR **#142** — original 5-snapshot smoke that motivated PR #4. Findings *interpretation* superseded by post-#145; *determinism contracts* still authoritative.
- PR **#143** — design doc (this report's companion).
- PR **#145** — memory-channel layout fix.
- PR **#146** — Ch1+2 (foundation + check_determinism + shuffle_test).
- PR **#147** — Ch3 (verify_memory_channels as runtime regression fence).
- PR **#148** — Ch4 (sweep_stride).
- PR **#149** — Ch5 (sweep_threshold) + config.log_directory safety guard.
- PR **#152** — Ch6 (ablate_cascade; defaults revised post-audit).
- PR **#153** — Ch7 (sweep_temporal).
- PR **#154** — Ch8 (sweep_patch_radius); **the gauntlet's last code chapter**.

---

## 8. What "calibration runs" means going forward

PR #4 shipped the *code*. The smoke passes embedded in each commit ran the code against 2–3 newest Medusa snapshots and were the inputs to this summary. The full short-set (12 snapshots) and long-set (12 snapshots) production calibration runs are **not in `data/` yet** — they would generate the canonical `calibration_sweeps.jsonl` files that future Lane A and PR #5+ work consumes.

**Whether to run those now or only after the §6 second-pass resolves the puzzles** is itself a question. My read: run the full sweeps *after* the predicate aggregator pass (§4.2) lands, so the JSONL artifacts that get baselined-against don't carry the `metta_warmth` dead-predicate rows as canonical data. But this too is for the operator gate.

---

**Approval requested from:** AURA — does the matrix in §2 represent the calibration fairly against your original framing? Jack — are the falsification thresholds in §1's table the right ones to cite, and is the Lane A recommendation in §6 the right discipline call? **Operator gate (Kevin)**: hold the merge button on this summary, and the separate gate on Lane A.

*— 84, 2026-05-27 (the fresh-head day, as promised)*
