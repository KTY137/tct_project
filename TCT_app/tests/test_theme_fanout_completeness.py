"""Guard the main-window theme fan-out against forgotten panels.

When a top-level panel caches theme-derived instance styling, it exposes
``refresh_theme()`` and ``TCTMainWindow._toggle_theme`` must call it. This test
discovers that contract dynamically from the real window attributes so adding a
new refreshable panel without wiring the fan-out fails immediately.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import yaml
from PySide6.QtWidgets import QApplication, QWidget


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump(ms: int = 60) -> None:
    app = _app()
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)


def _sim_config_path(tmp_path: Path) -> str:
    cfg = {
        "oscilloscope": {"backend": "visa", "simulation": True, "n_channels": 2},
        "motor_stage": {"backend": "simulated"},
        "intensity_monitor": {"backend": "simulated"},
        "camera": {"simulation": True},
        "waveform_generator": {"simulation": True},
        "bias_supply": {"backend": "simulated"},
        "slow_control": {"poll_interval_s": 5, "channels": []},
        "influx": {"enabled": False},
        "output": {"data_dir": str(tmp_path / "runs")},
    }
    path = tmp_path / "devices.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return str(path)


def _make_window(monkeypatch, tmp_path: Path):
    from tct_gui import TCTMainWindow

    monkeypatch.setattr(TCTMainWindow, "_restore_window_state", lambda self: None)
    win = TCTMainWindow(config_path=_sim_config_path(tmp_path))
    _pump()
    return win


def _destroy_window(win) -> None:
    try:
        win._teardown_panels()
        win._safe_bias_shutdown()
        win._devices.disconnect_all()
    finally:
        win.hide()
        win.deleteLater()
        _pump()


def _refreshable_window_widgets(win) -> list[tuple[str, QWidget]]:
    refreshables: list[tuple[str, QWidget]] = []
    seen: set[int] = set()
    for name, value in vars(win).items():
        if not isinstance(value, QWidget):
            continue
        if not callable(getattr(value, "refresh_theme", None)):
            continue
        ident = id(value)
        if ident in seen:
            continue
        seen.add(ident)
        refreshables.append((name, value))
    return refreshables


def test_theme_toggle_fans_out_to_every_refreshable_window_widget(monkeypatch, tmp_path):
    _app()
    win = _make_window(monkeypatch, tmp_path)
    try:
        refreshables = _refreshable_window_widgets(win)
        names = {name for name, _widget in refreshables}

        assert refreshables, "test helper found no refreshable main-window widgets"
        assert "_calib_panel" in names, "calibration panel must stay in the fan-out contract"

        calls: list[str] = []
        for name, widget in refreshables:
            def _spy(*_args, _name=name, **_kwargs) -> None:
                calls.append(_name)

            setattr(widget, "refresh_theme", _spy)

        win._settings = _SettingsSink()
        win._toggle_theme(checked=win._theme_mode != "dark")

        missed = sorted(names - set(calls))
        assert missed == []
    finally:
        _destroy_window(win)


class _SettingsSink:
    def setValue(self, *_args) -> None:
        pass
