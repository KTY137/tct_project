"""Unit tests for analysis/camera_calibration.py -- pure numpy, no hardware."""
from __future__ import annotations

import numpy as np
import pytest

from analysis.camera_calibration import (
    checkerboard_points_mm,
    fit_affine,
    fit_object_plane_calibration,
    residual_summary,
)


def test_checkerboard_points_are_row_major_mm_coordinates():
    pts = checkerboard_points_mm(rows=2, cols=3, pitch_mm=0.5, origin_mm=(10.0, -2.0))

    assert pts.shape == (6, 2)
    assert pts.tolist() == [
        [10.0, -2.0], [10.5, -2.0], [11.0, -2.0],
        [10.0, -1.5], [10.5, -1.5], [11.0, -1.5],
    ]


def test_affine_fit_recovers_scale_rotation_shear_and_offset():
    obj = checkerboard_points_mm(rows=6, cols=8, pitch_mm=0.25)
    matrix = np.array([[215.0, -11.0], [8.5, 207.0]])
    offset = np.array([640.0, 310.0])
    image = obj @ matrix.T + offset

    fit = fit_affine(obj, image)

    assert fit.rank == 3
    assert fit.matrix_px_per_mm == pytest.approx(matrix, abs=1e-9)
    assert fit.offset_px == pytest.approx(offset, abs=1e-9)
    assert fit.rms_px < 1e-10
    assert fit.max_abs_um < 1e-8
    assert fit.predict(obj) == pytest.approx(image, abs=1e-9)
    assert fit.image_to_object(image) == pytest.approx(obj, abs=1e-9)


def test_affine_fit_rejects_collinear_checker_points():
    obj = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]])
    image = np.array([[10.0, 20.0], [30.0, 21.0], [50.0, 22.0]])

    with pytest.raises(ValueError, match="non-collinear"):
        fit_affine(obj, image)


def test_degree3_distortion_fit_turns_curved_residuals_into_validation_metric():
    obj = checkerboard_points_mm(rows=9, cols=11, pitch_mm=0.2, origin_mm=(-1.0, -0.8))
    matrix = np.array([[340.0, 14.0], [-9.0, 332.0]])
    offset = np.array([920.0, 610.0])
    ideal = obj @ matrix.T + offset

    # Smooth object-plane field distortion: a small radial cubic plus a weak
    # saddle term. This is the shape we care about seeing in checker residuals
    # after affine removal.
    center = ideal.mean(axis=0)
    scale = np.ptp(ideal, axis=0).max()
    d = (ideal - center) / scale
    x, y = d[:, 0], d[:, 1]
    residual = np.column_stack([
        7.5 * x * (x * x + y * y) + 1.2 * x * y,
        6.0 * y * (x * x + y * y) - 0.8 * (x * x - y * y),
    ])
    measured = ideal + residual

    affine_only = fit_object_plane_calibration(obj, measured)
    corrected = fit_object_plane_calibration(obj, measured, distortion_degree=3)

    assert affine_only.max_abs_px > 0.6
    assert corrected.distortion is not None
    assert corrected.rms_px < affine_only.rms_px * 0.08
    assert corrected.max_abs_px < affine_only.max_abs_px * 0.12


def test_distorted_calibration_predicts_and_inverts_image_points():
    obj = checkerboard_points_mm(rows=7, cols=7, pitch_mm=0.3, origin_mm=(-0.9, -0.9))
    matrix = np.array([[260.0, -18.0], [20.0, 255.0]])
    offset = np.array([500.0, 420.0])
    ideal = obj @ matrix.T + offset
    center = ideal.mean(axis=0)
    scale = np.ptp(ideal, axis=0).max()
    d = (ideal - center) / scale
    x, y = d[:, 0], d[:, 1]
    measured = ideal + np.column_stack([
        4.0 * x * (x * x + y * y),
        -3.0 * y * (x * x + y * y),
    ])

    cal = fit_object_plane_calibration(obj, measured, distortion_degree=3)

    assert cal.predict(obj) == pytest.approx(measured, abs=0.03)
    assert cal.image_to_object(measured) == pytest.approx(obj, abs=2e-4)


def test_residual_summary_reports_um_and_pass_fail_against_tolerance():
    residuals = np.array([[0.3, 0.4], [0.0, 0.0]])  # max radial = 0.5 px

    summary = residual_summary(residuals, px_per_mm=500.0, tolerance_um=2.0)

    assert summary["max_abs_px"] == pytest.approx(0.5)
    assert summary["max_abs_um"] == pytest.approx(1.0)
    assert summary["rms_px"] == pytest.approx(np.sqrt((0.25 + 0.0) / 2.0))
    assert summary["passes"] is True
    assert residual_summary(residuals, px_per_mm=500.0, tolerance_um=0.5)["passes"] is False
