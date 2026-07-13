"""ArUco fiducial detection + 2D sensor-pose estimation.

Implements tier 1 of the detection/pose ladder in
``docs/research/sensor_alignment_cv.md`` ("(1) ArUco fiducial (preferred)"):
detect ``DICT_4X4_50`` markers with sub-pixel corner refinement, then solve a
2D rigid/similarity transform (``cv2.estimateAffinePartial2D``) between a
reference and a current detection. Tiers 2/3 of the ladder (bare-rectangle
``minAreaRect`` contour fit; rotation-search / Fourier-Mellin for the
fiducial-free case) are out of scope for this beat and are not implemented
here.

**Lazy import contract.** This module never imports ``cv2`` at module scope,
so importing it (or the ``vision`` package) always succeeds even when
``opencv-python-headless`` is not installed — the app must keep running fully
without OpenCV. Call :func:`is_available` to probe capability before doing
real work; every function that needs ``cv2`` raises
:class:`VisionUnavailableError` (a typed, catchable error — never a bare
``ImportError`` surfacing from deep inside app code) when it is missing.

**Precision caveat surfaced, not hidden.** Per the research note sec. 4,
corner-localization noise sigma ~= 0.05-0.1 px over a corner baseline of B px
gives angular precision sigma_theta ~= sigma_corner / B (radians). Hitting
the <0.05 deg alignment target needs B >~ 115 px between the two farthest
corners used in the fit. Every :class:`PoseEstimate` carries ``baseline_px``,
``estimated_precision_deg`` and ``meets_precision_target`` so a caller (or
the E7c alignment UI) can see -- and must actively check -- whether a given
detection geometrically supports the target, rather than silently trusting a
numeric ``theta_deg`` that a short baseline cannot actually back up.

Pure numpy-image-in / dataclass-result-out: no GUI, no device or motion
imports. Callers (a future alignment panel) get numbers only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

# ArUco dictionary used for all sensor-alignment fiducials (see research note
# sec. 2: "choose the smallest dictionary that fits your application" -- 4x4
# markers need the fewest bits/pixels to detect reliably).
ARUCO_DICT_NAME = "DICT_4X4_50"

# From docs/research/sensor_alignment_cv.md sec. 4: corner-localization noise
# sigma_corner ~= 0.05-0.1 px over a baseline of B px between the two
# farthest corners used gives angular precision sigma_theta ~= sigma_corner/B
# (rad). These are the defaults used to compute PoseEstimate.estimated_
# precision_deg / meets_precision_target; override via precision_at() /
# estimate_pose(corner_sigma_px=...) for a different assumed noise floor.
DEFAULT_CORNER_SIGMA_PX = 0.1
TARGET_ANGLE_PRECISION_DEG = 0.05
# B >= ~115 px is the baseline needed to reach TARGET_ANGLE_PRECISION_DEG at
# DEFAULT_CORNER_SIGMA_PX (110.6 px exactly; the note's "~115 px" is the
# stated rule of thumb -- kept as the literal threshold here so
# meets_precision_target matches the cited number, not a rounder one).
RECOMMENDED_MIN_BASELINE_PX = 115.0


class VisionError(RuntimeError):
    """Base class for vision/ package errors."""


class VisionUnavailableError(VisionError):
    """``cv2`` (opencv-python-headless) is not importable.

    Raised by every function in this module that needs OpenCV, instead of
    letting a bare ``ImportError`` propagate from deep inside a call stack.
    Callers (including a future GUI panel) can catch this specific type to
    degrade gracefully -- e.g. disable an "align" button and show an
    install hint -- without needing to know cv2 exists at all.
    """


class PoseEstimationError(VisionError):
    """A pose could not be estimated from the given marker correspondences."""


# --------------------------------------------------------------------------- #
# Capability probe + lazy cv2 import                                          #
# --------------------------------------------------------------------------- #


def is_available() -> bool:
    """Return whether ``cv2`` (with the ArUco ``objdetect`` API) is importable.

    Safe to call unconditionally at any time, including with OpenCV not
    installed -- this is the intended way for callers (GUI panels included)
    to check capability before attempting real detection/pose work.
    """
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False
    return hasattr(cv2, "aruco") and hasattr(cv2.aruco, "ArucoDetector")


def _require_cv2() -> Any:
    """Import and return the ``cv2`` module, or raise :class:`VisionUnavailableError`."""
    try:
        import cv2
    except ImportError as exc:
        raise VisionUnavailableError(
            "OpenCV (opencv-python-headless) is not installed; sensor-pose "
            "vision features are unavailable. Install with: "
            "pip install opencv-python-headless==4.9.0.80 "
            "(see requirements.txt / docs/research/sensor_alignment_cv.md)."
        ) from exc
    if not (hasattr(cv2, "aruco") and hasattr(cv2.aruco, "ArucoDetector")):
        raise VisionUnavailableError(
            "cv2 is installed but lacks the modern cv2.aruco.ArucoDetector "
            "API (needs OpenCV >= 4.7, where aruco moved into base "
            "objdetect); got cv2 " + str(getattr(cv2, "__version__", "?")) + "."
        )
    return cv2


# --------------------------------------------------------------------------- #
# Results                                                                      #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MarkerDetection:
    """One detected ArUco marker.

    ``corners_px`` is shape ``(4, 2)`` in ``cv2.aruco``'s corner order
    (top-left, top-right, bottom-right, bottom-left, clockwise), image pixel
    coordinates (u, v), sub-pixel refined when detection used
    ``CORNER_REFINE_SUBPIX`` (the default -- see :func:`detect_markers`).
    """

    marker_id: int
    corners_px: np.ndarray
    center_px: np.ndarray


@dataclass(frozen=True)
class DetectionResult:
    """All ArUco markers found in one image.

    ``n_rejected`` is the count of candidate quads OpenCV tried and rejected
    (failed the ID/border check) -- surfaced for diagnostics, e.g. distinguishing
    "no markers in frame" from "markers present but not decoding" (glare,
    focus, wrong dictionary).
    """

    markers: tuple[MarkerDetection, ...]
    image_shape: tuple[int, int]  # (height_px, width_px)
    n_rejected: int
    dictionary: str = ARUCO_DICT_NAME

    @property
    def n_detected(self) -> int:
        return len(self.markers)

    def by_id(self, marker_id: int) -> MarkerDetection | None:
        for m in self.markers:
            if m.marker_id == marker_id:
                return m
        return None


@dataclass(frozen=True)
class PoseEstimate:
    """2D rigid/similarity pose recovered from marker-corner correspondences.

    ``M = s * [[cos(theta), -sin(theta)], [sin(theta), cos(theta)]]``,
    ``dst ~= src @ M.T + translation_px`` (``cv2.estimateAffinePartial2D``
    convention -- see research note sec. 4).

    The precision fields are the load-bearing part of this dataclass: a
    ``theta_deg`` computed from a short ``baseline_px`` can look numerically
    precise while being physically unsupported by the corner geometry that
    produced it. Always check ``meets_precision_target`` (or
    ``estimated_precision_deg`` against your own tolerance) before trusting
    ``theta_deg`` to the <0.05 deg alignment target.
    """

    theta_deg: float
    scale: float
    translation_px: np.ndarray  # shape (2,): (tx_px, ty_px)
    baseline_px: float
    n_points: int
    n_inliers: int
    estimated_precision_deg: float
    meets_precision_target: bool

    def precision_at(self, corner_sigma_px: float) -> float:
        """Recompute the angular precision floor for a different assumed
        per-corner localization sigma (default used for
        ``estimated_precision_deg`` is :data:`DEFAULT_CORNER_SIGMA_PX`)."""
        return _angle_precision_deg(self.baseline_px, corner_sigma_px)


# --------------------------------------------------------------------------- #
# Detection                                                                    #
# --------------------------------------------------------------------------- #


def detect_markers(
    image: np.ndarray,
    *,
    refine_subpix: bool = True,
) -> DetectionResult:
    """Detect ``DICT_4X4_50`` ArUco markers in ``image``.

    ``image`` is a numpy array, grayscale ``(H, W)`` or color ``(H, W, 3|4)``
    (converted to grayscale internally); dtype is normalized to ``uint8``
    (see :func:`_as_gray_uint8`). Corner refinement defaults to
    ``CORNER_REFINE_SUBPIX`` (research note sec. 2: "the accuracy lever for
    pose") -- it is off by default in OpenCV and deliberately enabled here.

    Raises :class:`VisionUnavailableError` if ``cv2`` is not installed.
    """
    cv2 = _require_cv2()
    gray = _as_gray_uint8(image)

    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    params = cv2.aruco.DetectorParameters()
    if refine_subpix:
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    detector = cv2.aruco.ArucoDetector(aruco_dict, params)

    corners, ids, rejected = detector.detectMarkers(gray)

    markers: list[MarkerDetection] = []
    if ids is not None:
        for corner_set, marker_id in zip(corners, ids.reshape(-1)):
            pts = np.asarray(corner_set, dtype=np.float64).reshape(4, 2)
            markers.append(
                MarkerDetection(
                    marker_id=int(marker_id),
                    corners_px=pts,
                    center_px=pts.mean(axis=0),
                )
            )
    n_rejected = len(rejected) if rejected is not None else 0
    return DetectionResult(
        markers=tuple(markers),
        image_shape=(gray.shape[0], gray.shape[1]),
        n_rejected=n_rejected,
    )


def generate_marker_image(marker_id: int, side_px: int) -> np.ndarray:
    """Render a ``DICT_4X4_50`` marker image (uint8 grayscale, ``side_px``
    square) via ``cv2.aruco.generateImageMarker`` -- used to synthesize test
    fixtures and to preview a printable fiducial. Not used at detection time.

    Raises :class:`VisionUnavailableError` if ``cv2`` is not installed.
    """
    if side_px <= 0:
        raise ValueError(f"side_px must be positive; got {side_px}")
    cv2 = _require_cv2()
    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    return cv2.aruco.generateImageMarker(aruco_dict, int(marker_id), int(side_px))


# --------------------------------------------------------------------------- #
# Pose estimation                                                             #
# --------------------------------------------------------------------------- #


def estimate_pose(
    src_points_px: np.ndarray,
    dst_points_px: np.ndarray,
    *,
    method: str = "ransac",
    corner_sigma_px: float = DEFAULT_CORNER_SIGMA_PX,
) -> PoseEstimate:
    """Fit a 2D rigid/similarity transform ``src -> dst`` from point pairs.

    Thin, direct wrapper over ``cv2.estimateAffinePartial2D`` (research note
    sec. 4): ``method`` is ``"ransac"`` (default) or ``"lmeds"``. Needs
    ``len(src) == len(dst) >= 2``; feed it all refined corners of all
    matched markers for the best baseline (>=8 points recommended for a
    stable RANSAC fit per the note).

    ``baseline_px`` (and the derived precision fields) is computed from the
    farthest pairwise distance within ``dst_points_px`` -- the image-space
    corner spread that actually bounds the achievable angular precision.

    Raises :class:`VisionUnavailableError` if ``cv2`` is not installed, or
    :class:`PoseEstimationError` if the inputs are invalid or OpenCV could
    not find a transform (returns ``None``, e.g. degenerate/collinear points).
    """
    cv2 = _require_cv2()
    src = _as_points2(src_points_px, "src_points_px")
    dst = _as_points2(dst_points_px, "dst_points_px")
    if len(src) != len(dst):
        raise PoseEstimationError(
            f"src_points_px and dst_points_px must be the same length; "
            f"got {len(src)} and {len(dst)}"
        )
    if len(src) < 2:
        raise PoseEstimationError(
            f"estimateAffinePartial2D needs at least 2 point pairs; got {len(src)}"
        )

    method_key = method.lower()
    if method_key == "ransac":
        cv_method = cv2.RANSAC
    elif method_key == "lmeds":
        cv_method = cv2.LMEDS
    else:
        raise ValueError(f"method must be 'ransac' or 'lmeds'; got {method!r}")

    matrix, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv_method)
    if matrix is None:
        raise PoseEstimationError(
            "cv2.estimateAffinePartial2D found no similarity transform "
            "(degenerate or insufficient point correspondences)"
        )

    scale = float(math.hypot(matrix[0, 0], matrix[1, 0]))
    theta_deg = float(math.degrees(math.atan2(matrix[1, 0], matrix[0, 0])))
    translation_px = np.array([matrix[0, 2], matrix[1, 2]], dtype=np.float64)
    baseline_px = _max_pairwise_distance(dst)
    n_inliers = int(inliers.sum()) if inliers is not None else len(dst)
    precision_deg = _angle_precision_deg(baseline_px, corner_sigma_px)

    return PoseEstimate(
        theta_deg=theta_deg,
        scale=scale,
        translation_px=translation_px,
        baseline_px=baseline_px,
        n_points=len(dst),
        n_inliers=n_inliers,
        estimated_precision_deg=precision_deg,
        meets_precision_target=precision_deg <= TARGET_ANGLE_PRECISION_DEG,
    )


def estimate_relative_pose(
    reference: DetectionResult,
    current: DetectionResult,
    *,
    method: str = "ransac",
    corner_sigma_px: float = DEFAULT_CORNER_SIGMA_PX,
) -> PoseEstimate:
    """Estimate the ``reference -> current`` pose from matching marker IDs.

    Matches markers present in *both* detections by ``marker_id`` and feeds
    every matched marker's 4 corners into :func:`estimate_pose` -- the
    "two markers spread across the mosaic" long-baseline case from the
    research note is exactly this: more matched markers (or markers farther
    apart) widen ``baseline_px`` and improve ``estimated_precision_deg``.

    Raises :class:`PoseEstimationError` if no marker IDs are common to both
    detections, or :class:`VisionUnavailableError` if ``cv2`` is missing.
    """
    common_ids = sorted(
        {m.marker_id for m in reference.markers} & {m.marker_id for m in current.markers}
    )
    if not common_ids:
        raise PoseEstimationError(
            "no marker IDs are common to both the reference and current "
            "detections; cannot estimate a relative pose"
        )
    src = np.concatenate([reference.by_id(i).corners_px for i in common_ids], axis=0)
    dst = np.concatenate([current.by_id(i).corners_px for i in common_ids], axis=0)
    return estimate_pose(src, dst, method=method, corner_sigma_px=corner_sigma_px)


# --------------------------------------------------------------------------- #
# Internal helpers                                                            #
# --------------------------------------------------------------------------- #


def _angle_precision_deg(baseline_px: float, corner_sigma_px: float) -> float:
    """sigma_theta ~= corner_sigma_px / baseline_px (rad) -> degrees.

    ``inf`` for a degenerate (zero or negative) baseline -- an explicit
    "cannot say anything about angular precision" signal rather than a
    misleadingly small number.
    """
    if baseline_px <= 0.0:
        return float("inf")
    return math.degrees(corner_sigma_px / baseline_px)


def _max_pairwise_distance(points_px: np.ndarray) -> float:
    """Farthest distance between any two points -- the corner baseline B
    used by the precision estimate (research note sec. 4)."""
    if len(points_px) < 2:
        return 0.0
    diff = points_px[:, None, :] - points_px[None, :, :]
    dist = np.hypot(diff[..., 0], diff[..., 1])
    return float(dist.max())


def _as_points2(values: Any, name: str) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64).reshape(-1, 2)
    if len(arr) == 0:
        raise PoseEstimationError(f"{name} must contain at least one point")
    if not np.all(np.isfinite(arr)):
        raise PoseEstimationError(f"{name} contains NaN or infinite values")
    return np.ascontiguousarray(arr)


def _as_gray_uint8(image: np.ndarray) -> np.ndarray:
    """Normalize an input image to a contiguous grayscale ``uint8`` array.

    Accepts 2D grayscale or 3D color (3 or 4 channels, converted with
    ``cv2.cvtColor``). Non-``uint8`` dtypes are rescaled to ``0..255`` (see
    :func:`_to_uint8`) -- ArUco detection expects an 8-bit image.
    """
    arr = np.asarray(image)
    if arr.ndim == 3:
        cv2 = _require_cv2()
        if arr.shape[2] == 3:
            arr = cv2.cvtColor(_to_uint8(arr), cv2.COLOR_BGR2GRAY)
        elif arr.shape[2] == 4:
            arr = cv2.cvtColor(_to_uint8(arr), cv2.COLOR_BGRA2GRAY)
        else:
            raise ValueError(
                f"color image must have 3 or 4 channels; got shape {arr.shape}"
            )
        return np.ascontiguousarray(arr)
    if arr.ndim != 2:
        raise ValueError(
            f"image must be 2D (grayscale) or 3D (color); got shape {arr.shape}"
        )
    return np.ascontiguousarray(_to_uint8(arr))


def _to_uint8(arr: np.ndarray) -> np.ndarray:
    """Rescale ``arr`` to ``uint8``. Integer input is clipped/cast directly;
    float input in ``[0, 1]`` or ``[0, 255]`` is scaled accordingly; any
    other float range is linearly rescaled to span ``[0, 255]``."""
    if arr.dtype == np.uint8:
        return arr
    if np.issubdtype(arr.dtype, np.integer):
        return np.clip(arr, 0, 255).astype(np.uint8)
    farr = np.asarray(arr, dtype=np.float64)
    finite = farr[np.isfinite(farr)]
    if finite.size == 0:
        return np.zeros(farr.shape, dtype=np.uint8)
    lo, hi = float(finite.min()), float(finite.max())
    if lo >= 0.0 and hi <= 1.0 + 1e-9:
        scaled = farr * 255.0
    elif lo >= 0.0 and hi <= 255.0 + 1e-9:
        scaled = farr
    else:
        span = (hi - lo) if hi > lo else 1.0
        scaled = (farr - lo) / span * 255.0
    return np.clip(scaled, 0, 255).astype(np.uint8)
