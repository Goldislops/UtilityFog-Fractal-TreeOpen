import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from vis.export import to_numpy, STATE_NAMES


STATE_COLORS = {
    "void": "#9E9E9E",
    "structural": "#2196F3",
    "compute": "#4CAF50",
    "energy": "#FF9800",
    "sensor": "#E040FB",
}

STATE_ORDER = STATE_NAMES


def plot_timeseries(history, title="State Population Over Time",
                    log_scale=False, save_path=None, figsize=(10, 6),
                    dpi=150):
    arr = to_numpy(history)
    if arr.size == 0:
        fig, ax = plt.subplots(figsize=figsize)
        ax.set_title(title)
        if save_path:
            fig.savefig(save_path, dpi=dpi, bbox_inches="tight")
        return fig, ax

    steps = np.arange(arr.shape[0])
    fig, ax = plt.subplots(figsize=figsize)

    for i, name in enumerate(STATE_ORDER):
        ax.plot(steps, arr[:, i], label=name, color=STATE_COLORS[name],
                linewidth=1.5)

    ax.set_xlabel("Step")
    ax.set_ylabel("Node Count")
    ax.set_title(title)
    ax.legend(loc="upper right", framealpha=0.9)
    if log_scale:
        ax.set_yscale("log")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=dpi, bbox_inches="tight")

    return fig, ax


def plot_stacked_area(history, title="State Distribution Over Time",
                      save_path=None, figsize=(10, 6), dpi=150,
                      normalize=False):
    arr = to_numpy(history).astype(np.float64)
    if arr.size == 0:
        fig, ax = plt.subplots(figsize=figsize)
        ax.set_title(title)
        if save_path:
            fig.savefig(save_path, dpi=dpi, bbox_inches="tight")
        return fig, ax

    if normalize:
        totals = arr.sum(axis=1, keepdims=True)
        totals[totals == 0] = 1.0
        arr = arr / totals * 100.0

    steps = np.arange(arr.shape[0])
    fig, ax = plt.subplots(figsize=figsize)

    colors = [STATE_COLORS[name] for name in STATE_ORDER]
    ax.stackplot(steps, arr.T, labels=STATE_ORDER, colors=colors, alpha=0.85)

    ax.set_xlabel("Step")
    ax.set_ylabel("% of Nodes" if normalize else "Node Count")
    ax.set_title(title)
    ax.legend(loc="upper right", framealpha=0.9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=dpi, bbox_inches="tight")

    return fig, ax
