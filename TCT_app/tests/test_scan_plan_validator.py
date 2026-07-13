"""Tests for controller.scan_plan_validator — the fail-closed plan pre-flight.

Covers the required cases: stage-limit breach, max_points cap, HV plan without
require_hv_confirmation (fail-closed), bias out of range, a broken loop range
reported (not crashed), and a clean plan with no errors — plus the semantic and
branch checks.
"""
import pytest

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
    # Unknown OUTER params stay a WARNING for non-ACQUIRE actions (ACQUIRE_WAVEFORM
    # elevates them to ERROR — see test_acquire_unknown_outer_param_is_error).
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0],
                     children=[_acq(), _save(nonsense_key=1)])
    plan = ScanPlan(root=[loop])
    assert any("nonsense_key" in w for w in warnings(validate_plan(plan, limits())))


def test_acquire_unknown_outer_param_is_error():
    # A mistyped OUTER key ('wavgen' for 'wavegen') would silently DROP the whole
    # wavegen payload at execution, defeating the nested _KNOWN_WAVEGEN_KEYS ERROR
    # one level down.  On ACQUIRE_WAVEFORM the unknown outer key is an ERROR that
    # names the offending key — never a WARNING that rides along inert.
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0],
                     children=[_acq(wavgen={"duty_cycle_pct": 0.3}), _save()])
    plan = ScanPlan(root=[loop])
    issues = validate_plan(plan, limits())
    assert any("wavgen" in e for e in errors(issues))
    assert not any("wavgen" in w for w in warnings(issues))


def test_acquire_legitimate_outer_params_no_error():
    # The full legitimate ACQUIRE_WAVEFORM param set validates with 0 ERROR: the
    # action-scoped ERROR must fire only on UNKNOWN outer keys, never on these.
    loop = LoopBlock(
        axis=Axis.STAGE_X, values=[0.0],
        children=[_acq(wavegen={"frequency_hz": 1000.0}, n_averages=4,
                       channels=[1], record_length=1000, timeout_s=5.0,
                       label="pt"),
                  _save()])
    plan = ScanPlan(root=[loop])
    assert errors(validate_plan(plan, limits())) == []


def test_acquire_param_n_averages_below_one_is_error():
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0],
                     children=[_acq(n_averages=0), _save()])
    plan = ScanPlan(root=[loop])
    assert any("n_averages" in e for e in errors(validate_plan(plan, limits())))


# --------------------------------------------------------------------------- #
# nested wavegen params (P0': the C1-found validation gap)                     #
# --------------------------------------------------------------------------- #

def _wavegen_plan(wavegen):
    """A stage plan whose acquire carries params['wavegen'] = *wavegen*."""
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0],
                     children=[_acq(wavegen=wavegen), _save()])
    return ScanPlan(root=[loop])


def test_wavegen_known_keys_clean():
    plan = _wavegen_plan({
        "frequency_hz": 1000.0, "pulse_width_s": 100e-9,
        "duty_cycle_pct": 0.3, "amplitude_V": 3.3, "offset_V": 0.0,
    })
    assert errors(validate_plan(plan, limits())) == []


def test_wavegen_unknown_key_is_error_not_warning():
    # A 'dutycycle' typo must fail LOUD at validate time, not ride along inert
    # (unlike the outer unknown-param WARNING).
    plan = _wavegen_plan({"dutycycle": 5.0})
    issues = validate_plan(plan, limits())
    assert any("dutycycle" in e for e in errors(issues))
    assert not any("dutycycle" in w for w in warnings(issues))


def test_wavegen_duty_out_of_range_is_error():
    assert any("duty_cycle_pct" in e
               for e in errors(validate_plan(_wavegen_plan(
                   {"duty_cycle_pct": 150.0}), limits())))
    assert any("duty_cycle_pct" in e
               for e in errors(validate_plan(_wavegen_plan(
                   {"duty_cycle_pct": 0.0}), limits())))


def test_wavegen_nonpositive_frequency_and_width_are_errors():
    assert any("frequency_hz" in e
               for e in errors(validate_plan(_wavegen_plan(
                   {"frequency_hz": 0.0}), limits())))
    assert any("pulse_width_s" in e
               for e in errors(validate_plan(_wavegen_plan(
                   {"pulse_width_s": -1e-9}), limits())))


def test_wavegen_negative_amplitude_is_error():
    assert any("amplitude_V" in e
               for e in errors(validate_plan(_wavegen_plan(
                   {"amplitude_V": -1.0}), limits())))


def test_wavegen_non_numeric_value_is_error():
    assert any("must be a number" in e
               for e in errors(validate_plan(_wavegen_plan(
                   {"frequency_hz": "fast"}), limits())))


def test_wavegen_non_mapping_is_error():
    assert any("must be a mapping" in e
               for e in errors(validate_plan(_wavegen_plan([1, 2, 3]), limits())))


def test_wavegen_offset_unconstrained():
    # offset_V has no structural domain bound — any real is accepted.
    plan = _wavegen_plan({"offset_V": -12.5})
    assert errors(validate_plan(plan, limits())) == []


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


def test_trailing_manual_pause_warns():
    # A pause as the very last executable step gates nothing — WARNING, not
    # ERROR (the executor finishes such a run cleanly).
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0, 1.0],
                     children=[_acq(), _save()])
    pause = ActionBlock(action=ActionType.MANUAL_PAUSE,
                        params={"prompt": "flip sample"})
    plan = ScanPlan(name="t", root=[loop, pause])
    issues = validate_plan(plan, limits())
    assert errors(issues) == []
    assert any("MANUAL_PAUSE" in w and "gates nothing" in w
               for w in warnings(issues))


def test_mid_plan_manual_pause_does_not_warn():
    pause = ActionBlock(action=ActionType.MANUAL_PAUSE,
                        params={"prompt": "insert filter"})
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0, 1.0],
                     children=[_acq(), _save()])
    plan = ScanPlan(name="t", root=[pause, loop])
    issues = validate_plan(plan, limits())
    assert not any("MANUAL_PAUSE" in w for w in warnings(issues))


# --------------------------------------------------------------------------- #
# HV ramp shaping (G1): fail-closed on nonsensical values                      #
# --------------------------------------------------------------------------- #

def _bias_ramp_plan(ramp_step_V=None, ramp_delay_s=None):
    loop = LoopBlock(axis=Axis.BIAS_V, values=[-50.0],
                     ramp_step_V=ramp_step_V, ramp_delay_s=ramp_delay_s,
                     children=[_acq(), _save()])
    return ScanPlan(name="t", root=[loop],
                    safety={"require_hv_confirmation": True})


def test_valid_ramp_shaping_is_clean():
    plan = _bias_ramp_plan(ramp_step_V=5.0, ramp_delay_s=0.1)
    issues = validate_plan(plan, limits())
    assert errors(issues) == []
    assert not any("ramp_" in w for w in warnings(issues))


@pytest.mark.parametrize("bad", [0.0, -5.0])
def test_non_positive_ramp_step_is_error(bad):
    plan = _bias_ramp_plan(ramp_step_V=bad, ramp_delay_s=0.1)
    assert any("ramp_step_V" in e for e in errors(validate_plan(plan, limits())))


def test_negative_ramp_delay_is_error():
    plan = _bias_ramp_plan(ramp_step_V=5.0, ramp_delay_s=-0.1)
    assert any("ramp_delay_s" in e for e in errors(validate_plan(plan, limits())))


def test_zero_ramp_delay_is_clean():
    """A zero per-step dwell is legal (fast, delay-free ramp)."""
    plan = _bias_ramp_plan(ramp_step_V=5.0, ramp_delay_s=0.0)
    assert not any("ramp_delay_s" in e for e in errors(validate_plan(plan, limits())))


def test_ramp_shaping_on_stage_loop_warns():
    """Ramp shaping on a non-bias loop is ignored downstream → WARNING, not an
    ERROR (it is harmless, just useless)."""
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0],
                     ramp_step_V=5.0, ramp_delay_s=0.1,
                     children=[_acq(), _save()])
    plan = ScanPlan(name="t", root=[loop])
    issues = validate_plan(plan, limits())
    assert errors(issues) == []
    assert any("ramp_step_V" in w and "non-bias" in w for w in warnings(issues))


# --------------------------------------------------------------------------- #
# CAPTURE_PHOTO (B2): fail-closed device-availability gate + settle_s sanity    #
# --------------------------------------------------------------------------- #

def _photo_plan(**params):
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0],
                     children=[ActionBlock(action=ActionType.CAPTURE_PHOTO,
                                           params=params)])
    return ScanPlan(name="t", root=[loop])


def test_capture_photo_without_camera_is_error():
    """Fail-closed: a photo step with no camera available is rejected on paper."""
    errs = errors(validate_plan(_photo_plan(), limits(camera_available=False)))
    assert any("CAPTURE_PHOTO" in e and "camera" in e for e in errs)


def test_capture_photo_default_limits_reject_it():
    """PlanLimits defaults camera_available False, so an un-wired caller can
    never accidentally admit a camera-less photo plan."""
    errs = errors(validate_plan(_photo_plan(), limits()))
    assert any("camera" in e for e in errs)


def test_capture_photo_with_camera_is_accepted():
    issues = validate_plan(_photo_plan(settle_s=0.2, label="tile"),
                           limits(camera_available=True))
    assert errors(issues) == []
    # settle_s / label are known params → no unknown-param warning either.
    assert not any("unknown param" in w for w in warnings(issues))


def test_capture_photo_negative_settle_is_error():
    errs = errors(validate_plan(_photo_plan(settle_s=-0.5),
                                limits(camera_available=True)))
    assert any("settle_s" in e for e in errs)


def test_capture_photo_unknown_param_warns():
    issues = validate_plan(_photo_plan(exposure_ms=5),
                           limits(camera_available=True))
    assert any("exposure_ms" in w for w in warnings(issues))
