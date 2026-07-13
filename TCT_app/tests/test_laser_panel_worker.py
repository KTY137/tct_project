"""Headless GUI tests for the Laser panel's off-thread VISA worker
(FREEZE half of the bench reconnect bug, 2026-07-10).

Symptom: every waveform-generator set/query ran in the GUI slot (Apply,
each spinbox ``editingFinished``, Test Connection).  On a dead LAN peer a
single call blocks ≥5 s at the socket layer, freezing the whole window.

Fix: the blocking calls run on ``_LaserWorker`` (a dedicated QThread), driven
by *queued* invocations so writes apply in the exact order the user made them.
The GUI stays responsive; a busy chip / button state is the visible cue.  The
panel gains ``shutdown()`` (bounded join) and is added to
``tct_gui._teardown_panels``.  All tests use the simulated backend — no VISA.
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


def _pump(app, seconds: float = 0.2) -> None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        app.processEvents()
        time.sleep(0.01)


def _pump_until(app, pred, timeout: float = 5.0) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if pred():
            return True
        app.processEvents()
        time.sleep(0.005)
    return pred()


def _panel(wfg):
    from devices.laser_manual import LaserManualMetadata
    from gui.laser_panel import LaserPanel
    return LaserPanel(LaserManualMetadata(), wfg)


def _connected_wfg():
    from devices.waveform_generator import WaveformGenerator
    wfg = WaveformGenerator(simulation=True)
    wfg.connect()
    return wfg


# --------------------------------------------------------------------------- #
# The GUI event loop stays responsive while a slow write runs off-thread       #
# --------------------------------------------------------------------------- #

def test_apply_runs_off_thread_keeps_gui_responsive(qapp):
    """Apply submits a batch of setters to the worker; monkeypatch one to
    block, then prove the GUI event loop keeps ticking (a GUI-thread QTimer
    heartbeat still advances) while that write is stuck — the old synchronous
    path would have frozen it solid."""
    from PySide6.QtCore import QTimer

    wfg = _connected_wfg()
    panel = _panel(wfg)

    started = threading.Event()
    release = threading.Event()

    def slow_set_frequency(_hz):
        started.set()
        release.wait(timeout=5)

    wfg.set_frequency = slow_set_frequency   # runs on the worker thread

    ticks = {"n": 0}
    beat = QTimer()
    beat.setInterval(10)
    beat.timeout.connect(lambda: ticks.__setitem__("n", ticks["n"] + 1))
    beat.start()
    try:
        panel._apply_wfg()
        assert started.wait(timeout=3), "worker never entered the slow setter"
        # The write is stuck on the worker thread — the GUI loop must not be.
        before = ticks["n"]
        _pump(qapp, 0.2)
        assert ticks["n"] - before >= 3, \
            "GUI event loop was blocked during the off-thread write"
        release.set()
        assert _pump_until(qapp, lambda: panel._pending == 0), "job never drained"
    finally:
        beat.stop()
        release.set()
        panel.shutdown()
        _pump(qapp, 0.2)


def test_live_edits_apply_in_submission_order(qapp):
    """Writes must reach the instrument in the order the user made them — the
    worker's queued event loop is the FIFO.  Submit three live edits and assert
    the recorded call order matches."""
    wfg = _connected_wfg()
    panel = _panel(wfg)

    order: list[tuple[str, float]] = []
    wfg.set_frequency = lambda v: order.append(("freq", v))
    wfg.set_amplitude = lambda v: order.append(("ampl", v))
    wfg.set_offset = lambda v: order.append(("offset", v))
    try:
        panel._live_apply(wfg.set_frequency, 1000.0)
        panel._live_apply(wfg.set_amplitude, 2.0)
        panel._live_apply(wfg.set_offset, 0.5)
        assert _pump_until(qapp, lambda: panel._pending == 0), "jobs never drained"
        assert order == [("freq", 1000.0), ("ampl", 2.0), ("offset", 0.5)]
    finally:
        panel.shutdown()
        _pump(qapp, 0.2)


def test_disconnected_live_apply_does_not_touch_worker(qapp):
    """A live edit while the wavegen is not connected stays synchronous: it
    reports 'staged' immediately and enqueues nothing (no false 'busy')."""
    from devices.waveform_generator import WaveformGenerator

    wfg = WaveformGenerator(simulation=False)   # no session
    panel = _panel(wfg)
    try:
        panel._live_apply(wfg.set_frequency, 1234.0)
        assert panel._pending == 0
        assert "stag" in panel._chip_wfg.text().lower()
    finally:
        panel.shutdown()
        _pump(qapp, 0.2)


# --------------------------------------------------------------------------- #
# Bounded shutdown even with a write in flight                                  #
# --------------------------------------------------------------------------- #

def test_shutdown_bounded_when_write_in_flight(qapp):
    """A wavegen write can block ≥5 s on a dead peer; shutdown() must RETURN
    within its bound (never hang the GUI thread waiting for the socket)."""
    wfg = _connected_wfg()
    panel = _panel(wfg)

    started = threading.Event()
    release = threading.Event()

    def slow(_v):
        started.set()
        release.wait(timeout=5)

    wfg.set_frequency = slow
    try:
        panel._live_apply(wfg.set_frequency, 1.0)
        assert started.wait(timeout=3), "worker never entered the slow write"
        t0 = time.monotonic()
        panel.shutdown()
        elapsed = time.monotonic() - t0
        assert elapsed < 4.0, \
            f"shutdown() blocked {elapsed:.2f}s — the wait must be bounded"
    finally:
        release.set()          # let the still-running write finish + self-clean
        _pump(qapp, 0.5)


def test_worker_thread_not_parented_to_panel(qapp):
    """Structural guard (MotorPanel crash class): the VISA worker QThread must
    not be a child of the panel that setCentralWidget() can delete mid-call."""
    wfg = _connected_wfg()
    panel = _panel(wfg)
    try:
        assert panel._laser_thread is not None
        assert panel._laser_thread.parent() is not panel
    finally:
        panel.shutdown()
        _pump(qapp, 0.2)


# --------------------------------------------------------------------------- #
# Shared busy chip settles after jobs whose callbacks paint a different chip   #
# --------------------------------------------------------------------------- #

def test_busy_chip_settles_after_output_toggle(qapp):
    """Mary S2-freeze review nit: an isolated Output ON/OFF settles
    _chip_output, not _chip_wfg — the shared "Wavegen busy…" indicator must
    still resolve when the queue drains (and must NOT overwrite a more
    specific state another callback painted)."""
    wfg = _connected_wfg()
    panel = _panel(wfg)
    try:
        panel._output_off()
        assert panel._chip_wfg.text() == "Wavegen busy…"
        assert _pump_until(qapp, lambda: panel._pending == 0), "job never drained"
        _pump(qapp, 0.1)
        assert panel._chip_wfg.text() != "Wavegen busy…", \
            "shared busy chip latched after an output toggle"
    finally:
        panel.shutdown()
        _pump(qapp, 0.2)


# --------------------------------------------------------------------------- #
# Rule-5 safety net: a queued OFF discarded by shutdown() is rescued by the    #
# teardown -> disconnect_all ordering (WaveformGenerator.disconnect forces     #
# output_off for an armed output).  Pins the ordering dependency.              #
# --------------------------------------------------------------------------- #

def test_queued_output_off_rescued_by_teardown_order(qapp):
    """Arm the output, wedge the worker so a queued OFF cannot start, shut the
    panel down (discarding the queued OFF), then run the disconnect step that
    every teardown path performs after panel teardown — the wavegen output
    must end OFF."""
    wfg = _connected_wfg()
    panel = _panel(wfg)

    started = threading.Event()
    release = threading.Event()
    real_set_frequency = wfg.set_frequency

    def slow(_v):
        started.set()
        release.wait(timeout=5)
        real_set_frequency(_v)

    try:
        wfg.output_on()
        assert wfg.output_is_on

        wfg.set_frequency = slow
        panel._live_apply(wfg.set_frequency, 1000.0)   # wedges the worker
        assert started.wait(timeout=3)
        panel._output_off()                            # queued, never starts

        panel.shutdown()                               # discards the queued OFF
        release.set()
        _pump(qapp, 0.3)

        # The rescue every teardown path relies on (tct_gui order:
        # _teardown_panels() THEN disconnect_all() -> wavegen.disconnect()).
        wfg.disconnect()
        assert not wfg.output_is_on, \
            "queued OFF was lost AND disconnect() did not force output_off"
    finally:
        release.set()
        panel.shutdown()
        _pump(qapp, 0.2)
