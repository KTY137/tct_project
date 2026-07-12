"""Headless tests for the ScanController plan executor + danger gate.

Every test builds a fully *simulated* DeviceManager (no VISA / serial / Qt /
hardware I/O) and drives the state machine up to READY, mirroring the setup in
``test_scan_bias_channel.py``.  The plan executor (``start_plan`` / ``_run_plan``)
is exercised end-to-end through the same worker-thread path the GUI uses.

Cases (from the M2.2 step-2 brief):
  (a) full sim run with AutoConfirmGate → all SaveSteps written, FINISHED,
      wavegen output_off called.
  (b) unarmed bias plan → start_plan raises, no state change.
  (c) DenyAllGate → first BiasStep denied → bias ramped to 0 + output off,
      clean ABORTED stop, nothing saved.
  (d) simulated compliance trip mid-plan → abort + ramp-down + output_off,
      earlier point preserved.
  (e) validator ERROR (limit breach) → refuses before RUNNING.
  (f) pause→resume re-asserts the last commanded bias target (the deduped
      BiasStep list would otherwise skip the re-ramp).
  (g) x-only plan never commands y/z at the executor level (BLOCKER regression).
"""
from __future__ import annotations

import time
import unittest.mock as mock

import pytest
import yaml

from controller.device_manager import DeviceManager
from controller.state_machine import StateMachine, AppState
from controller.scan_controller import ScanController
from controller.scan_plan import ActionBlock, ActionType, Axis, LoopBlock, ScanPlan
from controller.scan_plan_validator import PlanLimits
from controller.danger_gate import AutoConfirmGate, DenyAllGate, DangerAction
from devices.bias_supply_base import BiasReading


# --------------------------------------------------------------------------- #
# Fully-simulated setup (no hardware)                                          #
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
    """Return a ready-to-run ``(dm, ctrl, sm)`` on fully-simulated backends."""
    dm = DeviceManager(config_path=_sim_config_path(tmp_path))
    assert dm.config_errors() == []
    results = dm.connect_all()
    assert all(v == "ok" for v in results.values()), results

    # Real homing cycle: the sim stage is already at the origin, so this is an
    # instant, zero-distance move.  (Was zero_position(), which used to fake
    # _homed=True — a user origin is NOT a machine home; see motor_base.)
    dm.motor.home()

    sm = StateMachine()
    for st in (AppState.CONNECTED, AppState.HOMED, AppState.CONFIGURED, AppState.READY):
        sm.transition(st)

    ctrl = ScanController(dm, sm)
    try:
        yield dm, ctrl, sm
    finally:
        dm.disconnect_all()


def _limits(**over) -> PlanLimits:
    d = dict(
        x_min_mm=-50.0, x_max_mm=50.0,
        y_min_mm=-50.0, y_max_mm=50.0,
        z_min_mm=-10.0, z_max_mm=10.0,
        voltage_range_V=1000.0, max_points=1_000_000,
    )
    d.update(over)
    return PlanLimits(**d)


# --------------------------------------------------------------------------- #
# plan builders                                                                #
# --------------------------------------------------------------------------- #
def _acq(**p):
    return ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params=p)


def _save():
    return ActionBlock(action=ActionType.SAVE_POINT, params={})


def _pause(msg):
    return ActionBlock(action=ActionType.MANUAL_PAUSE, params={"prompt": msg})


def _stage_plan(values):
    """An x-only stage raster: acquire + save at each x.  No bias."""
    loop = LoopBlock(axis=Axis.STAGE_X, values=[float(v) for v in values],
                     children=[_acq(), _save()])
    return ScanPlan(name="stage", root=[loop])


def _bias_plan(target, points=1):
    """Ramp bias to *target*, then *points* × (acquire + save) at that bias."""
    children = []
    for _ in range(points):
        children.extend([_acq(), _save()])
    loop = LoopBlock(axis=Axis.BIAS_V, values=[float(target)], children=children)
    return ScanPlan(name="bias", root=[loop],
                    safety={"require_hv_confirmation": True})


def _bias_pause_plan(target):
    """Ramp bias, acquire+save, manual-pause, then acquire+save again."""
    children = [_acq(), _save(), _pause("swap sample"), _acq(), _save()]
    loop = LoopBlock(axis=Axis.BIAS_V, values=[float(target)], children=children)
    return ScanPlan(name="bias_pause", root=[loop],
                    safety={"require_hv_confirmation": True})


def _bias_ramp_plan(target, ramp_step_V=None, ramp_delay_s=None, points=1):
    """A single-setpoint bias plan carrying explicit HV ramp shaping."""
    children: list = []
    for _ in range(points):
        children.extend([_acq(), _save()])
    loop = LoopBlock(axis=Axis.BIAS_V, values=[float(target)],
                     ramp_step_V=ramp_step_V, ramp_delay_s=ramp_delay_s,
                     children=children)
    return ScanPlan(name="bias_ramp", root=[loop],
                    safety={"require_hv_confirmation": True})


def _bias_ramp_pause_plan(target, ramp_step_V, ramp_delay_s):
    """A SHAPED bias ramp, acquire+save, a MID-plan manual-pause, then
    acquire+save.  Parks in PAUSED at the second acquire so a resume must
    re-assert the *shaped* ramp (compile_plan dedups the BiasStep)."""
    children = [_acq(), _save(), _pause("swap sample"), _acq(), _save()]
    loop = LoopBlock(axis=Axis.BIAS_V, values=[float(target)],
                     ramp_step_V=ramp_step_V, ramp_delay_s=ramp_delay_s,
                     children=children)
    return ScanPlan(name="bias_ramp_pause", root=[loop],
                    safety={"require_hv_confirmation": True})


def _trailing_pause_plan(msg="done — last step"):
    """acquire+save, then a MANUAL_PAUSE as the LAST executable step (no bias)."""
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0],
                     children=[_acq(), _save(), _pause(msg)])
    return ScanPlan(name="trailing_pause", root=[loop])


def _mid_pause_stage_plan(msg="hold"):
    """acquire+save, a MID-plan MANUAL_PAUSE, then acquire+save (no bias).

    Unlike a trailing pause (which finishes cleanly), this genuinely parks the
    run in PAUSED at the pause_event.wait() before the second acquire."""
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0],
                     children=[_acq(), _save(), _pause(msg), _acq(), _save()])
    return ScanPlan(name="mid_pause", root=[loop])


# --------------------------------------------------------------------------- #
# (a) full sim run                                                             #
# --------------------------------------------------------------------------- #
def test_full_run_writes_all_points(sim):
    dm, ctrl, sm = sim
    wf_off = mock.Mock(wraps=dm.waveform_generator.output_off)
    dm.waveform_generator.output_off = wf_off

    done: list = []
    progress: list = []
    ctrl.on_point_done = lambda r: done.append(r)
    ctrl.on_progress = lambda a, b: progress.append((a, b))

    ctrl.start_plan(_stage_plan([0.0, 1.0, 2.0]), _limits(), AutoConfirmGate())
    ctrl._thread.join(timeout=20)

    assert not ctrl._thread.is_alive()
    assert sm.state is AppState.FINISHED
    assert ctrl._writer._n_points == 3        # one per SaveStep
    assert len(done) == 3
    assert progress[-1] == (3, 3)
    assert wf_off.called                      # laser trigger disabled
    assert ctrl._hv_armed is False            # never armed; stays disarmed


# --------------------------------------------------------------------------- #
# (b) unarmed bias plan refuses                                                #
# --------------------------------------------------------------------------- #
def test_unarmed_bias_plan_refuses(sim):
    dm, ctrl, sm = sim
    with pytest.raises(RuntimeError, match="not armed"):
        ctrl.start_plan(_bias_plan(-10.0), _limits(), AutoConfirmGate())
    # No state change, no worker thread launched.
    assert sm.state is AppState.READY
    assert ctrl._thread is None


# --------------------------------------------------------------------------- #
# (c) denied HV ramp → fail-safe + clean abort                                 #
# --------------------------------------------------------------------------- #
def test_denied_bias_ramp_fails_safe(sim):
    dm, ctrl, sm = sim
    ch = dm.bias_supply
    ch.ramp_to = mock.Mock(wraps=ch.ramp_to)
    ch.output_off = mock.Mock(wraps=ch.output_off)
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)

    ctrl.arm_hv(True)
    ctrl.start_plan(_bias_plan(-100.0, points=2), _limits(), DenyAllGate())
    ctrl._thread.join(timeout=20)

    assert sm.state is AppState.ABORTED           # clean stop, not ERROR
    assert ch.setpoint_V == 0.0                   # ramped to 0
    assert not ch.driver.output_is_on_ch(ch.channel)   # output opened
    assert ch.output_off.called
    assert ctrl._writer._n_points == 0            # nothing acquired/saved
    assert errs                                   # deny surfaced to the operator
    assert ctrl._hv_armed is False                # disarmed after the run
    # The denied target was never ramped to; only the fail-safe ramp-to-0 ran.
    targets = [c.args[0] for c in ch.ramp_to.call_args_list if c.args]
    assert -100.0 not in targets
    assert 0.0 in targets


# --------------------------------------------------------------------------- #
# (d) compliance trip mid-plan                                                 #
# --------------------------------------------------------------------------- #
def test_compliance_trip_mid_plan(sim):
    dm, ctrl, sm = sim
    ch = dm.bias_supply
    ch.ramp_to = mock.Mock(wraps=ch.ramp_to)
    ch.output_off = mock.Mock(wraps=ch.output_off)
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)

    trip = {"armed": False}
    orig_read = ch.read

    def fake_read(*a, **k):
        if trip["armed"]:
            return BiasReading(voltage_V=-10.0, current_A=60e-6, compliant=True)
        return orig_read(*a, **k)

    ch.read = mock.Mock(side_effect=fake_read)
    # Arm the trip only after the first point has been saved, so one good point
    # is preserved before the abort (data-preservation on abort).
    ctrl.on_point_done = lambda r: trip.__setitem__("armed", True)

    ctrl.arm_hv(True)
    ctrl.start_plan(_bias_plan(-10.0, points=3), _limits(), AutoConfirmGate())
    ctrl._thread.join(timeout=20)

    assert sm.state is AppState.ABORTED
    assert ctrl._writer._n_points == 1                 # first point kept
    assert ch.setpoint_V == 0.0                        # ramped down
    assert ch.output_off.called
    assert any("compliance" in m.lower() for m in errs)
    assert any(c.args and c.args[0] == 0.0 for c in ch.ramp_to.call_args_list)


# --------------------------------------------------------------------------- #
# (e) validator ERROR refuses before RUNNING                                   #
# --------------------------------------------------------------------------- #
def test_validator_error_refuses_before_running(sim):
    dm, ctrl, sm = sim
    plan = _stage_plan([0.0, 1000.0])          # 1000 mm > x_max 50 → ERROR
    with pytest.raises(ValueError, match="validation"):
        ctrl.start_plan(plan, _limits(), AutoConfirmGate())
    assert sm.state is AppState.READY
    assert ctrl._thread is None


# --------------------------------------------------------------------------- #
# (f) pause → resume re-asserts bias                                           #
# --------------------------------------------------------------------------- #
def test_pause_resume_reasserts_bias(sim):
    dm, ctrl, sm = sim
    ch = dm.bias_supply
    ch.ramp_to = mock.Mock(wraps=ch.ramp_to)
    prompts: list = []
    ctrl.on_manual_pause = lambda p: prompts.append(p)

    ctrl.arm_hv(True)
    ctrl.start_plan(_bias_pause_plan(-5.0), _limits(), AutoConfirmGate())

    # The ManualPauseStep parks the run in PAUSED.
    deadline = time.time() + 20
    while time.time() < deadline and sm.state is not AppState.PAUSED:
        time.sleep(0.01)
    assert sm.state is AppState.PAUSED
    assert prompts == ["swap sample"]

    ctrl.resume()
    ctrl._thread.join(timeout=20)

    assert sm.state is AppState.FINISHED
    assert ctrl._writer._n_points == 2
    # -5 V is commanded twice: the initial BiasStep AND the resume re-assertion
    # (compile_plan dedups the BiasStep, so a bare resume would skip the re-ramp).
    targets = [c.args[0] for c in ch.ramp_to.call_args_list if c.args]
    assert targets.count(-5.0) >= 2


# --------------------------------------------------------------------------- #
# (g) x-only plan never commands y/z (BLOCKER regression at executor level)    #
# --------------------------------------------------------------------------- #
def test_x_only_plan_never_commands_y_or_z(sim):
    dm, ctrl, sm = sim
    # Park the stage at a non-zero y/z so a fabricated 0.0 would be visible.
    dm.motor.move_to(0.0, 3.0, 2.0)
    dm.motor.wait_until_ready()
    move_spy = mock.Mock(wraps=dm.motor.move_to)
    dm.motor.move_to = move_spy

    ctrl.start_plan(_stage_plan([0.0, 5.0, 10.0]), _limits(), AutoConfirmGate())
    ctrl._thread.join(timeout=20)

    assert sm.state is AppState.FINISHED
    assert move_spy.called
    # Every commanded move preserved the current y/z (3, 2) — never reset to 0.0.
    for c in move_spy.call_args_list:
        x, y, z = c.args
        assert y == 3.0 and z == 2.0
    assert [c.args[0] for c in move_spy.call_args_list] == [0.0, 5.0, 10.0]


# --------------------------------------------------------------------------- #
# (h) a plan ending on a trailing ManualPauseStep finishes cleanly             #
# --------------------------------------------------------------------------- #
def test_trailing_manual_pause_finishes(sim):
    """Last executable step = MANUAL_PAUSE → the loop exits in PAUSED with every
    acquire/save done.  The terminal block must promote PAUSED → RUNNING →
    FINISHED (both legal) instead of raising Invalid transition and mislabeling
    the clean run ABORTED + on_error (BUG, M2.2 review)."""
    dm, ctrl, sm = sim
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)
    prompts: list = []
    ctrl.on_manual_pause = lambda p: prompts.append(p)

    ctrl.start_plan(_trailing_pause_plan(), _limits(), AutoConfirmGate())
    ctrl._thread.join(timeout=20)

    assert not ctrl._thread.is_alive()
    assert sm.state is AppState.FINISHED          # not mislabeled ABORTED
    assert errs == []                             # no spurious on_error
    assert ctrl._writer._n_points == 1            # the acquire/save succeeded
    assert prompts == ["done — last step"]        # the pause prompt still surfaced


# --------------------------------------------------------------------------- #
# (i) a refused start clears the per-run HV arm latch (never sticky)           #
# --------------------------------------------------------------------------- #
def test_refused_start_clears_hv_arm(sim):
    """arm_hv(True) then a refused start_plan (validation ERROR) must clear the
    HV arm latch, so a *later* bias plan refuses with the unarmed error rather
    than inheriting the stale arm (RISK, M2.2 review)."""
    dm, ctrl, sm = sim
    ctrl.arm_hv(True)
    assert ctrl._hv_armed is True

    # A plan that fails validation refuses to start...
    bad = _stage_plan([0.0, 1000.0])              # 1000 mm > x_max 50 → ERROR
    with pytest.raises(ValueError, match="validation"):
        ctrl.start_plan(bad, _limits(), AutoConfirmGate())

    # ...and the refusal cleared the arm latch (never sticky across starts).
    assert ctrl._hv_armed is False
    assert sm.state is AppState.READY             # no state change

    # A subsequent bias plan now refuses with the unarmed error.
    with pytest.raises(RuntimeError, match="not armed"):
        ctrl.start_plan(_bias_plan(-10.0), _limits(), AutoConfirmGate())
    assert sm.state is AppState.READY
    assert ctrl._thread is None                   # no worker was ever launched


# --------------------------------------------------------------------------- #
# (j) HV ramp shaping (G1): the executor applies the requested shape           #
# --------------------------------------------------------------------------- #
def _ramp_up_prefix(set_v_spy, channel, target):
    """The intermediate set-voltage sequence up to the first *target* command."""
    volts = [c.args[1] for c in set_v_spy.call_args_list
             if c.args and c.args[0] == channel]
    return volts[:volts.index(target) + 1]


def test_bias_ramp_shaping_applied_intermediate_steps(sim):
    """A shaped plan ramps the SUPPLY in the requested step size — the simulated
    driver walks 10 V intermediate setpoints, not the 5 V default."""
    dm, ctrl, sm = sim
    drv = dm.bias_supply.driver
    set_v = mock.Mock(wraps=drv.set_voltage_ch)
    drv.set_voltage_ch = set_v

    ctrl.arm_hv(True)
    ctrl.start_plan(_bias_ramp_plan(-50.0, ramp_step_V=10.0, ramp_delay_s=0.0),
                    _limits(), AutoConfirmGate())
    ctrl._thread.join(timeout=20)

    assert sm.state is AppState.FINISHED
    # Coarse 10 V shaped ramp up to -50 V (intermediate voltage steps observed).
    assert _ramp_up_prefix(set_v, 0, -50.0) == [-10.0, -20.0, -30.0, -40.0, -50.0]


def test_bias_ramp_absent_uses_driver_default_step(sim):
    """Absent shaping = today's behaviour: the executor calls bias.ramp_to(target)
    with no kwargs, so the driver's default 5 V step walks the supply."""
    dm, ctrl, sm = sim
    drv = dm.bias_supply.driver
    set_v = mock.Mock(wraps=drv.set_voltage_ch)
    drv.set_voltage_ch = set_v

    ctrl.arm_hv(True)
    ctrl.start_plan(_bias_plan(-20.0), _limits(), AutoConfirmGate())
    ctrl._thread.join(timeout=20)

    assert sm.state is AppState.FINISHED
    # Default 5 V step (byte-identical to the pre-shaping BiasStep behaviour).
    assert _ramp_up_prefix(set_v, 0, -20.0) == [-5.0, -10.0, -15.0, -20.0]


def test_shaped_ramp_forwarded_to_ramp_to_kwargs(sim):
    """The requested shape reaches bias.ramp_to as step_V / delay_s kwargs."""
    dm, ctrl, sm = sim
    ch = dm.bias_supply
    ch.ramp_to = mock.Mock(wraps=ch.ramp_to)

    ctrl.arm_hv(True)
    ctrl.start_plan(_bias_ramp_plan(-30.0, ramp_step_V=15.0, ramp_delay_s=0.0),
                    _limits(), AutoConfirmGate())
    ctrl._thread.join(timeout=20)

    assert sm.state is AppState.FINISHED
    ramp_up = [c for c in ch.ramp_to.call_args_list
               if c.args and c.args[0] == -30.0]
    assert ramp_up, "the shaped target was never ramped to"
    for c in ramp_up:
        assert c.kwargs.get("step_V") == 15.0
        assert c.kwargs.get("delay_s") == 0.0


def test_pause_resume_reasserts_shaped_bias(sim):
    """Mary's RISK fix: a resume must re-apply the SAME step_V / delay_s the
    original shaped BiasStep used.  compile_plan dedups the BiasStep, so a bare
    resume would both skip the re-ramp AND (before this) drop the shaping — this
    parks a shaped ramp in PAUSED and proves the resume re-ramp keeps the shape.
    Mirrors test_shaped_ramp_forwarded_to_ramp_to_kwargs across a pause."""
    dm, ctrl, sm = sim
    ch = dm.bias_supply
    ch.ramp_to = mock.Mock(wraps=ch.ramp_to)
    prompts: list = []
    ctrl.on_manual_pause = lambda p: prompts.append(p)

    ctrl.arm_hv(True)
    ctrl.start_plan(
        _bias_ramp_pause_plan(-30.0, ramp_step_V=15.0, ramp_delay_s=0.0),
        _limits(), AutoConfirmGate())

    # The mid-plan ManualPauseStep parks the run in PAUSED.
    deadline = time.time() + 20
    while time.time() < deadline and sm.state is not AppState.PAUSED:
        time.sleep(0.01)
    assert sm.state is AppState.PAUSED
    assert prompts == ["swap sample"]

    ctrl.resume()
    ctrl._thread.join(timeout=20)

    assert sm.state is AppState.FINISHED
    assert ctrl._writer._n_points == 2
    ramp_up = [c for c in ch.ramp_to.call_args_list
               if c.args and c.args[0] == -30.0]
    # -30 V ramped twice: the initial shaped BiasStep AND the resume re-assertion.
    assert len(ramp_up) >= 2
    # EVERY ramp to the target carried the SAME shaping — incl. the resume one
    # (a bare bias.ramp_to(target) on resume would drop step_V/delay_s here).
    for c in ramp_up:
        assert c.kwargs.get("step_V") == 15.0
        assert c.kwargs.get("delay_s") == 0.0


# --------------------------------------------------------------------------- #
# (k) run-path seam (Q6ii): last_run_path for the "Open in Analysis" hand-off  #
# --------------------------------------------------------------------------- #
def test_last_run_path_none_before_and_set_after_finish(sim):
    dm, ctrl, sm = sim
    assert ctrl.last_run_path is None            # nothing has run yet

    ctrl.start_plan(_stage_plan([0.0, 1.0]), _limits(), AutoConfirmGate())
    ctrl._thread.join(timeout=20)

    assert sm.state is AppState.FINISHED
    path = ctrl.last_run_path
    assert path is not None
    assert path == ctrl._writer.path             # the just-written HDF5 file
    assert path.name == "waveforms.h5"
    assert path.exists()


def test_last_run_path_cleared_on_new_run(sim):
    dm, ctrl, sm = sim

    # First run finishes → path is published.
    ctrl.start_plan(_stage_plan([0.0]), _limits(), AutoConfirmGate())
    ctrl._thread.join(timeout=20)
    first = ctrl.last_run_path
    assert first is not None

    # Re-arm the state machine for another run (FINISHED → CONFIGURED → READY).
    sm.transition(AppState.CONFIGURED)
    sm.transition(AppState.READY)

    # A second run that parks in PAUSED (mid-plan manual pause): once it has
    # started, the previous path is cleared and no new one is published until it
    # finishes.
    ctrl.start_plan(_mid_pause_stage_plan(), _limits(), AutoConfirmGate())
    deadline = time.time() + 20
    while time.time() < deadline and sm.state is not AppState.PAUSED:
        time.sleep(0.01)
    assert sm.state is AppState.PAUSED
    assert ctrl.last_run_path is None            # cleared on the new run start

    ctrl.resume()
    ctrl._thread.join(timeout=20)
    assert sm.state is AppState.FINISHED
    second = ctrl.last_run_path
    assert second is not None
    assert second != first                       # a fresh run directory


# --------------------------------------------------------------------------- #
# danger-gate value types                                                      #
# --------------------------------------------------------------------------- #
def test_danger_gates_are_pure():
    action = DangerAction(kind="hv_ramp", summary="Ramp CH0 to -300 V",
                          detail={"target_V": -300.0})
    assert AutoConfirmGate().confirm(action) is True
    assert DenyAllGate().confirm(action) is False
    # DangerAction is frozen / hashable-ish and carries the real numbers.
    assert action.detail["target_V"] == -300.0
