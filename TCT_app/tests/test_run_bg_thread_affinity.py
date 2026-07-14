"""Thread-affinity regression for the two single-slot background runners
(``tct_gui.TCTMainWindow._run_bg`` and ``gui.device_panel.DeviceManagerWindow.
_run_bg``).

Bug beat (2026-07-14, Kaya's live bench crash + hard freeze). Both runners used
to connect ``_bg_task.done`` to a **bare nested closure** — a callable with no
receiver ``QObject``. Because the emitting task had been ``moveToThread``'d onto
the worker, PySide6 delivered that slot on the **worker** thread. The closure
then ran widget access, panel rebuilds, state-machine transitions and a modal
``QMessageBox`` off the GUI thread (the intermittent crash + the hard freeze),
and its ``thread.wait(2000)`` was the worker waiting on itself.

Paul's thread-id probe proved the fix empirically: a bare-closure slot fires on
the worker thread, but a slot that is a **bound method of a GUI-thread QObject**
fires on the GUI thread under queued delivery. These tests pin that contract for
both real implementations, and that a worker error still reaches ``on_done``.

No hardware: fully simulated device manager, offscreen Qt.
"""
from __future__ import annotations

import os
import threading
import time

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _pump(app, seconds: float = 0.1) -> None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        app.processEvents()
        time.sleep(0.01)


def _sim_device_manager(tmp_path):
    from controller.device_manager import DeviceManager
    cfg = {
        "oscilloscope":       {"backend": "visa", "simulation": True},
        "motor_stage":        {"backend": "simulated"},
        "intensity_monitor":  {"backend": "simulated"},
        "camera":             {"simulation": True},
        "waveform_generator": {"simulation": True},
        "bias_supply":        {"backend": "simulated"},
        "output":             {"data_dir": str(tmp_path / "runs")},
    }
    path = tmp_path / "devices.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return DeviceManager(config_path=str(path))


def _drive(win, app, fn, timeout: float = 5.0):
    """Run *fn* through *win*._run_bg and pump the GUI event loop until the
    done-handler fires. Returns (main_tid, captured-dict)."""
    main_tid = threading.get_ident()
    cap: dict = {}

    def on_done(result, err):
        cap["done_tid"] = threading.get_ident()
        cap["result"] = result
        cap["err"] = err

    started = win._run_bg(fn, on_done)
    assert started is True, "_run_bg refused to start (unexpected busy state)"

    deadline = time.monotonic() + timeout
    while "done_tid" not in cap and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert "done_tid" in cap, "on_done never fired within the deadline"
    return main_tid, cap


# --------------------------------------------------------------------------- #
# Device Manager window — real DeviceManagerWindow._run_bg / _bg_finished      #
# --------------------------------------------------------------------------- #

def test_device_panel_done_delivered_on_gui_thread(qapp, tmp_path):
    """The worker fn runs off the GUI thread, but the done-handler must be
    delivered back on the GUI thread (the bound-method receiver, not a closure
    on the worker)."""
    from gui.device_panel import DeviceManagerWindow

    win = DeviceManagerWindow(_sim_device_manager(tmp_path))
    try:
        worker: dict = {}

        def fn():
            worker["tid"] = threading.get_ident()
            return "payload"

        main_tid, cap = _drive(win, qapp, fn)
        assert worker["tid"] != main_tid, "worker fn did not run off the GUI thread"
        assert cap["done_tid"] == main_tid, \
            "on_done was delivered on the WORKER thread (the crash/freeze bug)"
        assert cap["result"] == "payload"
        assert cap["err"] == ""
        # The single-slot state was cleared on the GUI thread.
        assert win._bg_thread is None and win._bg_task is None
    finally:
        win.shutdown()
        _pump(qapp)


def test_device_panel_worker_error_reaches_on_done_on_gui_thread(qapp, tmp_path):
    """A raised exception in the worker still reaches on_done as (None, text),
    and still on the GUI thread."""
    from gui.device_panel import DeviceManagerWindow

    win = DeviceManagerWindow(_sim_device_manager(tmp_path))
    try:
        worker: dict = {}

        def fn():
            worker["tid"] = threading.get_ident()
            raise RuntimeError("kaboom")

        main_tid, cap = _drive(win, qapp, fn)
        assert worker["tid"] != main_tid
        assert cap["done_tid"] == main_tid
        assert cap["result"] is None
        assert "kaboom" in cap["err"]
    finally:
        win.shutdown()
        _pump(qapp)


# --------------------------------------------------------------------------- #
# Main window — REAL TCTMainWindow._run_bg / _bg_finished on a light QObject.   #
#                                                                              #
# Building the whole main window would start every device thread for no extra  #
# coverage of this branch, so we bind the *actual* method objects onto a       #
# minimal GUI-thread QObject. The bound-method receiver is therefore genuine   #
# (a real QObject), and the methods carry tct_gui's module globals, so         #
# notify/_BgTask/QThread/Qt resolve exactly as in production.                  #
# --------------------------------------------------------------------------- #

def _main_stub():
    from PySide6.QtCore import QObject
    from tct_gui import TCTMainWindow

    class _MainStub(QObject):
        _run_bg = TCTMainWindow._run_bg
        _bg_finished = TCTMainWindow._bg_finished
        # The real teardown choke-point closeEvent uses.  Every device/panel/QML
        # attribute it touches is read via getattr/hasattr, so a bare QObject
        # exercises only the branch under test: the in-flight ``_bg_thread`` join.
        # (``_device_manager_window`` is the one attribute read directly, and
        # ``_scanner.abort()`` is try/except-guarded — both harmless when None.)
        _teardown_panels = TCTMainWindow._teardown_panels

        def __init__(self) -> None:
            super().__init__()
            self._bg_thread = None
            self._bg_task = None
            self._bg_on_done = None
            self._device_manager_window = None

    return _MainStub()


def test_main_window_done_delivered_on_gui_thread(qapp):
    stub = _main_stub()
    try:
        worker: dict = {}

        def fn():
            worker["tid"] = threading.get_ident()
            return "payload"

        main_tid, cap = _drive(stub, qapp, fn)
        assert worker["tid"] != main_tid, "worker fn did not run off the GUI thread"
        assert cap["done_tid"] == main_tid, \
            "on_done was delivered on the WORKER thread (the crash/freeze bug)"
        assert cap["result"] == "payload"
        assert cap["err"] == ""
        assert stub._bg_thread is None and stub._bg_task is None
    finally:
        stub.deleteLater()
        _pump(qapp)


def test_main_window_worker_error_reaches_on_done_on_gui_thread(qapp):
    stub = _main_stub()
    try:
        worker: dict = {}

        def fn():
            worker["tid"] = threading.get_ident()
            raise RuntimeError("kaboom")

        main_tid, cap = _drive(stub, qapp, fn)
        assert worker["tid"] != main_tid
        assert cap["done_tid"] == main_tid
        assert cap["result"] is None
        assert "kaboom" in cap["err"]
    finally:
        stub.deleteLater()
        _pump(qapp)


# --------------------------------------------------------------------------- #
# Teardown while a _run_bg is in-flight — the "QThread: Destroyed while thread #
# is still running" hard crash (Mary's RISK rider, e0a9d91).                   #
#                                                                              #
# The window's [X] stays live even while _act_connect is disabled, so a user   #
# can close during an in-flight connect.  _teardown_panels() must join the     #
# in-flight worker (bounded quit()+wait()) BEFORE the window is destroyed, and #
# must NOT invoke the stashed on_done afterwards (panel rebuilds / dialogs off  #
# a dying window).                                                             #
# --------------------------------------------------------------------------- #

def test_teardown_joins_in_flight_bg_thread_and_drops_on_done(qapp):
    stub = _main_stub()
    try:
        worker: dict = {}
        gate = threading.Event()              # holds the worker in-flight
        teardown_started = threading.Event()  # main -> releaser handshake
        on_done_calls: list = []

        def on_done(result, err):
            on_done_calls.append((result, err))

        def fn():
            worker["tid"] = threading.get_ident()
            worker["blocked"] = True
            # Deterministic gate + bounded fallback (never a bare sleep / hang).
            gate.wait(5.0)
            return "payload"

        # Release the gate the instant teardown begins, from a SEPARATE thread:
        # _teardown_panels()'s wait() blocks the GUI thread, so the worker can
        # only complete (letting that wait() return) via an off-thread release.
        def releaser():
            teardown_started.wait(5.0)
            gate.set()

        rel = threading.Thread(target=releaser, daemon=True)
        rel.start()

        assert stub._run_bg(fn, on_done) is True
        # Confirm the worker genuinely reached the blocking point in-flight.
        deadline = time.monotonic() + 5.0
        while not worker.get("blocked") and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.005)
        assert worker.get("blocked") is True, "worker never entered its blocking wait"
        assert stub._bg_thread is not None and stub._bg_thread.isRunning()

        # Close/teardown the window while the worker is in-flight; the releaser
        # sets the gate so the bounded wait() joins the thread rather than hanging.
        teardown_started.set()
        stub._teardown_panels()   # must not crash

        # The single-slot state is cleared and the thread is fully joined.
        assert stub._bg_thread is None
        assert stub._bg_task is None
        assert stub._bg_on_done is None
        rel.join(5.0)
        assert not rel.is_alive()

        # A `done` may have been queued to the GUI thread before run() returned;
        # pump the loop so it is delivered.  _bg_finished must find the nulled
        # refs and DROP the callback — on_done never runs after teardown.
        _pump(qapp, 0.2)
        assert on_done_calls == [], \
            "on_done was invoked after teardown (panel rebuild off a dying window)"
    finally:
        gate.set()
        stub.deleteLater()
        _pump(qapp)
