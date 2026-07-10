"""Headless wiring-contract tests for the Scan Viewer (S2c).

These lock in that ``tct_gui.TCTMainWindow`` wires ``gui.scan_coordinator``
into ``gui.scan_viewer_panel.ScanViewerPanel`` correctly — the step that
retired ``ScanPanel``. They deliberately **mirror the exact connections the
composition root makes** (see ``_wire_like_tct_gui`` below); if that wiring
changes in ``tct_gui``, this file must change with it.

Three things are proved:

* the coordinator's run signals reach the viewer's slots (map / progress /
  chip) for a real, fully-*simulated* ScanController on a background thread,
  and a run-path publisher (replicating ``_publish_last_run_path``) enables
  "Open in Analysis" once the run finishes;
* the viewer's run-control signals (pause / abort) route back into the
  coordinator and reach the scanner (deterministic ``FakeScanner``);
* Rule-8 detach/re-dock: the viewer survives being torn off into a floating
  window and re-docked without being destroyed or losing its connections.

Idiom follows ``tests/test_scan_coordinator.py`` and the other gui tests:
``QT_QPA_PLATFORM=offscreen``, a shared ``QApplication.instance()``, no
pytest-qt, simulated backends only.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import yaml
from PySide6.QtWidgets import QApplication

from controller.device_manager import DeviceManager
from controller.state_machine import StateMachine, AppState
from controller.scan_controller import (
    ScanController, ScanConfig, ScanPoint, ScanResult,
)
from controller.scan_plan_validator import PlanLimits
from controller.danger_gate import AutoConfirmGate
from gui.detachable_tabs import DetachableTabWidget
from gui.scan_coordinator import ScanCoordinator
from gui.scan_viewer_panel import ScanViewerPanel


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
    coordinator's queued bridge signals are actually delivered."""
    deadline = time.time() + timeout
    while ctrl._thread is not None and ctrl._thread.is_alive():
        app.processEvents()
        time.sleep(0.005)
        if time.time() > deadline:
            raise AssertionError("scan thread did not finish in time")
    for _ in range(50):
        app.processEvents()
        time.sleep(0.002)


def _result(x: float, y: float, *, charge: float = 1.0, index: int = 0) -> ScanResult:
    return ScanResult(
        point=ScanPoint(x_mm=x, y_mm=y, z_mm=0.0, index=index),
        timestamp=0.0,
        ref_amplitude_V=0.5,
        ref_charge_pC=2.0,
        dut_amplitude_V=0.3,
        dut_charge_pC=charge,
        dut_charge_norm=charge / 2.0,
        baseline_rms_V=0.001,
        drift_time_s=1e-9,
        rise_time_s=2e-9,
        cfd_time_s=3e-9,
    )


class FakeScanner:
    """Minimal stand-in that records control calls (no threads, no hardware) —
    same shape as ``tests/test_scan_coordinator.py``'s FakeScanner."""

    def __init__(self) -> None:
        self.on_point_done = None
        self.on_progress = None
        self.on_finished = None
        self.on_error = None
        self.on_vscan_point = None
        self.on_manual_pause = None
        self.calls: list = []
        self.last_run_path = None

    def start(self, cfg):
        self.calls.append(("start", cfg))

    def start_z_focus_scan(self, cfg, on_point=None, on_done=None):
        self.calls.append(("z_focus", cfg))

    def start_voltage_scan(self, cfg):
        self.calls.append(("vscan", cfg))

    def start_plan(self, plan, limits, gate):
        self.calls.append(("start_plan", plan))

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
        AppState.CONNECTED: [AppState.CONNECTED],
        AppState.READY: [AppState.CONNECTED, AppState.HOMED,
                         AppState.CONFIGURED, AppState.READY],
    }[state]
    for st in path:
        sm.transition(st)
    fake = FakeScanner()
    coord = ScanCoordinator(fake, sm, AutoConfirmGate(), lambda: _limits())
    return coord, fake, sm


def _wire_like_tct_gui(coord: ScanCoordinator, viewer: ScanViewerPanel, scanner):
    """Mirror EXACTLY the coordinator<->viewer connections
    ``tct_gui.TCTMainWindow._build_central`` makes. This is the wiring
    contract — keep it in lock-step with the composition root.

    Returns ``(publish, opened_spy)`` where *publish* is the standalone
    equivalent of ``_publish_last_run_path`` and *opened_spy* records the
    "Open in Analysis" hand-off path.
    """
    # Coordinator → viewer.
    coord.point_done.connect(viewer.on_point_done)
    coord.progress.connect(viewer.on_progress)
    coord.scan_started.connect(viewer.on_scan_started)
    coord.scan_finished.connect(viewer.on_scan_finished)

    def publish() -> None:
        p = scanner.last_run_path
        viewer.set_last_run_path(str(p) if p else None)

    # Publisher wired AFTER on_scan_finished so the viewer's run-active flag is
    # already cleared when set_last_run_path enables the button (order matters).
    coord.scan_finished.connect(publish)
    coord.manual_pause.connect(viewer.on_manual_pause)
    coord.z_focus_pt.connect(viewer.on_z_focus_pt)
    coord.z_focus_done.connect(viewer.on_z_focus_done)

    # Viewer → coordinator (live run control only; Z-focus is the one start
    # path the viewer owns).
    viewer.pause_requested.connect(coord.toggle_pause)
    viewer.abort_requested.connect(coord.abort)
    viewer.z_focus_requested.connect(coord.start_z_focus)

    opened = Spy(viewer.open_in_analysis_requested)
    return publish, opened


# --------------------------------------------------------------------------- #
# (1) coordinator → viewer: full run flow + run-path handoff                    #
# --------------------------------------------------------------------------- #
def test_run_flow_reaches_viewer_and_enables_open_in_analysis(tmp_path):
    app = _app()
    dm, sm, ctrl = _ready_sim(tmp_path)
    try:
        coord = ScanCoordinator(ctrl, sm, AutoConfirmGate(), lambda: _limits())
        viewer = ScanViewerPanel()
        _publish, opened = _wire_like_tct_gui(coord, viewer, ctrl)

        # 2-point (x) × 1 (y) raster on the simulated stack.
        cfg = ScanConfig(x_start_mm=0.0, x_stop_mm=0.1, x_step_mm=0.1,
                         y_start_mm=0.0, y_stop_mm=0.0, y_step_mm=0.1,
                         n_averages=1, settle_time_s=0.0)
        coord.start_scan(cfg)
        _drain(app, ctrl)

        assert sm.state is AppState.FINISHED
        # Map accumulated both points through the coordinator's point_done.
        assert viewer._map_view.point_count() == 2
        # Progress metric shows the last (done, total).
        assert viewer._metric_progress.value() == "2/2"
        # Run chip settled on the finished state.
        assert viewer._chip_run.text() == "Finished"

        # The run-path publisher (mirroring _publish_last_run_path) handed the
        # written HDF5 path to the viewer, enabling "Open in Analysis".
        assert ctrl.last_run_path is not None
        assert viewer._btn_open_analysis.isEnabled() is True

        # Clicking it emits the just-written run path for the Analysis hand-off.
        viewer._btn_open_analysis.click()
        assert opened.last == (str(ctrl.last_run_path),)
    finally:
        dm.disconnect_all()


# --------------------------------------------------------------------------- #
# (1b) plan runs drive the viewer's run-active state (Mary S2c finding)         #
# --------------------------------------------------------------------------- #
def test_plan_run_drives_viewer_run_active_state():
    """After S2c a planner-launched run is the ONLY GUI raster path — it must
    engage the viewer's cockpit (map clear, Pause/Abort enable, chip, stale
    handoff invalidation) exactly like a classic start. Locks in the
    scan_started emit on ScanCoordinator.start_plan's success path."""
    app = _app()
    coord, fake, sm = _fake_coord(AppState.READY)
    viewer = ScanViewerPanel()
    _wire_like_tct_gui(coord, viewer, fake)

    # Stale state from an earlier run: painted map + a known handoff path.
    viewer.on_scan_started()
    viewer.on_point_done(_result(0.0, 0.0, charge=1.0))
    viewer.on_scan_finished()
    viewer.set_last_run_path("C:/data/run_00001/scan.h5")
    assert viewer._map_view.point_count() == 1
    assert viewer._btn_open_analysis.isEnabled()

    coord.start_plan(object())
    assert fake.names[-1] == "start_plan"
    assert coord.plan_run_active is True
    assert viewer._run_active is True
    assert viewer._btn_pause.isEnabled()
    assert viewer._btn_abort.isEnabled()
    assert viewer._chip_run.text() == "Running"
    assert viewer._map_view.point_count() == 0      # stale points cleared
    assert viewer._last_run_path is None            # stale handoff invalidated
    assert not viewer._btn_open_analysis.isEnabled()

    # Terminal via the bridge: viewer releases run-active and the publisher
    # hands over the freshly written path.
    fake.last_run_path = "C:/data/run_00002/scan.h5"
    coord._bridge.finished.emit()
    app.processEvents()
    assert viewer._run_active is False
    assert not viewer._btn_abort.isEnabled()
    assert viewer._btn_open_analysis.isEnabled()
    viewer._btn_open_analysis.click()


def test_refused_plan_start_does_not_paint_running_cockpit():
    """A refused start (state machine cannot enter RUNNING) must not fire
    scan_started — the cockpit stays idle and un-armed (fail-closed)."""
    _app()
    coord, fake, sm = _fake_coord(AppState.CONNECTED)
    viewer = ScanViewerPanel()
    _wire_like_tct_gui(coord, viewer, fake)
    warn = Spy(coord.warn_dialog)

    coord.start_plan(object())

    assert warn.count == 1
    assert viewer._run_active is False
    assert not viewer._btn_pause.isEnabled()
    assert not viewer._btn_abort.isEnabled()
    assert ("arm_hv", False) in fake.calls          # refusal un-arms (contract)


def test_raised_plan_start_does_not_paint_running_cockpit():
    """A start that raises in the controller must not fire scan_started."""
    _app()
    coord, fake, sm = _fake_coord(AppState.READY)
    viewer = ScanViewerPanel()
    _wire_like_tct_gui(coord, viewer, fake)
    err = Spy(coord.error_dialog)

    def boom(plan, limits, gate):
        raise RuntimeError("refused by controller")
    fake.start_plan = boom

    coord.start_plan(object())

    assert err.count == 1
    assert viewer._run_active is False
    assert not viewer._btn_abort.isEnabled()


# --------------------------------------------------------------------------- #
# (2) viewer → coordinator: pause / abort round-trip reaches the scanner        #
# --------------------------------------------------------------------------- #
def test_pause_and_abort_round_trip_to_scanner():
    _app()
    coord, fake, sm = _fake_coord(AppState.READY)
    viewer = ScanViewerPanel()
    _wire_like_tct_gui(coord, viewer, fake)

    # A run must be active for the viewer to forward run-control toggles.
    viewer.on_scan_started()

    viewer._btn_pause.setChecked(True)     # → pause_requested(True) → toggle_pause
    assert fake.names == ["pause"]

    viewer._btn_pause.setChecked(False)    # → pause_requested(False) → resume
    assert fake.names == ["pause", "resume"]

    viewer._btn_abort.click()              # → abort_requested → abort
    assert fake.names == ["pause", "resume", "abort"]


# --------------------------------------------------------------------------- #
# (3) Rule-8 detach / re-dock regression                                        #
# --------------------------------------------------------------------------- #
def test_viewer_survives_detach_and_redock_with_live_signals():
    app = _app()
    coord, fake, sm = _fake_coord(AppState.READY)
    viewer = ScanViewerPanel()
    # Only the streaming connection is needed to prove the signal survives.
    coord.point_done.connect(viewer.on_point_done)

    tabs = DetachableTabWidget()
    tabs.addTab(viewer, "Scan Viewer")
    assert tabs.count() == 1

    # Detach into a floating window.
    tabs.detach(0)
    assert tabs.count() == 0
    assert "Scan Viewer" in tabs.detached_titles()
    win, content, _idx = tabs._detached["Scan Viewer"]
    assert content is viewer

    # Feed a point while detached — the widget still renders, and its slot is
    # still reachable through the coordinator (queued/direct via the bridge).
    coord._bridge.point_done.emit(_result(0.0, 0.0, charge=1.0))
    app.processEvents()
    assert viewer._map_view.point_count() == 1

    # Re-dock by closing the floating window (the DetachableTabWidget contract).
    win.close()
    app.processEvents()
    assert tabs.count() == 1
    # The very same widget object came back — reparented, not destroyed.
    assert tabs.widget(0) is viewer

    # Connections survived the reparent: a further point still lands.
    coord._bridge.point_done.emit(_result(1.0, 0.0, charge=2.0))
    app.processEvents()
    assert viewer._map_view.point_count() == 2
