"""Stage-view frame contract — marker and envelope must share the USER frame.

Bench bug (Kaya, 2026-07-11): pressing "Zero Here" on the Motor panel made the
stage visualiser's position marker JUMP to the plot origin although the stage
physically had not moved.  Root cause (same frame-mixing family as the planner
fix, commit 2f91e00 / tests/test_motor_frame_contract.py): MotorPanel fed raw
``motor.limits`` — MACHINE frame for GRBL — to the StageView once at build
time and never refreshed it, while the marker is driven from ``get_position()``
(USER frame).  Zero Here shifts the user frame, so the marker teleported to
(0, 0) inside an envelope still drawn in the old frame.

Contract pinned here (docs/ARCHITECTURE.md "Motor frame contract"): the stage
view's envelope is ``motor.limits_user_frame()``, re-pulled on
``MotorPanel.origin_changed`` (home / Zero Here), so after Zero Here the
envelope shifts by exactly the old user position and the marker's RELATIVE
position inside it is unchanged.  The soft-limit status chip compares the
poller's user-frame position against the same user-frame limits (raw machine
limits flagged a false "X soft-limit error" right after Zero Here).

Idiom follows test_cockpit_batch_b_panels.py: ``QT_QPA_PLATFORM=offscreen``,
shared QApplication, no pytest-qt, simulated backends only —
``GRBLMotorStage(simulation=True)``, the backend that actually models the
user/machine display offset.
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from controller.danger_gate import AutoConfirmGate
from devices.motor_base import SoftwareLimits
from devices.motor_grbl import GRBLMotorStage
from gui.motor_panel import MotorPanel
from gui.stage_view import _HAS_PG


# Kaya's stage envelope (machine frame) — same as test_motor_frame_contract.py.
_MACHINE_LIMITS = SoftwareLimits(
    x_min=1.0, x_max=296.0, y_min=0.0, y_max=298.0, z_min=0.0, z_max=50.0,
)


# --------------------------------------------------------------------------- #
# Harness helpers (idiom: test_cockpit_batch_b_panels.py)                      #
# --------------------------------------------------------------------------- #

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
    """Orderly deferred-delete teardown (see test_cockpit_batch_b_panels.py:
    pyqtgraph widgets destroyed inside gc.collect() are an access-violation
    source; shutdown + deleteLater + pump destroys the tree top-down)."""
    app = _app()
    panel.shutdown()
    panel.deleteLater()
    _pump(app, 0.1)


def _sim_grbl() -> GRBLMotorStage:
    """Simulated GRBL stage: connected + homed, default lower-corner offset."""
    motor = GRBLMotorStage(simulation=True)
    motor.limits = _MACHINE_LIMITS
    motor.connect()
    motor.home()
    return motor


def _panel(motor: GRBLMotorStage) -> MotorPanel:
    """Motor panel wired to the headless confirmation gate.

    Home and Zero Here are danger-gated (CLAUDE.md rule 2 — the gate itself is
    pinned in tests/test_motor_danger_gate.py).  These tests exercise the FRAME
    plumbing behind those actions, not the confirmation, so they auto-confirm;
    ``AutoConfirmGate`` is simulation/test-only by construction.  A panel with
    no gate would (correctly) REFUSE both ops.
    """
    return MotorPanel(motor, gate=AutoConfirmGate())


def _run_panel_op(app: QApplication, panel: MotorPanel, op) -> None:
    """Drive one async panel motor op (home / Zero Here) through the REAL
    worker-thread path and wait for _on_task_done to run on the GUI thread."""
    op()
    assert panel._task_thread is not None, "op did not start a worker"
    assert _pump_until(app, lambda: panel._task_thread is None), \
        "motor op did not complete"


# Plot-data probes — read what is actually rendered, not cached attributes.

def _env_rect(plot) -> tuple[float, float, float, float]:
    """(min_h, max_h, min_v, max_v) of the drawn envelope polyline."""
    x, y = plot["env"].getData()
    return (float(min(x)), float(max(x)), float(min(y)), float(max(y)))


def _marker(plot) -> tuple[float, float]:
    x, y = plot["pos"].getData()
    return (float(x[0]), float(y[0]))


def _close(a, b, tol: float = 1e-6) -> bool:
    return all(abs(p - q) <= tol for p, q in zip(a, b))


def _skip_without_pg() -> None:
    if not _HAS_PG:
        pytest.skip("pyqtgraph required for the stage-view plot probes")


# --------------------------------------------------------------------------- #
# Core regression: Zero Here shifts the envelope WITH the marker               #
# --------------------------------------------------------------------------- #

def test_zero_here_envelope_shifts_with_marker():
    _skip_without_pg()
    app = _app()
    motor = _sim_grbl()
    motor.move_to(5.0, 5.0, 5.0)          # user frame; sim move is synchronous
    panel = _panel(motor)
    try:
        top = panel._stage_view._v2d._top
        side = panel._stage_view._v2d._side

        # Envelope at build time is already the USER frame (offset = lower
        # machine corner (1, 0, 0) → x 0..295, y 0..298, z 0..50).
        assert _env_rect(top) == pytest.approx((0.0, 295.0, 0.0, 298.0))
        assert _env_rect(side) == pytest.approx((0.0, 295.0, 0.0, 50.0))

        # Wait for the live poller to draw the pre-zero marker.
        assert _pump_until(app, lambda: _close(_marker(top), (5.0, 5.0)))
        top_before = _env_rect(top)
        side_before = _env_rect(side)
        mx, my = _marker(top)
        rel_before = (
            (mx - top_before[0]) / (top_before[1] - top_before[0]),
            (my - top_before[2]) / (top_before[3] - top_before[2]),
        )

        # Zero Here through the real async path (worker thread → done →
        # origin_changed → _refresh_stage_limits).
        _run_panel_op(app, panel, panel._zero_position)

        # Reported user position is the new origin...
        pos = motor.get_position()
        assert pos.x_mm == pytest.approx(0.0)
        assert pos.y_mm == pytest.approx(0.0)
        assert pos.z_mm == pytest.approx(0.0)

        # ...and the marker converges there via the poller.
        assert _pump_until(app, lambda: _close(_marker(top), (0.0, 0.0)))
        assert _close(_marker(side), (0.0, 0.0))

        # THE FIX: the envelope shifted by exactly the old user position
        # (-5 on every axis), so the marker did not teleport within it.
        top_after = _env_rect(top)
        side_after = _env_rect(side)
        assert top_after == pytest.approx(
            tuple(v - 5.0 for v in top_before))
        assert side_after == pytest.approx(
            tuple(v - 5.0 for v in side_before))

        # Marker's RELATIVE position inside the envelope is unchanged.
        rel_after = (
            (0.0 - top_after[0]) / (top_after[1] - top_after[0]),
            (0.0 - top_after[2]) / (top_after[3] - top_after[2]),
        )
        assert rel_after == pytest.approx(rel_before)
    finally:
        _dispose(panel)


def test_marker_tracks_real_moves_after_zero_here():
    """After Zero Here, a genuine move must move the marker (no frozen view)
    while the envelope stays put — position changes, frame does not."""
    _skip_without_pg()
    app = _app()
    motor = _sim_grbl()
    motor.move_to(5.0, 5.0, 5.0)
    panel = _panel(motor)
    try:
        top = panel._stage_view._v2d._top
        side = panel._stage_view._v2d._side
        _run_panel_op(app, panel, panel._zero_position)
        assert _pump_until(app, lambda: _close(_marker(top), (0.0, 0.0)))
        env_top = _env_rect(top)

        motor.move_to(2.0, 3.0, 1.0)      # user frame, inside shifted limits
        assert _pump_until(app, lambda: _close(_marker(top), (2.0, 3.0)))
        assert _close(_marker(side), (2.0, 1.0))
        assert _env_rect(top) == pytest.approx(env_top)   # frame unchanged
    finally:
        _dispose(panel)


def test_home_restores_default_frame_envelope():
    """Home resets the display offset (GRBL: _zero → None, lower-corner
    default) — the envelope must follow it back, not stay in the zeroed
    frame ('and on home' half of the refresh contract)."""
    _skip_without_pg()
    app = _app()
    motor = _sim_grbl()
    motor.move_to(5.0, 5.0, 5.0)
    panel = _panel(motor)
    try:
        top = panel._stage_view._v2d._top
        _run_panel_op(app, panel, panel._zero_position)
        assert _env_rect(top) == pytest.approx((-5.0, 290.0, -5.0, 293.0))

        _run_panel_op(app, panel, panel._home)
        assert _env_rect(top) == pytest.approx((0.0, 295.0, 0.0, 298.0))
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# Same frame-mixing family: the soft-limit chip after Zero Here                #
# --------------------------------------------------------------------------- #

def test_soft_limit_chip_uses_user_frame_after_zero_here():
    """Position (0,0,0) right after Zero Here is deep inside the (shifted)
    envelope — the chip must read 'Soft limits ok'.  Comparing against raw
    machine limits (x_min = 1) wrongly flagged 'X soft-limit error'."""
    _skip_without_pg()
    app = _app()
    motor = _sim_grbl()
    motor.move_to(5.0, 5.0, 5.0)
    panel = _panel(motor)
    try:
        _run_panel_op(app, panel, panel._zero_position)
        assert _pump_until(
            app, lambda: panel._chip_limits.text() == "Soft limits ok")
        assert panel._chip_limits.property("state") == "neutral"
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# C4 theme wiring stays intact through an origin change                        #
# --------------------------------------------------------------------------- #

def test_theme_switch_after_zero_here_keeps_frame_and_tokens():
    """refresh_theme after an origin change must restyle without disturbing
    the user-frame geometry (construction + theme-switch smoke)."""
    _skip_without_pg()
    app = _app()
    motor = _sim_grbl()
    motor.move_to(5.0, 5.0, 5.0)
    panel = _panel(motor)
    try:
        top = panel._stage_view._v2d._top
        _run_panel_op(app, panel, panel._zero_position)
        env = _env_rect(top)

        panel.refresh_theme("dark")
        assert panel._stage_view._theme_mode == "dark"
        assert panel._stage_view._v2d._theme_mode == "dark"
        assert _env_rect(top) == pytest.approx(env)   # geometry untouched

        panel.refresh_theme("light")
        assert panel._stage_view._v2d._theme_mode == "light"
        assert _env_rect(top) == pytest.approx(env)
    finally:
        _dispose(panel)
