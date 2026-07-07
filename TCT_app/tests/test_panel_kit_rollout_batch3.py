"""Headless construct/grab checks for the panel_kit rollout — Batch 3 /
"parity pass" (Phase 0.5): the last two un-migrated panels, camera and
analysis.

Follows the existing gui test idiom (see ``test_panel_kit_rollout_batch1.py``):
``QT_QPA_PLATFORM=offscreen``, a shared ``QApplication.instance()`` helper, no
pytest-qt.

Each touched widget is constructed and rendered (``.grab()``) under BOTH
themes (light/dark) to confirm the QGroupBox -> Card swap and the new
``panel_header()``s don't crash construction or leave a blank/zero-size
widget in either theme, and — where the panel exposes one — that
``refresh_theme()`` runs cleanly.  A couple of behavioural spot-checks
confirm the design-system swap kept the panels' public hooks (``_timer``,
``ReadoutCell``s, Card surfaces) and did not put a QGraphicsEffect on any
hot-path plot/frame-view widget (the laser/perf safety rule from
AGENT_PROTOCOL — camera live view, histogram, 2D map, CCE curve).
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame

from devices.camera_blackfly import BlackflyCamera
from gui.analysis_panel import AnalysisPanel
from gui.camera_panel import CameraPanel
from gui.style import WARN_AMBER, WARN_RED, apply_theme


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _grab_both_themes(make_panel, *, has_refresh: bool = True) -> None:
    """Build *make_panel()*, render it under light then dark, call
    ``refresh_theme`` if present, and confirm the pixmap is non-empty both
    times. Always tears the panel down via ``shutdown()``/``_timer.stop()``
    when available (mirrors test_panel_kit_rollout_batch1.py)."""
    app = _app()
    apply_theme(app, "light")
    panel = make_panel()
    try:
        pm_light = panel.grab()
        assert not pm_light.isNull()
        assert pm_light.width() > 0 and pm_light.height() > 0

        apply_theme(app, "dark")
        if has_refresh and hasattr(panel, "refresh_theme"):
            panel.refresh_theme("dark")
        pm_dark = panel.grab()
        assert not pm_dark.isNull()
        assert pm_dark.width() > 0 and pm_dark.height() > 0

        if has_refresh and hasattr(panel, "refresh_theme"):
            panel.refresh_theme("light")
        apply_theme(app, "light")
    finally:
        shutdown = getattr(panel, "shutdown", None)
        if shutdown is not None:
            shutdown()
        timer = getattr(panel, "_timer", None)
        if timer is not None:
            timer.stop()


# --------------------------------------------------------------------------- #
# Construction — both themes                                                  #
# --------------------------------------------------------------------------- #

def test_camera_panel_constructs_both_themes():
    _grab_both_themes(lambda: CameraPanel(BlackflyCamera(simulation=True)))


def test_analysis_panel_constructs_both_themes():
    # AnalysisPanel has no refresh_theme(): it bakes no per-theme instance
    # colours (its plot pens are fixed semantic colours, same idiom as
    # ScopePanel's onset/trailing/CFD markers) — has_refresh is False so the
    # helper doesn't require the hook to exist.
    _grab_both_themes(lambda: AnalysisPanel(), has_refresh=False)


# --------------------------------------------------------------------------- #
# Behavioural spot-checks: presentation swap kept every existing hook alive   #
# --------------------------------------------------------------------------- #

def test_camera_panel_hooks_survive_card_swap():
    _app()
    cam = BlackflyCamera(simulation=True)
    panel = CameraPanel(cam)
    try:
        # New Card sections carry the design-system surface objectName.
        assert len(panel.findChildren(QFrame, "cardPane")) >= 8
        # Beam-stats / frame-info readouts became ReadoutCell instances
        # (readout_cell()) — the Temp readout is a hand-built look-alike
        # (same objectName) so it keeps its tri-state colour override hook.
        assert len(panel.findChildren(QFrame, "readoutCell")) >= 12
        assert panel._temp_frame.objectName() == "readoutCell"
        # Existing public hook other code depends on (tct_gui.py teardown,
        # test_panel_kit_rollout_batch1.py's own "untouched" check).
        assert panel._timer is not None
    finally:
        panel._timer.stop()


def test_camera_panel_temp_readout_tristate_colours():
    """The Temp readout's good/warn/crit colour swap (bench overheat cue)
    survived the QLabel -> readoutCell-look-alike swap, using WARN_AMBER /
    WARN_RED tokens instead of the old hardcoded '#ffaa00' / '#ff4444'."""
    _app()
    cam = BlackflyCamera(simulation=True)
    cam.connect()
    panel = CameraPanel(cam)
    try:
        cam.get_temperature = lambda: 70.0   # >= 65 C -> crit
        panel._refresh()
        assert WARN_RED in panel._lbl_temp.styleSheet()

        cam.get_temperature = lambda: 60.0   # >= 55 C -> warn
        panel._refresh()
        assert WARN_AMBER in panel._lbl_temp.styleSheet()

        cam.get_temperature = lambda: 30.0   # normal -> style resets
        panel._refresh()
        assert panel._lbl_temp.styleSheet() == ""
    finally:
        panel._timer.stop()


def test_analysis_panel_hooks_survive_card_swap():
    _app()
    panel = AnalysisPanel()
    # File-loader / 2D-map / CCE-curve cards.
    assert len(panel.findChildren(QFrame, "cardPane")) >= 3
    # Existing public hooks other code / this panel's own methods depend on.
    assert panel._btn_open is not None
    assert hasattr(panel, "_map_view")
    assert hasattr(panel, "_cce_plot")


def test_hot_path_widgets_have_no_graphics_effect():
    """Laser/perf safety rule: no QGraphicsDropShadow/glow/animated effect on
    a camera frame view or any pyqtgraph plot/histogram — static depth
    (borders, surface, rails) only."""
    _app()
    cam = BlackflyCamera(simulation=True)
    cam_panel = CameraPanel(cam)
    ana_panel = AnalysisPanel()
    try:
        for w in (cam_panel._img_label, cam_panel._hist_plot,
                  ana_panel._map_view, ana_panel._cce_plot):
            assert w.graphicsEffect() is None
    finally:
        cam_panel._timer.stop()


# --------------------------------------------------------------------------- #
# No bleed into other already-migrated panels                                 #
# --------------------------------------------------------------------------- #

def test_motor_panel_still_constructs_untouched_by_this_batch():
    from devices.motor_simulated import SimulatedMotorStage
    from gui.motor_panel import MotorPanel
    _app()
    panel = MotorPanel(SimulatedMotorStage())
    try:
        pm = panel.grab()
        assert not pm.isNull()
    finally:
        panel.shutdown()
