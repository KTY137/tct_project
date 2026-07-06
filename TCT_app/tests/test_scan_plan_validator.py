"""Tests for controller.scan_plan_validator — the fail-closed plan pre-flight.

Covers the required cases: stage-limit breach, max_points cap, HV plan without
require_hv_confirmation (fail-closed), bias out of range, a broken loop range
reported (not crashed), and a clean plan with no errors — plus the semantic and
branch checks.
"""
from controller.scan_plan import (
    ActionBlock, ActionType, Axis, LoopBlock, ScanPlan,
)
from controller.scan_plan_validator import (
    PlanIssue, PlanLimits, validate_plan, errors, warnings, ERROR, WARNING,
)


# --------------------------------------------------------------------------- #
# builders                                                                     #
# --------------------------------------------------------------------------- #

def limits(**over) -> PlanLimits:
    d = dict(
        x_min_mm=-50.0, x_max_mm=50.0,
        y_min_mm=-50.0, y_max_mm=50.0,
        z_min_mm=-10.0, z_max_mm=10.0,
        voltage_range_V=1000.0, max_points=1_000_000,
    )
    d.update(over)
    return PlanLimits(**d)


def _acq(**params):
    return ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params=params)


def _save(**params):
    return ActionBlock(action=ActionType.SAVE_POINT, params=params)


def stage_plan(axis, values, **loop_kw):
    """A minimal stage-only plan: one loop over *axis* with acquire+save."""
    loop = LoopBlock(axis=axis, values=list(values),
                     children=[_acq(), _save()], **loop_kw)
    return ScanPlan(name="t", root=[loop])


def bias_plan(values, confirm=True):
    loop = LoopBlock(axis=Axis.BIAS_V, values=list(values),
                     children=[_acq(), _save()])
    safety = {"require_hv_confirmation": True} if confirm else {}
    return ScanPlan(name="t", root=[loop], safety=safety)


# --------------------------------------------------------------------------- #
# required cases                                                               #
# --------------------------------------------------------------------------- #

def test_clean_plan_has_no_errors():
    plan = stage_plan(Axis.STAGE_X, [-10.0, 0.0, 10.0])
    issues = validate_plan(plan, limits())
    assert errors(issues) == []


def test_stage_limit_breach_is_error():
    plan = stage_plan(Axis.STAGE_X, [0.0, 100.0])  # 100 > x_max 50
    errs = errors(validate_plan(plan, limits()))
    assert any("stage_x" in e and "software limits" in e for e in errs)


def test_stage_limit_breach_z_axis():
    plan = stage_plan(Axis.STAGE_Z, [0.0, 25.0])   # 25 > z_max 10
    assert any("stage_z" in e for e in errors(validate_plan(plan, limits())))


def test_max_points_cap_is_error():
    plan = stage_plan(Axis.STAGE_X, list(range(20)))  # 20 pts * 2 actions = 40
    errs = errors(validate_plan(plan, limits(max_points=10)))
    assert any("max_points" in e for e in errs)


def test_hv_plan_without_confirmation_is_error():
    """Fail-closed: any bias-driving plan must set require_hv_confirmation."""
    plan = bias_plan([-50.0], confirm=False)
    errs = errors(validate_plan(plan, limits()))
    assert any("require_hv_confirmation" in e for e in errs)


def test_hv_plan_with_confirmation_ok():
    plan = bias_plan([-50.0], confirm=True)
    errs = errors(validate_plan(plan, limits()))
    assert not any("require_hv_confirmation" in e for e in errs)


def test_validate_plan_tolerates_safety_none():
    """ScanPlan(safety=None) must not crash the HV-confirmation guard — it is
    treated as an empty (fail-closed) safety mapping."""
    loop = LoopBlock(axis=Axis.BIAS_V, values=[-50.0], children=[_acq(), _save()])
    plan = ScanPlan(root=[loop], safety=None)
    issues = validate_plan(plan, limits())          # must not raise
    assert any("require_hv_confirmation" in e for e in errors(issues))


def test_bias_out_of_range_is_error():
    plan = bias_plan([-2000.0], confirm=True)      # |V| 2000 > 1000
    errs = errors(validate_plan(plan, limits()))
    assert any("voltage_range_V" in e for e in errs)


def test_bad_range_is_error_not_crash():
    """A zero-step range makes materialize() raise — validator must report,
    never propagate."""
    loop = LoopBlock(axis=Axis.STAGE_X, start=0.0, stop=10.0, step=0.0,
                     children=[_acq(), _save()])
    plan = ScanPlan(root=[loop])
    issues = validate_plan(plan, limits())          # must not raise
    assert any("invalid loop range" in e for e in errors(issues))


def test_empty_plan_is_error():
    issues = validate_plan(ScanPlan(root=[]), limits())
    assert any("empty" in e for e in errors(issues))


# --------------------------------------------------------------------------- #
# semantic + branch checks                                                     #
# --------------------------------------------------------------------------- #

def test_negative_settle_is_error():
    plan = stage_plan(Axis.STAGE_X, [0.0], settle_s=-1.0)
    assert any("settle_s" in e for e in errors(validate_plan(plan, limits())))


def test_zero_averages_is_error():
    plan = stage_plan(Axis.STAGE_X, [0.0], n_averages=0)
    assert any("n_averages" in e for e in errors(validate_plan(plan, limits())))


def test_negative_wait_is_error():
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0], children=[
        ActionBlock(action=ActionType.WAIT, params={"seconds": -5.0}),
    ])
    plan = ScanPlan(root=[loop])
    assert any("WAIT seconds" in e for e in errors(validate_plan(plan, limits())))


def test_save_without_acquire_warns():
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0], children=[_save()])
    plan = ScanPlan(root=[loop])
    assert any("ACQUIRE_WAVEFORM" in w for w in warnings(validate_plan(plan, limits())))


def test_save_with_earlier_acquire_in_enclosing_scope_ok():
    """acquire at outer level, save nested in a child loop → acquire is in scope."""
    inner = LoopBlock(axis=Axis.STAGE_Y, values=[0.0], children=[_save()])
    outer = LoopBlock(axis=Axis.STAGE_X, values=[0.0], children=[_acq(), inner])
    plan = ScanPlan(root=[outer])
    assert not any("ACQUIRE_WAVEFORM" in w
                   for w in warnings(validate_plan(plan, limits())))


def test_sibling_loop_acquire_does_not_leak_to_later_branch():
    """acquire buried in one loop must NOT satisfy a save in a later sibling."""
    loop_a = LoopBlock(axis=Axis.STAGE_X, values=[0.0], children=[_acq()])
    loop_b = LoopBlock(axis=Axis.STAGE_Y, values=[0.0], children=[_save()])
    plan = ScanPlan(root=[loop_a, loop_b])
    assert any("ACQUIRE_WAVEFORM" in w
               for w in warnings(validate_plan(plan, limits())))


def test_unknown_reduce_warns():
    plan = stage_plan(Axis.STAGE_X, [0.0], reduce="definitely_not_a_reduce")
    assert any("reduce" in w for w in warnings(validate_plan(plan, limits())))


def test_unknown_param_key_warns():
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0],
                     children=[_acq(nonsense_key=1), _save()])
    plan = ScanPlan(root=[loop])
    assert any("nonsense_key" in w for w in warnings(validate_plan(plan, limits())))


def test_acquire_param_n_averages_below_one_is_error():
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0],
                     children=[_acq(n_averages=0), _save()])
    plan = ScanPlan(root=[loop])
    assert any("n_averages" in e for e in errors(validate_plan(plan, limits())))


def test_issue_is_frozen_and_stringifies_with_path():
    issue = PlanIssue(ERROR, "root/loop(stage_x)[0]", "boom")
    assert issue.severity == ERROR
    assert "root/loop(stage_x)[0]" in str(issue)


def test_errors_and_warnings_partition_by_severity():
    plan = stage_plan(Axis.STAGE_X, [0.0], reduce="bogus")  # a warning only
    issues = validate_plan(plan, limits())
    assert warnings(issues) and errors(issues) == []
    # every issue is one severity or the other, no overlap
    assert len(issues) == len([i for i in issues if i.severity in (ERROR, WARNING)])
