"""Cosmic Observatory: shared constants, colors, and channel definitions.

Phase 8 -- The Cosmic Observatory
"""

from __future__ import annotations

# Cell state IDs (must match continuous_evolution_ca.py)
VOID = 0
STRUCTURAL = 1
COMPUTE = 2
ENERGY = 3
SENSOR = 4

# Hex colors per state -- established project palette (vis/spatial_slice.py)
STATE_COLORS: dict[int, str] = {
    VOID:       "#9E9E9E",
    STRUCTURAL: "#2196F3",
    COMPUTE:    "#4CAF50",
    ENERGY:     "#FF9800",
    SENSOR:     "#E040FB",
}

# Human-readable state names
STATE_NAMES: dict[int, str] = {
    VOID:       "Void",
    STRUCTURAL: "Structural",
    COMPUTE:    "Compute",
    ENERGY:     "Energy",
    SENSOR:     "Sensor",
}

# RGBA tuples for Plotly 3D (r, g, b, default_opacity)
STATE_RGBA: dict[int, tuple[int, int, int, float]] = {
    VOID:       (158, 158, 158, 0.0),   # transparent -- hidden by default
    STRUCTURAL: ( 33, 150, 243, 0.25),  # semi-transparent blue body
    COMPUTE:    ( 76, 175,  80, 0.95),  # bright green ganglia
    ENERGY:     (255, 152,   0, 0.70),  # orange mycelial network
    SENSOR:     (224,  64, 251, 0.50),  # magenta surface sensors
}

# Default marker sizes for 3D scatter (per state)
STATE_MARKER_SIZE: dict[int, int] = {
    VOID:       2,
    STRUCTURAL: 3,
    COMPUTE:    5,
    ENERGY:     4,
    SENSOR:     4,
}

# 8-channel memory grid definitions
CHANNEL_NAMES: list[str] = [
    "compute_age",           # 0
    "structural_age",        # 1
    "memory_strength",       # 2
    "energy_reserve",        # 3
    "last_active_gen",       # 4
    "signal_field",          # 5
    "warmth",                # 6
    "compassion_cooldown",   # 7
]

CHANNEL_DESCRIPTIONS: list[str] = [
    "Age counter for COMPUTE cells",
    "Age counter for STRUCTURAL cells",
    "Mamba-Viking state-space memory M(t)",
    "Cellular energy/resource store",
    "Generation when cell was last active",
    "Mindsight stimulus (density gradient)",
    "Metta warmth accumulation",
    "Compassion echo suppression counter",
]

# Recommended colormaps per channel
CHANNEL_COLORMAPS: dict[int, str] = {
    0: "YlGn",       # compute_age: young=yellow, elder=dark green
    1: "Blues",       # structural_age: blue intensity
    2: "Oranges",     # memory_strength: Mamba-Viking accumulation
    3: "Purples",     # energy_reserve: purple depth
    4: "Greys",       # last_active_gen: recency
    5: "RdBu_r",     # signal_field: BIPOLAR (red=distress, blue=opportunity)
    6: "YlOrRd",     # warmth/metta: gold -> amber -> red glow
    7: "cool",        # compassion_cooldown: active response indicator
}

# Plotly-compatible diverging colorscale for bipolar signal_field
SIGNAL_PLOTLY_COLORSCALE = [
    [0.0,  "rgb(178,  24,  43)"],   # strong negative (distress)
    [0.25, "rgb(239, 138,  98)"],   # mild negative
    [0.5,  "rgb(247, 247, 247)"],   # zero (neutral)
    [0.75, "rgb(103, 169, 207)"],   # mild positive
    [1.0,  "rgb( 33, 102, 172)"],   # strong positive (opportunity)
]

# Sentinel channel indices
COMPUTE_AGE_CHANNEL = 0
STRUCTURAL_AGE_CHANNEL = 1
MEMORY_STRENGTH_CHANNEL = 2
ENERGY_RESERVE_CHANNEL = 3
LAST_ACTIVE_CHANNEL = 4
SIGNAL_FIELD_CHANNEL = 5
WARMTH_CHANNEL = 6
COMPASSION_CHANNEL = 7

NUM_CHANNELS = 8
