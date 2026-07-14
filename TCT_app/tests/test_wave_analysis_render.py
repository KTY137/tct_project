"""ANALYSIS_PANEL migrated onto the round-03 glass kit (panel wave beat 11/12).

Mirrors ``tests/test_wave_scope_render.py`` (wave 9) and
``tests/test_wave_scan_map_render.py`` (the embedded shared-map-view wave),
adapted to what this panel actually is: a program-class, heavily
pyqtgraph-plotted panel (2D map + slice profile, CCE-vs-bias, survey mosaic)
that registers NOTHING for glass — see the module docstring on
``gui/analysis_panel.py`` for the full per-card reasoning.

What it proves, headless and hardware-free (QT_QPA_PLATFORM=offscreen, no
device I/O — this panel never touches a motor/scope/HV, it only loads HDF5
files handed to it):

  * the panel is now one ``GlassPane`` shelf (``#shelfPane``) carrying the
    ``panel_header`` chrome head over the run-header bar / stack body;
  * that shelf, the compact run-header bar (``_header_card``) and the
    "Recent runs" empty-state card (``_recent_runs_card``) all opt NOTHING
    into the panel-glass switch — the Z-ladder census's plot/readout/
    live-value exclusions this panel's own cards fall under;
  * the 3-mode fade_swap wiring (``tests/test_analysis_panel_motion.py``) is
    untouched by the kit wrap;
  * a live light -> dark -> light theme switch survives without a crash and
    renders a non-null frame in both themes.

``tests/test_analysis_panel_motion.py``, ``test_analysis_panel_load_run.py``,
``test_analysis_panel_pose_align.py`` and ``test_analysis_panel_survey.py``
are READ-ONLY and stay green — they are the authority on this panel's
data/behaviour contract; this file only proves the glass re-skin didn't
disturb the structure/wiring those contract tests walk through.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QListWidget, QWidget

import gui.analysis_panel as analysis_panel_module
from gui import panel_kit
from gui.analysis_panel import AnalysisPanel, _SURVEY_MODE_INDEX
from gui.panel_kit import Card, FigureCard, GlassPane
from gui.status_widgets import ReadoutCell, StatusChip
from gui.style import apply_theme


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _dispose(panel: AnalysisPanel) -> None:
    panel.deleteLater()


# --------------------------------------------------------------------------- #
# Structure — one shelf, nothing registered, nothing detached                 #
# --------------------------------------------------------------------------- #

def test_panel_is_one_glass_pane_shelf(tmp_path):
    _app()
    panel = AnalysisPanel(runs_dir=tmp_path)
    try:
        assert isinstance(panel._shelf, GlassPane)
        assert panel._shelf.objectName() == "shelfPane"
        assert panel.isAncestorOf(panel._shelf)
    finally:
        _dispose(panel)


def test_analysis_panel_opts_nothing_into_glass(tmp_path):
    """The shelf's body hosts pyqtgraph FigureCards + MetricTile readouts at
    some descendant depth, and its own two plain Cards (header bar, recent-
    runs list) each host live-value/data-listing content — so this panel
    registers nothing, mirroring BiasPanel's "opts nothing in" shape for the
    same Z-ladder reason."""
    _app()
    panel = AnalysisPanel(runs_dir=tmp_path)
    try:
        panel_kit.set_panel_glass(True)
        panes = [p for p in panel_kit.registered_glass_panes()
                 if panel is p or panel.isAncestorOf(p)]
        assert panes == [], "AnalysisPanel must opt NOTHING into glass"
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(panel)


def test_header_card_and_recent_runs_card_are_never_registered(tmp_path):
    """The two named exclusions, spelled out (the blanket test above proves
    the rule; this proves we did not just fail to register ANYTHING at all
    by accident — these two real Cards are the ones actually excluded)."""
    _app()
    panel = AnalysisPanel(runs_dir=tmp_path)
    try:
        panel_kit.set_panel_glass(True)
        registered = set(map(id, panel_kit.registered_glass_panes()))
        assert id(panel._header_card) not in registered
        assert not panel._header_card.property("glassPane")
        assert id(panel._recent_runs_card) not in registered
        assert not panel._recent_runs_card.property("glassPane")
    finally:
        panel_kit.set_panel_glass(False)
        _dispose(panel)


def test_plot_and_readout_cards_would_fail_the_zladder_census_if_registered(tmp_path):
    """Pins WHY the shelf stays unregistered: it really does carry Z3
    (FigureCard/pg.PlotWidget) and Z4 (ReadoutCell/MetricTile) descendants —
    registering it would be exactly the violation
    ``test_panel_glass_rollout.py``'s live census walks for."""
    pytest.importorskip("pyqtgraph")
    import pyqtgraph as pg

    _app()
    panel = AnalysisPanel(runs_dir=tmp_path)
    try:
        descendants = [panel._shelf, *panel._shelf.findChildren(QWidget)]
        assert any(isinstance(w, (FigureCard, pg.PlotWidget)) for w in descendants), (
            "expected at least one FigureCard/PlotWidget under the shelf")
        assert any(isinstance(w, ReadoutCell) for w in descendants), (
            "expected at least one MetricTile/ReadoutCell under the shelf")
    finally:
        _dispose(panel)


def test_header_card_hosts_live_status_chips_and_recent_runs_hosts_a_list(tmp_path):
    """Confirms the actual disqualifying content named in the module
    docstring — the header bar's live StatusChips and the recent-runs card's
    QListWidget — rather than just trusting the comment."""
    _app()
    panel = AnalysisPanel(runs_dir=tmp_path)
    try:
        header_chips = [w for w in panel._header_card.findChildren(StatusChip)]
        assert len(header_chips) >= 4
        lists = [w for w in panel._recent_runs_card.findChildren(QListWidget)]
        assert lists, "expected the recent-runs QListWidget under its card"
    finally:
        _dispose(panel)


def test_kit_wrap_did_not_detach_anything_from_the_tree(tmp_path):
    """Kit-wrap sanity: every attribute existing tests read through directly
    is still reachable through the SAME attribute name and still a real
    descendant of the panel — a silent detach during the re-skin would still
    pass a pure attribute check but break rendering/geometry."""
    _app()
    panel = AnalysisPanel(runs_dir=tmp_path)
    try:
        for attr in (
            "_btn_open", "_lbl_file", "_chip_file", "_chip_dataset",
            "_chip_map", "_chip_export", "_stack", "_segmented", "_modes",
        ):
            widget = getattr(panel, attr)
            assert panel.isAncestorOf(widget), f"{attr} floated off the shelf"
        assert isinstance(panel._header_card, Card)
        assert isinstance(panel._recent_runs_card, Card)
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# fade_swap mode switch — still wired through the motion kit                  #
# --------------------------------------------------------------------------- #

def test_segmented_control_switch_still_uses_fade_swap(monkeypatch, tmp_path):
    """The kit wrap must not disturb the Task-2 fade_swap wiring pinned by
    tests/test_analysis_panel_motion.py — reuses that file's own spy
    approach rather than duplicating its whole suite."""
    _app()
    panel = AnalysisPanel(runs_dir=tmp_path)
    try:
        calls = []
        real_fade_swap = analysis_panel_module.fade_swap

        def spy(stacked, new_index, **kwargs):
            calls.append((stacked, new_index))
            return real_fade_swap(stacked, new_index, **kwargs)

        monkeypatch.setattr(analysis_panel_module, "fade_swap", spy)

        panel._segmented.set_current("survey")

        assert calls == [(panel._modes, _SURVEY_MODE_INDEX["survey"])]
        assert panel._modes.currentIndex() == _SURVEY_MODE_INDEX["survey"]
    finally:
        _dispose(panel)


# --------------------------------------------------------------------------- #
# Theme — light -> dark -> light survives, both themes render a real frame    #
# --------------------------------------------------------------------------- #

def test_refresh_theme_survives_light_dark_light(tmp_path):
    app = _app()
    apply_theme(app, "light")
    panel = AnalysisPanel(runs_dir=tmp_path)
    try:
        for mode in ("dark", "light", "dark"):
            apply_theme(app, mode)
            panel.refresh_theme(mode)
            assert not panel.grab().isNull()
    finally:
        _dispose(panel)
        app.setStyleSheet("")  # leave no stylesheet behind for later tests


def test_shutdown_is_clean(tmp_path):
    """Construction + teardown must not raise/crash headless — the same
    minimal shutdown-hygiene smoke every wave beat pins."""
    app = _app()
    panel = AnalysisPanel(runs_dir=tmp_path)
    panel.deleteLater()
    app.processEvents()
