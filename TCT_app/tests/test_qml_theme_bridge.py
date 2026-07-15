"""Headless tests for the LANTERN Theme-bridge beat (U2-entry plumbing).

Covers docs/design/qml_kit_forge/kit_spec_v1.md §6 + Appendix A (the 42
missing exposures enumerated by docs/CODEX_QUEUE.md §C13):

  (a) completeness — every one of the 42 named exposures exists on the
      ``Theme`` QML singleton and reads non-empty in BOTH themes;
  (b) type sanity — colour properties parse to a valid ``QColor``, numeric
      properties are actually numeric (no NaN, no stray strings);
  (c) the 10 colour exposures resolve 1:1 from ``gui.style.palette()`` via
      ``TOKEN_MAP`` (same contract ``test_qml_shell.py``'s existing
      consistency test already proves for the pre-existing tokens);
  (d) the fixed spec numbers (shadow ladder, blur/frost/focus/ground/motion
      constants) match kit_spec_v1.md Appendix A *exactly* — no rounding;
  (e) ``motionEnabled``/``livingGlassMode``/``livingGlassSpeed`` reflect
      ``gui.app_settings`` live.

VM-style headless: the session ``QApplication`` comes from
``tests/conftest.py``'s autouse fixture — no window/widget is built here.
"""
from __future__ import annotations

import math

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from gui import app_settings


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


# --------------------------------------------------------------------------- #
# The 42 exposures, grouped by expected QML/Python type (kit_spec_v1.md       #
# Appendix A's own grouping/counts — see the module docstring above).         #
# --------------------------------------------------------------------------- #
COLOR_PROPS = [
    "dangerFill", "onDanger", "onArmed", "error", "chip", "edge",
    "edgeShade", "pressed", "disabledBg", "shadowInk",
]  # A.1 (9) + shadowInk (A.4) = 10

INT_CONST_PROPS = [
    # A.2 typography (9)
    "fontRail", "weightRail", "fontPanelTitle", "weightPanelTitle",
    "fontBody", "weightBody", "weightMetricLabel", "weightValue",
    "weightUnit",
    # A.1 radii (2)
    "radiusXl", "radiusShelf",
    # A.3 motion durations (2)
    "motionTap", "motionUnfold",
    # A.5 frost/focus/ground fixed constants (7)
    "blurPane", "blurCard", "blurOverlay", "frostRebakeHzSubtle",
    "frostRebakeHzFull", "focusRingOffsetPx", "groundFlowPeriodS",
]  # 9 + 2 + 2 + 7 = 20

FLOAT_MODE_PROPS = [
    # A.1 glass alphas (2) + A.4 shadow alphas (4) + A.5 focus halo (1)
    "glassPaneAlpha", "glassCardAlpha",
    "shadowA", "shadowB", "shadowC", "shadowD",
    "focusHaloAlpha",
]  # 7

FLOAT_CONST_PROPS = ["groundTintAlphaMax"]  # A.5 (1, already-shipped constant)

BOOL_PROPS = ["motionEnabled"]              # A.3 (1)
STR_PROPS = ["livingGlassMode"]             # A.3 (1)
FLOAT_LIVE_PROPS = ["livingGlassSpeed"]     # A.3 (1)
DICT_PROPS = ["motionSpringUi"]             # A.3 (1, ONE exposure per spec)

ALL_42 = (
    COLOR_PROPS + INT_CONST_PROPS + FLOAT_MODE_PROPS + FLOAT_CONST_PROPS
    + BOOL_PROPS + STR_PROPS + FLOAT_LIVE_PROPS + DICT_PROPS
)


def test_the_42_count_reconciles():
    """The bookkeeping check the brief asks for: exactly 42, no duplicates."""
    assert len(ALL_42) == 42
    assert len(set(ALL_42)) == 42


# --------------------------------------------------------------------------- #
# (a) completeness + (b) type sanity                                          #
# --------------------------------------------------------------------------- #
def test_all_42_lantern_exposures_present_and_non_empty_both_themes():
    _app()
    from gui.qml_theme import Theme, set_theme_mode

    theme = Theme()
    try:
        for mode in ("light", "dark"):
            set_theme_mode(mode)
            for name in ALL_42:
                assert hasattr(theme, name), f"Theme.{name} missing ({mode})"
                value = getattr(theme, name)
                assert value is not None, f"Theme.{name} is None ({mode})"

                if name in COLOR_PROPS:
                    assert isinstance(value, QColor), (
                        f"Theme.{name} ({mode}) is not a QColor: {value!r}")
                    assert value.isValid(), f"Theme.{name} ({mode}) is not a valid colour"
                elif name in DICT_PROPS:
                    assert isinstance(value, dict) and value, (
                        f"Theme.{name} ({mode}) is not a non-empty mapping: {value!r}")
                elif name in STR_PROPS:
                    assert isinstance(value, str) and value.strip() != "", (
                        f"Theme.{name} ({mode}) is not a non-empty string: {value!r}")
                elif name in BOOL_PROPS:
                    assert isinstance(value, bool), (
                        f"Theme.{name} ({mode}) is not a bool: {value!r}")
                else:
                    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
                        f"Theme.{name} ({mode}) is not numeric: {value!r}")
                    assert not (isinstance(value, float) and math.isnan(value)), (
                        f"Theme.{name} ({mode}) is NaN")
    finally:
        set_theme_mode("light")


# --------------------------------------------------------------------------- #
# (c) the 10 colour exposures resolve 1:1 from gui.style.palette()            #
# --------------------------------------------------------------------------- #
def test_lantern_color_exposures_match_style_palette_both_modes():
    _app()
    from gui.qml_theme import TOKEN_MAP, Theme, set_theme_mode
    from gui.style import palette

    theme = Theme()
    try:
        for mode in ("light", "dark"):
            set_theme_mode(mode)
            pal = palette(mode)
            for name in COLOR_PROPS:
                key = TOKEN_MAP[name]
                got = getattr(theme, name).name().lower()
                expected = pal[key].lower()
                assert got == expected, (
                    f"Theme.{name} ({mode}) = {got}, expected palette[{key!r}] = {expected}")
    finally:
        set_theme_mode("light")


# --------------------------------------------------------------------------- #
# (d) fixed spec numbers match kit_spec_v1.md Appendix A exactly (no rounding)#
# --------------------------------------------------------------------------- #
def test_lantern_fixed_constants_match_spec_exactly():
    _app()
    from gui.qml_theme import Theme, set_theme_mode

    theme = Theme()
    try:
        # A.4 shadow ladder — .20/.24/.30/.55 dark, .06/.08/.10/.22 light
        set_theme_mode("dark")
        assert theme.shadowA == 0.20
        assert theme.shadowB == 0.24
        assert theme.shadowC == 0.30
        assert theme.shadowD == 0.55
        assert theme.shadowInk.name().lower() == "#000000"
        set_theme_mode("light")
        assert theme.shadowA == 0.06
        assert theme.shadowB == 0.08
        assert theme.shadowC == 0.10
        assert theme.shadowD == 0.22

        # A.5 frost/blur/focus/ground
        assert theme.blurPane == 40
        assert theme.blurCard == 16
        assert theme.blurOverlay == 28
        assert theme.frostRebakeHzSubtle == 6
        assert theme.frostRebakeHzFull == 12
        assert theme.focusRingOffsetPx == 2
        assert theme.groundFlowPeriodS == 90
        assert theme.groundTintAlphaMax == 0.07
        set_theme_mode("dark")
        assert theme.focusHaloAlpha == 0.35
        set_theme_mode("light")
        assert theme.focusHaloAlpha == 0.25

        # A.3 motion
        assert theme.motionTap == 120
        assert theme.motionUnfold == 280
        spring = theme.motionSpringUi
        assert spring["spring"] == 3.0
        assert spring["damping"] == 0.32

        # A.1 glass-card alpha (SCENE tier)
        set_theme_mode("dark")
        assert theme.glassCardAlpha == 0.62
        set_theme_mode("light")
        assert theme.glassCardAlpha == 0.86

        # A.1 radii (already-shipped RADIUS map)
        assert theme.radiusXl == 20
        assert theme.radiusShelf == 24
    finally:
        set_theme_mode("light")


# --------------------------------------------------------------------------- #
# (e) motionEnabled / livingGlassMode / livingGlassSpeed reflect app_settings #
# --------------------------------------------------------------------------- #
def test_motion_enabled_reflects_app_settings():
    _app()
    from gui.qml_theme import Theme

    theme = Theme()
    original = app_settings.motion_enabled()
    try:
        app_settings.set_motion_enabled(False)
        assert theme.motionEnabled is False
        app_settings.set_motion_enabled(True)
        assert theme.motionEnabled is True
    finally:
        app_settings.set_motion_enabled(original)


def test_living_glass_mode_reflects_app_settings_and_defaults_subtle():
    _app()
    from gui.qml_theme import Theme

    theme = Theme()
    original = app_settings.living_glass_mode()
    try:
        # Ratified default (kit_spec_v1.md §5.3 / DECISIONS.md 2026-07-15
        # "living glass default subtle") — a fresh store with no persisted
        # key reads "subtle", not "off".
        assert app_settings.living_glass_mode() in app_settings.LIVING_GLASS_MODES

        for mode in ("off", "subtle", "full"):
            app_settings.set_living_glass_mode(mode)
            assert app_settings.living_glass_mode() == mode
            assert theme.livingGlassMode == mode

        # Garbage/unknown value fails safe to "subtle", never wedges.
        app_settings.set_living_glass_mode("bogus")
        assert app_settings.living_glass_mode() == "subtle"
        assert theme.livingGlassMode == "subtle"
    finally:
        app_settings.set_living_glass_mode(original)


def test_living_glass_speed_reflects_app_settings_and_clamps():
    _app()
    from gui.qml_theme import Theme

    theme = Theme()
    original = app_settings.living_glass_speed()
    try:
        app_settings.set_living_glass_speed(1.5)
        assert app_settings.living_glass_speed() == 1.5
        assert theme.livingGlassSpeed == 1.5

        # Clamped to the ratified [0.25, 2.0] range.
        app_settings.set_living_glass_speed(99.0)
        assert app_settings.living_glass_speed() == app_settings.LIVING_GLASS_SPEED_MAX
        assert theme.livingGlassSpeed == app_settings.LIVING_GLASS_SPEED_MAX

        app_settings.set_living_glass_speed(-5.0)
        assert app_settings.living_glass_speed() == app_settings.LIVING_GLASS_SPEED_MIN
        assert theme.livingGlassSpeed == app_settings.LIVING_GLASS_SPEED_MIN
    finally:
        app_settings.set_living_glass_speed(original)


def test_living_glass_settings_round_trip_scratch_store(tmp_path):
    """Mirrors tests/test_app_settings.py's scratch-store pattern: the
    accessor itself is store-injectable even though Theme always reads the
    default (global) store."""
    from PySide6.QtCore import QSettings

    settings = QSettings(str(tmp_path / "living_glass.ini"), QSettings.Format.IniFormat)

    assert app_settings.living_glass_mode(settings) == "subtle"
    app_settings.set_living_glass_mode("off", settings)
    assert app_settings.living_glass_mode(settings) == "off"

    assert app_settings.living_glass_speed(settings) == app_settings.LIVING_GLASS_SPEED_DEFAULT
    app_settings.set_living_glass_speed(0.5, settings)
    assert app_settings.living_glass_speed(settings) == 0.5
