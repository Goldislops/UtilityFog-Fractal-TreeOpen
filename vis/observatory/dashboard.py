"""Cosmic Observatory: multi-panel dashboard for organism health summary.

Phase 8 -- The Cosmic Observatory

Layout (3 rows x 3 cols):
  [0,0] Population pie chart (non-void states)
  [0,1] Compute age histogram (channel 0)
  [0,2] Memory strength histogram (channel 2)
  [1,0] Z-slice lattice states (midpoint)
  [1,1] Z-slice signal_field overlay (channel 5)
  [1,2] Z-slice warmth overlay (channel 6)
  [2,0] Signal field distribution (bipolar histogram)
  [2,1] State ratios bar chart
  [2,2] Summary text panel
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import ListedColormap, TwoSlopeNorm, Normalize  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from vis.observatory.constants import (
    STATE_COLORS,
    STATE_NAMES,
    CHANNEL_NAMES,
    CHANNEL_COLORMAPS,
    VOID,
    STRUCTURAL,
    COMPUTE,
    ENERGY,
    SENSOR,
    COMPUTE_AGE_CHANNEL,
    MEMORY_STRENGTH_CHANNEL,
    SIGNAL_FIELD_CHANNEL,
    WARMTH_CHANNEL,
)
from vis.observatory.loader import ObservatorySnapshot


def _state_cmap() -> ListedColormap:
    return ListedColormap([STATE_COLORS[i] for i in range(5)])


def observatory_dashboard(
    snapshot: ObservatorySnapshot,
    save_path: Optional[str] = None,
    figsize: Tuple[float, float] = (20, 16),
    dpi: int = 150,
) -> Figure:
    """Full Cosmic Observatory dashboard -- 9-panel organism summary."""

    fig, axes = plt.subplots(3, 3, figsize=figsize)
    mid_z = snapshot.shape[2] // 2

    # ---- Row 0: Statistical Panels ----------------------------------------

    # [0,0] Population pie chart (non-void)
    ax_pie = axes[0, 0]
    counts = {s: snapshot.state_count(s) for s in [STRUCTURAL, COMPUTE, ENERGY, SENSOR]}
    nonzero = {s: c for s, c in counts.items() if c > 0}
    if nonzero:
        labels = [STATE_NAMES[s] for s in nonzero]
        values = list(nonzero.values())
        colors = [STATE_COLORS[s] for s in nonzero]
        ax_pie.pie(values, labels=labels, colors=colors,
                   autopct="%1.1f%%", startangle=90,
                   textprops={"fontsize": 8})
    ax_pie.set_title("Population Distribution\n(non-void)", fontsize=10)

    # [0,1] Compute age histogram
    ax_age = axes[0, 1]
    compute_ages = snapshot.channel(COMPUTE_AGE_CHANNEL)[snapshot.lattice == COMPUTE]
    if len(compute_ages) > 0:
        ax_age.hist(compute_ages, bins=30, color=STATE_COLORS[COMPUTE],
                    edgecolor="black", linewidth=0.5, alpha=0.85)
        ax_age.axvline(np.median(compute_ages), color="red", linestyle="--",
                       linewidth=1.5, label=f"median={np.median(compute_ages):.1f}")
        ax_age.legend(fontsize=8)
    ax_age.set_xlabel("Age (steps)")
    ax_age.set_ylabel("Count")
    ax_age.set_title("Compute Cell Age Distribution", fontsize=10)

    # [0,2] Memory strength histogram
    ax_mem = axes[0, 2]
    mem_vals = snapshot.channel(MEMORY_STRENGTH_CHANNEL)
    nonvoid_mem = mem_vals[snapshot.lattice > 0]
    if len(nonvoid_mem) > 0:
        ax_mem.hist(nonvoid_mem, bins=40, color="#FF6F00",
                    edgecolor="black", linewidth=0.5, alpha=0.85)
        ax_mem.axvline(np.median(nonvoid_mem), color="red", linestyle="--",
                       linewidth=1.5, label=f"median={np.median(nonvoid_mem):.2f}")
        ax_mem.legend(fontsize=8)
    ax_mem.set_xlabel("Memory Strength")
    ax_mem.set_ylabel("Count")
    ax_mem.set_title("Memory Strength (Mamba-Viking)", fontsize=10)

    # ---- Row 1: Spatial Slice Panels --------------------------------------

    cmap = _state_cmap()

    # [1,0] Z-slice lattice states
    ax_sl = axes[1, 0]
    lattice_z = snapshot.lattice[:, :, mid_z]
    im = ax_sl.imshow(lattice_z.T, origin="lower", cmap=cmap, vmin=0, vmax=4,
                      interpolation="nearest", aspect="equal")
    cbar = fig.colorbar(im, ax=ax_sl, ticks=[0, 1, 2, 3, 4], shrink=0.8)
    cbar.ax.set_yticklabels([STATE_NAMES[i] for i in range(5)], fontsize=7)
    ax_sl.set_title(f"Z={mid_z} Lattice States", fontsize=10)
    ax_sl.set_xlabel("X")
    ax_sl.set_ylabel("Y")

    # [1,1] Z-slice signal_field overlay
    ax_sig = axes[1, 1]
    sig_vol = snapshot.channel(SIGNAL_FIELD_CHANNEL).copy().astype(float)
    sig_vol[snapshot.lattice == VOID] = np.nan
    sig_z = sig_vol[:, :, mid_z]
    vmax_sig = max(abs(np.nanmin(sig_z)), abs(np.nanmax(sig_z)), 0.01)
    norm_sig = TwoSlopeNorm(vmin=-vmax_sig, vcenter=0, vmax=vmax_sig)
    # Base: lattice states
    ax_sig.imshow(lattice_z.T, origin="lower", cmap=cmap, vmin=0, vmax=4,
                  interpolation="nearest", aspect="equal")
    im_sig = ax_sig.imshow(sig_z.T, origin="lower", cmap="RdBu_r", norm=norm_sig,
                           interpolation="nearest", aspect="equal", alpha=0.65)
    fig.colorbar(im_sig, ax=ax_sig, label="Signal", shrink=0.8)
    ax_sig.set_title(f"Z={mid_z} Signal Field Overlay", fontsize=10)
    ax_sig.set_xlabel("X")
    ax_sig.set_ylabel("Y")

    # [1,2] Z-slice warmth overlay
    ax_wrm = axes[1, 2]
    wrm_vol = snapshot.channel(WARMTH_CHANNEL).copy().astype(float)
    wrm_vol[snapshot.lattice == VOID] = np.nan
    wrm_z = wrm_vol[:, :, mid_z]
    vmin_w = np.nanmin(wrm_z) if not np.all(np.isnan(wrm_z)) else 0
    vmax_w = np.nanmax(wrm_z) if not np.all(np.isnan(wrm_z)) else 1
    if vmax_w == vmin_w:
        vmax_w = vmin_w + 0.01
    norm_w = Normalize(vmin=vmin_w, vmax=vmax_w)
    ax_wrm.imshow(lattice_z.T, origin="lower", cmap=cmap, vmin=0, vmax=4,
                  interpolation="nearest", aspect="equal")
    im_wrm = ax_wrm.imshow(wrm_z.T, origin="lower", cmap="YlOrRd", norm=norm_w,
                           interpolation="nearest", aspect="equal", alpha=0.65)
    fig.colorbar(im_wrm, ax=ax_wrm, label="Warmth", shrink=0.8)
    ax_wrm.set_title(f"Z={mid_z} Metta Warmth Overlay", fontsize=10)
    ax_wrm.set_xlabel("X")
    ax_wrm.set_ylabel("Y")

    # ---- Row 2: Analytics Panels ------------------------------------------

    # [2,0] Signal field distribution (bipolar histogram)
    ax_sdist = axes[2, 0]
    sig_all = snapshot.channel(SIGNAL_FIELD_CHANNEL)
    sig_nonvoid = sig_all[snapshot.lattice > 0]
    sig_active = sig_nonvoid[np.abs(sig_nonvoid) > 0.01]
    if len(sig_active) > 0:
        ax_sdist.hist(sig_active, bins=40, color="#5C6BC0",
                      edgecolor="black", linewidth=0.5, alpha=0.85)
        ax_sdist.axvline(0, color="gray", linestyle="-", linewidth=0.8)
    ax_sdist.set_xlabel("Signal Value")
    ax_sdist.set_ylabel("Count")
    ax_sdist.set_title(
        f"Signal Field Distribution ({len(sig_active):,} active)", fontsize=10
    )

    # [2,1] State ratios bar chart
    ax_bar = axes[2, 1]
    all_states = [VOID, STRUCTURAL, COMPUTE, ENERGY, SENSOR]
    bar_counts = [snapshot.state_count(s) for s in all_states]
    total = sum(bar_counts)
    bar_pcts = [c / max(total, 1) * 100 for c in bar_counts]
    bar_colors = [STATE_COLORS[s] for s in all_states]
    bar_labels = [STATE_NAMES[s] for s in all_states]
    bars = ax_bar.bar(bar_labels, bar_pcts, color=bar_colors,
                      edgecolor="black", linewidth=0.5)
    for bar_obj, pct in zip(bars, bar_pcts):
        if pct > 1:
            ax_bar.text(bar_obj.get_x() + bar_obj.get_width() / 2, pct + 0.5,
                        f"{pct:.1f}%", ha="center", fontsize=8)
    ax_bar.set_ylabel("Percentage (%)")
    ax_bar.set_title("State Distribution", fontsize=10)

    # [2,2] Summary text panel
    ax_txt = axes[2, 2]
    ax_txt.axis("off")

    compute_ages_arr = snapshot.channel(COMPUTE_AGE_CHANNEL)[snapshot.lattice == COMPUTE]
    warmth_vals = snapshot.channel(WARMTH_CHANNEL)[snapshot.lattice == STRUCTURAL]

    summary_lines = [
        f"Generation:  {snapshot.generation:,}",
        f"CA Step:     {snapshot.ca_step:,}",
        f"Fitness:     {snapshot.best_fitness:.4f}",
        "",
        f"Total Cells: {np.prod(snapshot.shape):,}",
        f"Non-Void:    {snapshot.non_void_count:,} "
        f"({snapshot.non_void_count / np.prod(snapshot.shape) * 100:.1f}%)",
        "",
        f"STRUCTURAL:  {snapshot.state_count(STRUCTURAL):,}",
        f"COMPUTE:     {snapshot.state_count(COMPUTE):,}",
        f"ENERGY:      {snapshot.state_count(ENERGY):,}",
        f"SENSOR:      {snapshot.state_count(SENSOR):,}",
        "",
    ]

    if len(compute_ages_arr) > 0:
        summary_lines.extend([
            f"Compute Median Age: {np.median(compute_ages_arr):.1f}",
            f"Compute Max Age:    {np.max(compute_ages_arr):.1f}",
            f"Compute Mean Age:   {np.mean(compute_ages_arr):.1f}",
        ])

    summary_lines.append(f"Signal Active: {int(np.sum(np.abs(sig_nonvoid) > 0.01)):,}")

    if len(warmth_vals) > 0:
        warm_count = int(np.sum(warmth_vals > 0.001))
        summary_lines.append(
            f"Warm Cells:    {warm_count:,} (max={np.max(warmth_vals):.4f})"
        )

    ax_txt.text(
        0.05, 0.95, "\n".join(summary_lines),
        transform=ax_txt.transAxes, fontsize=9,
        verticalalignment="top", fontfamily="monospace",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#1a1a2e",
                  edgecolor="#16213e", alpha=0.9),
        color="white",
    )
    ax_txt.set_title("Organism Summary", fontsize=10)

    # ---- Final layout -----------------------------------------------------

    source = snapshot.source_path or "unknown"
    fig.suptitle(
        f"Cosmic Observatory  |  Gen {snapshot.generation:,}  |  "
        f"Step {snapshot.ca_step:,}  |  Fitness {snapshot.best_fitness:.4f}",
        fontsize=14, fontweight="bold", y=0.995,
        color="#2196F3",
    )
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    if save_path:
        fig.savefig(save_path, dpi=dpi, bbox_inches="tight",
                    facecolor="white", edgecolor="none")
        print(f"Dashboard saved: {save_path}")

    return fig
