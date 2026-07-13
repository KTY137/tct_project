"""gui/bias_panel.py's Voltage · measured hero tile — roll_number wiring
(fluent-motion beat, Task 2 consumer #2). Display only: no device/logic
change — set_reading()'s HV-state derivation, kill switch and danger well
are untouched and get NO animation (ratified law). Headless construction +
a light/dark theme-switch smoke test (required for every panel change),
plus a check that set_reading() drives gui.motion_kit.roll_number on the
tile's value QLabel and always lands exactly on the formatted reading.

Attribute-only fake supply / reading idiom matches
tests/test_bias_kill_switch_escalation.py / tests/test_bias_trip_visibility.py
(no event-loop pump needed — set_reading() is driven synchronously).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import gui.bias_panel as bias_panel_module
import gui.motion_kit as mk
from gui.bias_panel import BiasPanel
from gui.style import apply_theme


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _dispose(panel) -> None:
    shutdown = getattr(panel, "shutdown", None)
    if shutdown is not None:
        shutdown()
    panel.deleteLater()


@dataclass
class _Reading:
    voltage_V: float
    current_A: float
    compliant: bool
    tripped: bool = False


class _FakeSupply:
    def __init__(self, connected: bool = False) -> None:
        self.connected = connected
        self.setpoint_V = 0.0
        self.compliance_A = 100e-6
        self.voltage_range_V = 1000.0
        self.channel = 0


def test_bias_panel_constructs_headless():
    _app()
    panel = BiasPanel(_FakeSupply())
    try:
        assert panel._tile_v.value() == "—"
    finally:
        _dispose(panel)


def test_theme_switch_smoke_both_themes():
    app = _app()
    apply_theme(app, "light")
    panel = BiasPanel(_FakeSupply())
    try:
        apply_theme(app, "dark")
        panel.refresh_theme("dark")
        assert not panel.grab().isNull()
        apply_theme(app, "light")
        panel.refresh_theme("light")
        assert not panel.grab().isNull()
    finally:
        _dispose(panel)


def test_set_reading_drives_roll_number_and_lands_on_formatted_value(monkeypatch):
    _app()
    calls = []
    real_roll_number = bias_panel_module.roll_number

    def spy(label, old, new, fmt, **kwargs):
        calls.append((label, old, new, fmt))
        return real_roll_number(label, old, new, fmt, **kwargs)

    monkeypatch.setattr(bias_panel_module, "roll_number", spy)

    panel = BiasPanel(_FakeSupply(connected=True))
    try:
        panel.set_reading(_Reading(-150.236, 5e-6, False))

        assert len(calls) == 1
        label, old, new, fmt = calls[0]
        assert label is panel._tile_v._value
        assert old == 0.0
        assert new == -150.236
        assert fmt == "{:+.2f} V"

        anim = getattr(panel._tile_v._value, mk._ROLL_ATTR)
        anim.setCurrentTime(anim.duration())
        assert panel._tile_v._value.text() == "-150.24 V"
        assert panel._tile_v.value() == "-150.24 V"  # tooltip/_value_full agree

        # A second reading rolls from the FIRST reading, not from zero again.
        panel.set_reading(_Reading(-149.9, 5e-6, False))
        _, old2, new2, _ = calls[1]
        assert old2 == -150.236
        assert new2 == -149.9
    finally:
        _dispose(panel)


def test_set_reading_motion_off_jumps_directly(monkeypatch):
    """Kill switch off: the tile still lands on the correct value, with no
    animation machinery left behind."""
    _app()
    monkeypatch.setattr("gui.motion_kit.motion_enabled", lambda: False)
    panel = BiasPanel(_FakeSupply(connected=True))
    try:
        panel.set_reading(_Reading(220.5, 1e-6, False))
        assert panel._tile_v._value.text() == "+220.50 V"
        assert getattr(panel._tile_v._value, mk._ROLL_ATTR, None) is None
    finally:
        _dispose(panel)


def test_danger_well_and_kill_switch_get_no_animation():
    """Ratified law: only the Voltage · measured readout animates. The
    kill switch (Output OFF) and the HV/current tiles are untouched by
    this beat — no roll/pulse attribute ever appears on them."""
    _app()
    panel = BiasPanel(_FakeSupply(connected=True))
    try:
        panel.set_reading(_Reading(-300.0, 5e-6, False))
        assert getattr(panel._btn_off, mk._PULSE_ATTR, None) is None
        assert panel._btn_off.graphicsEffect() is None
        assert getattr(panel._tile_hv._value, mk._ROLL_ATTR, None) is None
        assert getattr(panel._tile_i._value, mk._ROLL_ATTR, None) is None
    finally:
        _dispose(panel)
