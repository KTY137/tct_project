"""Metrology-frame preprocessing: stabilize phase correlation under changing
illumination / vignette (Wave-5 step 1, ``docs/RESTART_HANDOFF_20260713.md``
"Wave 5 -- camera-metrology roadmap").

Raw-frame phase correlation (``controller.repeatability.cross_correlation_shift``,
``analysis.mosaic_stitch.refine_offset``) gets pinned toward ``(0, 0)`` when a
static vignette / bright rim dominates the frame: the vignette correlates at
zero shift regardless of real stage motion, biasing the peak
(``docs/design/camera_survey_metrology.md`` sections "B.0" point 5 and "D",
"[B] static vignette pins the correlation to (0,0)"). :func:`prepare_metrology_roi`
is the fix: crop to the region of interest, optionally calibrate out dark
current / flat-field response, flag saturated/invalid pixels, subtract a
broad Gaussian-blurred background (a vignette or illumination gradient is
almost entirely "background" at that scale), and normalize what is left --
so only genuine small-scale texture reaches the correlator.

Layer purity
------------
This module lives in ``analysis/`` and is therefore stdlib + numpy ONLY
(enforced by ``tests/test_layer_contracts.py::
test_analysis_is_stdlib_and_numpy_pure``) -- no Qt, no ``controller/``, no
``devices/``, no scipy, no cv2. The Gaussian blur is an FFT circular
convolution (``numpy.fft.rfft2``/``irfft2``), the same primitive already
used by ``controller.repeatability.cross_correlation_shift`` and
``analysis.mosaic_stitch.refine_offset`` -- no new numerical machinery
enters the codebase. numpy<2 pin: only long-stable APIs are used (``fft.rfft2``/
``irfft2``, ``pad``, ``outer``, ``diff``, ``ptp``, ``where``, ``isfinite``,
``iinfo``), matching the project-wide convention (see root ``CLAUDE.md``).

Never raises on frame CONTENT, however degenerate (all-NaN, all-saturated,
1x1, empty) -- a metrology run calls this once per grabbed frame and a
single bad frame must not abort the whole cycle; it simply scores
``quality = 0.0``. It DOES raise on a caller-configuration error (an *roi*
that does not fit the frame, or a *dark*/*flat* calibration frame shaped
wrong) -- those are refused fail-closed rather than silently misapplied, the
same "reject rather than guess" stance ``SCAN_DATA_FORMAT.md`` takes for the
HDF5 layout. See :func:`crop_roi` / :func:`apply_dark_flat`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "PreparedROI",
    "prepare_metrology_roi",
    "crop_roi",
    "apply_dark_flat",
    "saturation_mask",
    "high_pass_filter",
]

# --------------------------------------------------------------------------- #
# Tunable constants (all documented at point of use below)                    #
# --------------------------------------------------------------------------- #

#: Saturation threshold as a fraction of the integer dtype's max value, used
#: when the caller does not pass an explicit `saturation_level` for an
#: integer-dtype frame -- see :func:`saturation_mask`.
_SATURATION_DTYPE_FRACTION = 0.98

#: A flat-field pixel at or below this magnitude is treated as a no-op
#: divisor (1.0) rather than producing inf/NaN -- see :func:`apply_dark_flat`.
_FLAT_EPSILON = 1e-6

#: Below this std-dev, a valid-pixel patch is treated as numerically flat
#: (zero-mean only, no rescale) rather than dividing by a near-zero spread --
#: see :func:`prepare_metrology_roi`.
_STD_EPSILON = 1e-8

#: Reference amplitude for the quality score's soft contrast/edge-energy
#: ratios, as a fraction of the frame's dynamic range -- see
#: :func:`prepare_metrology_roi`'s "Quality score" docstring section.
_CONTRAST_REF_FRACTION = 0.05

#: Floor under that reference amplitude so a zero (or numerically tiny)
#: dynamic range never divides by zero.
_MIN_REFERENCE = 1e-6


# --------------------------------------------------------------------------- #
# Result container                                                            #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class PreparedROI:
    """Illumination-stabilized image ready for phase-correlation registration.

    Parameters
    ----------
    image : ndarray, float64, 2-D
        High-pass filtered (Gaussian-background-subtracted) and locally
        (zero-mean/unit-ish scale, over the valid mask) normalized image --
        see :func:`prepare_metrology_roi`. A pixel ``mask`` marks invalid is
        set to exactly ``0.0`` here (the zero-mean-neutral value), so a
        caller that correlates ``.image`` directly -- without separately
        consulting ``.mask`` -- still gets automatic, if partial,
        suppression of saturated/invalid regions.
    mask : ndarray, bool, 2-D, same shape as `image`
        ``True`` = valid (finite AND not saturated). ``False`` marks a pixel
        this function does not trust: saturated (at/above the detection
        threshold), non-finite (NaN/Inf) in the raw input, or made
        non-finite by dark/flat correction (e.g. a NaN calibration pixel).
    quality : float
        0-1 correlation-usability score; see :func:`prepare_metrology_roi`'s
        "Quality score" section for the formula. ``0.0`` for any degenerate
        input (all-invalid, tiny/empty, or textureless/blank).
    saturated_frac : float
        Fraction of ROI pixels (0-1) flagged saturated SPECIFICALLY --
        NOT the same as ``1 - mask.mean()``, which also counts non-finite
        pixels; see :func:`saturation_mask`.
    contrast : float
        RMS (std-dev) of the high-passed signal over valid pixels, in the
        SAME units as the (dark/flat-corrected) working array -- i.e.
        BEFORE the final zero-mean/unit-ish normalization divides that
        scale away. ``0.0`` when there are no valid pixels.
    """

    image: np.ndarray
    mask: np.ndarray
    quality: float
    saturated_frac: float
    contrast: float


# --------------------------------------------------------------------------- #
# Pipeline steps (each independently usable/testable)                         #
# --------------------------------------------------------------------------- #

def crop_roi(frame: np.ndarray, roi: tuple[int, int, int, int] | None) -> np.ndarray:
    """Crop *frame* to *roi* = ``(y0, x0, h, w)``.

    Convention: numpy axis order, row/Y first -- matches
    ``frame[y0:y0+h, x0:x0+w]`` directly and the ``(H, W)`` shape every
    camera frame in this app already uses (see e.g.
    ``analysis.mosaic_stitch``'s "Canvas axis convention": row tracks Y,
    column tracks X). This is deliberately NOT the ``(u, v)`` = (x, y)
    point-pair convention ``analysis.camera_calibration`` uses for affine
    fit correspondences -- a rectangle sliced out of an array and an
    image-space coordinate pair are different things and do not need the
    same axis order.

    ``roi=None`` returns *frame* unchanged (no crop).

    Fail-closed bounds validation: raises ``ValueError`` (never clips) if
    *roi* has a non-positive height/width, a negative origin, or extends
    past *frame*'s shape. An out-of-bounds *roi* is a caller/configuration
    error, not degenerate sensor data -- unlike the frame CONTENT handling
    elsewhere in this module (see the module docstring), a bad *roi* is
    refused rather than silently clipped or guessed at.
    """
    if roi is None:
        return frame
    y0, x0, h, w = (int(v) for v in roi)
    height, width = frame.shape[0], frame.shape[1]
    if h <= 0 or w <= 0:
        raise ValueError(f"roi height/width must be positive; got h={h}, w={w}")
    if y0 < 0 or x0 < 0:
        raise ValueError(f"roi origin must be non-negative; got (y0={y0}, x0={x0})")
    if y0 + h > height or x0 + w > width:
        raise ValueError(
            f"roi (y0={y0}, x0={x0}, h={h}, w={w}) exceeds frame shape {(height, width)}"
        )
    return frame[y0:y0 + h, x0:x0 + w]


def apply_dark_flat(
    raw: np.ndarray,
    dark: np.ndarray | None = None,
    flat: np.ndarray | None = None,
) -> np.ndarray:
    """Dark-subtract then flat-divide *raw* -> a float64 working array.

    ``corrected = (raw - dark) / flat`` (either step skipped if its argument
    is ``None``). *dark* and *flat*, when given, MUST already match
    ``raw.shape`` -- this function does not itself crop/resize a
    full-sensor calibration frame; pre-crop dark/flat to the same ROI you
    pass to :func:`crop_roi`. A shape mismatch raises ``ValueError`` rather
    than silently broadcasting (numpy broadcasting could otherwise succeed
    "successfully" against a wrong-shaped calibration frame, e.g. a 1-D
    array broadcast across every row, and silently produce a plausible but
    wrong result).

    *flat* is expected to already be a normalized flat-field reference
    (values near 1.0 for a uniformly-illuminated pixel, e.g.
    ``raw_flat / raw_flat.mean()``) -- this function does not normalize it.
    A near-zero flat pixel (``abs(flat) < 1e-6`` -- a dead pixel or an unset
    calibration slot) is guarded: its divisor is treated as ``1.0`` (a
    no-op) rather than producing ``inf``/``NaN``.
    """
    working = np.array(raw, dtype=np.float64, copy=True)
    if dark is not None:
        dark_arr = _as_calibration_frame(dark, working.shape, "dark")
        working = working - dark_arr
    if flat is not None:
        flat_arr = _as_calibration_frame(flat, working.shape, "flat")
        denom = np.where(np.abs(flat_arr) < _FLAT_EPSILON, 1.0, flat_arr)
        working = working / denom
    return working


def saturation_mask(
    raw: np.ndarray, saturation_level: float | None = None
) -> tuple[np.ndarray, float]:
    """Return ``(valid, saturated_frac)`` for *raw* -- the RAW, uncalibrated
    pixel values. Saturation is always judged on the raw sensor reading,
    BEFORE :func:`apply_dark_flat`: dark/flat-correcting a clipped pixel
    does not restore the lost information (it can even hide the clipping by
    rescaling it to a plausible-looking value).

    ``valid`` is ``True`` where the pixel is BOTH finite and NOT saturated.
    *saturation_level* (in raw counts) wins if given. Otherwise: for an
    integer *raw* dtype, the level is ``0.98 * iinfo(dtype).max`` (a
    dtype-derived ceiling, e.g. ~250 for uint8, ~64224 for uint16); for a
    float *raw* dtype there is no dtype "max" to derive a level from, so
    nothing is flagged saturated -- pass *saturation_level* explicitly for
    float frames (or for an integer frame whose calibrated full-scale is
    below the dtype's own range, e.g. a 12-bit sensor stored zero-padded
    into uint16) if saturation detection matters.

    ``saturated_frac`` counts ONLY genuinely-saturated (finite, >= level)
    pixels -- a non-finite (NaN/Inf) pixel is folded into ``valid=False``
    but is NOT counted as "saturated": that is a different failure mode
    (missing data), not a clipped reading.
    """
    raw = np.asarray(raw)
    raw_f = raw.astype(np.float64, copy=False)
    finite = np.isfinite(raw_f)
    if saturation_level is not None:
        level = float(saturation_level)
        saturated = finite & (raw_f >= level)
    elif np.issubdtype(raw.dtype, np.integer):
        level = _SATURATION_DTYPE_FRACTION * float(np.iinfo(raw.dtype).max)
        saturated = finite & (raw_f >= level)
    else:
        saturated = np.zeros(raw.shape, dtype=bool)
    valid = finite & ~saturated
    n = raw.size
    frac = float(np.count_nonzero(saturated)) / float(n) if n else 0.0
    return valid, frac


def high_pass_filter(image: np.ndarray, sigma_px: float) -> np.ndarray:
    """Subtract a Gaussian-blurred background from *image*::

        high_pass_filter(image, sigma) == image - gaussian_blur(image, sigma)

    This is what defeats a smooth vignette / illumination gradient: a broad
    gradient is almost entirely "background" at typical ``sigma_px``
    (default 15 px), and subtracting it away leaves only genuine small-scale
    texture -- exactly what phase correlation should lock onto instead of
    the vignette's centre.

    The blur is a separable Gaussian applied as an FFT CIRCULAR convolution
    (``numpy.fft.rfft2``/``irfft2`` only -- no ``scipy.ndimage``, no cv2;
    the same primitive already used by
    ``controller.repeatability.cross_correlation_shift`` and
    ``analysis.mosaic_stitch.refine_offset``, so no new numerical machinery
    enters the codebase). *image* is reflect-padded by
    ``ceil(3 * sigma_px)`` px per axis (clamped to ``size - 1`` so a tiny
    image never asks numpy to reflect past its own extent) before the FFT,
    then the pad is cropped back off -- this avoids BOTH the edge-darkening
    a zero-padded convolution would cause and the wrap-around a bare
    (unpadded) circular FFT convolution would cause.

    ``sigma_px <= 0`` or an empty *image* returns an all-zero array (the
    background estimate degenerates to the image itself) -- degenerate but
    valid, never raises.
    """
    image = np.asarray(image, dtype=np.float64)
    background = _gaussian_blur2d(image, sigma_px)
    return image - background


# --------------------------------------------------------------------------- #
# Main entry point                                                            #
# --------------------------------------------------------------------------- #

def prepare_metrology_roi(
    frame: np.ndarray,
    *,
    roi: tuple[int, int, int, int] | None = None,
    dark: np.ndarray | None = None,
    flat: np.ndarray | None = None,
    highpass_sigma_px: float = 15.0,
    saturation_level: float | None = None,
) -> PreparedROI:
    """Stabilize *frame* for phase-correlation registration under changing
    illumination / vignette -- see the module docstring for the "why".

    Pipeline (each step documented on its own public function)
    -------------------------------------------------------------
    1. **Grayscale + ROI crop.** A 3-D (colour) *frame* is averaged over its
       last axis first (mirrors ``controller.repeatability.
       cross_correlation_shift``'s convention); *roi* then crops via
       :func:`crop_roi` -- ``(y0, x0, h, w)``, fail-closed bounds.
    2. **Saturation mask.** Computed from the RAW crop, via
       :func:`saturation_mask` -- BEFORE any calibration correction.
    3. **Dark subtraction + flat division.** :func:`apply_dark_flat` on that
       same raw crop.
    4. **Invalid-pixel fill.** Pixels flagged untrustworthy (saturated,
       non-finite in the raw crop, OR made non-finite by dark/flat
       correction -- e.g. a NaN calibration pixel) are replaced with the
       mean of the valid pixels (``0.0`` if there are none) before
       filtering. This matters because step 5's blur is a GLOBAL FFT
       transform: a single leftover NaN would poison every output sample,
       not just the pixels near it. This is a standard "inpaint with a
       neutral level before filtering" step -- the filled pixels are still
       excluded from every reported statistic and zeroed in the final image
       (step 6), so they are never reported as real texture.
    5. **High-pass.** :func:`high_pass_filter` at *highpass_sigma_px*.
    6. **Local (zero-mean/unit-ish) normalization**, over the valid mask
       only: subtract the valid-pixel mean, divide by the valid-pixel
       std-dev (a std below ``1e-8`` is treated as "no spread" and skipped,
       to avoid amplifying a numerically-flat patch into noise). Invalid
       pixels are set to exactly ``0.0`` in the returned image.

    Quality score
    -------------
    ``quality = contrast_term * (1 - saturated_frac) * edge_term``, each
    factor bounded to ``[0, 1)`` / ``[0, 1]``::

        ref            = max(0.05 * dynamic_range, 1e-6)
        contrast_term  = contrast / (contrast + ref)
        edge_term      = edge_energy / (edge_energy + ref**2)

    ``contrast`` is the pre-normalization high-passed std-dev over valid
    pixels (see :class:`PreparedROI`). ``edge_energy`` is the mean squared
    finite-difference gradient of the (invalid-zeroed) high-passed image --
    a texture/edge-content term distinct from ``contrast``, which only sees
    overall spread and not spatial structure (a single smooth bump and a
    fine random dither can share a std-dev but not an edge-energy).
    ``dynamic_range`` is ``iinfo(dtype).max`` for an integer raw crop, else
    the raw crop's own valid-pixel peak-to-peak. Both ratio terms are soft
    (asymptotic, never hard-clamped) -- ``0`` for a flat/blank signal,
    approaching ``1`` for a signal large relative to 5% of the dynamic
    range, and always finite even when ``contrast``/``edge_energy`` are
    exactly ``0``. The product is clamped to ``[0, 1]`` defensively.

    A degenerate frame -- an all-invalid mask (all-NaN or all-saturated), or
    too small for a gradient (height or width ``< 2``), or empty -- always
    scores ``quality = 0.0``: ``contrast``/``edge_energy`` are ``0.0`` when
    there are no valid pixels, and the ratio terms map ``0`` to ``0``. This
    function never raises on frame CONTENT, however degenerate; only a
    caller-configuration error (a bad *roi*, or a *dark*/*flat* shaped
    wrong) raises -- see :func:`crop_roi` / :func:`apply_dark_flat`.

    Parameters
    ----------
    frame : ndarray, 2-D (or 3-D colour, averaged to gray first)
        The raw camera frame, any real dtype.
    roi : (y0, x0, h, w), optional
        See :func:`crop_roi`.
    dark, flat : ndarray, optional
        Calibration frames; must already match the ROI-cropped shape (or
        the full frame shape if *roi* is ``None``). See
        :func:`apply_dark_flat`.
    highpass_sigma_px : float
        Gaussian background sigma, in pixels (default 15.0). ``<= 0``
        degrades to an all-zero high-pass (see :func:`high_pass_filter`)
        rather than raising.
    saturation_level : float, optional
        Explicit saturation threshold in RAW counts; overrides the
        dtype-derived default. See :func:`saturation_mask`.

    Returns
    -------
    PreparedROI
    """
    frame = np.asarray(frame)
    if frame.ndim == 3:
        frame = frame.mean(axis=2)
    elif frame.ndim != 2:
        raise ValueError(
            f"frame must be 2-D (or 3-D colour, averaged to gray); got shape {frame.shape}"
        )

    raw = crop_roi(frame, roi)

    if raw.size == 0:
        empty_f = np.zeros(raw.shape, dtype=np.float64)
        return PreparedROI(
            image=empty_f,
            mask=np.zeros(raw.shape, dtype=bool),
            quality=0.0,
            saturated_frac=0.0,
            contrast=0.0,
        )

    raw_valid, saturated_frac = saturation_mask(raw, saturation_level)

    working = apply_dark_flat(raw, dark, flat)
    working_finite = np.isfinite(working)
    valid = raw_valid & working_finite
    n_valid = int(np.count_nonzero(valid))

    if n_valid > 0:
        fill_value = float(np.mean(working[valid]))
        if not np.isfinite(fill_value):
            fill_value = 0.0
    else:
        fill_value = 0.0
    working_filled = np.where(valid, working, fill_value)
    working_filled = np.where(np.isfinite(working_filled), working_filled, fill_value)

    highpassed = high_pass_filter(working_filled, highpass_sigma_px)

    if n_valid > 0:
        valid_vals = highpassed[valid]
        mean_valid = float(valid_vals.mean())
        contrast = float(valid_vals.std())
    else:
        mean_valid = 0.0
        contrast = 0.0

    edge_energy = _edge_energy(highpassed, valid)

    normalized = np.zeros_like(highpassed)
    if n_valid > 0:
        if contrast > _STD_EPSILON:
            normalized[valid] = (highpassed[valid] - mean_valid) / contrast
        else:
            normalized[valid] = highpassed[valid] - mean_valid

    if np.issubdtype(raw.dtype, np.integer):
        dynamic_range = float(np.iinfo(raw.dtype).max)
    elif n_valid > 0:
        dynamic_range = float(np.ptp(raw.astype(np.float64)[raw_valid]))
    else:
        dynamic_range = 0.0

    quality = _quality_score(contrast, saturated_frac, edge_energy, dynamic_range)

    return PreparedROI(
        image=normalized,
        mask=valid,
        quality=quality,
        saturated_frac=saturated_frac,
        contrast=contrast,
    )


# --------------------------------------------------------------------------- #
# Private helpers                                                             #
# --------------------------------------------------------------------------- #

def _as_calibration_frame(
    cal: np.ndarray, expected_shape: tuple[int, ...], name: str
) -> np.ndarray:
    """Validate a dark/flat calibration frame's shape (fail-closed -- see
    :func:`apply_dark_flat`) and return it as float64."""
    cal_arr = np.asarray(cal, dtype=np.float64)
    if cal_arr.shape != tuple(expected_shape):
        raise ValueError(
            f"{name} shape {cal_arr.shape} does not match the (possibly "
            f"ROI-cropped) frame shape {tuple(expected_shape)}; pre-crop "
            f"{name} to the same roi if you are using one"
        )
    return cal_arr


def _edge_energy(highpassed: np.ndarray, valid: np.ndarray) -> float:
    """Mean squared finite-difference gradient of *highpassed*, restricted
    to *valid* pixels (invalid pixels are zeroed before differencing, so a
    valid/invalid boundary contributes a small bounded jump rather than
    garbage -- an accepted approximation for this coarse quality heuristic,
    not a photometrically exact edge map).

    ``0.0`` for a frame smaller than 2 px on either axis (no gradient is
    defined there) -- part of the "tiny frames -> quality 0" contract.
    """
    if highpassed.shape[0] < 2 or highpassed.shape[1] < 2:
        return 0.0
    work = np.where(valid, highpassed, 0.0)
    gy = np.diff(work, axis=0)
    gx = np.diff(work, axis=1)
    count = gy.size + gx.size
    if count == 0:
        return 0.0
    total = float(np.sum(gy * gy)) + float(np.sum(gx * gx))
    return total / count


def _quality_score(
    contrast: float, saturated_frac: float, edge_energy: float, dynamic_range: float
) -> float:
    """See :func:`prepare_metrology_roi`'s "Quality score" docstring section."""
    ref = max(_CONTRAST_REF_FRACTION * dynamic_range, _MIN_REFERENCE)
    contrast_term = contrast / (contrast + ref)
    edge_term = edge_energy / (edge_energy + ref * ref)
    quality = contrast_term * (1.0 - saturated_frac) * edge_term
    return float(min(max(quality, 0.0), 1.0))


def _gaussian_kernel_axis(n: int, sigma: float) -> np.ndarray:
    """Length-*n* 1-D Gaussian already laid out for an FFT CIRCULAR
    convolution: peak at index 0, falling off symmetrically toward ``n/2``
    in both directions (circular distance), normalized to sum 1. No
    fftshift round-trip is needed because it is built pre-shifted."""
    idx = np.arange(n, dtype=np.float64)
    dist = np.minimum(idx, n - idx)
    kernel = np.exp(-0.5 * (dist / sigma) ** 2)
    total = kernel.sum()
    return kernel / total if total > 0.0 else kernel


def _gaussian_blur2d(image: np.ndarray, sigma_px: float) -> np.ndarray:
    """Isotropic Gaussian blur of a 2-D array via FFT circular convolution
    -- see :func:`high_pass_filter`, which is the public entry point."""
    image = np.asarray(image, dtype=np.float64)
    sigma = float(sigma_px)
    if sigma <= 0.0 or image.size == 0:
        return image.copy()

    h, w = image.shape
    pad = max(1, int(np.ceil(3.0 * sigma)))
    pad_h = min(pad, max(h - 1, 0))
    pad_w = min(pad, max(w - 1, 0))
    padded = np.pad(image, ((pad_h, pad_h), (pad_w, pad_w)), mode="reflect")

    ph, pw = padded.shape
    kernel2d = np.outer(_gaussian_kernel_axis(ph, sigma), _gaussian_kernel_axis(pw, sigma))

    spectrum = np.fft.rfft2(padded) * np.fft.rfft2(kernel2d)
    blurred = np.fft.irfft2(spectrum, s=padded.shape)

    return blurred[pad_h:pad_h + h, pad_w:pad_w + w]
