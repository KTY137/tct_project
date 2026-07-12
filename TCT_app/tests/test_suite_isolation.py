"""Guards for the process-global state that made the PARALLEL suite lie.

Background (D3, 2026-07-13): under ``pytest -n auto`` the suite failed tests
that pass serially and pass alone — an order/isolation defect, not a
regression. xdist workers slice the suite differently every run, so a leaked
global lands on a *different* victim test each time (that is why the reported
offenders looked unrelated: a bias-panel hook check, a settings-window header
check, a UI-monkey walk).

Three leak sources are now closed, and these tests keep them closed:

1. ``gui/status_widgets.py::flash_button`` armed an UNOWNED
   ``QTimer.singleShot`` closure over the button — the pending restore
   outlived its widget AND its test, then fired into whatever ran next.
   (Regression tests live with the monkey suite, which is where it was
   caught: ``tests/test_ui_monkey.py::test_flash_button_*``.)
2. ``QSettings("TCT", "TCTSetup")`` reached the developer's real registry
   unless ``tests/test_ui_monkey.py`` happened to be collected; conftest now
   repoints it per process.
3. ``gui/style.py``'s theme-customization globals persisted across tests;
   conftest now restores them.

The tests below are ORDER-DEPENDENT ON PURPOSE: the first of each pair dirties
the state, the second asserts the next test sees a clean slate. That is
exactly the contract xdist relies on. They are safe to reorder/split across
workers — each still passes alone, because the "dirty" test cleans up via the
same conftest fixture under test.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings

from gui import style


# --------------------------------------------------------------------------- #
# QSettings never reaches the real user store                                  #
# --------------------------------------------------------------------------- #

def test_qsettings_is_redirected_away_from_the_real_store():
    s = QSettings("TCT", "TCTSetup")
    assert s.format() == QSettings.Format.IniFormat, (
        "QSettings still defaults to the native store (Windows registry): a "
        "test could write the developer's real theme/geometry, and every xdist "
        "worker would share one key")
    path = s.fileName().replace("\\", "/")
    assert "tct_tests_settings_" in path, (
        f"QSettings is not pointed at the per-process test .ini: {path}")


def test_writing_qsettings_cannot_touch_the_developers_app():
    """Sanity: a test writing settings lands in the throwaway .ini only."""
    s = QSettings("TCT", "TCTSetup")
    s.setValue("theme", "dark")
    s.sync()
    assert "tct_tests_settings_" in s.fileName().replace("\\", "/")
    s.remove("theme")
    s.sync()


# --------------------------------------------------------------------------- #
# gui.style theme-customization globals are restored between tests             #
# --------------------------------------------------------------------------- #

def test_a_dirty_theme_customization_does_not_survive_the_test():
    """Dirty EVERY theme knob and clean up nothing — conftest must undo it."""
    style.set_glass_amount(0.0)
    style.apply_theme_overrides({"accent": "#ff00ff"}, "dark")
    style.apply_theme_overrides({"panel": "#ff00ff"}, "light")
    style.apply_radius_scale("l")
    style.apply_typography(sans="Arial", base_px=style.base_typography()["base_px"] - 2)
    assert style.DARK["accent"] == "#ff00ff"       # really applied


def test_b_next_test_sees_the_shipped_theme_defaults():
    """Runs after the polluter above (and must also pass alone)."""
    assert style.get_glass_amount() == style.DEFAULT_GLASS_AMOUNT
    assert style.theme_overrides("dark") == {}
    assert style.theme_overrides("light") == {}
    assert style.radius_scale() == "m"
    assert style.typography() == {"sans": None, "mono": None,
                                  "hinting": None, "base_px": None}
    assert style.DARK["accent"] == style.ACCENT_DARK
    assert style.FONT_MD == style.base_typography()["base_px"]
    # The in-place palette identity contract still holds (apply_theme does
    # `palette is DARK`), so the restore cannot have rebound the dicts.
    assert style.palette("dark") is style.DARK
    assert style.palette("light") is style.LIGHT
