import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap

from vis.export import STATE_NAMES


STATE_COLORS_RGB = {
    0: "#9E9E9E",
    1: "#2196F3",
    2: "#4CAF50",
    3: "#FF9800",
    4: "#E040FB",
}


def _build_cmap():
    colors = [STATE_COLORS_RGB[i] for i in range(5)]
    return ListedColormap(colors)


def plot_spatial_slice(coords, states, axis="z", level=None, tolerance=None,
                       title=None, save_path=None, figsize=(8, 8), dpi=150,
                       marker_size=20):
    coords = np.asarray(coords)
    states = np.asarray(states)

    if coords.shape[0] == 0:
        fig, ax = plt.subplots(figsize=figsize)
        ax.set_title(title or "Spatial Slice (empty)")
        if save_path:
            fig.savefig(save_path, dpi=dpi, bbox_inches="tight")
        return fig, ax

    axis_map = {"x": 0, "y": 1, "z": 2}
    ax_idx = axis_map.get(axis.lower(), 2)
    other_axes = [i for i in range(3) if i != ax_idx]
    axis_labels = ["X", "Y", "Z"]

    slice_vals = coords[:, ax_idx]
    if level is None:
        level = np.median(slice_vals)
    if tolerance is None:
        unique_vals = np.unique(slice_vals)
        if len(unique_vals) > 1:
            diffs = np.diff(np.sort(unique_vals))
            tolerance = np.min(diffs) * 0.6
        else:
            tolerance = 0.01

    mask = np.abs(slice_vals - level) <= tolerance
    if not np.any(mask):
        closest_idx = np.argmin(np.abs(slice_vals - level))
        closest_val = slice_vals[closest_idx]
        mask = np.abs(slice_vals - closest_val) <= tolerance

    slice_coords = coords[mask]
    slice_states = states[mask]

    fig, ax = plt.subplots(figsize=figsize)
    cmap = _build_cmap()

    scatter = ax.scatter(
        slice_coords[:, other_axes[0]],
        slice_coords[:, other_axes[1]],
        c=slice_states.clip(0, 4),
        cmap=cmap,
        vmin=0,
        vmax=4,
        s=marker_size,
        edgecolors="black",
        linewidths=0.3,
        alpha=0.9,
    )

    cbar = fig.colorbar(scatter, ax=ax, ticks=[0, 1, 2, 3, 4])
    cbar.ax.set_yticklabels(STATE_NAMES)

    ax.set_xlabel(axis_labels[other_axes[0]])
    ax.set_ylabel(axis_labels[other_axes[1]])
    if title is None:
        title = f"Spatial Slice at {axis_labels[ax_idx]}={level:.3f} ({mask.sum()} nodes)"
    ax.set_title(title)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.2)
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=dpi, bbox_inches="tight")

    return fig, ax


def plot_spatial_scatter_3d(coords, states, title="3D Node States",
                            save_path=None, figsize=(10, 8), dpi=150,
                            marker_size=15, elev=25, azim=45):
    coords = np.asarray(coords)
    states = np.asarray(states)

    fig = plt.figure(figsize=figsize)
    ax = fig.add_subplot(111, projection="3d")

    if coords.shape[0] == 0:
        ax.set_title(title)
        if save_path:
            fig.savefig(save_path, dpi=dpi, bbox_inches="tight")
        return fig, ax

    cmap = _build_cmap()
    scatter = ax.scatter(
        coords[:, 0], coords[:, 1], coords[:, 2],
        c=states.clip(0, 4),
        cmap=cmap,
        vmin=0,
        vmax=4,
        s=marker_size,
        alpha=0.8,
        edgecolors="black",
        linewidths=0.2,
    )

    cbar = fig.colorbar(scatter, ax=ax, ticks=[0, 1, 2, 3, 4], shrink=0.6)
    cbar.ax.set_yticklabels(STATE_NAMES)

    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_zlabel("Z")
    ax.set_title(title)
    ax.view_init(elev=elev, azim=azim)
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=dpi, bbox_inches="tight")

    return fig, ax
