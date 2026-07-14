"""The jog arrows must be visible — in BOTH themes, and after a toggle.

THE BUG (audit 2026-07-14). ``gui/motor_panel.py`` attached every icon with a
bare ``_apply_icon(btn, "fa5s.arrow-up")`` — no ``color=`` (contrast with the
STOP button two lines away, which passed one deliberately). qtawesome then falls
back to its OWN default fill, which is **black**, and bakes it into a pixmap at
construction time. That colour is never read from ``palette(mode)`` and never
re-applied by ``refresh_theme`` (``_restyle_jog_buttons`` only recoloured the
3 px axis stripe), so it is frozen for the life of the widget.

The dark theme — the shipped default — is the case that actually bites: a black
arrow on the dark slate jog button. The controls that MOVE THE STAGE were the
ones that vanished.

These tests assert the pixels, not the code path: they render each icon and
check the ink actually changes with the theme and stays legible against the
button it sits on.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from tests.test_palette_contrast import AA_NON_TEXT, contrast


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _panel():
    from devices.motor_simulated import SimulatedMotorStage
    from gui.motor_panel import MotorPanel

    _app()
    return MotorPanel(SimulatedMotorStage())


def _dominant_ink(button) -> tuple[int, int, int]:
    """The icon's ink colour: the most opaque, most saturated pixel it renders.

    A qtawesome glyph is antialiased, so most pixels are partial alpha — take
    the fully-opaque core, which is the actual ink."""
    from PySide6.QtCore import QSize

    pixmap = button.icon().pixmap(QSize(32, 32))
    assert not pixmap.isNull(), "icon did not render"
    image = pixmap.toImage()
    best = None
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if c.alpha() < 250:
                continue
            best = (c.red(), c.green(), c.blue())
            break
        if best:
            break
    assert best is not None, "icon rendered no opaque pixel"
    return best


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % rgb


def test_jog_icons_are_not_frozen_black():
    """The literal regression: qtawesome's default black, baked in forever."""
    pytest.importorskip("qtawesome")
    panel = _panel()
    try:
        panel.refresh_theme("dark")
        for btn in panel._jog_axis_btns["y"] + panel._jog_axis_btns["z"]:
            ink = _dominant_ink(btn)
            assert ink != (0, 0, 0), (
                "jog arrow is qtawesome-default BLACK on the dark cockpit "
                "theme — it was never given a palette colour")
    finally:
        panel.shutdown()


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_jog_icon_ink_matches_the_button_label_ink(mode):
    pytest.importorskip("qtawesome")
    from gui.style import palette

    panel = _panel()
    try:
        panel.refresh_theme(mode)
        want = palette(mode)["text"].lower()
        for axis in ("x", "y", "z"):
            for btn in panel._jog_axis_btns[axis]:
                assert _hex(_dominant_ink(btn)) == want, (
                    f"[{mode}] jog {axis} icon is {_hex(_dominant_ink(btn))}, "
                    f"expected the button's own label ink {want}")
    finally:
        panel.shutdown()


def test_jog_icons_retint_on_a_theme_toggle_in_BOTH_directions():
    """A one-way test would pass on the old code if the app happened to start in
    the theme whose default ink was legible. Toggle both ways and require the
    pixels to actually MOVE each time."""
    pytest.importorskip("qtawesome")
    from gui.style import palette

    panel = _panel()
    try:
        btn = panel._jog_axis_btns["y"][0]

        panel.refresh_theme("light")
        light_ink = _hex(_dominant_ink(btn))
        panel.refresh_theme("dark")
        dark_ink = _hex(_dominant_ink(btn))
        panel.refresh_theme("light")
        back_to_light = _hex(_dominant_ink(btn))

        assert light_ink == palette("light")["text"].lower()
        assert dark_ink == palette("dark")["text"].lower()
        assert back_to_light == light_ink, "icon did not follow the theme back"
        assert light_ink != dark_ink, "icon ink is frozen across the toggle"
    finally:
        panel.shutdown()


def test_jog_icons_are_legible_against_the_button_they_sit_on():
    """The point of the whole exercise: an arrow you can SEE. A glyph is a
    non-text graphical control indicator -> WCAG 1.4.11's 3:1."""
    pytest.importorskip("qtawesome")
    from gui.style import palette

    panel = _panel()
    try:
        for mode in ("light", "dark"):
            panel.refresh_theme(mode)
            surface = palette(mode)["field"]      # QPushButton's own background
            for axis in ("x", "y", "z"):
                for btn in panel._jog_axis_btns[axis]:
                    got = contrast(_hex(_dominant_ink(btn)), surface)
                    assert got >= AA_NON_TEXT, (
                        f"[{mode}] jog {axis} arrow is {got:.2f}:1 against the "
                        f"jog button surface — invisible")
    finally:
        panel.shutdown()


def test_stop_glyph_wears_the_danger_fills_own_label_ink():
    """The STOP icon sits ON the danger fill, so it must carry ``on_danger`` —
    the same token the QSS puts on ``#dangerBtn`` — not a hardcoded "white"
    that no contrast test can ever see."""
    pytest.importorskip("qtawesome")
    from gui.style import palette

    panel = _panel()
    try:
        stop = next(b for b, name, _tok in panel._themed_icons
                    if name == "fa5s.hand-paper")
        for mode in ("light", "dark"):
            panel.refresh_theme(mode)
            p = palette(mode)
            assert _hex(_dominant_ink(stop)) == p["on_danger"].lower()
            assert contrast(p["on_danger"], p["danger_fill"]) >= AA_NON_TEXT
    finally:
        panel.shutdown()


def test_every_icon_in_the_panel_is_token_bound():
    """Guards the guard: a future icon added with a bare ``_apply_icon`` would
    silently reintroduce the frozen-black bug in this panel.

    THE OLD GUARD WAS BLIND (Mary, review of 4ca8331). It regexed exactly one
    form — ``^\\s+_apply_icon\\(`` — in exactly one file, so it could not see
    ``_icon(...) + setPixmap`` two hundred lines above it in the SAME file, and
    of course not the 50 colourless call sites in the other fourteen. It is now
    an AST scan over all of ``gui/*.py``
    (``tests/test_icon_theming_gui.py::icon_call_sites``), applied here to
    motor_panel: every icon construction in this panel must carry a colour,
    whatever syntax it is written in. The repo-wide version of the same scan
    lives in that module."""
    pytest.importorskip("qtawesome")
    from tests.test_icon_theming_gui import icon_call_sites

    stray = [(f, ln, name) for f, ln, name, coloured in icon_call_sites()
             if f == "motor_panel.py" and not coloured]
    assert not stray, (
        "icon(s) attached without a palette token — use self._register_icon(): "
        f"{stray}")
