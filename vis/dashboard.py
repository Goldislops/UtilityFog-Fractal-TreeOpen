import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap

from vis.export import to_numpy, STATE_NAMES

STATE_COLORS = {
    "void": "#9E9E9E",
    "structural": "#2196F3",
    "compute": "#4CAF50",
    "energy": "#FF9800",
    "sensor": "#E040FB",
}


def _build_cmap():
    colors = [STATE_COLORS[name] for name in STATE_NAMES]
    return ListedColormap(colors)


def dashboard(history, coords=None, states=None, title="Utility Fog Dashboard",
              save_path=None, figsize=(16, 10), dpi=150, slice_axis="z",
              slice_level=None):
    arr = to_numpy(history)
    has_spatial = coords is not None and states is not None

    if has_spatial:
        fig = plt.figure(figsize=figsize)
        gs = fig.add_gridspec(2, 2, hspace=0.35, wspace=0.3)
        ax_ts = fig.add_subplot(gs[0, 0])
        ax_area = fig.add_subplot(gs[0, 1])
        ax_pie = fig.add_subplot(gs[1, 0])
        ax_slice = fig.add_subplot(gs[1, 1])
    else:
        fig = plt.figure(figsize=(figsize[0], figsize[1] * 0.55))
        gs = fig.add_gridspec(1, 3, wspace=0.35)
        ax_ts = fig.add_subplot(gs[0, 0])
        ax_area = fig.add_subplot(gs[0, 1])
        ax_pie = fig.add_subplot(gs[0, 2])
        ax_slice = None

    if arr.size > 0:
        steps = np.arange(arr.shape[0])
        for i, name in enumerate(STATE_NAMES):
            ax_ts.plot(steps, arr[:, i], label=name,
                       color=STATE_COLORS[name], linewidth=1.5)
        ax_ts.set_xlabel("Step")
        ax_ts.set_ylabel("Node Count")
        ax_ts.set_title("Time Series")
        ax_ts.legend(loc="upper right", fontsize=7, framealpha=0.9)
        ax_ts.grid(True, alpha=0.3)

        colors_list = [STATE_COLORS[name] for name in STATE_NAMES]
        ax_area.stackplot(steps, arr.T, labels=STATE_NAMES,
                          colors=colors_list, alpha=0.85)
        ax_area.set_xlabel("Step")
        ax_area.set_ylabel("Node Count")
        ax_area.set_title("Stacked Distribution")
        ax_area.legend(loc="upper right", fontsize=7, framealpha=0.9)
        ax_area.grid(True, alpha=0.3)

        final_census = arr[-1]
    else:
        ax_ts.set_title("Time Series (no data)")
        ax_area.set_title("Stacked Distribution (no data)")
        final_census = np.zeros(5)

    nonzero_mask = final_census > 0
    pie_labels = [STATE_NAMES[i] for i in range(5) if nonzero_mask[i]]
    pie_values = final_census[nonzero_mask]
    pie_colors = [STATE_COLORS[STATE_NAMES[i]] for i in range(5) if nonzero_mask[i]]

    if len(pie_values) > 0:
        ax_pie.pie(pie_values, labels=pie_labels, colors=pie_colors,
                   autopct="%1.1f%%", startangle=90)
    ax_pie.set_title("Final State Distribution")

    if ax_slice is not None and has_spatial:
        coords_arr = np.asarray(coords)
        states_arr = np.asarray(states)
        axis_map = {"x": 0, "y": 1, "z": 2}
        ax_idx = axis_map.get(slice_axis.lower(), 2)
        other_axes = [i for i in range(3) if i != ax_idx]
        axis_labels = ["X", "Y", "Z"]

        slice_vals = coords_arr[:, ax_idx]
        if slice_level is None:
            slice_level = np.median(slice_vals)

        unique_vals = np.unique(slice_vals)
        if len(unique_vals) > 1:
            tol = np.min(np.diff(np.sort(unique_vals))) * 0.6
        else:
            tol = 0.01

        mask = np.abs(slice_vals - slice_level) <= tol
        if not np.any(mask):
            closest_idx = np.argmin(np.abs(slice_vals - slice_level))
            closest_val = slice_vals[closest_idx]
            mask = np.abs(slice_vals - closest_val) <= tol

        sc = coords_arr[mask]
        ss = states_arr[mask]
        cmap = _build_cmap()

        scatter = ax_slice.scatter(
            sc[:, other_axes[0]], sc[:, other_axes[1]],
            c=ss.clip(0, 4), cmap=cmap, vmin=0, vmax=4,
            s=20, edgecolors="black", linewidths=0.3, alpha=0.9,
        )
        cbar = fig.colorbar(scatter, ax=ax_slice, ticks=[0, 1, 2, 3, 4])
        cbar.ax.set_yticklabels(STATE_NAMES)
        ax_slice.set_xlabel(axis_labels[other_axes[0]])
        ax_slice.set_ylabel(axis_labels[other_axes[1]])
        ax_slice.set_title(
            f"Slice at {axis_labels[ax_idx]}={slice_level:.3f} ({mask.sum()} nodes)"
        )
        ax_slice.set_aspect("equal")
        ax_slice.grid(True, alpha=0.2)

    fig.suptitle(title, fontsize=14, fontweight="bold", y=0.98)

    if save_path:
        fig.savefig(save_path, dpi=dpi, bbox_inches="tight")

    return fig
