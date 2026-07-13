"""``_run_bg`` busy-path feedback (FREEZE bug follow-up, 2026-07-10).

Both single-slot background runners (``tct_gui.TCTMainWindow._run_bg`` and
``gui.device_panel.DeviceManagerWindow._run_bg``) used to ``return False``
*silently* when a previous connect/disconnect was still in flight — the bench
"clicking reconnect does nothing" report.  They now surface the busy state on
the app status bus (``gui.status_bus.notify`` → logged on ``tct.status``)
before returning False, without building an arbitrary-depth job queue.
"""
from __future__ import annotations

import logging
import os
from types import SimpleNamespace

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _pump(app, seconds: float = 0.1) -> None:
    import time
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


# --------------------------------------------------------------------------- #
# Device Manager window                                                        #
# --------------------------------------------------------------------------- #

def test_device_manager_run_bg_busy_path_surfaces_feedback(qapp, tmp_path, caplog):
    """A second device action while one is running returns False AND surfaces a
    busy notification (was a silent no-op)."""
    from gui.device_panel import DeviceManagerWindow

    dm = _sim_device_manager(tmp_path)
    win = DeviceManagerWindow(dm)
    try:
        # Occupy the single background slot with a fake still-running thread.
        win._bg_thread = SimpleNamespace(isRunning=lambda: True)
        with caplog.at_level(logging.WARNING, logger="tct.status"):
            result = win._run_bg(lambda: None, lambda r, e: None)
        assert result is False
        assert any("busy" in r.message.lower() for r in caplog.records), \
            "no busy feedback was surfaced on the status bus"
        # The busy chip was nudged too (visible in the Device Manager itself).
        assert "working" in win._chip_busy.text().lower()
    finally:
        win._bg_thread = None
        win.shutdown()
        _pump(qapp, 0.1)


def test_device_manager_run_bg_idle_starts_task(qapp, tmp_path):
    """Sanity: when idle, _run_bg returns True and actually launches the task
    (the busy branch must not have broken the happy path)."""
    from gui.device_panel import DeviceManagerWindow

    dm = _sim_device_manager(tmp_path)
    win = DeviceManagerWindow(dm)
    try:
        win._bg_thread = None
        done: list = []
        started = win._run_bg(lambda: "ok", lambda r, e: done.append((r, e)))
        assert started is True
        import time
        t0 = time.monotonic()
        while not done and time.monotonic() - t0 < 3.0:
            qapp.processEvents()
            time.sleep(0.01)
        assert done and done[0] == ("ok", "")
    finally:
        win.shutdown()
        _pump(qapp, 0.1)


# --------------------------------------------------------------------------- #
# Main window                                                                  #
# --------------------------------------------------------------------------- #

def test_tct_main_run_bg_busy_path_surfaces_feedback(caplog):
    """Same contract for TCTMainWindow._run_bg, exercised against a lightweight
    stub self (building the whole main window would spin up every device thread
    for no extra coverage of this one branch)."""
    from tct_gui import TCTMainWindow

    stub = SimpleNamespace(_bg_thread=SimpleNamespace(isRunning=lambda: True))
    with caplog.at_level(logging.WARNING, logger="tct.status"):
        result = TCTMainWindow._run_bg(stub, lambda: None, lambda r, e: None)
    assert result is False
    assert any("busy" in r.message.lower() for r in caplog.records), \
        "no busy feedback was surfaced on the status bus"
