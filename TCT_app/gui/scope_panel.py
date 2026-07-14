"""Oscilloscope / DUT waveform panel.

Cockpit-style multi-channel scope view: a large pyqtgraph plot dominates, with a
right-hand column of per-channel colour cards (enable / role / live readout), an
inline trigger badge, a movable cursor with live readout, and the display-scale
controls.  Up to four channels (CH1–CH4) can be acquired; the channel whose role
is "DUT" is fed to :func:`analyse_waveform`, the "Reference" channel to the laser
normalisation display.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QLabel, QPushButton, QCheckBox, QSlider, QLineEdit,
    QComboBox, QDoubleSpinBox, QDialog, QDialogButtonBox, QMessageBox,
    QSplitter, QScrollArea, QFrame, QSizePolicy,
)

try:
    import pyqtgraph as pg
    _HAS_PG = True
except ImportError:
    _HAS_PG = False

# Optional prettification libs — the panel degrades gracefully without them.
# (qtawesome is NOT imported here anymore: every icon in this panel goes through
# gui.status_widgets.set_button_icon, which owns the optional-import fallback,
# the palette-token default, and the theme re-tint. A second, local icon helper
# was exactly how the colourless-icon bug survived here — see that module.)
try:
    from superqt import QToggleSwitch, QLabeledDoubleRangeSlider
    _HAS_SUPERQT = True
except ImportError:
    _HAS_SUPERQT = False

from controller.yaml_persist import update_yaml_file
from devices.oscilloscope import Oscilloscope
from analysis.waveform_analysis import analyse_waveform
from gui.app_settings import theme_mode
from gui.panel_kit import Card, CheckableCard, panel_header
from gui.scope_measurements import MeasurementPanel
from gui.status_bus import notify
from gui.status_widgets import ReadoutCell, StatusChip, StatusLamp, set_button_icon
from gui.style import DARK, LIGHT, SPACE_MD, SPACE_SM, WARN_AMBER, axis_color

logger = logging.getLogger(__name__)

# Marker colours
_COL_ONSET    = (80,  200, 80)   # green  – onset
_COL_TRAILING = (200, 80,  80)   # red    – trailing / end of drift
_COL_CFD      = (255, 200, 0)    # yellow – CFD threshold
_COL_INTWIN   = (60,  60,  160)  # blue   – integration window fill

# Per-channel defaults: colour (RGB), default role, enabled, human label.
_CHAN_DEFAULTS: dict[int, tuple[tuple[int, int, int], str, bool, str]] = {
    1: ((255, 215,  0),  "Reference", True,  "Ref photodiode"),
    2: ((0,   200, 255), "DUT",       True,  "DUT"),
    3: ((255, 105, 180), "—",         False, "CH3"),
    4: ((0,   230, 118), "—",         False, "CH4"),
}
_ROLES = ("—", "DUT", "Reference")


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


@dataclass
class _ChannelState:
    """UI/model state for one scope channel."""
    number: int
    color: tuple[int, int, int]
    role: str = "—"           # "—" | "DUT" | "Reference"
    enabled: bool = False
    label: str = ""


class _TriggerDialog(QDialog):
    """Modeless trigger-settings window (source / level / slope)."""

    def __init__(self, scope: Oscilloscope, config_path: str | None,
                 apply_trigger,
                 parent: QWidget | None = None,
                 theme_mode: str = "light") -> None:
        super().__init__(parent)
        self.setWindowTitle("Oscilloscope — Trigger Settings")
        self._scope = scope
        self._config_path = config_path
        self._apply_trigger_async = apply_trigger
        # Theme mode for the status caption's muted colour (see
        # _restyle_status()/refresh_theme() below) — passed in from
        # ScopePanel at construction; ScopePanel.refresh_theme() re-pushes it
        # live while this dialog is open (_restyle_theme_tokens()).
        self._theme_mode = theme_mode
        form = QFormLayout(self)

        self._source = QComboBox()
        # Only offer channels the instrument actually has; AUX is the external
        # trigger input on the Tektronix TBS family (the connector labelled
        # "AUX In"; "EXT" is accepted as an alias and reads back as AUX).
        n_ch = int(getattr(scope, "n_channels", 4) or 4)
        sources = [f"CH{i}" for i in range(1, n_ch + 1)] + ["AUX", "LINE"]
        cur = str(getattr(scope, "trig_source", "AUX"))
        if cur not in sources:            # keep a configured legacy value (e.g. EXT)
            sources.append(cur)
        self._source.addItems(sources)
        self._source.setCurrentText(cur)
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
        self._restyle_status()
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

    def _restyle_status(self) -> None:
        p = DARK if self._theme_mode == "dark" else LIGHT
        self._status.setStyleSheet(f"color: {p['muted']};")

    def refresh_theme(self, mode: str) -> None:
        """Re-resolve the status caption's muted colour after a light/dark
        switch (called by ``ScopePanel._restyle_theme_tokens`` while this
        dialog is open — same pattern as the panel's own refresh_theme)."""
        self._theme_mode = str(mode)
        self._restyle_status()

    def show_trigger_result(self, src: str, lvl: float, slope: str, err: str | None) -> None:
        if err:
            self._status.setText(f"Apply failed: {err}")
            return
        _save_trigger_to_yaml(self._config_path, src, lvl, slope)
        self._status.setText(f"Applied: {src}, {lvl:g} V, {slope}"
                             + ("" if self._scope.connected else "  (saved; not connected)"))


def _save_scope_keys_to_yaml(path: str | None, **keys) -> None:
    """Persist oscilloscope config keys into devices.yaml (merge, keep the
    rest -- including comments; see controller/yaml_persist.py, the fix for
    the comment-eating yaml.safe_load/yaml.dump round trip, TECH_DEBT.md
    RISK 2026-07-10)."""
    if not path:
        return
    try:
        update_yaml_file(path, {"oscilloscope": keys})
    except Exception:
        pass


def _save_trigger_to_yaml(path: str | None, source: str, level: float, slope: str) -> None:
    """Persist the trigger keys into devices.yaml (merge, preserve the rest)."""
    _save_scope_keys_to_yaml(path, trigger_source=source,
                             trigger_level_V=float(level), trigger_slope=slope)


class _ChannelCard(QFrame):
    """Compact per-channel control: colour swatch, enable, role, live readout."""

    changed = Signal()             # enable or role changed
    toggled = Signal(int, bool)    # channel number, enabled

    def __init__(self, state: _ChannelState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self.setObjectName("channelCard")
        self.setFrameShape(QFrame.StyledPanel)
        r, g, b = state.color
        # Calmer card weight (design v5): a 3 px rail like every other
        # axis-railed control, not a heavier 4 px stripe.  The rgb() is the
        # channel's DATA colour (trace ink), not chrome — allowed.
        self.setStyleSheet(
            f"#channelCard {{ border-left: 3px solid rgb({r},{g},{b}); "
            f"border-radius: 6px; }}"
        )
        lay = QGridLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setHorizontalSpacing(8)
        lay.setVerticalSpacing(2)

        swatch = QLabel()
        swatch.setFixedSize(12, 12)
        swatch.setStyleSheet(f"background: rgb({r},{g},{b}); border-radius: 6px;")
        # Quiet nominal: an enabled channel is routine configuration, not a
        # green light — the lamp only distinguishes on (neutral) from off.
        self._lamp = StatusLamp("neutral" if state.enabled else "disconnected")
        title = QLabel(f"CH{state.number}")
        title.setToolTip(state.label)
        self._role_chip = StatusChip(state.role if state.role != "—" else "No role",
                                     "info" if state.role != "—" else "neutral")

        if _HAS_SUPERQT:
            self._enable = QToggleSwitch()
            self._enable.setChecked(state.enabled)
            self._enable.toggled.connect(self._on_toggle)
        else:
            self._enable = QCheckBox("on")
            self._enable.setChecked(state.enabled)
            self._enable.toggled.connect(self._on_toggle)

        self._role = QComboBox()
        self._role.addItems(_ROLES)
        self._role.setCurrentText(state.role)
        self._role.currentTextChanged.connect(self._on_role)

        self._readout = QLabel("—")
        # Colour resolved by ScopePanel._restyle_theme_tokens() via
        # set_readout_color() below (theme-aware muted caption).
        self._readout.setStyleSheet("font-size: 11px;")

        lay.addWidget(swatch,       0, 0)
        lay.addWidget(title,        0, 1)
        lay.addWidget(self._role_chip, 0, 2)
        lay.addWidget(self._lamp,   0, 3, Qt.AlignRight)
        lay.addWidget(self._enable, 0, 4, Qt.AlignRight)
        lay.addWidget(QLabel("Role:"), 1, 0, 1, 1)
        lay.addWidget(self._role,   1, 1, 1, 4)
        lay.addWidget(self._readout, 2, 0, 1, 5)
        lay.setColumnStretch(1, 1)

    def _on_toggle(self, checked: bool) -> None:
        self._state.enabled = bool(checked)
        self._lamp.set_state("neutral" if checked else "disconnected")
        self.toggled.emit(self._state.number, bool(checked))
        self.changed.emit()

    def _on_role(self, role: str) -> None:
        self._state.role = role
        self._role_chip.set_status(role if role != "—" else "No role",
                                   "info" if role != "—" else "neutral")
        self.changed.emit()

    def set_readout(self, text: str) -> None:
        self._readout.setText(text)

    def set_readout_color(self, color: str) -> None:
        """Re-resolve the live-readout's muted colour (ScopePanel's
        ``_restyle_theme_tokens`` calls this for every card, once at
        construction and again after every light/dark switch)."""
        self._readout.setStyleSheet(f"color: {color}; font-size: 11px;")

    @property
    def state(self) -> _ChannelState:
        return self._state


class _ScopeReader(QObject):
    """Acquires the enabled channels in a dedicated QThread.

    VISA transfers take 10s of ms (or seconds when the scope stalls); running
    them on the GUI thread froze the window on every live-view tick.  Timer
    start/stop and read_once are only ever invoked via queued signals, so all
    I/O happens in the reader thread; ``Oscilloscope.io_lock`` serialises it
    against the scan thread.
    """
    acquired = Signal(object)          # dict[int, (t, v)]
    failed   = Signal(str)
    test_done = Signal(str)
    settings_done = Signal(object, str)   # settings dict, error text
    sync_done = Signal(str)
    trigger_done = Signal(str)
    display_done = Signal(int, bool, str)  # channel, on, error text
    avg_done = Signal(str)
    chan_config_done = Signal(str)

    def __init__(self, scope: Oscilloscope) -> None:
        super().__init__()
        self._scope = scope
        # Which channels to read.  Assignment of a new set is atomic in CPython,
        # so the GUI thread can update this without a lock.
        self._enabled: frozenset[int] = frozenset({1, 2})
        # Live acquisition timer — started/stopped via C++ Qt slots.
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(300)
        self._live_timer.timeout.connect(self.read_once)
        # Single-shot timer for one-off acquisitions — fired via C++ start() slot.
        self._once_timer = QTimer(self)
        self._once_timer.setSingleShot(True)
        self._once_timer.setInterval(0)
        self._once_timer.timeout.connect(self.read_once)

    def set_enabled_channels(self, channels: frozenset[int]) -> None:
        self._enabled = channels

    def read_once(self) -> None:
        if not self._scope.connected:
            # Don't leave a blank plot unexplained — surface it once.  The panel
            # de-duplicates identical messages, so a live-view tick loop only
            # notifies a single time until the state changes.
            self.failed.emit("Oscilloscope not connected.")
            return
        # Per-channel fault isolation: one dead channel (display off on the
        # scope, timeout, …) must not blank the channels that DID read fine —
        # that was the bench "nothing plots" failure (CH2 off killed CH1 too).
        results: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        errors: list[str] = []
        for ch in sorted(self._enabled):
            try:
                results[ch] = self._scope.read_channel(ch)
            except Exception as exc:
                errors.append(f"CH{ch}: {exc}")
        if results:
            self.acquired.emit(results)
        if errors:
            self.failed.emit(" | ".join(errors))

    def set_channel_display(self, channel: int, on: bool) -> None:
        if not self._scope.connected:
            return
        try:
            self._scope.set_channel_display(channel, on)
            self.display_done.emit(channel, on, "")
        except Exception as exc:
            self.display_done.emit(channel, on, str(exc))

    def apply_averaging(self, n_averages: int) -> None:
        try:
            self._scope.set_averaging(n_averages)
            self.avg_done.emit("")
        except Exception as exc:
            self.avg_done.emit(str(exc))

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

    def apply_chan_config(self, atten_factor: float, coupling: str, bw_limit: str) -> None:
        """Apply probe attenuation / coupling / bandwidth-limit to every
        currently-enabled channel (mirrors the per-channel fault isolation in
        read_once — one bad channel must not block the others)."""
        if not self._scope.connected:
            self.chan_config_done.emit("Oscilloscope not connected.")
            return
        errors: list[str] = []
        for ch in sorted(self._enabled):
            try:
                self._scope.set_probe_attenuation(ch, atten_factor)
                self._scope.set_coupling(ch, coupling)
                self._scope.set_bandwidth_limit(ch, bw_limit)
            except Exception as exc:
                errors.append(f"CH{ch}: {exc}")
        self.chan_config_done.emit(" | ".join(errors))


class ScopePanel(QWidget):
    # Queued requests into the reader thread (auto-queued: different thread).
    _acquire_requested   = Signal()   # -> reader._once_timer.start()
    _live_start_requested = Signal()   # -> reader._live_timer.start()
    _live_stop_requested  = Signal()   # -> reader._live_timer.stop()
    _test_requested       = Signal()
    _settings_requested   = Signal()
    _sync_requested       = Signal(float, float, float)
    _trigger_requested    = Signal(str, float, str)
    _display_requested    = Signal(int, bool)
    _avg_requested        = Signal(int)
    _chan_config_requested = Signal(float, str, str)   # probe factor, coupling, bw limit

    def __init__(self, scope: Oscilloscope, config_path: str | None = None,
                 analysis_kwargs: dict | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scope = scope
        self._config_path = config_path
        # Theme mode for the panel's theme-token accents (DUT Analysis stat
        # colours, the "delay"-axis time readouts, the probe-attenuation
        # warning).  Read once from the same QSettings key main.py/tct_gui.py
        # use, mirroring MotorPanel/BiasPanel — see refresh_theme() below.
        self._theme_mode = theme_mode()
        # Waveform-analysis parameters from devices.yaml (analysis: block) so
        # the live readout uses the same window/termination as the scans.
        self._analysis_kwargs = dict(analysis_kwargs or {})
        # Per-channel state + last acquired data.  Only offer channels the
        # instrument actually has (the bench TBS1052C has two; querying CH3/4
        # on it times out and wedges the VISA session).
        n_ch = int(getattr(scope, "n_channels", 4) or 4)
        self._channels: dict[int, _ChannelState] = {
            n: _ChannelState(number=n, color=col, role=role, enabled=en, label=lab)
            for n, (col, role, en, lab) in _CHAN_DEFAULTS.items()
            if n <= n_ch
        }
        self._last: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self._curves: dict[int, "pg.PlotDataItem"] = {}
        self._cards: dict[int, _ChannelCard] = {}
        self._trigger_dialog: _TriggerDialog | None = None
        self._cursor_on = False
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
        self._refresh_status_chips()

        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(75)
        self._sync_timer.timeout.connect(self._flush_scope_sync)

        # ── Acquisition worker thread ─────────────────────────────────
        # All scope I/O runs in this worker so slow VISA transfers never freeze
        # the GUI.  The timers live in the worker thread; a QTimer can only be
        # started/stopped from its own thread, so we drive them via queued
        # signals connected to timer.start/stop (the standard PySide6 pattern).
        # Parented to the long-lived QApplication, NOT this panel — the same
        # fix/idiom as gui/camera_panel.py / gui/motor_panel.py: a QThread
        # destroyed as a child of a dying widget while (or shortly after)
        # running is the MotorPanel hard-crash class; here it also surfaced
        # as an interpreter-exit access violation once several ScopePanels
        # had been built/discarded in one process (headless suite).  The
        # thread self-deletes on ``finished`` instead.
        self._reader = _ScopeReader(scope)
        self._reader_thread: QThread | None = QThread(QApplication.instance())
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
        self._display_requested.connect(self._reader.set_channel_display)
        self._avg_requested.connect(self._reader.apply_averaging)
        self._chan_config_requested.connect(self._reader.apply_chan_config)
        self._reader.acquired.connect(self._on_acquired)
        self._reader.failed.connect(self._on_acquire_failed)
        self._reader.test_done.connect(self._on_test_done)
        self._reader.settings_done.connect(self._on_settings_done)
        self._reader.sync_done.connect(self._on_sync_done)
        self._reader.trigger_done.connect(self._on_trigger_done)
        self._reader.display_done.connect(self._on_display_done)
        self._reader.avg_done.connect(self._on_avg_done)
        self._reader.chan_config_done.connect(self._on_chan_config_done)
        self._reader_thread.finished.connect(self._reader.deleteLater)
        self._reader_thread.finished.connect(self._reader_thread.deleteLater)
        self._reader_thread.start()
        self._sync_reader_channels()

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        root.setSpacing(SPACE_MD)

        root.addWidget(panel_header("TCT Control · Instrument", "Oscilloscope"))

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._build_plot())
        split.addWidget(self._build_side_column())
        split.setStretchFactor(0, 1)   # plot dominates
        split.setStretchFactor(1, 0)
        split.setSizes([820, 400])
        root.addWidget(split, 1)

        root.addLayout(self._build_acquire_row())

    def _build_plot(self) -> QWidget:
        if not _HAS_PG:
            card = Card("Live trace")
            card.add_widget(QLabel("(install pyqtgraph for live waveforms)"))
            return card
        self._plot = pg.PlotWidget()
        self._plot.setLabel("left",   "Amplitude", units="V")
        # units="s" lets pyqtgraph auto-pick ns/µs/ms.  Data is plotted in seconds.
        self._plot.setLabel("bottom", "Time",      units="s")
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        # Scale/offset come from the sliders — disable free mouse zoom so the
        # divisions stay authoritative (right-click menu still works).
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.getPlotItem().setMenuEnabled(True)
        # No plot title / legend: the coloured channel cards on the right ARE the
        # legend, which keeps the graph area clean (Tektronix/LeCroy style).

        for n, st in self._channels.items():
            curve = self._plot.plot(
                pen=pg.mkPen(st.color, width=2 if st.role == "DUT" else 1),
                name=f"CH{n} {st.label}",
            )
            curve.setVisible(st.enabled)
            self._curves[n] = curve

        # DUT markers (hidden until first acquire)
        def _vline(color: tuple) -> pg.InfiniteLine:
            line = pg.InfiniteLine(
                angle=90, movable=False,
                pen=pg.mkPen(color=color, width=1, style=Qt.PenStyle.DashLine),
            )
            line.setVisible(False)
            self._plot.addItem(line)
            return line

        self._line_onset    = _vline(_COL_ONSET)
        self._line_trailing = _vline(_COL_TRAILING)
        self._line_cfd      = _vline(_COL_CFD)

        self._int_region = pg.LinearRegionItem(
            values=(20e-9, 150e-9), brush=pg.mkBrush(60, 60, 160, 40),
            pen=pg.mkPen(_COL_INTWIN, width=1), movable=False,
        )
        self._int_region.setVisible(False)
        self._plot.addItem(self._int_region)

        # Cursor crosshair (hidden until toggled)
        self._cursor_v = pg.InfiniteLine(angle=90, movable=False,
                                         pen=pg.mkPen((150, 150, 150), width=1))
        self._cursor_h = pg.InfiniteLine(angle=0, movable=False,
                                         pen=pg.mkPen((150, 150, 150), width=1))
        for ln in (self._cursor_v, self._cursor_h):
            ln.setVisible(False)
            self._plot.addItem(ln)
        self._cursor_label = pg.TextItem(color=(200, 200, 200), anchor=(0, 1))
        self._cursor_label.setVisible(False)
        self._plot.addItem(self._cursor_label)
        self._cursor_proxy = pg.SignalProxy(
            self._plot.scene().sigMouseMoved, rateLimit=60, slot=self._on_mouse_moved)

        # Draggable cursor PAIRS for Δt (two vertical) and ΔV (two horizontal).
        def _pair(angle: int, color: tuple):
            a = pg.InfiniteLine(angle=angle, movable=True,
                                pen=pg.mkPen(color, width=1, style=Qt.PenStyle.DashLine))
            b = pg.InfiniteLine(angle=angle, movable=True,
                                pen=pg.mkPen(color, width=1, style=Qt.PenStyle.DashLine))
            for ln in (a, b):
                ln.setVisible(False)
                ln.sigPositionChanged.connect(self._update_cursor_readout)
                self._plot.addItem(ln)
            return a, b

        self._cur_t1, self._cur_t2 = _pair(90, (0, 200, 255))   # Δt (time)
        self._cur_v1, self._cur_v2 = _pair(0, (255, 200, 0))    # ΔV (volts)

        card = Card("Live trace", "amplitude (V) vs. time (s) · channel cards set colour + role")
        card.body.setContentsMargins(SPACE_SM, SPACE_SM, SPACE_SM, SPACE_SM)
        card.add_widget(self._plot)
        return card

    def _build_side_column(self) -> QWidget:
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(SPACE_MD)

        # Two columns, not one long row: the narrow side column (~360-400 px)
        # can't fit 5 status chips on one line without either clipping (a
        # disabled horizontal scrollbar) or crowding the DUT Analysis values
        # beside them (same width squeeze) — a pre-existing overflow this
        # composition pass fixes while keeping every chip.
        status_grid = QGridLayout()
        status_grid.setHorizontalSpacing(6)
        status_grid.setVerticalSpacing(6)
        self._chip_scope_conn = StatusChip("Scope offline", "neutral")
        self._chip_scope_live = StatusChip("Live off", "neutral")
        self._chip_scope_trigger = StatusChip("Trigger --", "neutral")
        self._chip_scope_avg = StatusChip("Avg --", "neutral")
        self._chip_scope_channels = StatusChip("Channels --", "neutral")
        for i, chip in enumerate((
            self._chip_scope_conn, self._chip_scope_live, self._chip_scope_trigger,
            self._chip_scope_avg, self._chip_scope_channels,
        )):
            status_grid.addWidget(chip, i // 2, i % 2, Qt.AlignLeft)
        v.addLayout(status_grid)

        # Trigger badge
        self._btn_trigger = QPushButton()
        # Amber is a FIXED safety token (identical in both palettes), so this
        # icon is caller-coloured on purpose and needs no theme re-tint.
        set_button_icon(self._btn_trigger, "mdi.flash", color=WARN_AMBER)
        self._btn_trigger.setToolTip("Open the trigger settings (source / level / slope)")
        self._btn_trigger.clicked.connect(self._open_trigger)
        self._refresh_trigger_badge()
        v.addWidget(self._btn_trigger)

        # Channel cards.  Keep the layout so rebuild_channels() can add/remove
        # cards when the scope's n_channels is refined (connect) or reconfigured.
        ch_card = Card("Channels", "enable · role · live readout")
        self._ch_layout = ch_card.body
        for n, st in self._channels.items():
            card = _ChannelCard(st)
            card.changed.connect(self._on_channel_changed)
            card.toggled.connect(self._on_channel_toggled)
            self._cards[n] = card
            self._ch_layout.addWidget(card)
        v.addWidget(ch_card)

        # DUT analysis stats
        v.addWidget(self._build_stats_box())

        # Automatic measurements (bench-scope "Measure" menu) — collapsed by
        # default (design system §7); the checkbox hides/shows the body
        # (CheckableCard has no built-in collapse — kit gap reported).
        self._meas_panel = MeasurementPanel()
        meas_card = CheckableCard("Measurements",
                                  "scope-style automatic measurements",
                                  checked=False)
        meas_body = meas_card.body.parentWidget()
        meas_card.toggled.connect(meas_body.setVisible)
        meas_body.setVisible(False)
        meas_card.add_widget(self._meas_panel)
        self._meas_card = meas_card
        v.addWidget(meas_card)

        # Cursor readout
        self._lbl_cursor = QLabel("Cursor: off")
        v.addWidget(self._lbl_cursor)

        # Display / scale controls
        if _HAS_PG:
            v.addWidget(self._build_scale_box())
            v.addWidget(self._build_chan_setup_box())

        v.addStretch(1)
        self._restyle_theme_tokens()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(col)
        scroll.setMinimumWidth(360)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        return scroll

    def _build_stats_box(self) -> Card:
        stats_card = Card("DUT analysis", "amplitude · charge · timing")

        # The four headline quantities as instrument tiles (design system §7
        # "Scope: 4 tiles — Amplitude/Rise/Charge/Drift time"), all straight
        # from analyse_waveform (analysis/ owns the formulas).  ReadoutCell,
        # NOT MetricTile, deliberately: with MetricTiles in this card,
        # repeated ScopePanel construct/teardown cycles in one process
        # reproducibly access-violate during gc (headless suite,
        # tests/test_oscilloscope_channel_count.py + batch-B combo) even
        # after the trigger-dialog/thread teardown fixes in shutdown();
        # the ReadoutCell variant is stable.  Open kit gap — reported for a
        # dedicated hunt.  Staleness is one shared caption under the grid
        # (law 4: the empty state is still explained).
        tile_grid = QGridLayout()
        tile_grid.setSpacing(SPACE_SM)
        self._tile_amp = ReadoutCell("Amplitude", "—", min_width=120)
        self._tile_rise = ReadoutCell("Rise time", "—", min_width=120)
        self._tile_chg = ReadoutCell("Charge", "—", min_width=120)
        self._tile_drift = ReadoutCell("Drift time", "—", min_width=120)
        self._stat_tiles = [self._tile_amp, self._tile_rise,
                            self._tile_chg, self._tile_drift]
        for i, tile in enumerate(self._stat_tiles):
            tile_grid.addWidget(tile, i // 2, i % 2)
        stats_card.add_layout(tile_grid)
        self._lbl_stats_stale = QLabel("No DUT waveform yet — values appear "
                                       "after the first acquisition.")
        self._lbl_stats_stale.setObjectName("cardSubtitle")
        self._lbl_stats_stale.setWordWrap(True)
        stats_card.add_widget(self._lbl_stats_stale)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setVerticalSpacing(3)

        # Secondary quantities stay as quiet rows (every existing readout
        # remains reachable): baseline RMS reads the theme accent, CFD time
        # the "delay" axis colour — see _restyle_theme_tokens().
        def _stat(row: int, label: str) -> QLabel:
            grid.addWidget(QLabel(label), row, 0)
            lbl = QLabel("—")
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(lbl, row, 1)
            return lbl

        self._lbl_rms      = _stat(0, "Baseline RMS")
        self._lbl_cfd      = _stat(1, "CFD time")

        # Marker visibility toggles
        marker_row = QHBoxLayout()
        self._chk_onset    = QCheckBox("Onset")
        self._chk_trailing = QCheckBox("Trailing")
        self._chk_cfd      = QCheckBox("CFD")
        self._chk_intwin   = QCheckBox("Int. win.")
        for chk in (self._chk_onset, self._chk_trailing, self._chk_cfd, self._chk_intwin):
            chk.setChecked(True)
            marker_row.addWidget(chk)
        if _HAS_PG:
            self._chk_onset.toggled.connect(self._line_onset.setVisible)
            self._chk_trailing.toggled.connect(self._line_trailing.setVisible)
            self._chk_cfd.toggled.connect(self._line_cfd.setVisible)
            self._chk_intwin.toggled.connect(self._int_region.setVisible)
        grid.addLayout(marker_row, 2, 0, 1, 2)
        stats_card.add_layout(grid)
        return stats_card

    def _build_acquire_row(self) -> QHBoxLayout:
        ctrl = QHBoxLayout()
        # ONE acquisition command bar (design system §7): Live | Single as a
        # segmented control, with the scope-side averaging selector beside
        # them — the same segmented QSS hooks MotorPanel's step presets use.
        seg = QFrame()
        seg.setObjectName("segmented")
        seg.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        seg_lay = QHBoxLayout(seg)
        seg_lay.setContentsMargins(3, 3, 3, 3)
        seg_lay.setSpacing(2)

        self._btn_live = QPushButton("Live")
        self._btn_live.setObjectName("segBtn")
        set_button_icon(self._btn_live, "mdi.play")
        self._btn_live.setCheckable(True)
        self._btn_live.toggled.connect(self._toggle_live)

        self._btn_single = QPushButton("Single")
        self._btn_single.setObjectName("segBtn")
        set_button_icon(self._btn_single, "mdi.camera")
        self._btn_single.clicked.connect(self._acquire_requested)

        seg_lay.addWidget(self._btn_live)
        seg_lay.addWidget(self._btn_single)

        self._cursor_mode = QComboBox()
        self._cursor_mode.addItems(["Cursor Off", "Track", "Δt (time)", "ΔV (volts)"])
        self._cursor_mode.setToolTip("Track rides the mouse; Δt/ΔV place a draggable "
                                     "pair and read the difference (Δt also shows 1/Δt)")
        self._cursor_mode.currentIndexChanged.connect(self._on_cursor_mode)

        # Scope-side acquisition averaging (ACQuire:MODe / NUMAVg).
        self._avg_combo = QComboBox()
        self._avg_combo.setToolTip("Scope-side acquisition averaging "
                                   "(ACQuire:NUMAVg — reduces noise, slows update)")
        for n in (1, 2, 4, 8, 16, 32, 64, 128, 256):
            self._avg_combo.addItem("Avg off" if n == 1 else f"Avg ×{n}", n)
        cur = int(getattr(self._scope, "n_averages", 1) or 1)
        idx = self._avg_combo.findData(cur)
        self._avg_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._avg_combo.currentIndexChanged.connect(self._on_avg_changed)

        btn_export = QPushButton("Export CSV")
        set_button_icon(btn_export, "mdi.content-save")
        btn_export.setToolTip("Save the currently displayed waveforms to a CSV file")
        btn_export.clicked.connect(self._export_csv)

        btn_test = QPushButton("Test")
        set_button_icon(btn_test, "mdi.lan-connect")
        btn_test.setToolTip("Query *IDN? and show the reply — confirms the VISA/USB link")
        btn_test.clicked.connect(self._test_connection)

        btn_visa = QPushButton("List VISA…")
        btn_visa.setToolTip("List VISA resource strings (find the scope's USB address)")
        btn_visa.clicked.connect(self._list_visa)

        for b in (seg, self._avg_combo,
                  self._cursor_mode, btn_export, btn_test, btn_visa):
            ctrl.addWidget(b)
        ctrl.addStretch(1)
        return ctrl

    # ------------------------------------------------------------------ #
    # Channel handling                                                     #
    # ------------------------------------------------------------------ #

    def _refresh_status_chips(self) -> None:
        # Law 7: these chips only claim what the panel truthfully knows.
        # There is NO instrument acquisition-state readback wired yet
        # (driver backlog, design system §6), so the "live" chip describes
        # OUR poll loop, and trigger/avg describe last-commanded config.
        connected = bool(getattr(self._scope, "connected", False))
        self._chip_scope_conn.set_status(
            "Scope connected" if connected else "Scope offline",
            "neutral" if connected else "disconnected",
        )
        live = bool(getattr(self, "_btn_live", None) and self._btn_live.isChecked())
        self._chip_scope_live.set_status(
            "Polling" if live else "Poll off",
            "busy" if live else "neutral",
            "This panel's live-view poll loop — not the instrument's own "
            "RUN/STOP state (not read back).")
        src = getattr(self._scope, "trig_source", "EXT")
        lvl = float(getattr(self._scope, "trig_level_V", 0.0))
        self._chip_scope_trigger.set_status(
            f"Trig {src} {lvl:g} V", "info",
            "Last commanded/configured trigger — not read back live.")
        avg = int(getattr(self._scope, "n_averages", 1) or 1)
        self._chip_scope_avg.set_status("Avg off" if avg <= 1 else f"Avg x{avg}",
                                        "neutral" if avg <= 1 else "info")
        enabled = len(self._enabled_channels())
        total = len(self._channels)
        self._chip_scope_channels.set_status(f"{enabled}/{total} channels",
                                             "neutral" if enabled else "warn")

    def _enabled_channels(self) -> frozenset[int]:
        return frozenset(n for n, st in self._channels.items() if st.enabled)

    def _dut_channel(self) -> int | None:
        for n, st in self._channels.items():
            if st.enabled and st.role == "DUT":
                return n
        return None

    def _sync_reader_channels(self) -> None:
        self._reader.set_enabled_channels(self._enabled_channels())

    def rebuild_channels(self) -> None:
        """Re-derive the channel cards, plot curves and trigger sources from the
        scope's CURRENT ``n_channels`` — e.g. after connect refined 4→2 via
        *IDN?, or a config reload changed the count — without an app restart.

        Reads only the ``n_channels`` attribute; never queries the instrument,
        so it is safe to call with hardware attached.  Enabled/role state is
        preserved for the channels that survive the change.
        """
        n_ch = int(getattr(self._scope, "n_channels", 4) or 4)
        desired = [n for n in _CHAN_DEFAULTS if n <= n_ch]
        if sorted(self._channels) == desired:
            return                      # unchanged — keep cards/curves/state

        # Drop channels the instrument no longer exposes.
        for n in sorted(self._channels):
            if n in desired:
                continue
            self._channels.pop(n, None)
            card = self._cards.pop(n, None)
            if card is not None:
                self._ch_layout.removeWidget(card)
                card.setParent(None)
                card.deleteLater()
            curve = self._curves.pop(n, None)
            if curve is not None and _HAS_PG:
                self._plot.removeItem(curve)

        # Add newly-available channels (seed from the per-channel defaults;
        # survivors keep their existing _ChannelState, so state is preserved).
        for n in desired:
            if n in self._channels:
                continue
            col, role, en, lab = _CHAN_DEFAULTS[n]
            st = _ChannelState(number=n, color=col, role=role, enabled=en, label=lab)
            self._channels[n] = st
            if _HAS_PG:
                curve = self._plot.plot(
                    pen=pg.mkPen(st.color, width=2 if st.role == "DUT" else 1),
                    name=f"CH{n} {st.label}",
                )
                curve.setVisible(st.enabled)
                self._curves[n] = curve
            card = _ChannelCard(st)
            card.changed.connect(self._on_channel_changed)
            card.toggled.connect(self._on_channel_toggled)
            self._cards[n] = card
            self._ch_layout.addWidget(card)

        # The trigger dialog snapshots the source list (CH1..CHn, AUX, LINE) at
        # construction; discard the cached one so it rebuilds with the new count.
        if self._trigger_dialog is not None:
            self._trigger_dialog.close()
            self._trigger_dialog.deleteLater()
            self._trigger_dialog = None

        # Reflect the new enabled set into the reader thread and repaint.
        self._sync_reader_channels()
        # Newly-added cards' readouts are unstyled until the next theme
        # switch otherwise (their colour is only set in __init__ via this
        # same call) — re-run now so a rebuild mid-session doesn't leave a
        # stray uncoloured channel card.
        self._restyle_theme_tokens()
        if self._last:
            self._render(self._last)

    def _on_channel_toggled(self, channel: int, on: bool) -> None:
        """Drive the scope's channel display to match the card toggle.

        An enabled card whose channel is off on the instrument was the bench
        "nothing plots" failure — CURVE? on an inactive source times out.
        Gated on the same "Drive scope" switch as the scale sync.
        """
        drive = getattr(self, "_chk_sync", None)
        if drive is not None and drive.isChecked() and self._scope.connected:
            self._display_requested.emit(channel, on)
        # Allow the deduplicated "CHx not active" warning to fire again if the
        # situation recurs after this state change.
        self._last_acq_err = None

    def _on_avg_changed(self, idx: int) -> None:
        n = int(self._avg_combo.itemData(idx))
        self._scope.n_averages = n
        if self._scope.connected:
            self._avg_requested.emit(n)
        _save_scope_keys_to_yaml(self._config_path, n_averages=n)
        self._refresh_status_chips()

    def _on_display_done(self, channel: int, on: bool, err: str) -> None:
        if err:
            notify(f"Scope CH{channel} display {'on' if on else 'off'} "
                   f"failed: {err}", "warn")

    def _on_avg_done(self, err: str) -> None:
        if err:
            notify(f"Scope averaging config failed: {err}", "warn")

    def _on_channel_changed(self) -> None:
        # Enable/role changed — update curve visibility, reader set, re-render.
        for n, st in self._channels.items():
            if n in self._curves:
                self._curves[n].setVisible(st.enabled)
                self._curves[n].setPen(pg.mkPen(
                    st.color, width=2 if st.role == "DUT" else 1))
        self._sync_reader_channels()
        self._refresh_status_chips()
        if self._last:
            self._render(self._last)

    # ------------------------------------------------------------------ #
    # Buttons / dialogs                                                    #
    # ------------------------------------------------------------------ #

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

    def _refresh_trigger_badge(self) -> None:
        src = getattr(self._scope, "trig_source", "EXT")
        lvl = float(getattr(self._scope, "trig_level_V", -0.41))
        slope = getattr(self._scope, "trig_slope", "FALL")
        arrow = "↑" if str(slope).upper().startswith("R") else "↓"
        self._btn_trigger.setText(f"  Trig: {src} {arrow} {lvl:g} V")
        if hasattr(self, "_chip_scope_trigger"):
            self._refresh_status_chips()

    def _open_trigger(self) -> None:
        if self._trigger_dialog is None:
            self._trigger_dialog = _TriggerDialog(
                self._scope, self._config_path, self._queue_trigger_apply, self,
                theme_mode=self._theme_mode,
            )
        self._trigger_dialog.show()
        self._trigger_dialog.raise_()
        self._trigger_dialog.activateWindow()

    def _queue_trigger_apply(self, src: str, lvl: float, slope: str,
                             dialog: _TriggerDialog | None = None) -> None:
        self._pending_trigger = (src, lvl, slope, dialog)
        self._trigger_requested.emit(src, lvl, slope)

    # ------------------------------------------------------------------ #
    # Cursor                                                               #
    # ------------------------------------------------------------------ #

    def _on_cursor_mode(self, idx: int) -> None:
        """0=Off, 1=Track, 2=Δt (vertical pair), 3=ΔV (horizontal pair)."""
        if not _HAS_PG:
            return
        self._cursor_on = (idx == 1)
        track = idx == 1
        for ln in (self._cursor_v, self._cursor_h):
            ln.setVisible(track)
        self._cursor_label.setVisible(track)

        dt = idx == 2
        dv = idx == 3
        # Seed pair positions from the current view so they start on-screen.
        xr = self._plot.viewRange()[0]; yr = self._plot.viewRange()[1]
        if dt:
            self._cur_t1.setPos(xr[0] + 0.35 * (xr[1] - xr[0]))
            self._cur_t2.setPos(xr[0] + 0.65 * (xr[1] - xr[0]))
        if dv:
            self._cur_v1.setPos(yr[0] + 0.35 * (yr[1] - yr[0]))
            self._cur_v2.setPos(yr[0] + 0.65 * (yr[1] - yr[0]))
        self._cur_t1.setVisible(dt); self._cur_t2.setVisible(dt)
        self._cur_v1.setVisible(dv); self._cur_v2.setVisible(dv)
        if idx == 0:
            self._lbl_cursor.setText("Cursor: off")
        elif track:
            self._lbl_cursor.setText("Cursor: track — move over plot")
        else:
            self._update_cursor_readout()

    def _update_cursor_readout(self) -> None:
        """Readout for the Δt / ΔV draggable pairs."""
        if not _HAS_PG:
            return
        if self._cur_t1.isVisible():
            t1, t2 = self._cur_t1.value(), self._cur_t2.value()
            dt = abs(t2 - t1)
            freq = (1.0 / dt) if dt > 0 else float("inf")
            self._lbl_cursor.setText(
                f"Δt = {_eng_format(dt, 's')}   (1/Δt = {_eng_format(freq, 'Hz')})\n"
                f"t1={_eng_format(t1, 's')}  t2={_eng_format(t2, 's')}")
        elif self._cur_v1.isVisible():
            v1, v2 = self._cur_v1.value(), self._cur_v2.value()
            self._lbl_cursor.setText(
                f"ΔV = {_eng_format(abs(v2 - v1), 'V')}\n"
                f"v1={_eng_format(v1, 'V')}  v2={_eng_format(v2, 'V')}")

    def _on_mouse_moved(self, evt) -> None:
        if not self._cursor_on or not _HAS_PG:
            return
        pos = evt[0]
        vb = self._plot.getPlotItem().vb
        if not self._plot.sceneBoundingRect().contains(pos):
            return
        mp = vb.mapSceneToView(pos)
        t, y = mp.x(), mp.y()
        self._cursor_v.setPos(t)
        self._cursor_h.setPos(y)
        self._cursor_label.setPos(t, y)
        self._cursor_label.setText(f" {_eng_format(t, 's')}\n {y * 1e3:.2f} mV")
        self._lbl_cursor.setText(f"Cursor: t={_eng_format(t, 's')}, V={y*1e3:.2f} mV")

    # ------------------------------------------------------------------ #
    # Display / scale controls                                            #
    # ------------------------------------------------------------------ #

    def _build_scale_box(self) -> Card:
        box = Card("Display & scale")
        g = QGridLayout()

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
        g.addLayout(row, 4, 0, 1, 3)
        g.addWidget(self._chk_sync, 5, 0, 1, 3)
        box.add_layout(g)
        return box

    def _build_chan_setup_box(self) -> Card:
        """Probe attenuation / coupling / bandwidth-limit for the enabled
        channels — the bench "wrong voltage scale" bug was a 10x probe factor
        left set on a bare BNC cable, silently multiplying every reading.
        A sibling card of "Display / Scale" (not nested inside it) so the
        safety warning below has room to read clearly."""
        box = Card("Channel setup", "probe · coupling · bandwidth")
        form = QFormLayout()

        self._probe_combo = QComboBox()
        for label, factor in (("1x", 1.0), ("10x", 10.0), ("100x", 100.0)):
            self._probe_combo.addItem(label, factor)
        self._probe_combo.setCurrentIndex(0)   # default 1x (bare BNC)
        self._probe_combo.setToolTip(
            "Probe attenuation applied to CH1:PRObe:GAIN on the enabled channel(s). "
            "Must match the physical probe — wrong here silently scales every reading.")
        form.addRow("Probe atten.:", self._probe_combo)

        self._coupling_combo = QComboBox()
        self._coupling_combo.addItems(["DC", "AC", "GND"])
        form.addRow("Coupling:", self._coupling_combo)

        self._bw_combo = QComboBox()
        self._bw_combo.addItem("Full", "FULL")
        self._bw_combo.addItem("20 MHz", "TWENTY")
        form.addRow("BW limit:", self._bw_combo)

        btn_apply_chan = QPushButton("Apply channel setup")
        btn_apply_chan.setToolTip("Push probe atten. / coupling / BW limit to the "
                                  "currently-enabled channel(s)")
        btn_apply_chan.clicked.connect(self._apply_chan_config)
        form.addRow(btn_apply_chan)

        self._lbl_probe_warn = QLabel("")
        self._lbl_probe_warn.setStyleSheet("font-weight: 600;")
        self._lbl_probe_warn.setVisible(False)
        form.addRow(self._lbl_probe_warn)
        box.add_layout(form)
        return box

    def _apply_chan_config(self) -> None:
        if not self._scope.connected:
            notify("Oscilloscope not connected.", "warn")
            return
        factor = float(self._probe_combo.currentData())
        coupling = self._coupling_combo.currentText()
        bw_limit = self._bw_combo.currentData()
        self._chan_config_requested.emit(factor, coupling, bw_limit)

    def _on_chan_config_done(self, err: str) -> None:
        if err:
            notify(f"Channel setup apply failed: {err}", "warn")
        else:
            notify("Applied probe atten. / coupling / BW limit.", "info")

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
        for t, v in self._last.values():
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

    def _on_acquired(self, results: dict) -> None:
        """GUI-thread slot: reader delivered fresh waveforms — pure widget work."""
        try:
            self._last = results
            if _HAS_PG and self._auto_first and results:
                self._auto_first = False
                self._render(results)
                self._autoscale()
            else:
                self._render(results)
            self._refresh_status_chips()
        except Exception as exc:
            self._on_acquire_failed(str(exc))

    def _render(self, results: dict) -> None:
        """Draw curves, per-channel readouts, DUT analysis + markers."""
        if _HAS_PG:
            for n, curve in self._curves.items():
                data = results.get(n)
                if data is not None and self._channels[n].enabled:
                    curve.setData(data[0], data[1])
                    curve.setVisible(True)
                else:
                    curve.setVisible(False)

        # Per-channel readouts (peak amplitude)
        for n, card in self._cards.items():
            data = results.get(n)
            if data is not None and len(data[1]):
                amp_mV = float(np.max(np.abs(data[1]))) * 1e3
                card.set_readout(f"peak {amp_mV:.2f} mV")
            else:
                card.set_readout("—" if not self._channels[n].enabled else "no data")

        # DUT analysis
        dut = self._dut_channel()
        dut_data = results.get(dut) if dut is not None else None
        if dut_data is None or not len(dut_data[1]):
            for tile in self._stat_tiles:
                tile.set_value("—")
            self._lbl_stats_stale.setVisible(True)
            for lbl in (self._lbl_rms, self._lbl_cfd):
                lbl.setText("—")
            self._meas_panel.update_values(None, None)
            return

        t2, v2 = dut_data
        self._meas_panel.update_values(t2, v2)
        result = analyse_waveform(t2, v2, **self._analysis_kwargs)
        self._lbl_stats_stale.setVisible(False)
        self._tile_amp.set_value(f"{result.amplitude_V * 1000:.2f} mV")
        self._tile_chg.set_value(f"{result.charge_pC:.3f} pC")
        self._lbl_rms.setText(f"{result.baseline_rms_V * 1000:.3f} mV")
        self._tile_drift.set_value(f"{result.drift_time_s * 1e9:.2f} ns"
                                   if result.drift_time_s is not None
                                   else "no edge")
        self._tile_rise.set_value(f"{result.rise_time_s * 1e9:.2f} ns"
                                  if result.rise_time_s is not None
                                  else "no edge")
        self._lbl_cfd.setText(f"{result.cfd_time_s * 1e9:.2f} ns"
                              if result.cfd_time_s is not None else "—")

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
            win = self._analysis_kwargs.get("integration_window_s", (20e-9, 150e-9))
            self._int_region.setRegion(tuple(win))
            self._int_region.setVisible(self._chk_intwin.isChecked())

    def _on_acquire_failed(self, msg: str) -> None:
        # Surface the failure (once per distinct error) instead of swallowing.
        if msg != getattr(self, "_last_acq_err", None):
            self._last_acq_err = msg
            notify(f"Oscilloscope acquire failed: {msg}", "warn")
        if hasattr(self, "_chip_scope_conn"):
            self._chip_scope_conn.set_status("Scope error", "warn", msg)

    def _toggle_live(self, checked: bool) -> None:
        if checked:
            self._live_start_requested.emit()
        else:
            self._live_stop_requested.emit()
        self._btn_live.setText("Stop" if checked else "Live")
        # Re-registers the new glyph under the same palette token, so the live/
        # stop icon keeps following the theme after this swap.
        set_button_icon(self._btn_live, "mdi.stop" if checked else "mdi.play")
        self._refresh_status_chips()

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
        # Surface a silent-scaling trap: a probe factor >1x on a channel that's
        # actually a bare BNC cable multiplies every reading (the bench
        # "wrong voltage scale" bug this task fixes the GUI side of).
        factor = s.get("probe_factor")
        warn = getattr(self, "_lbl_probe_warn", None)
        if warn is not None:
            if factor and factor > 1:
                coupling = s.get("coupling", "")
                warn.setText(f"⚠ CH1 scaled as {factor:g}x probe"
                             + (f"  ({coupling})" if coupling else ""))
                warn.setVisible(True)
            else:
                warn.setVisible(False)
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
        if not err:
            self._refresh_trigger_badge()
        else:
            notify(f"Trigger apply failed: {err}", "warn")

    # ------------------------------------------------------------------ #
    # Theme-token styling (gui.style) — re-run by refresh_theme()         #
    # ------------------------------------------------------------------ #

    def _restyle_theme_tokens(self) -> None:
        """Re-resolve theme-token colours baked as per-instance QLabel
        styles: the two secondary DUT stat rows (baseline RMS reads the
        theme accent; CFD time reads the "delay" axis-rail colour — a TCT
        CFD time genuinely is a delay measurement), the cursor readout, the
        per-channel-card live readout, the (possibly open) trigger dialog's
        status caption, and the probe-attenuation safety warning.  The four
        headline ReadoutCell tiles resolve their ink through the shared QSS
        tokens; everything else repaints automatically via the app-wide
        stylesheet ``gui.style.apply_theme()`` reapplies."""
        p = DARK if self._theme_mode == "dark" else LIGHT
        accent = p["accent"]
        delay = axis_color("delay", self._theme_mode)
        lbl_rms = getattr(self, "_lbl_rms", None)
        if lbl_rms is not None:
            lbl_rms.setStyleSheet(f"font-weight: 700; color: {accent};")
        lbl_cfd = getattr(self, "_lbl_cfd", None)
        if lbl_cfd is not None:
            lbl_cfd.setStyleSheet(f"font-weight: 700; color: {delay};")
        cursor = getattr(self, "_lbl_cursor", None)
        if cursor is not None:
            cursor.setStyleSheet(f"color: {p['muted']};")
        for card in getattr(self, "_cards", {}).values():
            card.set_readout_color(p["muted"])
        dialog = getattr(self, "_trigger_dialog", None)
        if dialog is not None:
            dialog.refresh_theme(self._theme_mode)
        warn = getattr(self, "_lbl_probe_warn", None)
        if warn is not None:
            warn.setStyleSheet(f"color: {p['warn']}; font-weight: 600;")

    def refresh_theme(self, mode: str | None = None) -> None:
        """Re-resolve theme-token colours after a light/dark switch (same
        pattern as ``MotorPanel.refresh_theme`` / ``BiasPanel.refresh_theme``).
        Structural chrome (``cardPane``/``cardHeader``/``statusChip``/...)
        already repaints via the app-wide stylesheet
        ``gui.style.apply_theme()`` reapplies; only the per-instance colours
        painted by ``_restyle_theme_tokens`` need this explicit refresh.

        Called live by ``tct_gui._toggle_theme`` (wired alongside the
        motor/bias/planner panels), so a theme switch re-resolves these
        instance-level colours immediately.
        """
        if mode:
            self._theme_mode = str(mode)
        self._restyle_theme_tokens()

    def shutdown(self) -> None:
        """Stop the acquisition thread — call before discarding the panel.

        Bounded wait; idempotent.  The thread is parented to QApplication and
        self-``deleteLater``s on ``finished`` (see __init__), so a VISA read
        still in flight past the bound finishes and cleans itself up rather
        than being destroyed as a child of this soon-deleted widget."""
        thread = self._reader_thread
        self._reader_thread = None
        try:
            self._sync_timer.stop()
            self._live_stop_requested.emit()
            if thread is not None:
                thread.quit()
                thread.wait(2000)
        except Exception:
            pass
        # Detach the cursor SignalProxy from the plot scene NOW, while both
        # are alive.  The proxy is an unparented QObject only referenced from
        # Python; leaving it connected lets a later garbage-collection pass
        # destroy scene and proxy in arbitrary order — and a proxy torn down
        # after its scene dereferences freed memory (access violation in
        # gc.collect(), reproduced headless once enough panels had lived in
        # one process).
        proxy = getattr(self, "_cursor_proxy", None)
        if proxy is not None:
            try:
                proxy.disconnect()
            except Exception:
                pass
            self._cursor_proxy = None
        # Retire the modeless trigger dialog deterministically.  It is
        # panel-parented AND Python-cycled back to the panel (its apply
        # callback is a bound method), so leaving it to a later gc pass lets
        # Python collect the wrappers in arbitrary order while Qt's C++
        # parent-cascade delete runs — the other half of the same headless
        # access violation.  Unparent first so its deletion is its own,
        # queued, orderly deleteLater instead of a cascade side effect.
        dlg = self._trigger_dialog
        self._trigger_dialog = None
        if dlg is not None:
            try:
                dlg.close()
                dlg.setParent(None)
                dlg.deleteLater()
            except Exception:
                pass

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)

    def _export_csv(self) -> None:
        """Save the last acquired waveforms (all enabled channels) to CSV."""
        if not self._last:
            return
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Export Waveform", "", "CSV (*.csv)")
        if not path:
            return
        try:
            import csv
            chans = sorted(self._last.keys())
            # Use the first channel's time base as the reference column.
            t_ref = self._last[chans[0]][0]
            with open(path, "w", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["time_ns"] + [f"ch{n}_V" for n in chans])
                for i in range(len(t_ref)):
                    row = [f"{t_ref[i] * 1e9:.4f}"]
                    for n in chans:
                        v = self._last[n][1]
                        row.append(f"{v[i]:.6f}" if i < len(v) else "")
                    writer.writerow(row)
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Export Error", str(exc))
