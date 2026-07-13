"""Tests for controller.survey_plan.plan_survey — the camera-survey plan builder.

Covers the brief's matrix: grid geometry + snake order (compiled MoveStep
sequence == plan_grid centres), overlap-clamp passthrough, compile+validate with
and without a camera (inherits B2's fail-closed gate), estimate charges every
grab, focus-plane Z commanded once at the start, spatially-correct r/c labels,
YAML/dict round-trip of the built plan (incl. the safety["survey"] metadata),
the degenerate area < FOV single-tile case, and fail-closed on bad inputs.
"""
from __future__ import annotations

import pytest

from analysis.mosaic_stitch import plan_grid
from controller.survey_plan import plan_survey
from controller.scan_plan import ScanPlan
from controller.plan_compiler import (
    compile_plan, MoveStep, CapturePhotoStep, WaitStep,
)
from controller.plan_estimate import estimate_plan, Sizing, CAMERA_GRAB_S
from controller.scan_plan_validator import (
    PlanLimits, validate_plan, errors, warnings,
)


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #

# A reference survey used by many tests: area 26x18 mm, 10x10 mm FOV, 20%
# overlap -> a 2x3 snake grid (matches test_mosaic_stitch's pinned example).
AREA = (26.0, 18.0)
FOV = (10.0, 10.0)
OVERLAP = 0.2


def _limits(**over) -> PlanLimits:
    """Wide software limits so the reference survey's centres are all in bounds
    (mirrors tests/test_scan_plan_validator.limits)."""
    d = dict(
        x_min_mm=-100.0, x_max_mm=200.0,
        y_min_mm=-100.0, y_max_mm=200.0,
        z_min_mm=-10.0, z_max_mm=10.0,
        voltage_range_V=1000.0, max_points=1_000_000,
    )
    d.update(over)
    return PlanLimits(**d)


def _moves(plan) -> list[MoveStep]:
    return [s for s in compile_plan(plan) if isinstance(s, MoveStep)]


def _photos(plan) -> list[CapturePhotoStep]:
    return [s for s in compile_plan(plan) if isinstance(s, CapturePhotoStep)]


def _grid(origin=(0.0, 0.0), overlap=OVERLAP):
    """plan_grid over the reference area at *origin* (absolute rectangle)."""
    ox, oy = origin
    rect = (ox, oy, ox + AREA[0], oy + AREA[1])
    return plan_grid(rect, FOV, overlap)


# --------------------------------------------------------------------------- #
# grid geometry + snake order                                                 #
# --------------------------------------------------------------------------- #

def test_move_sequence_matches_plan_grid_centers():
    """The compiled MoveStep sequence reproduces plan_grid's snake-ordered
    centres exactly, one per tile."""
    plan = plan_survey(AREA, FOV, OVERLAP)
    centers, (rows, cols) = _grid()
    moves = _moves(plan)
    assert len(moves) == len(centers) == rows * cols
    for m, (cx, cy) in zip(moves, centers):
        assert m.x_mm == pytest.approx(cx)
        assert m.y_mm == pytest.approx(cy)
        assert m.z_mm is None            # no focus plane in this call


def test_compiled_steps_are_move_photo_pairs_only():
    """Every tile compiles to exactly one MoveStep then one CapturePhotoStep —
    nothing else (settle rides on the photo, so no settle WaitStep)."""
    plan = plan_survey(AREA, FOV, OVERLAP)
    steps = compile_plan(plan)
    kinds = [type(s).__name__ for s in steps]
    n = len(kinds) // 2
    assert kinds[0::2] == ["MoveStep"] * n
    assert kinds[1::2] == ["CapturePhotoStep"] * n
    assert not any(isinstance(s, WaitStep) for s in steps)


def test_settle_rides_on_capture_photo_step():
    plan = plan_survey(AREA, FOV, OVERLAP, settle_s=0.3)
    photos = _photos(plan)
    assert photos
    assert all(p.settle_s == pytest.approx(0.3) for p in photos)


def test_origin_offsets_every_center():
    plan = plan_survey(AREA, FOV, OVERLAP, origin_mm=(100.0, 50.0))
    centers, _ = _grid(origin=(100.0, 50.0))
    moves = _moves(plan)
    assert len(moves) == len(centers)
    for m, (cx, cy) in zip(moves, centers):
        assert m.x_mm == pytest.approx(cx)
        assert m.y_mm == pytest.approx(cy)


# --------------------------------------------------------------------------- #
# overlap clamp passthrough                                                    #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("overlap", [0.9, -0.5])
def test_overlap_clamped_like_plan_grid(overlap):
    """Out-of-range overlap does not raise: it is passed through and plan_grid
    clamps it to [0.05, 0.5].  The survey's centres therefore match plan_grid
    called with the SAME out-of-range value."""
    plan = plan_survey(AREA, FOV, overlap)
    centers, _ = _grid(overlap=overlap)   # plan_grid clamps internally
    moves = _moves(plan)
    assert len(moves) == len(centers)
    for m, (cx, cy) in zip(moves, centers):
        assert m.x_mm == pytest.approx(cx)
        assert m.y_mm == pytest.approx(cy)


# --------------------------------------------------------------------------- #
# compile + validate matrix (B2's fail-closed camera gate)                    #
# --------------------------------------------------------------------------- #

def test_compiles_and_validates_with_camera():
    plan = plan_survey(AREA, FOV, OVERLAP)
    assert compile_plan(plan)                      # compiles without raising
    assert errors(validate_plan(plan, _limits(camera_available=True))) == []


def test_fails_validation_without_camera():
    """Inherits B2: a CAPTURE_PHOTO plan is an ERROR when no camera is
    configured/available (fail-closed, refused on paper)."""
    errs = errors(validate_plan(plan_survey(AREA, FOV, OVERLAP),
                                _limits(camera_available=False)))
    assert errs
    assert all("CAPTURE_PHOTO" in e and "camera" in e for e in errs)


def test_default_limits_reject_survey():
    """PlanLimits defaults camera_available False -> an un-wired caller can never
    accidentally admit a camera-less survey."""
    errs = errors(validate_plan(plan_survey(AREA, FOV, OVERLAP), _limits()))
    assert any("camera" in e for e in errs)


def test_survey_drives_no_bias_and_needs_no_hv_confirmation():
    plan = plan_survey(AREA, FOV, OVERLAP)
    assert "require_hv_confirmation" not in plan.safety
    assert errors(validate_plan(plan, _limits(camera_available=True))) == []


def test_clean_survey_has_no_unknown_param_warnings():
    """settle_s / label are known CAPTURE_PHOTO params -> no typo warnings."""
    issues = validate_plan(plan_survey(AREA, FOV, OVERLAP),
                           _limits(camera_available=True))
    assert not any("unknown param" in w for w in warnings(issues))


# --------------------------------------------------------------------------- #
# estimate includes every grab                                                #
# --------------------------------------------------------------------------- #

def test_estimate_counts_all_grabs():
    plan = plan_survey(AREA, FOV, OVERLAP, settle_s=0.3)
    centers, _ = _grid()
    n = len(centers)
    est = estimate_plan(plan)
    # One point / one leaf visit / one frame per tile.
    assert est.total_points == n
    assert est.total_leaf_visits == n
    # Photo-only survey: data is exactly n conservative full frames, no SaveStep.
    assert est.est_data_bytes == n * Sizing().camera_frame_bytes
    # Runtime includes at least each tile's (settle + grab); travel is extra.
    assert est.est_runtime_s >= n * (0.3 + CAMERA_GRAB_S)


# --------------------------------------------------------------------------- #
# focus-plane Z: commanded once at the start, never per tile                  #
# --------------------------------------------------------------------------- #

def test_z_plane_commanded_once_at_start():
    plan = plan_survey(AREA, FOV, OVERLAP, z_mm=5.0)
    moves = _moves(plan)
    assert moves[0].z_mm == pytest.approx(5.0)
    assert all(m.z_mm is None for m in moves[1:])
    assert sum(1 for m in moves if m.z_mm is not None) == 1
    # Z within limits -> still validates clean.
    assert errors(validate_plan(plan, _limits(camera_available=True))) == []


def test_no_z_command_when_z_none():
    moves = _moves(plan_survey(AREA, FOV, OVERLAP))    # z_mm defaults None
    assert moves
    assert all(m.z_mm is None for m in moves)


# --------------------------------------------------------------------------- #
# labels encode the spatial (row, col) grid cell                              #
# --------------------------------------------------------------------------- #

def test_labels_encode_spatial_row_col():
    """Each photo's label is r{row}_c{col} for the tile's spatial grid cell —
    derived independently here from the sorted unique X/Y centre coordinates."""
    plan = plan_survey(AREA, FOV, OVERLAP)
    centers, (rows, cols) = _grid()
    xs = sorted({round(x, 6) for x, _ in centers})
    ys = sorted({round(y, 6) for _, y in centers})
    photos = _photos(plan)
    assert len(photos) == len(centers)
    for photo, (cx, cy) in zip(photos, centers):
        exp_col = xs.index(round(cx, 6))
        exp_row = ys.index(round(cy, 6))
        assert photo.label == f"survey_r{exp_row}_c{exp_col}"


def test_labels_match_pinned_snake_order():
    """Pin the exact labels for the 2x3 snake example (row 1 walks right->left)."""
    photos = _photos(plan_survey(AREA, FOV, OVERLAP))
    labels = [p.label for p in photos]
    assert labels == [
        "survey_r0_c0", "survey_r0_c1", "survey_r0_c2",   # row 0: left -> right
        "survey_r1_c2", "survey_r1_c1", "survey_r1_c0",   # row 1: right -> left
    ]


def test_label_prefix_is_used():
    photos = _photos(plan_survey(AREA, FOV, OVERLAP, label_prefix="mymap"))
    assert photos[0].label == "mymap_r0_c0"
    assert all(p.label.startswith("mymap_r") for p in photos)


# --------------------------------------------------------------------------- #
# metadata: geometry stored for reconstruction, and round-trips               #
# --------------------------------------------------------------------------- #

def test_metadata_records_geometry():
    plan = plan_survey(AREA, FOV, OVERLAP, origin_mm=(1.0, 2.0), z_mm=3.0)
    m = plan.safety["survey"]
    assert m["area_mm"] == [26.0, 18.0]
    assert m["fov_mm"] == [10.0, 10.0]
    assert m["overlap_frac"] == pytest.approx(0.2)
    assert m["origin_mm"] == [1.0, 2.0]
    assert m["z_mm"] == pytest.approx(3.0)
    _, (rows, cols) = _grid(origin=(1.0, 2.0))
    assert (m["rows"], m["cols"]) == (rows, cols)


def test_metadata_z_none_when_unset():
    assert plan_survey(AREA, FOV, OVERLAP).safety["survey"]["z_mm"] is None


def test_metadata_lets_downstream_rebuild_centers():
    """The E6b reconstruction path: rebuild the exact tile centres from the
    stored geometry alone and confirm they match the compiled moves (frame i is
    grabbed at centers[i])."""
    plan = plan_survey(AREA, FOV, OVERLAP, origin_mm=(4.0, -3.0))
    m = plan.safety["survey"]
    ox, oy = m["origin_mm"]
    w, h = m["area_mm"]
    centers, _ = plan_grid((ox, oy, ox + w, oy + h),
                           tuple(m["fov_mm"]), m["overlap_frac"])
    moves = _moves(plan)
    assert len(moves) == len(centers)
    for mv, (cx, cy) in zip(moves, centers):
        assert mv.x_mm == pytest.approx(cx)
        assert mv.y_mm == pytest.approx(cy)


def test_dict_and_yaml_round_trip_unchanged():
    plan = plan_survey(AREA, FOV, OVERLAP, origin_mm=(1.0, 2.0),
                       z_mm=3.0, settle_s=0.15, label_prefix="s")
    d = plan.to_dict()
    assert ScanPlan.from_dict(d).to_dict() == d
    assert ScanPlan.from_yaml(plan.to_yaml()).to_dict() == d
    # the survey metadata specifically survives the YAML trip
    assert ScanPlan.from_yaml(plan.to_yaml()).safety["survey"] == d["safety"]["survey"]


# --------------------------------------------------------------------------- #
# degenerate: area smaller than one FOV -> a single centred tile              #
# --------------------------------------------------------------------------- #

def test_area_smaller_than_fov_is_single_tile():
    plan = plan_survey((5.0, 5.0), (10.0, 10.0), OVERLAP)
    moves = _moves(plan)
    photos = _photos(plan)
    assert len(moves) == 1 and len(photos) == 1
    # single tile centred on the area centre (origin 0 + size/2).
    assert moves[0].x_mm == pytest.approx(2.5)
    assert moves[0].y_mm == pytest.approx(2.5)
    assert photos[0].label == "survey_r0_c0"
    m = plan.safety["survey"]
    assert (m["rows"], m["cols"]) == (1, 1)
    # and it still validates (with a camera).
    assert errors(validate_plan(plan, _limits(camera_available=True))) == []


# --------------------------------------------------------------------------- #
# fail-closed on invalid inputs                                               #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("fov", [(-10.0, 10.0), (10.0, 0.0), (0.0, 0.0)])
def test_non_positive_fov_raises(fov):
    with pytest.raises(ValueError):
        plan_survey(AREA, fov, OVERLAP)


@pytest.mark.parametrize("area", [(-26.0, 18.0), (26.0, -18.0)])
def test_negative_area_raises(area):
    with pytest.raises(ValueError):
        plan_survey(area, FOV, OVERLAP)


def test_negative_settle_raises():
    with pytest.raises(ValueError):
        plan_survey(AREA, FOV, OVERLAP, settle_s=-0.1)
