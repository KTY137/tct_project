"""Motor control panel — works with any MotorStageBase implementation."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QGroupBox, QGridLayout, QHBoxLayout, QVBoxLayout,
    QLabel, QDoubleSpinBox, QPushButton, QSizePolicy,
)

from devices.motor_base import MotorStageBase
from PySide6.QtCore import QObject


class _PositionPoller(QObject):
    """
    Runs get_position() in a dedicated QThread so serial I/O never blocks
    the GUI thread.  Emits position_updated with the (x, y, z) strings.
    """
    position_updated = Signal(str, str, str)

    def __init__(self, motor: MotorStageBase) -> None:
        super().__init__()
        self._motor = motor
        self._paused = False
        # Parent the timer to self so moveToThread() carries it to the worker
        # thread automatically.  An unparented QTimer stays on the main thread
        # and 'startTimer from another thread' warnings / silent failures result.
        self._timer = QTimer(self)
        self._timer.setInterval(500)   # poll every 500 ms — fast enough for display
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def set_paused(self, paused: bool) -> None:
        """Pause status polling while a move/home runs in the task thread, so
        only one thread ever talks to the serial port at a time (a bool write
        is atomic in CPython — safe to flip from the GUI thread)."""
        self._paused = paused

    def _poll(self) -> None:
        if self._paused or not self._motor.connected:
            return
        try:
            pos = self._motor.get_position()
            self.position_updated.emit(
                f"X: {pos.x_mm:.4f} mm",
                f"Y: {pos.y_mm:.4f} mm",
                f"Z: {pos.z_mm:.4f} mm",
            )
        except Exception as exc:
            logging.getLogger(__name__).debug("position poll failed: %s", exc)


class _MotorTask(QObject):
    """Runs one blocking motor operation off the GUI thread.

    Homing and long absolute moves take seconds; running them directly in a
    button slot froze the whole window.  This carries the call into a worker
    QThread and reports completion (or the error) back via a signal.
    """
    done = Signal(str)   # "" on success, else the error message

    def __init__(self, fn) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self._fn()
            self.done.emit("")
        except Exception as exc:
            self.done.emit(str(exc))


class MotorPanel(QWidget):
    """
    X/Y/Z jog, absolute move, home, and emergency stop.

    Accepts any MotorStageBase subclass — swapping the motor backend
    requires no changes here.
    """

    # Emitted when user clicks "Set as Scan Start" — carries (x, y, z)
    set_as_scan_start = Signal(float, float, float)
    _poll_stop_requested = Signal()

    def __init__(self, motor: MotorStageBase, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._motor = motor
        self._motion_widgets: list[QWidget] = []   # disabled while a move runs
        self._task_thread: QThread | None = None
        self._task: _MotorTask | None = None
        self._build_ui()

        # Position polling runs in a separate thread so serial I/O never
        # blocks the GUI (especially important for Marlin M114 queries).
        self._poller = _PositionPoller(motor)
        self._poll_thread = QThread(self)
        self._poller.moveToThread(self._poll_thread)
        self._poll_thread.started.connect(self._poller.start)
        self._poll_stop_requested.connect(self._poller.stop)
        self._poll_thread.finished.connect(self._poller.deleteLater)
        self._poller.position_updated.connect(self._on_position_updated)
        self._poll_thread.start()

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── Position display ─────────────────────────────────────────
        pos_box = QGroupBox("Position")
        pos_grid = QGridLayout(pos_box)
        self._lbl_x = QLabel("X: —")
        self._lbl_y = QLabel("Y: —")
        self._lbl_z = QLabel("Z: —")
        for col, lbl in enumerate((self._lbl_x, self._lbl_y, self._lbl_z)):
            lbl.setAlignment(Qt.AlignCenter)
            pos_grid.addWidget(lbl, 0, col)
        btn_test = QPushButton("🔌 Test Connection")
        btn_test.setToolTip("Send a firmware-identity G-code (M115 / $I) and show the reply — "
                            "confirms the serial link without moving the stage")
        btn_test.clicked.connect(self._test_connection)
        pos_grid.addWidget(btn_test, 1, 0, 1, 3)
        root.addWidget(pos_box)

        # ── Jog controls ─────────────────────────────────────────────
        jog_box = QGroupBox("Jog")
        jog_layout = QGridLayout(jog_box)
        self._jog_step = QDoubleSpinBox()
        self._jog_step.setRange(0.001, 10.0)
        self._jog_step.setValue(0.1)
        self._jog_step.setSuffix(" mm")
        jog_layout.addWidget(QLabel("Step:"), 0, 0)
        jog_layout.addWidget(self._jog_step, 0, 1)

        axes = ["X", "Y", "Z"]
        deltas = {"−": -1, "+": +1}
        for row, axis in enumerate(axes, start=1):
            for col, (sign, direction) in enumerate(deltas.items()):
                btn = QPushButton(f"{axis} {sign}")
                ax_lower = axis.lower()
                btn.clicked.connect(
                    lambda _, a=ax_lower, d=direction: self._jog(a, d)
                )
                jog_layout.addWidget(btn, row, col)
                self._motion_widgets.append(btn)
        self._motion_widgets.append(self._jog_step)
        root.addWidget(jog_box)

        # ── Absolute move ─────────────────────────────────────────────
        abs_box = QGroupBox("Absolute Move")
        abs_layout = QGridLayout(abs_box)
        self._spin_x = self._make_spin()
        self._spin_y = self._make_spin()
        self._spin_z = self._make_spin()
        for col, (label, spin) in enumerate(
            [("X (mm)", self._spin_x), ("Y (mm)", self._spin_y), ("Z (mm)", self._spin_z)]
        ):
            abs_layout.addWidget(QLabel(label), 0, col)
            abs_layout.addWidget(spin, 1, col)
        btn_move = QPushButton("Move To")
        btn_move.clicked.connect(self._move_abs)
        abs_layout.addWidget(btn_move, 2, 0, 1, 3)
        self._motion_widgets.extend([self._spin_x, self._spin_y, self._spin_z, btn_move])
        root.addWidget(abs_box)

        # ── Action buttons ─────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._btn_home = QPushButton("Home All")
        self._btn_home.clicked.connect(self._home)
        btn_center = QPushButton("Center")
        btn_center.setToolTip("Move to the centre of the soft-limit envelope")
        btn_center.clicked.connect(self._move_center)
        btn_zero = QPushButton("Zero Here")
        btn_zero.setToolTip("Declare the current position as (0, 0, 0) without moving "
                            "(software display offset — does not touch GRBL's G54/G92)")
        btn_zero.clicked.connect(self._zero_position)
        btn_stop = QPushButton("⚠ STOP")
        btn_stop.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold;")
        btn_stop.clicked.connect(self._emergency_stop)
        btn_row.addWidget(self._btn_home)
        btn_row.addWidget(btn_center)
        btn_row.addWidget(btn_zero)
        btn_row.addWidget(btn_stop)
        self._motion_widgets.extend([self._btn_home, btn_center, btn_zero])
        root.addLayout(btn_row)

        # ── Scan-integration helpers ──────────────────────────────────
        helper_box = QGroupBox("Scan Integration")
        helper_layout = QHBoxLayout(helper_box)
        btn_use_pos = QPushButton("📋 Use Current Pos in Abs. Move")
        btn_use_pos.setToolTip("Copy current stage position into the Absolute Move spinboxes")
        btn_use_pos.clicked.connect(self._use_current_pos)
        btn_set_start = QPushButton("📌 Set as Scan Start")
        btn_set_start.setToolTip("Copy current X/Y/Z into the Scan panel start position")
        btn_set_start.clicked.connect(self._emit_set_as_start)
        helper_layout.addWidget(btn_use_pos)
        helper_layout.addWidget(btn_set_start)
        root.addWidget(helper_box)

        self.setLayout(root)

    # ------------------------------------------------------------------ #
    # Slots                                                               #
    # ------------------------------------------------------------------ #

    def _jog(self, axis: str, direction: int) -> None:
        step = self._jog_step.value() * direction
        self._run_async(lambda: self._motor.move_relative(
            dx_mm=step if axis == "x" else 0.0,
            dy_mm=step if axis == "y" else 0.0,
            dz_mm=step if axis == "z" else 0.0,
        ))

    def _move_abs(self) -> None:
        x, y, z = self._spin_x.value(), self._spin_y.value(), self._spin_z.value()
        self._run_async(lambda: self._motor.move_to(x, y, z))

    def _move_center(self) -> None:
        self._run_async(self._motor.move_to_center)

    def _home(self) -> None:
        self._run_async(self._motor.home)

    def _zero_position(self) -> None:
        self._run_async(self._motor.zero_position)

    def _emergency_stop(self) -> None:
        # Runs on the GUI thread on purpose: it must fire immediately and the
        # GRBL backend writes the real-time hold byte without taking any lock.
        try:
            self._motor.stop()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Async motor-operation runner (keeps the GUI responsive)             #
    # ------------------------------------------------------------------ #

    def _run_async(self, fn) -> None:
        """Run a blocking motor call in a worker thread; ignore if one is busy."""
        if self._task_thread is not None and self._task_thread.isRunning():
            return
        self._set_busy(True)
        self._poller.set_paused(True)      # only the task thread talks serial now
        self._task = _MotorTask(fn)
        self._task_thread = QThread(self)
        self._task.moveToThread(self._task_thread)
        self._task_thread.started.connect(self._task.run)
        self._task.done.connect(self._on_task_done)
        self._task_thread.start()

    def _on_task_done(self, err: str) -> None:
        thread = self._task_thread
        self._task_thread = None
        self._task = None
        if thread is not None:
            thread.quit()
            thread.wait(2000)
        self._poller.set_paused(False)     # resume live position updates
        self._set_busy(False)
        if err:
            self._show_error(err)

    def _set_busy(self, busy: bool) -> None:
        for w in self._motion_widgets:
            w.setEnabled(not busy)

    def _test_connection(self) -> None:
        """Run the backend's firmware handshake and show the reply."""
        from PySide6.QtWidgets import QMessageBox, QApplication
        if not self._motor.connected:
            QMessageBox.information(
                self, "Test Connection",
                "Motor is not connected.\nClick 'Connect All' in the top bar first.")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            msg = self._motor.test_connection()
        except Exception as exc:
            msg = f"Test failed: {exc}"
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "Motor Connection Test", msg)

    def _on_position_updated(self, x: str, y: str, z: str) -> None:
        self._lbl_x.setText(x)
        self._lbl_y.setText(y)
        self._lbl_z.setText(z)

    def _update_position(self) -> None:
        """Legacy stub — polling now handled by _PositionPoller in a QThread."""

    def shutdown(self) -> None:
        """Stop all worker threads — call before discarding the panel."""
        if self._task_thread is not None:
            self._task_thread.quit()
            self._task_thread.wait(2000)
        self._poll_stop_requested.emit()
        self._poll_thread.quit()
        self._poll_thread.wait(2000)

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)

    def _use_current_pos(self) -> None:
        """Copy current stage position into the absolute-move spinboxes."""
        if not self._motor.connected:
            return
        try:
            pos = self._motor.get_position()
            self._spin_x.setValue(pos.x_mm)
            self._spin_y.setValue(pos.y_mm)
            self._spin_z.setValue(pos.z_mm)
        except Exception:
            pass

    def _emit_set_as_start(self) -> None:
        """Emit set_as_scan_start with the current stage position."""
        if not self._motor.connected:
            return
        try:
            pos = self._motor.get_position()
            self.set_as_scan_start.emit(pos.x_mm, pos.y_mm, pos.z_mm)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _make_spin(self) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        # Wide enough for full printer travel (the old ±100 mm clamp made most
        # of the envelope unreachable); the motor's software limits do the real
        # bounds-checking before any move is sent.
        s.setRange(-2000.0, 2000.0)
        s.setDecimals(4)
        s.setSuffix(" mm")
        return s

    def _show_error(self, msg: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "Motor Error", msg)

    def set_motor(self, motor: MotorStageBase) -> None:
        """Hot-swap the motor backend at runtime."""
        self._motor = motor
