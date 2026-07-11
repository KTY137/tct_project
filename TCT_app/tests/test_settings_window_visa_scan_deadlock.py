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
