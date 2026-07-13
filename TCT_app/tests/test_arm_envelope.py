"""Tests for the arm-envelope model + gate (Item 1, DECISIONS 2026-07-12).

Two layers:

* PURE derivation / gate logic (no hardware, no threads): the envelope derived
  from a plan carries the correct bias + motion extremes (including a ramped
  bias loop), and the ArmedEnvelopeGate auto-approves actions provably inside
  the envelope while DENYING (fail-closed) anything outside it — wrong channel,
  out-of-range voltage, out-of-bounds / un-armed-axis move, and past-expiry.

* END-TO-END through the plan executor on fully-simulated backends: an
  in-envelope run FINISHES via the ArmedEnvelopeGate (no per-action dialog),
  and an out-of-envelope run ABORTS cleanly with the HV fail-safe — exactly like
  a user deny today.
"""
from __future__ import annotations

import time

import pytest
import yaml

from controller.device_manager import DeviceManager
from controller.state_machine import StateMachine, AppState
from controller.scan_controller import ScanController
from controller.scan_plan import ActionBlock, ActionType, Axis, LoopBlock, ScanPlan
from controller.scan_plan_validator import PlanLimits
from controller.plan_compiler import compile_plan
from controller.danger_gate import DangerAction
from controller.arm_envelope import (
    ArmedEnvelope, ArmedEnvelopeGate, derive_envelope, envelope_from_plan,
    envelope_from_plans,
)


# --------------------------------------------------------------------------- #
# plan builders                                                                #
# --------------------------------------------------------------------------- #
def _acq(**p):
    return ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params=p)


def _save():
    return ActionBlock(action=ActionType.SAVE_POINT, params={})


def _bias_xy_plan(bias_values, xs, ramp_step_V=None, ramp_delay_s=None):
    """Bias sweep (outer) over an X raster (inner) with acquire+save leaves."""
    xloop = LoopBlock(axis=Axis.STAGE_X, values=[float(x) for x in xs],
                      children=[_acq(), _save()])
    bloop = LoopBlock(axis=Axis.BIAS_V, values=[float(v) for v in bias_values],
                      ramp_step_V=ramp_step_V, ramp_delay_s=ramp_delay_s,
                      children=[xloop])
    return ScanPlan(name="bias_xy", root=[bloop],
                    safety={"require_hv_confirmation": True})


def _stage_plan(values):
    loop = LoopBlock(axis=Axis.STAGE_X, values=[float(v) for v in values],
                     children=[_acq(), _save()])
    return ScanPlan(name="stage", root=[loop])


def _bias_plan(target, points=1):
    children = []
    for _ in range(points):
        children.extend([_acq(), _save()])
    loop = LoopBlock(axis=Axis.BIAS_V, values=[float(target)], children=children)
    return ScanPlan(name="bias", root=[loop],
                    safety={"require_hv_confirmation": True})


def _D(kind, detail):
    return DangerAction(kind=kind, summary="", detail=detail)


# --------------------------------------------------------------------------- #
# (1) derivation: bias + motion extremes, incl. a ramped bias loop             #
# --------------------------------------------------------------------------- #
def test_envelope_derivation_extremes_and_ramp():
    plan = _bias_xy_plan([-10.0, -20.0, -30.0], [-1.0, 0.0, 1.0],
                         ramp_step_V=10.0, ramp_delay_s=0.1)
    env = envelope_from_plan(plan, channel=0)

    assert env.channels == frozenset({0})
    assert (env.hv_min_V, env.hv_max_V) == (-30.0, -10.0)   # signed min/max
    assert env.ramp_step_V == 10.0 and env.ramp_delay_s == 0.1
    assert env.x_bounds == (-1.0, 1.0)
    assert env.y_bounds is None and env.z_bounds is None    # never driven
    assert env.n_bias_setpoints == 3
    assert env.drives_hv is True


def test_envelope_derivation_matches_move_action_envelope():
    """The armed motion bounds equal the executor's own _move_action envelope,
    so an in-envelope run's move confirm is provably inside by construction."""
    plan = _bias_xy_plan([-50.0], [-2.0, 0.0, 2.0])
    steps = compile_plan(plan)
    ctrl_env = ScanController.__new__(ScanController)._move_action(steps).detail["envelope"]
    env = derive_envelope(steps, channel=0)
    assert env.x_bounds == ctrl_env["x_mm"]
    assert (env.y_bounds, env.z_bounds) == (ctrl_env["y_mm"], ctrl_env["z_mm"])


def test_stage_only_plan_has_no_hv():
    env = envelope_from_plan(_stage_plan([0.0, 5.0]), channel=0)
    assert env.channels == frozenset()
    assert env.hv_min_V is None and env.hv_max_V is None
    assert env.drives_hv is False
    assert env.x_bounds == (0.0, 5.0)


# --------------------------------------------------------------------------- #
# (2) in-envelope auto-approve                                                  #
# --------------------------------------------------------------------------- #
def test_in_envelope_actions_auto_approved():
    env = envelope_from_plan(_bias_xy_plan([-10.0, -30.0], [-1.0, 1.0]), channel=0)
    gate = ArmedEnvelopeGate(env)
    assert gate.confirm(_D("hv_ramp", {"channel": 0, "target_V": -20.0})) is True
    assert gate.confirm(_D("hv_ramp", {"channel": 0, "target_V": -30.0})) is True  # boundary
    assert gate.confirm(_D("move", {"envelope":
                                    {"x_mm": (-1.0, 1.0), "y_mm": None, "z_mm": None}})) is True


# --------------------------------------------------------------------------- #
# (3) out-of-envelope DENY (fail-closed)                                        #
# --------------------------------------------------------------------------- #
def test_out_of_range_voltage_denied():
    env = envelope_from_plan(_bias_plan(-10.0), channel=0)
    gate = ArmedEnvelopeGate(env)
    assert gate.confirm(_D("hv_ramp", {"channel": 0, "target_V": -100.0})) is False


def test_wrong_channel_denied():
    env = envelope_from_plan(_bias_plan(-10.0), channel=0)
    gate = ArmedEnvelopeGate(env)
    assert gate.confirm(_D("hv_ramp", {"channel": 1, "target_V": -10.0})) is False


def test_out_of_bounds_move_denied():
    env = envelope_from_plan(_stage_plan([-1.0, 1.0]), channel=0)
    gate = ArmedEnvelopeGate(env)
    # X span exceeds the armed [-1, 1] bound.
    assert gate.confirm(_D("move", {"envelope":
                                    {"x_mm": (-5.0, 1.0), "y_mm": None, "z_mm": None}})) is False


def test_move_on_unarmed_axis_denied():
    env = envelope_from_plan(_stage_plan([-1.0, 1.0]), channel=0)  # X only
    gate = ArmedEnvelopeGate(env)
    assert gate.confirm(_D("move", {"envelope":
                                    {"x_mm": (-1.0, 1.0), "y_mm": (0.0, 2.0), "z_mm": None}})) is False


def test_unknown_danger_kind_denied():
    env = envelope_from_plan(_bias_plan(-10.0), channel=0)
    gate = ArmedEnvelopeGate(env)
    assert gate.confirm(_D("laser", {})) is False
    assert gate.confirm(_D("scan_start", {})) is False


# --------------------------------------------------------------------------- #
# (4) expiry denies                                                            #
# --------------------------------------------------------------------------- #
def test_expiry_denies():
    # Armed with a timeout already in the past.
    env = derive_envelope(compile_plan(_bias_plan(-10.0)), channel=0,
                          timeout_s=0.0, now=time.monotonic() - 1.0)
    gate = ArmedEnvelopeGate(env)
    assert env.is_expired() is True
    assert gate.confirm(_D("hv_ramp", {"channel": 0, "target_V": -10.0})) is False


def test_no_timeout_never_expires():
    env = envelope_from_plan(_bias_plan(-10.0), channel=0)  # no timeout
    assert env.expiry_monotonic is None
    assert env.is_expired() is False


# --------------------------------------------------------------------------- #
# (5) summary carries the real numbers                                         #
# --------------------------------------------------------------------------- #
def test_summary_carries_numbers():
    env = envelope_from_plan(_bias_xy_plan([-10.0, -300.0], [-1.5, 1.5],
                                           ramp_step_V=5.0, ramp_delay_s=0.1),
                             channel=0, timeout_s=10.0)
    s = env.summary
    assert "CH0" in s
    assert "-300" in s and "-10" in s          # the signed HV range
    assert "5 V" in s and "0.1 s" in s         # the ramp shape
    assert "-1.5" in s and "1.5" in s          # the motion bounds
    assert "10 s" in s                          # the expiry window


def test_on_deny_audit_hook_fires():
    env = envelope_from_plan(_bias_plan(-10.0), channel=0)
    seen: list = []
    gate = ArmedEnvelopeGate(env, on_deny=lambda a, r: seen.append((a.kind, r)))
    assert gate.confirm(_D("hv_ramp", {"channel": 0, "target_V": -999.0})) is False
    assert seen and seen[0][0] == "hv_ramp" and "outside armed range" in seen[0][1]


# --------------------------------------------------------------------------- #
# (6) combined SEQUENCE envelope — one arm over a routine QUEUE                 #
#     (DECISIONS 2026-07-13: max HV, total travel, every routine named)         #
# --------------------------------------------------------------------------- #
def test_sequence_union_hv_and_motion_extremes():
    """Union of two plans = the GLOBAL envelope of both: HV min/max are the
    global extremes, per-axis bounds the global min/max, counts summed."""
    a = _bias_xy_plan([-10.0, -20.0], [-1.0, 1.0])   # HV -20..-10, X -1..1
    b = _bias_xy_plan([-30.0, -40.0], [2.0, 5.0])    # HV -40..-30, X 2..5
    env = envelope_from_plans([a, b], channel=0)

    assert env.channels == frozenset({0})
    assert (env.hv_min_V, env.hv_max_V) == (-40.0, -10.0)   # global signed extremes
    assert env.x_bounds == (-1.0, 5.0)                      # global travel
    assert env.y_bounds is None and env.z_bounds is None    # never driven
    # counts summed across both plans (2 + 2 setpoints, 4 + 4 moves)
    single_a = envelope_from_plan(a, channel=0)
    single_b = envelope_from_plan(b, channel=0)
    assert env.n_bias_setpoints == single_a.n_bias_setpoints + single_b.n_bias_setpoints
    assert env.n_moves == single_a.n_moves + single_b.n_moves


def test_sequence_mixed_ramp_shape_is_none():
    """Plans whose ramp shapes DIFFER collapse to None ("mixed") — safe because
    the gate never re-validates ramp rate (only channel + target voltage)."""
    a = _bias_xy_plan([-10.0], [0.0], ramp_step_V=5.0, ramp_delay_s=0.1)
    b = _bias_xy_plan([-20.0], [0.0], ramp_step_V=10.0, ramp_delay_s=0.2)
    env = envelope_from_plans([a, b], channel=0)
    assert env.ramp_step_V is None and env.ramp_delay_s is None


def test_sequence_uniform_ramp_shape_preserved():
    """A ramp shape uniform across every plan is preserved in the union."""
    a = _bias_xy_plan([-10.0], [0.0], ramp_step_V=5.0, ramp_delay_s=0.1)
    b = _bias_xy_plan([-20.0], [0.0], ramp_step_V=5.0, ramp_delay_s=0.1)
    env = envelope_from_plans([a, b], channel=0)
    assert env.ramp_step_V == 5.0 and env.ramp_delay_s == 0.1


def test_sequence_summary_names_every_routine_with_prefix():
    """Every routine name appears in the arm text behind the SEQUENCE prefix
    (ratified: the operator sees which routines the single hold-3s authorizes)."""
    a = _bias_plan(-10.0)
    b = _bias_xy_plan([-30.0], [-2.0, 2.0])
    c = _stage_plan([0.0, 8.0])
    env = envelope_from_plans([a, b, c], channel=0,
                              plan_names=["warmup", "iv-sweep", "focus-map"])
    s = env.summary
    assert s.startswith("Arm SEQUENCE envelope (3 routines: "
                        "warmup, iv-sweep, focus-map): ")
    for name in ("warmup", "iv-sweep", "focus-map"):
        assert name in s
    assert env.routine_names == ("warmup", "iv-sweep", "focus-map")
    # the union's real numbers still ride in the body
    assert "-30" in s and "-10" in s


def test_sequence_gate_approves_plan2_action_denies_outside_union():
    """A gate built from the union APPROVES a DangerAction from plan 2 that
    plan 1 alone would DENY, and DENIES an HV value outside the union."""
    p1 = _bias_plan(-10.0)     # armed for -10 V only
    p2 = _bias_plan(-100.0)    # extends the union down to -100 V

    # plan 1 alone does NOT cover the -100 V ramp.
    solo = ArmedEnvelopeGate(envelope_from_plan(p1, channel=0))
    assert solo.confirm(_D("hv_ramp", {"channel": 0, "target_V": -100.0})) is False

    union = ArmedEnvelopeGate(envelope_from_plans([p1, p2], channel=0))
    assert union.confirm(_D("hv_ramp", {"channel": 0, "target_V": -100.0})) is True
    assert union.confirm(_D("hv_ramp", {"channel": 0, "target_V": -10.0})) is True
    # outside the union [-100, -10] → fail-closed.
    assert union.confirm(_D("hv_ramp", {"channel": 0, "target_V": -200.0})) is False


def test_sequence_single_plan_matches_envelope_from_plan():
    """routine_names default keeps a plain result unchanged (backward compat):
    a one-plan, un-named sequence equals the historic single-plan envelope."""
    plan = _bias_xy_plan([-10.0, -30.0], [-1.0, 1.0], ramp_step_V=5.0)
    solo = envelope_from_plan(plan, channel=0)
    seq = envelope_from_plans([plan], channel=0)   # no plan_names
    assert seq.routine_names == ()
    assert seq.summary.startswith("Arm envelope:")
    assert seq.summary == solo.summary
    assert (seq.hv_min_V, seq.hv_max_V) == (solo.hv_min_V, solo.hv_max_V)
    assert seq.x_bounds == solo.x_bounds
    assert seq.ramp_step_V == solo.ramp_step_V


def test_sequence_backward_compat_plain_envelope_unchanged():
    """envelope_from_plan alone still yields the historic fields untouched."""
    env = envelope_from_plan(_bias_plan(-10.0), channel=0)
    assert env.routine_names == ()
    assert env.summary.startswith("Arm envelope:")
    assert "SEQUENCE" not in env.summary


def test_sequence_empty_plans_raises():
    """An empty queue can never be armed (fail-closed, no empty envelope)."""
    with pytest.raises(ValueError):
        envelope_from_plans([], channel=0)


# --------------------------------------------------------------------------- #
# End-to-end through the executor (fully simulated)                            #
# --------------------------------------------------------------------------- #
def _sim_config_path(tmp_path):
    cfg = {
        "oscilloscope":       {"backend": "visa", "simulation": True},
        "motor_stage":        {"backend": "simulated"},
        "intensity_monitor":  {"backend": "simulated"},
        "camera":             {"simulation": True},
        "waveform_generator": {"simulation": True},
        "bias_supply":        {"backend": "simulated"},
        "output":             {"data_dir": str(tmp_path / "runs")},
    }
    path = tmp_path / "devices.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return str(path)


@pytest.fixture
def sim(tmp_path):
    dm = DeviceManager(config_path=_sim_config_path(tmp_path))
    assert dm.config_errors() == []
    results = dm.connect_all()
    assert all(v == "ok" for v in results.values()), results
    dm.motor.home()                      # real homing (sim: instant, at origin)
    sm = StateMachine()
    for st in (AppState.CONNECTED, AppState.HOMED, AppState.CONFIGURED, AppState.READY):
        sm.transition(st)
    ctrl = ScanController(dm, sm)
    try:
        yield dm, ctrl, sm
    finally:
        dm.disconnect_all()


def _limits(**over) -> PlanLimits:
    d = dict(x_min_mm=-50.0, x_max_mm=50.0, y_min_mm=-50.0, y_max_mm=50.0,
             z_min_mm=-10.0, z_max_mm=10.0, voltage_range_V=1000.0,
             max_points=1_000_000)
    d.update(over)
    return PlanLimits(**d)


def test_in_envelope_bias_run_finishes_via_gate(sim):
    """A run armed from its OWN plan auto-approves every danger action and
    FINISHES — no AutoConfirmGate, no per-action dialog."""
    dm, ctrl, sm = sim
    plan = _bias_plan(-30.0, points=2)
    env = ctrl.arm_envelope_for(plan, timeout_s=60.0)
    assert env.channels == frozenset({dm.bias_supply.channel})

    ctrl.arm_hv(True)
    ctrl.start_plan(plan, _limits(), ArmedEnvelopeGate(env))
    ctrl._thread.join(timeout=20)

    assert sm.state is AppState.FINISHED
    assert ctrl._writer._n_points == 2
    assert ctrl._hv_armed is False


def test_out_of_envelope_bias_run_aborts_failsafe(sim):
    """Arm a NARROW envelope (only -10 V) then run a plan that ramps to -100 V:
    the gate denies the out-of-envelope ramp, and the run aborts cleanly with
    the HV fail-safe — exactly like a user deny today."""
    import unittest.mock as mock
    dm, ctrl, sm = sim
    ch = dm.bias_supply
    ch.ramp_to = mock.Mock(wraps=ch.ramp_to)
    ch.output_off = mock.Mock(wraps=ch.output_off)
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)

    narrow_env = ctrl.arm_envelope_for(_bias_plan(-10.0))       # armed for -10 V
    ctrl.arm_hv(True)
    ctrl.start_plan(_bias_plan(-100.0, points=2), _limits(),    # but runs to -100 V
                    ArmedEnvelopeGate(narrow_env))
    ctrl._thread.join(timeout=20)

    assert sm.state is AppState.ABORTED
    assert ch.setpoint_V == 0.0                        # ramped to 0
    assert not ch.driver.output_is_on_ch(ch.channel)   # output opened
    assert ctrl._writer._n_points == 0                 # nothing acquired/saved
    assert errs                                        # deny surfaced
    assert ctrl._hv_armed is False
    targets = [c.args[0] for c in ch.ramp_to.call_args_list if c.args]
    assert -100.0 not in targets and 0.0 in targets


def test_in_envelope_stage_run_finishes(sim):
    """A stage-only plan armed from itself finishes; the single motion confirm
    is auto-approved by the armed bounds."""
    import unittest.mock as mock
    dm, ctrl, sm = sim
    plan = _stage_plan([0.0, 5.0, 10.0])
    env = ctrl.arm_envelope_for(plan)
    move_spy = mock.Mock(wraps=dm.motor.move_to)
    dm.motor.move_to = move_spy

    ctrl.start_plan(plan, _limits(), ArmedEnvelopeGate(env))
    ctrl._thread.join(timeout=20)

    assert sm.state is AppState.FINISHED
    assert ctrl._writer._n_points == 3
    assert move_spy.called
