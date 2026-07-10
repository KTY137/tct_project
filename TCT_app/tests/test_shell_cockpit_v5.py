"""Headless checks for the cockpit v5 shell/ribbon polish."""
from __future__ import annotations

import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QLabel

from controller.state_machine import AppState
from gui.detachable_tabs import DetachableTabWidget


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump(ms: int = 60) -> None:
    app = _app()
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)


def _make_window(monkeypatch):
    from tct_gui import TCTMainWindow

    # Keep persisted user window state / detached tabs out of this headless
    # construction test; the detach contract is tested separately below.
    monkeypatch.setattr(TCTMainWindow, "_restore_window_state", lambda self: None)
    win = TCTMainWindow(config_path="configs/devices.yaml")
    _pump()
    return win


def _destroy_window(win) -> None:
    try:
        win._teardown_panels()
    finally:
        win.hide()
        win.deleteLater()
        _pump()


def test_system_ribbon_constructs_grouped_cached_status(monkeypatch):
    app = _app()
    win = _make_window(monkeypatch)
    try:
        ribbon = win.findChild(QFrame, "systemRibbon")
        assert ribbon is not None
        assert win.findChild(QLabel, "ribbonWordmark").text() == "TCT Control"
        assert len(ribbon.findChildren(QFrame, "ribbonGroup")) >= 5
        assert win._chip_bias_v.text().startswith("HV")
        assert win._chip_motion.text().startswith("Motion")
        assert win._chip_scan.text().startswith("Scan")
        assert win._chip_laser.text().startswith("Laser")
        assert win._ring_scan.objectName() == "activityRing"
        assert not win._ring_scan.is_active()
    finally:
        _destroy_window(win)
        app.processEvents()


def test_cached_bias_laser_and_scan_state_drive_ribbon(monkeypatch):
    win = _make_window(monkeypatch)
    try:
        reading = SimpleNamespace(voltage_V=-120.0, current_A=4.2e-7, compliant=False)
        win._refresh_bias_strip(reading)
        assert "HV -120.0 V" == win._chip_bias_v.text()
        assert win._chip_bias_v.property("motionPulse") == "hv"

        win._refresh_bias_strip(None)
        assert win._chip_bias_v.text() == "HV --"
        assert win._chip_bias_v.property("motionPulse") == ""

        wfg = win._devices.waveform_generator
        wfg.simulation = True
        wfg._output_on = True
        win._refresh_laser_strip()
        assert win._chip_laser.text() == "Laser ON"
        assert win._chip_laser.property("motionPulse") == "laser"

        wfg._output_on = False
        win._refresh_laser_strip()
        assert win._chip_laser.text() == "Laser off"
        assert win._chip_laser.property("motionPulse") == ""

        win._on_state_change(AppState.READY, AppState.RUNNING)
        assert win._ring_scan.is_active()
        assert win._chip_scan.property("motionPulse") == "scan"

        win._on_state_change(AppState.RUNNING, AppState.FINISHED)
        assert not win._ring_scan.is_active()
        assert win._chip_scan.property("motionPulse") == ""
    finally:
        _destroy_window(win)


def test_detach_button_polished_and_redock_contract_survives():
    app = _app()
    tabs = DetachableTabWidget()
    page = QLabel("viewer")
    tabs.addTab(page, "Scan Viewer")

    btn = tabs.cornerWidget()
    assert btn.objectName() == "detachTabButton"
    assert btn.toolTip()

    tabs.detach(0)
    assert "Scan Viewer" in tabs.detached_titles()
    win, content, _idx = tabs._detached["Scan Viewer"]
    assert content is page

    win.close()
    _pump()
    assert tabs.count() == 1
    assert tabs.tabText(0) == "Scan Viewer"
    assert tabs.widget(0) is page

    tabs.deleteLater()
    app.processEvents()
