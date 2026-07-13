"""Guard-rail for gui/qml_theme.py's ``Theme.specular`` (Task 0, fluent-motion
beat). ``gui/qml_theme.py`` used to carry its own hardcoded
``_SPECULAR_ALPHA = {"light": 0.85, "dark": 0.045}`` table (QColor cannot
parse gui/style.py's ``"rgba(255, 255, 255, a)"`` string) that quietly went
stale against a style.py bump to 0.92/0.14. The fix parses the alpha out of
``gui.style.LIGHT``/``DARK["specular"]`` live on every property access
instead of caching a second copy — this test pins that there is no separate
number left anywhere to drift.
"""
from __future__ import annotations

import re

from PySide6.QtWidgets import QApplication

from gui.qml_theme import Theme, _alpha_from_rgba, set_theme_mode
from gui.style import DARK, LIGHT


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_alpha_from_rgba_parses_style_specular_strings():
    assert _alpha_from_rgba(LIGHT["specular"]) == 0.92
    assert _alpha_from_rgba(DARK["specular"]) == 0.14


def test_theme_specular_alpha_matches_style_for_both_modes():
    _app()
    theme = Theme()
    try:
        for mode, tokens in (("light", LIGHT), ("dark", DARK)):
            set_theme_mode(mode)
            expected = _alpha_from_rgba(tokens["specular"])
            got = theme.specular.alphaF()
            # QColor.setAlphaF() round-trips through its internal (16-bit)
            # storage, so alphaF() is not bit-exact — tolerance well below
            # the 0.92 vs 0.14 gap this test exists to catch, well above the
            # ~1e-5 quantization noise observed.
            assert abs(got - expected) < 1e-3, (
                f"Theme.specular alpha ({mode}) = {got}, expected {expected}"
            )
    finally:
        set_theme_mode("light")


def test_theme_specular_tracks_live_style_mutation():
    """The alpha is read fresh from gui.style's LIGHT/DARK dicts on every
    access (not cached at import/class scope) — the same reason ``_c()``
    re-reads ``palette(_MODE)`` every time: those dicts are mutated in place
    at runtime (``set_glass_amount`` / dev-tool overrides call
    ``_recompute_palettes``, which does ``live.clear(); live.update(merged)``
    on the very LIGHT/DARK objects imported here). A cached alpha would go
    stale exactly like the old hardcoded table did.
    """
    _app()
    theme = Theme()
    set_theme_mode("light")
    original = LIGHT["specular"]
    try:
        LIGHT["specular"] = "rgba(255, 255, 255, 0.5)"
        assert abs(theme.specular.alphaF() - 0.5) < 1e-3
    finally:
        LIGHT["specular"] = original
        set_theme_mode("light")


def test_alpha_from_rgba_rejects_non_rgba_string():
    import pytest

    with pytest.raises(ValueError):
        _alpha_from_rgba("#ffffff")


def test_specular_property_falls_back_when_token_unparseable(caplog):
    """A malformed specular token must NOT raise from inside the ``specular``
    QML @Property getter (an exception there surfaces as an opaque binding
    error with no site — a diagnosis nightmare). It degrades to a warned,
    conservative fallback alpha instead; the strict parser
    (``_alpha_from_rgba``) still raises, so the drift-guard above is unchanged.
    """
    import logging

    import gui.qml_theme as qml_theme

    _app()
    theme = Theme()
    set_theme_mode("light")
    original = LIGHT["specular"]
    qml_theme._specular_parse_warned = False   # so the once-only WARNING fires here
    try:
        LIGHT["specular"] = "not-a-parseable-token"
        with caplog.at_level(logging.WARNING, logger="gui.qml_theme"):
            colour = theme.specular            # must NOT raise
        assert abs(colour.alphaF() - qml_theme._SPECULAR_FALLBACK_ALPHA) < 1e-3
        assert any("specular" in r.getMessage() for r in caplog.records), \
            "no warning breadcrumb logged for the unparseable specular token"
    finally:
        LIGHT["specular"] = original
        qml_theme._specular_parse_warned = False
        set_theme_mode("light")
