"""Object-plane camera calibration for TCT metrology.

This module is deliberately pure numpy: it does not detect checkerboard corners
from an image.  It calibrates the geometry once corner/fiducial coordinates have
been measured, whether those points came from a manual clicker, a future
OpenCV-based detector, or phase-correlation of printed target patches.

The model matches the bench need documented in
``docs/design/camera_survey_metrology.md``: first fit the stage/object-plane
``(x_mm, y_mm) -> (u_px, v_px)`` affine transform (scale, rotation, shear), then
optionally fit a small residual field that represents optical distortion left
after the affine.  The residuals are the validation signal for the optics.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Iterable

import numpy as np


def checkerboard_points_mm(
    rows: int,
    cols: int,
    pitch_mm: float,
    *,
    origin_mm: tuple[float, float] = (0.0, 0.0),
) -> np.ndarray:
    """Return row-major ``(x_mm, y_mm)`` checker/fiducial coordinates.

    ``rows`` and ``cols`` count detectable points, not squares.  A 9x6 inner
    corner checkerboard therefore passes ``rows=6, cols=9``.
    """
    if rows <= 0 or cols <= 0:
        raise ValueError(f"rows/cols must be positive; got rows={rows}, cols={cols}")
    if pitch_mm <= 0.0:
        raise ValueError(f"pitch_mm must be positive; got {pitch_mm}")
    ox, oy = float(origin_mm[0]), float(origin_mm[1])
    xs = ox + np.arange(cols, dtype=np.float64) * float(pitch_mm)
    ys = oy + np.arange(rows, dtype=np.float64) * float(pitch_mm)
    grid_x, grid_y = np.meshgrid(xs, ys)
    return np.column_stack([grid_x.ravel(), grid_y.ravel()])


@dataclass(frozen=True)
class AffineFit:
    """Least-squares object-plane affine calibration.

    ``matrix_px_per_mm`` maps object/stage deltas in mm to image deltas in px::

        [u_px, v_px] = [x_mm, y_mm] @ matrix_px_per_mm.T + offset_px

    Columns of ``matrix_px_per_mm`` are the image-space vectors produced by a
    +1 mm object motion along X and Y respectively.
    """

    matrix_px_per_mm: np.ndarray
    offset_px: np.ndarray
    residuals_px: np.ndarray
    rms_px: float
    max_abs_px: float
    rank: int

    def predict(self, object_xy_mm: np.ndarray) -> np.ndarray:
        pts = _as_points2(object_xy_mm, "object_xy_mm")
        return pts @ self.matrix_px_per_mm.T + self.offset_px

    def image_to_object(self, image_uv_px: np.ndarray) -> np.ndarray:
        pts = _as_points2(image_uv_px, "image_uv_px")
        inv = np.linalg.inv(self.matrix_px_per_mm)
        return (pts - self.offset_px) @ inv.T

    @property
    def px_per_mm_x(self) -> float:
        return float(np.linalg.norm(self.matrix_px_per_mm[:, 0]))

    @property
    def px_per_mm_y(self) -> float:
        return float(np.linalg.norm(self.matrix_px_per_mm[:, 1]))

    @property
    def mean_px_per_mm(self) -> float:
        return 0.5 * (self.px_per_mm_x + self.px_per_mm_y)

    @property
    def mean_um_per_px(self) -> float:
        scale = self.mean_px_per_mm
        return float("inf") if scale <= 0.0 else 1000.0 / scale

    @property
    def rms_um(self) -> float:
        return self.rms_px * self.mean_um_per_px

    @property
    def max_abs_um(self) -> float:
        return self.max_abs_px * self.mean_um_per_px


@dataclass(frozen=True)
class PolynomialDistortion:
    """Residual image-space distortion model.

    The polynomial is evaluated on normalized affine-predicted image
    coordinates.  Constant and linear terms are kept because a global affine
    fit can redistribute part of a curved field into the remaining residual map.
    Degree 3 captures the usual smooth radial/decentering-like residual field
    without adding OpenCV as a dependency.
    """

    degree: int
    center_px: np.ndarray
    scale_px: float
    powers: tuple[tuple[int, int], ...]
    coeffs_px: np.ndarray

    def evaluate(self, affine_uv_px: np.ndarray) -> np.ndarray:
        pts = _as_points2(affine_uv_px, "affine_uv_px")
        basis = _poly_basis(pts, self.center_px, self.scale_px, self.powers)
        return basis @ self.coeffs_px


@dataclass(frozen=True)
class ObjectPlaneCalibration:
    """Affine plus optional residual distortion calibration."""

    affine: AffineFit
    distortion: PolynomialDistortion | None
    residuals_px: np.ndarray
    rms_px: float
    max_abs_px: float

    def predict(self, object_xy_mm: np.ndarray) -> np.ndarray:
        affine_uv = self.affine.predict(object_xy_mm)
        if self.distortion is None:
            return affine_uv
        return affine_uv + self.distortion.evaluate(affine_uv)

    def image_to_object(self, image_uv_px: np.ndarray, *, iterations: int = 8) -> np.ndarray:
        """Invert image pixels back to object mm by fixed-point correction.

        For affine-only calibration this is exact.  With a distortion model,
        the affine inverse gives the initial guess, then each iteration converts
        the remaining pixel error through the affine inverse.  The intended
        residual fields are small and smooth, so a handful of iterations is
        enough for metrology-scale use.
        """
        image = _as_points2(image_uv_px, "image_uv_px")
        guess = self.affine.image_to_object(image)
        if self.distortion is None:
            return guess
        inv = np.linalg.inv(self.affine.matrix_px_per_mm)
        for _ in range(max(int(iterations), 0)):
            err_px = image - self.predict(guess)
            guess = guess + err_px @ inv.T
        return guess

    @property
    def mean_px_per_mm(self) -> float:
        return self.affine.mean_px_per_mm

    @property
    def mean_um_per_px(self) -> float:
        return self.affine.mean_um_per_px

    @property
    def rms_um(self) -> float:
        return self.rms_px * self.mean_um_per_px

    @property
    def max_abs_um(self) -> float:
        return self.max_abs_px * self.mean_um_per_px


def fit_affine(object_xy_mm: np.ndarray, image_uv_px: np.ndarray) -> AffineFit:
    """Fit ``object mm -> image px`` affine and return residual diagnostics."""
    obj = _as_points2(object_xy_mm, "object_xy_mm")
    img = _as_points2(image_uv_px, "image_uv_px")
    _require_same_len(obj, img)
    if len(obj) < 3:
        raise ValueError("at least three non-collinear points are required")

    design = np.column_stack([obj, np.ones(len(obj), dtype=np.float64)])
    rank = int(np.linalg.matrix_rank(design))
    if rank < 3:
        raise ValueError("object points are degenerate; need non-collinear points")

    params, _, _, _ = np.linalg.lstsq(design, img, rcond=None)
    pred = design @ params
    residuals = img - pred
    matrix = params[:2, :].T
    offset = params[2, :]
    rms, max_abs = _residual_metrics(residuals)
    return AffineFit(
        matrix_px_per_mm=matrix,
        offset_px=offset,
        residuals_px=residuals,
        rms_px=rms,
        max_abs_px=max_abs,
        rank=rank,
    )


def fit_object_plane_calibration(
    object_xy_mm: np.ndarray,
    image_uv_px: np.ndarray,
    *,
    distortion_degree: int | None = None,
) -> ObjectPlaneCalibration:
    """Fit affine calibration, optionally followed by residual distortion.

    ``distortion_degree=None`` or ``<=1`` returns the affine-only calibration.
    ``degree=3`` is the usual choice for smooth relay/lens distortion.
    """
    obj = _as_points2(object_xy_mm, "object_xy_mm")
    img = _as_points2(image_uv_px, "image_uv_px")
    affine = fit_affine(obj, img)
    affine_pred = affine.predict(obj)

    distortion: PolynomialDistortion | None = None
    pred = affine_pred
    if distortion_degree is not None and int(distortion_degree) > 1:
        distortion = fit_polynomial_distortion(
            affine_pred,
            img - affine_pred,
            degree=int(distortion_degree),
        )
        pred = affine_pred + distortion.evaluate(affine_pred)

    residuals = img - pred
    rms, max_abs = _residual_metrics(residuals)
    return ObjectPlaneCalibration(
        affine=affine,
        distortion=distortion,
        residuals_px=residuals,
        rms_px=rms,
        max_abs_px=max_abs,
    )


def fit_polynomial_distortion(
    affine_uv_px: np.ndarray,
    residual_uv_px: np.ndarray,
    *,
    degree: int = 3,
) -> PolynomialDistortion:
    """Fit smooth residual distortion as a polynomial vector field.

    Inputs are the affine-predicted image coordinates and the measured residuals
    at those coordinates.  The affine-only residual metrics should still be
    reported alongside corrected metrics so optical warping stays visible during
    validation instead of being silently hidden.
    """
    pts = _as_points2(affine_uv_px, "affine_uv_px")
    residuals = _as_points2(residual_uv_px, "residual_uv_px")
    _require_same_len(pts, residuals)
    degree = int(degree)
    if degree <= 1:
        raise ValueError(f"degree must be >= 2 for distortion; got {degree}")

    powers = _distortion_powers(degree)
    if len(pts) < len(powers):
        raise ValueError(
            f"not enough points for degree {degree} distortion "
            f"({len(pts)} points, {len(powers)} terms)"
        )

    center = pts.mean(axis=0)
    span = np.ptp(pts, axis=0)
    scale = float(max(span.max(), 1.0))
    basis = _poly_basis(pts, center, scale, powers)
    coeffs, _, _, _ = np.linalg.lstsq(basis, residuals, rcond=None)
    return PolynomialDistortion(
        degree=degree,
        center_px=center,
        scale_px=scale,
        powers=tuple(powers),
        coeffs_px=coeffs,
    )


def residual_summary(
    residuals_px: np.ndarray,
    px_per_mm: float,
    *,
    tolerance_um: float | None = None,
) -> dict[str, float | bool]:
    """Return px/um residual metrics, optionally with a pass/fail flag."""
    residuals = _as_points2(residuals_px, "residuals_px")
    if px_per_mm <= 0.0:
        raise ValueError(f"px_per_mm must be positive; got {px_per_mm}")
    rms_px, max_abs_px = _residual_metrics(residuals)
    um_per_px = 1000.0 / float(px_per_mm)
    out: dict[str, float | bool] = {
        "rms_px": rms_px,
        "max_abs_px": max_abs_px,
        "rms_um": rms_px * um_per_px,
        "max_abs_um": max_abs_px * um_per_px,
    }
    if tolerance_um is not None:
        out["passes"] = bool(out["max_abs_um"] <= float(tolerance_um))
    return out


def _as_points2(values: np.ndarray, name: str) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError(f"{name} must have shape (N, 2); got {arr.shape}")
    if len(arr) == 0:
        raise ValueError(f"{name} must contain at least one point")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} contains NaN or infinite values")
    return arr


def _require_same_len(a: np.ndarray, b: np.ndarray) -> None:
    if len(a) != len(b):
        raise ValueError(f"point arrays must have the same length; got {len(a)} and {len(b)}")


def _residual_metrics(residuals: np.ndarray) -> tuple[float, float]:
    radial = np.hypot(residuals[:, 0], residuals[:, 1])
    rms = float(sqrt(float(np.mean(radial * radial)))) if len(radial) else 0.0
    max_abs = float(np.max(radial)) if len(radial) else 0.0
    return rms, max_abs


def _distortion_powers(degree: int) -> list[tuple[int, int]]:
    powers: list[tuple[int, int]] = []
    for total in range(0, degree + 1):
        for px in range(total, -1, -1):
            py = total - px
            powers.append((px, py))
    return powers


def _poly_basis(
    pts_px: np.ndarray,
    center_px: np.ndarray,
    scale_px: float,
    powers: Iterable[tuple[int, int]],
) -> np.ndarray:
    norm = (pts_px - center_px) / float(scale_px)
    x = norm[:, 0]
    y = norm[:, 1]
    cols = [(x ** px) * (y ** py) for px, py in powers]
    return np.column_stack(cols)
