"""Headless smoke + honesty checks for the cockpit-v5 BATCH B migration
(bias/multi-bias, camera, laser, motor, scope — docs/design/
cockpit_design_system.md §6-7).

Follows the existing gui test idiom (``test_panel_kit_rollout_batch1.py``):
``QT_QPA_PLATFORM=offscreen``, a shared ``QApplication.instance()`` helper,
no pytest-qt, simulated backends only.  Covers the batch's design contract:

* Bias hero trio (Voltage·measured / Current / HV STATE) with honestly
  derived + captioned states (law 7), compliance trip = crit alarm.
* Standalone sweeps folded into ONE collapsed advanced card — reachable.
* Camera Live/Single/Stop drive the EXISTING worker poll; designed empty
  states; stream still auto-starts (worker-test contract unchanged).
* Laser: amber manual-laser banner, no software emission switch, wavegen
  stays the controllable hero, PDL 800 metadata demoted/collapsed.
* Motor: Move-absolute is motion/amber class (law 2), limit-SWITCH honesty
  chip, STOP untouched.
* Scope: 4 headline MetricTiles, one segmented Live/Single command bar,
  measurements collapsed by default, truthful poll/config chips.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from devices.bias_channel import BiasChannel
from devices.bias_supply_simulated import SimulatedBiasSupply
from devices.camera_blackfly import BlackflyCamera
from devices.laser_manual import LaserManualMetadata
from devices.motor_simulated import SimulatedMotorStage
from devices.oscilloscope import Oscilloscope
from devices.waveform_generator import WaveformGenerator
from gui.bias_panel import BiasPanel
from gui.camera_panel import CameraPanel
from gui.laser_panel import LaserPanel
from gui.motor_panel import MotorPanel
from gui.multi_bias_panel import MultiBiasPanel
from gui.scope_panel import ScopePanel
from gui.style import palette


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump(app: QApplication, seconds: float = 0.2) -> None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        app.processEvents()
        time.sleep(0.01)


def _pump_until(app: QApplication, cond, timeout: float = 5.0) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if cond():
            return True
        app.processEvents()
        time.sleep(0.02)
    return cond()


def _dispose(panel) -> None:
    """Tear a panel down through Qt's ORDERLY deferred-delete path instead
    of leaving it to Python gc: a pyqtgraph-bearing widget destroyed inside
    ``gc.collect()`` (arbitrary destruction order) is a known access-
    violation source in this suite; ``deleteLater`` + a pump destroys the
    C++ tree top-down while everything is still alive."""
    app = _app()
    shutdown = getattr(panel, "shutdown", None)
    if shutdown is not None:
        shutdown()
    panel.deleteLater()
    _pump(app, 0.1)


@dataclass
class _Reading:
    voltage_V: float
    current_A: float
    compliant: bool


class _FakeSupply:
    """Attribute-only stand-in — ``connected = False`` keeps the panel's
    readout poller idle, so ``set_reading`` can be driven synchronously."""
    connected = False
    setpoint_V = -300.0
    compliance_A = 100e-6
    voltage_range_V = 1000.0
    channel = 0


# --------------------------------------------------------------------------- #
# Bias — safety dashboard                                                      #
# --------------------------------------------------------------------------- #

def test_bias_hero_tiles_stale_until_reading_then_derive_states():
    _app()
    panel = BiasPanel(_FakeSupply())
    try:
        # Law 4: nothing to say yet → stale with a caption, never a bare dash.
        assert panel._tile_v.is_stale()
        assert panel._tile_hv.is_stale()

        # SETTLED (inferred): measured ≈ setpoint, no command in flight.
        panel.set_reading(_Reading(-299.0, 5e-6, False))
        assert panel._tile_hv.value() == "SETTLED"
        assert "inferred" in panel._tile_hv._caption.text()
        # Polarity sign comes from the readback; setpoint sits in the caption.
        assert panel._tile_v.value() == "-299.00 V"
        assert "setpoint -300.0 V" in panel._tile_v._caption.text()
        # Compliance headroom in the Current caption (5 µA of 100 µA).
        assert "5% of 100 µA compliance" in panel._tile_i._caption.text()

        # RAMPING while a ramp command is in flight (armed, law 2's amber).
        panel._hv_ramping = True
        panel.set_reading(_Reading(-100.0, 5e-6, False))
        assert panel._tile_hv.value().startswith("RAMPING")
        assert panel._tile_hv.state() == "armed"
        panel._hv_ramping = False

        # TRIPPED is a real crit alarm state (not "LIMIT OK" prose).
        panel.set_reading(_Reading(-250.0, 100e-6, True))
        assert panel._tile_hv.value() == "TRIPPED"
        assert panel._tile_hv.state() == "crit"
        assert panel._tile_i.state() == "crit"

        # OFF (inferred) when both measured and setpoint sit at ~0.
        panel._supply.setpoint_V = 0.0
        panel.set_reading(_Reading(0.0, 0.0, False))
        assert panel._tile_hv.value() == "OFF"
        assert "not readable" in panel._tile_hv._caption.text()

        # LIVE? guard: measured HV with no commanded setpoint must warn.
        panel.set_reading(_Reading(-80.0, 1e-6, False))
        assert panel._tile_hv.value() == "LIVE?"
        assert panel._tile_hv.state() == "warn"

        # Disconnect blanks back to stale-with-caption.
        panel.set_reading(None)
        assert panel._tile_hv.is_stale()
    finally:
        _dispose(panel)


def test_bias_unknown_output_state_is_not_red_but_trip_stays_crit():
    """Council v5 ladder (docs/design/council_v5_paul.md §1): the supply has NO
    output-on/ramp-state readback, so OFF/SETTLED are INFERRED (their caption
    says "not readable") — i.e. the true output-on fact is UNKNOWN.  Unknown is
    not a fault: those states must never borrow the crit/red class.  Red stays
    reserved for a genuine TRIPPED/compliance fault — this guardrail must not
    be softened while fixing the off/absent/unknown red-misuses."""
    _app()
    panel = BiasPanel(_FakeSupply())
    try:
        # Inferred OFF while the real output-on state is unknown → neutral,
        # never red.
        panel._supply.setpoint_V = 0.0
        panel.set_reading(_Reading(0.0, 0.0, False))
        assert panel._tile_hv.value() == "OFF"
        assert "not readable" in panel._tile_hv._caption.text()
        assert panel._tile_hv.state() != "crit"
        # A real compliance trip DOES stay crit — the loud fault is preserved.
        panel._supply.setpoint_V = -250.0
        panel.set_reading(_Reading(-250.0, 100e-6, True))
        assert panel._tile_hv.value() == "TRIPPED"
        assert panel._tile_hv.state() == "crit"
    finally:
        _dispose(panel)


def test_bias_sweeps_fold_into_one_collapsed_advanced_card():
    _app()
    panel = BiasPanel(SimulatedBiasSupply())
    try:
        card = panel._sweeps_card
        assert not card.is_checked()
        body = card.body.parentWidget()
        assert body.isHidden()
        # Everything stays reachable: expanding exposes both sweep starters
        # and lazily builds the two plots (never constructed while hidden —
        # a hidden, never-polished PlotWidget is a Windows teardown AV).
        assert panel._iv_plot is None and panel._vscan_plot is None
        card.set_checked(True)
        assert not body.isHidden()
        assert panel._btn_iv.text() == "▶ Run IV scan"
        assert panel._btn_vscan.text() == "▶ Start bias + waveform scan"
        from gui.bias_panel import _HAS_PG
        if _HAS_PG:
            assert panel._iv_plot is not None and panel._vscan_plot is not None
    finally:
        _dispose(panel)


def test_multi_bias_quiet_nominal_and_honest_tab_labels():
    _app()
    drv = SimulatedBiasSupply(channel_count=2, voltage_range_V=1000.0)
    drv.connect()
    panel = MultiBiasPanel([BiasChannel(drv, 0), BiasChannel(drv, 1)])
    try:
        # All-connected is routine — grey, not a persistent green light.
        assert panel._chip_channels.property("state") == "neutral"
        # "connected", never "LIVE": link-up is not an energized output.
        assert panel._tabs.tabText(0) == "CH0 · connected"
        # The loudest red stays exactly as it was.
        assert panel._btn_all_off.objectName() == "dangerBtn"
        assert panel._btn_all_off.text() == "⏹ ALL OUTPUTS OFF"
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# Camera — Live/Single/Stop over the existing worker poll                      #
# --------------------------------------------------------------------------- #

def test_camera_action_bar_drives_existing_stream():
    _app()
    panel = CameraPanel(BlackflyCamera(simulation=True))
    try:
        # Streaming still auto-starts (worker-test contract unchanged) and
        # the not-connected surface shows on the view stack.
        assert panel._btn_live.isChecked()
        assert panel._view_stack.currentWidget() is panel._empty_offline
        # Council v5 state ladder (docs/design/council_v5_paul.md §1): a
        # disconnected camera is an ABSENCE, not an alarm — the offline surface
        # must NOT use the crit "error" variant (which paints the title/icon
        # red). Red is reserved for HV-live / trip / abort; "off" is not danger.
        assert panel._empty_offline._variant == "default"
        # Stop and Single both disarm the live toggle (single = one grab).
        panel._btn_stop.click()
        assert not panel._btn_live.isChecked()
        panel._btn_live.setChecked(True)
        panel._btn_single.click()
        assert not panel._btn_live.isChecked()
    finally:
        _dispose(panel)


def test_camera_first_frame_switches_to_image_and_wakes_tiles():
    app = _app()
    cam = BlackflyCamera(simulation=True)
    cam.connect()
    panel = CameraPanel(cam)
    try:
        assert all(t.is_stale() for t in panel._stats_tiles)
        assert _pump_until(app, lambda: panel._last_frame is not None), \
            "worker never delivered a simulated frame"
        assert panel._view_stack.currentWidget() is panel._img_label
        assert not any(t.is_stale() for t in panel._stats_tiles)
        # px units live on the beam-stat values themselves.
        assert panel._ro_cx.value().endswith(" px")
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# Laser — law 7 banner; wavegen hero; PDL 800 demoted                          #
# --------------------------------------------------------------------------- #

def test_laser_manual_banner_no_emission_switch_pdl_collapsed():
    app = _app()
    panel = LaserPanel(LaserManualMetadata(), WaveformGenerator(simulation=True))
    try:
        assert "not PC-controllable" in panel._lbl_banner.text()
        assert "Verify at the head" in panel._lbl_banner.text()
        # The manual-laser card carries NO software emission control — its
        # only button is the metadata save.
        pdl_buttons = [b.text() for b in panel._card_pdl.findChildren(QPushButton)]
        assert pdl_buttons == ["Save to metadata"]
        # Demoted: collapsed by default, expandable (reachable).
        assert not panel._card_pdl.is_checked()
        assert panel._card_pdl.body.parentWidget().isHidden()
        panel._card_pdl.set_checked(True)
        assert not panel._card_pdl.body.parentWidget().isHidden()
        # The WAVEGEN keeps its real on/off — that device IS controllable.
        assert panel._btn_on.text() == "Output on"
        assert panel._btn_off.text() == "Output off"
        # Banner ink resolves from the warn token in both themes.
        panel.refresh_theme("dark")
        assert palette("dark")["warn"] in panel._lbl_banner.styleSheet()
        panel.refresh_theme("light")
        assert palette("light")["warn"] in panel._lbl_banner.styleSheet()
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# Motor — motion command class, limit-switch honesty, STOP untouched           #
# --------------------------------------------------------------------------- #

def test_motor_move_absolute_motion_class_and_switch_honesty():
    app = _app()
    panel = MotorPanel(SimulatedMotorStage())
    try:
        moves = [b for b in panel.findChildren(QPushButton) if b.text() == "Move to"]
        assert len(moves) == 1
        assert moves[0].property("state") == "motion"   # law 2: amber, not red
        # Council v5 ladder: red is reserved for faults/HV/abort — a MOVE STAGE
        # (motion) command must never borrow the danger/crit class.
        assert moves[0].property("state") not in ("danger", "crit")
        assert panel._chip_switches.text() == "Switches unknown"
        assert panel._chip_switches.property("state") == "unknown"
        # STOP: still the single danger control, still never busy-disabled.
        stops = [b for b in panel.findChildren(QPushButton)
                 if b.objectName() == "dangerBtn"]
        assert len(stops) == 1 and stops[0].text() == "STOP"
        assert stops[0] not in panel._motion_widgets
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# Scope — 4 tiles, one seg command bar, collapsed measurements, honest chips   #
# --------------------------------------------------------------------------- #

def test_scope_tiles_seg_bar_collapsed_measurements_honest_chips():
    _app()
    panel = ScopePanel(Oscilloscope(simulation=True))
    try:
        assert [t._title_full for t in panel._stat_tiles] == [
            "AMPLITUDE", "RISE TIME", "CHARGE", "DRIFT TIME"]
        # Law 4: the empty state is explained (shared caption), never bare.
        assert all(t.value() == "—" for t in panel._stat_tiles)
        assert panel._lbl_stats_stale.isVisibleTo(panel)
        # Live + Single share ONE segmented command bar.
        assert panel._btn_live.objectName() == "segBtn"
        assert panel._btn_single.objectName() == "segBtn"
        assert panel._btn_live.parentWidget() is panel._btn_single.parentWidget()
        assert panel._btn_live.parentWidget().objectName() == "segmented"
        # Measurements table: collapsed by default, reachable on expand.
        assert not panel._meas_card.is_checked()
        assert panel._meas_card.body.parentWidget().isHidden()
        panel._meas_card.set_checked(True)
        assert not panel._meas_card.body.parentWidget().isHidden()
        # Chips claim only what the panel truthfully knows: the "live" chip
        # is OUR poll loop (no instrument acquisition-state readback yet).
        assert panel._chip_scope_live.text() == "Poll off"
        assert "not read back" in panel._chip_scope_live.toolTip()
        assert panel._chip_scope_conn.property("state") == "disconnected"
    finally:
        _dispose(panel)
