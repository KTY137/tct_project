"""Headless tests for gui.scan_coordinator.ScanCoordinator.

The coordinator is the run-control glue extracted from ``tct_gui`` (build-order
step 4 of the Scan Viewer). These tests prove the extraction is
behaviour-preserving:

* start → progress → finished signal flow for a classic scan (real, fully
  *simulated* ScanController on a background thread, marshalled through the
  coordinator's bridge onto the Qt main thread);
* the same for a plan run, and that a plan run additionally drives the planner
  signals (``plan_progress`` / ``plan_finished``) while a classic run does not
  (the ``_plan_run_active`` dual-dispatch gate);
* pause / resume / abort / arm-HV / manual-pause routing (deterministic, via a
  fake scanner that records calls);
* refused starts emit the warning dialog + never leave HV armed.

Idiom follows the existing gui tests: ``QT_QPA_PLATFORM=offscreen``, a shared
``QApplication.instance()``, no pytest-qt. No real ``QMessageBox`` is shown —
the coordinator only *emits* dialog-request signals; the tests spy on them.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import pytest
import yaml
from PySide6.QtWidgets import QApplication

from controller.device_manager import DeviceManager
from controller.state_machine import StateMachine, AppState
from controller.scan_controller import ScanController, ScanConfig
from controller.scan_plan import ActionBlock, ActionType, Axis, LoopBlock, ScanPlan
from controller.scan_plan_validator import PlanLimits
from controller.danger_gate import AutoConfirmGate
from gui.scan_coordinator import ScanCoordinator, _ScanBridge


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class Spy:
    """Records every emission of a Qt signal as a tuple of its arguments."""

    def __init__(self, signal) -> None:
        self.calls: list = []
        signal.connect(lambda *a: self.calls.append(a))

    @property
    def count(self) -> int:
        return len(self.calls)

    @property
    def last(self):
        return self.calls[-1]


def _limits(**over) -> PlanLimits:
    d = dict(
        x_min_mm=-50.0, x_max_mm=50.0,
        y_min_mm=-50.0, y_max_mm=50.0,
        z_min_mm=-10.0, z_max_mm=10.0,
        voltage_range_V=1000.0, max_points=1_000_000,
    )
    d.update(over)
    return PlanLimits(**d)


def _sim_config_path(tmp_path) -> str:
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


def _ready_sim(tmp_path):
    """Return ``(dm, sm, ctrl)`` on fully-simulated backends, state READY."""
    dm = DeviceManager(config_path=_sim_config_path(tmp_path))
    assert dm.config_errors() == []
    assert all(v == "ok" for v in dm.connect_all().values())
    dm.motor.zero_position()             # homed without moving
    sm = StateMachine()
    for st in (AppState.CONNECTED, AppState.HOMED, AppState.CONFIGURED, AppState.READY):
        sm.transition(st)
    ctrl = ScanController(dm, sm)
    return dm, sm, ctrl


def _drain(app, ctrl, timeout=30.0) -> None:
    """Join the scan worker thread while pumping the Qt event loop so the
    coordinator's queued bridge signals are actually delivered, then flush any
    signals emitted right at completion."""
    deadline = time.time() + timeout
    while ctrl._thread is not None and ctrl._thread.is_alive():
        app.processEvents()
        time.sleep(0.005)
        if time.time() > deadline:
            raise AssertionError("scan thread did not finish in time")
    for _ in range(50):
        app.processEvents()
        time.sleep(0.002)


def _stage_plan(values):
    """An x-only stage raster: acquire + save at each x.  No bias → no arm."""
    loop = LoopBlock(
        axis=Axis.STAGE_X, values=[float(v) for v in values],
        children=[ActionBlock(action=ActionType.ACQUIRE_WAVEFORM, params={}),
                  ActionBlock(action=ActionType.SAVE_POINT, params={})],
    )
    return ScanPlan(name="stage", root=[loop])


class FakeScanner:
    """Minimal stand-in that records control calls (no threads, no hardware).

    Used for the routing / gating tests where a real background run would only
    add nondeterminism.  Carries the same ``on_*`` callback attributes the real
    ScanController exposes so the coordinator can wire its bridge to them.
    """

    def __init__(self) -> None:
        self.on_point_done = None
        self.on_progress = None
        self.on_finished = None
        self.on_error = None
        self.on_vscan_point = None
        self.on_manual_pause = None
        self.calls: list = []
        # Per-entry-point RuntimeError injection — models the controller's
        # fail-closed _refuse_if_active() raising while PAUSED / worker alive.
        self.start_raises: Exception | None = None
        self.start_z_focus_raises: Exception | None = None
        self.start_voltage_raises: Exception | None = None
        self.start_plan_raises: Exception | None = None

    def start(self, cfg):
        self.calls.append(("start", cfg))
        if self.start_raises is not None:
            raise self.start_raises

    def start_z_focus_scan(self, cfg, on_point=None, on_done=None):
        self.calls.append(("z_focus", cfg))
        if self.start_z_focus_raises is not None:
            raise self.start_z_focus_raises

    def start_voltage_scan(self, cfg):
        self.calls.append(("vscan", cfg))
        if self.start_voltage_raises is not None:
            raise self.start_voltage_raises

    def start_plan(self, plan, limits, gate):
        self.calls.append(("start_plan", plan))
        if self.start_plan_raises is not None:
            raise self.start_plan_raises

    def pause(self):
        self.calls.append(("pause",))

    def resume(self):
        self.calls.append(("resume",))

    def abort(self):
        self.calls.append(("abort",))

    def arm_hv(self, confirmed):
        self.calls.append(("arm_hv", confirmed))

    @property
    def names(self) -> list[str]:
        return [c[0] for c in self.calls]


def _fake_coord(state=AppState.READY):
    """Coordinator on a FakeScanner + a StateMachine driven to *state*."""
    sm = StateMachine()
    path = {
        AppState.DISCONNECTED: [],
        AppState.CONNECTED: [AppState.CONNECTED],
        AppState.READY: [AppState.CONNECTED, AppState.HOMED,
                         AppState.CONFIGURED, AppState.READY],
    }[state]
    for st in path:
        sm.transition(st)
    fake = FakeScanner()
    coord = ScanCoordinator(fake, sm, AutoConfirmGate(), lambda: _limits())
    return coord, fake, sm


# --------------------------------------------------------------------------- #
# (1) classic scan: start → progress → finished, no planner leak               #
# --------------------------------------------------------------------------- #
def test_classic_scan_signal_flow(tmp_path):
    app = _app()
    dm, sm, ctrl = _ready_sim(tmp_path)
    try:
        coord = ScanCoordinator(ctrl, sm, AutoConfirmGate(), lambda: _limits())
        started = Spy(coord.scan_started)
        points = Spy(coord.point_done)
        progress = Spy(coord.progress)
        finished = Spy(coord.scan_finished)
        plan_prog = Spy(coord.plan_progress)
        plan_fin = Spy(coord.plan_finished)

        # 2-point (x) × 1 (y) raster.
        cfg = ScanConfig(x_start_mm=0.0, x_stop_mm=0.1, x_step_mm=0.1,
                         y_start_mm=0.0, y_stop_mm=0.0, y_step_mm=0.1,
                         n_averages=1, settle_time_s=0.0)
        coord.start_scan(cfg)
        assert coord.plan_run_active is False
        _drain(app, ctrl)

        assert sm.state is AppState.FINISHED
        assert started.count == 1
        assert points.count == 2
        assert progress.last == (2, 2)
        assert finished.count == 1
        # A classic run must NOT leak into the planner dispatch.
        assert plan_prog.count == 0
        assert plan_fin.count == 0
    finally:
        dm.disconnect_all()


# --------------------------------------------------------------------------- #
# (2) plan run: dispatches to planner AND the classic scan panel               #
# --------------------------------------------------------------------------- #
def test_plan_run_signal_flow(tmp_path):
    app = _app()
    dm, sm, ctrl = _ready_sim(tmp_path)
    try:
        coord = ScanCoordinator(ctrl, sm, AutoConfirmGate(), lambda: _limits())
        progress = Spy(coord.progress)          # classic fan-out
        finished = Spy(coord.scan_finished)     # classic fan-out
        plan_prog = Spy(coord.plan_progress)
        plan_fin = Spy(coord.plan_finished)
        plan_run = Spy(coord.plan_running)

        coord.start_plan(_stage_plan([0.0, 1.0]))
        assert coord.plan_run_active is True     # set on a successful start
        _drain(app, ctrl)

        assert sm.state is AppState.FINISHED
        assert coord.plan_run_active is False     # cleared at finish
        # Planner dispatch fired.
        assert plan_prog.count >= 1
        assert plan_prog.last == (2, 2)
        assert plan_fin.count == 1                # genuine FINISHED terminal
        assert plan_run.calls == []               # FINISHED path, not set_running
        # Classic fan-out fired too (byte-identical to pre-extraction behaviour).
        assert progress.last == (2, 2)
        assert finished.count == 1
    finally:
        dm.disconnect_all()


# --------------------------------------------------------------------------- #
# (3) refused classic start → warning, no start, HV untouched                  #
# --------------------------------------------------------------------------- #
def test_refused_classic_start_warns():
    _app()
    coord, fake, sm = _fake_coord(AppState.CONNECTED)   # cannot RUNNING
    warn = Spy(coord.warn_dialog)
    started = Spy(coord.scan_started)

    coord.start_scan(ScanConfig())

    assert warn.count == 1
    assert warn.last[0] == "Cannot Start"
    assert started.count == 0
    assert "start" not in fake.names
    assert sm.state is AppState.CONNECTED          # unchanged


def test_refused_zfocus_and_vscan_warn():
    _app()
    coord, fake, sm = _fake_coord(AppState.CONNECTED)
    warn = Spy(coord.warn_dialog)

    from controller.scan_controller import ZFocusScanConfig, VoltageScanConfig
    coord.start_z_focus(ZFocusScanConfig())
    coord.start_voltage_scan(VoltageScanConfig())

    assert warn.count == 2
    assert fake.names == []                         # nothing launched


# --------------------------------------------------------------------------- #
# (3b) controller-side fail-closed refusal (PAUSED / worker still alive):      #
#      the state gate passes but _refuse_if_active() raises RuntimeError.       #
#      Every start slot must surface it via error_dialog, NEVER paint a         #
#      running status/signal, and never let the exception escape the Qt slot.   #
# --------------------------------------------------------------------------- #
def test_zfocus_start_refused_by_controller_fails_closed():
    _app()
    coord, fake, sm = _fake_coord(AppState.READY)       # passes can(RUNNING)
    fake.start_z_focus_raises = RuntimeError(
        "A run is already active (paused or running).")
    err = Spy(coord.error_dialog)
    status = Spy(coord.status_message)

    from controller.scan_controller import ZFocusScanConfig
    coord.start_z_focus(ZFocusScanConfig())             # must not raise

    assert err.count == 1
    assert err.last[0] == "Z-focus scan refused"
    assert status.count == 0                            # never painted "running…"


def test_voltage_start_refused_by_controller_fails_closed():
    _app()
    coord, fake, sm = _fake_coord(AppState.READY)
    fake.start_voltage_raises = RuntimeError(
        "A run is already active (paused or running).")
    err = Spy(coord.error_dialog)
    status = Spy(coord.status_message)

    from controller.scan_controller import VoltageScanConfig
    coord.start_voltage_scan(VoltageScanConfig())       # must not raise

    assert err.count == 1
    assert err.last[0] == "Voltage scan refused"
    assert status.count == 0                            # never painted "running…"


def test_classic_start_refused_by_controller_fails_closed():
    _app()
    coord, fake, sm = _fake_coord(AppState.READY)
    fake.start_raises = RuntimeError(
        "A run is already active (paused or running).")
    err = Spy(coord.error_dialog)
    started = Spy(coord.scan_started)

    coord.start_scan(ScanConfig())                      # must not raise

    assert err.count == 1
    assert err.last[0] == "Scan refused"
    assert started.count == 0                           # never painted running


# --------------------------------------------------------------------------- #
# (4) pause / resume / abort routing                                           #
# --------------------------------------------------------------------------- #
def test_pause_resume_abort_routing():
    _app()
    coord, fake, sm = _fake_coord(AppState.READY)
    status = Spy(coord.status_message)

    coord.toggle_pause(True)
    coord.toggle_pause(False)
    coord.abort()
    coord.resume()

    assert fake.names == ["pause", "resume", "abort", "resume"]
    assert ("Scan paused",) in status.calls
    assert ("Scan resumed",) in status.calls


# --------------------------------------------------------------------------- #
# (5) arm-HV routing                                                           #
# --------------------------------------------------------------------------- #
def test_arm_hv_routing():
    _app()
    coord, fake, sm = _fake_coord(AppState.READY)
    armed = Spy(coord.hv_armed)

    coord.arm_hv()

    assert ("arm_hv", True) in fake.calls
    assert armed.last == (True,)


# --------------------------------------------------------------------------- #
# (6) plan start refused when not ready → un-arms, never launches              #
# --------------------------------------------------------------------------- #
def test_plan_start_not_ready_unarms():
    _app()
    coord, fake, sm = _fake_coord(AppState.CONNECTED)   # cannot RUNNING
    warn = Spy(coord.warn_dialog)
    armed = Spy(coord.hv_armed)

    coord.start_plan(_stage_plan([0.0]))

    assert warn.count == 1
    assert warn.last[0] == "Not ready"
    assert ("arm_hv", False) in fake.calls
    assert armed.last == (False,)
    assert "start_plan" not in fake.names
    assert coord.plan_run_active is False


def test_plan_start_exception_unarms():
    _app()
    coord, fake, sm = _fake_coord(AppState.READY)
    fake.start_plan_raises = RuntimeError("plan drives HV but HV is not armed")
    err = Spy(coord.error_dialog)
    armed = Spy(coord.hv_armed)
    started = Spy(coord.scan_started)

    coord.start_plan(_stage_plan([0.0]))

    assert err.count == 1
    assert err.last[0] == "Plan refused"
    assert armed.last == (False,)
    assert started.count == 0                        # never painted running cockpit
    assert coord.plan_run_active is False           # never set on a failed start


# --------------------------------------------------------------------------- #
# (7) dual-dispatch gate: classic progress never reaches the planner           #
# --------------------------------------------------------------------------- #
def test_classic_progress_not_leaked_to_planner():
    app = _app()
    coord, fake, sm = _fake_coord(AppState.READY)
    progress = Spy(coord.progress)
    plan_prog = Spy(coord.plan_progress)

    # No plan run active → a bridge progress tick reaches only the classic path.
    coord._bridge.progress.emit(1, 3)
    app.processEvents()

    assert progress.last == (1, 3)
    assert plan_prog.count == 0


# --------------------------------------------------------------------------- #
# (8) manual-pause prompt forwarded to the composition root                    #
# --------------------------------------------------------------------------- #
def test_manual_pause_forwarded():
    app = _app()
    coord, fake, sm = _fake_coord(AppState.READY)
    prompts = Spy(coord.manual_pause)

    coord._bridge.manual_pause.emit("swap the sample")
    app.processEvents()

    assert prompts.last == ("swap the sample",)


# --------------------------------------------------------------------------- #
# (9) scanner callbacks are wired to the coordinator's bridge                  #
# --------------------------------------------------------------------------- #
def test_scanner_callbacks_wired():
    _app()
    coord, fake, sm = _fake_coord(AppState.READY)
    # The coordinator must have installed its bridge emitters as the scanner's
    # callbacks (the cross-thread marshalling seam).
    assert callable(fake.on_point_done)
    assert callable(fake.on_progress)
    assert callable(fake.on_finished)
    assert callable(fake.on_error)
    assert callable(fake.on_vscan_point)
    assert callable(fake.on_manual_pause)
    assert isinstance(coord._bridge, _ScanBridge)
