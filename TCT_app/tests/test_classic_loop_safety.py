"""Safety tests for the CLASSIC run loops (voltage scan + z-focus).

Mary's REQUEST-CHANGES on 3f6e2b7 proved (AST reachability probe + a full
simulated run) that ``_apply_slow_control_policy`` was reachable ONLY from
``_run``/``_run_plan`` (via ``_acquire_core`` / ``ReadSlowControlStep``). The
three "classic" loops — ``_run_z_focus_amplitude``, ``_run_z_focus_edge`` and
``_run_voltage_scan`` — read the scope directly and never sampled slow control,
so:

  * a default voltage sweep drove HV to -300 V with **zero** temperature /
    humidity interlock (an ALARM could not ramp HV down), contradicting the
    RATIFIED policy in ``docs/DECISIONS.md`` 2026-07-12 §2;
  * a compliance trip inside the voltage loop did NOT set the abort event, so
    the run settled **FINISHED** — the cockpit painted the green "Scan
    finished" banner over a trip;
  * an Abort pressed mid-``ramp_to`` still completed the ramp, the dwell and a
    full acquisition (continued HV increase after the operator hit stop);
  * a run parked in PAUSED held HV while re-reading *nothing* — no compliance
    check, no slow-control evaluation.

This file locks all of that down, plus the honest terminal paint in the Scan
Viewer. Everything runs on fully-simulated backends; excursion values are made
deterministic (noise=0, drift=0) or monkeypatched, never left to the drifting
simulator.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
import unittest.mock as mock

import pytest
import yaml
from PySide6.QtWidgets import QApplication

from controller.device_manager import DeviceManager
from controller.state_machine import StateMachine, AppState
from controller.scan_controller import (
    ScanController, VoltageScanConfig, ZFocusScanConfig,
)
from controller.scan_plan_validator import PlanLimits
from controller.danger_gate import AutoConfirmGate
from devices.bias_supply_base import BiasReading
from gui.scan_coordinator import ScanCoordinator
from gui.scan_viewer_panel import ScanViewerPanel


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _flat_channel(name="temperature_C", unit="C", nominal=25.0, **thresholds):
    """A simulated slow-control channel with NO noise/drift (value == nominal)."""
    ch = {"name": name, "unit": unit, "backend": "simulated",
          "nominal": nominal, "noise": 0.0, "drift_amplitude": 0.0,
          "drift_period_s": 60.0}
    ch.update(thresholds)
    return ch


@pytest.fixture
def make_ctrl(tmp_path):
    """(dm, ctrl, sm) on fully-simulated backends, state READY."""
    created: list = []

    def _factory(sc_channels=None):
        cfg = {
            "oscilloscope":       {"backend": "visa", "simulation": True},
            "motor_stage":        {"backend": "simulated"},
            "intensity_monitor":  {"backend": "simulated"},
            "camera":             {"simulation": True},
            "waveform_generator": {"simulation": True},
            "bias_supply":        {"backend": "simulated"},
            "output":             {"data_dir": str(tmp_path / "runs")},
        }
        if sc_channels:
            cfg["slow_control"] = {"channels": sc_channels}
        path = tmp_path / "devices.yaml"
        path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        dm = DeviceManager(config_path=str(path))
        assert dm.config_errors() == [], dm.config_errors()
        assert all(v == "ok" for v in dm.connect_all().values())
        dm.motor.home()                  # real homing (sim: instant, at origin)
        sm = StateMachine()
        for st in (AppState.CONNECTED, AppState.HOMED,
                   AppState.CONFIGURED, AppState.READY):
            sm.transition(st)
        ctrl = ScanController(dm, sm)
        ctrl._PAUSE_POLL_S = 0.02        # fast park supervision for tests
        created.append(dm)
        return dm, ctrl, sm

    yield _factory
    for dm in created:
        dm.disconnect_all()


def _vscan(**over) -> VoltageScanConfig:
    """A short, fast IV sweep: 0 → -20 V in 10 V steps (3 points)."""
    d = dict(v_start_V=0.0, v_stop_V=-20.0, v_step_V=-10.0,
             ramp_step_V=20.0, ramp_delay_s=0.0, hold_delay_s=0.0,
             n_averages=1)
    d.update(over)
    return VoltageScanConfig(**d)


def _zfocus(**over) -> ZFocusScanConfig:
    d = dict(mode="amplitude", x_mm=0.0, y_mm=0.0,
             z_start_mm=0.0, z_stop_mm=0.2, z_step_mm=0.1,
             n_averages=1, settle_time_s=0.0)
    d.update(over)
    return ZFocusScanConfig(**d)


def _wait_state(sm, state, timeout=20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline and sm.state is not state:
        time.sleep(0.01)
    return sm.state is state


def _join(ctrl, timeout=20.0) -> None:
    if ctrl._thread is not None:
        ctrl._thread.join(timeout=timeout)
        assert not ctrl._thread.is_alive(), "worker thread did not finish"


def _limits() -> PlanLimits:
    return PlanLimits(x_min_mm=-50.0, x_max_mm=50.0, y_min_mm=-50.0, y_max_mm=50.0,
                      z_min_mm=-10.0, z_max_mm=10.0, voltage_range_V=1000.0,
                      max_points=1_000_000)


# =========================================================================== #
# FINDING 1 — the classic loops now sample slow control and honour the policy  #
# =========================================================================== #
def test_warn_during_voltage_scan_safe_holds_with_hv_held(make_ctrl):
    """WARN in an IV sweep → safe-hold PAUSE, HV HELD at the last set point
    (ratified: WARN never de-energizes), operator prompt carries the numbers."""
    dm, ctrl, sm = make_ctrl([
        _flat_channel("temperature_C", "C", nominal=31.0,
                      warn_high=30.0, alarm_high=35.0),
    ])
    prompts: list = []
    ctrl.on_manual_pause = lambda p: prompts.append(p)
    bias = dm.bias_supply

    ctrl.start_voltage_scan(_vscan())

    assert _wait_state(sm, AppState.PAUSED), "WARN must safe-hold the IV sweep"
    assert len(prompts) == 1
    reason = prompts[0]
    assert "temperature_C" in reason and "31" in reason and "30" in reason
    assert "warn" in reason.lower() and "held" in reason.lower()
    # HV is HELD, not ramped down: the output was never opened by the hold.
    assert ctrl._abort_event.is_set() is False

    ctrl.resume()
    _join(ctrl)
    assert sm.state is AppState.FINISHED
    assert len(prompts) == 1                      # latched — no re-pause storm
    assert bias.setpoint_V == 0.0                 # clean end still ramps down


def test_alarm_during_voltage_scan_failsafe_aborts_with_hv_at_zero(make_ctrl):
    """ALARM in an IV sweep → full fail-safe abort: HV ramped to 0 V, output
    open, ABORTED, and the points taken before the alarm are preserved."""
    dm, ctrl, sm = make_ctrl([
        _flat_channel("temperature_C", "C", nominal=25.0,
                      warn_high=30.0, alarm_high=35.0),
    ])
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)
    bias = dm.bias_supply
    bias.ramp_to = mock.Mock(wraps=bias.ramp_to)

    # First sample OK (point 0 saved), then ALARM.
    calls = {"n": 0}
    sc = dm.slow_control.channels[0]

    def escalating():
        calls["n"] += 1
        return 25.0 if calls["n"] == 1 else 40.0        # 40 >= alarm_high 35
    sc.read = escalating

    ctrl.start_voltage_scan(_vscan())
    _join(ctrl)

    assert sm.state is AppState.ABORTED
    assert bias.setpoint_V == 0.0                                  # HV down
    assert not bias.driver.output_is_on_ch(bias.channel)           # output open
    assert any(c.args and c.args[0] == 0.0 for c in bias.ramp_to.call_args_list)
    assert errs and "alarm" in errs[-1].lower()
    assert "temperature_C" in errs[-1] and "40" in errs[-1] and "35" in errs[-1]
    # Data already taken survives the fail-safe abort (writer flushed + closed).
    assert ctrl._writer._voltage_n >= 1
    assert ctrl.last_run_path is not None


def test_alarm_during_z_focus_failsafe_aborts_with_hv_at_zero(make_ctrl):
    """The z-focus loops drive no HV, but the DUT is biased — an ALARM must
    still de-energize the supply and abort (ratified policy is run-type blind)."""
    dm, ctrl, sm = make_ctrl([
        _flat_channel("humidity_pct", "%RH", nominal=80.0,
                      warn_high=60.0, alarm_high=70.0),
    ])
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)
    bias = dm.bias_supply
    bias.ramp_to(-50.0, step_V=25.0, delay_s=0.0)     # DUT biased before the scan
    assert bias.setpoint_V == -50.0

    ctrl.start_z_focus_scan(_zfocus())
    _join(ctrl)

    assert sm.state is AppState.ABORTED
    assert bias.setpoint_V == 0.0                                  # HV ramped down
    assert not bias.driver.output_is_on_ch(bias.channel)
    assert errs and "humidity_pct" in errs[-1] and "alarm" in errs[-1].lower()


def test_warn_during_z_focus_edge_safe_holds(make_ctrl):
    """Edge-scan focus mode honours the WARN safe-hold too (it was equally
    interlock-free)."""
    dm, ctrl, sm = make_ctrl([
        _flat_channel("temperature_C", "C", nominal=31.0, warn_high=30.0),
    ])
    prompts: list = []
    ctrl.on_manual_pause = lambda p: prompts.append(p)

    ctrl.start_z_focus_scan(_zfocus(
        mode="edge_scan", x_edge_center_mm=0.0,
        x_edge_range_mm=0.01, x_edge_step_mm=0.005,
    ))

    assert _wait_state(sm, AppState.PAUSED), "WARN must safe-hold the edge scan"
    assert prompts and "temperature_C" in prompts[0]

    ctrl.resume()
    _join(ctrl)
    assert sm.state is AppState.FINISHED
    assert len(prompts) == 1                      # latched — no re-pause storm


# =========================================================================== #
# FINDING 2 — a compliance trip is an ABORT, never a clean FINISHED            #
# =========================================================================== #
def test_compliance_trip_in_voltage_scan_settles_aborted(make_ctrl):
    """A trip must set the abort event so the run settles ABORTED; it used to
    log + on_error + break, and _settle_terminal_state then said FINISHED."""
    dm, ctrl, sm = make_ctrl()
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)
    points: list = []
    ctrl.on_vscan_point = lambda v, c, i: points.append(v)
    bias = dm.bias_supply

    calls = {"n": 0}

    def tripping_read():
        calls["n"] += 1
        # 1st point clean (saved), the 2nd setpoint trips compliance.
        return BiasReading(voltage_V=-10.0 * (calls["n"] - 1),
                           current_A=2e-6, compliant=calls["n"] >= 2)
    bias.read = tripping_read

    ctrl.start_voltage_scan(_vscan())
    _join(ctrl)

    assert sm.state is AppState.ABORTED, "a trip must NOT be reported as FINISHED"
    assert ctrl._abort_event.is_set()
    assert errs and "compliance" in errs[-1].lower()
    assert len(points) == 1                       # data taken before the trip kept
    assert bias.setpoint_V == 0.0                 # HV left safe
    assert not bias.driver.output_is_on_ch(bias.channel)


def test_viewer_paints_fault_not_green_finish_on_trip(make_ctrl):
    """End-to-end: a compliance trip in a real (simulated) voltage scan must not
    leave the cockpit showing the green "Scan finished — map retained." banner.

    The wiring here mirrors the composition root plus the ONE line it still owes
    (``coord.error_dialog.connect(viewer.on_scan_error)``) — the coordinator
    already carries every run fault on ``error_dialog``.
    """
    app = QApplication.instance() or QApplication([])
    dm, ctrl, sm = make_ctrl()
    coord = ScanCoordinator(ctrl, sm, AutoConfirmGate(), _limits)
    viewer = ScanViewerPanel()
    coord.scan_started.connect(viewer.on_scan_started)
    coord.scan_finished.connect(viewer.on_scan_finished)
    coord.progress.connect(viewer.on_progress)
    coord.error_dialog.connect(viewer.on_scan_error)   # <- composition-root TODO

    bias = dm.bias_supply
    bias.read = lambda: BiasReading(voltage_V=-10.0, current_A=2e-6, compliant=True)

    coord.start_voltage_scan(_vscan())
    deadline = time.time() + 20.0
    while ctrl._thread is not None and ctrl._thread.is_alive():
        app.processEvents()
        time.sleep(0.005)
        assert time.time() < deadline, "voltage scan did not finish"
    for _ in range(50):
        app.processEvents()
        time.sleep(0.002)

    assert sm.state is AppState.ABORTED
    assert viewer._fault_pending is True
    assert viewer._chip_finished.text() == "Fault"
    assert viewer._chip_finished.property("state") == "crit"
    assert viewer._chip_run.text() == "Fault"
    assert "map retained." != viewer._lbl_finished.text()
    assert "fault" in viewer._lbl_finished.text().lower()
    assert "Scan finished" not in viewer._lbl_finished.text()


def test_viewer_still_paints_green_on_a_clean_finish(make_ctrl):
    """Guard against over-correction: a clean run still reads FINISHED/good."""
    QApplication.instance() or QApplication([])
    viewer = ScanViewerPanel()
    viewer.on_scan_started()
    viewer.on_progress(3, 3)
    viewer.on_scan_finished()
    assert viewer._chip_finished.text() == "Finished"
    assert viewer._chip_finished.property("state") == "good"
    assert viewer._lbl_finished.text() == "Scan finished — map retained."


# =========================================================================== #
# FINDING 5 — abort mid-ramp does not complete another acquisition             #
# =========================================================================== #
def test_abort_during_ramp_does_not_acquire_another_point(make_ctrl):
    """``ramp_to`` is a blocking driver loop with no abort check; an Abort landing
    inside it used to dwell + acquire a full point (continued HV increase) before
    breaking on the NEXT iteration."""
    dm, ctrl, sm = make_ctrl()
    points: list = []
    ctrl.on_vscan_point = lambda v, c, i: points.append(v)
    bias = dm.bias_supply

    real_ramp = bias.ramp_to
    calls = {"n": 0}

    def aborting_ramp(target_V, **kw):
        calls["n"] += 1
        real_ramp(target_V, **kw)
        if calls["n"] == 2:                  # operator hits Abort DURING the ramp
            ctrl.abort()
    bias.ramp_to = aborting_ramp

    # Long dwell: without the post-ramp abort check the loop would sleep here and
    # then acquire — with it, the loop breaks immediately.
    ctrl.start_voltage_scan(_vscan(hold_delay_s=1.0))
    _join(ctrl)

    assert sm.state is AppState.ABORTED
    assert len(points) == 1, (
        "abort during the ramp must not complete another acquisition "
        f"(got points at {points})")
    assert bias.setpoint_V == 0.0
    assert not bias.driver.output_is_on_ch(bias.channel)


# =========================================================================== #
# FINDING 4 — the z-focus loops report progress (honest tiles + real ETA)      #
# =========================================================================== #
def test_z_focus_reports_progress(make_ctrl):
    dm, ctrl, sm = make_ctrl()
    progress: list = []
    ctrl.on_progress = lambda d, t: progress.append((d, t))

    ctrl.start_z_focus_scan(_zfocus(z_start_mm=0.0, z_stop_mm=0.2, z_step_mm=0.1))
    _join(ctrl)

    assert sm.state is AppState.FINISHED
    assert progress == [(1, 3), (2, 3), (3, 3)]


def test_z_focus_edge_reports_progress(make_ctrl):
    dm, ctrl, sm = make_ctrl()
    progress: list = []
    ctrl.on_progress = lambda d, t: progress.append((d, t))

    ctrl.start_z_focus_scan(_zfocus(
        mode="edge_scan", z_start_mm=0.0, z_stop_mm=0.1, z_step_mm=0.1,
        x_edge_center_mm=0.0, x_edge_range_mm=0.01, x_edge_step_mm=0.005,
    ))
    _join(ctrl)

    assert sm.state is AppState.FINISHED
    assert progress == [(1, 2), (2, 2)]


def test_progress_tile_is_stale_until_the_first_progress_lands():
    """Law 8: "0/0" is not a measurement — the tile must not be painted crisp
    before any run has reported progress (the ETA tile next to it already was
    honest)."""
    QApplication.instance() or QApplication([])
    viewer = ScanViewerPanel()
    viewer.on_scan_started()
    assert viewer._metric_progress.value() == "0/0"
    assert viewer._metric_progress.is_stale() is True

    viewer.on_progress(1, 4)
    assert viewer._metric_progress.value() == "1/4"
    assert viewer._metric_progress.is_stale() is False


# =========================================================================== #
# FINDING 6 — a run parked at HV is SUPERVISED (watchdog), not left blind      #
# =========================================================================== #
def test_paused_run_at_hv_failsafe_aborts_on_alarm(make_ctrl):
    """A paused run HOLDS HV (ratified). While parked the worker must keep
    polling compliance + slow control: an ALARM raised *during the pause* is a
    full fail-safe abort, not an indefinite sit at high voltage."""
    dm, ctrl, sm = make_ctrl([
        _flat_channel("temperature_C", "C", nominal=25.0,
                      warn_high=30.0, alarm_high=35.0),
    ])
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)
    first_point = threading.Event()
    ctrl.on_vscan_point = lambda v, c, i: first_point.set()
    bias = dm.bias_supply

    # Slow dwell so the run is still in flight when we pause it.
    ctrl.start_voltage_scan(_vscan(v_stop_V=-40.0, hold_delay_s=0.3))
    assert first_point.wait(timeout=20.0), "no IV point acquired"

    ctrl.pause()
    assert _wait_state(sm, AppState.PAUSED)
    # HV is HELD at the last commanded set point across the pause.
    assert bias.setpoint_V != 0.0

    # The environment goes bad WHILE parked — nothing else is watching.
    sc = dm.slow_control.channels[0]
    sc.read = lambda: 40.0                         # >= alarm_high 35

    assert _wait_state(sm, AppState.ABORTED, timeout=10.0), (
        "the paused-at-HV watchdog must fail-safe abort on ALARM")
    _join(ctrl)
    assert bias.setpoint_V == 0.0                              # HV ramped down
    assert not bias.driver.output_is_on_ch(bias.channel)       # output open
    assert errs and "alarm" in errs[-1].lower()
    assert ctrl.last_run_path is not None                      # writer flushed


def test_paused_run_at_hv_failsafe_aborts_on_compliance_trip(make_ctrl):
    """Same watchdog, other guard: a compliance trip while parked aborts too."""
    dm, ctrl, sm = make_ctrl()
    errs: list = []
    ctrl.on_error = lambda m: errs.append(m)
    first_point = threading.Event()
    ctrl.on_vscan_point = lambda v, c, i: first_point.set()
    bias = dm.bias_supply

    ctrl.start_voltage_scan(_vscan(v_stop_V=-40.0, hold_delay_s=0.3))
    assert first_point.wait(timeout=20.0), "no IV point acquired"

    ctrl.pause()
    assert _wait_state(sm, AppState.PAUSED)

    # The DUT starts drawing compliance current while the run sits at HV.
    bias.read = lambda: BiasReading(voltage_V=-20.0, current_A=2e-6, compliant=True)

    assert _wait_state(sm, AppState.ABORTED, timeout=10.0), (
        "a compliance trip while parked must fail-safe abort")
    _join(ctrl)
    assert bias.setpoint_V == 0.0
    assert not bias.driver.output_is_on_ch(bias.channel)
    assert errs and "compliance" in errs[-1].lower()


def test_paused_run_stays_paused_while_the_environment_is_fine(make_ctrl):
    """The watchdog must not be trigger-happy: a healthy paused run keeps
    holding HV and resumes to a clean FINISHED."""
    dm, ctrl, sm = make_ctrl([
        _flat_channel("temperature_C", "C", nominal=25.0,
                      warn_high=30.0, alarm_high=35.0),
    ])
    first_point = threading.Event()
    ctrl.on_vscan_point = lambda v, c, i: first_point.set()

    ctrl.start_voltage_scan(_vscan(v_stop_V=-40.0, hold_delay_s=0.2))
    assert first_point.wait(timeout=20.0)

    ctrl.pause()
    assert _wait_state(sm, AppState.PAUSED)
    time.sleep(0.3)                        # several supervision sweeps
    assert sm.state is AppState.PAUSED     # still parked, still holding HV
    assert not ctrl._abort_event.is_set()

    ctrl.resume()
    _join(ctrl)
    assert sm.state is AppState.FINISHED


# =========================================================================== #
# FINDING 3 — terminal settling is race-safe (a clean run is never an ERROR)   #
# =========================================================================== #
def test_settle_terminal_state_survives_a_resume_race(make_ctrl):
    """A GUI resume() landing between the PAUSED->RUNNING promotion and the
    RUNNING->FINISHED transition used to raise ValueError inside the loop's
    except path, reporting a CLEAN run as ERROR("Invalid transition")."""
    dm, ctrl, sm = make_ctrl()
    sm.transition(AppState.RUNNING)
    ctrl._pause_event.clear()
    sm.transition(AppState.PAUSED)

    original = sm.transition
    raced = {"done": False}

    def racing_transition(target):
        original(target)
        # The instant the worker promotes PAUSED->RUNNING, a GUI resume() lands.
        if target is AppState.RUNNING and not raced["done"]:
            raced["done"] = True
            ctrl.resume()                  # no-op on state, but exercises the edge
            original(AppState.PAUSED)      # ... and the operator re-pauses
    sm.transition = racing_transition      # type: ignore[method-assign]

    ctrl._settle_terminal_state()

    assert sm.state is AppState.FINISHED   # converged, never raised


def test_settle_error_state_never_swallows_the_fault(make_ctrl):
    """A fault raised while PAUSED must still reach a terminal state, and the
    on_error message must have been delivered BEFORE the settle (so a settle
    race can never hide the original fault)."""
    dm, ctrl, sm = make_ctrl()
    sm.transition(AppState.RUNNING)
    sm.transition(AppState.PAUSED)

    ctrl._settle_error_state()
    assert sm.state is AppState.ERROR      # promoted PAUSED->RUNNING->ERROR

    # And from a terminal state it is a no-op, never a raise.
    ctrl._settle_error_state()
    assert sm.state is AppState.ERROR
