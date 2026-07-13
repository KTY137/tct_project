"""Guard: no widget may paint the CANVAS colour on top of a card/panel.

THE BUG THIS PINS (2026-07-13, Kaya: "Siehst du diese schwarze Box um den Text?
… das zerstört einen großen Teil der Aesthetics"):

``gui/style.py`` painted the canvas with a bare ``QWidget`` type selector::

    QMainWindow, QDialog, QWidget { background: #0A0D13; }

Qt QSS type selectors match SUBCLASSES. ``QLabel`` IS a ``QWidget`` — so every
label (and checkbox, splitter, list, scroll area, tab pane …) got
``background: bg``, and because setting *any* background turns on
``WA_StyledBackground``, it actually PAINTED it. Invisible against the canvas
itself; a black slab behind the text on every card and panel.

The probe below is the measurement that root-caused it: render a widget on a
panel-coloured ``Card`` and read the pixel behind its text. On a correct build
that pixel is the CARD's colour. On the broken build it was ``#0a0d13``.

These tests are theme-agnostic (they compare against the *rendered card*, never
a hard-coded hex) and must fail if anyone re-adds a blanket background rule.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QLabel, QListWidget, QRadioButton, QScrollArea,
    QSplitter, QStackedWidget, QTabWidget, QWidget,
)

from gui.panel_kit import Card
from gui.status_widgets import StatusChip
from gui.style import apply_theme, palette

MODES = ("dark", "light")


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _render_on_card(widget: QWidget) -> tuple[str, str]:
    """Put *widget* on a real ``Card``, render offscreen, and return
    ``(card_surface_hex, pixel_inside_the_widget_hex)``.

    The card pixel is sampled in the card's own padding gutter (never a rounded
    corner); the widget pixel is sampled inside the widget's rect at its right
    edge — past the glyphs, so we read the widget's BACKGROUND, not its text.
    """
    card = Card()
    card.add_widget(widget)
    card.resize(440, 120)
    card.ensurePolished()
    _app().processEvents()

    img = QImage(card.size(), QImage.Format.Format_RGB32)
    img.fill(0)
    card.render(img)

    card_px = img.pixelColor(6, card.height() // 2).name()
    g = widget.geometry()
    inside_px = img.pixelColor(g.right() - 2, g.center().y()).name()
    card.deleteLater()
    return card_px, inside_px


# --------------------------------------------------------------------------- #
# The regression itself: text widgets are transparent, not canvas-coloured      #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("factory,name", [
    (lambda: QLabel("Setup view"), "QLabel"),
    (lambda: QCheckBox("Crosshair"), "QCheckBox"),
    (lambda: QRadioButton("2D"), "QRadioButton"),
])
def test_text_widget_on_a_card_paints_the_card_not_the_canvas(mode, factory, name):
    app = _app()
    apply_theme(app, mode)
    card_px, inside_px = _render_on_card(factory())

    assert inside_px == card_px, (
        f"{name} on a Card paints {inside_px} but the card surface is {card_px} "
        f"({mode} theme) — the black box is back. A text widget must be "
        f"transparent; check for a blanket background rule in gui/style.py."
    )
    # And specifically NOT the canvas (the exact colour of the original bug).
    assert inside_px != palette(mode)["bg"].lower()


# --------------------------------------------------------------------------- #
# Containers inherited the same defect — they are containers, not surfaces      #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("factory,name", [
    (lambda: QWidget(), "QWidget"),
    (lambda: QSplitter(), "QSplitter"),
    (lambda: QStackedWidget(), "QStackedWidget"),
    (lambda: QScrollArea(), "QScrollArea"),
    (lambda: QTabWidget(), "QTabWidget"),
])
def test_container_on_a_card_does_not_punch_a_canvas_hole(mode, factory, name):
    """A plain container nested in a card must show the card through it. These
    all painted the canvas before the fix — QScrollArea and QTabWidget::pane
    from their OWN hard-coded ``background: bg`` rules, the rest from the
    blanket QWidget selector."""
    app = _app()
    apply_theme(app, mode)
    w = factory()
    w.setMinimumHeight(28)
    card_px, inside_px = _render_on_card(w)

    assert inside_px != palette(mode)["bg"].lower(), (
        f"{name} punches a canvas-coloured ({inside_px}) hole through a card "
        f"({card_px}) in the {mode} theme."
    )


# --------------------------------------------------------------------------- #
# The fix must not flatten the things that are SUPPOSED to have a background    #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mode", MODES)
def test_status_chip_keeps_its_own_background(mode):
    """Chips/pills carry their own fill via ID/class selectors, which outrank a
    type selector — making QLabel transparent must not erase them (a status chip
    with no fill is a safety-legibility regression, not just a cosmetic one)."""
    app = _app()
    apply_theme(app, mode)
    card_px, inside_px = _render_on_card(StatusChip("HV LIVE", "crit"))

    assert inside_px != card_px, (
        f"StatusChip lost its own background in the {mode} theme — it now paints "
        f"the bare card surface ({card_px}). Safety chips must stay legible."
    )


@pytest.mark.parametrize("mode", MODES)
def test_item_view_keeps_a_real_surface(mode):
    """Item views are a surface (they hold data), and used to get one only by
    accident from the blanket rule. They must have an explicit one now — and it
    must not be the canvas."""
    app = _app()
    apply_theme(app, mode)
    lst = QListWidget()
    lst.addItem("run_00001/waveforms.h5")
    lst.setMinimumHeight(40)
    _card_px, inside_px = _render_on_card(lst)

    assert inside_px == palette(mode)["panel"].lower(), (
        f"QListWidget should sit on the panel surface, got {inside_px} ({mode})."
    )


# --------------------------------------------------------------------------- #
# Source-level guard: the blanket rule must never come back                     #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mode", MODES)
def test_qss_has_no_blanket_widget_background(mode):
    """The class-of-bug guard. A background on a bare ``QWidget`` type selector
    hits every widget in the app; paint shells by name instead (QMainWindow,
    QDialog, QWidget#mainShell)."""
    from gui.style import build_qss

    qss = build_qss(palette(mode))
    for block in qss.split("}"):
        if "background" not in block or "{" not in block:
            continue
        selectors = block.split("{", 1)[0]
        for sel in selectors.split(","):
            sel = sel.strip()
            # A bare, unqualified QWidget type selector — no #id, no [prop], no
            # ::subcontrol, no :state, no descendant qualifier.
            assert sel != "QWidget", (
                "gui/style.py sets a background on a bare `QWidget` selector "
                "again. Qt QSS type selectors match subclasses, so this paints "
                "the canvas behind every QLabel/QCheckBox/... — the black box. "
                f"Offending block:\n{block.strip()[:200]}"
            )
