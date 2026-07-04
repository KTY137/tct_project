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
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QGroupBox, QLabel, QSpinBox, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
)

try:
    import pyqtgraph as pg
    import numpy as np
    _HAS_PG = True
except ImportError:
    _HAS_PG = False

from devices.slow_control_base import AlarmStatus, ALARM_COLORS, SlowControlReading

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
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    # ------------------------------------------------------------------ #
    # UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── Toolbar ───────────────────────────────────────────────────
        bar = QHBoxLayout()
        self._lbl_alarm = QLabel("● All OK")
        self._lbl_alarm.setStyleSheet(f"color: {ALARM_COLORS[AlarmStatus.OK]}; font-weight: bold;")
        bar.addWidget(self._lbl_alarm)
        bar.addStretch()
        bar.addWidget(QLabel("Poll every"))
        self._spin_interval = QSpinBox()
        self._spin_interval.setRange(1, 3600)
        self._spin_interval.setValue(self._poll_ms // 1000)
        self._spin_interval.setSuffix(" s")
        self._spin_interval.valueChanged.connect(self._update_interval)
        bar.addWidget(self._spin_interval)
        self._btn_toggle = QPushButton("▶ Start")
        self._btn_toggle.setCheckable(True)
        self._btn_toggle.toggled.connect(self._toggle_polling)
        bar.addWidget(self._btn_toggle)
        root.addLayout(bar)

        # ── Splitter: table (top) + plot (bottom) ────────────────────
        splitter = QSplitter(Qt.Vertical)

        # Channel table
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
        splitter.addWidget(self._table)

        # History plot
        if _HAS_PG:
            self._plot = pg.PlotWidget(title="Channel history")
            self._plot.setLabel("left",   "Value")
            self._plot.setLabel("bottom", "Time", units="s ago")
            self._curve = self._plot.plot(pen=pg.mkPen("#3498db", width=2))
            splitter.addWidget(self._plot)
        else:
            splitter.addWidget(QLabel("(install pyqtgraph for history plot)"))

        splitter.setSizes([250, 250])
        root.addWidget(splitter)

    def _populate_table_rows(self) -> None:
        channels = self._manager.channels
        self._table.setRowCount(len(channels))
        for row, ch in enumerate(channels):
            for col in range(5):
                self._table.setItem(row, col, QTableWidgetItem(""))
            self._table.item(row, 0).setText(ch.name)
            self._table.item(row, 2).setText(ch.unit)

    # ------------------------------------------------------------------ #
    # Polling                                                             #
    # ------------------------------------------------------------------ #

    def _toggle_polling(self, checked: bool) -> None:
        if checked:
            self._timer.start(self._poll_ms)
            self._btn_toggle.setText("⏹ Stop")
            self._poll()          # immediate first read
        else:
            self._timer.stop()
            self._btn_toggle.setText("▶ Start")

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
            self._table.item(row, 3).setText(r.status.value)
            self._table.item(row, 4).setText(ts_str)

            colour = QColor(ALARM_COLORS.get(r.status, "#ffffff"))
            brush  = QBrush(colour)
            for col in range(5):
                item = self._table.item(row, col)
                item.setForeground(brush)

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
        for r in readings.values():
            if priority.index(r.status) > priority.index(worst):
                worst = r.status
        colour = ALARM_COLORS.get(worst, "#ffffff")
        if worst in (AlarmStatus.ALARM_LOW, AlarmStatus.ALARM_HIGH):
            self._lbl_alarm.setText("⚠ ALARM")
        elif worst in (AlarmStatus.WARN_LOW, AlarmStatus.WARN_HIGH):
            self._lbl_alarm.setText("⚡ WARNING")
        elif worst == AlarmStatus.UNAVAILABLE:
            self._lbl_alarm.setText("? UNAVAILABLE")
        else:
            self._lbl_alarm.setText("● All OK")
        self._lbl_alarm.setStyleSheet(f"color: {colour}; font-weight: bold;")

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def start_polling(self) -> None:
        """Called by the main window after devices are connected."""
        self._btn_toggle.setChecked(True)

    def stop_polling(self) -> None:
        """Called by the main window before devices are disconnected."""
        self._btn_toggle.setChecked(False)
