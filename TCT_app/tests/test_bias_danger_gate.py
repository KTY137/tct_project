"""Every HV-energizing path in the bias panels is danger-gated (CLAUDE.md
hardware-safety rule 2) — and the fail-safe stops are NOT (cockpit law 5).

Regression guard for the rule-2 violation found 2026-07-12: ``BiasPanel`` did
not import ``DangerGate`` at all, so "Ramp to voltage" (and the panel's IV /
bias+waveform sweeps) energized the HV output with **zero** confirmation, while
``CalibrationPanel`` already routed its motion through the injected
``QtDangerGate``.  These tests pin, headless and hardware-free:

* manual ramp / IV sweep / bias+waveform sweep / polarity relay all ask the
  injected gate BEFORE any driver call, and a decline leaves the supply
  untouched and the panel unarmed (no busy button, no RAMPING tile);
* the ``DangerAction`` carries the REAL numbers (target V, step, delay,
  channel) — a dialog that could lie about the setpoint is a safety bug;
* "Output OFF (0 V)" and "ALL OUTPUTS OFF" stay ONE TAP even with a gate that
  refuses everything;
* ``gate=None`` REFUSES (and says so) — the same fail-safe fallback
  ``CalibrationPanel`` uses for gate-less motion, never "no gate = no
  confirmation needed".

Idiom follows tests/test_cockpit_batch_b_panels.py: QT_QPA_PLATFORM=offscreen,
a shared QApplication, no pytest-qt, simulated backends only.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from controller.danger_gate import AutoConfirmGate, DenyAllGate
from devices.bias_channel import BiasChannel
from devices.bias_supply_simulated import SimulatedBiasSupply
from gui import bias_panel as bias_panel_mod
from gui.bias_panel import BiasPanel
from gui.multi_bias_panel import MultiBiasPanel


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
    app = _app()
    shutdown = getattr(panel, "shutdown", None)
    if shutdown is not None:
        shutdown()
    panel.deleteLater()
    _pump(app, 0.1)


def _expand_sweeps(panel: BiasPanel) -> None:
    """Expand the "Standalone sweeps (advanced)" CheckableCard — its body (and
    therefore the IV / vscan buttons) is DISABLED while collapsed, so this is
    the same step the operator takes before either sweep can be started."""
    panel._sweeps_card.set_checked(True)
    _pump(_app(), 0.05)
    assert panel._btn_iv.isEnabled() and panel._btn_vscan.isEnabled()


@dataclass
class _Reading:
    voltage_V: float
    current_A: float
    compliant: bool


class _SpySupply:
    """Records every driver call.  ``connected = False`` keeps the panel's
    readout poller idle, so nothing races the assertions."""

    connected = False
    simulation = True
    setpoint_V = 0.0
    compliance_A = 100e-6
    voltage_range_V = 1000.0
    channel = 0

    def __init__(self) -> None:
        self.ramp_calls: list[tuple] = []
        self.output_off_calls = 0
        self.compliance_calls: list[float] = []
        self.polarity_calls: list[str] = []

    def ramp_to(self, target_V, step_V=5.0, delay_s=0.1):
        self.ramp_calls.append((target_V, step_V, delay_s))
        self.setpoint_V = target_V

    def output_off(self):
        self.output_off_calls += 1

    def set_compliance(self, current_A):
        self.compliance_calls.append(current_A)

    def set_polarity(self, polarity):
        self.polarity_calls.append(polarity)

    def read(self):
        return _Reading(self.setpoint_V, 1e-6, False)

    def get_polarity(self):
        return "n"

    def supports_polarity_switch(self):
        return True


class _SpyGate:
    """Records every DangerAction and answers with a fixed verdict."""

    def __init__(self, allow: bool) -> None:
        self._allow = allow
        self.actions: list = []

    def confirm(self, action) -> bool:
        self.actions.append(action)
        return self._allow


# --------------------------------------------------------------------------- #
# 1. Manual ramp — the headline fix                                            #
# --------------------------------------------------------------------------- #

def test_manual_ramp_refused_when_gate_declines():
    """A declined confirmation must reach NO driver call, and must leave no
    busy/RAMPING state stuck behind it."""
    app = _app()
    supply = _SpySupply()
    panel = BiasPanel(supply, gate=DenyAllGate())
    try:
        panel._spin_volt.setValue(-300.0)
        panel._btn_apply.click()
        _pump(app, 0.2)

        assert supply.ramp_calls == [], "HV was ramped without confirmation"
        assert supply.output_off_calls == 0
        # No stuck busy state: no worker thread, buttons live, tile not armed.
        assert panel._op_thread is None
        assert panel._hv_ramping is False
        assert panel._btn_apply.isEnabled()
        assert not panel._tile_hv.value().startswith("RAMPING")
        assert panel._tile_hv.state() != "armed"
    finally:
        _dispose(panel)


def test_manual_ramp_proceeds_when_gate_confirms():
    """A confirmed ramp reaches the driver exactly once, with the spin values."""
    app = _app()
    supply = _SpySupply()
    panel = BiasPanel(supply, gate=AutoConfirmGate())
    try:
        panel._spin_volt.setValue(-250.0)
        panel._spin_step.setValue(20.0)
        panel._spin_delay.setValue(0.25)
        panel._btn_apply.click()

        assert _pump_until(app, lambda: bool(supply.ramp_calls)), \
            "confirmed ramp never reached the driver"
        _pump(app, 0.2)
        assert supply.ramp_calls == [(-250.0, 20.0, 0.25)]
        assert len(supply.ramp_calls) == 1
    finally:
        _dispose(panel)


def test_manual_ramp_action_carries_the_real_setpoint():
    """The dialog cannot lie: the DangerAction is an ``hv_ramp`` whose summary
    and detail carry the actual target voltage, step, delay and channel."""
    app = _app()
    supply = _SpySupply()
    gate = _SpyGate(allow=False)          # deny: we only inspect the payload
    panel = BiasPanel(supply, gate=gate)
    try:
        panel._spin_volt.setValue(-420.0)
        panel._spin_step.setValue(15.0)
        panel._spin_delay.setValue(0.5)
        panel._btn_apply.click()
        _pump(app, 0.1)

        assert len(gate.actions) == 1
        action = gate.actions[0]
        assert action.kind == "hv_ramp"
        assert "-420" in action.summary, action.summary
        assert action.detail["target_V"] == -420.0
        assert action.detail["ramp_step_V"] == 15.0
        assert action.detail["ramp_delay_s"] == 0.5
        assert action.detail["channel"] == 0
        assert supply.ramp_calls == []
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# 2. IV sweep (this panel's own worker ramps HV)                                #
# --------------------------------------------------------------------------- #

def test_iv_sweep_refused_when_gate_declines():
    app = _app()
    supply = _SpySupply()
    panel = BiasPanel(supply, gate=DenyAllGate())
    try:
        _expand_sweeps(panel)
        panel._spin_iv_start.setValue(0.0)
        panel._spin_iv_stop.setValue(-30.0)
        panel._spin_iv_step.setValue(10.0)
        panel._btn_iv.click()
        _pump(app, 0.2)

        assert supply.ramp_calls == [], "IV sweep energized HV without confirmation"
        assert supply.compliance_calls == []
        assert getattr(panel, "_iv_thread", None) is None, "worker thread started anyway"
        assert panel._btn_iv.isEnabled()
        assert panel._hv_scan_stepping is False
    finally:
        _dispose(panel)


def test_iv_sweep_gate_sees_the_sweep_envelope():
    app = _app()
    supply = _SpySupply()
    gate = _SpyGate(allow=False)
    panel = BiasPanel(supply, gate=gate)
    try:
        _expand_sweeps(panel)
        panel._spin_iv_start.setValue(0.0)
        panel._spin_iv_stop.setValue(-300.0)
        panel._spin_iv_step.setValue(10.0)
        panel._btn_iv.click()
        _pump(app, 0.1)

        assert len(gate.actions) == 1
        action = gate.actions[0]
        assert action.kind == "hv_ramp"
        assert "-300" in action.summary, action.summary
        assert action.detail["target_V"] == -300.0
        assert action.detail["start_V"] == 0.0
        assert action.detail["channel"] == 0
    finally:
        _dispose(panel)


def test_iv_sweep_starts_once_confirmed():
    app = _app()
    supply = _SpySupply()
    panel = BiasPanel(supply, gate=AutoConfirmGate())
    try:
        _expand_sweeps(panel)
        panel._spin_iv_start.setValue(0.0)
        panel._spin_iv_stop.setValue(-20.0)
        panel._spin_iv_step.setValue(10.0)
        panel._spin_iv_delay.setValue(0.1)
        panel._btn_iv.click()

        assert _pump_until(app, lambda: bool(supply.ramp_calls)), \
            "confirmed IV sweep never reached the driver"
        assert panel._hv_scan_stepping is True
    finally:
        _dispose(panel)          # aborts the worker + joins its thread


# --------------------------------------------------------------------------- #
# 3. Bias + waveform sweep (the ScanController's classic vscan loop ramps HV   #
#    with no gate of its own, so the panel that starts it must confirm)        #
# --------------------------------------------------------------------------- #

def test_vscan_refused_when_gate_declines():
    app = _app()
    supply = _SpySupply()
    panel = BiasPanel(supply, gate=DenyAllGate())
    seen: list = []
    panel.vscan_requested.connect(seen.append)
    try:
        _expand_sweeps(panel)
        panel._spin_vs_start.setValue(0.0)
        panel._spin_vs_stop.setValue(-300.0)
        panel._btn_vscan.click()
        _pump(app, 0.1)

        assert seen == [], "unconfirmed bias+waveform scan was requested anyway"
        assert supply.ramp_calls == []
    finally:
        _dispose(panel)


def test_vscan_requested_once_confirmed_and_action_carries_stop_voltage():
    app = _app()
    supply = _SpySupply()
    gate = _SpyGate(allow=True)
    panel = BiasPanel(supply, gate=gate)
    seen: list = []
    panel.vscan_requested.connect(seen.append)
    try:
        _expand_sweeps(panel)
        panel._spin_vs_start.setValue(0.0)
        panel._spin_vs_stop.setValue(-300.0)
        panel._spin_vs_step.setValue(-10.0)
        panel._btn_vscan.click()
        _pump(app, 0.1)

        assert len(seen) == 1
        assert seen[0].v_stop_V == -300.0
        assert len(gate.actions) == 1
        action = gate.actions[0]
        assert action.kind == "hv_ramp"
        assert "-300" in action.summary, action.summary
        assert action.detail["target_V"] == -300.0
        assert action.detail["ramp_step_V"] == -10.0
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# 4. Polarity relay — same gate, no hand-rolled QMessageBox                     #
# --------------------------------------------------------------------------- #

def test_polarity_switch_refused_when_gate_declines():
    app = _app()
    supply = _SpySupply()
    panel = BiasPanel(supply, gate=DenyAllGate())
    try:
        panel._last_polarity = "n"
        panel._on_switch_polarity()
        _pump(app, 0.1)
        assert supply.polarity_calls == [], "HV relay thrown without confirmation"
    finally:
        _dispose(panel)


def test_polarity_switch_routes_through_the_injected_gate():
    app = _app()
    supply = _SpySupply()
    gate = _SpyGate(allow=True)
    panel = BiasPanel(supply, gate=gate)
    try:
        panel._last_polarity = "n"
        panel._on_switch_polarity()

        assert _pump_until(app, lambda: bool(supply.polarity_calls))
        assert supply.polarity_calls == ["p"]
        assert len(gate.actions) == 1
        action = gate.actions[0]
        assert action.kind == "hv_polarity"
        assert action.detail["to"] == "p"
        assert action.detail["channel"] == 0
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# 5. Fail-safe stops stay ONE TAP (law 5) even with a gate that denies all      #
# --------------------------------------------------------------------------- #

def test_output_off_is_not_gated():
    """The per-channel kill switch must fire under a DenyAllGate: a stop can
    only make things safer, so it never waits on a confirmation."""
    app = _app()
    supply = _SpySupply()
    gate = _SpyGate(allow=False)
    panel = BiasPanel(supply, gate=gate)
    try:
        panel._btn_off.click()

        assert _pump_until(app, lambda: supply.output_off_calls > 0), \
            "Output OFF was blocked — the kill switch must stay one-tap"
        assert supply.ramp_calls and supply.ramp_calls[0][0] == 0.0
        assert gate.actions == [], "the kill switch must never ask the gate"
    finally:
        _dispose(panel)


def test_all_outputs_off_is_not_gated():
    """MultiBiasPanel's global ALL OUTPUTS OFF is likewise ungated."""
    app = _app()
    drv = SimulatedBiasSupply(channel_count=2, voltage_range_V=1000.0)
    drv.connect()
    gate = _SpyGate(allow=False)
    panel = MultiBiasPanel([BiasChannel(drv, 0), BiasChannel(drv, 1)], gate=gate)
    try:
        for ch in (0, 1):
            drv.output_on_ch(ch)
            drv.set_voltage_ch(ch, -100.0)

        panel._btn_all_off.click()

        assert _pump_until(
            app,
            lambda: not drv.output_is_on_ch(0) and not drv.output_is_on_ch(1),
        ), "ALL OUTPUTS OFF was blocked — the kill switch must stay one-tap"
        assert drv.setpoint_V_ch(0) == 0.0 and drv.setpoint_V_ch(1) == 0.0
        assert gate.actions == [], "ALL OUTPUTS OFF must never ask the gate"
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# 6. gate=None — CalibrationPanel's fallback: refuse and say so                 #
# --------------------------------------------------------------------------- #

def test_no_gate_refuses_every_hv_path_and_surfaces_it(monkeypatch):
    app = _app()
    supply = _SpySupply()
    shown: list[str] = []

    def _fake_warning(parent, title, text, *a, **k):
        shown.append(f"{title}|{text}")
        return None

    monkeypatch.setattr(bias_panel_mod.QMessageBox, "warning",
                        staticmethod(_fake_warning))

    panel = BiasPanel(supply)          # no gate injected
    seen: list = []
    panel.vscan_requested.connect(seen.append)
    try:
        assert panel._gate is None
        _expand_sweeps(panel)

        panel._spin_volt.setValue(-300.0)
        panel._btn_apply.click()
        panel._btn_iv.click()
        panel._btn_vscan.click()
        panel._last_polarity = "n"
        panel._on_switch_polarity()
        _pump(app, 0.2)

        # Fail-safe: an un-wired confirmation path is a REFUSAL, never a bypass.
        assert supply.ramp_calls == [], "HV ramped with no confirmation gate wired"
        assert supply.polarity_calls == []
        assert seen == []
        assert panel._hv_ramping is False
        assert panel._op_thread is None
        # ...and the operator is told why, rather than facing a dead button.
        assert len(shown) == 4, shown
        assert all("Confirmation unavailable" in s for s in shown)

        # The kill switch still works with no gate (law 5).
        panel._btn_off.click()
        assert _pump_until(app, lambda: supply.output_off_calls > 0)
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# 7. MultiBiasPanel forwards the ONE app gate to every child panel             #
# --------------------------------------------------------------------------- #

def test_multi_bias_panel_forwards_gate_to_children_and_rebuilds():
    _app()
    drv = SimulatedBiasSupply(channel_count=3, voltage_range_V=1000.0)
    drv.connect()
    gate = AutoConfirmGate()
    panel = MultiBiasPanel([BiasChannel(drv, 0)], gate=gate)
    try:
        assert panel._panels[0]._gate is gate

        # Channels enumerated after connect must be gated too.
        panel.rebuild([BiasChannel(drv, i) for i in range(3)])
        assert len(panel._panels) == 3
        assert all(p._gate is gate for p in panel._panels), \
            "a rebuilt channel tab lost its confirmation gate"
    finally:
        _dispose(panel)


def test_main_window_injects_one_gate_into_the_bias_panels():
    """The bias panels get the SAME QtDangerGate instance as the plan executor
    and the calibration panel — one confirmation mechanism for the whole app."""
    import inspect

    import tct_gui

    src = inspect.getsource(tct_gui.TCTMainWindow._build_central)
    assert "MultiBiasPanel(self._devices.bias_channels," in src
    # Same instance for the bias panels and the calibration panel / executor.
    assert src.count("gate=self._danger_gate") >= 2
    assert "QtDangerGate(parent=self)" in src
    # The gate must be built before the panels that take it by injection.
    assert src.index("QtDangerGate(parent=self)") < src.index("MultiBiasPanel(")


# --------------------------------------------------------------------------- #
# 8. Manual-danger lock (A5.1) — a Scan Sequencer run owns the HV: every        #
#    HV-ENERGIZING control locks, but OFF / ALL-OFF stay ONE TAP + FUNCTIONAL   #
# --------------------------------------------------------------------------- #

def test_manual_danger_lock_disables_energize_but_keeps_output_off_live():
    """The headline A5.1 guarantee for the bias panel: locking disables every
    HV-ENERGIZING control, but the per-channel Output OFF stays enabled AND
    actually fires while locked (the kill switch is never greyed out)."""
    app = _app()
    supply = _SpySupply()
    panel = BiasPanel(supply, gate=AutoConfirmGate())
    try:
        _expand_sweeps(panel)              # so the IV/vscan parents are enabled
        panel.set_manual_danger_locked(True)
        # Every HV-ENERGIZING control is disabled ...
        for w in (panel._btn_apply, panel._btn_set_comp, panel._spin_comp,
                  panel._btn_iv, panel._btn_vscan):
            assert not w.isEnabled()
        # ... but the per-channel Output OFF stays enabled AND fires while locked.
        assert panel._btn_off.isEnabled()
        panel._btn_off.click()
        assert _pump_until(app, lambda: supply.output_off_calls > 0), \
            "Output OFF was blocked while the panel was locked"
        assert supply.ramp_calls and supply.ramp_calls[0][0] == 0.0
    finally:
        _dispose(panel)


def test_manual_danger_unlock_restores_energize_controls():
    app = _app()
    supply = _SpySupply()
    panel = BiasPanel(supply, gate=AutoConfirmGate())
    try:
        _expand_sweeps(panel)
        panel.set_manual_danger_locked(True)
        panel.set_manual_danger_locked(False)
        for w in (panel._btn_apply, panel._btn_set_comp, panel._spin_comp,
                  panel._btn_iv, panel._btn_vscan):
            assert w.isEnabled()
    finally:
        _dispose(panel)


def test_manual_danger_unlock_does_not_reenable_collapsed_sweeps():
    """Unlock restores the panel's OWN state, not a blanket enable: the IV/vscan
    buttons stay effectively disabled while the sweeps card is collapsed (their
    parent body is disabled), lock or no lock."""
    app = _app()
    supply = _SpySupply()
    panel = BiasPanel(supply, gate=AutoConfirmGate())
    try:
        # sweeps card stays COLLAPSED (its body is disabled) the whole time
        assert not panel._btn_iv.isEnabled()
        panel.set_manual_danger_locked(True)
        panel.set_manual_danger_locked(False)
        assert not panel._btn_iv.isEnabled(), \
            "unlock blanket-enabled a control the collapsed card should keep off"
        assert not panel._btn_vscan.isEnabled()
        # The always-visible ramp control, by contrast, is live again.
        assert panel._btn_apply.isEnabled()
    finally:
        _dispose(panel)


def test_manual_danger_lock_tooltips_energize_but_not_output_off():
    app = _app()
    supply = _SpySupply()
    panel = BiasPanel(supply, gate=AutoConfirmGate())
    try:
        off_tip = panel._btn_off.toolTip()
        panel.set_manual_danger_locked(True)
        assert panel._btn_apply.toolTip() == "locked while a sequence runs"
        # The kill switch keeps its own tooltip — never the lock text.
        assert panel._btn_off.toolTip() == off_tip
        panel.set_manual_danger_locked(False)
        assert panel._btn_apply.toolTip() != "locked while a sequence runs"
    finally:
        _dispose(panel)


def test_multi_bias_lock_forwards_to_children_and_keeps_all_off_live():
    """MultiBiasPanel.set_manual_danger_locked forwards to every channel tab, and
    the global ALL OUTPUTS OFF stays enabled AND functional while locked."""
    app = _app()
    drv = SimulatedBiasSupply(channel_count=2, voltage_range_V=1000.0)
    drv.connect()
    panel = MultiBiasPanel([BiasChannel(drv, 0), BiasChannel(drv, 1)],
                           gate=AutoConfirmGate())
    try:
        for ch in (0, 1):
            drv.output_on_ch(ch)
            drv.set_voltage_ch(ch, -100.0)

        panel.set_manual_danger_locked(True)
        # Every child's energize path is locked, its own Output OFF stays live.
        for child in panel._panels:
            assert not child._btn_apply.isEnabled()
            assert child._btn_off.isEnabled()
        # ... and the global ALL OUTPUTS OFF stays live AND functional.
        assert panel._btn_all_off.isEnabled()
        panel._btn_all_off.click()
        assert _pump_until(
            app,
            lambda: not drv.output_is_on_ch(0) and not drv.output_is_on_ch(1),
        ), "ALL OUTPUTS OFF was blocked while the panel was locked"
        # Settle on the REAL invariant, not just a nulled handle: the all-off
        # teardown must have fully landed ON THE GUI THREAD — worker joined
        # (_off_thread is None) AND the tabs re-enabled (_on_all_off_done's
        # _tabs.setEnabled(True) ran).  Nulling _off_thread happens first inside
        # that slot, so waiting on it alone could unlock while the re-enable is
        # still pending; if the teardown ran in the worker's context (the
        # wait-on-itself bug) it could even re-enable the tabs off-thread and
        # race the unlock below.  This stays a BOUNDED pump, so a genuinely
        # lost/late re-enable times out and fails here instead of papering over.
        assert _pump_until(
            app,
            lambda: panel._off_thread is None and panel._tabs.isEnabled(),
        ), "ALL OUTPUTS OFF teardown never settled on the GUI thread"

        panel.set_manual_danger_locked(False)
        for child in panel._panels:
            assert child._btn_apply.isEnabled()
    finally:
        _dispose(panel)
