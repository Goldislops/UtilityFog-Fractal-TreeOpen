"""Workstream B empirical profiling — offline, read-only analysis.

Loads a sample of Medusa snapshots and computes distributional profiles
for the two non-discriminating predicates (metta_warmth, phase_boundary /
DIVERSITY_BOUNDARY). Outputs a results markdown document.

Guardrails:
  - Read-only with respect to snapshots (np.load only, no writes)
  - Offline analysis only (no live-process interaction)
  - No engine touch, no Lane A, no tuning API
  - Outputs go to docs/WORKSTREAM_B_EMPIRICAL_PROFILING_RESULTS.md
  - No predicate changes — evidence only

Usage:
    python scripts/workstream_b_profile_predicates.py [--snapshots N] [--stride S]
"""
from __future__ import annotations

import argparse
import math
import pathlib
import sys
import textwrap
import time
from collections import Counter

import numpy as np

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAPSHOT_GLOB = "data/v070_gen*.npz"
WARMTH_IDX = 6
N_STATES = 5
STATE_NAMES = ["VOID", "STRUCTURAL", "COMPUTE", "ENERGY", "SENSOR"]

WARMTH_MAX_THRESHOLDS = [
    0.05, 0.06, 0.07, 0.08, 0.09,
    0.10, 0.11, 0.12, 0.13, 0.14, 0.15,
    0.16, 0.17, 0.18, 0.19, 0.20,
]
ENTROPY_THRESHOLDS = [
    0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40,
    0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75,
    0.80, 0.85, 0.90, 0.95,
]


def find_newest_snapshots(n: int) -> list[pathlib.Path]:
    candidates = sorted(
        REPO_ROOT.glob(SNAPSHOT_GLOB),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[:n]


def load_snapshot(path: pathlib.Path):
    data = np.load(str(path), allow_pickle=False)
    state = data["lattice"]
    memory = data["memory_grid"]
    gen = int(data["generation"])
    return state, memory, gen


def extract_patches(state, memory, *, stride=8, radius=1):
    X, Y, Z = state.shape
    patches_state = []
    patches_memory_warmth = []
    for x in range(radius, X - radius, stride):
        sx = slice(x - radius, x + radius + 1)
        for y in range(radius, Y - radius, stride):
            sy = slice(y - radius, y + radius + 1)
            for z in range(radius, Z - radius, stride):
                sz = slice(z - radius, z + radius + 1)
                patches_state.append(state[sx, sy, sz])
                patches_memory_warmth.append(memory[WARMTH_IDX, sx, sy, sz])
    return patches_state, patches_memory_warmth


def compute_warmth_profile(patches_warmth):
    means = []
    maxes = []
    warm_counts_at_005 = []
    warm_counts_at_010 = []
    warm_counts_at_015 = []

    for w in patches_warmth:
        flat = w.ravel()
        means.append(float(flat.mean()))
        maxes.append(float(flat.max()))
        warm_counts_at_005.append(int(np.sum(flat >= 0.05)))
        warm_counts_at_010.append(int(np.sum(flat >= 0.10)))
        warm_counts_at_015.append(int(np.sum(flat >= 0.15)))

    return {
        "means": np.array(means),
        "maxes": np.array(maxes),
        "warm_005": np.array(warm_counts_at_005),
        "warm_010": np.array(warm_counts_at_010),
        "warm_015": np.array(warm_counts_at_015),
    }


def compute_cluster_profile(patches_warmth, threshold=0.10):
    from scipy import ndimage

    cluster_sizes_all = []
    patches_with_clusters = 0
    max_cluster_per_patch = []

    for w in patches_warmth:
        mask = w >= threshold
        n_warm = int(mask.sum())
        if n_warm == 0:
            max_cluster_per_patch.append(0)
            continue

        labeled, n_clusters = ndimage.label(mask)
        if n_clusters == 0:
            max_cluster_per_patch.append(0)
            continue

        sizes = ndimage.sum(mask, labeled, range(1, n_clusters + 1))
        sizes = [int(s) for s in sizes]
        cluster_sizes_all.extend(sizes)
        max_cluster_per_patch.append(max(sizes))
        if max(sizes) >= 2:
            patches_with_clusters += 1

    return {
        "all_sizes": cluster_sizes_all,
        "max_per_patch": np.array(max_cluster_per_patch),
        "patches_with_cluster_ge2": patches_with_clusters,
    }


def compute_entropy_profile(patches_state, n_states=N_STATES):
    entropies = []
    distinct_counts = []

    for s in patches_state:
        flat = s.ravel()
        total = len(flat)
        counts = np.bincount(flat, minlength=n_states)[:n_states]
        fracs = counts / total

        distinct = int(np.sum(counts > 0))
        distinct_counts.append(distinct)

        h = 0.0
        for p in fracs:
            if p > 0:
                h -= p * math.log2(p)
        h_max = math.log2(n_states)
        h_norm = h / h_max if h_max > 0 else 0.0
        entropies.append(h_norm)

    return {
        "entropies": np.array(entropies),
        "distinct_counts": np.array(distinct_counts),
    }


def firing_rate(arr, threshold):
    return float(np.mean(arr >= threshold))


def format_pct(val):
    return f"{val * 100:.1f}%"


def generate_results_markdown(
    warmth_r1, cluster_r1, entropy_r1, entropy_r2,
    n_snapshots, n_patches_r1, n_patches_r2,
    snapshot_names, global_warmth_stats,
):
    lines = []

    def w(line=""):
        lines.append(line)

    w("# Workstream B — Empirical Profiling Results")
    w()
    w(f"**Generated**: offline profiling over {n_snapshots} newest snapshots.")
    w(f"**Snapshots**: {', '.join(snapshot_names)}")
    w(f"**Patches at r=1**: {n_patches_r1:,} (stride=8, 3x3x3 = 27 cells/patch)")
    w(f"**Patches at r=2**: {n_patches_r2:,} (stride=8, 5x5x5 = 125 cells/patch)")
    w("**Guardrails**: Read-only analysis. No predicate changes. No engine touch. Lane A parked.")
    w()
    w("---")
    w()

    # === Section 1: Global warmth stats ===
    w("## 1. Global warmth channel statistics")
    w()
    w("Per-snapshot whole-lattice warmth channel (memory index 6):")
    w()
    w("| Snapshot | Sparsity | Min | Max | Mean (non-zero) | Non-zero count |")
    w("|---|---|---|---|---|---|")
    for s in global_warmth_stats:
        w(f"| {s['name']} | {s['sparsity']:.4f} | {s['min']:.6f} | {s['max']:.6f} "
          f"| {s['mean_nonzero']:.6f} | {s['nonzero_count']:,} |")
    w()

    # === Section 2: metta_warmth profiling ===
    w("## 2. `metta_warmth` — patch-level warmth distributions (r=1)")
    w()

    w("### 2.1 Patch mean vs patch max")
    w()
    w("| Statistic | Patch mean | Patch max |")
    w("|---|---|---|")
    w(f"| Min | {warmth_r1['means'].min():.6f} | {warmth_r1['maxes'].min():.6f} |")
    w(f"| 25th percentile | {np.percentile(warmth_r1['means'], 25):.6f} | {np.percentile(warmth_r1['maxes'], 25):.6f} |")
    w(f"| Median | {np.median(warmth_r1['means']):.6f} | {np.median(warmth_r1['maxes']):.6f} |")
    w(f"| 75th percentile | {np.percentile(warmth_r1['means'], 75):.6f} | {np.percentile(warmth_r1['maxes'], 75):.6f} |")
    w(f"| 90th percentile | {np.percentile(warmth_r1['means'], 90):.6f} | {np.percentile(warmth_r1['maxes'], 90):.6f} |")
    w(f"| 95th percentile | {np.percentile(warmth_r1['means'], 95):.6f} | {np.percentile(warmth_r1['maxes'], 95):.6f} |")
    w(f"| 99th percentile | {np.percentile(warmth_r1['means'], 99):.6f} | {np.percentile(warmth_r1['maxes'], 99):.6f} |")
    w(f"| Max | {warmth_r1['means'].max():.6f} | {warmth_r1['maxes'].max():.6f} |")
    w(f"| Mean | {warmth_r1['means'].mean():.6f} | {warmth_r1['maxes'].mean():.6f} |")
    w()

    w("### 2.2 Firing rate curve — patch max at candidate thresholds")
    w()
    w("Current `THRESHOLD_WARMTH = 0.3` fires on `warmth_mean`. This table shows "
      "what fires on `warmth_max` at various candidate thresholds.")
    w()
    w("| Threshold | Firing rate (max) | Firing rate (mean) | Patches firing (max) |")
    w("|---|---|---|---|")
    for t in WARMTH_MAX_THRESHOLDS:
        fr_max = firing_rate(warmth_r1["maxes"], t)
        fr_mean = firing_rate(warmth_r1["means"], t)
        n_fire = int(np.sum(warmth_r1["maxes"] >= t))
        w(f"| {t:.2f} | {format_pct(fr_max)} | {format_pct(fr_mean)} | {n_fire:,} |")
    w(f"| 0.30 (current) | {format_pct(firing_rate(warmth_r1['maxes'], 0.30))} "
      f"| {format_pct(firing_rate(warmth_r1['means'], 0.30))} "
      f"| {int(np.sum(warmth_r1['maxes'] >= 0.30)):,} |")
    w()

    w("### 2.3 Warm-cell count per patch")
    w()
    w("Number of cells in each patch with warmth >= threshold:")
    w()
    w("| Metric | >= 0.05 | >= 0.10 | >= 0.15 |")
    w("|---|---|---|---|")
    for label, arr in [
        ("Mean per patch", [warmth_r1["warm_005"].mean(), warmth_r1["warm_010"].mean(), warmth_r1["warm_015"].mean()]),
        ("Median", [np.median(warmth_r1["warm_005"]), np.median(warmth_r1["warm_010"]), np.median(warmth_r1["warm_015"])]),
        ("Max", [warmth_r1["warm_005"].max(), warmth_r1["warm_010"].max(), warmth_r1["warm_015"].max()]),
        ("Patches with >= 1", [
            int(np.sum(warmth_r1["warm_005"] >= 1)),
            int(np.sum(warmth_r1["warm_010"] >= 1)),
            int(np.sum(warmth_r1["warm_015"] >= 1)),
        ]),
        ("Patches with >= 2", [
            int(np.sum(warmth_r1["warm_005"] >= 2)),
            int(np.sum(warmth_r1["warm_010"] >= 2)),
            int(np.sum(warmth_r1["warm_015"] >= 2)),
        ]),
    ]:
        if isinstance(arr[0], float):
            w(f"| {label} | {arr[0]:.3f} | {arr[1]:.3f} | {arr[2]:.3f} |")
        else:
            w(f"| {label} | {arr[0]:,} | {arr[1]:,} | {arr[2]:,} |")
    w()

    w("### 2.4 Cluster analysis (6-neighbour face adjacency)")
    w()
    w("Connected-component labelling of warm cells (warmth >= 0.10) per patch. "
      "Uses `scipy.ndimage.label` with default 6-neighbour face adjacency.")
    w()
    if cluster_r1["all_sizes"]:
        size_counter = Counter(cluster_r1["all_sizes"])
        w("**Cluster size histogram** (AURA's 'Planck Star' knee search — "
          "architectural metaphor for localized density, not a physics claim):")
        w()
        w("| Cluster size | Count | Fraction of all clusters |")
        w("|---|---|---|")
        total_clusters = len(cluster_r1["all_sizes"])
        for size in sorted(size_counter.keys()):
            count = size_counter[size]
            w(f"| {size} | {count:,} | {format_pct(count / total_clusters)} |")
        w()
        w(f"Total clusters found: {total_clusters:,}")
        w(f"Patches with max cluster >= 2: {cluster_r1['patches_with_cluster_ge2']:,} "
          f"({format_pct(cluster_r1['patches_with_cluster_ge2'] / n_patches_r1)})")
        w()

        max_clust = cluster_r1["max_per_patch"]
        w("**Max cluster size per patch:**")
        w()
        w(f"- Mean: {max_clust[max_clust > 0].mean():.2f}" if np.any(max_clust > 0) else "- Mean: N/A (no warm patches)")
        w(f"- Median (among patches with warmth): {np.median(max_clust[max_clust > 0]):.1f}" if np.any(max_clust > 0) else "")
        w(f"- Max: {max_clust.max()}")
        w()
    else:
        w("No warm cells found at threshold 0.10 — cluster analysis returned empty.")
        w()

    # === Section 3: DIVERSITY_BOUNDARY / entropy profiling ===
    w("## 3. `DIVERSITY_BOUNDARY` / `phase_boundary` — entropy profiling")
    w()

    w("### 3.1 Distinct-state count distributions")
    w()
    w("| Distinct states | r=1 count | r=1 fraction | r=2 count | r=2 fraction |")
    w("|---|---|---|---|---|")
    for n in range(1, N_STATES + 1):
        c1 = int(np.sum(entropy_r1["distinct_counts"] == n))
        c2 = int(np.sum(entropy_r2["distinct_counts"] == n))
        w(f"| {n} | {c1:,} | {format_pct(c1 / n_patches_r1)} | {c2:,} | {format_pct(c2 / n_patches_r2)} |")
    w()
    r1_fire = firing_rate(entropy_r1["distinct_counts"], 4)
    r2_fire = firing_rate(entropy_r2["distinct_counts"], 4)
    w(f"**Current `phase_boundary` firing rate** (distinct_states >= 4):")
    w(f"- r=1: {format_pct(r1_fire)} ({int(r1_fire * n_patches_r1):,} patches)")
    w(f"- r=2: {format_pct(r2_fire)} ({int(r2_fire * n_patches_r2):,} patches)")
    w()

    w("### 3.2 Normalized entropy distributions")
    w()
    w("| Statistic | r=1 | r=2 |")
    w("|---|---|---|")
    for label, pctile in [
        ("Min", 0), ("10th", 10), ("25th", 25), ("Median", 50),
        ("75th", 75), ("90th", 90), ("95th", 95), ("99th", 99), ("Max", 100),
    ]:
        v1 = np.percentile(entropy_r1["entropies"], pctile)
        v2 = np.percentile(entropy_r2["entropies"], pctile)
        if pctile == 0:
            v1, v2 = entropy_r1["entropies"].min(), entropy_r2["entropies"].min()
        elif pctile == 100:
            v1, v2 = entropy_r1["entropies"].max(), entropy_r2["entropies"].max()
        w(f"| {label} percentile | {v1:.4f} | {v2:.4f} |")
    w(f"| Mean | {entropy_r1['entropies'].mean():.4f} | {entropy_r2['entropies'].mean():.4f} |")
    w(f"| Std | {entropy_r1['entropies'].std():.4f} | {entropy_r2['entropies'].std():.4f} |")
    w()

    w("### 3.3 ROC-style threshold table (Jack's separability analysis)")
    w()
    w("For each candidate entropy threshold: r=1 firing rate, r=2 firing rate, "
      "and separation score (r=1 - r=2). Positive separation = the threshold "
      "preserves more r=1 firing while suppressing r=2.")
    w()
    w("| Entropy threshold | r=1 fires | r=2 fires | Separation (r1 - r2) | r=1 patches | r=2 patches |")
    w("|---|---|---|---|---|---|")
    for t in ENTROPY_THRESHOLDS:
        fr1 = firing_rate(entropy_r1["entropies"], t)
        fr2 = firing_rate(entropy_r2["entropies"], t)
        sep = fr1 - fr2
        w(f"| {t:.2f} | {format_pct(fr1)} | {format_pct(fr2)} | {sep:+.3f} | "
          f"{int(fr1 * n_patches_r1):,} | {int(fr2 * n_patches_r2):,} |")
    w()

    # Overlap area estimation
    bins = np.linspace(0, 1, 101)
    h1, _ = np.histogram(entropy_r1["entropies"], bins=bins, density=True)
    h2, _ = np.histogram(entropy_r2["entropies"], bins=bins, density=True)
    bin_width = bins[1] - bins[0]
    overlap = float(np.sum(np.minimum(h1, h2)) * bin_width)

    w("### 3.4 Distribution overlap (AURA's separability metric)")
    w()
    w(f"**Overlap area between r=1 and r=2 entropy distributions: {overlap:.4f}**")
    w()
    w("(0.0 = perfectly separable, 1.0 = identical distributions. "
      "Lower is better for choosing a discriminating threshold.)")
    w()

    # === Section 4: Answers ===
    w("## 4. Answers to the profiling questions")
    w()
    w("The following answers are computed mechanically from the data above. "
      "Interpretation and candidate selection are for AURA + Jack + Kevin review.")
    w()

    max_fire_010 = firing_rate(warmth_r1["maxes"], 0.10)
    max_fire_015 = firing_rate(warmth_r1["maxes"], 0.15)
    max_fire_020 = firing_rate(warmth_r1["maxes"], 0.20)

    w(f"**Q1: Does `warmth_max` fire too broadly?**")
    w(f"At threshold 0.10: {format_pct(max_fire_010)}. "
      f"At 0.15: {format_pct(max_fire_015)}. "
      f"At 0.20: {format_pct(max_fire_020)}. "
      "Compare against target range of 5-15% for an informative-but-not-dominant predicate.")
    w()

    cluster_rate = cluster_r1["patches_with_cluster_ge2"] / n_patches_r1 if n_patches_r1 > 0 else 0
    w(f"**Q2: Does count/cluster density fire too rarely?**")
    w(f"Patches with cluster >= 2 warm cells (face-adjacent): {format_pct(cluster_rate)}. "
      "If this is below ~2%, the cluster candidate may be too restrictive at current sparsity.")
    w()

    if cluster_r1["all_sizes"]:
        sizes = sorted(Counter(cluster_r1["all_sizes"]).items())
        size_1_frac = sum(c for s, c in sizes if s == 1) / sum(c for _, c in sizes)
        w(f"**Q3: Is there a cluster-size knee?**")
        w(f"Fraction of clusters that are size 1 (isolated specks): {format_pct(size_1_frac)}. "
          "A strong knee would show a clear gap between size-1 and size-2+ clusters. "
          "If nearly all clusters are size 1, the 'Planck Star' interpretation "
          "(AURA's metaphor) has weak empirical support at current sparsity.")
    else:
        w("**Q3: Is there a cluster-size knee?** No warm cells found — cannot assess.")
    w()

    best_sep = max(
        (firing_rate(entropy_r1["entropies"], t) - firing_rate(entropy_r2["entropies"], t), t)
        for t in ENTROPY_THRESHOLDS
    )
    w(f"**Q4: Does entropy separate r=1 from r=2?**")
    w(f"Best separation score: {best_sep[0]:+.3f} at threshold {best_sep[1]:.2f}. "
      f"Overlap area: {overlap:.4f}. "
      "If best separation > +0.10, entropy is a meaningful improvement over raw count.")
    w()

    w(f"**Q5: Is there a defensible threshold range?**")
    good_thresholds = [
        t for t in ENTROPY_THRESHOLDS
        if firing_rate(entropy_r1["entropies"], t) >= 0.50
        and firing_rate(entropy_r2["entropies"], t) <= 0.80
    ]
    if good_thresholds:
        w(f"Candidate range: {min(good_thresholds):.2f} – {max(good_thresholds):.2f} "
          "(r=1 fires >= 50%, r=2 fires <= 80%).")
    else:
        w("No threshold satisfies r=1 >= 50% AND r=2 <= 80%. The distributions "
          "may overlap too heavily for entropy alone to fix the scale sensitivity.")
    w()

    w("---")
    w()
    w("**This document is evidence, not a decision.** Candidate selection "
      "requires AURA architectural review, Jack measurement audit, and Kevin's "
      "operator gate. No predicate behavior was changed. Lane A remains parked.")
    w()
    w(f"*— 84, profiling script run on {n_snapshots} snapshots, "
      f"{n_patches_r1:,} r=1 patches, {n_patches_r2:,} r=2 patches*")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Workstream B predicate profiling")
    parser.add_argument("--snapshots", type=int, default=5,
                        help="Number of newest snapshots to profile (default: 5)")
    parser.add_argument("--stride", type=int, default=8,
                        help="Patch stride (default: 8)")
    args = parser.parse_args()

    print(f"Finding {args.snapshots} newest snapshots...")
    snapshot_paths = find_newest_snapshots(args.snapshots)
    if not snapshot_paths:
        print("ERROR: No snapshots found matching", SNAPSHOT_GLOB)
        sys.exit(1)
    print(f"Found {len(snapshot_paths)} snapshots")

    all_warmth_r1 = {"means": [], "maxes": [], "warm_005": [], "warm_010": [], "warm_015": []}
    all_entropy_r1 = {"entropies": [], "distinct_counts": []}
    all_entropy_r2 = {"entropies": [], "distinct_counts": []}
    all_cluster_sizes = []
    cluster_patches_ge2 = 0
    all_max_per_patch = []
    global_warmth_stats = []
    snapshot_names = []
    total_patches_r1 = 0
    total_patches_r2 = 0

    for i, path in enumerate(snapshot_paths):
        fname = path.name
        snapshot_names.append(fname)
        print(f"\n[{i+1}/{len(snapshot_paths)}] Loading {fname}...")
        t0 = time.time()
        state, memory, gen = load_snapshot(path)
        print(f"  Loaded gen={gen}, shape={state.shape}, {time.time()-t0:.1f}s")

        warmth_full = memory[WARMTH_IDX]
        nonzero_mask = warmth_full > 0
        nz_count = int(nonzero_mask.sum())
        total_voxels = int(warmth_full.size)
        global_warmth_stats.append({
            "name": fname,
            "sparsity": 1.0 - nz_count / total_voxels,
            "min": float(warmth_full[nonzero_mask].min()) if nz_count > 0 else 0.0,
            "max": float(warmth_full.max()),
            "mean_nonzero": float(warmth_full[nonzero_mask].mean()) if nz_count > 0 else 0.0,
            "nonzero_count": nz_count,
        })

        # r=1 patches
        print("  Extracting r=1 patches...")
        t0 = time.time()
        ps1, pw1 = extract_patches(state, memory, stride=args.stride, radius=1)
        n1 = len(ps1)
        total_patches_r1 += n1
        print(f"  {n1:,} r=1 patches in {time.time()-t0:.1f}s")

        print("  Computing warmth profile...")
        wp = compute_warmth_profile(pw1)
        for k in all_warmth_r1:
            all_warmth_r1[k].append(wp[k])

        print("  Computing cluster profile (scipy.ndimage.label)...")
        t0 = time.time()
        cp = compute_cluster_profile(pw1, threshold=0.10)
        all_cluster_sizes.extend(cp["all_sizes"])
        cluster_patches_ge2 += cp["patches_with_cluster_ge2"]
        all_max_per_patch.append(cp["max_per_patch"])
        print(f"  Cluster analysis in {time.time()-t0:.1f}s")

        print("  Computing entropy profile r=1...")
        ep1 = compute_entropy_profile(ps1)
        for k in all_entropy_r1:
            all_entropy_r1[k].append(ep1[k])

        # r=2 patches
        print("  Extracting r=2 patches...")
        t0 = time.time()
        ps2, _ = extract_patches(state, memory, stride=args.stride, radius=2)
        n2 = len(ps2)
        total_patches_r2 += n2
        print(f"  {n2:,} r=2 patches in {time.time()-t0:.1f}s")

        print("  Computing entropy profile r=2...")
        ep2 = compute_entropy_profile(ps2)
        for k in all_entropy_r2:
            all_entropy_r2[k].append(ep2[k])

        del state, memory
        print(f"  Snapshot {i+1} complete.")

    # Concatenate arrays
    warmth_r1_agg = {k: np.concatenate(v) for k, v in all_warmth_r1.items()}
    entropy_r1_agg = {k: np.concatenate(v) for k, v in all_entropy_r1.items()}
    entropy_r2_agg = {k: np.concatenate(v) for k, v in all_entropy_r2.items()}
    cluster_r1_agg = {
        "all_sizes": all_cluster_sizes,
        "max_per_patch": np.concatenate(all_max_per_patch) if all_max_per_patch else np.array([]),
        "patches_with_cluster_ge2": cluster_patches_ge2,
    }

    print(f"\n=== Generating results document ===")
    print(f"Total r=1 patches: {total_patches_r1:,}")
    print(f"Total r=2 patches: {total_patches_r2:,}")

    md = generate_results_markdown(
        warmth_r1=warmth_r1_agg,
        cluster_r1=cluster_r1_agg,
        entropy_r1=entropy_r1_agg,
        entropy_r2=entropy_r2_agg,
        n_snapshots=len(snapshot_paths),
        n_patches_r1=total_patches_r1,
        n_patches_r2=total_patches_r2,
        snapshot_names=snapshot_names,
        global_warmth_stats=global_warmth_stats,
    )

    out_path = REPO_ROOT / "docs" / "WORKSTREAM_B_EMPIRICAL_PROFILING_RESULTS.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"\nResults written to: {out_path}")
    print("Done.")


if __name__ == "__main__":
    main()
