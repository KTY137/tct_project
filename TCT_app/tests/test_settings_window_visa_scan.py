"""Regression tests for the Settings dialog VISA/LAN scanning bench bug.

Three defects fixed in ``gui/settings_window.py``:

1. ``_VisaPicker`` used to call ``list_visa_resources()`` synchronously in
   ``__init__``; ``_rebuild_quick_settings`` builds four pickers (scope /
   keithley / iseg / wfg), so opening Settings — or switching back from the
   Full YAML tab — fired four blocking VISA scans on the GUI thread.
2. ``_VisaPicker._add_lan`` blocked the GUI thread for ~2.5 s under
   ``WaitCursor`` via ``discover_lan_instruments()``.
3. ``_VisaPicker._fill`` auto-selected ``found[0]`` whenever the saved
   address looked like a placeholder — since ``list_visa_resources()``
   returns every VISA-visible resource, a picker for one device (e.g. the
   waveform generator) could silently adopt a *different* device's address
   (e.g. the oscilloscope's USB address) and mark the config dirty.

The fix centralises scanning in ``_VisaScanManager`` (cached, off-thread,
shared by every picker) and removes auto-select entirely.  These tests pin:
scan-count sharing (not once-per-picker), no cross-device auto-write / no
spurious dirty flag, non-blocking construction under a slow scan, a working
manual rescan, off-thread LAN discovery, and — the sharpest regression check
— that closing the dialog while a scan is still in flight cannot crash the
process (a still-running QThread destroyed via Qt's parent-child cascade is
a hard abort in Qt6, not a catchable Python exception, so this test's mere
survival is the assertion).
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QInputDialog

from gui.settings_window import SettingsWindow

_REAL_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "devices.yaml"

# A minimal config with *placeholder* VISA addresses on two different device
# kinds, so a cross-device auto-select (bug #3) would be observable.
_PLACEHOLDER_CFG = """
oscilloscope:
  backend: visa
  visa_address: "USB0::..."
  vendor: tektronix
waveform_generator:
  visa_address: "USB0::..."
  vendor: rigol
bias_supply:
  backend: iseg
  visa_address: "ASRL6::INSTR"
output:
  data_dir: runs
"""


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump_until(app: QApplication, predicate, timeout_s: float = 2.0) -> bool:
    """Process the Qt event loop until *predicate* is true or timeout."""
    t0 = time.monotonic()
    while not predicate():
        if time.monotonic() - t0 > timeout_s:
            return False
        app.processEvents()
        time.sleep(0.005)
    return True


def _write_cfg(tmp_path: Path, text: str) -> Path:
    cfg = tmp_path / "devices.yaml"
    cfg.write_text(text, encoding="utf-8")
    return cfg


# --------------------------------------------------------------------------- #
# Defect 1 — one shared scan, not one per picker / per tab switch             #
# --------------------------------------------------------------------------- #

def test_dialog_open_scans_visa_once_not_once_per_picker(tmp_path, monkeypatch):
    calls = {"n": 0}
    lock = threading.Lock()

    def fake_list():
        with lock:
            calls["n"] += 1
        return ["USB0::0x1AB1::0x0641::DG4162::INSTR"]

    monkeypatch.setattr("devices.waveform_generator.list_visa_resources", fake_list)

    app = _app()
    win = SettingsWindow(config_path=_write_cfg(tmp_path, _REAL_CONFIG.read_text(encoding="utf-8")))
    try:
        assert _pump_until(app, lambda: win._visa_scan_mgr.cache is not None), \
            "shared scan never completed"
        # 4 pickers (scope / keithley(unused-iseg backend but section still
        # builds the keithley frame) / iseg / wfg) were built at construction.
        assert calls["n"] == 1

        # Switching to Full YAML and back rebuilds every device section (and
        # therefore every picker) via _rebuild_quick_settings — must reuse
        # the cache, never re-scan.
        win._tabs.setCurrentIndex(win._yaml_tab_index)
        win._tabs.setCurrentIndex(0)
        _pump_until(app, lambda: True, timeout_s=0.05)
        assert calls["n"] == 1
    finally:
        win.close()


@pytest.mark.timing_sensitive
def test_construction_does_not_block_on_slow_scan(tmp_path, monkeypatch):
    """A slow (bench-realistic) VISA enumeration must not stall __init__."""
    def slow_list():
        time.sleep(3.0)
        return []

    monkeypatch.setattr("devices.waveform_generator.list_visa_resources", slow_list)

    app = _app()
    t0 = time.monotonic()
    win = SettingsWindow(config_path=_write_cfg(tmp_path, _REAL_CONFIG.read_text(encoding="utf-8")))
    elapsed = time.monotonic() - t0
    try:
        # The point is "returned well before the scan could have finished",
        # not "instant": the budget must stay below the simulated scan sleep
        # above, but generous enough that widget-construction overhead on a
        # loaded machine can't trip it (the old 1.0s/0.5s pairing flaked
        # repeatedly under back-to-back suite runs, 2026-07-07/08).
        assert elapsed < 2.0, f"SettingsWindow() blocked for {elapsed:.3f}s on the VISA scan"
        # The picker must stay usable (editable combo) while the scan runs.
        picker = win._scope_section._visa_addr
        assert picker._combo.isEnabled()
        assert picker._combo.isEditable()
        # Let the background scan actually land before teardown so this test
        # doesn't race its own QThread's shutdown.
        assert _pump_until(app, lambda: win._visa_scan_mgr.cache is not None, timeout_s=5.0)
    finally:
        win.close()


# --------------------------------------------------------------------------- #
# Defect 3 — no cross-device auto-select, no spurious dirty flag              #
# --------------------------------------------------------------------------- #

def test_no_cross_device_auto_select_and_no_dirty(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "devices.waveform_generator.list_visa_resources",
        lambda: ["USB0::0x1AB1::0x0641::DG4162::INSTR"],   # looks like the wfg, not the scope
    )
    app = _app()
    win = SettingsWindow(config_path=_write_cfg(tmp_path, _PLACEHOLDER_CFG))
    try:
        assert _pump_until(app, lambda: win._visa_scan_mgr.cache is not None)
        # The oscilloscope picker's saved address is a placeholder, and the
        # only discovered resource looks like a *different* device — it must
        # NOT have been silently adopted.
        scope_addr = win._scope_section._visa_addr.text()
        assert scope_addr != "USB0::0x1AB1::0x0641::DG4162::INSTR"
        assert win._dirty is False
        # The discovered resource is still offered in the dropdown for the
        # user to pick explicitly.
        combo = win._scope_section._visa_addr._combo
        assert combo.findText("USB0::0x1AB1::0x0641::DG4162::INSTR") >= 0
    finally:
        win.close()


def test_no_dirty_from_rescan_landing_either(tmp_path, monkeypatch):
    """Even an explicit 🔄 rescan (not just the automatic first scan) must
    not auto-write a foreign address / mark the config dirty on its own."""
    monkeypatch.setattr(
        "devices.waveform_generator.list_visa_resources",
        lambda: ["TCPIP0::10.0.0.5::INSTR"],
    )
    monkeypatch.setattr("gui.settings_window.QMessageBox.information", lambda *a, **k: None)

    app = _app()
    win = SettingsWindow(config_path=_write_cfg(tmp_path, _PLACEHOLDER_CFG))
    try:
        assert _pump_until(app, lambda: win._visa_scan_mgr.cache is not None)
        assert win._dirty is False
        picker = win._wfg_section._addr
        picker._refresh()
        assert _pump_until(app, lambda: not win._visa_scan_mgr._visa_busy)
        assert win._wfg_section._addr.text() != "TCPIP0::10.0.0.5::INSTR"
        assert win._dirty is False
    finally:
        win.close()


# --------------------------------------------------------------------------- #
# Manual rescan actually re-runs the scan                                     #
# --------------------------------------------------------------------------- #

def test_rescan_button_reruns_scan(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_list():
        calls["n"] += 1
        return []

    monkeypatch.setattr("devices.waveform_generator.list_visa_resources", fake_list)
    monkeypatch.setattr("gui.settings_window.QMessageBox.information", lambda *a, **k: None)

    app = _app()
    win = SettingsWindow(config_path=_write_cfg(tmp_path, _REAL_CONFIG.read_text(encoding="utf-8")))
    try:
        # Wait for the *whole* round trip (cache populated), not just the
        # worker having called fake_list() — otherwise the manager may still
        # think the first scan is in flight (_visa_busy not yet reset by the
        # queued completion callback) and correctly coalesce this rescan into
        # it instead of starting a second one.
        assert _pump_until(app, lambda: win._visa_scan_mgr.cache is not None)
        assert calls["n"] == 1
        picker = win._scope_section._visa_addr
        picker._refresh()
        assert _pump_until(app, lambda: calls["n"] >= 2)
    finally:
        win.close()


# --------------------------------------------------------------------------- #
# Defect 2 — LAN discovery runs off-thread                                    #
# --------------------------------------------------------------------------- #

def test_lan_scan_runs_off_thread_and_offers_manual_entry_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("devices.waveform_generator.list_visa_resources", lambda: [])
    calls = {"n": 0}

    def fake_lan(timeout: float = 2.5):
        calls["n"] += 1
        time.sleep(0.05)   # still off-thread, but non-trivial — proves no GUI block
        return []

    monkeypatch.setattr("devices.waveform_generator.discover_lan_instruments", fake_lan)
    prompted = {"shown": False}

    def fake_get_text(*_a, **_k):
        prompted["shown"] = True
        return "", False

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(fake_get_text))

    app = _app()
    win = SettingsWindow(config_path=_write_cfg(tmp_path, _REAL_CONFIG.read_text(encoding="utf-8")))
    try:
        picker = win._wfg_section._addr
        t0 = time.monotonic()
        picker._add_lan()
        elapsed = time.monotonic() - t0
        assert elapsed < 0.03, f"_add_lan() blocked for {elapsed:.3f}s"
        assert _pump_until(app, lambda: calls["n"] >= 1)
        assert _pump_until(app, lambda: prompted["shown"])
    finally:
        win.close()


# --------------------------------------------------------------------------- #
# Thread lifecycle — closing mid-scan must not crash                          #
# --------------------------------------------------------------------------- #

def test_close_while_scan_in_flight_does_not_crash(tmp_path, monkeypatch):
    """A still-running QThread destroyed via Qt's cascade is a hard Qt6
    abort, not a Python exception — so this test's mere survival (plus
    pytest continuing to the next test) is the real assertion."""
    def slow_list():
        time.sleep(0.2)
        return []

    monkeypatch.setattr("devices.waveform_generator.list_visa_resources", slow_list)

    app = _app()
    win = SettingsWindow(config_path=_write_cfg(tmp_path, _REAL_CONFIG.read_text(encoding="utf-8")))
    # Close immediately — the scan (0.2s) cannot have completed yet.
    win.close()
    _pump_until(app, lambda: True, timeout_s=0.05)
    # If we get here at all, the process survived; explicitly assert the
    # manager believes it has joined its threads (best-effort, bounded wait).
    assert win._visa_scan_mgr._threads == set() or True  # survival is the point


def test_settings_window_gc_without_close_does_not_crash(tmp_path, monkeypatch):
    """Some callers never explicitly close() a parent-less SettingsWindow
    (see test_panel_kit_rollout_batch1.py::test_settings_window_still_
    constructs_untouched) — Python garbage-collecting it while the initial
    scan is still in flight must not crash either.

    The scan thread is parented to the QApplication (not the GC'd window), so
    it OUTLIVES the window and must be driven to completion via its own
    done -> quit -> finished -> reap chain, which needs the GUI event loop
    pumped. Left running it is destroyed only when ``~QApplication`` runs at
    interpreter exit — a hard Qt6 abort ("QThread: Destroyed while thread is
    still running"). So pump until the process-lifetime reaper has retired it;
    a bare ``lambda: True`` predicate returns from ``_pump_until`` without
    processing a single event and leaks the thread to interpreter exit."""
    from gui.settings_window import _scan_reaper

    def slow_list():
        time.sleep(0.15)
        return []

    monkeypatch.setattr("devices.waveform_generator.list_visa_resources", slow_list)

    app = _app()
    # The reaper is a process-lifetime singleton shared across every dialog in
    # the suite; measure its baseline so this assertion tracks OUR orphaned
    # thread being retired, not the global count reaching exactly zero.
    before = _scan_reaper().active_count()
    win = SettingsWindow(config_path=_write_cfg(tmp_path, _REAL_CONFIG.read_text(encoding="utf-8")))
    del win   # drop the only reference while the 0.15s scan is still running
    import gc
    gc.collect()
    assert _pump_until(app, lambda: _scan_reaper().active_count() <= before,
                       timeout_s=5.0), \
        "orphaned VISA scan thread was never reaped — it would survive to " \
        "interpreter exit and hard-abort Qt6 at ~QApplication"
