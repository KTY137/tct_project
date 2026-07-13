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
