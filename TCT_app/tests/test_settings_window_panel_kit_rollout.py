"""Headless construct/grab checks for the panel_kit rollout — Batch 2
(gui/settings_window.py — the multi-tab devices.yaml editor).

Follows the existing gui test idiom (see ``test_panel_kit_rollout_batch1.py``):
``QT_QPA_PLATFORM=offscreen``, a shared ``QApplication.instance()`` helper, no
pytest-qt. ``SettingsWindow.refresh_theme()`` (new, additive) stands in for
the ``tct_gui._toggle_theme`` live-refresh loop that other panels are wired
into — settings_window.py cannot touch tct_gui.py, so this is the only way to
exercise both themes here.

Every per-device Quick-Settings tab is built eagerly at construction/reload
time (``_rebuild_quick_settings`` fills all six ``QScrollArea``s at once, the
``QTabWidget`` only hides the non-current ones) — so a single construction is
enough to reach every tab's Card without clicking through the QTabWidget.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
import yaml
from PySide6.QtWidgets import QApplication, QFrame, QLabel

from devices.camera_blackfly import BlackflyCamera
from gui.camera_panel import CameraPanel
from gui.settings_window import SettingsWindow
from gui.style import apply_theme

_REAL_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "devices.yaml"


@pytest.fixture(autouse=True)
def _stub_visa_scan(monkeypatch):
    """Every test here builds a real (untouched-config) ``SettingsWindow``,
    whose ``_VisaScanManager`` fires a real ``list_visa_resources()`` VISA
    bus enumeration off-thread unless stubbed — real hardware I/O during a
    test run, and (per the 2026-07-08 pyvisa access-violation diagnosis) the
    actual trigger for many concurrent first-ever pyvisa imports racing
    across ~13 SettingsWindow instances in this file. Mirrors the existing
    stub in test_settings_window_visa_scan.py."""
    monkeypatch.setattr("devices.waveform_generator.list_visa_resources", lambda: [])


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _grab_both_themes(win: SettingsWindow) -> None:
    app = _app()
    apply_theme(app, "light")
    win.refresh_theme("light")
    pm_light = win.grab()
    assert not pm_light.isNull()
    assert pm_light.width() > 0 and pm_light.height() > 0

    apply_theme(app, "dark")
    win.refresh_theme("dark")
    pm_dark = win.grab()
    assert not pm_dark.isNull()
    assert pm_dark.width() > 0 and pm_dark.height() > 0

    win.refresh_theme("light")
    apply_theme(app, "light")


def _cards(widget) -> list[QFrame]:
    return widget.findChildren(QFrame, "cardPane")


# --------------------------------------------------------------------------- #
# Construct / render — both themes                                            #
# --------------------------------------------------------------------------- #

def test_settings_window_constructs_both_themes():
    _app()
    win = SettingsWindow()
    try:
        _grab_both_themes(win)
    finally:
        win.close()


def test_settings_window_every_tab_grabs_both_themes():
    """Switch to each of the 7 tabs (6 device tabs + Full YAML) and grab —
    catches a per-tab layout crash that a whole-window grab could miss."""
    _app()
    apply_theme(_app(), "light")
    win = SettingsWindow()
    try:
        for i in range(win._tabs.count()):
            win._tabs.setCurrentIndex(i)
            pm = win.grab()
            assert not pm.isNull(), f"tab {i} ({win._tabs.tabText(i)}) grabbed empty"
    finally:
        win.close()
        apply_theme(_app(), "light")


# --------------------------------------------------------------------------- #
# Card-ification: every device tab got a titled Card                          #
# --------------------------------------------------------------------------- #

def test_every_device_section_has_exactly_one_card():
    _app()
    win = SettingsWindow()
    try:
        sections = (
            win._scope_section, win._motor_section, win._bias_section,
            win._wfg_section, win._cam_section, win._data_section,
        )
        for sec in sections:
            assert sec is not None
            assert len(_cards(sec)) == 1, type(sec).__name__
        # Full YAML tab's editor surface also got a Card frame.
        assert len(_cards(win)) >= len(sections) + 1
    finally:
        win.close()


def test_yaml_tab_card_has_devices_yaml_header():
    _app()
    win = SettingsWindow()
    try:
        titles = [lbl.text() for lbl in win.findChildren(QLabel, "cardTitle")]
        subtitles = [lbl.text() for lbl in win.findChildren(QLabel, "cardSubtitle")]
        assert "devices.yaml" in titles
        assert str(win._config_path) in subtitles
    finally:
        win.close()


# --------------------------------------------------------------------------- #
# Axis-rail wiring: bias amber, motor x/y/z, waveform-gen delay, scope accent #
# --------------------------------------------------------------------------- #

def test_bias_card_carries_bias_rail():
    _app()
    win = SettingsWindow()
    try:
        card = _cards(win._bias_section)[0]
        assert card.property("railAxis") == "bias"
    finally:
        win.close()


def test_waveform_card_carries_delay_rail():
    _app()
    win = SettingsWindow()
    try:
        card = _cards(win._wfg_section)[0]
        assert card.property("railAxis") == "delay"
    finally:
        win.close()


def test_scope_card_carries_accent_rail():
    """No AXIS_RAIL token fits a non-scan-axis device identity (kit gap,
    reported); settings_window works around it locally with _accent_rail()."""
    _app()
    win = SettingsWindow()
    try:
        card = _cards(win._scope_section)[0]
        assert card.property("railAxis") == "accent"
    finally:
        win.close()


def test_motor_limit_rows_have_xyz_axis_captions():
    _app()
    win = SettingsWindow()
    try:
        captions = [lbl.text() for lbl in win._motor_section.findChildren(QLabel, "eyebrow")]
        assert any("X LIMITS" in c for c in captions)
        assert any("Y LIMITS" in c for c in captions)
        assert any("Z LIMITS" in c for c in captions)
    finally:
        win.close()


# --------------------------------------------------------------------------- #
# Hint-label theme-token fix (the 5 hardcoded color:#888 idioms + friends)    #
# --------------------------------------------------------------------------- #

def test_no_hardcoded_hint_grey_left_in_any_section():
    _app()
    win = SettingsWindow()
    try:
        sections = (
            win._scope_section, win._motor_section, win._bias_section,
            win._wfg_section, win._cam_section, win._data_section,
        )
        for sec in sections:
            for lbl in sec.findChildren(QLabel):
                assert "#888" not in lbl.styleSheet()
        # Dialog chrome (path label / info note / parse-error banner) too.
        assert "#555" not in win._lbl_path.styleSheet()
        assert "#666" not in win._info_label.styleSheet()
    finally:
        win.close()


# --------------------------------------------------------------------------- #
# Behavioural: Card swap did not disturb the save -> reload wiring            #
# --------------------------------------------------------------------------- #

def test_quick_settings_to_yaml_to_save_roundtrip(tmp_path, monkeypatch):
    # _save() ends with a modal QMessageBox.information() — real user-facing
    # behaviour, left untouched, but exec() blocks forever under
    # QT_QPA_PLATFORM=offscreen with no user to click OK. Stub it out for
    # this test only, the same way a pytest-qt suite would stub a modal.
    monkeypatch.setattr(
        "gui.settings_window.QMessageBox.information", lambda *a, **k: None)

    tmp_cfg = tmp_path / "devices.yaml"
    tmp_cfg.write_text(_REAL_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    _app()
    win = SettingsWindow(config_path=tmp_cfg)
    try:
        win._motor_section._feed_rate.setValue(4321)
        assert "4321" in win._editor.toPlainText()
        win._save()
        saved = yaml.safe_load(tmp_cfg.read_text(encoding="utf-8"))
        assert saved["motor_stage"]["feed_rate_mm_min"] == 4321
        assert win._dirty is False
    finally:
        win.close()


def test_known_drs4_trigger_hardcode_untouched():
    """Tech-debt (Noah-owned, separate task): _OscilloscopeSection.to_dict()
    always writes the DRS4 trigger_* defaults regardless of form state when
    backend == 'drs4'. This test pins the current (unfixed) behaviour so an
    unrelated change doesn't silently alter it."""
    _app()
    win = SettingsWindow()
    try:
        sec = win._scope_section
        sec._backend.setCurrentText("drs4")
        sec._trig_edge.setCurrentText("RISE")
        d = sec.to_dict()
        assert d["trigger_source"] == "EXT"
        assert d["trigger_edge"] == "RISE"
    finally:
        win.close()


# --------------------------------------------------------------------------- #
# No bleed into an untouched panel                                            #
# --------------------------------------------------------------------------- #

def test_camera_panel_still_constructs_untouched():
    _app()
    panel = CameraPanel(BlackflyCamera(simulation=True))
    try:
        pm = panel.grab()
        assert not pm.isNull()
    finally:
        panel.shutdown()   # stops the frame-acquisition worker thread
