"""STAGE_VIEW migrated onto the round-03 glass kit (panel wave, beat 2).

Mirrors ``tests/test_pilot_bias_render.py`` minimally, adapted to what this
panel actually is: a read-only 2D setup schematic (no HV, no numeric-input
widgets), not the pilot's hazard dashboard.

What it proves, headless and hardware-free (QT_QPA_PLATFORM=offscreen, no
device I/O — ``StageView`` never touches a motor, it only draws whatever
``set_limits``/``set_position``/``set_scan_region`` hand it):

  * the panel is now one ``GlassPane`` shelf (``#shelfPane``) carrying a
    ``panel_header`` chrome head (eyebrow + title + the live Z chip) and the
    legend row, with the 2D schematic (``StageView2D``, two live pyqtgraph
    plots) as its body;
  * that shelf opts NOTHING into the panel-glass switch — not for the
    pilot's HV reason, but because it hosts the live X-Y/X-Z plot pair
    directly, which is ``panel_kit.register_glass_pane``'s own HARD
    exclusion ("a pane hosting a pyqtgraph plot ... must NEVER be
    registered");
  * the kit wrap did not detach the 2D view or the Z chip from the widget
    tree (same objects, same attribute names — the frame-contract test
    reads through them via ``panel._stage_view._v2d._top``/``_side``, so a
    silent detach would break geometry it never directly asserts);
  * a live light -> dark -> light switch re-resolves the plot tokens without
    a crash and renders a non-null frame in both themes.

``tests/test_stage_view_frame_contract.py`` is READ-ONLY and stays green —
it is the authority on the marker/envelope frame contract; this file only
proves the glass re-skin didn't disturb the structure that contract test
walks through.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from devices.motor_base import SoftwareLimits
from gui import panel_kit
from gui.panel_kit import GlassPane
from gui.stage_view import StageView, StageView2D, _HAS_PG
from gui.style import apply_theme

_ARTIFACT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "artifacts_claude" / "wave_stage_view"
)

_LIMITS = SoftwareLimits(
    x_min=0.0, x_max=295.0, y_min=0.0, y_max=298.0, z_min=0.0, z_max=50.0,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _dispose(view: StageView) -> None:
    view.deleteLater()


# --------------------------------------------------------------------------- #
# Structure — one shelf, plot-hosting exclusion, nothing detached             #
# --------------------------------------------------------------------------- #

def test_panel_is_one_glass_pane_shelf():
    _app()
    view = StageView(_LIMITS)
    try:
        assert isinstance(view._shelf, GlassPane)
        assert view._shelf.objectName() == "shelfPane"
        assert view.isAncestorOf(view._shelf)
    finally:
        _dispose(view)


def test_stage_view_opts_nothing_into_glass():
    """The shelf's body IS the live plot pair, so it falls under the kit's
    plot-hosting hard exclusion — the same "opts nothing in" shape as the
    pilot's HV dashboard, for a different, equally load-bearing reason."""
    _app()
    view = StageView(_LIMITS)
    try:
        panel_kit.set_panel_glass(True)
        panes = [p for p in panel_kit.registered_glass_panes()
                 if view is p or view.isAncestorOf(p)]
        assert panes == [], "the plot-hosting shelf must opt NOTHING into glass"
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(view)


def test_z_chip_and_2d_view_still_live_on_the_shelf():
    """Kit-wrap sanity: the header's Z chip and the 2D schematic are still
    reachable through the SAME attribute names and are still real descendants
    of this widget — a silent detach during the re-skin would still pass a
    pure attribute check but break rendering/geometry."""
    _app()
    view = StageView(_LIMITS)
    try:
        assert isinstance(view._v2d, StageView2D)
        assert view.isAncestorOf(view._v2d)
        assert view.isAncestorOf(view._z_chip)
        assert view._z_chip.text() == "Z 0.000 mm"
        view.set_position(1.0, 2.0, 3.5)
        assert view._z_chip.text() == "Z 3.500 mm"
    finally:
        _dispose(view)


# --------------------------------------------------------------------------- #
# Theme — light -> dark -> light survives, both themes render a real frame    #
# --------------------------------------------------------------------------- #

def test_refresh_theme_survives_light_dark_light():
    _app()
    view = StageView(_LIMITS, theme_mode="light")
    try:
        for mode in ("dark", "light", "dark"):
            view.refresh_theme(mode)
            assert view._theme_mode == mode
            assert view._v2d._theme_mode == mode
    finally:
        _dispose(view)


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_render_migrated_stage_view_both_themes(mode):
    if not _HAS_PG:
        pytest.skip("pyqtgraph required for the stage-view plot render")
    app = _app()
    apply_theme(app, mode)
    view = StageView(_LIMITS, theme_mode=mode)
    try:
        view.refresh_theme(mode)
        view.set_position(3.0, 4.0, 7.5)
        view.set_scan_region(10.0, 20.0, 10.0, 20.0, 5.0, 15.0)

        view.resize(420, max(520, view.sizeHint().height()))
        view.show()
        app.processEvents()

        img = view.grab().toImage()
        assert not img.isNull()

        _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        out = _ARTIFACT_DIR / f"stage_view_{mode}_token.png"
        assert img.save(str(out)), f"failed to write {out}"
        assert out.exists() and out.stat().st_size > 0
    finally:
        view.hide()
        _dispose(view)
        app.setStyleSheet("")  # leave no stylesheet behind for later tests
