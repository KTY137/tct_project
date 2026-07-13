"""Headless GUI tests for the Camera panel's off-thread frame worker
(FREEZE half of the bench reconnect bug, 2026-07-10).

Symptom: the Camera panel ran all PySpin I/O on the GUI thread — a 100 ms
``QTimer`` → ``_refresh`` → ``get_frame_with_meta()`` (``GetNextImage(2000)``)
plus ``get_temperature()`` / ``get_fps_actual()``.  A pulled USB3 camera blocked
the event loop ~2 s per tick (the frozen GUI), and even a healthy link left the
loop stuck inside PySpin most of the time.

Fix: acquisition moves to ``_CameraWorker`` on a dedicated QThread (mirroring
``motor_panel._PositionPoller`` / ``tct_gui._BiasPoller``); the GUI thread only
renders frames delivered via a queued signal.  The panel gains ``shutdown()``
(bounded join) and is added to ``tct_gui._teardown_panels``.  All tests run
against the simulated backend — no hardware, no PySpin.
"""
from __future__ import annotations

import os
import threading
import time

import numpy as np
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


def _panel(cam):
    from gui.camera_panel import CameraPanel
    return CameraPanel(cam)


# --------------------------------------------------------------------------- #
# Mono16 display windowing (Kaya's "aliasing" bug) — the old path was          #
# ``(frame >> 4).astype(uint8)``: a fixed 12-bit assumption that hard-          #
# truncated the low 8 bits, wrapping a smooth gradient every 256 counts.        #
# --------------------------------------------------------------------------- #

def test_mono16_display_uses_full_window_no_truncation(qapp):
    """A narrow-dynamic-range Mono16 frame (values in a small band) must be
    autoscaled across the full 0..255 display range — the old ``>>4`` path
    left it a near-black, contrast-free band."""
    from gui.camera_panel import CameraPanel

    frame = np.linspace(1000, 1100, 64 * 64, dtype=np.uint16).reshape(64, 64)
    disp = CameraPanel._to_display_8bit(frame)

    assert disp.dtype == np.uint8
    # New window spans the range; old truncation would not.
    assert disp.min() <= 5 and disp.max() >= 250
    assert int(disp.max()) - int(disp.min()) > 200
    old = (frame >> 4).astype(np.uint8)              # the removed path
    assert int(old.max()) - int(old.min()) < 20      # ~no contrast — the bug


def test_mono16_display_is_monotonic_no_wrap(qapp):
    """A full-scale 16-bit ramp (Mono16 is 12-bit left-justified, values up to
    ~65535): the old ``>>4`` recovered 0..4095 and the uint8 cast then wrapped
    every 256 counts (the sawtooth 'aliasing'); the windowed map is monotonic."""
    from gui.camera_panel import CameraPanel

    frame = np.linspace(0, 65535, 4096, dtype=np.uint16).reshape(64, 64)
    disp = CameraPanel._to_display_8bit(frame).ravel().astype(int)
    assert np.all(np.diff(disp) >= 0)                # monotonic — no wrap
    old = (frame >> 4).astype(np.uint8).ravel().astype(int)
    assert not np.all(np.diff(old) >= 0)             # old path wraps (sawtooth)


def test_mono8_display_passthrough_unchanged(qapp):
    """Mono8 frames must pass straight through the display conversion — their
    native range already is the display range (behaviour preserved)."""
    from gui.camera_panel import CameraPanel

    frame = np.arange(256, dtype=np.uint8).reshape(16, 16)
    disp = CameraPanel._to_display_8bit(frame)
    assert disp.dtype == np.uint8
    assert np.array_equal(disp, frame)


# --------------------------------------------------------------------------- #
# The worker actually streams frames to the GUI thread                         #
# --------------------------------------------------------------------------- #

def test_panel_streams_frames_from_worker(qapp):
    """A connected (simulated) camera → the worker grabs off-thread and the
    GUI render slot lands a frame + updates the beam stats and the live chip,
    with zero device I/O on the GUI thread."""
    from devices.camera_blackfly import BlackflyCamera

    cam = BlackflyCamera(simulation=True)
    cam.connect()
    panel = _panel(cam)
    try:
        assert _pump_until(qapp, lambda: panel._last_frame is not None), \
            "no frame reached the GUI thread from the worker"
        assert panel._last_meta is not None
        # The render slots ran: live chip flipped, a beam-stat readout filled.
        assert "live" in panel._chip_camera.text().lower()
        assert panel._ro_mean.value() not in ("-", "")
    finally:
        panel.shutdown()
        _pump(qapp, 0.2)


def test_camera_panel_construct_and_theme_switch(qapp):
    """Construction + refresh_theme() smoke test (per the panel-change rule):
    the histogram-bar accent brush is cached at build time; refresh_theme()
    must re-resolve it from gui.style tokens for BOTH themes (zero inline hex)."""
    import pyqtgraph as pg

    from devices.camera_blackfly import BlackflyCamera
    from gui.style import DARK, LIGHT

    cam = BlackflyCamera(simulation=True)
    cam.connect()
    panel = _panel(cam)
    try:
        panel.refresh_theme("dark")
        assert (panel._hist_brush().color().name().lower()
                == pg.mkColor(DARK["accent"]).name().lower())
        panel.refresh_theme("light")
        assert (panel._hist_brush().color().name().lower()
                == pg.mkColor(LIGHT["accent"]).name().lower())
    finally:
        panel.shutdown()
        _pump(qapp, 0.2)


def test_panel_reports_offline_when_camera_not_connected(qapp):
    """Never-connected camera → the worker emits offline() and the chips read
    the neutral offline state (the old _refresh not-connected branch)."""
    from devices.camera_blackfly import BlackflyCamera

    cam = BlackflyCamera(simulation=True)   # not connected
    panel = _panel(cam)
    try:
        assert _pump_until(
            qapp, lambda: "offline" in panel._chip_camera.text().lower())
        assert panel._last_frame is None
    finally:
        panel.shutdown()
        _pump(qapp, 0.2)


# --------------------------------------------------------------------------- #
# Worker lifecycle: bounded shutdown even with a slow grab in flight           #
# --------------------------------------------------------------------------- #

def test_shutdown_joins_within_bound_when_grab_in_flight(qapp, monkeypatch):
    """Mirrors tests/test_motor_panel_reload.py::test_teardown_completes_when_
    poller_mid_cycle: patch get_frame_with_meta() to block, wait until a grab
    is genuinely in flight, then assert shutdown() returns within its bound
    instead of hanging for the grab's whole duration."""
    from devices.camera_blackfly import BlackflyCamera

    grab_started = threading.Event()
    release = threading.Event()
    orig = BlackflyCamera.get_frame_with_meta

    def slow_grab(self):
        grab_started.set()
        release.wait(timeout=5)
        return orig(self)

    monkeypatch.setattr(BlackflyCamera, "get_frame_with_meta", slow_grab)

    cam = BlackflyCamera(simulation=True)
    cam.connect()
    panel = _panel(cam)
    try:
        assert grab_started.wait(timeout=3), "worker never started a grab"
        t0 = time.monotonic()
        panel.shutdown()
        elapsed = time.monotonic() - t0
        # The internal wait bound is 3 s — comfortable headroom above it, and
        # nowhere near hanging until the (here indefinite) grab returns.
        assert elapsed < 4.0, \
            f"shutdown() blocked {elapsed:.2f}s while a grab was in flight"
    finally:
        release.set()          # let the still-running grab actually return
        _pump(qapp, 1.0)


def test_worker_thread_not_parented_to_panel(qapp):
    """Structural guard for the MotorPanel crash class: the worker QThread must
    NOT be a child of the panel, or setCentralWidget() deleting the panel during
    a soft reload could cascade-delete a still-running QThread (hard Qt6 abort).
    Parented to QApplication instead — it self-deletes on ``finished``."""
    from devices.camera_blackfly import BlackflyCamera

    cam = BlackflyCamera(simulation=True)
    cam.connect()
    panel = _panel(cam)
    try:
        assert panel._cam_thread is not None
        assert panel._cam_thread.parent() is not panel
    finally:
        panel.shutdown()
        _pump(qapp, 0.2)


def test_shutdown_is_idempotent(qapp):
    """Teardown may call shutdown() and then closeEvent() fire it again — the
    second call must be a harmless no-op (thread already gone)."""
    from devices.camera_blackfly import BlackflyCamera

    cam = BlackflyCamera(simulation=True)
    cam.connect()
    panel = _panel(cam)
    panel.shutdown()
    panel.shutdown()          # must not raise
    assert panel._cam_thread is None
    _pump(qapp, 0.1)


# --------------------------------------------------------------------------- #
# tct_gui._teardown_panels now stops the camera AND laser panels               #
# --------------------------------------------------------------------------- #

def test_teardown_panels_shuts_down_camera_and_laser():
    """The panels own worker threads now, so a soft config-reload / exit must
    call their shutdown().  Exercises the real ``_teardown_panels`` panel-
    iteration loop against a lightweight stub self (no full main window / no
    device threads needed to verify the wiring)."""
    from types import SimpleNamespace

    from tct_gui import TCTMainWindow

    calls: list[str] = []

    def _mk(name):
        return SimpleNamespace(shutdown=lambda n=name: calls.append(n))

    stub = SimpleNamespace(
        _light_timer=None,
        _bias_poll_thread=None,
        _liveness_thread=None,
        _danger_gate=None,
        _device_manager_window=None,
        _scanner=SimpleNamespace(abort=lambda: None),
        _motor_panel=_mk("motor"),
        _bias_panel=_mk("bias"),
        _intensity_panel=_mk("intensity"),
        _scope_panel=_mk("scope"),
        _camera_panel=_mk("camera"),
        _laser_panel=_mk("laser"),
        _calib_panel=_mk("calib"),
        _planner_panel=_mk("planner"),
        _monitor_panel=SimpleNamespace(stop_polling=lambda: calls.append("monitor")),
    )

    TCTMainWindow._teardown_panels(stub)

    assert "camera" in calls, "camera panel not torn down"
    assert "laser" in calls, "laser panel not torn down"
    # The pre-existing entries are still wired (guards against a botched edit).
    assert {"motor", "scope", "monitor"} <= set(calls)
