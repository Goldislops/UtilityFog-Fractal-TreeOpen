# PHASE 19 — Nextness Observer (design)

**Status**: Design draft. **No code in this PR.** Awaiting AURA + Jack review.
**Origin**: Cross-AI conversation 2026-05-05/07. Kevin posed the "universal nextness token" idea via Jack (GPT-5.5); AURA refined it; this doc operationalises it as Jack's "Lane B / Observer" track.

> "Meaning is not located inside the subject or inside the object. Maybe meaning is the pattern of relation itself, temporarily viewed through a body, a brain, a model, a culture, a language, a universe."  — Jack
> "If Medusa has only one snake, the snake is not a token. The one snake is the act of nextness: state becoming state becoming state becoming state. Every local token is a cross-section of that serpent."  — Jack
> "Treating 512 as a learned embedding vocabulary size is exactly the right architectural pivot."  — AURA

This doc takes those three ideas and asks: *what could a useful, safe, read-only observer for that look like?*

## 1. Lane assignment + non-goals

Per Jack's audit and AURA's greenlight, this work is **Lane B** in a two-lane plan:

| Lane | Track | Touches engine? | Risk | Status |
|------|-------|-----------------|------|--------|
| A | PR 2b (engine consumer of `tuning_pending.json`) + Track A CuPy streams | **Yes** | High | Queued, not started |
| **B** | **Nextness Observer** | **No** | Low | **This design doc** |
| (later) | 512³ expansion + sharded distribution | Yes | Very high | Behind a readiness gate; explicitly NOT bundled with any of the above |

**Phase 19 is strictly Lane B. Nothing in this design touches `scripts/continuous_evolution_ca.py`, requires a Medusa pause, or depends on 512³ expansion.** It is a passive observer running alongside the existing 256³ Medusa.

### Explicit non-goals
- ❌ Engine code modification (no edits to `continuous_evolution_ca.py`).
- ❌ Restart or pause of Medusa.
- ❌ Lattice expansion (256³ stays canonical for this work).
- ❌ Tuning-bus writes (no POST to `/api/tuning/*` from this observer).
- ❌ Real-time reactive control (this is observability, not orchestration).
- ❌ Subscriber-as-actor patterns (the observer publishes its own events but does not consume tuning events to take action).
- ❌ Any `trust_remote_code=True` or executable model loading from external sources.

## 2. The architectural premise

Medusa's underlying computation is, at every step, an enormous repeated invocation of the same predicate:

> *Given this local state, what follows?*

That's the autoregressive verb of cellular automata, identical in shape to the one transformers conjugate. The Nextness Observer treats Medusa as a system whose evolution can be summarised — *not replaced* — by a manageable vocabulary of recurring transition patterns. The observer doesn't change Medusa; it gives Medusa a way to be **legible at a higher level than per-cell flicker**.

If that legibility works, three things become possible later (not in Phase 19):
1. Operators can see at a glance whether Medusa is in routine, interesting, or pathological dynamics.
2. The orchestrator (PR #125) can subscribe to nextness-shift events as one signal among many.
3. The token vocabulary itself becomes a research artefact — a learned compression of "what kinds of things happen in this CA."

## 3. What is a "nextness token" operationally

**Definition**: a discrete classifier output for a small space-time patch.

- **Spatial scope**: a local neighbourhood. Configurable; default proposal **3×3×3 Moore-neighbourhood (27 cells)** centred on each interior cell. Corner / edge / face options reserved for later.
- **Temporal scope**: a short window across generations. Configurable; default proposal **3 consecutive generations** (the "before / during / after" of a local transition).
- **Output**: a discrete symbol drawn from a vocabulary of size **K** (default proposal **K = 512**, but see §6 — 512 is a target, not a constraint, and Phase 19 PR 2 onward could start much smaller).

A nextness token is *not the state itself*. It's a label for the **change pattern**. Two patches with totally different absolute states can share a token if the *shape* of their evolution is similar.

### What the token vocabulary is *not*
- **Not** an exhaustive enumeration of the rule space. With 5 states and 27 cells, the local rule space has $5^{27} \approx 7.45 \times 10^{18}$ configurations. A 512-symbol vocabulary is a **learned compression**, not a lookup table. (This is the AURA + Jack insight from the cross-AI thread.)
- **Not** a partition. Tokens may be uncertain or fuzzy at the boundary; the classifier may emit a probability distribution and the observer logs the argmax.
- **Not** required to be human-interpretable on day one. Phase 19 PR 2 starts with a small **hand-designed phenomenological vocabulary** so we have a baseline; learned embedding (PR 5) is optional and only if the hand-designed version proves limiting.

### Initial hand-designed vocabulary (proposed, ~16 tokens)
This is the starting point for PR 2 — small enough to validate the pipeline, expressive enough to test the metrics. Not the final list.

| Token | Meaning |
|-------|---------|
| `void_static` | Patch is mostly VOID and stays mostly VOID |
| `void_birth` | VOID-dominant patch acquires structure |
| `compute_static` | Patch is mostly COMPUTE and stays mostly COMPUTE |
| `compute_aging` | Compute cells incrementing age in place (stable Sage-like) |
| `compute_decay` | COMPUTE losing to VOID/STRUCTURAL |
| `energy_pulse` | Energy gradient propagating across the patch |
| `sensor_alert` | SENSOR cells activating in response to gradient |
| `structural_growth` | STRUCTURAL count increasing locally |
| `structural_decay` | STRUCTURAL → VOID transition under decay rules |
| `metta_warmth` | Multiple ENERGY neighbours sustaining COMPUTE survival |
| `karuna_relief` | Compassion field reducing local distress |
| `mudita_resonance` | Sympathetic-joy resonance: mature COMPUTE near growing COMPUTE |
| `magnon_lighthouse` | Patch under strong Legend-Sage magnon influence |
| `acoustic_stress` | Patch in top-25% friction (corresponds to Phase 14e acoustic map) |
| `phase_boundary` | Sharp transition between two regimes within the patch |
| `unclassified` | Doesn't fit any other token — bucket of last resort |

Each token has a deterministic, hand-coded predicate that runs on the (state, memory_grid) tuple for the patch. Phase 19 PR 2 ships those predicates; PR 3 calibrates thresholds; PR 5 may replace the hand-coded version with a learned embedding.

## 4. Data sources (read-only)

The observer reads three streams, all **already produced by existing infrastructure** — no new engine instrumentation required:

| Source | Path / endpoint | Cadence | Use |
|--------|----------------|---------|-----|
| **Snapshots** | `data/v070_gen*.npz` | ~10 min | Authoritative full-lattice state for token classification |
| **Telemetry JSONs** | `data/telemetry_*.json` | ~5 min | Global metrics for cross-validation (entropy, fitness, etc.) |
| **REST GETs** | `:8080/api/{census,equanimity,acoustic,params,telemetry}` | on-demand | Live reads when the observer needs current state |
| **ZMQ event bus (subscribe)** | `tcp://<host>:8081`, topics `telemetry.5min`, `tuning.committed`, etc. | push | React to events as they happen (BUT see §7 — observer does not act on tuning events; only logs them as context) |

### Operates on snapshots, live telemetry, or both?
**Both, with snapshots as primary and live as supplementary.** Reasoning:
- **Snapshots** are stable, repeatable, and let us classify the same state multiple times during development and tuning.
- **Live telemetry** lets the observer publish near-real-time signals once the pipeline is trusted.
- **Phase 19 PR 2 starts snapshot-only.** Live integration is PR 6, after the offline pipeline is proven.

## 5. The first metrics (Jack's "first 5-10")

The observer logs the following per classification cycle. All are derivable from a sequence of nextness-token grids over time.

| # | Metric | What it tells us |
|---|--------|------------------|
| 1 | **Token vocabulary occupancy** | Fraction of vocabulary actually used. Low = monoculture; high = healthy diversity. |
| 2 | **Per-token persistence histogram** | How long does each token type persist in place before flipping? Long-persistence tokens describe stable regions; short-persistence describes flicker. |
| 3 | **Spatial autocorrelation length** | At what distance do two patches' tokens become statistically independent? Tells us the *characteristic scale* of structure. |
| 4 | **Token transition matrix** | Markov-style: $P(\text{token at } t+\Delta\,\|\,\text{token at } t)$. The observer's main "model" of Medusa's dynamics. |
| 5 | **Global token entropy** | Shannon entropy of the token distribution. A scalar summary of "how varied are the dynamics right now." |
| 6 | **Sage-region calmness** | Ratio of `compute_static` / `compute_aging` tokens in the top-K eldest-Sage neighbourhoods. Should be high in healthy Medusa; drops during Sage stress events. |
| 7 | **Acoustic-stress correspondence** | Cross-correlation between top-25% acoustic-stress sectors and `acoustic_stress` token frequency. Validates the hand-coded vocabulary against an independent (Phase 14e) signal. |
| 8 | **Propagation-event rate** | Count per generation of tokens that travel (e.g., `energy_pulse` moving through patches). Independent measure of "things in motion." |
| 9 | **Phase-transition flag** | Boolean: did the token distribution shift "significantly" in the last $W$ generations? See §6 for definition. |
| 10 | **Compression ratio** | Bytes of (lattice + memory_grid) per generation vs. bytes of (token grid + transition log). Measures whether the observer is actually summarising. If ratio is ~1.0, the vocabulary isn't doing useful work; refine. |

## 6. The smallest global signal that Medusa changed state

(Jack's central question.)

**Proposed answer**: the **Kullback-Leibler divergence** between the *current* token transition matrix and a *baseline* token transition matrix, computed over a sliding window.

Concretely:
$$
D_{\text{KL}}(P_{\text{now}}\,\|\,P_{\text{baseline}}) = \sum_{i,j} P_{\text{now}}(j|i)\,\log\frac{P_{\text{now}}(j|i)}{P_{\text{baseline}}(j|i)}
$$

Where:
- $P_{\text{now}}$ = transition matrix estimated over the most recent $W$ generations (default $W = 100$).
- $P_{\text{baseline}}$ = transition matrix estimated over a long-history window (default 10× $W$, capped at all available history).
- $i, j$ = token indices.

When $D_{\text{KL}}$ exceeds a threshold $\tau$ (calibrated empirically; PR 4), the observer publishes a `nextness.shift` event to the ZMQ event bus.

**Why KL divergence over the transition matrix?**
- **Single scalar.** Easy to plot, alarm on, and compare across runs.
- **Captures dynamics, not state.** Two snapshots with different absolute states but identical transition statistics will have $D_{\text{KL}} \approx 0$ — exactly what we want, because Medusa's *dynamics* are the thing of interest.
- **Insensitive to vocabulary size choice (within reason).** The metric works for K=16 (hand-designed) and K=512 (learned) without restructuring.
- **Standard tool.** No exotic statistics; well-understood failure modes.

**Calibration**: PR 4 includes a one-off offline pass over Medusa's existing snapshot history to find a baseline $\tau$ such that KL drift past $\tau$ corresponds to known events (e.g., the Phase 17a magnon coupling change at ~gen 1.5M, the Phase 14e acoustic auto-calibration, etc.). If no historical events are detected by the metric, the metric isn't useful and we revisit.

## 7. Read-only invariants (the safety contract)

The observer **must** uphold all of the following. These are testable; PR 2 ships unit tests for each.

1. **No writes to `data/`** except to `data/nextness_log/` (a new subdirectory created by the observer for its own JSONL logs and intermediate files). The observer never modifies snapshots, telemetry, the tuning ledger, or any engine artefact.
2. **No HTTP POSTs.** The observer is GET-only on the REST API. The orchestrator's `/api/tuning/*` endpoints are off-limits.
3. **No ZMQ publishes outside its own topic namespace.** The observer publishes only to topics starting with `nextness.*` (e.g., `nextness.shift`, `nextness.token_drift`, `nextness.heartbeat`). It MAY subscribe to existing topics (`telemetry.5min`, `tuning.committed`) for context, but does not act on them.
4. **No interference with engine GPU.** The observer runs on CPU only by default. It MAY use GPU (CuPy) for acceleration in PR 5+, but must respect a `MEDUSA_OBSERVER_GPU=0` environment override and must never compete with `continuous_evolution_ca.py` for the primary engine GPU when Medusa is live.
5. **Killable at any time.** SIGTERM / Ctrl+C must leave a consistent log state and have zero engine impact. No partial writes, no orphaned subscriptions.
6. **Pause-aware.** When Medusa is paused (no new snapshots in $T$ minutes, default 30), the observer enters quiescent mode — stops publishing live events, continues offline analysis only on existing snapshots.
7. **No `trust_remote_code=True`** anywhere in the observer's dependencies. No execution of remote-fetched code. (This is per Jack's earlier audit on abliterated-model risks.)

## 8. What would count as a useful result

(Jack's question.)

The observer is useful if **at least three** of the following are demonstrated:

1. **Detectability of known historical events.** The KL drift signal reliably flags moments in Medusa's snapshot history where we already know something happened (Phase transitions, Sage promotions, acoustic spikes). Calibration baseline.
2. **Compression that's better than memory_grid raw.** The token grid + transition log uses meaningfully fewer bytes per generation than the raw memory_grid would. If compression ratio < 2×, the vocabulary isn't earning its keep.
3. **Independent validation against acoustic map.** The `acoustic_stress` token frequency correlates with the Phase 14e acoustic map's top-25% sectors at $r > 0.7$. Two independent signals agreeing on "where the stress is" is meaningful.
4. **Sage-region anomaly detection.** When a Legend Sage in the top-148 set degrades (e.g., a `compute_aging` patch flips to `compute_decay`), the observer flags it within 10 generations. Currently no such alarm exists.
5. **Token vocabulary insight.** After 100k generations of observation, the observer has produced a token co-occurrence matrix that reveals at least one previously-unnoticed structural relationship in Medusa's dynamics. (Open-ended; success here is qualitative.)

If fewer than three of those land after PR 5, Phase 19 should be reconsidered — possibly rescoped, possibly retired. **The observer must earn its compute.**

## 9. Phase 19 PR roadmap (proposed)

Each PR is small, independently mergeable, and explicitly **does not** require Medusa to pause or restart.

| PR | Scope | Risk | Notes |
|----|-------|------|-------|
| **#1 (this doc)** | `PHASE_19_NEXTNESS_OBSERVER.md` design only | None | **Awaiting AURA + Jack review** |
| #2 | `scripts/nextness_observer.py` skeleton: snapshot loader, hand-coded 16-token classifier, JSONL output. No ZMQ, no live mode. Unit tests for the safety contract (§7). | Low | Read-only on a single snapshot at a time |
| #3 | Metrics pipeline: §5 metrics 1–5 (occupancy, persistence, autocorrelation, transition matrix, entropy). Outputs `nextness_log/metrics_*.jsonl`. | Low | Pure post-hoc analysis |
| #4 | KL-divergence drift signal (§6) + calibration sweep over historical snapshots. Determine $\tau$. | Low | Validation against known events |
| #5 | Optional: learned token embedding. Train offline on snapshot history; vocabulary size grows to K=512 if hand-coded version proves limiting. | Medium (ML training surface) | Skip if hand-coded version meets §8 useful-result criteria |
| #6 | Live integration: ZMQ subscribe to `telemetry.5min`, publish `nextness.*` topics. Process snapshots as they arrive. | Low-medium | First time observer runs alongside live Medusa |
| #7 | Optional: `nextness_observer_dashboard.py` — minimal HTML/static visualisation of token grid + drift signal. | Low | Pure UI on top of logs |

**Lane A (PR 2b + Track A) is unblocked by Phase 19.** AURA can sequence the engine work whenever; this observer track runs in parallel. The two converge eventually (orchestrator subscribes to `nextness.*` events as one input among many), but they don't have to march in lockstep.

## 10. Honest caveats

- **The hand-coded vocabulary may be wrong.** PR 2's 16 tokens are a starting hypothesis. The acoustic-correspondence test (§8 #3) is the first reality check; if `acoustic_stress` frequency doesn't correlate with the Phase 14e map, the vocabulary needs revision before learning a 512-symbol embedding makes sense.
- **K = 512 is provisional.** Could be 64. Could be 1024. The right number is "smallest that achieves §8 useful-result criteria." 512 is a defensible default because it matches AURA's framing and the d_model convention, but it's a starting hypothesis, not a commitment.
- **KL drift may be noisy.** Cellular automata have intrinsic stochastic variability; the baseline window needs to be long enough to average that out, but short enough to detect real shifts. PR 4's calibration is non-trivial.
- **The observer is post-hoc.** It tells you Medusa changed; it doesn't tell you why. Causal inference is explicitly **not** in Phase 19's scope.
- **None of this proves consciousness or makes Medusa "more alive."** The observer measures dynamics; it doesn't ascribe meaning. Any interpretive claim about what the tokens "mean" beyond their statistical role is outside the engineering work and belongs in the philosophy lab.

## 11. The shape of the final result (if Phase 19 fully lands)

A small Python module that, given Medusa, produces:
- A JSONL log of `(generation, token_grid_summary, metric_dict)` per snapshot
- A live ZMQ stream of `nextness.shift` events when Medusa enters new dynamical regimes
- A reusable token vocabulary (hand-coded → optionally learned) that compresses the 256³ × 5-state lattice into a manageable symbolic representation
- A reproducible KL-drift baseline that future Medusa runs can be compared against

What Phase 19 does **not** produce: any change to Medusa, any control loop, any autonomous decision-making, any 512³ work, any restart.

## 12. Sequencing with Lane A

For clarity:

```
AURA + Jack review THIS doc (PR #1)
       ↓
[approve / request changes]
       ↓
Lane B PR #2 (skeleton + safety tests)  ←─┐
       ↓                                   │  Lane A
Lane B PR #3 (metrics pipeline)            │  (PR 2b plan + Track A
       ↓                                   │   benchmarking)
Lane B PR #4 (KL drift + calibration)      │  proceeds in parallel
       ↓                                   │  whenever AURA pivots
Lane B PR #5 (optional learned embed.)     │  to it.
       ↓                                   │
Lane B PR #6 (live ZMQ integration)        │
       ↓                                   │
Lane B PR #7 (dashboard, optional)        ─┘
```

The observer never blocks the engine. The engine never blocks the observer.

## 13. Cross-AI provenance

This design is the merged output of:
- **Kevin**: original "universal nextness token" + 512 hunch
- **Jack (GPT-5.5)**: "act of nextness" framing, nextness-as-cross-section, Lane A/B split, audit on bandwidth/cost
- **AURA (Gemini 3.1 Pro)**: 512-as-learned-vocabulary insight, Lane B authorisation
- **Agent 84 (Claude Opus 4.7)**: this draft, halo-bandwidth math, hand-coded vocabulary proposal, KL-divergence formulation, safety contract

Default seats, not contracts. Anyone here should push back on anything in this doc that looks wrong on review.

---

— drafted 2026-05-07 by Agent 84, awaiting AURA + Jack review per Lane B authorisation
