"""Headless checks for the HV safety gate — GUI half (Wave-0, Beat 0.1).

Covers three fixes, simulated/mock objects only, ``QT_QPA_PLATFORM=offscreen``:

* ``BiasPanel._derive_hv_state`` — a LATCHED hardware trip (``tripped is True``)
  wins over compliance and never shows a healthy SETTLED tile; a compliance-only
  reading still yields the compliance TRIPPED state; a 3-field reading with no
  ``tripped`` attribute keeps today's behaviour and never crashes.
* ``_IVWorker.run`` — stops on a latched trip (before compliance) and on
  compliance, emitting a VISIBLE, DISTINCT reason for each cause.
* ``tct_gui.TCTMainWindow._safe_bias_shutdown`` — output_off is always attempted
  even when the ramp-down raises, and an output_off that itself raises is logged
  rather than propagated.
"""
from __future__ import annotations

import os
import types
from dataclasses import dataclass

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui.bias_panel import BiasPanel, _IVWorker
from tct_gui import TCTMainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


# --------------------------------------------------------------------------- #
# Reading stand-ins                                                            #
# --------------------------------------------------------------------------- #

@dataclass
class _Reading:
    """4-field reading with the optional hardware-status ``tripped`` flag."""
    voltage_V: float
    current_A: float
    compliant: bool
    tripped: bool | None = None


@dataclass
class _LegacyReading:
    """3-field reading (no ``tripped`` attribute) — mirrors the fake used in
    tests/test_cockpit_batch_b_panels.py; must keep working via ``getattr``."""
    voltage_V: float
    current_A: float
    compliant: bool


class _FakeSupply:
    """Attribute-only stand-in; ``connected = False`` keeps the poller idle."""
    connected = False
    setpoint_V = -300.0
    compliance_A = 100e-6
    voltage_range_V = 1000.0
    channel = 0


def _dispose(panel) -> None:
    app = _app()
    shutdown = getattr(panel, "shutdown", None)
    if shutdown is not None:
        shutdown()
    panel.deleteLater()
    app.processEvents()


# --------------------------------------------------------------------------- #
# _derive_hv_state — latched-trip honesty                                      #
# --------------------------------------------------------------------------- #

def test_derive_tripped_first_wins_over_compliant():
    _app()
    panel = BiasPanel(_FakeSupply())
    try:
        # tripped AND compliant both set: the latched-trip branch must win, with
        # its own (distinct) reason text — not the compliance reason.
        value, state, reason = panel._derive_hv_state(
            _Reading(-250.0, 100e-6, compliant=True, tripped=True), -250.0)
        assert value == "TRIPPED"
        assert state == "crit"
        assert "latched" in reason.lower()
        assert "compliance" not in reason.lower()
    finally:
        _dispose(panel)


def test_derive_tripped_alone_masks_settled_looking_readback():
    _app()
    panel = BiasPanel(_FakeSupply())
    try:
        # |V| ~= setpoint, not compliant: would normally read SETTLED. A latched
        # trip must override that and never show a healthy tile.
        value, state, reason = panel._derive_hv_state(
            _Reading(-299.0, 5e-6, compliant=False, tripped=True), -300.0)
        assert value == "TRIPPED"
        assert state == "crit"
        assert "latched" in reason.lower()
    finally:
        _dispose(panel)


def test_derive_compliant_only_still_yields_compliance_trip():
    _app()
    panel = BiasPanel(_FakeSupply())
    try:
        value, state, reason = panel._derive_hv_state(
            _Reading(-250.0, 100e-6, compliant=True, tripped=None), -250.0)
        assert value == "TRIPPED"
        assert state == "crit"
        # Distinct from the latched-trip reason.
        assert "compliance" in reason.lower()
        assert "latched" not in reason.lower()
    finally:
        _dispose(panel)


def test_derive_three_field_reading_keeps_todays_behavior():
    _app()
    panel = BiasPanel(_FakeSupply())
    try:
        # No ``tripped`` attr at all: must not crash, and a settled-looking
        # non-compliant reading keeps deriving SETTLED as before.
        value, state, _ = panel._derive_hv_state(
            _LegacyReading(-299.0, 5e-6, compliant=False), -300.0)
        assert value == "SETTLED"
        # Compliance-only on a legacy reading still trips.
        value2, state2, reason2 = panel._derive_hv_state(
            _LegacyReading(-250.0, 100e-6, compliant=True), -250.0)
        assert value2 == "TRIPPED"
        assert state2 == "crit"
        assert "compliance" in reason2.lower()
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# _IVWorker — visible early-stop on trip / compliance                          #
# --------------------------------------------------------------------------- #

class _SweepSupply:
    """Scripted supply: one reading per ``read()`` call, records ramp targets."""

    def __init__(self, readings):
        self._readings = list(readings)
        self._i = 0
        self.ramp_calls: list[float] = []

    def set_compliance(self, current_A):
        pass

    def ramp_to(self, voltage_V, step_V=None, delay_s=None):
        self.ramp_calls.append(voltage_V)

    def read(self):
        r = self._readings[min(self._i, len(self._readings) - 1)]
        self._i += 1
        return r


def _run_worker(readings):
    """Drive _IVWorker.run() synchronously (no thread → direct connections)
    and collect the emitted stop reason / error."""
    _app()
    supply = _SweepSupply(readings)
    worker = _IVWorker(
        supply=supply,
        voltages=[-10.0, -20.0, -30.0],
        compliance_A=100e-6,
        delay_s=0.0,
        ramp_step_V=10.0,
    )
    box = {"stopped": [], "error": [], "finished": 0}
    worker.stopped.connect(lambda msg: box["stopped"].append(msg))
    worker.error.connect(lambda msg: box["error"].append(msg))
    worker.finished.connect(lambda: box.__setitem__("finished", box["finished"] + 1))
    worker.run()
    return supply, box


def test_ivworker_stops_on_latched_trip():
    supply, box = _run_worker([
        _Reading(-10.0, 1e-6, compliant=False, tripped=False),
        _Reading(-20.0, 2e-6, compliant=False, tripped=True),
    ])
    assert box["error"] == []
    assert box["finished"] == 1
    # Stopped after the 2nd point → only two ramps issued, third never stepped.
    assert supply.ramp_calls == [-10.0, -20.0]
    assert len(box["stopped"]) == 1
    assert "trip" in box["stopped"][0].lower()


def test_ivworker_stops_on_compliance():
    supply, box = _run_worker([
        _Reading(-10.0, 1e-6, compliant=False, tripped=None),
        _Reading(-20.0, 100e-6, compliant=True, tripped=None),
    ])
    assert box["error"] == []
    assert box["finished"] == 1
    assert supply.ramp_calls == [-10.0, -20.0]
    assert len(box["stopped"]) == 1
    assert "compliance" in box["stopped"][0].lower()


def test_ivworker_reasons_are_distinct_and_both_visible():
    _, trip_box = _run_worker([
        _Reading(-10.0, 1e-6, compliant=False, tripped=True),
    ])
    _, comp_box = _run_worker([
        _Reading(-10.0, 100e-6, compliant=True, tripped=None),
    ])
    assert trip_box["stopped"] and comp_box["stopped"]
    trip_reason = trip_box["stopped"][0]
    comp_reason = comp_box["stopped"][0]
    # Both surfaced, and the texts distinguish the two causes.
    assert trip_reason != comp_reason
    assert "trip" in trip_reason.lower() and "compliance" not in trip_reason.lower()
    assert "compliance" in comp_reason.lower() and "trip" not in comp_reason.lower()


def test_ivworker_trip_takes_priority_over_compliance():
    # Both flags set on the same reading: the trip reason must be the one shown.
    _, box = _run_worker([
        _Reading(-10.0, 100e-6, compliant=True, tripped=True),
    ])
    assert len(box["stopped"]) == 1
    assert "trip" in box["stopped"][0].lower()


# --------------------------------------------------------------------------- #
# _safe_bias_shutdown — output_off must survive a raising ramp                 #
# --------------------------------------------------------------------------- #

class _RaisingBias:
    connected = True
    setpoint_V = -300.0

    def __init__(self, ramp_raises=False, off_raises=False):
        self._ramp_raises = ramp_raises
        self._off_raises = off_raises
        self.ramp_called = False
        self.off_called = False

    def ramp_to(self, voltage_V, **kwargs):
        self.ramp_called = True
        if self._ramp_raises:
            raise RuntimeError("ramp boom")

    def output_off(self):
        self.off_called = True
        if self._off_raises:
            raise RuntimeError("off boom")


def _fake_main(bias):
    """A bare object carrying only what _safe_bias_shutdown reads."""
    return types.SimpleNamespace(_devices=types.SimpleNamespace(bias_supply=bias))


def test_safe_shutdown_disables_output_even_when_ramp_raises():
    bias = _RaisingBias(ramp_raises=True)
    # Must not propagate; output_off is the safety-critical step and must run.
    TCTMainWindow._safe_bias_shutdown(_fake_main(bias))
    assert bias.ramp_called is True
    assert bias.off_called is True


def test_safe_shutdown_logs_when_output_off_itself_raises():
    bias = _RaisingBias(off_raises=True)
    # A raising output_off is logged, not propagated.
    TCTMainWindow._safe_bias_shutdown(_fake_main(bias))
    assert bias.off_called is True
