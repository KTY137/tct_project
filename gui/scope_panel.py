"""Oscilloscope / DUT waveform panel."""
from __future__ import annotations

import logging
import math
import re
from pathlib import Path

import numpy as np
import yaml
from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QGroupBox, QLabel, QPushButton, QCheckBox, QSlider, QLineEdit,
    QComboBox, QDoubleSpinBox, QDialog, QDialogButtonBox, QMessageBox,
)

try:
    import pyqtgraph as pg
    _HAS_PG = True
except ImportError:
    _HAS_PG = False

from devices.oscilloscope import Oscilloscope
from analysis.waveform_analysis import analyse_waveform
from gui.status_bus import notify

logger = logging.getLogger(__name__)

# Marker colours
_COL_ONSET    = (80,  200, 80)   # green  – onset
_COL_TRAILING = (200, 80,  80)   # red    – trailing / end of drift
_COL_CFD      = (255, 200, 0)    # yellow – CFD threshold
_COL_INTWIN   = (60,  60,  160)  # blue   – integration window fill

# ─────────────────────────────────────────────────────────────────────
# Engineering-notation helpers (auto ns/µs/mV…)
# ─────────────────────────────────────────────────────────────────────
_SI = [(1e-12, "p"), (1e-9, "n"), (1e-6, "µ"), (1e-3, "m"),
       (1.0, ""), (1e3, "k"), (1e6, "M")]
_PREFIX = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3,
           "": 1.0, "k": 1e3, "M": 1e6}
_QTY_RE = re.compile(r"^([-+]?[\d.]+(?:[eE][-+]?\d+)?)\s*([pnuµmkM]?)\s*([a-zA-Z]*)$")


def _eng_format(value: float, unit: str) -> str:
    """5e-8, 's' -> '50 ns';  0.5, 'V' -> '500 mV'."""
    if value == 0:
        return f"0 {unit}"
    for scale, pre in reversed(_SI):
        if abs(value) >= scale:
            return f"{value / scale:g} {pre}{unit}"
    scale, pre = _SI[0]
    return f"{value / scale:g} {pre}{unit}"


def _parse_quantity(text: str) -> float | None:
    """'50ns'|'2 us'|'0.5V'|'100mV' -> SI base value (seconds / volts)."""
    m = _QTY_RE.match(text.strip().replace(" ", ""))
    if not m:
        return None
    return float(m.group(1)) * _PREFIX.get(m.group(2), 1.0)


def _seq_125(lo: float, hi: float) -> list[float]:
    """1-2-5 sequence of per-division values from *lo* to *hi*."""
    out: list[float] = []
    e = math.floor(math.log10(lo))
    for dec in range(e, e + 13):
        for mant in (1, 2, 5):
            val = mant * (10.0 ** dec)
            if lo * 0.9999 <= val <= hi * 1.0001:
                out.append(val)
    return out


def _nearest_125(value: float, seq: list[float]) -> int:
    """Index of the sequence entry closest to *value* (log distance)."""
    value = max(value, seq[0])
    return min(range(len(seq)),
               key=lambda i: abs(math.log10(seq[i]) - math.log10(value)))


class _TriggerDialog(QDialog):
    """Modeless trigger-settings window (source / level / slope)."""

    def __init__(self, scope: Oscilloscope, config_path: str | None,
                 apply_trigger,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Oscilloscope — Trigger Settings")
        self._scope = scope
        self._config_path = config_path
        self._apply_trigger_async = apply_trigger
        form = QFormLayout(self)

        self._source = QComboBox()
        self._source.addItems(["EXT", "CH1", "CH2", "CH3", "CH4", "LINE"])
        self._source.setCurrentText(str(getattr(scope, "trig_source", "EXT")))
        self._level = QDoubleSpinBox()
        self._level.setRange(-50.0, 50.0)
        self._level.setDecimals(3)
        self._level.setSuffix(" V")
        self._level.setValue(float(getattr(scope, "trig_level_V", -0.41)))
        self._slope = QComboBox()
        self._slope.addItems(["FALL", "RISE"])
        self._slope.setCurrentText(str(getattr(scope, "trig_slope", "FALL")))
        form.addRow("Source:", self._source)
        form.addRow("Level:", self._level)
        form.addRow("Slope:", self._slope)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#888;")
        form.addRow(self._status)

        bb = QDialogButtonBox()
        apply_btn = bb.addButton("Apply", QDialogButtonBox.AcceptRole)
        bb.addButton("Close", QDialogButtonBox.RejectRole)
        apply_btn.clicked.connect(self._apply)
        bb.rejected.connect(self.close)
        form.addRow(bb)

    def _apply(self) -> None:
        src = self._source.currentText()
        lvl = self._level.value()
        slope = self._slope.currentText()
        self._status.setText("Applying…")
        self._apply_trigger_async(src, lvl, slope, self)

    def show_trigger_result(self, src: str, lvl: float, slope: str, err: str | None) -> None:
        if err:
            self._status.setText(f"Apply failed: {err}")
            return
        _save_trigger_to_yaml(self._config_path, src, lvl, slope)
        self._status.setText(f"Applied: {src}, {lvl:g} V, {slope}"
                             + ("" if self._scope.connected else "  (saved; not connected)"))


def _save_trigger_to_yaml(path: str | None, source: str, level: float, slope: str) -> None:
    """Persist the trigger keys into devices.yaml (merge, preserve the rest)."""
    if not path:
        return
    p = Path(path)
    try:
        cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        osc = cfg.setdefault("oscilloscope", {})
        osc["trigger_source"] = source
        osc["trigger_level_V"] = float(level)
        osc["trigger_slope"] = slope
        p.write_text(yaml.dump(cfg, default_flow_style=False, sort_keys=False,
                               allow_unicode=True), encoding="utf-8")
    except Exception:
        pass


class _ScopeReader(QObject):
    """Acquires both channels in a dedicated QThread.

    VISA transfers take 10s of ms (or seconds when the scope stalls); running
    them on the GUI thread froze the window on every live-view tick.  Timer
    start/stop and read_once are only ever invoked via queued signals, so all
    I/O happens in the reader thread; ``Oscilloscope.io_lock`` serialises it
    against the scan thread.
    """
    acquired = Signal(object, object, object, object)   # t1, v1, t2, v2
    failed   = Signal(str)
    test_done = Signal(str)
    settings_done = Signal(object, str)   # settings dict, error text
    sync_done = Signal(str)
    trigger_done = Signal(str)

    def __init__(self, scope: Oscilloscope) -> None:
        super().__init__()
        self._scope = scope
        # Live acquisition timer — started/stopped via C++ Qt slots.
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(300)
        self._live_timer.timeout.connect(self.read_once)
        # Single-shot timer for one-off acquisitions — fired via C++ start() slot.
        self._once_timer = QTimer(self)
        self._once_timer.setSingleShot(True)
        self._once_timer.setInterval(0)
        self._once_timer.timeout.connect(self.read_once)

    def read_once(self) -> None:
        if not self._scope.connected:
            # Don't leave a blank plot unexplained — surface it once.  The panel
            # de-duplicates identical messages, so a live-view tick loop only
            # notifies a single time until the state changes.
            self.failed.emit("Oscilloscope not connected.")
            return
        try:
            t1, v1 = self._scope.read_channel(1)
            t2, v2 = self._scope.read_channel(2)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.acquired.emit(t1, v1, t2, v2)

    def test_connection(self) -> None:
        try:
            self.test_done.emit(self._scope.test_connection())
        except Exception as exc:
            self.test_done.emit(f"Test failed: {exc}")

    def read_settings(self) -> None:
        if not self._scope.connected:
            self.settings_done.emit({}, "Oscilloscope not connected.")
            return
        try:
            self.settings_done.emit(self._scope.read_settings(), "")
        except Exception as exc:
            self.settings_done.emit({}, str(exc))

    def sync_scope(self, tdiv: float, vdiv: float, voff_frac: float) -> None:
        if not self._scope.connected:
            self.sync_done.emit("")
            return
        try:
            self._scope.set_timebase(tdiv)
            self._scope.set_channel_scale(1, vdiv)
            self._scope.set_channel_scale(2, vdiv)
            if hasattr(self._scope, "set_channel_position"):
                self._scope.set_channel_position(2, voff_frac * 4.0)
            self.sync_done.emit("")
        except Exception as exc:
            self.sync_done.emit(str(exc))

    def apply_trigger(self, source: str, level_V: float, slope: str) -> None:
        try:
            self._scope.configure_tct_trigger(source, level_V, slope)
            self.trigger_done.emit("")
        except Exception as exc:
            self.trigger_done.emit(str(exc))


class ScopePanel(QWidget):
    # Queued requests into the reader thread (auto-queued: different thread).
    _acquire_requested   = Signal()   # -> reader._once_timer.start()
    _live_start_requested = Signal()   # -> reader._live_timer.start()
    _live_stop_requested  = Signal()   # -> reader._live_timer.stop()
    _test_requested       = Signal()
    _settings_requested   = Signal()
    _sync_requested       = Signal(float, float, float)
    _trigger_requested    = Signal(str, float, str)

    def __init__(self, scope: Oscilloscope, config_path: str | None = None,
                 analysis_kwargs: dict | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scope = scope
        self._config_path = config_path
        # Waveform-analysis parameters from devices.yaml (analysis: block) so
        # the live readout uses the same window/termination as the scans.
        self._analysis_kwargs = dict(analysis_kwargs or {})
        self._last_t1: np.ndarray | None = None
        self._last_v1: np.ndarray | None = None
        self._last_t2: np.ndarray | None = None
        self._last_v2: np.ndarray | None = None
        self._trigger_dialog: _TriggerDialog | None = None
        # Display scale state (seconds / volts per division) + pan fractions.
        self._tdiv_seq = _seq_125(1e-9, 1.0)      # 1 ns … 1 s
        self._vdiv_seq = _seq_125(1e-3, 10.0)     # 1 mV … 10 V
        self._tdiv = 50e-9
        self._vdiv = 0.05
        self._toff_frac = 0.0
        self._voff_frac = 0.0
        self._auto_first = True                   # autoscale on the first acquire
        self._pending_sync: tuple[float, float, float] | None = None
        self._pending_trigger: tuple[str, float, str, _TriggerDialog | None] | None = None
        self._build_ui()
        self._apply_view()

        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(75)
        self._sync_timer.timeout.connect(self._flush_scope_sync)

        # ── Acquisition worker thread ─────────────────────────────────
        # All scope I/O runs in this worker so slow VISA transfers never freeze
        # the GUI.  The timers live in the worker thread; a QTimer can only be
        # started/stopped from its own thread, so we drive them via queued
        # signals connected to timer.start/stop (the standard PySide6 pattern).
        self._reader = _ScopeReader(scope)
        self._reader_thread = QThread(self)
        self._reader.moveToThread(self._reader_thread)
        # Cross-thread timer control (queued to the worker thread):
        self._acquire_requested.connect(self._reader._once_timer.start)
        self._live_start_requested.connect(self._reader._live_timer.start)
        self._live_stop_requested.connect(self._reader._live_timer.stop)
        # Control / diagnostic operations (queued to the worker thread):
        self._test_requested.connect(self._reader.test_connection)
        self._settings_requested.connect(self._reader.read_settings)
        self._sync_requested.connect(self._reader.sync_scope)
        self._trigger_requested.connect(self._reader.apply_trigger)
        self._reader.acquired.connect(self._on_acquired)
        self._reader.failed.connect(self._on_acquire_failed)
        self._reader.test_done.connect(self._on_test_done)
        self._reader.settings_done.connect(self._on_settings_done)
        self._reader.sync_done.connect(self._on_sync_done)
        self._reader.trigger_done.connect(self._on_trigger_done)
        self._reader_thread.finished.connect(self._reader.deleteLater)
        self._reader_thread.start()

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── Waveform plot ────────────────────────────────────────────
        if _HAS_PG:
            self._plot = pg.PlotWidget(title="Waveforms")
            self._plot.setLabel("left",   "Amplitude", units="V")
            # units="s" lets pyqtgraph auto-pick ns/µs/ms (the old "ns" label
            # produced nonsense like "kns").  Data is plotted in seconds.
            self._plot.setLabel("bottom", "Time",      units="s")
            # Scale/offset come from the sliders below — disable free mouse zoom
            # so the divisions stay authoritative (right-click menu still works).
            self._plot.setMouseEnabled(x=False, y=False)
            self._plot.getPlotItem().setMenuEnabled(True)
            self._curve_ref = self._plot.plot(
                pen=pg.mkPen("y", width=1), name="CH1 ref photodiode")
            self._curve_dut = self._plot.plot(
                pen=pg.mkPen("c", width=2), name="CH2 DUT")
            self._plot.addLegend()

            # Vertical marker lines (hidden until first acquire)
            def _vline(color: tuple) -> pg.InfiniteLine:
                line = pg.InfiniteLine(
                    angle=90,
                    movable=False,
                    pen=pg.mkPen(color=color, width=1, style=Qt.PenStyle.DashLine),
                )
                line.setVisible(False)
                self._plot.addItem(line)
                return line

            self._line_onset    = _vline(_COL_ONSET)
            self._line_trailing = _vline(_COL_TRAILING)
            self._line_cfd      = _vline(_COL_CFD)

            # Integration window shaded region
            self._int_region = pg.LinearRegionItem(
                values=(20e-9, 150e-9),  # seconds, updated on acquire
                brush=pg.mkBrush(60, 60, 160, 40),
                pen=pg.mkPen(_COL_INTWIN, width=1),
                movable=False,
            )
            self._int_region.setVisible(False)
            self._plot.addItem(self._int_region)

            root.addWidget(self._plot)
        else:
            root.addWidget(QLabel("(install pyqtgraph for live waveforms)"))

        # ── Analysis readout ─────────────────────────────────────────
        stats_box = QGroupBox("DUT Analysis")
        grid = QGridLayout(stats_box)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        def _stat(row: int, col: int, label: str) -> QLabel:
            grid.addWidget(QLabel(label), row, col)
            lbl = QLabel("—")
            grid.addWidget(lbl, row, col + 1)
            return lbl

        self._lbl_amp      = _stat(0, 0, "Amplitude:")
        self._lbl_chg      = _stat(1, 0, "Charge:")
        self._lbl_rms      = _stat(2, 0, "Baseline RMS:")
        self._lbl_drift    = _stat(0, 2, "Drift time:")
        self._lbl_rise     = _stat(1, 2, "Rise time:")
        self._lbl_cfd      = _stat(2, 2, "CFD time:")
        root.addWidget(stats_box)

        # ── Marker visibility toggles ────────────────────────────────
        if _HAS_PG:
            marker_row = QHBoxLayout()
            self._chk_onset    = QCheckBox("Onset (green)")
            self._chk_trailing = QCheckBox("Trailing (red)")
            self._chk_cfd      = QCheckBox("CFD (yellow)")
            self._chk_intwin   = QCheckBox("Int. window (blue)")
            for chk in (self._chk_onset, self._chk_trailing,
                        self._chk_cfd, self._chk_intwin):
                chk.setChecked(True)
                marker_row.addWidget(chk)
            self._chk_onset.toggled.connect(self._line_onset.setVisible)
            self._chk_trailing.toggled.connect(self._line_trailing.setVisible)
            self._chk_cfd.toggled.connect(self._line_cfd.setVisible)
            self._chk_intwin.toggled.connect(self._int_region.setVisible)
            root.addLayout(marker_row)

        # ── Display / Scale controls ─────────────────────────────────
        if _HAS_PG:
            root.addWidget(self._build_scale_box())

        # ── Acquire controls ─────────────────────────────────────────
        ctrl = QHBoxLayout()
        btn_trigger = QPushButton("⚡ Trigger Settings")
        btn_trigger.setToolTip("Open the trigger settings window (source / level / slope)")
        btn_trigger.clicked.connect(self._open_trigger)
        ctrl.addWidget(btn_trigger)
        self._btn_single = QPushButton("Single Acquire")
        self._btn_single.clicked.connect(self._acquire_requested)
        self._btn_live = QPushButton("Live ▶")
        self._btn_live.setCheckable(True)
        self._btn_live.toggled.connect(self._toggle_live)
        btn_export = QPushButton("💾 Export CSV")
        btn_export.setToolTip("Save the currently displayed waveforms to a CSV file")
        btn_export.clicked.connect(self._export_csv)
        btn_test = QPushButton("🔌 Test Connection")
        btn_test.setToolTip("Query *IDN? and show the reply — confirms the VISA/USB link")
        btn_test.clicked.connect(self._test_connection)
        btn_visa = QPushButton("List VISA…")
        btn_visa.setToolTip("List VISA resource strings (find the scope's USB address)")
        btn_visa.clicked.connect(self._list_visa)
        ctrl.addWidget(self._btn_single)
        ctrl.addWidget(self._btn_live)
        ctrl.addWidget(btn_export)
        ctrl.addWidget(btn_test)
        ctrl.addWidget(btn_visa)
        root.addLayout(ctrl)

    def _test_connection(self) -> None:
        self._test_requested.emit()

    def _list_visa(self) -> None:
        from PySide6.QtWidgets import QMessageBox, QApplication
        from devices.waveform_generator import list_visa_resources
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = list_visa_resources()
            text = ("\n".join(res) if res
                    else "No VISA resources found.\nIs the instrument on and NI-VISA installed?")
        except Exception as exc:
            text = f"{exc}"
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "VISA Resources", text)

    def _open_trigger(self) -> None:
        if self._trigger_dialog is None:
            self._trigger_dialog = _TriggerDialog(
                self._scope, self._config_path, self._queue_trigger_apply, self
            )
        self._trigger_dialog.show()
        self._trigger_dialog.raise_()
        self._trigger_dialog.activateWindow()

    def _queue_trigger_apply(self, src: str, lvl: float, slope: str,
                             dialog: _TriggerDialog | None = None) -> None:
        self._pending_trigger = (src, lvl, slope, dialog)
        self._trigger_requested.emit(src, lvl, slope)

    # ------------------------------------------------------------------ #
    # Display / scale controls                                            #
    # ------------------------------------------------------------------ #

    def _build_scale_box(self) -> QGroupBox:
        box = QGroupBox("Display / Scale")
        g = QGridLayout(box)

        self._tdiv_slider = QSlider(Qt.Horizontal)
        self._tdiv_slider.setRange(0, len(self._tdiv_seq) - 1)
        self._tdiv_slider.setValue(_nearest_125(self._tdiv, self._tdiv_seq))
        self._tdiv_edit = QLineEdit(_eng_format(self._tdiv, "s"))
        self._tdiv_edit.setMaximumWidth(90)
        self._tdiv_edit.setToolTip("Type an exact value, e.g. 50ns, 2us, 1ms")
        self._tdiv_slider.valueChanged.connect(self._on_tdiv_slider)
        self._tdiv_edit.editingFinished.connect(self._on_tdiv_edit)
        g.addWidget(QLabel("Time / div:"), 0, 0)
        g.addWidget(self._tdiv_slider, 0, 1)
        g.addWidget(self._tdiv_edit, 0, 2)

        self._vdiv_slider = QSlider(Qt.Horizontal)
        self._vdiv_slider.setRange(0, len(self._vdiv_seq) - 1)
        self._vdiv_slider.setValue(_nearest_125(self._vdiv, self._vdiv_seq))
        self._vdiv_edit = QLineEdit(_eng_format(self._vdiv, "V"))
        self._vdiv_edit.setMaximumWidth(90)
        self._vdiv_edit.setToolTip("Type an exact value, e.g. 50mV, 0.5V, 2V")
        self._vdiv_slider.valueChanged.connect(self._on_vdiv_slider)
        self._vdiv_edit.editingFinished.connect(self._on_vdiv_edit)
        g.addWidget(QLabel("Volts / div:"), 1, 0)
        g.addWidget(self._vdiv_slider, 1, 1)
        g.addWidget(self._vdiv_edit, 1, 2)

        self._toff_slider = QSlider(Qt.Horizontal)
        self._toff_slider.setRange(-100, 100)
        self._toff_slider.setValue(0)
        self._toff_slider.valueChanged.connect(self._on_toff)
        g.addWidget(QLabel("Time offset:"), 2, 0)
        g.addWidget(self._toff_slider, 2, 1)

        self._voff_slider = QSlider(Qt.Horizontal)
        self._voff_slider.setRange(-100, 100)
        self._voff_slider.setValue(0)
        self._voff_slider.valueChanged.connect(self._on_voff)
        g.addWidget(QLabel("Volts offset:"), 3, 0)
        g.addWidget(self._voff_slider, 3, 1)

        row = QHBoxLayout()
        btn_auto = QPushButton("Autoscale")
        btn_auto.setToolTip("Fit the view to the current waveform")
        btn_auto.clicked.connect(self._autoscale)
        btn_read = QPushButton("⤵ Read scope")
        btn_read.setToolTip("Read the instrument's current t/div, V/div and offset into the panel")
        btn_read.clicked.connect(self._read_from_scope)
        self._chk_sync = QCheckBox("Drive scope (→ SCPI)")
        self._chk_sync.setToolTip("When on, the sliders set the REAL oscilloscope "
                                  "(t/div, V/div, offset), not just the display.")
        self._chk_sync.setChecked(True)
        row.addWidget(btn_auto)
        row.addWidget(btn_read)
        row.addWidget(self._chk_sync)
        row.addStretch()
        rw = QWidget()
        rw.setLayout(row)
        g.addWidget(rw, 4, 0, 1, 3)
        return box

    def _on_tdiv_slider(self, idx: int) -> None:
        self._tdiv = self._tdiv_seq[idx]
        self._tdiv_edit.setText(_eng_format(self._tdiv, "s"))
        self._apply_view()
        self._sync_scope()

    def _on_tdiv_edit(self) -> None:
        v = _parse_quantity(self._tdiv_edit.text())
        if v and v > 0:
            self._tdiv = v
            self._tdiv_slider.blockSignals(True)
            self._tdiv_slider.setValue(_nearest_125(v, self._tdiv_seq))
            self._tdiv_slider.blockSignals(False)
            self._apply_view()
            self._sync_scope()
        self._tdiv_edit.setText(_eng_format(self._tdiv, "s"))

    def _on_vdiv_slider(self, idx: int) -> None:
        self._vdiv = self._vdiv_seq[idx]
        self._vdiv_edit.setText(_eng_format(self._vdiv, "V"))
        self._apply_view()
        self._sync_scope()

    def _on_vdiv_edit(self) -> None:
        v = _parse_quantity(self._vdiv_edit.text())
        if v and v > 0:
            self._vdiv = v
            self._vdiv_slider.blockSignals(True)
            self._vdiv_slider.setValue(_nearest_125(v, self._vdiv_seq))
            self._vdiv_slider.blockSignals(False)
            self._apply_view()
            self._sync_scope()
        self._vdiv_edit.setText(_eng_format(self._vdiv, "V"))

    def _on_toff(self, val: int) -> None:
        self._toff_frac = val / 100.0
        self._apply_view()

    def _on_voff(self, val: int) -> None:
        self._voff_frac = val / 100.0
        self._apply_view()
        self._sync_scope()

    def _apply_view(self) -> None:
        """10×8 division view: ±5 t/div horizontal, ±4 V/div vertical."""
        if not _HAS_PG:
            return
        tc = self._toff_frac * 5 * self._tdiv
        vc = self._voff_frac * 4 * self._vdiv
        self._plot.setXRange(tc - 5 * self._tdiv, tc + 5 * self._tdiv, padding=0)
        self._plot.setYRange(vc - 4 * self._vdiv, vc + 4 * self._vdiv, padding=0)

    def _sync_scope(self) -> None:
        """Push the current scale/offset to the real instrument (SCPI)."""
        if not getattr(self, "_chk_sync", None) or not self._chk_sync.isChecked():
            return
        if not self._scope.connected:
            return
        self._pending_sync = (self._tdiv, self._vdiv, self._voff_frac)
        self._sync_timer.start()

    def _flush_scope_sync(self) -> None:
        if self._pending_sync is None:
            return
        tdiv, vdiv, voff_frac = self._pending_sync
        self._pending_sync = None
        self._sync_requested.emit(tdiv, vdiv, voff_frac)

    def _read_from_scope(self) -> None:
        """Pull the instrument's current t/div, V/div and offset into the panel."""
        if not self._scope.connected:
            notify("Oscilloscope not connected.", "warn")
            return
        self._settings_requested.emit()

    def _autoscale(self) -> None:
        spans = []
        for t, v in ((self._last_t1, self._last_v1), (self._last_t2, self._last_v2)):
            if t is not None and len(t):
                spans.append((float(t.min()), float(t.max()),
                              float(v.min()), float(v.max())))
        if not spans:
            return
        tmin = min(s[0] for s in spans); tmax = max(s[1] for s in spans)
        vmin = min(s[2] for s in spans); vmax = max(s[3] for s in spans)
        tspan = max(tmax - tmin, 1e-12); vspan = max(vmax - vmin, 1e-6)
        self._tdiv = self._tdiv_seq[_nearest_125(tspan / 8.0, self._tdiv_seq)]
        self._vdiv = self._vdiv_seq[_nearest_125(vspan / 6.0, self._vdiv_seq)]
        tmid = (tmin + tmax) / 2.0
        vmid = (vmin + vmax) / 2.0
        self._toff_frac = max(-1.0, min(1.0, tmid / (5 * self._tdiv)))
        self._voff_frac = max(-1.0, min(1.0, vmid / (4 * self._vdiv)))
        self._set_widgets_from_state()
        self._apply_view()
        self._sync_scope()

    def _set_widgets_from_state(self) -> None:
        for slider, edit, val, seq, unit in (
                (self._tdiv_slider, self._tdiv_edit, self._tdiv, self._tdiv_seq, "s"),
                (self._vdiv_slider, self._vdiv_edit, self._vdiv, self._vdiv_seq, "V")):
            slider.blockSignals(True)
            slider.setValue(_nearest_125(val, seq))
            slider.blockSignals(False)
            edit.setText(_eng_format(val, unit))
        for slider, frac in ((self._toff_slider, self._toff_frac),
                             (self._voff_slider, self._voff_frac)):
            slider.blockSignals(True)
            slider.setValue(int(round(frac * 100)))
            slider.blockSignals(False)

    # ------------------------------------------------------------------ #
    # Acquisition                                                          #
    # ------------------------------------------------------------------ #

    def _on_acquired(self, t1, v1, t2, v2) -> None:
        """GUI-thread slot: reader delivered fresh waveforms — pure widget work."""
        try:
            self._last_t1, self._last_v1 = t1, v1
            self._last_t2, self._last_v2 = t2, v2

            if _HAS_PG:
                self._curve_ref.setData(t1, v1)   # seconds — axis auto-units
                self._curve_dut.setData(t2, v2)
                if self._auto_first:
                    self._auto_first = False
                    self._autoscale()

            result = analyse_waveform(t2, v2, **self._analysis_kwargs)

            # ── Text readout ─────────────────────────────────────────
            self._lbl_amp.setText(f"{result.amplitude_V * 1000:.2f} mV")
            self._lbl_chg.setText(f"{result.charge_pC:.3f} pC")
            self._lbl_rms.setText(f"{result.baseline_rms_V * 1000:.3f} mV")
            self._lbl_drift.setText(
                f"{result.drift_time_s * 1e9:.2f} ns"
                if result.drift_time_s is not None else "—"
            )
            self._lbl_rise.setText(
                f"{result.rise_time_s * 1e9:.2f} ns"
                if result.rise_time_s is not None else "—"
            )
            self._lbl_cfd.setText(
                f"{result.cfd_time_s * 1e9:.2f} ns"
                if result.cfd_time_s is not None else "—"
            )

            # ── Waveform markers ─────────────────────────────────────
            if _HAS_PG:
                if result.onset_time_s is not None:
                    self._line_onset.setValue(result.onset_time_s)
                    self._line_onset.setVisible(self._chk_onset.isChecked())
                if result.trailing_time_s is not None:
                    self._line_trailing.setValue(result.trailing_time_s)
                    self._line_trailing.setVisible(self._chk_trailing.isChecked())
                if result.cfd_time_s is not None:
                    self._line_cfd.setValue(result.cfd_time_s)
                    self._line_cfd.setVisible(self._chk_cfd.isChecked())
                # Integration window — same one analyse_waveform used.
                win = self._analysis_kwargs.get("integration_window_s", (20e-9, 150e-9))
                self._int_region.setRegion(tuple(win))
                self._int_region.setVisible(self._chk_intwin.isChecked())
        except Exception as exc:
            self._on_acquire_failed(str(exc))

    def _on_acquire_failed(self, msg: str) -> None:
        # Surface the failure (once per distinct error) instead of swallowing.
        if msg != getattr(self, "_last_acq_err", None):
            self._last_acq_err = msg
            notify(f"Oscilloscope acquire failed: {msg}", "warn")

    def _toggle_live(self, checked: bool) -> None:
        if checked:
            self._live_start_requested.emit()
        else:
            self._live_stop_requested.emit()
        self._btn_live.setText("Live ⏹" if checked else "Live ▶")

    def _on_test_done(self, msg: str) -> None:
        QMessageBox.information(self, "Oscilloscope Test", msg)

    def _on_settings_done(self, settings, err: str) -> None:
        if err:
            notify(f"Read from scope failed: {err}", "warn")
            return
        s = settings or {}
        if not s:
            notify("No settings could be read from the oscilloscope.", "warn")
            return
        if s.get("tdiv"):
            self._tdiv = s["tdiv"]
        if s.get("vdiv"):
            self._vdiv = s["vdiv"]
        if s.get("voff_div") is not None:
            self._voff_frac = max(-1.0, min(1.0, s["voff_div"] / 4.0))
        self._set_widgets_from_state()
        self._apply_view()
        notify("Read t/div, V/div, offset from oscilloscope.", "info")

    def _on_sync_done(self, err: str) -> None:
        if err:
            notify(f"Scope scale sync failed: {err}", "warn")

    def _on_trigger_done(self, err: str) -> None:
        pending = self._pending_trigger
        self._pending_trigger = None
        if pending is None:
            return
        src, lvl, slope, dialog = pending
        if dialog is not None:
            dialog.show_trigger_result(src, lvl, slope, err or None)
        if err:
            notify(f"Trigger apply failed: {err}", "warn")

    def shutdown(self) -> None:
        """Stop the acquisition thread — call before discarding the panel."""
        try:
            self._sync_timer.stop()
            self._live_stop_requested.emit()
            self._reader_thread.quit()
            self._reader_thread.wait(2000)
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)

    def _export_csv(self) -> None:
        """Save the last acquired waveforms to a CSV file."""
        if self._last_t2 is None:
            return
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Waveform", "", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            import csv
            with open(path, "w", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["time_ns", "ch1_ref_V", "ch2_dut_V"])
                t1 = self._last_t1 if self._last_t1 is not None else self._last_t2
                v1 = self._last_v1 if self._last_v1 is not None else np.zeros_like(self._last_t2)
                for t, a, b in zip(self._last_t2 * 1e9, v1, self._last_v2):
                    writer.writerow([f"{t:.4f}", f"{a:.6f}", f"{b:.6f}"])
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Export Error", str(exc))
