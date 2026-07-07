"""Headless tests for the panel-composition kit (gui/panel_kit.py, M2.4).

Follows the existing gui test idiom (see test_status_widgets.py):
QT_QPA_PLATFORM=offscreen, a shared QApplication.instance() helper, no
pytest-qt.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout

from gui.panel_kit import (
    Card, axis_rail_css, eyebrow_title, form_row, panel_header,
    readout_cell, section_header,
)
from gui.status_widgets import ReadoutCell
from gui.style import axis_color


def _app():
    return QApplication.instance() or QApplication([])


def test_card_without_title_has_no_header():
    _app()
    card = Card()
    assert card.objectName() == "cardPane"
    assert card._header is None
    assert isinstance(card.body, QVBoxLayout)


def test_card_with_title_builds_header_row():
    _app()
    card = Card("Channels", "enable · role · live readout")
    assert card._header is not None
    assert card._title_label.text() == "Channels"
    assert card._subtitle_label.text() == "enable · role · live readout"


def test_card_set_title_and_subtitle_update_labels():
    _app()
    card = Card("Old title")
    card.set_title("New title")
    assert card._title_label.text() == "New title"
    # No subtitle was given -> set_subtitle is a safe no-op.
    card.set_subtitle("ignored")
    assert card._subtitle_label is None


def test_card_add_widget_and_add_layout_populate_body():
    _app()
    card = Card("Body test")
    lbl = QLabel("hello")
    card.add_widget(lbl)
    assert card.body.count() == 1

    inner = QVBoxLayout()
    inner.addWidget(QPushButton("go"))
    card.add_layout(inner)
    assert card.body.count() == 2


def test_card_set_rail_applies_axis_color_stylesheet():
    _app()
    card = Card("Laser")
    card.set_rail("laser", "dark")
    css = card.styleSheet()
    color = axis_color("laser", "dark")
    assert color in css
    assert "border-left" in css


def test_section_header_exposes_title_and_subtitle_labels():
    _app()
    row = section_header("Recipe", "edge-TCT · CCE(V) map")
    assert row.title_label.text() == "Recipe"
    assert row.subtitle_label.text() == "edge-TCT · CCE(V) map"


def test_section_header_without_subtitle_leaves_it_none():
    _app()
    row = section_header("Recipe")
    assert row.subtitle_label is None


def test_eyebrow_title_builds_two_stacked_labels():
    _app()
    col = eyebrow_title("TCT Control", "Oscilloscope")
    labels = col.findChildren(QLabel)
    assert len(labels) == 2
    texts = {l.text() for l in labels}
    assert "TCT CONTROL" in texts   # eyebrow is upper-cased
    assert "Oscilloscope" in texts


def test_panel_header_includes_trailing_widgets():
    _app()
    chip = QPushButton("chip")
    bar = panel_header("TCT Control", "Scope", trailing=[chip])
    assert chip in bar.findChildren(QPushButton)


def test_readout_cell_is_a_status_widgets_readout_cell():
    _app()
    cell = readout_cell("HV", "-300 V", min_width=80)
    assert isinstance(cell, ReadoutCell)
    assert cell.value() == "-300 V"


def test_form_row_wraps_caption_and_widget():
    _app()
    spin = QPushButton("42")
    row = form_row("Wavelength", spin, axis="laser", theme_mode="dark")
    assert row.caption_label.text() == "WAVELENGTH"
    color = axis_color("laser", "dark")
    assert color in row.caption_label.styleSheet()
    assert spin.parent() is row


def test_form_row_without_axis_has_no_inline_color():
    _app()
    btn = QPushButton("x")
    row = form_row("Plain", btn)
    assert row.caption_label.styleSheet() == ""


def test_axis_rail_css_formats_selector_and_color():
    css = axis_rail_css("delay", "light", selector="#cardPane", width=3)
    color = axis_color("delay", "light")
    assert css == f"#cardPane {{ border-left: 3px solid {color}; }}"


def test_axis_rail_css_supports_alternate_side_and_width():
    css = axis_rail_css("hazard", "dark", selector="*", side="top", width=2)
    color = axis_color("hazard", "dark")
    assert css == f"* {{ border-top: 2px solid {color}; }}"
