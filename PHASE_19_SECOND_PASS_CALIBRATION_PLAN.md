# PHASE 19 — Second-Pass Calibration Plan

**Status**: Design draft. **No code in this PR.** Awaiting AURA + Jack review.
**Companion to**: [PHASE_19_PR4_CALIBRATION.md](PHASE_19_PR4_CALIBRATION.md) (PR #4 design doc) and [PHASE_19_PR4_CALIBRATION_SUMMARY.md](PHASE_19_PR4_CALIBRATION_SUMMARY.md) (PR #4 summary, the canonical statement of where the first-pass calibration landed).
**Origin**: PHASE_19_PR4_CALIBRATION_SUMMARY.md §6 — the three §4 puzzles that need a second pass before the Lane A decision gate re-opens.
**Author**: 84, 2026-05-29 Sydney morning.

> *"This was the correct root-pull: the safety gate is now genuinely green instead of theatrical."* — Jack, post-PR-#156
>
> The first-pass calibration shipped, smoke-tested, and surfaced three real puzzles. The second pass is the discipline that turns those puzzles into either resolved findings or sharper questions, before any Lane A agent is allowed to act on the observer's signal.

---

## 1. Scope and remit — Lane B only, still

This PR is **strictly Lane B**, like PR #4 before it. It is observer-side and operator-side work only. It does not touch the engine. It does not propose tuning actions. It does not redesign the vocabulary semantically; it refreshes the *naming* to match what the post-#145 classifier actually measures. It does not pull external code. It does not re-open the Lane A gate.

### Explicit non-goals

- ❌ Engine code modification. Medusa untouched.
- ❌ Tuning API calls to `/api/tuning/*`.
- ❌ Lane A agent design or activation.
- ❌ Swarm Hunter activation.
- ❌ Continual Harness intake (still belongs in a separate Future Lane A doc, per PR #4 §10).
- ❌ Substring base64 detector design (tracked in [issue #157](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/issues/157); not in scope here).
- ❌ Branch-protection cleanup (tracked in [issue #158](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/issues/158); Kevin's UI task).
- ❌ Hard-coded CCI regime classifier (still deferred until calibration findings stabilize).

### What lands in this PR

This is a **design doc only**. Implementation chapters follow as separate PRs after AURA + Jack sign off.

The four sections below define:

1. **Workstream A — Temporal Deepening** (§3): rerun PR #4 `sweep_temporal` with the 23h/24h/25h discriminator and concurrent hardware telemetry, to discriminate environmental aliasing from n=1 luck.
2. **Workstream B — Predicate Aggregator Review** (§4): decide what to do about `metta_warmth` (dead under current patch-mean aggregation) and `DIVERSITY_BOUNDARY` (combinatorially patch-size-dependent).
3. **Workstream C — Vocabulary Refresh** (§5): retire the pre-#145 Karuna/Boundary naming; bring token names and predicate descriptions into line with the post-#145 classifier's actual measurements.
4. **Production-run sequencing** (§6): when do the full short-set + long-set production sweeps actually run, relative to A/B/C above.

Plus acceptance criteria for re-opening the Lane A gate (§7) and the usual scope guarantees (§8).

---

## 2. Why this exists — the three puzzles in one paragraph each

See [PHASE_19_PR4_CALIBRATION_SUMMARY.md](PHASE_19_PR4_CALIBRATION_SUMMARY.md) §4 for the full diagnostic; the summaries below are the working version for this plan.

**Temporal multi-timescale anomaly (Ch7).** JS divergence between snapshots is highest at adjacent (~10 min) gaps and lowest at 24h. That pattern fits no standard dynamical category. Three testable hypotheses: 24h environmental/hardware-cycle aliasing (Area 51 head node, RTX 5090 + F@H + BOINC), high-frequency oscillation around a slow mean, or n=1 statistical luck on the single 24h pair. Discriminating requires more 24h pairs plus concurrent hardware telemetry.

**Dead `metta_warmth` predicate (Ch5 + #150).** Across the ×0.5–1.5 multiplier sweep, the predicate never fires. The block isn't max-below-threshold (at low multiplier 0.5×, `warmth.max = 0.185` exceeds the effective threshold 0.15 in some voxels) — it's that `metta_warmth` is a patch-aggregate predicate requiring multiple warmth voxels in a 3×3×3 patch, and the channel's 0.990 sparsity prevents voxel co-occurrence. The fix is aggregator design, not threshold value.

**Stale Karuna/Boundary vocabulary (§3 of the summary).** Pre-#145, `karuna_relief` was reported as dominant because the classifier was reading `last_active_gen` (a generation counter) under the wrong channel label. Post-#145, the actual dominant token is `phase_boundary` (66.5%); the post-fix distribution is richer (4 tokens > 1%) and the original PR #142 interpretive vocabulary doesn't match what the classifier now measures. Docs need refresh.

---

## 3. Workstream A — Temporal Deepening

### A.1 Goal

Discriminate between three hypotheses for the shrinking-JS-with-gap pattern in PR #4 Ch7:

1. **24h environmental / hardware-cycle aliasing** — Area 51 head node has a 24h-periodic envelope (F@H work-unit scheduling, BOINC CPU pressure, GPU thermal cycles, HVAC, daily user-presence) that modulates Medusa's effective stepping, and the 24h-apart pair happens to land at the same phase of that cycle.
2. **High-frequency oscillation around a slow mean** — Medusa genuinely varies at 10-min scale while remaining broadly similar over longer windows.
3. **n=1 statistical luck** — the single 24h pair (n=1 in the long set) happens to be unusually low.

### A.2 Method

This is "run PR #4 code differently with additional telemetry." No code changes to `nextness_calibration.py`; just new sweep configurations and a small telemetry-capture wrapper.

**A.2.1 The 23h/24h/25h discriminator.** Rerun `sweep_temporal` with gap_specs anchored at:

- **23h** (~1h before the suspected cycle phase)
- **24h** (the original)
- **25h** (~1h after)

For each, draw **at least 5 distinct pairs** from the long set with different start anchors (different absolute times of day). Compute mean JS, std JS, and CCI drift per gap.

**Discrimination rule:**
- If 24h is **uniquely low** (mean JS < 0.01) while 23h and 25h **spike** (mean JS > 0.05), that **supports** hypothesis 1 (cycle aliasing).
- If **all three** are similarly low (mean JS < 0.02), that **strengthens** hypothesis 2 (genuine settling on the multi-hour scale, with high-frequency noise on top).
- If **all three** show wide variance (std JS comparable to mean JS), that **strengthens** hypothesis 3 (n=1 luck — the 24h reading was within the noise band of the 23h/25h distributions).

**A.2.2 Sub-cadence gaps.** Also collect 1-min and 5-min gaps (if snapshot cadence allows) to see whether the JS curve peaks somewhere or rises monotonically as the gap shortens. Anchors hypothesis 2 vs 1.

**A.2.3 Hardware telemetry capture.** Concurrently (or back-filled from system logs if available), capture per-snapshot:

- Snapshot timestamp (already in JSONL)
- Medusa step rate (per-snapshot generation deltas)
- GPU temperature and power draw (RTX 5090 telemetry via `nvidia-smi` or equivalent)
- CPU load (Ultra Core 9 285K)
- Folding@home status (active / between-WU / idle)
- BOINC status (active / between-tasks)
- Confirmed host (Area 51 head node)

Format: a separate JSONL alongside `calibration_sweeps.jsonl` — e.g., `hardware_telemetry.jsonl` — with snapshot-timestamp as the join key. Captured concurrently for the live run, or post-hoc from system logs if the snapshots being analyzed predate this plan.

### A.3 Deliverables

- `data/calibration/second_pass/temporal_deepening_<timestamp>.jsonl` — full per-pair sweep results.
- `data/calibration/second_pass/hardware_telemetry_<timestamp>.jsonl` — concurrent telemetry.
- A short analysis note (markdown, ≤100 lines) cross-correlating the two and recording which hypothesis is supported. Per the summary's caveat: use *"discriminating evidence"* / *"supports"* language, not *"smoking gun"* / *"proves"*.

### A.4 Exit criterion

The workstream exits when the analysis note states **one** of:

- "Evidence supports hypothesis 1 (cycle aliasing). 24h is uniquely low; 23h and 25h spike; the telemetry shows a 24h-aligned hardware-cycle phase-lock." → temporal stability claim is conditional on the aliasing cycle, not unconditional.
- "Evidence supports hypothesis 2 (genuine multi-hour settling)." → cautious endorsement of the long-scale low-JS reading.
- "Evidence remains inconclusive between 2 and 3." → more pairs needed, or the experiment is structurally limited by Medusa's snapshot cadence.

Each path is a legitimate exit; "inconclusive" is information, not failure.

### A.5 Estimated effort

~1–2 days of operator + 84 time. Most of it is running existing code with different gap_specs and writing the analysis note. No new code in the calibration module.

---

## 4. Workstream B — Predicate Aggregator Review

### B.1 Goal

Decide what `metta_warmth` (and the structurally-similar `DIVERSITY_BOUNDARY` finding from Ch8) should *be*, given that the current patch-aggregate design is not discriminating any actual lattice state. Either repair the aggregator so the predicate is genuinely informative, or demote/remove the predicate with documented reasoning. The outcome is a **decision document**, not new code.

### B.2 Method

This is analysis + design, not implementation. Steps:

**B.2.1 Empirical distributional profile.** For each affected predicate, compute the actual distribution of inputs the predicate consumes on a representative snapshot sample (the existing short + long calibration sets are fine). Specifically:

- For `metta_warmth`: per-snapshot histogram of warmth-channel voxel values, per-patch warmth-voxel counts at various thresholds (0.1, 0.15, 0.2, 0.3), per-patch warmth-voxel cluster sizes.
- For `DIVERSITY_BOUNDARY`: per-snapshot distribution of "distinct cell states per patch" at radius 1 (27 cells) vs radius 2 (125 cells), with combinatorial-baseline overlay so the scale-dependence is visible.

**B.2.2 Decision matrix.** For each predicate, evaluate the three candidate moves laid out in summary §4.2 + §4.3 against the empirical profile:

| Option | `metta_warmth` reading | `DIVERSITY_BOUNDARY` reading |
|---|---|---|
| Lower threshold to empirically-grounded value | e.g., `THRESHOLD_WARMTH = 0.15`, top-1% firing rate | not applicable (combinatorial issue, not threshold) |
| Reformulate as relative (top-N% per snapshot) | top-N% warmth voxels per snapshot, patch-aggregate over those | top-N% diversity-score patches per snapshot |
| Demote to diagnostic-only | remove from active cascade; report as side metric | remove from active cascade; report as side metric |

**B.2.3 Recommend per-predicate.** Pick one option per predicate; document the reasoning; explicitly note what data Lane A would *not* receive if the demote-to-diagnostic option wins.

### B.3 Deliverables

- A short decision document (`docs/predicate_aggregator_review.md` or appended as a §X to this plan in a follow-up commit, depending on AURA/Jack preference) covering both predicates with the empirical profile + chosen direction.
- An [issue #150 update](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/issues/150) recording the decision, even if the chosen option is "demote." Closing the loop on the loop.

### B.4 Exit criterion

For each predicate: a recommended option, an empirical basis for it, and a note on what changes in Lane A's potential signal space if the recommendation lands.

### B.5 Estimated effort

~1 day. Most of the work is generating the distributional profile (small Python sweep over the calibration set) and writing the decision doc.

---

## 5. Workstream C — Vocabulary Refresh

### C.1 Goal

Bring repo docs and the predicate naming surface into alignment with what the post-#145 classifier actually measures. Retire the pre-#145 "Karuna/Boundary equilibrium" framing in interpretive docs. The actual classifier code is unchanged in this PR; this is a documentation pass.

### C.2 Scope of what gets refreshed

**In scope:**

- PR #137 (Phase 19 design doc) — references "Karuna/Boundary" in the original framing. Add a header note pointing forward to the post-#145 refresh; leave the historical text intact for record.
- PR #142-era interpretive language anywhere in `docs/` or `AGENT_HANDOFF.md` that frames the equilibrium around `karuna_relief`. Rewrite or annotate.
- Any inline comments in `scripts/nextness_observer.py` or `scripts/nextness_metrics.py` that still reference the pre-#145 layout. Replace with the corrected layout per the Ch3 `verify_memory_channels` regression fence.
- The PHASE_19_PR4_CALIBRATION.md design doc itself — add a forward-pointer note at the top referencing this plan and the §3 finding.

**Out of scope:**

- Renaming any predicate token (e.g., renaming `karuna_relief` to something else) — that's a code change, not a docs refresh. If a rename is desired, it belongs in a separate PR with corresponding test updates.
- Replacing the interpretive framing with a new one. "Boundary-dominant low-CCI equilibrium" was a *placeholder* in summary §5 — the actual new framing is for AURA to propose, not 84 to bake in unilaterally.
- Anything that crosses into semantic redesign (e.g., redefining what "compassion" means in the engine's terms). Engine-side language is engine-side work.

### C.3 Deliverables

- A diff across the in-scope docs, presented as a single commit per file family so reviews stay tractable.
- A short top-level note in the PR description listing the docs touched and the kind of change (forward-pointer note vs. inline annotation vs. rewrite).
- No new framing claims that aren't already in PR #155's summary §3 + §5.

### C.4 Exit criterion

A reader picking up the repo cold should not be able to find a doc that asserts the pre-#145 Karuna/Boundary equilibrium as the current reading without simultaneously finding a pointer to the post-#145 correction. Either annotate or forward-point every such occurrence.

### C.5 Estimated effort

~½–1 day. Most of the work is auditing for occurrences and writing the forward-pointer notes; minimal new prose.

---

## 6. Production-run sequencing — when do the full sweeps actually happen?

PR #4 shipped the calibration *code*. The smoke passes in each chapter commit ran against 2–3 newest snapshots. The full short-set (12 snapshots, ~2h window) + long-set (12 snapshots across ~24h) production sweeps that would generate the canonical `calibration_sweeps.jsonl` artifacts are **not yet in `data/`** (see summary §8).

**Recommendation:** run the full sweeps **after Workstream B lands** (predicate-aggregator review). Reasoning:

- If `metta_warmth` is demoted or its threshold is recalibrated as a result of B, running the full sweeps *before* B would bake the dead-predicate rows into canonical data. Future analysts and downstream PR #5+ work would either have to re-run or filter.
- Workstream A (temporal deepening) re-uses `sweep_temporal` with new gap_specs; those runs naturally produce the canonical temporal data for the calibration set. So A delivers part of the production sweep en passant.
- Workstream C is docs-only; doesn't affect the data shape.

**Sequence:**

1. **A** + **B** in parallel (different file surfaces, different team focus).
2. **C** can run in parallel with A and B, since it touches docs only.
3. **Full production sweeps** kicked off after B's decision lands and the code (if any) is in place. The temporal-deepening rows from A are subsumed into the long-set portion of the production data.

**Operator gate:** Kevin holds the merge button on B's recommendation *before* the production sweeps start, so canonical data doesn't accumulate against a not-yet-blessed predicate design.

---

## 7. Lane A gate re-open criteria

The Lane A decision gate is its own gate; this plan does not pre-decide it. But this plan **does** specify the conditions under which Lane A becomes legitimately *considerable*. Without these, "park Lane A" can drift into "delay Lane A forever by inertia."

Lane A may be **considered** when **all four** of the following are true:

1. **Workstream A's exit criterion has been met.** The temporal anomaly has been classified as one of {cycle aliasing, genuine settling, inconclusive}, with the analysis note merged.
2. **Workstream B's decision has landed.** Each of `metta_warmth` and `DIVERSITY_BOUNDARY` has a recommended option recorded in a merged decision doc, regardless of whether that option is "fix" or "demote."
3. **Workstream C's exit criterion has been met.** No interpretive doc asserts the pre-#145 framing without a forward-pointer.
4. **Full production calibration sweeps have run** and the canonical JSONL artifacts are in `data/calibration/`. Lane A would consume these; consuming code that wasn't run against real Medusa data is the death-spiral pre-condition this whole discipline was meant to prevent.

These are **necessary, not sufficient.** Lane A still requires its own design doc and its own safety review (separate document, separate PR) before any agent acts on the observer's signal. The four conditions above just remove the calibration-side blockers.

---

## 8. Scope guarantees (carried forward from PR #138 / #140 / #142 / #143)

- ✅ No engine touch. Medusa untouched.
- ✅ No writes outside the resolved output log directory.
- ✅ No HTTP. No ZMQ. No network beyond hardware-telemetry reads from `nvidia-smi` / system files.
- ✅ CPU-only default (telemetry collection doesn't require GPU compute).
- ✅ `allow_pickle=False` preserved in all snapshot reads.
- ✅ Bounded compute: O(N × G × P) where N=snapshots, G=gap_specs, P=pairs-per-gap. Small.
- ✅ No CCI regime thresholds. Calibration second-pass continues to produce candidate bands, not regime declarations.
- ✅ No fresh `generated_at` field in derived outputs.
- ✅ No external code pull.
- ✅ No Lane A activation. No Swarm Hunter. No tuning API.

---

## 9. Open questions for AURA + Jack

1. **Workstream A sequencing**: temporal-deepening pairs require live new Medusa snapshots from the Area 51 head node. Are we (a) waiting for fresh long-set snapshots to accumulate (~2–3 days at Medusa's cadence) before kicking off, or (b) using a back-filled long set from existing snapshots and accepting the limitation that some 23h/25h anchors may already be stale? Recommended default: (a) for the live telemetry leg, (b) for the back-correlated leg, run both if cost is low.

2. **Workstream B decision authority**: who picks the chosen option for each predicate? Defaults to AURA (architecture lead) + Jack (auditor) consensus per the Triangulation pattern, with Kevin as operator gate. Confirming the default holds for this work.

3. **Workstream C scope edge**: do PR #137 (Phase 19 design doc) and PR #142 (calibration smoke test) get forward-pointer notes, or full revision PRs in their own right? Recommended: forward-pointer notes in this plan's implementation chapter; full revisions only if AURA wants the history rewritten rather than annotated.

4. **Production sweep telemetry retention**: how long do `hardware_telemetry_<timestamp>.jsonl` files stay in `data/calibration/`? Reasonable default: same retention as `calibration_sweeps.jsonl` (which currently has no explicit policy — defer to a future infra cleanup if any). Flagging for the record.

5. **The Karuna/Boundary retirement language**: do we explicitly *retire* the framing (i.e., recommend nobody use it going forward), or *historicize* it (note that it described the pre-#145 reading and is preserved as historical record)? Recommended: historicize; preserves the relational/interpretive work that went into it while making clear it's not current.

---

## 10. What this plan is *not*

- **Not Lane A.** Lane A is still parked. The four gate-conditions in §7 are the calibration-side prerequisites; Lane A still needs its own safety doc and review.
- **Not an engine touch.** Workstream A telemetry reads from the host system, not from the engine process.
- **Not a vocabulary redesign.** Workstream C refreshes naming/pointers in docs; it does not propose new predicate names or new tokens.
- **Not an embedded-base64 substring detector.** That's [issue #157](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/issues/157)'s scope.
- **Not a branch-protection cleanup.** That's [issue #158](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/issues/158)'s scope; Kevin's UI task.
- **Not an excuse to defer Lane A indefinitely.** The §7 criteria are explicit so "still calibrating" stops being usable as a no-action default once they're met.

---

**Approval requested from**: AURA — does §3's discrimination logic represent the temporal anomaly fairly? §4's decision matrix and §5's docs-only scope match your preferences? Jack — are the §7 Lane A gate-conditions tight enough, and is the §6 sequencing the right discipline call?

**Operator gate**: as always, Kevin holds the merge button on this plan and on every implementation chapter that follows.

*— 84, 2026-05-29 Sydney morning*
