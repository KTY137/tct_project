"""
Sensor-mosaic stitching — pure math (night-shift beat A4a, ``docs/
NIGHT_SHIFT_20260712.md`` Lane A4a; design: ``artifacts_claude/v5/src/
mosaic.body.html`` §"How it works", ``docs/design/feature_requests_v5.md``
§3).

Raster the stage under the camera, grab one frame per tile, stitch them
with the px→mm calibration already trusted from the camera repeatability
test (``controller.repeatability.RepeatabilityTester.calibrate``) — one
high-resolution image of the whole sensor with real millimetre axes. This
module is ONLY the math: grid planning, calibrated placement + blending,
canvas/mm geometry, and a v2 seam-refinement hook. No Qt, no hardware I/O,
no motion — the move→settle→grab loop and the DangerGate-gated procedure
that drives real tiles into :func:`place_tiles` are a later beat (A4b
camera/motor plumbing, A4c procedure runner + UI), per CLAUDE.md's
"analysis/" row: named/derived math lives here, panels and procedures call
it.

v1 contract
-----------
Tile placement comes ONLY from the stage position each tile was grabbed at,
converted to pixels via the camera's px→mm calibration — see
:func:`plan_grid` (grid layout) and :func:`place_tiles` (calibrated
placement + linear feather blending in overlap zones). There is **no
global optimisation, no bundle adjustment, no seam search** in v1:
:func:`refine_offset` is a *v2* building block (a per-pair sub-pixel
correlation you can call yourself) and is **not** wired into
:func:`place_tiles` here — a caller that wants refined seams computes
corrected centres with it and passes THOSE into :func:`place_tiles`.

Units
-----
Every quantity is explicitly mm (stage/calibration space) or px (canvas/
image-pixel space) in both parameter names (``_mm`` / ``_px`` suffixes,
matching the ``points/x_mm`` convention in ``SCAN_DATA_FORMAT.md``) and
docstrings. The shared scale between the two is ``px_per_mm`` (a single
isotropic scalar — one camera magnification for a whole mosaic run, the
same quantity :meth:`~controller.repeatability.RepeatabilityTester.calibrate`
returns).

Canvas axis convention
-----------------------
A stitched canvas is a plain 2-D array, shape ``(H_px, W_px)``. Row axis
(axis 0) tracks Y, column axis (axis 1) tracks X — the standard image-array
``(height, width)`` shape order, matching every camera frame in this app.
Row/column increase with increasing Y/X respectively (no vertical flip):
canvas pixel ``(row=0, col=0)`` sits at mm position ``origin_mm`` = the
area's own ``(x0_mm, y0_mm)`` (minimum-corner), i.e. this is a plain
Cartesian mm grid, not a display image. Any camera-sensor-vs-stage-axis
flip is a hardware/plumbing concern for the caller (A4b) — out of scope for
this pure-math v1 layer.

Layer purity
------------
This module lives in ``analysis/`` and is therefore restricted to
stdlib + numpy only (enforced by ``tests/test_layer_contracts.py::
test_analysis_is_stdlib_and_numpy_pure``) — no Qt, no ``controller/``, no
``devices/``. In particular, :func:`refine_offset` does **not** import
``controller.repeatability.cross_correlation_shift`` (the sub-pixel
phase-correlation helper already shipped for the camera repeatability
test): that helper lives in ``controller/`` which, although not GUI code,
sits one layer away from analysis's pure-leaf layer and cannot be imported
from here. This module instead carries a small, self-contained
re-implementation of the same algorithm (Hann-windowed FFT phase
correlation + parabolic sub-pixel peak fit) with the identical
``(dy_px, dx_px)`` sign convention, so the two stay drop-in consistent even
though no code is shared — see :func:`refine_offset`'s docstring for
detail.

Typical v1 pipeline (illustrative — grab_frame_at is NOT part of this
module; it is the A4b/A4c motion+camera plumbing)::

    centers_mm, (rows, cols) = plan_grid(area_mm, fov_mm, overlap_frac=0.15)
    shape_px, origin_mm = canvas_geometry(area_mm, px_per_mm)
    tiles = [(grab_frame_at(x, y), (x, y)) for x, y in centers_mm]
    canvas, weight_map = place_tiles(shape_px, tiles, px_per_mm, origin_mm)

numpy<2: only long-stable APIs are used (``ceil``, ``linspace``, ``arange``,
``minimum``, ``outer``, ``isnan``, ``where``, ``hanning``, ``fft.rfft2``/
``irfft2``, ``unravel_index``) — matches the project-wide ``numpy<2`` pin
(see root ``CLAUDE.md``).
"""
from __future__ import annotations

import numpy as np

__all__ = [
    "OVERLAP_FRAC_MIN",
    "OVERLAP_FRAC_MAX",
    "plan_grid",
    "canvas_geometry",
    "mm_to_px",
    "px_to_mm",
    "place_tiles",
    "refine_offset",
]

# --------------------------------------------------------------------------- #
# Grid planning                                                               #
# --------------------------------------------------------------------------- #

#: Requested overlap fractions outside this range are silently clamped (see
#: :func:`plan_grid`) — 5% floor because 0% overlap gives v2's
#: :func:`refine_offset` nothing to correlate against; 50% ceiling because
#: beyond that adjacent tiles cover mostly the same ground.
OVERLAP_FRAC_MIN = 0.05
OVERLAP_FRAC_MAX = 0.50


def plan_grid(
    area_mm: tuple[float, float, float, float],
    fov_mm: tuple[float, float],
    overlap_frac: float,
) -> tuple[list[tuple[float, float]], tuple[int, int]]:
    """Plan a raster of camera field-of-view tiles covering *area_mm*.

    Parameters
    ----------
    area_mm : (x0_mm, y0_mm, x1_mm, y1_mm)
        The region to cover, in stage millimetres. Requires
        ``x1_mm >= x0_mm`` and ``y1_mm >= y0_mm`` (a zero-width/height area
        is allowed and degenerates to a single tile).
    fov_mm : (width_mm, height_mm)
        The camera's field of view at the working magnification, in mm —
        one tile's footprint. Both entries must be strictly positive.
    overlap_frac : float
        Requested fractional overlap between adjacent tiles (e.g. ``0.15``
        for 15%). Silently clamped to ``[OVERLAP_FRAC_MIN, OVERLAP_FRAC_MAX]``
        = ``[0.05, 0.5]`` before use.

    Returns
    -------
    (centers_mm, (rows, cols))
        *centers_mm* is a flat ``list[(x_mm, y_mm)]`` of tile-centre
        coordinates in **row-major, snake (boustrophedon) order**: outer
        loop over *rows* (each row is one fixed Y position — one pass along
        X), inner loop over *cols* (X positions within that row);
        odd-indexed rows (1, 3, 5, ...) walk X in reverse so consecutive
        tiles in the flat list are always spatially adjacent (the last tile
        of one row neighbours the first tile of the next) — minimises stage
        travel for the move→settle→grab loop this feeds. *rows* counts
        distinct Y positions, *cols* counts distinct X positions, so
        ``len(centers_mm) == rows * cols``; this matches
        :func:`canvas_geometry`'s ``shape_px = (H_px, W_px)`` convention
        (H tracks Y/rows, W tracks X/cols).

        Tile centres are evenly spaced between ``lo + fov/2`` and
        ``hi - fov/2`` on each axis (not a fixed stride), so the first and
        last tile's outer edges land exactly on the requested area boundary
        with no ragged partial tile — realised overlap is therefore always
        ``>=`` the requested *overlap_frac* (rounding the tile count up, per
        axis, can only add overlap, never remove it), keeping
        :func:`place_tiles`'s coverage gap-free by construction.

        If *area_mm* fits inside a single *fov_mm* footprint on both axes,
        the result is one tile centred on the area's own centre and
        ``(rows, cols) == (1, 1)``.

    Raises
    ------
    ValueError
        If *fov_mm* is not strictly positive on both axes, or
        ``x1_mm < x0_mm`` / ``y1_mm < y0_mm``.
    """
    x0, y0, x1, y1 = (float(v) for v in area_mm)
    fov_w, fov_h = float(fov_mm[0]), float(fov_mm[1])
    if fov_w <= 0.0 or fov_h <= 0.0:
        raise ValueError(f"fov_mm must be positive on both axes; got {fov_mm}")
    if x1 < x0 or y1 < y0:
        raise ValueError(
            f"area_mm must have x1_mm >= x0_mm and y1_mm >= y0_mm; got {area_mm}"
        )

    overlap = min(max(float(overlap_frac), OVERLAP_FRAC_MIN), OVERLAP_FRAC_MAX)
    area_w, area_h = x1 - x0, y1 - y0
    stride_w = fov_w * (1.0 - overlap)
    stride_h = fov_h * (1.0 - overlap)

    cols = 1 if area_w <= fov_w else int(np.ceil((area_w - fov_w) / stride_w)) + 1
    rows = 1 if area_h <= fov_h else int(np.ceil((area_h - fov_h) / stride_h)) + 1

    xs = _axis_tile_centers(x0, x1, fov_w, cols)
    ys = _axis_tile_centers(y0, y1, fov_h, rows)

    centers_mm: list[tuple[float, float]] = []
    for r in range(rows):
        row_xs = xs if r % 2 == 0 else list(reversed(xs))
        y = ys[r]
        centers_mm.extend((x, y) for x in row_xs)

    return centers_mm, (rows, cols)


def _axis_tile_centers(lo: float, hi: float, fov: float, n: int) -> list[float]:
    """*n* evenly spaced tile-centre coordinates (mm) covering ``[lo, hi]``
    with footprint *fov* per tile (see :func:`plan_grid`). ``n <= 1``
    returns the midpoint regardless of how *lo*/*hi* compare to *fov*."""
    if n <= 1:
        return [(lo + hi) / 2.0]
    c_lo, c_hi = lo + fov / 2.0, hi - fov / 2.0
    return [float(v) for v in np.linspace(c_lo, c_hi, n)]


# --------------------------------------------------------------------------- #
# mm <-> px geometry                                                          #
# --------------------------------------------------------------------------- #

def canvas_geometry(
    area_mm: tuple[float, float, float, float],
    px_per_mm: float,
) -> tuple[tuple[int, int], tuple[float, float]]:
    """Canvas pixel shape + mm origin for a stitched mosaic covering
    *area_mm* at *px_per_mm* — everything a caller needs to derive real mm
    axes for the canvas :func:`place_tiles` builds (mirrors
    :func:`analysis.scan_grid.grid_extent`'s role for scan maps).

    Parameters
    ----------
    area_mm : (x0_mm, y0_mm, x1_mm, y1_mm)
        Same convention as :func:`plan_grid`.
    px_per_mm : float
        The camera's pixel scale from self-calibration (see
        ``controller.repeatability.RepeatabilityTester.calibrate``) — must
        be positive; shared by the canvas and every tile placed into it.

    Returns
    -------
    (shape_px, origin_mm)
        *shape_px* = ``(H_px, W_px)``: the canvas array shape
        :func:`place_tiles` expects as ``canvas_shape_px`` — ``H_px`` spans
        the area's Y extent (``y1_mm - y0_mm``), ``W_px`` its X extent, each
        rounded UP to the nearest whole pixel so the canvas never clips a
        fraction of a pixel off the requested area (minimum ``1`` per axis,
        even for a zero-extent area). The mm→px product is rounded to 6
        decimals before ceiling (matches ``analysis.scan_grid``'s
        ``decimals=6`` convention) purely to absorb float jitter that could
        otherwise push an exact boundary (e.g. ``12.0 mm * 5 px/mm``) up to
        a spurious extra pixel.

        *origin_mm* = ``(x0_mm, y0_mm)`` — the mm position of canvas pixel
        ``(row=0, col=0)``; pass straight through to :func:`place_tiles`,
        :func:`mm_to_px`, and :func:`px_to_mm` as their ``origin_mm``.

    Raises
    ------
    ValueError
        If *px_per_mm* is not positive, or ``x1_mm < x0_mm`` /
        ``y1_mm < y0_mm``.
    """
    x0, y0, x1, y1 = (float(v) for v in area_mm)
    if px_per_mm <= 0.0:
        raise ValueError(f"px_per_mm must be positive; got {px_per_mm}")
    if x1 < x0 or y1 < y0:
        raise ValueError(
            f"area_mm must have x1_mm >= x0_mm and y1_mm >= y0_mm; got {area_mm}"
        )
    w_px = max(1, int(np.ceil(round((x1 - x0) * px_per_mm, 6))))
    h_px = max(1, int(np.ceil(round((y1 - y0) * px_per_mm, 6))))
    return (h_px, w_px), (x0, y0)


def mm_to_px(
    x_mm: float,
    y_mm: float,
    origin_mm: tuple[float, float],
    px_per_mm: float,
) -> tuple[float, float]:
    """Stage ``(x_mm, y_mm)`` -> floating-point canvas pixel
    ``(col_px, row_px)``.

    *origin_mm* is ``(x0_mm, y0_mm)`` — the mm position of canvas pixel
    ``(row=0, col=0)`` (see :func:`canvas_geometry` / module docstring
    "Canvas axis convention"): column increases with X, row increases with
    Y, no flip.
    """
    ox_mm, oy_mm = origin_mm
    col_px = (float(x_mm) - float(ox_mm)) * float(px_per_mm)
    row_px = (float(y_mm) - float(oy_mm)) * float(px_per_mm)
    return col_px, row_px


def px_to_mm(
    col_px: float,
    row_px: float,
    origin_mm: tuple[float, float],
    px_per_mm: float,
) -> tuple[float, float]:
    """Inverse of :func:`mm_to_px`: canvas pixel ``(col_px, row_px)`` ->
    stage ``(x_mm, y_mm)``."""
    ox_mm, oy_mm = origin_mm
    x_mm = float(ox_mm) + float(col_px) / float(px_per_mm)
    y_mm = float(oy_mm) + float(row_px) / float(px_per_mm)
    return x_mm, y_mm


# --------------------------------------------------------------------------- #
# Placement + linear feather blending                                        #
# --------------------------------------------------------------------------- #

def place_tiles(
    canvas_shape_px: tuple[int, int],
    tiles: list[tuple[np.ndarray, tuple[float, float]]],
    px_per_mm: float,
    origin_mm: tuple[float, float],
) -> tuple[np.ndarray, np.ndarray]:
    """Stitch *tiles* onto one canvas by calibrated placement + linear
    feather blending (v1 contract — see module docstring: no seam search,
    no global optimisation).

    Parameters
    ----------
    canvas_shape_px : (H_px, W_px)
        Output canvas shape in pixels — typically
        ``canvas_geometry(area_mm, px_per_mm)[0]``. H tracks Y, W tracks X
        (see module docstring "Canvas axis convention").
    tiles : list of (image2d, center_mm)
        One entry per grabbed frame. *image2d* is a 2-D array, shape
        ``(H_tile_px, W_tile_px)`` — any real dtype, cast to float64
        internally; a NaN pixel inside a tile (e.g. a known-bad camera
        pixel) is "no data" and contributes zero weight, never averaged in
        as a fabricated value. *center_mm* is the ``(x_mm, y_mm)`` stage
        position the tile was grabbed at (a :func:`plan_grid` centre, or the
        actual motor readback at grab time). Tiles need not be uniform
        size. Order never matters (see "Blending" below).
    px_per_mm : float
        Shared pixel scale for the canvas AND every tile (one camera
        magnification for the whole mosaic run). Must be positive.
    origin_mm : (x0_mm, y0_mm)
        mm position of canvas pixel ``(row=0, col=0)`` — typically
        ``canvas_geometry(area_mm, px_per_mm)[1]``.

    Returns
    -------
    (canvas, weight_map) : tuple[ndarray, ndarray]
        Both shape *canvas_shape_px*, dtype float64.

        *canvas* is the feather-blended stitch: at each pixel, the weighted
        mean of every tile covering it. A pixel no tile covers at all is
        ``NaN`` — never zero-filled, never dropped from the array (the
        canvas is always exactly *canvas_shape_px*), matching the
        NaN-for-unsampled-cell convention :func:`analysis.scan_grid.
        points_to_grid` already uses for scan maps.

        *weight_map* is the raw accumulated feather-weight sum backing each
        canvas pixel — ``0.0`` exactly where no tile covers it (so
        ``np.isnan(canvas) == (weight_map == 0.0)`` always holds), and the
        DENOMINATOR of the weighted average elsewhere. It is a
        coverage/confidence map a caller can threshold or display; it is
        NOT itself normalised to ``[0, 1]``.

    Blending
    --------
    Each tile contributes a separable linear ("triangular hat") feather
    weight per axis: highest at the tile's own centre, lowest — but always
    **strictly positive**, never exactly zero — at its border (see
    :func:`_axis_ramp`). The strictly-positive floor matters: it is what
    lets an isolated tile edge (the outer boundary of the whole mosaic,
    where no neighbouring tile exists to blend with) still contribute its
    real pixel value with full fidelity, because a weighted average with
    only ONE nonzero-weight contributor always equals that contributor's
    value exactly, whatever the weight's magnitude. The ramp only visibly
    matters where two-or-more tiles overlap — the requested "weight ramps
    at tile borders" v1 behaviour. Because every tile's contribution is
    *added* into a shared numerator/denominator (never assigned), placement
    order never changes the result: **later tiles never hard-overwrite**
    earlier ones. Placement itself is nearest-pixel (each tile's centre is
    rounded to the nearest integer canvas pixel) — v1 does no sub-pixel
    resampling/interpolation of the source tile.

    Raises
    ------
    ValueError
        If *canvas_shape_px* is not positive on both axes, *px_per_mm* is
        not positive, or any tile's *image2d* is not a non-empty 2-D array.
    """
    h_px, w_px = int(canvas_shape_px[0]), int(canvas_shape_px[1])
    if h_px <= 0 or w_px <= 0:
        raise ValueError(f"canvas_shape_px must be positive; got {canvas_shape_px}")
    if px_per_mm <= 0.0:
        raise ValueError(f"px_per_mm must be positive; got {px_per_mm}")

    numerator = np.zeros((h_px, w_px), dtype=np.float64)
    weight_sum = np.zeros((h_px, w_px), dtype=np.float64)

    for image2d, center_mm in tiles:
        img = np.asarray(image2d, dtype=np.float64)
        if img.ndim != 2 or img.size == 0:
            raise ValueError(
                f"tile image2d must be a non-empty 2-D array; got shape {img.shape}"
            )
        th, tw = img.shape

        col_px, row_px = mm_to_px(center_mm[0], center_mm[1], origin_mm, px_per_mm)
        r0 = int(round(row_px - th / 2.0))
        c0 = int(round(col_px - tw / 2.0))

        w2d = _feather_weight(th, tw)

        # Clip the tile rectangle to the canvas -- a tile may hang off any edge.
        src_r0, src_c0, src_r1, src_c1 = 0, 0, th, tw
        dst_r0, dst_c0, dst_r1, dst_c1 = r0, c0, r0 + th, c0 + tw
        if dst_r0 < 0:
            src_r0 -= dst_r0
            dst_r0 = 0
        if dst_c0 < 0:
            src_c0 -= dst_c0
            dst_c0 = 0
        if dst_r1 > h_px:
            src_r1 -= dst_r1 - h_px
            dst_r1 = h_px
        if dst_c1 > w_px:
            src_c1 -= dst_c1 - w_px
            dst_c1 = w_px
        if dst_r0 >= dst_r1 or dst_c0 >= dst_c1:
            continue  # tile lands entirely outside the canvas

        img_v = img[src_r0:src_r1, src_c0:src_c1]
        w_v = w2d[src_r0:src_r1, src_c0:src_c1]

        valid = ~np.isnan(img_v)
        contrib_w = np.where(valid, w_v, 0.0)
        contrib_val = np.where(valid, img_v, 0.0)

        numerator[dst_r0:dst_r1, dst_c0:dst_c1] += contrib_val * contrib_w
        weight_sum[dst_r0:dst_r1, dst_c0:dst_c1] += contrib_w

    canvas = np.full((h_px, w_px), np.nan, dtype=np.float64)
    covered = weight_sum > 0.0
    canvas[covered] = numerator[covered] / weight_sum[covered]
    return canvas, weight_sum


def _axis_ramp(n: int) -> np.ndarray:
    """1-D linear ("triangular hat") feather weight, length *n*: peaks at
    1.0 at the centre index, decreases toward each end, floored strictly
    above 0 at the two border pixels — never exactly 0, see
    :func:`place_tiles`'s "Blending" section for why that floor matters.
    ``n <= 1`` returns a constant array of 1.0 (no room for a ramp)."""
    if n <= 1:
        return np.ones(max(n, 0), dtype=np.float64)
    idx = np.arange(n, dtype=np.float64)
    dist_to_edge = np.minimum(idx, (n - 1) - idx)
    half = (n - 1) / 2.0
    return (dist_to_edge + 1.0) / (half + 1.0)


def _feather_weight(h: int, w: int) -> np.ndarray:
    """Separable 2-D linear feather weight for an ``(h, w)`` tile — outer
    product of the two 1-D :func:`_axis_ramp` windows."""
    return np.outer(_axis_ramp(h), _axis_ramp(w))


# --------------------------------------------------------------------------- #
# v2 hook: sub-pixel seam refinement (NOT wired into place_tiles here)       #
# --------------------------------------------------------------------------- #

#: A measured correction larger than this fraction of either tile dimension
#: is treated as a garbage lock-on and discarded wholesale (see
#: :func:`refine_offset`).
_REFINE_MAX_CORRECTION_FRAC = 0.10

#: Tiles smaller than this on either axis are rejected without even
#: attempting a correlation (too few samples for a meaningful FFT peak).
_REFINE_MIN_TILE_PX = 4


def refine_offset(
    tile_a: np.ndarray,
    tile_b: np.ndarray,
    nominal_shift_px: tuple[float, float],
) -> tuple[float, float]:
    """v2 seam-refinement hook: sub-pixel phase-correlation shift of
    *tile_b* relative to *tile_a*, sanity-gated against *nominal_shift_px*.

    NOT wired into :func:`place_tiles` in v1 (see module docstring) — a
    caller that wants refined seams calls this per adjacent tile pair and
    folds the corrected centre into its own *tiles* list before calling
    :func:`place_tiles`.

    Re-implementation note
    -----------------------
    Same algorithm (Hann-windowed FFT phase correlation with a 3-point
    parabolic sub-pixel peak fit) and the same sign convention as
    ``controller.repeatability.cross_correlation_shift`` — the helper
    already shipped for the camera repeatability test — but a fresh,
    self-contained copy, not an import: ``analysis/`` is a pure stdlib+numpy
    leaf (``tests/test_layer_contracts.py::
    test_analysis_is_stdlib_and_numpy_pure``) and may not import
    ``controller/``, Qt, or anything else project-internal. If
    ``controller/repeatability.py``'s algorithm ever changes, this copy
    needs updating by hand alongside it.

    Parameters
    ----------
    tile_a, tile_b : ndarray, 2-D
        Grayscale image tiles to correlate — pass the full FOV-sized tiles
        (not just an overlap strip): the 10% rejection cap below is
        measured against *these* arrays' own ``(h, w)``, which is only
        "10% of the camera FOV" in the design-doc sense if what you pass in
        IS the FOV-sized tile. Cropped to their common
        ``(min(h), min(w))`` region internally if shapes differ.
    nominal_shift_px : (dy_px, dx_px)
        The shift predicted purely from the calibrated stage-position
        placement (e.g. the difference between the two tiles'
        :func:`mm_to_px` centres) — the v1 placement this function may
        correct, in the SAME ``(dy, dx)`` = (row, column) order as the
        return value.

    Returns
    -------
    (dy_px, dx_px)
        The measured sub-pixel shift of *tile_b* relative to *tile_a*
        (positive dy = *tile_b* appears shifted down; positive dx = right),
        if trusted; otherwise *nominal_shift_px* unchanged (see
        "Rejection").

    Rejection
    ---------
    A measured correction (``measured - nominal``) larger than
    :data:`_REFINE_MAX_CORRECTION_FRAC` (10%) of either tile dimension is
    treated as a garbage lock-on (e.g. a periodic/textureless surface with
    no real matching feature) and discarded WHOLESALE — this returns
    *nominal_shift_px* completely unchanged rather than a partially-trusted
    clamp, since a bad correlation peak is not "slightly wrong in a safe
    direction," it is uninformative. Tiles smaller than
    :data:`_REFINE_MIN_TILE_PX` on either axis are rejected the same way,
    without even attempting the correlation.

    Raises
    ------
    ValueError
        If *tile_a* or *tile_b* is not 2-D.
    """
    a = np.asarray(tile_a, dtype=np.float64)
    b = np.asarray(tile_b, dtype=np.float64)
    if a.ndim != 2 or b.ndim != 2:
        raise ValueError("refine_offset expects 2-D (grayscale) tiles")

    nominal = (float(nominal_shift_px[0]), float(nominal_shift_px[1]))

    h = min(a.shape[0], b.shape[0])
    w = min(a.shape[1], b.shape[1])
    if h < _REFINE_MIN_TILE_PX or w < _REFINE_MIN_TILE_PX:
        return nominal

    dy, dx = _phase_correlation_shift(a[:h, :w], b[:h, :w])

    limit_dy = _REFINE_MAX_CORRECTION_FRAC * h
    limit_dx = _REFINE_MAX_CORRECTION_FRAC * w
    if abs(dy - nominal[0]) > limit_dy or abs(dx - nominal[1]) > limit_dx:
        return nominal

    return dy, dx


def _hann2d(shape: tuple[int, int]) -> np.ndarray:
    wy = np.hanning(shape[0])
    wx = np.hanning(shape[1])
    return np.outer(wy, wx)


def _parabolic_peak(corr: np.ndarray, peak: tuple[int, int], axis: int) -> float:
    """Refine an integer *peak* index to sub-pixel along *axis* with a
    3-point parabola fit through the neighbouring correlation samples
    (wraps circularly at the array boundary, matching the FFT's periodic
    domain)."""
    n = corr.shape[axis]
    i = peak[axis]

    def val(k: int) -> float:
        idx = list(peak)
        idx[axis] = k % n
        return float(corr[tuple(idx)])

    ym1, y0, yp1 = val(i - 1), val(i), val(i + 1)
    denom = ym1 - 2.0 * y0 + yp1
    delta = 0.5 * (ym1 - yp1) / denom if denom != 0.0 else 0.0
    return i + delta


def _phase_correlation_shift(ref: np.ndarray, img: np.ndarray) -> tuple[float, float]:
    """Sub-pixel ``(dy, dx)`` displacement of *img* relative to *ref* via
    windowed FFT phase correlation — see :func:`refine_offset`'s
    "Re-implementation note" for provenance and sign-convention detail."""
    ref = np.asarray(ref, dtype=np.float64)
    img = np.asarray(img, dtype=np.float64)
    if ref.shape != img.shape:
        hh = min(ref.shape[0], img.shape[0])
        ww = min(ref.shape[1], img.shape[1])
        ref, img = ref[:hh, :ww], img[:hh, :ww]

    win = _hann2d(ref.shape)
    a = (ref - ref.mean()) * win
    b = (img - img.mean()) * win

    F = np.fft.rfft2(a)
    G = np.fft.rfft2(b)
    R = F * np.conj(G)
    R /= np.abs(R) + 1e-12
    corr = np.fft.irfft2(R, s=ref.shape)

    peak = np.unravel_index(int(np.argmax(corr)), corr.shape)
    dy = _parabolic_peak(corr, peak, axis=0)
    dx = _parabolic_peak(corr, peak, axis=1)

    H, W = corr.shape
    if dy > H / 2:
        dy -= H
    if dx > W / 2:
        dx -= W
    return -dy, -dx
