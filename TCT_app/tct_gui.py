"""
TCT Setup — Main Window

Assembles all panels, wires the ScanController callbacks, and manages
the application state machine.  GUI panels reference only abstract
device interfaces so hardware swaps need no UI code changes.
"""
from __future__ import annotations

import logging
import os
import sys

from PySide6.QtCore import Qt, Slot, Signal, QObject, QThread, QTimer, QSettings, QUrl
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QTabWidget, QApplication, QStyle,
    QVBoxLayout, QHBoxLayout, QStatusBar, QToolBar, QSizePolicy,
    QPushButton, QLabel, QMessageBox, QFileDialog, QCheckBox,
    QFrame, QDockWidget, QPlainTextEdit, QScrollArea,
)

from gui.style import apply_theme
from gui.detachable_tabs import DetachableTabWidget

from controller.device_manager import DeviceManager
from controller.state_machine import StateMachine, AppState
from controller.scan_controller import ScanController

from gui.motor_panel import MotorPanel
from gui.intensity_panel import IntensityPanel
from gui.camera_panel import CameraPanel
from gui.scope_panel import ScopePanel
from gui.laser_panel import LaserPanel
from gui.scan_viewer_panel import ScanViewerPanel
from gui.multi_bias_panel import MultiBiasPanel
from gui.monitor_panel import MonitorPanel
from gui.analysis_panel import AnalysisPanel
from gui.calibration_panel import CalibrationPanel
from gui.device_panel import DeviceManagerWindow, device_state
from gui.liveness import LivenessMonitor
from gui.motion import ActivityRing, set_pulse
from gui.settings_window import SettingsWindow
from gui.status_bus import notify
from gui.status_widgets import StatusChip, StatusPill
from gui.planner_panel import PlannerPanel
from gui.qt_danger_gate import QtDangerGate
from gui.scan_coordinator import ScanCoordinator
from controller.scan_plan_validator import PlanLimits

logger = logging.getLogger(__name__)


def _scrollable(widget: QWidget) -> QScrollArea:
    """Wrap *widget* in a resizable scroll area.

    Keeps every tab usable on small / low-resolution screens: when a panel is
    taller or wider than the viewport the scroll bars appear instead of the
    content being cropped off the edge of the window.
    """
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setWidget(widget)
    return area


class _LogBridge(QObject):
    """Carries formatted log lines onto the Qt main thread."""
    record = Signal(str)


class _QtLogHandler(logging.Handler):
    """Logging handler that forwards records to a Qt signal (thread-safe)."""

    def __init__(self) -> None:
        super().__init__()
        self.bridge = _LogBridge()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.bridge.record.emit(self.format(record))
        except Exception:
            pass


class _QtDeviceDebugHandler(logging.Handler):
    """Logging handler that forwards raw device I/O to a Qt signal."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.bridge = _LogBridge()
        self._enabled = False

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def emit(self, record: logging.LogRecord) -> None:
        if not self._enabled:
            return
        try:
            self.bridge.record.emit(self.format(record))
        except Exception:
            pass


class _BgTask(QObject):
    """Runs one blocking callable off the GUI thread (connect/disconnect).

    Same pattern as MotorPanel._MotorTask: the call is carried into a worker
    QThread and the result (or error text) comes back via a queued signal, so
    multi-second VISA/serial connects never freeze the window.
    """
    done = Signal(object, str)   # (result, "") on success, (None, error) on failure

    def __init__(self, fn) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self._fn(), "")
        except Exception as exc:
            self.done.emit(None, str(exc))


class _BiasPoller(QObject):
    """Reads the bias supply in a dedicated QThread so a slow/hung instrument
    can never stall the GUI (the old 1 s QTimer read on the main thread did)."""
    reading = Signal(object)   # BiasReading, or None when unavailable

    def __init__(self, get_supply) -> None:
        super().__init__()
        self._get_supply = get_supply
        self._timer = QTimer(self)     # parented → moves with us to the thread
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _poll(self) -> None:
        supply = self._get_supply()
        if supply is None or not getattr(supply, "connected", False):
            self.reading.emit(None)
            return
        try:
            self.reading.emit(supply.read())
        except Exception:
            self.reading.emit(None)


class TCTMainWindow(QMainWindow):
    _bias_poll_stop_requested = Signal()
    _liveness_stop_requested = Signal()
    # State-machine transitions fire synchronously from the scan worker
    # thread; this signal hops them onto the GUI thread (queued) before any
    # widget is touched (StatusChip repolish / setEnabled are not thread-safe).
    _state_changed_sig = Signal(object, object)   # old, new AppState

    def __init__(self, config_path: str = "configs/devices.yaml") -> None:
        super().__init__()
        self.setWindowTitle("TCT Setup Control")
        self.resize(1400, 900)
        self._config_path = config_path

        # ── Core objects ──────────────────────────────────────────────
        self._sm      = StateMachine()
        self._devices = DeviceManager(config_path)
        # The ScanController allocates a fresh per-run HDF5Writer itself
        # (_begin_run); no writer is created here.
        self._scanner = ScanController(self._devices, self._sm)
        self._bg_thread: QThread | None = None
        self._bg_task: _BgTask | None = None

        # Aux windows (created lazily) + one-time wiring
        self._device_manager_window: DeviceManagerWindow | None = None
        self._settings_window: SettingsWindow | None = None
        self._settings = QSettings("TCT", "TCTSetup")
        self._theme_mode = str(self._settings.value("theme", "light"))
        self._state_changed_sig.connect(self._on_state_change)
        self._sm.add_callback(
            lambda old, new: self._state_changed_sig.emit(old, new))
        self._build_log_dock()
        self._build_device_debug_dock()
        self._build_menu_and_toolbar()
        self._build_central()
        self._restore_window_state()
        # App-wide status/notification bus → status bar (one-time connect).
        from gui.status_bus import STATUS
        STATUS.message.connect(self._on_status_message)

    def _build_central(self) -> None:
        """Build (or rebuild) all device panels, tabs, wiring and timers.

        Called once at startup and again by ``_reload_config`` after the config
        is saved, so every ``devices.yaml`` change applies without restarting
        the process.  ``setCentralWidget`` does NOT delete the previous
        central widget it replaces (confirmed empirically — Qt only detaches
        it from the layout, leaving it alive as a hidden orphan otherwise), so
        ``_teardown_panels`` must both stop every panel's threads/timers AND
        explicitly ``deleteLater()`` the outgoing central widget itself before
        this method builds and installs the next one."""
        # ── GUI panels ────────────────────────────────────────────────
        self._motor_panel     = MotorPanel(self._devices.motor)
        self._intensity_panel = IntensityPanel(self._devices.intensity_monitor)
        self._camera_panel    = CameraPanel(self._devices.camera)
        self._scope_panel     = ScopePanel(self._devices.scope, config_path=self._config_path,
                                           analysis_kwargs=self._devices.analysis_kwargs)
        self._laser_panel     = LaserPanel(self._devices.laser, self._devices.waveform_generator)
        self._scan_viewer     = ScanViewerPanel()
        # One tab per HV channel.  Starts as [primary] and is rebuilt from the
        # driver's real channel count once connect_all() runs refresh_bias_channels().
        self._bias_panel      = MultiBiasPanel(self._devices.bias_channels)
        self._monitor_panel   = MonitorPanel(
            self._devices.slow_control,
            poll_interval_s=self._devices._poll_interval_s,
            influx_writer=self._devices.influx,
        )
        self._analysis_panel  = AnalysisPanel()
        # Danger-confirm gate.  The gate lives here (parented to the window)
        # because the plan executor calls gate.confirm() from the scan worker
        # thread; teardown must shutdown() it so a pending confirm can never
        # block app exit.  Constructed BEFORE the calibration panel because the
        # panel now requires the SAME gate instance (repeatability motion is
        # danger-gated — Abel, controller/repeatability.py) and refuses motion
        # without it.
        self._danger_gate     = QtDangerGate(parent=self)
        self._calib_panel     = CalibrationPanel(self._devices, gate=self._danger_gate)
        # Scan-routine planner (Recipe Tree) — shares the gate above.
        self._planner_panel   = PlannerPanel(parent=self)

        # ── Layout ────────────────────────────────────────────────────
        central = QWidget()
        central.setObjectName("mainShell")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        # (Connect/Disconnect/Settings/Log live on the menu bar + toolbar, built
        #  once in __init__ so they survive a soft-reload.)

        # System ribbon: grouped cached status, always visible regardless of
        # active tab. Pure widget composition; device I/O remains in the
        # existing pollers/workers below.
        ribbon = QFrame()
        ribbon.setObjectName("systemRibbon")
        status_strip = QHBoxLayout(ribbon)
        status_strip.setContentsMargins(10, 7, 10, 7)
        status_strip.setSpacing(8)

        brand = QFrame()
        brand.setObjectName("ribbonBrand")
        brand_row = QHBoxLayout(brand)
        brand_row.setContentsMargins(0, 0, 2, 0)
        brand_row.setSpacing(6)
        mark = QLabel("T")
        mark.setObjectName("ribbonMark")
        name = QLabel("TCT Control")
        name.setObjectName("ribbonWordmark")
        brand_row.addWidget(mark)
        brand_row.addWidget(name)
        status_strip.addWidget(brand)

        def _group(label: str, widgets: list[QWidget]) -> QFrame:
            group = QFrame()
            group.setObjectName("ribbonGroup")
            row = QHBoxLayout(group)
            row.setContentsMargins(7, 3, 7, 3)
            row.setSpacing(6)
            caption = QLabel(label.upper())
            caption.setObjectName("ribbonLabel")
            row.addWidget(caption)
            for widget in widgets:
                row.addWidget(widget)
            return group

        self._lights: dict[str, StatusPill] = {}
        device_lights: list[QWidget] = []
        for name in self._devices.named_devices():
            light = StatusPill(name, "neutral")
            self._lights[name] = light
            device_lights.append(light)
        status_strip.addWidget(_group("Devices", device_lights))
        self._chip_bias_v = StatusChip("HV --", "neutral", min_width=84)
        self._chip_bias_v.setToolTip("Live bias voltage on the primary HV channel")
        self._chip_bias_i = StatusChip("I --", "neutral", min_width=86)
        self._chip_bias_i.setToolTip("Live leakage/current on the primary HV channel")
        self._chip_bias_comp = StatusChip("Compliance --", "neutral", min_width=112)
        self._chip_bias_comp.setToolTip("Primary HV channel compliance state")
        self._chip_motion = StatusChip("Motion offline", "neutral", min_width=112)
        self._chip_motion.setToolTip("Motor connection and homing state")
        self._chip_scan = StatusChip(f"Scan {self._sm.state.name}", "neutral", min_width=96)
        self._chip_scan.setToolTip("Application scan state")
        self._ring_scan = ActivityRing(active=False)
        self._chip_laser = StatusChip("Laser --", "neutral", min_width=92)
        self._chip_laser.setToolTip("Cached wavegen trigger output state")
        status_strip.addWidget(_group(
            "Bias", [self._chip_bias_v, self._chip_bias_i, self._chip_bias_comp]))
        status_strip.addWidget(_group("Motion", [self._chip_motion]))
        status_strip.addWidget(_group("Scan", [self._ring_scan, self._chip_scan]))
        status_strip.addWidget(_group("Laser", [self._chip_laser]))
        status_strip.addStretch(1)
        # Horizontal scroll so the device lights + bias readout never clip on a
        # narrow window; fixed height keeps it a thin strip.
        strip_scroll = QScrollArea()
        strip_scroll.setObjectName("ribbonScroll")
        strip_scroll.setWidgetResizable(True)
        strip_scroll.setFrameShape(QFrame.NoFrame)
        strip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        strip_scroll.setFixedHeight(54)
        strip_scroll.setWidget(ribbon)

        # Main tabs — detachable (double-click / ⧉ to pop into a window).  Each
        # page is wrapped in a QScrollArea so panels scroll instead of cropping.
        self._tabs = DetachableTabWidget()

        # Motor stage and the reference-intensity monitor are independent,
        # independently-detachable tabs (the panels are self-contained widgets).
        self._tabs.addTab(_scrollable(self._motor_panel), "Motor Stage")
        self._tabs.addTab(_scrollable(self._intensity_panel), "Reference Monitor")
        self._tabs.addTab(_scrollable(self._camera_panel), "Camera")
        self._tabs.addTab(_scrollable(self._scope_panel), "Oscilloscope")
        self._tabs.addTab(_scrollable(self._laser_panel), "Laser / Trigger")
        self._tabs.addTab(_scrollable(self._scan_viewer), "Scan Viewer")
        self._tabs.addTab(_scrollable(self._planner_panel), "Scan Planner")
        self._tabs.addTab(_scrollable(self._bias_panel), "Bias Supply")
        self._tabs.addTab(_scrollable(self._calib_panel), "Calibration")
        self._tabs.addTab(_scrollable(self._monitor_panel), "Monitor")
        self._tabs.addTab(_scrollable(self._analysis_panel), "Analysis")

        # ── QML chrome shell (opt-in: TCT_QML_SHELL=1) ────────────────────
        # DEFAULT (flag unset) is the classic QWidget shell, byte-for-byte
        # unchanged: the ribbon strip + toolbar are shown and no QQuickWidget
        # is built. When set, the QML rail + pill shelf REPLACE the ribbon
        # strip AND the classic toolbar (hidden, not removed — the toolbar's
        # non-duplicated affordances (Device Manager / Settings / Show Log /
        # Show Device Debug / the app-state readout) are re-exposed as a
        # compact rail cluster routed to the SAME existing handlers, so there
        # is exactly one visible Connect/Disconnect/Devices/Settings/Log/Debug
        # surface, never two — see gui/qml_shell.py / gui/qml/Shell.qml). The
        # classic ribbon strip and toolbar widgets stay alive (hidden,
        # parented to `central`) so they remain the cached-state source the
        # QML rail mirrors, and the DetachableTabWidget stays the tab/detach
        # engine (its native tab bar is hidden by build_qml_chrome).
        self._qml_chrome = None
        self._shell_bridge = None
        self._scope_vm = None
        # Read-only run/scan-state facade for the QML Scan Viewer. Built AND fed
        # in BOTH modes (the poll + coordinator feeds below are mode-agnostic);
        # registered as the "runState" QML context property only in QML mode.
        # Holds no ScanController/StateMachine/coordinator reference — the
        # read/command boundary is structural (docs/design/run_state_facade.md).
        from gui.run_state_viewmodel import RunStateViewModel
        self._run_vm = RunStateViewModel()
        if os.environ.get("TCT_QML_SHELL") == "1":
            from gui.qml_shell import build_qml_chrome
            from gui.scope_viewmodel import ScopeViewModel
            scope_vm = ScopeViewModel()
            chrome, bridge = build_qml_chrome(
                self, self._tabs,
                state_provider=self._collect_shell_state,
                scope_vm=scope_vm,
                run_vm=self._run_vm,
                on_connect=self._connect_all,
                on_disconnect=self._disconnect_all,
                on_toggle_theme=self._toggle_theme_from_qml,
                on_open_devices=self._open_device_manager,
                on_open_settings=self._open_settings,
                on_toggle_log=self._toggle_log_from_qml,
                on_toggle_debug=self._toggle_debug_from_qml,
                theme_mode=getattr(self, "_theme_mode", "light"),
            )
            if chrome is not None:
                self._qml_chrome = chrome
                self._shell_bridge = bridge
                self._scope_vm = scope_vm
                strip_scroll.setParent(central)   # keep chips alive; not shown
                strip_scroll.hide()
                self._toolbar.setVisible(False)
                outer.addWidget(chrome)
                outer.addWidget(self._tabs)
            else:
                # Fail safe (Rule 5 spirit): Shell.qml failed to load —
                # build_qml_chrome already released everything it constructed
                # and touched neither the toolbar nor the native tab bar.
                # Stay fully classic and operable rather than run with a
                # half-built/missing chrome.
                notify("QML chrome failed to load — using the classic shell. "
                       "See the log for the QML error.", "error")
                self._toolbar.setVisible(True)
                outer.addWidget(strip_scroll)
                outer.addWidget(self._tabs)
        else:
            self._toolbar.setVisible(True)
            outer.addWidget(strip_scroll)
            outer.addWidget(self._tabs)

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Disconnected")

        # ── Scan run-control coordinator ──────────────────────────────────
        # The ScanCoordinator owns the run-control logic (bridge, plan-vs-classic
        # dispatch, start/pause/abort/arm-HV) that used to live inline here; this
        # window is now a composition root that only wires panel signals into the
        # coordinator's methods and the coordinator's signals into panel slots
        # (plus a couple of dialog / status shims).  See gui/scan_coordinator.py.
        # Not parented to the window: like the old _ScanBridge it is held alive
        # only by this attribute, so a soft config-reload's reassignment lets the
        # previous coordinator (bound to the discarded ScanController) be
        # collected instead of accumulating on every reload.  Created on the GUI
        # thread → GUI-thread affinity → queued delivery of the daemon-thread
        # scan callbacks is preserved.
        self._coordinator = ScanCoordinator(
            self._scanner, self._sm, self._danger_gate, self._plan_limits,
        )
        coord = self._coordinator

        # Coordinator → Scan Viewer (fired for every run — plan or classic).
        coord.point_done.connect(self._scan_viewer.on_point_done)
        coord.progress.connect(self._scan_viewer.on_progress)
        coord.scan_started.connect(self._scan_viewer.on_scan_started)
        coord.scan_finished.connect(self._scan_viewer.on_scan_finished)
        # Coordinator → run-state facade (read-only mirror for the QML Scan
        # Viewer; the SAME already-marshaled GUI-thread signals feed it in
        # parallel with the classic panel — see run_state_facade.md §3 path 2).
        # These connections die with the coordinator (reassigned on soft-reload),
        # the same lifetime as the ScanViewerPanel connections above.
        coord.scan_started.connect(self._run_vm.on_scan_started)
        coord.progress.connect(self._run_vm.on_progress)
        coord.point_done.connect(self._run_vm.on_point_done)
        coord.scan_finished.connect(self._run_vm.on_scan_finished)
        coord.error_dialog.connect(self._run_vm.on_error)
        # Publish the finished run's HDF5 path AFTER on_scan_finished has cleared
        # the viewer's run-active flag, so set_last_run_path can enable "Open in
        # Analysis" (order matters — see _publish_last_run_path).
        coord.scan_finished.connect(self._publish_last_run_path)
        # Manual-pause prompt: the viewer flags it on its run chip; the modal
        # Resume/Abort dialog shim (_on_plan_manual_pause, below) is still wired
        # too — both consumers are wanted.
        coord.manual_pause.connect(self._scan_viewer.on_manual_pause)
        # Z-focus results are connected once here (connecting them per-run
        # duplicated the slots: double plot points and marker written twice).
        coord.z_focus_pt.connect(self._scan_viewer.on_z_focus_pt)
        coord.z_focus_done.connect(self._scan_viewer.on_z_focus_done)
        # Coordinator → bias panel (voltage-scan IV points).
        coord.vscan_point.connect(self._bias_panel.on_vscan_point)
        # Coordinator → Scan Planner (forwarded only for a planner-launched run;
        # the gating lives in the coordinator so no cross-talk from classic scans).
        coord.plan_progress.connect(self._planner_panel.on_progress)
        coord.plan_error.connect(self._planner_panel.on_error)
        coord.plan_finished.connect(self._planner_panel.on_finished)
        coord.plan_running.connect(self._planner_panel.set_running)
        coord.hv_armed.connect(self._planner_panel.set_hv_armed)
        # Coordinator → composition-root dialog / status shims.
        coord.manual_pause.connect(self._on_plan_manual_pause)
        coord.warn_dialog.connect(self._show_warn_dialog)
        coord.error_dialog.connect(self._show_error_dialog)
        coord.status_message.connect(self._status.showMessage)

        # Scan Viewer → coordinator (live run control only — the Scan Planner is
        # the sole scan-start surface; the viewer owns no start path except its
        # Z-focus live assist, the one sanctioned exception).
        self._scan_viewer.pause_requested.connect(coord.toggle_pause)
        self._scan_viewer.abort_requested.connect(coord.abort)
        self._scan_viewer.z_focus_requested.connect(coord.start_z_focus)
        # Scan Viewer → Analysis handoff: open the just-finished run's HDF5 file.
        self._scan_viewer.open_in_analysis_requested.connect(self._open_in_analysis)

        # Planner panel → coordinator. arm_hv_requested/start_plan_requested are
        # the legacy dialog-confirm fallback (arm-latch flag off);
        # execute_plan_requested is the two-step-latch path (design law 5),
        # carrying the ArmedEnvelopeGate the panel built over the rendered
        # envelope. The panel derives that envelope via the controller's
        # read-only arm_envelope_for (real bias-channel resolution).
        self._planner_panel.arm_hv_requested.connect(coord.arm_hv)
        self._planner_panel.start_plan_requested.connect(coord.start_plan)
        self._planner_panel.execute_plan_requested.connect(coord.execute_plan)
        self._planner_panel.abort_requested.connect(coord.abort)
        # Mary milestone review: give the gate an INDEPENDENT freshness bound
        # (~3x the GUI's 10 s arm latch) so the controller boundary rejects a
        # stale arm even if a future edit path missed disarm — defense in
        # depth; the 10 s latch stays the primary UX timer.
        self._planner_panel.set_envelope_provider(
            lambda plan: self._scanner.arm_envelope_for(plan, timeout_s=30.0)
        )

        # Bias panel → coordinator (voltage scan also starts from the bias panel).
        self._bias_panel.vscan_requested.connect(coord.start_voltage_scan)

        # Motor → Scan Planner: "Set as Start" seeds the planner's current-
        # position affordance (G3 — a plan has no single start position, only
        # per-axis loops; replaces the retired quick-scan start-position seam).
        self._motor_panel.set_as_scan_start.connect(
            self._planner_panel.set_position_from_motor
        )
        # Home / Zero Here shift the motor's user/machine display offset, so the
        # planner's user-frame soft limits (PlanLimits) must be recomputed from
        # the new origin — otherwise a plan built around a fresh Zero Here is
        # gated against stale bounds. Re-push on every offset change.
        self._motor_panel.origin_changed.connect(self._refresh_plan_limits)

        # Scan Viewer → Scan Planner: "Apply to Planner" stages the Z-focus
        # assist's best-Z result into the planner's "Use focus Z" affordance
        # (G4 — staging only; never moves the motor, never touches a running
        # plan).
        self._scan_viewer.best_z_apply_requested.connect(
            self._planner_panel.set_focus_z
        )

        # ── Live bias readout (dedicated thread — instrument I/O must never
        #    run on the GUI thread; a hung GPIB read froze the window) ─────
        self._bias_poller = _BiasPoller(lambda: getattr(self._devices, "bias_supply", None))
        self._bias_poll_thread = QThread(self)
        self._bias_poller.moveToThread(self._bias_poll_thread)
        self._bias_poll_thread.started.connect(self._bias_poller.start)
        self._bias_poll_stop_requested.connect(self._bias_poller.stop)
        self._bias_poll_thread.finished.connect(self._bias_poller.deleteLater)
        # Drives the always-visible safety strip (primary channel).  The per-tab
        # readout is now driven by each BiasPanel's own poll thread, so this
        # poller no longer feeds the panel directly.
        self._bias_poller.reading.connect(self._refresh_bias_strip)
        self._bias_poll_thread.start()

        # Always-on poll so the device lights reflect the live state — including
        # individual connects/disconnects made from the Device Manager window.
        # The same tick advances the app state machine (e.g. CONNECTED → READY
        # once the stage reports homed), whichever panel did the homing.
        self._light_timer = QTimer(self)
        self._light_timer.setInterval(1000)
        self._light_timer.timeout.connect(self._refresh_lights)
        self._light_timer.timeout.connect(self._sync_app_state)
        # BOTH modes: mirror machine state + run metadata into the read-only
        # run-state facade on the SAME shared 1 Hz tick (no new QTimer, no new
        # thread; single-timer law). Guarded feeder — safe after teardown drops
        # _run_vm. See run_state_facade.md §3 path 1.
        self._light_timer.timeout.connect(self._feed_run_state)
        # QML mode only: the shell bridge polls the SAME cached state at the
        # SAME cadence — one shared 1 Hz timer instead of a second QTimer
        # doing duplicate work (slice 2a coffee-retro item; _ShellBridge owns
        # no timer of its own — see gui/qml_shell.py).
        if self._shell_bridge is not None:
            self._light_timer.timeout.connect(self._shell_bridge.pull)
        self._light_timer.start()
        self._refresh_lights()

        # ── Device liveness monitor (own thread — probes may do I/O) ─────
        # Actively verifies links (BaseDevice.is_alive) so a yanked cable
        # flips the flag instead of showing CONNECTED forever; the lights /
        # Device Manager table repaint from the corrected flags above.
        self._liveness = LivenessMonitor(self._devices)
        self._liveness_thread = QThread(self)
        self._liveness.moveToThread(self._liveness_thread)
        self._liveness_thread.started.connect(self._liveness.start)
        self._liveness_stop_requested.connect(self._liveness.stop)
        self._liveness_thread.finished.connect(self._liveness.deleteLater)
        self._liveness.device_lost.connect(self._on_device_lost)
        self._liveness_thread.start()

        # Re-assert the theme now that every panel exists so the global QSS is
        # consistent for the fully-built window. Plots no longer depend on this
        # call for their canvas: each pg.PlotWidget self-styles at construction
        # (background=PLOT_BG + showGrid), and apply_theme() only sets the
        # pyqtgraph config defaults — it deliberately never walks live widgets
        # (see gui.style._apply_pyqtgraph for the removed AV vector).
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, getattr(self, "_theme_mode", "light"))

    # ------------------------------------------------------------------ #
    # Status strip / log dock                                             #
    # ------------------------------------------------------------------ #

    def _build_log_dock(self) -> None:
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(2000)
        font = self._log_view.font()
        font.setFamily("Consolas")
        self._log_view.setFont(font)
        dock = QDockWidget("Log", self)
        dock.setWidget(self._log_view)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        dock.hide()   # available via View; hidden by default to stay uncramped
        self._log_dock = dock

        handler = _QtLogHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s — %(message)s",
                                               datefmt="%H:%M:%S"))
        handler.bridge.record.connect(self._log_view.appendPlainText)
        logging.getLogger().addHandler(handler)

    def _build_device_debug_dock(self) -> None:
        panel = QWidget()
        root = QVBoxLayout(panel)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        bar = QHBoxLayout()
        self._chk_device_debug = QCheckBox("Capture raw scope/iseg I/O")
        self._chk_device_debug.setChecked(True)
        self._chk_device_debug.setToolTip(
            "Logs raw SCPI/serial TX/RX lines for the oscilloscope and iseg bias supply."
        )
        btn_clear = QPushButton("Clear")
        hint = QLabel("Binary waveform replies are summarized, not dumped.")
        hint.setStyleSheet("color:#888;")
        btn_clear.clicked.connect(lambda: self._device_debug_view.clear())
        bar.addWidget(self._chk_device_debug)
        bar.addWidget(btn_clear)
        bar.addWidget(hint)
        bar.addStretch()
        root.addLayout(bar)

        self._device_debug_view = QPlainTextEdit()
        self._device_debug_view.setReadOnly(True)
        self._device_debug_view.setMaximumBlockCount(5000)
        font = self._device_debug_view.font()
        font.setFamily("Consolas")
        self._device_debug_view.setFont(font)
        root.addWidget(self._device_debug_view)

        dock = QDockWidget("Device Debug", self)
        dock.setWidget(panel)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        dock.hide()
        self._device_debug_dock = dock

        handler = _QtDeviceDebugHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
        handler.bridge.record.connect(self._device_debug_view.appendPlainText)
        handler.set_enabled(self._chk_device_debug.isChecked())
        self._chk_device_debug.toggled.connect(handler.set_enabled)

        device_logger = logging.getLogger("tct.device_io")
        device_logger.setLevel(logging.DEBUG)
        device_logger.propagate = False
        device_logger.addHandler(handler)
        self._device_debug_handler = handler

    # ------------------------------------------------------------------ #
    # Menu bar / toolbar / theme / window-state persistence              #
    # ------------------------------------------------------------------ #

    def _build_menu_and_toolbar(self) -> None:
        st = self.style()

        def _act(text, slot, icon=None, checkable=False, shortcut=None, tip=None):
            a = QAction(text, self)
            if icon is not None:
                a.setIcon(st.standardIcon(icon))
            a.setCheckable(checkable)
            if shortcut:
                a.setShortcut(shortcut)
            if tip:
                a.setToolTip(tip)
                a.setStatusTip(tip)
            if checkable:
                a.toggled.connect(slot)               # passes the bool
            else:
                a.triggered.connect(lambda *_: slot())  # drop the checked arg
            return a

        self._act_connect    = _act("Connect All", self._connect_all,
                                     QStyle.SP_DialogYesButton, tip="Connect all devices")
        self._act_disconnect = _act("Disconnect All", self._disconnect_all,
                                     QStyle.SP_DialogNoButton, tip="Disconnect all devices")
        self._act_disconnect.setEnabled(False)
        self._act_devices    = _act("Device Manager…", self._open_device_manager,
                                     QStyle.SP_ComputerIcon)
        self._act_settings   = _act("Settings…", self._open_settings,
                                     QStyle.SP_FileDialogDetailedView,
                                     shortcut=QKeySequence("Ctrl+,"))
        self._act_log        = _act("Show Log", self._log_dock.setVisible,
                                     QStyle.SP_FileDialogInfoView, checkable=True,
                                     tip="Show/hide the log panel")
        self._log_dock.visibilityChanged.connect(self._act_log.setChecked)
        self._act_device_debug = _act(
            "Show Device Debug", self._device_debug_dock.setVisible,
            QStyle.SP_FileDialogContentsView, checkable=True,
            tip="Show raw scope/iseg SCPI and serial traffic"
        )
        self._device_debug_dock.visibilityChanged.connect(self._act_device_debug.setChecked)
        self._act_dark       = _act("Dark mode", self._toggle_theme, checkable=True,
                                     tip="Toggle dark / light theme")
        self._act_dark.setChecked(self._theme_mode == "dark")
        self._act_quit       = _act("Quit", self.close, shortcut=QKeySequence.Quit)
        self._act_about      = _act("About", self._about)

        mb = self.menuBar()
        m_file = mb.addMenu("&File")
        m_file.addAction(self._act_settings)
        m_file.addSeparator()
        m_file.addAction(self._act_quit)
        m_view = mb.addMenu("&View")
        m_view.addAction(self._act_dark)
        m_view.addAction(self._act_log)
        m_view.addAction(self._act_device_debug)
        m_dev = mb.addMenu("&Devices")
        m_dev.addAction(self._act_connect)
        m_dev.addAction(self._act_disconnect)
        m_dev.addSeparator()
        m_dev.addAction(self._act_devices)
        m_help = mb.addMenu("&Help")
        m_help.addAction(self._act_about)

        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)  # icon + label
        self.addToolBar(tb)
        # Kept as an attribute so the QML branch of _build_central can hide it
        # (QML mode replaces it with a rail cluster routed to the SAME actions
        # below — see _collect_shell_state / gui/qml_shell.py).
        self._toolbar = tb
        tb.addAction(self._act_connect)
        tb.addAction(self._act_disconnect)
        tb.addSeparator()
        tb.addAction(self._act_devices)
        tb.addAction(self._act_settings)
        tb.addAction(self._act_log)
        tb.addAction(self._act_device_debug)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self._lbl_state = StatusChip(f"State: {self._sm.state.name}", "neutral")
        tb.addWidget(self._lbl_state)
        # objectNames for the green/red QSS accents
        for act, name in ((self._act_connect, "connectBtn"),
                          (self._act_disconnect, "disconnectBtn")):
            w = tb.widgetForAction(act)
            if w is not None:
                w.setObjectName(name)

    def _toggle_theme(self, checked: bool) -> None:
        self._theme_mode = "dark" if checked else "light"
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self._theme_mode)
        # Keep the QML chrome (if built) in lockstep with the QSS theme: swap the
        # Theme singleton's active palette so its bound QML properties repaint.
        if getattr(self, "_qml_chrome", None) is not None:
            from gui.qml_theme import set_theme_mode
            set_theme_mode(self._theme_mode)
        # apply_theme() repaints every QSS hook globally, but axis_color()-based
        # instance styles (motor axis rails, bias amber, plot pens) are baked at
        # construction — panels expose refresh_theme() to re-resolve them live.
        for panel in (getattr(self, "_motor_panel", None),
                      getattr(self, "_bias_panel", None),
                      getattr(self, "_planner_panel", None),
                      getattr(self, "_scan_viewer", None),
                      getattr(self, "_scope_panel", None),
                      getattr(self, "_laser_panel", None),
                      getattr(self, "_monitor_panel", None),
                      getattr(self, "_camera_panel", None),
                      getattr(self, "_calib_panel", None),
                      getattr(self, "_analysis_panel", None),
                      getattr(self, "_settings_window", None)):
            if panel is not None and hasattr(panel, "refresh_theme"):
                try:
                    panel.refresh_theme(self._theme_mode)
                except Exception:
                    logger.debug("panel refresh_theme failed", exc_info=True)
        self._settings.setValue("theme", self._theme_mode)

    def _about(self) -> None:
        QMessageBox.about(
            self, "About TCT Setup",
            "<b>TCT Setup Control</b><br><br>"
            "Laser-TCT acquisition &amp; motor-stage control.<br>"
            "Tip: double-click a tab (or use ⧉) to pop a panel into its own window.")

    def _restore_window_state(self) -> None:
        s = self._settings
        geo = s.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        idx = s.value("active_tab")
        if idx is not None:
            try:
                self._tabs.setCurrentIndex(int(idx))
            except (TypeError, ValueError):
                pass
        detached = s.value("detached_titles") or []
        if isinstance(detached, str):
            detached = [detached]
        for title in detached:
            self._tabs.detach_by_title(title)

    def _save_window_state(self) -> None:
        s = self._settings
        s.setValue("geometry", self.saveGeometry())
        s.setValue("theme", self._theme_mode)
        if hasattr(self, "_tabs"):
            s.setValue("active_tab", self._tabs.currentIndex())
            s.setValue("detached_titles", self._tabs.detached_titles())

    def _refresh_lights(self) -> None:
        """Update the device lights from the *live* device state.

        Driven by a timer (not the last connect_all result) so individual
        connects/disconnects from the Device Manager window are reflected too,
        and simulated devices show purple rather than green.
        """
        named = self._devices.named_devices()
        for disp, light in self._lights.items():
            dev = named.get(disp)
            if dev is not None:
                state = device_state(dev)
                label = {
                    "connected": f"{disp} on",
                    "simulated": f"{disp} sim",
                    "disconnected": f"{disp} off",
                }.get(state, disp)
                light.set_status(label, state, state.capitalize())
        motor = getattr(self._devices, "motor", None)
        if hasattr(self, "_chip_motion"):
            if motor is None or not getattr(motor, "connected", False):
                self._chip_motion.set_status("Motion offline", "neutral")
            elif getattr(motor, "homed", False):
                self._chip_motion.set_status("Motion homed", "good")
            else:
                self._chip_motion.set_status("Motion not homed", "warn")
        self._refresh_laser_strip()

    def _refresh_laser_strip(self) -> None:
        """Update the ribbon's laser trigger chip from cached wavegen state."""
        if not hasattr(self, "_chip_laser"):
            return
        wfg = getattr(self._devices, "waveform_generator", None)
        try:
            live = bool(wfg is not None and (
                getattr(wfg, "connected", False) or getattr(wfg, "simulation", False)
            ))
            state = getattr(wfg, "output_is_on", None) if wfg is not None else None
        except Exception:
            live = False
            state = None
        if not live:
            set_pulse(self._chip_laser, False)
            self._chip_laser.set_status("Laser --", "neutral")
        elif state is True:
            self._chip_laser.set_status("Laser ON", "armed")
            set_pulse(self._chip_laser, True, kind="laser")
        elif state is False:
            set_pulse(self._chip_laser, False)
            self._chip_laser.set_status("Laser off", "good")
        else:
            self._chip_laser.set_status("Laser unknown", "warn")
            set_pulse(self._chip_laser, True, kind="laser")

    def _collect_shell_state(self) -> dict:
        """Snapshot the cached ribbon state for the QML rail (QML-mode only).

        Pure reads of already-cached values — device connection flags and the
        classic status chips (which the existing pollers keep current) — plus
        the scope panel's Live-button state. No hardware I/O: this is the same
        cached state the classic ribbon shows, mirrored into the QML view.
        """
        dot_map = {"connected": "on", "simulated": "sim", "disconnected": "off"}
        devices: list[list[str]] = []
        for disp, dev in self._devices.named_devices().items():
            devices.append([disp, dot_map.get(device_state(dev), "off")])

        def _chip(chip) -> list[str]:
            return [chip.text(), str(chip.property("state") or "neutral")]

        scope = getattr(self._devices, "scope", None)
        sc_conn = bool(getattr(scope, "connected", False))
        sc_sim = bool(getattr(scope, "simulation", False))
        live_btn = getattr(getattr(self, "_scope_panel", None), "_btn_live", None)
        acquiring = bool(live_btn is not None and live_btn.isChecked())
        if not (sc_conn or sc_sim):
            sc_status = "Scope offline"
        elif acquiring:
            sc_status = "Scope live"
        else:
            sc_status = "Scope sim" if sc_sim else "Scope ready"

        return {
            "devices": devices,
            "hv": _chip(self._chip_bias_v),
            "motion": _chip(self._chip_motion),
            "scan": _chip(self._chip_scan),
            "laser": _chip(self._chip_laser),
            # The toolbar's app-state readout (self._lbl_state) — distinct from
            # the "Scan" chip above — re-exposed on the rail since the classic
            # toolbar is hidden in QML mode (see _build_central's QML branch).
            "app": _chip(self._lbl_state),
            "scope": {
                "connected": sc_conn, "simulated": sc_sim,
                "acquiring": acquiring, "status": sc_status,
            },
            # Dock visibility — drives the rail's Log/Debug button highlight so
            # a QML click and the View-menu checkbox never disagree.
            "log_visible": bool(self._log_dock.isVisible()),
            "debug_visible": bool(self._device_debug_dock.isVisible()),
        }

    def _feed_run_state(self) -> None:
        """Mirror machine state + run metadata into the run-state facade.

        Runs on the shared 1 Hz ``_light_timer`` (GUI thread), in BOTH shells.
        Pure reads: ``sm.state`` is an atomic enum-reference read (the same
        cross-thread read the rail's app chip already tolerates — worst case one
        tick stale), and ``current_scan_type``/``last_run_path`` are the
        controller's thread-safe accessors. ``scan_type`` is ADVISORY: it reads
        ``None`` for a sub-second window at run start, so ``running``/``active``
        key off ``sm.state`` (above) — not this. Wholly guarded so a routine,
        no-I/O poll step can never crash the process from a Qt-invoked slot."""
        vm = getattr(self, "_run_vm", None)
        if vm is None:
            return
        try:
            sm = getattr(self, "_sm", None)
            scanner = getattr(self, "_scanner", None)
            state = getattr(sm, "state", None) if sm is not None else None
            stype = getattr(scanner, "current_scan_type", None) if scanner is not None else None
            rpath = getattr(scanner, "last_run_path", None) if scanner is not None else None
            vm.update(
                state=state,
                scan_type=stype or "",
                run_path=str(rpath) if rpath else "",
            )
        except Exception:
            logger.debug("run-state facade poll feed failed", exc_info=True)

    def _toggle_theme_from_qml(self) -> None:
        """QML rail theme button → flip the same checkable View-menu action so
        the classic ``_toggle_theme`` path (QSS + panel refresh + QML sync)
        runs unchanged."""
        self._act_dark.setChecked(not self._act_dark.isChecked())

    def _toggle_log_from_qml(self) -> None:
        """QML rail Log button → flip the same checkable ``_act_log`` action
        (toggled → ``self._log_dock.setVisible``), so the toolbar/menu and the
        QML rail can never fall out of sync."""
        self._act_log.setChecked(not self._act_log.isChecked())

    def _toggle_debug_from_qml(self) -> None:
        """QML rail Debug button → flip the same checkable ``_act_device_debug``
        action, mirroring ``_toggle_log_from_qml`` above."""
        self._act_device_debug.setChecked(not self._act_device_debug.isChecked())

    @Slot(str)
    def _on_device_lost(self, name: str) -> None:
        """A liveness probe found a dead link — surface it loudly.

        The device's own driver already flipped its connected flag, so the
        lights and Device Manager table go red on their next refresh tick;
        this adds the human-visible alert.
        """
        notify(f"⚠ {name} connection lost — check cable/power. "
               "Marked disconnected.", "error")
        self._refresh_lights()

    @Slot(object)
    def _refresh_bias_strip(self, r) -> None:
        """Update the bias strip from a reading delivered by the _BiasPoller
        thread (None = supply unavailable).  Pure widget work — no I/O here."""
        if r is None:
            set_pulse(self._chip_bias_v, False)
            self._chip_bias_v.set_status("HV --", "neutral")
            self._chip_bias_i.set_status("I --", "neutral")
            self._chip_bias_comp.set_status("Compliance --", "neutral")
            return
        compliant = bool(getattr(r, "compliant", False))
        # Log once on the transition into compliance (don't spam the 1 s timer).
        if compliant and not getattr(self, "_bias_compliant_prev", False):
            logger.warning("Bias supply hit COMPLIANCE: %.1f V, %.3f µA",
                           r.voltage_V, r.current_A * 1e6)
        self._bias_compliant_prev = compliant
        hv_state = "armed" if abs(float(r.voltage_V)) > 1.0 else "good"
        self._chip_bias_v.set_status(f"HV {r.voltage_V:+.1f} V", hv_state)
        set_pulse(self._chip_bias_v, hv_state == "armed", kind="hv")
        self._chip_bias_i.set_status(f"I {r.current_A*1e6:+.3f} uA", hv_state)
        self._chip_bias_comp.set_status(
            "Compliance HIT" if compliant else "Compliance OK",
            "crit" if compliant else "good",
        )

    def _safe_bias_shutdown(self) -> None:
        """Ramp the bias to 0 V and disable the output before any teardown, so
        the sensor is never left biased when the app disconnects / closes."""
        bias = getattr(self._devices, "bias_supply", None)
        if bias is None or not getattr(bias, "connected", False):
            return
        try:
            if abs(getattr(bias, "setpoint_V", 0.0)) > 1.0:
                logger.info("Safety: ramping bias to 0 V before shutdown")
                bias.ramp_to(0.0)
            bias.output_off()
        except Exception as exc:
            logger.warning("Bias safe-shutdown failed: %s", exc)

    # ------------------------------------------------------------------ #
    # Connection                                                          #
    # ------------------------------------------------------------------ #

    @Slot()
    def _open_settings(self) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow(parent=self)
            self._settings_window.saved.connect(self._reload_config)
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    @Slot(str)
    def _reload_config(self, path: str) -> None:
        """Soft-reload: rebuild the DeviceManager + all panels from the saved
        config so changes apply without restarting the app."""
        reply = QMessageBox.question(
            self, "Reload settings",
            "Devices will be disconnected and the configuration reloaded so the "
            "changes take effect.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply != QMessageBox.Yes:
            return
        # Stop every I/O thread (panels, pollers, liveness monitor) BEFORE
        # disconnecting devices — the always-on liveness monitor and scope
        # reader must not issue VISA I/O while disconnect() closes the handle
        # (same ordering closeEvent uses; reversing it races the close).
        self._teardown_panels()
        self._safe_bias_shutdown()
        try:
            self._devices.disconnect_all()
        except Exception:
            pass
        self._config_path = path
        try:
            self._devices = DeviceManager(path)
            self._scanner = ScanController(self._devices, self._sm)
        except Exception as exc:
            QMessageBox.critical(self, "Reload failed",
                                 f"Could not load the new config:\n{exc}")
            return
        self._build_central()
        if self._sm.state != AppState.DISCONNECTED:
            self._sm.transition(AppState.DISCONNECTED)
        self._act_connect.setEnabled(True)
        self._act_disconnect.setEnabled(False)
        self._status.showMessage("Config reloaded — click Connect All")

    def _teardown_panels(self) -> None:
        """Stop every panel-owned thread/timer before the panels are discarded
        (child-widget deletion does not fire closeEvent)."""
        # Detach the QML shell bridge from the shared light timer (QML mode
        # only) so a tick can't reach into discarded widgets after a
        # soft-reload / on close. The bridge owns no timer of its own (slice
        # 2a — see gui/qml_shell.py); it only rides `_light_timer.timeout`,
        # stopped a few lines below, so this disconnect is the only bridge-
        # specific teardown needed and is safe to repeat (idempotent).
        bridge = getattr(self, "_shell_bridge", None)
        if bridge is not None:
            light_timer = getattr(self, "_light_timer", None)
            if light_timer is not None:
                try:
                    light_timer.timeout.disconnect(bridge.pull)
                except (TypeError, RuntimeError):
                    pass
            self._shell_bridge = None
        # Explicitly release the QML chrome's engine/scene-graph resources
        # BEFORE ``_build_central`` (a soft config reload) constructs a new
        # QQuickWidget. A QQuickWidget owns its own QQmlEngine; clearing its
        # source releases the root object graph and engine-owned resources
        # synchronously (Qt's own recommended teardown for a QQuickWidget
        # about to be discarded) instead of leaving that to whatever/whenever
        # discards the widget itself.
        chrome = getattr(self, "_qml_chrome", None)
        if chrome is not None:
            try:
                chrome.setSource(QUrl())
            except Exception:
                pass
            self._qml_chrome = None
        self._scope_vm = None
        # Drop the run-state facade here too (poll feed is a guarded shared-timer
        # slot stopped a few lines below; coordinator connections die with the
        # coordinator on rebuild). See run_state_facade.md §5 step 3.
        self._run_vm = None
        # The OLD central widget (built by the PREVIOUS ``_build_central()``
        # call, holding the chrome released above) is not deleted by a later
        # ``setCentralWidget()`` call — confirmed empirically: Qt only detaches
        # the widget it replaces from the layout, leaving it alive as a
        # hidden, still-parented child of this window forever unless something
        # explicitly deletes it. In QML mode that silently accumulates live
        # QQuickWidgets (each with its own QQmlEngine/RHI resources) across
        # repeated soft reloads. Schedule the whole old subtree for deletion
        # now, before ``_build_central`` constructs the next one.
        #
        # Deliberately a plain, UNFORCED ``deleteLater()`` — do not "help" it
        # along with an immediate/forced delete. Two forcing alternatives were
        # tried and rejected: a raw ``shiboken6.delete()`` and forcing
        # ``QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)``
        # through synchronously. Both crashed the real, fully populated app
        # (reproduced with the live ``TCTMainWindow``, its threads and every
        # panel — not just the QML chrome in isolation); only the natural,
        # deferred ``deleteLater()`` proved stable. A soft reload is only ever
        # re-triggered by another user click — another real event-loop turn —
        # so Qt's normal idle processing reclaims this cycle's deferred
        # deletion well before the next reload can start.
        # ``getattr``-guarded (not a direct ``self.centralWidget()`` call): a
        # lightweight test stub for this method's panel-iteration loop (see
        # tests/test_camera_panel_worker.py::
        # test_teardown_panels_shuts_down_camera_and_laser) passes a bare
        # ``SimpleNamespace`` as ``self``, with no real ``QMainWindow``
        # underneath — matching the same "provide only what you use" idiom
        # this method already applies to every other panel/thread attribute.
        get_central = getattr(self, "centralWidget", None)
        old_central = get_central() if callable(get_central) else None
        if old_central is not None:
            old_central.deleteLater()
        # Re-dock any floating panels so their windows don't orphan on rebuild.
        if hasattr(self, "_tabs"):
            self._tabs.redock_all()
        t = getattr(self, "_light_timer", None)
        if t is not None:
            t.stop()
            t.deleteLater()
        # Stop the bias poller thread (it holds a reference into the old
        # DeviceManager via its getter closure).
        if getattr(self, "_bias_poll_thread", None) is not None:
            self._bias_poll_stop_requested.emit()
            self._bias_poll_thread.quit()
            self._bias_poll_thread.wait(2000)
            self._bias_poll_thread = None
        # Stop the liveness monitor (it holds the old DeviceManager).  Stop the
        # timer first (queued into its thread) so no new sweep starts, then
        # quit; the wait margin covers an in-flight sweep's probe timeout.
        if getattr(self, "_liveness_thread", None) is not None:
            self._liveness_stop_requested.emit()
            self._liveness_thread.quit()
            self._liveness_thread.wait(4000)
            self._liveness_thread = None
            self._liveness = None
        # Release any gate.confirm() blocked in the scan thread FIRST, so a
        # pending danger dialog can never hold up abort/teardown.
        if getattr(self, "_danger_gate", None) is not None:
            try:
                self._danger_gate.shutdown()
            except Exception:
                pass
        try:
            self._scanner.abort()
        except Exception:
            pass
        for panel, method in ((getattr(self, "_motor_panel", None),   "shutdown"),
                      (getattr(self, "_bias_panel", None),    "shutdown"),
                      (getattr(self, "_intensity_panel", None), "shutdown"),
                              (getattr(self, "_scope_panel", None),   "shutdown"),
                              (getattr(self, "_camera_panel", None),  "shutdown"),
                              (getattr(self, "_laser_panel", None),   "shutdown"),
                              (getattr(self, "_calib_panel", None),   "shutdown"),
                              (getattr(self, "_planner_panel", None), "shutdown"),
                              (getattr(self, "_monitor_panel", None), "stop_polling")):
            if panel is not None and hasattr(panel, method):
                try:
                    getattr(panel, method)()
                except Exception:
                    pass
        # The Device Manager window holds a stale DeviceManager reference.
        if self._device_manager_window is not None:
            try:
                self._device_manager_window.shutdown()
                self._device_manager_window.hide()
                self._device_manager_window.deleteLater()
            except Exception:
                pass
            self._device_manager_window = None

    @Slot()
    def _open_device_manager(self) -> None:
        if self._device_manager_window is None:
            self._device_manager_window = DeviceManagerWindow(self._devices, parent=self)
        # Re-centre over the main window every time it is shown so it never
        # appears in a stale off-screen or collapsed position.
        win = self._device_manager_window
        win.show()
        win.raise_()
        win.activateWindow()
        # Centre over parent after show() so the frame geometry is valid.
        parent_rect = self.geometry()
        win_rect = win.frameGeometry()
        win.move(
            parent_rect.center().x() - win_rect.width() // 2,
            parent_rect.center().y() - win_rect.height() // 2,
        )

    def _run_bg(self, fn, on_done) -> bool:
        """Run *fn* in a worker QThread; deliver (result, err) to *on_done* on
        the GUI thread.  Returns False if another background task is running.

        The single-slot design is deliberate (no arbitrary-depth queue): a
        connect/disconnect can legitimately take many seconds, and stacking
        more onto the same VISA/serial links would only pile up contention.
        When busy we surface that on the status bus instead of the old silent
        ``return False`` — the "clicking reconnect does nothing" bench report.
        """
        if self._bg_thread is not None and self._bg_thread.isRunning():
            notify("Still busy with the previous device operation — "
                   "please wait for it to finish.", "warn")
            return False
        self._bg_task = _BgTask(fn)
        self._bg_thread = QThread(self)
        self._bg_task.moveToThread(self._bg_thread)
        self._bg_thread.started.connect(self._bg_task.run)

        def _finish(result, err):
            thread = self._bg_thread
            self._bg_thread = None
            self._bg_task = None
            if thread is not None:
                thread.quit()
                thread.wait(2000)
            on_done(result, err)

        self._bg_task.done.connect(_finish)
        self._bg_thread.start()
        return True

    @Slot()
    def _connect_all(self) -> None:
        # Config sanity gate: validation errors block connecting outright.
        errors = self._devices.config_errors()
        if errors:
            QMessageBox.critical(
                self, "Invalid configuration",
                "devices.yaml has errors that must be fixed before connecting:\n\n"
                + "\n".join(f"• {e}" for e in errors))
            return
        warnings = self._devices.config_warnings()
        if warnings:
            logger.warning("Config warnings:\n%s", "\n".join(warnings))
        if not self._run_bg(self._devices.connect_all, self._on_connect_done):
            return
        self._act_connect.setEnabled(False)
        self._status.showMessage("Connecting…")

    def _on_connect_done(self, results, err: str) -> None:
        self._refresh_lights()
        # connect_all() ran refresh_bias_channels(); reflect the real channel
        # count in the bias panel (no-ops when the channel set is unchanged).
        try:
            self._bias_panel.rebuild(self._devices.bias_channels)
        except Exception:
            logger.debug("bias panel rebuild failed", exc_info=True)
        # Connect may have refined scope.n_channels from *IDN? (capability
        # clamp); resize the scope panel's channel cards to match (no-op when
        # the channel set is unchanged, reads the attribute only — no I/O).
        try:
            self._scope_panel.rebuild_channels()
        except Exception:
            logger.debug("scope panel rebuild failed", exc_info=True)
        # Push real device-derived plan limits to the planner (it starts with
        # conservative defaults; this re-locks Start against the new limits).
        try:
            self._planner_panel.set_limits(self._plan_limits())
        except Exception:
            logger.debug("planner set_limits failed", exc_info=True)
        if err:
            QMessageBox.critical(self, "Connection Failed", err)
            self._act_connect.setEnabled(True)
            self._status.showMessage("Connect failed")
            return
        failed = {k: v for k, v in (results or {}).items() if v != "ok"}
        if failed:
            detail = "\n".join(f"  {k}: {v}" for k, v in failed.items())
            QMessageBox.warning(self, "Connection Warning",
                                f"Some devices failed to connect:\n{detail}")
        if self._sm.state == AppState.DISCONNECTED:
            self._sm.transition(AppState.CONNECTED)
        self._act_disconnect.setEnabled(True)
        self._status.showMessage("Connected — home the stage to enable scans")
        self._monitor_panel.start_polling()

    @Slot()
    def _disconnect_all(self) -> None:
        self._monitor_panel.stop_polling()
        try:
            self._scanner.abort()
        except Exception:
            pass

        def _work():
            self._safe_bias_shutdown()
            self._devices.disconnect_all()

        if not self._run_bg(_work, self._on_disconnect_done):
            return
        self._act_disconnect.setEnabled(False)
        self._status.showMessage("Disconnecting — ramping bias to 0 V…")

    def _on_disconnect_done(self, _result, err: str) -> None:
        if err:
            logger.warning("Disconnect reported: %s", err)
        if self._sm.state != AppState.DISCONNECTED:
            self._sm.transition(AppState.DISCONNECTED)
        self._act_connect.setEnabled(True)
        self._act_disconnect.setEnabled(False)
        self._status.showMessage("Disconnected")
        self._refresh_lights()
        self._refresh_bias_strip(None)
        self._bias_panel.set_reading(None)

    # ------------------------------------------------------------------ #
    # App-state housekeeping                                              #
    # ------------------------------------------------------------------ #

    def _sync_app_state(self) -> None:
        """Advance the state machine from live device state (1 s timer).

        HOMED/CONFIGURED/READY carry no extra configuration today, so once the
        stage reports homed the state walks straight through to READY — this is
        what arms the Start buttons.  Finished/aborted/errored runs recover to
        READY the same way so the next scan can start without reconnecting.
        """
        try:
            motor = self._devices.motor
            ready = bool(getattr(motor, "connected", False) and getattr(motor, "homed", False))
            st = self._sm.state
            if st == AppState.CONNECTED and ready:
                self._sm.transition(AppState.HOMED)
                self._sm.transition(AppState.CONFIGURED)
                self._sm.transition(AppState.READY)
            elif st in (AppState.FINISHED, AppState.ABORTED, AppState.ERROR):
                self._sm.transition(AppState.CONFIGURED)
                if ready:
                    self._sm.transition(AppState.READY)
        except ValueError:
            # A scan thread transitioned concurrently — harmless, resync next tick.
            pass
        except Exception:
            logger.debug("state sync failed", exc_info=True)

    # ------------------------------------------------------------------ #
    # Scan run-control dialog / status shims (coordinator → widgets)      #
    # ------------------------------------------------------------------ #

    @Slot(str, str)
    def _show_warn_dialog(self, title: str, message: str) -> None:
        """Coordinator asked for a warning box (e.g. a refused start)."""
        QMessageBox.warning(self, title, message)

    @Slot(str, str)
    def _show_error_dialog(self, title: str, message: str) -> None:
        """Coordinator asked for a critical box (scan error / plan refused)."""
        QMessageBox.critical(self, title, message)

    # ------------------------------------------------------------------ #
    # Scan-routine planner wiring                                          #
    # ------------------------------------------------------------------ #

    def _plan_limits(self) -> PlanLimits:
        """PlanLimits from the live device config — the motor's SoftwareLimits
        and the bias supply's voltage range (conservative defaults when a
        device doesn't expose them).

        Frame contract: planner coordinates live in the motor's USER frame
        (what ``get_position``/``move_to`` speak, what ``set_position_from_motor``
        receives), so the validator bounds must be the machine soft limits
        expressed in that SAME frame — i.e. ``motor.limits_user_frame()``, which
        tracks the current ``zero_position`` origin.  Using raw ``motor.limits``
        (machine frame) here was the "Zero Here → planner rejects the plan on
        soft limits" bug.  This is re-pushed on every offset change (home/zero)
        via the motor panel's ``origin_changed`` signal, so it never goes stale.
        """
        motor = getattr(self._devices, "motor", None)
        lim = None
        if motor is not None:
            try:
                lim = motor.limits_user_frame()
            except Exception:
                logger.debug("motor.limits_user_frame() failed", exc_info=True)
                lim = getattr(motor, "limits", None)
        try:
            rng = self._devices.bias_supply.voltage_range_V
        except Exception:
            rng = None
        return PlanLimits(
            x_min_mm=lim.x_min if lim else -5.0,
            x_max_mm=lim.x_max if lim else 5.0,
            y_min_mm=lim.y_min if lim else -5.0,
            y_max_mm=lim.y_max if lim else 5.0,
            z_min_mm=lim.z_min if lim else -5.0,
            z_max_mm=lim.z_max if lim else 5.0,
            voltage_range_V=float(rng) if rng else 3000.0,
            max_points=250_000,
        )

    @Slot()
    def _refresh_plan_limits(self) -> None:
        """Re-push user-frame plan limits to the planner after an offset change.

        Wired to ``MotorPanel.origin_changed`` (home / Zero Here). Rebuilding
        the planner's ``PlanLimits`` from the driver's current offset keeps its
        soft-limit gate in the same frame the operator now sees; the panel
        re-validates against the fresh bounds (a plan edit / dry run re-locks
        Start regardless, so this never silently unlocks a run)."""
        try:
            self._planner_panel.set_limits(self._plan_limits())
        except Exception:
            logger.debug("planner limit refresh (origin change) failed", exc_info=True)

    @Slot()
    def _publish_last_run_path(self) -> None:
        """Hand the just-written run's HDF5 path to the Scan Viewer so its
        "Open in Analysis" button can enable.

        ``ScanController.last_run_path`` is a thread-safe accessor published in
        ``_end_run`` *before* the finished callback fires, and stays correct on
        an aborted/errored terminal (abort preserves the data already taken).
        Wired to ``scan_finished`` *after* the viewer's own ``on_scan_finished``
        so the viewer's run-active flag is cleared by the time
        ``set_last_run_path`` runs and enables the button."""
        p = self._scanner.last_run_path
        self._scan_viewer.set_last_run_path(str(p) if p else None)

    @Slot(str)
    def _open_in_analysis(self, path: str) -> None:
        """Scan Viewer "Open in Analysis": load the finished run's HDF5 file
        into the Analysis tab and switch to it.  ``AnalysisPanel.load_run``
        never raises — it reports failure via its own file chip and a ``False``
        return; the try/except is a belt-and-braces guard mirroring the old
        ``_open_in_planner`` shape."""
        try:
            ok = self._analysis_panel.load_run(path)
        except Exception as exc:
            QMessageBox.warning(self, "Cannot open run", str(exc))
            return
        if not ok:
            QMessageBox.warning(
                self, "Cannot open run",
                f"The run file could not be loaded:\n{path}")
            return
        for i in range(self._tabs.count()):
            if self._tabs.tabText(i) == "Analysis":
                self._tabs.setCurrentIndex(i)
                break
        notify("Run opened in the Analysis tab", "info")

    @Slot(str)
    def _on_plan_manual_pause(self, prompt: str) -> None:
        """The plan executor hit a ManualPauseStep: surface the operator
        prompt; Resume continues the plan, Abort stops it fail-safe.  The
        Resume/Abort decision routes back through the coordinator (which owns the
        ScanController); this slot is a pure modal-dialog shim."""
        box = QMessageBox(QMessageBox.Information, "Manual step",
                          prompt or "Manual intervention required.", parent=self)
        resume = box.addButton("Resume plan", QMessageBox.AcceptRole)
        box.addButton("Abort plan", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is resume:
            self._coordinator.resume()
        else:
            self._coordinator.abort()

    def _on_state_change(self, old: AppState, new: AppState) -> None:
        state_map = {
            AppState.DISCONNECTED: "neutral",
            AppState.CONNECTED: "info",
            AppState.HOMED: "info",
            AppState.CONFIGURED: "info",
            AppState.READY: "good",
            AppState.RUNNING: "busy",
            AppState.PAUSED: "warn",
            AppState.FINISHED: "good",
            AppState.ABORTED: "warn",
            AppState.ERROR: "crit",
        }
        visual = state_map.get(new, "neutral")
        self._lbl_state.set_status(f"State: {new.name}", visual)
        if hasattr(self, "_chip_scan"):
            self._chip_scan.set_status(f"Scan {new.name}", visual)
            set_pulse(self._chip_scan, new == AppState.RUNNING, kind="scan")
        if hasattr(self, "_ring_scan"):
            self._ring_scan.set_active(new == AppState.RUNNING)
        panel = getattr(self, "_planner_panel", None)
        if panel is not None:
            # Only a planner-launched run drives the panel's running state; a
            # terminal transition always releases it (flag already cleared).
            coord = getattr(self, "_coordinator", None)
            running = bool(coord is not None and coord.plan_run_active) and \
                new in (AppState.RUNNING, AppState.PAUSED)
            panel.set_running(running)
        self._status.showMessage(f"State: {new.name}")

    def _on_status_message(self, text: str, level: str) -> None:
        """Show a transient status-bar message from the app-wide status bus."""
        if hasattr(self, "_status"):
            self._status.showMessage(text, 8000 if level.startswith(("warn", "err")) else 4000)

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    def closeEvent(self, event) -> None:
        self._save_window_state()
        # Stop all panel/poller threads first so nothing touches the devices
        # while they are being shut down (intentionally synchronous: the app is
        # exiting and the sensor must never be left biased).
        self._teardown_panels()
        self._safe_bias_shutdown()
        self._devices.disconnect_all()
        super().closeEvent(event)
