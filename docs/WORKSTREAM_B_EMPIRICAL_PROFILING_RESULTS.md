# Workstream B — Empirical Profiling Results

**Generated**: offline profiling over 5 newest snapshots.
**Snapshots**: v070_gen1738057_step17380574_20260530T192039.npz, v070_gen1738017_step17380172_20260530T191038.npz, v070_gen1737976_step17379768_20260530T190038.npz, v070_gen1737936_step17379365_20260530T185036.npz, v070_gen1737896_step17378962_20260530T184036.npz
**Patches at r=1**: 163,840 (stride=8, 3x3x3 = 27 cells/patch)
**Patches at r=2**: 163,840 (stride=8, 5x5x5 = 125 cells/patch)
**Guardrails**: Read-only analysis. No predicate changes. No engine touch. Lane A parked.

---

## 1. Global warmth channel statistics

Per-snapshot whole-lattice warmth channel (memory index 6):

| Snapshot | Sparsity | Min | Max | Mean (non-zero) | Non-zero count |
|---|---|---|---|---|---|
| v070_gen1738057_step17380574_20260530T192039.npz | 0.9900 | 0.009025 | 0.184211 | 0.023904 | 167,748 |
| v070_gen1738017_step17380172_20260530T191038.npz | 0.9900 | 0.009025 | 0.199884 | 0.023989 | 166,978 |
| v070_gen1737976_step17379768_20260530T190038.npz | 0.9901 | 0.009025 | 0.174000 | 0.023883 | 166,865 |
| v070_gen1737936_step17379365_20260530T185036.npz | 0.9900 | 0.009025 | 0.205474 | 0.023884 | 167,734 |
| v070_gen1737896_step17378962_20260530T184036.npz | 0.9900 | 0.009025 | 0.208023 | 0.023968 | 167,063 |

## 2. `metta_warmth` — patch-level warmth distributions (r=1)

### 2.1 Patch mean vs patch max

| Statistic | Patch mean | Patch max |
|---|---|---|
| Min | 0.000000 | 0.000000 |
| 25th percentile | 0.000000 | 0.000000 |
| Median | 0.000000 | 0.000000 |
| 75th percentile | 0.000000 | 0.000000 |
| 90th percentile | 0.000940 | 0.023005 |
| 95th percentile | 0.001481 | 0.030000 |
| 99th percentile | 0.002812 | 0.060000 |
| Max | 0.009469 | 0.188551 |
| Mean | 0.000240 | 0.005736 |

### 2.2 Firing rate curve — patch max at candidate thresholds

Current `THRESHOLD_WARMTH = 0.3` fires on `warmth_mean`. This table shows what fires on `warmth_max` at various candidate thresholds.

| Threshold | Firing rate (max) | Firing rate (mean) | Patches firing (max) |
|---|---|---|---|
| 0.05 | 2.5% | 0.0% | 4,174 |
| 0.06 | 1.0% | 0.0% | 1,646 |
| 0.07 | 0.7% | 0.0% | 1,067 |
| 0.08 | 0.4% | 0.0% | 584 |
| 0.09 | 0.1% | 0.0% | 197 |
| 0.10 | 0.1% | 0.0% | 141 |
| 0.11 | 0.0% | 0.0% | 72 |
| 0.12 | 0.0% | 0.0% | 30 |
| 0.13 | 0.0% | 0.0% | 17 |
| 0.14 | 0.0% | 0.0% | 11 |
| 0.15 | 0.0% | 0.0% | 5 |
| 0.16 | 0.0% | 0.0% | 2 |
| 0.17 | 0.0% | 0.0% | 1 |
| 0.18 | 0.0% | 0.0% | 1 |
| 0.19 | 0.0% | 0.0% | 0 |
| 0.20 | 0.0% | 0.0% | 0 |
| 0.30 (current) | 0.0% | 0.0% | 0 |

### 2.3 Warm-cell count per patch

Number of cells in each patch with warmth >= threshold:

| Metric | >= 0.05 | >= 0.10 | >= 0.15 |
|---|---|---|---|
| Mean per patch | 0.026 | 0.001 | 0.000 |
| Median | 0.000 | 0.000 | 0.000 |
| Max | 3 | 1 | 1 |
| Patches with >= 1 | 4,174 | 141 | 5 |
| Patches with >= 2 | 112 | 0 | 0 |

### 2.4 Cluster analysis (6-neighbour face adjacency)

Connected-component labelling of warm cells (warmth >= 0.10) per patch. Uses `scipy.ndimage.label` with default 6-neighbour face adjacency.

**Cluster size histogram** (AURA's 'Planck Star' knee search — architectural metaphor for localized density, not a physics claim):

| Cluster size | Count | Fraction of all clusters |
|---|---|---|
| 1 | 141 | 100.0% |

Total clusters found: 141
Patches with max cluster >= 2: 0 (0.0%)

**Max cluster size per patch:**

- Mean: 1.00
- Median (among patches with warmth): 1.0
- Max: 1

## 3. `DIVERSITY_BOUNDARY` / `phase_boundary` — entropy profiling

### 3.1 Distinct-state count distributions

| Distinct states | r=1 count | r=1 fraction | r=2 count | r=2 fraction |
|---|---|---|---|---|
| 1 | 0 | 0.0% | 0 | 0.0% |
| 2 | 25,572 | 15.6% | 32 | 0.0% |
| 3 | 69,436 | 42.4% | 2,488 | 1.5% |
| 4 | 55,130 | 33.6% | 35,883 | 21.9% |
| 5 | 13,702 | 8.4% | 125,437 | 76.6% |

**Current `phase_boundary` firing rate** (distinct_states >= 4):
- r=1: 42.0% (68,832 patches)
- r=2: 98.5% (161,320 patches)

### 3.2 Normalized entropy distributions

| Statistic | r=1 | r=2 |
|---|---|---|
| Min percentile | 0.2167 | 0.4161 |
| 10th percentile | 0.4268 | 0.5315 |
| 25th percentile | 0.4971 | 0.5593 |
| Median percentile | 0.5513 | 0.5891 |
| 75th percentile | 0.5976 | 0.6201 |
| 90th percentile | 0.6735 | 0.6474 |
| 95th percentile | 0.7106 | 0.6631 |
| 99th percentile | 0.7679 | 0.6965 |
| Max percentile | 0.9511 | 0.7941 |
| Mean | 0.5509 | 0.5894 |
| Std | 0.0892 | 0.0452 |

### 3.3 ROC-style threshold table (Jack's separability analysis)

For each candidate entropy threshold: r=1 firing rate, r=2 firing rate, and separation score (r=1 - r=2). Positive separation = the threshold preserves more r=1 firing while suppressing r=2.

| Entropy threshold | r=1 fires | r=2 fires | Separation (r1 - r2) | r=1 patches | r=2 patches |
|---|---|---|---|---|---|
| 0.10 | 100.0% | 100.0% | +0.000 | 163,840 | 163,840 |
| 0.15 | 100.0% | 100.0% | +0.000 | 163,840 | 163,840 |
| 0.20 | 100.0% | 100.0% | +0.000 | 163,840 | 163,840 |
| 0.25 | 100.0% | 100.0% | -0.000 | 163,837 | 163,840 |
| 0.30 | 100.0% | 100.0% | -0.000 | 163,774 | 163,840 |
| 0.35 | 99.9% | 100.0% | -0.001 | 163,619 | 163,840 |
| 0.40 | 97.8% | 100.0% | -0.022 | 160,223 | 163,840 |
| 0.45 | 83.4% | 99.9% | -0.166 | 136,566 | 163,754 |
| 0.50 | 74.0% | 97.5% | -0.235 | 121,276 | 159,809 |
| 0.55 | 51.4% | 80.6% | -0.292 | 84,192 | 132,068 |
| 0.60 | 24.3% | 41.3% | -0.170 | 39,868 | 67,722 |
| 0.65 | 12.8% | 8.7% | +0.041 | 20,935 | 14,173 |
| 0.70 | 5.6% | 0.8% | +0.048 | 9,126 | 1,284 |
| 0.75 | 1.9% | 0.0% | +0.019 | 3,138 | 62 |
| 0.80 | 0.4% | 0.0% | +0.004 | 683 | 0 |
| 0.85 | 0.1% | 0.0% | +0.001 | 94 | 0 |
| 0.90 | 0.0% | 0.0% | +0.000 | 10 | 0 |
| 0.95 | 0.0% | 0.0% | +0.000 | 1 | 0 |

### 3.4 Distribution overlap (AURA's separability metric)

**Overlap area between r=1 and r=2 entropy distributions: 0.4830**

(0.0 = perfectly separable, 1.0 = identical distributions. Lower is better for choosing a discriminating threshold.)

## 4. Answers to the profiling questions

The following answers are computed mechanically from the data above. Interpretation and candidate selection are for AURA + Jack + Kevin review.

**Q1: Does `warmth_max` fire too broadly?**
At threshold 0.10: 0.1%. At 0.15: 0.0%. At 0.20: 0.0%. Compare against target range of 5-15% for an informative-but-not-dominant predicate.

**Q2: Does count/cluster density fire too rarely?**
Patches with cluster >= 2 warm cells (face-adjacent): 0.0%. If this is below ~2%, the cluster candidate may be too restrictive at current sparsity.

**Q3: Is there a cluster-size knee?**
Fraction of clusters that are size 1 (isolated specks): 100.0%. A strong knee would show a clear gap between size-1 and size-2+ clusters. If nearly all clusters are size 1, the 'Planck Star' interpretation (AURA's metaphor) has weak empirical support at current sparsity.

**Q4: Does entropy separate r=1 from r=2?**
Best separation score: +0.048 at threshold 0.70. Overlap area: 0.4830. If best separation > +0.10, entropy is a meaningful improvement over raw count.

**Q5: Is there a defensible threshold range?**
No threshold satisfies r=1 >= 50% AND r=2 <= 80%. The distributions may overlap too heavily for entropy alone to fix the scale sensitivity.

---

**This document is evidence, not a decision.** Candidate selection requires AURA architectural review, Jack measurement audit, and Kevin's operator gate. No predicate behavior was changed. Lane A remains parked.

*— 84, profiling script run on 5 snapshots, 163,840 r=1 patches, 163,840 r=2 patches*