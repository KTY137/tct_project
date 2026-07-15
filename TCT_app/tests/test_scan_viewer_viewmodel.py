"""Direct unit tests for ``gui.scan_viewer_viewmodel.ScanViewerViewModel``
(U1.2, ``docs/design/u1_staging.md`` §4.3 — the C12-classified (a) tests
reclaimed out of ``tests/test_scan_viewer_panel.py``, host changed only; the
assertions survive).

Headless, no widget: a bare ``QObject`` subtype only needs a
``QCoreApplication`` (house pattern, mirrors ``tests/test_run_state_
viewmodel.py``). ``ScanViewerViewModel`` COMPOSES ``RunStateViewModel`` as
its ``run`` sub-view-model rather than re-deriving run state — run-state
assertions (progress/eta/elapsed/active) read through ``vm.run``; only
genuinely viewer-local state (staleness, current-position text, manual-pause
text, z-focus curve, best-Z chip text, open-in-analysis eligibility) is
asserted on ``vm`` directly.

Includes the standing-law pair (S2 Ruling Q3, replicated 1:1 from
``test_run_state_viewmodel.py``), asserted on BOTH the viewer VM and its
``run`` sub-VM per §4.3's exit criteria.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication

from controller.scan_controller import ScanPoint, ScanResult
from gui.run_state_viewmodel import RunStateViewModel
from gui.scan_viewer_viewmodel import ScanViewerViewModel
from tests._viewmodel_standing_law import (
    assert_no_command_surface,
    assert_owns_no_timer_or_thread,
)


def _app() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


def _result(x: float = 0.0, y: float = 0.0, z: float = 0.0, index: int = 0) -> ScanResult:
    """A minimal ScanResult carrying a ScanPoint (the only field the viewer
    VM / run sub-VM read)."""
    return ScanResult(
        point=ScanPoint(x_mm=x, y_mm=y, z_mm=z, index=index),
        timestamp=0.0,
        ref_amplitude_V=0.0,
        ref_charge_pC=0.0,
        dut_amplitude_V=0.0,
        dut_charge_pC=0.0,
        dut_charge_norm=0.0,
        baseline_rms_V=0.0,
    )


# --------------------------------------------------------------------------- #
# Construction (§7 exit-gate per-panel smoke: every new VM imports and        #
# instantiates headless)                                                      #
# --------------------------------------------------------------------------- #
def test_default_construction_no_parent_does_not_raise():
    _app()
    vm = ScanViewerViewModel(parent=None)
    assert isinstance(vm, ScanViewerViewModel)
    assert isinstance(vm.run, RunStateViewModel)


# --------------------------------------------------------------------------- #
# Reclaimed (1/15) — was test_scan_started_enables_run_control_and_arms_tiles #
# --------------------------------------------------------------------------- #
def test_scan_started_enables_run_control_and_arms_tiles():
    _app()
    vm = ScanViewerViewModel()
    vm.on_scan_started()
    assert vm.run.active is True
    # Law 4/8: only *elapsed* has something real to say the instant a run is
    # armed (the clock started). Progress/ETA/point stay honestly stale
    # (captioned) until a real callback lands.
    assert vm.run.elapsedText != "--"
    assert vm.progressStale is True
    assert vm.etaStale is True
    assert vm.pointStale is True


# --------------------------------------------------------------------------- #
# Reclaimed (2/15) — was test_first_progress_de_stales_the_progress_tile      #
# --------------------------------------------------------------------------- #
def test_first_progress_de_stales_the_progress_tile():
    """The other half of the contract above: the tile goes live only once a
    real ``on_progress`` has landed, and then it carries the real count."""
    _app()
    vm = ScanViewerViewModel()
    vm.on_scan_started()
    assert vm.progressStale is True

    vm.on_progress(1, 4)
    assert vm.progressStale is False
    assert vm.run.done == 1
    assert vm.run.total == 4


# --------------------------------------------------------------------------- #
# Reclaimed (3/15) — was test_point_done_fills_map_and_updates_point_metric   #
# --------------------------------------------------------------------------- #
def test_point_done_fills_map_and_updates_point_metric():
    """Map bookkeeping itself is ``ScanMapView``'s job (exercised in
    ``tests/test_scan_map_view.py``, U1.1) — the VM-portable half is the
    current-position tile text, last-write-wins on revisit."""
    _app()
    vm = ScanViewerViewModel()
    vm.on_scan_started()
    vm.on_point_done(_result(0.0, 0.0, 1.0))
    vm.on_point_done(_result(1.0, 0.0, 1.0))
    assert "x=1.000" in vm.currentPositionText
    assert "z=1.000" in vm.currentPositionText


# --------------------------------------------------------------------------- #
# Reclaimed (4/15) — was                                                      #
# test_progress_updates_progress_and_eta_and_elapsed_tiles                    #
# --------------------------------------------------------------------------- #
def test_progress_updates_progress_and_eta_and_elapsed_tiles():
    _app()
    vm = ScanViewerViewModel()
    vm.on_scan_started()
    vm.on_progress(1, 4)
    assert vm.run.done == 1
    assert vm.run.total == 4
    # ETA/elapsed are time-based; only assert they are populated (not the
    # placeholder) and don't raise — exact formatting is
    # test_run_state_viewmodel.py's job (the one derivation).
    assert vm.run.elapsedText != "--"


# --------------------------------------------------------------------------- #
# Reclaimed (5/15) — was                                                      #
# test_progress_before_any_elapsed_time_reports_eta_dashes                    #
# --------------------------------------------------------------------------- #
def test_progress_before_any_elapsed_time_reports_eta_dashes():
    _app()
    vm = ScanViewerViewModel()
    # No on_scan_started -> no run t0 -> ETA must degrade gracefully.
    vm.on_progress(1, 4)
    assert vm.run.etaText == "--"


# --------------------------------------------------------------------------- #
# Reclaimed (6/15) — was                                                      #
# test_scan_finished_disables_run_control_and_keeps_map                      #
# --------------------------------------------------------------------------- #
def test_scan_finished_disables_run_control_and_keeps_map():
    """Map retention itself is ``ScanMapView``'s job; the run-state half this
    VM owns is that the run is no longer active once finished."""
    _app()
    vm = ScanViewerViewModel()
    vm.on_scan_started()
    vm.on_point_done(_result(0.0, 0.0))
    vm.on_scan_finished()
    assert vm.run.active is False
    # Final position stays readable (the finished cockpit still shows it).
    assert vm.currentPositionText != "x=-- y=-- z=--"


# --------------------------------------------------------------------------- #
# Reclaimed (7/15) — was test_new_run_clears_previous_map                     #
# --------------------------------------------------------------------------- #
def test_new_run_clears_previous_map():
    """Map clearing itself is the panel's/``ScanMapView``'s job; the
    VM-portable analogue is that a new run resets the per-run derived state
    (position text, staleness, done/total) even though the previous run's
    data was still showing a moment ago."""
    _app()
    vm = ScanViewerViewModel()
    vm.on_scan_started()
    vm.on_point_done(_result(0.0, 0.0))
    vm.on_scan_finished()
    assert vm.currentPositionText != "x=-- y=-- z=--"

    vm.on_scan_started()
    assert vm.currentPositionText == "x=-- y=-- z=--"
    assert vm.run.done == 0
    assert vm.run.total == 0
    assert vm.pointStale is True


# --------------------------------------------------------------------------- #
# Reclaimed (8/15) — was test_manual_pause_sets_warn_chip                     #
# --------------------------------------------------------------------------- #
def test_manual_pause_sets_warn_chip():
    _app()
    vm = ScanViewerViewModel()
    vm.on_scan_started()
    vm.on_manual_pause("swap sample now")
    assert vm.manualPauseMessage == "swap sample now"


# --------------------------------------------------------------------------- #
# Reclaimed (9/15) — was test_set_current_position_updates_point_tile         #
# --------------------------------------------------------------------------- #
def test_set_current_position_updates_point_tile():
    _app()
    vm = ScanViewerViewModel()
    vm.set_current_position(1.5, -2.5, 0.75)
    assert "x=1.500" in vm.currentPositionText
    assert "y=-2.500" in vm.currentPositionText
    assert "z=0.750" in vm.currentPositionText


# --------------------------------------------------------------------------- #
# Reclaimed (10/15) — was test_z_focus_point_accumulates_curve_data           #
# --------------------------------------------------------------------------- #
def test_z_focus_point_accumulates_curve_data():
    _app()
    vm = ScanViewerViewModel()
    vm.on_z_focus_pt(-1.0, 0.2)
    vm.on_z_focus_pt(0.0, 0.5)
    vm.on_z_focus_pt(1.0, 0.3)
    assert vm.zFocusZ == [-1.0, 0.0, 1.0]
    assert vm.zFocusA == [0.2, 0.5, 0.3]


# --------------------------------------------------------------------------- #
# Reclaimed (11/15) — was test_z_focus_done_updates_header_chip               #
# --------------------------------------------------------------------------- #
def test_z_focus_done_updates_header_chip():
    _app()
    vm = ScanViewerViewModel()
    vm.on_z_focus_done(0.42, "edge_scan")
    assert "0.420" in vm.bestZSummaryText


# --------------------------------------------------------------------------- #
# Reclaimed (12/15) — was                                                     #
# test_open_in_analysis_disabled_until_path_and_finished                      #
# --------------------------------------------------------------------------- #
def test_open_in_analysis_disabled_until_path_and_finished():
    _app()
    vm = ScanViewerViewModel()
    vm.on_scan_started()
    vm.set_last_run_path("C:/data/run_00001/scan.h5")
    # Path known but run still active -> stays ineligible.
    assert vm.openInAnalysisEligible is False

    vm.on_scan_finished()
    assert vm.openInAnalysisEligible is True


# --------------------------------------------------------------------------- #
# Reclaimed (13/15) — was                                                     #
# test_open_in_analysis_enables_immediately_if_path_set_after_finish          #
# --------------------------------------------------------------------------- #
def test_open_in_analysis_enables_immediately_if_path_set_after_finish():
    _app()
    vm = ScanViewerViewModel()
    vm.on_scan_started()
    vm.on_scan_finished()
    assert vm.openInAnalysisEligible is False
    vm.set_last_run_path("C:/data/run_00002/scan.h5")
    assert vm.openInAnalysisEligible is True


# --------------------------------------------------------------------------- #
# Reclaimed (14/15) — was test_new_run_invalidates_previous_run_path          #
# --------------------------------------------------------------------------- #
def test_new_run_invalidates_previous_run_path():
    _app()
    vm = ScanViewerViewModel()
    vm.on_scan_started()
    vm.on_scan_finished()
    vm.set_last_run_path("C:/data/run_00005/scan.h5")
    assert vm.openInAnalysisEligible is True

    # A new run must never re-offer the previous run's file: if it ends
    # without publishing a fresh path (e.g. aborted before the writer
    # opened), eligibility stays False.
    vm.on_scan_started()
    assert vm.lastRunPath == ""
    vm.on_scan_finished()
    assert vm.openInAnalysisEligible is False


# --------------------------------------------------------------------------- #
# Reclaimed (15/15) — was test_full_simulated_run_sequence                    #
# --------------------------------------------------------------------------- #
def test_full_simulated_run_sequence():
    _app()
    vm = ScanViewerViewModel()

    vm.on_scan_started()
    total = 3
    for i, (x, y) in enumerate([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]):
        vm.on_point_done(_result(x, y))
        vm.on_progress(i + 1, total)
    vm.on_scan_finished()
    vm.set_last_run_path("C:/data/run_00004/scan.h5")

    assert vm.run.done == 3
    assert vm.run.total == 3
    assert vm.run.active is False
    assert vm.openInAnalysisEligible is True


# --------------------------------------------------------------------------- #
# Standing law (S2 Ruling Q3) — replicated on BOTH the viewer VM and its      #
# `run` sub-VM (§4.3 exit criterion)                                          #
# --------------------------------------------------------------------------- #
def test_read_only_no_command_surface():
    """Neither the viewer VM nor its composed ``run`` sub-VM may expose a
    run-control callable or hold a reference through which one could reach —
    the structural read/command boundary (hardware safety rule 2)."""
    _app()
    vm = ScanViewerViewModel()
    assert_no_command_surface(vm, vm.run)


def test_owns_no_timer_no_thread():
    _app()
    vm = ScanViewerViewModel()
    assert_owns_no_timer_or_thread(vm, vm.run)
