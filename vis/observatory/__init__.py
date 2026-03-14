"""Cosmic Observatory: Phase 8 visualization pipeline for UtilityFog CA.

Provides 3D volumetric rendering, 2D slice analysis, channel overlays,
and multi-panel dashboards for the 64-cubed lattice organism.

Tiered rendering:
  Tier 1 (matplotlib): 2D slices + channel heatmaps -- always available
  Tier 2 (plotly):     Interactive 3D WebGL scatter -- ``pip install plotly``
  Tier 3 (pyvista):    True volume rendering -- ``pip install pyvista``
"""

from vis.observatory.loader import (
    ObservatorySnapshot,
    load_snapshot,
    load_npz,
    load_genome,
    load_snapshot_series,
)
from vis.observatory.constants import (
    STATE_COLORS,
    STATE_NAMES,
    CHANNEL_NAMES,
    CHANNEL_COLORMAPS,
)

__all__ = [
    "ObservatorySnapshot",
    "load_snapshot",
    "load_npz",
    "load_genome",
    "load_snapshot_series",
    "STATE_COLORS",
    "STATE_NAMES",
    "CHANNEL_NAMES",
    "CHANNEL_COLORMAPS",
]
