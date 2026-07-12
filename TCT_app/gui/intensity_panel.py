"""
Reference Monitor panel (laser-intensity reference).

Displays real-time reference photodiode / SiPM amplitude + stability with the
live waveform as the hero (design system §7 "Reference Monitor: 2 tiles +
chip + waveform hero").  Works with any IntensityMonitorBase implementation —
swap the backend and this panel adapts automatically.

No ``refresh_theme`` needed by design: the waveform lives on the fixed-dark
instrument canvas (``gui.style.PLOT_BG`` — identical in both themes), its pen
is resolved once against that fixed canvas, and every other surface here is
app-stylesheet QSS that repaints globally on a theme switch.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QTimer, QThread, QObject, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QDoubleSpinBox, QPushButton,
)

try:
    import pyqtgraph as pg
    _HAS_PG = True
except ImportError:
    _HAS_PG = False

from devices.intensity_base import IntensityMonitorBase
from gui.panel_kit import FigureCard, MetricGrid, panel_header
from gui.status_widgets import StatusChip, flash_button, set_button_icon
from gui.style import axis_color

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

        # ONE status chip (§7): live/offline/saturated, most-important-wins.
        self._chip_live = StatusChip("Monitor offline", "disconnected")
        root.addWidget(panel_header(
            "TCT Control · Instrument", "Reference Monitor",
            trailing=[self._chip_live],
        ))

        # ── Top strip: exactly two tiles (§7) ─────────────────────────
        # Amplitude carries charge in its caption (subordinated, still
        # reachable); Stability holds the last stability-check result.
        self._metrics = MetricGrid(columns=2)
        self._tile_amp = self._metrics.add_tile(("Amplitude", "--"))
        self._tile_stab = self._metrics.add_tile(("Stability", "--"))
        self._tile_amp.set_stale(True, "monitor offline")
        self._tile_stab.set_stale(True, "not yet measured")
        root.addWidget(self._metrics)

        # ── Waveform hero ─────────────────────────────────────────────
        if _HAS_PG:
            self._figure = FigureCard("Reference waveform")
            self._plot = self._figure.plot
            self._plot.setLabel("left",   "Amplitude", units="V")
            self._plot.setLabel("bottom", "Time",      units="s")
            # Laser-reference data ink, resolved once against the fixed-dark
            # instrument canvas (PLOT_BG is theme-invariant, so the dark-mode
            # rail colour is always the right contrast — no refresh needed).
            self._curve = self._plot.plot(
                pen=pg.mkPen(axis_color("laser", "dark"), width=1))
            root.addWidget(self._figure, 1)
        else:
            root.addWidget(QLabel("(install pyqtgraph for live waveform)"))

        # ── Command row: scale + stability check ──────────────────────
        cmd_row = QHBoxLayout()
        cmd_row.addWidget(QLabel("Scale (V/div):"))
        self._spin_scale = QDoubleSpinBox()
        self._spin_scale.setRange(0.001, 10.0)
        self._spin_scale.setValue(0.1)
        self._spin_scale.setDecimals(3)
        cmd_row.addWidget(self._spin_scale)
        self._btn_apply_scale = QPushButton("Apply scale")
        self._btn_apply_scale.setProperty("state", "secondary")
        set_button_icon(self._btn_apply_scale, "mdi.tune")
        self._btn_apply_scale.clicked.connect(self._apply_scale)
        cmd_row.addWidget(self._btn_apply_scale)
        cmd_row.addStretch(1)
        self._btn_stab = QPushButton("Check stability (10 shots)")
        self._btn_stab.setProperty("state", "secondary")
        set_button_icon(self._btn_stab, "mdi.chart-bell-curve")
        self._btn_stab.clicked.connect(self._check_stability)
        cmd_row.addWidget(self._btn_stab)
        root.addLayout(cmd_row)

    # ------------------------------------------------------------------ #
    # Slots                                                               #
    # ------------------------------------------------------------------ #

    def _on_reading(self, reading) -> None:
        if reading is None:
            # Law 4: the tile keeps its last value but goes stale with a
            # caption saying why — never a silently frozen number.
            self._tile_amp.set_stale(True, "monitor offline")
            self._chip_live.set_status("Monitor offline", "disconnected")
            return
        try:
            self._tile_amp.set_value(f"{reading.amplitude_V*1000:.2f} mV")
            self._tile_amp.set_stale(False, f"charge {reading.charge_pC:.3f} pC")
            if reading.saturated:
                # The single chip carries the most important state (law 2:
                # saturation is a data-validity warning, amber not red).
                self._chip_live.set_status(
                    "Saturated", "warn",
                    "Reference signal is clipping — reduce intensity or scale")
                self._tile_amp.set_state("warn")
            else:
                self._chip_live.set_status("Monitor live", "busy")
                self._tile_amp.set_state("normal")

            if _HAS_PG and reading.time_s is not None and reading.waveform_V is not None:
                self._curve.setData(reading.time_s, reading.waveform_V)
        except Exception:
            pass

    def _on_failed(self, msg: str) -> None:
        logger.debug("Intensity monitor poll failed: %s", msg)

    def _apply_scale(self) -> None:
        try:
            self._monitor.set_scale(self._spin_scale.value())
            flash_button(self._btn_apply_scale, "good", "Applied")
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Scale error", str(exc))

    def _check_stability(self) -> None:
        try:
            stable, rms_rel = self._monitor.check_stability()
            self._tile_stab.set_value(f"{rms_rel*100:.2f} %")
            self._tile_stab.set_state("normal" if stable else "warn")
            self._tile_stab.set_stale(
                False, "stable over 10 shots" if stable else "unstable over 10 shots")
            flash_button(self._btn_stab, "good" if stable else "warn")
        except Exception as exc:
            self._tile_stab.set_value("--")
            self._tile_stab.set_state("crit")
            self._tile_stab.set_stale(False, f"check failed: {exc}")

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
