"""
Slow-control monitor panel.

Shows a live table of all channels with colour-coded alarm status and
a time-series history plot for any selected channel.  Polls the
SlowControlManager via a QTimer — no background threads needed.
"""
from __future__ import annotations

import collections
import math
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QSpinBox, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
)

try:
    import pyqtgraph as pg
    import numpy as np
    _HAS_PG = True
except ImportError:
    _HAS_PG = False

from devices.slow_control_base import AlarmStatus, SlowControlReading
from gui.app_settings import theme_mode
from gui.panel_kit import Card, FigureCard, MetricGrid, MetricTile, panel_header
from gui.status_widgets import StatusChip, set_button_icon
from gui.style import DARK, LIGHT, SPACE_SM

if TYPE_CHECKING:
    from controller.slow_control_manager import SlowControlManager

# How many history points to keep per channel
_HISTORY_LEN = 600

# The four headline dashboard tiles (design system §7 "Monitor: 4
# alarm-colored tiles up top") and the channel-name fragments that claim
# them. Matching is by substring against the configured channel key so a
# rename like "temperature_C" -> "dut_temp_C" still lands in the right tile.
_TILE_SPECS: list[tuple[str, tuple[str, ...]]] = [
    ("Temperature", ("temp",)),
    ("Humidity", ("humid",)),
    ("Bias", ("bias", "volt")),
    ("Leakage", ("leak", "curr")),
]

# Unit-ish suffixes stripped when deriving a friendly display name from a
# config channel key ("leakage_current_nA" -> "Leakage current").
_UNIT_SUFFIXES = {
    "c", "k", "pct", "rh", "v", "mv", "kv", "a", "ma", "ua", "na", "pa",
    "mbar", "bar", "pc",
}


def friendly_channel_name(key: str) -> str:
    """Human-readable channel label from a config key — sentence case, unit
    suffix dropped (the unit is shown separately, never smuggled in the
    name). The raw key stays available as a tooltip wherever this is used."""
    parts = [p for p in str(key).split("_") if p]
    if len(parts) > 1 and parts[-1].lower() in _UNIT_SUFFIXES:
        parts = parts[:-1]
    label = " ".join(parts).strip() or str(key)
    return label[:1].upper() + label[1:].lower() if label else str(key)


class MonitorPanel(QWidget):
    """
    Live slow-control dashboard.

    Accepts any SlowControlManager whose channels list can grow or
    shrink at runtime without changes here.
    """

    def __init__(
        self,
        manager: "SlowControlManager",
        poll_interval_s: float = 5.0,
        influx_writer=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._manager       = manager
        self._influx        = influx_writer
        self._poll_ms       = int(poll_interval_s * 1000)
        self._history: dict[str, collections.deque] = {
            ch.name: collections.deque(maxlen=_HISTORY_LEN)
            for ch in manager.channels
        }
        self._selected_channel: str | None = (
            manager.channels[0].name if manager.channels else None
        )
        # Theme mode for the History-plot curve accent (gui.style tokens).
        # Read once from the same QSettings key main.py/tct_gui.py use,
        # mirroring MotorPanel/BiasPanel; see refresh_theme() below.
        self._theme_mode = theme_mode()
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    # ------------------------------------------------------------------ #
    # UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # Trust boundary (council_v5_paul.md §4 — state-color census D4 item
        # 3): "All nominal" must be GATED on >=1 real reading. Construction
        # happens before the first poll has run, i.e. exactly zero data — so
        # the honest initial claim is "no data yet" (unknown), never a
        # confident nominal; see _update_alarm_banner() for the live-poll
        # counterpart of this same rule.
        self._chip_alarm = StatusChip("No data", "unknown")
        root.addWidget(panel_header(
            "TCT Control · Instrument", "Monitor",
            trailing=[self._chip_alarm],
        ))

        # ── Headline tiles (§7: 4 alarm-colored tiles up top) ─────────
        # One tile per headline quantity, claimed from the configured
        # channels by name fragment; a quantity with no configured channel
        # keeps its tile — honestly stale, captioned "not configured" — so
        # the dashboard shape never silently changes with the config.
        self._tiles = MetricGrid(columns=4, compact=True)
        self._tile_channel: dict[str, MetricTile] = {}
        claimed: set[str] = set()
        for label, fragments in _TILE_SPECS:
            ch_name = self._match_channel(fragments, claimed)
            tile = self._tiles.add_tile(MetricTile(
                friendly_channel_name(ch_name) if ch_name else label,
                "--", compact=True))
            if ch_name:
                claimed.add(ch_name)
                tile.setToolTip(f"config channel: {ch_name}")
                tile.set_stale(True, "no reading yet")
                self._tile_channel[ch_name] = tile
            else:
                tile.set_stale(True, "not configured")
        root.addWidget(self._tiles)

        # ── Toolbar / command row ─────────────────────────────────────
        bar = QHBoxLayout()
        self._chip_polling = StatusChip("Polling off", "neutral")
        self._chip_stale = StatusChip("Fresh --", "neutral")
        self._chip_alarm_count = StatusChip("0 alarms", "neutral")
        for chip in (self._chip_polling, self._chip_stale, self._chip_alarm_count):
            bar.addWidget(chip)
        bar.addStretch()
        bar.addWidget(QLabel("Poll every"))
        self._spin_interval = QSpinBox()
        self._spin_interval.setRange(1, 3600)
        self._spin_interval.setValue(self._poll_ms // 1000)
        self._spin_interval.setSuffix(" s")
        self._spin_interval.valueChanged.connect(self._update_interval)
        bar.addWidget(self._spin_interval)
        self._btn_toggle = QPushButton("▶ Start")
        set_button_icon(self._btn_toggle, "mdi.play")
        self._btn_toggle.setCheckable(True)
        self._btn_toggle.toggled.connect(self._toggle_polling)
        bar.addWidget(self._btn_toggle)
        root.addLayout(bar)

        # ── Splitter: table (demoted detail) + history plot ──────────
        splitter = QSplitter(Qt.Vertical)

        # Channel table — every channel, friendly-named (raw config key in
        # the tooltip), demoted below the headline tiles.
        table_card = Card("All channels")
        table_card.body.setContentsMargins(SPACE_SM, SPACE_SM, SPACE_SM, SPACE_SM)
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(
            ["Channel", "Value", "Unit", "Status", "Updated"]
        )
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._on_selection)
        self._populate_table_rows()
        table_card.add_widget(self._table)
        splitter.addWidget(table_card)

        # History plot — FigureCard with a unit-tagged legend chip in the
        # header (§4: "per-channel units/legend chips — no mixed unlabeled
        # axis").
        if _HAS_PG:
            self._figure = FigureCard("History")
            self._chip_legend = StatusChip("no channel selected", "neutral")
            self._figure.add_header_widget(self._chip_legend)
            self._plot = self._figure.plot
            self._plot.setLabel("left",   "Value")
            self._plot.setLabel("bottom", "Time", units="s ago")
            self._curve = self._plot.plot(pen=pg.mkPen(self._history_accent(), width=2))
            splitter.addWidget(self._figure)
        else:
            plot_card = Card("History")
            plot_card.add_widget(QLabel("(install pyqtgraph for history plot)"))
            splitter.addWidget(plot_card)

        splitter.setSizes([250, 250])
        root.addWidget(splitter)
        self._update_legend_chip()

    def _match_channel(self, fragments: tuple[str, ...], claimed: set[str]) -> str | None:
        """First configured channel whose key contains any of *fragments*
        (case-insensitive) and is not already claimed by an earlier tile."""
        for ch in self._manager.channels:
            name = ch.name.lower()
            if ch.name not in claimed and any(f in name for f in fragments):
                return ch.name
        return None

    # ------------------------------------------------------------------ #
    # Theme-token styling (gui.style) — re-run by refresh_theme()         #
    # ------------------------------------------------------------------ #

    def _history_accent(self) -> str:
        """Resolve the History-plot curve colour from the theme accent
        token (replaces a hardcoded '#3498db') for the current theme mode."""
        return (DARK if self._theme_mode == "dark" else LIGHT)["accent"]

    def _restyle_theme_tokens(self) -> None:
        """Re-resolve the History curve's accent colour, baked as a pyqtgraph
        pen at construction time (a theme switch does not otherwise touch it)."""
        if _HAS_PG and hasattr(self, "_curve"):
            self._curve.setPen(pg.mkPen(self._history_accent(), width=2))

    def refresh_theme(self, mode: str | None = None) -> None:
        """Re-resolve theme-token colours after a light/dark switch (same
        pattern as ``MotorPanel.refresh_theme`` / ``BiasPanel.refresh_theme``).
        Structural chrome (``cardPane``/``cardHeader``/``statusChip``/...)
        already repaints via the app-wide stylesheet
        ``gui.style.apply_theme()`` reapplies; only the curve pen baked by
        ``_restyle_theme_tokens`` needs this explicit refresh."""
        if mode:
            self._theme_mode = str(mode)
        self._restyle_theme_tokens()

    def _populate_table_rows(self) -> None:
        channels = self._manager.channels
        self._table.setRowCount(len(channels))
        for row, ch in enumerate(channels):
            for col in range(5):
                self._table.setItem(row, col, QTableWidgetItem(""))
            # Friendly name on display, raw config key kept in the tooltip
            # (law 7: the UI must stay traceable to the configured truth).
            name_item = self._table.item(row, 0)
            name_item.setText(friendly_channel_name(ch.name))
            name_item.setToolTip(f"config channel: {ch.name}")
            self._table.item(row, 2).setText(ch.unit)
            self._table.setCellWidget(row, 3, StatusChip("—", "neutral"))

    # ------------------------------------------------------------------ #
    # Polling                                                             #
    # ------------------------------------------------------------------ #

    def _toggle_polling(self, checked: bool) -> None:
        if checked:
            self._timer.start(self._poll_ms)
            self._btn_toggle.setText("⏹ Stop")
            set_button_icon(self._btn_toggle, "mdi.stop")
            self._chip_polling.set_status("Polling on", "busy")
            self._poll()          # immediate first read
        else:
            self._timer.stop()
            self._btn_toggle.setText("▶ Start")
            set_button_icon(self._btn_toggle, "mdi.play")
            self._chip_polling.set_status("Polling off", "neutral")

    def _update_interval(self, seconds: int) -> None:
        self._poll_ms = seconds * 1000
        if self._timer.isActive():
            self._timer.setInterval(self._poll_ms)

    def _poll(self) -> None:
        readings = self._manager.read_all()
        self._update_tiles(readings)
        self._update_table(readings)
        self._store_history(readings)
        self._update_plot()
        self._update_alarm_banner(readings)
        if self._influx is not None:
            self._influx.write_readings(readings)

    # ------------------------------------------------------------------ #
    # Table update                                                        #
    # ------------------------------------------------------------------ #

    def _update_table(self, readings: dict[str, SlowControlReading]) -> None:
        for row, ch in enumerate(self._manager.channels):
            r = readings.get(ch.name)
            if r is None:
                continue
            val_str = (
                "N/A" if math.isnan(r.value) else f"{r.value:.4g}"
            )
            # Per-row staleness (§4): wall time plus age, so a wedged
            # channel's row says how old its number is, not just when.
            age_s = max(0.0, time.time() - r.timestamp)
            ts_str = time.strftime("%H:%M:%S", time.localtime(r.timestamp))
            self._table.item(row, 1).setText(val_str)
            self._table.item(row, 4).setText(f"{ts_str} ({age_s:.0f} s ago)")
            chip: StatusChip = self._table.cellWidget(row, 3)
            chip.set_status(r.status.value, self._alarm_state(r.status))

    def _update_tiles(self, readings: dict[str, SlowControlReading]) -> None:
        """Refresh the four headline tiles (§7). Alarm colour through value
        ink (law 1: nominal stays quiet grey); staleness is a caption with
        the reading's age (law 4); UNAVAILABLE is visually distinct from a
        merely old value (law 7)."""
        stale_after_s = max(2.0, 2.0 * (self._poll_ms / 1000.0))
        for ch_name, tile in self._tile_channel.items():
            r = readings.get(ch_name)
            if r is None:
                continue
            ch = next((c for c in self._manager.channels if c.name == ch_name), None)
            unit = ch.unit if ch else ""
            if r.status == AlarmStatus.UNAVAILABLE or math.isnan(r.value):
                tile.set_state("normal")
                tile.set_stale(True, "unavailable — channel not responding")
                continue
            tile.set_value(f"{r.value:.4g} {unit}".strip())
            state = self._alarm_state(r.status)
            tile.set_state("normal" if state in ("good", "unknown", "neutral") else state)
            age_s = max(0.0, time.time() - r.timestamp)
            if age_s > stale_after_s:
                tile.set_stale(True, f"value aged {age_s:.0f} s")
            else:
                tile.set_stale(False, f"updated {age_s:.0f} s ago")

    @staticmethod
    def _alarm_state(status: AlarmStatus) -> str:
        if status in (AlarmStatus.ALARM_LOW, AlarmStatus.ALARM_HIGH):
            return "crit"
        if status in (AlarmStatus.WARN_LOW, AlarmStatus.WARN_HIGH):
            return "warn"
        if status == AlarmStatus.UNAVAILABLE:
            # Law 7: "we don't know" is its own designed state (dashed-ring
            # chip chrome), never the same quiet dot as "confirmed fine".
            return "unknown"
        # Law 1 (quiet nominal): an in-range reading is routine — grey, not
        # a persistent green light.
        return "neutral"

    # ------------------------------------------------------------------ #
    # History + plot                                                      #
    # ------------------------------------------------------------------ #

    def _store_history(self, readings: dict[str, SlowControlReading]) -> None:
        now = time.monotonic()
        for name, r in readings.items():
            if name not in self._history:
                self._history[name] = collections.deque(maxlen=_HISTORY_LEN)
            # Failed polls are stored as NaN — the curve draws a GAP there
            # (§4: "NaN gaps for failed polls"), never a bridging line that
            # invents data across the outage.
            self._history[name].append((now, r.value))

    def _update_plot(self) -> None:
        if not _HAS_PG or self._selected_channel is None:
            return
        hist = self._history.get(self._selected_channel)
        if not hist:
            return
        now = time.monotonic()
        times  = np.array([-(now - t) for t, _ in hist])
        values = np.array([v            for _, v in hist])
        self._curve.setData(times, values, connect="finite")
        ch = next((c for c in self._manager.channels
                   if c.name == self._selected_channel), None)
        label = friendly_channel_name(self._selected_channel)
        # Unit in the label text, not pyqtgraph's ``units=`` — SI prefixing
        # would mangle non-SI units like %RH into "k%RH" when autoscaling.
        self._plot.setLabel("left", f"{label} ({ch.unit})" if ch else label)

    def _update_legend_chip(self) -> None:
        """The FigureCard header's unit-tagged legend chip (§4)."""
        if not hasattr(self, "_chip_legend"):
            return
        if self._selected_channel is None:
            self._chip_legend.set_status("no channel selected", "neutral")
            return
        ch = next((c for c in self._manager.channels
                   if c.name == self._selected_channel), None)
        unit = ch.unit if ch else "?"
        self._chip_legend.set_status(
            f"{friendly_channel_name(self._selected_channel)} · {unit}",
            "neutral", f"config channel: {self._selected_channel}")

    def _on_selection(self) -> None:
        rows = self._table.selectedItems()
        if rows:
            row = self._table.row(rows[0])
            channels = self._manager.channels
            if row < len(channels):
                self._selected_channel = channels[row].name
                self._update_legend_chip()
                self._update_plot()

    # ------------------------------------------------------------------ #
    # Alarm banner                                                        #
    # ------------------------------------------------------------------ #

    def _update_alarm_banner(self, readings: dict[str, SlowControlReading]) -> None:
        worst = AlarmStatus.OK
        priority = list(AlarmStatus)
        alarm_count = 0
        for r in readings.values():
            if priority.index(r.status) > priority.index(worst):
                worst = r.status
            if r.status != AlarmStatus.OK:
                alarm_count += 1
        # Quiet nominal (law 1): only abnormal states get colour; routine
        # "everything in range" is grey prose, never a standing green light.
        # Trust boundary (council_v5_paul.md §4): "All nominal" must be
        # GATED on >=1 real reading -- an empty readings dict (zero
        # configured channels, or read_all() hasn't produced anything yet)
        # is UNKNOWN, never a confident "fine" claim (law 7).
        if not readings:
            self._chip_alarm.set_status("No data", "unknown")
        elif worst in (AlarmStatus.ALARM_LOW, AlarmStatus.ALARM_HIGH):
            self._chip_alarm.set_status("Alarm", "crit")
        elif worst in (AlarmStatus.WARN_LOW, AlarmStatus.WARN_HIGH):
            self._chip_alarm.set_status("Warning", "warn")
        elif worst == AlarmStatus.UNAVAILABLE:
            self._chip_alarm.set_status("Unavailable", "unknown")
        else:
            self._chip_alarm.set_status("All nominal", "neutral")
        self._chip_alarm_count.set_status(
            f"{alarm_count} alarms",
            "neutral" if alarm_count == 0 else (
                "crit" if worst in (AlarmStatus.ALARM_LOW, AlarmStatus.ALARM_HIGH) else "warn"
            ),
        )
        if readings:
            newest = max(r.timestamp for r in readings.values())
            age_s = max(0.0, time.time() - newest)
            stale = age_s > max(2.0, 2.0 * (self._poll_ms / 1000.0))
            self._chip_stale.set_status(
                f"Stale {age_s:.0f}s" if stale else "Fresh",
                "warn" if stale else "neutral",
            )

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def start_polling(self) -> None:
        """Called by the main window after devices are connected."""
        self._btn_toggle.setChecked(True)

    def stop_polling(self) -> None:
        """Called by the main window before devices are disconnected."""
        self._btn_toggle.setChecked(False)
