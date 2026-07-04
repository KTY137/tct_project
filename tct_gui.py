"""
TCT Setup — Main Window

Assembles all panels, wires the ScanController callbacks, and manages
the application state machine.  GUI panels reference only abstract
device interfaces so hardware swaps need no UI code changes.
"""
from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt, Slot, Signal, QObject, QThread, QTimer, QSettings
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
from controller.scan_controller import ScanController, ScanConfig, ZFocusScanConfig, VoltageScanConfig

from gui.motor_panel import MotorPanel
from gui.intensity_panel import IntensityPanel
from gui.camera_panel import CameraPanel
from gui.scope_panel import ScopePanel
from gui.laser_panel import LaserPanel
from gui.scan_panel import ScanPanel
from gui.bias_panel import BiasPanel
from gui.monitor_panel import MonitorPanel
from gui.analysis_panel import AnalysisPanel
from gui.calibration_panel import CalibrationPanel
from gui.device_panel import DeviceManagerWindow, device_state
from gui.settings_window import SettingsWindow

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


class _StatusLight(QFrame):
    """Small coloured dot + label showing one device's connection state.

    Colours match the Device Manager window:
        green  = connected (real hardware)
        purple = connected in simulation mode
        grey   = disconnected
    """

    _COLORS = {
        "connected":    "#27ae60",   # green
        "simulated":    "#8e44ad",   # purple
        "disconnected": "#b0b6bf",   # grey
    }

    def __init__(self, name: str) -> None:
        super().__init__()
        self.setObjectName("statusLight")
        # A bordered pill so every device reads as its own distinct chip.
        self.setStyleSheet(
            "#statusLight { border: 1px solid rgba(128,128,128,0.40); "
            "border-radius: 9px; }"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 2, 10, 2)
        lay.setSpacing(6)
        self._dot = QLabel("●")
        self._dot.setStyleSheet(f"color: {self._COLORS['disconnected']}; font-size: 14px;")
        lay.addWidget(self._dot)
        lbl = QLabel(name)
        lbl.setStyleSheet("font-weight: 600;")
        lay.addWidget(lbl)

    def set_state(self, state: str) -> None:
        self._dot.setStyleSheet(
            f"color: {self._COLORS.get(state, self._COLORS['disconnected'])}; font-size: 14px;"
        )
        self.setToolTip(state.capitalize())


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


class _ScanBridge(QObject):
    """
    Marshals ScanController callbacks (called from background threads) onto
    the Qt main thread via queued signal/slot delivery.  This prevents
    PySide6 from crashing when a scan thread tries to update GUI widgets.
    """
    point_done   = Signal(object)        # ScanResult
    progress     = Signal(int, int)      # done, total
    finished     = Signal()
    error        = Signal(str)
    z_focus_pt   = Signal(float, float)  # z_mm, amplitude_V
    z_focus_done = Signal(float)         # best_z_mm
    vscan_point  = Signal(float, float, float)  # voltage_V, charge_pC, current_A


class TCTMainWindow(QMainWindow):
    _bias_poll_stop_requested = Signal()

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
        self._sm.add_callback(self._on_state_change)
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
        the process.  ``setCentralWidget`` deletes the previous panels, so
        ``_teardown_panels`` must stop their threads first."""
        # ── GUI panels ────────────────────────────────────────────────
        self._motor_panel     = MotorPanel(self._devices.motor)
        self._intensity_panel = IntensityPanel(self._devices.intensity_monitor)
        self._camera_panel    = CameraPanel(self._devices.camera)
        self._scope_panel     = ScopePanel(self._devices.scope, config_path=self._config_path,
                                           analysis_kwargs=self._devices.analysis_kwargs)
        self._laser_panel     = LaserPanel(self._devices.laser, self._devices.waveform_generator)
        self._scan_panel      = ScanPanel()
        self._bias_panel      = BiasPanel(self._devices.bias_supply)
        self._monitor_panel   = MonitorPanel(
            self._devices.slow_control,
            poll_interval_s=self._devices._poll_interval_s,
            influx_writer=self._devices.influx,
        )
        self._analysis_panel  = AnalysisPanel()
        self._calib_panel     = CalibrationPanel(self._devices)

        # ── Layout ────────────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        # (Connect/Disconnect/Settings/Log live on the menu bar + toolbar, built
        #  once in __init__ so they survive a soft-reload.)

        # Status strip: per-device connection lights + live bias readout.
        # Always visible regardless of the active tab (bias is safety-critical).
        status_strip = QHBoxLayout()
        status_strip.setSpacing(6)
        self._lights: dict[str, _StatusLight] = {}
        for name in self._devices.named_devices():
            light = _StatusLight(name)
            self._lights[name] = light
            status_strip.addWidget(light)
        status_strip.addStretch()
        self._lbl_bias = QLabel("Bias: —")
        self._lbl_bias.setToolTip("Live bias voltage / current / compliance")
        self._lbl_bias.setStyleSheet("font-weight:600; padding:2px 8px;")
        status_strip.addWidget(self._lbl_bias)
        strip_frame = QFrame()
        strip_frame.setLayout(status_strip)
        # Horizontal scroll so the device lights + bias readout never clip on a
        # narrow window; fixed height keeps it a thin strip.
        strip_scroll = QScrollArea()
        strip_scroll.setWidgetResizable(True)
        strip_scroll.setFrameShape(QFrame.NoFrame)
        strip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        strip_scroll.setFixedHeight(44)
        strip_scroll.setWidget(strip_frame)
        outer.addWidget(strip_scroll)

        # Main tabs — detachable (double-click / ⧉ to pop into a window).  Each
        # page is wrapped in a QScrollArea so panels scroll instead of cropping.
        self._tabs = DetachableTabWidget()

        # Tab 1: Motor + Intensity side-by-side
        ctrl_tab = QWidget()
        ctrl_layout = QHBoxLayout(ctrl_tab)
        ctrl_layout.addWidget(self._motor_panel, stretch=1)
        ctrl_layout.addWidget(self._intensity_panel, stretch=1)
        self._tabs.addTab(_scrollable(ctrl_tab), "Motor / Intensity Monitor")
        self._tabs.addTab(_scrollable(self._camera_panel), "Camera")
        self._tabs.addTab(_scrollable(self._scope_panel), "Oscilloscope")
        self._tabs.addTab(_scrollable(self._laser_panel), "Laser / Trigger")
        self._tabs.addTab(_scrollable(self._scan_panel), "Scan")
        self._tabs.addTab(_scrollable(self._bias_panel), "Bias Supply")
        self._tabs.addTab(_scrollable(self._calib_panel), "Calibration")
        self._tabs.addTab(_scrollable(self._monitor_panel), "Monitor")
        self._tabs.addTab(_scrollable(self._analysis_panel), "Analysis")

        outer.addWidget(self._tabs)

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Disconnected")

        # ── Thread-safe scan callback bridge ──────────────────────────────
        # ScanController runs in a daemon threading.Thread; all GUI updates
        # must go through Qt queued signals to avoid cross-thread crashes.
        self._bridge = _ScanBridge()
        self._bridge.point_done.connect(self._scan_panel.on_point_done)
        self._bridge.progress.connect(self._scan_panel.on_progress)
        self._bridge.finished.connect(self._on_scan_finished)
        self._bridge.error.connect(self._on_scan_error)
        self._bridge.vscan_point.connect(self._bias_panel._on_vscan_point_cb)

        self._scanner.on_point_done = lambda r:       self._bridge.point_done.emit(r)
        self._scanner.on_progress   = lambda d, t:    self._bridge.progress.emit(d, t)
        self._scanner.on_finished   = lambda:         self._bridge.finished.emit()
        self._scanner.on_error      = lambda msg:     self._bridge.error.emit(msg)
        self._scanner.on_vscan_point = lambda v, c, i: self._bridge.vscan_point.emit(v, c, i)

        self._scan_panel.start_requested.connect(self._start_scan)
        self._scan_panel.abort_requested.connect(self._scanner.abort)
        self._scan_panel.z_focus_requested.connect(self._start_z_focus)
        self._scan_panel.vscan_requested.connect(self._start_voltage_scan)
        self._bias_panel.vscan_requested.connect(self._start_voltage_scan)

        # Motor → Scan panel: "Set as Start"
        self._motor_panel.set_as_scan_start.connect(
            self._scan_panel.set_start_position
        )

        # Z-focus results go through the bridge like every other scan signal —
        # connected once here (connecting them in _start_z_focus duplicated the
        # slots on every run: double plot points and spin_z written twice).
        self._bridge.z_focus_pt.connect(self._scan_panel.on_z_focus_point)
        self._bridge.z_focus_done.connect(self._scan_panel.on_z_focus_done)

        # Pause / resume the running scan from the Scan panel.
        self._scan_panel.pause_requested.connect(self._toggle_pause)

        # ── Live bias readout (dedicated thread — instrument I/O must never
        #    run on the GUI thread; a hung GPIB read froze the window) ─────
        self._bias_poller = _BiasPoller(lambda: getattr(self._devices, "bias_supply", None))
        self._bias_poll_thread = QThread(self)
        self._bias_poller.moveToThread(self._bias_poll_thread)
        self._bias_poll_thread.started.connect(self._bias_poller.start)
        self._bias_poll_stop_requested.connect(self._bias_poller.stop)
        self._bias_poll_thread.finished.connect(self._bias_poller.deleteLater)
        self._bias_poller.reading.connect(self._refresh_bias_strip)
        self._bias_poller.reading.connect(self._bias_panel.set_reading)
        self._bias_poll_thread.start()

        # Always-on poll so the device lights reflect the live state — including
        # individual connects/disconnects made from the Device Manager window.
        # The same tick advances the app state machine (e.g. CONNECTED → READY
        # once the stage reports homed), whichever panel did the homing.
        self._light_timer = QTimer(self)
        self._light_timer.setInterval(1000)
        self._light_timer.timeout.connect(self._refresh_lights)
        self._light_timer.timeout.connect(self._sync_app_state)
        self._light_timer.start()
        self._refresh_lights()

        # Re-apply the theme now that the pyqtgraph plots exist, so they get the
        # dark canvas + grid (they didn't exist when apply_theme ran at startup).
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
        self._lbl_state = QLabel(f"State: {self._sm.state.name}")
        self._lbl_state.setStyleSheet("padding: 0 10px; font-weight: 600;")
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
                light.set_state(device_state(dev))

    @Slot(object)
    def _refresh_bias_strip(self, r) -> None:
        """Update the bias strip from a reading delivered by the _BiasPoller
        thread (None = supply unavailable).  Pure widget work — no I/O here."""
        if r is None:
            self._lbl_bias.setText("Bias: —")
            self._lbl_bias.setStyleSheet("font-weight:600; padding:2px 8px;")
            return
        compliant = bool(getattr(r, "compliant", False))
        # Log once on the transition into compliance (don't spam the 1 s timer).
        if compliant and not getattr(self, "_bias_compliant_prev", False):
            logger.warning("Bias supply hit COMPLIANCE: %.1f V, %.3f µA",
                           r.voltage_V, r.current_A * 1e6)
        self._bias_compliant_prev = compliant
        flag = "COMPLIANT" if compliant else "OK"
        color = "#c0392b" if compliant else "#27ae60"
        self._lbl_bias.setText(
            f"Bias: {r.voltage_V:+.1f} V   I: {r.current_A*1e6:+.3f} µA   {flag}"
        )
        self._lbl_bias.setStyleSheet(f"font-weight:600; padding:2px 8px; color:{color};")

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
        self._safe_bias_shutdown()
        try:
            self._devices.disconnect_all()
        except Exception:
            pass
        self._teardown_panels()
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
        try:
            self._scanner.abort()
        except Exception:
            pass
        for panel, method in ((getattr(self, "_motor_panel", None),   "shutdown"),
                      (getattr(self, "_bias_panel", None),    "shutdown"),
                      (getattr(self, "_intensity_panel", None), "shutdown"),
                              (getattr(self, "_scope_panel", None),   "shutdown"),
                              (getattr(self, "_calib_panel", None),   "shutdown"),
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
        the GUI thread.  Returns False if another background task is running."""
        if self._bg_thread is not None and self._bg_thread.isRunning():
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

    @Slot(bool)
    def _toggle_pause(self, pause: bool) -> None:
        try:
            if pause:
                self._scanner.pause()
                self._status.showMessage("Scan paused")
            else:
                self._scanner.resume()
                self._status.showMessage("Scan resumed")
        except Exception as exc:
            logger.warning("Pause/resume failed: %s", exc)

    # ------------------------------------------------------------------ #
    # Scan                                                                #
    # ------------------------------------------------------------------ #

    @Slot(ScanConfig)
    def _start_scan(self, cfg: ScanConfig) -> None:
        if not self._sm.can(AppState.RUNNING):
            QMessageBox.warning(self, "Cannot Start",
                                f"Cannot start scan in state {self._sm.state.name}.\n"
                                "Ensure devices are connected and stage is homed.")
            return

        # The ScanController allocates its own run directory + writer per run
        # (see ScanController._begin_run), so no writer is created here.
        self._scan_panel.on_scan_started()
        self._scanner.start(cfg)

    def _on_scan_finished(self) -> None:
        self._scan_panel.on_scan_finished()
        self._status.showMessage(f"Scan finished — state: {self._sm.state.name}")

    def _on_scan_error(self, msg: str) -> None:
        self._scan_panel.on_scan_finished()
        QMessageBox.critical(self, "Scan Error", msg)

    @Slot(ZFocusScanConfig)
    def _start_z_focus(self, cfg: ZFocusScanConfig) -> None:
        if not self._sm.can(AppState.RUNNING):
            QMessageBox.warning(self, "Cannot Start",
                                f"Cannot start Z-focus scan in state {self._sm.state.name}.\n"
                                "Ensure devices are connected.")
            return
        self._status.showMessage("Z-focus scan running…")
        # Bridge signals are connected once in _build_central — connecting them
        # here leaked a duplicate connection per run.
        self._scanner.start_z_focus_scan(
            cfg,
            on_point=lambda z, a: self._bridge.z_focus_pt.emit(z, a),
            on_done=lambda z:     self._bridge.z_focus_done.emit(z),
        )

    @Slot(VoltageScanConfig)
    def _start_voltage_scan(self, cfg: VoltageScanConfig) -> None:
        if not self._sm.can(AppState.RUNNING):
            QMessageBox.warning(self, "Cannot Start",
                                f"Cannot start voltage scan in state {self._sm.state.name}.\n"
                                "Ensure devices are connected.")
            return
        self._status.showMessage("Voltage scan running…")
        self._scanner.start_voltage_scan(cfg)

    # ------------------------------------------------------------------ #
    # State updates                                                       #
    # ------------------------------------------------------------------ #

    def _on_state_change(self, old: AppState, new: AppState) -> None:
        self._lbl_state.setText(f"State: {new.name}")
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
