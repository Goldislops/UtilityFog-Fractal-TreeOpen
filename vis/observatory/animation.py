"""Cosmic Observatory: time-lapse animation from sequential NPZ snapshots.

Phase 8 -- The Cosmic Observatory

Produces animated GIFs of lattice evolution using matplotlib FuncAnimation.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.animation import FuncAnimation, PillowWriter  # noqa: E402
from matplotlib.colors import ListedColormap, TwoSlopeNorm, Normalize  # noqa: E402

from vis.observatory.constants import (
    STATE_COLORS,
    STATE_NAMES,
    CHANNEL_NAMES,
    CHANNEL_COLORMAPS,
    SIGNAL_FIELD_CHANNEL,
    VOID,
)
from vis.observatory.loader import ObservatorySnapshot, load_snapshot_series


def _state_cmap() -> ListedColormap:
    return ListedColormap([STATE_COLORS[i] for i in range(5)])


def animate_slices(
    snapshots: List[ObservatorySnapshot],
    axis: str = "z",
    level: Optional[int] = None,
    overlay_channel: Optional[int] = None,
    output_path: str = "observatory_timelapse.gif",
    fps: int = 4,
    figsize: tuple = (10, 8),
    dpi: int = 100,
) -> str:
    """Create animated GIF of lattice evolution from snapshot series.

    Each frame shows a 2D slice at the given axis/level.
    If *overlay_channel* is specified, composites the channel on top.

    Parameters
    ----------
    snapshots : list[ObservatorySnapshot]
    axis : str
        Slice axis ("x", "y", "z").
    level : int, optional
        Slice index.  Defaults to midpoint.
    overlay_channel : int, optional
        Memory channel to overlay as heatmap.
    output_path : str
        Output GIF file path.
    fps : int
        Frames per second.

    Returns
    -------
    str
        Path to the saved GIF file.
    """
    if not snapshots:
        raise ValueError("No snapshots to animate")

    if level is None:
        axis_map = {"x": 0, "y": 1, "z": 2}
        ax_idx = axis_map.get(axis.lower(), 2)
        level = snapshots[0].shape[ax_idx] // 2

    fig, ax_obj = plt.subplots(figsize=figsize)
    cmap = _state_cmap()

    # First frame
    axis_map = {"x": 0, "y": 1, "z": 2}
    ax_num = axis_map.get(axis.lower(), 2)

    first_sl = np.take(snapshots[0].lattice, level, axis=ax_num)
    im_base = ax_obj.imshow(
        first_sl.T, origin="lower", cmap=cmap, vmin=0, vmax=4,
        interpolation="nearest", aspect="equal",
    )

    im_overlay = None
    if overlay_channel is not None:
        ch_vol = snapshots[0].channel(overlay_channel).copy().astype(float)
        ch_vol[snapshots[0].lattice == VOID] = np.nan
        ch_sl = np.take(ch_vol, level, axis=ax_num)
        cmap_name = CHANNEL_COLORMAPS.get(overlay_channel, "viridis")
        im_overlay = ax_obj.imshow(
            ch_sl.T, origin="lower", cmap=cmap_name,
            interpolation="nearest", aspect="equal", alpha=0.6,
        )

    title_obj = ax_obj.set_title("")

    def update(frame_idx):
        snap = snapshots[frame_idx]
        sl = np.take(snap.lattice, level, axis=ax_num)
        im_base.set_data(sl.T)

        if im_overlay is not None and overlay_channel is not None:
            ch_vol = snap.channel(overlay_channel).copy().astype(float)
            ch_vol[snap.lattice == VOID] = np.nan
            ch_sl = np.take(ch_vol, level, axis=ax_num)
            im_overlay.set_data(ch_sl.T)

            # Update normalization
            if overlay_channel == SIGNAL_FIELD_CHANNEL:
                vmax = max(abs(np.nanmin(ch_sl)), abs(np.nanmax(ch_sl)), 0.01)
                im_overlay.set_norm(TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax))
            else:
                vmin_val = np.nanmin(ch_sl) if not np.all(np.isnan(ch_sl)) else 0
                vmax_val = np.nanmax(ch_sl) if not np.all(np.isnan(ch_sl)) else 1
                if vmin_val == vmax_val:
                    vmax_val = vmin_val + 1
                im_overlay.set_norm(Normalize(vmin=vmin_val, vmax=vmax_val))

        nv = int(np.sum(sl > 0))
        ch_label = ""
        if overlay_channel is not None:
            ch_label = f" + {CHANNEL_NAMES[overlay_channel]}"
        title_obj.set_text(
            f"Gen {snap.generation:,}  |  Step {snap.ca_step:,}  |  "
            f"{nv:,} cells{ch_label}"
        )
        return [im_base] + ([im_overlay] if im_overlay else [])

    anim = FuncAnimation(
        fig, update, frames=len(snapshots),
        interval=1000 // fps, blit=False,
    )

    writer = PillowWriter(fps=fps)
    anim.save(output_path, writer=writer, dpi=dpi)
    plt.close(fig)
    print(f"Animation saved: {output_path} ({len(snapshots)} frames, {fps} fps)")
    return output_path


def animate_from_directory(
    directory: str | Path,
    pattern: str = "v070_*.npz",
    max_frames: int = 50,
    output_path: str = "observatory_timelapse.gif",
    **kwargs,
) -> str:
    """Convenience: load snapshots from directory and animate.

    Parameters
    ----------
    directory : str or Path
        Directory containing .npz snapshot files.
    pattern : str
        Glob pattern for snapshot files.
    max_frames : int
        Maximum number of frames to include.

    Returns
    -------
    str
        Path to the saved GIF file.
    """
    snapshots = load_snapshot_series(directory, pattern, max_count=max_frames)
    return animate_slices(snapshots, output_path=output_path, **kwargs)
