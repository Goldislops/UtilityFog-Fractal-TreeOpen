# PHASE 19 PR #3 — Metrics Pipeline (design)

**Status**: Design draft. **No code in this PR.** Awaiting AURA + Jack review.
**Origin**: Issue #139 calibration findings; AURA's "Karuna/Boundary equilibrium" reframe + Sakana "God Simulator" conceptual blueprint; Jack's audit cautions; 84's "formalize the metaphors as testable metrics" engineering layer.
**Predecessors**: PR #137 (Phase 19 design doc), PR #138 (PR #2 observer skeleton, merged as `d651f2c`), PR #140 (PR #2 follow-up snapshot-validity + `fraction_used` fix, merged as `d2b5db9`).

> ⚠️ **Historical note (added 2026-06-02)** — read the framing below as period thinking, not current truth. This document predates the **#145** memory-channel-layout correction and the **Workstream B/C** follow-up (**PRs #160–#164**). The "Karuna/Boundary equilibrium" framing and `metta_warmth` language here are **historical**. *Current observer semantics*: post-#145 the dominant token is `phase_boundary` (the pre-fix `karuna_relief` dominance was a mislabelled-channel artefact); `metta_warmth` is now status `diagnostic_only` (removed from the classification cascade, surfaced as `warmth_max`/`warm_cell_count` diagnostics); `phase_boundary` is radius/lens-specific; and routing occupancy (`active_vocabulary_occupancy`) is reported separately from full historical vocabulary occupancy. **Canonical current docs**: `PHASE_19_PR4_CALIBRATION_SUMMARY.md` §3, `docs/WORKSTREAM_B_*.md`, `docs/WORKSTREAM_C_VOCABULARY_STATUS_REVIEW.md`.

> *"The current `karuna_relief` / `phase_boundary` saturation might be a stable attractor. It might also be a threshold/cascade artefact. Treat it as hypothesis, not conclusion."* — Jack
>
> *"Treat saturation as the first real research result, not a bug. The question is which of model state, sampling, thresholds, cascade order, and missing temporal context caused the collapse."* — AURA
>
> *"Useful intuition pumps from Gaussian Splatting, fungal networks, and the Oberth effect — but their mathematical content doesn't transfer mechanically. The design doc partitions framings into 'operationalized as metrics' vs 'interpretive scaffolding.'"* — 84

This doc takes those three positions and asks: *what metrics, computed offline from `nextness_runs.jsonl` and successive Medusa snapshots, could turn the conceptual claims into falsifiable measurements?*

## 1. Scope and remit

PR #3 is **strictly Lane B**. It does not touch the engine, does not propose tuning actions, does not consume ZMQ, does not expose HTTP endpoints, does not create a dashboard. It computes derived metrics on top of the JSONL log that PR #2 (`process_snapshot`) already emits, and extends the per-snapshot JSONL record with additional measurements that are cheap to compute at observation time.

### Explicit non-goals
- ❌ Engine code modification.
- ❌ Vocabulary redesign or threshold tuning (deferred to PR #4).
- ❌ Memory-channel layout verification (deferred to PR #4 acoustic-map cross-validation).
- ❌ Closed-loop tuning proposals.
- ❌ Real-time dashboards or visualization.
- ❌ HTTP, ZMQ, network egress of any kind.
- ❌ `trust_remote_code=True` or executable model loading.
- ❌ Any change to `scripts/continuous_evolution_ca.py` or `medusa_start.py`.

### What lands in PR #3
1. Four additional fields in the per-snapshot JSONL entry produced by `process_snapshot()` (cheap to compute on data the observer already has loaded).
2. A new module `scripts/nextness_metrics.py` for across-snapshots metrics (distribution drift, boundary persistence, CCI interpretive scoring).
3. A CLI entry point that consumes an existing `nextness_runs.jsonl` log and emits a derived `nextness_run_metrics.jsonl` (one row per snapshot pair, plus an aggregate summary row).
4. Tests for every new metric, including golden-file tests using the existing playground snapshot.

## 2. Motivation — what we learned from the first real offline run

The PR #138 first-real-pass results (documented in issue #139) showed:

- Vocabulary occupancy 0.125 (only `karuna_relief` and `phase_boundary` fired)
- VOID/COMPUTE balance at 47.14% / 46.01% — near-perfect two-phase symmetry
- Wall time 1.02s on 32,768 patches at stride 8 — ~16× under the conservative budget

A single snapshot tells us the *state space* once. It does not tell us whether that distribution is:
- **A stable attractor** — the system has settled into the basin and small perturbations return to it.
- **A slow transient** — the system is passing through this distribution on the way to something else.
- **A classifier artefact** — the distribution is an artefact of stride sampling, threshold settings, or cascade ordering, and would shift dramatically under different observer parameters.

**The only way to discriminate these three is time-series.** PR #3 is the instrument that makes time-series interpretation possible.

## 3. Per-snapshot metrics (extends `process_snapshot()`)

Four new fields added to the JSONL entry already produced by PR #138, plus explicit preservation of the existing `vocabulary_occupancy` field as a top-level diagnostic. All five are computed from data that `process_snapshot()` has already loaded into memory; no additional snapshot reads.

### 3.0 Preserved + promoted from PR #138: `vocabulary_occupancy`

Already emitted by `process_snapshot()` (PR #138):

$$O_{\text{vocab}} = \frac{|\{i : N_i > 0\}|}{K}$$

where $K = |\text{TOKEN\_NAMES}|$. Range $[0, 1]$.

- **JSONL field**: `vocabulary_occupancy` (unchanged from PR #138).
- **Why it's listed here**: vocabulary occupancy was central to issue #139's findings discussion (the 0.125 value drove the whole "two-token saturation" conversation). Calling it out explicitly in PR #3 ensures it stays a first-class diagnostic alongside the four new metrics, rather than getting overlooked as "implicit in `token_counts`."

### 3.1 Shannon entropy of token distribution

$$H = -\sum_{i \in \text{TOKENS}} p_i \log_2(p_i)$$

where $p_i$ is the observed frequency of token $i$ (count / total_classified) and the convention $0 \cdot \log_2(0) = 0$ applies.

- **Range**: $[0, \log_2(K)]$ where $K = |\text{TOKEN\_NAMES}| = 16$, so $H \in [0, 4]$ bits.
- **JSONL field**: `shannon_entropy_bits`.

### 3.2 Normalized entropy

$$H_{\text{norm}} = \frac{H}{\log_2(K)}$$

- **Range**: $[0, 1]$. Easier to compare across runs with different vocabulary sizes (e.g. if PR #5 introduces the 512-token learned vocabulary).
- **JSONL field**: `entropy_normalized`.

### 3.3 VOID/COMPUTE balance

$$B_{\text{V/C}} = \frac{2 \cdot \min(P_{\text{VOID}}, P_{\text{COMPUTE}})}{P_{\text{VOID}} + P_{\text{COMPUTE}}}$$

where $P_{\text{VOID}}$ and $P_{\text{COMPUTE}}$ are the raw cell-state frequencies (not token frequencies).

- **Range**: $[0, 1]$. $B_{\text{V/C}} = 1$ iff $P_{\text{VOID}} = P_{\text{COMPUTE}}$; $B_{\text{V/C}} \to 0$ as one state dominates.
- **Rationale**: captures the Sakana "coexistence axis" using the two cell states that dominate the mature lattice. For gen 1,621,779: $P_{\text{VOID}} = 0.4714, P_{\text{COMPUTE}} = 0.4601 \implies B_{\text{V/C}} = 0.988$.
- **JSONL field**: `void_compute_balance`.

### 3.4 Boundary rate

$$R_{\text{boundary}} = \frac{N_{\text{phase\_boundary}}}{\sum_i N_i}$$

- **Range**: $[0, 1]$. Just `phase_boundary`'s count normalized to total classified patches.
- **Rationale**: promotes the single most-architecturally-important token to a top-level field for fast time-series scans. Already implicit in `token_counts` but explicit here.
- **JSONL field**: `boundary_rate`.

**Implementation note**: all four fields are dataclass-friendly floats. Total CPU cost on a 32,768-patch run: ~50 µs. Negligible.

## 4. Across-snapshots metrics (`scripts/nextness_metrics.py`)

A separate module that consumes an existing `nextness_runs.jsonl` and computes pairwise + windowed metrics. Output written to a sibling file `nextness_run_metrics.jsonl`. Each output row corresponds to a snapshot pair `(t-1, t)`, with one final row carrying aggregate diagnostics for the run.

### 4.1 KL divergence (informative, not symmetric)

$$D_{\text{KL}}(P_{t-1} \| P_t) = \sum_{i : P_{t-1}(i) > 0} P_{t-1}(i) \log_2 \frac{P_{t-1}(i)}{P_t(i)}$$

- **Smoothing**: tokens with zero count in $P_t$ but nonzero in $P_{t-1}$ are handled via additive (Laplace) smoothing with $\epsilon = 10^{-6}$ before normalization. Documented; tunable; not a free parameter that masks structure.
- **Smoothing-and-normalization algorithm** (per Jack's audit): the smoothed probability vector is built by iterating over `TOKEN_NAMES` in canonical order, adding $\epsilon$ to each slot (whether the token fired or not), and then dividing by the resulting sum so each vector totals to 1.0. Pseudocode:
  ```python
  def smoothed_distribution(counts: dict[str, int], eps: float) -> list[float]:
      raw = [counts.get(tok, 0) + eps for tok in TOKEN_NAMES]
      total = sum(raw)
      return [v / total for v in raw]
  ```
  This makes the KL computation independent of dict iteration order or how the caller constructed `counts`.
- **Use case**: directional — "how surprised is yesterday's distribution by today's?"
- **JSONL field**: `kl_divergence_bits`.

### 4.2 Jensen-Shannon divergence (symmetric, bounded, primary)

$$M = \frac{P_{t-1} + P_t}{2}, \quad D_{\text{JS}}(P_{t-1}, P_t) = \frac{1}{2} D_{\text{KL}}(P_{t-1} \| M) + \frac{1}{2} D_{\text{KL}}(P_t \| M)$$

- **Range**: $[0, 1]$ bits when computed with $\log_2$.
- **Use case**: the **canonical** distribution-drift metric for time-series. Symmetric, bounded, no division-by-zero risk, well-defined for any pair of probability vectors over the same support.
- **JSONL field**: `js_divergence_bits`.

### 4.3 Boundary persistence

Pairwise:

$$\pi_{\text{boundary}}(t-1, t) = 1 - \frac{|R_{\text{boundary}}(t) - R_{\text{boundary}}(t-1)|}{\max(R_{\text{boundary}}(t-1), R_{\text{boundary}}(t), \delta)}$$

with $\delta = 10^{-3}$ to avoid singularities when both rates are near zero.

- **Range**: $[0, 1]$. High = the boundary rate is stable across the pair; low = volatile.
- **JSONL field**: `boundary_persistence_pairwise`.

Aggregate (across full run window of $N$ snapshots) — per Jack's audit, emitted as **two** fields rather than one collapsed score:

**Raw coefficient of variation** (diagnostic, unbounded):

$$\text{CV}_{\text{boundary}} = \frac{\sigma(R_{\text{boundary}})}{\mu(R_{\text{boundary}}) + \delta}$$

- **Range**: $[0, \infty)$. CV $= 0$ means constant rate; CV $\geq 1$ means standard deviation exceeds mean (the original formula's failure case at rates like $[0, 0.5, 0, 0.5, 0]$ where $\mu = 0.2, \sigma \approx 0.245$).
- **Use case**: raw diagnostic for analysts who want the underlying signal, not the clamped readability score.
- **JSONL field** (in run-aggregate row): `boundary_cv`.

**Clamped persistence score** (readable, bounded):

$$\Pi_{\text{boundary,clamped}} = \max(0, 1 - \text{CV}_{\text{boundary}})$$

- **Range**: $[0, 1]$. Genuinely bounded; equals 1 when boundary rate is constant; equals 0 when CV ≥ 1 (volatile / drifting).
- **Use case**: time-series plots and CCI-adjacent summaries that want a single number on a comparable scale.
- **JSONL field** (in run-aggregate row): `boundary_persistence_aggregate_clamped`.

Emitting both keeps the diagnostic CV available without losing the readable score. Analysts can use either or both.

### 4.4 Coexistence–Crystallization Index (CCI)

This is the operational version of AURA's three-regime framing (mixing / crystallization / coexistence). It is **a scoring function, not a classifier** — the design doc deliberately does not commit to thresholds. Calibration is a PR #4 question.

$$\text{CCI}(t) = B_{\text{V/C}}(t) \cdot R_{\text{boundary}}(t) \cdot (1 - H_{\text{norm}}(t))$$

- **Range**: $[0, 1]$. Each factor is in $[0, 1]$; product is in $[0, 1]$.
- **Interpretation guide** (post-hoc empirical, to be confirmed via multi-snapshot runs):
  - **High CCI** (e.g. $> 0.3$): high VOID/COMPUTE balance + high boundary rate + low entropy = balanced two-phase structure with active boundaries and concentrated token distribution. *Candidate "stable coexistence."*
  - **Low CCI from low $H_{\text{norm}}$ + low $R_{\text{boundary}}$**: distribution is concentrated but boundaries have collapsed. *Candidate "crystallized / hard-separated."*
  - **Low CCI from high $H_{\text{norm}}$**: distribution is spread over many tokens. *Candidate "mixing / soup."*
- **JSONL field**: `coexistence_crystallization_index`.

**Audit caveat (Jack-shaped):** the CCI compresses three numbers into one. The three components $(B_{\text{V/C}}, R_{\text{boundary}}, H_{\text{norm}})$ are all preserved in the JSONL alongside the CCI itself, so analysts can recompute, re-scatter, or use the 3-component point directly without trusting the composite. The CCI is a convenience for time-series plots, not a regime claim.

**For gen 1,621,779** (single data point, illustrative only):
- $B_{\text{V/C}} = 0.988$
- $R_{\text{boundary}} = 0.422$
- $H_{\text{norm}} = 0.246$ (from $H = 0.983$ bits at 2 firing tokens)
- $\text{CCI} = 0.988 \cdot 0.422 \cdot 0.754 = 0.314$

Whether 0.314 means "coexistence" or "crystallization on the way to mixing" requires *more snapshots*, not more interpretation.

### 4.5 Aggregate run summary (final row)

The last row of `nextness_run_metrics.jsonl` is a special entry containing:

- `summary_type: "run_aggregate"`
- `n_snapshots: N`
- `mean_js_divergence_bits`, `std_js_divergence_bits` — how much does the token distribution typically drift between adjacent snapshots?
- `mean_cci`, `std_cci` — average regime score and its volatility
- `boundary_cv` — raw coefficient of variation of the boundary rate across the run
- `boundary_persistence_aggregate_clamped` — clamped readable score $\max(0, 1 - \text{CV})$
- `min_cci`, `max_cci`, `argmin_cci_snapshot`, `argmax_cci_snapshot` — endpoints for diagnostic drill-in

## 5. Module structure proposal

```
scripts/
├── nextness_observer.py        (existing; gains 4 new per-snapshot fields in process_snapshot)
└── nextness_metrics.py         (NEW)
    ├── token_distribution(entry) -> dict[str, float]
    ├── kl_divergence(p, q, smoothing=1e-6) -> float
    ├── js_divergence(p, q, smoothing=1e-6) -> float
    ├── boundary_persistence_pairwise(r1, r2, delta=1e-3) -> float
    ├── boundary_persistence_aggregate(rates, delta=1e-3) -> float
    ├── cci(balance, boundary, entropy_norm) -> float
    ├── compute_run_metrics(log_path, out_path) -> dict
    └── main()                    (CLI entry: python -m scripts.nextness_metrics)
```

**CLI surface** (proposed):

```
python -m scripts.nextness_metrics \
    --log data/nextness_log/nextness_runs.jsonl \
    --out data/nextness_log/nextness_run_metrics.jsonl \
    [--smoothing 1e-6] \
    [--boundary-delta 1e-3]
```

The CLI reads a JSONL log, computes pairwise + aggregate metrics, writes derived JSONL. Idempotent: re-running on the same input produces the same output. No state outside the file system, no network, no engine touch.

## 6. Test plan

### Unit tests
- `test_shannon_entropy_*` — uniform distribution → $\log_2(K)$, single-token concentration → 0, intermediate cases verified against scipy-equivalent reference values.
- `test_kl_divergence_*` — identical distributions → 0; orthogonal distributions → finite via smoothing; symmetry violation (KL is not symmetric) confirmed.
- `test_js_divergence_*` — identical → 0; orthogonal → $\log_2(2) = 1$ bit; symmetry $D_{\text{JS}}(P, Q) = D_{\text{JS}}(Q, P)$ confirmed.
- `test_boundary_persistence_pairwise_*` — identical rates → 1.0; rate jumping 0 → 1 → 0.0; series with high variance vs low variance gives correct ordering.
- `test_boundary_cv_*` — constant series → CV = 0; high-volatility series (rates like `[0, 0.5, 0, 0.5, 0]`) → CV ≥ 1 (the original-formula failure case).
- `test_boundary_persistence_aggregate_clamped_*` — constant series → 1.0; CV ≥ 1 series → 0.0 (clamp engages); intermediate series → matches `1 - CV` exactly.
- `test_cci_*` — $\text{CCI} = 0$ if any factor is 0; $\text{CCI} = 1$ iff all three factors are 1; monotonicity in each component.

### Integration tests
- `test_compute_run_metrics_two_snapshots` — minimal two-snapshot JSONL → emits one pairwise row + one aggregate row with correct fields.
- `test_compute_run_metrics_identical_snapshots` — two identical entries → JS divergence $= 0$, boundary persistence $= 1$, CCI unchanged.
- `test_compute_run_metrics_idempotent` — running twice on the same input produces byte-identical output. Explicitly verifies no fresh `generated_at` timestamp is present and that input ordering follows `(generation, filename, source_timestamp)`.
- `test_compute_run_metrics_deterministic_sort` — feeds the same snapshots to the orchestrator in three different input orderings (mtime-ascending, reverse-mtime, shuffled) and asserts byte-identical output across all three.

### Golden-file test
- A captured `nextness_runs.jsonl` with 5 synthetic but plausible entries → known-good `nextness_run_metrics.jsonl`. Locks the metric arithmetic against silent regressions.

### Process-snapshot extension tests
- `test_process_snapshot_emits_shannon_entropy` — verifies the new field is present, type-checks, range-checks.
- Same for `entropy_normalized`, `void_compute_balance`, `boundary_rate`.

**Expected test count after PR #3**: ~73 (current `test_nextness_observer.py`) + ~18 new tests = ~91 tests in the Nextness Observer test suite. Total project test suite: ~272.

## 7. Interpretive vs operational — partitioning the metaphors

Per Jack's audit caution and 84's audit-hat-on engineering note, the design doc explicitly partitions the framings inherited from AURA's Sakana drop:

### Operationalized as metrics in PR #3
- **3-regime interpretive framing (mixing / crystallization / coexistence)** → CCI scoring function + the three-component vector $(B_{\text{V/C}}, R_{\text{boundary}}, H_{\text{norm}})$. *Not* a classifier; no hard regime thresholds in PR #3.
- **Boundary persistence** → pairwise persistence per snapshot pair, plus aggregate raw `boundary_cv` and clamped score $\Pi_{\text{boundary,clamped}}$ in the run summary
- **Distribution drift** → JS divergence between adjacent snapshots
- **Vocabulary occupancy over time** → `vocabulary_occupancy` preserved from PR #138, plus new entropy and normalized entropy fields
- **Fungal-network "growth at active boundary"** → `boundary_rate` as a first-class field

### Interpretive scaffolding (useful intuition; not computed against)
- **Gaussian Splatting**: motivates the "extract representative samples" intuition but the mathematical content (implicit-to-explicit field conversion) doesn't apply to our explicit-lattice patches. Held as metaphor, not derivation.
- **Oberth effect**: motivates the "intervene at the right moment" intuition but kinetic-energy-multiplication-at-periapsis is not a transferable mechanism. PR #4+ may define an analogous "high-leverage observation window" but it will be operationalized from data, not derived from orbital mechanics.
- **Quantum-gravity plaquette**: motivates the "microscopic measurement of universe-scale fluctuation" intuition but the lattice-gauge-theory machinery doesn't transfer; Medusa is a classical discrete dynamical system.
- **Plasma-flash crystallization**: motivates the "stable state emits localized signature" intuition but plasma physics isn't a derivation here.

### Why this partition matters
Future PRs that consume PR #3 outputs (PR #4 calibration, PR #5 learned embedding) need to know which framings are *metrics they can compute against* and which are *intuition pumps for human reviewers*. Conflating the two leads to "we measured Fokker-Planck coefficients" claims that aren't supported by what the code actually computed.

## 8. What this PR does NOT decide

Deliberately deferred to **PR #4** (calibration), not part of PR #3 scope:

- Threshold tuning (`THRESHOLD_COMPASSION`, etc.)
- Vocabulary cascade order changes
- Memory-channel layout verification against Phase 14e acoustic map
- Stride sweep / sampling-resolution experiments
- Cascade ablation studies
- CCI threshold definitions for "this snapshot IS in coexistence regime"

Deliberately deferred to **PR #5+**:

- Learned 512-token embedding vocabulary
- Multi-snapshot temporal feature engineering inside the classifier (the classifier remains spatial-state-plus-memory in PR #3; temporal context is added via the across-snapshots metrics, not via re-architecting the classifier)
- Importance sampling / dense sampling implementations

Deliberately deferred to **Lane A** (engine track, separately scoped, currently parked):

- Engine-state perturbation experiments (would require touching `continuous_evolution_ca.py`)
- Closed-loop tuning proposals to `tuning_pending.json`
- Any change to Medusa's update rule, memory grid, or lattice size

## 9. Scope guarantees (carried forward from PR #138 + PR #140)

- ✅ No engine touch. Medusa untouched.
- ✅ No writes outside `log_directory` (the new metrics file is a sibling of `nextness_runs.jsonl` inside the same `log_directory`).
- ✅ No HTTP. No ZMQ. No network.
- ✅ CPU-only default.
- ✅ `WriteOutsideLogDirError` continues to gate all writes via realpath check.
- ✅ `allow_pickle=False` preserved in any new snapshot reads (the metrics module reads JSONL, not `.npz`, so this is N/A for the new module, but is preserved in `process_snapshot()` extensions).
- ✅ Bounded compute (the metrics module is $O(N \cdot K)$ where $N$ is number of snapshots and $K$ is vocabulary size). ~~both are small~~ — the smallness of $N$ was an **unenforced assumption** until the 2026-07-18 input-work-bounds amendment: $N$ is now enforced per invocation (§9.5); $K$ is fixed by the vocabulary.

### 9.1 Output-boundary hardening (2026-07-15 reliability amendment)

Two gaps in the original write lane were repaired after the Nextness
NP-stack established the house convention for derived-output safety
(`os.path.samefile` identity guards in NP6/NP8; explicit byte output
in NP5/NP6/NP8, later NP1):

- **Input-identity guard**: `--out` may never name or alias the input
  log — refused by resolved-path equality (direct path, lexical
  variants like `sub/../log.jsonl`, symlink aliases) and by file
  identity (`os.path.samefile` on resolved paths, catching hard
  links), failing closed when an existing output's identity cannot be
  verified. The refusal keeps the existing boundary convention (exit
  code 3, one `safety error:` line, `WriteOutsideLogDirError`) and
  happens before the log is read, any metric computed, or any output
  parent created. Ordinary sibling outputs — nonexistent or existing
  non-alias — remain allowed.
- **Byte-exact streamed output**: the derived JSONL is written in
  binary mode, one row at a time — each line is its canonical
  `json.dumps(..., sort_keys=True, default=str)` serialization encoded
  as UTF-8 plus a single LF byte. Windows text-mode newline
  translation can no longer alter the derived file's bytes, so
  re-runs are byte-identical across platforms. Streaming is
  preserved: the output is never materialized in full.
- **Directory-target refusal**: an `--out` that resolves to an existing
  directory (including through a symlink) is refused in the same exit-3
  boundary lane, before the log is read or any metric computed — the
  binary open would otherwise escape as an uncaught
  `IsADirectoryError`/`PermissionError` traceback after computation.
  Ordinary non-alias *file* targets are unaffected.
- **Residual race, stated precisely**: identity is verified at
  validation time; the write does not re-verify. A concurrent actor
  replacing the output path between validation and write can still
  redirect the write. The guard defends against aliases that exist at
  validation time; it does not claim to eliminate the
  validation-to-write (TOCTOU) interval.

All metric formulas, row ordering, JSON field ordering, the stdout
summary and every exit code are unchanged by this amendment.

### 9.2 Operational output-write failure lane (2026-07-17 reliability amendment)

The 2026-07-17 CLI failure-contract audit reproduced (twice, public CLI)
an escaped `PermissionError` traceback when `--out` named an existing
**read-only file** inside the log directory: every pre-write safety
check legitimately passed, and the binary `open("wb")` then failed with
no handler — crashing at process exit 1, numerically colliding with the
missing-log lane. Repaired by a **narrowly typed** lane, and recorded
here as metrics-specific truth (this is not harmonisation with any
other module's map):

- `OSError` is caught **only around the output region — output-parent
  creation plus the binary open/write/close** — inside
  `compute_run_metrics`, where it becomes the typed
  `MetricsOutputWriteError` with a concise path-specific message.
  Read-side or computation errors are **never** reclassified as output
  failures and continue to propagate loudly.
- The CLI maps `MetricsOutputWriteError` to **exit 4** with one
  `error:` line — deliberately distinct from **exit 3 + `safety
  error:`** (pre-write containment/identity/directory safety refusal),
  **exit 2** (data/validation), and **exit 1** (missing log, now also
  documented). Complete map: 0 success · 1 missing log · 2
  data/validation · 3 pre-write safety refusal (`safety error:`) · 4
  operational output-write failure (`error:`).
- **Destination-preservation contract, stated precisely**: a failure at
  or before the binary open — a read-only destination, or a failed
  output-parent mkdir — leaves any existing destination byte-identical
  (nothing was truncated) and creates no output. Once the binary open
  has succeeded, output is direct, streamed and **non-atomic**: a later
  write or close failure may leave a truncated or partial destination,
  and **no general destination-preservation guarantee is made or
  implied**. In the exercised failure lanes, and absent the documented
  validation-to-write replacement race (§9.1), the input log remains
  unchanged. This repair adds no stronger input-log guarantee: a
  concurrent actor may still redirect the later direct write, as the
  existing TOCTOU non-claim states.
- Streaming binary LF-only output, row order, field order, formulas,
  aggregate values, ordinary sibling-overwrite behavior, and the
  documented validation-to-write (TOCTOU) non-claim are all unchanged.
  No atomic-write behavior was introduced.

### 9.3 Typed input boundary (2026-07-18 metrics pilot)

Recorded here as metrics-specific truth (not harmonisation with any
other module's map): the CLI's **exit-2 catch is exactly the typed
`MetricsInputError` plus the `FileNotFoundError` validation-to-read race
lane** (the pre-checked missing-log lane remains exit 1). The five
genuine input/configuration raises carry the typed class with their
message text byte-identical: malformed JSONL (the `json.JSONDecodeError`
wrapper), negative smoothing, **the existing negative-rate guard in
`boundary_persistence_pairwise`**, non-positive pairwise delta, and
non-positive CV delta. A plain `ValueError` — like
any exception outside the documented catch classes — **propagates**
rather than being reported as a concise data failure (test-pinned
alongside the standing read-side-OSError propagation pin). Locally
handled `_safe_float` coercion and the containment-to-
`WriteOutsideLogDirError` conversion are untouched. `MetricsInputError`
is exported through `__all__`. Direct-Python note: callers catching
`ValueError` remain compatible because `MetricsInputError` subclasses
it, but exact class identity, repr and traceback text change at the five
reclassified sites. Exit codes, messages, output bytes and the §9.1/§9.2
contracts are unchanged.

**Invalid-UTF-8 input lane (post-pilot restoration)**: the typed
narrowing initially let `UnicodeDecodeError` (a `ValueError` subclass)
escape on an undecodable `--log` — pre-pilot the broad catch reported it
as concise exit 2. Restored by a **narrow wrapping boundary** around the
input-log text-reading region only: `except UnicodeDecodeError` exactly
(never `UnicodeError`/`ValueError`/`OSError`), re-raised as
`MetricsInputError(str(e))` with the original error as `__cause__`, so
the public stderr bytes match the pre-pilot lane byte-for-byte and
read-side `OSError` propagation is untouched. The typed lane therefore
comprises the **five existing direct typed raises plus this one
invalid-UTF-8 wrapping boundary**. This is a **restoration of an
undocumented behavior changed by the pilot**, not a new family-wide
convention.

**Separate observation — `boundary_cv` rate validation (recorded, not
changed here)**: `boundary_cv` currently performs **no**
non-negative-rate validation of its own — direct calls may accept
negative rates or reach an invalid denominator, and a one-entry CLI log
bypasses the pairwise guard entirely (no pair row is computed, so the
`boundary_persistence_pairwise` guard never runs). This is a **future,
independently gated behavior candidate**: adding validation would be a
separately observable production/API change. It is **not a defect
repaired by the typed-boundary pilot** and no `boundary_cv` production
behavior changed in it.

### 9.4 Strict input domain (2026-07-18, Kev-authorized policy)

Recorded as metrics-specific policy (not harmonisation). Every rejection
below is typed `MetricsInputError` → exit 2, one `error:` line, no
traceback, input and any pre-existing destination byte-identical, no new
destination.

- **JSON constants**: `NaN`, `Infinity`, `-Infinity` are rejected at
  decode (`parse_constant` hook) — in **any** field of any row.
- **Unit fields** (`void_compute_balance`, `boundary_rate`,
  `entropy_normalized`), when present: real JSON numbers (booleans
  excluded), finite, within `[0, 1]`. Explicit `null`, numeric strings
  and all other non-numeric values are rejected. **An absent unit field
  is `0.0` — an explicitly chosen compatibility policy established
  HERE**; PR #141 never documented default-on-failure, and `_safe_float`
  is retained only as the realization of this absent-field policy behind
  the validation gate.
- **`token_counts`**, when the key is present: a JSON object of
  non-boolean, non-negative integer counts (the shape the canonical
  distributions consume). Rows must be JSON objects.
- **Numeric parameters**: `smoothing` finite and non-negative;
  `boundary_delta` finite and strictly positive (validated before any
  read work).
- **Public boundary helpers hardened consistently** (`pairwise`,
  `boundary_cv`, `aggregate_clamped`): out-of-type and out-of-domain
  rates and invalid deltas raise `MetricsInputError`, validated
  **before** single-element early returns — closing the direct-API
  `TypeError`/`ZeroDivisionError`/negative-CV/sign-flip escapes. The
  aggregate now carries an explicit two-sided clamp (a no-op for valid
  input; results for the valid domain are unchanged).
- **Pre-write invariant + strict serialization**: before parent-mkdir/
  open, every float in every output row — computed AND pass-through,
  **recursively through nested built-in containers** (e.g. a
  numeric-overflow `generation` such as `1e400` → `inf`, or an `inf`
  nested inside a pass-through list) — must be finite, with the
  rejection naming the offending output key/path. The traversal is
  hook-safe (exact built-in `dict`/`list`/`tuple` and exact `float`
  only). The writer serializes with `allow_nan=False` as a backstop
  (unreachable given the invariant; a failure there is an internal
  contract failure and propagates loudly). This adds **no partial-output
  claim** and leaves the §9.2 streamed, non-atomic write contract for
  genuine write failures unchanged.
- **Finite-computability of counts**: a token count too large to
  participate in finite float arithmetic is a typed rejection at
  ingestion (no arbitrary semantic cap — the constraint is numeric
  computability); the smoothed raw vector and its total are also
  guarded against non-finite arithmetic.
- **Zero smoothing, defined semantics**: `smoothing >= 0` remains the
  authorized policy; KL with positive support in P and zero support in
  Q under zero smoothing is mathematically undefined and raises a
  typed, concise `MetricsInputError` stating that positive smoothing is
  required (direct and public pins).
- **Located constant rejections**: the NaN/Infinity refusal is wrapped
  at the decode call site with the exact log path and line number
  (`invalid JSON value at <path>:<line>: …`, cause preserved) — a valid
  JSON extension token refused by policy, never mislabeled an ordinary
  `JSONDecodeError`.
- **Finite-computability totality (2026-07-18 follow-up)**: the late
  Codex finding on the merged strict domain — a raw oversized INTEGER
  (magnitude `10**400`) on the unit-field, helper (`_require_rate`/
  `_require_delta`), smoothing or boundary-delta surfaces reached
  `float()`/`math.isfinite()` and escaped as `OverflowError`. Closed by
  one narrow conversion path (`_finite_float`): types are rejected
  exactly as before; accepted ints/floats convert catching only the
  expected conversion `OverflowError`; `math.isfinite` applies only
  after safe conversion; the smoothed raw vector/total guard uses the
  same path so `smoothed_distribution` cannot leak `OverflowError` from
  huge counts with integer-zero smoothing. **This is finite-
  computability totality, not a semantic value cap** — no magnitude
  limit is invented; messages, strict JSON, absent-field 0.0, output
  bytes, exit codes, failure classification and write/preservation
  contracts are unchanged.
- **Decoder conversion-limit boundary (distinct from materialized huge
  integers)**: `_finite_float` repairs integers that have already
  MATERIALIZED as Python values; a valid JSON integer literal beyond
  Python's decimal-digit conversion limit (>= ~4300 digits) makes the
  DECODER itself raise `ValueError` before any value exists. That is
  translated at the narrow `json.loads` boundary only — located
  `malformed JSONL at <path>:<line>` with the original as `__cause__`.
  `main()` and the computation catches are NOT broadened; the
  post-validation internal plain-`ValueError` sentinel still propagates
  (pinned). No arbitrary application-level magnitude cap exists on
  either lane.
- **Parser depth boundary**: a JSONL row nested beyond the parser's
  recursion limit (inside the byte ceiling) is a located typed
  rejection at the same narrow decode seam (`malformed JSONL at
  <path>:<line>: nesting exceeds the parser's depth limit`) — metrics
  is fatal-typed, not row-contained. `RecursionError` outside the
  decode seam is not swallowed anywhere and still propagates.
- **Message origins**: the negative-rate / smoothing / delta rejection
  messages now originate at the ingestion/parameter seam with
  strict-domain wording; the old helper-origin messages are subsumed
  (codes and one-line shape unchanged).
- **Byte compatibility**: accepted historical fixtures and ordinary
  valid logs produce byte-identical output (golden + determinism pins).
- ~~Recorded residual: zero-smoothing `ZeroDivisionError`~~ — **closed
  by this policy's hardening round**: the formerly escaping crash is now
  the typed zero-smoothing rejection above.

### 9.5 Input-work bounds (2026-07-18, Jack policy decision; Kev-authorized)

The input-work-bounds audit found metrics was the only CLI in the
family with no ingestion bounds — §9's "both are small" was a
documented assumption with nothing enforcing it. Per Jack's policy
decision, metrics now enforces explicit per-invocation JSONL bounds:

- **Defaults and ceiling**: `--max-rows` default **100,000** with a
  hard parameter ceiling of **1,000,000**; `--max-line-bytes` default
  **65,536** (any positive integer). Both are validated typed BEFORE
  any input reading; both pass from `main()` into
  `compute_run_metrics` (direct-Python callers get the same defaults).
- **What is counted**: bounds apply to **raw physical JSONL records** —
  blank and rejected records consume row budget alike. Line size is
  measured in **raw bytes with the LF or CRLF terminator excluded**.
- **Enforced before unbounded materialization**: the log is read in
  binary with bounded `readline(max_line_bytes + 2)` probes, so an
  oversized record is never materialized in full and never drained
  past; the offending record is refused before it is decoded or
  validated.
- **Excess rows are a typed refusal, not prefix truncation**: unlike
  the predictor's truncating row budget (a prediction can honestly use
  a prefix), metrics summarizes a COMPLETE run — silently producing
  metrics from a prefix would misrepresent a complete-run result, so
  an input with more than `max_rows` physical records is a located
  `MetricsInputError`.
- **Exit code unchanged**: bounds refusals ride the existing concise
  exit-**2** data lane (one `error:` line, no traceback; input and any
  pre-existing destination preserved byte-for-byte, absent destination
  stays absent).
- **Accepted-input behavior unchanged**: the metrics/output schema and
  deterministic bytes for in-bound inputs are byte-identical to
  pre-repair main (`4fa0f458`, receipt-pinned in the suite).
- **No output-size ceiling is added** by this amendment: the derived
  JSONL remains un-ceilinged, as the failure-contracts table has
  always recorded.

This closes §9's previously unenforced "both are small" assumption.

## 10. Open questions for AURA + Jack

1. **CCI composition**: I've defined it as a product of three factors in $[0, 1]$. An alternative is a weighted geometric mean, $\text{CCI} = (B^{w_1} \cdot R^{w_2} \cdot (1-H)^{w_3})^{1/(w_1+w_2+w_3)}$. The product is simpler and has the right "any factor zero → CCI zero" property. Weighted GM lets us emphasize boundary rate over balance if calibration suggests we should. Recommend starting with the simple product; revisit in PR #4 if calibration shows it's miscalibrated.

2. **Smoothing constant** for KL divergence: $\epsilon = 10^{-6}$ is conservative. It allows tokens that fired once-per-million-patches to register as nonzero without dominating the divergence. AURA / Jack: any preference?

3. **Boundary-persistence aggregation window**: should the aggregate version operate on the full run, or on a rolling window of (say) 5 snapshots? The full-run version is simpler; the rolling-window version makes the metric responsive to phase transitions during the run. Recommend full-run for PR #3, add rolling-window in PR #4 if needed.

4. **Should `compute_run_metrics` output be deterministic?** Yes — and per Jack's audit the spec needs explicit determinism contracts to actually achieve byte-identical re-run output:
   - **Sort key for input snapshots**: `(generation, snapshot_filename, source_timestamp)` in that priority order. Generation is the primary key (it's monotonic and embedded in the data); filename is the deterministic tiebreaker; source timestamp from the snapshot itself (NOT a fresh `datetime.now()`) is the final fallback if neither prior key disambiguates.
   - **No fresh `generated_at` field in the metrics output.** A `generated_at: datetime.now().isoformat()` field — the kind of thing any sensible engineer would reach for — would break byte-identical re-run on every invocation. The metrics output carries source-data timestamps and generations only.
   - **Floating-point summation order**: deterministic via the canonical TOKEN_NAMES iteration order (see §4.1 KL pseudocode) and a single-pass accumulator. Catastrophic cancellation in entropy / KL sums is not a concern at our scale (16 tokens, counts $\leq 10^5$).

5. **Multi-snapshot observer mode**: PR #3 as currently scoped consumes an existing JSONL. To produce that JSONL across multiple snapshots, the operator can currently invoke `process_snapshot()` in a loop. Should PR #3 also add a `--snapshots-dir` / `--max-snapshots N` flag to `nextness_observer.py` for one-shot multi-snapshot runs? Or keep it as a separate concern? Recommend the latter (one-shot loop can be a 5-line shell script; PR #3 stays focused on metrics).

## 11. Proposed PR #3 implementation order

After AURA + Jack greenlight on this design doc:

1. Extend `process_snapshot()` with the four per-snapshot fields. Tests for each.
2. Implement `nextness_metrics.py` with the building-block functions (entropy, KL, JS, persistence, CCI). Unit tests for each.
3. Implement `compute_run_metrics` orchestrator. Integration tests.
4. Implement CLI. Manual smoke test against the existing playground JSONL (gen 1,621,779) plus 4 more sandboxed snapshots → produce the first real `nextness_run_metrics.jsonl`.
5. Add golden-file test.
6. Open PR #3 implementation against main.

Total expected diff: ~250 lines of code in `nextness_metrics.py`, ~30 lines of extension to `nextness_observer.py`, ~200 lines of tests. Should land cleanly.

---

**Approval requested from**: AURA (lead architect) — does the CCI composition + 3-regime mapping match your intent? Jack (auditor) — are the metric formulas, smoothing constants, and "interpretive vs operational" partition consistent with your scope concerns?

**Operator gate**: as always, Kevin holds the merge button.
