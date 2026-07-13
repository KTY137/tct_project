"""Regression guard for the intermittent whole-process freeze in the Settings
dialog's VISA/LAN scan machinery (py-spy native dumps, 2026-07-11).

Root cause (see ``gui.settings_window._ScanReaper``): a ``_ScanWorker``'s
Python reference used to be dropped from a module-level ``set`` *inside*
``_ScanWorker.run`` — i.e. on the *worker* thread — leaving the worker
reachable only through self-referential Qt connections (a reference cycle).
A cycle is reclaimed only by CPython's cyclic GC, which can fire on ANY thread
at ANY allocation, including a freshly-started sibling scan thread mid
``QThread.started`` delivery.  Collecting the dead worker there runs
``QObject::~QObject`` off the GUI thread (needs the GIL *and* the Qt
connection-pool mutex the running ``activate`` already holds) while the GUI
thread sits in ``QLineEdit``/``connectImpl`` holding the GIL and blocked on the
same connection-pool mutex bucket → an ABBA deadlock that froze the whole
process at 0 CPU (and even wedged pytest-timeout's watchdog thread).

The fix keeps each worker's *only* strong Python reference in the
GUI-thread-affine ``_ScanReaper`` singleton and retires it (drops the ref +
``deleteLater``) ONLY on the GUI thread, at ``QThread.finished``.  These tests
pin the two observable consequences of that fix:

* ``test_scan_workers_stay_referenced_until_finished`` — while scans are in
  flight the reaper holds them (they survive an explicit ``gc.collect()``),
  and every one is retired once finished.
* ``test_scan_worker_destroyed_on_gui_thread`` — the *second entry door*
  (py-spy, 2026-07-12): the worker's C++ ``~QObject`` must run on the GUI
  thread, never on its own (worker) loop.  A ``done -> worker.deleteLater``
  would flush the DeferredDelete inside ``QThreadPrivate::finish`` on the
  worker thread; the reaper instead re-homes the finished worker to the GUI
  thread and deletes it there.  The test spies ``QObject.destroyed`` recording
  ``QThread.currentThread()`` and asserts the wrapper stays valid until reap.
* ``test_rescan_worker_replacement_stress`` (``@slow``) — 50 back-to-back
  worker-replacement cycles complete without a freeze and leave nothing
  leaked, exercising the exact overlap (a new scan thread starting while the
  previous one is still tearing down) that triggered the deadlock.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import gc
import threading
import time
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QApplication, QInputDialog

from gui.settings_window import SettingsWindow

_REAL_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "devices.yaml"


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump_until(app: QApplication, predicate, timeout_s: float = 5.0) -> bool:
    t0 = time.monotonic()
    while not predicate():
        if time.monotonic() - t0 > timeout_s:
            return False
        app.processEvents()
        time.sleep(0.005)
    return True


def _write_cfg(tmp_path: Path) -> Path:
    cfg = tmp_path / "devices.yaml"
    cfg.write_text(_REAL_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    return cfg


def test_scan_workers_stay_referenced_until_finished(tmp_path, monkeypatch):
    """Two back-to-back (concurrent) scan workers must both stay strongly
    referenced by the reaper — surviving an explicit GC — until each finishes,
    then be retired.  If a worker were reachable only through a connection
    cycle it could be reclaimed early on an arbitrary thread (the deadlock)."""
    # Instant VISA scan so the automatic construction-time scan drains fast.
    monkeypatch.setattr("devices.waveform_generator.list_visa_resources", lambda: [])
    # Gate the LAN discovery so we can hold two workers in flight at once.
    release = threading.Event()

    def blocking_lan(timeout: float = 2.5):
        release.wait(5.0)
        return []

    monkeypatch.setattr("devices.waveform_generator.discover_lan_instruments", blocking_lan)
    # LAN discovery finding nothing prompts a manual-entry dialog — stub it.
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))

    app = _app()
    win = SettingsWindow(config_path=_write_cfg(tmp_path))
    try:
        mgr = win._visa_scan_mgr
        reaper = mgr._reaper
        # Let the automatic VISA scan complete AND be retired on the GUI thread.
        assert _pump_until(app, lambda: mgr.cache is not None)
        assert _pump_until(app, lambda: reaper.active_count() == 0), \
            "initial VISA scan worker was never retired"

        # Two independent LAN scans (this path never coalesces) — both block,
        # so both are simultaneously in flight (the worker-replacement overlap).
        win._scope_section._visa_addr._add_lan()
        win._wfg_section._addr._add_lan()
        assert _pump_until(app, lambda: reaper.active_count() == 2), \
            "both in-flight scan workers should be tracked by the reaper"

        # The reaper's reference is a plain reachable one, not a cycle — an
        # explicit collection must NOT reclaim a worker mid-scan.
        gc.collect()
        assert reaper.active_count() == 2

        # Releasing lets both finish; retirement happens on the GUI thread.
        release.set()
        assert _pump_until(app, lambda: reaper.active_count() == 0, timeout_s=6.0), \
            "finished scan workers/threads were not retired"
    finally:
        release.set()
        win.close()


def test_scan_worker_destroyed_on_gui_thread(tmp_path, monkeypatch):
    """The worker's C++ ``~QObject`` must run on the GUI thread — the second
    entry door of the ABBA deadlock (py-spy native dump, 2026-07-12).

    Deleting a PySide-wrapped worker on its own loop (``done ->
    worker.deleteLater``) flushes the DeferredDelete inside
    ``QThreadPrivate::finish`` *on the worker thread*, running ``~QObject``
    (Shiboken GIL re-entry + connection-pool mutex disconnect) off-GUI — the
    same ABBA pair against the GUI thread's ``connectImpl`` as the cyclic-GC
    path.  The fix re-homes the finished worker to the GUI thread in
    ``_ScanReaper._reap`` and ``deleteLater``s it there.

    We spy ``QObject.destroyed`` (fires synchronously inside ``~QObject``, on
    the destroying thread) and record ``QThread.currentThread()``.  If the
    worker were still deleted on its own loop the destroy would happen on the
    worker thread; if a broken ``moveToThread`` left it stranded on the exited
    worker thread the DeferredDelete would never flush and the object would
    never be destroyed at all — both are caught here.
    """
    monkeypatch.setattr("devices.waveform_generator.list_visa_resources", lambda: [])
    release = threading.Event()

    def blocking_lan(timeout: float = 2.5):
        release.wait(5.0)
        return []

    monkeypatch.setattr("devices.waveform_generator.discover_lan_instruments", blocking_lan)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))

    app = _app()
    gui_thread = app.thread()
    gui_ptr = shiboken6.getCppPointer(gui_thread)
    win = SettingsWindow(config_path=_write_cfg(tmp_path))
    try:
        mgr = win._visa_scan_mgr
        reaper = mgr._reaper
        # Drain + retire the automatic construction-time VISA scan first.
        assert _pump_until(app, lambda: mgr.cache is not None)
        assert _pump_until(app, lambda: reaper.active_count() == 0)

        # One blocking LAN scan so we can grab the single in-flight worker.
        win._scope_section._visa_addr._add_lan()
        assert _pump_until(app, lambda: reaper.active_count() == 1)
        (worker,) = list(reaper._pairs.values())

        # DirectConnection: the slot must run inside ~QObject on its own
        # (destroying) thread, un-requeued, so QThread.currentThread() is that
        # thread.  Record the C++ pointer, not the wrapper — PySide can hand out
        # a fresh QThread wrapper for the same C++ thread, so ``is`` is unsafe.
        seen: dict[str, object] = {}
        worker.destroyed.connect(
            lambda *_: seen.setdefault(
                "thread_ptr", shiboken6.getCppPointer(QThread.currentThread())
            ),
            Qt.DirectConnection,
        )
        # While the scan is in flight the C++ object is alive and NOT yet
        # destroyed — the reaper holds it until its thread finishes.
        assert shiboken6.isValid(worker)
        assert "thread_ptr" not in seen

        # Let the scan finish; reap (GUI thread) deletes the re-homed worker.
        release.set()
        assert _pump_until(app, lambda: reaper.active_count() == 0, timeout_s=6.0)
        # The GUI event loop must actually flush the DeferredDelete — if this
        # never trips, the worker was stranded on its exited worker thread.
        assert _pump_until(app, lambda: "thread_ptr" in seen, timeout_s=6.0), \
            "worker C++ object was never destroyed (stranded DeferredDelete?)"
        assert not shiboken6.isValid(worker), \
            "worker C++ object should be gone after reap + GUI event turn"
        assert seen["thread_ptr"] == gui_ptr, (
            "worker ~QObject ran on a worker thread, must run on the GUI thread "
            f"(ran on {seen['thread_ptr']}, GUI is {gui_ptr})"
        )
    finally:
        release.set()
        win.close()


@pytest.mark.slow
def test_rescan_worker_replacement_stress(tmp_path, monkeypatch):
    """50 tight back-to-back rescans (each spawns a fresh worker+thread while
    the previous is still tearing down) must complete well under 30 s without
    a freeze, and leak no worker/thread."""
    monkeypatch.setattr("devices.waveform_generator.list_visa_resources", lambda: [])
    monkeypatch.setattr("gui.settings_window.QMessageBox.information", lambda *a, **k: None)

    app = _app()
    win = SettingsWindow(config_path=_write_cfg(tmp_path))
    try:
        mgr = win._visa_scan_mgr
        assert _pump_until(app, lambda: mgr.cache is not None)
        picker = win._scope_section._visa_addr

        t0 = time.monotonic()
        for _ in range(50):
            picker._refresh()
            # Wait only until the scan is no longer "busy", then immediately
            # fire the next one — the previous worker's thread is typically
            # still in its quit/finished/deleteLater teardown at this point,
            # which is exactly the overlap that used to deadlock.
            assert _pump_until(app, lambda: not mgr._visa_busy, timeout_s=5.0)
        elapsed = time.monotonic() - t0
        assert elapsed < 30.0, f"50 rescans took {elapsed:.1f}s (freeze/regression?)"

        # Everything retired on the GUI thread — nothing left dangling.
        assert _pump_until(app, lambda: mgr._reaper.active_count() == 0, timeout_s=5.0)
    finally:
        win.close()
