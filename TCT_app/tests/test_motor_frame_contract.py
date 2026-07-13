"""Coordinate-frame contract between the motor driver, the Scan Planner, and
the pre-flight validator.

Live bug (Kaya, Marlin stage): after the motor panel's "Zero Here" the Scan
Planner did not adopt the new origin and immediately complained about soft
limits.  Root cause: planner loop coordinates and ``set_position_from_motor``
live in the driver's USER frame (``get_position``/``move_to``), but the
validator's ``PlanLimits`` were built from ``motor.limits`` in the MACHINE
frame — so a plan built around a fresh Zero-Here origin was checked against
bounds it never shared.

Contract pinned here: the validator's stage bounds are the machine soft limits
expressed in the SAME user frame the plan lives in — ``motor.limits_user_frame()``
— which tracks the active ``zero_position`` offset.  The translation only
SHIFTS the envelope, never widens it, so a plan exceeding real machine travel
is still rejected (equivalent to the per-move gate ``move_to`` enforces).
"""
from __future__ import annotations

import pytest

from devices.motor_grbl import GRBLMotorStage
from devices.motor_simulated import SimulatedMotorStage
from devices.motor_base import SoftwareLimits, MotorLimitError
from controller.scan_plan import (
    ActionBlock, ActionType, Axis, LoopBlock, ScanPlan,
)
from controller.scan_plan_validator import PlanLimits, validate_plan, errors


# Kaya's stage envelope (machine frame): x 1..296, y 0..298, z 0..50.
_MACHINE_LIMITS = SoftwareLimits(
    x_min=1.0, x_max=296.0, y_min=0.0, y_max=298.0, z_min=0.0, z_max=50.0,
)


def _plan_limits_from(lim: SoftwareLimits) -> PlanLimits:
    """Mirror tct_gui._plan_limits' SoftwareLimits -> PlanLimits mapping."""
    return PlanLimits(
        x_min_mm=lim.x_min, x_max_mm=lim.x_max,
        y_min_mm=lim.y_min, y_max_mm=lim.y_max,
        z_min_mm=lim.z_min, z_max_mm=lim.z_max,
        voltage_range_V=3000.0, max_points=250_000,
    )


def _stage_plan(axis: Axis, values: list[float]) -> ScanPlan:
    loop = LoopBlock(
        axis=axis, values=list(values),
        children=[
            ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params={"n_averages": 4}),
            ActionBlock(action=ActionType.SAVE_POINT, params={}),
        ],
    )
    return ScanPlan(name="t", root=[loop])


def _zeroed_stage(machine_pos: tuple[float, float, float]) -> GRBLMotorStage:
    """A simulated GRBL stage homed then Zero-Here'd at *machine_pos*.

    Places the machine position via a user-frame move (the app-facing path),
    then declares it the origin, so get_position() reads (0, 0, 0) afterwards.
    """
    motor = GRBLMotorStage(simulation=True)
    motor.limits = _MACHINE_LIMITS
    motor.connect()
    motor.home()                       # sim: homed + centered, _zero back to None
    # Drive to the requested machine position through the user frame, then zero.
    off = motor._offset()              # default lower-corner offset (no _zero yet)
    mx, my, mz = machine_pos
    motor.move_to(mx - off.x_mm, my - off.y_mm, mz - off.z_mm)
    motor.zero_position()              # _zero := current machine position
    return motor


# --------------------------------------------------------------------------- #
# Core reproduction: Zero Here -> plan around new origin -> validator verdict  #
# --------------------------------------------------------------------------- #

def test_zero_here_reports_new_origin_as_zero():
    motor = _zeroed_stage((150.0, 150.0, 25.0))
    pos = motor.get_position()
    assert pos.x_mm == pytest.approx(0.0)
    assert pos.y_mm == pytest.approx(0.0)
    assert pos.z_mm == pytest.approx(0.0)


def test_plan_around_zero_here_origin_validates_clean():
    """The bug: a plan built around the Zero-Here origin (0..10 mm) must pass."""
    motor = _zeroed_stage((150.0, 150.0, 25.0))
    user_limits = _plan_limits_from(motor.limits_user_frame())

    plan = _stage_plan(Axis.STAGE_X, [0.0, 5.0, 10.0])
    assert errors(validate_plan(plan, user_limits)) == []

    # And the machine coordinate each user set-point maps to is genuinely in
    # range — the driver accepts the same moves the validator passed.
    for u in (0.0, 5.0, 10.0):
        motor.move_to(u, 0.0, 0.0)     # no MotorLimitError == in machine range


def test_machine_frame_limits_would_have_wrongly_rejected_origin_plan():
    """Pin the actual defect: using raw machine-frame limits (the pre-fix
    behaviour) flags the Zero-Here origin plan on soft limits."""
    motor = _zeroed_stage((150.0, 150.0, 25.0))
    machine_limits = _plan_limits_from(motor.limits)   # WRONG frame (the bug)

    plan = _stage_plan(Axis.STAGE_X, [0.0, 5.0, 10.0])
    errs = errors(validate_plan(plan, machine_limits))
    assert errs, "machine-frame limits should (wrongly) reject the origin plan"
    assert "software limits" in errs[0]


# --------------------------------------------------------------------------- #
# Safety: the translation never widens the envelope                           #
# --------------------------------------------------------------------------- #

def test_plan_exceeding_real_travel_still_rejected_after_zero():
    """A plan that would exceed REAL machine travel must still fail, even
    expressed in the shifted user frame — validation must not get weaker."""
    motor = _zeroed_stage((150.0, 150.0, 25.0))
    user_limits = _plan_limits_from(motor.limits_user_frame())

    # user x=200 -> machine 350 > x_max 296: out of travel.
    plan = _stage_plan(Axis.STAGE_X, [0.0, 200.0])
    assert errors(validate_plan(plan, user_limits)), "over-travel plan must be rejected"

    # The driver's own per-move gate agrees (ground-truth machine-frame check).
    with pytest.raises(MotorLimitError):
        motor.move_to(200.0, 0.0, 0.0)


def test_user_frame_bound_equals_machine_gate_exactly():
    """Equivalence invariant: user coord u passes limits_user_frame iff its
    machine coord (u + offset) passes the driver's machine-frame limits."""
    motor = _zeroed_stage((150.0, 150.0, 25.0))
    ulim = motor.limits_user_frame()
    off = motor._offset()

    # x_max in the user frame maps exactly to the machine x_max — the boundary
    # is preserved, not shifted open.
    assert ulim.x_max + off.x_mm == pytest.approx(_MACHINE_LIMITS.x_max)
    assert ulim.x_min + off.x_mm == pytest.approx(_MACHINE_LIMITS.x_min)
    assert ulim.y_max + off.y_mm == pytest.approx(_MACHINE_LIMITS.y_max)
    assert ulim.z_min + off.z_mm == pytest.approx(_MACHINE_LIMITS.z_min)


def test_default_offset_frame_also_translated_before_zero():
    """Even without Zero Here, the default offset is the lower-limit corner,
    so the user frame starts at 0 — limits_user_frame reflects that."""
    motor = GRBLMotorStage(simulation=True)
    motor.limits = _MACHINE_LIMITS
    motor.connect()
    motor.home()
    ulim = motor.limits_user_frame()
    # Default offset = (x_min, y_min, z_min) -> user lower corner is 0.
    assert ulim.x_min == pytest.approx(0.0)
    assert ulim.y_min == pytest.approx(0.0)
    assert ulim.x_max == pytest.approx(_MACHINE_LIMITS.x_max - _MACHINE_LIMITS.x_min)


# --------------------------------------------------------------------------- #
# Base default: backends with no user/machine split return limits unchanged   #
# --------------------------------------------------------------------------- #

def test_base_default_limits_user_frame_is_identity():
    motor = SimulatedMotorStage(simulation=True)
    motor.limits = _MACHINE_LIMITS
    assert motor.limits_user_frame() is motor.limits
