"""SCAN_MAP_VIEW migrated onto the round-03 glass kit (panel wave beat).

Mirrors ``tests/test_pilot_bias_render.py`` (the pilot) and
``tests/test_wave_stage_view_render.py`` (wave 1), adapted to what this
widget actually is: a reusable, EMBEDDED map renderer (no HV, no top-level
tab of its own) hosted below ``ScanViewerPanel``'s and ``AnalysisPanel``'s
own page-level ``panel_header`` — the same nested-widget shape
``StageView``/``MotorPanel`` already established for this wave.

What it proves, headless and hardware-free (QT_QPA_PLATFORM=offscreen, no
device I/O — this widget never touches a motor/scope, it only accumulates
``controller.scan_controller.ScanResult`` points handed to it):

  * the widget is now one ``GlassPane`` shelf (``#shelfPane``) carrying a
    ``panel_header`` chrome head (eyebrow + title + the point-count status
    chip, re-parented from the toolbar) over the toolbar / map stack /
    cursor-readout body;
  * that shelf opts NOTHING into the panel-glass switch — the same
    plot-hosting hard exclusion (design law 8 / Baldr's Z-ladder census)
    ``StageView`` hit, because the shelf's body directly hosts the
    ``FigureCard`` wrapping the live ``pyqtgraph.ImageView`` map;
  * the quantity combo recesses into an opaque ``Well`` (§4.4);
  * the kit wrap did not detach anything from the widget tree — every
    attribute name the pinned test and the two host panels read through
    (``_combo_qty``, ``_chip_points``, ``_btn_freeze``, ``_btn_export_png``,
    ``_btn_export_csv``, ``_figure_card``, ``_stack``, ``_lbl_cursor``) is
    still reachable and still a real descendant;
  * a live light -> dark -> light switch re-resolves the map canvas/axis
    pens without a crash and renders a non-null frame in both themes.

``tests/test_scan_map_view.py`` is READ-ONLY and stays green — it is the
authority on the widget's data/render contract (streaming, batch load,
freeze-levels, NaN honesty, export); this file only proves the glass re-skin
didn't disturb the structure that contract test walks through.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from controller.scan_controller import ScanPoint, ScanResult
from gui import panel_kit
from gui.panel_kit import FigureCard, GlassPane, Well
from gui.scan_map_view import ScanMapView, _HAS_PG
from gui.style import apply_theme

_ARTIFACT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "artifacts_claude" / "wave_scan_map_view"
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _dispose(view: ScanMapView) -> None:
    view.deleteLater()


def _result(x: float, y: float, *, charge: float = 1.0, index: int = 0) -> ScanResult:
    return ScanResult(
        point=ScanPoint(x_mm=x, y_mm=y, z_mm=0.0, index=index),
        timestamp=0.0,
        ref_amplitude_V=0.5,
        ref_charge_pC=2.0,
        dut_amplitude_V=0.3,
        dut_charge_pC=charge,
        dut_charge_norm=charge / 2.0,
        baseline_rms_V=0.001,
        drift_time_s=1e-9,
        rise_time_s=2e-9,
        cfd_time_s=3e-9,
    )


# --------------------------------------------------------------------------- #
# Structure — one shelf, plot-hosting exclusion, nothing detached             #
# --------------------------------------------------------------------------- #

def test_panel_is_one_glass_pane_shelf():
    _app()
    view = ScanMapView()
    try:
        assert isinstance(view._shelf, GlassPane)
        assert view._shelf.objectName() == "shelfPane"
        assert view.isAncestorOf(view._shelf)
    finally:
        _dispose(view)


def test_scan_map_view_opts_nothing_into_glass():
    """The shelf's body directly hosts the live map FigureCard, so it falls
    under the kit's plot-hosting hard exclusion — the same "opts nothing in"
    shape as StageView (wave 1), for the same reason: register_glass_pane's
    own hard exclusion refuses any pane hosting a pyqtgraph plot/FigureCard
    descendant (design law 8)."""
    _app()
    view = ScanMapView()
    try:
        panel_kit.set_panel_glass(True)
        panes = [p for p in panel_kit.registered_glass_panes()
                 if view is p or view.isAncestorOf(p)]
        assert panes == [], "the plot-hosting shelf must opt NOTHING into glass"
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(view)


def test_shelf_would_fail_the_zladder_census_if_registered():
    """Pins WHY the shelf stays unregistered: it really does carry a Z3
    instrument screen (FigureCard/pyqtgraph.PlotWidget) as a descendant —
    registering it would be exactly the violation
    ``test_panel_glass_rollout.py``'s live census walks for."""
    if not _HAS_PG:
        pytest.skip("pyqtgraph required")
    import pyqtgraph as pg

    _app()
    view = ScanMapView()
    try:
        descendants = [view._shelf, *view._shelf.findChildren(QWidget)]
        assert any(isinstance(w, (FigureCard, pg.PlotWidget)) for w in descendants), (
            "expected the map FigureCard under the shelf")
    finally:
        _dispose(view)


def test_quantity_combo_lives_in_a_well():
    _app()
    view = ScanMapView()
    try:
        parent = view._combo_qty.parentWidget()
        assert isinstance(parent, Well), (
            f"{view._combo_qty.objectName() or view._combo_qty} is not in a Well (§4.4)")
    finally:
        _dispose(view)


def test_kit_wrap_did_not_detach_anything_from_the_tree():
    """Kit-wrap sanity: every attribute the pinned test and the two host
    panels (ScanViewerPanel, AnalysisPanel) read through directly is still
    reachable through the SAME attribute name and still a real descendant —
    a silent detach during the re-skin would still pass a pure attribute
    check but break rendering/geometry."""
    _app()
    view = ScanMapView()
    try:
        for attr in ("_combo_qty", "_chip_points", "_btn_freeze",
                     "_btn_export_png", "_btn_export_csv", "_lbl_cursor"):
            widget = getattr(view, attr)
            assert view.isAncestorOf(widget), f"{attr} floated off the shelf"
        if _HAS_PG:
            assert view.isAncestorOf(view._figure_card)
            assert view.isAncestorOf(view._stack)
        # The point-count chip re-parented into the header trailing slot —
        # still the SAME object, its .text() contract is untouched.
        assert view._chip_points.text() == "No data"
    finally:
        _dispose(view)


# --------------------------------------------------------------------------- #
# Theme — light -> dark -> light survives, both themes render a real frame    #
# --------------------------------------------------------------------------- #

def test_refresh_theme_survives_light_dark_light():
    _app()
    view = ScanMapView()
    try:
        for mode in ("dark", "light", "dark"):
            view.refresh_theme(mode)
            assert view._theme_mode == mode
    finally:
        _dispose(view)


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_render_migrated_scan_map_view_both_themes(mode):
    if not _HAS_PG:
        pytest.skip("pyqtgraph required for the scan-map render")
    app = _app()
    apply_theme(app, mode)
    view = ScanMapView()
    try:
        view.refresh_theme(mode)
        for (x, y) in [(0.0, 0.0), (0.0, 1.0), (1.0, 0.0), (1.0, 1.0)]:
            view.update_point(_result(x, y, charge=x + y + 1.0))
        view.flush_pending()

        view.resize(520, max(520, view.sizeHint().height()))
        view.show()
        app.processEvents()

        img = view.grab().toImage()
        assert not img.isNull()

        _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        out = _ARTIFACT_DIR / f"scan_map_view_{mode}_token.png"
        assert img.save(str(out)), f"failed to write {out}"
        assert out.exists() and out.stat().st_size > 0
    finally:
        view.hide()
        _dispose(view)
        app.setStyleSheet("")  # leave no stylesheet behind for later tests
