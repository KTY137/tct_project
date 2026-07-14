"""The CAMERA panel — migrated onto the round-03 glass kit (wave beat 8/12).

Non-hazard census panel, but a PROGRAM beat: the panel is a two-column shelf
(image/histogram/stats/metadata/actions on the left, acquisition/image-
processing/trigger/info on the right) plus its own modal top-level,
``_ROIDialog``. Mirrors ``tests/test_wave_intensity_render.py`` (the smallest
sibling: one shelf, content-hosting shelf stays unregistered, pure-chrome
sub-cards register) and ``tests/test_wave_device_render.py`` (satellite-window
surface-prep wiring), headless and hardware-free (QT_QPA_PLATFORM=offscreen,
the simulated ``BlackflyCamera`` backend only — never connected in most tests,
per hardware-safety rule 1; the worker-streaming tests below connect the
SIMULATED backend the same way ``tests/test_camera_panel_worker.py`` already
does).

What it proves:

  * the whole panel is now ONE ``GlassPane`` shelf (``#shelfPane``,
    ``register=False`` — a CONTENT consequence: it hosts the live view card,
    the histogram ``pg.PlotWidget`` (Z3), the beam-stats ``MetricGrid`` (Z4)
    and the frame-metadata ``ReadoutCell``\\ s (Z4) directly);
  * the Z-ladder split, both directions: the pure-chrome cards (view & capture
    actions, acquisition, image processing, trigger, camera-info bookkeeping)
    register for glass; the content-hosting cards (live view, histogram, beam
    stats, frame metadata) never do;
  * the live view / histogram canvases stay fixed-dark (``PLOT_BG``) in both
    themes — pyqtgraph/camera-view canvases never migrate onto the glass tint;
  * ``_ROIDialog`` (the modal top-level) gets the same
    ``prepare_window_surface``/``reassert_window_backdrop`` satellite-window
    surface treatment every other material-capable top-level uses;
  * ``refresh_theme`` survives a light -> dark -> light round trip (the
    pre-existing histogram-brush/EmptyState refresh, now alongside the new kit
    surfaces, which resolve purely through the app-wide QSS);
  * the camera worker thread / poll timer are completely untouched by the kit
    wrap: construction still starts the worker, ``shutdown()`` still joins it
    within its bound and is idempotent (mirrors
    ``tests/test_camera_panel_worker.py``, not re-litigated here beyond a
    presentation-adjacent smoke check).

``tests/test_camera_panel_worker.py`` and ``tests/test_camera_blackfly.py``
are READ-ONLY and stay green — they are the authority on the worker/thread
lifecycle and the device driver; this file only proves the glass re-skin
didn't disturb the structure those contracts walk through.
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import pyqtgraph as pg
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QStackedWidget, QWidget

from devices.camera_blackfly import BlackflyCamera
from gui import panel_kit
from gui.camera_panel import CameraPanel, _ROIDialog
from gui.panel_kit import Card, GlassPane, MetricGrid
from gui.status_widgets import ReadoutCell
from gui.style import PLOT_BG, apply_theme


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _panel(connected: bool = False) -> CameraPanel:
    """A CameraPanel over a simulated (never-touching-real-hardware) camera.
    Not connected by default (hardware-safety rule 1 — construction only);
    pass ``connected=True`` only for the worker-streaming smoke check, which
    mirrors the existing pattern in tests/test_camera_panel_worker.py."""
    cam = BlackflyCamera(simulation=True)
    if connected:
        cam.connect()
    return CameraPanel(cam)


def _dispose(panel: CameraPanel) -> None:
    panel.shutdown()
    panel.deleteLater()


def _pump(app, seconds: float = 0.2) -> None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        app.processEvents()
        time.sleep(0.01)


# --------------------------------------------------------------------------- #
# Structure — one shelf holds the whole panel                                 #
# --------------------------------------------------------------------------- #

def test_the_one_shelf_holds_the_whole_panel():
    _app()
    panel = _panel()
    try:
        assert isinstance(panel._shelf, GlassPane)
        assert panel._shelf.objectName() == "shelfPane"
        for attr in ("_view_card", "_hist_card", "_stats_card", "_meta_card",
                     "_actions_card", "_acq_card", "_img_card", "_trig_card",
                     "_info_card"):
            widget = getattr(panel, attr)
            assert panel._shelf.isAncestorOf(widget), f"{attr} floated off the shelf"
        assert isinstance(panel._view_card, Card)
        assert isinstance(panel._hist_card, Card)
        assert isinstance(panel._stats_card, Card)
        assert isinstance(panel._meta_card, Card)
    finally:
        _dispose(panel)


def test_kit_wrap_did_not_detach_anything_worker_still_reachable():
    """Kit-wrap sanity: every attribute the pinned worker/lifecycle tests read
    through directly is still reachable, and the worker itself is untouched
    (still constructed, still running, same thread parent)."""
    _app()
    panel = _panel()
    try:
        assert panel._cam_thread is not None
        assert panel._cam_thread.parent() is not panel
        assert callable(panel.shutdown)
        for attr in ("_img_label", "_hist_plot", "_ro_mean",
                     "_chip_camera", "_btn_live", "_btn_single", "_btn_stop",
                     "_btn_roi"):
            widget = getattr(panel, attr)
            assert panel.isAncestorOf(widget), f"{attr} floated off the panel"
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# The Z-ladder split — chrome cards register, content-hosting cards never do  #
# --------------------------------------------------------------------------- #

def test_chrome_cards_register_content_cards_never_do():
    _app()
    panel = _panel()
    try:
        registered = {id(p) for p in panel_kit.registered_glass_panes()}

        # Chrome — pure buttons/checkboxes/spinboxes/static bookkeeping.
        for attr in ("_actions_card", "_acq_card", "_img_card", "_trig_card",
                     "_info_card"):
            card = getattr(panel, attr)
            assert id(card) in registered, f"{attr} should register for glass"

        # Content — hosts a plot/readout/instrument-screen directly.
        for attr in ("_view_card", "_hist_card", "_stats_card", "_meta_card"):
            card = getattr(panel, attr)
            assert id(card) not in registered, f"{attr} must never register"

        # And the shelf itself never registers either (the content consequence
        # runs through it, not around it).
        assert id(panel._shelf) not in registered
    finally:
        _dispose(panel)


def test_glass_switch_tints_only_the_registered_cards():
    _app()
    panel = _panel()
    try:
        panel_kit.set_panel_glass(True)
        for attr in ("_actions_card", "_acq_card", "_img_card", "_trig_card",
                     "_info_card"):
            assert getattr(panel, attr).property("glassPane") == "true"
        for attr in ("_view_card", "_hist_card", "_stats_card", "_meta_card",
                     "_shelf"):
            assert not getattr(panel, attr).property("glassPane")
        panel_kit.set_panel_glass(False)
        for attr in ("_actions_card", "_acq_card", "_img_card", "_trig_card",
                     "_info_card", "_view_card", "_hist_card", "_stats_card",
                     "_meta_card", "_shelf"):
            assert not getattr(panel, attr).property("glassPane")
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(panel)


def test_shelf_and_content_cards_would_fail_the_zladder_census_if_registered():
    """Pins WHY these stay unregistered: they really do carry the Z-ladder's
    own disqualifier types as descendants."""
    _app()
    panel = _panel()
    try:
        shelf_descendants = [panel._shelf, *panel._shelf.findChildren(QWidget)]
        assert any(isinstance(w, ReadoutCell) for w in shelf_descendants), (
            "expected a ReadoutCell/MetricTile under the shelf")
        assert any(isinstance(w, pg.PlotWidget) for w in shelf_descendants), (
            "expected the histogram pg.PlotWidget under the shelf")

        stats_descendants = [panel._stats_card, *panel._stats_card.findChildren(QWidget)]
        assert any(isinstance(w, ReadoutCell) for w in stats_descendants)
        assert isinstance(
            panel._stats_card.findChild(MetricGrid), MetricGrid)

        hist_descendants = [panel._hist_card, *panel._hist_card.findChildren(QWidget)]
        assert any(isinstance(w, pg.PlotWidget) for w in hist_descendants)

        meta_descendants = [panel._meta_card, *panel._meta_card.findChildren(QWidget)]
        assert any(isinstance(w, ReadoutCell) for w in meta_descendants)
    finally:
        _dispose(panel)


def test_live_view_and_histogram_canvases_stay_fixed_dark():
    """The live view / histogram canvases never migrate onto the glass tint —
    both stay on the PLOT_BG token regardless of the panel-glass switch."""
    _app()
    panel = _panel()
    try:
        assert panel._img_label.styleSheet() == f"background: {PLOT_BG};"
        assert panel._hist_plot.backgroundBrush().color().name().lower() == \
            pg.mkColor(PLOT_BG).name().lower()
        panel_kit.set_panel_glass(True)
        assert panel._img_label.styleSheet() == f"background: {PLOT_BG};"
        assert panel._hist_plot.backgroundBrush().color().name().lower() == \
            pg.mkColor(PLOT_BG).name().lower()
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(panel)


def test_view_stack_still_swaps_offline_stopped_live_states():
    """The kit wrap changed the containing Card only — the QStackedWidget
    empty-state machinery underneath is untouched."""
    _app()
    panel = _panel()
    try:
        assert isinstance(panel._view_stack, QStackedWidget)
        assert panel._view_stack.currentWidget() is panel._empty_offline
        assert isinstance(panel._img_label, QLabel)
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# _ROIDialog — its own satellite window surface                               #
# --------------------------------------------------------------------------- #

def test_roi_dialog_gets_the_satellite_window_surface_treatment(monkeypatch):
    """The modal top-level goes through the same single entry point every
    other material-capable window uses — prepare BEFORE children exist,
    reassert once the form is built."""
    _app()
    calls: list[str] = []

    def fake_prepare(window):
        calls.append("prepare")
        return False

    def fake_reassert(window, reason="apply"):
        calls.append("reassert")
        return "none"

    monkeypatch.setattr("gui.camera_panel.style.prepare_window_surface", fake_prepare)
    monkeypatch.setattr("gui.camera_panel.style.reassert_window_backdrop", fake_reassert)

    dlg = _ROIDialog(0, 0, 640, 480)
    try:
        assert calls == ["prepare", "reassert"], (
            "expected prepare_window_surface before reassert_window_backdrop, "
            f"got {calls}")
    finally:
        dlg.deleteLater()


def test_roi_dialog_still_constructs_and_returns_values():
    """Presentation-only change: the dialog's real behaviour (fields, values())
    is untouched."""
    _app()
    dlg = _ROIDialog(10, 20, 640, 480)
    try:
        assert isinstance(dlg, QDialog)
        assert dlg.values() == (10, 20, 640, 480)
    finally:
        dlg.deleteLater()


# --------------------------------------------------------------------------- #
# Theme — light -> dark -> light survives, both themes render a real frame    #
# --------------------------------------------------------------------------- #

def test_refresh_theme_survives_light_dark_light():
    _app()
    panel = _panel()
    try:
        for mode in ("dark", "light", "dark"):
            panel.refresh_theme(mode)
            assert panel._theme_mode == mode
    finally:
        _dispose(panel)


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_render_migrated_camera_panel_both_themes(mode):
    app = _app()
    apply_theme(app, mode)
    panel = _panel()
    try:
        panel.refresh_theme(mode)
        panel.resize(900, 650)
        panel.show()
        app.processEvents()

        img = panel.grab().toImage()
        assert not img.isNull()
    finally:
        panel.hide()
        _dispose(panel)
        app.setStyleSheet("")   # leave no stylesheet behind for later tests


# --------------------------------------------------------------------------- #
# Worker teardown — untouched by the presentation change                      #
# --------------------------------------------------------------------------- #

def test_shutdown_is_idempotent_after_the_kit_wrap():
    _app()
    panel = _panel()
    panel.shutdown()
    panel.shutdown()   # must not raise
    assert panel._cam_thread is None


def test_worker_still_streams_frames_after_the_kit_wrap():
    """One end-to-end smoke check (mirrors
    tests/test_camera_panel_worker.py::test_panel_streams_frames_from_worker)
    that the kit re-skin did not silently break the render slot's path from a
    connected simulated camera to the (now glass-shelved) image label."""
    app = _app()
    panel = _panel(connected=True)
    try:
        t0 = time.monotonic()
        while panel._last_frame is None and time.monotonic() - t0 < 5.0:
            app.processEvents()
            time.sleep(0.005)
        assert panel._last_frame is not None, \
            "no frame reached the GUI thread from the worker"
        assert "live" in panel._chip_camera.text().lower()
    finally:
        panel.shutdown()
        _pump(app, 0.2)
