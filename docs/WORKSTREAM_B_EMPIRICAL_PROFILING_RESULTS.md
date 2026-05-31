# Workstream B — Empirical Profiling Results

**Generated**: offline profiling over 5 newest snapshots.
**Snapshots**: v070_gen1743056_step17430564_20260531T144155.npz, v070_gen1743014_step17430142_20260531T143154.npz, v070_gen1742970_step17429700_20260531T142153.npz, v070_gen1742929_step17429290_20260531T141151.npz, v070_gen1742887_step17428878_20260531T140150.npz
**Patches at r=1**: 163,840 (stride=8, 3x3x3 = 27 cells/patch)
**Patches at r=2**: 163,840 (stride=8, 5x5x5 = 125 cells/patch)
**Guardrails**: Read-only analysis. No predicate changes. No engine touch. Lane A parked.

---

## 1. Global warmth channel statistics

Per-snapshot whole-lattice warmth channel (memory index 6):

| Snapshot | Sparsity | Min | Max | Mean (non-zero) | Non-zero count |
|---|---|---|---|---|---|
| v070_gen1743056_step17430564_20260531T144155.npz | 0.9900 | 0.009025 | 0.193444 | 0.023892 | 167,131 |
| v070_gen1743014_step17430142_20260531T143154.npz | 0.9900 | 0.009025 | 0.215875 | 0.023977 | 167,350 |
| v070_gen1742970_step17429700_20260531T142153.npz | 0.9900 | 0.009025 | 0.196196 | 0.023850 | 167,929 |
| v070_gen1742929_step17429290_20260531T141151.npz | 0.9900 | 0.009025 | 0.166667 | 0.023867 | 167,082 |
| v070_gen1742887_step17428878_20260531T140150.npz | 0.9900 | 0.009025 | 0.172509 | 0.023890 | 167,397 |

## 2. `metta_warmth` — patch-level warmth distributions (r=1)

### 2.1 Patch mean vs patch max

| Statistic | Patch mean | Patch max |
|---|---|---|
| Min | 0.000000 | 0.000000 |
| 25th percentile | 0.000000 | 0.000000 |
| Median | 0.000000 | 0.000000 |
| 75th percentile | 0.000000 | 0.000000 |
| 90th percentile | 0.000940 | 0.022833 |
| 95th percentile | 0.001452 | 0.030000 |
| 99th percentile | 0.002795 | 0.059368 |
| Max | 0.008616 | 0.203421 |
| Mean | 0.000239 | 0.005730 |

### 2.2 Firing rate curve — patch max at candidate thresholds

Current `THRESHOLD_WARMTH = 0.3` fires on `warmth_mean`. This table shows what fires on `warmth_max` at various candidate thresholds.

| Threshold | Firing rate (max) | Firing rate (mean) | Patches firing (max) |
|---|---|---|---|
| 0.05 | 2.5% | 0.0% | 4,033 |
| 0.06 | 1.0% | 0.0% | 1,611 |
| 0.07 | 0.7% | 0.0% | 1,111 |
| 0.08 | 0.4% | 0.0% | 584 |
| 0.09 | 0.1% | 0.0% | 213 |
| 0.10 | 0.1% | 0.0% | 142 |
| 0.11 | 0.0% | 0.0% | 70 |
| 0.12 | 0.0% | 0.0% | 29 |
| 0.13 | 0.0% | 0.0% | 20 |
| 0.14 | 0.0% | 0.0% | 10 |
| 0.15 | 0.0% | 0.0% | 4 |
| 0.16 | 0.0% | 0.0% | 1 |
| 0.17 | 0.0% | 0.0% | 1 |
| 0.18 | 0.0% | 0.0% | 1 |
| 0.19 | 0.0% | 0.0% | 1 |
| 0.20 | 0.0% | 0.0% | 1 |
| 0.30 (current) | 0.0% | 0.0% | 0 |

### 2.3 Warm-cell count per patch

Number of cells in each patch with warmth >= threshold:

| Metric | >= 0.05 | >= 0.10 | >= 0.15 |
|---|---|---|---|
| Mean per patch | 0.025 | 0.001 | 0.000 |
| Median | 0.000 | 0.000 | 0.000 |
| Max | 3 | 1 | 1 |
| Patches with >= 1 | 4,033 | 142 | 4 |
| Patches with >= 2 | 121 | 0 | 0 |

### 2.4 Cluster analysis (6-neighbour face adjacency)

Connected-component labelling of warm cells per patch at multiple thresholds. Uses `scipy.ndimage.label` with default 6-neighbour face adjacency (requires scipy).

AURA's 'Planck Star' knee search (architectural metaphor for localized density, not a physics claim): we look for the threshold at which isolated specks give way to multi-cell clusters.

#### Warmth >= 0.05

| Cluster size | Count | Fraction of all clusters |
|---|---|---|
| 1 | 4,090 | 99.2% |
| 2 | 33 | 0.8% |

Total clusters found: 4,123
Patches with max cluster >= 2: 33 (0.0%)

Max cluster size per patch — mean: 1.01, median: 1.0, max: 2

#### Warmth >= 0.10

| Cluster size | Count | Fraction of all clusters |
|---|---|---|
| 1 | 142 | 100.0% |

Total clusters found: 142
Patches with max cluster >= 2: 0 (0.0%)

Max cluster size per patch — mean: 1.00, median: 1.0, max: 1

#### Warmth >= 0.15

| Cluster size | Count | Fraction of all clusters |
|---|---|---|
| 1 | 4 | 100.0% |

Total clusters found: 4
Patches with max cluster >= 2: 0 (0.0%)

Max cluster size per patch — mean: 1.00, median: 1.0, max: 1

## 3. `DIVERSITY_BOUNDARY` / `phase_boundary` — entropy profiling

### 3.1 Distinct-state count distributions

| Distinct states | r=1 count | r=1 fraction | r=2 count | r=2 fraction |
|---|---|---|---|---|
| 1 | 0 | 0.0% | 0 | 0.0% |
| 2 | 25,335 | 15.5% | 35 | 0.0% |
| 3 | 69,518 | 42.4% | 2,471 | 1.5% |
| 4 | 55,340 | 33.8% | 36,080 | 22.0% |
| 5 | 13,647 | 8.3% | 125,254 | 76.4% |

**Current `phase_boundary` firing rate** (distinct_states >= 4):
- r=1: 42.1% (68,987 patches)
- r=2: 98.5% (161,334 patches)

### 3.2 Normalized entropy distributions

| Statistic | r=1 | r=2 |
|---|---|---|
| Min percentile | 0.2606 | 0.4182 |
| 10th percentile | 0.4268 | 0.5313 |
| 25th percentile | 0.4971 | 0.5593 |
| Median percentile | 0.5513 | 0.5891 |
| 75th percentile | 0.5976 | 0.6201 |
| 90th percentile | 0.6735 | 0.6473 |
| 95th percentile | 0.7106 | 0.6626 |
| 99th percentile | 0.7679 | 0.6962 |
| Max percentile | 0.9446 | 0.8219 |
| Mean | 0.5512 | 0.5893 |
| Std | 0.0891 | 0.0451 |

### 3.3 ROC-style threshold table (Jack's separability analysis)

For each candidate entropy threshold: r=1 firing rate, r=2 firing rate, and separation score (r=1 - r=2). Positive separation = the threshold preserves more r=1 firing while suppressing r=2.

| Entropy threshold | r=1 fires | r=2 fires | Separation (r1 - r2) | r=1 patches | r=2 patches |
|---|---|---|---|---|---|
| 0.10 | 100.0% | 100.0% | +0.000 | 163,840 | 163,840 |
| 0.15 | 100.0% | 100.0% | +0.000 | 163,840 | 163,840 |
| 0.20 | 100.0% | 100.0% | +0.000 | 163,840 | 163,840 |
| 0.25 | 100.0% | 100.0% | +0.000 | 163,840 | 163,840 |
| 0.30 | 100.0% | 100.0% | -0.000 | 163,791 | 163,840 |
| 0.35 | 99.9% | 100.0% | -0.001 | 163,666 | 163,840 |
| 0.40 | 97.8% | 100.0% | -0.022 | 160,248 | 163,840 |
| 0.45 | 83.5% | 100.0% | -0.165 | 136,761 | 163,771 |
| 0.50 | 74.1% | 97.5% | -0.234 | 121,421 | 159,735 |
| 0.55 | 51.5% | 80.6% | -0.291 | 84,394 | 132,052 |
| 0.60 | 24.4% | 41.2% | -0.168 | 40,032 | 67,493 |
| 0.65 | 12.8% | 8.6% | +0.042 | 21,046 | 14,100 |
| 0.70 | 5.6% | 0.8% | +0.048 | 9,141 | 1,264 |
| 0.75 | 1.9% | 0.0% | +0.019 | 3,107 | 57 |
| 0.80 | 0.4% | 0.0% | +0.004 | 690 | 2 |
| 0.85 | 0.0% | 0.0% | +0.000 | 81 | 0 |
| 0.90 | 0.0% | 0.0% | +0.000 | 14 | 0 |
| 0.95 | 0.0% | 0.0% | +0.000 | 0 | 0 |

### 3.4 Distribution overlap (AURA's separability metric)

**Overlap area between r=1 and r=2 entropy distributions: 0.4817**

(0.0 = perfectly separable, 1.0 = identical distributions. Lower is better for choosing a discriminating threshold.)

## 4. Answers to the profiling questions

The following answers are computed mechanically from the data above. Interpretation and candidate selection are for AURA + Jack + Kevin review.

**Q1: Does `warmth_max` fire too broadly?**
At threshold 0.10: 0.1%. At 0.15: 0.0%. At 0.20: 0.0%. Compare against target range of 5-15% for an informative-but-not-dominant predicate.

**Q2: Does count/cluster density fire too rarely?**
Per-threshold cluster rates (patches with max cluster >= 2, face-adjacent):

- Warmth >= 0.05: 0.0% (33 patches)
- Warmth >= 0.10: 0.0% (0 patches)
- Warmth >= 0.15: 0.0% (0 patches)

If all thresholds are below ~2%, the cluster candidate may be too restrictive at current sparsity.

**Q3: Is there a cluster-size knee?**
Per-threshold breakdown of cluster sizes:

- Warmth >= 0.05: 4,123 total clusters. Size 1: 99.2% (4,090). Size >= 2: 0.8% (33).
- Warmth >= 0.10: 142 total clusters. Size 1: 100.0% (142). Size >= 2: 0.0% (0).
- Warmth >= 0.15: 4 total clusters. Size 1: 100.0% (4). Size >= 2: 0.0% (0).

A strong 'Planck Star' knee (AURA's architectural metaphor) would show a clear gap between isolated specks (size 1) and multi-cell clusters (size >= 2) at some threshold. If all thresholds are dominated by size-1 clusters, the localized-structure interpretation has weak empirical support at current sparsity.

**Q4: Does entropy separate r=1 from r=2?**
Best separation score: +0.048 at threshold 0.70. Overlap area: 0.4817. If best separation > +0.10, entropy is a meaningful improvement over raw count.

**Q5: Is there a defensible threshold range?**
No threshold satisfies r=1 >= 50% AND r=2 <= 80%. The distributions may overlap too heavily for entropy alone to fix the scale sensitivity.

---

**This document is evidence, not a decision.** Candidate selection requires AURA architectural review, Jack measurement audit, and Kevin's operator gate. No predicate behavior was changed. Lane A remains parked.

*— 84, profiling script run on 5 snapshots, 163,840 r=1 patches, 163,840 r=2 patches*