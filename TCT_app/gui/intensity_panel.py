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
from gui.status_widgets import ReadoutCell, StatusChip, flash_button, set_button_icon

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
        vals_v = QVBoxLayout(vals_box)
        status_row = QHBoxLayout()
        self._chip_live = StatusChip("Monitor offline", "neutral")
        self._chip_sat = StatusChip("Saturation --", "neutral")
        self._chip_stab = StatusChip("Stability --", "neutral")
        self._chip_scale = StatusChip("Scale --", "neutral")
        for chip in (self._chip_live, self._chip_sat, self._chip_stab, self._chip_scale):
            status_row.addWidget(chip)
        status_row.addStretch(1)
        vals_v.addLayout(status_row)
        vals_layout = QHBoxLayout()
        self._lbl_amp = ReadoutCell("Amplitude", "--")
        self._lbl_chg = ReadoutCell("Charge", "--")
        vals_layout.addWidget(self._lbl_amp)
        vals_layout.addWidget(self._lbl_chg)
        vals_layout.addStretch(1)
        vals_v.addLayout(vals_layout)
        root.addWidget(vals_box)

        # ── Scale control ─────────────────────────────────────────────
        scale_row = QHBoxLayout()
        scale_row.addWidget(QLabel("Scale (V/div):"))
        self._spin_scale = QDoubleSpinBox()
        self._spin_scale.setRange(0.001, 10.0)
        self._spin_scale.setValue(0.1)
        self._spin_scale.setDecimals(3)
        self._btn_apply_scale = QPushButton("Apply")
        set_button_icon(self._btn_apply_scale, "mdi.tune")
        self._btn_apply_scale.clicked.connect(self._apply_scale)
        scale_row.addWidget(self._spin_scale)
        scale_row.addWidget(self._btn_apply_scale)
        root.addLayout(scale_row)

        # ── Stability check ───────────────────────────────────────────
        stab_row = QHBoxLayout()
        self._btn_stab = QPushButton("Check Stability (10 shots)")
        set_button_icon(self._btn_stab, "mdi.chart-bell-curve")
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
            self._lbl_amp.set_value("--")
            self._lbl_chg.set_value("--")
            self._chip_live.set_status("Monitor offline", "neutral")
            self._chip_sat.set_status("Saturation --", "neutral")
            return
        try:
            self._chip_live.set_status("Monitor live", "busy")
            self._lbl_amp.set_value(f"{reading.amplitude_V*1000:.2f} mV")
            self._lbl_chg.set_value(f"{reading.charge_pC:.3f} pC")
            if reading.saturated:
                self._chip_sat.set_status("Saturated", "warn")
            else:
                self._chip_sat.set_status("Saturation OK", "good")

            if _HAS_PG and reading.time_s is not None and reading.waveform_V is not None:
                self._curve.setData(reading.time_s, reading.waveform_V)
        except Exception:
            pass

    def _on_failed(self, msg: str) -> None:
        logger.debug("Intensity monitor poll failed: %s", msg)

    def _apply_scale(self) -> None:
        try:
            self._monitor.set_scale(self._spin_scale.value())
            self._chip_scale.set_status(f"Scale {self._spin_scale.value():.3g} V/div", "good")
            flash_button(self._btn_apply_scale, "good", "Applied")
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            self._chip_scale.set_status("Scale error", "crit", str(exc))
            QMessageBox.warning(self, "Scale Error", str(exc))

    def _check_stability(self) -> None:
        try:
            stable, rms_rel = self._monitor.check_stability()
            msg = f"RMS {rms_rel*100:.2f} % — {'STABLE' if stable else 'UNSTABLE'}"
            self._lbl_stab.setText(msg)
            color = "green" if stable else "red"
            self._lbl_stab.setStyleSheet(f"color: {color};")
            self._chip_stab.set_status("Stable" if stable else "Unstable",
                                       "good" if stable else "warn")
            flash_button(self._btn_stab, "good" if stable else "warn")
        except Exception as exc:
            self._lbl_stab.setText(str(exc))
            self._chip_stab.set_status("Stability error", "crit", str(exc))

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
