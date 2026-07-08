"""
Reconstruct a scattered ``(x, y, value)`` point cloud into a regular 2-D grid.

Every 2-D map in this app (live scan-panel map, the detachable
``ScanMapWindow``, the post-run ``AnalysisPanel`` re-plot) starts from the
same shape of data: a set of ``(x_mm, y_mm)`` stage positions, each with one
scalar value (charge, amplitude, drift time, ...), and needs to end up as a
dense 2-D array for ``pyqtgraph.ImageView``. Three near-identical
implementations grew independently with subtly different NaN handling
(``gui/scan_panel.py``, ``gui/scan_map_window.py``, ``gui/analysis_panel.py``
— see ``docs/research/scan_viewer_design_review.md``). This module is the one
canonical implementation; GUI code should call it rather than re-deriving the
grid inline (see ``.claude/AGENT_PROTOCOL.md`` — physics/formula code lives in
``analysis/``, GUI panels call it).

Axes / units convention
------------------------
``x_mm`` / ``y_mm`` are stage coordinates in millimetres — the same
convention as the ``points/x_mm`` and ``points/y_mm`` datasets documented in
``SCAN_DATA_FORMAT.md``. The returned ``grid`` has shape
``(len(x_mm), len(y_mm))`` with ``grid[i, j]`` the value measured at
``(x_mm[i], y_mm[j])`` — X is axis 0 (rows), Y is axis 1 (columns). This
matches the ``arr[xi[x], yi[y]]`` convention used by every prior map
renderer in this codebase, so callers can drop this in without transposing.

NaN policy
----------
Every grid cell with no corresponding input point (never sampled — e.g. a
scan still in progress, or a genuinely partial/aborted raster) is ``NaN``.
Cells are *never* silently dropped or zero-filled: this function always
returns a rectangular grid covering the full outer product of the observed
x/y coordinates, and every gap is accounted for in
:attr:`ScanGridResult.n_missing`. A supplied *value* that is itself NaN
(e.g. an analysis quantity that failed for that point, such as a saturated
waveform with no valid rise time) is written through as NaN too, but is
counted separately in :attr:`ScanGridResult.n_nan_values` — "not sampled
yet" and "sampled but invalid" are different situations and this keeps them
distinguishable.

Point ordering
--------------
XY scans in this app walk a serpentine (boustrophedon) path — see
"Point ordering" in ``SCAN_DATA_FORMAT.md`` — so points must not be assumed
row-major, and a live viewer may call this function repeatedly with a
growing, arbitrarily-ordered, partial point set as a scan progresses. This
function makes no ordering assumption: axis values are derived from
``numpy.unique`` over the observed coordinates, so it is correct for
unordered, partial, and mid-scan-live inputs alike.

numpy<2: only ``numpy.unique``/``numpy.round``/``numpy.full``/``numpy.isnan``/
``numpy.count_nonzero`` are used — all stable across the numpy 1.x/2.x ABI
split, matching the project-wide ``numpy<2`` pin (see root ``CLAUDE.md``).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ScanGridResult:
    """Regular 2-D grid reconstructed from scattered scan points.

    Attributes
    ----------
    grid : ndarray, shape (len(x_mm), len(y_mm))
        Gridded values; f8. ``grid[i, j]`` corresponds to
        ``(x_mm[i], y_mm[j])``. Unsampled cells are NaN.
    x_mm, y_mm : ndarray
        Sorted, de-duplicated (post-rounding) grid axis coordinates, in mm.
    n_points : int
        Number of input points supplied (before de-duplication).
    n_unique_points : int
        Number of distinct rounded ``(x, y)`` cells that received a value —
        i.e. ``grid.size - n_missing``.
    n_duplicate_points : int
        ``n_points - n_unique_points``: input points that shared a rounded
        coordinate with an earlier point. Never dropped silently — the last
        one in input order wins (see module docstring / function docstring
        for why), and this count makes that explicit.
    n_missing : int
        Grid cells with no corresponding input point at all (``grid.size -
        n_unique_points``); NaN because they were never sampled.
    n_nan_values : int
        Of the ``n_points`` input values, how many were themselves NaN
        (sampled, but the value is invalid/missing) — a subset of what ends
        up NaN in the grid, counted separately from ``n_missing``.
    """

    grid: np.ndarray
    x_mm: np.ndarray
    y_mm: np.ndarray
    n_points: int
    n_unique_points: int
    n_duplicate_points: int
    n_missing: int
    n_nan_values: int


def points_to_grid(
    x_mm,
    y_mm,
    values,
    *,
    decimals: int = 6,
) -> ScanGridResult:
    """Bin scattered ``(x_mm, y_mm, value)`` points onto a regular 2-D grid.

    Parameters
    ----------
    x_mm, y_mm : array_like, shape (N,)
        Stage coordinates in millimetres, in any order — a live/mid-scan
        caller may pass a growing, unordered, partial set on every point.
    values : array_like, shape (N,)
        The quantity to grid at each point (e.g. ``dut_charge_pC``). May
        itself contain NaN (e.g. a failed per-point analysis); propagated
        to the grid as-is and counted in ``n_nan_values``.
    decimals : int, default 6
        Coordinates are rounded to this many decimal places before being
        treated as distinct grid-axis values, to absorb floating-point
        jitter from motor position readback (two nominally-identical
        positions rarely compare bit-exact). 6 decimals on millimetre
        coordinates is 1 nm resolution — far finer than any stage's
        mechanical repeatability — so genuinely distinct scan points are
        never merged. Matches the live map dict-key convention already used
        in ``gui/scan_panel.py`` / ``gui/scan_map_window.py``
        (``round(x, 6)``).

    Returns
    -------
    ScanGridResult

    Duplicate points
    -----------------
    If two input points round to the same ``(x, y)`` cell (a re-visited
    position, or a live scan re-emitting an updated value for a position
    already drawn), the *last* one in input order wins. This matches every
    existing map renderer's dict-overwrite behaviour and is the useful
    choice for a live view (a newer measurement should replace a stale one,
    not be discarded in favour of it). The overwrite is never silent:
    ``n_duplicate_points`` reports how many input points did not get their
    own cell.

    Raises
    ------
    ValueError
        If ``x_mm``, ``y_mm``, ``values`` don't all have the same length.
    """
    x = np.asarray(x_mm, dtype=float)
    y = np.asarray(y_mm, dtype=float)
    v = np.asarray(values, dtype=float)
    if not (x.shape == y.shape == v.shape):
        raise ValueError(
            "x_mm, y_mm, values must have the same shape; got "
            f"{x.shape}, {y.shape}, {v.shape}"
        )
    n_points = int(x.shape[0])

    xr = np.round(x, decimals)
    yr = np.round(y, decimals)

    xs = np.unique(xr)
    ys = np.unique(yr)
    nx, ny = len(xs), len(ys)

    xi = {val: i for i, val in enumerate(xs)}
    yi = {val: i for i, val in enumerate(ys)}

    grid = np.full((nx, ny), np.nan, dtype=float)
    filled_cells: set[tuple[int, int]] = set()
    for k in range(n_points):
        cell = (xi[xr[k]], yi[yr[k]])
        grid[cell] = v[k]
        filled_cells.add(cell)

    n_unique_points = len(filled_cells)
    n_duplicate_points = n_points - n_unique_points
    n_missing = nx * ny - n_unique_points
    n_nan_values = int(np.count_nonzero(np.isnan(v)))

    return ScanGridResult(
        grid=grid,
        x_mm=xs,
        y_mm=ys,
        n_points=n_points,
        n_unique_points=n_unique_points,
        n_duplicate_points=n_duplicate_points,
        n_missing=n_missing,
        n_nan_values=n_nan_values,
    )


def grid_extent(result: ScanGridResult) -> tuple[tuple[float, float], tuple[float, float]]:
    """``(pos, scale)`` for ``pyqtgraph.ImageView.setImage`` / ``ImageItem``.

    ``pos`` is the mm coordinate of ``grid[0, 0]``; ``scale`` is the
    ``(dx, dy)`` mm pixel pitch, estimated as the first-to-last span over the
    number of grid steps (assumes an approximately regular raster, true for
    XY scans in this app — see ``SCAN_DATA_FORMAT.md``). This is purely a
    rendering convenience so every map widget computes the same extent from
    a :class:`ScanGridResult` instead of re-deriving it inline (that
    duplication was one of the three near-identical implementations this
    module replaces).

    Falls back to a 1.0 mm/px pitch when a grid axis has fewer than 2
    points (no adjacent sample to measure a spacing from) or is empty — a
    display-only fallback; it does not affect ``grid``, ``x_mm``, or
    ``y_mm``.
    """
    xs, ys = result.x_mm, result.y_mm
    nx, ny = len(xs), len(ys)
    pos = (float(xs[0]), float(ys[0])) if nx and ny else (0.0, 0.0)
    dx = float((xs[-1] - xs[0]) / (nx - 1)) if nx > 1 else 1.0
    dy = float((ys[-1] - ys[0]) / (ny - 1)) if ny > 1 else 1.0
    return pos, (dx, dy)
