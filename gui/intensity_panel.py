"""
Intensity monitor panel.

Displays real-time reference photodiode / SiPM amplitude, charge, and
a live mini-waveform plot.  Works with any IntensityMonitorBase
implementation — swap the backend and this panel adapts automatically.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer, QThread, QObject, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QDoubleSpinBox, QPushButton,
)

try:
    import pyqtgraph as pg
    _HAS_PG = True
except ImportError:
    _HAS_PG = False

from devices.intensity_base import IntensityMonitorBase

logger = logging.getLogger(__name__)


class _IntensityReader(QObject):
    """Polls the intensity monitor in a dedicated thread."""

    reading = Signal(object)
    failed = Signal(str)

    def __init__(self, monitor: IntensityMonitorBase) -> None:
        super().__init__()
        self._monitor = monitor
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.read_once)

    def set_monitor(self, monitor: IntensityMonitorBase) -> None:
        self._monitor = monitor

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def read_once(self) -> None:
        if not self._monitor.connected:
            self.reading.emit(None)
            return
        try:
            self.reading.emit(self._monitor.read())
        except Exception as exc:
            self.failed.emit(str(exc))


class IntensityPanel(QWidget):
    """
    Live readout panel for the reference laser intensity monitor.

    Accepts any IntensityMonitorBase subclass (ScopeChannelMonitor,
    SimulatedIntensityMonitor, or a future NI-DAQ / standalone TIA
    implementation) without any code changes.
    """

    _stop_requested = Signal()

    def __init__(
        self,
        monitor: IntensityMonitorBase,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._monitor = monitor
        self._build_ui()
        self._reader = _IntensityReader(monitor)
        self._reader_thread = QThread(self)
        self._reader.moveToThread(self._reader_thread)
        self._reader_thread.started.connect(self._reader.start)
        self._stop_requested.connect(self._reader.stop)
        self._reader_thread.finished.connect(self._reader.deleteLater)
        self._reader.reading.connect(self._on_reading)
        self._reader.failed.connect(self._on_failed)
        self._reader_thread.start()

    # ------------------------------------------------------------------ #
    # UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── Live values ───────────────────────────────────────────────
        vals_box = QGroupBox("Reference Monitor")
        vals_layout = QHBoxLayout(vals_box)
        self._lbl_amp  = QLabel("Amplitude: —")
        self._lbl_chg  = QLabel("Charge: —")
        self._lbl_sat  = QLabel("")
        for lbl in (self._lbl_amp, self._lbl_chg, self._lbl_sat):
            lbl.setAlignment(Qt.AlignCenter)
            vals_layout.addWidget(lbl)
        root.addWidget(vals_box)

        # ── Scale control ─────────────────────────────────────────────
        scale_row = QHBoxLayout()
        scale_row.addWidget(QLabel("Scale (V/div):"))
        self._spin_scale = QDoubleSpinBox()
        self._spin_scale.setRange(0.001, 10.0)
        self._spin_scale.setValue(0.1)
        self._spin_scale.setDecimals(3)
        btn_apply_scale = QPushButton("Apply")
        btn_apply_scale.clicked.connect(self._apply_scale)
        scale_row.addWidget(self._spin_scale)
        scale_row.addWidget(btn_apply_scale)
        root.addLayout(scale_row)

        # ── Stability check ───────────────────────────────────────────
        stab_row = QHBoxLayout()
        self._btn_stab = QPushButton("Check Stability (10 shots)")
        self._btn_stab.clicked.connect(self._check_stability)
        self._lbl_stab = QLabel("")
        stab_row.addWidget(self._btn_stab)
        stab_row.addWidget(self._lbl_stab)
        root.addLayout(stab_row)

        # ── Waveform plot ─────────────────────────────────────────────
        if _HAS_PG:
            self._plot = pg.PlotWidget(title="Reference waveform")
            self._plot.setLabel("left",   "Amplitude", units="V")
            self._plot.setLabel("bottom", "Time",      units="s")
            self._curve = self._plot.plot(pen=pg.mkPen("y", width=1))
            root.addWidget(self._plot)
        else:
            root.addWidget(QLabel("(install pyqtgraph for live waveform)"))

    # ------------------------------------------------------------------ #
    # Slots                                                               #
    # ------------------------------------------------------------------ #

    def _on_reading(self, reading) -> None:
        if reading is None:
            self._lbl_amp.setText("Amplitude: —")
            self._lbl_chg.setText("Charge: —")
            self._lbl_sat.setText("")
            return
        try:
            self._lbl_amp.setText(f"Amplitude: {reading.amplitude_V*1000:.2f} mV")
            self._lbl_chg.setText(f"Charge: {reading.charge_pC:.3f} pC")
            if reading.saturated:
                self._lbl_sat.setText("⚠ SATURATED")
                self._lbl_sat.setStyleSheet("color: red; font-weight: bold;")
            else:
                self._lbl_sat.setText("OK")
                self._lbl_sat.setStyleSheet("color: green;")

            if _HAS_PG and reading.time_s is not None and reading.waveform_V is not None:
                self._curve.setData(reading.time_s, reading.waveform_V)
        except Exception:
            pass

    def _on_failed(self, msg: str) -> None:
        logger.debug("Intensity monitor poll failed: %s", msg)

    def _apply_scale(self) -> None:
        try:
            self._monitor.set_scale(self._spin_scale.value())
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Scale Error", str(exc))

    def _check_stability(self) -> None:
        try:
            stable, rms_rel = self._monitor.check_stability()
            msg = f"RMS {rms_rel*100:.2f} % — {'STABLE' if stable else 'UNSTABLE'}"
            self._lbl_stab.setText(msg)
            color = "green" if stable else "red"
            self._lbl_stab.setStyleSheet(f"color: {color};")
        except Exception as exc:
            self._lbl_stab.setText(str(exc))

    def set_monitor(self, monitor: IntensityMonitorBase) -> None:
        """Hot-swap the intensity monitor backend at runtime."""
        self._monitor = monitor
        self._reader.set_monitor(monitor)

    def shutdown(self) -> None:
        try:
            self._stop_requested.emit()
            self._reader_thread.quit()
            self._reader_thread.wait(2000)
        except Exception:
            pass
