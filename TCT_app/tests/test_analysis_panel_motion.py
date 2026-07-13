"""gui/analysis_panel.py's 2D-map/CCE/Survey mode switch — fade_swap wiring
(fluent-motion beat, Task 2 consumer #1). Headless construction + a
light/dark theme-switch smoke test (required for every panel change per the
GUI agent's standing rules), plus a check that the segmented control drives
``gui.motion_kit.fade_swap`` (not a bare ``setCurrentIndex``) and that the
mode stack still lands on the correct page either way.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import gui.analysis_panel as analysis_panel_module
from gui.analysis_panel import AnalysisPanel, _SURVEY_MODE_INDEX
from gui.style import apply_theme


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_analysis_panel_constructs_headless():
    _app()
    panel = AnalysisPanel()
    assert panel._modes.count() == 3


def test_theme_switch_smoke_both_themes():
    app = _app()
    apply_theme(app, "light")
    panel = AnalysisPanel()
    apply_theme(app, "dark")
    panel.refresh_theme("dark")
    assert not panel.grab().isNull()
    apply_theme(app, "light")
    panel.refresh_theme("light")
    assert not panel.grab().isNull()


def test_segmented_control_switch_uses_fade_swap(monkeypatch):
    """The mode switch is wired through gui.motion_kit.fade_swap, not a bare
    QStackedWidget.setCurrentIndex — pins the Task-2 wiring itself (not just
    the end-state)."""
    _app()
    panel = AnalysisPanel()

    calls = []
    real_fade_swap = analysis_panel_module.fade_swap

    def spy(stacked, new_index, **kwargs):
        calls.append((stacked, new_index))
        return real_fade_swap(stacked, new_index, **kwargs)

    monkeypatch.setattr(analysis_panel_module, "fade_swap", spy)

    panel._segmented.set_current("cce")

    assert calls == [(panel._modes, _SURVEY_MODE_INDEX["cce"])]
    assert panel._modes.currentIndex() == _SURVEY_MODE_INDEX["cce"]


def test_segmented_control_switch_lands_on_correct_page_motion_off(monkeypatch):
    """With the motion kill switch off, the mode switch is an instant jump —
    still lands on the right page, no leftover overlay."""
    _app()
    monkeypatch.setattr("gui.motion_kit.motion_enabled", lambda: False)
    panel = AnalysisPanel()

    for key in ("survey", "map", "cce", "map"):
        panel._segmented.set_current(key)
        assert panel._modes.currentIndex() == _SURVEY_MODE_INDEX[key]
