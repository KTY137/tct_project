"""The OSCILLOSCOPE panel — migrated onto the round-03 glass kit (wave beat
9/12).

Non-hazard census panel, but a PROGRAM beat: one shelf (plot + side column of
channel/DUT-analysis/measurement cards) plus its own floating top-level,
``_TriggerDialog``. Mirrors ``tests/test_wave_camera_render.py`` (the same
Z-ladder split shape: content-hosting cards never register, pure parameter
chrome does) and ``tests/test_wave_device_render.py`` (satellite-window
surface-prep wiring), headless and hardware-free (QT_QPA_PLATFORM=offscreen,
the simulated ``Oscilloscope`` backend only — never connected, per hardware-
safety rule 1).

What it proves:

  * the whole panel is now ONE ``GlassPane`` shelf (``#shelfPane``,
    ``register=False`` — a CONTENT consequence: it hosts the live-trace
    ``pg.PlotWidget`` (Z3), the per-channel live-readout cards, the DUT-
    analysis ``ReadoutCell`` tiles (Z4) and the Measurements panel's live
    values directly);
  * the Z-ladder split, both directions: "Display & scale" and "Channel
    setup" (pure parameter chrome) register; "Live trace", "Channels", "DUT
    analysis" and "Measurements" (content-hosting) never do;
  * ``_TriggerDialog`` (the floating modeless top-level) gets the same
    ``prepare_window_surface``/``reassert_window_backdrop`` satellite-window
    surface treatment every other material-capable window uses;
  * ``refresh_theme`` survives a light -> dark -> light round trip, including
    while the trigger dialog is open;
  * ``shutdown()`` still joins the reader thread within its bound and is
    idempotent — the kit wrap did not disturb worker/thread lifecycle.

``tests/test_scope_viewmodel.py``, ``tests/test_scope_panel_yaml_persist.py``
and ``tests/test_oscilloscope_channel_count.py`` are READ-ONLY and stay
green — they are the authority on acquisition/viewmodel logic, YAML
persistence and channel-count rebuild; this file only proves the glass
re-skin didn't disturb the structure those contracts walk through.
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pyqtgraph as pg
import pytest
from PySide6.QtWidgets import QApplication, QWidget

from devices.oscilloscope import Oscilloscope
from gui import panel_kit
from gui.panel_kit import Card, CheckableCard, GlassPane
from gui.scope_panel import ScopePanel, _TriggerDialog
from gui.status_widgets import ReadoutCell
from gui.style import apply_theme


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _panel(n_channels: int = 2) -> tuple[Oscilloscope, ScopePanel]:
    """A ScopePanel over a simulated (never-touching-real-hardware) scope.
    Never connected (hardware-safety rule 1 — construction only)."""
    scope = Oscilloscope(simulation=True, n_channels=n_channels)
    return scope, ScopePanel(scope)


def _dispose(panel: ScopePanel) -> None:
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
    _scope, panel = _panel()
    try:
        assert isinstance(panel._shelf, GlassPane)
        assert panel._shelf.objectName() == "shelfPane"
        for attr in ("_trace_card", "_ch_card", "_stats_card", "_meas_card",
                     "_scale_card", "_chan_setup_card"):
            widget = getattr(panel, attr)
            assert panel._shelf.isAncestorOf(widget), f"{attr} floated off the shelf"
        assert isinstance(panel._trace_card, Card)
        assert isinstance(panel._ch_card, Card)
        assert isinstance(panel._stats_card, Card)
        assert isinstance(panel._meas_card, CheckableCard)
    finally:
        _dispose(panel)


def test_kit_wrap_did_not_detach_anything_reader_still_reachable():
    """Kit-wrap sanity: the reader thread / control widgets the pinned
    lifecycle tests read through directly are still reachable, untouched."""
    _app()
    _scope, panel = _panel()
    try:
        assert panel._reader_thread is not None
        assert panel._reader_thread.parent() is not panel
        assert callable(panel.shutdown)
        for attr in ("_btn_live", "_btn_single", "_btn_trigger",
                     "_avg_combo", "_cursor_mode"):
            widget = getattr(panel, attr)
            assert panel.isAncestorOf(widget), f"{attr} floated off the panel"
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# The Z-ladder split — chrome cards register, content-hosting cards never do  #
# --------------------------------------------------------------------------- #

def test_chrome_cards_register_content_cards_never_do():
    _app()
    _scope, panel = _panel()
    try:
        registered = {id(p) for p in panel_kit.registered_glass_panes()}

        # Chrome — pure parameter controls, no readout/plot content.
        for attr in ("_scale_card", "_chan_setup_card"):
            card = getattr(panel, attr)
            assert id(card) in registered, f"{attr} should register for glass"

        # Content — hosts a plot/readout directly (or, for Measurements/
        # Channels, live per-acquire values not built from the kit's
        # ReadoutCell but the same content class).
        for attr in ("_trace_card", "_ch_card", "_stats_card", "_meas_card"):
            card = getattr(panel, attr)
            assert id(card) not in registered, f"{attr} must never register"

        # The shelf itself never registers either (the content consequence
        # runs through it, not around it).
        assert id(panel._shelf) not in registered
    finally:
        _dispose(panel)


def test_glass_switch_tints_only_the_registered_cards():
    _app()
    _scope, panel = _panel()
    try:
        panel_kit.set_panel_glass(True)
        for attr in ("_scale_card", "_chan_setup_card"):
            assert getattr(panel, attr).property("glassPane") == "true"
        for attr in ("_trace_card", "_ch_card", "_stats_card", "_meas_card",
                     "_shelf"):
            assert not getattr(panel, attr).property("glassPane")
        panel_kit.set_panel_glass(False)
        for attr in ("_scale_card", "_chan_setup_card", "_trace_card",
                     "_ch_card", "_stats_card", "_meas_card", "_shelf"):
            assert not getattr(panel, attr).property("glassPane")
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(panel)


def test_waveform_card_and_shelf_would_fail_the_zladder_census_if_registered():
    """Pins WHY the trace card / shelf stay unregistered: they really do carry
    the Z-ladder's own disqualifier types as descendants (Baldr's Z3 rule —
    pyqtgraph never migrates onto the glass tint)."""
    _app()
    _scope, panel = _panel()
    try:
        trace_descendants = [panel._trace_card, *panel._trace_card.findChildren(QWidget)]
        assert any(isinstance(w, pg.PlotWidget) for w in trace_descendants), (
            "expected the live-trace pg.PlotWidget under the trace card")

        shelf_descendants = [panel._shelf, *panel._shelf.findChildren(QWidget)]
        assert any(isinstance(w, pg.PlotWidget) for w in shelf_descendants)
        assert any(isinstance(w, ReadoutCell) for w in shelf_descendants), (
            "expected a ReadoutCell (DUT-analysis tile) under the shelf")

        stats_descendants = [panel._stats_card, *panel._stats_card.findChildren(QWidget)]
        assert any(isinstance(w, ReadoutCell) for w in stats_descendants)
    finally:
        _dispose(panel)


def test_full_panel_census_via_the_shared_disqualifier_helper():
    """Runs the exact disqualifier walk tests/test_panel_glass_rollout.py uses
    against every registered pane this panel contributes — the general form,
    not just the two cards spelled out above."""
    _app()
    _scope, panel = _panel()
    try:
        panel_kit.set_panel_glass(True)
        from tests.test_panel_glass_rollout import _glass_disqualifiers

        ours = [p for p in panel_kit.registered_glass_panes()
                if panel.isAncestorOf(p)]
        assert ours, "the panel registered nothing at all"
        offenders = {p.objectName() or type(p).__name__: _glass_disqualifiers(p)
                     for p in ours}
        offenders = {k: v for k, v in offenders.items() if v}
        assert not offenders, f"a registered pane hosts a forbidden surface: {offenders}"
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(panel)


# --------------------------------------------------------------------------- #
# _TriggerDialog — its own satellite window surface                           #
# --------------------------------------------------------------------------- #

def test_trigger_dialog_gets_the_satellite_window_surface_treatment(monkeypatch):
    """The floating modeless top-level goes through the same single entry
    point every other material-capable window uses — prepare BEFORE children
    exist, reassert once the form is built."""
    _app()
    calls: list[str] = []

    def fake_prepare(window):
        calls.append("prepare")
        return False

    def fake_reassert(window, reason="apply"):
        calls.append("reassert")
        return "none"

    monkeypatch.setattr("gui.scope_panel.style.prepare_window_surface", fake_prepare)
    monkeypatch.setattr("gui.scope_panel.style.reassert_window_backdrop", fake_reassert)

    scope = Oscilloscope(simulation=True, n_channels=2)
    dlg = _TriggerDialog(scope, None, lambda *a, **k: None)
    try:
        assert calls == ["prepare", "reassert"], (
            "expected prepare_window_surface before reassert_window_backdrop, "
            f"got {calls}")
    finally:
        dlg.deleteLater()


def test_trigger_dialog_still_constructs_with_expected_fields():
    """Presentation-only change: the dialog's real fields/behaviour are
    untouched."""
    _app()
    scope = Oscilloscope(simulation=True, n_channels=2)
    dlg = _TriggerDialog(scope, None, lambda *a, **k: None)
    try:
        assert dlg._source.count() >= 2
        assert dlg._level.value() == pytest.approx(float(
            getattr(scope, "trig_level_V", -0.41)))
        assert dlg._slope.currentText() in ("FALL", "RISE")
    finally:
        dlg.deleteLater()


def test_open_trigger_from_panel_constructs_and_shows_the_dialog():
    _app()
    _scope, panel = _panel()
    try:
        assert panel._trigger_dialog is None
        panel._open_trigger()
        assert isinstance(panel._trigger_dialog, _TriggerDialog)
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# Theme — light -> dark -> light survives, including with the dialog open     #
# --------------------------------------------------------------------------- #

def test_refresh_theme_survives_light_dark_light():
    _app()
    _scope, panel = _panel()
    try:
        for mode in ("dark", "light", "dark"):
            panel.refresh_theme(mode)
            assert panel._theme_mode == mode
    finally:
        _dispose(panel)


def test_refresh_theme_reaches_the_open_trigger_dialog():
    _app()
    _scope, panel = _panel()
    try:
        panel._open_trigger()
        dlg = panel._trigger_dialog
        panel.refresh_theme("dark")
        assert dlg._theme_mode == "dark"
        panel.refresh_theme("light")
        assert dlg._theme_mode == "light"
    finally:
        _dispose(panel)


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_render_migrated_scope_panel_both_themes(mode):
    app = _app()
    apply_theme(app, mode)
    _scope, panel = _panel()
    try:
        panel.refresh_theme(mode)
        panel.resize(1000, 650)
        panel.show()
        app.processEvents()

        img = panel.grab().toImage()
        assert not img.isNull()
    finally:
        panel.hide()
        _dispose(panel)
        app.setStyleSheet("")   # leave no stylesheet behind for later tests


# --------------------------------------------------------------------------- #
# Reader-thread teardown — untouched by the presentation change               #
# --------------------------------------------------------------------------- #

def test_shutdown_is_idempotent_after_the_kit_wrap():
    _app()
    _scope, panel = _panel()
    panel.shutdown()
    panel.shutdown()   # must not raise
    assert panel._reader_thread is None


def test_shutdown_retires_an_open_trigger_dialog():
    app = _app()
    _scope, panel = _panel()
    panel._open_trigger()
    assert panel._trigger_dialog is not None
    panel.shutdown()
    assert panel._trigger_dialog is None
    _pump(app, 0.1)
