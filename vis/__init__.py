from vis.export import to_csv, to_numpy, history_to_dict_list
from vis.timeseries_plot import plot_timeseries, plot_stacked_area
from vis.spatial_slice import plot_spatial_slice, plot_spatial_scatter_3d
from vis.dashboard import dashboard

# Phase 8: Cosmic Observatory (optional -- imports gracefully if available)
try:
    from vis.observatory import (
        ObservatorySnapshot,
        load_snapshot,
        load_snapshot_series,
    )
except ImportError:
    pass
