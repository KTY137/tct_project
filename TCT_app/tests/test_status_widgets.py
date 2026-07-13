import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from gui.status_widgets import (
    ReadoutCell,
    StatusChip,
    StatusPill,
    normalize_state,
    set_button_busy,
)


def _app():
    return QApplication.instance() or QApplication([])


def test_status_chip_sets_text_and_state_property():
    _app()
    chip = StatusChip("Idle", "neutral")
    chip.set_status("Ready", "good", "all clear")

    assert chip.text() == "Ready"
    assert chip.property("state") == "good"
    assert chip.toolTip() == "all clear"


def test_status_pill_normalizes_simulated_state():
    _app()
    pill = StatusPill("Scope", "simulation")

    assert pill.property("state") == "simulated"


def test_readout_cell_value_roundtrip():
    _app()
    cell = ReadoutCell("HV", "--")
    cell.set_value("+12.3 V")

    assert cell.value() == "+12.3 V"


def test_button_busy_restores_text_and_enabled_state():
    _app()
    button = QPushButton("Apply")

    set_button_busy(button, True, "Applying...")
    assert button.text() == "Applying..."
    assert button.property("state") == "busy"
    assert not button.isEnabled()

    set_button_busy(button, False)
    assert button.text() == "Apply"
    assert button.property("state") == ""
    assert button.isEnabled()


def test_state_aliases_cover_operator_terms():
    # Design law 1 (quiet nominal, D0): nominal states are NEUTRAL grey —
    # "connected" must never resolve to green; color is reserved for
    # abnormal / armed / live states.
    assert normalize_state("connected") == "neutral"
    assert normalize_state("running") == "busy"
    assert normalize_state("on") == "armed"
    assert normalize_state("invalid") == "crit"
