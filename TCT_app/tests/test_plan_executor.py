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

    dm.motor.zero_position()            # homed without moving

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


def _trailing_pause_plan(msg="done — last step"):
    """acquire+save, then a MANUAL_PAUSE as the LAST executable step (no bias)."""
    loop = LoopBlock(axis=Axis.STAGE_X, values=[0.0],
                     children=[_acq(), _save(), _pause(msg)])
    return ScanPlan(name="trailing_pause", root=[loop])


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
# danger-gate value types                                                      #
# --------------------------------------------------------------------------- #
def test_danger_gates_are_pure():
    action = DangerAction(kind="hv_ramp", summary="Ramp CH0 to -300 V",
                          detail={"target_V": -300.0})
    assert AutoConfirmGate().confirm(action) is True
    assert DenyAllGate().confirm(action) is False
    # DangerAction is frozen / hashable-ish and carries the real numbers.
    assert action.detail["target_V"] == -300.0
