"""Cosmic Observatory: Tier 1 matplotlib 2D slice visualization.

Operates directly on dense (64,64,64) lattice arrays and 8-channel memory
grids.  Unlike ``vis/spatial_slice.py`` (which takes point-cloud coords),
this module works with the full volumetric data.

All functions follow vis/ conventions:
  - ``matplotlib.use("Agg")`` for headless rendering
  - Returns ``(fig, ax)`` or ``fig``
  - ``save_path`` kwarg for PNG export
  - ``dpi=150`` default
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import ListedColormap, Normalize, TwoSlopeNorm  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from vis.observatory.constants import (
    STATE_COLORS,
    STATE_NAMES,
    CHANNEL_NAMES,
    CHANNEL_COLORMAPS,
    SIGNAL_FIELD_CHANNEL,
    VOID,
)
from vis.observatory.loader import ObservatorySnapshot


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _state_cmap() -> ListedColormap:
    """Build 5-color discrete colormap matching project convention."""
    return ListedColormap([STATE_COLORS[i] for i in range(5)])


def _take_slice(vol: np.ndarray, axis: str, level: int) -> np.ndarray:
    """Extract a 2D slice from a 3D volume along the given axis."""
    axis_map = {"x": 0, "y": 1, "z": 2}
    ax = axis_map.get(axis.lower(), 2)
    return np.take(vol, level, axis=ax)


def _axis_labels(axis: str) -> Tuple[str, str, str]:
    """Return (slice_axis_label, horizontal_label, vertical_label)."""
    labels = {
        "x": ("X", "Y", "Z"),
        "y": ("Y", "X", "Z"),
        "z": ("Z", "X", "Y"),
    }
    return labels.get(axis.lower(), ("Z", "X", "Y"))


def _default_level(snapshot: ObservatorySnapshot, axis: str) -> int:
    """Return midpoint index along the given axis."""
    axis_map = {"x": 0, "y": 1, "z": 2}
    ax = axis_map.get(axis.lower(), 2)
    return snapshot.shape[ax] // 2


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def slice_lattice(
    snapshot: ObservatorySnapshot,
    axis: str = "z",
    level: Optional[int] = None,
    title: Optional[str] = None,
    save_path: Optional[str] = None,
    figsize: Tuple[float, float] = (8, 8),
    dpi: int = 150,
) -> Tuple[Figure, plt.Axes]:
    """Render a 2D slice of the lattice colored by cell state.

    Parameters
    ----------
    snapshot : ObservatorySnapshot
    axis : str
        Slice axis: "x", "y", or "z".
    level : int, optional
        Slice index along *axis*.  Defaults to midpoint.
    title : str, optional
    save_path : str, optional
        Save the figure as PNG.
    """
    if level is None:
        level = _default_level(snapshot, axis)

    sl = _take_slice(snapshot.lattice, axis, level)
    ax_label, h_label, v_label = _axis_labels(axis)

    fig, ax = plt.subplots(figsize=figsize)
    cmap = _state_cmap()

    im = ax.imshow(
        sl.T, origin="lower", cmap=cmap, vmin=0, vmax=4,
        interpolation="nearest", aspect="equal",
    )
    cbar = fig.colorbar(im, ax=ax, ticks=[0, 1, 2, 3, 4])
    cbar.ax.set_yticklabels([STATE_NAMES[i] for i in range(5)])

    ax.set_xlabel(h_label)
    ax.set_ylabel(v_label)
    if title is None:
        nv = int(np.sum(sl > 0))
        title = f"Lattice Slice at {ax_label}={level}  ({nv} non-void cells)"
    ax.set_title(title)
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=dpi, bbox_inches="tight")

    return fig, ax


def slice_channel(
    snapshot: ObservatorySnapshot,
    channel: int,
    axis: str = "z",
    level: Optional[int] = None,
    state_mask: Optional[int] = None,
    title: Optional[str] = None,
    save_path: Optional[str] = None,
    figsize: Tuple[float, float] = (8, 8),
    dpi: int = 150,
) -> Tuple[Figure, plt.Axes]:
    """Render a 2D slice of a memory channel as a heatmap.

    Parameters
    ----------
    channel : int
        Memory channel index (0-7).
    state_mask : int, optional
        If provided, only show values where ``lattice == state_mask``.
        Other cells are shown as NaN (transparent).
    """
    if level is None:
        level = _default_level(snapshot, axis)

    if state_mask is not None:
        vol = snapshot.channel_masked(channel, state_mask)
    else:
        vol = snapshot.channel(channel).copy().astype(float)
        # Mask void cells as NaN so they appear transparent
        vol[snapshot.lattice == VOID] = np.nan

    sl = _take_slice(vol, axis, level)
    ax_label, h_label, v_label = _axis_labels(axis)

    fig, ax = plt.subplots(figsize=figsize)

    # Bipolar normalization for signal_field
    cmap_name = CHANNEL_COLORMAPS.get(channel, "viridis")
    if channel == SIGNAL_FIELD_CHANNEL:
        vmax = max(abs(np.nanmin(sl)), abs(np.nanmax(sl)), 0.01)
        norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)
    else:
        vmin_val = np.nanmin(sl) if not np.all(np.isnan(sl)) else 0
        vmax_val = np.nanmax(sl) if not np.all(np.isnan(sl)) else 1
        if vmin_val == vmax_val:
            vmax_val = vmin_val + 1
        norm = Normalize(vmin=vmin_val, vmax=vmax_val)

    im = ax.imshow(
        sl.T, origin="lower", cmap=cmap_name, norm=norm,
        interpolation="nearest", aspect="equal",
    )
    fig.colorbar(im, ax=ax, label=CHANNEL_NAMES[channel])

    ax.set_xlabel(h_label)
    ax.set_ylabel(v_label)
    if title is None:
        title = f"{CHANNEL_NAMES[channel]} at {ax_label}={level}"
    ax.set_title(title)
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=dpi, bbox_inches="tight")

    return fig, ax


def slice_composite(
    snapshot: ObservatorySnapshot,
    axis: str = "z",
    level: Optional[int] = None,
    overlay_channel: int = SIGNAL_FIELD_CHANNEL,
    overlay_alpha: float = 0.6,
    title: Optional[str] = None,
    save_path: Optional[str] = None,
    figsize: Tuple[float, float] = (10, 8),
    dpi: int = 150,
) -> Tuple[Figure, plt.Axes]:
    """Composite view: lattice state base layer + memory channel overlay.

    Renders cell states as the base image, then overlays a semi-transparent
    memory channel heatmap on top.
    """
    if level is None:
        level = _default_level(snapshot, axis)

    lattice_sl = _take_slice(snapshot.lattice, axis, level)

    # Channel data -- mask void cells
    ch_vol = snapshot.channel(overlay_channel).copy().astype(float)
    ch_vol[snapshot.lattice == VOID] = np.nan
    ch_sl = _take_slice(ch_vol, axis, level)

    ax_label, h_label, v_label = _axis_labels(axis)

    fig, ax = plt.subplots(figsize=figsize)

    # Base layer: cell states
    cmap = _state_cmap()
    ax.imshow(
        lattice_sl.T, origin="lower", cmap=cmap, vmin=0, vmax=4,
        interpolation="nearest", aspect="equal",
    )

    # Overlay: channel heatmap
    cmap_name = CHANNEL_COLORMAPS.get(overlay_channel, "viridis")
    if overlay_channel == SIGNAL_FIELD_CHANNEL:
        vmax = max(abs(np.nanmin(ch_sl)), abs(np.nanmax(ch_sl)), 0.01)
        norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)
    else:
        vmin_val = np.nanmin(ch_sl) if not np.all(np.isnan(ch_sl)) else 0
        vmax_val = np.nanmax(ch_sl) if not np.all(np.isnan(ch_sl)) else 1
        if vmin_val == vmax_val:
            vmax_val = vmin_val + 1
        norm = Normalize(vmin=vmin_val, vmax=vmax_val)

    im = ax.imshow(
        ch_sl.T, origin="lower", cmap=cmap_name, norm=norm,
        interpolation="nearest", aspect="equal", alpha=overlay_alpha,
    )
    fig.colorbar(im, ax=ax, label=CHANNEL_NAMES[overlay_channel])

    ax.set_xlabel(h_label)
    ax.set_ylabel(v_label)
    if title is None:
        title = (
            f"Composite: States + {CHANNEL_NAMES[overlay_channel]} "
            f"at {ax_label}={level}"
        )
    ax.set_title(title)
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=dpi, bbox_inches="tight")

    return fig, ax


def tri_slice(
    snapshot: ObservatorySnapshot,
    level_x: Optional[int] = None,
    level_y: Optional[int] = None,
    level_z: Optional[int] = None,
    channel: Optional[int] = None,
    save_path: Optional[str] = None,
    figsize: Tuple[float, float] = (18, 6),
    dpi: int = 150,
) -> Figure:
    """Three orthogonal slices (X, Y, Z) in a single figure.

    If *channel* is ``None``, shows cell states.  Otherwise, shows that
    memory channel as a heatmap.
    """
    if level_x is None:
        level_x = _default_level(snapshot, "x")
    if level_y is None:
        level_y = _default_level(snapshot, "y")
    if level_z is None:
        level_z = _default_level(snapshot, "z")

    fig, axes = plt.subplots(1, 3, figsize=figsize)

    for ax_obj, axis, level in zip(axes, ["x", "y", "z"], [level_x, level_y, level_z]):
        if channel is None:
            sl = _take_slice(snapshot.lattice, axis, level)
            cmap = _state_cmap()
            ax_obj.imshow(
                sl.T, origin="lower", cmap=cmap, vmin=0, vmax=4,
                interpolation="nearest", aspect="equal",
            )
        else:
            ch_vol = snapshot.channel(channel).copy().astype(float)
            ch_vol[snapshot.lattice == VOID] = np.nan
            sl = _take_slice(ch_vol, axis, level)
            cmap_name = CHANNEL_COLORMAPS.get(channel, "viridis")

            if channel == SIGNAL_FIELD_CHANNEL:
                vmax = max(abs(np.nanmin(sl)), abs(np.nanmax(sl)), 0.01)
                norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)
            else:
                vmin_val = np.nanmin(sl) if not np.all(np.isnan(sl)) else 0
                vmax_val = np.nanmax(sl) if not np.all(np.isnan(sl)) else 1
                if vmin_val == vmax_val:
                    vmax_val = vmin_val + 1
                norm = Normalize(vmin=vmin_val, vmax=vmax_val)

            ax_obj.imshow(
                sl.T, origin="lower", cmap=cmap_name, norm=norm,
                interpolation="nearest", aspect="equal",
            )

        ax_label, h_label, v_label = _axis_labels(axis)
        ax_obj.set_xlabel(h_label)
        ax_obj.set_ylabel(v_label)
        ax_obj.set_title(f"{axis.upper()}={level}")

    ch_label = CHANNEL_NAMES[channel] if channel is not None else "Cell States"
    fig.suptitle(
        f"Tri-Slice: {ch_label}  (gen {snapshot.generation:,})",
        fontsize=14, fontweight="bold",
    )
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=dpi, bbox_inches="tight")

    return fig
