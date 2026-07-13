"""Tests for the central GUI QSettings accessor."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QSettings

from gui import app_settings


def _scratch_settings(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "app_settings.ini"), QSettings.Format.IniFormat)


def test_app_settings_round_trip_uses_existing_defaults(tmp_path):
    settings = _scratch_settings(tmp_path)

    assert app_settings.theme_mode(settings) == "light"
    app_settings.set_theme_mode("dark", settings)
    assert app_settings.theme_mode(settings) == "dark"

    assert app_settings.active_tab_index(settings) is None
    app_settings.set_active_tab_index(3, settings)
    assert app_settings.active_tab_index(settings) == 3

    assert app_settings.detached_titles(settings) == []
    app_settings.set_detached_titles(["Scope", "Motor"], settings)
    assert app_settings.detached_titles(settings) == ["Scope", "Motor"]
    settings.setValue(app_settings.DETACHED_TITLES_KEY, "Camera")
    assert app_settings.detached_titles(settings) == ["Camera"]

    assert app_settings.planner_arm_latch_enabled(settings) is True
    settings.setValue(app_settings.PLANNER_ARM_LATCH_KEY, "false")
    assert app_settings.planner_arm_latch_enabled(settings) is False

    app_settings.save_theme_customization_values(
        glass_amount=0.25,
        window_opacity=0.9,
        window_backdrop="mica",
        overrides_json='{"light": {"accent": "#123456"}, "dark": {}}',
        typography_json='{"sans": "Inter"}',
        radius_scale="l",
        store=settings,
    )
    assert float(app_settings.theme_glass_amount_value(settings)) == 0.25
    assert float(app_settings.theme_window_opacity_value(settings)) == 0.9
    assert app_settings.theme_window_backdrop_value(settings) == "mica"
    assert app_settings.theme_overrides_json(settings) == (
        '{"light": {"accent": "#123456"}, "dark": {}}'
    )
    assert app_settings.theme_typography_json(settings) == '{"sans": "Inter"}'
    assert app_settings.theme_radius_scale(settings) == "l"

    app_settings.set_user_presets_json('[{"name": "Bench"}]', settings)
    assert app_settings.user_presets_json(settings) == '[{"name": "Bench"}]'


def test_gui_code_does_not_construct_app_qsettings_directly():
    app_root = Path(__file__).resolve().parents[1]
    direct_ctor = re.compile(
        r"QSettings\s*\(\s*['\"]TCT['\"]\s*,\s*['\"]TCTSetup['\"]\s*\)"
    )
    candidates = list((app_root / "gui").rglob("*.py")) + [
        app_root / "tct_gui.py",
        app_root / "main.py",
    ]

    # Another day-shift beat owns gui/style.py; C7 intentionally leaves its
    # theme/* persistence lines unmigrated and reports that allowlist.
    allowed = {"gui/style.py"}
    offenders = []
    for path in candidates:
        if path.name == "app_settings.py":
            continue
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(app_root).as_posix()
        if rel in allowed:
            continue
        if direct_ctor.search(text):
            offenders.append(rel)

    assert offenders == []
