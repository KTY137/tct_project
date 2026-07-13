"""Headless tests for the slow-control Monitor panel (``gui/monitor_panel.py``),
cockpit v5 batch A: 4 headline alarm tiles, friendly channel names, per-row
staleness, unit-tagged history legend chip (design system §4/§7).

Drives the panel through a tiny fake manager (duck-typed: ``.channels`` +
``.read_all()``) — no device backends, no timers started.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math
import time
from dataclasses import dataclass

from PySide6.QtWidgets import QApplication

from devices.slow_control_base import AlarmStatus, SlowControlReading
from gui.monitor_panel import MonitorPanel, friendly_channel_name
from gui.style import apply_theme


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@dataclass
class _Chan:
    name: str
    unit: str


class _FakeManager:
    def __init__(self) -> None:
        self.channels = [
            _Chan("temperature_C", "°C"),
            _Chan("humidity_pct", "%RH"),
            _Chan("bias_voltage_V", "V"),
            _Chan("leakage_current_nA", "nA"),
        ]
        self.readings: dict[str, SlowControlReading] = {}

    def set(self, name: str, value: float, status: AlarmStatus,
            age_s: float = 0.0) -> None:
        unit = next(c.unit for c in self.channels if c.name == name)
        self.readings[name] = SlowControlReading(
            name=name, value=value, unit=unit,
            timestamp=time.time() - age_s, status=status)

    def read_all(self) -> dict[str, SlowControlReading]:
        return dict(self.readings)


def _panel() -> tuple[MonitorPanel, _FakeManager]:
    mgr = _FakeManager()
    return MonitorPanel(mgr, poll_interval_s=5.0), mgr


# --------------------------------------------------------------------------- #
# Friendly names                                                              #
# --------------------------------------------------------------------------- #

def test_friendly_channel_name_drops_unit_suffix():
    assert friendly_channel_name("temperature_C") == "Temperature"
    assert friendly_channel_name("humidity_pct") == "Humidity"
    assert friendly_channel_name("bias_voltage_V") == "Bias voltage"
    assert friendly_channel_name("leakage_current_nA") == "Leakage current"
    # No recognised suffix -> name kept whole.
    assert friendly_channel_name("box_flow") == "Box flow"


def test_table_shows_friendly_names_with_config_key_tooltip():
    _app()
    panel, _ = _panel()
    assert panel._table.item(0, 0).text() == "Temperature"
    assert "temperature_C" in panel._table.item(0, 0).toolTip()


# --------------------------------------------------------------------------- #
# Headline tiles                                                              #
# --------------------------------------------------------------------------- #

def test_four_headline_tiles_claim_the_configured_channels():
    _app()
    panel, _ = _panel()
    assert len(panel._tiles.tiles()) == 4
    assert set(panel._tile_channel) == {
        "temperature_C", "humidity_pct", "bias_voltage_V", "leakage_current_nA",
    }
    # No reading yet — honestly stale, captioned (law 4).
    for tile in panel._tiles.tiles():
        assert tile.is_stale()


def test_missing_channel_keeps_tile_as_not_configured():
    _app()
    mgr = _FakeManager()
    mgr.channels = [c for c in mgr.channels if c.name != "humidity_pct"]
    panel = MonitorPanel(mgr, poll_interval_s=5.0)
    assert len(panel._tiles.tiles()) == 4
    captions = [t._caption.text() for t in panel._tiles.tiles()]
    assert "not configured" in captions


def test_poll_updates_tiles_with_alarm_ink_and_age_caption():
    _app()
    panel, mgr = _panel()
    mgr.set("temperature_C", 22.1, AlarmStatus.OK)
    mgr.set("humidity_pct", 75.0, AlarmStatus.WARN_HIGH)
    mgr.set("bias_voltage_V", -150.0, AlarmStatus.OK)
    mgr.set("leakage_current_nA", 600.0, AlarmStatus.ALARM_HIGH)
    panel._poll()

    t_temp = panel._tile_channel["temperature_C"]
    t_hum = panel._tile_channel["humidity_pct"]
    t_leak = panel._tile_channel["leakage_current_nA"]
    # Quiet nominal: in-range value ink stays normal, alarms get colour.
    assert t_temp.state() == "normal"
    assert t_hum.state() == "warn"
    assert t_leak.state() == "crit"
    assert "°C" in t_temp.value()
    assert not t_temp.is_stale()
    assert "ago" in t_temp._caption.text()


def test_unavailable_channel_is_distinct_from_aged_value():
    _app()
    panel, mgr = _panel()
    mgr.set("temperature_C", float("nan"), AlarmStatus.UNAVAILABLE)
    mgr.set("humidity_pct", 45.0, AlarmStatus.OK, age_s=60.0)
    mgr.set("bias_voltage_V", -150.0, AlarmStatus.OK)
    mgr.set("leakage_current_nA", 5.0, AlarmStatus.OK)
    panel._poll()

    t_unavail = panel._tile_channel["temperature_C"]
    t_aged = panel._tile_channel["humidity_pct"]
    assert t_unavail.is_stale()
    assert "unavailable" in t_unavail._caption.text()
    assert t_aged.is_stale()
    assert "aged" in t_aged._caption.text()
    assert t_unavail._caption.text() != t_aged._caption.text()


# --------------------------------------------------------------------------- #
# Quiet-nominal chips                                                         #
# --------------------------------------------------------------------------- #

def test_all_nominal_chip_is_quiet_grey_not_green():
    _app()
    panel, mgr = _panel()
    for name in ("temperature_C", "humidity_pct", "bias_voltage_V",
                 "leakage_current_nA"):
        mgr.set(name, 1.0, AlarmStatus.OK)
    panel._poll()
    assert panel._chip_alarm.text() == "All nominal"
    assert panel._chip_alarm.property("state") == "neutral"
    assert panel._chip_alarm_count.property("state") == "neutral"


def test_alarm_escalates_header_chip():
    _app()
    panel, mgr = _panel()
    mgr.set("temperature_C", 99.0, AlarmStatus.ALARM_HIGH)
    mgr.set("humidity_pct", 45.0, AlarmStatus.OK)
    panel._poll()
    assert panel._chip_alarm.text() == "Alarm"
    assert panel._chip_alarm.property("state") == "crit"


def test_unavailable_reads_unknown_not_neutral():
    """Law 7: 'we don't know' is visually distinct from 'confirmed fine'."""
    _app()
    panel, mgr = _panel()
    mgr.set("temperature_C", float("nan"), AlarmStatus.UNAVAILABLE)
    panel._poll()
    assert panel._chip_alarm.text() == "Unavailable"
    assert panel._chip_alarm.property("state") == "unknown"
    row_chip = panel._table.cellWidget(0, 3)
    assert row_chip.property("state") == "unknown"


def test_construction_never_claims_all_nominal_before_first_poll():
    """Trust boundary (council_v5_paul.md §4 -- state-color census D4 item
    3): construction happens before any reading exists at all -- the header
    banner must not open on a confident "All nominal" it has zero data to
    back up."""
    _app()
    panel, _mgr = _panel()
    assert panel._chip_alarm.text() != "All nominal"
    assert panel._chip_alarm.property("state") == "unknown"


def test_zero_readings_poll_never_claims_all_nominal():
    """A poll whose read_all() comes back empty (zero configured channels,
    or nothing produced yet) is UNKNOWN, not a confident "All nominal" --
    the exact 'ALL NOMINAL with zero readings' lie council_v5_paul.md §4
    calls out. No mgr.set() calls here: read_all() returns {} even though
    4 channels ARE configured, exercising the "gated on >=1 real reading"
    rule directly."""
    _app()
    panel, mgr = _panel()
    assert mgr.read_all() == {}
    panel._poll()
    assert panel._chip_alarm.text() != "All nominal"
    assert panel._chip_alarm.property("state") == "unknown"


def test_at_least_one_real_reading_still_reads_all_nominal():
    """The gate gets out of the way the moment there IS real data -- this is
    a >=1-reading gate, not a require-every-channel gate."""
    _app()
    panel, mgr = _panel()
    mgr.set("temperature_C", 22.0, AlarmStatus.OK)
    panel._poll()
    assert panel._chip_alarm.text() == "All nominal"
    assert panel._chip_alarm.property("state") == "neutral"


# --------------------------------------------------------------------------- #
# History plot: legend chip + NaN gaps                                        #
# --------------------------------------------------------------------------- #

def test_history_legend_chip_is_unit_tagged():
    _app()
    panel, mgr = _panel()
    mgr.set("temperature_C", 22.0, AlarmStatus.OK)
    panel._poll()
    panel._table.selectRow(0)
    assert "Temperature" in panel._chip_legend.text()
    assert "°C" in panel._chip_legend.text()


def test_failed_polls_leave_nan_gaps_in_history():
    _app()
    panel, mgr = _panel()
    mgr.set("temperature_C", 22.0, AlarmStatus.OK)
    panel._poll()
    mgr.set("temperature_C", float("nan"), AlarmStatus.UNAVAILABLE)
    panel._poll()
    mgr.set("temperature_C", 23.0, AlarmStatus.OK)
    panel._poll()
    hist = panel._history["temperature_C"]
    values = [v for _, v in hist]
    assert len(values) == 3
    assert math.isnan(values[1])   # the gap is stored, not skipped


# --------------------------------------------------------------------------- #
# Theme switch smoke                                                          #
# --------------------------------------------------------------------------- #

def test_theme_switch_smoke():
    app = _app()
    apply_theme(app, "light")
    panel, mgr = _panel()
    mgr.set("temperature_C", 22.0, AlarmStatus.OK)
    panel._poll()
    apply_theme(app, "dark")
    panel.refresh_theme("dark")
    assert not panel.grab().isNull()
    apply_theme(app, "light")
    panel.refresh_theme("light")
    assert not panel.grab().isNull()


def test_no_graphics_effect_on_history_plot():
    _app()
    panel, _ = _panel()
    assert panel._figure.graphicsEffect() is None
    assert panel._plot.graphicsEffect() is None
