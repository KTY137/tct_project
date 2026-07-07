"""Headless GUI regression tests for the Motor panel soft-reload freeze
(bench bug, 2026-07-07).

Symptom: after Settings -> Save triggers a soft config-reload, the Motor
panel froze (unresponsive) and its connection indicator showed
"disconnected" even though the hardware was still connected.

``tct_gui._reload_config`` -> ``_teardown_panels`` -> ``_build_central``
disconnects every device, stops every panel-owned thread (via each panel's
``shutdown()``), then discards the old panel tree via
``setCentralWidget()``, which — per the comment in ``tct_gui._build_central``
— *deletes* the previous panels.

Two independent defects, pinned here against the simulated backend:

  * FREEZE: ``MotorPanel`` owns two worker QThreads (the position poller and
    the async task runner used by jog/home/move).  They used to be parented
    to the panel itself (``QThread(self)``).  ``shutdown()``'s waits were
    already individually bounded, but a bound is not a guarantee the thread
    has actually stopped — a home()/move() can legitimately run for up to
    ~120 s.  If the wait timed out, the still-running QThread was a *child*
    of the widget that ``setCentralWidget()`` deletes moments later —
    destroying a running QThread via Qt's parent-child cascade is a hard
    Qt6 abort (see gui/settings_window.py's ``_VisaScanManager`` docstring
    for the identical, previously-fixed class of bug).  The fix: pause the
    poller and best-effort interrupt any in-flight task via ``motor.stop()``
    (deliberately non-blocking, same call ``_emergency_stop()`` uses) before
    waiting, and — belt and suspenders — parent both worker threads to the
    long-lived QApplication instance instead of the panel, so a thread that
    outlives the bounded wait cleans itself up later via its own
    quit -> finished -> deleteLater chain instead of being destroyed mid-run.

  * STALE DISPLAY: the panel's own connected/homed chip only used to update
    from a successful poller tick (``position_updated`` -> emitted only
    after ``get_position()`` succeeds).  The poller intentionally never
    calls ``get_position()`` on a disconnected motor, so a freshly-built
    panel for a not-yet-connected device (exactly the post-reload state,
    "Config reloaded - click Connect All") was stuck showing its
    construction-time default text ("Not homed" / neutral) instead of an
    accurate "Offline" — never mind "frozen".  Fixed with a lightweight,
    GUI-thread-only, I/O-free timer that reads only the plain
    ``connected``/``homed`` attributes (same pattern tct_gui.py's top-bar
    status strip already uses).
"""
from __future__ import annotations

import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _pump(app, seconds: float) -> None:
    """Process the Qt event loop for *seconds* so queued deleteLater()/signal
    deliveries actually run (same helper pattern as
    tests/test_settings_window_visa_scan.py::_pump_until)."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        app.processEvents()
        time.sleep(0.01)


class _StuckHomeMotor:
    """Minimal MotorStageBase-shaped fake whose home() blocks on an Event
    that stop() may or may not release — lets tests pin both the
    "stop() interrupts it" fast path and the worst-case bounded-wait path
    (a backend that ignores/can't honour stop() promptly)."""

    def __init__(self, stop_releases: bool) -> None:
        self._stop_releases = stop_releases
        self.connected = True
        self.homed = False
        self.limits = None
        self._release = threading.Event()
        self.stop_called = threading.Event()
        self.home_started = threading.Event()

    def get_position(self):
        from devices.motor_base import Position
        return Position(0.0, 0.0, 0.0)

    def home(self, axes=None) -> None:
        self.home_started.set()
        self._release.wait(timeout=5.0)
        self.homed = True

    def stop(self) -> None:
        self.stop_called.set()
        if self._stop_releases:
            self._release.set()


# --------------------------------------------------------------------------- #
# FREEZE: shutdown() must interrupt a stuck task and never wait unbounded     #
# --------------------------------------------------------------------------- #

def test_shutdown_stops_stuck_task_via_motor_stop(qapp):
    """The normal case: a real backend's stop() (GRBL/Marlin) is documented
    as safe/non-blocking even mid-move, so shutdown() calling it should let
    the bounded wait succeed almost immediately instead of timing out."""
    from gui.motor_panel import MotorPanel

    motor = _StuckHomeMotor(stop_releases=True)
    panel = MotorPanel(motor)
    try:
        panel._run_async(motor.home)
        assert motor.home_started.wait(timeout=2.0), "task never started"

        t0 = time.monotonic()
        panel.shutdown()
        elapsed = time.monotonic() - t0

        assert motor.stop_called.is_set(), \
            "shutdown() never called motor.stop() to interrupt the in-flight task"
        assert elapsed < 2.0, \
            f"shutdown() took {elapsed:.2f}s even though motor.stop() unblocked the task"
    finally:
        _pump(qapp, 0.2)


def test_shutdown_bounded_even_when_task_ignores_stop(qapp):
    """Worst case: the backend doesn't (or can't) honour stop() promptly.
    shutdown() must still RETURN within a bound — never hang the GUI thread
    for anywhere near the ~120s a real stuck home() could otherwise run."""
    from gui.motor_panel import MotorPanel

    motor = _StuckHomeMotor(stop_releases=False)
    panel = MotorPanel(motor)
    try:
        panel._run_async(motor.home)
        assert motor.home_started.wait(timeout=2.0), "task never started"

        t0 = time.monotonic()
        panel.shutdown()
        elapsed = time.monotonic() - t0

        assert motor.stop_called.is_set()
        # Bounded: the panel's internal wait() bounds are 3s each — comfortable
        # headroom above that, nowhere near "hangs until the move finishes".
        assert elapsed < 5.0, \
            f"shutdown() blocked for {elapsed:.2f}s — the wait must be bounded, not indefinite"
    finally:
        motor._release.set()   # let the still-running task thread actually finish
        _pump(qapp, 0.5)


def test_worker_threads_not_parented_to_the_panel(qapp):
    """Structural regression guard for the actual crash/freeze mechanism:
    gui/settings_window.py's _VisaScanManager hit the identical bug
    ("QThread: Destroyed while thread is still running" — a hard Qt6 abort,
    not a catchable Python exception) and fixed it by parenting worker
    threads to QApplication instead of the widget that can be torn down
    mid-operation.  If _poll_thread/_task_thread were ever re-parented back
    to the panel, setCentralWidget() deleting an old MotorPanel during a
    soft reload could once again cascade-delete a still-running QThread."""
    from gui.motor_panel import MotorPanel

    motor = _StuckHomeMotor(stop_releases=True)
    panel = MotorPanel(motor)
    try:
        assert panel._poll_thread.parent() is not panel

        panel._run_async(motor.home)
        assert motor.home_started.wait(timeout=2.0), "task never started"
        assert panel._task_thread is not None
        assert panel._task_thread.parent() is not panel
    finally:
        panel.shutdown()
        _pump(qapp, 0.3)


# --------------------------------------------------------------------------- #
# Soft-reload cycle: teardown must not hang while the poller is mid-cycle     #
# --------------------------------------------------------------------------- #

def test_teardown_completes_when_poller_mid_cycle(qapp, monkeypatch):
    """Mirrors the actual reload path (tct_gui._teardown_panels() calls
    MotorPanel.shutdown()): patch the poller's get_position() to sleep, wait
    until a poll is genuinely in flight, then assert shutdown() returns
    within the bound instead of hanging for the sleep's duration."""
    from gui.motor_panel import MotorPanel
    from devices.motor_simulated import SimulatedMotorStage

    poll_started = threading.Event()
    orig_get_position = SimulatedMotorStage.get_position

    def slow_get_position(self):
        poll_started.set()
        time.sleep(0.8)
        return orig_get_position(self)

    monkeypatch.setattr(SimulatedMotorStage, "get_position", slow_get_position)

    motor = SimulatedMotorStage(simulation=True)
    motor.connect()
    panel = MotorPanel(motor)
    try:
        assert poll_started.wait(timeout=2.0), "poller never started polling"
        t0 = time.monotonic()
        panel.shutdown()
        elapsed = time.monotonic() - t0
        assert elapsed < 4.0, \
            f"shutdown() blocked for {elapsed:.2f}s while the poller was mid-cycle"
    finally:
        _pump(qapp, 1.2)   # let the slow get_position() call actually return


# --------------------------------------------------------------------------- #
# STALE DISPLAY: a fresh (post-reload) panel must show accurate state        #
# --------------------------------------------------------------------------- #

def test_fresh_panel_shows_offline_immediately_when_disconnected(qapp):
    """A freshly-built panel for a not-yet-connected motor (the state right
    after a soft reload, before "Connect All") must read "Offline"
    immediately — not the construction-time default "Not homed" (which
    implies connected-but-not-homed) sitting stale forever because the
    poller never gets a successful tick to refresh it."""
    from gui.motor_panel import MotorPanel
    from devices.motor_simulated import SimulatedMotorStage

    motor = SimulatedMotorStage(simulation=True)   # never connect()
    assert motor.connected is False
    panel = MotorPanel(motor)
    try:
        assert "offline" in panel._chip_homed.text().lower()
        # Not half-initialized/frozen: ordinary motion controls stay enabled
        # (nothing latched a stale "busy" state from a previous panel).
        assert panel._btn_home.isEnabled()
    finally:
        panel.shutdown()
        _pump(qapp, 0.2)


def test_connection_chip_updates_when_motor_connects_after_panel_built(qapp):
    """Sanity check the other direction: once the device *is* connected
    (Connect All), the chip stops reading Offline on the next tick without
    needing a live poll."""
    from gui.motor_panel import MotorPanel
    from devices.motor_simulated import SimulatedMotorStage

    motor = SimulatedMotorStage(simulation=True)
    panel = MotorPanel(motor)
    try:
        assert "offline" in panel._chip_homed.text().lower()
        motor.connect()
        panel._refresh_connection_state()
        assert "offline" not in panel._chip_homed.text().lower()
        assert "not homed" in panel._chip_homed.text().lower()
    finally:
        panel.shutdown()
        _pump(qapp, 0.2)
