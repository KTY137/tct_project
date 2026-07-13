"""
Survey / mosaic **plan builder** — parametric camera raster over a rectangle.

:func:`plan_survey` builds a :class:`~controller.scan_plan.ScanPlan` that drives
the stage under the camera in a snake grid, grabbing one frame per tile
(``CAPTURE_PHOTO``).  It is the acquisition-side counterpart to the pure-math
stitcher: the tile centres come from :func:`analysis.mosaic_stitch.plan_grid`
(the single source of truth for snake order + overlap clamping), and the frames
this plan grabs are exactly what :func:`analysis.mosaic_stitch.place_tiles`
later stitches into one high-resolution mosaic.

Why a new module (not ``plan_from_config``)
-------------------------------------------
``controller.plan_from_config`` documents that it imports *only* the plan data
model (``controller.scan_plan``) and is narrowly a *classic-config → plan*
converter.  A survey is neither: it is a parametric grid builder that must import
``analysis.mosaic_stitch`` for the tile layout.  Folding it into
``plan_from_config`` would break that module's stated import purity, so the
survey builder lives here instead (``controller`` → ``analysis`` is an allowed
dependency — see ``tests/test_layer_contracts.py``).

Purity
------
Pure and hardware-free, like the rest of the plan layer: this module only builds
a :class:`ScanPlan` tree.  It never opens a camera, moves a stage, spawns a
thread, or touches a file.  The move→settle→grab loop that *drives* the compiled
plan into real tiles is a separate executor/plumbing beat.

Compiled shape (what the executor sees)
---------------------------------------
Each tile is expressed as nested single-value stage loops wrapping one
``CAPTURE_PHOTO`` action, so :func:`~controller.plan_compiler.compile_plan`
flattens the whole plan to a strict, snake-ordered sequence::

    MoveStep(x0, y0[, z]) , CapturePhotoStep(settle_s, label="<prefix>_r0_c0")
    MoveStep(x1, y1)      , CapturePhotoStep(settle_s, label="<prefix>_r0_c1")
    ...

* The MoveStep coordinates reproduce ``plan_grid``'s centre list *exactly*, in
  its snake (boustrophedon) order (verified in the tests).
* ``settle_s`` rides on the ``CAPTURE_PHOTO`` action itself (its pre-grab dwell,
  so the stage stops ringing before the frame) — it is NOT a loop settle, so no
  separate settle ``WaitStep`` is emitted.
* ``label`` encodes the tile's **spatial** grid position ``r{row}_c{col}``
  (row = Y index, col = X index), not merely its visit order — so a stitcher can
  address any tile by grid cell.
* ``z_mm`` (focus plane) is commanded **once**, folded into the first tile's
  MoveStep; every later move leaves ``z_mm`` ``None`` ("do not command").  A
  photo-only survey never re-focuses per tile.

Because the plan drives no bias, it emits no ``BIAS_V`` loop and needs no
``require_hv_confirmation`` (the validator agrees a camera-only plan needs no HV
confirmation).  Each ``CAPTURE_PHOTO`` still inherits B2's fail-closed gate:
the plan validates only when ``PlanLimits.camera_available`` is True, and is
rejected on paper when no camera is configured.

Metadata — what is stored, and where (read this, E6b)
-----------------------------------------------------
The plan model has no generic metadata field, so the survey geometry rides in a
namespaced, machine-readable ``safety["survey"]`` sub-dict (``safety`` is a
free-form dict; the validator/executor read only their own keys —
``require_hv_confirmation`` / ``bias_channel`` — and ignore this one).  It
round-trips through ``to_dict``/``from_dict``/YAML.  Schema::

    plan.safety["survey"] = {
        "area_mm":      [width_mm, height_mm],   # raster SIZE (not a rectangle)
        "fov_mm":       [fov_w_mm, fov_h_mm],
        "overlap_frac": <as requested; plan_grid re-clamps to [0.05, 0.5]>,
        "origin_mm":    [x0_mm, y0_mm],          # min-corner the raster starts at
        "rows":         <int>,   "cols": <int>,  # grid shape from plan_grid
        "z_mm":         <float or None>,         # focus plane, or None
    }

A downstream reader (e.g. E6b's mosaic view) rebuilds the exact snake-ordered
tile centres from this metadata alone::

    m = plan.safety["survey"]
    x0, y0 = m["origin_mm"];  w, h = m["area_mm"]
    centers, (rows, cols) = plan_grid((x0, y0, x0 + w, y0 + h),
                                      tuple(m["fov_mm"]), m["overlap_frac"])
    # frame i (camera/frame_point_index == i) was grabbed at centers[i].

KNOWN GAP (do NOT solve here — data-lane decision, queued for E6b / Jonathan)
----------------------------------------------------------------------------
A photo-only survey writes ``camera/frames`` + ``camera/frame_point_index`` but
leaves ``points/`` empty (there is no ACQUIRE/SAVE), so the **per-frame stage
position is not yet recorded in the run file**.  A writer-side position record
(e.g. a ``camera/frame_pos_mm`` dataset) is a ``data/`` decision, not this
builder's to make.  Until then the mosaic is *still fully reconstructable today*
from this ``safety["survey"]`` geometry + frame order: tile centres are
deterministic (``plan_grid`` above), and frames are grabbed in that same snake
order, so ``frame i → centers[i]`` recovers every tile's position without a
per-frame record.
"""
from __future__ import annotations

from analysis.mosaic_stitch import plan_grid
from controller.scan_plan import (
    ActionBlock,
    ActionType,
    Axis,
    LoopBlock,
    ScanPlan,
)

__all__ = ["plan_survey"]


def _fixed(axis: Axis, value: float, children: list) -> LoopBlock:
    """A degenerate single-value loop pinning *axis* at *value*.

    ``materialize`` returns ``[value]`` verbatim, so the compiler commands the
    axis exactly once at this coordinate — the clean, model-faithful way to
    express an absolute position (the plan model has no standalone "move" block;
    a move is implied by a leaf's enclosing loop coordinates).  Mirrors
    ``plan_from_config._fixed``.
    """
    return LoopBlock(axis=axis, values=[float(value)], children=children)


def _row_col(index: int, rows: int, cols: int) -> tuple[int, int]:
    """Map a flat snake-order tile *index* back to its spatial ``(row, col)``.

    :func:`analysis.mosaic_stitch.plan_grid` lays tiles out row-major with
    odd rows reversed (snake), so within-row visit position ``k`` maps to the
    spatial column ``k`` on even rows and ``cols-1-k`` on odd (reversed) rows.
    Row is always ``index // cols`` (visit order never reverses rows).  The
    returned pair is the tile's grid CELL, so ``label=..._r{row}_c{col}`` is a
    stable spatial address regardless of raster direction.
    """
    row = index // cols
    k = index % cols
    col = k if (row % 2 == 0) else (cols - 1 - k)
    return row, col


def plan_survey(
    area_mm: tuple[float, float],
    fov_mm: tuple[float, float],
    overlap_frac: float = 0.2,
    *,
    origin_mm: tuple[float, float] = (0.0, 0.0),
    settle_s: float = 0.1,
    label_prefix: str = "survey",
    z_mm: float | None = None,
) -> ScanPlan:
    """Build a snake-raster camera-survey :class:`ScanPlan` over a rectangle.

    Parameters
    ----------
    area_mm : (width_mm, height_mm)
        The raster SIZE to cover (not a rectangle) — the region spans
        ``origin_mm`` to ``origin_mm + area_mm``.  Must be non-negative on both
        axes; a size smaller than one ``fov_mm`` on both axes degenerates to a
        single centred tile.
    fov_mm : (width_mm, height_mm)
        The camera field of view at the working magnification — one tile's
        footprint.  Both entries must be strictly positive.
    overlap_frac : float, default 0.2
        Requested fractional overlap between adjacent tiles.  Passed straight to
        :func:`~analysis.mosaic_stitch.plan_grid`, which silently clamps it to
        ``[0.05, 0.5]`` — out-of-range values do NOT raise (clamp, don't fail).
    origin_mm : (x0_mm, y0_mm), keyword-only, default (0, 0)
        Stage mm position of the raster's minimum corner; every tile centre is
        offset by it.
    settle_s : float, keyword-only, default 0.1
        Per-tile pre-grab dwell (seconds, >= 0) carried on each ``CAPTURE_PHOTO``
        so the stage stops ringing before the frame.  Negative → ``ValueError``
        (fail-closed at build time).
    label_prefix : str, keyword-only, default "survey"
        Prefix for each tile's ``label`` (``f"{label_prefix}_r{row}_c{col}"``).
    z_mm : float or None, keyword-only, default None
        Optional focus-plane Z.  When set, Z is commanded ONCE (folded into the
        first tile's move); the raster never re-focuses per tile.  When None, Z
        is never commanded.

    Returns
    -------
    ScanPlan
        A camera-only plan (no bias, no waveform) whose compiled form is a
        snake-ordered ``MoveStep``+``CapturePhotoStep`` per tile.  Geometry for
        later reconstruction rides in ``safety["survey"]`` (see module docstring).

    Raises
    ------
    ValueError
        If ``fov_mm`` is not strictly positive, ``area_mm`` is negative on either
        axis (both surface as :func:`plan_grid`'s own ``ValueError``), or
        ``settle_s`` is negative.
    """
    if float(settle_s) < 0.0:
        raise ValueError(f"settle_s must be >= 0 (got {settle_s!r})")

    x0, y0 = float(origin_mm[0]), float(origin_mm[1])
    width, height = float(area_mm[0]), float(area_mm[1])

    # plan_grid is the single source of truth for the tile layout: snake order,
    # even spacing, overlap clamp, and the "area < fov -> one tile" degeneracy.
    # Folding origin_mm into the rectangle it receives is equivalent to offsetting
    # every returned centre (plan_grid is a translation-equivariant linspace),
    # and lets plan_grid do all input validation (positive fov, non-negative
    # extent) rather than duplicating — and risking drift from — those checks.
    rect = (x0, y0, x0 + width, y0 + height)
    centers_mm, (rows, cols) = plan_grid(rect, (float(fov_mm[0]), float(fov_mm[1])),
                                         float(overlap_frac))

    root: list = []
    for i, (cx, cy) in enumerate(centers_mm):
        row, col = _row_col(i, rows, cols)
        photo = ActionBlock(
            action=ActionType.CAPTURE_PHOTO,
            params={"settle_s": float(settle_s),
                    "label": f"{label_prefix}_r{row}_c{col}"},
        )
        # Nested single-value loops pin (x, y) at this tile; the compiler emits a
        # MoveStep-on-change to that coordinate, then the CapturePhotoStep.
        block: LoopBlock = _fixed(Axis.STAGE_X, cx, [_fixed(Axis.STAGE_Y, cy, [photo])])
        # Focus plane: command Z only on the FIRST tile (once at the start), so
        # exactly one compiled MoveStep carries z_mm and no tile re-focuses.
        if z_mm is not None and i == 0:
            block = _fixed(Axis.STAGE_Z, float(z_mm), [block])
        root.append(block)

    n_tiles = len(centers_mm)
    z_desc = f" at Z {float(z_mm):g} mm" if z_mm is not None else ""
    plan = ScanPlan(
        name=f"Camera survey {rows}x{cols}",
        description=(
            f"Snake raster of {n_tiles} camera tile(s) over a "
            f"{width:g}x{height:g} mm area (FOV {float(fov_mm[0]):g}x"
            f"{float(fov_mm[1]):g} mm, {float(overlap_frac):g} overlap) from "
            f"origin ({x0:g}, {y0:g}) mm{z_desc}. One CAPTURE_PHOTO per tile; "
            "no waveform/points written (photo-only survey)."
        ),
        root=root,
        # Machine-readable geometry for downstream mosaic reconstruction (E6b).
        # Lists (not tuples) so the dict is byte-stable across YAML round-trips.
        safety={"survey": {
            "area_mm": [width, height],
            "fov_mm": [float(fov_mm[0]), float(fov_mm[1])],
            "overlap_frac": float(overlap_frac),
            "origin_mm": [x0, y0],
            "rows": int(rows),
            "cols": int(cols),
            "z_mm": (None if z_mm is None else float(z_mm)),
        }},
    )
    return plan
