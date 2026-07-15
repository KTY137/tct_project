"""Direct unit tests for ``gui.scan_map_viewmodel.ScanMapViewModel`` — the
U1.1 extraction (``docs/design/u1_staging.md`` §4.2) of the scan-map's points
store, quantity selection, grid derivation, cursor readout, and CSV export out
of ``gui/scan_map_view.py``.

These 17 reclaim the (a)-class rows of the ``test_scan_map_view.py`` C12
table (``docs/CODEX_QUEUE.md`` §C12) — same assertions, VM host instead of
widget. The 15 (b)-class residue (pyqtgraph/toolbar/theme/timer behavior)
stays in ``test_scan_map_view.py``, byte-untouched.

Headless, no QML engine, no pyqtgraph — a bare ``QObject`` subtype only needs
a ``QCoreApplication`` (unlike ``ScanMapView``, this VM has no pyqtgraph
dependency at all).

Includes the standing-law pair every U1 VM suite carries (S2 Ruling Q3,
modeled 1:1 on ``tests/test_run_state_viewmodel.py``):
``test_read_only_no_command_surface`` and ``test_owns_no_timer_no_thread``.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import csv

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication

from controller.scan_controller import ScanPoint, ScanResult
from gui.scan_map_viewmodel import QUANTITIES, ScanMapViewModel
from tests._viewmodel_standing_law import (
    assert_no_command_surface,
    assert_owns_no_timer_or_thread,
)


def _app() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


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
# Schema contract                                                              #
# --------------------------------------------------------------------------- #

def test_quantities_list_matches_scan_result_fields():
    for qty in QUANTITIES:
        assert hasattr(ScanResult, "__dataclass_fields__")
        assert qty in ScanResult.__dataclass_fields__


# --------------------------------------------------------------------------- #
# update_point (live streaming)                                               #
# --------------------------------------------------------------------------- #

def test_update_point_streams_and_builds_grid():
    _app()
    vm = ScanMapViewModel()
    for (x, y) in [(0.0, 0.0), (0.0, 1.0), (1.0, 0.0), (1.0, 1.0)]:
        vm.update_point(_result(x, y, charge=x + y + 1.0))

    assert vm.point_count() == 4
    result = vm.grid_result()
    assert result is not None
    assert result.grid.shape == (2, 2)
    assert result.n_missing == 0
    assert np.count_nonzero(np.isnan(result.grid)) == 0


def test_update_point_partial_scan_reports_nan_missing_cells():
    _app()
    vm = ScanMapViewModel()
    # 3x3 raster, only 2 of 9 points arrived — a live/mid-scan view.
    vm.update_point(_result(0.0, 0.0, charge=1.0))
    vm.update_point(_result(1.0, 1.0, charge=2.0))
    vm.update_point(_result(2.0, 2.0, charge=3.0))

    result = vm.grid_result()
    assert result.grid.shape == (3, 3)
    assert result.n_missing == 9 - 3
    assert np.count_nonzero(np.isnan(result.grid)) == result.n_missing


def test_update_point_last_write_wins_on_revisit():
    _app()
    vm = ScanMapViewModel()
    vm.update_point(_result(0.0, 0.0, charge=1.0))
    vm.update_point(_result(0.0, 0.0, charge=99.0))
    assert vm.point_count() == 1
    result = vm.grid_result()
    assert result.grid[0, 0] == pytest.approx(99.0)


# --------------------------------------------------------------------------- #
# Quantity switch                                                             #
# --------------------------------------------------------------------------- #

def test_quantity_switch_rerenders_without_restreaming():
    _app()
    vm = ScanMapViewModel()
    vm.update_point(_result(0.0, 0.0, charge=5.0))
    vm.update_point(_result(1.0, 0.0, charge=10.0))

    assert vm.current_quantity() == "dut_charge_pC"
    result_charge = vm.grid_result()
    assert set(result_charge.grid[~np.isnan(result_charge.grid)]) == {5.0, 10.0}

    vm.set_quantity("baseline_rms_V")
    assert vm.current_quantity() == "baseline_rms_V"
    # No new update_point() call — same accumulated points, new quantity.
    assert vm.point_count() == 2
    result_rms = vm.grid_result()
    assert np.allclose(result_rms.grid[~np.isnan(result_rms.grid)], 0.001)


# --------------------------------------------------------------------------- #
# set_points (batch load)                                                     #
# --------------------------------------------------------------------------- #

def test_set_points_batch_load_from_iterable_of_results():
    _app()
    vm = ScanMapViewModel()
    results = [_result(x, y, charge=x * 10 + y) for x in (0.0, 1.0) for y in (0.0, 1.0)]
    vm.set_points(results)
    assert vm.point_count() == 4
    assert vm.grid_result().grid.shape == (2, 2)


def test_set_points_batch_load_from_mapping_replaces_state():
    _app()
    vm = ScanMapViewModel()
    vm.update_point(_result(5.0, 5.0, charge=1.0))
    assert vm.point_count() == 1

    mapping = {
        (0.0, 0.0): _result(0.0, 0.0, charge=1.0),
        (0.0, 1.0): _result(0.0, 1.0, charge=2.0),
    }
    vm.set_points(mapping)
    assert vm.point_count() == 2
    assert (5.0, 5.0) not in vm.points()


def test_set_points_mapping_branch_counts_rounding_collisions():
    """The mapping branch of set_points() must count a duplicate exactly
    like the iterable branch: two distinct raw (x, y) keys that collide
    only AFTER the 6-decimal rounding (storage-layer dedup) still increment
    the one honest _n_duplicates counter — never silently absorbed."""
    _app()
    vm = ScanMapViewModel()
    mapping = {
        (1e-7, 0.0): _result(1e-7, 0.0, charge=1.0),
        (4e-7, 0.0): _result(4e-7, 0.0, charge=2.0),   # rounds to the same (0.0, 0.0) cell
    }
    vm.set_points(mapping)

    assert vm.point_count() == 1
    assert vm.duplicate_count() == 1


def test_set_points_accepts_plain_dict_values():
    _app()
    vm = ScanMapViewModel()
    mapping = {
        (0.0, 0.0): {"dut_charge_pC": 1.0},
        (1.0, 0.0): {"dut_charge_pC": 2.0},
    }
    vm.set_points(mapping)
    result = vm.grid_result()
    assert result.grid.shape == (2, 1)
    assert set(result.grid.flatten()) == {1.0, 2.0}


# --------------------------------------------------------------------------- #
# Cursor readout                                                              #
# --------------------------------------------------------------------------- #

def test_cursor_readout_formats_with_value():
    _app()
    vm = ScanMapViewModel()
    vm.update_point(_result(0.0, 0.0, charge=1.0))
    vm.update_point(_result(1.0, 0.0, charge=2.0))
    text = vm.cursor_text(1.0, 0.0)
    assert "1.0000 mm" in text
    assert "0.0000 mm" in text
    assert "dut_charge_pC" in text
    assert "2" in text


def test_cursor_readout_default_before_any_motion():
    _app()
    vm = ScanMapViewModel()
    assert "--" in vm.cursor_text()


def test_cursor_readout_out_of_bounds_shows_dashes():
    _app()
    vm = ScanMapViewModel()
    vm.update_point(_result(0.0, 0.0, charge=1.0))
    assert "--" in vm.cursor_text(500.0, 500.0)


# --------------------------------------------------------------------------- #
# NaN colorbar policy                                                         #
# --------------------------------------------------------------------------- #

def test_nan_value_does_not_skew_autoscale_levels():
    _app()
    vm = ScanMapViewModel()
    vm.update_point(_result(0.0, 0.0, charge=10.0))
    vm.update_point(_result(1.0, 0.0, charge=20.0))
    # A third point whose selected-quantity value is itself NaN (e.g. a
    # failed per-point analysis) must not corrupt the sampled-cell range.
    bad = _result(2.0, 0.0, charge=float("nan"))
    vm.update_point(bad)

    grid = vm.grid_result().grid
    finite = grid[~np.isnan(grid)]
    assert set(finite.tolist()) == {10.0, 20.0}


# --------------------------------------------------------------------------- #
# CSV export (data contract)                                                  #
# --------------------------------------------------------------------------- #

def test_write_csv_writes_expected_rows(tmp_path):
    _app()
    vm = ScanMapViewModel()
    vm.update_point(_result(0.0, 0.0, charge=1.0))
    vm.update_point(_result(1.0, 0.0, charge=2.0))
    vm.update_point(_result(0.0, 1.0, charge=3.0))

    out = tmp_path / "map.csv"
    vm.write_csv(str(out))

    assert out.exists()
    with open(out, newline="") as fh:
        rows = list(csv.reader(fh))

    assert rows[0] == ["x_mm", "y_mm", "dut_charge_pC"]
    # Rows are written in sorted (x_mm, y_mm) order.
    assert rows[1] == ["0.000000", "0.000000", "1"]
    assert rows[2] == ["0.000000", "1.000000", "3"]
    assert rows[3] == ["1.000000", "0.000000", "2"]
    assert len(rows) == 4


def test_write_csv_uses_currently_selected_quantity(tmp_path):
    _app()
    vm = ScanMapViewModel()
    vm.update_point(_result(0.0, 0.0, charge=1.0))
    vm.set_quantity("baseline_rms_V")

    out = tmp_path / "map.csv"
    vm.write_csv(str(out))

    with open(out, newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == ["x_mm", "y_mm", "baseline_rms_V"]
    assert float(rows[1][2]) == pytest.approx(0.001, rel=1e-6)


def test_write_csv_on_empty_view_writes_header_only(tmp_path):
    _app()
    vm = ScanMapViewModel()
    out = tmp_path / "empty.csv"
    vm.write_csv(str(out))
    with open(out, newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows == [["x_mm", "y_mm", "dut_charge_pC"]]


# --------------------------------------------------------------------------- #
# Missing/duplicate counts (design system §4: surfaced, never silently        #
# absorbed) — the count MODEL; the widget's chip/subtitle text is (b),        #
# stays in test_scan_map_view.py.                                             #
# --------------------------------------------------------------------------- #

def test_missing_and_duplicate_counts_surfaced():
    _app()
    vm = ScanMapViewModel()
    # 3 of 4 cells sampled; one cell revisited (last-write-wins, but the
    # revisit is COUNTED, never silently absorbed — §4).
    vm.update_point(_result(0.0, 0.0, charge=1.0))
    vm.update_point(_result(1.0, 1.0, charge=2.0))
    vm.update_point(_result(1.0, 0.0, charge=3.0))
    vm.update_point(_result(1.0, 1.0, charge=9.0))

    result = vm.grid_result()
    n_total = int(result.grid.size)
    n_filled = n_total - result.n_missing
    assert (n_filled, n_total) == (3, 4)
    assert result.n_missing == 1
    assert vm.duplicate_count() == 1

    # Batch load: duplicates counted across the incoming iterable too.
    vm.set_points([
        _result(0.0, 0.0, charge=1.0),
        _result(0.0, 0.0, charge=5.0),
        _result(1.0, 1.0, charge=2.0),
    ])
    assert vm.duplicate_count() == 1
    # clear() re-arms the counter.
    vm.clear()
    assert vm.duplicate_count() == 0


# --------------------------------------------------------------------------- #
# Default construction (how the widget builds it; U1 exit-gate §7.4a)         #
# --------------------------------------------------------------------------- #

def test_default_construction_no_parent_does_not_raise():
    _app()
    vm = ScanMapViewModel(parent=None)
    assert isinstance(vm, ScanMapViewModel)


# --------------------------------------------------------------------------- #
# SAFETY-CRITICAL standing law (S2 Ruling Q3): no command surface, no upward   #
# reference, no owned timer/thread — replicated verbatim from               #
# tests/test_run_state_viewmodel.py for every U1 VM.                          #
# --------------------------------------------------------------------------- #

def test_read_only_no_command_surface():
    """The scan-map VM is fed plain data (points/quantity); it must expose NO
    run-control callable and hold NO reference through which a command could
    reach a controller/state machine/coordinator — the structural read/command
    boundary that encodes hardware safety rule 2."""
    _app()
    vm = ScanMapViewModel()
    assert_no_command_surface(
        vm,
        extra_names=("execute", "arm"),
        extra_attrs=("_scan",),
    )


def test_owns_no_timer_no_thread():
    _app()
    vm = ScanMapViewModel()
    assert_owns_no_timer_or_thread(vm)
