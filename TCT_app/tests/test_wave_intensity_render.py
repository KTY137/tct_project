"""The INTENSITY panel — migrated onto the round-03 glass kit (wave beat).

Smallest panel of the wave (non-hazard — "Reference Monitor": 2 tiles + chip +
waveform hero, design system §7). Mirrors ``tests/test_pilot_bias_render.py``
(the pilot) minimally, headless and hardware-free (QT_QPA_PLATFORM=offscreen,
simulated backend only). What it proves:

  * the whole panel is now ONE ``GlassPane`` shelf holding the chrome head,
    the hero ``MetricGrid``, the waveform ``FigureCard`` and the controls
    ``Card`` (the same "one shelf" structure the pilot introduced);
  * the numeric scale input lives in an opaque ``Well`` (§4.4);
  * the Z-ladder split: the pure-chrome controls card registers for glass
    (the kit default for a NON-hazard panel — unlike bias's blanket opt-out),
    while the shelf itself stays unregistered because it hosts the hero
    tiles (Z4 ``ReadoutCell``) and the waveform (Z3 ``FigureCard``) directly —
    the same violation ``tests/test_panel_glass_rollout.py``'s live-registry
    census would catch on ANY panel, hazard or not;
  * flipping the panel-glass switch tints only the registered card, never the
    shelf;
  * a light->dark->light theme switch survives with no ``refresh_theme`` hook
    (none is needed — see the module docstring in ``gui/intensity_panel.py``
    for why, and the pin below for the evidence).
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui import panel_kit
from gui.intensity_panel import IntensityPanel
from gui.panel_kit import Card, FigureCard, GlassPane, MetricGrid, Well
from devices.intensity_simulated import SimulatedIntensityMonitor
from gui.style import apply_theme


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _panel() -> IntensityPanel:
    return IntensityPanel(SimulatedIntensityMonitor())


def _dispose(panel) -> None:
    shutdown = getattr(panel, "shutdown", None)
    if shutdown is not None:
        shutdown()
    panel.deleteLater()


# --------------------------------------------------------------------------- #
# Structure — one shelf holds the whole panel                                 #
# --------------------------------------------------------------------------- #

def test_the_one_shelf_holds_the_whole_panel():
    _app()
    panel = _panel()
    try:
        assert isinstance(panel._shelf, GlassPane)
        assert panel._shelf.objectName() == "shelfPane"
        # Every top-level section is a descendant of the one shelf.
        assert panel._shelf.isAncestorOf(panel._chip_live)
        assert panel._shelf.isAncestorOf(panel._metrics)
        assert panel._shelf.isAncestorOf(panel._figure)
        assert panel._shelf.isAncestorOf(panel._ctrl_card)
        # The hero + waveform kit shapes are unchanged by the migration.
        assert isinstance(panel._metrics, MetricGrid)
        assert isinstance(panel._figure, FigureCard)
        assert isinstance(panel._ctrl_card, Card)
    finally:
        _dispose(panel)


def test_scale_input_lives_in_a_well():
    _app()
    panel = _panel()
    try:
        parent = panel._spin_scale.parentWidget()
        assert isinstance(parent, Well), (
            f"{panel._spin_scale.objectName() or panel._spin_scale} "
            "is not in a Well (§4.4)")
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# The Z-ladder split — pure-chrome card registers, the shelf does not         #
# --------------------------------------------------------------------------- #

def test_ctrl_card_registers_for_glass_the_shelf_does_not():
    """Non-hazard panel: the pure-chrome controls card opts IN (the kit
    default), but the shelf hosts the hero tiles + waveform directly, so it
    can never be a legal glass pane (Baldr's Z-ladder) — a content
    consequence, not a hazard-panel opt-out like bias's."""
    _app()
    panel = _panel()
    try:
        registered = {id(p) for p in panel_kit.registered_glass_panes()}
        assert id(panel._ctrl_card) in registered
        assert id(panel._shelf) not in registered
    finally:
        _dispose(panel)


def test_glass_switch_tints_only_the_registered_card():
    _app()
    panel = _panel()
    try:
        panel_kit.set_panel_glass(True)
        assert panel._ctrl_card.property("glassPane") == "true"
        assert not panel._shelf.property("glassPane")
        panel_kit.set_panel_glass(False)
        assert not panel._ctrl_card.property("glassPane")
        assert not panel._shelf.property("glassPane")
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(panel)


def test_shelf_would_fail_the_zladder_census_if_registered():
    """Pins WHY the shelf stays unregistered: it really does carry a Z4
    readout cell and a Z3 instrument screen as descendants — registering it
    would be exactly the violation ``test_panel_glass_rollout.py``'s live
    census walks for."""
    import pyqtgraph as pg
    from PySide6.QtWidgets import QWidget

    from gui.status_widgets import ReadoutCell

    _app()
    panel = _panel()
    try:
        descendants = [panel._shelf, *panel._shelf.findChildren(QWidget)]
        assert any(isinstance(w, ReadoutCell) for w in descendants), (
            "expected the hero MetricTile (a ReadoutCell) under the shelf")
        assert any(isinstance(w, (FigureCard, pg.PlotWidget)) for w in descendants), (
            "expected the waveform FigureCard under the shelf")
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# Theme switch — no refresh_theme hook needed, by design                      #
# --------------------------------------------------------------------------- #

def test_no_refresh_theme_hook_and_light_dark_light_survives():
    """Pins the "genuinely needs none" call: every kit surface this panel
    grew (GlassPane/Card/Well/MetricGrid) is styled purely through the
    app-wide QSS ``apply_theme()`` regenerates, and the one thing that WOULD
    need re-resolving — the waveform pen — is intentionally fixed-dark
    (unaffected by theme) by the panel's own pre-existing design note. If a
    future change adds a cached theme color, it must also add and wire a
    ``refresh_theme`` — this assertion is the tripwire."""
    app = _app()
    apply_theme(app, "light")
    panel = _panel()
    try:
        assert not hasattr(panel, "refresh_theme")

        assert not panel.grab().isNull()
        apply_theme(app, "dark")
        assert not panel.grab().isNull()
        apply_theme(app, "light")
        assert not panel.grab().isNull()
    finally:
        panel.hide()
        _dispose(panel)
        app.setStyleSheet("")   # leave no stylesheet behind for later tests
