"""Headless tests for the two-step arm latch (design-system law 5 / §11).

Covers the reusable ``gui.arm_latch.ArmLatch`` widget mechanics (hold-to-arm,
press-twice, timeout, click-to-disarm) and its wiring into ``PlannerPanel``
(envelope rendered over the latch, Execute builds an ``ArmedEnvelopeGate``,
plan-edit disarms, abort is never gated), plus the coordinator Execute sequence
(``arm_hv`` + ``start_plan`` with the armed-envelope gate).

Same idiom as ``test_planner_panel.py``: ``QT_QPA_PLATFORM=offscreen``, a shared
``QApplication.instance()``, no pytest-qt, no real dialogs.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from controller.arm_envelope import ArmedEnvelope, ArmedEnvelopeGate
from controller.scan_plan_validator import PlanLimits
import gui.planner_panel as planner_module
from gui.arm_latch import ARMED_TIMEOUT_S, ArmLatch
from gui.planner_panel import PlannerPanel
from gui.scan_coordinator import ScanCoordinator


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _press(btn) -> None:
    btn.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(5, 5),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier))


def _release(btn, inside: bool = True) -> None:
    pt = QPointF(5, 5) if inside else QPointF(-50, -50)
    btn.mouseReleaseEvent(QMouseEvent(
        QEvent.Type.MouseButtonRelease, pt,
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier))


# --------------------------------------------------------------------------- #
# ArmLatch widget                                                             #
# --------------------------------------------------------------------------- #

def test_latch_constructs_and_survives_theme_switch():
    _app()
    latch = ArmLatch(theme_mode="light")
    try:
        assert not latch.is_armed()
        latch.refresh_theme("dark")
        latch.refresh_theme("light")
        latch.set_envelope_text("<div>hello</div>")
        assert latch._envelope_lbl.isVisibleTo(latch)
    finally:
        latch.shutdown()


def test_latch_has_no_graphics_effect():
    """Design charter: static depth only — no QGraphicsEffect on the latch or
    its command buttons."""
    _app()
    latch = ArmLatch()
    try:
        assert latch.graphicsEffect() is None
        assert latch._arm_btn.graphicsEffect() is None
        assert latch._exec_btn.graphicsEffect() is None
    finally:
        latch.shutdown()


def test_hold_completes_arms():
    _app()
    latch = ArmLatch()
    try:
        armed_hits = []
        started_hits = []
        latch.armed.connect(lambda: armed_hits.append(True))
        latch.arm_started.connect(lambda: started_hits.append(True))
        latch.set_ready(True)

        btn = latch._arm_btn
        _press(btn)
        assert btn._hold_active           # gesture started
        # Drive the hold ticker to completion deterministically.
        btn._progress = 0.999
        btn._on_hold_tick()

        assert latch.is_armed()
        assert armed_hits == [True]
        assert started_hits == [True]
        assert latch._exec_btn.isVisibleTo(latch)   # Execute revealed
    finally:
        latch.shutdown()


def test_release_before_hold_completes_cancels():
    _app()
    latch = ArmLatch()
    try:
        latch.set_ready(True)
        btn = latch._arm_btn
        _press(btn)
        assert btn._hold_active
        # Release well before HOLD_MS elapses, outside the button rect.
        _release(btn, inside=False)
        assert not btn._hold_active
        assert not latch.is_armed()
    finally:
        latch.shutdown()


def test_leaving_button_mid_hold_cancels():
    _app()
    latch = ArmLatch()
    try:
        latch.set_ready(True)
        btn = latch._arm_btn
        _press(btn)
        btn._progress = 0.5
        # Cursor leaves the button rect → hold cancels (no arm).
        btn.mouseMoveEvent(QMouseEvent(
            QEvent.Type.MouseMove, QPointF(-100, -100),
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
        assert not btn._hold_active
        assert not latch.is_armed()
    finally:
        latch.shutdown()


def test_press_twice_arms():
    _app()
    latch = ArmLatch()
    try:
        latch.set_ready(True)
        # Two activations inside the window (keyboard parity: QPushButton.click()
        # emits `clicked` exactly like Enter/Space does).
        latch._arm_btn.click()
        assert not latch.is_armed()       # one press is not enough
        latch._arm_btn.click()
        assert latch.is_armed()
    finally:
        latch.shutdown()


def test_single_press_does_not_arm():
    _app()
    latch = ArmLatch()
    try:
        latch.set_ready(True)
        latch._arm_btn.click()
        assert not latch.is_armed()
    finally:
        latch.shutdown()


def test_not_ready_refuses_arm_and_shows_reason():
    _app()
    latch = ArmLatch()
    try:
        latch.set_ready(False, "Dry run the recipe first.")
        assert not latch._arm_btn.isEnabled()
        assert "Dry run" in latch._hint.text()
        # Even a full gesture cannot arm while not ready.
        latch._arm_btn.click()
        latch._arm_btn.click()
        assert not latch.is_armed()
    finally:
        latch.shutdown()


def test_timeout_disarms():
    _app()
    latch = ArmLatch()
    try:
        disarms = []
        latch.disarmed.connect(lambda r: disarms.append(r))
        latch.set_ready(True)
        latch._arm_btn.click()
        latch._arm_btn.click()
        assert latch.is_armed()
        # Fast-forward the countdown to its final tick.
        latch._seconds_left = 1
        latch._on_countdown_tick()
        assert not latch.is_armed()
        assert disarms == ["timeout"]
    finally:
        latch.shutdown()


def test_click_when_armed_disarms():
    _app()
    latch = ArmLatch()
    try:
        latch.set_ready(True)
        latch._arm_btn.click()
        latch._arm_btn.click()
        assert latch.is_armed()
        latch._arm_btn.click()            # single click while armed → disarm
        assert not latch.is_armed()
    finally:
        latch.shutdown()


def test_execute_only_fires_when_armed():
    _app()
    latch = ArmLatch()
    try:
        hits = []
        latch.execute_requested.connect(lambda: hits.append(True))
        # Not armed → Execute is a no-op.
        latch._on_execute_clicked()
        assert hits == []
        latch.set_ready(True)
        latch._arm_btn.click()
        latch._arm_btn.click()
        latch._exec_btn.click()
        assert hits == [True]
        assert not latch.is_armed()       # Execute consumes the latch
    finally:
        latch.shutdown()


def test_default_timeout_is_ten_seconds():
    assert ARMED_TIMEOUT_S == 10


# --------------------------------------------------------------------------- #
# PlannerPanel integration                                                    #
# --------------------------------------------------------------------------- #

def test_panel_latch_enabled_by_default_hides_legacy_buttons():
    _app()
    panel = PlannerPanel()
    try:
        assert panel._latch_enabled is True
        assert panel._latch.isVisibleTo(panel)
        assert not panel._btn_arm.isVisibleTo(panel)
        assert not panel._btn_start.isVisibleTo(panel)
    finally:
        panel.shutdown()


def test_panel_flag_off_keeps_legacy_arm_start(monkeypatch):
    _app()
    monkeypatch.setattr(planner_module, "_arm_latch_enabled", lambda: False)
    panel = PlannerPanel()
    try:
        assert panel._latch_enabled is False
        assert not panel._latch.isVisibleTo(panel)
        assert panel._btn_arm.isVisibleTo(panel)
        assert panel._btn_start.isVisibleTo(panel)
    finally:
        panel.shutdown()


def test_dry_run_renders_envelope_over_latch():
    _app()
    panel = PlannerPanel()
    try:
        # Before dry run the latch is not armable and says why.
        ready_ok, reason = panel._latch_readiness()
        assert ready_ok is False and "Dry run" in reason

        panel._on_dry_run_clicked()
        assert panel._dry_run_ok is True
        text = panel._latch._envelope_lbl.text()
        # The template drives HV, so the HV energization line is present and the
        # envelope summary is rendered verbatim beneath it.
        assert "Ramps HV" in text
        assert "Arm envelope:" in text
        assert panel._armed_env is not None
        assert panel._latch._arm_btn.isEnabled()
    finally:
        panel.shutdown()


def test_execute_emits_plan_and_armed_envelope_gate():
    _app()
    panel = PlannerPanel()
    try:
        received = []
        panel.execute_plan_requested.connect(
            lambda plan, gate: received.append((plan, gate)))

        panel._on_dry_run_clicked()
        panel._latch._arm_btn.click()
        panel._latch._arm_btn.click()
        assert panel._latch.is_armed()
        panel._latch._exec_btn.click()

        assert len(received) == 1
        plan, gate = received[0]
        assert plan is panel._plan
        assert isinstance(gate, ArmedEnvelopeGate)
        # The gate wraps the exact envelope rendered over the latch.
        assert gate.envelope is panel._armed_env
    finally:
        panel.shutdown()


def test_plan_edit_disarms_latch_and_clears_envelope():
    _app()
    panel = PlannerPanel()
    try:
        bias_loop = panel._plan.root[0]
        editors = panel._loop_editors[id(bias_loop)]

        panel._on_dry_run_clicked()
        panel._latch._arm_btn.click()
        panel._latch._arm_btn.click()
        assert panel._latch.is_armed()
        assert panel._latch._envelope_lbl.text()

        # Any edit invalidates the run state → the armed envelope is discarded.
        editors["step"].setValue(editors["step"].value() - 5.0)
        assert not panel._latch.is_armed()
        assert panel._latch._envelope_lbl.text() == ""
        assert panel._armed_env is None
    finally:
        panel.shutdown()


def test_running_makes_latch_inert_but_abort_is_never_latched():
    _app()
    panel = PlannerPanel()
    try:
        aborts = []
        panel.abort_requested.connect(lambda: aborts.append(True))

        # Arm, then a run starts → latch disarms and its Arm control locks.
        panel._on_dry_run_clicked()
        panel._latch._arm_btn.click()
        panel._latch._arm_btn.click()
        assert panel._latch.is_armed()

        panel.set_running(True)
        assert not panel._latch.is_armed()
        assert not panel._latch._arm_btn.isEnabled()

        # Abort is a separate always-live control — instant, never gated by the
        # latch's armed state.
        assert panel._btn_abort.isEnabled()
        panel._btn_abort.click()
        assert aborts == [True]
    finally:
        panel.shutdown()


# --------------------------------------------------------------------------- #
# Coordinator Execute sequence                                                #
# --------------------------------------------------------------------------- #

class _FakeSM:
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow

    def can(self, _state) -> bool:
        return self.allow


class _FakeScanner:
    """Records the two-step-latch Execute sequence (arm_hv + start_plan)."""

    def __init__(self) -> None:
        self.armed = None
        self.start_args = None

    def arm_hv(self, confirmed: bool) -> None:
        self.armed = bool(confirmed)

    def start_plan(self, plan, limits, gate) -> None:
        self.start_args = (plan, limits, gate)


def _envelope() -> ArmedEnvelope:
    return ArmedEnvelope(
        channels=frozenset({0}), hv_min_V=-300.0, hv_max_V=0.0,
        ramp_step_V=None, ramp_delay_s=None,
        x_bounds=None, y_bounds=None, z_bounds=None, summary="test")


def _limits() -> PlanLimits:
    return PlanLimits(
        x_min_mm=-5, x_max_mm=5, y_min_mm=-5, y_max_mm=5,
        z_min_mm=-5, z_max_mm=5, voltage_range_V=3000.0, max_points=250_000)


def test_coordinator_execute_plan_calls_start_plan_with_gate():
    _app()
    scanner = _FakeScanner()
    coord = ScanCoordinator(scanner, _FakeSM(allow=True), object(), _limits)
    gate = ArmedEnvelopeGate(_envelope())
    plan = object()

    coord.execute_plan(plan, gate)

    assert scanner.armed is True                     # HV armed as part of Execute
    assert scanner.start_args is not None
    got_plan, got_limits, got_gate = scanner.start_args
    assert got_plan is plan
    assert got_gate is gate                           # the armed-envelope gate
    assert isinstance(got_gate, ArmedEnvelopeGate)


def test_coordinator_execute_plan_refused_when_not_ready():
    _app()
    scanner = _FakeScanner()
    coord = ScanCoordinator(scanner, _FakeSM(allow=False), object(), _limits)
    hv_states = []
    coord.hv_armed.connect(lambda v: hv_states.append(v))

    coord.execute_plan(object(), ArmedEnvelopeGate(_envelope()))

    assert scanner.start_args is None                 # never started
    assert scanner.armed is False                     # un-armed on refusal
    assert hv_states == [False]                        # panel latch re-locked
