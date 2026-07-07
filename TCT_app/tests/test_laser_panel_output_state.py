"""Headless GUI regression tests for the Laser/Trigger panel (2026-07-07).

Two bench complaints, pinned here against the simulated backend:

  * the armed/output chip "was always just a flag" — it now reflects the REAL
    driver output state, so a scan arming the trigger (output_on() called
    without any panel button press) still flips the chip to ARMED, and a
    connected-but-unknown state reads "unknown" instead of a false "off";
  * settings "couldn't pass properly" — Apply on a NOT-connected wavegen must
    report "staged", not a green "configured", because the driver silently
    caches writes when there is no session.
"""
import os

import pytest


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _panel(wfg):
    from devices.laser_manual import LaserManualMetadata
    from gui.laser_panel import LaserPanel
    return LaserPanel(LaserManualMetadata(), wfg)


def test_armed_chip_tracks_driver_state_not_button(qapp) -> None:
    from devices.waveform_generator import WaveformGenerator
    wfg = WaveformGenerator(simulation=True)
    wfg.connect()
    panel = _panel(wfg)
    panel._refresh_output_chip()
    assert "off" in panel._chip_output.text().lower()

    # Simulate the SCAN THREAD arming the trigger — the panel pressed nothing.
    wfg.output_on()
    panel._refresh_output_chip()
    assert "arm" in panel._chip_output.text().lower()

    wfg.output_off()
    panel._refresh_output_chip()
    assert "off" in panel._chip_output.text().lower()


def test_armed_chip_unknown_when_connected_state_unknown(qapp) -> None:
    from devices.waveform_generator import WaveformGenerator
    wfg = WaveformGenerator(simulation=False)
    wfg._connected = True            # connected, but output_is_on is None
    panel = _panel(wfg)
    panel._refresh_output_chip()
    assert "unknown" in panel._chip_output.text().lower()


def test_armed_chip_neutral_when_not_connected(qapp) -> None:
    from devices.waveform_generator import WaveformGenerator
    wfg = WaveformGenerator(simulation=False)   # no session
    panel = _panel(wfg)
    panel._refresh_output_chip()
    # Neither a false "off" nor "armed" — just no trustworthy state.
    txt = panel._chip_output.text().lower()
    assert "arm" not in txt


def test_apply_while_disconnected_reports_staged_not_configured(qapp) -> None:
    from devices.waveform_generator import WaveformGenerator
    wfg = WaveformGenerator(simulation=False)   # not connected, no session
    panel = _panel(wfg)
    panel._spin_freq.setValue(3210.0)
    panel._spin_ampl.setValue(2.1)
    panel._apply_wfg()
    txt = panel._chip_wfg.text().lower()
    assert "stag" in txt and "configured" not in txt
    # Values are staged on the driver so a later connect applies them.
    assert wfg._frequency == 3210.0
    assert wfg._amplitude == 2.1


def test_apply_when_connected_reports_configured(qapp) -> None:
    from devices.waveform_generator import WaveformGenerator
    wfg = WaveformGenerator(simulation=True)
    wfg.connect()
    panel = _panel(wfg)
    panel._spin_freq.setValue(1500.0)
    panel._apply_wfg()
    assert "configured" in panel._chip_wfg.text().lower()
