"""The unbounded / frame-changing motor controls are danger-gated (CLAUDE.md
hardware-safety rule 2) — and jog / STOP are deliberately NOT (cockpit law 5).

Second half of the rule-2 gap found 2026-07-12: ``MotorPanel`` did not import
``DangerGate`` at all, so "Home all", the absolute "Move to", "Center" and
"Zero here" commanded the stage (or silently redefined the user-frame origin)
with **zero** confirmation, while the plan executor, the calibration panel and
the bias panels all routed through the injected ``QtDangerGate``.  These tests
pin, headless and hardware-free:

* Home / Move to / Center / Zero here ask the injected gate BEFORE any driver
  call, and a decline leaves the driver untouched and the panel idle (no busy
  buttons, no "Moving..." chip — no state lie);
* the ``DangerAction`` carries the REAL numbers (target x/y/z, current
  position, travel distance; for Zero Here the new origin) — a dialog that
  could lie about where the stage is going is a safety bug;
* **jog stays ungated** (Adam's ruling: a bounded, soft-limit-checked,
  deliberate click; a modal per jog trains operators to click through dialogs).
  Should that ruling change, gating it is one ``_confirm_motion`` call — these
  tests then flip, they do not have to be rewritten;
* **STOP stays ONE TAP** even under a gate that refuses everything (law 5);
* ``gate=None`` REFUSES the gated actions (and says so), while jog and STOP
  keep working — an un-wired confirmation path is never "no confirmation
  needed".

Idiom follows tests/test_bias_danger_gate.py: QT_QPA_PLATFORM=offscreen, a
shared QApplication, no pytest-qt, spy/simulated backends only.
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from controller.danger_gate import AutoConfirmGate, DenyAllGate
from devices.motor_base import Position, SoftwareLimits
from gui import motor_panel as motor_panel_mod
from gui.motor_panel import MotorPanel


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


def _dispose(panel: MotorPanel) -> None:
    app = _app()
    panel.shutdown()
    panel.deleteLater()
    _pump(app, 0.1)


def _button(panel: MotorPanel, text: str) -> QPushButton:
    """The real button the operator clicks — so these tests exercise the
    wiring, not just the slot (a button re-connected to an ungated path would
    otherwise slip through)."""
    for btn in panel.findChildren(QPushButton):
        if btn.text().strip().casefold() == text.casefold():
            return btn
    raise AssertionError(f"no button labelled {text!r} in the motor panel")


class _SpyMotor:
    """Records every driver call.  ``connected = False`` keeps the panel's
    position poller idle, so no background thread races the assertions (the
    task thread still runs the commanded op — that is what we are measuring)."""

    connected = False
    homed = True
    simulation = True

    def __init__(self) -> None:
        # Deliberately NOT centred on the origin: the centre of this envelope
        # is (100, 50), which no spinbox default could accidentally match.
        self.limits = SoftwareLimits(x_min=0.0, x_max=200.0,
                                     y_min=0.0, y_max=100.0,
                                     z_min=-10.0, z_max=10.0)
        self._pos = Position(0.0, 0.0, 0.0)
        self.move_to_calls: list[tuple[float, float, float]] = []
        self.move_relative_calls: list[tuple[float, float, float]] = []
        self.home_calls = 0
        self.zero_calls = 0
        self.center_calls = 0
        self.stop_calls = 0

    # --- MotorStageBase surface the panel touches -------------------------
    def get_position(self) -> Position:
        return self._pos

    def limits_user_frame(self) -> SoftwareLimits:
        return self.limits

    def move_to(self, x_mm: float, y_mm: float, z_mm: float) -> None:
        self.move_to_calls.append((x_mm, y_mm, z_mm))

    def move_relative(self, dx_mm: float, dy_mm: float, dz_mm: float) -> None:
        self.move_relative_calls.append((dx_mm, dy_mm, dz_mm))

    def move_to_center(self) -> None:
        self.center_calls += 1

    def home(self, axes=None) -> None:
        self.home_calls += 1

    def zero_position(self) -> None:
        self.zero_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1

    def test_connection(self) -> str:
        return "spy motor"


class _SpyGate:
    """Records every DangerAction and answers with a fixed verdict."""

    def __init__(self, allow: bool) -> None:
        self._allow = allow
        self.actions: list = []

    def confirm(self, action) -> bool:
        self.actions.append(action)
        return self._allow


def _assert_idle(panel: MotorPanel) -> None:
    """A refused action must leave NO trace: no worker thread, no disabled
    (busy) controls, no "Moving..." chip claiming motion that never happened."""
    assert panel._task_thread is None, "a refused action started a worker thread"
    assert panel._chip_motion.text() == "Idle", panel._chip_motion.text()
    assert _button(panel, "Home all").isEnabled()
    assert _button(panel, "Move to").isEnabled()


# --------------------------------------------------------------------------- #
# 1. Home — rule 2 names homing explicitly                                      #
# --------------------------------------------------------------------------- #

def test_home_refused_when_gate_declines():
    app = _app()
    motor = _SpyMotor()
    panel = MotorPanel(motor, gate=DenyAllGate())
    try:
        _button(panel, "Home all").click()
        _pump(app, 0.2)

        assert motor.home_calls == 0, "the stage was homed without confirmation"
        _assert_idle(panel)
    finally:
        _dispose(panel)


def test_home_proceeds_when_gate_confirms():
    app = _app()
    motor = _SpyMotor()
    panel = MotorPanel(motor, gate=AutoConfirmGate())
    try:
        _button(panel, "Home all").click()

        assert _pump_until(app, lambda: motor.home_calls > 0), \
            "a confirmed home never reached the driver"
        _pump(app, 0.2)
        assert motor.home_calls == 1
        assert motor.move_to_calls == []
    finally:
        _dispose(panel)


def test_home_action_names_homing_and_the_frame_reset():
    app = _app()
    motor = _SpyMotor()
    gate = _SpyGate(allow=False)          # deny: we only inspect the payload
    panel = MotorPanel(motor, gate=gate)
    try:
        _button(panel, "Home all").click()
        _pump(app, 0.1)

        assert len(gate.actions) == 1
        action = gate.actions[0]
        assert action.kind == "move"
        assert "Home ALL axes" in action.summary, action.summary
        assert action.detail["motion"] == "home"
        assert action.detail["axes"] == "X, Y, Z"
        # The operator is told the origin moves — that is half the hazard.
        assert "origin" in action.summary.lower()
        assert motor.home_calls == 0
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# 2. Absolute move — unbounded travel to an arbitrary target                    #
# --------------------------------------------------------------------------- #

def test_move_abs_refused_when_gate_declines():
    app = _app()
    motor = _SpyMotor()
    panel = MotorPanel(motor, gate=DenyAllGate())
    try:
        panel._spin_x.setValue(120.0)
        panel._spin_y.setValue(-35.5)
        panel._spin_z.setValue(2.25)
        _button(panel, "Move to").click()
        _pump(app, 0.2)

        assert motor.move_to_calls == [], "the stage moved without confirmation"
        _assert_idle(panel)
    finally:
        _dispose(panel)


def test_move_abs_proceeds_once_with_the_spin_values():
    app = _app()
    motor = _SpyMotor()
    panel = MotorPanel(motor, gate=AutoConfirmGate())
    try:
        panel._spin_x.setValue(120.0)
        panel._spin_y.setValue(-35.5)
        panel._spin_z.setValue(2.25)
        _button(panel, "Move to").click()

        assert _pump_until(app, lambda: bool(motor.move_to_calls)), \
            "a confirmed move never reached the driver"
        _pump(app, 0.2)
        assert motor.move_to_calls == [(120.0, -35.5, 2.25)]
    finally:
        _dispose(panel)


def test_move_abs_action_carries_the_real_target_coordinates():
    """The dialog cannot lie: the summary the operator reads must contain the
    actual target the driver is about to be given."""
    app = _app()
    motor = _SpyMotor()
    gate = _SpyGate(allow=False)
    panel = MotorPanel(motor, gate=gate)
    try:
        panel._last_pos = (10.0, 20.0, 0.0)      # as the poller would leave it
        panel._spin_x.setValue(120.0)
        panel._spin_y.setValue(-35.5)
        panel._spin_z.setValue(2.25)
        _button(panel, "Move to").click()
        _pump(app, 0.1)

        assert len(gate.actions) == 1
        action = gate.actions[0]
        assert action.kind == "move"
        # Target coordinates, visible in the text — not just in the payload.
        for token in ("120.0", "-35.5", "2.25"):
            assert token in action.summary, (token, action.summary)
        assert action.detail["target_mm"] == {"x": 120.0, "y": -35.5, "z": 2.25}
        assert action.detail["current_mm"] == {"x": 10.0, "y": 20.0, "z": 0.0}
        assert action.detail["distance_mm"] > 0.0
        assert action.detail["frame"] == "user"
        assert motor.move_to_calls == []
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# 3. Center — same class as an absolute move                                    #
# --------------------------------------------------------------------------- #

def test_center_refused_when_gate_declines():
    app = _app()
    motor = _SpyMotor()
    panel = MotorPanel(motor, gate=DenyAllGate())
    try:
        _button(panel, "Center").click()
        _pump(app, 0.2)

        assert motor.center_calls == 0, "the stage centred without confirmation"
        _assert_idle(panel)
    finally:
        _dispose(panel)


def test_center_proceeds_when_confirmed_and_quotes_the_centre_point():
    app = _app()
    motor = _SpyMotor()
    gate = _SpyGate(allow=True)
    panel = MotorPanel(motor, gate=gate)
    try:
        _button(panel, "Center").click()

        assert _pump_until(app, lambda: motor.center_calls > 0), \
            "a confirmed centre move never reached the driver"
        _pump(app, 0.2)
        assert motor.center_calls == 1

        assert len(gate.actions) == 1
        action = gate.actions[0]
        assert action.kind == "move"
        # Midpoint of the spy envelope (0..200, 0..100) = (100, 50) — the exact
        # point move_to_center() commands, spelled out for the operator.
        assert "100.0" in action.summary and "50.0" in action.summary, action.summary
        assert action.detail["target_mm"]["x"] == 100.0
        assert action.detail["target_mm"]["y"] == 50.0
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# 4. Zero here — NOT motion, but it redefines the frame every soft-limit check  #
#    is validated against (the bench bug class)                                 #
# --------------------------------------------------------------------------- #

def test_zero_here_refused_when_gate_declines():
    app = _app()
    motor = _SpyMotor()
    panel = MotorPanel(motor, gate=DenyAllGate())
    try:
        _button(panel, "Zero here").click()
        _pump(app, 0.2)

        assert motor.zero_calls == 0, "the user-frame origin was redefined " \
                                      "without confirmation"
        _assert_idle(panel)
    finally:
        _dispose(panel)


def test_zero_here_action_says_what_changes_and_carries_the_new_origin():
    app = _app()
    motor = _SpyMotor()
    gate = _SpyGate(allow=True)
    panel = MotorPanel(motor, gate=gate)
    try:
        panel._last_pos = (12.5, -3.25, 1.0)
        _button(panel, "Zero here").click()

        assert _pump_until(app, lambda: motor.zero_calls > 0)
        assert motor.zero_calls == 1
        assert motor.move_to_calls == [] and motor.move_relative_calls == []

        assert len(gate.actions) == 1
        action = gate.actions[0]
        assert action.kind == "zero_here"
        # It must say plainly: the ORIGIN moves, the STAGE does not.
        assert "origin" in action.summary.lower()
        assert "does not move" in action.summary.lower()
        for token in ("12.5", "-3.25", "1.0"):
            assert token in action.summary, (token, action.summary)
        assert action.detail["moves_stage"] is False
        assert action.detail["new_origin_mm"] == {"x": 12.5, "y": -3.25, "z": 1.0}
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# 5. Jog is NOT gated (Adam's ruling) — a bounded, deliberate, checked click    #
# --------------------------------------------------------------------------- #

def test_jog_is_not_gated_even_under_a_declining_gate():
    app = _app()
    motor = _SpyMotor()
    gate = _SpyGate(allow=False)          # refuses everything it is asked
    panel = MotorPanel(motor, gate=gate)
    try:
        _button(panel, "X+").click()

        assert _pump_until(app, lambda: bool(motor.move_relative_calls)), \
            "jog was blocked — a bounded jog must not need a modal"
        _pump(app, 0.2)
        assert motor.move_relative_calls == [(0.1, 0.0, 0.0)]   # default step
        assert gate.actions == [], "jog must not ask the gate (Adam's ruling)"
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# 6. STOP stays ONE TAP (law 5) even under a gate that denies everything        #
# --------------------------------------------------------------------------- #

def test_stop_is_not_gated():
    app = _app()
    motor = _SpyMotor()
    gate = _SpyGate(allow=False)
    panel = MotorPanel(motor, gate=gate)
    try:
        _button(panel, "STOP").click()
        _pump(app, 0.1)

        assert motor.stop_calls == 1, "STOP was blocked — it must stay one tap"
        assert gate.actions == [], "STOP must never ask the gate"
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# 7. gate=None — refuse the dangerous actions and say so; jog / STOP still work #
# --------------------------------------------------------------------------- #

def test_no_gate_refuses_the_gated_actions_and_surfaces_it(monkeypatch):
    app = _app()
    motor = _SpyMotor()
    shown: list[str] = []

    def _fake_warning(parent, title, text, *a, **k):
        shown.append(f"{title}|{text}")
        return None

    monkeypatch.setattr(motor_panel_mod.QMessageBox, "warning",
                        staticmethod(_fake_warning))

    panel = MotorPanel(motor)             # no gate injected
    try:
        assert panel._gate is None

        panel._spin_x.setValue(50.0)
        _button(panel, "Home all").click()
        _button(panel, "Move to").click()
        _button(panel, "Center").click()
        _button(panel, "Zero here").click()
        _pump(app, 0.2)

        # Fail-safe: an un-wired confirmation path is a REFUSAL, never a bypass.
        assert motor.home_calls == 0
        assert motor.move_to_calls == []
        assert motor.center_calls == 0
        assert motor.zero_calls == 0
        _assert_idle(panel)
        # ...and the operator is told why, rather than facing a dead button.
        assert len(shown) == 4, shown
        assert all("Confirmation unavailable" in s for s in shown)

        # Jog and STOP still work with no gate (bounded click / law 5).
        _button(panel, "X+").click()
        assert _pump_until(app, lambda: bool(motor.move_relative_calls))
        _button(panel, "STOP").click()
        _pump(app, 0.1)
        assert motor.stop_calls == 1
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# 8. The main window injects the ONE app gate into the motor panel              #
# --------------------------------------------------------------------------- #

def test_main_window_injects_the_shared_gate_into_the_motor_panel():
    """The motor panel gets the SAME QtDangerGate instance as the plan
    executor, the calibration panel and the bias panels — one confirmation
    mechanism (and one audit surface) for the whole app."""
    import inspect

    import tct_gui

    src = inspect.getsource(tct_gui.TCTMainWindow._build_central)
    assert "MotorPanel(self._devices.motor," in src
    assert "gate=self._danger_gate" in src
    assert "QtDangerGate(parent=self)" in src
    # The gate must be built before the panels that take it by injection.
    assert src.index("QtDangerGate(parent=self)") < src.index("MotorPanel(")


# --------------------------------------------------------------------------- #
# 9. Manual-danger lock (A5.1) — a Scan Sequencer run owns the stage: every     #
#    motion-START control locks, but STOP stays ONE TAP and FUNCTIONAL          #
# --------------------------------------------------------------------------- #

def test_manual_danger_lock_disables_motion_but_keeps_stop_live():
    """The headline A5.1 guarantee for the motor panel: locking disables every
    motion-START control, but the emergency STOP stays enabled AND actually
    fires while locked (a panicking operator's control is never greyed out)."""
    app = _app()
    motor = _SpyMotor()
    panel = MotorPanel(motor, gate=AutoConfirmGate())
    try:
        panel.set_manual_danger_locked(True)
        # Every motion-START control (jog / step / move-to / home / center /
        # zero — the whole _motion_widgets set) is disabled ...
        for label in ("Home all", "Move to", "Center", "Zero here"):
            assert not _button(panel, label).isEnabled(), label
        assert all(not w.isEnabled() for w in panel._motion_widgets)
        # ... but STOP is untouched by the lock AND fires while locked (law 5).
        stop = _button(panel, "STOP")
        assert stop.isEnabled()
        assert stop not in panel._motion_widgets
        stop.click()
        _pump(app, 0.1)
        assert motor.stop_calls == 1, "STOP was blocked while the panel was locked"
    finally:
        _dispose(panel)


def test_manual_danger_unlock_restores_motion_controls():
    app = _app()
    motor = _SpyMotor()
    panel = MotorPanel(motor, gate=AutoConfirmGate())
    try:
        panel.set_manual_danger_locked(True)
        panel.set_manual_danger_locked(False)
        assert all(w.isEnabled() for w in panel._motion_widgets)
        # ...and a real move reaches the driver again after unlock.
        _button(panel, "Home all").click()
        assert _pump_until(app, lambda: motor.home_calls > 0), \
            "a move was still blocked after unlock"
    finally:
        _dispose(panel)


def test_manual_danger_unlock_composes_with_busy_never_blanket_enables():
    """Unlock restores the panel's OWN busy-aware state, not a blanket enable: a
    control disabled because a move is in flight stays disabled after unlock."""
    app = _app()
    motor = _SpyMotor()
    panel = MotorPanel(motor, gate=AutoConfirmGate())
    try:
        panel._set_busy(True)              # simulate an in-flight move (no thread)
        panel.set_manual_danger_locked(True)
        panel.set_manual_danger_locked(False)
        # Still busy → motion controls must remain disabled after the unlock.
        assert not _button(panel, "Home all").isEnabled()
        panel._set_busy(False)             # move finished
        assert _button(panel, "Home all").isEnabled()
    finally:
        _dispose(panel)


def test_manual_danger_lock_tooltips_motion_but_not_stop():
    app = _app()
    motor = _SpyMotor()
    panel = MotorPanel(motor, gate=AutoConfirmGate())
    try:
        center = _button(panel, "Center")
        original = center.toolTip()
        assert original                    # Center ships a real tooltip
        panel.set_manual_danger_locked(True)
        assert center.toolTip() == "locked while a sequence runs"
        # STOP never carries the lock tooltip — it is not a locked control.
        assert _button(panel, "STOP").toolTip() != "locked while a sequence runs"
        panel.set_manual_danger_locked(False)
        assert center.toolTip() == original
    finally:
        _dispose(panel)
