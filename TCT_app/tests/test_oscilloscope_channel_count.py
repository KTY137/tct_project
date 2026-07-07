"""Headless tests for the modular oscilloscope channel-count system.

Covers, without touching hardware:
  * the driver's channel-count precedence — explicit config (clamped DOWN to a
    detected capability) > *IDN? detection > default 4 (2026-07-06 bench:
    querying CH3/CH4 on a 2-channel TBS1052C wedged the VISA session);
  * the DRS4 / Tek-FastFrame backends declaring their real channel count;
  * the config-validator value check on n_channels;
  * ScopePanel.rebuild_channels() re-sizing its cards / curves / trigger
    sources to the scope's current n_channels while preserving survivor state.

The clamp is exercised through _apply_channel_count_from_idn(), the exact
method connect() calls after *IDN? — so no VISA session is opened here.
"""
import numpy as np
import pytest

from devices.oscilloscope import Oscilloscope


# --------------------------------------------------------------------------- #
# Driver: channel-count precedence / capability clamp                         #
# --------------------------------------------------------------------------- #

_IDN_2CH = "TEKTRONIX,TBS1052C,C010198,CF:91.1CT FV:v1.29.30"
_IDN_4CH = "TEKTRONIX,MSO5204B,SN123,FW1"
_IDN_UNKNOWN = "KEYSIGHT,DSOX1204A,SN,FW"


def test_config_exceeding_capability_is_clamped(caplog) -> None:
    # Config asks for 4; *IDN? proves a 2-channel TBS1052C → clamp to 2 + warn.
    scope = Oscilloscope(simulation=False, n_channels=4)
    with caplog.at_level("WARNING"):
        scope._apply_channel_count_from_idn(_IDN_2CH)
    assert scope.n_channels == 2
    assert "clamp" in caplog.text.lower()


def test_config_fewer_than_capability_is_honored() -> None:
    # Config asks for 2 on a 4-channel scope → honored (a valid user choice),
    # no clamp, no warning.
    scope = Oscilloscope(simulation=False, n_channels=2)
    scope._apply_channel_count_from_idn(_IDN_4CH)
    assert scope.n_channels == 2


def test_config_equal_to_capability_is_honored() -> None:
    scope = Oscilloscope(simulation=False, n_channels=2)
    scope._apply_channel_count_from_idn(_IDN_2CH)
    assert scope.n_channels == 2


def test_detection_fills_in_when_no_config() -> None:
    # No explicit config → detection refines the default 4 down to 2.
    scope = Oscilloscope(simulation=False)
    assert scope.n_channels == 4                    # pre-connect default
    scope._apply_channel_count_from_idn(_IDN_2CH)
    assert scope.n_channels == 2


def test_unknown_model_keeps_explicit_config() -> None:
    # Detection returns None → the explicit config is trusted verbatim.
    scope = Oscilloscope(simulation=False, n_channels=4)
    scope._apply_channel_count_from_idn(_IDN_UNKNOWN)
    assert scope.n_channels == 4


def test_unknown_model_keeps_default_when_no_config() -> None:
    scope = Oscilloscope(simulation=False)
    scope._apply_channel_count_from_idn(_IDN_UNKNOWN)
    assert scope.n_channels == 4


def test_simulation_connect_preserves_config_count() -> None:
    # Simulation connect() never queries *IDN?, so an explicit count stands.
    scope = Oscilloscope(simulation=True, n_channels=2)
    scope.connect()
    assert scope.n_channels == 2


# --------------------------------------------------------------------------- #
# Backend capabilities                                                        #
# --------------------------------------------------------------------------- #

def test_drs4_declares_four_channels() -> None:
    from devices.oscilloscope_drs4 import DRS4Oscilloscope
    assert DRS4Oscilloscope(simulation=True).n_channels == 4


def test_tek_fastframe_declares_four_channels() -> None:
    from devices.oscilloscope_tek_fastframe import TekFastFrameOscilloscope
    assert TekFastFrameOscilloscope(simulation=True).n_channels == 4


# --------------------------------------------------------------------------- #
# Config validator                                                            #
# --------------------------------------------------------------------------- #

def test_validator_warns_on_out_of_range_n_channels() -> None:
    from controller.config_validator import validate_config, warnings
    cfg = {"oscilloscope": {"backend": "visa", "simulation": True, "n_channels": 12}}
    warns = warnings(validate_config(cfg))
    assert any("n_channels" in w for w in warns)


def test_validator_warns_on_non_numeric_n_channels() -> None:
    from controller.config_validator import validate_config, warnings
    cfg = {"oscilloscope": {"backend": "visa", "simulation": True, "n_channels": "two"}}
    warns = warnings(validate_config(cfg))
    assert any("n_channels" in w for w in warns)


def test_validator_accepts_valid_n_channels() -> None:
    from controller.config_validator import validate_config, warnings
    cfg = {"oscilloscope": {"backend": "visa", "simulation": True, "n_channels": 2}}
    warns = warnings(validate_config(cfg))
    assert not any("n_channels" in w for w in warns)


# --------------------------------------------------------------------------- #
# ScopePanel.rebuild_channels() — needs an offscreen QApplication             #
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _panel(n_channels: int):
    from gui.scope_panel import ScopePanel
    scope = Oscilloscope(simulation=True, n_channels=n_channels)
    return scope, ScopePanel(scope)


def test_panel_sizes_cards_to_scope_channel_count(qapp) -> None:
    _scope, panel = _panel(2)
    try:
        assert sorted(panel._cards) == [1, 2]
        assert sorted(panel._channels) == [1, 2]
    finally:
        panel.shutdown()


def test_panel_rebuild_grows_and_preserves_survivor_state(qapp) -> None:
    from gui.scope_panel import _HAS_PG
    scope, panel = _panel(2)
    try:
        # Mutate surviving-channel state, then refine 2 → 4 (config change).
        panel._channels[1].enabled = False
        panel._channels[2].role = "Reference"
        scope.n_channels = 4
        panel.rebuild_channels()
        assert sorted(panel._cards) == [1, 2, 3, 4]
        assert sorted(panel._channels) == [1, 2, 3, 4]
        # Survivors kept their state; new channels seeded from defaults.
        assert panel._channels[1].enabled is False
        assert panel._channels[2].role == "Reference"
        assert panel._channels[3].role == "—"
        if _HAS_PG:
            assert sorted(panel._curves) == [1, 2, 3, 4]
    finally:
        panel.shutdown()


def test_panel_rebuild_shrinks(qapp) -> None:
    from gui.scope_panel import _HAS_PG
    scope, panel = _panel(4)
    try:
        assert sorted(panel._cards) == [1, 2, 3, 4]
        # Connect-time refinement 4 → 2 (e.g. a TBS1052C answered *IDN?).
        scope.n_channels = 2
        panel.rebuild_channels()
        assert sorted(panel._cards) == [1, 2]
        assert sorted(panel._channels) == [1, 2]
        if _HAS_PG:
            assert sorted(panel._curves) == [1, 2]
    finally:
        panel.shutdown()


def test_panel_rebuild_noop_when_count_unchanged(qapp) -> None:
    scope, panel = _panel(2)
    try:
        card1 = panel._cards[1]
        scope.n_channels = 2            # unchanged
        panel.rebuild_channels()
        assert panel._cards[1] is card1  # same card object — no rebuild churn
    finally:
        panel.shutdown()


def test_panel_rebuild_refreshes_trigger_sources(qapp) -> None:
    scope, panel = _panel(2)
    try:
        panel._open_trigger()
        dlg = panel._trigger_dialog
        assert dlg is not None
        srcs = [dlg._source.itemText(i) for i in range(dlg._source.count())]
        assert "CH1" in srcs and "CH2" in srcs and "CH3" not in srcs
        # Grow + rebuild discards the cached dialog; a fresh one shows CH3/CH4.
        scope.n_channels = 4
        panel.rebuild_channels()
        assert panel._trigger_dialog is None
        panel._open_trigger()
        srcs2 = [panel._trigger_dialog._source.itemText(i)
                 for i in range(panel._trigger_dialog._source.count())]
        assert "CH3" in srcs2 and "CH4" in srcs2
    finally:
        panel.shutdown()
