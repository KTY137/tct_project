"""Unit tests for vision/sensor_align.py.

Real ArUco detection/pose tests need ``cv2`` installed and use
``pytest.importorskip`` (same pattern as ``test_waveform_generator.py`` does
for ``pyvisa``) so the suite degrades gracefully in an environment without
OpenCV, matching the module's own optional-dependency contract. The
degradation-path tests deliberately force the ``cv2`` import to fail via
monkeypatch regardless of whether it is actually installed here.
"""
from __future__ import annotations

import importlib
import math
import sys

import numpy as np
import pytest

from vision import sensor_align as sa

cv2 = pytest.importorskip("cv2")  # noqa: E402  -- real detection/pose tests need cv2


def _make_marker_canvas(
    marker_id: int,
    *,
    marker_px: int = 200,
    canvas_size: int = 500,
) -> np.ndarray:
    """White canvas (uint8) with one generated DICT_4X4_50 marker centered."""
    marker_img = sa.generate_marker_image(marker_id, marker_px)
    canvas = np.full((canvas_size, canvas_size), 255, dtype=np.uint8)
    off = (canvas_size - marker_px) // 2
    canvas[off : off + marker_px, off : off + marker_px] = marker_img
    return canvas


class TestAvailability:
    def test_is_available_true_with_cv2_installed(self):
        assert sa.is_available() is True


class TestDetection:
    def test_detect_generated_marker(self):
        canvas = _make_marker_canvas(marker_id=7, marker_px=200, canvas_size=500)
        result = sa.detect_markers(canvas)
        assert result.n_detected == 1
        assert result.image_shape == (500, 500)

        marker = result.markers[0]
        assert marker.marker_id == 7
        assert marker.corners_px.shape == (4, 2)
        assert marker.center_px == pytest.approx([250.0, 250.0], abs=2.0)

    def test_detect_markers_no_marker_returns_empty(self):
        blank = np.full((200, 200), 255, dtype=np.uint8)
        result = sa.detect_markers(blank)
        assert result.n_detected == 0
        assert result.markers == ()
        assert result.image_shape == (200, 200)

    def test_detect_markers_accepts_color_image(self):
        gray = _make_marker_canvas(marker_id=3, marker_px=200, canvas_size=400)
        color = np.stack([gray, gray, gray], axis=-1)  # (H, W, 3)
        result = sa.detect_markers(color)
        assert result.n_detected == 1
        assert result.markers[0].marker_id == 3

    def test_by_id_lookup(self):
        canvas = _make_marker_canvas(marker_id=11, marker_px=200, canvas_size=400)
        result = sa.detect_markers(canvas)
        assert result.by_id(11) is not None
        assert result.by_id(99) is None


def _forward_affine(center_xy, angle_deg, dx, dy):
    """Build a 2x3 matrix ``dst = M @ [src, 1]`` rotating by ``angle_deg`` (the
    same atan2(M[1,0], M[0,0]) sign convention ``PoseEstimate.theta_deg`` and
    the research note use) about ``center_xy``, then translating by (dx, dy).

    Deliberately NOT ``cv2.getRotationMatrix2D``: that helper's ``angle``
    parameter is "positive = counter-clockwise as displayed", which embeds
    R(-angle) in raw (y-down) pixel-matrix terms -- the opposite sign of the
    plain ``atan2(M[1,0], M[0,0])`` convention used here and in the note.
    Building M directly keeps this test's ``angle_deg`` numerically equal to
    the recovered ``theta_deg``, which is what's actually under test.
    """
    theta = math.radians(angle_deg)
    c, s = math.cos(theta), math.sin(theta)
    cx, cy = center_xy
    return np.array(
        [
            [c, -s, cx * (1 - c) + cy * s + dx],
            [s, c, cy * (1 - c) - cx * s + dy],
        ],
        dtype=np.float64,
    )


class TestPoseRecovery:
    """Synthetic marker at a known rotation+translation -> pose recovery."""

    @pytest.mark.parametrize("angle_deg,dx,dy", [(0.0, 0.0, 0.0), (15.0, 20.0, -10.0), (-30.0, -15.0, 25.0)])
    def test_estimate_relative_pose_recovers_known_transform(self, angle_deg, dx, dy):
        ref_canvas = _make_marker_canvas(marker_id=4, marker_px=200, canvas_size=500)
        center = (ref_canvas.shape[1] / 2.0, ref_canvas.shape[0] / 2.0)
        rot = _forward_affine(center, angle_deg, dx, dy)
        cur_canvas = cv2.warpAffine(
            ref_canvas, rot, (ref_canvas.shape[1], ref_canvas.shape[0]),
            borderValue=255,
        )

        reference = sa.detect_markers(ref_canvas)
        current = sa.detect_markers(cur_canvas)
        assert reference.n_detected == 1
        assert current.n_detected == 1

        pose = sa.estimate_relative_pose(reference, current)

        assert pose.theta_deg == pytest.approx(angle_deg, abs=0.3)
        assert pose.translation_px[0] == pytest.approx(rot[0, 2], abs=1.5)
        assert pose.translation_px[1] == pytest.approx(rot[1, 2], abs=1.5)
        assert pose.scale == pytest.approx(1.0, abs=0.02)
        assert pose.n_points == 4
        assert pose.baseline_px > 0.0

    def test_estimate_relative_pose_no_common_ids_raises(self):
        ref_canvas = _make_marker_canvas(marker_id=1, marker_px=200, canvas_size=400)
        cur_canvas = _make_marker_canvas(marker_id=2, marker_px=200, canvas_size=400)
        reference = sa.detect_markers(ref_canvas)
        current = sa.detect_markers(cur_canvas)
        with pytest.raises(sa.PoseEstimationError):
            sa.estimate_relative_pose(reference, current)

    def test_estimate_pose_requires_matching_lengths(self):
        with pytest.raises(sa.PoseEstimationError):
            sa.estimate_pose([[0.0, 0.0], [1.0, 1.0]], [[0.0, 0.0]])

    def test_estimate_pose_requires_at_least_two_points(self):
        with pytest.raises(sa.PoseEstimationError):
            sa.estimate_pose([[0.0, 0.0]], [[0.0, 0.0]])


class TestPrecisionQualityMetric:
    """The <0.05 deg / ~115 px corner-baseline caveat from
    docs/research/sensor_alignment_cv.md sec. 4, exercised directly on
    synthetic point correspondences (no detection noise) so the threshold
    behaviour itself is what's under test."""

    @staticmethod
    def _similarity_points(span_px: float, angle_deg: float = 2.0):
        theta = math.radians(angle_deg)
        rot = np.array(
            [[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]]
        )
        src = np.array([[0.0, 0.0], [span_px, 0.0], [0.0, span_px], [span_px, span_px]])
        dst = (src @ rot.T) + np.array([5.0, -3.0])
        return src, dst

    def test_meets_precision_target_above_recommended_baseline(self):
        src, dst = self._similarity_points(span_px=130.0)
        pose = sa.estimate_pose(src, dst)
        assert pose.baseline_px > sa.RECOMMENDED_MIN_BASELINE_PX
        assert pose.estimated_precision_deg < sa.TARGET_ANGLE_PRECISION_DEG
        assert pose.meets_precision_target is True

    def test_fails_precision_target_below_recommended_baseline(self):
        src, dst = self._similarity_points(span_px=20.0)
        pose = sa.estimate_pose(src, dst)
        assert pose.baseline_px < sa.RECOMMENDED_MIN_BASELINE_PX
        assert pose.estimated_precision_deg > sa.TARGET_ANGLE_PRECISION_DEG
        assert pose.meets_precision_target is False

    def test_precision_at_scales_linearly_with_assumed_sigma(self):
        src, dst = self._similarity_points(span_px=200.0)
        pose = sa.estimate_pose(src, dst)
        assert pose.precision_at(0.2) == pytest.approx(2.0 * pose.precision_at(0.1), rel=1e-6)

    def test_zero_baseline_is_infinite_precision(self):
        pose = sa.estimate_pose([[0.0, 0.0], [0.0, 0.0]], [[1.0, 1.0], [1.0, 1.0]])
        assert pose.baseline_px == 0.0
        assert pose.estimated_precision_deg == float("inf")
        assert pose.meets_precision_target is False


class TestDegradation:
    """cv2 forcibly unavailable -> clean, typed degradation everywhere."""

    def test_module_import_does_not_require_cv2(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "cv2", None)
        for name in list(sys.modules):
            if name == "vision" or name.startswith("vision."):
                monkeypatch.delitem(sys.modules, name, raising=False)

        reloaded = importlib.import_module("vision.sensor_align")
        assert reloaded.is_available() is False

    def test_is_available_false_when_cv2_missing(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "cv2", None)
        assert sa.is_available() is False

    def test_detect_markers_raises_typed_error(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "cv2", None)
        with pytest.raises(sa.VisionUnavailableError):
            sa.detect_markers(np.zeros((10, 10), dtype=np.uint8))

    def test_estimate_pose_raises_typed_error(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "cv2", None)
        with pytest.raises(sa.VisionUnavailableError):
            sa.estimate_pose([[0.0, 0.0], [1.0, 1.0]], [[0.0, 0.0], [1.0, 1.0]])

    def test_generate_marker_image_raises_typed_error(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "cv2", None)
        with pytest.raises(sa.VisionUnavailableError):
            sa.generate_marker_image(0, 100)

    def test_typed_error_is_not_bare_import_error(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "cv2", None)
        try:
            sa.detect_markers(np.zeros((10, 10), dtype=np.uint8))
        except sa.VisionUnavailableError as exc:
            assert type(exc) is not ImportError
            assert isinstance(exc, sa.VisionError)
            assert isinstance(exc, RuntimeError)
        else:
            pytest.fail("expected VisionUnavailableError")


class TestDataclassContract:
    def test_pose_estimate_carries_quality_fields_not_hidden(self):
        src, dst = TestPrecisionQualityMetric._similarity_points(span_px=200.0)
        pose = sa.estimate_pose(src, dst)
        for field in (
            "theta_deg", "scale", "translation_px", "baseline_px",
            "n_points", "n_inliers", "estimated_precision_deg",
            "meets_precision_target",
        ):
            assert hasattr(pose, field), f"PoseEstimate missing field {field!r}"
