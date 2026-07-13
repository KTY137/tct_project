"""
1-D line-cut through a 2-D scan map — the "Measurement vs. axis" plot the
Analysis panel's map slicer draws (canonical edge-TCT depth profile: signal
vs. position along one axis, averaged over a strip of the other).

Starts from the same gridded array every map renderer already builds via
:func:`analysis.scan_grid.points_to_grid` — this module never re-derives the
grid itself, only reduces an existing ``ScanGridResult.grid`` (or any
``(x_mm, y_mm)``-indexed array following its axis convention) down to a 1-D
profile. Pure numpy; no Qt, no pyqtgraph — the GUI (``gui/analysis_panel.py``)
calls this and only this for the slice math (``.claude/AGENT_PROTOCOL.md`` —
named physics/derived-quantity code lives in ``analysis/``, panels call it).

Axis convention
----------------
Matches :mod:`analysis.scan_grid` exactly: ``grid`` has shape
``(len(x_mm), len(y_mm))`` with ``grid[i, j]`` the value at
``(x_mm[i], y_mm[j])`` — X is axis 0 (rows), Y is axis 1 (columns).

Orientation
-----------
``axis="x"`` — "profile vs. X": the cut *line* sits at a fixed **Y**
position (a horizontal line on the X/Y map) and the returned profile walks
the full X range at that Y (± an averaging band of neighbouring Y
rows/columns). ``axis="y"`` is the mirror: a fixed X position (a vertical
line on the map), profile walks Y, averaged over neighbouring X columns.
This is the "which axis do you want the profile plotted against" reading —
the GUI's X/Y toggle picks *this*, not the line's own screen angle (the
panel derives the perpendicular ``pg.InfiniteLine`` angle from it).

NaN policy
----------
Averaging uses :func:`numpy.nanmean` over the ± *width* window so a single
invalid sample inside the band doesn't blank the whole profile point; a
position whose *entire* window is NaN (never sampled, or every sample
invalid) stays NaN in the output — never dropped, never a fabricated 0 — and
never raises numpy's "Mean of empty slice" ``RuntimeWarning`` (this module
deliberately traps it: an all-NaN window is an expected, common case for a
partial/edge scan, not a program error worth a console warning per call).

Width clamping
---------------
The ± *width* averaging window is clamped at the grid edges (never wraps,
never indexes out of bounds) — a position near the edge of the map simply
gets a narrower band, which the caller can see by construction (band size is
always ``min(width, distance to edge)`` on each side; nothing here reports
the effective width back, since the map/band overlay drawn by the GUI is
itself the honest indicator of what was actually averaged).
"""
from __future__ import annotations

import warnings

import numpy as np

__all__ = [
    "mm_to_index", "slice_grid", "slice_grid_at_mm",
    "display_unit_scale", "strip_unit_suffix",
]


def mm_to_index(axis_values, position_mm: float) -> int:
    """Nearest grid-axis index to *position_mm*, clamped to a valid index.

    Parameters
    ----------
    axis_values : array_like, shape (N,)
        A grid axis vector (``ScanGridResult.x_mm`` or ``.y_mm``), in mm.
    position_mm : float
        A position along that axis, in mm — need not land exactly on a
        sampled coordinate (e.g. dragged from a pyqtgraph cut line).

    Returns
    -------
    int
        Index of the nearest entry in *axis_values*. Always in
        ``[0, len(axis_values) - 1]`` — an out-of-range *position_mm* (off
        either end of the scanned extent) clamps to the nearest edge index
        rather than raising, since ``argmin`` over absolute distance already
        picks the nearest end point.

    Raises
    ------
    ValueError
        If *axis_values* is empty.
    """
    axis = np.asarray(axis_values, dtype=float)
    if axis.size == 0:
        raise ValueError("axis_values must not be empty")
    return int(np.argmin(np.abs(axis - float(position_mm))))


def _nanmean_no_warn(sub: np.ndarray, axis: int) -> np.ndarray:
    """``numpy.nanmean(sub, axis=axis)`` with numpy's "Mean of empty slice"
    ``RuntimeWarning`` suppressed — an all-NaN window is an expected outcome
    here (see module docstring "NaN policy"), not a warning-worthy anomaly."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        return np.nanmean(sub, axis=axis)


def slice_grid(
    grid: np.ndarray,
    x_mm,
    y_mm,
    axis: str,
    index: int,
    width: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Reduce a 2-D scan grid to a 1-D profile along *axis*, at grid-index
    *index* on the perpendicular axis, averaged over a ± *width* band.

    Parameters
    ----------
    grid : ndarray, shape (len(x_mm), len(y_mm))
        A gridded map, e.g. ``ScanGridResult.grid`` — ``grid[i, j]`` is the
        value at ``(x_mm[i], y_mm[j])`` (see module docstring "Axis
        convention"). Unsampled cells are expected to be NaN.
    x_mm, y_mm : array_like
        The grid's own axis vectors (``ScanGridResult.x_mm`` / ``.y_mm``).
    axis : {"x", "y"}
        Which axis the returned profile walks — "x" holds Y fixed at
        *index* and profiles over X; "y" holds X fixed and profiles over Y
        (see module docstring "Orientation").
    index : int
        Grid index along the perpendicular (fixed) axis — resolve a mm
        position to this via :func:`mm_to_index` first, or use
        :func:`slice_grid_at_mm` to do both in one call. Clamped to a valid
        index (never raises for an out-of-range value).
    width : int, default 0
        Averaging half-width in grid steps: the band covers indices
        ``[index - width, index + width]`` on the fixed axis, clamped at the
        grid edges (see module docstring "Width clamping"). ``0`` = a bare
        single row/column, no averaging.

    Returns
    -------
    (positions_mm, values) : tuple[ndarray, ndarray]
        *positions_mm* is *x_mm* (axis="x") or *y_mm* (axis="y") — the free
        axis's coordinate vector, unchanged. *values* is the NaN-preserving
        mean over the band at each position, same length as *positions_mm*.

    Raises
    ------
    ValueError
        If *axis* is not ``"x"``/``"y"``, or *grid*'s shape does not match
        ``(len(x_mm), len(y_mm))``.
    """
    axis_key = str(axis).strip().lower()
    if axis_key not in ("x", "y"):
        raise ValueError(f"axis must be 'x' or 'y', got {axis!r}")

    g = np.asarray(grid, dtype=float)
    xs = np.asarray(x_mm, dtype=float)
    ys = np.asarray(y_mm, dtype=float)
    if g.shape != (xs.size, ys.size):
        raise ValueError(
            f"grid.shape {g.shape} does not match (len(x_mm), len(y_mm)) "
            f"= ({xs.size}, {ys.size})"
        )

    w = max(0, int(width))

    if axis_key == "x":
        # Fixed axis is Y (grid columns, axis 1); profile walks X.
        fixed_len = g.shape[1]
        idx = int(np.clip(int(index), 0, max(fixed_len - 1, 0)))
        lo, hi = max(0, idx - w), min(fixed_len, idx + w + 1)
        values = _nanmean_no_warn(g[:, lo:hi], axis=1)
        positions = xs.copy()
    else:
        # Fixed axis is X (grid rows, axis 0); profile walks Y.
        fixed_len = g.shape[0]
        idx = int(np.clip(int(index), 0, max(fixed_len - 1, 0)))
        lo, hi = max(0, idx - w), min(fixed_len, idx + w + 1)
        values = _nanmean_no_warn(g[lo:hi, :], axis=0)
        positions = ys.copy()

    return positions, values


def slice_grid_at_mm(
    grid: np.ndarray,
    x_mm,
    y_mm,
    axis: str,
    position_mm: float,
    width: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """:func:`slice_grid`, resolving *position_mm* (on the fixed axis) to a
    grid index via :func:`mm_to_index` first — the one call the GUI's
    position spin box / draggable cut line needs on every move."""
    axis_key = str(axis).strip().lower()
    if axis_key not in ("x", "y"):
        raise ValueError(f"axis must be 'x' or 'y', got {axis!r}")
    fixed_axis_values = y_mm if axis_key == "x" else x_mm
    index = mm_to_index(fixed_axis_values, position_mm)
    return slice_grid(grid, x_mm, y_mm, axis_key, index, width)


# Quantities displayed in a scaled unit on the slicer's OWN profile plot only
# — the map colorbar itself (gui/scan_map_view.py QUANTITY_UNITS) keeps the
# raw stored unit (pC) unchanged; this is purely a profile-plot display
# convention. Charge in this app is genuinely sub-pC (docs/design/
# council_v5_jonathan.md §4: "charge tiles in fC (x1000) everywhere a
# per-point/per-shot value is shown" — raw pC at a few decimals reads as
# near-zero for a typical sub-pC edge-TCT signal). Only "dut_charge_pC" is
# in gui/scan_map_view.py's QUANTITIES (the map's own selectable list) today
# — "ref_charge_pC" is a stored analysis column but not map-selectable, so
# it is deliberately not listed here (nothing would ever look it up).
_FEMTO_SCALED_QUANTITIES = {"dut_charge_pC"}


def display_unit_scale(quantity: str, native_unit: str) -> tuple[str, float]:
    """``(display_unit, multiplier)`` for the slicer profile plot's y-axis.

    Charge quantities are shown in femtocoulombs (``multiplier=1000.0``,
    ``display_unit="fC"``) — multiply the *native_unit* (pC) values by
    *multiplier* before plotting/exporting. Every other quantity passes
    through unscaled: ``(native_unit, 1.0)``.
    """
    if quantity in _FEMTO_SCALED_QUANTITIES:
        return "fC", 1000.0
    return native_unit, 1.0


def strip_unit_suffix(quantity: str, unit: str) -> str:
    """*quantity* with a trailing ``_<unit>`` removed, if present.

    Every :data:`~gui.scan_map_view.QUANTITIES` name already spells out its
    own native unit (``"dut_charge_pC"``, ``"drift_time_s"``, ...). A caller
    about to label an axis/column with a (possibly *different*, see
    :func:`display_unit_scale`) unit of its own should build the label from
    this stripped base, or the result doubles up — e.g. an axis reading
    ``"dut_charge_pC (fC)"``, or a CSV header ``dut_charge_pC_fC`` — instead
    of the intended ``"dut_charge (fC)"`` / ``dut_charge_fC``.

    A *quantity* that does not end in ``_<unit>`` (or an empty *unit*, e.g.
    the dimensionless ``dut_charge_norm``) is returned unchanged.
    """
    suffix = f"_{unit}"
    if unit and quantity.endswith(suffix):
        return quantity[: -len(suffix)]
    return quantity
