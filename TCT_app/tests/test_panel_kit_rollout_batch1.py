"""Headless construct/grab checks for the panel_kit rollout — Batch 1
(the five LOW-RISK mechanical panels: motor, bias, multi-bias, intensity,
monitor, device manager).

Follows the existing gui test idiom (see ``test_status_widgets.py`` /
``test_planner_panel.py``): ``QT_QPA_PLATFORM=offscreen``, a shared
``QApplication.instance()`` helper, no pytest-qt.

Each batch-1 widget is constructed and rendered (``.grab()``) under BOTH
themes (light/dark) to confirm the Card presentation and the new
panel_header()s don't crash construction or leave a blank/zero-size widget
in either theme. Two panels outside this batch's scope (camera, settings)
are also constructed to confirm the batch-1 design-system swap has no bleed
into other panel surfaces.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFrame, QPushButton

from controller.device_manager import DeviceManager
from controller.slow_control_manager import SlowControlManager
from devices.bias_channel import BiasChannel
from devices.bias_supply_simulated import SimulatedBiasSupply
from devices.camera_blackfly import BlackflyCamera
from devices.intensity_simulated import SimulatedIntensityMonitor
from devices.motor_simulated import SimulatedMotorStage
from devices.slow_control_simulated import SimulatedSlowChannel
from gui.bias_panel import BiasPanel
from gui.camera_panel import CameraPanel
from gui.device_panel import DeviceManagerWindow
from gui.intensity_panel import IntensityPanel
from gui.monitor_panel import MonitorPanel
from gui.motor_panel import MotorPanel
from gui.multi_bias_panel import MultiBiasPanel
from gui.settings_window import SettingsWindow
from gui.style import apply_theme


@pytest.fixture(autouse=True)
def _stub_visa_scan(monkeypatch):
    """test_settings_window_constructs_without_batch1_bleed() below builds a real
    ``SettingsWindow``, whose ``_VisaScanManager`` fires a real
    ``list_visa_resources()`` VISA bus enumeration off-thread unless stubbed
    — real hardware I/O during a test run, and (per the 2026-07-08 pyvisa
    access-violation diagnosis) part of the concurrent-first-import AV
    trigger. Mirrors the existing stub in test_settings_window_visa_scan.py."""
    monkeypatch.setattr("devices.waveform_generator.list_visa_resources", lambda: [])


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _grab_both_themes(make_panel, *, has_refresh: bool = True) -> None:
    """Build *make_panel()*, render it under light then dark, call
    ``refresh_theme`` if present, and confirm the pixmap is non-empty both
    times. Always tears the panel down via ``shutdown()`` when available."""
    app = _app()
    apply_theme(app, "light")
    panel = make_panel()
    try:
        pm_light = panel.grab()
        assert not pm_light.isNull()
        assert pm_light.width() > 0 and pm_light.height() > 0

        apply_theme(app, "dark")
        if has_refresh and hasattr(panel, "refresh_theme"):
            panel.refresh_theme("dark")
        pm_dark = panel.grab()
        assert not pm_dark.isNull()
        assert pm_dark.width() > 0 and pm_dark.height() > 0

        if has_refresh and hasattr(panel, "refresh_theme"):
            panel.refresh_theme("light")
        apply_theme(app, "light")
    finally:
        shutdown = getattr(panel, "shutdown", None)
        if shutdown is not None:
            shutdown()


# --------------------------------------------------------------------------- #
# Touched panels — both themes                                                #
# --------------------------------------------------------------------------- #

def test_motor_panel_constructs_both_themes():
    _grab_both_themes(lambda: MotorPanel(SimulatedMotorStage()))


def test_bias_panel_constructs_both_themes():
    _grab_both_themes(lambda: BiasPanel(SimulatedBiasSupply()))


def test_multi_bias_panel_constructs_both_themes():
    def _make():
        drv = SimulatedBiasSupply(channel_count=2, voltage_range_V=1000.0)
        drv.connect()
        return MultiBiasPanel([BiasChannel(drv, 0), BiasChannel(drv, 1)])
    _grab_both_themes(_make)


def test_intensity_panel_constructs_both_themes():
    _grab_both_themes(lambda: IntensityPanel(SimulatedIntensityMonitor()))


def test_monitor_panel_constructs_both_themes():
    def _make():
        mgr = SlowControlManager([SimulatedSlowChannel("Temp", "C")])
        return MonitorPanel(mgr)
    _grab_both_themes(_make)


def test_device_manager_window_constructs_both_themes():
    _grab_both_themes(lambda: DeviceManagerWindow(DeviceManager()))


# --------------------------------------------------------------------------- #
# Behavioural spot-checks: presentation swap kept every existing hook alive   #
# --------------------------------------------------------------------------- #

def test_motor_panel_hooks_survive_card_swap():
    _app()
    panel = MotorPanel(SimulatedMotorStage())
    try:
        # jogBtn / dangerBtn / segmented / instrumentReadout / controlCluster
        # objectNames all still resolve after the QGroupBox -> Card swap
        # (Card only wraps the section; it does not touch these inner hooks).
        assert panel.findChild(QFrame, "instrumentReadout") is not None
        assert panel.findChild(QFrame, "controlCluster") is not None
        assert panel.findChild(QFrame, "segmented") is not None
        jog_btns = [b for b in panel.findChildren(QPushButton)
                    if b.objectName() == "jogBtn"]
        assert len(jog_btns) == 6   # X+/X-/Y+/Y-/Z+/Z-
        stop_btns = [b for b in panel.findChildren(QPushButton)
                     if b.objectName() == "dangerBtn"]
        assert len(stop_btns) == 1 and stop_btns[0].text() == "STOP"
        # New Card sections carry the design-system surface objectName.
        assert len(panel.findChildren(QFrame, "cardPane")) >= 5
    finally:
        panel.shutdown()


def test_bias_panel_danger_and_rail_hooks_present():
    _app()
    panel = BiasPanel(SimulatedBiasSupply())
    try:
        # Kill-switch escalation ruling (council_v5_paul.md §2): Output OFF
        # is no longer the ALWAYS-red "dangerBtn" -- its own "killSwitchBtn"
        # identity stays denied by the monkey harness's object-substring
        # layer, but its CHROME escalates with real HV energy (see
        # test_bias_kill_switch_escalation.py). A never-connected supply
        # starts "ghost" (nothing to kill).
        assert panel._btn_off.objectName() == "killSwitchBtn"
        assert panel._btn_off.property("state") == "ghost"
        assert panel._btn_polarity.objectName() == "dangerBtn"
        # The amber rail now lives on the Card via set_rail()'s railAxis
        # property instead of the old "#biasRail" objectName.
        assert panel._volt_box.property("railAxis") == "bias"
        assert "bias" in panel._volt_box.styleSheet() or \
            panel._volt_box.property("railAxis") == "bias"
    finally:
        panel.shutdown()


def test_multi_bias_panel_all_off_button_still_dangerous():
    drv = SimulatedBiasSupply(channel_count=1, voltage_range_V=1000.0)
    drv.connect()
    panel = MultiBiasPanel([BiasChannel(drv, 0)])
    try:
        # Kill-switch escalation ruling (council_v5_paul.md §2): still its
        # OWN distinct identity (denied by the monkey's object-substring
        # layer), but no longer standing red chrome -- see
        # test_bias_kill_switch_escalation.py for the full ghost/neutral/
        # danger lifecycle.
        assert panel._btn_all_off.objectName() == "killSwitchBtn"
        assert panel._btn_all_off.text() == "⏹ ALL OUTPUTS OFF"
    finally:
        panel.shutdown()


# --------------------------------------------------------------------------- #
# Cross-batch bleed checks — construct only, to prove no bleed from batch 1   #
# --------------------------------------------------------------------------- #

def test_camera_panel_constructs_without_batch1_bleed():
    _app()
    panel = CameraPanel(BlackflyCamera(simulation=True))
    try:
        pm = panel.grab()
        assert not pm.isNull()
    finally:
        panel.shutdown()   # stops the frame-acquisition worker thread


def test_settings_window_constructs_without_batch1_bleed():
    _app()
    win = SettingsWindow()
    try:
        pm = win.grab()
        assert not pm.isNull()
    finally:
        # Orphaning this window to GC leaves its _VisaScanManager scan
        # QThread still running when the C++ object gets collected — a
        # still-running QThread destroyed that way is a hard Qt6 abort, not
        # a catchable Python exception. close() runs closeEvent's shutdown.
        win.close()
