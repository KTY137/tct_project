"""Headless guard tests for ``scripts/capture_onscreen.py`` (manual-run tool).

This file tests ONLY the pieces that are safe and meaningful inside the
headless pytest suite (``QT_QPA_PLATFORM=offscreen``, forced by
``tests/conftest.py``): the refuse-to-run environment guard, the pure
``--list`` dry-run plan, the QSettings snapshot/restore helper, and the
all-simulated config guard.

The actual on-screen DWM capture path (``_run_capture`` / ``_grab`` /
``_bitblt_grab`` / ``_probe_capture_method``) is manual-run-only by design
and is deliberately NOT exercised here — see
``scripts/capture_onscreen.py``'s own module docstring for how a human runs
it for real, on a real desktop session.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from gui import app_settings
from scripts import capture_onscreen as co

APP_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Refuse-to-run guard                                                         #
# --------------------------------------------------------------------------- #

def test_check_environment_refuses_under_forced_offscreen():
    """The whole suite runs with QT_QPA_PLATFORM=offscreen (conftest.py) --
    this IS the environment the tool must refuse, and it must refuse from
    the env var alone, before ever constructing/querying a QApplication."""
    assert os.environ.get("QT_QPA_PLATFORM", "").split(":")[0].strip().lower() == "offscreen"
    reason = co.check_environment()
    assert reason is not None
    assert "offscreen" in reason.lower()


def test_check_environment_refuses_on_disallowed_platform_name(monkeypatch):
    """Exercises the app.platformName() branch independently via a duck-typed
    stub -- no real QApplication needed for this half of the guard. The env
    var alone already refuses in this suite, so it is monkeypatched away
    (restored automatically at teardown) to isolate the app-side branch."""
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)

    class _StubApp:
        def platformName(self):
            return "minimal"

        def primaryScreen(self):
            return object()

    reason = co.check_environment(_StubApp())
    assert reason is not None
    assert "minimal" in reason.lower()


def test_check_environment_refuses_with_no_primary_screen(monkeypatch):
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)

    class _StubApp:
        def platformName(self):
            return "windows"

        def primaryScreen(self):
            return None

    reason = co.check_environment(_StubApp())
    assert reason is not None
    assert "screen" in reason.lower()


def test_check_environment_allows_a_clean_stub(monkeypatch):
    """The suite forces QT_QPA_PLATFORM=offscreen, which alone is always
    sufficient to refuse -- monkeypatch it away for this one assertion so
    the app-side (platformName/primaryScreen) branch is exercised in
    isolation, restored automatically at test teardown."""
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)

    class _StubApp:
        def platformName(self):
            return "windows"

        def primaryScreen(self):
            return object()

    assert co.check_environment(_StubApp()) is None


def test_main_refuses_without_list_flag(capsys):
    rc = co.main([])
    assert rc == 2
    captured = capsys.readouterr()
    assert "REFUSED" in captured.err


# --------------------------------------------------------------------------- #
# --list dry run -- pure, no QApplication, no window                          #
# --------------------------------------------------------------------------- #

def test_list_flag_prints_plan_without_launching(capsys):
    rc = co.main(["--list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "acrylic" in out and "mica" in out and "none" in out
    assert "Glass" in out
    assert "transition" in out.lower()


def test_scenario_matrix_shape():
    scenarios, transitions = co.build_full_plan()
    canvas_modes = co._available_canvas_modes()
    # 3 backdrops x 2 presets x N canvas modes (1 today) + 1 light spot check
    # + 1 detached-tab shot.
    assert len(scenarios) == 3 * 2 * len(canvas_modes) + 2
    assert len(transitions) == 2

    filenames = [s.filename for s in scenarios]
    assert len(filenames) == len(set(filenames)), "scenario filenames must be unique"

    detached = [s for s in scenarios if s.detach_title]
    assert len(detached) == 1
    assert detached[0].detach_title == "Motor Stage"

    light = [s for s in scenarios if s.theme == "light"]
    assert len(light) == 1

    dark = [s for s in scenarios if s.theme == "dark" and s.detach_title is None]
    assert len(dark) == 3 * 2 * len(canvas_modes)
    assert {s.backdrop for s in dark} == {"none", "mica", "acrylic"}
    assert {s.preset for s in dark} == {"Cockpit Dark", "Glass"}


def test_available_canvas_modes_today_is_a_only():
    """Documents the current state: gui/backdrop.py exposes no runtime
    setter for its _CANVAS_MODE constant, so only canvas 'A' is captured.
    This is a tripwire -- it should FAIL (and need updating, not silencing)
    the day a parallel beat adds a real setter."""
    assert co._available_canvas_modes() == ["A"]


# --------------------------------------------------------------------------- #
# QSettings snapshot / restore                                                #
# --------------------------------------------------------------------------- #

def test_snapshot_restore_round_trip():
    settings = app_settings.settings()  # isolated per-process .ini (conftest.py)
    settings.setValue(app_settings.THEME_KEY, "dark")
    settings.setValue(app_settings.THEME_WINDOW_BACKDROP_KEY, "none")
    settings.remove(app_settings.THEME_PRESETS_KEY)  # ensure this key starts ABSENT
    settings.sync()

    snap = co.snapshot_settings(settings)

    # Mutate everything the way a real scenario run would.
    settings.setValue(app_settings.THEME_KEY, "light")
    settings.setValue(app_settings.THEME_WINDOW_BACKDROP_KEY, "acrylic")
    settings.setValue(app_settings.THEME_PRESETS_KEY, '[{"name": "Glass"}]')
    settings.sync()

    co.restore_settings(settings, snap)

    assert settings.value(app_settings.THEME_KEY) == "dark"
    assert settings.value(app_settings.THEME_WINDOW_BACKDROP_KEY) == "none"
    assert not settings.contains(app_settings.THEME_PRESETS_KEY)


def test_snapshot_covers_every_declared_settings_key():
    """The snapshot must track every app_settings.*_KEY constant, not a
    hand-maintained duplicate list that can silently drift out of sync."""
    declared = {v for k, v in vars(app_settings).items() if k.endswith("_KEY")}
    settings = app_settings.settings()
    snap = co.snapshot_settings(settings)
    assert set(snap.keys()) == declared


# --------------------------------------------------------------------------- #
# All-simulated config guard                                                  #
# --------------------------------------------------------------------------- #

def test_assert_all_simulated_accepts_shipped_config():
    co._assert_all_simulated(str(APP_ROOT / "configs" / "devices.yaml"))


def test_assert_all_simulated_rejects_real_hardware(tmp_path):
    cfg = yaml.safe_load((APP_ROOT / "configs" / "devices.yaml").read_text())
    cfg["motor_stage"]["simulation"] = False
    path = tmp_path / "devices.yaml"
    path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(RuntimeError, match="motor_stage"):
        co._assert_all_simulated(str(path))


def test_assert_all_simulated_rejects_non_simulated_slow_control_channel(tmp_path):
    cfg = yaml.safe_load((APP_ROOT / "configs" / "devices.yaml").read_text())
    cfg["slow_control"]["channels"][0]["backend"] = "real_sensor"
    path = tmp_path / "devices.yaml"
    path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(RuntimeError, match="slow_control channel"):
        co._assert_all_simulated(str(path))
