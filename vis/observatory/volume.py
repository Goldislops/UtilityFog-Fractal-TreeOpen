"""Cosmic Observatory: Tier 3 PyVista volumetric rendering (optional).

Phase 8 -- The Cosmic Observatory

PyVista may not have wheels for Python 3.14.  All functions raise
ImportError with a helpful message if unavailable.  The rest of the
observatory works perfectly without this module.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from vis.observatory.loader import ObservatorySnapshot
from vis.observatory.constants import (
    STATE_COLORS,
    STATE_NAMES,
    CHANNEL_COLORMAPS,
    CHANNEL_NAMES,
    VOID,
)

_PYVISTA_AVAILABLE = False
try:
    import pyvista as pv
    _PYVISTA_AVAILABLE = True
except ImportError:
    pass


def is_available() -> bool:
    """Check if PyVista is installed and importable."""
    return _PYVISTA_AVAILABLE


def _require_pyvista():
    if not _PYVISTA_AVAILABLE:
        raise ImportError(
            "PyVista is not installed. Tier 3 volumetric rendering requires:\n"
            "  pip install pyvista\n\n"
            "If PyVista has no wheel for your Python version, use Tier 2 "
            "(Plotly WebGL) instead:\n"
            "  python -m vis.observatory body <snapshot>"
        )


def volume_render(
    snapshot: ObservatorySnapshot,
    opacity_map: Optional[dict] = None,
    window_size: tuple = (1200, 900),
    background: str = "black",
    save_screenshot: Optional[str] = None,
):
    """True volume rendering of the lattice with opacity transfer.

    Uses PyVista UniformGrid for voxel representation.
    Each cell state maps to a different color and opacity.

    Parameters
    ----------
    snapshot : ObservatorySnapshot
    opacity_map : dict, optional
        Maps state ID to opacity (0-1).
    window_size : tuple
        Render window size in pixels.
    background : str
        Background color.
    save_screenshot : str, optional
        Save a screenshot to this path.
    """
    _require_pyvista()

    if opacity_map is None:
        opacity_map = {
            VOID: 0.0,
            1: 0.15,  # STRUCTURAL
            2: 0.90,  # COMPUTE
            3: 0.60,  # ENERGY
            4: 0.40,  # SENSOR
        }

    grid = pv.ImageData(dimensions=np.array(snapshot.shape) + 1)
    grid.cell_data["state"] = snapshot.lattice.flatten(order="F")

    plotter = pv.Plotter(window_size=window_size)
    plotter.set_background(background)

    # Render each state separately for independent opacity control
    for state_id in range(5):
        if state_id == VOID:
            continue
        mask = snapshot.lattice == state_id
        if not np.any(mask):
            continue

        state_grid = grid.threshold(
            value=[state_id - 0.5, state_id + 0.5],
            scalars="state",
        )
        plotter.add_mesh(
            state_grid,
            color=STATE_COLORS[state_id],
            opacity=opacity_map.get(state_id, 0.5),
            label=STATE_NAMES[state_id],
        )

    plotter.add_legend()

    if save_screenshot:
        plotter.show(screenshot=save_screenshot)
    else:
        plotter.show()


def channel_volume(
    snapshot: ObservatorySnapshot,
    channel: int,
    clim: Optional[tuple] = None,
    opacity: str = "sigmoid",
    save_screenshot: Optional[str] = None,
):
    """Volume render a single memory channel as continuous scalar field.

    Good for seeing signal_field and warmth as volumetric fog/glow.

    Parameters
    ----------
    channel : int
        Memory channel index (0-7).
    clim : tuple, optional
        Color limits (vmin, vmax).
    opacity : str
        Opacity transfer function: "sigmoid", "linear", "geom".
    save_screenshot : str, optional
        Save screenshot to this path.
    """
    _require_pyvista()

    ch_data = snapshot.channel(channel).copy()
    # Zero out void cells
    ch_data[snapshot.lattice == VOID] = 0.0

    grid = pv.ImageData(dimensions=np.array(snapshot.shape) + 1)
    grid.cell_data[CHANNEL_NAMES[channel]] = ch_data.flatten(order="F")

    plotter = pv.Plotter()
    plotter.set_background("black")
    plotter.add_volume(
        grid,
        scalars=CHANNEL_NAMES[channel],
        cmap=CHANNEL_COLORMAPS.get(channel, "viridis"),
        clim=clim,
        opacity=opacity,
    )

    if save_screenshot:
        plotter.show(screenshot=save_screenshot)
    else:
        plotter.show()
