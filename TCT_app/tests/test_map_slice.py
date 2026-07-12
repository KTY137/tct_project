"""Unit tests for analysis/map_slice.py — pure numpy, no Qt.

Grid convention under test (matches analysis/scan_grid.py exactly):
grid[i, j] is the value at (x_mm[i], y_mm[j]) — X is axis 0 (rows), Y is
axis 1 (columns).
"""
from __future__ import annotations

import warnings

import numpy as np
import pytest

from analysis.map_slice import (
    display_unit_scale,
    mm_to_index,
    slice_grid,
    slice_grid_at_mm,
    strip_unit_suffix,
)

nan = float("nan")


# --------------------------------------------------------------------------- #
# mm_to_index                                                                  #
# --------------------------------------------------------------------------- #

class TestMmToIndex:
    def test_exact_match(self):
        assert mm_to_index([0.0, 1.0, 2.0, 3.0], 2.0) == 2

    def test_nearest_neighbour(self):
        assert mm_to_index([0.0, 1.0, 2.0, 3.0], 1.6) == 2
        assert mm_to_index([0.0, 1.0, 2.0, 3.0], 1.4) == 1

    def test_clamps_below_range(self):
        assert mm_to_index([10.0, 20.0, 30.0], -100.0) == 0

    def test_clamps_above_range(self):
        assert mm_to_index([10.0, 20.0, 30.0], 999.0) == 2

    def test_non_square_axis_lengths_independent(self):
        # A 3-long X axis and a 5-long Y axis must each map independently —
        # no accidental cross-talk between the two axis vectors.
        x_mm = [0.0, 5.0, 10.0]
        y_mm = [0.0, 1.0, 2.0, 3.0, 4.0]
        assert mm_to_index(x_mm, 5.0) == 1
        assert mm_to_index(y_mm, 3.2) == 3

    def test_empty_axis_raises(self):
        with pytest.raises(ValueError):
            mm_to_index([], 0.0)


# --------------------------------------------------------------------------- #
# slice_grid — basic row/col extraction                                       #
# --------------------------------------------------------------------------- #

class TestSliceGridExtraction:
    """3 (X) x 4 (Y) grid, non-square on purpose to catch an axis-swap bug."""

    def _grid(self):
        x_mm = np.array([0.0, 1.0, 2.0])
        y_mm = np.array([10.0, 20.0, 30.0, 40.0])
        grid = np.array([
            [1.0, 5.0, 2.0, 100.0],
            [11.0, 15.0, 12.0, 110.0],
            [21.0, 25.0, 22.0, 120.0],
        ])
        assert grid.shape == (3, 4)
        return grid, x_mm, y_mm

    def test_axis_x_profile_walks_x_at_fixed_y_index(self):
        grid, x_mm, y_mm = self._grid()
        positions, values = slice_grid(grid, x_mm, y_mm, "x", index=1, width=0)
        # Fixed Y index 1 (y=20mm) -> column 1 across all X rows.
        assert np.array_equal(positions, x_mm)
        assert np.allclose(values, [5.0, 15.0, 25.0])

    def test_axis_y_profile_walks_y_at_fixed_x_index(self):
        grid, x_mm, y_mm = self._grid()
        positions, values = slice_grid(grid, x_mm, y_mm, "y", index=2, width=0)
        # Fixed X index 2 (x=2mm) -> row 2 across all Y columns.
        assert np.array_equal(positions, y_mm)
        assert np.allclose(values, [21.0, 25.0, 22.0, 120.0])

    def test_positions_is_a_copy_not_a_view(self):
        grid, x_mm, y_mm = self._grid()
        positions, _ = slice_grid(grid, x_mm, y_mm, "x", index=0, width=0)
        positions[0] = -999.0
        assert x_mm[0] == 0.0   # caller's axis vector must be untouched

    def test_invalid_axis_raises(self):
        grid, x_mm, y_mm = self._grid()
        with pytest.raises(ValueError):
            slice_grid(grid, x_mm, y_mm, "z", index=0)

    def test_shape_mismatch_raises(self):
        grid, x_mm, y_mm = self._grid()
        with pytest.raises(ValueError):
            slice_grid(grid, x_mm, y_mm[:-1], "x", index=0)


# --------------------------------------------------------------------------- #
# slice_grid — ± width averaging math                                         #
# --------------------------------------------------------------------------- #

class TestSliceGridAveraging:
    def test_width_averages_neighbouring_columns(self):
        x_mm = np.array([0.0, 1.0])
        y_mm = np.array([0.0, 1.0, 2.0])
        grid = np.array([
            [1.0, 5.0, 2.0],
            [10.0, 50.0, 20.0],
        ])
        # index=1, width=1 -> average columns 0,1,2 (all of them here).
        positions, values = slice_grid(grid, x_mm, y_mm, "x", index=1, width=1)
        assert np.array_equal(positions, x_mm)
        assert values[0] == pytest.approx((1.0 + 5.0 + 2.0) / 3)
        assert values[1] == pytest.approx((10.0 + 50.0 + 20.0) / 3)

    def test_width_averages_neighbouring_rows(self):
        x_mm = np.array([0.0, 1.0, 2.0])
        y_mm = np.array([0.0, 1.0])
        grid = np.array([
            [1.0, 10.0],
            [3.0, 30.0],
            [5.0, 50.0],
        ])
        # index=1 (middle X row), width=1 -> average rows 0,1,2.
        positions, values = slice_grid(grid, x_mm, y_mm, "y", index=1, width=1)
        assert np.array_equal(positions, y_mm)
        assert values[0] == pytest.approx((1.0 + 3.0 + 5.0) / 3)
        assert values[1] == pytest.approx((10.0 + 30.0 + 50.0) / 3)

    def test_width_zero_is_bare_single_row_or_column(self):
        x_mm = np.array([0.0, 1.0])
        y_mm = np.array([0.0, 1.0, 2.0])
        grid = np.array([
            [1.0, 5.0, 2.0],
            [10.0, 50.0, 20.0],
        ])
        _, values = slice_grid(grid, x_mm, y_mm, "x", index=1, width=0)
        assert np.allclose(values, [5.0, 50.0])

    def test_negative_width_treated_as_zero(self):
        x_mm = np.array([0.0, 1.0])
        y_mm = np.array([0.0, 1.0, 2.0])
        grid = np.array([
            [1.0, 5.0, 2.0],
            [10.0, 50.0, 20.0],
        ])
        _, values = slice_grid(grid, x_mm, y_mm, "x", index=1, width=-3)
        assert np.allclose(values, [5.0, 50.0])


# --------------------------------------------------------------------------- #
# slice_grid — NaN preservation, no warnings                                  #
# --------------------------------------------------------------------------- #

class TestSliceGridNaNPolicy:
    def test_all_nan_window_stays_nan_no_warning(self):
        x_mm = np.array([0.0, 1.0, 2.0])
        y_mm = np.array([0.0, 1.0, 2.0])
        grid = np.full((3, 3), nan)
        grid[0, 0] = 5.0  # one valid cell elsewhere, irrelevant to the window below

        with warnings.catch_warnings():
            warnings.simplefilter("error")   # any warning -> test failure
            positions, values = slice_grid(grid, x_mm, y_mm, "x", index=2, width=0)

        assert np.array_equal(positions, x_mm)
        assert np.all(np.isnan(values))

    def test_partial_nan_window_ignores_nan_entries(self):
        x_mm = np.array([0.0])
        y_mm = np.array([0.0, 1.0, 2.0])
        grid = np.array([[10.0, nan, 30.0]])
        _, values = slice_grid(grid, x_mm, y_mm, "x", index=1, width=1)
        # nanmean over [10, nan, 30] -> 20, not nan.
        assert values[0] == pytest.approx(20.0)

    def test_all_nan_column_preserved_through_full_profile(self):
        """A never-sampled Y position (whole column NaN) stays NaN in the
        profile at every X, not silently dropped or zero-filled."""
        x_mm = np.array([0.0, 1.0, 2.0])
        y_mm = np.array([0.0, 1.0])
        grid = np.array([
            [1.0, nan],
            [2.0, nan],
            [3.0, nan],
        ])
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            _, values = slice_grid(grid, x_mm, y_mm, "y", index=0, width=0)
        # index=0 fixes X row 0 -> values across Y = [1.0, nan]
        assert values[0] == pytest.approx(1.0)
        assert np.isnan(values[1])


# --------------------------------------------------------------------------- #
# slice_grid — edge clamping                                                  #
# --------------------------------------------------------------------------- #

class TestSliceGridEdgeClamping:
    def test_width_window_clamps_at_low_edge(self):
        x_mm = np.array([0.0])
        y_mm = np.array([0.0, 1.0, 2.0, 3.0])
        grid = np.array([[1.0, 2.0, 3.0, 4.0]])
        # index=0, width=5 -> window would be [-5, 6), clamps to [0, 4).
        _, values = slice_grid(grid, x_mm, y_mm, "x", index=0, width=5)
        assert values[0] == pytest.approx((1.0 + 2.0 + 3.0 + 4.0) / 4)

    def test_width_window_clamps_at_high_edge(self):
        x_mm = np.array([0.0])
        y_mm = np.array([0.0, 1.0, 2.0, 3.0])
        grid = np.array([[1.0, 2.0, 3.0, 4.0]])
        # index=3 (last), width=5 -> window clamps to [0, 4) too.
        _, values = slice_grid(grid, x_mm, y_mm, "x", index=3, width=5)
        assert values[0] == pytest.approx((1.0 + 2.0 + 3.0 + 4.0) / 4)

    def test_out_of_range_index_clamps_to_nearest_edge(self):
        x_mm = np.array([0.0])
        y_mm = np.array([0.0, 1.0, 2.0])
        grid = np.array([[1.0, 2.0, 3.0]])
        _, values_hi = slice_grid(grid, x_mm, y_mm, "x", index=999, width=0)
        assert values_hi[0] == pytest.approx(3.0)
        _, values_lo = slice_grid(grid, x_mm, y_mm, "x", index=-999, width=0)
        assert values_lo[0] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# slice_grid_at_mm — mm -> index resolution folded in                         #
# --------------------------------------------------------------------------- #

class TestSliceGridAtMm:
    def test_resolves_fixed_axis_from_mm_position_axis_x(self):
        x_mm = np.array([0.0, 1.0, 2.0])
        y_mm = np.array([0.0, 10.0, 20.0])
        grid = np.array([
            [1.0, 2.0, 3.0],
            [4.0, 5.0, 6.0],
            [7.0, 8.0, 9.0],
        ])
        # axis="x" -> fixed axis is Y; position 9.0mm nearest to y_mm[1]=10.0.
        positions, values = slice_grid_at_mm(grid, x_mm, y_mm, "x", 9.0, width=0)
        assert np.array_equal(positions, x_mm)
        assert np.allclose(values, [2.0, 5.0, 8.0])

    def test_resolves_fixed_axis_from_mm_position_axis_y(self):
        x_mm = np.array([0.0, 1.0, 2.0])
        y_mm = np.array([0.0, 10.0, 20.0])
        grid = np.array([
            [1.0, 2.0, 3.0],
            [4.0, 5.0, 6.0],
            [7.0, 8.0, 9.0],
        ])
        # axis="y" -> fixed axis is X; position 1.1mm nearest to x_mm[1]=1.0.
        positions, values = slice_grid_at_mm(grid, x_mm, y_mm, "y", 1.1, width=0)
        assert np.array_equal(positions, y_mm)
        assert np.allclose(values, [4.0, 5.0, 6.0])

    def test_invalid_axis_raises(self):
        grid = np.zeros((2, 2))
        with pytest.raises(ValueError):
            slice_grid_at_mm(grid, [0.0, 1.0], [0.0, 1.0], "z", 0.0)


# --------------------------------------------------------------------------- #
# display_unit_scale                                                          #
# --------------------------------------------------------------------------- #

class TestDisplayUnitScale:
    def test_charge_quantity_scales_to_femtocoulombs(self):
        unit, scale = display_unit_scale("dut_charge_pC", "pC")
        assert unit == "fC"
        assert scale == pytest.approx(1000.0)

    def test_non_charge_quantity_passes_through_unscaled(self):
        unit, scale = display_unit_scale("dut_amplitude_V", "V")
        assert unit == "V"
        assert scale == pytest.approx(1.0)

    def test_dimensionless_quantity_passes_through_unscaled(self):
        unit, scale = display_unit_scale("dut_charge_norm", "")
        assert unit == ""
        assert scale == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# strip_unit_suffix                                                           #
# --------------------------------------------------------------------------- #

class TestStripUnitSuffix:
    def test_strips_matching_native_unit_suffix(self):
        assert strip_unit_suffix("dut_charge_pC", "pC") == "dut_charge"
        assert strip_unit_suffix("drift_time_s", "s") == "drift_time"
        assert strip_unit_suffix("dut_amplitude_V", "V") == "dut_amplitude"

    def test_no_suffix_match_returns_unchanged(self):
        assert strip_unit_suffix("dut_charge_norm", "pC") == "dut_charge_norm"

    def test_empty_unit_returns_unchanged(self):
        assert strip_unit_suffix("dut_charge_norm", "") == "dut_charge_norm"

    def test_avoids_doubled_label_with_display_unit_scale(self):
        """The exact bug this exists to prevent: a naive f"{qty}_{unit}"
        build doubles the unit for a quantity whose stored name already
        spells out its native one."""
        qty, native = "dut_charge_pC", "pC"
        disp_unit, _ = display_unit_scale(qty, native)
        base = strip_unit_suffix(qty, native)
        label = f"{base}_{disp_unit}" if disp_unit else base
        assert label == "dut_charge_fC"
        assert "pC" not in label
