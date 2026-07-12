"""Headless tests for the live Scan Viewer (``gui/scan_viewer_panel.py``,
cockpit build-order step 5 — docs/design/cockpit_style_overhaul.md Phase 2,
docs/research/scan_viewer_design_review.md).

Follows the existing gui test idiom (see ``test_scan_map_view.py`` /
``test_panel_kit_cockpit.py``): ``QT_QPA_PLATFORM=offscreen``, a shared
``QApplication.instance()`` helper, no pytest-qt, no hardware/simulated
backends (this panel never touches a device — it only consumes signals fed
into its slots, matching ``gui/scan_coordinator.py``'s interface).
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ast
import inspect
import re

import pytest
from PySide6.QtWidgets import QApplication

from controller.scan_controller import ScanPoint, ScanResult, ZFocusScanConfig
from gui.scan_viewer_panel import ScanViewerPanel
from gui.style import apply_theme


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _result(x: float, y: float, z: float = 0.0, *, charge: float = 1.0, index: int = 0) -> ScanResult:
    return ScanResult(
        point=ScanPoint(x_mm=x, y_mm=y, z_mm=z, index=index),
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
# Construction                                                                #
# --------------------------------------------------------------------------- #

def test_construct_headless_no_hardware():
    _app()
    panel = ScanViewerPanel()
    assert panel._run_active is False
    assert panel._last_run_path is None


def test_initial_state_shows_empty_state_and_disabled_run_control():
    _app()
    panel = ScanViewerPanel()
    # Empty placeholder now lives INSIDE ScanMapView (map toolbar stays
    # visible pre-run, design system §7) — no panel-level stack anymore.
    assert not panel._map_view.is_showing_map()
    assert not panel._btn_pause.isEnabled()
    assert not panel._btn_abort.isEnabled()
    assert not panel._btn_open_analysis.isEnabled()
    assert panel._finished_banner.isHidden()


def test_map_toolbar_reachable_in_empty_state():
    """Design system §7: quantity/freeze/export stay present before any run."""
    _app()
    panel = ScanViewerPanel()
    assert not panel._map_view.is_showing_map()
    # The toolbar widgets are OUTSIDE the internal empty/map stack: not
    # hidden by the placeholder page.
    assert not panel._map_view._combo_qty.isHidden()
    assert not panel._map_view._btn_freeze.isHidden()
    assert not panel._map_view._btn_export_png.isHidden()
    assert not panel._map_view._btn_export_csv.isHidden()


# --------------------------------------------------------------------------- #
# Simulated run: started -> points -> progress -> finished                    #
# --------------------------------------------------------------------------- #

def test_scan_started_enables_run_control_and_arms_tiles():
    _app()
    panel = ScanViewerPanel()
    panel.on_scan_started()
    assert panel._run_active is True
    assert panel._btn_pause.isEnabled()
    assert panel._btn_abort.isEnabled()
    assert not panel._btn_open_analysis.isEnabled()
    assert panel._finished_banner.isHidden()
    assert panel._chip_run.text() == "Running"
    # Laws 4/8: only *elapsed* has something real to say the instant a run is
    # armed (the clock started). Progress/ETA/point stay honestly stale
    # (captioned) until a real callback lands. "0/0" painted crisp-fresh is a
    # claim the panel cannot back: a z-focus run that reported nothing yet
    # would show a live-ink 0-of-0 that is not a measurement.
    assert not panel._metric_elapsed.is_stale()
    assert panel._metric_progress.is_stale()
    assert "waiting for progress" in panel._metric_progress._caption.text()
    assert panel._metric_eta.is_stale()
    assert panel._metric_point.is_stale()


def test_first_progress_de_stales_the_progress_tile():
    """The other half of the contract above: the tile goes live only once a
    real ``on_progress`` has landed, and then it carries the real count."""
    _app()
    panel = ScanViewerPanel()
    panel.on_scan_started()
    assert panel._metric_progress.is_stale()

    panel.on_progress(1, 4)
    assert not panel._metric_progress.is_stale()
    assert panel._metric_progress.value() == "1/4"


def test_point_done_fills_map_and_updates_point_metric():
    _app()
    panel = ScanViewerPanel()
    panel.on_scan_started()
    panel.on_point_done(_result(0.0, 0.0, 1.0, charge=5.0))
    panel.on_point_done(_result(1.0, 0.0, 1.0, charge=7.0))
    assert panel._map_view.point_count() == 2
    assert "x=1.000" in panel._metric_point.value()
    assert "z=1.000" in panel._metric_point.value()


def test_point_done_before_scan_started_still_swaps_to_map():
    _app()
    panel = ScanViewerPanel()
    panel.on_point_done(_result(0.0, 0.0, charge=1.0))
    assert panel._map_view.is_showing_map()


def test_progress_updates_progress_and_eta_and_elapsed_tiles():
    _app()
    panel = ScanViewerPanel()
    panel.on_scan_started()
    panel.on_progress(1, 4)
    assert panel._metric_progress.value() == "1/4"
    # ETA/elapsed are time-based; only assert they are populated (not the
    # placeholder) and don't raise.
    assert panel._metric_elapsed.value() != "--"


def test_progress_before_any_elapsed_time_reports_eta_dashes():
    _app()
    panel = ScanViewerPanel()
    # No on_scan_started -> no _start_time -> ETA must degrade gracefully.
    panel.on_progress(1, 4)
    assert panel._metric_eta.value() == "--"


def test_scan_finished_disables_run_control_and_keeps_map():
    _app()
    panel = ScanViewerPanel()
    panel.on_scan_started()
    panel.on_point_done(_result(0.0, 0.0, charge=1.0))
    panel.on_scan_finished()
    assert panel._run_active is False
    assert not panel._btn_pause.isEnabled()
    assert not panel._btn_abort.isEnabled()
    assert panel._chip_run.text() == "Finished"
    # Map is NOT cleared / swapped back to the empty placeholder after
    # finish — retained (stale-captioned tiles) for the Analysis handoff.
    assert panel._map_view.is_showing_map()
    assert panel._map_view.point_count() == 1
    # Terminal state as design (§5): banner shown, tiles honestly final.
    assert not panel._finished_banner.isHidden()
    assert panel._chip_finished.text() == "Finished"
    assert panel._metric_progress.is_stale()


def test_abort_finish_shows_aborted_banner_variant():
    _app()
    panel = ScanViewerPanel()
    panel.on_scan_started()
    panel.on_point_done(_result(0.0, 0.0, charge=1.0))
    panel._btn_abort.click()
    panel.on_scan_finished()
    assert not panel._finished_banner.isHidden()
    assert panel._chip_finished.text() == "Aborted"
    assert panel._chip_run.text() == "Aborted"
    # Partial data stays on screen (fail-safe caption, not a wiped map).
    assert panel._map_view.point_count() == 1

    # The abort flag is per-run: the next run that finishes cleanly reads
    # Finished again.
    panel.on_scan_started()
    panel.on_scan_finished()
    assert panel._chip_finished.text() == "Finished"


def test_new_run_clears_previous_map():
    _app()
    panel = ScanViewerPanel()
    panel.on_scan_started()
    panel.on_point_done(_result(0.0, 0.0, charge=1.0))
    panel.on_scan_finished()
    assert panel._map_view.point_count() == 1

    panel.on_scan_started()
    assert panel._map_view.point_count() == 0


# --------------------------------------------------------------------------- #
# Run control ActionBar gating                                                #
# --------------------------------------------------------------------------- #

def test_pause_toggle_emits_signal_only_while_enabled():
    _app()
    panel = ScanViewerPanel()
    seen = []
    panel.pause_requested.connect(seen.append)

    # Disabled: toggling programmatically must not emit (mirrors the
    # on_scan_started/finished un-check guard).
    panel._btn_pause.setChecked(True)
    assert seen == []

    panel._btn_pause.setChecked(False)
    panel.on_scan_started()
    panel._btn_pause.setChecked(True)
    assert seen == [True]
    assert panel._btn_pause.text() == "Resume"

    panel._btn_pause.setChecked(False)
    assert seen == [True, False]


def test_abort_button_emits_abort_requested():
    _app()
    panel = ScanViewerPanel()
    panel.on_scan_started()
    seen = []
    panel.abort_requested.connect(lambda: seen.append(True))
    panel._btn_abort.click()
    assert len(seen) == 1
    assert panel._chip_run.text() == "Aborting"


def test_abort_disabled_when_idle_rule():
    _app()
    panel = ScanViewerPanel()
    assert not panel._btn_abort.isEnabled()
    panel.on_scan_started()
    panel.on_scan_finished()
    assert not panel._btn_abort.isEnabled()


def test_manual_pause_sets_warn_chip():
    _app()
    panel = ScanViewerPanel()
    panel.on_scan_started()
    panel.on_manual_pause("swap sample now")
    assert "swap sample now" in panel._chip_run.text()


def test_set_current_position_updates_point_tile():
    _app()
    panel = ScanViewerPanel()
    panel.set_current_position(1.5, -2.5, 0.75)
    assert "x=1.500" in panel._metric_point.value()
    assert "y=-2.500" in panel._metric_point.value()
    assert "z=0.750" in panel._metric_point.value()


# --------------------------------------------------------------------------- #
# Z-focus                                                                     #
# --------------------------------------------------------------------------- #

def test_z_focus_start_emits_config_and_resets_curve():
    _app()
    panel = ScanViewerPanel()
    panel.on_z_focus_pt(0.0, 0.1)   # stale data from a previous run
    seen = []
    panel.z_focus_requested.connect(seen.append)
    panel._btn_zf_start.click()
    assert len(seen) == 1
    assert isinstance(seen[0], ZFocusScanConfig)
    assert panel._zf_z_data == []
    assert panel._zf_a_data == []


def test_z_focus_point_accumulates_curve_data():
    _app()
    panel = ScanViewerPanel()
    panel.on_z_focus_pt(-1.0, 0.2)
    panel.on_z_focus_pt(0.0, 0.5)
    panel.on_z_focus_pt(1.0, 0.3)
    assert panel._zf_z_data == [-1.0, 0.0, 1.0]
    assert panel._zf_a_data == [0.2, 0.5, 0.3]


def test_z_focus_done_sets_marker_and_label():
    _app()
    panel = ScanViewerPanel()
    panel.on_z_focus_done(0.42)
    assert "0.420" in panel._lbl_best_z.text()
    assert panel._zf_marker.isVisible()
    assert panel._zf_marker.value() == pytest.approx(0.42)


def test_apply_best_z_disabled_until_z_focus_done():
    _app()
    panel = ScanViewerPanel()
    assert not panel._btn_apply_best_z.isEnabled()

    panel.on_z_focus_done(0.42)
    assert panel._btn_apply_best_z.isEnabled()


def test_apply_best_z_redisabled_on_new_z_focus_run():
    _app()
    panel = ScanViewerPanel()
    panel.on_z_focus_done(0.42)
    assert panel._btn_apply_best_z.isEnabled()

    # A fresh "Find Focus" run resets the stale result -- Apply must not
    # keep offering the previous run's best-Z.
    panel._btn_zf_start.click()
    assert not panel._btn_apply_best_z.isEnabled()
    assert panel._last_best_z is None


def test_apply_best_z_click_emits_last_value():
    _app()
    panel = ScanViewerPanel()
    panel.on_z_focus_done(1.234)
    seen = []
    panel.best_z_apply_requested.connect(seen.append)
    panel._btn_apply_best_z.click()
    assert seen == [pytest.approx(1.234)]


def test_apply_best_z_noop_without_result():
    _app()
    panel = ScanViewerPanel()
    seen = []
    panel.best_z_apply_requested.connect(seen.append)
    panel._on_apply_best_z_clicked()
    assert seen == []


def test_z_focus_mode_switch_toggles_edge_and_amp_frames():
    _app()
    panel = ScanViewerPanel()
    # isHidden() reflects the explicit setVisible() call regardless of
    # top-level show() state (this panel is never shown in headless tests);
    # isVisible() would be False for every child either way.
    # Default is edge_scan (index 0).
    assert not panel._zf_edge_frame.isHidden()
    assert panel._zf_amp_frame.isHidden()

    idx = panel._zf_mode.findData("amplitude")
    panel._zf_mode.setCurrentIndex(idx)
    assert panel._zf_edge_frame.isHidden()
    assert not panel._zf_amp_frame.isHidden()


def test_z_focus_card_collapsed_by_default_with_header_controls():
    """Design system §7: Z-focus collapsed by default — the body (form +
    curve) hidden, while the header chip and the "Find focus" verb stay
    reachable; expanding discloses the form."""
    _app()
    panel = ScanViewerPanel()
    card = panel._zf_card
    assert not card.is_expanded()
    body = card.body.parentWidget()
    assert body.isHidden()
    # Header summary chip + primary verb stay live while collapsed.
    assert not panel._btn_zf_start.isHidden()
    assert panel._btn_zf_start.isEnabled()
    assert panel._chip_best_z.text() == "No focus result"

    card.set_expanded(True)
    assert not body.isHidden()
    card.set_expanded(False)
    assert body.isHidden()


def test_z_focus_done_updates_header_chip():
    _app()
    panel = ScanViewerPanel()
    panel.on_z_focus_done(0.42)
    assert "0.420" in panel._chip_best_z.text()


# --------------------------------------------------------------------------- #
# Open in Analysis                                                            #
# --------------------------------------------------------------------------- #

def test_open_in_analysis_disabled_until_path_and_finished():
    _app()
    panel = ScanViewerPanel()
    panel.on_scan_started()
    panel.set_last_run_path("C:/data/run_00001/scan.h5")
    # Path known but run still active -> stays disabled.
    assert not panel._btn_open_analysis.isEnabled()

    panel.on_scan_finished()
    assert panel._btn_open_analysis.isEnabled()


def test_open_in_analysis_enables_immediately_if_path_set_after_finish():
    _app()
    panel = ScanViewerPanel()
    panel.on_scan_started()
    panel.on_scan_finished()
    assert not panel._btn_open_analysis.isEnabled()
    panel.set_last_run_path("C:/data/run_00002/scan.h5")
    assert panel._btn_open_analysis.isEnabled()


def test_open_in_analysis_click_emits_path():
    _app()
    panel = ScanViewerPanel()
    panel.on_scan_started()
    panel.on_scan_finished()
    panel.set_last_run_path("C:/data/run_00003/scan.h5")
    seen = []
    panel.open_in_analysis_requested.connect(seen.append)
    panel._btn_open_analysis.click()
    assert seen == ["C:/data/run_00003/scan.h5"]


def test_new_run_invalidates_previous_run_path():
    _app()
    panel = ScanViewerPanel()
    panel.on_scan_started()
    panel.on_scan_finished()
    panel.set_last_run_path("C:/data/run_00005/scan.h5")
    assert panel._btn_open_analysis.isEnabled()

    # A new run must never re-offer the previous run's file: if it ends
    # without publishing a fresh path (e.g. aborted before the writer
    # opened), Open in Analysis stays disabled.
    panel.on_scan_started()
    assert panel._last_run_path is None
    panel.on_scan_finished()
    assert not panel._btn_open_analysis.isEnabled()


def test_zf_spin_suffixes_match_units():
    _app()
    panel = ScanViewerPanel()
    assert panel._zf_settle.suffix() == " s"
    assert panel._zf_edge_step.suffix() == " mm"
    assert panel._zf_dz.suffix() == " mm"


def test_open_in_analysis_noop_without_path():
    _app()
    panel = ScanViewerPanel()
    seen = []
    panel.open_in_analysis_requested.connect(seen.append)
    panel._emit_open_in_analysis()
    assert seen == []


# --------------------------------------------------------------------------- #
# Full simulated run (integration-style, within this panel only)              #
# --------------------------------------------------------------------------- #

def test_full_simulated_run_sequence():
    _app()
    panel = ScanViewerPanel()

    panel.on_scan_started()
    total = 3
    for i, (x, y) in enumerate([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]):
        panel.on_point_done(_result(x, y, charge=float(i)))
        panel.on_progress(i + 1, total)
    panel.on_scan_finished()
    panel.set_last_run_path("C:/data/run_00004/scan.h5")

    assert panel._map_view.point_count() == 3
    assert panel._metric_progress.value() == "3/3"
    assert panel._chip_run.text() == "Finished"
    assert panel._btn_open_analysis.isEnabled()
    assert panel._map_view.is_showing_map()
    assert not panel._finished_banner.isHidden()


# --------------------------------------------------------------------------- #
# Theme switch                                                                #
# --------------------------------------------------------------------------- #

def test_theme_switch_survives_with_data():
    app = _app()
    apply_theme(app, "light")
    panel = ScanViewerPanel()
    panel.on_scan_started()
    panel.on_point_done(_result(0.0, 0.0, charge=1.0))
    panel.on_z_focus_pt(0.0, 0.2)

    apply_theme(app, "dark")
    panel.refresh_theme("dark")
    pm_dark = panel.grab()
    assert not pm_dark.isNull()

    apply_theme(app, "light")
    panel.refresh_theme("light")
    pm_light = panel.grab()
    assert not pm_light.isNull()

    # Accumulated state survives a theme switch untouched.
    assert panel._map_view.point_count() == 1
    assert panel._zf_z_data == [0.0]


def test_theme_switch_before_any_data_does_not_raise():
    app = _app()
    panel = ScanViewerPanel()
    apply_theme(app, "dark")
    panel.refresh_theme("dark")
    apply_theme(app, "light")
    panel.refresh_theme("light")


# --------------------------------------------------------------------------- #
# Rule 2 — Abort is the loudest control (dangerBtn / state="danger")          #
# --------------------------------------------------------------------------- #

def test_abort_uses_shared_danger_language():
    _app()
    panel = ScanViewerPanel()
    assert panel._btn_abort.objectName() == "dangerBtn"
    assert panel._btn_abort.property("state") == "danger"
    assert panel._btn_pause.property("state") == "secondary"


# --------------------------------------------------------------------------- #
# Rule 3 — no QGraphicsEffect on the hot-path map/z-focus plots               #
# --------------------------------------------------------------------------- #

def test_no_graphics_effect_on_map_or_zfocus_plot():
    _app()
    panel = ScanViewerPanel()
    assert panel._map_view.graphicsEffect() is None
    assert panel._zf_figure.graphicsEffect() is None
    assert panel._zf_figure.plot.graphicsEffect() is None


# --------------------------------------------------------------------------- #
# Zero inline hex (rule 1)                                                    #
# --------------------------------------------------------------------------- #

_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")


def test_scan_viewer_panel_source_has_zero_inline_hex():
    import gui.scan_viewer_panel as mod
    src = inspect.getsource(mod)
    matches = _HEX_RE.findall(src)
    assert matches == [], f"inline hex literals found in gui/scan_viewer_panel.py: {matches}"


def test_scan_viewer_panel_never_calls_set_graphics_effect():
    import gui.scan_viewer_panel as mod
    tree = ast.parse(inspect.getsource(mod))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "setGraphicsEffect"
    ]
    assert calls == []
