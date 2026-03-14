"""Cosmic Observatory: Tier 2 Plotly WebGL interactive 3D scatter rendering.

Requires ``plotly`` (already declared in Makefile install target).
Import is guarded at function level so the module loads even without plotly.

Handles ~75,000 non-void cells in a typical 64-cubed snapshot comfortably.
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np

from vis.observatory.constants import (
    STATE_COLORS,
    STATE_NAMES,
    STATE_MARKER_SIZE,
    STATE_RGBA,
    CHANNEL_NAMES,
    CHANNEL_COLORMAPS,
    SIGNAL_PLOTLY_COLORSCALE,
    VOID,
    STRUCTURAL,
    COMPUTE,
    ENERGY,
    SENSOR,
    SIGNAL_FIELD_CHANNEL,
    WARMTH_CHANNEL,
    COMPUTE_AGE_CHANNEL,
    MEMORY_STRENGTH_CHANNEL,
    COMPASSION_CHANNEL,
)
from vis.observatory.loader import ObservatorySnapshot


def _require_plotly():
    try:
        import plotly  # noqa: F401
    except ImportError:
        raise ImportError(
            "Plotly is required for Tier 2 3D visualization.\n"
            "Install with:  pip install plotly\n"
            "Or use Tier 1 (matplotlib slices):  "
            "python -m vis.observatory slice <snapshot>"
        ) from None


def _dark_layout(title: str = "") -> dict:
    """Shared Plotly layout for dark-background 3D scenes."""
    return dict(
        title=title,
        scene=dict(
            xaxis=dict(title="X", backgroundcolor="rgb(20,20,20)",
                       gridcolor="rgb(50,50,50)", showbackground=True),
            yaxis=dict(title="Y", backgroundcolor="rgb(20,20,20)",
                       gridcolor="rgb(50,50,50)", showbackground=True),
            zaxis=dict(title="Z", backgroundcolor="rgb(20,20,20)",
                       gridcolor="rgb(50,50,50)", showbackground=True),
            aspectmode="data",
        ),
        paper_bgcolor="rgb(10,10,10)",
        plot_bgcolor="rgb(10,10,10)",
        font=dict(color="white"),
        legend=dict(bgcolor="rgba(20,20,20,0.8)"),
    )


def _save_or_show(fig, save_html: Optional[str]):
    """Save to HTML or show interactively."""
    if save_html:
        fig.write_html(save_html, include_plotlyjs="cdn")
        print(f"Saved: {save_html}")
    else:
        fig.show()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def organism_body(
    snapshot: ObservatorySnapshot,
    opacity_by_state: Optional[Dict[int, float]] = None,
    show_void: bool = False,
    title: Optional[str] = None,
    save_html: Optional[str] = None,
):
    """Render 3D organism body colored by cell state.

    Default opacities make STRUCTURAL translucent (body shell) so you can
    see COMPUTE ganglia and ENERGY mycelial network inside.

    Returns a plotly Figure.
    """
    _require_plotly()
    import plotly.graph_objects as go

    if opacity_by_state is None:
        opacity_by_state = {
            STRUCTURAL: 0.25,
            COMPUTE:    0.95,
            ENERGY:     0.70,
            SENSOR:     0.50,
        }

    if title is None:
        title = (
            f"Organism Body  (gen {snapshot.generation:,}, "
            f"{snapshot.non_void_count:,} cells)"
        )

    fig = go.Figure(layout=_dark_layout(title))

    states_to_show = [STRUCTURAL, SENSOR, ENERGY, COMPUTE]
    if show_void:
        states_to_show = [VOID] + states_to_show

    for state_id in states_to_show:
        coords = snapshot.state_coords(state_id)
        if len(coords) == 0:
            continue

        opacity = opacity_by_state.get(state_id, 0.5)
        r, g, b, _ = STATE_RGBA[state_id]
        size = STATE_MARKER_SIZE[state_id]

        fig.add_trace(go.Scatter3d(
            x=coords[:, 0], y=coords[:, 1], z=coords[:, 2],
            mode="markers",
            marker=dict(
                size=size,
                color=f"rgba({r},{g},{b},{opacity})",
                line=dict(width=0),
            ),
            name=f"{STATE_NAMES[state_id]} ({len(coords):,})",
            hovertemplate=(
                f"{STATE_NAMES[state_id]}<br>"
                "x=%{x}, y=%{y}, z=%{z}<extra></extra>"
            ),
        ))

    return fig if save_html is None else (_save_or_show(fig, save_html) or fig)


def channel_overlay(
    snapshot: ObservatorySnapshot,
    channel: int,
    state_filter: Optional[int] = None,
    threshold: float = 0.01,
    title: Optional[str] = None,
    save_html: Optional[str] = None,
):
    """Render a memory channel as 3D scatter with color intensity.

    Only shows cells where ``abs(channel_value) > threshold``.
    For channel 5 (signal_field), uses diverging colorscale.

    Parameters
    ----------
    channel : int
        Memory channel index (0-7).
    state_filter : int, optional
        Only show cells of this state type.
    threshold : float
        Minimum ``|value|`` to display.
    """
    _require_plotly()
    import plotly.graph_objects as go

    vol = snapshot.channel(channel)
    mask = np.abs(vol) > threshold

    if state_filter is not None:
        mask &= (snapshot.lattice == state_filter)
    else:
        mask &= (snapshot.lattice > 0)  # exclude void

    coords = np.argwhere(mask)
    values = vol[mask]

    if len(coords) == 0:
        print(f"No cells above threshold {threshold} for channel "
              f"{CHANNEL_NAMES[channel]}")
        fig = go.Figure(layout=_dark_layout(
            title or f"{CHANNEL_NAMES[channel]} (no data above threshold)"
        ))
        return fig

    if title is None:
        title = (
            f"{CHANNEL_NAMES[channel]}  ({len(coords):,} cells, "
            f"gen {snapshot.generation:,})"
        )

    fig = go.Figure(layout=_dark_layout(title))

    # Colorscale selection
    if channel == SIGNAL_FIELD_CHANNEL:
        colorscale = SIGNAL_PLOTLY_COLORSCALE
        cmid = 0
    else:
        cmap_name = CHANNEL_COLORMAPS.get(channel, "Viridis")
        colorscale = cmap_name
        cmid = None

    marker_kwargs = dict(
        size=np.clip(np.abs(values) * 10 + 3, 3, 10),
        color=values,
        colorscale=colorscale,
        colorbar=dict(title=CHANNEL_NAMES[channel]),
        opacity=0.85,
        line=dict(width=0),
    )
    if cmid is not None:
        marker_kwargs["cmid"] = cmid

    fig.add_trace(go.Scatter3d(
        x=coords[:, 0], y=coords[:, 1], z=coords[:, 2],
        mode="markers",
        marker=marker_kwargs,
        name=CHANNEL_NAMES[channel],
        hovertemplate=(
            f"{CHANNEL_NAMES[channel]}: " + "%{marker.color:.3f}<br>"
            "x=%{x}, y=%{y}, z=%{z}<extra></extra>"
        ),
    ))

    if save_html:
        _save_or_show(fig, save_html)
    return fig


def signal_field_3d(
    snapshot: ObservatorySnapshot,
    threshold: float = 0.01,
    title: str = "Signal Field (Mindsight / Mycelial Network)",
    save_html: Optional[str] = None,
):
    """Specialized view for channel 5: signal_field.

    Shows distress (red) and opportunity (blue) signals as separate visual
    clusters with marker size proportional to ``|signal|``.
    """
    _require_plotly()
    import plotly.graph_objects as go

    signal = snapshot.channel(SIGNAL_FIELD_CHANNEL)
    mask = (np.abs(signal) > threshold) & (snapshot.lattice > 0)
    coords = np.argwhere(mask)
    values = signal[mask]

    if len(coords) == 0:
        fig = go.Figure(layout=_dark_layout(title + " (no active signals)"))
        if save_html:
            _save_or_show(fig, save_html)
        return fig

    title_full = (
        f"{title}  ({len(coords):,} active cells, "
        f"gen {snapshot.generation:,})"
    )
    fig = go.Figure(layout=_dark_layout(title_full))

    # Separate distress (negative) and opportunity (positive)
    neg_mask = values < 0
    pos_mask = values > 0

    if np.any(neg_mask):
        nc = coords[neg_mask]
        nv = values[neg_mask]
        fig.add_trace(go.Scatter3d(
            x=nc[:, 0], y=nc[:, 1], z=nc[:, 2],
            mode="markers",
            marker=dict(
                size=np.clip(np.abs(nv) * 15, 3, 12),
                color="rgba(214, 39, 40, 0.85)",
                line=dict(width=0),
            ),
            name=f"Distress ({np.sum(neg_mask):,})",
            hovertemplate="Distress: %{text:.3f}<br>x=%{x} y=%{y} z=%{z}<extra></extra>",
            text=nv,
        ))

    if np.any(pos_mask):
        pc = coords[pos_mask]
        pv = values[pos_mask]
        fig.add_trace(go.Scatter3d(
            x=pc[:, 0], y=pc[:, 1], z=pc[:, 2],
            mode="markers",
            marker=dict(
                size=np.clip(np.abs(pv) * 15, 3, 12),
                color="rgba(31, 119, 180, 0.85)",
                line=dict(width=0),
            ),
            name=f"Opportunity ({np.sum(pos_mask):,})",
            hovertemplate="Opportunity: %{text:.3f}<br>x=%{x} y=%{y} z=%{z}<extra></extra>",
            text=pv,
        ))

    if save_html:
        _save_or_show(fig, save_html)
    return fig


def warmth_glow_3d(
    snapshot: ObservatorySnapshot,
    threshold: float = 0.001,
    title: str = "Metta Warmth (Loving-Kindness)",
    save_html: Optional[str] = None,
):
    """Specialized view for channel 6: warmth.

    Shows STRUCTURAL cells colored by warmth intensity.  Gold/amber
    colorscale.  Only cells with warmth > threshold are shown.
    """
    _require_plotly()
    import plotly.graph_objects as go

    warmth = snapshot.channel(WARMTH_CHANNEL)
    # Only STRUCTURAL cells accumulate warmth via Phase 6a metta
    mask = (warmth > threshold) & (snapshot.lattice == STRUCTURAL)
    coords = np.argwhere(mask)
    values = warmth[mask]

    if len(coords) == 0:
        fig = go.Figure(layout=_dark_layout(title + " (no warmth detected)"))
        if save_html:
            _save_or_show(fig, save_html)
        return fig

    # Normalize to data range for visible colorscale
    v_max = max(values.max(), 0.01)

    title_full = (
        f"{title}  ({len(coords):,} warm cells, "
        f"max={v_max:.4f}, gen {snapshot.generation:,})"
    )
    fig = go.Figure(layout=_dark_layout(title_full))

    fig.add_trace(go.Scatter3d(
        x=coords[:, 0], y=coords[:, 1], z=coords[:, 2],
        mode="markers",
        marker=dict(
            size=5,
            color=values,
            colorscale="YlOrRd",
            cmin=0,
            cmax=v_max,
            colorbar=dict(title="Warmth"),
            opacity=0.85,
            line=dict(width=0),
        ),
        name="Metta Warmth",
        hovertemplate="Warmth: %{marker.color:.4f}<br>x=%{x} y=%{y} z=%{z}<extra></extra>",
    ))

    if save_html:
        _save_or_show(fig, save_html)
    return fig


def compute_elders_3d(
    snapshot: ObservatorySnapshot,
    title: str = "Compute Age (Elder Ganglia)",
    save_html: Optional[str] = None,
):
    """Specialized view for channel 0: compute_age.

    Shows COMPUTE cells colored by age.  Elder cells are larger and brighter.
    """
    _require_plotly()
    import plotly.graph_objects as go

    age = snapshot.channel(COMPUTE_AGE_CHANNEL)
    mask = snapshot.lattice == COMPUTE
    coords = np.argwhere(mask)
    values = age[mask]

    if len(coords) == 0:
        fig = go.Figure(layout=_dark_layout(title + " (no COMPUTE cells)"))
        if save_html:
            _save_or_show(fig, save_html)
        return fig

    max_age = max(values.max(), 1.0)

    title_full = (
        f"{title}  ({len(coords):,} cells, "
        f"max_age={max_age:.1f}, gen {snapshot.generation:,})"
    )
    fig = go.Figure(layout=_dark_layout(title_full))

    fig.add_trace(go.Scatter3d(
        x=coords[:, 0], y=coords[:, 1], z=coords[:, 2],
        mode="markers",
        marker=dict(
            size=np.clip(values / max_age * 8 + 3, 3, 11),
            color=values,
            colorscale="YlGn",
            cmin=0,
            cmax=max_age,
            colorbar=dict(title="Compute Age"),
            opacity=0.90,
            line=dict(width=0),
        ),
        name="Compute Cells",
        hovertemplate="Age: %{marker.color:.1f}<br>x=%{x} y=%{y} z=%{z}<extra></extra>",
    ))

    if save_html:
        _save_or_show(fig, save_html)
    return fig


def dual_view(
    snapshot: ObservatorySnapshot,
    left_channel: int = SIGNAL_FIELD_CHANNEL,
    right_channel: int = WARMTH_CHANNEL,
    threshold: float = 0.01,
    title: Optional[str] = None,
    save_html: Optional[str] = None,
):
    """Side-by-side 3D subplots: two different channel overlays.

    Uses Plotly subplots with shared scene configuration.
    """
    _require_plotly()
    from plotly.subplots import make_subplots
    import plotly.graph_objects as go

    if title is None:
        title = (
            f"{CHANNEL_NAMES[left_channel]} vs {CHANNEL_NAMES[right_channel]}  "
            f"(gen {snapshot.generation:,})"
        )

    fig = make_subplots(
        rows=1, cols=2,
        specs=[[{"type": "scatter3d"}, {"type": "scatter3d"}]],
        subplot_titles=[CHANNEL_NAMES[left_channel], CHANNEL_NAMES[right_channel]],
    )

    for col, ch in enumerate([left_channel, right_channel], 1):
        vol = snapshot.channel(ch)
        mask = (np.abs(vol) > threshold) & (snapshot.lattice > 0)
        coords = np.argwhere(mask)
        values = vol[mask]

        if len(coords) == 0:
            continue

        if ch == SIGNAL_FIELD_CHANNEL:
            colorscale = SIGNAL_PLOTLY_COLORSCALE
        else:
            colorscale = CHANNEL_COLORMAPS.get(ch, "Viridis")

        fig.add_trace(
            go.Scatter3d(
                x=coords[:, 0], y=coords[:, 1], z=coords[:, 2],
                mode="markers",
                marker=dict(
                    size=4,
                    color=values,
                    colorscale=colorscale,
                    colorbar=dict(
                        title=CHANNEL_NAMES[ch],
                        x=0.45 if col == 1 else 1.0,
                    ),
                    opacity=0.8,
                    line=dict(width=0),
                ),
                name=CHANNEL_NAMES[ch],
            ),
            row=1, col=col,
        )

    fig.update_layout(
        title=title,
        paper_bgcolor="rgb(10,10,10)",
        font=dict(color="white"),
    )

    if save_html:
        _save_or_show(fig, save_html)
    return fig
