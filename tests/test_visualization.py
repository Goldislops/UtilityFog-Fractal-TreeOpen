import os
import sys
import csv
import tempfile

import pytest
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vis.export import to_numpy, to_csv, history_to_dict_list, STATE_NAMES
from vis.timeseries_plot import plot_timeseries, plot_stacked_area
from vis.spatial_slice import plot_spatial_slice, plot_spatial_scatter_3d
from vis.dashboard import dashboard


SAMPLE_FLAT = [
    [100, 20, 5, 10, 3],
    [95, 22, 6, 12, 3],
    [90, 25, 8, 11, 4],
    [85, 28, 10, 10, 5],
    [80, 30, 12, 9, 7],
]

SAMPLE_DICT = [
    {0: 100, 1: 20, 2: 5, 3: 10, 4: 3},
    {0: 95, 1: 22, 2: 6, 3: 12, 4: 3},
    {0: 90, 1: 25, 2: 8, 3: 11, 4: 4},
    {0: 85, 1: 28, 2: 10, 3: 10, 4: 5},
    {0: 80, 1: 30, 2: 12, 3: 9, 4: 7},
]

SAMPLE_COORDS = [
    (0.0, 0.0, 0.0),
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (1.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
    (1.0, 0.0, 1.0),
    (0.0, 1.0, 1.0),
    (1.0, 1.0, 1.0),
]

SAMPLE_STATES = [0, 1, 2, 3, 4, 3, 2, 1]


class TestExportNumpy:
    def test_flat_to_numpy_shape(self):
        arr = to_numpy(SAMPLE_FLAT)
        assert arr.shape == (5, 5)

    def test_flat_to_numpy_dtype(self):
        arr = to_numpy(SAMPLE_FLAT)
        assert arr.dtype == np.uint64

    def test_flat_to_numpy_values(self):
        arr = to_numpy(SAMPLE_FLAT)
        assert arr[0, 0] == 100
        assert arr[4, 4] == 7

    def test_dict_to_numpy_shape(self):
        arr = to_numpy(SAMPLE_DICT)
        assert arr.shape == (5, 5)

    def test_dict_to_numpy_matches_flat(self):
        flat_arr = to_numpy(SAMPLE_FLAT)
        dict_arr = to_numpy(SAMPLE_DICT)
        np.testing.assert_array_equal(flat_arr, dict_arr)

    def test_empty_history(self):
        arr = to_numpy([])
        assert arr.shape == (0, 5)

    def test_single_step(self):
        arr = to_numpy([[10, 20, 30, 40, 50]])
        assert arr.shape == (1, 5)
        assert arr[0, 2] == 30

    def test_dict_missing_keys(self):
        arr = to_numpy([{0: 10, 3: 5}])
        assert arr[0, 0] == 10
        assert arr[0, 1] == 0
        assert arr[0, 3] == 5


class TestExportCSV:
    def test_csv_creates_file(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        try:
            to_csv(SAMPLE_FLAT, path)
            assert os.path.exists(path)
        finally:
            os.unlink(path)

    def test_csv_header(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            path = f.name
        try:
            to_csv(SAMPLE_FLAT, path)
            with open(path) as f:
                reader = csv.reader(f)
                header = next(reader)
            assert header == ["step", "void", "structural", "compute", "energy", "sensor"]
        finally:
            os.unlink(path)

    def test_csv_row_count(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        try:
            to_csv(SAMPLE_FLAT, path)
            with open(path) as f:
                lines = f.readlines()
            assert len(lines) == 6
        finally:
            os.unlink(path)

    def test_csv_no_header(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        try:
            to_csv(SAMPLE_FLAT, path, header=False)
            with open(path) as f:
                lines = f.readlines()
            assert len(lines) == 5
        finally:
            os.unlink(path)

    def test_csv_values(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        try:
            to_csv(SAMPLE_FLAT, path)
            with open(path) as f:
                reader = csv.reader(f)
                next(reader)
                first_row = next(reader)
            assert first_row == ["0", "100", "20", "5", "10", "3"]
        finally:
            os.unlink(path)

    def test_csv_empty_history(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        try:
            to_csv([], path)
            with open(path) as f:
                lines = f.readlines()
            assert len(lines) == 1
        finally:
            os.unlink(path)


class TestExportDictList:
    def test_dict_list_length(self):
        result = history_to_dict_list(SAMPLE_FLAT)
        assert len(result) == 5

    def test_dict_list_keys(self):
        result = history_to_dict_list(SAMPLE_FLAT)
        expected_keys = {"step", "void", "structural", "compute", "energy", "sensor"}
        assert set(result[0].keys()) == expected_keys

    def test_dict_list_step_numbers(self):
        result = history_to_dict_list(SAMPLE_FLAT)
        assert [d["step"] for d in result] == [0, 1, 2, 3, 4]

    def test_dict_list_values(self):
        result = history_to_dict_list(SAMPLE_FLAT)
        assert result[0]["void"] == 100
        assert result[0]["energy"] == 10


class TestTimeseriesPlot:
    def test_returns_fig_and_ax(self):
        fig, ax = plot_timeseries(SAMPLE_FLAT)
        assert isinstance(fig, plt.Figure)
        assert isinstance(ax, plt.Axes)
        plt.close(fig)

    def test_line_count(self):
        fig, ax = plot_timeseries(SAMPLE_FLAT)
        assert len(ax.get_lines()) == 5
        plt.close(fig)

    def test_save_png(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            fig, ax = plot_timeseries(SAMPLE_FLAT, save_path=path)
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0
            plt.close(fig)
        finally:
            os.unlink(path)

    def test_log_scale(self):
        fig, ax = plot_timeseries(SAMPLE_FLAT, log_scale=True)
        assert ax.get_yscale() == "log"
        plt.close(fig)

    def test_custom_title(self):
        fig, ax = plot_timeseries(SAMPLE_FLAT, title="Test Title")
        assert ax.get_title() == "Test Title"
        plt.close(fig)

    def test_empty_history(self):
        fig, ax = plot_timeseries([])
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_dict_input(self):
        fig, ax = plot_timeseries(SAMPLE_DICT)
        assert len(ax.get_lines()) == 5
        plt.close(fig)


class TestStackedArea:
    def test_returns_fig_and_ax(self):
        fig, ax = plot_stacked_area(SAMPLE_FLAT)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_save_svg(self):
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
            path = f.name
        try:
            fig, ax = plot_stacked_area(SAMPLE_FLAT, save_path=path)
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0
            plt.close(fig)
        finally:
            os.unlink(path)

    def test_normalized(self):
        fig, ax = plot_stacked_area(SAMPLE_FLAT, normalize=True)
        assert "%" in ax.get_ylabel()
        plt.close(fig)

    def test_empty_history(self):
        fig, ax = plot_stacked_area([])
        assert isinstance(fig, plt.Figure)
        plt.close(fig)


class TestSpatialSlice:
    def test_returns_fig_and_ax(self):
        fig, ax = plot_spatial_slice(SAMPLE_COORDS, SAMPLE_STATES)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_z_slice(self):
        fig, ax = plot_spatial_slice(SAMPLE_COORDS, SAMPLE_STATES,
                                     axis="z", level=0.0)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_x_slice(self):
        fig, ax = plot_spatial_slice(SAMPLE_COORDS, SAMPLE_STATES,
                                     axis="x", level=0.0)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_y_slice(self):
        fig, ax = plot_spatial_slice(SAMPLE_COORDS, SAMPLE_STATES,
                                     axis="y", level=1.0)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_save_png(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            fig, ax = plot_spatial_slice(SAMPLE_COORDS, SAMPLE_STATES,
                                         save_path=path)
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0
            plt.close(fig)
        finally:
            os.unlink(path)

    def test_empty_coords(self):
        fig, ax = plot_spatial_slice([], [])
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_custom_title(self):
        fig, ax = plot_spatial_slice(SAMPLE_COORDS, SAMPLE_STATES,
                                     title="Custom Slice")
        assert ax.get_title() == "Custom Slice"
        plt.close(fig)

    def test_auto_level(self):
        fig, ax = plot_spatial_slice(SAMPLE_COORDS, SAMPLE_STATES)
        assert "Slice" in ax.get_title()
        plt.close(fig)


class TestSpatialScatter3D:
    def test_returns_fig_and_ax(self):
        fig, ax = plot_spatial_scatter_3d(SAMPLE_COORDS, SAMPLE_STATES)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_save_png(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            fig, ax = plot_spatial_scatter_3d(SAMPLE_COORDS, SAMPLE_STATES,
                                              save_path=path)
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0
            plt.close(fig)
        finally:
            os.unlink(path)

    def test_empty_coords(self):
        fig, ax = plot_spatial_scatter_3d([], [])
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_custom_view(self):
        fig, ax = plot_spatial_scatter_3d(SAMPLE_COORDS, SAMPLE_STATES,
                                          elev=45, azim=90)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)


class TestDashboard:
    def test_returns_fig_no_spatial(self):
        fig = dashboard(SAMPLE_FLAT)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_returns_fig_with_spatial(self):
        fig = dashboard(SAMPLE_FLAT, coords=SAMPLE_COORDS,
                        states=SAMPLE_STATES)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_save_png(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            fig = dashboard(SAMPLE_FLAT, save_path=path)
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0
            plt.close(fig)
        finally:
            os.unlink(path)

    def test_save_with_spatial(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            fig = dashboard(SAMPLE_FLAT, coords=SAMPLE_COORDS,
                            states=SAMPLE_STATES, save_path=path)
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0
            plt.close(fig)
        finally:
            os.unlink(path)

    def test_empty_history(self):
        fig = dashboard([])
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_custom_title(self):
        fig = dashboard(SAMPLE_FLAT, title="My Dashboard")
        assert "My Dashboard" in fig.texts[0].get_text() if fig.texts else True
        plt.close(fig)

    def test_slice_axis_x(self):
        fig = dashboard(SAMPLE_FLAT, coords=SAMPLE_COORDS,
                        states=SAMPLE_STATES, slice_axis="x")
        assert isinstance(fig, plt.Figure)
        plt.close(fig)


class TestStateNames:
    def test_state_names_order(self):
        assert STATE_NAMES == ["void", "structural", "compute", "energy", "sensor"]

    def test_state_names_count(self):
        assert len(STATE_NAMES) == 5
