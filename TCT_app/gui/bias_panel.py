"""
Bias supply control panel — the HV safety dashboard (cockpit design §6).

Provides:
  - Hero trio tiles: Voltage · measured (polarity sign from readback,
    setpoint in the caption), Current (compliance headroom in the caption)
    and HV STATE (OFF / RAMPING / SETTLED / TRIPPED — derived from readback
    + in-flight commands; inferred states say so, law 7)
  - Compliance setting (with red warning if too high)
  - Voltage setpoint + ramp controls, quick-off safety button
  - Standalone sweeps (advanced, collapsed): IV scan + CCE-vs-V — QThread
"""
from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import QTimer, Signal, QThread, QObject, QSettings
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QDoubleSpinBox, QSpinBox,
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
from gui.panel_kit import Card, CheckableCard, MetricGrid, MetricTile, section_header
from gui.status_bus import notify
from gui.style import PLOT_BG, WARN_RED, axis_color
from gui.status_widgets import StatusChip, flash_button, set_button_busy, set_button_icon


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
        # Presentation-only HV-state bookkeeping (design system §6): the
        # supply exposes NO output-on/ramp-state readback today, so the HV
        # STATE tile derives OFF/RAMPING/SETTLED/TRIPPED from setpoint +
        # measured + in-flight commands and *says so* in its caption (law 7).
        self._hv_ramping = False       # a ramp command is in flight
        self._hv_scan_stepping = False # an IV / bias+waveform scan drives HV
        self._vscan_last_point_t = float("-inf")   # last vscan point (monotonic)
        # Theme mode for the bias axis-rail accent (gui.style.axis_color) —
        # bias reads amber everywhere.  Read once from the same QSettings key
        # main.py/tct_gui.py use; see refresh_theme() for why this isn't
        # live-notified yet.
        self._theme_mode = str(QSettings("TCT", "TCTSetup").value("theme", "light"))
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

        # ── Status strip ───────────────────────────────────────────────
        # Connection chip only — output/compliance state moved into the hero
        # trio tiles below (design system §6: the bias panel is a safety
        # dashboard, its primary display is Voltage · Current · HV STATE).
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self._chip_conn = StatusChip("Disconnected", "disconnected")
        status_row.addWidget(self._chip_conn)
        status_row.addStretch(1)
        root.addLayout(status_row)

        # ── Hero trio: Voltage · measured / Current / HV STATE ─────────
        # (design system §6, Paul's hardware-truth map).  Polarity sign comes
        # from the READBACK; the setpoint lives in the caption, labelled
        # apart (law 7 "measured vs setpoint labeled apart").
        hero = MetricGrid(columns=3)
        self._tile_v: MetricTile = hero.add_tile(
            MetricTile("Voltage · measured", "—", min_width=130))
        self._tile_i: MetricTile = hero.add_tile(
            MetricTile("Current", "—", min_width=130))
        self._tile_hv: MetricTile = hero.add_tile(
            MetricTile("HV state", "—", min_width=130))
        for tile in (self._tile_v, self._tile_i, self._tile_hv):
            tile.set_stale(True, "not connected")
        root.addWidget(hero)

        # ── Safety / compliance ────────────────────────────────────────
        safe_box = Card("Compliance (current limit)")
        safe_form = QFormLayout()

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
        self._lbl_comp_warn.setStyleSheet(f"color: {WARN_RED}; font-weight: bold;")
        # Quiet-nominal (law 1): a sane configured limit is grey, not a
        # persistent green "LIMIT OK" light; only a dangerously high limit
        # shouts.  A real compliance TRIP is a crit alarm on the hero tiles.
        self._chip_comp_limit = StatusChip("Limit ok", "neutral")

        safe_form.addRow("Compliance:", self._spin_comp)
        safe_form.addRow("Limit state:", self._chip_comp_limit)
        safe_form.addRow(self._lbl_comp_warn)

        self._btn_set_comp = QPushButton("Apply compliance")
        set_button_icon(self._btn_set_comp, "mdi.check")
        self._btn_set_comp.clicked.connect(self._apply_compliance)
        safe_form.addRow(self._btn_set_comp)
        safe_box.add_layout(safe_form)
        root.addWidget(safe_box)

        # ── Voltage control ────────────────────────────────────────────
        # Bias-axis rail (gui.style.axis_color("bias", ...)) marks this as
        # the panel's primary bias-axis control; the hero voltage tile and
        # the two sweep plots echo the same amber (_restyle_bias_axis).
        # Card.set_rail() replaces the old "#biasRail" objectName + inline
        # QSS border — same amber accent, scoped to this Card via panel_kit.
        volt_box = Card("Bias voltage")
        self._volt_box = volt_box
        volt_form = QFormLayout()

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
        self._btn_apply = QPushButton("▶ Ramp to voltage")
        set_button_icon(self._btn_apply, "mdi.trending-up")
        self._btn_apply.clicked.connect(self._apply_voltage)
        self._btn_off = QPushButton("⏹ Output OFF (0 V)")
        # Reuse the shared dangerBtn hook instead of a hardcoded hex (same
        # red language as STOP/ALL-OFF, plus working hover/pressed states
        # the old inline style didn't have).
        self._btn_off.setObjectName("dangerBtn")
        set_button_icon(self._btn_off, "mdi.power", color="white")
        self._btn_off.clicked.connect(self._emergency_off)
        btn_row.addWidget(self._btn_apply)
        btn_row.addWidget(self._btn_off)
        volt_form.addRow(btn_row)
        volt_box.add_layout(volt_form)
        root.addWidget(volt_box)

        # ── Polarity ───────────────────────────────────────────────────
        # Read-only indicator (polled off-thread) + a DANGEROUS switch button
        # that only appears when the supply reports the channel reversible.
        # (The live V/I readout itself lives in the hero trio tiles above.)
        pol_box = Card("Polarity")
        pol_form = QFormLayout()
        self._lbl_polarity = QLabel("—")
        self._lbl_polarity.setStyleSheet("font-weight: 700; font-size: 16px;")
        self._lbl_polarity.setToolTip("Current HV output polarity (read-only).")
        pol_form.addRow("Current polarity:", self._lbl_polarity)
        self._btn_polarity = QPushButton("⇄ Switch polarity")
        self._btn_polarity.setObjectName("dangerBtn")
        self._btn_polarity.setToolTip(
            "Reverse HV polarity (throws an HV relay).\n"
            "Output must be OFF and fully discharged first."
        )
        self._btn_polarity.clicked.connect(self._on_switch_polarity)
        self._btn_polarity.setVisible(False)   # shown only when reversible
        pol_form.addRow(self._btn_polarity)
        pol_box.add_layout(pol_form)
        root.addWidget(pol_box)

        # ── Standalone sweeps (advanced) ───────────────────────────────
        # IV scan + CCE-vs-V fold into ONE collapsed card (design system §7):
        # both are advanced, standalone procedures, not everyday controls.
        # CheckableCard has no built-in collapse, so the header checkbox is
        # additionally wired to hide/show the body (nearest kit primitive —
        # gap reported); every control inside stays fully reachable.
        sweeps_card = CheckableCard(
            "Standalone sweeps (advanced)", "IV curve · CCE vs bias",
            checked=False)
        self._sweeps_card = sweeps_card
        sweeps_body = sweeps_card.body.parentWidget()
        sweeps_card.toggled.connect(sweeps_body.setVisible)
        sweeps_body.setVisible(False)

        sweeps_card.add_widget(section_header(
            "IV scan", "bias sweep · record current"))
        iv_form = QFormLayout()

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

        self._btn_iv = QPushButton("▶ Run IV scan")
        self._btn_iv.clicked.connect(self._run_iv_scan)
        iv_form.addRow(self._btn_iv)

        sweeps_card.add_layout(iv_form)

        # ── Bias + waveform scan (requires ScanController) ─────────────
        sweeps_card.add_widget(section_header(
            "CCE vs voltage", "bias + waveform scan"))
        vscan_form = QFormLayout()

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

        self._btn_vscan = QPushButton("▶ Start bias + waveform scan")
        self._btn_vscan.clicked.connect(self._emit_vscan)
        vscan_form.addRow(self._btn_vscan)

        sweeps_card.add_layout(vscan_form)
        root.addWidget(sweeps_card)

        # The two sweep plots are built LAZILY on first expand: a pyqtgraph
        # PlotWidget constructed inside an explicitly-hidden body and then
        # torn down without ever being polished is a teardown access-
        # violation on Windows (reproduced headless) — and nobody pays for
        # plots they never open.  The forms keep the row slots; the curves
        # stay None until _ensure_sweep_plots() runs.
        self._iv_form = iv_form
        self._vscan_form = vscan_form
        self._iv_plot = None
        self._iv_curve = None
        self._vscan_plot = None
        self._vscan_curve = None
        sweeps_card.toggled.connect(self._ensure_sweep_plots)

        self._on_compliance_changed(self._spin_comp.value())
        self._restyle_bias_axis()

    def _ensure_sweep_plots(self, checked: bool) -> None:
        """Build the IV / charge-vs-bias plots the first time the advanced
        sweeps card is expanded (see the comment at the call site)."""
        if not checked or not _HAS_PG or self._iv_plot is not None:
            return
        color = axis_color("bias", self._theme_mode)
        self._iv_plot = pg.PlotWidget(title="IV Curve", background=PLOT_BG)
        self._iv_plot.showGrid(x=True, y=True, alpha=0.25)
        self._iv_plot.setLabel("left",   "Current", units="A")
        self._iv_plot.setLabel("bottom", "Voltage", units="V")
        self._iv_plot.setMaximumHeight(160)
        self._iv_curve = self._iv_plot.plot(pen=pg.mkPen(color, width=2))
        self._iv_form.addRow(self._iv_plot)
        if self._iv_v:
            self._iv_curve.setData(self._iv_v, self._iv_i)

        self._vscan_plot = pg.PlotWidget(title="Charge vs. Bias", background=PLOT_BG)
        self._vscan_plot.showGrid(x=True, y=True, alpha=0.25)
        self._vscan_plot.setLabel("left",   "Charge", units="pC")
        self._vscan_plot.setLabel("bottom", "Bias", units="V")
        self._vscan_plot.setMaximumHeight(160)
        self._vscan_curve = self._vscan_plot.plot(
            pen=pg.mkPen(color, width=2), symbol="o", symbolSize=4)
        self._vscan_form.addRow(self._vscan_plot)
        if self._vscan_v:
            self._vscan_curve.setData(self._vscan_v, self._vscan_q)

    # ------------------------------------------------------------------ #
    # Bias-axis styling (gui.style.axis_color) — re-run by refresh_theme() #
    # ------------------------------------------------------------------ #

    def _restyle_bias_axis(self) -> None:
        """Tint the bias-axis accents (gui.style.axis_color): the voltage
        card's rail and the IV/Vscan plot curves.  Bias reads amber in both
        themes, everywhere in this panel.  (The hero tiles resolve their own
        ink through the shared QSS tokens — nothing to re-tint there.)"""
        color = axis_color("bias", self._theme_mode)
        self._volt_box.set_rail("bias", self._theme_mode)
        if _HAS_PG and self._iv_curve is not None:
            self._iv_curve.setPen(pg.mkPen(color, width=2))
        if _HAS_PG and self._vscan_curve is not None:
            self._vscan_curve.setPen(pg.mkPen(color, width=2))

    def refresh_theme(self, mode: str | None = None) -> None:
        """Re-resolve the bias axis-rail accent after a light/dark switch.

        ``gui.style.apply_theme(app, mode)`` repaints every objectName-based
        QSS hook (statusChip, dangerBtn, ...) automatically; the amber
        accents above are baked in as instance-level inline styles/pen
        colours at construction time, so they need this explicit refresh.

        Called live via ``tct_gui._toggle_theme`` →
        ``MultiBiasPanel.refresh_theme()``, which forwards to every tab's
        panel; see ``MotorPanel.refresh_theme()`` for the same pattern.
        """
        if mode:
            self._theme_mode = str(mode)
        self._restyle_bias_axis()

    # ------------------------------------------------------------------ #
    # Slots                                                               #
    # ------------------------------------------------------------------ #

    def _on_compliance_changed(self, value: float) -> None:
        if value * 1e-6 > self._COMPLIANCE_WARN_A:
            self._chip_comp_limit.set_status("Limit high", "crit")
            self._lbl_comp_warn.setText(
                f"⚠ Compliance > {self._COMPLIANCE_WARN_A*1e3:.0f} mA — risk of sensor damage!"
            )
        else:
            # Quiet nominal (law 1): a sane limit is not an event.
            self._chip_comp_limit.set_status("Limit ok", "neutral")
            self._lbl_comp_warn.setText("")

    def _apply_compliance(self) -> None:
        compliance_A = self._spin_comp.value() * 1e-6
        started = self._run_supply_call(
            lambda: self._supply.set_compliance(compliance_A),
            self._on_apply_compliance_done,
        )
        if started:
            set_button_busy(self._btn_set_comp, True, "Applying...")

    def _apply_voltage(self) -> None:
        target_V = self._spin_volt.value()
        step_V = self._spin_step.value()
        delay_s = self._spin_delay.value()
        started = self._run_supply_call(
            lambda: self._supply.ramp_to(
                target_V,
                step_V=step_V,
                delay_s=delay_s,
            ),
            self._on_apply_voltage_done,
        )
        if started:   # not already busy with another supply call
            set_button_busy(self._btn_apply, True, "Ramping...")
            self._hv_ramping = True
            self._set_hv_tile("RAMPING", "armed", "ramp command in flight")

    def _emergency_off(self) -> None:
        started = self._run_supply_call(
            self._do_emergency_off,
            self._on_emergency_off_done,
        )
        if started:
            set_button_busy(self._btn_off, True, "Turning off...")
            self._hv_ramping = True
            self._set_hv_tile("RAMPING ↓", "armed", "ramping to 0 V")

    # ------------------------------------------------------------------ #
    # Hero tiles (design system §6 — Voltage · Current · HV STATE)        #
    # ------------------------------------------------------------------ #

    def _set_hv_tile(self, value: str, state: str, caption: str = "") -> None:
        self._tile_hv.set_stale(False)
        self._tile_hv.set_value(value)
        self._tile_hv.set_state(state)
        self._tile_hv.set_caption(caption)

    def _derive_hv_state(self, r, setpoint_V: float) -> tuple[str, str, str]:
        """OFF / RAMPING / SETTLED / TRIPPED, derived from what the driver
        can actually tell us today (readback + setpoint + in-flight
        commands).  There is NO output-on/ramp-state readback on this supply
        yet, so inferred states say so in their caption (law 7) — the driver
        backlog for the real bits is Paul's (design system §6)."""
        v = float(r.voltage_V)
        if getattr(r, "compliant", False):
            return "TRIPPED", "crit", "compliance limit hit — output current-limited"
        scan_live = (self._hv_scan_stepping
                     or (time.monotonic() - self._vscan_last_point_t) < 5.0)
        if self._hv_ramping or scan_live:
            arrow = "↑" if abs(setpoint_V) > abs(v) else "↓"
            why = ("sweep stepping the bias" if scan_live
                   else "ramp command in flight")
            return f"RAMPING {arrow}", "armed", why
        if abs(v) < 1.0 and abs(setpoint_V) < 1.0:
            return "OFF", "normal", "inferred — output-on state not readable"
        if abs(v - setpoint_V) <= max(2.0, 0.02 * abs(setpoint_V)):
            return "SETTLED", "normal", "at setpoint — inferred from readback"
        if abs(v) > 1.0 and abs(setpoint_V) < 1.0:
            # An actor this panel doesn't hear about (e.g. the plan executor)
            # can energize the output behind it — a live |V| contradicting a
            # zero setpoint must never read as safe.
            return "LIVE?", "warn", "measured voltage with no commanded setpoint"
        return "MOVING?", "warn", "measured differs from setpoint"

    def set_reading(self, r) -> None:
        if r is None:
            for tile in (self._tile_v, self._tile_i, self._tile_hv):
                tile.set_state("normal")
                tile.set_value("—")
                tile.set_stale(True, "not connected")
            self._chip_conn.set_status("Disconnected", "disconnected")
            return
        try:
            sp = float(getattr(self._supply, "setpoint_V", 0.0) or 0.0)
            # Voltage · measured — polarity sign straight from the readback;
            # the setpoint is caption-only, labelled apart (law 7).
            self._tile_v.set_stale(False)
            self._tile_v.set_value(f"{r.voltage_V:+.2f} V")
            cap = f"setpoint {sp:+.1f} V"
            if self._pol_supported:
                sym = self._POL_SYMBOLS.get(self._last_polarity)
                cap += f" · polarity {sym}" if sym else " · polarity unknown"
            self._tile_v.set_caption(cap)

            # Current — compliance headroom in the caption; a real trip is a
            # crit alarm state, not text.
            i_uA = r.current_A * 1e6
            limit_uA = float(self._spin_comp.value())
            self._tile_i.set_stale(False)
            self._tile_i.set_value(f"{i_uA:.3f} µA")
            if limit_uA > 0:
                pct = abs(i_uA) / limit_uA * 100.0
                self._tile_i.set_caption(f"{pct:.0f}% of {limit_uA:g} µA compliance")
            else:
                pct = 0.0
                self._tile_i.set_caption("compliance limit not set")
            if getattr(r, "compliant", False):
                self._tile_i.set_state("crit")
            elif pct >= 80.0:
                self._tile_i.set_state("warn")
            else:
                self._tile_i.set_state("normal")

            self._set_hv_tile(*self._derive_hv_state(r, sp))
        except Exception:
            pass
        # Connection chip: a live reading only ever arrives once the poller
        # observes supply.connected (see _ReadoutPoller._poll) — reading the
        # flag directly here is the same cheap, no-I/O check other panels
        # already do on the GUI thread (e.g. MotorPanel._test_connection).
        # Quiet nominal: connected is grey, not a persistent green light.
        connected = bool(getattr(self._supply, "connected", False))
        self._chip_conn.set_status(
            "Connected" if connected else "Disconnected",
            "neutral" if connected else "disconnected")

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
        if _HAS_PG and self._vscan_curve is not None:
            self._vscan_curve.setData(self._vscan_v, self._vscan_q)
        # The scan controller (not this panel) drives the ramp during a
        # bias+waveform scan; a point arriving means the output is live and
        # being stepped.  Timestamp (not a latch) so the HV tile falls back
        # to the inferred readback state a few seconds after the last point.
        self._vscan_last_point_t = time.monotonic()
        self._set_hv_tile("RAMPING", "armed", "bias + waveform scan stepping the bias")

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
        self._hv_scan_stepping = True
        self._set_hv_tile("RAMPING", "armed", "IV sweep stepping the bias")

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
        self._iv_worker.finished.connect(self._on_iv_finished_chip)
        self._iv_worker.error.connect(
            lambda msg: notify(f"IV scan error: {msg}", "error")
        )
        # Clean up thread object when done
        self._iv_thread.finished.connect(self._iv_thread.deleteLater)

        self._iv_thread.start()

    def _on_iv_point(self, v: float, i: float) -> None:
        self._iv_v.append(v)
        self._iv_i.append(i)
        if _HAS_PG and self._iv_curve is not None:
            self._iv_curve.setData(self._iv_v, self._iv_i)

    def _on_iv_finished_chip(self) -> None:
        """Best-effort HV-tile refresh once an IV scan stops.

        _IVWorker ramps the output on but never explicitly switches it off
        (see _IVWorker.run), so it is still on at the last swept setpoint
        whether the sweep completed or stopped on a compliance trip — the
        next readout poll re-derives SETTLED/TRIPPED from the readback.
        """
        self._hv_scan_stepping = False

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
        set_button_busy(self._btn_set_comp, False)
        if err:
            self._lbl_comp_warn.setText(f"Error: {err}")
            return
        self._on_compliance_changed(self._spin_comp.value())
        flash_button(self._btn_set_comp, "good", "Applied")

    def _on_apply_voltage_done(self, err: str) -> None:
        set_button_busy(self._btn_apply, False)
        self._hv_ramping = False
        if err:
            notify(f"Bias ramp failed: {err}", "error")
            self._set_hv_tile("ERROR", "crit", err)
        else:
            # ramp_to() always leaves the output on (see BiasSupplyBase.ramp_to);
            # the next readout poll re-derives SETTLED from the readback.
            flash_button(self._btn_apply, "good", "Ramped")

    def _on_emergency_off_done(self, err: str) -> None:
        set_button_busy(self._btn_off, False)
        self._hv_ramping = False
        if err:
            notify(f"Output OFF failed: {err}", "error")
            self._set_hv_tile("ERROR", "crit", err)
        else:
            self._set_hv_tile("OFF", "normal",
                              "inferred — output-on state not readable")
            flash_button(self._btn_off, "good", "Off")

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
