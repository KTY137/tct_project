"""Headless tests for the shared 2-D scan-map widget (``gui/scan_map_view.py``)
and its embedding in ``gui/scan_map_window.py``.

Follows the existing gui test idiom: ``QT_QPA_PLATFORM=offscreen``, a shared
``QApplication.instance()`` helper, no pytest-qt, no hardware/simulated
backends needed (this widget never touches a device).
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from controller.scan_controller import ScanPoint, ScanResult
from gui.scan_map_view import QUANTITIES, ScanMapView
from gui.scan_map_window import ScanMapWindow
from gui.style import apply_theme


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


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
# Construction                                                                #
# --------------------------------------------------------------------------- #

def test_construct_headless_no_hardware():
    _app()
    view = ScanMapView()
    assert view.point_count() == 0
    assert view.grid_result() is None


def test_quantities_list_matches_scan_result_fields():
    for qty in QUANTITIES:
        assert hasattr(ScanResult, "__dataclass_fields__")
        assert qty in ScanResult.__dataclass_fields__


# --------------------------------------------------------------------------- #
# update_point (live streaming)                                               #
# --------------------------------------------------------------------------- #

def test_update_point_streams_and_builds_grid():
    _app()
    view = ScanMapView()
    for (x, y) in [(0.0, 0.0), (0.0, 1.0), (1.0, 0.0), (1.0, 1.0)]:
        view.update_point(_result(x, y, charge=x + y + 1.0))

    assert view.point_count() == 4
    result = view.grid_result()
    assert result is not None
    assert result.grid.shape == (2, 2)
    assert result.n_missing == 0
    assert np.count_nonzero(np.isnan(result.grid)) == 0


def test_update_point_partial_scan_reports_nan_missing_cells():
    _app()
    view = ScanMapView()
    # 3x3 raster, only 2 of 9 points arrived — a live/mid-scan view.
    view.update_point(_result(0.0, 0.0, charge=1.0))
    view.update_point(_result(1.0, 1.0, charge=2.0))
    view.update_point(_result(2.0, 2.0, charge=3.0))

    result = view.grid_result()
    assert result.grid.shape == (3, 3)
    assert result.n_missing == 9 - 3
    assert np.count_nonzero(np.isnan(result.grid)) == result.n_missing


def test_update_point_last_write_wins_on_revisit():
    _app()
    view = ScanMapView()
    view.update_point(_result(0.0, 0.0, charge=1.0))
    view.update_point(_result(0.0, 0.0, charge=99.0))
    assert view.point_count() == 1
    result = view.grid_result()
    assert result.grid[0, 0] == pytest.approx(99.0)


# --------------------------------------------------------------------------- #
# Quantity switch                                                             #
# --------------------------------------------------------------------------- #

def test_quantity_switch_rerenders_without_restreaming():
    _app()
    view = ScanMapView()
    view.update_point(_result(0.0, 0.0, charge=5.0))
    view.update_point(_result(1.0, 0.0, charge=10.0))

    assert view.current_quantity() == "dut_charge_pC"
    result_charge = view.grid_result()
    assert set(result_charge.grid[~np.isnan(result_charge.grid)]) == {5.0, 10.0}

    view.set_quantity("baseline_rms_V")
    assert view.current_quantity() == "baseline_rms_V"
    # No new update_point() call — same accumulated points, new quantity.
    assert view.point_count() == 2
    result_rms = view.grid_result()
    assert np.allclose(result_rms.grid[~np.isnan(result_rms.grid)], 0.001)


# --------------------------------------------------------------------------- #
# set_points (batch load)                                                     #
# --------------------------------------------------------------------------- #

def test_set_points_batch_load_from_iterable_of_results():
    _app()
    view = ScanMapView()
    results = [_result(x, y, charge=x * 10 + y) for x in (0.0, 1.0) for y in (0.0, 1.0)]
    view.set_points(results)
    assert view.point_count() == 4
    assert view.grid_result().grid.shape == (2, 2)


def test_set_points_batch_load_from_mapping_replaces_state():
    _app()
    view = ScanMapView()
    view.update_point(_result(5.0, 5.0, charge=1.0))
    assert view.point_count() == 1

    mapping = {
        (0.0, 0.0): _result(0.0, 0.0, charge=1.0),
        (0.0, 1.0): _result(0.0, 1.0, charge=2.0),
    }
    view.set_points(mapping)
    assert view.point_count() == 2
    assert (5.0, 5.0) not in view.points()


def test_set_points_accepts_plain_dict_values():
    _app()
    view = ScanMapView()
    mapping = {
        (0.0, 0.0): {"dut_charge_pC": 1.0},
        (1.0, 0.0): {"dut_charge_pC": 2.0},
    }
    view.set_points(mapping)
    result = view.grid_result()
    assert result.grid.shape == (2, 1)
    assert set(result.grid.flatten()) == {1.0, 2.0}


# --------------------------------------------------------------------------- #
# Cursor readout                                                              #
# --------------------------------------------------------------------------- #

def test_cursor_readout_formats_with_value():
    _app()
    view = ScanMapView()
    view.update_point(_result(0.0, 0.0, charge=1.0))
    view.update_point(_result(1.0, 0.0, charge=2.0))
    view._update_cursor_readout(1.0, 0.0)
    text = view._lbl_cursor.text()
    assert "1.0000 mm" in text
    assert "0.0000 mm" in text
    assert "dut_charge_pC" in text
    assert "2" in text


def test_cursor_readout_default_before_any_motion():
    _app()
    view = ScanMapView()
    assert "--" in view._lbl_cursor.text()


def test_cursor_readout_out_of_bounds_shows_dashes():
    _app()
    view = ScanMapView()
    view.update_point(_result(0.0, 0.0, charge=1.0))
    view._update_cursor_readout(500.0, 500.0)
    assert "--" in view._lbl_cursor.text()


# --------------------------------------------------------------------------- #
# Theme switch                                                                #
# --------------------------------------------------------------------------- #

def test_theme_switch_survives_and_grid_intact():
    app = _app()
    apply_theme(app, "light")
    view = ScanMapView()
    view.update_point(_result(0.0, 0.0, charge=1.0))
    view.update_point(_result(1.0, 1.0, charge=2.0))

    apply_theme(app, "dark")
    view.refresh_theme("dark")
    pm_dark = view.grab()
    assert not pm_dark.isNull()

    apply_theme(app, "light")
    view.refresh_theme("light")
    pm_light = view.grab()
    assert not pm_light.isNull()

    # Accumulated state survives a theme switch untouched.
    assert view.point_count() == 2
    assert view.grid_result().grid.shape == (2, 2)


# --------------------------------------------------------------------------- #
# Rule 3 — no QGraphicsEffect on the hot-path plot                            #
# --------------------------------------------------------------------------- #

def test_no_graphics_effect_on_figure_card_or_plot():
    _app()
    view = ScanMapView()
    assert view.graphicsEffect() is None
    assert view._figure_card is not None
    assert view._figure_card.graphicsEffect() is None
    assert view._figure_card.plot.graphicsEffect() is None
    assert view.image_view().graphicsEffect() is None


# --------------------------------------------------------------------------- #
# NaN colorbar policy                                                         #
# --------------------------------------------------------------------------- #

def test_nan_value_does_not_skew_autoscale_levels():
    _app()
    view = ScanMapView()
    view.update_point(_result(0.0, 0.0, charge=10.0))
    view.update_point(_result(1.0, 0.0, charge=20.0))
    # A third point whose selected-quantity value is itself NaN (e.g. a
    # failed per-point analysis) must not corrupt the sampled-cell range.
    bad = _result(2.0, 0.0, charge=float("nan"))
    view.update_point(bad)

    grid = view.grid_result().grid
    finite = grid[~np.isnan(grid)]
    assert set(finite.tolist()) == {10.0, 20.0}


# --------------------------------------------------------------------------- #
# ScanMapWindow embedding                                                     #
# --------------------------------------------------------------------------- #

def test_scan_map_window_constructs_and_embeds_shared_view():
    _app()
    window = ScanMapWindow()
    assert window._map_view is not None
    assert isinstance(window._map_view, ScanMapView)


def test_scan_map_window_update_point_and_set_quantity_delegate_to_view():
    _app()
    window = ScanMapWindow()
    window.set_quantity("dut_amplitude_V")
    window.update_point(_result(0.0, 0.0, charge=1.0))
    window.update_point(_result(1.0, 0.0, charge=2.0))

    assert window._map_view.current_quantity() == "dut_amplitude_V"
    result = window._map_view.grid_result()
    assert np.allclose(result.grid.flatten(), 0.3)

    window.clear()
    assert window._map_view.point_count() == 0


def test_scan_map_window_theme_switch_survives():
    app = _app()
    apply_theme(app, "light")
    window = ScanMapWindow()
    window.update_point(_result(0.0, 0.0, charge=1.0))
    apply_theme(app, "dark")
    window.refresh_theme("dark")
    pm = window.grab()
    assert not pm.isNull()
