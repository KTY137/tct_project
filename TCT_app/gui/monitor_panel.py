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

from PySide6.QtCore import Qt, QTimer, QSettings
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
from gui.panel_kit import Card, panel_header
from gui.status_widgets import StatusChip, set_button_icon
from gui.style import DARK, LIGHT, PLOT_BG, SPACE_SM

if TYPE_CHECKING:
    from controller.slow_control_manager import SlowControlManager

# How many history points to keep per channel
_HISTORY_LEN = 600


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
        self._theme_mode = str(QSettings("TCT", "TCTSetup").value("theme", "light"))
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    # ------------------------------------------------------------------ #
    # UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        root.addWidget(panel_header("TCT Control · Instrument", "Monitor"))

        # ── Toolbar ───────────────────────────────────────────────────
        bar = QHBoxLayout()
        self._chip_alarm = StatusChip("All OK", "good")
        self._chip_polling = StatusChip("Polling off", "neutral")
        self._chip_stale = StatusChip("Fresh --", "neutral")
        self._chip_alarm_count = StatusChip("0 alarms", "good")
        for chip in (self._chip_alarm, self._chip_polling, self._chip_stale, self._chip_alarm_count):
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

        # ── Splitter: table (top) + plot (bottom) ────────────────────
        splitter = QSplitter(Qt.Vertical)

        # Channel table
        table_card = Card("Channels")
        table_card.body.setContentsMargins(SPACE_SM, SPACE_SM, SPACE_SM, SPACE_SM)
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(
            ["Channel", "Value", "Unit", "Status", "Timestamp"]
        )
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._on_selection)
        self._populate_table_rows()
        table_card.add_widget(self._table)
        splitter.addWidget(table_card)

        # History plot
        plot_card = Card("History")
        plot_card.body.setContentsMargins(SPACE_SM, SPACE_SM, SPACE_SM, SPACE_SM)
        if _HAS_PG:
            self._plot = pg.PlotWidget(title="Channel history", background=PLOT_BG)
            self._plot.showGrid(x=True, y=True, alpha=0.25)
            self._plot.setLabel("left",   "Value")
            self._plot.setLabel("bottom", "Time", units="s ago")
            self._curve = self._plot.plot(pen=pg.mkPen(self._history_accent(), width=2))
            plot_card.add_widget(self._plot)
        else:
            plot_card.add_widget(QLabel("(install pyqtgraph for history plot)"))
        splitter.addWidget(plot_card)

        splitter.setSizes([250, 250])
        root.addWidget(splitter)

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
            self._table.item(row, 0).setText(ch.name)
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
            ts_str = time.strftime("%H:%M:%S", time.localtime(r.timestamp))
            self._table.item(row, 1).setText(val_str)
            self._table.item(row, 4).setText(ts_str)
            chip: StatusChip = self._table.cellWidget(row, 3)
            chip.set_status(r.status.value, self._alarm_state(r.status))

    @staticmethod
    def _alarm_state(status: AlarmStatus) -> str:
        if status in (AlarmStatus.ALARM_LOW, AlarmStatus.ALARM_HIGH):
            return "crit"
        if status in (AlarmStatus.WARN_LOW, AlarmStatus.WARN_HIGH):
            return "warn"
        if status == AlarmStatus.UNAVAILABLE:
            return "neutral"
        return "good"

    # ------------------------------------------------------------------ #
    # History + plot                                                      #
    # ------------------------------------------------------------------ #

    def _store_history(self, readings: dict[str, SlowControlReading]) -> None:
        now = time.monotonic()
        for name, r in readings.items():
            if name not in self._history:
                self._history[name] = collections.deque(maxlen=_HISTORY_LEN)
            if not math.isnan(r.value):
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
        self._curve.setData(times, values)
        ch_list = self._manager.channels
        ch = next((c for c in ch_list if c.name == self._selected_channel), None)
        label = f"{self._selected_channel} [{ch.unit}]" if ch else self._selected_channel
        self._plot.setTitle(label)
        self._plot.setLabel("left", label)

    def _on_selection(self) -> None:
        rows = self._table.selectedItems()
        if rows:
            row = self._table.row(rows[0])
            channels = self._manager.channels
            if row < len(channels):
                self._selected_channel = channels[row].name
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
        if worst in (AlarmStatus.ALARM_LOW, AlarmStatus.ALARM_HIGH):
            self._chip_alarm.set_status("ALARM", "crit")
        elif worst in (AlarmStatus.WARN_LOW, AlarmStatus.WARN_HIGH):
            self._chip_alarm.set_status("WARNING", "warn")
        elif worst == AlarmStatus.UNAVAILABLE:
            self._chip_alarm.set_status("UNAVAILABLE", "neutral")
        else:
            self._chip_alarm.set_status("All OK", "good")
        self._chip_alarm_count.set_status(
            f"{alarm_count} alarms",
            "good" if alarm_count == 0 else (
                "crit" if worst in (AlarmStatus.ALARM_LOW, AlarmStatus.ALARM_HIGH) else "warn"
            ),
        )
        if readings:
            newest = max(r.timestamp for r in readings.values())
            age_s = max(0.0, time.time() - newest)
            stale = age_s > max(2.0, 2.0 * (self._poll_ms / 1000.0))
            self._chip_stale.set_status(
                f"Stale {age_s:.0f}s" if stale else "Fresh",
                "warn" if stale else "good",
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
