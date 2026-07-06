"""Tests for controller.plan_estimate.estimate_plan.

Known plan -> exact points/leaf counts and runtime/data; runtime & data grow
monotonically with work; a serpentine plan travels strictly less than the raster
version; and the HV range is reported correctly.
"""
import pytest

from controller.scan_plan import (
    ActionBlock, ActionType, Axis, LoopBlock, ScanPlan,
)
from controller.plan_estimate import estimate_plan, PlanEstimate, Timing, Sizing


def _acq(**p):
    return ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params=p)


def _save():
    return ActionBlock(action=ActionType.SAVE_POINT, params={})


def simple_plan():
    """bias[-50] x x[0,10], acquire+save -> 2 points, 4 leaf visits."""
    x = LoopBlock(axis=Axis.STAGE_X, values=[0.0, 10.0], children=[_acq(), _save()])
    b = LoopBlock(axis=Axis.BIAS_V, values=[-50.0], children=[x])
    return ScanPlan(root=[b], safety={"require_hv_confirmation": True})


def raster_plan(snake: bool):
    y = LoopBlock(axis=Axis.STAGE_Y, values=[0.0, 1.0], snake=snake,
                  children=[_acq(), _save()])
    x = LoopBlock(axis=Axis.STAGE_X, values=[0.0, 1.0], children=[y])
    b = LoopBlock(axis=Axis.BIAS_V, values=[-10.0, -20.0], children=[x])
    return ScanPlan(root=[b], safety={"require_hv_confirmation": True})


def test_counts_are_exact():
    est = estimate_plan(simple_plan())
    assert est.total_points == 2
    assert est.total_leaf_visits == 4


def test_runtime_and_data_are_exact_with_default_models():
    est = estimate_plan(simple_plan(), Timing(), Sizing())
    # Bias 0->-50: (50/5)*0.1 + 1.0 = 2.0 ; first move free ; move 0->10:
    # 10/25 = 0.4 (no settle: the x loop sets no settle_s) ; two acquires:
    # 2*(1*0.02)=0.04
    assert est.est_runtime_s == pytest.approx(2.0 + 0.4 + 0.04)
    # 2 saves * (2ch*1024*4 + 16*8) = 2 * 8320
    assert est.est_data_bytes == 2 * (2 * 1024 * 4 + 16 * 8)
    assert est.stage_travel_mm == {"x": 10.0, "y": 0.0, "z": 0.0}
    assert est.hv_range_V == (-50.0, -50.0)


def test_hv_range_spans_min_max():
    est = estimate_plan(raster_plan(snake=False))
    assert est.hv_range_V == (-20.0, -10.0)


def test_no_bias_plan_reports_zero_hv_range():
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0, 1.0], children=[_acq(), _save()])
    est = estimate_plan(ScanPlan(root=[loop]))
    assert est.hv_range_V == (0.0, 0.0)


def test_snake_travels_less_than_raster():
    snake = estimate_plan(raster_plan(snake=True))
    raster = estimate_plan(raster_plan(snake=False))
    assert sum(snake.stage_travel_mm.values()) < sum(raster.stage_travel_mm.values())
    # runtime follows travel (fewer/shorter moves), counts are identical
    assert snake.est_runtime_s < raster.est_runtime_s
    assert snake.total_leaf_visits == raster.total_leaf_visits


def test_runtime_monotonic_in_averages():
    def plan(navg):
        loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0, 1.0],
                         children=[_acq(n_averages=navg), _save()])
        return ScanPlan(root=[loop])
    assert estimate_plan(plan(64)).est_runtime_s > estimate_plan(plan(1)).est_runtime_s


def test_data_monotonic_in_points():
    def plan(n):
        loop = LoopBlock(axis=Axis.STAGE_X, values=[float(i) for i in range(n)],
                         children=[_acq(), _save()])
        return ScanPlan(root=[loop])
    assert estimate_plan(plan(10)).est_data_bytes > estimate_plan(plan(3)).est_data_bytes


def test_wait_step_adds_to_runtime():
    base = LoopBlock(axis=Axis.STAGE_X, values=[0.0], children=[_acq(), _save()])
    waited = LoopBlock(axis=Axis.STAGE_X, values=[0.0], children=[
        _acq(), _save(), ActionBlock(action=ActionType.WAIT, params={"seconds": 7.0}),
    ])
    r0 = estimate_plan(ScanPlan(root=[base])).est_runtime_s
    r1 = estimate_plan(ScanPlan(root=[waited])).est_runtime_s
    assert r1 == pytest.approx(r0 + 7.0)


def test_loop_settle_adds_to_runtime_estimate():
    """Regression (BUG): loop settle_s reaches the runtime via emitted settle
    WaitSteps (one per move), not a hard-coded per-move constant."""
    base = LoopBlock(axis=Axis.STAGE_X, values=[0.0, 1.0],
                     children=[_acq(), _save()])
    settled = LoopBlock(axis=Axis.STAGE_X, values=[0.0, 1.0], settle_s=0.5,
                        children=[_acq(), _save()])
    r0 = estimate_plan(ScanPlan(root=[base])).est_runtime_s
    r1 = estimate_plan(ScanPlan(root=[settled])).est_runtime_s
    # two coordinates -> two moves -> two settle waits of 0.5 s
    assert r1 == pytest.approx(r0 + 2 * 0.5)


def test_manual_pause_adds_warning_not_runtime():
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0], children=[
        ActionBlock(action=ActionType.MANUAL_PAUSE, params={"prompt": "swap"}),
    ])
    est = estimate_plan(ScanPlan(root=[loop]))
    assert any("manual pause" in w for w in est.warnings)


def test_estimate_is_frozen_dataclass():
    import dataclasses
    est = estimate_plan(simple_plan())
    assert isinstance(est, PlanEstimate)
    with pytest.raises(dataclasses.FrozenInstanceError):
        est.est_runtime_s = 0.0


def test_custom_timing_scales_runtime():
    fast = estimate_plan(simple_plan(), Timing(motor_speed_mm_s=1000.0))
    slow = estimate_plan(simple_plan(), Timing(motor_speed_mm_s=1.0))
    assert slow.est_runtime_s > fast.est_runtime_s
