"""The alarm with no home (TECH_DEBT round-01).

A slow-control ALARM used to be rendered ONLY as a coloured row inside the
Monitor tab's table: an operator on the Bias tab during a MANUAL HV ramp --
exactly when no scan supervisor is running -- could not see it at all.

``MonitorPanel`` now announces alarm *transitions* on the app-wide status bus
(``gui/status_bus.py``): ``notify()`` for the human-readable event (status bar
+ Log dock) and ``set_alarm()`` for the sticky worst-state headline.

These tests pin the properties that make such an announcement trustworthy:
it fires on a TRANSITION (never once per poll), it escalates immediately,
it names the channel/value/limit in TEXT (no colour-only state, nothing that
depends on a glass tier), and a broken notification sink can never take the
poll loop down with it.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from dataclasses import dataclass, field

import pytest
from PySide6.QtWidgets import QApplication

from devices.slow_control_base import (
    AlarmStatus,
    AlarmThresholds,
    SlowControlReading,
)
from gui import monitor_panel as mp
from gui.monitor_panel import MonitorPanel
from gui.status_bus import STATUS
from gui.style import apply_theme


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@dataclass
class _Chan:
    """Duck-typed slow-control channel: name + unit + thresholds, exactly what
    the panel reads (never a device)."""
    name: str
    unit: str
    thresholds: AlarmThresholds = field(default_factory=AlarmThresholds)


class _FakeManager:
    def __init__(self) -> None:
        self.channels = [
            _Chan("temperature_C", "°C",
                  AlarmThresholds(warn_high=25.0, alarm_high=30.0,
                                  warn_low=15.0, alarm_low=10.0)),
            _Chan("humidity_pct", "%RH",
                  AlarmThresholds(warn_high=50.0, alarm_high=60.0)),
        ]
        self.readings: dict[str, SlowControlReading] = {}

    def set(self, name: str, value: float, status: AlarmStatus) -> None:
        unit = next(c.unit for c in self.channels if c.name == name)
        self.readings[name] = SlowControlReading(
            name=name, value=value, unit=unit,
            timestamp=time.time(), status=status)

    def read_all(self) -> dict[str, SlowControlReading]:
        return dict(self.readings)


class _Sink:
    """Records everything the panel pushes onto the status bus."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def __call__(self, text: str, level: str = "info") -> None:
        self.events.append((text, level))

    @property
    def texts(self) -> list[str]:
        return [t for t, _ in self.events]

    def with_prefix(self, prefix: str) -> list[str]:
        return [t for t in self.texts if t.startswith(prefix)]


@pytest.fixture()
def panel(monkeypatch) -> tuple[MonitorPanel, _FakeManager, _Sink]:
    _app()
    sink = _Sink()
    monkeypatch.setattr(mp, "notify", sink)
    mgr = _FakeManager()
    return MonitorPanel(mgr, poll_interval_s=1.0), mgr, sink


# --------------------------------------------------------------------------- #
# Transition, not per-poll                                                     #
# --------------------------------------------------------------------------- #

def test_entering_alarm_notifies_exactly_once(panel):
    """The poll timer runs ~1 Hz. An alarm must announce itself when the state
    ENTERS the alarm class -- not once per second. A notification storm is how
    a real alarm gets ignored."""
    p, mgr, sink = panel
    mgr.set("temperature_C", 31.4, AlarmStatus.ALARM_HIGH)
    mgr.set("humidity_pct", 40.0, AlarmStatus.OK)
    for _ in range(5):                      # five polls of a steady alarm
        p._poll()
    assert len(sink.with_prefix("ALARM")) == 1
    assert len(sink.events) == 1


def test_alarm_present_on_the_very_first_poll_is_announced(panel):
    """Opening the app into an already-hot box must not adopt the alarm
    silently: the baseline is OK, so the first poll is an escalation."""
    p, mgr, sink = panel
    mgr.set("temperature_C", 33.0, AlarmStatus.ALARM_HIGH)
    p._poll()
    assert len(sink.with_prefix("ALARM")) == 1


def test_warn_then_alarm_escalation_renotifies_then_stays_quiet(panel):
    """WARN -> ALARM is an escalation: it must re-notify (ALARM outranks WARN).
    A steady ALARM afterwards must not."""
    p, mgr, sink = panel
    mgr.set("temperature_C", 26.0, AlarmStatus.WARN_HIGH)
    p._poll()
    assert len(sink.with_prefix("WARN")) == 1

    mgr.set("temperature_C", 31.0, AlarmStatus.ALARM_HIGH)
    p._poll()
    assert len(sink.with_prefix("ALARM")) == 1

    for _ in range(4):                      # steady alarm — silence
        p._poll()
    assert len(sink.events) == 2
    assert sink.events[-1][1] == "error"    # ALARM rides the error level


def test_escalation_is_never_delayed(panel):
    """The anti-flap hold applies ONLY to improvements. A hazard is announced
    on the first poll that sees it."""
    p, mgr, sink = panel
    mgr.set("temperature_C", 22.0, AlarmStatus.OK)
    p._poll()
    assert sink.events == []
    mgr.set("temperature_C", 31.0, AlarmStatus.ALARM_HIGH)
    p._poll()
    assert len(sink.with_prefix("ALARM")) == 1


def test_alarm_easing_to_warn_is_reported_not_swallowed(panel):
    """ALARM -> WARN is an improvement, but it is still a CHANGE the operator
    must hear about."""
    p, mgr, sink = panel
    mgr.set("temperature_C", 31.0, AlarmStatus.ALARM_HIGH)
    p._poll()
    mgr.set("temperature_C", 26.0, AlarmStatus.WARN_HIGH)
    for _ in range(mp._CLEAR_HOLD_POLLS):   # improvement must hold
        p._poll()
    warns = sink.with_prefix("WARN")
    assert len(warns) == 1
    assert "eased from ALARM" in warns[0]
    assert sink.events[-1][1] == "warn"


def test_clearing_back_to_ok_notifies_once(panel):
    p, mgr, sink = panel
    mgr.set("temperature_C", 31.0, AlarmStatus.ALARM_HIGH)
    p._poll()
    mgr.set("temperature_C", 22.0, AlarmStatus.OK)
    for _ in range(6):                      # sustained recovery
        p._poll()
    oks = sink.with_prefix("OK")
    assert len(oks) == 1
    assert "cleared" in oks[0]
    assert sink.events[-1][1] == "info"


def test_dithering_across_the_limit_does_not_storm(panel):
    """The dominant storm mode: a noisy value sitting exactly ON its limit.
    Without the improvement-hold this alternates ALARM/cleared forever."""
    p, mgr, sink = panel
    mgr.set("temperature_C", 30.1, AlarmStatus.ALARM_HIGH)
    p._poll()
    for _ in range(5):                      # 29.9 / 30.1 / 29.9 / ...
        mgr.set("temperature_C", 29.9, AlarmStatus.OK)
        p._poll()
        mgr.set("temperature_C", 30.1, AlarmStatus.ALARM_HIGH)
        p._poll()
    assert len(sink.events) == 1            # the original ALARM, nothing else


def test_same_class_transition_is_not_news(panel):
    """WARN_LOW -> WARN_HIGH stays inside the WARN class: no re-notify."""
    p, mgr, sink = panel
    mgr.set("temperature_C", 14.0, AlarmStatus.WARN_LOW)
    p._poll()
    mgr.set("temperature_C", 26.0, AlarmStatus.WARN_HIGH)
    p._poll()
    assert len(sink.events) == 1


# --------------------------------------------------------------------------- #
# The message must be actionable                                              #
# --------------------------------------------------------------------------- #

def test_message_names_the_channel_the_value_and_the_limit(panel):
    """"Slow-control alarm" is useless. The operator needs the channel, the
    reading and the limit it crossed."""
    p, mgr, sink = panel
    mgr.set("temperature_C", 31.4, AlarmStatus.ALARM_HIGH)
    p._poll()
    text = sink.with_prefix("ALARM")[0]
    assert "Temperature" in text            # channel (friendly name)
    assert "31.4" in text                   # offending value
    assert "°C" in text                     # unit
    assert "30" in text                     # the limit it crossed
    assert "above" in text                  # which way it crossed


def test_low_side_alarm_names_the_low_limit(panel):
    p, mgr, sink = panel
    mgr.set("temperature_C", 8.0, AlarmStatus.ALARM_LOW)
    p._poll()
    text = sink.with_prefix("ALARM")[0]
    assert "below" in text and "10" in text


def test_state_is_carried_by_text_not_colour(panel):
    """WCAG + the FLAT glass tier: the hazard must survive with zero colour,
    zero glass, zero blur -- a frostless RDP session still reads the word.
    Levels are a redundant channel, never the only one."""
    p, mgr, sink = panel
    mgr.set("temperature_C", 31.0, AlarmStatus.ALARM_HIGH)
    p._poll()
    mgr.set("humidity_pct", 55.0, AlarmStatus.WARN_HIGH)
    p._poll()
    words = [t.split(" ")[0] for t in sink.texts]
    assert words == ["ALARM", "WARN"]       # the state word leads every message
    assert [lvl for _, lvl in sink.events] == ["error", "warn"]


def test_sensor_dropout_is_announced_and_restoration_too(panel):
    """UNAVAILABLE is its own state (law 7): a sensor that stopped answering
    during a manual HV ramp is not 'fine'."""
    p, mgr, sink = panel
    mgr.set("temperature_C", 22.0, AlarmStatus.OK)
    p._poll()
    mgr.set("temperature_C", float("nan"), AlarmStatus.UNAVAILABLE)
    p._poll()
    assert len(sink.with_prefix("SENSOR LOST")) == 1

    mgr.set("temperature_C", 22.5, AlarmStatus.OK)
    for _ in range(mp._CLEAR_HOLD_POLLS):
        p._poll()
    restored = sink.with_prefix("OK")
    assert len(restored) == 1
    assert "restored" in restored[0]


# --------------------------------------------------------------------------- #
# Sticky app-wide headline (status_bus.set_alarm)                             #
# --------------------------------------------------------------------------- #

def _record_headlines() -> tuple[list[tuple[str, str]], callable]:
    seen: list[tuple[str, str]] = []
    slot = lambda text, level: seen.append((text, level))  # noqa: E731
    STATUS.alarm.connect(slot)
    return seen, slot


def test_sticky_headline_is_emitted_once_and_cleared_once(panel):
    """The persistent indicator's state channel: emitted on CHANGE only, and
    carrying no live value (a steady alarm whose number drifts must not
    re-emit)."""
    p, mgr, _sink = panel
    seen, slot = _record_headlines()
    try:
        for value in (31.0, 31.2, 31.4):        # steady alarm, drifting number
            mgr.set("temperature_C", value, AlarmStatus.ALARM_HIGH)
            p._poll()
        assert seen == [("ALARM · Temperature", "error")]

        mgr.set("temperature_C", 22.0, AlarmStatus.OK)
        for _ in range(3):
            p._poll()
        assert seen[-1] == ("", "")             # all clear, exactly once
        assert len(seen) == 2
    finally:
        STATUS.alarm.disconnect(slot)


def test_headline_reports_the_worst_state_and_counts_the_rest(panel):
    p, mgr, _sink = panel
    seen, slot = _record_headlines()
    try:
        mgr.set("temperature_C", 31.0, AlarmStatus.ALARM_HIGH)
        mgr.set("humidity_pct", 65.0, AlarmStatus.ALARM_HIGH)
        p._poll()
        text, level = seen[-1]
        assert text.startswith("ALARM")
        assert "+1 more" in text                # both channels are in alarm
        assert level == "error"
    finally:
        STATUS.alarm.disconnect(slot)


def test_alarm_outranks_warn_in_the_headline(panel):
    p, mgr, _sink = panel
    seen, slot = _record_headlines()
    try:
        mgr.set("temperature_C", 31.0, AlarmStatus.ALARM_HIGH)
        mgr.set("humidity_pct", 55.0, AlarmStatus.WARN_HIGH)
        p._poll()
        assert seen[-1] == ("ALARM · Temperature", "error")
    finally:
        STATUS.alarm.disconnect(slot)


# --------------------------------------------------------------------------- #
# Fail safe: the Monitor tab keeps working without a notification sink        #
# --------------------------------------------------------------------------- #

def test_broken_notification_sink_never_breaks_the_poll_loop(monkeypatch):
    """If the status bus is unavailable/raises, the Monitor tab must still work
    exactly as it does today: the table, tiles and banner keep updating."""
    _app()

    def _boom(*_a, **_k):
        raise RuntimeError("status bus is down")

    monkeypatch.setattr(mp, "notify", _boom)
    monkeypatch.setattr(mp, "set_alarm", _boom)
    mgr = _FakeManager()
    p = MonitorPanel(mgr, poll_interval_s=1.0)

    mgr.set("temperature_C", 31.4, AlarmStatus.ALARM_HIGH)
    p._poll()                                   # must not raise
    assert p._table.item(0, 1).text() == "31.4"          # table still updated
    assert p._chip_alarm.property("state") == "crit"     # banner still escalates
    assert p._tile_channel["temperature_C"].state() == "crit"

    mgr.set("temperature_C", 22.0, AlarmStatus.OK)
    for _ in range(3):
        p._poll()                               # loop survives, keeps polling
    assert p._table.item(0, 1).text() == "22"
    assert p._chip_alarm.text() == "All nominal"


def test_influx_write_still_runs_when_the_announcer_is_broken(monkeypatch):
    """The announcer sits between the banner and the Influx write — a failure
    there must not silently drop slow-control data."""
    _app()
    monkeypatch.setattr(mp, "notify", lambda *_a, **_k: 1 / 0)
    written: list[dict] = []
    mgr = _FakeManager()
    influx = type("_Influx", (), {"write_readings": lambda _s, r: written.append(r)})()
    p = MonitorPanel(mgr, poll_interval_s=1.0, influx_writer=influx)

    mgr.set("temperature_C", 31.4, AlarmStatus.ALARM_HIGH)
    p._poll()
    assert len(written) == 1


# --------------------------------------------------------------------------- #
# Construction + theme-switch smoke                                           #
# --------------------------------------------------------------------------- #

def test_theme_switch_smoke_with_an_active_alarm(panel):
    app = _app()
    p, mgr, _sink = panel
    mgr.set("temperature_C", 31.4, AlarmStatus.ALARM_HIGH)
    apply_theme(app, "light")
    p.refresh_theme("light")
    p._poll()
    assert not p.grab().isNull()
    apply_theme(app, "dark")
    p.refresh_theme("dark")
    p._poll()
    assert not p.grab().isNull()
    apply_theme(app, "light")
