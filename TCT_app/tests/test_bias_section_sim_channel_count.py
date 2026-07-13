"""GUI half of the sim_channel_count beat (backend landed as a75dfba).

Paul's findings, reproduced here as regressions:

  1. ``_BiasSection`` had NO simulated-backend frame — nowhere to set
     ``bias_supply.sim_channel_count`` (Kaya's literal symptom: "I can't
     find the setting").
  2. ``_BiasSection.to_dict()``'s simulated branch emitted only
     ``{backend, simulation, compliance_A}`` — a hand-edited
     ``sim_channel_count`` (and ``channel``) in devices.yaml was SILENTLY
     DROPPED the next time Quick Settings saved. That is a config-eating
     bug independent of the new key.

Follows the existing gui test idiom (see
``test_settings_window_panel_kit_rollout.py``): ``QT_QPA_PLATFORM=offscreen``,
a shared ``QApplication.instance()`` helper, no pytest-qt.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from gui.settings_window import _BiasSection
from gui.style import apply_theme


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


# --------------------------------------------------------------------------- #
# Round trip -- the silent-drop regression                                    #
# --------------------------------------------------------------------------- #

def test_sim_channel_count_and_channel_load_into_widgets():
    _app()
    cfg = {"backend": "simulated", "sim_channel_count": 3, "channel": 1}
    sec = _BiasSection(cfg)
    assert sec._sim_count.value() == 3
    assert sec._sim_channel.value() == 1
    assert sec._sim_channel.maximum() == 2  # count - 1


def test_sim_channel_count_and_channel_round_trip_through_to_dict():
    """The regression Paul flagged: a hand-edited sim_channel_count/channel
    must survive a Quick Settings save, not be silently dropped."""
    _app()
    cfg = {"backend": "simulated", "sim_channel_count": 3, "channel": 1,
           "compliance_A": 100e-6, "simulation": True}
    sec = _BiasSection(cfg)
    d = sec.to_dict()
    assert d["sim_channel_count"] == 3
    assert d["channel"] == 1
    assert d["backend"] == "simulated"


def test_sim_channel_count_defaults_to_one_when_absent():
    _app()
    sec = _BiasSection({"backend": "simulated"})
    assert sec._sim_count.value() == 1
    assert sec._sim_channel.value() == 0
    d = sec.to_dict()
    assert d["sim_channel_count"] == 1
    assert d["channel"] == 0


# --------------------------------------------------------------------------- #
# Backend switch show/hide                                                    #
# --------------------------------------------------------------------------- #

def test_simulated_frame_visible_only_for_simulated_backend():
    _app()
    sec = _BiasSection({"backend": "iseg"})
    assert not sec._simulated_frame.isVisibleTo(sec)
    assert sec._iseg_frame.isVisibleTo(sec)

    idx = sec._backend.findText("simulated")
    assert idx >= 0
    sec._backend.setCurrentIndex(idx)
    assert sec._simulated_frame.isVisibleTo(sec)
    assert not sec._iseg_frame.isVisibleTo(sec)
    assert not sec._keithley_frame.isVisibleTo(sec)
    assert not sec._e4c_frame.isVisibleTo(sec)


def test_simulated_frame_hidden_for_other_backends():
    _app()
    sec = _BiasSection({"backend": "simulated"})
    assert sec._simulated_frame.isVisibleTo(sec)

    for backend in ("keithley", "e4control", "iseg"):
        idx = sec._backend.findText(backend)
        assert idx >= 0
        sec._backend.setCurrentIndex(idx)
        assert not sec._simulated_frame.isVisibleTo(sec)


# --------------------------------------------------------------------------- #
# Count <-> primary-channel lockstep                                          #
# --------------------------------------------------------------------------- #

def test_channel_spin_max_follows_count_spin():
    _app()
    sec = _BiasSection({"backend": "simulated", "sim_channel_count": 5, "channel": 4})
    assert sec._sim_channel.maximum() == 4

    sec._sim_count.setValue(2)
    assert sec._sim_channel.maximum() == 1
    # The validator's channel >= sim_channel_count is a hard ERROR; the
    # editor must clamp the primary channel down with the new ceiling
    # rather than let the pair drift out of range.
    assert sec._sim_channel.value() <= 1

    sec._sim_count.setValue(16)
    assert sec._sim_channel.maximum() == 15


def test_sim_count_range_matches_validator_ceiling():
    """Range must mirror controller.config_validator._MAX_SIM_BIAS_CHANNELS
    -- if that constant ever changes, this test (and the widget) should
    move with it since both import the same symbol."""
    from controller.config_validator import _MAX_SIM_BIAS_CHANNELS
    _app()
    sec = _BiasSection({"backend": "simulated"})
    assert sec._sim_count.minimum() == 1
    assert sec._sim_count.maximum() == _MAX_SIM_BIAS_CHANNELS


# --------------------------------------------------------------------------- #
# changed signal wiring -- Apply flow must see edits                          #
# --------------------------------------------------------------------------- #

def test_sim_count_and_channel_edits_fire_changed_signal():
    _app()
    sec = _BiasSection({"backend": "simulated", "sim_channel_count": 4, "channel": 0})
    seen = []
    sec.changed.connect(lambda: seen.append(True))

    sec._sim_count.setValue(2)
    assert seen, "sim_channel_count edit did not fire changed"
    seen.clear()

    sec._sim_channel.setValue(1)
    assert seen, "channel edit did not fire changed"


# --------------------------------------------------------------------------- #
# End-to-end via SettingsWindow -- exercises the real load/save path          #
# --------------------------------------------------------------------------- #

_REAL_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "devices.yaml"


@pytest.fixture(autouse=True)
def _stub_visa_scan(monkeypatch):
    monkeypatch.setattr("devices.waveform_generator.list_visa_resources", lambda: [])


@pytest.fixture(autouse=True)
def _stub_save_dialog(monkeypatch):
    monkeypatch.setattr("gui.settings_window.QMessageBox.information", lambda *a, **k: None)


def test_settings_window_round_trips_sim_channel_count_to_disk(tmp_path):
    import shutil
    import yaml
    from gui.settings_window import SettingsWindow

    _app()
    cfg_path = tmp_path / "devices.yaml"
    shutil.copy(_REAL_CONFIG, cfg_path)

    win = SettingsWindow(config_path=cfg_path)
    try:
        idx = win._bias_section._backend.findText("simulated")
        assert idx >= 0
        win._bias_section._backend.setCurrentIndex(idx)
        win._bias_section._sim_count.setValue(3)
        win._bias_section._sim_channel.setValue(1)
        win._save()

        on_disk = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        assert on_disk["bias_supply"]["backend"] == "simulated"
        assert on_disk["bias_supply"]["sim_channel_count"] == 3
        assert on_disk["bias_supply"]["channel"] == 1
    finally:
        win.close()


# --------------------------------------------------------------------------- #
# Headless construction + theme-switch smoke test                            #
# --------------------------------------------------------------------------- #

def test_bias_section_constructs_and_survives_theme_switch():
    app = _app()
    cfg = {"backend": "simulated", "sim_channel_count": 3, "channel": 1}

    apply_theme(app, "light")
    sec = _BiasSection(cfg, theme_mode="light")
    pm_light = sec.grab()
    assert not pm_light.isNull()

    apply_theme(app, "dark")
    sec_dark = _BiasSection(cfg, theme_mode="dark")
    pm_dark = sec_dark.grab()
    assert not pm_dark.isNull()

    apply_theme(app, "light")
