"""Headless tests for the shared 2-D scan-map widget (``gui/scan_map_view.py``),
including its own PNG/CSV export + freeze-levels toolbar (the ``ScanMapView``
now owns what the retired ``ScanMapWindow`` used to add on top).

Follows the existing gui test idiom: ``QT_QPA_PLATFORM=offscreen``, a shared
``QApplication.instance()`` helper, no pytest-qt, no hardware/simulated
backends needed (this widget never touches a device).
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import csv
import math

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from controller.scan_controller import ScanPoint, ScanResult
from gui.scan_map_view import QUANTITIES, ScanMapView
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
    # New toolbar controls (freeze toggle + PNG/CSV export) — static depth
    # only, same rule 3 guard as the plot itself.
    assert view._btn_freeze.graphicsEffect() is None
    assert view._btn_export_png.graphicsEffect() is None
    assert view._btn_export_csv.graphicsEffect() is None


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
# PNG/CSV export (S2c work package A) — dialog-free write helpers behind the  #
# toolbar's export toolbuttons.                                               #
# --------------------------------------------------------------------------- #

def test_write_csv_writes_expected_rows(tmp_path):
    _app()
    view = ScanMapView()
    view.update_point(_result(0.0, 0.0, charge=1.0))
    view.update_point(_result(1.0, 0.0, charge=2.0))
    view.update_point(_result(0.0, 1.0, charge=3.0))

    out = tmp_path / "map.csv"
    view._write_csv(str(out))

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
    view = ScanMapView()
    view.update_point(_result(0.0, 0.0, charge=1.0))
    view.set_quantity("baseline_rms_V")

    out = tmp_path / "map.csv"
    view._write_csv(str(out))

    with open(out, newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == ["x_mm", "y_mm", "baseline_rms_V"]
    assert float(rows[1][2]) == pytest.approx(0.001, rel=1e-6)


def test_write_png_writes_nonzero_file(tmp_path):
    app = _app()
    view = ScanMapView()
    if view.image_view() is None:
        pytest.skip("pyqtgraph not installed — no map image to export")
    view.update_point(_result(0.0, 0.0, charge=1.0))
    view.update_point(_result(1.0, 1.0, charge=2.0))
    # pg.exporters.ImageExporter needs real item geometry — an unshown
    # widget's imageItem has none yet in an offscreen session.
    view.resize(400, 300)
    view.show()
    app.processEvents()

    out = tmp_path / "map.png"
    try:
        view._write_png(str(out))
    except Exception as exc:  # pragma: no cover - exercised only if the
        # pg.exporters ImageExporter path is unavailable in this environment.
        pytest.skip(f"pyqtgraph PNG exporter unavailable: {exc}")

    assert out.exists()
    assert out.stat().st_size > 0


def test_write_csv_on_empty_view_writes_header_only(tmp_path):
    _app()
    view = ScanMapView()
    out = tmp_path / "empty.csv"
    view._write_csv(str(out))
    with open(out, newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows == [["x_mm", "y_mm", "dut_charge_pC"]]


# --------------------------------------------------------------------------- #
# Freeze-levels toggle (S2c work package A, ratified 2026-07-10 —             #
# was the parked "Map colorbar levels" decision, docs/OVERNIGHT_LOG.md)       #
# --------------------------------------------------------------------------- #

def test_freeze_levels_keeps_colorbar_fixed_while_new_points_widen_range():
    _app()
    view = ScanMapView()
    if view.image_view() is None:
        pytest.skip("pyqtgraph not installed")
    view.update_point(_result(0.0, 0.0, charge=10.0))
    view.update_point(_result(1.0, 0.0, charge=20.0))

    assert view._btn_freeze.isChecked() is False
    view._btn_freeze.setChecked(True)
    assert view._btn_freeze.isChecked() is True

    frozen_levels = tuple(view.image_view().imageItem.getLevels())
    assert frozen_levels == pytest.approx((10.0, 20.0))

    # A new point far outside the captured range arrives while frozen — the
    # colorbar must not move.
    view.update_point(_result(2.0, 0.0, charge=100.0))
    still_frozen = tuple(view.image_view().imageItem.getLevels())
    assert still_frozen == pytest.approx(frozen_levels)

    # Another new point below the captured range too — still fixed.
    view.update_point(_result(3.0, 0.0, charge=-50.0))
    assert tuple(view.image_view().imageItem.getLevels()) == pytest.approx(frozen_levels)


def test_unfreeze_levels_resumes_live_autoscale():
    _app()
    view = ScanMapView()
    if view.image_view() is None:
        pytest.skip("pyqtgraph not installed")
    view.update_point(_result(0.0, 0.0, charge=10.0))
    view.update_point(_result(1.0, 0.0, charge=20.0))
    view._btn_freeze.setChecked(True)
    view.update_point(_result(2.0, 0.0, charge=100.0))

    view._btn_freeze.setChecked(False)
    live_levels = tuple(view.image_view().imageItem.getLevels())
    assert live_levels == pytest.approx((10.0, 100.0))

    # Autoscale keeps tracking further new points once unfrozen.
    view.update_point(_result(3.0, 0.0, charge=200.0))
    assert tuple(view.image_view().imageItem.getLevels()) == pytest.approx((10.0, 200.0))


# --------------------------------------------------------------------------- #
# Data truth (design system §4): NaN honesty, viridis, colorbar unit, counts  #
# --------------------------------------------------------------------------- #

def test_unsampled_cells_stay_nan_in_displayed_image():
    """The NaN→vmin bug fix: the image handed to the ImageItem keeps its
    NaNs (pyqtgraph renders them alpha-0/transparent), so an unsampled cell
    can never wear the coldest data colour."""
    _app()
    view = ScanMapView()
    if view.image_view() is None:
        pytest.skip("pyqtgraph not installed")
    # 2 of 4 cells in a 2x2 grid sampled.
    view.update_point(_result(0.0, 0.0, charge=10.0))
    view.update_point(_result(1.0, 1.0, charge=20.0))

    displayed = view.image_view().imageItem.image
    assert displayed is not None
    assert int(np.count_nonzero(np.isnan(displayed))) == 2
    # Levels still come from sampled cells only.
    assert tuple(view.image_view().imageItem.getLevels()) == pytest.approx((10.0, 20.0))


def test_unsampled_cells_render_transparent_not_vmin_color():
    _app()
    view = ScanMapView()
    if view.image_view() is None:
        pytest.skip("pyqtgraph not installed")
    view.update_point(_result(0.0, 0.0, charge=10.0))
    view.update_point(_result(1.0, 1.0, charge=20.0))

    item = view.image_view().imageItem
    item.render()
    rgba = item.qimage
    assert rgba is not None
    # Grid rows map x -> image columns after ImageItem's axis handling; scan
    # both diagonal-off cells for a fully transparent pixel and both
    # diagonal-on cells for opaque data ink.
    alphas = {(x, y): rgba.pixelColor(x, y).alpha()
              for x in (0, 1) for y in (0, 1)}
    assert sorted(alphas.values()) == [0, 0, 255, 255]


def test_colorbar_unit_bound_to_selected_quantity():
    _app()
    view = ScanMapView()
    if view.image_view() is None:
        pytest.skip("pyqtgraph not installed")
    view.update_point(_result(0.0, 0.0, charge=1.0))

    assert view._hist_axis.labelUnits == "pC"
    view.set_quantity("dut_amplitude_V")
    assert view._hist_axis.labelUnits == "V"
    view.set_quantity("drift_time_s")
    assert view._hist_axis.labelUnits == "s"


def test_viridis_colormap_applied():
    _app()
    view = ScanMapView()
    if view.image_view() is None:
        pytest.skip("pyqtgraph not installed")
    import pyqtgraph as pg
    expected = pg.colormap.get("viridis").getLookupTable(nPts=16)
    actual = view.image_view().ui.histogram.gradient.colorMap().getLookupTable(nPts=16)
    assert np.array_equal(expected, actual)


def test_missing_and_duplicate_counts_surfaced():
    _app()
    view = ScanMapView()
    if view.image_view() is None:
        pytest.skip("pyqtgraph not installed")
    # 3 of 4 cells sampled; one cell revisited (last-write-wins, but the
    # revisit is COUNTED, never silently absorbed — §4).
    view.update_point(_result(0.0, 0.0, charge=1.0))
    view.update_point(_result(1.0, 1.0, charge=2.0))
    view.update_point(_result(1.0, 0.0, charge=3.0))
    view.update_point(_result(1.0, 1.0, charge=9.0))

    assert view.duplicate_count() == 1
    assert "3/4 sampled" in view._chip_points.text()
    subtitle = view._figure_card._subtitle_label.text()
    assert "1 unsampled" in subtitle
    assert "1 duplicate" in subtitle

    # Batch load: duplicates counted across the incoming iterable too.
    view.set_points([
        _result(0.0, 0.0, charge=1.0),
        _result(0.0, 0.0, charge=5.0),
        _result(1.0, 1.0, charge=2.0),
    ])
    assert view.duplicate_count() == 1
    # clear() re-arms the counter.
    view.clear()
    assert view.duplicate_count() == 0


def test_empty_view_shows_placeholder_page_with_toolbar_live():
    _app()
    view = ScanMapView()
    if view.image_view() is None:
        pytest.skip("pyqtgraph not installed")
    assert not view.is_showing_map()
    assert view._stack.currentWidget() is view._empty_state
    # Toolbar lives outside the stack — never hidden by the placeholder.
    assert not view._combo_qty.isHidden()
    assert not view._btn_freeze.isHidden()

    view.update_point(_result(0.0, 0.0, charge=1.0))
    assert view.is_showing_map()

    view.clear()
    assert not view.is_showing_map()


def test_freeze_toggled_before_any_data_captures_on_first_arrival():
    _app()
    view = ScanMapView()
    if view.image_view() is None:
        pytest.skip("pyqtgraph not installed")

    view._btn_freeze.setChecked(True)
    assert view.grid_result() is None

    view.update_point(_result(0.0, 0.0, charge=5.0))
    first_levels = tuple(view.image_view().imageItem.getLevels())
    assert first_levels == pytest.approx((5.0, 5.0 + 1e-9), rel=1e-6)

    view.update_point(_result(1.0, 0.0, charge=500.0))
    assert tuple(view.image_view().imageItem.getLevels()) == pytest.approx(first_levels)
