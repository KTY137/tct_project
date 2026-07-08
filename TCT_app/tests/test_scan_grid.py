"""Canonical points -> 2-D grid reconstruction (analysis.scan_grid)."""
from __future__ import annotations

import numpy as np
import pytest

from analysis.scan_grid import ScanGridResult, grid_extent, points_to_grid


def test_full_grid_no_missing_no_duplicates():
    xs = [0.0, 0.0, 1.0, 1.0]
    ys = [0.0, 1.0, 0.0, 1.0]
    vals = [10.0, 20.0, 30.0, 40.0]
    result = points_to_grid(xs, ys, vals)

    assert result.grid.shape == (2, 2)
    assert list(result.x_mm) == [0.0, 1.0]
    assert list(result.y_mm) == [0.0, 1.0]
    assert result.n_points == 4
    assert result.n_unique_points == 4
    assert result.n_duplicate_points == 0
    assert result.n_missing == 0
    assert result.n_nan_values == 0
    # grid[i, j] <-> (x_mm[i], y_mm[j])
    assert result.grid[0, 0] == 10.0
    assert result.grid[0, 1] == 20.0
    assert result.grid[1, 0] == 30.0
    assert result.grid[1, 1] == 40.0


def test_partial_mid_scan_missing_cells_are_nan_and_counted():
    # A 3x3 raster where only 6 of 9 points have arrived so far (live view).
    # Every x and every y value is touched at least once (so the grid axes
    # are still the full 3x3), but (0, 2), (1, 1), (2, 0) never landed.
    xs = [0.0, 0.0, 1.0, 1.0, 2.0, 2.0]
    ys = [0.0, 1.0, 0.0, 2.0, 1.0, 2.0]
    vals = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    result = points_to_grid(xs, ys, vals)

    assert result.grid.shape == (3, 3)
    assert result.n_points == 6
    assert result.n_unique_points == 6
    assert result.n_missing == 9 - 6
    assert np.count_nonzero(np.isnan(result.grid)) == result.n_missing
    # sampled cells keep their value
    assert result.grid[0, 0] == 0.0
    assert result.grid[0, 1] == 1.0
    assert result.grid[2, 2] == 5.0
    # never-sampled combinations are NaN
    assert np.isnan(result.grid[0, 2])
    assert np.isnan(result.grid[1, 1])
    assert np.isnan(result.grid[2, 0])


def test_unordered_points_give_the_same_grid_as_ordered():
    xs = [0.0, 0.0, 1.0, 1.0, 2.0, 2.0]
    ys = [0.0, 1.0, 0.0, 1.0, 0.0, 1.0]
    vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]

    ordered = points_to_grid(xs, ys, vals)

    rng = np.random.default_rng(0)
    perm = rng.permutation(len(xs))
    shuffled = points_to_grid(
        np.array(xs)[perm], np.array(ys)[perm], np.array(vals)[perm]
    )

    assert np.array_equal(ordered.x_mm, shuffled.x_mm)
    assert np.array_equal(ordered.y_mm, shuffled.y_mm)
    np.testing.assert_array_equal(ordered.grid, shuffled.grid)
    assert ordered.n_missing == shuffled.n_missing == 0


def test_nan_input_value_counted_separately_from_missing_cells():
    xs = [0.0, 0.0, 1.0]
    ys = [0.0, 1.0, 0.0]
    vals = [1.0, float("nan"), 3.0]
    result = points_to_grid(xs, ys, vals)

    # 2x2 grid, (1, 1) never sampled -> missing; (0, 1) sampled but NaN value.
    assert result.grid.shape == (2, 2)
    assert result.n_missing == 1               # (1, 1) never visited
    assert result.n_nan_values == 1             # the (0.0, 1.0) point's value
    assert np.isnan(result.grid[0, 1])          # sampled-but-NaN cell
    assert np.isnan(result.grid[1, 1])          # never-sampled cell
    assert result.grid[0, 0] == 1.0
    assert result.grid[1, 0] == 3.0


def test_single_point():
    result = points_to_grid([5.0], [7.0], [42.0])
    assert result.grid.shape == (1, 1)
    assert result.grid[0, 0] == 42.0
    assert result.n_missing == 0
    assert result.n_duplicate_points == 0

    pos, scale = grid_extent(result)
    assert pos == (5.0, 7.0)
    # No adjacent sample to infer a pitch from -> documented 1.0 mm/px fallback.
    assert scale == (1.0, 1.0)


def test_non_square_grid():
    # 3 distinct x values, 2 distinct y values -> 3x2, not square.
    xs = [0.0, 0.0, 1.0, 1.0, 2.0, 2.0]
    ys = [0.0, 1.0, 0.0, 1.0, 0.0, 1.0]
    vals = [1, 2, 3, 4, 5, 6]
    result = points_to_grid(xs, ys, vals)
    assert result.grid.shape == (3, 2)
    assert len(result.x_mm) == 3
    assert len(result.y_mm) == 2
    assert result.n_missing == 0


def test_duplicate_point_last_value_wins_and_is_counted():
    xs = [0.0, 0.0]
    ys = [0.0, 0.0]
    vals = [1.0, 2.0]     # same (rounded) coordinate revisited
    result = points_to_grid(xs, ys, vals)

    assert result.grid.shape == (1, 1)
    assert result.grid[0, 0] == 2.0     # last one wins
    assert result.n_points == 2
    assert result.n_unique_points == 1
    assert result.n_duplicate_points == 1
    assert result.n_missing == 0


def test_rounding_absorbs_floating_point_jitter():
    # Two "same" positions differing only in float noise below the default
    # 6-decimal tolerance must merge into a single grid column, not split.
    xs = [0.0, 0.0]
    ys = [1.0, 1.0 + 1e-9]
    vals = [1.0, 2.0]
    result = points_to_grid(xs, ys, vals)
    assert result.grid.shape == (1, 1)
    assert result.n_duplicate_points == 1


def test_mismatched_lengths_raise_value_error():
    with pytest.raises(ValueError):
        points_to_grid([0.0, 1.0], [0.0], [1.0, 2.0])


def test_grid_extent_multi_point_pitch():
    xs = [0.0, 0.0, 2.0, 2.0]
    ys = [0.0, 4.0, 0.0, 4.0]
    vals = [1.0, 2.0, 3.0, 4.0]
    result = points_to_grid(xs, ys, vals)
    pos, scale = grid_extent(result)
    assert pos == (0.0, 0.0)
    assert scale == (2.0, 4.0)


def test_result_is_a_scan_grid_result_dataclass():
    result = points_to_grid([0.0], [0.0], [1.0])
    assert isinstance(result, ScanGridResult)
