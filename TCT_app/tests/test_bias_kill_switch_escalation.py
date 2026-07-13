"""Guard tests for the kill-switch escalation ruling (state-color census D4
rank-2 fix; ``docs/design/council_v5_paul.md`` §2 "Bias Supply"):

    "it is ALWAYS visible but escalates with real HV energy -- OFFLINE ->
    ghost outline, muted, no fill (nothing to kill); connected + output-off
    -> neutral outline (ready, inert); HV-live (ramping/settled) -> filled
    red, full salience, one-tap instant. Red arrives only with volts, never
    as chrome."

Before this fix, ``BiasPanel._btn_off`` ("Output OFF") and
``MultiBiasPanel._btn_all_off`` ("ALL OUTPUTS OFF") carried the static
``dangerBtn`` objectName -- solid red chrome unconditionally, even while
DISCONNECTED (nothing to kill). Both now carry the ``killSwitchBtn`` identity
(still denied by the monkey harness's object-substring layer, same as
"dangerBtn" before it -- see ``tests/test_ui_monkey.py``) and drive their
visual chrome purely through the dynamic ``state`` QSS property, re-derived
every time the HV tile updates (``BiasPanel._set_hv_tile`` ->
``_update_kill_switch_style`` -> ``kill_switch_state_changed`` ->
``MultiBiasPanel._update_all_off_style`` for the aggregate control).

Uses attribute-only fake supplies (same idiom as
``tests/test_cockpit_batch_b_panels.py``'s ``_FakeSupply``/``_Reading``) so
``set_reading()`` can be driven synchronously -- the readout poller stays
running in its own QThread, but this file never pumps the Qt event loop, so
its queued cross-thread ``reading`` signals are never delivered mid-test
(the same no-pump determinism every other bias_panel test in this suite
already relies on).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from devices.bias_channel import BiasChannel
from devices.bias_supply_simulated import SimulatedBiasSupply
from gui.bias_panel import BiasPanel
from gui.multi_bias_panel import MultiBiasPanel


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
    """Attribute-only stand-in with a plain, per-instance MUTABLE
    ``connected`` (unlike the real driver's read-only property) so a single
    test can drive both the OFFLINE and connected escalation branches."""

    def __init__(self, connected: bool = False) -> None:
        self.connected = connected
        self.setpoint_V = 0.0
        self.compliance_A = 100e-6
        self.voltage_range_V = 1000.0
        self.channel = 0


# --------------------------------------------------------------------------- #
# Single-channel BiasPanel — the Output OFF kill switch                        #
# --------------------------------------------------------------------------- #

def test_kill_switch_ghost_while_offline():
    """OFFLINE -> ghost outline: nothing to kill, so it must not read as an
    always-red danger control while there is not even a device to talk to."""
    _app()
    panel = BiasPanel(_FakeSupply(connected=False))
    try:
        assert panel._btn_off.objectName() == "killSwitchBtn"
        assert panel._btn_off.property("state") == "ghost"
    finally:
        _dispose(panel)


def test_kill_switch_neutral_when_connected_and_off():
    """Connected + output-off (or simply unread yet) -> plain neutral
    outline: ready and inert, not a standing alarm."""
    _app()
    panel = BiasPanel(_FakeSupply(connected=True))
    try:
        # Stale (pre-first-reading) but connected -> already neutral, not
        # ghost -- there IS something to potentially kill.
        assert panel._btn_off.property("state") == ""
        panel.set_reading(_Reading(0.0, 0.0, False))
        assert panel._tile_hv.value() == "OFF"
        assert panel._btn_off.property("state") == ""
    finally:
        _dispose(panel)


def test_kill_switch_escalates_to_danger_when_hv_settled_live():
    """HV-live (settled at a real setpoint) -> filled red, full salience."""
    _app()
    supply = _FakeSupply(connected=True)
    supply.setpoint_V = -300.0
    panel = BiasPanel(supply)
    try:
        panel.set_reading(_Reading(-300.0, 5e-6, False))
        assert panel._tile_hv.value() == "SETTLED"
        assert panel._btn_off.property("state") == "danger"
    finally:
        _dispose(panel)


def test_kill_switch_escalates_on_compliance_trip():
    """TRIPPED must escalate too -- a fault is exactly when the operator
    most needs the kill switch to stand out."""
    _app()
    supply = _FakeSupply(connected=True)
    supply.setpoint_V = -300.0
    panel = BiasPanel(supply)
    try:
        panel.set_reading(_Reading(-300.0, 150e-6, True))
        assert panel._tile_hv.value() == "TRIPPED"
        assert panel._btn_off.property("state") == "danger"
    finally:
        _dispose(panel)


def test_kill_switch_returns_to_ghost_on_disconnect():
    """A disconnect (``set_reading(None)``, the main window's hook) must
    de-escalate all the way back to ghost, never leave a stale red."""
    _app()
    supply = _FakeSupply(connected=True)
    supply.setpoint_V = -300.0
    panel = BiasPanel(supply)
    try:
        panel.set_reading(_Reading(-300.0, 5e-6, False))
        assert panel._btn_off.property("state") == "danger"
        # A real disconnect drops the driver's connected flag FIRST (that is
        # what makes the poller emit None in the first place) -- mirror that
        # here rather than just calling set_reading(None) in isolation.
        supply.connected = False
        panel.set_reading(None)
        assert panel._btn_off.property("state") == "ghost"
    finally:
        _dispose(panel)


def test_kill_switch_off_failure_stays_escalated_not_reassuring():
    """A failed Output OFF (``_on_emergency_off_done`` error path) must
    escalate straight to filled red instead of fading to the busy-cleared
    neutral -- a stop that did NOT confirm off must never look safe."""
    _app()
    supply = _FakeSupply(connected=True)
    supply.setpoint_V = -300.0
    panel = BiasPanel(supply)
    try:
        panel.set_reading(_Reading(-300.0, 5e-6, False))
        assert panel._btn_off.property("state") == "danger"
        panel._on_emergency_off_done("supply timeout")
        assert panel._tile_hv.value() == "ERROR"
        assert panel._btn_off.property("state") == "danger"
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# MultiBiasPanel — the ALL OUTPUTS OFF aggregate kill switch                   #
# --------------------------------------------------------------------------- #

def test_multi_bias_all_off_ghost_when_nothing_connected():
    _app()
    drv = SimulatedBiasSupply(channel_count=2, voltage_range_V=1000.0)
    panel = MultiBiasPanel([BiasChannel(drv, 0), BiasChannel(drv, 1)])
    try:
        assert panel._btn_all_off.objectName() == "killSwitchBtn"
        assert panel._btn_all_off.property("state") == "ghost"
    finally:
        panel.shutdown()


def test_multi_bias_all_off_aggregates_worst_channel_state():
    """The ONE global control must escalate the instant ANY channel might be
    HV-live, and de-escalate again once none is -- driven purely by each
    child BiasPanel's own kill_switch_state_changed signal, never a new
    poll/timer of MultiBiasPanel's own."""
    _app()
    drv = SimulatedBiasSupply(channel_count=2, voltage_range_V=1000.0)
    drv.connect()   # safe, simulated -- both channel proxies read connected
    panel = MultiBiasPanel([BiasChannel(drv, 0), BiasChannel(drv, 1)])
    try:
        # Connected, no reading pushed on either channel yet -- neutral, not
        # ghost (there IS something that could be live).
        assert panel._btn_all_off.property("state") == ""

        panel0, panel1 = panel._panels   # the two per-channel BiasPanels
        # Drive channel 0's tile directly into a live rung (bypasses the
        # voltage-derivation arithmetic -- _set_hv_tile is the one choke
        # point every real path already funnels through).
        panel0._set_hv_tile("SETTLED", "armed", "live at setpoint — inferred")
        assert panel0._btn_off.property("state") == "danger"
        assert panel._btn_all_off.property("state") == "danger", (
            "aggregate must escalate the instant ANY channel is live")

        # Settle channel 0 back down -- the aggregate must de-escalate once
        # no channel is live any more.
        panel0._set_hv_tile("OFF", "normal", "inferred — output-on state not readable")
        assert panel0._btn_off.property("state") == ""
        assert panel._btn_all_off.property("state") == "", (
            "aggregate must de-escalate once no channel is live")
    finally:
        panel.shutdown()
