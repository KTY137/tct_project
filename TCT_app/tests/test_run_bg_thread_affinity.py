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

        def __init__(self) -> None:
            super().__init__()
            self._bg_thread = None
            self._bg_task = None
            self._bg_on_done = None

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
