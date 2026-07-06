"""
Bias supply control panel.

Provides:
  - Compliance setting (with red warning if too high)
  - Voltage setpoint + ramp controls
  - Live voltage / current readout with compliance indicator
  - Quick-off safety button
  - IV scan (bias sweep while recording current) — runs in a QThread
"""
from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import QTimer, Qt, Signal, QThread, QObject
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel, QDoubleSpinBox, QSpinBox,
    QPushButton, QProgressBar, QMessageBox,
)

try:
    import pyqtgraph as pg
    import numpy as np
    _HAS_PG = True
except ImportError:
    _HAS_PG = False

from devices.bias_supply_base import BiasSupplyBase
from controller.scan_controller import VoltageScanConfig
from gui.status_bus import notify


# ---------------------------------------------------------------------------
# IV scan worker (runs in QThread so the GUI stays responsive)
# ---------------------------------------------------------------------------

class _IVWorker(QObject):
    """
    Background worker that executes a blocking IV sweep.

    Signals
    -------
    point(float, float)   — emitted after each step: (voltage_V, current_A)
    progress(int)         — number of steps completed so far
    finished()            — emitted when the sweep ends (normally or on trip)
    error(str)            — emitted on exception
    """
    point    = Signal(float, float)   # (V, I)
    progress = Signal(int)
    finished = Signal()
    error    = Signal(str)

    def __init__(
        self,
        supply: BiasSupplyBase,
        voltages: list[float],
        compliance_A: float,
        delay_s: float,
        ramp_step_V: float,
    ) -> None:
        super().__init__()
        self._supply      = supply
        self._voltages    = voltages
        self._compliance  = compliance_A
        self._delay_s     = delay_s
        self._ramp_step_V = ramp_step_V
        self._abort       = False

    def abort(self) -> None:
        self._abort = True

    def run(self) -> None:
        try:
            self._supply.set_compliance(self._compliance)
            for idx, v in enumerate(self._voltages):
                if self._abort:
                    break
                self._supply.ramp_to(v, step_V=abs(self._ramp_step_V), delay_s=0.05)
                time.sleep(self._delay_s)
                r = self._supply.read()
                self.point.emit(r.voltage_V, r.current_A)
                self.progress.emit(idx + 1)
                if r.compliant:
                    break   # stop on compliance trip
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class _SupplyCallWorker(QObject):
    """Runs one blocking supply operation off the GUI thread."""

    done = Signal(str)   # "" on success, error text on failure

    def __init__(self, fn: Callable[[], None]) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self._fn()
            self.done.emit("")
        except Exception as exc:
            self.done.emit(str(exc))


class _ReadoutPoller(QObject):
    """Polls one channel's live readout + polarity in a dedicated QThread.

    Instrument reads (``read``/``get_polarity``/``supports_polarity_switch``)
    are blocking I/O on real hardware, so they must never run on the GUI
    thread.  The poller emits pure data back via queued signals; the panel only
    updates widgets.  It reads *nothing* until the supply reports ``connected``
    (mirrors the main-window ``_BiasPoller``), so constructing/starting it never
    touches hardware.
    """

    reading  = Signal(object)         # BiasReading, or None when unavailable
    polarity = Signal(object, bool)   # (polarity 'p'/'n'/None, supports_switch)

    def __init__(self, get_supply, interval_ms: int = 500) -> None:
        super().__init__()
        self._get_supply = get_supply
        self._timer = QTimer(self)     # parented → moves with us to the thread
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _poll(self) -> None:
        supply = self._get_supply()
        if supply is None or not getattr(supply, "connected", False):
            self.reading.emit(None)
            self.polarity.emit(None, False)
            return
        try:
            self.reading.emit(supply.read())
        except Exception:
            self.reading.emit(None)
        try:
            pol = supply.get_polarity()
        except Exception:
            pol = None
        try:
            supports = bool(supply.supports_polarity_switch())
        except Exception:
            supports = False
        self.polarity.emit(pol, supports)


class BiasPanel(QWidget):
    """
    GUI panel for a single bias supply channel.

    Signals
    -------
    output_toggled(bool)  — emitted when output state changes
    """

    output_toggled  = Signal(bool)
    vscan_requested = Signal(VoltageScanConfig)
    _read_stop_requested = Signal()

    _COMPLIANCE_WARN_A = 1e-3    # warn if compliance > 1 mA
    _POLL_MS = 500               # live readout interval
    _POL_SYMBOLS = {"p": "+", "n": "−"}

    def __init__(self, supply: BiasSupplyBase, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._supply = supply
        self._iv_v: list[float] = []
        self._iv_i: list[float] = []
        self._vscan_v: list[float] = []
        self._vscan_q: list[float] = []
        self._op_thread: QThread | None = None
        self._op_worker: _SupplyCallWorker | None = None
        self._io_busy = False
        self._last_polarity: str | None = None
        self._pol_supported = False
        self._build_ui()

        # ── Live readout + polarity poll (own thread — instrument I/O must
        #    never run on the GUI thread).  Safe to start now: it emits None
        #    until the supply reports connected, so it touches no hardware. ──
        self._read_poller = _ReadoutPoller(lambda: self._supply, self._POLL_MS)
        self._read_thread = QThread(self)
        self._read_poller.moveToThread(self._read_thread)
        self._read_thread.started.connect(self._read_poller.start)
        self._read_stop_requested.connect(self._read_poller.stop)
        self._read_thread.finished.connect(self._read_poller.deleteLater)
        self._read_poller.reading.connect(self.set_reading)
        self._read_poller.polarity.connect(self._on_polarity_polled)
        self._read_thread.start()

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── Safety / compliance ────────────────────────────────────────
        safe_box = QGroupBox("⚠ Compliance (current limit)")
        safe_form = QFormLayout(safe_box)

        comp_uA = max(0.001, float(getattr(self._supply, "compliance_A", 100e-6)) * 1e6)
        self._spin_comp = QDoubleSpinBox()
        self._spin_comp.setRange(0.001, 10000.0)
        self._spin_comp.setDecimals(3)
        self._spin_comp.setSingleStep(1.0)
        self._spin_comp.setValue(comp_uA)
        self._spin_comp.setSuffix(" µA")
        self._spin_comp.setToolTip(
            "Current compliance limit.\n"
            "Too high a value can DESTROY the sensor if breakdown occurs!"
        )
        self._spin_comp.valueChanged.connect(self._on_compliance_changed)
        self._lbl_comp_warn = QLabel("")
        self._lbl_comp_warn.setStyleSheet("color: red; font-weight: bold;")

        safe_form.addRow("Compliance:", self._spin_comp)
        safe_form.addRow(self._lbl_comp_warn)

        self._btn_set_comp = QPushButton("Apply Compliance")
        self._btn_set_comp.clicked.connect(self._apply_compliance)
        safe_form.addRow(self._btn_set_comp)
        root.addWidget(safe_box)

        # ── Voltage control ────────────────────────────────────────────
        volt_box = QGroupBox("Bias Voltage")
        volt_form = QFormLayout(volt_box)

        vlim = abs(float(getattr(self._supply, "voltage_range_V", None) or 1100.0))

        self._spin_volt = QDoubleSpinBox()
        self._spin_volt.setRange(-vlim, vlim)
        self._spin_volt.setDecimals(1)
        self._spin_volt.setSingleStep(10.0)
        self._spin_volt.setValue(float(getattr(self._supply, "setpoint_V", 0.0)))
        self._spin_volt.setSuffix(" V")
        volt_form.addRow("Target voltage:", self._spin_volt)

        self._spin_step = QDoubleSpinBox()
        self._spin_step.setRange(0.1, 100.0)
        self._spin_step.setDecimals(1)
        self._spin_step.setValue(5.0)
        self._spin_step.setSuffix(" V/step")
        volt_form.addRow("Ramp step:", self._spin_step)

        self._spin_delay = QDoubleSpinBox()
        self._spin_delay.setRange(0.01, 10.0)
        self._spin_delay.setDecimals(2)
        self._spin_delay.setValue(0.1)
        self._spin_delay.setSuffix(" s")
        volt_form.addRow("Step delay:", self._spin_delay)

        btn_row = QHBoxLayout()
        self._btn_apply = QPushButton("▶ Ramp to Voltage")
        self._btn_apply.clicked.connect(self._apply_voltage)
        self._btn_off = QPushButton("⏹ Output OFF (0 V)")
        self._btn_off.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold;")
        self._btn_off.clicked.connect(self._emergency_off)
        btn_row.addWidget(self._btn_apply)
        btn_row.addWidget(self._btn_off)
        volt_form.addRow(btn_row)
        root.addWidget(volt_box)

        # ── Live readout ───────────────────────────────────────────────
        read_box = QGroupBox("Live Readout")
        read_form = QFormLayout(read_box)

        self._lbl_v = QLabel("— V")
        self._lbl_i = QLabel("— A")
        self._lbl_comp_status = QLabel("OK")
        self._lbl_comp_status.setAlignment(Qt.AlignmentFlag.AlignCenter)

        read_form.addRow("Voltage:", self._lbl_v)
        read_form.addRow("Current:", self._lbl_i)
        read_form.addRow("Compliance:", self._lbl_comp_status)
        root.addWidget(read_box)

        # ── Polarity ───────────────────────────────────────────────────
        # Read-only indicator (polled off-thread) + a DANGEROUS switch button
        # that only appears when the supply reports the channel reversible.
        pol_box = QGroupBox("Polarity")
        pol_form = QFormLayout(pol_box)
        self._lbl_polarity = QLabel("—")
        self._lbl_polarity.setStyleSheet("font-weight: 700; font-size: 16px;")
        self._lbl_polarity.setToolTip("Current HV output polarity (read-only).")
        pol_form.addRow("Current polarity:", self._lbl_polarity)
        self._btn_polarity = QPushButton("⇄ Switch Polarity")
        self._btn_polarity.setObjectName("dangerBtn")
        self._btn_polarity.setToolTip(
            "Reverse HV polarity (throws an HV relay).\n"
            "Output must be OFF and fully discharged first."
        )
        self._btn_polarity.clicked.connect(self._on_switch_polarity)
        self._btn_polarity.setVisible(False)   # shown only when reversible
        pol_form.addRow(self._btn_polarity)
        root.addWidget(pol_box)

        # ── IV scan ────────────────────────────────────────────────────
        iv_box = QGroupBox("IV Scan")
        iv_box.setCheckable(True)
        iv_box.setChecked(False)
        iv_form = QFormLayout(iv_box)

        self._spin_iv_start = QDoubleSpinBox()
        self._spin_iv_start.setRange(-vlim, vlim)
        self._spin_iv_start.setValue(0.0)
        self._spin_iv_start.setSuffix(" V")

        self._spin_iv_stop = QDoubleSpinBox()
        self._spin_iv_stop.setRange(-vlim, vlim)
        self._spin_iv_stop.setValue(-300.0)
        self._spin_iv_stop.setSuffix(" V")

        self._spin_iv_step = QDoubleSpinBox()
        self._spin_iv_step.setRange(0.1, 100.0)
        self._spin_iv_step.setValue(10.0)
        self._spin_iv_step.setSuffix(" V")

        self._spin_iv_delay = QDoubleSpinBox()
        self._spin_iv_delay.setRange(0.1, 60.0)
        self._spin_iv_delay.setValue(1.0)
        self._spin_iv_delay.setSuffix(" s")

        iv_form.addRow("Start:", self._spin_iv_start)
        iv_form.addRow("Stop:",  self._spin_iv_stop)
        iv_form.addRow("Step:",  self._spin_iv_step)
        iv_form.addRow("Delay:", self._spin_iv_delay)

        self._iv_progress = QProgressBar()
        self._iv_progress.setValue(0)
        iv_form.addRow(self._iv_progress)

        self._btn_iv = QPushButton("▶ Run IV Scan")
        self._btn_iv.clicked.connect(self._run_iv_scan)
        iv_form.addRow(self._btn_iv)

        if _HAS_PG:
            self._iv_plot = pg.PlotWidget(title="IV Curve")
            self._iv_plot.setLabel("left",   "Current", units="A")
            self._iv_plot.setLabel("bottom", "Voltage", units="V")
            self._iv_plot.setMaximumHeight(160)
            self._iv_curve = self._iv_plot.plot(pen=pg.mkPen("y", width=2))
            iv_form.addRow(self._iv_plot)

        root.addWidget(iv_box)

        # ── Bias + waveform scan (requires ScanController) ─────────────
        vscan_box = QGroupBox("Bias + Waveform Scan (CCE vs. Voltage)")
        vscan_box.setCheckable(True)
        vscan_box.setChecked(False)
        vscan_form = QFormLayout(vscan_box)

        self._spin_vs_start = self._make_dspin(-vlim, vlim, 0.0, " V")
        self._spin_vs_stop  = self._make_dspin(-vlim, vlim, -300.0, " V")
        self._spin_vs_step  = self._make_dspin(-100.0,  -0.1,   -10.0, " V")
        self._spin_vs_hold  = self._make_dspin(0.1, 60.0, 1.0, " s")
        self._spin_vs_nav   = QSpinBox()
        self._spin_vs_nav.setRange(1, 100)
        self._spin_vs_nav.setValue(3)

        vscan_form.addRow("V start:",   self._spin_vs_start)
        vscan_form.addRow("V stop:",    self._spin_vs_stop)
        vscan_form.addRow("V step:",    self._spin_vs_step)
        vscan_form.addRow("Hold (s):",  self._spin_vs_hold)
        vscan_form.addRow("Averages:",  self._spin_vs_nav)

        self._btn_vscan = QPushButton("▶ Start Bias+Waveform Scan")
        self._btn_vscan.clicked.connect(self._emit_vscan)
        vscan_form.addRow(self._btn_vscan)

        if _HAS_PG:
            self._vscan_plot = pg.PlotWidget(title="Charge vs. Bias")
            self._vscan_plot.setLabel("left",   "Charge", units="pC")
            self._vscan_plot.setLabel("bottom", "Bias", units="V")
            self._vscan_plot.setMaximumHeight(160)
            self._vscan_curve = self._vscan_plot.plot(
                pen=pg.mkPen("c", width=2), symbol="o", symbolSize=4
            )
            vscan_form.addRow(self._vscan_plot)

        root.addWidget(vscan_box)
        self._on_compliance_changed(self._spin_comp.value())

    # ------------------------------------------------------------------ #
    # Slots                                                               #
    # ------------------------------------------------------------------ #

    def _on_compliance_changed(self, value: float) -> None:
        if value * 1e-6 > self._COMPLIANCE_WARN_A:
            self._lbl_comp_warn.setText(
                f"⚠ Compliance > {self._COMPLIANCE_WARN_A*1e3:.0f} mA — risk of sensor damage!"
            )
        else:
            self._lbl_comp_warn.setText("")

    def _apply_compliance(self) -> None:
        compliance_A = self._spin_comp.value() * 1e-6
        self._run_supply_call(
            lambda: self._supply.set_compliance(compliance_A),
            self._on_apply_compliance_done,
        )

    def _apply_voltage(self) -> None:
        target_V = self._spin_volt.value()
        step_V = self._spin_step.value()
        delay_s = self._spin_delay.value()
        self._run_supply_call(
            lambda: self._supply.ramp_to(
                target_V,
                step_V=step_V,
                delay_s=delay_s,
            ),
            self._on_apply_voltage_done,
        )

    def _emergency_off(self) -> None:
        self._run_supply_call(
            self._do_emergency_off,
            self._on_emergency_off_done,
        )

    def set_reading(self, r) -> None:
        if r is None:
            self._lbl_v.setText("— V")
            self._lbl_i.setText("— A")
            self._lbl_comp_status.setText("—")
            self._lbl_comp_status.setStyleSheet("")
            return
        try:
            self._lbl_v.setText(f"{r.voltage_V:.2f} V")
            i_uA = r.current_A * 1e6
            self._lbl_i.setText(f"{i_uA:.3f} µA")
            if r.compliant:
                self._lbl_comp_status.setText("⚠ COMPLIANCE HIT")
                self._lbl_comp_status.setStyleSheet(
                    "background-color: red; color: white; font-weight: bold;"
                )
            else:
                self._lbl_comp_status.setText("OK")
                self._lbl_comp_status.setStyleSheet(
                    "background-color: green; color: white;"
                )
        except Exception:
            pass

    def _emit_vscan(self) -> None:
        cfg = VoltageScanConfig(
            v_start_V=self._spin_vs_start.value(),
            v_stop_V=self._spin_vs_stop.value(),
            v_step_V=self._spin_vs_step.value(),
            hold_delay_s=self._spin_vs_hold.value(),
            n_averages=self._spin_vs_nav.value(),
        )
        self._vscan_v = []
        self._vscan_q = []
        self.vscan_requested.emit(cfg)

    def _on_vscan_point_cb(self, voltage_V: float, charge_pC: float, current_A: float) -> None:
        """Called by ScanController for each voltage step."""
        self._vscan_v.append(voltage_V)
        self._vscan_q.append(charge_pC)
        if _HAS_PG:
            self._vscan_curve.setData(self._vscan_v, self._vscan_q)

    @staticmethod
    def _make_dspin(lo: float, hi: float, val: float, suffix: str = "") -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setValue(val)
        s.setDecimals(1)
        if suffix:
            s.setSuffix(suffix)
        return s

    def _run_iv_scan(self) -> None:
        """Start the IV scan in a background QThread."""
        import numpy as np

        start = self._spin_iv_start.value()
        stop  = self._spin_iv_stop.value()
        step  = self._spin_iv_step.value()
        delay = self._spin_iv_delay.value()

        # Determine sign of step automatically
        if stop >= start:
            voltages = list(np.arange(start, stop + step / 2, step))
        else:
            voltages = list(np.arange(start, stop - step / 2, -step))
        if not voltages:
            return

        self._iv_v, self._iv_i = [], []
        self._iv_progress.setMaximum(len(voltages))
        self._iv_progress.setValue(0)
        self._btn_iv.setEnabled(False)

        self._iv_worker = _IVWorker(
            supply=self._supply,
            voltages=voltages,
            compliance_A=self._spin_comp.value() * 1e-6,
            delay_s=delay,
            ramp_step_V=step,
        )
        self._iv_thread = QThread(self)
        self._iv_worker.moveToThread(self._iv_thread)

        # Connect worker signals
        self._iv_thread.started.connect(self._iv_worker.run)
        self._iv_worker.point.connect(self._on_iv_point)
        self._iv_worker.progress.connect(self._iv_progress.setValue)
        self._iv_worker.finished.connect(self._iv_thread.quit)
        self._iv_worker.finished.connect(lambda: self._btn_iv.setEnabled(True))
        self._iv_worker.error.connect(
            lambda msg: self._lbl_v.setText(f"IV Error: {msg}")
        )
        # Clean up thread object when done
        self._iv_thread.finished.connect(self._iv_thread.deleteLater)

        self._iv_thread.start()

    def _on_iv_point(self, v: float, i: float) -> None:
        self._iv_v.append(v)
        self._iv_i.append(i)
        if _HAS_PG:
            self._iv_curve.setData(self._iv_v, self._iv_i)

    def _run_supply_call(self, fn: Callable[[], None], on_done) -> bool:
        if self._op_thread is not None and self._op_thread.isRunning():
            self._lbl_comp_warn.setText("Another bias operation is still running.")
            return False

        self._set_io_busy(True)
        self._op_worker = _SupplyCallWorker(fn)
        self._op_thread = QThread(self)
        self._op_worker.moveToThread(self._op_thread)
        self._op_thread.started.connect(self._op_worker.run)

        def _finish(err: str) -> None:
            thread = self._op_thread
            self._op_thread = None
            self._op_worker = None
            if thread is not None:
                thread.quit()
                thread.wait(2000)
            self._set_io_busy(False)
            on_done(err)

        self._op_worker.done.connect(_finish)
        self._op_thread.start()
        return True

    def _set_io_busy(self, busy: bool) -> None:
        self._io_busy = busy
        for widget in (self._btn_set_comp, self._btn_apply, self._btn_off,
                       self._btn_iv, self._btn_vscan):
            widget.setEnabled(not busy)
        # Polarity button follows both the busy state and whether the supply
        # reports the channel reversible (tracked from the poll thread).
        self._btn_polarity.setEnabled(self._pol_supported and not busy)

    def _on_polarity_polled(self, polarity, supports: bool) -> None:
        """Update the read-only polarity indicator + switch-button visibility
        from data delivered by the readout poll thread (pure widget work)."""
        self._last_polarity = polarity if polarity in ("p", "n") else None
        self._pol_supported = bool(supports)
        self._lbl_polarity.setText(self._POL_SYMBOLS.get(self._last_polarity, "—"))
        self._btn_polarity.setVisible(self._pol_supported)
        self._btn_polarity.setEnabled(self._pol_supported and not self._io_busy)

    def _on_switch_polarity(self) -> None:
        """Confirm, then reverse HV polarity off the GUI thread (DANGEROUS).

        The driver enforces the real gate (output OFF + discharged + confirm);
        this adds the mandatory explicit user confirmation on top."""
        target = {"p": "n", "n": "p"}.get(self._last_polarity)
        ch = getattr(self._supply, "channel", "?")
        if target is None:
            notify("Current polarity unknown — wait for the readout before switching.",
                   "warn")
            return
        cur_sym = self._POL_SYMBOLS.get(self._last_polarity, "?")
        tgt_sym = self._POL_SYMBOLS.get(target, "?")
        reply = QMessageBox.warning(
            self, "Reverse HV Polarity",
            f"Reverse HV polarity on CH{ch}  ({cur_sym} → {tgt_sym})?\n\n"
            "Output must be OFF and fully discharged.\n"
            "This physically throws an HV relay.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._run_supply_call(
            lambda: self._supply.set_polarity(target),
            self._on_switch_polarity_done,
        )

    def _on_switch_polarity_done(self, err: str) -> None:
        ch = getattr(self._supply, "channel", "?")
        if err:
            notify(f"CH{ch} polarity switch failed: {err}", "error")
        else:
            notify(f"CH{ch} polarity switched.", "info")

    def _do_emergency_off(self) -> None:
        # Disable the output even if the ramp raises — output_off is the
        # safety-critical step and must never be skipped by a ramp error.
        try:
            self._supply.ramp_to(0.0, step_V=20.0, delay_s=0.05)
        finally:
            self._supply.output_off()

    def _on_apply_compliance_done(self, err: str) -> None:
        if err:
            self._lbl_comp_warn.setText(f"Error: {err}")
            return
        self._on_compliance_changed(self._spin_comp.value())

    def _on_apply_voltage_done(self, err: str) -> None:
        if err:
            self._lbl_v.setText(f"Error: {err}")

    def _on_emergency_off_done(self, err: str) -> None:
        if err:
            self._lbl_v.setText(f"Error: {err}")

    def shutdown(self) -> None:
        try:
            worker = getattr(self, "_iv_worker", None)
            if worker is not None:
                worker.abort()
        except Exception:
            pass
        try:
            thread = getattr(self, "_iv_thread", None)
            if thread is not None and thread.isRunning():
                thread.quit()
                thread.wait(2000)
        except Exception:
            pass
        try:
            if self._op_thread is not None and self._op_thread.isRunning():
                self._op_thread.quit()
                self._op_thread.wait(2000)
        except Exception:
            pass
        try:
            thread = getattr(self, "_read_thread", None)
            if thread is not None and thread.isRunning():
                self._read_stop_requested.emit()   # stop the QTimer in its thread
                thread.quit()
                thread.wait(2000)
        except Exception:
            pass

