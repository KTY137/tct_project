"""Unit tests for analysis/image_prep.py — pure numpy, no Qt, no hardware.

Covers: crop_roi's (y0, x0, h, w) convention + fail-closed bounds,
apply_dark_flat's hand-computed math + zero-guard + shape validation,
saturation_mask's dtype-derived vs explicit level, high_pass_filter
suppressing a smooth (vignette-like) gradient relative to real texture, the
textured > blurred > blank quality ordering, and the degenerate-never-raises
matrix (all-NaN, all-saturated, tiny/empty frames, a single poisoned
calibration pixel that must not NaN-poison the whole FFT-based blur).
"""
from __future__ import annotations

import numpy as np
import pytest

from analysis.image_prep import (
    PreparedROI,
    apply_dark_flat,
    crop_roi,
    high_pass_filter,
    prepare_metrology_roi,
    saturation_mask,
)


def _textured_frame(shape=(64, 64), seed=1, amp=40.0, base=120.0):
    """Bounded-uint8 frame with real pixel-to-pixel texture (i.i.d. noise)."""
    rng = np.random.default_rng(seed)
    return np.clip(base + amp * rng.standard_normal(shape), 0, 255).astype(np.uint8)


def _box_blur(image: np.ndarray, k: int) -> np.ndarray:
    """Crude O(N*k^2) box blur — test-only helper to build a "blurred" frame
    that is unambiguously a low-pass version of `_textured_frame`, without
    importing scipy/cv2 (this test module is not layer-restricted, but there
    is no need to add the dependency just for a fixture)."""
    img = image.astype(np.float64)
    pad = k // 2
    padded = np.pad(img, pad, mode="reflect")
    out = np.zeros_like(img)
    for i in range(img.shape[0]):
        for j in range(img.shape[1]):
            out[i, j] = padded[i:i + k, j:j + k].mean()
    return out


# --------------------------------------------------------------------------- #
# crop_roi: (y0, x0, h, w) convention + fail-closed bounds                    #
# --------------------------------------------------------------------------- #

class TestCropRoi:
    def test_roi_none_returns_frame_unchanged(self):
        frame = np.arange(20).reshape(4, 5)
        assert crop_roi(frame, None) is frame

    def test_convention_is_y0_x0_h_w_matching_numpy_slicing(self):
        frame = np.arange(100).reshape(10, 10)
        cropped = crop_roi(frame, (2, 3, 4, 5))
        assert cropped.shape == (4, 5)
        np.testing.assert_array_equal(cropped, frame[2:6, 3:8])

    @pytest.mark.parametrize("roi", [
        (0, 0, 0, 5),    # zero height
        (0, 0, 5, 0),    # zero width
        (0, 0, 5, -1),   # negative width
        (-1, 0, 5, 5),   # negative y origin
        (0, -1, 5, 5),   # negative x origin
        (8, 0, 5, 5),    # exceeds height (10)
        (0, 8, 5, 5),    # exceeds width (10)
    ])
    def test_invalid_bounds_raise_value_error_fail_closed(self, roi):
        frame = np.arange(100).reshape(10, 10)
        with pytest.raises(ValueError):
            crop_roi(frame, roi)

    def test_exact_fit_roi_does_not_raise(self):
        frame = np.arange(100).reshape(10, 10)
        cropped = crop_roi(frame, (0, 0, 10, 10))
        np.testing.assert_array_equal(cropped, frame)


# --------------------------------------------------------------------------- #
# apply_dark_flat: hand-computed math + zero-guard + shape validation         #
# --------------------------------------------------------------------------- #

class TestApplyDarkFlat:
    def test_dark_only_hand_computed(self):
        raw = np.array([[10.0, 20.0], [30.0, 40.0]])
        dark = np.array([[1.0, 2.0], [3.0, 4.0]])
        out = apply_dark_flat(raw, dark=dark)
        np.testing.assert_allclose(out, raw - dark)

    def test_flat_only_hand_computed(self):
        raw = np.array([[10.0, 20.0], [30.0, 40.0]])
        flat = np.array([[1.0, 2.0], [0.5, 4.0]])
        out = apply_dark_flat(raw, flat=flat)
        np.testing.assert_allclose(out, raw / flat)

    def test_dark_and_flat_together_hand_computed_with_zero_guard(self):
        raw = np.array([[10.0, 20.0], [30.0, 40.0]])
        dark = np.array([[1.0, 2.0], [3.0, 4.0]])
        # last entry is treated as a dead/unset calibration slot (guarded).
        flat = np.array([[1.0, 2.0], [0.5, 1e-9]])
        out = apply_dark_flat(raw, dark=dark, flat=flat)
        expected = np.array([
            [(10.0 - 1.0) / 1.0, (20.0 - 2.0) / 2.0],
            [(30.0 - 3.0) / 0.5, (40.0 - 4.0) / 1.0],  # /1.0: guarded divisor
        ])
        np.testing.assert_allclose(out, expected)

    def test_neither_dark_nor_flat_returns_raw_as_float64(self):
        raw = np.array([[1, 2], [3, 4]], dtype=np.uint8)
        out = apply_dark_flat(raw)
        assert out.dtype == np.float64
        np.testing.assert_allclose(out, raw.astype(np.float64))

    def test_dark_shape_mismatch_raises(self):
        raw = np.zeros((4, 4))
        with pytest.raises(ValueError):
            apply_dark_flat(raw, dark=np.zeros((3, 3)))

    def test_flat_shape_mismatch_raises(self):
        raw = np.zeros((4, 4))
        with pytest.raises(ValueError):
            apply_dark_flat(raw, flat=np.zeros((4, 3)))

    def test_flat_shape_mismatch_does_not_silently_broadcast(self):
        """A 1-D flat of length == width would otherwise numpy-broadcast
        across every row and silently produce a wrong-but-plausible result —
        must raise instead."""
        raw = np.ones((4, 4))
        with pytest.raises(ValueError):
            apply_dark_flat(raw, flat=np.ones(4))


# --------------------------------------------------------------------------- #
# saturation_mask: dtype-derived vs explicit level, NaN vs saturated          #
# --------------------------------------------------------------------------- #

class TestSaturationMask:
    def test_uint8_dtype_derived_level(self):
        raw = np.array([0, 100, 250, 255], dtype=np.uint8)
        mask, frac = saturation_mask(raw)
        # level = 0.98 * 255 = 249.9 -> 250 and 255 are saturated.
        np.testing.assert_array_equal(mask, [True, True, False, False])
        assert frac == pytest.approx(0.5)

    def test_uint16_dtype_derived_level(self):
        raw = np.array([0, 60000, 65535], dtype=np.uint16)
        mask, frac = saturation_mask(raw)
        # level = 0.98 * 65535 = 64224.3 -> 60000 is still below it.
        np.testing.assert_array_equal(mask, [True, True, False])
        assert frac == pytest.approx(1.0 / 3.0)

    def test_explicit_level_overrides_dtype_default(self):
        raw = np.array([0, 100, 200], dtype=np.uint8)
        mask, frac = saturation_mask(raw, saturation_level=150.0)
        np.testing.assert_array_equal(mask, [True, True, False])
        assert frac == pytest.approx(1.0 / 3.0)

    def test_float_frame_without_explicit_level_flags_nothing_saturated(self):
        raw = np.array([0.0, 1e6, 1e12], dtype=np.float64)
        mask, frac = saturation_mask(raw)
        np.testing.assert_array_equal(mask, [True, True, True])
        assert frac == 0.0

    def test_float_frame_with_explicit_level_still_works(self):
        raw = np.array([0.0, 5.0, 10.0], dtype=np.float64)
        mask, frac = saturation_mask(raw, saturation_level=5.0)
        np.testing.assert_array_equal(mask, [True, False, False])
        assert frac == pytest.approx(2.0 / 3.0)

    def test_non_finite_is_invalid_but_not_counted_as_saturated(self):
        raw = np.array([1.0, np.nan, np.inf], dtype=np.float64)
        mask, frac = saturation_mask(raw, saturation_level=100.0)
        np.testing.assert_array_equal(mask, [True, False, False])
        # Neither NaN nor +inf reaches the explicit level via a real
        # comparison (NaN comparisons are always False; +inf is caught by
        # `finite` first) -- both are "invalid", zero are "saturated".
        assert frac == 0.0


# --------------------------------------------------------------------------- #
# high_pass_filter / prepare_metrology_roi: kills a smooth vignette gradient  #
# --------------------------------------------------------------------------- #

class TestHighPassSuppressesGradient:
    def test_constant_image_highpass_is_exactly_zero(self):
        image = np.full((16, 16), 42.0)
        out = high_pass_filter(image, sigma_px=5.0)
        np.testing.assert_allclose(out, 0.0, atol=1e-9)

    def test_sigma_non_positive_returns_all_zero(self):
        image = np.arange(16.0).reshape(4, 4)
        out = high_pass_filter(image, sigma_px=0.0)
        np.testing.assert_allclose(out, 0.0, atol=1e-9)

    def test_gradient_frame_prepped_contrast_is_near_zero_vs_textured(self):
        """Correlation-relevant: a smooth vignette-like gradient must not
        look like real texture after prepare_metrology_roi — its contrast
        must be small relative to a genuinely textured frame of the same
        size/dynamic range (empirically ~5% at the default sigma; asserted
        with a generous margin to avoid flakiness)."""
        size = 128
        yy, xx = np.mgrid[0:size, 0:size]
        gradient = np.clip(50 + 0.5 * xx + 0.3 * yy, 0, 255).astype(np.uint8)
        textured = _textured_frame((size, size))

        r_gradient = prepare_metrology_roi(gradient)
        r_textured = prepare_metrology_roi(textured)

        assert r_gradient.contrast < 0.15 * r_textured.contrast
        assert r_gradient.quality < 0.05 * r_textured.quality


# --------------------------------------------------------------------------- #
# Quality ordering: textured > blurred > blank                                #
# --------------------------------------------------------------------------- #

class TestQualityOrdering:
    def test_textured_beats_blurred_beats_blank(self):
        textured = _textured_frame((64, 64), seed=1)
        blurred = np.clip(_box_blur(textured, k=15), 0, 255).astype(np.uint8)
        blank = np.full((64, 64), 120, dtype=np.uint8)

        r_textured = prepare_metrology_roi(textured)
        r_blurred = prepare_metrology_roi(blurred)
        r_blank = prepare_metrology_roi(blank)

        assert r_textured.quality > r_blurred.quality > r_blank.quality
        assert r_blank.quality == 0.0


# --------------------------------------------------------------------------- #
# Degenerate-input matrix: never raises, quality lands at 0                   #
# --------------------------------------------------------------------------- #

class TestDegenerateInputsNeverRaise:
    def test_all_nan_frame(self):
        frame = np.full((10, 10), np.nan, dtype=np.float64)
        result = prepare_metrology_roi(frame)
        assert isinstance(result, PreparedROI)
        assert result.quality == 0.0
        assert result.saturated_frac == 0.0   # NaN != "saturated"
        assert result.mask.sum() == 0
        assert np.all(np.isfinite(result.image))

    def test_all_saturated_frame(self):
        frame = np.full((10, 10), 255, dtype=np.uint8)
        result = prepare_metrology_roi(frame)
        assert result.quality == 0.0
        assert result.saturated_frac == 1.0
        assert result.mask.sum() == 0
        assert np.all(np.isfinite(result.image))

    @pytest.mark.parametrize("shape", [(1, 1), (1, 8), (8, 1)])
    def test_single_row_or_column_or_pixel_frames(self, shape):
        frame = np.full(shape, 100, dtype=np.uint8)
        result = prepare_metrology_roi(frame)
        assert result.quality == 0.0   # no 2-D gradient is definable
        assert np.all(np.isfinite(result.image))

    @pytest.mark.parametrize("shape", [(0, 5), (5, 0), (0, 0)])
    def test_empty_frames(self, shape):
        frame = np.zeros(shape, dtype=np.uint8)
        result = prepare_metrology_roi(frame)
        assert result.quality == 0.0
        assert result.image.shape == shape
        assert result.mask.shape == shape

    def test_three_dimensional_colour_frame_is_averaged_to_gray(self):
        frame = np.zeros((20, 20, 3), dtype=np.uint8)
        frame[..., 0] = 100  # only the red channel set
        result = prepare_metrology_roi(frame)
        assert result.image.ndim == 2
        assert result.image.shape == (20, 20)

    def test_wrong_ndim_is_a_caller_error_and_raises(self):
        """Unlike frame CONTENT degeneracy, a fundamentally malformed shape
        (1-D) is a caller bug, not sensor noise — this one DOES raise."""
        with pytest.raises(ValueError):
            prepare_metrology_roi(np.zeros(10))

    def test_single_poisoned_calibration_pixel_does_not_nan_poison_whole_frame(self):
        """Regression guard: the Gaussian background blur is a GLOBAL FFT
        transform, so a naive implementation would let ONE non-finite
        working-array pixel (e.g. a NaN flat-field calibration pixel) turn
        the ENTIRE high-passed image to NaN. prepare_metrology_roi fills
        invalid pixels with the valid-pixel mean before blurring specifically
        to prevent this — assert the damage stays local (quality barely
        moves) rather than global (quality collapsing to ~0)."""
        frame = _textured_frame((32, 32), seed=3)
        flat_clean = np.ones((32, 32), dtype=np.float64)
        flat_poisoned = flat_clean.copy()
        flat_poisoned[10, 10] = np.nan

        clean = prepare_metrology_roi(frame, flat=flat_clean)
        poisoned = prepare_metrology_roi(frame, flat=flat_poisoned)

        assert np.all(np.isfinite(poisoned.image))
        assert poisoned.mask[10, 10] == False  # noqa: E712 (readability)
        # Exactly one ADDITIONAL pixel (the poisoned one) drops out relative
        # to the clean reference -- some frames also have their own
        # naturally-saturated pixels from random clipping, so compare
        # against `clean`, not a bare `frame.size - 1`.
        assert poisoned.mask.sum() == clean.mask.sum() - 1
        # The single bad pixel must not measurably move the whole-frame
        # quality score -- a poisoned FFT would instead collapse it near 0.
        assert poisoned.quality == pytest.approx(clean.quality, rel=0.05)


# --------------------------------------------------------------------------- #
# End-to-end composition: roi + dark + flat + saturation together             #
# --------------------------------------------------------------------------- #

class TestPrepareMetrologyRoiIntegration:
    def test_roi_dark_flat_saturation_compose_without_raising(self):
        rng = np.random.default_rng(7)
        full_frame = rng.integers(0, 255, size=(20, 20)).astype(np.uint8)
        full_frame[0, 0] = 255  # a saturated pixel outside the ROI
        roi = (2, 2, 10, 10)
        dark = np.full((10, 10), 2.0)
        flat = np.ones((10, 10))

        result = prepare_metrology_roi(full_frame, roi=roi, dark=dark, flat=flat)

        assert result.image.shape == (10, 10)
        assert result.mask.shape == (10, 10)
        assert 0.0 <= result.quality <= 1.0
        assert 0.0 <= result.saturated_frac <= 1.0

    def test_mask_true_pixels_are_finite_and_unsaturated_in_source(self):
        frame = _textured_frame((16, 16), seed=2)
        frame[3, 3] = 255  # force one saturated pixel (level ~250 for uint8)
        result = prepare_metrology_roi(frame)
        assert result.mask[3, 3] == False  # noqa: E712 (readability)
        assert result.saturated_frac > 0.0

    def test_default_highpass_sigma_is_15px(self):
        import inspect
        sig = inspect.signature(prepare_metrology_roi)
        assert sig.parameters["highpass_sigma_px"].default == 15.0
