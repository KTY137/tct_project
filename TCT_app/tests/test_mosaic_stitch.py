"""Unit tests for analysis/mosaic_stitch.py — pure numpy, no Qt, no hardware.

Canvas convention under test (matches analysis/mosaic_stitch.py exactly):
canvas shape is ``(H_px, W_px)``, row axis (0) tracks Y, column axis (1)
tracks X; ``origin_mm`` is the mm position of canvas pixel ``(row=0,
col=0)``. All numeric expectations below were cross-checked against the
actual implementation before being pinned here (see module docstrings for
the derivations, e.g. the phase-correlation sign convention).
"""
from __future__ import annotations

import numpy as np
import pytest

from analysis.camera_calibration import AffineFit
from analysis.mosaic_stitch import (
    OVERLAP_FRAC_MAX,
    OVERLAP_FRAC_MIN,
    canvas_geometry,
    mm_to_px,
    place_tiles,
    plan_grid,
    px_to_mm,
    refine_offset,
)

nan = float("nan")


# --------------------------------------------------------------------------- #
# plan_grid                                                                   #
# --------------------------------------------------------------------------- #

class TestPlanGrid:
    def test_overlap_bounds_are_five_and_fifty_percent(self):
        assert OVERLAP_FRAC_MIN == pytest.approx(0.05)
        assert OVERLAP_FRAC_MAX == pytest.approx(0.50)

    def test_counts_and_snake_order(self):
        # area 26 x 18 mm, 10x10 mm FOV, 20% overlap -> stride 8mm/tile.
        # cols: ceil((26-10)/8)+1 = 3; rows: ceil((18-10)/8)+1 = 2.
        centers, (rows, cols) = plan_grid((0, 0, 26, 18), (10, 10), 0.2)
        assert (rows, cols) == (2, 3)
        assert len(centers) == rows * cols

        expected = [
            (5.0, 5.0), (13.0, 5.0), (21.0, 5.0),   # row 0: left -> right
            (21.0, 13.0), (13.0, 13.0), (5.0, 13.0),  # row 1: right -> left (snake)
        ]
        assert len(centers) == len(expected)
        for (x, y), (ex, ey) in zip(centers, expected):
            assert x == pytest.approx(ex)
            assert y == pytest.approx(ey)

    def test_single_tile_when_area_smaller_than_fov(self):
        centers, rowscols = plan_grid((2, 3, 7, 8), (10, 10), 0.2)
        assert rowscols == (1, 1)
        assert len(centers) == 1
        x, y = centers[0]
        assert x == pytest.approx(4.5)   # area centre: (2+7)/2
        assert y == pytest.approx(5.5)   # area centre: (3+8)/2

    def test_single_column_when_only_x_extent_fits_fov(self):
        # width 5mm fits in a 10mm FOV (cols=1); height 18mm does not (rows=2).
        centers, (rows, cols) = plan_grid((0, 0, 5, 18), (10, 10), 0.2)
        assert (rows, cols) == (2, 1)
        assert centers == [(2.5, 5.0), (2.5, 13.0)]

    def test_zero_extent_area_is_a_single_tile(self):
        centers, rowscols = plan_grid((4.0, 4.0, 4.0, 4.0), (10, 10), 0.2)
        assert rowscols == (1, 1)
        assert centers == [(4.0, 4.0)]

    def test_overlap_below_minimum_clamps_to_five_percent(self):
        a, rc_a = plan_grid((0, 0, 26, 18), (10, 10), 0.0)
        b, rc_b = plan_grid((0, 0, 26, 18), (10, 10), OVERLAP_FRAC_MIN)
        assert rc_a == rc_b
        assert a == b

    def test_overlap_above_maximum_clamps_to_fifty_percent(self):
        a, rc_a = plan_grid((0, 0, 26, 18), (10, 10), 0.9)
        b, rc_b = plan_grid((0, 0, 26, 18), (10, 10), OVERLAP_FRAC_MAX)
        assert rc_a == rc_b
        assert a == b

    def test_negative_overlap_also_clamps_to_minimum(self):
        a, rc_a = plan_grid((0, 0, 26, 18), (10, 10), -5.0)
        b, rc_b = plan_grid((0, 0, 26, 18), (10, 10), OVERLAP_FRAC_MIN)
        assert rc_a == rc_b
        assert a == b

    def test_nonpositive_fov_raises(self):
        with pytest.raises(ValueError):
            plan_grid((0, 0, 10, 10), (0.0, 5.0), 0.2)
        with pytest.raises(ValueError):
            plan_grid((0, 0, 10, 10), (5.0, -1.0), 0.2)

    def test_inverted_area_raises(self):
        with pytest.raises(ValueError):
            plan_grid((10, 0, 0, 10), (5, 5), 0.2)   # x1 < x0
        with pytest.raises(ValueError):
            plan_grid((0, 10, 10, 0), (5, 5), 0.2)   # y1 < y0

    def test_full_coverage_edges_reach_area_boundary(self):
        """Every axis's outer tile edges must reach (or exceed) the requested
        area boundary -- no ragged partial tile left uncovered."""
        area = (0, 0, 26, 18)
        fov = (10, 10)
        centers, (rows, cols) = plan_grid(area, fov, 0.2)
        xs = sorted({x for x, _ in centers})
        ys = sorted({y for _, y in centers})
        assert xs[0] - fov[0] / 2 <= area[0] + 1e-9
        assert xs[-1] + fov[0] / 2 >= area[2] - 1e-9
        assert ys[0] - fov[1] / 2 <= area[1] + 1e-9
        assert ys[-1] + fov[1] / 2 >= area[3] - 1e-9


# --------------------------------------------------------------------------- #
# canvas_geometry                                                             #
# --------------------------------------------------------------------------- #

class TestCanvasGeometry:
    def test_shape_and_origin(self):
        shape_px, origin_mm = canvas_geometry((0, 0, 12, 6), 5.0)
        assert shape_px == (30, 60)     # (H_px, W_px) = (6*5, 12*5)
        assert origin_mm == (0.0, 0.0)

    def test_nonzero_origin_passes_through(self):
        shape_px, origin_mm = canvas_geometry((2.0, -3.0, 4.0, 1.0), 10.0)
        assert shape_px == (40, 20)
        assert origin_mm == (2.0, -3.0)

    def test_partial_pixel_rounds_up(self):
        # width 1.01mm @ 3 px/mm = 3.03px -> ceils to 4; height 1.0mm -> 3.
        shape_px, _ = canvas_geometry((0, 0, 1.01, 1.0), 3.0)
        assert shape_px == (3, 4)

    def test_zero_extent_area_still_yields_one_pixel(self):
        shape_px, origin_mm = canvas_geometry((5.0, 5.0, 5.0, 5.0), 10.0)
        assert shape_px == (1, 1)
        assert origin_mm == (5.0, 5.0)

    def test_nonpositive_px_per_mm_raises(self):
        with pytest.raises(ValueError):
            canvas_geometry((0, 0, 10, 10), 0.0)
        with pytest.raises(ValueError):
            canvas_geometry((0, 0, 10, 10), -2.0)

    def test_inverted_area_raises(self):
        with pytest.raises(ValueError):
            canvas_geometry((10, 0, 0, 10), 5.0)


def _rotated_sheared_affine(scale=10.0, degrees=15.0, shear=0.1, offset_px=(5.0, -3.0)):
    """A hand-built (not fitted) rotation+shear+scale AffineFit for tests --
    no correspondence points needed, just a known, invertible matrix."""
    theta = np.radians(degrees)
    matrix = scale * np.array(
        [
            [np.cos(theta) + shear * np.sin(theta), -np.sin(theta)],
            [np.sin(theta), np.cos(theta)],
        ]
    )
    return AffineFit(
        matrix_px_per_mm=matrix,
        offset_px=np.array(offset_px, dtype=np.float64),
        residuals_px=np.zeros((3, 2)),
        rms_px=0.0,
        max_abs_px=0.0,
        rank=3,
    )


class TestCanvasGeometryAffine:
    def test_affine_bounds_cover_all_four_projected_corners(self):
        """Rotation means all FOUR area corners (not just the two diagonal
        ones the scalar path uses) can extend the bounding box."""
        affine = _rotated_sheared_affine()
        area = (0.0, 0.0, 10.0, 8.0)
        shape_px, origin_mm = canvas_geometry(area, 10.0, affine=affine)

        corners_mm = np.array([[0, 0], [10, 0], [10, 8], [0, 8]], dtype=np.float64)
        corners_px = affine.predict(corners_mm)
        expect_w = corners_px[:, 0].max() - corners_px[:, 0].min()
        expect_h = corners_px[:, 1].max() - corners_px[:, 1].min()

        assert shape_px[0] == pytest.approx(expect_h, abs=1.0)
        assert shape_px[1] == pytest.approx(expect_w, abs=1.0)

        # origin_mm must map (via affine) back to the bounding box's own
        # minimum-corner pixel -- "mm position of canvas pixel (0, 0)".
        origin_px = affine.predict(np.array([[origin_mm[0], origin_mm[1]]]))[0]
        assert origin_px[0] == pytest.approx(corners_px[:, 0].min(), abs=1e-6)
        assert origin_px[1] == pytest.approx(corners_px[:, 1].min(), abs=1e-6)

    def test_affine_none_matches_scalar_path(self):
        """affine=None (default) is exactly the pre-existing scalar path."""
        area = (0.0, 0.0, 12.0, 6.0)
        assert canvas_geometry(area, 5.0) == canvas_geometry(area, 5.0, affine=None)

    def test_affine_zero_extent_area_still_one_pixel(self):
        affine = _rotated_sheared_affine()
        shape_px, _ = canvas_geometry((5.0, 5.0, 5.0, 5.0), 10.0, affine=affine)
        assert shape_px == (1, 1)


# --------------------------------------------------------------------------- #
# mm <-> px round trip                                                        #
# --------------------------------------------------------------------------- #

class TestMmPxRoundTrip:
    def test_mm_to_px_to_mm_recovers_original(self):
        origin = (0.0, 0.0)
        px_per_mm = 12.3
        x0, y0 = 3.456, -1.234
        col, row = mm_to_px(x0, y0, origin, px_per_mm)
        x1, y1 = px_to_mm(col, row, origin, px_per_mm)
        assert x1 == pytest.approx(x0, abs=1e-9)
        assert y1 == pytest.approx(y0, abs=1e-9)

    def test_px_to_mm_to_px_recovers_original(self):
        origin = (2.5, -7.0)
        px_per_mm = 8.0
        col0, row0 = 100.0, 42.0
        x, y = px_to_mm(col0, row0, origin, px_per_mm)
        col1, row1 = mm_to_px(x, y, origin, px_per_mm)
        assert col1 == pytest.approx(col0, abs=1e-9)
        assert row1 == pytest.approx(row0, abs=1e-9)

    def test_origin_pixel_maps_to_origin_mm(self):
        origin = (5.0, -3.0)
        col, row = mm_to_px(origin[0], origin[1], origin, px_per_mm=4.0)
        assert (col, row) == pytest.approx((0.0, 0.0))

    def test_matches_canvas_geometry_origin_convention(self):
        area_mm = (0.0, 0.0, 10.0, 10.0)
        px_per_mm = 2.0
        shape_px, origin_mm = canvas_geometry(area_mm, px_per_mm)
        # The area's own min corner must map to pixel (0, 0).
        col, row = mm_to_px(area_mm[0], area_mm[1], origin_mm, px_per_mm)
        assert (col, row) == pytest.approx((0.0, 0.0))
        # The area's max corner must map at/near the far pixel edge.
        col1, row1 = mm_to_px(area_mm[2], area_mm[3], origin_mm, px_per_mm)
        assert col1 == pytest.approx(shape_px[1], abs=1e-9)
        assert row1 == pytest.approx(shape_px[0], abs=1e-9)


# --------------------------------------------------------------------------- #
# place_tiles                                                                 #
# --------------------------------------------------------------------------- #

class TestPlaceTilesGroundTruth:
    """Slice tiles out of one consistent synthetic 'world' array at their
    true pixel positions -- since overlapping tiles then always AGREE
    pixel-for-pixel, any weighted blend of them must reconstruct the world
    exactly (mod float noise), regardless of the feather ramp's exact shape.
    This is a stronger, implementation-agnostic check than pinning the ramp
    formula itself."""

    def _build(self, area_mm, fov_mm, overlap, px_per_mm=1.0):
        centers, rowscols = plan_grid(area_mm, fov_mm, overlap)
        shape_px, origin_mm = canvas_geometry(area_mm, px_per_mm)
        h_px, w_px = shape_px
        world = 10.0 * np.add.outer(np.arange(h_px), np.zeros(w_px)) + \
            2.0 * np.add.outer(np.zeros(h_px), np.arange(w_px))
        tw = int(round(fov_mm[0] * px_per_mm))
        th = int(round(fov_mm[1] * px_per_mm))
        tiles = []
        for x_mm, y_mm in centers:
            col_px, row_px = mm_to_px(x_mm, y_mm, origin_mm, px_per_mm)
            r0 = int(round(row_px - th / 2.0))
            c0 = int(round(col_px - tw / 2.0))
            tiles.append((world[r0:r0 + th, c0:c0 + tw].copy(), (x_mm, y_mm)))
        return world, shape_px, origin_mm, tiles

    def test_gradient_world_reconstructed_including_overlap_zones(self):
        world, shape_px, origin_mm, tiles = self._build(
            (0, 0, 26, 18), (10, 10), 0.2
        )
        canvas, weight_map = place_tiles(shape_px, tiles, 1.0, origin_mm)
        assert canvas.shape == shape_px
        assert not np.any(np.isnan(canvas)), "full-coverage grid must leave no gaps"
        assert np.allclose(canvas, world, atol=1e-9)
        assert np.array_equal(np.isnan(canvas), weight_map == 0.0)

    def test_constant_world_reconstructed_exactly(self):
        centers, rowscols = plan_grid((0, 0, 26, 18), (10, 10), 0.2)
        shape_px, origin_mm = canvas_geometry((0, 0, 26, 18), 1.0)
        tiles = [(np.full((10, 10), 7.0), c) for c in centers]
        canvas, weight_map = place_tiles(shape_px, tiles, 1.0, origin_mm)
        covered = weight_map > 0.0
        assert covered.any()
        assert np.allclose(canvas[covered], 7.0, atol=1e-9)


class TestPlaceTilesBlendingAndNaN:
    def test_order_independence_and_blend_strictly_between(self):
        tile_a = np.full((10, 10), 4.0)
        tile_b = np.full((10, 10), 10.0)
        tiles_ab = [(tile_a, (5.0, 5.0)), (tile_b, (11.0, 5.0))]
        tiles_ba = [(tile_b, (11.0, 5.0)), (tile_a, (5.0, 5.0))]

        canvas_ab, _ = place_tiles((10, 16), tiles_ab, 1.0, (0.0, 0.0))
        canvas_ba, _ = place_tiles((10, 16), tiles_ba, 1.0, (0.0, 0.0))

        assert np.allclose(canvas_ab, canvas_ba, equal_nan=True), (
            "placement order must never change the stitched result "
            "-- a hard 'last tile wins' overwrite would fail this"
        )
        # A column well inside the true overlap footprint (cols 6-9) must be
        # a genuine blend, not equal to either source tile's raw value.
        overlap_val = canvas_ab[5, 7]
        assert 4.0 < overlap_val < 10.0
        # Columns covered by only one tile must equal that tile exactly.
        assert canvas_ab[5, 0] == pytest.approx(4.0)
        assert canvas_ab[5, 15] == pytest.approx(10.0)

    def test_missing_tile_region_stays_nan(self):
        tile = np.full((10, 10), 5.0)
        canvas, weight_map = place_tiles((20, 20), [(tile, (5.0, 5.0))], 1.0, (0.0, 0.0))
        assert np.allclose(canvas[0:10, 0:10], 5.0)
        assert np.all(np.isnan(canvas[10:20, 10:20]))
        assert np.all(weight_map[10:20, 10:20] == 0.0)

    def test_internal_nan_pixel_not_averaged_as_zero(self):
        tile = np.full((10, 10), 5.0)
        tile[3, 3] = nan
        canvas, weight_map = place_tiles((10, 10), [(tile, (5.0, 5.0))], 1.0, (0.0, 0.0))
        assert np.isnan(canvas[3, 3]), "a NaN source pixel with no other tile covering it stays NaN"
        assert weight_map[3, 3] == 0.0
        assert canvas[3, 4] == pytest.approx(5.0), "neighbouring valid pixels are unaffected"

    def test_nan_pixel_filled_by_overlapping_tile(self):
        """A camera dropout in one tile is masked out, not zero-averaged,
        so an overlapping second tile's real value wins cleanly."""
        tile_a = np.full((10, 10), 5.0)
        tile_a[5, 8] = nan     # dropout inside the overlap footprint
        tile_b = np.full((10, 10), 5.0)
        canvas, _ = place_tiles((10, 16), [(tile_a, (5.0, 5.0)), (tile_b, (11.0, 5.0))],
                                 1.0, (0.0, 0.0))
        assert canvas[5, 8] == pytest.approx(5.0)

    def test_empty_tiles_list_yields_all_nan(self):
        canvas, weight_map = place_tiles((5, 5), [], 1.0, (0.0, 0.0))
        assert np.all(np.isnan(canvas))
        assert np.all(weight_map == 0.0)

    def test_tile_entirely_off_canvas_contributes_nothing(self):
        tile = np.full((3, 3), 1.0)
        canvas, weight_map = place_tiles((5, 5), [(tile, (500.0, 500.0))], 1.0, (0.0, 0.0))
        assert np.all(np.isnan(canvas))
        assert np.all(weight_map == 0.0)

    def test_tile_partially_off_canvas_is_clipped_not_dropped(self):
        tile = np.full((10, 10), 9.0)
        # Centred at (0, 0) with origin (0,0) -> tile spans rows/cols
        # [-5, 5); only its [0, 5) x [0, 5) corner overlaps the canvas.
        canvas, weight_map = place_tiles((10, 10), [(tile, (0.0, 0.0))], 1.0, (0.0, 0.0))
        assert canvas[0, 0] == pytest.approx(9.0)
        assert canvas[4, 4] == pytest.approx(9.0)
        assert np.isnan(canvas[9, 9])       # outside the clipped placement
        assert weight_map[9, 9] == 0.0

    def test_nonpositive_canvas_shape_raises(self):
        with pytest.raises(ValueError):
            place_tiles((0, 10), [], 1.0, (0.0, 0.0))

    def test_nonpositive_px_per_mm_raises(self):
        with pytest.raises(ValueError):
            place_tiles((10, 10), [], 0.0, (0.0, 0.0))

    def test_non_2d_tile_image_raises(self):
        bad = np.zeros((4, 4, 3))   # e.g. an accidental RGB frame
        with pytest.raises(ValueError):
            place_tiles((10, 10), [(bad, (5.0, 5.0))], 1.0, (0.0, 0.0))

    def test_empty_tile_image_raises(self):
        bad = np.zeros((0, 5))
        with pytest.raises(ValueError):
            place_tiles((10, 10), [(bad, (5.0, 5.0))], 1.0, (0.0, 0.0))


# --------------------------------------------------------------------------- #
# place_tiles(affine=...) placement                                          #
# --------------------------------------------------------------------------- #

class TestPlaceTilesAffine:
    def test_known_center_lands_at_affine_predicted_canvas_px(self):
        """A single-hot-pixel marker tile placed via *affine* must land at
        exactly ``affine.predict(center_mm) - affine.predict(origin_mm)``
        (rounded the same nearest-pixel way the scalar path rounds)."""
        affine = _rotated_sheared_affine()
        area = (0.0, 0.0, 10.0, 8.0)
        shape_px, origin_mm = canvas_geometry(area, 10.0, affine=affine)

        tile = np.zeros((4, 4))
        tile[2, 2] = 9.0
        center_mm = (5.0, 4.0)
        canvas, weight_map = place_tiles(
            shape_px, [(tile, center_mm)], 10.0, origin_mm, affine=affine
        )
        peak = np.unravel_index(int(np.nanargmax(canvas)), canvas.shape)

        rel_px = affine.predict(np.array([center_mm])) - affine.predict(
            np.array([[origin_mm[0], origin_mm[1]]])
        )
        col_px, row_px = float(rel_px[0, 0]), float(rel_px[0, 1])
        expect_r0 = int(round(row_px - 4 / 2.0))
        expect_c0 = int(round(col_px - 4 / 2.0))
        assert peak == (expect_r0 + 2, expect_c0 + 2)
        assert weight_map[peak] > 0.0

    def test_affine_none_is_byte_identical_to_scalar_mm_to_px(self):
        """affine=None (default) must reproduce the scalar path exactly --
        no new rounding/branch differences sneak in."""
        tiles = [(np.full((10, 10), 4.0), (5.0, 5.0)), (np.full((10, 10), 10.0), (11.0, 5.0))]
        canvas_default, w_default = place_tiles((10, 16), tiles, 1.0, (0.0, 0.0))
        canvas_explicit, w_explicit = place_tiles(
            (10, 16), tiles, 1.0, (0.0, 0.0), affine=None
        )
        np.testing.assert_array_equal(canvas_default, canvas_explicit)
        np.testing.assert_array_equal(w_default, w_explicit)


class TestPlaceTilesDefaultApiUnchanged:
    """Scalar-path regression marker: the pre-existing 47 tests above are
    the real regression suite (unmodified); this class just pins the
    *return shape* contract the new opt-in kwargs must not disturb."""

    def test_default_call_returns_a_plain_2tuple(self):
        tile = np.full((5, 5), 3.0)
        result = place_tiles((10, 10), [(tile, (2.5, 2.5))], 1.0, (0.0, 0.0))
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_return_diagnostics_false_is_still_a_2tuple(self):
        tile = np.full((5, 5), 3.0)
        result = place_tiles(
            (10, 10), [(tile, (2.5, 2.5))], 1.0, (0.0, 0.0), return_diagnostics=False
        )
        assert len(result) == 2


# --------------------------------------------------------------------------- #
# refine_offset (v2 hook)                                                     #
# --------------------------------------------------------------------------- #

class TestRefineOffset:
    def _textured_tile(self, seed=0, shape=(48, 48)):
        rng = np.random.default_rng(seed)
        return rng.standard_normal(shape)

    def test_recovers_known_synthetic_shift(self):
        tile_a = self._textured_tile()
        dy0, dx0 = 3, 2
        tile_b = np.roll(np.roll(tile_a, dy0, axis=0), dx0, axis=1)

        dy, dx = refine_offset(tile_a, tile_b, nominal_shift_px=(0.0, 0.0))

        assert dy == pytest.approx(dy0, abs=0.1)
        assert dx == pytest.approx(dx0, abs=0.1)

    def test_accepts_measurement_close_to_nominal(self):
        tile_a = self._textured_tile(seed=1)
        dy0, dx0 = -2, 4
        tile_b = np.roll(np.roll(tile_a, dy0, axis=0), dx0, axis=1)

        # Nominal close to (but not exactly) the true shift -- refine_offset
        # should still return the MEASURED value, not just echo the nominal.
        dy, dx = refine_offset(tile_a, tile_b, nominal_shift_px=(-2.3, 3.7))

        assert dy == pytest.approx(dy0, abs=0.1)
        assert dx == pytest.approx(dx0, abs=0.1)

    def test_rejects_absurd_match_and_returns_nominal(self):
        tile_a = self._textured_tile(seed=2)
        # A 20px shift on a 48px tile is far beyond the +-10% FOV cap (4.8px).
        tile_b = np.roll(np.roll(tile_a, 20, axis=0), 0, axis=1)
        nominal = (0.0, 0.0)

        result = refine_offset(tile_a, tile_b, nominal_shift_px=nominal)

        assert result == nominal

    def test_rejects_when_only_one_axis_is_absurd(self):
        tile_a = self._textured_tile(seed=3)
        tile_b = np.roll(np.roll(tile_a, 1, axis=0), 30, axis=1)  # dx way over cap
        nominal = (0.0, 0.0)

        result = refine_offset(tile_a, tile_b, nominal_shift_px=nominal)

        assert result == nominal, "a garbage match is rejected wholesale, not per-axis"

    def test_tiny_tiles_return_nominal_without_crashing(self):
        tiny_a = np.zeros((2, 2))
        tiny_b = np.ones((2, 2))
        nominal = (1.5, -2.5)

        result = refine_offset(tiny_a, tiny_b, nominal_shift_px=nominal)

        assert result == nominal

    def test_mismatched_shapes_are_cropped_not_rejected_outright(self):
        tile_a = self._textured_tile(seed=4, shape=(48, 48))
        tile_b = np.roll(np.roll(tile_a, 2, axis=0), 1, axis=1)[:40, :44]

        dy, dx = refine_offset(tile_a, tile_b, nominal_shift_px=(0.0, 0.0))

        assert dy == pytest.approx(2.0, abs=0.2)
        assert dx == pytest.approx(1.0, abs=0.2)

    def test_non_2d_tile_raises(self):
        bad = np.zeros((4, 4, 3))
        good = np.zeros((4, 4))
        with pytest.raises(ValueError):
            refine_offset(bad, good, (0.0, 0.0))


# --------------------------------------------------------------------------- #
# place_tiles(refine=True) -- pairwise seam refinement integration            #
# --------------------------------------------------------------------------- #

class TestPlaceTilesRefineRecovery:
    def test_refine_recovers_injected_seam_shift_under_vignette(self):
        """Two same-source-texture tiles nominally 30% overlapping (a
        realistic mosaic stride), with a genuine 4px registration error
        baked into tile_b's content on top of a shared synthetic vignette.
        Both directions: refine=True measurably corrects it; refine=False
        leaves it (the shift "persists")."""
        rng = np.random.default_rng(11)
        S = 80
        tile_a = rng.standard_normal((S, S))
        true_shift_dx = -20.0  # wrapped nominal (-24) + injected error (+4)
        tile_b = np.roll(tile_a, shift=int(true_shift_dx), axis=1)

        # Synthetic vignette: same smooth radial bump baked into both tiles
        # (an optical vignette is a camera property, not scene content) --
        # exercises prepare_metrology_roi's illumination stabilization
        # inside place_tiles(refine=True).
        yy, xx = np.mgrid[0:S, 0:S]
        vignette = 25.0 * np.exp(
            -(((xx - S / 2) ** 2 + (yy - S / 2) ** 2) / (2 * (S / 3.0) ** 2))
        )
        tile_a_v = tile_a + vignette
        tile_b_v = tile_b + vignette

        center_a = (40.0, 40.0)
        center_b = (96.0, 40.0)  # nominal dx=56 -> 30% overlap, wraps to -24
        tiles = [(tile_a_v, center_a), (tile_b_v, center_b)]

        _, _, diag_refined = place_tiles(
            (100, 200), tiles, 1.0, (0.0, 0.0), refine=True, return_diagnostics=True
        )
        _, _, diag_plain = place_tiles(
            (100, 200), tiles, 1.0, (0.0, 0.0), refine=False, return_diagnostics=True
        )

        # Direction 1: refine=True measurably corrects the injected error
        # (total pairwise correction ~4px, split in half onto each tile).
        (dy_a, dx_a), (dy_b, dx_b) = diag_refined["applied_offset_px"]
        assert dx_b - dx_a == pytest.approx(4.0, abs=0.5)
        assert diag_refined["mean_abs_offset_px"] > 1.0

        # Direction 2: refine=False leaves the injected error completely
        # uncorrected -- the shift persists by construction (the API never
        # looks at pixel content when refine=False).
        assert diag_plain["applied_offset_px"] == [(0.0, 0.0), (0.0, 0.0)]
        assert diag_plain["mean_abs_offset_px"] == 0.0


class TestPlaceTilesRefineClamp:
    def test_large_correction_on_thin_overlap_is_clamped_and_counted(self):
        """A correction refine_offset itself trusts (comfortably inside its
        own +-10%-of-tile accept window) can still be large RELATIVE to a
        thin nominal overlap strip -- place_tiles' own +-25%-of-overlap
        clamp exists exactly for that gap (a garbage correlation must not
        throw a tile), and it is independent of refine_offset's own gate
        (see place_tiles' "Seam refinement" docstring section)."""
        rng = np.random.default_rng(3)
        tile_a = rng.standard_normal((60, 60))
        tile_b = np.roll(tile_a, shift=-7, axis=1)

        center_a = (30.0, 30.0)
        center_b = (78.0, 30.0)  # nominal dx=48 -> 20% overlap (12px), wraps to -12
        tiles = [(tile_a, center_a), (tile_b, center_b)]

        _, _, diag = place_tiles(
            (100, 150), tiles, 1.0, (0.0, 0.0), refine=True, return_diagnostics=True
        )

        assert diag["n_clamped"] == 1
        # Clamp limit is 25% of the 12px overlap = 3px total correction,
        # split in half onto each tile -> +-1.5px each.
        (dy_a, dx_a), (dy_b, dx_b) = diag["applied_offset_px"]
        assert dx_a == pytest.approx(-1.5, abs=0.05)
        assert dx_b == pytest.approx(1.5, abs=0.05)

    def test_non_overlapping_tiles_are_never_refined(self):
        """Two tiles with no nominal overlap at all -- refine=True must not
        crash or fabricate a correction; nothing to clamp either."""
        tile_a = np.zeros((10, 10))
        tile_b = np.zeros((10, 10))
        tiles = [(tile_a, (0.0, 0.0)), (tile_b, (500.0, 500.0))]

        _, _, diag = place_tiles(
            (20, 20), tiles, 1.0, (0.0, 0.0), refine=True, return_diagnostics=True
        )
        assert diag["applied_offset_px"] == [(0.0, 0.0), (0.0, 0.0)]
        assert diag["n_clamped"] == 0


# --------------------------------------------------------------------------- #
# place_tiles(return_diagnostics=True) shape contract                        #
# --------------------------------------------------------------------------- #

class TestPlaceTilesDiagnosticsShape:
    def test_return_diagnostics_true_yields_3tuple_with_expected_keys(self):
        tile_a = np.full((10, 10), 1.0)
        tile_b = np.full((10, 10), 2.0)
        tiles = [(tile_a, (5.0, 5.0)), (tile_b, (11.0, 5.0))]

        result = place_tiles((10, 16), tiles, 1.0, (0.0, 0.0), return_diagnostics=True)

        assert len(result) == 3
        canvas, weight_map, diag = result
        assert canvas.shape == (10, 16)
        assert weight_map.shape == (10, 16)
        assert set(diag.keys()) == {"applied_offset_px", "n_clamped", "mean_abs_offset_px"}
        assert len(diag["applied_offset_px"]) == len(tiles)
        assert isinstance(diag["n_clamped"], int)
        assert isinstance(diag["mean_abs_offset_px"], float)

    def test_diagnostics_default_refine_false_are_all_zero(self):
        tile = np.full((10, 10), 1.0)
        _, _, diag = place_tiles(
            (10, 10), [(tile, (5.0, 5.0))], 1.0, (0.0, 0.0), return_diagnostics=True
        )
        assert diag["applied_offset_px"] == [(0.0, 0.0)]
        assert diag["n_clamped"] == 0
        assert diag["mean_abs_offset_px"] == 0.0

    def test_diagnostics_empty_tiles_list(self):
        _, _, diag = place_tiles((5, 5), [], 1.0, (0.0, 0.0), return_diagnostics=True)
        assert diag["applied_offset_px"] == []
        assert diag["n_clamped"] == 0
        assert diag["mean_abs_offset_px"] == 0.0
